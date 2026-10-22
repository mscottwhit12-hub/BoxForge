# =============================================================================
# GUI
# =============================================================================
# =============================================================================
# Theme
# =============================================================================
T = dict(
    bg="#121217", rail="#0c0c10", panel="#1a1a21", panel2="#22222b", card="#1e1e26", card_h="#262633",
    thumb="#15151b", border="#2f2f3b", border_h="#8b5cf6", text="#ececf3", muted="#9a9ab0", dim="#6c6c80",
    accent="#8b5cf6", accent_h="#a07bff", good="#34d399", warn="#fbbf24", err="#f87171", info="#60a5fa",
    cut="#5b8cff", fold="#ff5d5d", canvas="#16161c", grid="#1f1f27",
    body="#67e8f9", body_dim="#1f5560", flap="#c4b5fd", flap_dim="#473a78",
)
FAMILY = "TkDefaultFont"

# =============================================================================
# Screen scaling: fixed pixel sizes (padding, panel widths, drawn coordinates) grow with the screen's DPI
# =============================================================================
SCALE = 1.0                   # 1.0 = a 96 dpi screen; 1.5 = 150 %, ...


def S(v):
    """A pixel size scaled for the screen (numbers, or a pair of them); whole pixels, never below 1 unless 0."""
    if isinstance(v, (tuple, list)):
        return tuple(S(x) for x in v)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or SCALE == 1.0 or v == 0:
        return v
    return max(1, int(round(v * SCALE)))


_PX_ALWAYS = ("padx", "pady", "ipadx", "ipady", "wraplength", "highlightthickness", "bd", "borderwidth", "sashwidth",
              "sashpad", "x", "y")
_PX_SIZED = ("Frame", "Canvas", "Toplevel", "LabelFrame", "PanedWindow", "Scrollbar", "Tk")   # width / height are pixels
_scaled_done = False


def detect_scale(root):
    """The scale for this screen: from the screen's resolution (dots per inch), or BOXFORGE_SCALE if set."""
    env = os.environ.get("BOXFORGE_SCALE")
    if env:
        try:
            return min(3.0, max(1.0, float(env)))
        except ValueError:
            pass
    if sys.platform == "darwin":                       # Tk on a Mac already works in points
        return 1.0
    try:
        sc = root.winfo_fpixels("1i") / 96.0
    except Exception:                                  # noqa: BLE001
        return 1.0
    return min(3.0, max(1.0, round(sc * 4) / 4.0)) if sc >= 1.2 else 1.0


def init_scale(root):
    """Set SCALE for this screen and, when it is above 100 %, make Tk apply it to every pixel size given as a widget
    option or to a geometry manager (pack / grid / place). Drawn coordinates and window sizes call S() themselves."""
    global SCALE, _scaled_done
    SCALE = detect_scale(root)
    if SCALE == 1.0 or _scaled_done:
        return SCALE
    _scaled_done = True
    try:
        root.tk.call("tk", "scaling", SCALE * 96.0 / 72.0)      # fonts are in points: they follow this
    except tk.TclError:
        pass

    def fix(cls_name, kw):
        for k in list(kw):
            if k in _PX_ALWAYS or (k in ("width", "height") and cls_name in _PX_SIZED):
                kw[k] = S(kw[k])
        return kw
    orig_init = tk.Widget.__init__

    def widget_init(self, master, widgetName, cnf={}, kw={}, extra=()):
        name = type(self).__name__
        base = next((c.__name__ for c in type(self).__mro__ if c.__module__ == "tkinter"), name)
        orig_init(self, master, widgetName, fix(base, dict(cnf)), fix(base, dict(kw)), extra)
    tk.Widget.__init__ = widget_init
    for cls, names in ((tk.Pack, ("pack", "pack_configure")), (tk.Grid, ("grid", "grid_configure")),
                       (tk.Place, ("place", "place_configure"))):
        for nm in names:
            f = getattr(cls, nm)

            def wrap(self, cnf={}, f=f, **kw):
                for k in ("padx", "pady", "ipadx", "ipady", "x", "y", "width", "height", "bordermode"):
                    if k in kw and k != "bordermode":
                        kw[k] = S(kw[k])
                    if k in cnf:
                        cnf = dict(cnf, **{k: S(cnf[k])})
                return f(self, cnf, **kw)
            setattr(cls, nm, wrap)
    return SCALE


