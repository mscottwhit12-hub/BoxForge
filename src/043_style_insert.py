# =============================================================================
# Style: Insert (diagonal X divider) - one folded strip, for square and rectangular boxes
# =============================================================================
# The strip has three panels in a row: a blade, a wall panel and a blade. The wall panel stands against one wall of
# the box (the shorter wall); each blade folds back off one end of it and runs corner to corner, so the two blades
# cross at the centre of the box in an X. A slot cut from the top of one blade and from the bottom of the other lets
# them slide together (a half lap). The fold lines carry a slit through the middle half of their height so the thick
# board can turn through the fold angle; the top and bottom quarters stay joined and act as hinges.
INS_TURN = 0.75 * math.pi       # the fold angle in a square box: 135 degrees (the blade ends up 45 degrees to the wall panel)
INS_MAX_RATIO = 3.0             # longest box (length / width) the diagonal insert is offered for
INS_NAMES = ("ia", "ib", "ic")   # blade, wall panel, blade (the wall panel is the root; list it first)
_SQ2 = math.sqrt(2.0)


def insert_nominal_bend(t):
    """(inside radius, K) the insert is sized with. Fixed on purpose: the dieline must not move when the 3-D preview's
    bend radius is changed."""
    m = BEND_MATERIALS[BEND_DEFAULT]
    return m["ri"] * t, m["k"]


def insert_fold_length(t, turn=INS_TURN):
    """Neutral length of board one fold uses up (the width a hinge slit has to be at least)."""
    ri, K = insert_nominal_bend(t)
    return turn * (ri + K * t)


def insert_geometry(Sw, t, Sl=None):
    """Sizes of the strip for a space `Sw` wide (the wall panel's wall) and `Sl` long (Sl >= Sw; a square when omitted),
    the clear size the insert may use, all in the same units as t.
    Plan view of the folded insert, board outside face against the wall: the wall panel lies along the wall, each fold
    is a true arc of outside radius rho = ri + t, and each blade's far corner just touches the corner of the space
    (its outer face the wall that faces it, the inner face the side wall). With phi the blade's angle to the wall
    (atan Sl / Sw, 45 degrees in a square) each fold turns through turn = 180 degrees - phi, and
        lam blade flat length       = (Sl - (1 + cos phi) rho) / sin phi
        b   wall panel flat length  = 2 lam cos phi - Sw - 2 rho sin phi + 2 t sin phi
    With bn = the neutral length of one fold, m = b + bn (crease to crease on the wall panel) and q = lam + bn / 2
    (crease to the end of a blade). `sc` is how far from the start of a blade's flat part the two blades cross, and
    `kslot` how much wider than the board a slot has to be because the blades cross at an angle."""
    Sl = Sw if Sl is None else Sl
    ri, K = insert_nominal_bend(t)
    rn, rho = ri + K * t, ri + t
    phi = math.atan2(Sl, Sw)
    turn = math.pi - phi
    c, sn_ = math.cos(phi), math.sin(phi)
    bn = turn * rn
    lam = (Sl - (1 + c) * rho) / sn_
    b = 2 * lam * c - Sw - 2 * rho * sn_ + 2 * t * sn_
    return dict(ri=ri, K=K, rn=rn, rho=rho, bn=bn, b=b, lam=lam, m=b + bn, q=lam + bn / 2,
                sc=(b / 2 + rho * sn_ - t * sn_ / 2) / c, turn=turn, phi=phi, Sw=Sw, Sl=Sl,
                kslot=1.0 / max(1e-6, abs(math.sin(2 * phi))))


