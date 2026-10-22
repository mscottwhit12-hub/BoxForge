# =============================================================================
# Style: Slot-fit test - a small sheet of slotted plates to find the slot width that suits the board
# =============================================================================
# Board thickness varies and so does the cut width of a laser, so the right slot width for a half-lap joint is found by
# trying it. The sheet holds a plain key plate (the board edge to push in) and N plates whose slots grow in steps from
# exactly the board thickness. The number of small notches along the bottom edge of a plate says which slot it is.
# The slot that lets the key slide in with a light push and no wobble is the one to use as the "Slot width" option.
FIT_MAX = 12


def fit_widths(t, step, n):
    return [t + i * step for i in range(n)]


def _fit_outline(x0, y0, L, H, slot, d, notches, nt):
    """A plate L x H at (x0, y0): slot of width `slot` and depth `d` cut down from the top at the middle, and `notches`
    small square notches (side nt) along the bottom edge."""
    pts = [(x0, y0)]
    if notches:
        gap = (L - 2 * nt * notches) / (notches + 1)
        x = x0
        for _ in range(notches):
            x += gap
            pts += [(x, y0), (x, y0 + nt), (x + nt, y0 + nt), (x + nt, y0)]
            x += nt
        # (the notch width is nt; the spacing above keeps two notch widths per notch so they stay well apart)
    pts += [(x0 + L, y0), (x0 + L, y0 + H)]
    if slot:
        cx = x0 + L / 2.0
        pts += [(cx + slot / 2, y0 + H), (cx + slot / 2, y0 + H - d), (cx - slot / 2, y0 + H - d), (cx - slot / 2, y0 + H)]
    pts.append((x0, y0 + H))
    return pts