def init_fonts(root):
    global FAMILY
    try:
        fams = set(tkfont.families(root))
    except Exception:
        fams = set()
    for f in ("Segoe UI", "SF Pro Text", "Helvetica Neue", "Inter", "Ubuntu", "DejaVu Sans", "Helvetica", "Arial"):
        if f in fams:
            FAMILY = f
            return


def F(size=10, weight="normal"):
    return (FAMILY, size, weight)


def _rgb(h):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def mix(c1, c2, t):
    a, b = _rgb(c1), _rgb(c2)
    t = max(0.0, min(1.0, t))
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _decomma(t):
    """'1,234.5' and '1,234,567' lose their thousands separators; a lone comma is a decimal point, so '1,5' is 1.5 and
    '3,125' is 3.125 (not 3125: a size typed with a decimal comma is far more likely than one in thousands)."""
    def fix(m):
        if m.group(1).count(",") > 1 or m.group(2):
            return m.group(1).replace(",", "") + (m.group(2) or "")
        return m.group(0)
    t = _re.sub(r"(?<![\d.,])([1-9]\d{0,2}(?:,\d{3})+)(\.\d+)?(?![\d,])", fix, t)
    return t.replace(",", ".")


def parse_num(s):
    """'12', '12.5', '1/2', '1 1/2', '1,234.5' -> float; blank -> None; anything else (including nan/inf) raises ValueError."""
    s = _decomma((s or "").strip())
    if not s:
        return None
    try:
        v = float(s)
        if not math.isfinite(v):
            raise ValueError(s)
        return v
    except ValueError:
        pass
    try:
        if "/" in s:
            parts = s.split()
            whole = float(parts[0]) if len(parts) == 2 else 0.0
            n, d = parts[-1].split("/")
            frac = float(n) / float(d)
            if len(parts) == 2 and (parts[-1].startswith("-") or parts[-1].startswith("+")):
                raise ValueError(s)                       # '2 -3/4' is not a mixed number
            v = whole - frac if (len(parts) == 2 and parts[0].startswith("-")) else whole + frac
            if math.isfinite(v):
                return v
    except (ValueError, ZeroDivisionError):
        pass
    raise ValueError(s)


_CALC_UNITS = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "inch": 25.4, "inches": 25.4, "\"": 25.4,
               "ft": 304.8, "feet": 304.8, "'": 304.8}
_CALC_WORDS = (("divided by", "/"), ("multiplied by", "*"), ("times", "*"), ("minus", "-"), ("plus", "+"),
               ("over", "/"), ("less", "-"), ("add", "+"), ("\u00d7", "*"), ("\u00f7", "/"), ("\u2212", "-"))
_CALC_TOKEN = _re.compile(r"\s*(?:(\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+)|([A-Za-z\"']+)|(.))")


