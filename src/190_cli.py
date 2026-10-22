def parse_feature_arg(kind, text, panels):
    """'--window back,60,40,4' (centred on a panel) or '--window 100,80,60,40,4' (X,Y,W,H,R on the flat sheet).
    Zones take an optional .svg path and 'border' / 'noborder' as extra items."""
    parts = [x.strip() for x in text.split(",") if x.strip()]
    extras = [x for x in parts if x.lower() in ("border", "noborder") or x.lower().endswith(".svg")]
    parts = [x for x in parts if x not in extras]
    art = next((import_svg(x) for x in extras if x.lower().endswith(".svg")), None)
    outline = True if "border" in [x.lower() for x in extras] else False if "noborder" in [x.lower() for x in extras] else None
    try:
        float(parts[0])
        nums = [float(x) for x in parts]
        if len(nums) < 4:
            raise ValueError
        cx, cy, w, h = nums[:4]
        r = nums[4] if len(nums) > 4 else 0.0
    except ValueError:
        by = {n: (cx, cy) for n, cx, cy, *_ in panel_centres(panels or [])}
        if parts[0] not in by:
            raise SystemExit(f"--{kind}: '{parts[0]}' is not a panel big enough to carry a feature. "
                             f"Use --list-panels to see the names and centres.")
        cx, cy = by[parts[0]]
        nums = [float(x) for x in parts[1:]]
        if len(nums) < 2:
            raise SystemExit(f"--{kind}: need PANEL,W,H" + (",R" if kind == "window" else ""))
        w, h = nums[:2]
        r = nums[2] if len(nums) > 2 else 0.0
    return Feature(kind, cx, cy, w, h, r, art=art, outline=outline)