def insert_panels(g, Hs, slot, relief, ox=0.0, oy=0.0, pre=""):
    """The three panels of the strip at (ox, oy), height Hs. `g` from insert_geometry. Slot of width `slot`, half the
    height deep, from the top of the first blade and from the bottom of the second; fold slits `relief` wide and half
    the height tall, centred on the folds."""
    q, m, bn, sc = g["q"], g["m"], g["bn"], g["sc"]
    turn = g.get("turn", INS_TURN)
    slot = slot * g.get("kslot", 1.0)               # blades crossing at an angle need a longer slot in each
    x1 = ox + q
    x2 = x1 + m
    x3 = x2 + q
    h, d, sw = relief / 2.0, Hs / 2.0, slot
    r0, r1 = oy + Hs / 4.0, oy + 3.0 * Hs / 4.0
    y0, y1 = oy, oy + Hs
    ca = x1 - (bn / 2.0 + sc)                    # slot centre on the first blade
    cc = x2 + (bn / 2.0 + sc)                    # ... and on the second
    A = [(ox, y0), (x1, y0), (x1, r0), (x1 - h, r0), (x1 - h, r1), (x1, r1), (x1, y1),
         (ca + sw / 2, y1), (ca + sw / 2, y1 - d), (ca - sw / 2, y1 - d), (ca - sw / 2, y1), (ox, y1)]
    B = [(x1, y0), (x2, y0), (x2, r0), (x2 - h, r0), (x2 - h, r1), (x2, r1), (x2, y1), (x1, y1), (x1, r1),
         (x1 + h, r1), (x1 + h, r0), (x1, r0)]
    C = [(x2, y0), (cc - sw / 2, y0), (cc - sw / 2, y0 + d), (cc + sw / 2, y0 + d), (cc + sw / 2, y0), (x3, y0),
         (x3, y1), (x2, y1), (x2, r1), (x2 + h, r1), (x2 + h, r0), (x2, r0)]
    pB = Panel(pre + "ib", B, None, None, 90.0, "body")
    pA = Panel(pre + "ia", A, pre + "ib", ((x1, y0), (x1, y1)), round(math.degrees(turn), 9), "body")
    pC = Panel(pre + "ic", C, pre + "ib", ((x2, y0), (x2, y1)), round(math.degrees(turn), 9), "body")
    pA.fold_segs = [((x1, y0), (x1, r0)), ((x1, r1), (x1, y1))]
    pC.fold_segs = [((x2, y0), (x2, r0)), ((x2, r1), (x2, y1))]
    pB.meta = dict(kind="diag", Hs=Hs, q=q, m=m, relief=relief, slot=slot, bn=bn, slot_from_crease=bn / 2.0 + sc,
                   turn=turn, Li=g.get("Sl", 0.0), Wi=g.get("Sw", 0.0))
    for pn in (pA, pB, pC):
        pn.group = "insert"
    return [pB, pA, pC]