def calc_eval(text, cur, unit="mm"):
    """Small calculator for the input boxes. + - * / ( ), numbers with an optional length unit (mm cm m in ft),
    and `cur` / `current` for the box's present value. A leading operator works on the present value:
    '-2 in', '*2.5', '/2'. Numbers without a unit are in `unit` ('mm', 'in' or None = no units allowed).
    Returns a float; raises ValueError with a short reason."""
    t = _decomma((text or "").strip().lower())
    for w, sym in _CALC_WORDS:
        t = t.replace(w, f" {sym} ")
    if not t:
        raise ValueError("empty")
    if t[0] in "+-*/" and cur is not None:
        t = "cur " + t
    toks, pos = [], 0
    while pos < len(t):
        m = _CALC_TOKEN.match(t, pos)
        if not m or m.end() == pos:
            break
        pos = m.end()
        num, word, sym = m.groups()
        if num is not None:
            toks.append(("n", float(num)))
        elif word is not None:
            toks.append(("w", word))
        elif sym.strip():
            toks.append(("o", sym))
    k = {"mm": 1.0, "in": 25.4}.get(unit)
    i = 0

    def peek():
        return toks[i] if i < len(toks) else (None, None)

    def atom():
        """Returns (value, unit factor or None). A number with a unit is returned unconverted; term() applies the
        unit to the whole product/quotient, so '10/4 in' and '10 in / 4' agree."""
        nonlocal i
        kind, v = peek()
        if kind == "n":
            i += 1
            k2, w = peek()
            if (k2 == "w" and w in _CALC_UNITS) or (k2 == "o" and w in ("\"", "'")):
                i += 1
                if k is None:
                    raise ValueError("units are not used in this box")
                return v, _CALC_UNITS[w] / k
            return v, None
        if kind == "w" and v in ("cur", "current", "now"):
            i += 1
            if cur is None:
                raise ValueError("there is no current value")
            return cur, 1.0
        if kind == "o" and v == "(":
            i += 1
            x = expr()
            if peek() != ("o", ")"):
                raise ValueError("missing )")
            i += 1
            return x, None
        raise ValueError("can't read " + (repr(v) if v is not None else "the end of that"))

    def factor():
        nonlocal i
        kind, v = peek()
        if kind == "o" and v in "+-":
            i += 1
            x, u = factor()
            return (-x if v == "-" else x), u
        return atom()

    def term():
        nonlocal i
        x, uc = factor()
        while peek()[0] == "o" and peek()[1] in "*/":
            op = toks[i][1]
            i += 1
            y, yc = factor()
            if op == "/":
                if y == 0:
                    raise ValueError("divide by zero")
                x /= y
                if yc is not None:
                    if uc is None:
                        uc = yc                    # '10/4 in': the unit belongs to the whole term
                    else:
                        x *= uc / yc               # length / length is a plain ratio
                        uc = None
            else:
                x *= y
                if yc is not None:
                    if uc is not None:
                        raise ValueError("can't multiply two lengths; use a plain number")
                    uc = yc
        return x * uc if uc is not None else x

    def expr():
        nonlocal i
        x = term()
        while peek()[0] == "o" and peek()[1] in "+-":
            op = toks[i][1]
            i += 1
            y = term()
            x = x + y if op == "+" else x - y
        return x

    x = expr()
    if i != len(toks):
        raise ValueError("can't read " + repr(toks[i][1]))
    if not math.isfinite(x):
        raise ValueError("not a finite number")
    return x


def is_plain_number(text):
    """True when parse_num already understands the text (12, 12.5, 1/2, 1 1/2) and it is not a relative edit."""
    t = (text or "").strip()
    if t[:1] in ("+", "-", "*", "/"):
        return False
    try:
        parse_num(t)
        return True
    except ValueError:
        return False


# =============================================================================
# Small widgets
# =============================================================================
class Btn(tk.Label):
    KINDS = {"primary": ("accent", "accent_h", "#ffffff"), "ghost": ("panel2", "border", "text"),
             "flat": ("panel", "panel2", "text")}

    def __init__(self, master, text, command=None, kind="ghost", size=10, padx=14, pady=8, bold=False, **kw):
        self.kind, self.command, self.enabled = kind, command, True
        bg, hov, fg = self.KINDS[kind]
        super().__init__(master, text=text, font=F(size, "bold" if bold or kind == "primary" else "normal"),
                         bg=T[bg], fg=fg if fg.startswith("#") else T[fg], padx=padx, pady=pady,
                         cursor="hand2", **kw)
        self.bind("<Enter>", lambda e=None: self._paint(True))
        self.bind("<Leave>", lambda e=None: self._paint(False))
        self.bind("<Button-1>", self._click)

    def _paint(self, hover):
        bg, hov, fg = self.KINDS[self.kind]
        if not self.enabled:
            self.config(bg=T["panel2"], fg=T["dim"], cursor="arrow")
            return
        self.config(bg=T[hov] if hover else T[bg], fg=fg if fg.startswith("#") else T[fg], cursor="hand2")

    def _click(self, e):
        if self.command and self.enabled:
            self.command()

    def set_enabled(self, on):
        self.enabled = on
        self._paint(False)


