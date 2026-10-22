# =============================================================================
# Style: Lid & Base (telescope box)
# =============================================================================
def tray_panels(Lc, Wc, Hc, fw, rf, ox=0.0, oy=0.0, pre=""):
    """Open tray: bottom + 4 walls + 4 corner flaps hinged on the front/back walls."""
    def X(x): return x + ox
    def Y(y): return y + oy
    n = lambda s: pre + s
    P = [Panel(n("bottom"), rect_verts(X(0), Y(0), X(Lc), Y(Wc)))]
    P.append(Panel(n("front"), rect_verts(X(0), Y(-Hc), X(Lc), Y(0)), n("bottom"), ((X(0), Y(0)), (X(Lc), Y(0)))))
    P.append(Panel(n("back"), rect_verts(X(0), Y(Wc), X(Lc), Y(Wc + Hc)), n("bottom"),
                   ((X(0), Y(Wc)), (X(Lc), Y(Wc)))))
    P.append(Panel(n("left"), rect_verts(X(-Hc), Y(0), X(0), Y(Wc)), n("bottom"), ((X(0), Y(0)), (X(0), Y(Wc)))))
    P.append(Panel(n("right"), rect_verts(X(Lc), Y(0), X(Lc + Hc), Y(Wc)), n("bottom"),
                   ((X(Lc), Y(0)), (X(Lc), Y(Wc)))))
    if fw > 0:
        P.append(Panel(n("cfl"), [(X(0), Y(-Hc), 0), (X(0), Y(0), 0), (X(-fw), Y(0), 0), (X(-fw), Y(-Hc), rf)],
                       n("front"), ((X(0), Y(-Hc)), (X(0), Y(0))), 90, "flap"))
        P.append(Panel(n("cfr"), [(X(Lc), Y(-Hc), 0), (X(Lc + fw), Y(-Hc), rf), (X(Lc + fw), Y(0), 0), (X(Lc), Y(0), 0)],
                       n("front"), ((X(Lc), Y(-Hc)), (X(Lc), Y(0))), 90, "flap"))
        P.append(Panel(n("cbl"), [(X(0), Y(Wc), 0), (X(0), Y(Wc + Hc), 0), (X(-fw), Y(Wc + Hc), rf), (X(-fw), Y(Wc), 0)],
                       n("back"), ((X(0), Y(Wc)), (X(0), Y(Wc + Hc))), 90, "flap"))
        P.append(Panel(n("cbr"), [(X(Lc), Y(Wc), 0), (X(Lc + fw), Y(Wc), 0), (X(Lc + fw), Y(Wc + Hc), rf),
                                  (X(Lc), Y(Wc + Hc), 0)],
                       n("back"), ((X(Lc), Y(Wc)), (X(Lc), Y(Wc + Hc))), 90, "flap"))
    return P