class Insert(Style):
    zero_ok = ("clr", "hclr")
    auto_tol = {"slot": 0.1}                   # half-lap slots are cut to the board, not die-cut flap slots
    id, name = "insert", "Insert (diagonal X)"
    code = "Box insert"
    blurb = ("A divider that stands inside a square or rectangular box: one folded strip whose two blades cross "
             "corner to corner in an X and lock together at their slots. Sized from the box's inside dimensions.")
    status = "experimental"
    defaults = dict(L=150.0, W=150.0, H=120.0, t=3.0)
    options = [("clr", "Fit clearance (across the box)"), ("hclr", "Height clearance"), ("slot", "Slot width"),
               ("relief", "Fold slit width")]
    height_label = "Box inside height"
    view_up = "y"
    mode_help = {
        "inner": "Inside of the box the insert goes into (the Slotted Box's inside size).",
        "outer": "Outside of the closed Slotted Box it goes into.",
        "manufacturer": "Centre-of-crease sizes of the Slotted Box it goes into.",
    }

    # the box it goes into is a Slotted Box (RSC): same size rules
    def crease(self, L, W, H, t, mode):
        return STYLE_BY_ID["rsc"].crease(L, W, H, t, mode)

    def inner(self, Lc, Wc, Hc, t):
        return STYLE_BY_ID["rsc"].inner(Lc, Wc, Hc, t)

    def resolve(self, c):
        t = c.t
        Li, Wi, Hi = self.inner(c.Lc, c.Wc, c.Hc, t)
        clr = _auto(c, "clr", t + max(c.mm_(0.5), 0.25 * t))        # one board for the box's glue flap, plus a little play
        hclr = _auto(c, "hclr", max(c.mm_(1.0), 0.25 * t))
        slot = _auto(c, "slot", t + max(c.mm_(0.3), 0.05 * t))
        Sw, Sl, Hs = min(Li, Wi) - clr, max(Li, Wi) - clr, Hi - hclr
        if Sw <= 0:                                           # no room at all: sizes that check() reports as an error
            return dict(clr=clr, hclr=hclr, slot=slot, relief=0.0, Sw=Sw, Sl=Sl, Hs=Hs, too_small=True, b=0.0, lam=0.0,
                        bn=0.0, m=0.0, q=0.0, turn=INS_TURN)
        g = insert_geometry(Sw, t, Sl)
        relief = _auto(c, "relief", insert_fold_length(t, g["turn"]))
        return dict(clr=clr, hclr=hclr, slot=slot, relief=relief, Hs=Hs, long_side="L" if Li >= Wi else "W", **g)

    def check(self, c, r, iss):
        t = c.t
        Li, Wi, Hi = self.inner(c.Lc, c.Wc, c.Hc, t)
        if r.get("too_small") or r["b"] < 1.5 * t or r["lam"] < 3 * t:
            iss.append(Issue("error", "The box is too small for an insert at this board thickness. Reduce the "
                                      "thickness or enlarge the box.", ("L", "W", "t")))
            return
        if r["Sl"] > INS_MAX_RATIO * r["Sw"]:
            iss.append(Issue("error", f"The box is too long and narrow for a diagonal insert (length to width "
                                      f"{r['Sl'] / r['Sw']:.1f} : 1, the most is {INS_MAX_RATIO:g} : 1). Use the cross "
                                      f"divider instead.", ("L", "W")))
            iss[-1].code = "too_long"
            return
        if r["clr"] < 0 or r["hclr"] < 0:
            iss.append(Issue("error", "Clearances cannot be negative.", ("clr", "hclr")))
        elif r["clr"] < t:
            iss.append(Issue("warn", "Less than one board thickness of clearance across the box: the glue flap inside "
                                     "the Slotted Box can stop the insert going in.", ("clr", "t")))
        if r["Hs"] < 4 * t:
            iss.append(Issue("error", f"Insert height ({fmt(r['Hs'])}) is under 4× the board thickness. Raise the "
                                      f"box height or lower the height clearance.", ("H", "hclr", "t")))
        if r["slot"] < t:
            iss.append(Issue("error", "Slots narrower than the board: the two blades cannot slide together.",
                             ("slot", "t")))
        elif r["slot"] > 1.5 * t:
            iss.append(Issue("warn", "Slots wider than 1.5× the board make the crossing loose.", ("slot", "t")))
        if r["relief"] < r["bn"] - 1e-9:
            iss.append(Issue("error", f"Fold slits must be at least {fmt(r['bn'], 3)} wide, the length of board a "
                                      f"fold uses up, or they would not clear the bend.", ("relief",)))
        elif r["relief"] > r["m"] / 3:
            iss.append(Issue("warn", "Very wide fold slits leave the wall panel short.", ("relief",)))

    def build(self, c, r):
        return insert_panels(r, r["Hs"], r["slot"], r["relief"]), None

    rounded_folds = False
    tol_keys = ("panel", "slot", "overall_len", "overall_h")
    draw_sub = "Diagonal X insert, single folded strip"
    draw_cap = "BOX INSERT"
    anchor_panel = "ib"
    step_text = {"flat": "As cut: the strip with its slots and fold slits.",
                 "partial": "Both folds half way: the blades swing in off the wall panel.",
                 "folded": "Both creases folded and the blades slid together at the slots, corner to corner."}
    step_amount = 0.55

    view_title = "FOLDED INSERT (NOT TO SCALE)"
    table_title = "INSERT SIZES"
    steps_note = "(not to scale; board drawn at full thickness)"

    def view_caption(self, res, units):
        Li, Wi, Hi = res.info["inner"]
        return f"fits a box {_fnum(Li, units)} × {_fnum(Wi, units)} × {_fnum(Hi, units)} {units} inside"

    def bend_notes(self, rep):
        ri, K = insert_nominal_bend(1.0)
        return ["The dieline is not changed by this page. The insert is sized with a fixed bend model (inside radius "
                f"{ri:g} × board, K {K:g}): each fold is a true arc, and each blade just reaches the corner of the box.",
                "Changing the radius or K-factor here shows how the real fold behaves; it does not move any crease."]

    def tol_note(self, f, units):
        return f"Tolerances (± {units}): panels / scores {f('panel')}; slots {f('slot')}; blank {f('overall_len')} x {f('overall_h')}."

    def dimensions(self, res, spec):
        return insert_dimensions(res, spec)

    def dim_field(self, dm, res, spec):
        tag, au = dm.get("tag"), res.info.get("auto", {})
        if tag == "slot" and "slot" in au:
            return "slot", au["slot"], 1.0 / au.get("kslot", 1.0)       # the cut slot is wider than the box value on a long box
        if tag == "height":
            return "H", None
        if tag == "slot_depth":
            return "H", None, 2.0
        return None

    def size_rows(self, c):
        a, u = c.a, c.units
        return [("Box inside L × W × H", c.tri(c.Li, c.Wi, c.Hi)),
                ("Insert fits L × W × H", insert_fit_tri(c, a)),
                ("Blade / wall / blade", c.tri(a["q"], a["m"], a["q"])), c.flat,
                ("Board thickness", c.fnum(c.t, u)),
                ("Fit clearance", c.fnum(a["clr"], u)),
                ("Slot width (cut)", c.fnum(a["slot"] * a.get("kslot", 1.0), u) + c.tol("slot")),
                ("Fold slit width", c.fnum(a["relief"], u)),
                ("Units", u)]

    def drawing_notes(self, res, units):
        a = res.info["auto"]
        return [f"Fold both creases the same way, away from the printed outside, until each blade stands at "
                f"{math.degrees(a['phi']):.0f}° to the wall panel (a {math.degrees(a['turn']):.0f}° fold). The wall panel "
                f"goes flat against the shorter wall of the box.",
                "Slide the blades together at the slots: the slot cut from the top of one blade meets the slot cut from "
                "the bottom of the other, so they cross at the centre of the box.",
                "The fold slits are cut through, 1/2 of the height at the middle of each crease; the top and bottom "
                "quarters stay as hinges."]

    def fold_sequence(self, panels, t, amount):
        return insert_sequence(panels, t, amount)