class Seg(tk.Frame):
    def __init__(self, master, options, var, size=9, bg=None):
        super().__init__(master, bg=T["panel2"], highlightthickness=1, highlightbackground=T["border"])
        self.var, self.labels = var, {}
        for val, text in options:
            lb = tk.Label(self, text=text, font=F(size), padx=11, pady=5, cursor="hand2")
            lb.pack(side="left")
            lb.bind("<Button-1>", lambda e, v=val: self.var.set(v))
            self.labels[val] = lb
        self.var.trace_add("write", lambda *a: self._paint())
        self._paint()

    def _paint(self):
        for v, lb in self.labels.items():
            on = self.var.get() == v
            lb.config(bg=T["accent"] if on else T["panel2"], fg="#ffffff" if on else T["muted"],
                      font=F(9, "bold" if on else "normal"))


class Switch(tk.Frame):
    def __init__(self, master, text, var):
        super().__init__(master, bg=T["panel"])
        self.var = var
        self.enabled = True
        self.cv = tk.Canvas(self, width=34, height=18, bg=T["panel"], highlightthickness=0, cursor="hand2")   # scaled by init_scale
        self.cv.pack(side="left")
        self.lb = tk.Label(self, text=text, font=F(9), bg=T["panel"], fg=T["text"], cursor="hand2")
        self.lb.pack(side="left", padx=(8, 0))
        for w in (self.cv, self.lb):
            w.bind("<Button-1>", lambda e: self.var.set(not self.var.get()) if self.enabled else None)
        self._tid = self.var.trace_add("write", lambda *a: self._paint())
        self.bind("<Destroy>", self._gone)
        self._paint()

    def _gone(self, e):
        if e.widget is self:
            try:
                self.var.trace_remove("write", self._tid)
            except (tk.TclError, ValueError):
                pass

    def set_enabled(self, enabled):
        """Grey the switch out (it keeps its value but cannot be clicked)."""
        self.enabled = bool(enabled)
        self.lb.config(fg=T["text"] if enabled else T["dim"], cursor="hand2" if enabled else "arrow")
        self.cv.config(cursor="hand2" if enabled else "arrow")
        self._paint()

    def _paint(self):
        on = self.var.get()
        c = self.cv
        c.delete("all")
        col = T["accent"] if (on and self.enabled) else T["border"]
        c.create_oval(1, 1, 17, 17, fill=col, outline=col)
        c.create_oval(17, 1, 33, 17, fill=col, outline=col)
        c.create_rectangle(9, 1, 25, 17, fill=col, outline=col)
        x = 25 if on else 9
        c.create_oval(x - 6, 3, x + 6, 15, fill="#ffffff", outline="#ffffff")
        if SCALE != 1.0:
            c.scale("all", 0, 0, SCALE, SCALE)


def make_paned(parent, orient):
    """A split container whose divider the user can drag. Panes keep a minimum size, so none can be closed up, and
    they cannot be pulled out into a window of their own (a PanedWindow has no such feature)."""
    return tk.PanedWindow(parent, orient=orient, sashwidth=7, sashrelief="flat", bg=T["border"], bd=0,
                          opaqueresize=True, showhandle=False,
                          sashcursor="sb_h_double_arrow" if orient == "horizontal" else "sb_v_double_arrow")