class Telescope(Style):
    id, name = "telescope", "Lid & Base"
    code = "FEFCO 0301 style"
    blurb = "Two-piece telescope box: a tray base and a slightly larger tray lid that slides over it. One sheet, two trays."
    status = "standard"
    view_up = "z"
    defaults = dict(L=150.0, W=100.0, H=60.0, t=2.0)
    options = [("lidh", "Lid depth (outside)"), ("clr", "Lid clearance"), ("flap", "Corner flap width")]
    height_label = "Base height"
    zero_ok = ("clr", "flap")                  # a press-fit lid and a tray without corner flaps are both allowed
    mode_help = {
        "inner": "Inside of the BASE tray (the lid is sized from it).",
        "outer": "Outside of the BASE tray.",
        "manufacturer": "Centre-of-crease sizes of the BASE tray.",
    }

    # The left / right walls stand one board outside the base sheet plane (see telescope_sequence), so the base is 2t
    # longer outside than its crease length. Corner flaps lie inside those walls, so with flaps the clear length
    # BETWEEN the flaps is 2t shorter than the crease length. W has neither effect.
    def crease(self, L, W, H, t, mode, flaps=True):
        return {"inner": (L + (2 * t if flaps else 0.0), W + t, H + t / 2), "outer": (L - 2 * t, W - t, H - t / 2),
                "manufacturer": (L, W, H)}[mode]

    def inner(self, Lc, Wc, Hc, t, flaps=True):
        return Lc - (2 * t if flaps else 0.0), Wc - t, Hc - t / 2

    @staticmethod
    def _flaps(spec):
        return spec.opts.get("flap") != 0

    def crease_for(self, spec):
        return self.crease(spec.L, spec.W, spec.H, spec.t, spec.mode, self._flaps(spec))

    def inner_for(self, spec, Lc, Wc, Hc):
        return self.inner(Lc, Wc, Hc, spec.t, self._flaps(spec))

    def resolve(self, c):
        t, Hc = c.t, c.Hc
        clr = _auto(c, "clr", max(c.mm_(0.6), 0.25 * t))
        lidh = _auto(c, "lidh", max(3 * t, 0.4 * Hc))
        return dict(clr=clr, lidh=lidh, flap=_auto(c, "flap", min(max(c.t, Hc - c.t), 0.45 * c.Wc)),
                    Llc=c.Lc + 4 * t + clr, Wlc=c.Wc + 2 * t + clr, Hlc=lidh - t / 2)

    def check(self, c, r, iss):
        t = c.t
        if r["clr"] < 0:
            iss.append(Issue("error", "Lid clearance cannot be negative.", ("clr",)))
        elif r["clr"] < c.mm_(0.3):
            iss.append(Issue("warn", "Lid clearance under 0.3 mm is tighter than most laser / die cutting can hold; "
                                     "the lid may not go on.", ("clr",)))
        elif r["clr"] > 2 * t:
            iss.append(Issue("warn", "Lid clearance is more than 2× the board thickness; the lid will be loose.",
                             ("clr", "t")))
        if r["lidh"] < 2.5 * t:
            iss.append(Issue("error", f"Lid depth must be at least 2.5× the board thickness ({fmt(2.5 * t)}).",
                             ("lidh", "t")))
        elif r["lidh"] > c.Hc:
            iss.append(Issue("warn", "Lid is deeper than the base; it will bottom out on the table before closing.",
                             ("lidh", "H")))
        elif r["lidh"] < c.Hc / 4:
            iss.append(Issue("warn", "Shallow lid (<¼ of the base height): little overlap, so it may slip off.",
                             ("lidh",)))
        fw = r["flap"]
        if 2 * fw > c.Wc:
            iss.append(Issue("warn", "Base corner flaps overlap each other. Make them narrower.", ("flap", "W")))

    def build(self, c, r):
        t = c.t
        rf = min(0.25 * c.Hc, 4 * t)
        base = tray_panels(c.Lc, c.Wc, c.Hc, r["flap"], rf, 0, 0, "b_")
        gap = max(c.mm_(8), 2 * t)
        ox = c.Lc + c.Hc + gap + r["Hlc"]
        oy = (c.Wc - r["Wlc"]) / 2
        fwl = min(r["flap"] * 0.9 + t, r["Hlc"])
        lid = tray_panels(r["Llc"], r["Wlc"], r["Hlc"], fwl, min(0.25 * r["Hlc"], 4 * t), ox, oy, "l_")
        return base + lid, None

    rounded_folds = True
    draw_sub = "Telescope lid and base  ·  FEFCO 0301 style"
    draw_cap = "LID AND BASE"
    step_text = {"flat": "As cut: base and lid trays with their corner flaps open.",
                 "partial": "Corner flaps folded in first, walls half way up.",
                 "folded": "Both trays folded; the lid slides over the base."}
    step_amount = 0.62

    def dimensions(self, res, spec):
        return telescope_dimensions(res, spec)

    def dim_field(self, dm, res, spec):
        tag, kind, au = dm.get("tag", ""), dm.get("kind"), res.info.get("auto", {})
        if tag == "b_bottom" and kind == "h":
            return "L", None
        if tag in ("b_left", "b_right") and kind == "h":
            return "H", None
        if tag == "b_flap" and "flap" in au:
            return "flap", dm["v"]
        if (tag in ("l_left", "l_right") and kind == "h") or (tag in ("l_front", "l_back") and kind == "v"):
            return ("lidh", au["lidh"]) if "lidh" in au else None
        if tag == "l_bottom" and "clr" in au:
            return "clr", au["clr"]
        return None

    def size_rows(self, c):
        a, t = c.a, c.t
        return [("Base inside L × W × H", c.tri(c.Li, c.Wi, c.Hi) + c.tol("box")),
                ("Base outside L × W × H", c.tri(c.Lc + 2 * t, c.Wc + t, c.Hc + t / 2) + c.tol("box")),
                ("Lid crease L × W × H", c.tri(a["Llc"], a["Wlc"], a["Hlc"])), c.flat,
                ("Board thickness", c.fnum(t, c.units)),
                ("Lid clearance", c.fnum(a["clr"], c.units)),
                ("Lid depth (outside)", c.fnum(a["lidh"], c.units)),
                ("Corner flap width", c.fnum(a["flap"], c.units) + c.tol("flap")),
                ("Units", c.units)]

    def drawing_notes(self, res, units):
        return ["Base inside length is the clear length between the corner flaps. Two trays on one sheet. Fold the four corner flaps of each tray first, then the walls, so the "
                "flaps end up inside the left and right walls. The lid slides over the base with the "
                f"clearance shown ({_fnum(res.info['auto']['clr'], units)})."]

    def fold_sequence(self, panels, t, amount):
        return telescope_sequence(panels, t, amount)


