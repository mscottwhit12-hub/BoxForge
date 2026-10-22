# =============================================================================
# Style: Cross / grid divider - flat slotted panels that cross at half-lap slots, for any rectangular box
# =============================================================================
# Dividers run along the length of the box ("lengthwise", slots cut from their top) and across its width
# ("crosswise", slots cut from their bottom). Each lengthwise divider has one slot per crosswise divider and the other
# way round, so the two sets slide together into a grid of equal compartments. Every divider is its own flat piece:
# nothing is folded. One lengthwise and one crosswise divider make a simple cross.
GRID_MAX = 9                      # most dividers each way
GRID_PREFIX = {"l": "gl", "w": "gw"}


def _grid_count(c, key, default=1):
    v = c.o.get(key)
    if v is None:
        return default
    return int(round(v)) if abs(v - round(v)) < 1e-9 else v           # a non-whole number is reported by check()


def grid_geometry(Li, Wi, Hi, t, nl, nw, clr, hclr, slot):
    """Sizes of the dividers for a box with inside length Li, width Wi and height Hi, all in the same units as t.
    `nl` dividers run along the length (spaced across the width), `nw` run across the width (spaced along the length).
    The compartments are equal, each divider's board counted. Returns a dict (see the keys below)."""
    Lp, Wp, Hs = Li - clr, Wi - clr, Hi - hclr
    cw = (Wi - nl * t) / (nl + 1)                          # clear width of a compartment across the box
    cl = (Li - nw * t) / (nw + 1)                          # clear length of a compartment along the box
    zs = [(j + 1) * cw + (j + 0.5) * t - Wi / 2.0 for j in range(nl)]       # lengthwise dividers: centre across, from the middle
    xs = [(i + 1) * cl + (i + 0.5) * t - Li / 2.0 for i in range(nw)]       # crosswise dividers: centre along, from the middle
    return dict(Lp=Lp, Wp=Wp, Hs=Hs, nl=nl, nw=nw, cl=cl, cw=cw, zs=zs, xs=xs, slot=slot, d=Hs / 2.0,
                slots_l=[x + Lp / 2.0 for x in xs],        # slot centres along a lengthwise divider (from its end)
                slots_w=[z + Wp / 2.0 for z in zs],        # ... and along a crosswise one
                Li=Li, Wi=Wi)


def _grid_outline(x0, y0, L, Hs, slots, sw, d, from_top):
    """One divider (a rectangle L x Hs at (x0, y0)) with a slot of width sw and depth d at each position in `slots`."""
    pts = [(x0, y0), (x0 + L, y0)]
    if from_top:
        pts.append((x0 + L, y0 + Hs))
        for u in sorted(slots, reverse=True):
            pts += [(x0 + u + sw / 2, y0 + Hs), (x0 + u + sw / 2, y0 + Hs - d), (x0 + u - sw / 2, y0 + Hs - d),
                    (x0 + u - sw / 2, y0 + Hs)]
        pts.append((x0, y0 + Hs))
    else:
        pts = [(x0, y0)]
        for u in sorted(slots):
            pts += [(x0 + u - sw / 2, y0), (x0 + u - sw / 2, y0 + d), (x0 + u + sw / 2, y0 + d), (x0 + u + sw / 2, y0)]
        pts += [(x0 + L, y0), (x0 + L, y0 + Hs), (x0, y0 + Hs)]
    return pts


def grid_items(g, crosswise_first=False):
    """[(name, role, index, length, slots)] of every divider: the lengthwise ones first (or last)."""
    a = [(f"gl{j + 1}", "l", j, g["Lp"], g["slots_l"]) for j in range(g["nl"])]
    b = [(f"gw{i + 1}", "w", i, g["Wp"], g["slots_w"]) for i in range(g["nw"])]
    return b + a if crosswise_first else a + b


