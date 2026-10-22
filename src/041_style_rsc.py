# =============================================================================
# Style: Slotted Box (RSC), FEFCO 0201
# =============================================================================
def _loop_bodies(Lc, Wc, Hc, glue, y0=0.0, chamfer=None):
    """Four body panels in a row (L, W, L, W) plus the manufacturer's joint on the left."""
    xs = [0, Lc, Lc + Wc, 2 * Lc + Wc, 2 * Lc + 2 * Wc]
    P = [Panel("p1", rect_verts(xs[0], y0, xs[1], y0 + Hc))]
    for i in range(1, 4):
        P.append(Panel(f"p{i + 1}", rect_verts(xs[i], y0, xs[i + 1], y0 + Hc), f"p{i}",
                       ((xs[i], y0), (xs[i], y0 + Hc))))
    ch = min(glue * 0.5, Hc * 0.2) if chamfer is None else chamfer
    P.append(Panel("glue", [(0, y0), (-glue, y0 + ch), (-glue, y0 + Hc - ch), (0, y0 + Hc)], "p1",
                   ((0, y0), (0, y0 + Hc)), 90, "flap"))
    return P, xs


class RSC(Style):
    id, name = "rsc", "Slotted Box (RSC)"
    code = "FEFCO 0201"
    blurb = "The classic shipping carton: four walls, a glued manufacturer's joint and four closing flaps top and bottom."
    status = "standard"
    defaults = dict(L=200.0, W=150.0, H=120.0, t=3.0)
    options = [("glue", "Glue flap width"), ("slot", "Slot width"), ("flap", "Flap length"),
               ("gnl", "Cross divider: along the length"), ("gnw", "Cross divider: across the width")]
    count_keys = ("gnl", "gnw")
    toggles = [("insert", "Add a matching diagonal insert", False),
               ("insert_grid", "Add a matching cross divider", False)]
    exclusive = (("insert", "insert_grid"),)              # switches that cannot both be on
    mode_help = {
        "inner": "Inside of the box (FEFCO internal size: crease centre − 1 board; height − 2 boards).",
        "outer": "Outside of the closed box.",
        "manufacturer": "Centre-of-crease sizes straight onto the blank.",
    }

    def crease(self, L, W, H, t, mode):
        return {"inner": (L + t, W + t, H + 2 * t),
                "outer": (L - t, W - t, H - 2 * t),
                "manufacturer": (L, W, H)}[mode]

    def inner(self, Lc, Wc, Hc, t):
        return Lc - t, Wc - t, Hc - 2 * t

    def resolve(self, c):
        t, Lc, Wc = c.t, c.Lc, c.Wc
        glue = _auto(c, "glue", max(3 * t, min(c.mm_(25), 0.4 * min(Lc, Wc))))
        r = dict(glue=glue, slot=_auto(c, "slot", max(2 * t, c.mm_(1.0))), flap=_auto(c, "flap", (min(Lc, Wc) - t) / 2))
        if c.flags.get("insert") and not c.flags.get("insert_grid"):     # an insert sized from this box's inside dimensions
            r["ins"] = STYLE_BY_ID["insert"].resolve(insert_ctx(c))
            r["ins_kind"] = "diag"
        elif c.flags.get("insert_grid") and not c.flags.get("insert"):
            c2 = insert_ctx(c)
            c2.o = {k: c.o.get(k) for k in ("gnl", "gnw") if c.o.get(k) is not None}
            r["ins"] = STYLE_BY_ID["grid"].resolve(c2, keys=("gnl", "gnw"))
            r["ins_kind"] = "grid"
        return r

    def check(self, c, r, iss):
        t = c.t
        if r["slot"] >= min(c.Lc, c.Wc) * 0.5:
            iss.append(Issue("error", "Slot width is too large for the smallest panel.", ("slot",)))
        if r["glue"] < 3 * t:
            iss.append(Issue("error", f"Manufacturer's joint must be at least 3× the board thickness ({fmt(3 * t)}).",
                             ("glue", "t")))
        elif r["glue"] < c.mm_(12):
            iss.append(Issue("warn", "Manufacturer's joint is narrow (<12 mm); the glue bond may be weak.", ("glue",)))
        if r["glue"] > 0.5 * min(c.Lc, c.Wc) + 1e-9:
            iss.append(Issue("error", f"The glue flap ({fmt(r['glue'])}) is wider than half the narrowest wall "
                                      f"({fmt(min(c.Lc, c.Wc))}): it would run past the next corner and block that wall "
                                      f"from closing.", ("glue",)))
        elif r["glue"] > 0.4 * min(c.Lc, c.Wc) + 1e-9 and r["glue"] > c.mm_(40):
            iss.append(Issue("warn", "A glue flap this wide wastes board; 25-40 mm is usual.", ("glue",)))
        if c.spec.flute == "h":
            iss.append(Issue("warn", "Flutes run horizontally around the walls: the box loses much of its stacking "
                                     "strength and the flap creases run along the flutes, so they may fold off-line. "
                                     "Corrugated cartons are normally cut with the flutes vertical.", ("flute",)))
        if r["slot"] < t:
            iss.append(Issue("warn", "Slots narrower than the board thickness can make the flaps catch on each "
                                     "other when folding.", ("slot", "t")))
        if c.flags.get("insert") and c.flags.get("insert_grid"):
            iss.append(Issue("error", "Choose either the diagonal insert or the cross divider, not both.", ()))
        elif r.get("ins_kind") == "grid":
            n0 = len(iss)
            STYLE_BY_ID["grid"].check(insert_ctx(c), r["ins"], iss)
            for i in iss[n0:]:                                # the counts are called gnl / gnw here
                i.fields = tuple({"nl": "gnl", "nw": "gnw"}.get(f, f) for f in i.fields)
        elif r.get("ins"):
            tmp = []
            STYLE_BY_ID["insert"].check(insert_ctx(c), r["ins"], tmp)
            long_ = [i for i in tmp if getattr(i, "code", "") == "too_long"]
            if long_:                                     # a box that is fine without it stays exportable
                r["ins"], r["ins_kind"] = None, None
                iss.append(Issue("warn", "The diagonal insert was left out: " + long_[0].msg, ("insert",)))
                tmp = [i for i in tmp if i not in long_]
            iss.extend(tmp)
        half = (min(c.Lc, c.Wc) - t) / 2                  # half the smaller inside size: facing flaps just meet
        if r["flap"] > half + 1e-6:
            iss.append(Issue("warn", "Flaps longer than half the smaller inside size (length or width) collide in "
                                     "the middle of the box.", ("flap",)))
        elif r["flap"] < 0.9 * half:
            iss.append(Issue("warn", "Flaps shorter than ~half the smaller inside size (length or width) leave a "
                                     "gap in the closed box.", ("flap",)))

    def toggle_hint(self, key, vals):
        if key == "insert":
            L, W = vals.get("L"), vals.get("W")
            if L and W and max(L, W) > INS_MAX_RATIO * min(L, W):
                return ("A diagonal insert needs a box no longer than %g times its width: use the cross divider "
                        "instead." % INS_MAX_RATIO)
        return None

    def option_enabled(self, key, flags):
        return bool(flags.get("insert_grid")) if key in ("gnl", "gnw") else True

    def toggle_conflict(self, key, on):
        """Switches to turn off when `key` is turned on."""
        return [b if a == key else a for a, b in self.exclusive if key in (a, b)] if on else []

    def has_insert(self, res):
        ins = res.info.get("auto", {}).get("ins")
        return bool(ins) and not ins.get("bad_count") and ins.get("Hs", 1) > 0

    def insert_kind(self, res):
        return res.info.get("auto", {}).get("ins_kind")

    def build(self, c, r):
        Lc, Wc, Hc, t, s, fl = c.Lc, c.Wc, c.Hc, c.t, r["slot"], r["flap"]
        P, xs = _loop_bodies(Lc, Wc, Hc, r["glue"])
        rf = min(2 * t, fl / 4, (min(Lc, Wc) - s) / 4)
        for i in range(4):
            xa, xb = xs[i] + s / 2, xs[i + 1] - s / 2
            P.append(Panel(f"top{i + 1}", [(xa, Hc, 0), (xb, Hc, 0), (xb, Hc + fl, rf), (xa, Hc + fl, rf)],
                           f"p{i + 1}", ((xa, Hc), (xb, Hc)), 90, "flap"))
            P.append(Panel(f"bot{i + 1}", [(xa, 0, 0), (xa, -fl, rf), (xb, -fl, rf), (xb, 0, 0)],
                           f"p{i + 1}", ((xa, 0), (xb, 0)), 90, "flap"))
        ins = r.get("ins")
        if ins:                                            # the insert strip, cut from the same sheet below the box
            gap = max(c.mm_(8), 2 * t)
            if r.get("ins_kind") == "grid":
                if not ins.get("bad_count") and ins["Hs"] > 0:
                    P += STYLE_BY_ID["grid"].box_layout(ins, Lc + Wc, -fl - gap, 2 * (Lc + Wc), max(c.mm_(5), 2 * t))[0]
            else:
                ox = (Lc + Wc) - (ins["m"] + 2 * ins["q"]) / 2
                P += insert_panels(ins, ins["Hs"], ins["slot"], ins["relief"], ox, -fl - gap - ins["Hs"])
        return P, None

    rounded_folds = True
    tol_keys = ("panel", "flap", "slot", "glue", "overall_len", "overall_h", "box")
    draw_sub = "Regular slotted container  ·  FEFCO 0201"
    draw_cap = "FEFCO 0201"
    anchor_panel = "p1"
    closing_report = True

    def dimensions(self, res, spec):
        dims = rsc_dimensions(res, spec)
        if self.has_insert(res):                           # the insert's dimensions go below it; no room for the slot dim
            dims = [d for d in dims if d.get("tag") != "slot"] + (
                STYLE_BY_ID["grid"].box_dims(res, spec) if self.insert_kind(res) == "grid" else insert_dims_below(res, spec))
        return dims

    def dim_field(self, dm, res, spec):
        tag = dm.get("tag", "")
        key = {"glue": "glue", "slot": "slot", "flap_top": "flap", "flap_bot": "flap", "panel1": "L", "panel3": "L",
               "panel2": "W", "panel4": "W", "panel_h": "H"}.get(tag)
        if tag == "height":                                # the insert's / dividers' height follows the box height
            return "H", None
        if tag == "slot_depth":                            # half of that height
            return "H", None, 2.0
        if tag.startswith("div_gl"):
            return "L", None
        if tag.startswith("div_gw"):
            return "W", None
        if key is None or (tag == "slot" and self.has_insert(res)):
            return None
        return key, (None if key in ("L", "W", "H") else dm["v"])

    def size_rows(self, c):
        rows = [("Inside L × W × H", c.tri(c.Li, c.Wi, c.Hi) + c.tol("box")),
                ("Outside L × W × H", c.tri(c.Lc + c.t, c.Wc + c.t, c.Hc + 2 * c.t) + c.tol("box")),
                ("Crease L × W × H", c.tri(c.Lc, c.Wc, c.Hc)), c.flat,
                ("Board thickness", c.fnum(c.t, c.units)),
                ("Glue flap", c.fnum(c.a["glue"], c.units) + c.tol("glue")),
                ("Slot width", c.fnum(c.a["slot"], c.units) + c.tol("slot")),
                ("Flap length", c.fnum(c.a["flap"], c.units) + c.tol("flap"))]
        ins = c.a.get("ins")
        if ins and c.a.get("ins_kind") == "grid":
            if not ins.get("bad_count"):
                rows += STYLE_BY_ID["grid"].in_box_rows(c, ins)
        elif ins:
            rows += [("Insert blade / wall / blade", c.tri(ins["q"], ins["m"], ins["q"])),
                     ("Insert fits L × W × H", insert_fit_tri(c, ins))]
        if ins and not ins.get("bad_count"):
            rows.append(("Divider slot width (cut)" if c.a.get("ins_kind") == "grid"
                         else "Insert slot width (cut)", c.fnum(ins["slot"] * ins.get("kslot", 1.0), c.units) + c.tol_mm(0.1)))
        return rows + [("Units", c.units)]

    def table_rows(self, res):
        return 12 if self.has_insert(res) else 9

    def toggle_view(self, key):
        return SEQ_INS_DROP if key in ("insert", "insert_grid") else None         # insert down in the open box, flaps still open

    def view_heading(self, res):
        if self.has_insert(res):                           # shown before the flaps close, so the insert can be seen
            return ("BOX WITH DIVIDERS  -  FLAPS OPEN (NOT TO SCALE)" if self.insert_kind(res) == "grid"
                    else "BOX WITH INSERT  -  FLAPS OPEN (NOT TO SCALE)")
        return self.view_title

    def view_amount(self, res):
        return SEQ_INS_DROP if self.has_insert(res) else 1.0   # insert down in the open box: the insert shows inside

    def drawing_notes(self, res, units):
        notes = [f"Slots (6 off) {_fnum(res.info['auto']['slot'], units)} wide, cut through."]
        if self.has_insert(res):
            notes.append("The slot tolerance in note 2 applies to these flap slots only; the insert / divider half-lap slots "
                         "are held to the tighter tolerance in the size table (Insert slot width).")
        if self.insert_kind(res) == "grid":
            notes.append(STYLE_BY_ID["grid"].box_note())
        elif self.has_insert(res):
            notes.append("Insert (cut from the same sheet, below the box): fold both creases away from the printed side "
                         "to the fold angle, slide the two blades together at their slots (one cut from the top, one from the "
                         "bottom) and stand it in the box with the wall panel against one wall, before the top flaps "
                         "are closed. The fold slits stay cut through; the top and bottom quarters of each crease are "
                         "the hinges.")
        return notes

    def fold_sequence(self, panels, t, amount):
        return rsc_sequence(panels, t, amount)

    def step_views(self, res):
        if not self.has_insert(res):
            return list(STEP_VIEWS)
        return [STEP_VIEWS[0],
                ("above",) + (("STEP 2  -  DIVIDERS ASSEMBLED", STYLE_BY_ID["grid"].step_heads[1]) if self.insert_kind(res) == "grid" else
                              ("STEP 2  -  INSERT FOLDED", "Walls and glue flap folded; the insert folded into its X, above the box.")),
                ("down", "STEP 3  -  " + ("DIVIDERS IN THE BOX" if self.insert_kind(res) == "grid" else "INSERT IN THE BOX"),
                 "The " + ("dividers" if self.insert_kind(res) == "grid" else "insert") + " lowered into the open box; flaps still open."),
                ("folded", "STEP 4  -  FULLY FOLDED", STEP_VIEWS[2][2])]

    def stage_amount(self, stage):
        return {"above": SEQ_INS_FOLD, "down": SEQ_INS_DROP}.get(stage)