def insert_fit_tri(c, a):
    """'L × W × H' of the space the insert fits, in the box's own orientation."""
    Sl, Sw = a["Sl"], a["Sw"]
    return c.tri(*((Sl, Sw) if a.get("long_side", "L") == "L" else (Sw, Sl)), a["Hs"])


def insert_ctx(c):
    """Build context for an insert that rides along with a Slotted Box: the same sizes, but none of the box's own
    advanced options (the box's slot width is not the insert's)."""
    c2 = Ctx(c.spec, c.Lc, c.Wc, c.Hc)
    c2.o = {}
    return c2


def insert_dims_below(res, spec):
    return insert_dimensions(res, spec, below=True)


def insert_sequence(panels, t, amount):
    """Both blades fold together, 0 -> 1 over the whole slider."""
    clamp = lambda v: min(1.0, max(0.0, v))

    def prog_of(p, d, m):
        return clamp(amount) if p.name[-2:] in ("ia", "ic") else 0.0
    return prog_of, None, None


def insert_dimensions(res, spec, below=False):
    """Dimension records for the flat strip (see rsc_dimensions for the format). `below`: the strip sits under a box,
    so its widths go on the rows below it and the slot (listed in the size table) is left out."""
    pn = {p.name: p for p in res.panels if p.name in INS_NAMES}
    tv = res.info["tol"]["values"]
    a, b, c = (_bbox(pn[k]) for k in ("ia", "ib", "ic"))
    top, bot = b[3], b[1]
    r1, r2, edge = (-1, -2, bot) if below else (1, 2, top)
    out = [dict(kind="h", row=r1, a=a[0], b=a[2], v=a[2] - a[0], tol=tv["panel"], ref=edge, tag="blade1"),
           dict(kind="h", row=r1, a=b[0], b=b[2], v=b[2] - b[0], tol=tv["panel"], ref=edge, tag="wall"),
           dict(kind="h", row=r1, a=c[0], b=c[2], v=c[2] - c[0], tol=tv["panel"], ref=edge, tag="blade2"),
           dict(kind="h", row=r2, a=a[0], b=c[2], v=c[2] - a[0], tol=tv["overall_len"], ref=edge, tag="overall_len")]
    xs = sorted(q[0] for q in pn["ic"].poly if abs(q[1] - (bot + (top - bot) / 2)) < 1e-6)     # the slot floor corners
    if len(xs) >= 2 and not below:
        out.append(dict(kind="h", row=-1, a=xs[0], b=xs[-1], v=xs[-1] - xs[0], tol=half_lap_tol(res, tv), ref=bot, tag="slot",
                        note="SLOT"))
    out.append(dict(kind="v", row=2, a=bot, b=top, v=top - bot, tol=tv["overall_h"], ref=c[2], tag="height"))
    out.append(dict(kind="v", row=1, a=bot, b=bot + (top - bot) / 2, v=(top - bot) / 2, tol=half_lap_tol(res, tv), ref=c[2],
                    tag="slot_depth"))                       # the shorter one inside, so no line runs through a label
    return out


register_style(Insert())