def grid_panels(g, x0=0.0, y0=0.0, wmax=None, step=1.0, gap=0.0):
    """The divider panels laid out in rows from (x0, y0): left to right, a new row when the next one would pass
    x0 + wmax. A row is placed `step` x (height + gap) above the previous one (step = -1 puts the rows going down;
    the first row's bottom edge is at y0 either way)."""
    Hs, sw, d = g["Hs"], g["slot"], g["d"]
    out, x, row = [], x0, 0
    for name, role, idx, L, slots in grid_items(g, step < 0):      # rows going down: the crosswise ones on top, so that
        # in the 3-D model (where the sheet stands on its edge) the lengthwise dividers are always the lowest row
        if wmax is not None and x > x0 and x + L > x0 + wmax + 1e-9:
            x, row = x0, row + 1
        y = y0 + step * row * (Hs + gap)
        pn = Panel(name, _grid_outline(x, y, L, Hs, slots, sw, d, role == "l"), None, None, 90.0, "body")
        pn.group = "insert"
        pn.meta = dict(kind="grid", role=role, idx=idx, L=L, Hs=Hs, slots=list(slots), slot=sw, d=d,
                       nl=g["nl"], nw=g["nw"], zs=list(g["zs"]), xs=list(g["xs"]), Li=g["Li"], Wi=g["Wi"])
        out.append(pn)
        x += L + gap
    return out


def grid_size(g, gap, wmax):
    """(width, height, rows) of the laid-out dividers."""
    x, row, width = 0.0, 0, 0.0
    for name, role, idx, L, slots in grid_items(g, True):
        if wmax is not None and x > 0 and x + L > wmax + 1e-9:
            x, row = 0.0, row + 1
        x += L + gap
        width = max(width, x - gap)
    return width, (row + 1) * g["Hs"] + row * gap, row + 1


def grid_pieces(L, Hs, slots, sw, d, from_top):
    """The convex pieces one divider is drawn in (3-D preview): [(suffix, polygon (u, v), joints)]. The solid half is
    cut into a strip between each pair of slot centres and the slotted half into a column between each pair of slots.
    Every piece then lies wholly on one side of each crossing divider, which keeps the draw order exact where
    several dividers interlock."""
    cuts = sorted(slots)
    ub = [0.0]
    for u in cuts:
        ub += [u - sw / 2, u + sw / 2]
    ub.append(L)
    cols = [(ub[i], ub[i + 1]) for i in range(0, len(ub), 2) if ub[i + 1] - ub[i] > 1e-9]
    vlo, vhi = (0.0, Hs - d) if from_top else (d, Hs)          # the solid half
    v_int = vhi if from_top else vlo                           # where the slotted half meets it
    c0, c1 = (Hs - d, Hs) if from_top else (0.0, d)            # the slotted half
    bounds = [0.0] + cuts + [L]
    out, k = [], 0
    for a, b in zip(bounds, bounds[1:]):
        ins = [c for ca, cb in cols for c in (ca, cb) if a + 1e-9 < c < b - 1e-9]
        if from_top:
            poly = [(a, vlo), (b, vlo), (b, vhi)] + [(c, vhi) for c in sorted(set(ins), reverse=True)] + [(a, vhi)]
        else:
            poly = [(a, vlo)] + [(c, vlo) for c in sorted(set(ins))] + [(b, vlo), (b, vhi), (a, vhi)]
        joints = [((a, vlo), (a, vhi))] * (a > 1e-9) + [((b, vlo), (b, vhi))] * (b < L - 1e-9)
        joints += [((max(ca, a), v_int), (min(cb, b), v_int)) for ca, cb in cols if min(cb, b) > max(ca, a) + 1e-9]
        out.append((str(k), poly, joints))
        k += 1
    for ca, cb in cols:
        out.append((str(k), [(ca, c0), (cb, c0), (cb, c1), (ca, c1)], [((ca, v_int), (cb, v_int))]))
        k += 1
    return out