SEQ_WALLS, SEQ_MINOR = 0.50, 0.75      # slider fraction where the walls are done / the shorter flaps are done
# With an insert the walls AND the insert's folds take the first stretch together (the insert folds into its X over
# the box while the glue flap is being attached), then the insert goes down into the box, then the flaps close.
SEQ_INS_FOLD, SEQ_INS_DROP, SEQ_INS_MINOR = 0.34, 0.58, 0.79


def rsc_sequence(panels, t, amount):
    """Fold order of a real slotted box for slider position `amount` (0..1): all four walls and the glue flap
    together, then the two shorter flaps (facing each other) at the same time, then the two longer flaps together.
    With an insert strip on the sheet: walls, glue flap and the insert's folds together (the insert hovering above the
    open box), then the insert lowered into the box, then the flaps as before. The insert's height above its final
    place is `prog_of.insert_hover` (1 = hovering, 0 = in place).
    Returns (prog_of, lift_of, layer) for panel_transforms / solid_faces / iso_solid_polys (layer None while the
    flaps are still open, since sorting by depth is then enough)."""
    lift = stage_lift(panels, t)
    major = lift.major if lift else set()
    clamp = lambda v: min(1.0, max(0.0, v))
    has_ins = any(is_insert(p) for p in panels)
    a_w, a_d, a_m = (SEQ_INS_FOLD, SEQ_INS_DROP, SEQ_INS_MINOR) if has_ins else (SEQ_WALLS, SEQ_WALLS, SEQ_MINOR)

    def prog_of(p, d, m):
        if p.role == "body" or p.name == "glue" or is_insert(p):
            return clamp(amount / a_w)
        if p.name in major:
            return clamp((amount - a_m) / (1.0 - a_m))
        return clamp((amount - a_d) / (a_m - a_d))
    prog_of.insert_hover = (1.0 - clamp((amount - a_w) / (a_d - a_w))) if has_ins else 0.0
    layer = None
    if amount > a_d and lift:
        layer = {pn.name: ((0.5 if pn.name in major else 0) if pn.name.startswith("bot") else
                           (3 if pn.name in major else 2) if pn.name.startswith("top") else 1) for pn in panels}
    return prog_of, lift, layer


