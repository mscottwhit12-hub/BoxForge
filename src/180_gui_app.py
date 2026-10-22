# =============================================================================
# Application
# =============================================================================
LIMITS_TEXT = """How the checks work

RED  - blocks export. The geometry is impossible or would be cut wrong: an inside dimension that is zero or negative, the smallest inside dimension under 4x the board thickness, flaps that cannot fit, or cut outlines that overlap in the flat layout.

AMBER - allowed, but flagged. The design should work but is outside what we can vouch for (smallest dimension under 8x the board thickness, flaps near their limits, extreme proportions, very tight lid clearance...). The notes are saved inside the exported file (SVG <desc>, DXF/EPS/G-code comments, PDF subject).

BLUE - information only.

What the limits are based on
- Structure of each style follows the FEFCO / ECMA families: 0201 slotted box, 0301 telescope. Internal-size conventions come from the FEFCO measuring recommendation (inside length/breadth = crease-to-crease minus one board; height minus two boards).
- Neither FEFCO nor the converter guides found publish numeric limits for board thickness against panel size, so the 4x / 8x rules, slot widths and clearances are engineering rules of thumb, not a standard.

Always cut a test piece on your actual board before a full run: crease behaviour varies with flute, grain direction and score depth."""


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        init_scale(self)                             # before any widget is made
        init_fonts(self)
        self.title("BoxForge  -  Box Dieline Studio")
        self.configure(bg=T["bg"])
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{min(S(1380), sw - 40)}x{min(S(840), sh - 90)}")
        self.minsize(min(S(1100), sw - 40), min(S(700), sh - 90))
        self.saved = {}
        self.gcode = dict(GCODE_DEFAULTS)
        self.drawing_opts = drawing_defaults()       # session only
        self.layout = dict(side_w=S(352), lower_h=None, split=0.5)     # divider positions, kept for the session
        self.look = dict(LOOK_DEFAULTS)     # line colours / weights: shared across boxes
        self.dash = dict(perf_dash=5.0, perf_tie=2.0, bend_r=0.25, bend_on=True, bend_len=True, bend_edges=False)   # dash length / bridge (mm), bend radius (x board), rounded folds on: per session
        self.error_hook = None                       # tests set this to catch errors instead of showing the dialog
        self.recent = []                             # project files opened or saved lately, newest first
        self._last_err = 0.0
        self._load_settings()
        try:
            self._icon = icon_photo(self, 64)
            self.iconphoto(True, self._icon)
        except tk.TclError:                          # a Tk without PhotoImage transparency: keep the default icon
            pass
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.host = tk.Frame(self, bg=T["bg"])
        self.host.pack(fill="both", expand=True)
        self.home = Home(self.host, self)
        self.editor = None
        mac = sys.platform == "darwin"
        for seq, redo in ((("<Command-z>", False), ("<Command-Z>", True)) if mac else ()) + (
                ("<Control-z>", False), ("<Control-Z>", True), ("<Control-y>", True), ("<Control-Y>", True)):
            cb = (lambda e, r=redo: self._undo_key(r))
            self.bind(seq, cb)
            self.bind_class("Entry", seq, cb)                  # Entry's built-in binding for these keys would win
        mod = "Command" if sys.platform == "darwin" else "Control"
        self.bind(f"<{mod}-s>", lambda e: self.save_project())
        self.bind(f"<{mod}-S>", lambda e: self.save_project(True))
        self.bind(f"<{mod}-o>", lambda e: self.open_project())
        self._mac_menu()
        self.show_home()

    def _mac_menu(self, force=False):
        """macOS: the menu bar at the top of the screen (About under the BoxForge menu, File with Open / Save, Quit).
        Other systems keep the menu-free window."""
        if sys.platform != "darwin" and not force:
            return None
        bar = tk.Menu(self)
        appm = tk.Menu(bar, name="apple", tearoff=0)
        appm.add_command(label="About BoxForge", command=self.show_about)
        bar.add_cascade(menu=appm)
        filem = tk.Menu(bar, name="file", tearoff=0)
        filem.add_command(label="Open Project…", accelerator="Cmd+O", command=self.open_project)
        filem.add_command(label="Save", accelerator="Cmd+S", command=self.save_project)
        filem.add_command(label="Save As…", accelerator="Shift+Cmd+S", command=lambda: self.save_project(True))
        filem.add_separator()
        filem.add_command(label="Back to All Boxes", command=self.show_home)
        bar.add_cascade(label="File", menu=filem)
        self.config(menu=bar)
        if sys.platform == "darwin":
            self.createcommand("tk::mac::ShowAbout", self.show_about)
            self.createcommand("tk::mac::Quit", self.close)
        return bar

    # ---------------------------------------------------------------- projects ----
    def _remember(self, path):
        path = os.path.abspath(path)
        self.recent = [path] + [p for p in self.recent if p != path]
        del self.recent[RECENT_MAX:]
        self.home.refresh_recent()

    def _set_title(self):
        ed = self.editor
        nm = os.path.splitext(os.path.basename(ed.project_path))[0] if ed and ed.project_path else ""
        if nm and self.project_dirty():
            nm += " *"
        self.title(f"{nm}  -  BoxForge" if nm else "BoxForge  -  Box Dieline Studio")

    def project_dirty(self):
        """True when the open box came from / went to a project file and has been changed since."""
        ed = self.editor
        return bool(ed and ed.project_path and getattr(ed, "saved_state", None) is not None
                    and ed._state() != ed.saved_state)

    def confirm_leave(self):
        """Before the open project is closed or replaced: offer to save its unsaved changes. False = stay."""
        if not self.project_dirty():
            return True
        nm = os.path.basename(self.editor.project_path)
        ans = messagebox.askyesnocancel("Unsaved changes", f"Save the changes to {nm} before leaving it?", parent=self)
        if ans is None:
            return False
        return self.save_project() if ans else True

    def save_project(self, save_as=False):
        """Save the open box as a project file (asks for a name the first time, or always with `save_as`)."""
        ed = self.editor
        if ed is None:
            return False
        path = ed.project_path
        if save_as or not path:
            path = filedialog.asksaveasfilename(
                parent=self, title="Save project", defaultextension=PROJECT_EXT,
                initialdir=os.path.dirname(path) if path else None,
                initialfile=os.path.basename(path) if path else f"{ed.style.id}-box{PROJECT_EXT}",
                filetypes=[("BoxForge project", "*" + PROJECT_EXT), ("All files", "*.*")])
            if not path:
                return False
        try:
            write_project(path, ed.style.id, ed._state())
        except ValueError as exc:
            ed.toast.config(text=str(exc), fg=T["err"])
            return False
        ed.project_path = path
        ed.saved_state = ed._state()
        self._remember(path)
        self._set_title()
        ed.toast.config(text=f"Saved {os.path.basename(path)}.", fg=T["good"])
        return True

    def open_project(self, path=None):
        """Open a project file (asks which one when no path is given). Returns True when it opened."""
        if not path:
            path = filedialog.askopenfilename(parent=self, title="Open project",
                                              filetypes=[("BoxForge project", "*" + PROJECT_EXT), ("All files", "*.*")])
            if not path:
                return False
        try:
            sid, st = read_project(path)
        except ValueError as exc:
            self.recent = [p for p in self.recent if p != os.path.abspath(path)] if "Could not read" in str(exc) else self.recent
            self.home.refresh_recent()
            messagebox.showerror("Open project", f"{os.path.basename(path)}\n\n{exc}", parent=self)
            return False
        need = [k for k in ("L", "W", "H", "t") if k not in st["vars"]]
        if need:
            messagebox.showerror("Open project", f"{os.path.basename(path)}\n\nThe project has no value for "
                                 f"{', '.join(need)}, so it cannot be opened.", parent=self)
            return False
        if self.editor is not None and not self.confirm_leave():
            return False
        self.saved[sid] = {}                                  # start from the style's defaults, not the last session's
        self.open_style(STYLE_BY_ID[sid])
        ed = self.editor
        full = ed._state()
        full["vars"] = {k: ("" if k not in ("L", "W", "H", "t") else v) for k, v in full["vars"].items()}   # blank = automatic
        full["units"], full["mode"], full["flute"], full["folds"], full["perf"] = "mm", "inner", "off", True, False
        full["feats"] = []
        for k in ("units", "mode", "flute", "folds", "perf", "feats"):
            if k in st:
                full[k] = st[k]
        def compat(old, new):                                  # same kind of value as the editor's own
            if isinstance(old, bool) or isinstance(new, bool):
                return isinstance(old, bool) and isinstance(new, bool)
            if isinstance(old, str):
                return isinstance(new, str)
            return isinstance(new, (int, float))
        for k in ("vars", "flags", "dash", "look"):
            full[k] = {a: (st[k][a] if a in st[k] and compat(v, st[k][a]) else v) for a, v in full[k].items()}
        full["sel"] = None
        ed._apply_state(full)
        ed._undo.clear()
        ed._redo.clear()
        ed.project_path = os.path.abspath(path)
        ed.saved_state = ed._state()
        self._remember(path)
        self._set_title()
        ed.toast.config(text=f"Opened {os.path.basename(path)}.", fg=T["good"])
        return True

    # ---------------------------------------------------------------- settings ----
    def _load_settings(self):
        data = load_settings()
        self.look = _merge_known(self.look, data.get("look"))
        if self.look["cut_weight"] <= 0 or self.look["fold_weight"] <= 0 or self.look["engrave_weight"] <= 0:
            self.look = dict(LOOK_DEFAULTS)
        names = {n for n, _, _ in LINE_COLORS}
        for k in ("cut_color", "fold_color", "engrave_color"):
            if self.look[k] not in names:
                self.look[k] = LOOK_DEFAULTS[k]
        self.gcode = _merge_known(self.gcode, data.get("gcode"))
        self.dash = _merge_known(self.dash, data.get("dash"))
        for k in ("perf_dash", "perf_tie", "bend_r"):
            if self.dash[k] < 0:
                self.dash[k] = {"perf_dash": 5.0, "perf_tie": 2.0, "bend_r": 0.25}[k]
        self.drawing_opts = _merge_known(self.drawing_opts, data.get("drawing"))
        rc = data.get("recent")
        if isinstance(rc, list):
            self.recent = [x for x in rc if isinstance(x, str) and len(x) < 600][:RECENT_MAX]
        sv = data.get("saved")
        if isinstance(sv, dict):
            for sid, snap in sv.items():
                if sid in STYLE_BY_ID:
                    self.saved[sid] = clean_snapshot(snap)

    def save_settings(self):
        if self.editor is not None:
            self.saved[self.editor.style.id] = self.editor.snapshot()
        return save_settings(dict(version=1, look=self.look, gcode=self.gcode, dash=self.dash,
                                  drawing=self.drawing_opts, saved=self.saved, recent=self.recent))

    def reset_settings(self):
        """Forget everything that was saved and go back to the factory values (the open editor is closed)."""
        try:
            os.remove(settings_path())
        except OSError:
            pass
        self.saved = {}
        self.recent = []
        self.look = dict(LOOK_DEFAULTS)
        self.gcode = dict(GCODE_DEFAULTS)
        self.drawing_opts = drawing_defaults()
        self.dash = dict(perf_dash=5.0, perf_tie=2.0, bend_r=0.25, bend_on=True, bend_len=True, bend_edges=False)
        if self.editor is not None:
            self.editor.shutdown()
            self.editor.destroy()
            self.editor = None
            self.show_home()

    def close(self):
        if not self.confirm_leave():
            return
        try:
            self.save_settings()
        finally:
            for stop in (self.home.stop, getattr(self.editor, "shutdown", lambda: None)):   # no timer left running
                try:
                    stop()
                except Exception:                                # noqa: BLE001
                    pass
            self.destroy()

    # ------------------------------------------------------------------ errors ----
    def report_callback_exception(self, exc, val, tb):
        """Anything that goes wrong inside a button or a timer: write it to the log and tell the person, instead of
        failing silently (a packaged program has no console to print to)."""
        text = "".join(traceback.format_exception(exc, val, tb))
        log_error(text)
        try:
            print(text, file=sys.stderr)
        except Exception:                                       # noqa: BLE001
            pass
        if self.error_hook is not None:
            self.error_hook(text)
            return
        now = time.monotonic()
        if now - self._last_err < 3.0:                           # one failing timer must not bury the screen in dialogs
            return
        self._last_err = now
        try:
            messagebox.showerror(
                "BoxForge - something went wrong",
                f"{exc.__name__}: {val}\n\nNothing was lost that was already saved to a file. The details are in:\n"
                f"{log_path()}\n\nIf it keeps happening, send that file along with what you were doing.", parent=self)
        except Exception:                                       # noqa: BLE001
            pass

    def show_about(self):
        win = tk.Toplevel(self, bg=T["panel"])
        win.title("About BoxForge")
        win.resizable(False, False)
        win.transient(self)
        try:
            win.iconphoto(False, self._icon)
        except (AttributeError, tk.TclError):
            pass
        box = tk.Frame(win, bg=T["panel"])
        box.pack(padx=34, pady=26)
        logo = tk.Label(box, image=self._icon, bg=T["panel"]) if getattr(self, "_icon", None) else None
        if logo is not None:
            logo.pack()
        tk.Label(box, text="BoxForge", font=F(18, "bold"), fg=T["text"], bg=T["panel"]).pack(pady=(6, 0))
        tk.Label(box, text=f"Version {__version__}", font=F(10), fg=T["muted"], bg=T["panel"]).pack()
        tk.Label(box, text="Box dieline studio for laser and die cutting", font=F(10), fg=T["text"],
                 bg=T["panel"]).pack(pady=(10, 0))
        tk.Label(box, text=f"Python {sys.version.split()[0]}  ·  Tk {tk.TkVersion}\nSettings and error log: {user_dir()}",
                 font=F(8), fg=T["dim"], bg=T["panel"], justify="center", wraplength=360).pack(pady=(12, 14))
        row = tk.Frame(box, bg=T["panel"])
        row.pack()
        Btn(row, "Limits & sources", lambda: (win.destroy(), self.show_limits()), "ghost", size=9, padx=12,
            pady=6).pack(side="left", padx=4)

        def reset():
            if messagebox.askyesno("Reset saved settings", "Forget the saved sizes, line colours and other options and "
                                   "go back to the factory values?", parent=win):
                win.destroy()
                self.reset_settings()
        Btn(row, "Reset saved settings", reset, "ghost", size=9, padx=12, pady=6).pack(side="left", padx=4)
        Btn(row, "Close", win.destroy, "primary", size=9, padx=16, pady=6).pack(side="left", padx=4)
        win.bind("<Escape>", lambda e: win.destroy())

    def _undo_key(self, redo):
        if self.editor is not None:
            return self.editor.redo() if redo else self.editor.undo()
        return None

    def show_home(self):
        if self.editor and not self.confirm_leave():
            return
        if self.editor:
            self.saved[self.editor.style.id] = self.editor.snapshot()
            self.editor.shutdown()
            self.editor.destroy()
            self.editor = None
        self.title("BoxForge  -  Box Dieline Studio")
        self.home.refresh_recent()
        self.home.pack(fill="both", expand=True)
        self.home.start()

    def open_style(self, style):
        if self.editor is not None:                  # only one box is open at a time
            self.show_home()
        self.home.stop()
        self.home.pack_forget()
        self.editor = Editor(self.host, self, style, self.saved.get(style.id))
        self.editor.pack(fill="both", expand=True)
        self._set_title()

    def show_limits(self):
        win = tk.Toplevel(self, bg=T["panel"])
        win.title("Limits & sources")
        win.geometry(f"{S(720)}x{S(700)}")
        txt = tk.Text(win, wrap="word", bg=T["panel"], fg=T["text"], font=F(10), relief="flat", padx=22, pady=18,
                      insertbackground=T["text"], spacing3=6)
        txt.insert("1.0", LIMITS_TEXT)
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True)


def run_gui():
    if not HAVE_TK:
        print("The window needs Python's tkinter, which isn't installed.\n"
              "  Windows/macOS: reinstall Python from python.org (tick 'tcl/tk').\n"
              "  Debian/Ubuntu: sudo apt install python3-tk\n"
              "The command-line mode still works:  python dieline_generator.py --help")
        return 1
    enable_dpi_awareness()
    try:
        app = App()
    except Exception:                                    # noqa: BLE001 - the window itself could not start
        text = traceback.format_exc()
        log_error(text)
        try:
            print(text, file=sys.stderr)
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror("BoxForge could not start", f"The window could not be opened.\n\nDetails were saved to:\n{log_path()}")
            r.destroy()
        except Exception:                                # noqa: BLE001
            pass
        return 1
    app.mainloop()
    return 0


