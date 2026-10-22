# =============================================================================
# Drawing tolerances (RSC). Values in millimetres, plus/minus.
# =============================================================================
TOL_LABELS = {
    "panel": "Panel width / height (score to score)",
    "flap": "Flap length (score to cut)",
    "slot": "Slot width",
    "glue": "Glue flap width",
    "overall_len": "Overall blank length",
    "overall_h": "Overall blank height",
    "box": "Finished box size",
}
TOL_MIN_MM, TOL_MAX_MM = 0.1, 10.0


def _r05(x):
    """Round to the nearest 0.5 mm (halves round up)."""
    return math.floor(x * 2 + 0.5) / 2


def auto_tolerances(t_mm, len_mm, h_mm):
    """Typical corrugated-converter tolerances, +/- mm, scaled with board thickness.
    Score-to-score +/-1.5 mm on ~3 mm board (rising ~0.2 mm per mm of board), flaps and slots slightly looser
    because they are cut, glue flap and overall blank about twice the score tolerance, +0.5 mm per 500 mm of
    blank beyond 1 m."""
    panel = _r05(max(1.0, 1.0 + 0.2 * t_mm))
    extra = lambda size: 0.5 * math.floor(max(0.0, size - 1000.0) / 500.0)
    return {
        "panel": panel,
        "flap": panel + 0.5,
        "slot": _r05(max(1.0, 0.25 * t_mm + 0.5)),
        "glue": _r05(max(2.0, 2 * panel)),
        "overall_len": _r05(2 * panel + extra(len_mm)),
        "overall_h": _r05(2 * panel + extra(h_mm)),
        "box": _r05(2 * panel),
    }


def resolve_tolerances(t_mm, len_mm, h_mm, override=None, style_auto=None):
    """-> (values, auto_flags, issues[(level, msg, key)]). `override` maps key -> mm (None/blank = automatic)."""
    vals = auto_tolerances(t_mm, len_mm, h_mm)
    vals.update(style_auto or {})                      # a style whose parts are cut tighter than a die-cut flap slot
    auto = {k: True for k in vals}
    issues = []
    for k, v in (override or {}).items():
        if k not in vals or v is None:
            continue
        if not isinstance(v, (int, float)) or not math.isfinite(v) or not TOL_MIN_MM <= v <= TOL_MAX_MM:
            issues.append(("error", f"{TOL_LABELS.get(k, k)} tolerance must be between {TOL_MIN_MM:g} and "
                                    f"{TOL_MAX_MM:g} mm.", k))
            continue
        vals[k], auto[k] = float(v), False
        if v < 0.25:
            issues.append(("warn", f"{TOL_LABELS[k]} tolerance of ±{v:g} mm is tighter than corrugated board can "
                                   f"reliably hold.", k))
        elif v > 5:
            issues.append(("warn", f"{TOL_LABELS[k]} tolerance of ±{v:g} mm is very loose.", k))
    return vals, auto, issues