class Grid(Style):
    zero_ok = ("clr", "hclr")
    flat_parts = True
    auto_tol = {"slot": 0.1}                   # half-lap slots are cut to the board, not die-cut flap slots
    id, name = "grid", "Cross / grid divider"
    code = "Box divider"
    blurb = ("Slotted dividers that cross in a grid inside any rectangular box: one or more along the length, one or "
             "more across the width, sliding together at half-lap slots. Sized from the box's inside dimensions.")
    status = "experimental"
    defaults = dict(L=200.0, W=150.0, H=120.0, t=3.0)
    options = [("nl", "Dividers along the length"), ("nw", "Dividers across the width"),
               ("clr", "Fit clearance (along and across)"), ("hclr", "Height clearance"), ("slot", "Slot width")]
    count_keys = ("nl", "nw")
    height_label = "Box inside height"
    view_up = "y"
    mode_help = {
        "inner": "Inside of the box the dividers go into (the Slotted Box's inside size).",
        "outer": "Outside of the closed Slotted Box they go into.",
        "manufacturer": "Centre-of-crease sizes of the Slotted Box they go into.",
    }
    insert_blurb = "cross divider"

    def crease(self, L, W, H, t, mode):
        return STYLE_BY_ID["rsc"].crease(L, W, H, t, mode)

    def inner(self, Lc, Wc, Hc, t):
        return STYLE_BY_ID["rsc"].inner(Lc, Wc, Hc, t)

    def resolve(self, c, keys=("nl", "nw")):
        t = c.t
        Li, Wi, Hi = self.inner(c.Lc, c.Wc, c.Hc, t)
        nl, nw = _grid_count(c, keys[0]), _grid_count(c, keys[1])
        clr = _auto(c, "clr", t + max(c.mm_(0.5), 0.25 * t))
        hclr = _auto(c, "hclr", max(c.mm_(1.0), 0.25 * t))
        slot = _auto(c, "slot", t + max(c.mm_(0.3), 0.05 * t))
        if not (isinstance(nl, int) and isinstance(nw, int)) or nl < 0 or nw < 0 or nl > GRID_MAX or nw > GRID_MAX:
            return dict(bad_count=True, nl=nl, nw=nw, clr=clr, hclr=hclr, slot=slot, Li=Li, Wi=Wi, Hi=Hi)
        g = grid_geometry(Li, Wi, Hi, t, nl, nw, clr, hclr, slot)
        return dict(clr=clr, hclr=hclr, **g)

    def check(self, c, r, iss):
        t = c.t
        if r.get("bad_count"):
            iss.append(Issue("error", f"The number of dividers must be a whole number from 0 to {GRID_MAX} in each "
                                      f"direction.", ("nl", "nw")))
            return
        if r["nl"] + r["nw"] < 1:
            iss.append(Issue("error", "Add at least one divider.", ("nl", "nw")))
            return
        if r["nl"] == 0 or r["nw"] == 0:
            iss.append(Issue("warn", "Dividers in one direction only cross nothing: they have no slots to hold them "
                                     "upright and will lean or fall over. Add dividers in the other direction too.",
                             ("nl", "nw")))
        if r["clr"] < 0 or r["hclr"] < 0:
            iss.append(Issue("error", "Clearances cannot be negative.", ("clr", "hclr")))
        elif r["clr"] < t:
            iss.append(Issue("warn", "Less than one board thickness of clearance: the glue flap inside the Slotted "
                                     "Box can stop the dividers going in.", ("clr", "t")))
        if r["Lp"] < 3 * t or r["Wp"] < 3 * t:
            iss.append(Issue("error", "The box is too small for dividers at this board thickness.", ("L", "W", "t")))
            return
        if r["Hs"] < 4 * t:
            iss.append(Issue("error", f"Divider height ({fmt(r['Hs'])}) is under 4× the board thickness. Raise the box "
                                      f"height or lower the height clearance.", ("H", "hclr", "t")))
        if r["slot"] < t:
            iss.append(Issue("error", "Slots narrower than the board: the dividers cannot slide together.", ("slot", "t")))
        elif r["slot"] > 1.5 * t:
            iss.append(Issue("warn", "Slots wider than 1.5× the board make the crossings loose.", ("slot", "t")))
        for nm, cl, n, L, slots in (("along the length", r["cl"], r["nw"], r["Lp"], r["slots_l"]),
                                    ("across the width", r["cw"], r["nl"], r["Wp"], r["slots_w"])):
            if n and slots:
                lig = min([b - a - r["slot"] for a, b in zip(slots, slots[1:])] or [9e9])
                end = min(slots[0] - r["slot"] / 2, L - slots[-1] - r["slot"] / 2)
                if min(lig, end) < 1.5 * t - 1e-9:
                    iss.append(Issue("error", f"The compartments {nm} are too narrow ({fmt(cl)}): the slots would "
                                              f"leave less than 1.5 boards of material between them. Use fewer "
                                              f"dividers or a larger box.", ("nl", "nw", "slot", "t")))
        if r["cl"] < 8 * t or r["cw"] < 8 * t:
            iss.append(Issue("info", "Very small compartments (under 8 boards wide).", ("nl", "nw")))

    def build(self, c, r):
        g = r
        gap = max(c.mm_(5), 2 * c.t)
        wmax = 2.05 * max(g["Lp"], g["Wp"]) + gap
        return grid_panels(g, 0.0, 0.0, wmax, 1.0, gap), None

    rounded_folds = False
    tol_keys = ("panel", "slot", "overall_len", "overall_h")
    draw_sub = "Cross / grid divider, flat slotted panels"
    draw_cap = "BOX DIVIDER"
    anchor_panel = None
    step_text = {"flat": "As cut: every divider flat, lengthwise ones (slots on top) and crosswise ones (slots below).",
                 "partial": "The lengthwise dividers stand in place; the crosswise ones are turned and held above them.",
                 "folded": "The crosswise dividers lowered so each pair of slots meets: a grid of equal compartments."}
    step_amount = 0.5
    view_title = "ASSEMBLED DIVIDERS (NOT TO SCALE)"
    table_title = "DIVIDER SIZES"
    steps_note = "(not to scale; board drawn at full thickness)"
    step_heads = ("INSERT ASSEMBLED", "Walls and glue flap folded; the dividers slotted together above the box.")

    def view_caption(self, res, units):
        Li, Wi, Hi = res.info["inner"]
        return f"fits a box {_fnum(Li, units)} × {_fnum(Wi, units)} × {_fnum(Hi, units)} {units} inside"

    def bend_notes(self, rep):
        return ["The dividers are flat panels: there are no folds, so this page does not change the dieline.",
                "The bend settings only affect a box this divider is added to."]

    def tol_note(self, f, units):
        return f"Tolerances (± {units}): panels {f('panel')}; slots {f('slot')}; blank {f('overall_len')} x {f('overall_h')}."

    def dimensions(self, res, spec):
        return grid_dimensions(res, spec)

    def dim_field(self, dm, res, spec):
        tag = dm.get("tag", "")
        if tag.startswith("div_gl"):
            return "L", None
        if tag.startswith("div_gw"):
            return "W", None
        if tag == "height":
            return "H", None
        if tag == "slot_depth":
            return "H", None, 2.0
        return None

    def size_rows(self, c):
        a, u = c.a, c.units
        rows = [("Box inside L × W × H", c.tri(c.Li, c.Wi, c.Hi))]
        rows += self.in_box_rows(c, a)
        return rows + [c.flat, ("Board thickness", c.fnum(c.t, u)),
                       ("Fit clearance", c.fnum(a["clr"], u)),
                       ("Slot width", c.fnum(a["slot"], u) + c.tol("slot")),
                       ("Slot depth", c.fnum(a["d"], u)),
                       ("Units", u)]

    extra_rows = 2

    def in_box_rows(self, c, a):
        """Two table rows: the dividers and the compartments they make (also used when added to a Slotted Box)."""
        rows = []
        parts = []
        if a["nl"]:
            parts.append(f"{a['nl']} × {_fnum(a['Lp'], c.units)}")
        if a["nw"]:
            parts.append(f"{a['nw']} × {_fnum(a['Wp'], c.units)}")
        rows.append(("Dividers (along / across)", " + ".join(parts) + f"  ×  {_fnum(a['Hs'], c.units)} high"))
        rows.append((f"Compartments ({(a['nl'] + 1) * (a['nw'] + 1)})",
                     f"{_fnum(a['cl'], c.units)} × {_fnum(a['cw'], c.units)}"))
        return rows

    def drawing_notes(self, res, units):
        a = res.info["auto"]
        fm = lambda v: _fnum(v, units)
        notes = ["Stand the lengthwise dividers (slots cut from the top) in the box, then lower the crosswise dividers "
                 "(slots cut from the bottom) over them so every pair of slots meets and the tops finish level."]
        if a["nw"]:
            notes.append("Slot centres along each lengthwise divider, from one end: " + ", ".join(fm(v) for v in a["slots_l"])
                         + f"  (slot {fm(a['slot'])} wide, {fm(a['d'])} deep).")
        if a["nl"]:
            notes.append("Slot centres along each crosswise divider, from one end: " + ", ".join(fm(v) for v in a["slots_w"])
                         + f"  (slot {fm(a['slot'])} wide, {fm(a['d'])} deep).")
        return notes

    def fold_sequence(self, panels, t, amount):
        return grid_sequence(panels, t, amount)

    # ---- how it sits on the sheet of a Slotted Box ---------------------------------------------------------
    def box_layout(self, g, ox_centre, y_top, wmax, gap):
        """The divider panels placed below a box blank: rows going down from y_top, left edge at ox_centre - wmax / 2."""
        wid, hgt, rows = grid_size(g, gap, wmax)
        return grid_panels(g, ox_centre - wid / 2.0, y_top - g["Hs"], wmax, -1.0, gap), hgt

    def box_dims(self, res, spec):
        return grid_dimensions(res, spec, below=True)

    def box_note(self):
        return ("Dividers (cut from the same sheet, below the box): stand the lengthwise ones in the box, lower the "
                "crosswise ones over them so the slots meet, and fit the assembly before the top flaps are closed.")