def main(argv=None):
    """No arguments -> open the GUI.  With arguments -> headless export (handy for batch jobs)."""
    import argparse
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        safe_streams()
        return run_gui() or 0
    attach_console()                                 # a windowed program: print to the console it was started from
    if argv == ["--version"]:
        print(f"{APP_NAME} {__version__}")
        return 0
    ap = argparse.ArgumentParser(description="BoxForge - generate a box dieline without the GUI.")
    ap.add_argument("--version", action="store_true", help="print the version and exit")
    ap.add_argument("--style", required=True, choices=sorted(s.id for s in STYLES), help="box style")
    for k in ("L", "W", "H", "t"):
        ap.add_argument(f"--{k}", type=float, required=True)
    ap.add_argument("--mode", choices=["inner", "outer", "manufacturer"], default="inner")
    ap.add_argument("--units", choices=["mm", "in"], default="mm")
    ap.add_argument("--no-folds", action="store_true", help="leave the fold lines out")
    names = [n for n, _, _ in LINE_COLORS]
    ap.add_argument("--cut-color", default=LOOK_DEFAULTS["cut_color"], type=str.title,
                    help="cut line colour: " + ", ".join(names))
    ap.add_argument("--fold-color", default=LOOK_DEFAULTS["fold_color"], type=str.title,
                    help="fold line colour (same presets)")
    ap.add_argument("--cut-weight", type=float, default=LOOK_DEFAULTS["cut_weight"],
                    help="cut line weight in pt (SVG/PDF/EPS only; default 0.1)")
    ap.add_argument("--fold-weight", type=float, default=LOOK_DEFAULTS["fold_weight"],
                    help="fold line weight in pt (SVG/PDF/EPS only; default 1)")
    ap.add_argument("--engrave-color", default=LOOK_DEFAULTS["engrave_color"], type=str.title,
                    help="engrave (zone) line colour (same presets)")
    ap.add_argument("--engrave-weight", type=float, default=LOOK_DEFAULTS["engrave_weight"],
                    help="engrave line weight in pt (SVG/PDF/EPS only; default 0.5)")
    ap.add_argument("--window", action="append", default=[], metavar="SPEC",
                    help="rounded window: PANEL,W,H[,R] or X,Y,W,H[,R] (flat-sheet coordinates); repeatable")
    ap.add_argument("--info", action="append", default=[], metavar="SPEC",
                    help="info zone: PANEL,W,H[,file.svg][,border] or X,Y,W,H[,...]; repeatable")
    ap.add_argument("--logo", action="append", default=[], metavar="SPEC",
                    help="logo zone: PANEL,W,H[,file.svg][,border] or X,Y,W,H[,...]; repeatable")
    seen_tg = {}
    for st_ in STYLES:                                   # a switch of a style becomes a flag: --insert
        for key, label, _ in st_.toggles:
            seen_tg.setdefault(key, label)
    for key, label in seen_tg.items():
        ap.add_argument("--" + key.replace("_", "-"), dest="tg_" + key, action="store_true", help=label)
    ap.add_argument("--list-panels", action="store_true", help="print panel names, centres and sizes, then exit")
    ap.add_argument("--drawing", metavar="FILE.pdf", help="write a dimensioned drawing sheet ")
    ap.add_argument("--dwg-off", default="", metavar="LIST",
                    help="drawing blocks to leave out, comma separated: " + ",".join(b.cli for b in DRAWING_BLOCKS)
                    + " (" + ", ".join(f"{b.cli} = {b.note}" for b in DRAWING_BLOCKS if b.note) + ")")
    for k, _, _ in DRAWING_FIELDS:
        ap.add_argument("--dwg-" + k, default="", help=f"drawing title block: {k}")
    for k, lab in TOL_LABELS.items():
        ap.add_argument("--tol-" + k.replace("_", "-"), type=float, default=None,
                        help=f"drawing tolerance +/- mm: {lab.lower()} (default: automatic)")
    ap.add_argument("--stl", metavar="FILE.stl", help="write the flat cut blank as a 3-D solid, binary STL")
    ap.add_argument("--3mf", dest="threemf", metavar="FILE.3mf", help="same, as a 3MF file ")
    ap.add_argument("--dashed", action="store_true", help="draw fold lines as dashed cuts (perforation)")
    ap.add_argument("--dash", type=float, default=5.0, metavar="MM",
                    help="dashed folds: length of each cut, 1-20 mm (default 5; needs --dashed)")
    ap.add_argument("--bridge", type=float, default=2.0, metavar="MM",
                    help="dashed folds: uncut bridge between cuts, 0.5-10 mm (default 2; needs --dashed)")
    ap.add_argument("--material", choices=sorted(BEND_MATERIALS), default=BEND_DEFAULT,
                    help="bend model preset (typical values, not measured): sets the default bend radius, K-factor, springback")
    ap.add_argument("--bend-radius", type=float, default=None, metavar="R",
                    help="inside bend radius in the chosen units (default: the material preset x board thickness)")
    ap.add_argument("--bend-k", type=float, default=None, metavar="K", help="neutral-axis K-factor 0..0.5 (default: material preset)")
    ap.add_argument("--bend-report", action="store_true",
                    help="print bend angles, bend allowance / deduction per fold type and material usage ")
    ap.add_argument("--kerf", type=float, default=0.0, help="laser kerf (beam width) in the chosen units; 0 = off")
    ap.add_argument("--opt", action="append", default=[], metavar="KEY=VALUE",
                    help="advanced option (e.g. glue=25); repeat as needed")
    ap.add_argument("--flute", choices=("off", "vertical", "horizontal"), default="off",
                    help="corrugated flute direction on the flat sheet: marked on the drawing (label and arrow) "
                         "- vertical = along the sheet's up-down axis")
    for f in CLI_FORMATS:
        ap.add_argument("--" + f.flag, help=f"write a .{f.flag} file")
    for k, v in GCODE_DEFAULTS.items():
        ap.add_argument("--" + k.replace("_", "-"), type=float, default=v, help="G-code " + k.replace("_", " "))
    a = ap.parse_args(argv)
    st = STYLE_BY_ID[a.style]
    spec = default_spec(st, a.units)
    spec.L, spec.W, spec.H, spec.t, spec.mode, spec.folds = a.L, a.W, a.H, a.t, a.mode, not a.no_folds
    spec.kerf = a.kerf
    for key, _, _ in st.toggles:
        spec.flags[key] = bool(getattr(a, "tg_" + key, False))
    for key in seen_tg:
        if getattr(a, "tg_" + key, False) and key not in {k for k, _, _ in st.toggles}:
            print(f"[NOTE ] --{key.replace('_', '-')} does not apply to {st.name}; it was ignored.")
    spec.material, spec.bend_r, spec.bend_k = a.material, a.bend_radius, a.bend_k
    spec.perf = a.dashed
    spec.flute = {"vertical": "v", "horizontal": "h"}.get(a.flute)
    spec.perf_dash, spec.perf_tie = a.dash, a.bridge
    if not a.dashed and (a.dash != 5.0 or a.bridge != 2.0):
        print("[NOTE ] --dash and --bridge only apply with --dashed; they were ignored.")
    spec.look = dict(cut_color=a.cut_color, fold_color=a.fold_color, cut_weight=a.cut_weight,
                     fold_weight=a.fold_weight, engrave_color=a.engrave_color, engrave_weight=a.engrave_weight)
    for kv in a.opt:
        k, _, v = kv.partition("=")
        spec.opts[k] = float(v)
    spec.tol = {k: getattr(a, "tol_" + k) for k in TOL_LABELS if getattr(a, "tol_" + k) is not None}
    if a.list_panels or a.window or a.info or a.logo:
        base = generate(st, spec)
        if a.list_panels:
            for n, cx, cy, w, h, _ in panel_centres(base.panels or []):
                nd = 3 if a.units == "in" else 2
                print(f"{n:10s} centre ({cx:.{nd}f}, {cy:.{nd}f})  size {w:.{nd}f} x {h:.{nd}f} {a.units}")
            return 0
        try:
            spec.features = [parse_feature_arg(k, t, base.panels) for k, lst in
                             (("window", a.window), ("info", a.info), ("logo", a.logo)) for t in lst]
        except (ValueError, OSError) as exc:
            raise SystemExit(f"Could not read a window / zone option: {exc}")
    res = generate(st, spec)
    for i in res.issues:
        print(f"[{i.level.upper():5s}] {i.msg}")
    if not res.ok:
        print("Not exported: fix the errors above.")
        return 1
    lk = res.look
    head = f"BoxForge {st.name} L{fmt(a.L, 3)} W{fmt(a.W, 3)} H{fmt(a.H, 3)} t{fmt(a.t, 3)} {a.units} ({a.mode})"
    gc = {k: getattr(a, k) for k in GCODE_DEFAULTS}
    for kind, path in ((f.kind, getattr(a, f.flag)) for f in CLI_FORMATS):
        if path:
            notes = [head + f". CUT {lk['cut_name']}, FOLD {lk['fold_name']}"
                     + (f"; line weights cut {lk['cut_pt']:g} pt, fold {lk['fold_pt']:g} pt." if kind in WEIGHT_FORMATS
                        else ".")] + res.notes()
            if kind not in WEIGHT_FORMATS and (a.cut_weight != LOOK_DEFAULTS["cut_weight"]
                                              or a.fold_weight != LOOK_DEFAULTS["fold_weight"]):
                print(f"[NOTE ] {WEIGHT_NOTE} Weights were not applied to {path}.")
            data = render_export(kind, res.drawing, a.units, notes, gc, lk)
            with open(path, "wb" if isinstance(data, bytes) else "w", **({} if isinstance(data, bytes) else {"encoding": "utf-8"})) as fh:
                fh.write(data)
            print("wrote", path)
    if a.bend_report:
        print(bend_report_text(bend_report(res, spec), a.units))
    if a.drawing:
        off = {x.strip() for x in a.dwg_off.split(",") if x.strip()}
        blocks = drawing_blocks_from_off(off, {k: getattr(a, "dwg_" + k) for k, _, _ in DRAWING_FIELDS})
        with open(a.drawing, "wb") as fh:
            fh.write(drawing_pdf(res, spec, blocks))
        print("wrote", a.drawing)
    for kind, path in (("stl", a.stl), ("3mf", a.threemf)):
        if path:
            data, m = model_export(res, spec, kind)
            if m.open_edges():
                print("[ERROR] the solid model has gaps; not written.")
                return 1
            with open(path, "wb") as fh:
                fh.write(data)
            print("wrote", path)
            for line in model_notes(m):
                print("[NOTE ]", line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