def rsc_dimensions(res, spec):
    """Dimension list for the RSC flat blank, in user units. kind 'h' / 'v'; row 1 / 2 = distance from the
    blank (row -1 = below it); a, b = the two measured positions; ref = where the extension lines start."""
    pn = {p.name: p for p in res.panels}
    tv = res.info["tol"]["values"]
    glue, p1, p2, p3, p4 = (_bbox(pn[k]) for k in ("glue", "p1", "p2", "p3", "p4"))
    top1, top2, bot1 = (_bbox(pn[k]) for k in ("top1", "top2", "bot1"))
    yb, yt = p1[1], p1[3]
    ftop, fbot = top1[3], bot1[1]
    xs = [p1[0], p2[0], p3[0], p4[0], p4[2]]
    out = [dict(kind="h", row=1, a=glue[0], b=xs[0], v=xs[0] - glue[0], tol=tv["glue"], ref=ftop, tag="glue")]
    for i in range(4):
        out.append(dict(kind="h", row=1, a=xs[i], b=xs[i + 1], v=xs[i + 1] - xs[i], tol=tv["panel"], ref=ftop,
                        tag=f"panel{i + 1}"))
    out.append(dict(kind="h", row=2, a=glue[0], b=xs[4], v=xs[4] - glue[0], tol=tv["overall_len"], ref=ftop,
                    tag="overall_len"))
    out.append(dict(kind="h", row=-1, a=top1[2], b=top2[0], v=top2[0] - top1[2], tol=tv["slot"], ref=fbot,
                    tag="slot", note="TYP"))
    out.append(dict(kind="v", row=1, a=fbot, b=yb, v=yb - fbot, tol=tv["flap"], ref=xs[4], tag="flap_bot"))
    out.append(dict(kind="v", row=1, a=yb, b=yt, v=yt - yb, tol=tv["panel"], ref=xs[4], tag="panel_h"))
    out.append(dict(kind="v", row=1, a=yt, b=ftop, v=ftop - yt, tol=tv["flap"], ref=xs[4], tag="flap_top"))
    out.append(dict(kind="v", row=2, a=fbot, b=ftop, v=ftop - fbot, tol=tv["overall_h"], ref=xs[4], tag="overall_h"))
    return out


register_style(RSC())