class FitTest(Style):
    zero_ok = ("step",)
    flat_parts = True
    auto_tol = {"slot": 0.02}                  # half-lap slots are cut to the board, not die-cut flap slots
    id, name = "fit", "Slot-fit test"
    code = "Test coupon"
    blurb = ("A small sheet of slotted plates whose slots grow in steps from the board thickness, plus a key plate to "
             "push in: cut it on your board, find the slot that fits, and use that width in the dividers and inserts.")
    status = "experimental"
    defaults = dict(L=30.0, W=30.0, H=15.0, t=3.0)
    options = [("count", "Number of slots"), ("step", "Slot width step")]
    count_keys = ("count",)
    height_label = "Slot depth"
    ratio_dims = ("L", "W")                    # the generic "smallest dimension" check applies to the plates only
    view_up = "y"
    mode_help = {k: "Sizes as typed: plate width (length), plate height (width) and slot depth (height)."
                 for k in ("inner", "outer", "manufacturer")}

    def crease(self, L, W, H, t, mode):
        return L, W, H

    def inner(self, Lc, Wc, Hc, t):
        return Lc, Wc, Hc

    def resolve(self, c):
        t = c.t
        step = _auto(c, "step", max(c.mm_(0.1), 0.02 * t))
        n = c.o.get("count")
        n = 6 if n is None else (int(round(n)) if abs(n - round(n)) < 1e-9 else n)
        return dict(step=step, n=n, pw=c.Lc, ph=c.Wc, d=c.Hc, nt=max(c.mm_(1.5), 0.5 * t))

    def check(self, c, r, iss):
        t = c.t
        if not isinstance(r["n"], int) or not 2 <= r["n"] <= FIT_MAX:
            iss.append(Issue("error", f"The number of slots must be a whole number from 2 to {FIT_MAX}.", ("count",)))
            return
        if r["step"] <= 0:
            iss.append(Issue("error", "The slot width step must be above zero.", ("step",)))
            return
        if r["pw"] < 8 * t or r["ph"] < r["d"] + 2 * t:
            iss.append(Issue("error", "The plates are too small: make them at least 8 boards wide and 2 boards taller "
                                      "than the slot is deep.", ("L", "W", "H", "t")))
            return
        if r["d"] < t:
            iss.append(Issue("error", "The slot depth must be at least one board.", ("H", "t")))
            return
        need = 2 * r["nt"] * r["n"] + r["nt"] * (r["n"] + 1)
        if need > r["pw"]:
            iss.append(Issue("error", "The plates are too narrow for the number of marking notches.", ("L", "count")))
        if r["n"] * r["step"] > t:
            iss.append(Issue("info", "The widest slot is more than a board wider than the board.", ("count", "step")))

    PER_ROW = 4

    def build(self, c, r):
        t, pw, ph, d, n = c.t, r["pw"], r["ph"], r["d"], r["n"]
        gap = max(c.mm_(5), 2 * t)
        out = []
        items = [("key", 0.0, 0)] + [(f"s{i + 1}", w, i + 1) for i, w in enumerate(fit_widths(t, r["step"], n))]
        for k, (nm, w, notches) in enumerate(items):
            row, col = divmod(k, self.PER_ROW)
            x, y = col * (pw + gap), -row * (ph + gap)
            if nm == "key":                        # the plain plate to push in: as tall as a slot is deep, plus a handle
                pts = [(x, y), (x + pw, y), (x + pw, y + ph), (x, y + ph)]
            else:
                pts = _fit_outline(x, y, pw, ph, w, d, notches, r["nt"])
            out.append(Panel(nm, pts, None, None, 90.0, "body"))
        return out, None

    rounded_folds = False
    tol_keys = ("panel", "slot", "overall_len", "overall_h")
    draw_sub = "Slot-fit test coupon"
    draw_cap = "SLOT TEST"
    anchor_panel = None
    step_text = {"flat": "As cut: the key plate and the numbered plates, flat.",
                 "partial": "As cut: the key plate and the numbered plates, flat.",
                 "folded": "As cut: the key plate and the numbered plates, flat."}
    step_amount = 0.5
    view_title = "TEST PLATES (NOT TO SCALE)"
    table_title = "TEST SIZES"
    steps_note = "(not to scale; board drawn at full thickness)"

    def view_caption(self, res, units):
        a = res.info["auto"]
        t = res.spec.t
        return f"{a['n']} slots, {_fnum(t, units)} to {_fnum(t + (a['n'] - 1) * a['step'], units)} {units} wide"

    def bend_notes(self, rep):
        return ["The test plates are flat: there are no folds, so this page does not change the dieline."]

    def tol_note(self, f, units):
        return f"Tolerances (± {units}): plates {f('panel')}; slots {f('slot')}; blank {f('overall_len')} x {f('overall_h')}."

    def dim_field(self, dm, res, spec):
        tag = dm.get("tag", "")
        if tag.startswith("plate"):
            return "L", None
        if tag == "height":
            return "W", None
        return None

    def dimensions(self, res, spec):
        pans = list(res.panels)
        tv = res.info["tol"]["values"]
        bb = {p.name: _bbox(p) for p in pans}
        top = max(b[3] for b in bb.values())
        first = sorted((b for b in bb.values() if abs(b[3] - top) < 1e-6), key=lambda b: b[0])
        out = [dict(kind="h", row=1, a=b[0], b=b[2], v=b[2] - b[0], tol=tv["panel"], ref=top, tag="plate%d" % i)
               for i, b in enumerate(first[:2])]
        xl, xr = min(b[0] for b in bb.values()), max(b[2] for b in bb.values())
        out.append(dict(kind="h", row=2, a=xl, b=xr, v=xr - xl, tol=tv["overall_len"], ref=top, tag="overall_len"))
        f = first[0]
        out.append(dict(kind="v", row=1, a=f[1], b=f[3], v=f[3] - f[1], tol=tv["overall_h"], ref=xr, tag="height"))
        return out

    def size_rows(self, c):
        a, u = c.a, c.units
        ws = fit_widths(c.t, a["step"], a["n"])
        return [("Plate L × H", f"{_fnum(a['pw'], u)} × {_fnum(a['ph'], u)}"),
                ("Slot depth", c.fnum(a["d"], u)), c.flat, ("Board thickness", c.fnum(c.t, u)),
                ("Slot widths", f"{_fnum(ws[0], u)} to {_fnum(ws[-1], u)}, step {_fnum(a['step'], u)}"),
                ("Number of slots", str(a["n"])), ("Units", u)]

    def drawing_notes(self, res, units):
        a = res.info["auto"]
        return ["Push the edge of the key plate into each numbered slot. The number of notches on a plate's bottom edge "
                "is its slot number (1 = the narrowest).",
                "Use the narrowest slot the key slides into with a light push and no rattle as the 'Slot width' option of "
                "the dividers and inserts. Test on the board you will really cut: laser kerf and board thickness vary."]

    def fold_sequence(self, panels, t, amount):
        return (lambda p, d, m: 0.0), None, None


register_style(FitTest())