def telescope_sequence(panels, t, amount):
    """Lid & Base: in each tray the four corner flaps fold first, then the four walls fold up together so the
    flaps end up against the inside of the left / right walls. The left / right walls stand one board outside the base so the front and
    back walls end against them."""
    clamp = lambda v: min(1.0, max(0.0, v))

    def prog_of(p, d, m):
        n = p.name[2:] if p.name[1:2] == "_" else p.name
        if n.startswith("c"):
            return clamp(amount / 0.25)
        return clamp((amount - 0.25) / 0.75) if p.parent else 0.0

    def lift_of(p, prog):
        n = p.name[2:] if p.name[1:2] == "_" else p.name
        if n == "left":
            return (-t * prog, 0.0, 0.0)
        if n == "right":
            return (t * prog, 0.0, 0.0)
        if n in ("cfl", "cbl"):
            return (0.0, 0.0, 0.5 * t * prog)
        if n in ("cfr", "cbr"):
            return (0.0, 0.0, 0.5 * t * prog)
        return None
    return prog_of, lift_of, None


def telescope_dimensions(res, spec):
    """Dimension list for the two-tray telescope blank: widths of the base and lid trays across the top, heights of
    the lid tray down the right-hand side (the base heights are in the size table)."""
    pn = {p.name: p for p in res.panels}
    tv = res.info["tol"]["values"]
    bb = {k: _bbox(v) for k, v in pn.items()}
    out = []
    for pre in ("b_", "l_"):
        top = max(bb[pre + n][3] for n in ("back", "cbl", "cbr"))
        low = min(bb[pre + n][1] for n in ("front", "cfl", "cfr"))
        for nm, key in (("left", "panel"), ("bottom", "panel"), ("right", "panel")):
            b = bb[pre + nm]
            out.append(dict(kind="h", row=1, a=b[0], b=b[2], v=b[2] - b[0], tol=tv[key], ref=top, yref=top,      # from the top of the drawing, so the line
                            tag=pre + nm))                                 # does not run along a flap hinge
        x0, x1 = min(bb[pre + "left"][0], bb[pre + "cfl"][0]), max(bb[pre + "right"][2], bb[pre + "cfr"][2])
        out.append(dict(kind="h", row=2, a=x0, b=x1, v=x1 - x0, tol=tv["overall_len"], ref=bb[pre + "back"][3], yref=top,
                        tag=pre + "overall"))
        f = bb[pre + "cfl"]
        out.append(dict(kind="h", row=-1, a=f[0], b=f[2], v=f[2] - f[0], tol=tv["flap"], ref=f[1], yref=low,
                        tag=pre + "flap", note="FLAP"))
    xr = bb["l_cfr"][2]
    for nm, key in (("front", "panel"), ("bottom", "panel"), ("back", "panel")):
        b = bb["l_" + nm]
        out.append(dict(kind="v", row=1, a=b[1], b=b[3], v=b[3] - b[1], tol=tv[key], ref=xr, xref=xr,
                        tag="l_" + nm))
    y0, y1 = bb["l_front"][1], bb["l_back"][3]
    out.append(dict(kind="v", row=2, a=y0, b=y1, v=y1 - y0, tol=tv["overall_h"], ref=xr, xref=xr,
                    tag="l_overall_h"))
    return out


register_style(Telescope())