class ScrollFrame(tk.Frame):
    def __init__(self, master, bg, height=None, bar=False):
        super().__init__(master, bg=bg)
        self.cv = tk.Canvas(self, bg=bg, highlightthickness=0, **({"height": height} if height else {}))
        if bar:      # slim draggable scroll indicator
            self.bar = tk.Canvas(self, width=8, bg=bg, highlightthickness=0, cursor="hand2")   # scaled by init_scale
            self.bar.pack(side="right", fill="y")
            self.cv.configure(yscrollcommand=self._on_scroll)
            self.bar.bind("<Button-1>", self._bar_drag)
            self.bar.bind("<B1-Motion>", self._bar_drag)
        self.cv.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.cv, bg=bg)
        self.win = self.cv.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.cv.configure(scrollregion=self.cv.bbox("all")))
        self.cv.bind("<Configure>", lambda e: self.cv.itemconfigure(self.win, width=e.width))
        self.bind("<Enter>", lambda e: self._wheel_bind(True))
        self.bind("<Leave>", lambda e: self._wheel_bind(False))

    def _on_scroll(self, lo, hi):
        self.bar.delete("all")
        lo, hi = float(lo), float(hi)
        if hi - lo < 0.999:
            h = max(self.bar.winfo_height(), 1)
            self.bar.create_rectangle(1, lo * h + 1, S(7), hi * h - 1, fill=T["dim"], outline="")

    def _bar_drag(self, e):
        h = max(self.bar.winfo_height(), 1)
        lo, hi = self.cv.yview()
        self.cv.yview_moveto(max(0.0, min(1.0, e.y / h - (hi - lo) / 2)))

    def reveal(self, widget):
        """Scroll so `widget` is fully visible (used when a control appears below the fold)."""
        self.update_idletasks()
        total = max(self.inner.winfo_height(), 1)
        top = widget.winfo_rooty() - self.inner.winfo_rooty()
        bot = top + widget.winfo_height()
        lo, hi = self.cv.yview()
        view = self.cv.winfo_height()
        if bot > hi * total:
            self.cv.yview_moveto(max(0.0, min(1.0, (bot - view) / total)))
        elif top < lo * total:
            self.cv.yview_moveto(max(0.0, top / total))

    def _wheel_bind(self, on):
        if on:
            self.cv.bind_all("<MouseWheel>", self._wheel)
            self.cv.bind_all("<Button-4>", lambda e: self.cv.yview_scroll(-2, "units"))
            self.cv.bind_all("<Button-5>", lambda e: self.cv.yview_scroll(2, "units"))
        else:
            for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.cv.unbind_all(ev)

    def _wheel(self, e):
        if self.inner.winfo_height() > self.cv.winfo_height():
            self.cv.yview_scroll(int(-e.delta / 60) or (-1 if e.delta > 0 else 1), "units")


