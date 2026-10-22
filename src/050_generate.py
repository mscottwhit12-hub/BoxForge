# =============================================================================
# Generation + validation
# =============================================================================
def generate(style, spec):
    """Build the dieline for `spec` and decide whether it is possible (error), questionable (warn) or fine."""
    res = Result(style, spec)
    iss = res.issues
    mm = 25.4 if spec.units == "in" else 1.0

    for key, label in (("L", "Length"), ("W", "Width"), ("H", style.height_label), ("t", "Material thickness")):
        v = getattr(spec, key)
        if v is None or not math.isfinite(v):
            iss.append(Issue("error", f"{label}: enter a number.", (key,)))
        elif v <= 0:
            iss.append(Issue("error", f"{label} must be greater than zero.", (key,)))
    counts = tuple(getattr(style, "count_keys", ())) + tuple(getattr(style, "zero_ok", ()))
    for key, v in spec.opts.items():
        if v is not None and (not math.isfinite(v) or v < 0 or (v == 0 and key not in counts)):
            iss.append(Issue("error", "Advanced values must be positive numbers (leave blank for automatic).", (key,)))
    kerf = spec.kerf or 0.0
    if not math.isfinite(kerf) or kerf < 0:
        iss.append(Issue("error", "Kerf must be zero or a positive number.", ("kerf",)))
    if spec.perf:
        for key, lo, hi, nm in (("perf_dash", 1.0, 20.0, "Dash length"), ("perf_tie", 0.5, 10.0, "Bridge spacing")):
            v = getattr(spec, key)
            if not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
                iss.append(Issue("error", f"{nm} must be between {lo:g} and {hi:g} mm.", (key,)))
    try:
        res.look = resolve_look(spec.look)
        if res.look["cut_pt"] == res.look["fold_pt"]:
            iss.append(Issue("warn", "Cut and fold lines have the same weight. Software that sorts by line "
                                     "weight will not tell them apart.", ("cut_weight", "fold_weight")))
        if res.look["cut_hex"] == res.look["fold_hex"]:
            iss.append(Issue("info", "Cut and fold lines have the same colour.", ()))
    except (ValueError, TypeError) as exc:
        res.look = resolve_look()
        bad = ("cut_weight", "fold_weight", "engrave_weight") if "weight" in str(exc) else ()
        iss.append(Issue("error", f"Line settings: {exc}.", bad))
    for key, label in (("L", "Length"), ("W", "Width"), ("H", style.height_label)):
        v = getattr(spec, key) * mm
        if v > 10000:
            iss.append(Issue("error", f"{label} is over 10 metres: check the units and the decimal point.", (key,)))
        elif v > 2500:
            iss.append(Issue("warn", f"{label} is over 2.5 metres. Check the units and the decimal point.", (key,)))
    if res.errors:
        return res

    t = spec.t
    try:
        Lc, Wc, Hc = style.crease_for(spec)
    except KeyError:
        iss.append(Issue("error", "Unknown dimension mode.", ()))
        return res
    c = Ctx(spec, Lc, Wc, Hc)
    Li, Wi, Hi = style.inner_for(spec, Lc, Wc, Hc)
    res.info.update(crease=(Lc, Wc, Hc), inner=(Li, Wi, Hi))

    # ---- universal limits ------------------------------------------------------------------------
    names = {"L": Li, "W": Wi, "H": Hi}
    if min(Lc, Wc, Hc) <= 0 or min(Li, Wi, Hi) <= 0:
        bad = [k for k, v in names.items() if v <= 0] or ["t"]
        iss.append(Issue("error", "These numbers leave a panel with no size once the board thickness is taken "
                                  "into account. Reduce the thickness or enlarge the box.", tuple(bad) + ("t",)))
        return res
    dims = {k: names[k] for k in style.ratio_dims}
    kmin = min(dims, key=dims.get)
    vmin = dims[kmin]
    ratio = vmin / t
    if ratio < 4:
        iss.append(Issue("error",
                         f"Smallest inside dimension ({fmt(vmin)} {spec.units}) is only {fmt(ratio, 1)}× the board "
                         f"thickness. Panels this small cannot hold a crease or seat the flaps. Use at least "
                         f"{fmt(4 * t)} {spec.units} (or board ≤ {fmt(vmin / 4)} {spec.units}).", (kmin, "t")))
    elif ratio < 8:
        iss.append(Issue("warn",
                         f"Smallest inside dimension is only {fmt(ratio, 1)}× the board thickness. It will probably "
                         f"work, but folds on thick board get bulky; aim for ≥ {fmt(8 * t)} {spec.units} or test first.",
                         (kmin, "t")))
    if t * mm > 12:
        iss.append(Issue("warn", "Board over 12 mm is thicker than typical scored / laser-folded cardboard; creases "
                                 "may crack instead of folding.", ("t",)))
    elif t * mm < 0.15:
        iss.append(Issue("warn", "Board under 0.15 mm: fold and cut lines nearly coincide at this scale. Check units.",
                         ("t",)))

    r = style.resolve(c)
    res.info["auto"] = r
    style.check(c, r, iss)
    if res.errors:
        return res

    # ---- build --------------------------------------------------------------------------------------
    try:
        panels, drawing = style.build(c, r)
        hand_drawn = drawing is not None
        if drawing is None:
            drawing = panels_to_drawing(panels, spec.folds)
        res.nominal = drawing
        kpan = panels
        if kerf > 0 and hand_drawn:
            kpan = style.kerf_panels(c, r) if hasattr(style, "kerf_panels") else None
            if kpan is None:
                iss.append(Issue("warn", "Kerf compensation is not available for this style yet; the dieline is "
                                         "at nominal size.", ("kerf",)))
        if kerf > 0 and kpan is not None:
            if kerf * mm > 1.0:
                iss.append(Issue("warn", "Kerf over 1 mm is unusual for a laser (typically 0.1-0.5 mm). Check the "
                                         "units.", ("kerf",)))
            try:
                drawing = kerf_drawing(kpan, drawing, kerf)
                res.info["kerf"] = kerf
                sw_ = getattr(drawing, "swallowed", [])
                if sw_:
                    iss.append(Issue("warn", f"The kerf is wider than a few tiny gaps in this layout, so {len(sw_)} very "
                                             f"short cut edge(s) were merged into their neighbours (near "
                                             f"{', '.join(f'({x:g}, {y:g})' for x, y in sw_[:3])}). Check those "
                                             f"corners on a test cut.", ("kerf",)))
                iss.append(Issue("info", f"Kerf compensation applied: cut lines moved {fmt(kerf / 2, 3)} "
                                         f"{spec.units} away from the parts (half the {fmt(kerf, 3)} kerf).", ()))
            except ValueError as exc:
                iss.append(Issue("error", f"Kerf compensation failed: {exc}. Reduce the kerf or enlarge the "
                                          f"small features.", ("kerf",)))
                return res
        if spec.perf and spec.folds:
            dash_mm, tie_mm = spec.perf_dash, spec.perf_tie
            drawing, nd, ns = perforate(drawing, dash_mm / mm, tie_mm / mm, res.info.get("kerf", 0.0))
            res.info["perf"] = (nd, ns)
            msg = (f"Fold lines drawn as dashed cuts ({nd} lines, {dash_mm:g} mm cuts with {tie_mm:g} mm bridges).")
            if ns:
                msg += f" {ns} short fold line{'s' if ns > 1 else ''} kept as scored lines."
            iss.append(Issue("info", msg, ()))
            if t * mm > 3 and tie_mm < 3:
                iss.append(Issue("warn", f"Dashed folds on thick board leave weak {tie_mm:g} mm bridges; test a "
                                         f"sample, board over 3 mm may need longer bridges.", ("t",)))
            if tie_mm > dash_mm:
                iss.append(Issue("warn", f"The bridges ({tie_mm:g} mm) are longer than the cuts ({dash_mm:g} mm), so "
                                         f"the fold may not bend cleanly. Lengthen the dashes or shorten the "
                                         f"bridges.", ("perf_dash", "perf_tie")))
        if spec.features:
            nf = apply_features(drawing, panels, spec.features, t, mm, kerf, iss)
            res.info["features"] = nf
            if any(f.kind != "window" for f in spec.features) and res.look["engrave_pt"] in (res.look["cut_pt"], res.look["fold_pt"]):
                iss.append(Issue("warn", "Engrave lines share a weight with cut or fold lines, so software that sorts "
                                         "by line weight cannot separate them.", ("engrave_weight",)))
            if nf:
                iss.append(Issue("info", f"{nf} window / zone feature{'s' if nf > 1 else ''} added.", ()))
        if True:                                           # tolerances for the drawing sheet (every style)
            fx0, fy0, fx1, fy1 = drawing.bounds()
            tv, ta, ti = resolve_tolerances(t * mm, (fx1 - fx0) * mm, (fy1 - fy0) * mm, spec.tol,
                                            getattr(style, "auto_tol", None))
            res.info["tol"] = dict(values=tv, auto=ta)
            for lvl, msg, key in ti:
                iss.append(Issue(lvl, msg, ("tol_" + key,)))
            if res.errors:
                return res
        res.panels, res.drawing = panels, drawing
    except Exception as exc:                                   # geometry that cannot be built cleanly
        iss.append(Issue("error", f"Could not build this geometry cleanly ({exc.__class__.__name__}: {exc}). "
                                  f"Try different dimensions.", ()))
        return res

    x0, y0, x1, y1 = drawing.bounds()
    if not all(map(math.isfinite, (x0, y0, x1, y1))):
        iss.append(Issue("error", "Geometry contains invalid numbers.", ()))
        return res
    res.info["flat"] = (x1 - x0, y1 - y0)

    bad = overlapping_panels(panels, max(1e-4, 0.01 * t))
    if bad:
        names_ = ", ".join(f"{a}/{b}" for a, b in bad[:3]) + (" …" if len(bad) > 3 else "")
        iss.append(Issue("error", f"Cut outlines overlap in the flat layout ({names_}), so the lines would cross. "
                                  f"Adjust the flap / panel sizes.", tuple(style_opt_keys(style))))

    sw, sh = spec.sheet
    if sw and sh and not bad:
        w, h = x1 - x0, y1 - y0
        if not ((w <= sw and h <= sh) or (w <= sh and h <= sw)):
            iss.append(Issue("warn", f"Flat layout ({fmt(w)} × {fmt(h)}) is larger than the sheet "
                                     f"({fmt(sw)} × {fmt(sh)}).", ("sheetw", "sheeth")))
        elif not (w <= sw and h <= sh):
            iss.append(Issue("info", "Fits the sheet only when rotated 90°.", ()))
    return res


def style_opt_keys(style):
    return [k for k, _ in style.options]


def default_spec(style, units="mm"):
    d = style.defaults
    k = 1.0 if units == "mm" else 1 / 25.4
    return Spec(d["L"] * k, d["W"] * k, d["H"] * k, d["t"] * k, "inner", units,
                {key: None for key, _ in style.options},
                True, {key: dflt for key, _, dflt in style.toggles})