def grid_sequence(panels, t, amount):
    """All dividers share one progress, 0 -> 1 over the whole slider (see fold_grid for what moves when)."""
    clamp = lambda v: min(1.0, max(0.0, v))

    def prog_of(p, d, m):
        return clamp(amount) if is_insert(p) else 0.0
    return prog_of, None, None


def grid_dimensions(res, spec, below=False):
    """Dimension records for the divider sheet: the first row of dividers, the blank's size, the height and the slot depth."""
    pans = [p for p in res.panels if is_insert(p)]
    tv = res.info["tol"]["values"]
    bb = {p.name: _bbox(p) for p in pans}
    top = max(b[3] for b in bb.values())
    bot = min(b[1] for b in bb.values())
    edge_y = bot if below else top                       # the row next to the dimensions: the bottom one when they go below
    first = [(p.name, bb[p.name]) for p in pans if abs((bb[p.name][1] if below else bb[p.name][3]) - edge_y) < 1e-6]
    r1, r2, edge = (-1, -2, bot) if below else (1, 2, top)
    out = []
    for nm, b in first[:3]:
        out.append(dict(kind="h", row=r1, a=b[0], b=b[2], v=b[2] - b[0], tol=tv["panel"], ref=edge, tag="div_" + nm))
    xl = min(b[0] for b in bb.values())
    xr = max(b[2] for b in bb.values())
    out.append(dict(kind="h", row=r2, a=xl, b=xr, v=xr - xl, tol=tv["overall_len"], ref=edge, tag="overall_len"))
    ref = xr
    f = first[0][1]
    out.append(dict(kind="v", row=2, a=f[1], b=f[3], v=f[3] - f[1], tol=tv["overall_h"], ref=ref, tag="height"))
    out.append(dict(kind="v", row=1, a=f[1], b=f[1] + (f[3] - f[1]) / 2, v=(f[3] - f[1]) / 2, tol=half_lap_tol(res, tv), ref=ref,
                    tag="slot_depth"))
    return out


register_style(Grid())