class SwatchPicker(tk.Canvas):
    """One colour swatch with a drop-down arrow. Click it and a small popup of the preset line colours opens; click a
    colour to set `var` to its name (the popup closes), or click anywhere else / press Esc to close it unchanged."""

    def __init__(self, master, var, bg, cols=4, size=28, gap=6):
        self.sw = S(24)
        super().__init__(master, width=self.sw + S(22), height=self.sw + S(4), bg=bg, highlightthickness=0, cursor="hand2")
        self.var, self.cols, self.size, self.gap, self.pop = var, cols, S(size), S(gap), None
        self.bind("<Button-1>", self._toggle)
        self.bind("<Destroy>", lambda e: self._close() if e.widget is self else None)
        self._trace = var.trace_add("write", lambda *a: self.draw())
        self.draw()

    def _hex(self, name=None):
        name = self.var.get() if name is None else name
        return next((h for n, h, _ in LINE_COLORS if n == name), "#888888")

    def draw(self):
        try:
            self.delete("all")
        except tk.TclError:
            return
        self.create_rectangle(2, 2, 2 + self.sw, 2 + self.sw, fill=self._hex(), outline=T["border"], width=1)
        x, y = 2 + self.sw + S(10), 2 + self.sw / 2
        self.create_polygon(x - S(5), y - S(2), x + S(5), y - S(2), x, y + S(4), fill=T["muted"], outline="")

    def _cell(self, i):
        r, c = divmod(i, self.cols)
        return S(8) + c * (self.size + self.gap), S(8) + r * (self.size + self.gap)

    def _toggle(self, e=None):
        if self.pop is not None:
            self._close()
        else:
            self._open()

    def _open(self):
        rows = -(-len(LINE_COLORS) // self.cols)
        w = self.cols * (self.size + self.gap) - self.gap + S(16)
        h = rows * (self.size + self.gap) - self.gap + S(16) + S(22)
        pop = self.pop = tk.Toplevel(self, bg=T["border"])
        pop.overrideredirect(True)
        x, y = self.winfo_rootx(), self.winfo_rooty() + self.winfo_height() + 2
        x = max(0, min(x, self.winfo_screenwidth() - w - 2))
        if y + h > self.winfo_screenheight():                       # no room below: open above the swatch
            y = max(0, self.winfo_rooty() - h - 2)
        pop.geometry(f"{w}x{h}+{x}+{y}")
        inner = tk.Canvas(pop, width=w - 2, height=h - 2, bg=T["panel2"], highlightthickness=0, cursor="hand2")
        inner.place(x=1, y=1)
        self._cv, self._name_id = inner, None

        def paint(hover=None):
            inner.delete("all")
            cur = self.var.get()
            for i, (name, hx, _a) in enumerate(LINE_COLORS):
                cx, cy = self._cell(i)
                sel = name == cur
                inner.create_rectangle(cx, cy, cx + self.size, cy + self.size, fill=hx, width=3 if sel else 1,
                                       outline=T["text"] if sel else T["border"])
            inner.create_text(S(8), h - S(17), text=hover or cur, anchor="w", font=F(8), fill=T["muted"])

        def at(ev):
            for i, (name, _h, _a) in enumerate(LINE_COLORS):
                cx, cy = self._cell(i)
                if cx <= ev.x <= cx + self.size and cy <= ev.y <= cy + self.size:
                    return name
            return None

        def pick(ev):
            name = at(ev)
            if name:
                self.var.set(name)
                self._close()

        def move(ev):
            paint(at(ev))
        inner.bind("<Button-1>", pick)
        inner.bind("<Motion>", move)
        inner.bind("<Leave>", lambda ev: paint())
        paint()
        pop.bind("<Escape>", lambda ev: self._close())
        pop.bind("<Button-1>", lambda ev: self._close() if ev.widget is pop else None)   # a click outside the popup
        try:
            pop.update_idletasks()
            pop.wait_visibility()
            pop.grab_set()
            pop.focus_force()
        except tk.TclError:
            pass

    def _close(self):
        pop, self.pop = self.pop, None
        if pop is not None:
            try:
                pop.grab_release()
            except tk.TclError:
                pass
            try:
                pop.destroy()
            except tk.TclError:
                pass


class Slider(tk.Canvas):
    """Flat 0-100 slider bound to a DoubleVar."""

    def __init__(self, master, var, command, lo=0.0, hi=100.0, step=None):
        super().__init__(master, height=24, bg=T["panel"], highlightthickness=0, cursor="hand2")   # scaled by init_scale
        self.var, self.command, self.lo, self.hi, self.step = var, command, lo, hi, step
        self.bind("<Configure>", lambda e: self._paint())
        self.bind("<Button-1>", self._set)
        self.bind("<B1-Motion>", self._set)
        self.var.trace_add("write", lambda *a: self._paint())

    def _set(self, e):
        pad, w = S(12), max(self.winfo_width(), 40)
        v = self.lo + (self.hi - self.lo) * max(0.0, min(1.0, (e.x - pad) / (w - 2 * pad)))
        if self.step:
            v = round(v / self.step) * self.step
        self.var.set(round(max(self.lo, min(self.hi, v)), 6))
        self.command()

    def _paint(self):
        self.delete("all")
        pad, w, h = S(12), max(self.winfo_width(), 40), S(24)
        x = pad + (w - 2 * pad) * (self.var.get() - self.lo) / (self.hi - self.lo)
        self.create_line(pad, h / 2, w - pad, h / 2, fill=T["border"], width=S(4), capstyle="round")
        self.create_line(pad, h / 2, x, h / 2, fill=T["accent"], width=S(4), capstyle="round")
        r = S(8)
        self.create_oval(x - r, h / 2 - r, x + r, h / 2 + r, fill="#ffffff", outline=T["accent"], width=S(2))


def chip(master, text, color, bg=None):
    return tk.Label(master, text=text, font=F(8, "bold"), fg=color, bg=bg or T["card"], padx=7, pady=2,
                    highlightthickness=1, highlightbackground=mix(color, bg or T["card"], 0.62))


STATUS_CHIP = {"calibrated": ("CALIBRATED", "good"), "standard": ("STANDARD", "info"),
               "experimental": ("EXPERIMENTAL", "warn")}


