# =============================================================================
# Editor
# =============================================================================
class Editor(tk.Frame):
    def __init__(self, master, app, style, saved=None):
        super().__init__(master, bg=T["bg"])
        self.app, self.style = app, style
        self.res = None
        self._job = None
        self._loading = True
        self.user_view = False
        self.view = dict(s=1.0, ox=0.0, oy=0.0)
        self._drag = None
        self._anim = None
        self._spin = None

        spec0 = default_spec(style)
        sv = saved or {}
        self.units = tk.StringVar(value=sv.get("units", "mm"))
        self.mode = tk.StringVar(value=sv.get("mode", "inner"))
        self.folds = tk.BooleanVar(value=sv.get("folds", True))
        self.perf = tk.BooleanVar(value=sv.get("perf", False))
        self.flute = tk.StringVar(value=sv.get("flute", "off"))      # corrugated flute direction: off / v / h
        self.dvars = {k: (tk.BooleanVar if k in ("bend_on", "bend_len", "bend_edges") else tk.DoubleVar)(value=app.dash[k])
                      for k in ("perf_dash", "perf_tie", "bend_r", "bend_on", "bend_len", "bend_edges")}
        self.project_path = None                              # the project file this box was opened from / saved to
        self.flags = {k: tk.BooleanVar(value=sv.get("flag_" + k, d)) for k, _, d in style.toggles}
        self.vars = {}
        for k in ("L", "W", "H", "t"):
            self.vars[k] = tk.StringVar(value=sv.get(k, fmt(getattr(spec0, k), 3)))
        if style.square:                                      # a square-only style: Width follows Length
            self.vars["W"].set(self.vars["L"].get())
            self.vars["L"].trace_add("write", lambda *a: self.vars["W"].set(self.vars["L"].get()))
        for k, _ in style.options:
            self.vars[k] = tk.StringVar(value=sv.get(k, ""))
        self.vars["kerf"] = tk.StringVar(value=sv.get("kerf", ""))
        self.has_drawing = True                              # engineering drawing sheets: every style
        self.has_solid = True                                # board-thickness 3-D preview: every style
        if self.has_drawing:
            for k in TOL_LABELS:
                self.vars["tol_" + k] = tk.StringVar(value=sv.get("tol_" + k, ""))
        self.tol_open = tk.BooleanVar(value=False)
        self.vars["sheetw"] = tk.StringVar(value=sv.get("sheetw", ""))
        self.vars["sheeth"] = tk.StringVar(value=sv.get("sheeth", ""))
        lk = app.look                      # colours / weights are shared by every box in this session
        self.lvars = {k: tk.StringVar(value=lk[k] if k.endswith("color") else fmt(lk[k], 4))
                      for k in ("cut_color", "fold_color", "cut_weight", "fold_weight", "engrave_color", "engrave_weight")}
        self.features, self.sel = [], None            # windows / zones live for this editor session only
        self.fvars = {k: tk.StringVar() for k in ("cx", "cy", "w", "h", "r")}
        self._fplain = {}                                # last plain number in each window / zone box (for typed maths)

        def _keep(k):
            def f(*a):
                if is_plain_number(self.fvars[k].get()):
                    try:
                        self._fplain[k] = parse_num(self.fvars[k].get())
                    except ValueError:
                        pass
            return f
        for k, v in self.fvars.items():
            v.trace_add("write", _keep(k))
        self.f_outline, self.f_rot = tk.BooleanVar(value=False), tk.BooleanVar(value=False)
        self._floading, self._fdrag = False, None
        self.view_mode = tk.StringVar(value=sv.get("view", "split"))
        self.amount = tk.DoubleVar(value=100.0)
        for k, v in self.flags.items():                       # a switch that adds something inside the box starts with the box open
            if v.get() and style.toggle_view(k) is not None:
                self.amount.set(style.toggle_view(k) * 100.0)
        self.ents, self.auto_lbl = {}, {}
        self._last_units = self.units.get()

        self._build_top()
        body = self.body = make_paned(self, "horizontal")          # sidebar | views, divider draggable
        body.pack(fill="both", expand=True)
        self._build_sidebar(body)
        self._build_main(body)
        self._sash_drag = False
        for w_ in (self.body, self.vp, self.stage):
            w_.bind("<ButtonPress-1>", self._sash_press, add="+")
            w_.bind("<ButtonRelease-1>", self._sash_release, add="+")
        self.stage.bind("<Configure>", lambda e: self._apply_split(), add="+")
        self.side.bind("<Configure>", lambda e: self._fit_wraps(), add="+")
        self.after_idle(self._init_sashes)

        for v in list(self.vars.values()) + [self.mode, self.folds, self.perf, self.flute] + list(self.dvars.values()) + list(self.flags.values()) + list(self.lvars.values()):
            v.trace_add("write", lambda *a: self.schedule())
        for v in list(self.fvars.values()) + [self.f_outline, self.f_rot]:
            v.trace_add("write", lambda *a: self._fvar_changed())
        self.units.trace_add("write", self._on_units)
        self.view_mode.trace_add("write", lambda *a: self._layout_views())
        self._undo, self._redo, self._base, self._last_change, self._restoring = [], [], None, 0.0, False
        self._loading = False
        self._layout_views()
        self.after(60, self.refresh)

    # ---------------------------------------------------------------- build ----
    def _build_top(self):
        top = tk.Frame(self, bg=T["panel"], height=54)
        top.pack(fill="x")
        top.pack_propagate(False)
        Btn(top, "←  All boxes", self.app.show_home, kind="flat", padx=16, pady=14).pack(side="left", padx=(6, 6))
        tk.Frame(top, bg=T["border"], width=1).pack(side="left", fill="y", pady=12)
        tk.Label(top, text=self.style.name, font=F(13, "bold"), fg=T["text"], bg=T["panel"]).pack(side="left", padx=(16, 10))
        if self.style.code:
            chip(top, self.style.code, T["muted"], T["panel"]).pack(side="left", padx=(0, 6))
        txt, col = STATUS_CHIP[self.style.status]
        chip(top, txt, T[col], T["panel"]).pack(side="left")
        right = tk.Frame(top, bg=T["panel"])
        right.pack(side="right", padx=14)
        Btn(right, "Save", self.app.save_project, "ghost", size=9, padx=14, pady=6).pack(side="right", padx=(10, 0), pady=11)
        Seg(right, [("dieline", "Dieline"), ("split", "Split"), ("fold3d", "3-D fold")], self.view_mode).pack(
            side="right", pady=12)

    def _section(self, parent, text):
        tk.Label(parent, text=text, font=F(8, "bold"), fg=T["dim"], bg=T["panel"], anchor="w").pack(
            fill="x", padx=18, pady=(16, 6))

    def _calc_bind(self, entry, var, unit_of, toast=True, cur_fn=None):
        """Typed maths in a number box: evaluated on Enter or when the box loses focus (never while typing).
        `unit_of()` gives 'mm' / 'in' for length boxes or None for unitless ones."""
        last = {"v": None}

        def plain_now(*a):
            tx = var.get()
            if is_plain_number(tx):
                try:
                    last["v"] = parse_num(tx)
                except ValueError:
                    pass
        if cur_fn is None:                                   # remember the last plain value typed in this box
            plain_now()
            var.trace_add("write", plain_now)

        def commit(e=None):
            tx = var.get()
            if not tx.strip() or is_plain_number(tx):
                return
            try:
                r = calc_eval(tx, cur_fn() if cur_fn else last["v"], unit_of())
            except ValueError as exc:
                self.toast.config(text=f"Can't work that out: {exc}.", fg=T["err"])
                return
            var.set(fmt(r, 4 if self.units.get() == "in" else 3))
            self.toast.config(text=f"{tx.strip()}  =  {var.get()}", fg=T["muted"])
        entry.bind("<Return>", commit, add="+")
        entry.bind("<KP_Enter>", commit, add="+")
        entry.bind("<FocusOut>", commit, add="+")

    def _unit_for(self, key):
        return lambda: "mm" if key.startswith("tol_") else self.units.get()

    def _field(self, parent, key, label, unit=True):
        row = tk.Frame(parent, bg=T["panel"])
        row.pack(fill="x", padx=18, pady=3)
        row.grid_columnconfigure(0, weight=1)                        # a long label wraps; the entry keeps its size and column
        tk.Label(row, text=label, font=F(9), fg=T["text"], bg=T["panel"], anchor="w", justify="left",
                 wraplength=150).grid(row=0, column=0, sticky="w")
        right = tk.Frame(row, bg=T["panel"])
        right.grid(row=0, column=1, sticky="e")
        lbl = tk.Label(right, text="", font=F(8), fg=T["dim"], bg=T["panel"], width=9, anchor="e")
        lbl.pack(side="left", padx=(0, 6))
        e = tk.Entry(right, textvariable=self.vars[key], width=8, font=F(10), bg=T["panel2"], fg=T["text"],
                     insertbackground=T["text"], relief="flat", justify="right", highlightthickness=1,
                     highlightbackground=T["border"], highlightcolor=T["accent"])
        e.pack(side="left", ipady=4)
        self._calc_bind(e, self.vars[key], self._unit_for(key))
        self.ents[key], self.auto_lbl[key] = e, lbl

    def _lfield(self, parent, key, label, unit):
        row = tk.Frame(parent, bg=T["panel"])
        row.pack(fill="x", padx=18, pady=3)
        tk.Label(row, text=label, font=F(9), fg=T["text"], bg=T["panel"], anchor="w").pack(side="left")
        right = tk.Frame(row, bg=T["panel"])
        right.pack(side="right")
        tk.Label(right, text=unit, font=F(8), fg=T["dim"], bg=T["panel"], width=9, anchor="e").pack(
            side="left", padx=(0, 6))
        e = tk.Entry(right, textvariable=self.lvars[key], width=8, font=F(10), bg=T["panel2"], fg=T["text"],
                     insertbackground=T["text"], relief="flat", justify="right", highlightthickness=1,
                     highlightbackground=T["border"], highlightcolor=T["accent"])
        e.pack(side="left", ipady=4)
        if not key.endswith("color"):
            self._calc_bind(e, self.lvars[key], lambda: None)
        self.ents[key] = e

    def _color_row(self, parent, key, label):
        row = tk.Frame(parent, bg=T["panel"])
        row.pack(fill="x", padx=18, pady=(6, 2))
        tk.Label(row, text=label, font=F(9), fg=T["text"], bg=T["panel"], anchor="w").pack(side="left")
        SwatchPicker(row, self.lvars[key], T["panel"]).pack(side="right")
        tk.Label(row, textvariable=self.lvars[key], font=F(8), fg=T["dim"], bg=T["panel"], anchor="e").pack(
            side="right", padx=(0, 6))

    def _build_sidebar(self, parent):
        side = self.side = tk.Frame(parent, bg=T["panel"], width=1)
        parent.add(side, minsize=S(290), width=self.app.layout["side_w"], stretch="never")
        side.pack_propagate(False)
        vp = self.vp = make_paned(side, "vertical")                # options above, checks + export below
        vp.pack(fill="both", expand=True)
        top_pane = tk.Frame(vp, bg=T["panel"])
        self.lower = tk.Frame(vp, bg=T["panel"])
        vp.add(top_pane, minsize=S(150), stretch="always")
        vp.add(self.lower, minsize=S(92), stretch="never")
        low_sf = self.lower_sf = ScrollFrame(self.lower, T["panel"], height=60, bar=True)   # scrolls when the window is short
        low_sf.pack(fill="both", expand=True)
        low = low_sf.inner
        bottom = tk.Frame(low, bg=T["panel"])
        bottom.pack(side="bottom", fill="x", padx=16, pady=14)
        row = tk.Frame(bottom, bg=T["panel"])
        row.pack(fill="x")
        self.export_btns = []
        for i, (kind, label) in enumerate(EXPORT_FORMATS):
            if i == 2:
                row = tk.Frame(bottom, bg=T["panel"])
                row.pack(fill="x", pady=(6, 0))
            b = Btn(row, ("Export " + label) if i < 2 else label, lambda k=kind: self.export(k),
                    "primary" if i == 0 else "ghost", size=10 if i < 2 else 9, pady=10 if i < 2 else 6)
            b.pack(side="left", fill="x", expand=True, padx=(0, 6) if i not in (1, len(EXPORT_FORMATS) - 1) else 0)
            self.export_btns.append(b)
        if self.has_drawing:
            b = Btn(bottom, "Export Drawing (PDF)…", self.export_drawing, "ghost", size=9, pady=7)
            b.pack(fill="x", pady=(6, 0))
            self.export_btns.append(b)
            b = Btn(bottom, "Export 3D Model (3MF / STL)…", self.export_model3d, "ghost", size=9, pady=7)
            b.pack(fill="x", pady=(6, 0))
            self.export_btns.append(b)
        self.toast = tk.Label(bottom, text="", font=F(8), fg=T["good"], bg=T["panel"], wraplength=310, justify="left",
                              anchor="w")
        self.toast.pack(fill="x", pady=(8, 0))
        chk_wrap = tk.Frame(low, bg=T["panel"])
        chk_wrap.pack(side="bottom", fill="x")
        tk.Label(chk_wrap, text="CHECKS", font=F(8, "bold"), fg=T["dim"], bg=T["panel"], anchor="w").pack(
            fill="x", padx=18, pady=(10, 2))
        chk_sf = ScrollFrame(chk_wrap, T["panel"], height=72)
        chk_sf.pack(fill="x", padx=0)
        self.checks = chk_sf.inner
        tk.Frame(low, bg=T["border"], height=1).pack(side="bottom", fill="x")

        sf = self.side_sf = ScrollFrame(top_pane, T["panel"], bar=True)
        sf.pack(fill="both", expand=True)
        s = sf.inner
        hdr = tk.Frame(s, bg=T["panel"])
        hdr.pack(fill="x", padx=18, pady=(14, 0))
        tk.Label(hdr, text="Units", font=F(9), fg=T["text"], bg=T["panel"]).pack(side="left")
        Seg(hdr, [("mm", "mm"), ("in", "inch")], self.units).pack(side="right")

        self._section(s, "DIMENSIONS")
        self._field(s, "L", "Length")
        self._field(s, "W", "Width (same as length)" if self.style.square else "Width")
        if self.style.square:
            self.ents["W"].config(state="disabled", disabledbackground=T["panel"], disabledforeground=T["muted"])
        self._field(s, "H", self.style.height_label)
        self._field(s, "t", "Material thickness")

        self._section(s, "THESE DIMENSIONS ARE…")
        Seg(s, [("inner", "Inner"), ("outer", "Outer"), ("manufacturer", "Maker")], self.mode).pack(
            anchor="w", padx=18)
        self.mode_lbl = tk.Label(s, text="", font=F(8), fg=T["muted"], bg=T["panel"], wraplength=310, justify="left",
                                 anchor="w")
        self.mode_lbl.pack(fill="x", padx=18, pady=(6, 0))

        self._section(s, "OPTIONS")
        Switch(s, "Include fold lines", self.folds).pack(anchor="w", padx=18, pady=3)
        sw_perf = Switch(s, "Dashed cuts instead of fold lines", self.perf)
        sw_perf.pack(anchor="w", padx=18, pady=3)
        self.dash_box = tk.Frame(s, bg=T["panel"])
        self.dash_val = {}
        for key, label, lo, hi, step in (("perf_dash", "Dash length", 1.0, 20.0, 0.5),
                                          ("perf_tie", "Bridge spacing", 0.5, 10.0, 0.1)):
            row = tk.Frame(self.dash_box, bg=T["panel"])
            row.pack(fill="x", pady=(2, 0))
            tk.Label(row, text=label, font=F(9), fg=T["muted"], bg=T["panel"], anchor="w").pack(side="left")
            self.dash_val[key] = tk.Label(row, text="", font=F(9, "bold"), fg=T["text"], bg=T["panel"], anchor="e")
            self.dash_val[key].pack(side="right")
            Slider(self.dash_box, self.dvars[key], lambda: None, lo, hi, step).pack(fill="x")
        tk.Label(self.dash_box, text="Cut length and uncut bridge along each fold, in mm.", font=F(8), fg=T["dim"],
                 bg=T["panel"], anchor="w").pack(fill="x")
        self._sw_perf = sw_perf
        self.perf.trace_add("write", lambda *a: self._show_dash())
        for k, v in self.dvars.items():
            v.trace_add("write", lambda *a, k=k: self._dash_changed(k))
        self._show_dash()
        Switch(s, "Edge lines in the 3-D preview", self.dvars["bend_edges"]).pack(anchor="w", padx=18, pady=3)
        tk.Label(s, text="Flute direction (corrugated board)", font=F(9), fg=T["text"], bg=T["panel"], anchor="w").pack(
            fill="x", padx=18, pady=(8, 3))
        Seg(s, [("off", "Off"), ("v", "Vertical"), ("h", "Horizontal")], self.flute).pack(anchor="w", padx=18)
        tk.Label(s, text="Vertical = along the flat sheet's up-down axis. Shown as faint lines on the outside of the "
                         "3-D preview and as a label on the drawing.", font=F(8), fg=T["dim"], bg=T["panel"],
                 wraplength=310, justify="left", anchor="w").pack(fill="x", padx=18, pady=(4, 6))
        if self.style.rounded_folds:
            Switch(s, "Rounded folds in the 3-D preview", self.dvars["bend_on"]).pack(anchor="w", padx=18, pady=3)
            Switch(s, "Take bend length out of the flaps", self.dvars["bend_len"]).pack(anchor="w", padx=18, pady=3)
            brow = tk.Frame(s, bg=T["panel"])
            brow.pack(fill="x", padx=18, pady=(0, 4))
            r_ = tk.Frame(brow, bg=T["panel"])
            r_.pack(fill="x", pady=(2, 0))
            tk.Label(r_, text="Inside bend radius", font=F(9), fg=T["muted"], bg=T["panel"], anchor="w").pack(side="left")
            self.dash_val["bend_r"] = tk.Label(r_, text="", font=F(9, "bold"), fg=T["text"], bg=T["panel"], anchor="e")
            self.dash_val["bend_r"].pack(side="right")
            Slider(brow, self.dvars["bend_r"], lambda: None, 0.0, 3.0, 0.05).pack(fill="x")
            tk.Label(brow, text="In board thicknesses. Preview and the bend data page only; the dieline is unchanged.",
                     font=F(8), fg=T["dim"], bg=T["panel"], anchor="w", wraplength=300, justify="left").pack(fill="x")
            self._dash_changed("bend_r", schedule=False)
        self.flag_sw, self.flag_hint = {}, {}
        for key, label, _ in self.style.toggles:
            sw_ = Switch(s, label, self.flags[key])
            sw_.pack(anchor="w", padx=18, pady=3)
            hint = tk.Label(s, text="", font=F(8), fg=T["muted"], bg=T["panel"], wraplength=300, justify="left", anchor="w")
            self.flag_sw[key], self.flag_hint[key] = sw_, hint

            def _shown(*a, k=key):
                if self.flags[k].get():
                    for other in self.style.toggle_conflict(k, True):
                        if other in self.flags and self.flags[other].get():
                            self.flags[other].set(False)
                if self.flags[k].get() and not getattr(self, "_restoring", False) and self.style.toggle_view(k) is not None:
                    self.amount.set(self.style.toggle_view(k) * 100.0)
                    wire = getattr(self, "wire", None)
                    if wire is not None:
                        wire.pitch = max(wire.pitch, 0.9)          # look down into the open box
                    self._on_amount()
            self.flags[key].trace_add("write", _shown)

        self._section(s, "LASER KERF  ·  blank = off")
        self._field(s, "kerf", "Kerf (beam width)")
        tk.Label(s, text="Cut lines move half the kerf away from the part so it finishes at true size. A faint "
                 "dashed outline shows the original size.", font=F(8), fg=T["dim"], bg=T["panel"], wraplength=300,
                 justify="left", anchor="w").pack(fill="x", padx=18, pady=(2, 0))

        self._section(s, "WINDOWS & ZONES")
        fb = tk.Frame(s, bg=T["panel"])
        fb.pack(fill="x", padx=18)
        for kind, lab in (("window", "+ Window"), ("info", "+ Info zone"), ("logo", "+ Logo zone")):
            Btn(fb, lab, lambda k=kind: self.add_feature(k), "ghost", size=9, padx=8, pady=5).pack(
                side="left", expand=True, fill="x", padx=(0, 4))
        self.flist = tk.Frame(s, bg=T["panel"])
        self.flist.pack(fill="x", padx=18, pady=(6, 0))
        self.fedit = tk.Frame(s, bg=T["panel"])
        self.fedit.pack(fill="x")
        self._rebuild_features_ui()

        self._section(s, "LINE COLOURS  ·  preview and export")
        self._color_row(s, "cut_color", "Cut lines")
        self._color_row(s, "fold_color", "Fold lines")
        self._color_row(s, "engrave_color", "Engrave (zones)")
        self._section(s, "LINE WEIGHTS  ·  export only")
        self._lfield(s, "cut_weight", "Cut weight", "pt")
        self._lfield(s, "fold_weight", "Fold weight", "pt")
        self._lfield(s, "engrave_weight", "Engrave weight", "pt")
        tk.Label(s, text=WEIGHT_NOTE, font=F(8), fg=T["dim"], bg=T["panel"], wraplength=300, justify="left",
                 anchor="w").pack(fill="x", padx=18, pady=(4, 0))

        if self.style.options:
            self._section(s, "ADVANCED  ·  blank = automatic")
            for key, label in self.style.options:
                self._field(s, key, label)

        if self.has_drawing:
            hd = tk.Frame(s, bg=T["panel"], cursor="hand2")
            hd.pack(fill="x", padx=18, pady=(16, 6))
            self.tol_hd = hd
            self.tol_arrow = tk.Label(hd, text="▸", font=F(8, "bold"), fg=T["dim"], bg=T["panel"], cursor="hand2")
            self.tol_arrow.pack(side="left")
            tl = tk.Label(hd, text=" DRAWING TOLERANCES  ·  advanced", font=F(8, "bold"), fg=T["dim"], bg=T["panel"],
                          anchor="w", cursor="hand2")
            tl.pack(side="left")
            for w_ in (hd, self.tol_arrow, tl):
                w_.bind("<Button-1>", lambda e: self.tol_open.set(not self.tol_open.get()))
            self.tol_body = tk.Frame(s, bg=T["panel"])
            tk.Label(self.tol_body, text="± mm, used on the exported drawing sheet. Blank = industry standard for "
                     "this board.", font=F(8), fg=T["dim"], bg=T["panel"], wraplength=300, justify="left",
                     anchor="w").pack(fill="x", padx=18, pady=(0, 4))
            for k, lab in TOL_LABELS.items():
                if k not in self.style.tol_keys:                          # e.g. no slots / glue flap on some styles
                    continue
                self._field(self.tol_body, "tol_" + k, lab.split(" (")[0] + "  ±")
            self.tol_open.trace_add("write", lambda *a: self._tol_toggle())

        self._section(s, "MATERIAL SHEET  ·  optional")
        self._field(s, "sheetw", "Sheet width")
        self._field(s, "sheeth", "Sheet height")

        tk.Frame(s, bg=T["panel"], height=16).pack()

    # ------------------------------------------------------ windows & zones ----
    def _fnum(self, k):
        try:
            return parse_num(self.fvars[k].get())
        except ValueError:
            return None

    def add_feature(self, kind):
        if not self.res or not self.res.panels:
            self.toast.config(text="Fix the dimensions first, then add a window or zone.", fg=T["err"])
            return
        rows = panel_centres(self.res.panels)[:3]
        mm = 25.4 if self.units.get() == "in" else 1.0
        r = 4.0 / mm if kind == "window" else 0.0
        spec = self.read_spec()
        pick = None
        # try spots on the biggest faces until one passes every structural check
        for scale in (1.0, 0.7, 0.5):
            for name, cx, cy, pw, ph, _a in rows:
                fw, fh = (0.5 * pw, 0.3 * ph) if kind == "window" else (0.4 * pw, 0.22 * ph)
                for oy in (0, 0.27, -0.27, 0.0, 0.0):
                    for ox in (0, 0.25, -0.25):
                        if oy == 0.0 and ox == 0 and pick is not None:
                            continue
                        c = Feature(kind, cx + ox * pw, cy + oy * ph, fw * scale, fh * scale, r)
                        spec.features = self.features + [c]
                        g = generate(self.style, spec)
                        if g.ok and not any("overlaps" in i.msg for i in g.warnings):
                            pick = c
                            break
                    if pick:
                        break
                if pick:
                    break
            if pick:
                break
        if pick is None:
            name, cx, cy, pw, ph, _a = rows[0]
            pick = Feature(kind, cx, cy, 0.3 * pw, 0.2 * ph, r)
            self.toast.config(text="No free spot found; drag the new item onto a clear area.", fg=T["warn"])
        self.features.append(pick)
        self.sel = len(self.features) - 1
        self._rebuild_features_ui()
        self.refresh()

    def select_feature(self, i):
        self.sel = i
        self._rebuild_features_ui()
        self.draw2d()

    def del_feature(self, i):
        del self.features[i]
        self.sel = None if not self.features else min(self.sel or 0, len(self.features) - 1)
        self._rebuild_features_ui()
        self.refresh()

    def _rebuild_features_ui(self):
        for w in self.flist.winfo_children() + self.fedit.winfo_children():
            w.destroy()
        for i, f in enumerate(self.features):
            row = tk.Frame(self.flist, bg=T["panel2"] if i == self.sel else T["panel"])
            row.pack(fill="x", pady=1)
            cnt = sum(1 for g in self.features[:i + 1] if g.kind == f.kind)
            lb = tk.Label(row, text=f"{f.label()} {cnt}", anchor="w", font=F(9), fg=T["text"], bg=row.cget("bg"),
                          cursor="hand2", padx=8)
            lb.pack(side="left", fill="x", expand=True, ipady=4)
            lb.bind("<Button-1>", lambda e, i=i: self.select_feature(i))
            x = tk.Label(row, text="✕", font=F(9), fg=T["muted"], bg=row.cget("bg"), cursor="hand2", padx=8)
            x.pack(side="right", ipady=4)
            x.bind("<Button-1>", lambda e, i=i: self.del_feature(i))
        if self.sel is None or self.sel >= len(self.features):
            if not self.features:
                tk.Label(self.flist, text="Add a window (cut hole) or an info / logo zone (engraved). Drag it on the "
                         "dieline to place it.", font=F(8), fg=T["dim"], bg=T["panel"], wraplength=300, justify="left",
                         anchor="w").pack(fill="x")
            return
        f = self.features[self.sel]
        self._floading = True
        for k in ("cx", "cy", "w", "h", "r"):
            self.fvars[k].set(fmt(getattr(f, k), 3))
        self.f_outline.set(f.outline)
        self.f_rot.set(f.rot == 90)
        self._floading = False
        e = self.fedit
        labels = [("cx", "Centre X"), ("cy", "Centre Y"), ("w", "Width"), ("h", "Height")]
        if f.kind == "window":
            labels.append(("r", "Corner radius"))
        for k, lab in labels:
            row = tk.Frame(e, bg=T["panel"])
            row.pack(fill="x", padx=18, pady=2)
            tk.Label(row, text=lab, font=F(9), fg=T["text"], bg=T["panel"]).pack(side="left")
            fe = tk.Entry(row, textvariable=self.fvars[k], width=8, font=F(10), bg=T["panel2"], fg=T["text"],
                          insertbackground=T["text"], relief="flat", justify="right", highlightthickness=1,
                          highlightbackground=T["border"], highlightcolor=T["accent"])
            fe.pack(side="right", ipady=3)
            self._calc_bind(fe, self.fvars[k], lambda: self.units.get(), cur_fn=(lambda k=k: self._fplain.get(k)))
        if f.kind != "window":
            Switch(e, "Draw border", self.f_outline).pack(anchor="w", padx=18, pady=3)
            b = tk.Frame(e, bg=T["panel"])
            b.pack(fill="x", padx=18, pady=(2, 0))
            Btn(b, "Import SVG…", self.import_art, "ghost", size=9, padx=10, pady=4).pack(side="left")
            if f.art is not None:
                Btn(b, "Remove", self.remove_art, "ghost", size=9, padx=10, pady=4).pack(side="left", padx=(6, 0))
                Switch(e, "Turn artwork 90°", self.f_rot).pack(anchor="w", padx=18, pady=3)
                tk.Label(e, text=f"{f.art.name or 'artwork'}  ·  {f.art.w:.1f} × {f.art.h:.1f} mm, "
                         f"{f.art.segs()} segments", font=F(8), fg=T["dim"], bg=T["panel"], wraplength=300,
                         justify="left", anchor="w").pack(fill="x", padx=18, pady=(2, 0))
                if f.art.skipped:
                    tk.Label(e, text="Ignored: " + ", ".join(f.art.skipped) + " (convert to outlines first).",
                             font=F(8), fg=T["warn"], bg=T["panel"], wraplength=300, justify="left",
                             anchor="w").pack(fill="x", padx=18)
            tk.Label(e, text="Engraved with fine lines, the art is scaled to fit and centred in the zone. Filled "
                     "shapes are engraved as outlines.", font=F(8), fg=T["dim"], bg=T["panel"], wraplength=300,
                     justify="left", anchor="w").pack(fill="x", padx=18, pady=(4, 0))

    def _fvar_changed(self):
        if self._floading or self.sel is None or self.sel >= len(self.features):
            return
        f = self.features[self.sel]
        for k in ("cx", "cy", "w", "h", "r"):
            v = self._fnum(k)
            setattr(f, k, float("nan") if v is None else v)
        f.outline, f.rot = self.f_outline.get(), 90 if self.f_rot.get() else 0
        self.schedule()

    def import_art(self):
        if self.sel is None:
            return
        path = filedialog.askopenfilename(title="Import SVG artwork", filetypes=[("SVG artwork", "*.svg")])
        if not path:
            return
        try:
            art = import_svg(path)
        except (ValueError, OSError) as exc:
            self.toast.config(text=f"Could not import: {exc}", fg=T["err"])
            return
        self.features[self.sel].art = art
        self.toast.config(text=f"Imported {art.name}.", fg=T["good"])
        self._rebuild_features_ui()
        self.refresh()

    def remove_art(self):
        if self.sel is not None:
            self.features[self.sel].art = None
            self._rebuild_features_ui()
            self.refresh()

    def _to_draw(self, ex, ey):
        v = self.view
        return (ex - v["ox"]) / v["s"], (v["oy"] - ey) / v["s"]

    def _feat_at(self, ex, ey):
        x, y = self._to_draw(ex, ey)
        order = ([self.sel] if self.sel is not None else []) + list(range(len(self.features) - 1, -1, -1))
        for i in order:
            if i < len(self.features):
                f = self.features[i]
                if abs(x - f.cx) <= f.w / 2 and abs(y - f.cy) <= f.h / 2:
                    return i, x - f.cx, y - f.cy
        return None

    def _build_main(self, parent):
        main = tk.Frame(parent, bg=T["bg"])
        parent.add(main, minsize=S(460), stretch="always")
        self.stage = make_paned(main, "horizontal")                # dieline | 3-D preview, divider draggable
        self.stage.pack(fill="both", expand=True)

        self.pane2 = tk.Frame(self.stage, bg=T["canvas"])
        self.cv2 = tk.Canvas(self.pane2, bg=T["canvas"], highlightthickness=0, cursor="fleur")
        self.cv2.pack(fill="both", expand=True)
        self.cv2.bind("<Configure>", lambda e: self.draw2d())
        self.cv2.bind("<ButtonPress-1>", self._p2_down)
        self.cv2.bind("<B1-Motion>", self._p2_move)
        self.cv2.bind("<ButtonRelease-1>", self._p2_up)
        self.cv2.bind("<MouseWheel>", self._p2_wheel)
        self.cv2.bind("<Button-4>", lambda e: self._p2_zoom(e, 1.12))
        self.cv2.bind("<Button-5>", lambda e: self._p2_zoom(e, 1 / 1.12))
        self.cv2.bind("<Double-Button-1>", lambda e: self._fit())
        self.show_labels, self.show_dims = tk.BooleanVar(value=True), tk.BooleanVar(value=True)
        self._dims, self._dim_entry = [], None
        self._tog = []
        for txt, var in (("Panel labels", self.show_labels), ("Dimensions", self.show_dims)):
            self._tog.append(tk.Checkbutton(self.cv2, text=txt, variable=var, command=self.draw2d, font=F(8), bd=0,
                                            fg=T["muted"], bg=T["canvas"], activebackground=T["canvas"],
                                            activeforeground=T["text"], selectcolor=T["panel2"], highlightthickness=0,
                                            cursor="hand2"))
        self.cv2.tag_bind("dimedit", "<Enter>", lambda e: self.cv2.config(cursor="hand2"))
        self.cv2.tag_bind("dimedit", "<Leave>", lambda e: self.cv2.config(cursor="fleur"))

        self.pane3 = tk.Frame(self.stage, bg=T["thumb"])
        self.cv3 = tk.Canvas(self.pane3, bg=T["thumb"], highlightthickness=0, cursor="exchange")
        self.cv3.pack(fill="both", expand=True)
        self.wire = Wire3D(self.cv3, self.style.view_up, lw=1.6)
        self.wire.fixed_frame = True               # no re-centring or zoom pumping while the box folds
        self.cv3.bind("<Configure>", lambda e: self._render3d())
        self.cv3.bind("<ButtonPress-1>", lambda e: setattr(self, "_drag3", (e.x, e.y)))
        self.cv3.bind("<B1-Motion>", self._p3_move)
        self.cv3.bind("<MouseWheel>", lambda e: self._p3_zoom(1.1 if e.delta > 0 else 1 / 1.1))
        self.cv3.bind("<Button-4>", lambda e: self._p3_zoom(1.1))
        self.cv3.bind("<Button-5>", lambda e: self._p3_zoom(1 / 1.1))
        bar = tk.Frame(self.pane3, bg=T["panel"], height=46)
        bar.pack(fill="x", side="bottom")
        self.btn_play = Btn(bar, "▶  Fold", self.play, "ghost", size=9, padx=12, pady=5)
        self.btn_play.pack(side="left", padx=(12, 8), pady=8)
        self.btn_spin = Btn(bar, "⟳ Spin", self.toggle_spin, "ghost", size=9, padx=10, pady=5)
        self.btn_spin.pack(side="right", padx=12, pady=8)
        self.solid_on = self.has_solid                        # opens in the solid (thickness) view
        if self.has_solid:                                    # solid board-thickness view
            self.btn_solid = Btn(bar, "▢ Wire" if self.solid_on else "◼ Solid", self.toggle_solid, "ghost", size=9,
                                 padx=10, pady=5)
            self.btn_solid.pack(side="right", padx=(0, 0), pady=8)
        sc = Slider(bar, self.amount, self._on_amount)
        sc.pack(side="left", fill="x", expand=True, pady=10, padx=(0, 10))

        self.status = tk.Label(main, text="", font=F(9), fg=T["muted"], bg=T["panel"], anchor="w", padx=16, pady=7)
        self.status.pack(fill="x", side="bottom")

    def _layout_views(self):
        m = self.view_mode.get()
        for p_ in (self.pane2, self.pane3):
            try:
                self.stage.forget(p_)
            except tk.TclError:
                pass
        for p_ in {"dieline": (self.pane2,), "fold3d": (self.pane3,)}.get(m, (self.pane2, self.pane3)):
            self.stage.add(p_, minsize=S(230), stretch="always")
        self.after(30, lambda: (self._apply_split(), self.draw2d(), self._render3d()))

    # ------------------------------------------------------------ dividers ----
    def _both_views(self):
        return len(self.stage.panes()) == 2

    def _apply_split(self):
        """Keep the dieline / 3-D divider at the remembered fraction when the window or the sidebar changes size."""
        if self._sash_drag or not self._both_views():
            return
        w = self.stage.winfo_width()
        if w > 100:
            try:
                self.stage.sash_place(0, int(w * self.app.layout["split"]), 0)
            except tk.TclError:
                pass

    def _init_sashes(self, tries=0):
        """Put every divider at its remembered place (the sidebar's checks + export area at its natural height
        the first time)."""
        lay = self.app.layout
        if self.vp.winfo_height() < 60 and tries < 30:
            self.after(40, lambda: self._init_sashes(tries + 1))
            return
        try:
            self.update_idletasks()
            self.body.sash_place(0, lay["side_w"], 0)
            nat = self.lower_sf.inner.winfo_reqheight()       # the checks + export stack at its natural height,
            low = lay["lower_h"] if lay["lower_h"] else min(nat, max(S(160), int(self.vp.winfo_height() * 0.42)))   # but never more than ~40 % of a short window
            self.vp.sash_place(0, 0, self.vp.winfo_height() - low - S(7))
        except tk.TclError:
            pass
        self._apply_split()
        self._fit_wraps()

    def _sash_press(self, e):
        w_ = e.widget
        try:
            self._sash_drag = bool(w_.identify(e.x, e.y))
        except (tk.TclError, AttributeError):
            self._sash_drag = False

    def _sash_release(self, e):
        if not self._sash_drag:
            return
        self._sash_drag = False
        lay = self.app.layout
        try:
            lay["side_w"] = self.body.sash_coord(0)[0]
            lay["lower_h"] = max(S(92), self.vp.winfo_height() - self.vp.sash_coord(0)[1] - S(7))
            if self._both_views() and self.stage.winfo_width() > 100:
                lay["split"] = min(0.8, max(0.2, self.stage.sash_coord(0)[0] / self.stage.winfo_width()))
        except tk.TclError:
            pass
        self._fit_wraps()

    def _fit_wraps(self):
        """Wrapped helper texts in the sidebar follow its width."""
        w = self.side.winfo_width()
        if w < 100:
            return

        def walk(wd):
            for c in wd.winfo_children():
                if isinstance(c, tk.Label):
                    try:
                        wl = int(float(c.cget("wraplength")))
                    except (tk.TclError, ValueError):
                        wl = 0
                    if wl:
                        base = getattr(c, "_wl0", None)
                        if base is None:
                            base = c._wl0 = wl
                        new = max(S(120), base + (w - S(352)))
                        if new != wl:
                            c.configure(wraplength=new)
                walk(c)
        walk(self.side)

    # --------------------------------------------------------------- inputs ----
    def schedule(self):
        if self._loading:
            return
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(140, self.refresh)

    def _on_units(self, *a):
        if self._loading:
            return
        new, old = self.units.get(), self._last_units
        if new == old:
            return
        f = f_ = 1 / 25.4 if new == "in" else 25.4
        self._loading = True
        exact = getattr(self, "_mm_exact", None)
        if exact is None:
            exact = self._mm_exact = {}
        for k, v in self.vars.items():
            if k.startswith("tol_") or k in self.style.count_keys:     # tolerances are always mm; counts have no unit
                continue
            try:
                x = parse_num(v.get())
            except ValueError:
                continue
            if x is not None:
                txt = v.get()
                kept = exact.get(k)
                mm = kept[1] if kept and kept[0] == txt else x * (25.4 if old == "in" else 1.0)   # unchanged since the last
                new_txt = fmt(mm * (1 / 25.4 if new == "in" else 1.0), 4 if new == "in" else 3)        # switch: use the exact
                v.set(new_txt)                                                                           # value, not the text
                exact[k] = (new_txt, mm)
        for f in self.features:
            for k in ("cx", "cy", "w", "h", "r"):
                setattr(f, k, getattr(f, k) * f_)
        self._loading = False
        self._last_units = new
        self.user_view = False
        self._rebuild_features_ui()
        self.refresh()

    def _show_dash(self):
        if self.perf.get():
            self.dash_box.pack(fill="x", padx=18, pady=(0, 4), after=self._sw_perf)
            if getattr(self, "side_sf", None) is not None:
                self.after_idle(lambda: self.side_sf.reveal(self.dash_box))
        else:
            self.dash_box.pack_forget()
        for k in self.dvars:
            self._dash_changed(k, schedule=False)

    def _dash_changed(self, k, schedule=True):
        try:
            v = self.dvars[k].get()
        except tk.TclError:
            return
        self.app.dash[k] = v
        if k in self.dash_val:
            self.dash_val[k].config(text=f"{v:g} mm" if k.startswith("perf") else f"{v:.2f} x board")
        if k.startswith("bend") and schedule and getattr(self, "has_drawing", False) and not self._loading:
            self._sync_solid()
            self.wire.render()

    def snapshot(self):
        d = {k: v.get() for k, v in self.vars.items()}
        d.update(units=self.units.get(), mode=self.mode.get(), folds=self.folds.get(), perf=self.perf.get(),
                 flute=self.flute.get(), view=self.view_mode.get())
        for k, v in self.flags.items():
            d["flag_" + k] = v.get()
        return d

    def read_spec(self):
        pre = []
        vals = {}
        for k in ("L", "W", "H", "t"):
            try:
                vals[k] = parse_num(self.vars[k].get())
            except ValueError:
                vals[k] = None
                pre.append((k, "not a number"))
            if vals[k] is None and not any(p[0] == k for p in pre):
                pre.append((k, "required"))
        opts = {}
        for k, _ in self.style.options:
            try:
                opts[k] = parse_num(self.vars[k].get())
            except ValueError:
                opts[k] = float("nan")
        sh = []
        for k in ("sheetw", "sheeth"):
            try:
                sh.append(parse_num(self.vars[k].get()))
            except ValueError:
                sh.append(None)
        flags = {}
        for k, v in self.flags.items():                       # an option the typed sizes cannot use is left out, with a reason
            why = self.style.toggle_hint(k, vals)
            flags[k] = bool(v.get()) and not why
            sw_, hint = self.flag_sw.get(k), self.flag_hint.get(k)
            if sw_ is not None:
                sw_.set_enabled(not why)
                if why:
                    hint.config(text=why)
                    hint.pack(fill="x", padx=18, after=sw_)
                else:
                    hint.pack_forget()
        spec = Spec(vals["L"], vals["W"], vals["H"], vals["t"], self.mode.get(), self.units.get(), opts,
                    self.folds.get(), flags, tuple(sh))
        spec.perf = self.perf.get()
        spec.flute = {"v": "v", "h": "h"}.get(self.flute.get())
        spec.perf_dash, spec.perf_tie = self.dvars["perf_dash"].get(), self.dvars["perf_tie"].get()
        spec.bend_r = max(0.0, self.dvars["bend_r"].get()) * spec.t if spec.t and math.isfinite(spec.t) else None
        spec.features = self.features
        if self.has_drawing:
            spec.tol = {}
            for k in TOL_LABELS:
                try:
                    tv = parse_num(self.vars["tol_" + k].get())
                except ValueError:
                    tv = float("nan")
                if tv is not None:
                    spec.tol[k] = tv
        try:
            kv = parse_num(self.vars["kerf"].get())
        except ValueError:
            kv = float("nan")
        spec.kerf = 0.0 if kv is None else kv
        look = dict(cut_color=self.lvars["cut_color"].get(), fold_color=self.lvars["fold_color"].get(),
                    engrave_color=self.lvars["engrave_color"].get())
        for k in ("cut_weight", "fold_weight", "engrave_weight"):
            try:
                v = parse_num(self.lvars[k].get())
            except ValueError:
                v = None
            look[k] = float("nan") if v is None else v
        spec.look = look
        for k, v in look.items():                       # remembered for the other boxes in this session only
            if not (isinstance(v, float) and not math.isfinite(v)):
                self.app.look[k] = v
        return spec

    # -------------------------------------------------------------- refresh ----
    # ----------------------------------------------------- undo / redo ----
    def _state(self):
        feats = [(f.kind, f.cx, f.cy, f.w, f.h, f.r, f.art, f.outline, f.rot) for f in self.features]
        return dict(vars={k: v.get() for k, v in self.vars.items()}, units=self.units.get(), mode=self.mode.get(),
                    folds=self.folds.get(), perf=self.perf.get(), flute=self.flute.get(),
                    flags={k: v.get() for k, v in self.flags.items()},
                    look={k: v.get() for k, v in self.lvars.items()},
                    dash={k: v.get() for k, v in self.dvars.items()}, feats=feats, sel=self.sel)

    def _track(self):
        """Remember the state before each burst of edits (typing, dragging a slider or a window = one step)."""
        if self._restoring:
            return
        import time
        cur = self._state()
        if self._base is None:
            self._base = cur
            return
        if cur == self._base:
            return
        now = time.monotonic()
        if now - self._last_change > 0.8:
            self._undo.append(self._base)
            del self._undo[:-100]
            self._redo.clear()
        self._last_change = now
        self._base = cur

    def _apply_state(self, st):
        self._restoring = self._loading = True
        try:
            for k, v in st["vars"].items():
                if k in self.vars:
                    self.vars[k].set(v)
            self.units.set(st["units"])
            self._last_units = st["units"]
            self.mode.set(st["mode"])
            self.folds.set(st["folds"])
            self.perf.set(st["perf"])
            self.flute.set(st.get("flute", "off"))
            for k, v in st["flags"].items():
                if k in self.flags:
                    self.flags[k].set(v)
            for k, v in st["look"].items():
                self.lvars[k].set(v)
            for k, v in st["dash"].items():
                self.dvars[k].set(v)
            self.features = [Feature(kd, cx, cy, w, h, r, art, ol, rot) for kd, cx, cy, w, h, r, art, ol, rot in st["feats"]]
            self.sel = st["sel"] if st["sel"] is not None and st["sel"] < len(self.features) else None
        finally:
            self._loading = False
        self._rebuild_features_ui()
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        self.refresh()
        self._restoring = False
        self._base = self._state()
        self._last_change = 0.0

    def _flush_pending(self):
        if self._job:                                       # an edit still waiting for its redraw: record it first
            self.after_cancel(self._job)
            self.refresh()

    def undo(self, e=None):
        self._flush_pending()
        if not self._undo:
            self.toast.config(text="Nothing to undo.", fg=T["muted"])
            return "break"
        self._redo.append(self._state())
        self._apply_state(self._undo.pop())
        self.toast.config(text=f"Undo  ({len(self._undo)} more)", fg=T["muted"])
        return "break"

    def redo(self, e=None):
        self._flush_pending()
        if not self._redo:
            self.toast.config(text="Nothing to redo.", fg=T["muted"])
            return "break"
        self._undo.append(self._state())
        self._apply_state(self._redo.pop())
        self.toast.config(text=f"Redo  ({len(self._redo)} more)", fg=T["muted"])
        return "break"

    def refresh(self):
        self._job = None
        self._track()
        if self.project_path:
            self.app._set_title()                             # shows a * while there are unsaved changes
        self.mode_lbl.config(text=self.style.mode_help.get(self.mode.get(), ""))
        spec = self.read_spec()
        res = generate(self.style, spec)
        self.res = res
        self._show_issues(res)
        self._show_autos(res)
        ok = res.ok
        for b in self.export_btns:
            b.set_enabled(ok)
        if res.panels:
            self._sync_solid(spec)
            self.wire.set_panels(res.panels, self.style.view_up)
            self._on_amount(redraw=False)
        else:
            self.wire.set_panels(None)
        self.draw2d()
        self._render3d()
        u = spec.units
        if res.info.get("flat"):
            w, h = res.info["flat"]
            i = res.info["inner"]
            self.status.config(text=f"Flat sheet  {fmt(w, 1)} × {fmt(h, 1)} {u}     ·     Inside  "
                                    f"{fmt(i[0], 2)} × {fmt(i[1], 2)} × {fmt(i[2], 2)} {u}")
        else:
            self.status.config(text="")
        self.after_idle(self._fit_wraps)

    def _show_issues(self, res):
        for w in self.checks.winfo_children():
            w.destroy()
        for e in self.ents.values():
            e.config(highlightbackground=T["border"])
        order = {"error": 0, "warn": 1, "info": 2}
        issues = sorted(res.issues, key=lambda i: order[i.level])
        if not issues:
            row = tk.Frame(self.checks, bg=T["panel"])
            row.pack(fill="x", pady=2, padx=18)
            tk.Label(row, text="●", fg=T["good"], bg=T["panel"], font=F(9)).pack(side="left", anchor="n")
            tk.Label(row, text="Looks good - no problems found.", fg=T["muted"], bg=T["panel"], font=F(9)).pack(
                side="left", padx=(6, 0))
        colors = {"error": T["err"], "warn": T["warn"], "info": T["info"]}
        for i in issues:
            row = tk.Frame(self.checks, bg=T["panel"])
            row.pack(fill="x", pady=3, padx=18)
            tk.Label(row, text="●", fg=colors[i.level], bg=T["panel"], font=F(9)).pack(side="left", anchor="n")
            tk.Label(row, text=i.msg, fg=T["text"] if i.level != "info" else T["muted"], bg=T["panel"], font=F(9),
                     wraplength=285, justify="left", anchor="w").pack(side="left", padx=(6, 0), fill="x", expand=True)
            for f in i.fields:
                e = self.ents.get(f)
                if e is not None and (e.cget("highlightbackground") != colors["error"]):
                    e.config(highlightbackground=colors[i.level])
        if not res.ok:
            self.toast.config(text="Export is disabled until the red items are fixed.", fg=T["err"])
        elif self.toast.cget("fg") == T["err"]:
            self.toast.config(text="")

    def _tol_toggle(self):
        if self.tol_open.get():
            self.tol_body.pack(fill="x", after=self.tol_hd)
        else:
            self.tol_body.pack_forget()
        self.tol_arrow.config(text="▾" if self.tol_open.get() else "▸")

    def _show_autos(self, res):
        tol = res.info.get("tol")
        if self.has_drawing and tol:
            for k in TOL_LABELS:
                lbl = self.auto_lbl.get("tol_" + k)
                if lbl is not None:
                    lbl.config(text=f"auto {fmt(tol['values'][k], 2)}" if not self.vars["tol_" + k].get().strip() else "")
            if any(i.fields and i.fields[0].startswith("tol_") for i in res.issues if i.level != "info") \
                    and not self.tol_open.get():
                self.tol_open.set(True)
        auto = res.info.get("auto", {})
        flags = {k: v.get() for k, v in self.flags.items()}
        for key, _ in self.style.options:
            on = self.style.option_enabled(key, flags)                   # an option for a switch that is off is greyed out
            self.ents[key].config(state="normal" if on else "disabled", disabledbackground=T["panel"],
                                  disabledforeground=T["dim"])
            lbl = self.auto_lbl[key]
            val = auto.get(self._auto_key(key))
            if val is None and key in self.style.count_keys and isinstance(auto.get("ins"), dict):
                val = auto["ins"].get(key[1:])                           # the Slotted Box's divider counts: gnl -> nl
            if val is not None and not self.vars[key].get().strip():
                lbl.config(text=f"auto {fmt(val, 2)}")
            else:
                lbl.config(text="")

    def _auto_key(self, key):
        return {"lidh": "lidh", "clr": "clr"}.get(key, key)

    # ----------------------------------------------------------------- 2-D ----
    def _bounds(self):
        d = self.res.drawing
        return d.bounds() if d else None

    def _fit(self):
        self.user_view = False
        self.draw2d()

    def _p2_down(self, e):
        self._fdrag = None
        if self._dim_entry is not None:
            return
        for it in reversed(self.cv2.find_overlapping(e.x - 4, e.y - 4, e.x + 4, e.y + 4)):
            tg = [t for t in self.cv2.gettags(it) if t.startswith("dimi")]
            if tg and "dimedit" in self.cv2.gettags(it):
                self._drag = None
                self._dim_edit(int(tg[0][4:]))
                return
        hit = self._feat_at(e.x, e.y) if self.res is not None and self.res.drawing is not None else None
        if hit:
            i, dx, dy = hit
            if i != self.sel:
                self.select_feature(i)
            self._fdrag = (i, dx, dy)
            self._drag = None
            return
        self._drag = (e.x, e.y)

    def _p2_up(self, e):
        self._fdrag = None

    def _p2_move(self, e):
        if self._fdrag:
            i, dx, dy = self._fdrag
            x, y = self._to_draw(e.x, e.y)
            f = self.features[i]
            f.cx, f.cy = x - dx, y - dy
            self._floading = True
            self.fvars["cx"].set(fmt(f.cx, 3))
            self.fvars["cy"].set(fmt(f.cy, 3))
            self._floading = False
            self.schedule()
            return
        if self._drag:
            self.view["ox"] += e.x - self._drag[0]
            self.view["oy"] += e.y - self._drag[1]
            self._drag = (e.x, e.y)
            self.user_view = True
            self.draw2d()

    def _p2_wheel(self, e):
        self._p2_zoom(e, 1.12 if e.delta > 0 else 1 / 1.12)

    def _p2_zoom(self, e, k):
        v = self.view
        v["ox"] = e.x - (e.x - v["ox"]) * k
        v["oy"] = e.y - (e.y - v["oy"]) * k
        v["s"] *= k
        self.user_view = True
        self.draw2d()

    def draw2d(self):
        cv = self.cv2
        if self._dim_entry is not None:                       # a redraw while a dimension is being typed: drop the box
            try:
                self._dim_entry.destroy()
            except tk.TclError:
                pass
            self._dim_entry = None
        cv.delete("all")
        self._dims = []
        W, H = cv.winfo_width(), cv.winfo_height()
        if W < 20 or H < 20 or self.res is None:
            return
        d = self.res.drawing
        u = self.units.get()
        if d is None:
            cv.create_text(W / 2, H / 2, text="No dieline yet", fill=T["dim"], font=F(14))
            self._banner(cv, W)
            return
        x0, y0, x1, y1 = d.bounds()
        if not self.user_view:
            pad = S(112) if self.show_dims.get() else 64
            s = min((W - 2 * pad) / max(x1 - x0, 1e-9), (H - 2 * pad) / max(y1 - y0, 1e-9))
            self.view.update(s=s, ox=(W - s * (x1 - x0)) / 2 - s * x0, oy=(H + s * (y1 - y0)) / 2 + s * y0)
        v = self.view
        s = v["s"]
        X = lambda x: v["ox"] + s * x
        Y = lambda y: v["oy"] - s * y
        # dot grid
        step = 20
        for gx in range(0, W, 40):
            for gy in range(0, H, 40):
                cv.create_rectangle(gx, gy, gx + 1, gy + 1, fill=T["grid"], outline="")
        try:
            lk = resolve_look({k: v for k, v in self.app.look.items()})
        except (ValueError, TypeError):
            lk = resolve_look()
        cut_c, fold_c = view_color(lk["cut_hex"]), view_color(lk["fold_hex"])
        col = {CUT: cut_c, FOLD: fold_c, ENGRAVE: view_color(lk["engrave_hex"])}
        bad = not self.res.ok
        nom = self.res.nominal
        if nom is not None and self.res.info.get("kerf"):
            ghost = mix(T["dim"], T["canvas"], 0.2)
            for it in nom.items:
                if it[0] == "L":
                    _, p, q, _l = it
                    cv.create_line(X(p[0]), Y(p[1]), X(q[0]), Y(q[1]), fill=ghost, width=1, dash=(2, 3))
                else:
                    _, ce, r, a0, a1, _l = it
                    cv.create_arc(X(ce[0] - r), Y(ce[1] + r), X(ce[0] + r), Y(ce[1] - r), start=a0,
                                  extent=(a1 - a0) % 360 or 360, style="arc", outline=ghost, width=1, dash=(2, 3))
        for it in d.items:
            c = col[it[-1]]
            if bad:
                c = mix(c, T["canvas"], 0.55)
            lw = 1.6 if it[-1] == CUT else 1.3 if it[-1] == FOLD else 1.0
            if it[0] == "L":
                _, p, q, layer = it
                cv.create_line(X(p[0]), Y(p[1]), X(q[0]), Y(q[1]), fill=c, width=lw, capstyle="round")
            else:
                _, ce, r, a0, a1, layer = it
                span = (a1 - a0) % 360 or 360
                cv.create_arc(X(ce[0] - r), Y(ce[1] + r), X(ce[0] + r), Y(ce[1] - r), start=a0, extent=span,
                              style="arc", outline=c, width=lw)
        if self.sel is not None and self.sel < len(self.features):
            f = self.features[self.sel]
            if all(math.isfinite(q) for q in (f.cx, f.cy, f.w, f.h)):
                cv.create_rectangle(X(f.cx - f.w / 2), Y(f.cy + f.h / 2), X(f.cx + f.w / 2), Y(f.cy - f.h / 2),
                                    outline=T["accent"], dash=(4, 3), width=1)
        if self.show_labels.get():
            self._draw_labels(cv, X, Y, s)
        drew = self.show_dims.get() and self._draw_dims(cv, X, Y, u)
        # overall size callouts (the dimension callouts above already carry them)
        ax = T["dim"]
        if not drew:
            by = Y(y0) + S(22)
            cv.create_line(X(x0), by, X(x1), by, fill=ax, arrow="both")
            cv.create_text((X(x0) + X(x1)) / 2, by + S(12), text=f"{fmt(x1 - x0, 1)} {u}", fill=T["muted"], font=F(8))
            rx = X(x1) + S(22)
            cv.create_line(rx, Y(y0), rx, Y(y1), fill=ax, arrow="both")
            cv.create_text(rx + S(14), (Y(y0) + Y(y1)) / 2, text=f"{fmt(y1 - y0, 1)} {u}", fill=T["muted"], font=F(8),
                           angle=90)
        for i, tw in enumerate(self._tog):
            cv.create_window(S(12) + i * S(104), S(8), window=tw, anchor="nw")
        # legend
        lx, ly = S(18), H - S(20)
        cv.create_line(lx, ly, lx + S(22), ly, fill=cut_c, width=2)
        cv.create_text(lx + S(30), ly, text="Cut", fill=T["muted"], font=F(8), anchor="w")
        cv.create_line(lx + S(70), ly, lx + S(92), ly, fill=fold_c, width=2)
        cv.create_text(lx + S(100), ly, text="Fold / score", fill=T["muted"], font=F(8), anchor="w")
        if self.res.info.get("kerf"):
            cv.create_line(lx + S(300), ly, lx + S(322), ly, fill=T["dim"], dash=(2, 3))
            cv.create_text(lx + S(330), ly, text="Original size", fill=T["muted"], font=F(8), anchor="w")
        if any(it[-1] == ENGRAVE for it in d.items):
            cv.create_line(lx + S(190), ly, lx + S(212), ly, fill=col[ENGRAVE], width=2)
            cv.create_text(lx + S(220), ly, text="Engrave", fill=T["muted"], font=F(8), anchor="w")
        cv.create_text(W - S(14), H - S(20), text=("drag = pan · wheel = zoom · drag a window / zone to move it" if W > S(820) else ""), fill=T["dim"], font=F(8),
                       anchor="e")
        self._banner(cv, W)

    def _draw_labels(self, cv, X, Y, s):
        """Each panel's name and its crease-to-crease size, in the middle of the panel (left out when it would not fit)."""
        u = self.units.get()
        for p in self.res.panels or []:
            xs, ys = [q[0] for q in p.poly], [q[1] for q in p.poly]
            bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
            pw, ph = (bx1 - bx0) * s, (by1 - by0) * s
            name = self.style.panel_label(p.name)
            size = f"{fmt(bx1 - bx0, 1)} × {fmt(by1 - by0, 1)}"
            cx, cy = (X(bx0) + X(bx1)) / 2, (Y(by0) + Y(by1)) / 2
            if pw >= S(14) + 5.2 * len(name) and ph >= S(34):
                cv.create_text(cx, cy - S(6), text=name, fill=T["muted"], font=F(7, "bold"))
                if pw >= S(14) + 5.2 * len(size):
                    cv.create_text(cx, cy + S(6), text=size, fill=T["dim"], font=F(7))
            elif pw >= S(14) + 5.2 * len(name) and ph >= S(16):
                cv.create_text(cx, cy, text=name, fill=T["muted"], font=F(7, "bold"))
            elif ph >= S(14) + 5.2 * len(name) and pw >= S(16):      # tall and thin: read it sideways
                cv.create_text(cx, cy, text=name, fill=T["muted"], font=F(7, "bold"), angle=90)

    def _draw_dims(self, cv, X, Y, u):
        """Dimension callouts of the flat blank (the same ones as on the drawing sheet). A callout that is one sidebar box
        (a panel width, the flap, the glue flap ...) is drawn in the accent colour and can be clicked to change it."""
        res = self.res
        try:
            dims = self.style.dimensions(res, res.spec)
        except Exception:                                  # noqa: BLE001  (a blank that failed its checks has no callouts)
            return False
        if not dims:
            return False
        ax = T["dim"]
        row1, row2, gap, over = S(30), S(52), S(3), S(4)
        crowd = 0
        self._dims = []
        for dm in dims:
            try:
                fld = self.style.dim_field(dm, res, res.spec)
            except Exception:                              # noqa: BLE001
                fld = None
            label = _fnum(dm["v"], u) + (f" {dm['note']}" if dm.get("note") else "")
            col = T["accent"] if fld else T["muted"]
            tag = (f"dimi{len(self._dims)}", "dimedit") if fld else ()
            font = F(8, "bold") if fld else F(8)
            off = row1 if abs(dm["row"]) == 1 else row2
            if dm["kind"] == "h":
                a, b = X(dm["a"]), X(dm["b"])
                yo = Y(dm["ref"])
                yb0 = Y(dm.get("yref", dm["ref"]))
                sg = 1 if dm["row"] > 0 else -1
                yl = yb0 - sg * off
                for xx in (a, b):
                    cv.create_line(xx, yo - sg * gap, xx, yl - sg * over, fill=ax)
                lo, hi = min(a, b), max(a, b)
                cv.create_line(lo, yl, hi, yl, fill=ax, arrow="both", arrowshape=(S(7), S(8), S(3)))
                tx, ty = (lo + hi) / 2, yl - sg * S(10)
                if len(label) * S(6) > hi - lo - S(8):      # a span narrower than its text: neighbours alternate in height
                    ty -= sg * S(12) * (crowd % 2)
                    crowd += 1
                anchor, ang = "center", 0
            else:
                a, b = Y(dm["a"]), Y(dm["b"])
                xo = X(dm["ref"])
                xl = X(dm.get("xref", dm["ref"])) + off
                for yy in (a, b):
                    cv.create_line(xo + gap, yy, xl + over, yy, fill=ax)
                lo, hi = min(a, b), max(a, b)
                cv.create_line(xl, lo, xl, hi, fill=ax, arrow="both", arrowshape=(S(7), S(8), S(3)))
                tx, ty = xl + S(10), (lo + hi) / 2
                anchor, ang = "center", 90
            it = cv.create_text(tx, ty, text=label, fill=col, font=font, angle=ang, anchor=anchor, tags=tag)
            if fld:
                self._dims.append((dm, fld, tx, ty, ang))
        return True

    def _dim_edit(self, i):
        """Type a new value for callout `i`: a box opens on it, and Enter changes the matching sidebar box by the same
        amount (so a panel width in Inner mode still means the inside size), exactly as if it had been typed there."""
        dm, fld, tx, ty, ang = self._dims[i]
        key, now = fld[0], fld[1]
        scale = fld[2] if len(fld) > 2 else 1.0           # how far the box moves for one unit of the dimension
        u = self.units.get()
        var = self.vars[key]
        ent = tk.Entry(self.cv2, width=9, font=F(10), bg=T["panel2"], fg=T["text"], insertbackground=T["text"],
                       relief="flat", justify="center", highlightthickness=1, highlightbackground=T["accent"],
                       highlightcolor=T["accent"])
        ent.insert(0, fmt(dm["v"], 4 if u == "in" else 3))
        self._dim_entry = ent
        self.cv2.create_window(tx, ty, window=ent, anchor="center")

        def close(*_):
            if self._dim_entry is ent:
                self._dim_entry = None
            try:
                ent.destroy()
            except tk.TclError:
                pass

        def commit(*_):
            raw = ent.get()
            try:
                typed = parse_num(raw) if is_plain_number(raw) else calc_eval(raw, dm["v"], u)
                base = parse_num(var.get()) if now is None else now
                if base is None:
                    raise ValueError("that box is empty")
            except ValueError as exc:
                self.toast.config(text=f"Can't use that: {exc}.", fg=T["err"])
                return
            new = base + (typed - dm["v"]) * scale
            close()
            var.set(fmt(new, 4 if u == "in" else 3))
            self.toast.config(text=f"{dict(self._box_labels()).get(key, key)} set to {var.get()}", fg=T["muted"])
            self.schedule()

        ent.bind("<Return>", commit)
        ent.bind("<KP_Enter>", commit)
        ent.bind("<Escape>", close)
        ent.bind("<FocusOut>", close)
        ent.focus_set()
        ent.select_range(0, "end")

    def _box_labels(self):
        """[(key, label)] of the sidebar boxes, for messages."""
        return [("L", "Length"), ("W", "Width"), ("H", self.style.height_label), ("t", "Thickness")] + list(self.style.options)

    def _banner(self, cv, W):
        if self.res is None or self.res.ok:
            return
        errs = self.res.errors
        msg = errs[0].msg if errs else ""
        if len(errs) > 1:
            msg += f"   (+{len(errs) - 1} more)"
        t = cv.create_text(W / 2, 16, text="⚠  " + msg, fill="#ffffff", font=F(9, "bold"), width=max(W - 100, 120),
                           anchor="n", justify="center")
        bb = cv.bbox(t)
        r = cv.create_rectangle(bb[0] - 14, bb[1] - 7, bb[2] + 14, bb[3] + 7, fill=mix(T["err"], T["canvas"], 0.55),
                                outline=T["err"])
        cv.tag_lower(r, t)

    # ----------------------------------------------------------------- 3-D ----
    def _render3d(self):
        cv = self.cv3
        for it in cv.find_withtag("msg"):
            cv.delete(it)
        if self.res is None:
            return
        if self.wire.panels:
            self.wire.render()
            cv.create_text(16, 16, anchor="nw", text="drag = rotate · wheel = zoom", fill=T["dim"], font=F(8), tags="msg")
        else:
            W, H = cv.winfo_width(), cv.winfo_height()
            cv.create_text(W / 2, H / 2, text="No folded preview until the red items are fixed", fill=T["dim"],
                           font=F(12), tags="msg")

    def _on_amount(self, redraw=True):
        self.wire.amount = self.amount.get() / 100.0
        if redraw:
            self.wire.render()

    def _p3_move(self, e):
        x, y = self._drag3
        self.wire.yaw += (e.x - x) * 0.01
        self.wire.pitch = max(-1.45, min(1.45, self.wire.pitch + (e.y - y) * 0.01))
        self._drag3 = (e.x, e.y)
        self.wire.render()

    def _p3_zoom(self, k):
        self.wire.zoom = max(0.3, min(4.0, self.wire.zoom * k))
        self.wire.render()

    def play(self):
        if self._anim:
            self.after_cancel(self._anim)
            self._anim = None
            self.btn_play.config(text="▶  Fold")
            return
        if self.amount.get() >= 99.5:
            self.amount.set(0)
        self.btn_play.config(text="❚❚  Pause")
        self._anim_t = time.perf_counter()
        self._step()

    def _step(self):
        now = time.perf_counter()                          # time-based: the fold takes the same ~1.7 s however long a frame takes
        dt = min(0.1, now - getattr(self, "_anim_t", now))
        self._anim_t = now
        v = self.amount.get() + (dt * 58.0 if dt > 0 else 1.4)
        if v >= 100:
            self.amount.set(100)
            self._on_amount()
            self._anim = None
            self.btn_play.config(text="▶  Fold")
            return
        self.amount.set(v)
        self._on_amount()
        self._anim = self.after(max(1, 16 - int((time.perf_counter() - now) * 1000)), self._step)

    def _sync_solid(self, spec=None):
        spec = spec or self.read_spec()
        t = spec.t if (spec.t and math.isfinite(spec.t)) else 0.0
        self.wire.solid = bool(self.solid_on and self.has_solid and t > 0)
        self.wire.seq = bool(self.has_solid and t > 0)
        self.wire.style_id = self.style.id
        self.wire.thick = t
        try:
            on = bool(self.dvars["bend_on"].get())
            self.wire.bend = self.dvars["bend_r"].get() * t if (on and t > 0 and self.style.rounded_folds) else None
            self.wire.bend_len = bool(self.dvars["bend_len"].get())
            self.wire.edges = bool(self.dvars["bend_edges"].get())
            self.wire.flute = getattr(spec, "flute", None)
        except (tk.TclError, KeyError):
            self.wire.bend = None

    def toggle_solid(self):
        self.solid_on = not self.solid_on
        self.btn_solid.config(text="◼ Solid" if not self.solid_on else "▢ Wire")
        self._sync_solid()
        self.wire.render()

    def toggle_spin(self):
        if self._spin:
            self.after_cancel(self._spin)
            self._spin = None
            self.btn_spin.config(text="⟳ Spin")
            return
        self.btn_spin.config(text="■ Stop")
        self._spin_t = time.perf_counter()
        self._spin_step()

    def _spin_step(self):
        now = time.perf_counter()                          # time-based, so the turn rate does not depend on frame time
        dt = min(0.1, now - getattr(self, "_spin_t", now))
        self._spin_t = now
        self.wire.yaw += 0.55 * dt if dt > 0 else 0.018
        self.wire.render()
        self._spin = self.after(max(1, 16 - int((time.perf_counter() - now) * 1000)), self._spin_step)

    def shutdown(self):
        for j in (self._job, self._anim, self._spin):
            if j:
                try:
                    self.after_cancel(j)
                except Exception:
                    pass

    # --------------------------------------------------------------- export ----
    def _gcode_dialog(self):
        win = tk.Toplevel(self, bg=T["panel"])
        win.title("G-code settings")
        win.transient(self.winfo_toplevel())
        win.resizable(False, False)
        tk.Label(win, text="GRBL-style laser job: M4 dynamic power, origin = bottom-left of the sheet.\n"
                           "Engraving runs first, then scores, then cuts. Test on scrap and lower the power if unsure.",
                 font=F(9), fg=T["muted"], bg=T["panel"], justify="left").grid(row=0, column=0, columnspan=2,
                                                                              padx=18, pady=(16, 8), sticky="w")
        rows = [("cut_power", "Cut power (S, 0-1000)"), ("cut_feed", "Cut speed (mm/min)"),
                ("cut_passes", "Cut passes"), ("fold_power", "Score power (S, 0-1000)"),
                ("fold_feed", "Score speed (mm/min)"), ("fold_passes", "Score passes"),
                ("engrave_power", "Engrave power (S, 0-1000)"), ("engrave_feed", "Engrave speed (mm/min)"),
                ("engrave_passes", "Engrave passes")]
        vs = {}
        for i, (k, lab) in enumerate(rows, 1):
            tk.Label(win, text=lab, font=F(9), fg=T["text"], bg=T["panel"]).grid(row=i, column=0, padx=(18, 10),
                                                                                  pady=3, sticky="w")
            vs[k] = tk.StringVar(value=fmt(self.app.gcode[k], 2))
            tk.Entry(win, textvariable=vs[k], width=9, font=F(10), bg=T["panel2"], fg=T["text"],
                     insertbackground=T["text"], relief="flat", justify="right").grid(row=i, column=1, padx=(0, 18),
                                                                                       pady=3, ipady=3)
        err = tk.Label(win, text="", font=F(8), fg=T["err"], bg=T["panel"])
        err.grid(row=11, column=0, columnspan=2, padx=18, sticky="w")
        out = {}

        def ok():
            try:
                v = {k: float(x.get().replace(",", ".")) for k, x in vs.items()}
            except ValueError:
                err.config(text="Enter numbers only.")
                return
            if not all(0 <= v[k] <= 1000 for k in ("cut_power", "fold_power", "engrave_power")):
                err.config(text="Power must be between 0 and 1000.")
                return
            if v["cut_feed"] <= 0 or v["fold_feed"] <= 0 or v["engrave_feed"] <= 0 \
                    or v["cut_passes"] < 1 or v["fold_passes"] < 1 or v["engrave_passes"] < 1:
                err.config(text="Speeds must be > 0 and passes >= 1.")
                return
            for k in ("cut_passes", "fold_passes", "engrave_passes"):
                v[k] = int(v[k])
            out.update(v)
            win.destroy()

        bar = tk.Frame(win, bg=T["panel"])
        bar.grid(row=12, column=0, columnspan=2, pady=(8, 16), padx=18, sticky="e")
        Btn(bar, "Cancel", win.destroy, "ghost", pady=6).pack(side="left", padx=(0, 8))
        Btn(bar, "Save G-code…", ok, "primary", pady=6).pack(side="left")
        win.update_idletasks()
        try:
            win.grab_set()
        except tk.TclError:
            pass
        self.wait_window(win)
        if out:
            self.app.gcode.update(out)
        return out or None

    def _drawing_dialog(self):
        o = self.app.drawing_opts
        win = tk.Toplevel(self, bg=T["panel"])
        win.title("Export drawing")
        win.transient(self.winfo_toplevel())
        win.resizable(False, False)
        tk.Label(win, text="Dimensioned dieline sheet (PDF). Choose what goes on it.", font=F(9), fg=T["muted"],
                 bg=T["panel"]).grid(row=0, column=0, columnspan=2, padx=18, pady=(16, 8), sticky="w")
        bv = {b.key: tk.BooleanVar(value=o.get(b.key, True)) for b in DRAWING_BLOCKS}
        for i, (k, lab) in enumerate(((b.key, b.label) for b in DRAWING_BLOCKS), 1):
            Switch(win, lab, bv[k]).grid(row=i, column=0, columnspan=2, padx=18, pady=3, sticky="w")
        tv = {}
        for j, (k, lab) in enumerate(((k, lab) for k, lab, _ in DRAWING_FIELDS), 7):
            tk.Label(win, text=lab, font=F(9), fg=T["text"], bg=T["panel"]).grid(row=j, column=0, padx=(18, 10),
                                                                                  pady=3, sticky="w")
            tv[k] = tk.StringVar(value=o[k])
            tk.Entry(win, textvariable=tv[k], width=22, font=F(10), bg=T["panel2"], fg=T["text"],
                     insertbackground=T["text"], relief="flat").grid(row=j, column=1, padx=(0, 18), pady=3, ipady=3)
        tk.Label(win, text="Text fields appear in the title block.", font=F(8), fg=T["dim"], bg=T["panel"]).grid(
            row=12, column=0, columnspan=2, padx=18, sticky="w")
        out = {}

        def ok():
            out.update({k: v.get() for k, v in bv.items()})
            out.update({k: v.get().strip() for k, v in tv.items()})
            win.destroy()

        bar = tk.Frame(win, bg=T["panel"])
        bar.grid(row=13, column=0, columnspan=2, pady=(8, 16), padx=18, sticky="e")
        Btn(bar, "Cancel", win.destroy, "ghost", pady=6).pack(side="left", padx=(0, 8))
        Btn(bar, "Save drawing…", ok, "primary", pady=6).pack(side="left")
        win.update_idletasks()
        try:
            win.grab_set()
        except tk.TclError:
            pass
        self.wait_window(win)
        if out:
            self.app.drawing_opts.update(out)
        return out or None

    def export_drawing(self):
        res = self.res
        if res is None or not res.ok or res.drawing is None:
            messagebox.showerror("Can't export yet", "\n\n".join(i.msg for i in (res.errors if res else [])) or
                                 "Fix the highlighted problems first.")
            return
        opts = self._drawing_dialog()
        if opts is None:
            return
        sp = res.spec
        name = f"{self.style.id}_{fmt(sp.L)}x{fmt(sp.W)}x{fmt(sp.H)}_{sp.units}_drawing.pdf"
        path = filedialog.asksaveasfilename(defaultextension=".pdf", initialfile=name,
                                            filetypes=[("PDF drawing", "*.pdf")])
        if not path:
            return
        try:
            data = drawing_pdf(res, sp, opts)
            with open(path, "wb") as fh:
                fh.write(data)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not save", str(exc))
            return
        self.toast.config(text=f"Saved drawing {os.path.basename(path)}", fg=T["good"])

    def export_model3d(self):
        res = self.res
        if res is None or not res.ok or res.drawing is None:
            messagebox.showerror("Can't export yet", "\n\n".join(i.msg for i in (res.errors if res else [])) or
                                 "Fix the highlighted problems first.")
            return
        sp = res.spec
        name = f"{self.style.id}_{fmt(sp.L)}x{fmt(sp.W)}x{fmt(sp.H)}_{sp.units}_blank.3mf"
        path = filedialog.asksaveasfilename(defaultextension=".3mf", initialfile=name,
                                            filetypes=[("3MF model", "*.3mf"), ("STL model", "*.stl")])
        if not path:
            return
        kind = "stl" if path.lower().endswith(".stl") else "3mf"
        try:
            data, m = model_export(res, sp, kind)
            if m.open_edges():
                raise ValueError("the solid model has gaps, so it was not saved")
            with open(path, "wb") as fh:
                fh.write(data)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not save", str(exc))
            return
        note = model_notes(m)
        self.toast.config(text=f"Saved {os.path.basename(path)}" + ("\n" + note[1] if len(note) > 1 else ""),
                          fg=T["good"] if len(note) == 1 else T["warn"])

    def export(self, kind):
        res = self.res
        if res is None or not res.ok or res.drawing is None:
            messagebox.showerror("Can't export yet", "\n\n".join(i.msg for i in (res.errors if res else [])) or
                                 "Fix the highlighted problems first.")
            return
        if res.warnings:
            body = "\n\n".join("• " + w.msg for w in res.warnings)
            if not messagebox.askyesno("Export with notes?",
                                       f"This design has {len(res.warnings)} note(s):\n\n{body}\n\n"
                                       f"They will also be saved inside the file. Export anyway?"):
                return
        sp = res.spec
        gc = None
        if kind == "nc":
            gc = self._gcode_dialog()
            if gc is None:
                return
        name = f"{self.style.id}_{fmt(sp.L)}x{fmt(sp.W)}x{fmt(sp.H)}_{sp.units}.{kind}"
        label = dict(EXPORT_FORMATS)[kind]
        path = filedialog.asksaveasfilename(defaultextension=f".{kind}", initialfile=name,
                                            filetypes=[(label + " file", f"*.{kind}")])
        if not path:
            return
        lk = res.look
        head = (f"BoxForge {self.style.name}: L{fmt(sp.L)} W{fmt(sp.W)} H{fmt(sp.H)} thickness {fmt(sp.t)} "
                f"{sp.units} ({sp.mode} dimensions). Layers: CUT {lk['cut_name'].lower()}, "
                f"FOLD {lk['fold_name'].lower()}."
                + (f" Line weights: cut {lk['cut_pt']:g} pt, fold {lk['fold_pt']:g} pt." if kind in WEIGHT_FORMATS
                   else ""))
        notes = [head] + res.notes()
        try:
            data = render_export(kind, res.drawing, sp.units, notes, gc, lk)
            if isinstance(data, bytes):
                with open(path, "wb") as fh:
                    fh.write(data)
            else:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(data)
        except OSError as exc:
            messagebox.showerror("Could not save", str(exc))
            return
        self.toast.config(text=f"Saved {os.path.basename(path)}" + (f"  ·  with {len(res.warnings)} note(s)"
                                                                      if res.warnings else "")
                          + ("" if kind in WEIGHT_FORMATS else "  ·  line weights not applied to this format"),
                          fg=T["good"])


