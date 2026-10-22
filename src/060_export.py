# =============================================================================
# Line colours and weights
#   Every preset is an exact AutoCAD colour-index (ACI) colour, so DXF exports carry the same colour.
#   Weights are written exactly (points) into SVG, PDF and EPS; DXF (R12), HPGL and G-code cannot carry them.
# =============================================================================
LINE_COLORS = [("Blue", "#0000FF", 5), ("Red", "#FF0000", 1), ("Black", "#000000", 7), ("Green", "#00FF00", 3),
               ("Cyan", "#00FFFF", 4), ("Magenta", "#FF00FF", 6), ("Yellow", "#FFFF00", 2),
               ("Orange", "#FF7F00", 30), ("Amber", "#FFBF00", 40), ("Lime", "#7FFF00", 70),
               ("Spring green", "#00FF7F", 110), ("Sky blue", "#007FFF", 150), ("Violet", "#7F00FF", 190),
               ("Pink", "#FF007F", 230), ("Gray", "#808080", 8), ("Light gray", "#C0C0C0", 9)]
LOOK_DEFAULTS = dict(cut_color="Blue", fold_color="Red", cut_weight=0.1, fold_weight=1.0,
                     engrave_color="Green", engrave_weight=0.5)
WEIGHT_NOTE = "Custom line weights apply to SVG, PDF and EPS only."


def resolve_look(look=None):
    """Validate a {cut_color, fold_color, cut_weight, fold_weight} dict -> hex / ACI / points for the writers."""
    lk = dict(LOOK_DEFAULTS)
    lk.update({k: v for k, v in (look or {}).items() if v is not None})
    by = {n.lower(): (h, a, n) for n, h, a in LINE_COLORS}
    out = {}
    for layer in ("cut", "fold", "engrave"):
        key = str(lk[layer + "_color"]).strip().lower()
        if key not in by:
            raise ValueError(f"unknown {layer} colour '{lk[layer + '_color']}'")
        out[layer + "_hex"], out[layer + "_aci"], out[layer + "_name"] = by[key]
        w = float(lk[layer + "_weight"])
        if not math.isfinite(w) or w <= 0:
            raise ValueError(f"{layer} weight must be a number greater than zero")
        out[layer + "_pt"] = w
    return out


def _rgb01(hexs):
    return tuple(int(hexs[i:i + 2], 16) / 255 for i in (1, 3, 5))


def view_color(hexs):
    """Colour used on the dark preview canvas: dark presets are lightened so they stay visible."""
    r, g, b = (int(hexs[i:i + 2], 16) for i in (1, 3, 5))
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    if lum < 0.45:
        t = 0.45 if lum < 0.1 else 0.3
        r, g, b = (round(c + (255 - c) * t) for c in (r, g, b))
        if lum < 0.05:
            r = g = b = 225
    return f"#{r:02x}{g:02x}{b:02x}"


# =============================================================================
# Exporters
# =============================================================================
def to_dxf(d, units="mm", notes=(), look=None):
    lk = look or resolve_look()
    out = []
    w = lambda code, val: out.extend([str(code), str(val)])
    f = lambda v: f"{v:.5f}"
    w(999, "BoxForge DXF - drawing units: " + ("millimetres" if units == "mm" else "inches")
      + " (also stored in $INSUNITS; some importers ignore it, so check the scale on import)")
    for n in notes:
        w(999, n.replace("\n", " ")[:240])
    w(0, "SECTION"); w(2, "HEADER")
    w(9, "$ACADVER"); w(1, "AC1009")
    w(9, "$INSUNITS"); w(70, 4 if units == "mm" else 1)
    w(0, "ENDSEC")
    w(0, "SECTION"); w(2, "TABLES")
    w(0, "TABLE"); w(2, "LTYPE"); w(70, 1)
    w(0, "LTYPE"); w(2, "CONTINUOUS"); w(70, 0); w(3, "Solid line"); w(72, 65); w(73, 0); w(40, "0.0")
    w(0, "ENDTAB")
    w(0, "TABLE"); w(2, "LAYER"); w(70, 3)
    for name, col in ((CUT, lk["cut_aci"]), (FOLD, lk["fold_aci"]), (ENGRAVE, lk["engrave_aci"])):
        w(0, "LAYER"); w(2, name); w(70, 0); w(62, col); w(6, "CONTINUOUS")
    w(0, "ENDTAB")
    w(0, "ENDSEC")
    w(0, "SECTION"); w(2, "ENTITIES")
    for it in d.items:
        if it[0] == "L":
            _, p, q, layer = it
            w(0, "LINE"); w(8, layer)
            w(10, f(p[0])); w(20, f(p[1])); w(30, "0.0")
            w(11, f(q[0])); w(21, f(q[1])); w(31, "0.0")
        else:
            _, c, r, a0, a1, layer = it
            w(0, "ARC"); w(8, layer)
            w(10, f(c[0])); w(20, f(c[1])); w(30, "0.0")
            w(40, f(r)); w(50, f(a0)); w(51, f(a1))
    w(0, "ENDSEC"); w(0, "EOF")
    return "\n".join(out) + "\n"


def _xml(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _chain_segs(segs, eps=1e-3):
    """Join segments (p, q, arc) that share endpoints into chains, reversing where needed.
    An arc is (radius, large_flag, sweep_flag); reversing one flips its sweep.
    Slits that end free (a cut that stops inside the board, or runs out onto an outline) are set aside first, so the
    segments left form closed loops and each comes out as one closed chain; the slits follow as open chains of their own."""
    segs = list(segs)
    pts = [pt for sg in segs for pt in sg[:2]]
    out = []
    for a, b, arc in segs:                            # split a line wherever another segment's end lands on it (a T-junction)
        if arc is None:
            L2 = (b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2
            cuts = []
            for pt in pts:
                if L2 > 0:
                    u = ((pt[0] - a[0]) * (b[0] - a[0]) + (pt[1] - a[1]) * (b[1] - a[1])) / L2
                    if 0 < u < 1 and math.dist(pt, (a[0] + u * (b[0] - a[0]), a[1] + u * (b[1] - a[1]))) < eps \
                            and math.dist(pt, a) > eps and math.dist(pt, b) > eps:
                        cuts.append((u, pt))
            if cuts:
                cuts.sort()
                chain_pts = [a] + [pt for _, pt in cuts] + [b]
                for k in range(len(chain_pts) - 1):
                    if math.dist(chain_pts[k], chain_pts[k + 1]) > eps:
                        out.append((chain_pts[k], chain_pts[k + 1], None))
                continue
        out.append((a, b, arc))
    segs = out
    n = len(segs)

    def flip(sg):
        a, b, arc = sg
        return (b, a, None if arc is None else (arc[0], arc[1], 1 - arc[2]))

    def heading(a, b):
        return math.atan2(b[1] - a[1], b[0] - a[0])

    core = set(range(n))
    changed = True
    while changed:                                     # peel off segments with a free end, repeatedly
        changed = False
        for i in sorted(core):
            for pt in segs[i][:2]:
                if not any(j != i and (math.dist(segs[j][0], pt) < eps or math.dist(segs[j][1], pt) < eps) for j in core):
                    core.discard(i)
                    changed = True
                    break

    def build(allowed):
        used = {i: False for i in allowed}

        def pick(point, direction):
            best, bi, bflip = None, None, False
            for i in allowed:
                if used[i]:
                    continue
                sg = segs[i]
                for fl, (p, q) in ((False, (sg[0], sg[1])), (True, (sg[1], sg[0]))):
                    if math.dist(p, point) < eps:
                        turn = abs((heading(p, q) - direction + math.pi) % (2 * math.pi) - math.pi)
                        if best is None or turn < best:
                            best, bi, bflip = turn, i, fl
            return bi, bflip

        out = []
        for i0 in sorted(allowed):
            if used[i0]:
                continue
            used[i0] = True
            chain = [segs[i0]]
            while not (len(chain) > 1 and math.dist(chain[-1][1], chain[0][0]) < eps):
                i, fl = pick(chain[-1][1], heading(*chain[-1][:2]))
                if i is None:
                    break
                used[i] = True
                chain.append(flip(segs[i]) if fl else segs[i])
            if not (len(chain) > 1 and math.dist(chain[-1][1], chain[0][0]) < eps):
                while True:                            # an open chain: also grow it backwards from its start
                    i, fl = pick(chain[0][0], heading(chain[0][1], chain[0][0]))
                    if i is None:
                        break
                    used[i] = True
                    chain.insert(0, segs[i] if fl else flip(segs[i]))
            out.append(chain)
        return out

    return build(core) + build(set(range(n)) - core)


def to_svg(d, units="mm", margin=5.0, notes=(), look=None):
    """SVG at true size. Coordinates are in points (1 user unit = 1 pt), so stroke-width is the exact weight in pt."""
    lk = look or resolve_look()
    k = 72 / 25.4 if units == "mm" else 72.0
    x0, y0, x1, y1 = d.bounds()
    mg = margin if units == "mm" else margin / 25.4
    x0 -= mg; y0 -= mg; x1 += mg; y1 += mg
    W, H = (x1 - x0) * k, (y1 - y0) * k
    X = lambda x: (x - x0) * k
    Y = lambda y: (y1 - y) * k
    groups = {CUT: [], FOLD: [], ENGRAVE: []}
    segs = {CUT: [], FOLD: [], ENGRAVE: []}
    for it in d.items:
        if it[0] == "L":
            _, p, q, layer = it
            segs[layer].append((tuple(p), tuple(q), None))
        else:
            _, c, r, a0, a1, layer = it
            span = (a1 - a0) % 360
            sx, sy = c[0] + r * math.cos(math.radians(a0)), c[1] + r * math.sin(math.radians(a0))
            ex_, ey = c[0] + r * math.cos(math.radians(a1)), c[1] + r * math.sin(math.radians(a1))
            segs[layer].append(((sx, sy), (ex_, ey), (r, 1 if span > 180 else 0, 0)))
    eps = 0.001 / (25.4 if units == "in" else 1.0)     # 1 micron: the rebuilt edges differ by ~1e-6 in an inch job
    for layer, sl in segs.items():
        for chain in _chain_segs(sl, eps):
            a = chain[0][0]
            dstr = f"M {X(a[0]):.4f} {Y(a[1]):.4f}"
            for (pa, pb, arc) in chain:
                if arc is None:
                    dstr += f" L {X(pb[0]):.4f} {Y(pb[1]):.4f}"
                else:
                    r_, large, sweep = arc
                    dstr += f" A {r_ * k:.4f} {r_ * k:.4f} 0 {large} {sweep} {X(pb[0]):.4f} {Y(pb[1]):.4f}"
            closed = math.dist(chain[0][0], chain[-1][1]) < eps and len(chain) > 1
            groups[layer].append(f'<path d="{dstr}{" Z" if closed else ""}"/>')
    spec = {CUT: (lk["cut_hex"], lk["cut_pt"]), FOLD: (lk["fold_hex"], lk["fold_pt"]),
            ENGRAVE: (lk["engrave_hex"], lk["engrave_pt"])}
    body = "\n".join(
        f'<g id="{key}" fill="none" stroke="{spec[key][0]}" stroke-width="{spec[key][1]:g}" '
        f'stroke-linecap="round">\n' + "\n".join(v) + "\n</g>" for key, v in groups.items() if v or key != ENGRAVE)
    desc = f"<desc>{_xml(' | '.join(notes))}</desc>\n" if notes else ""
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.4f}pt" height="{H:.4f}pt" '
            f'viewBox="0 0 {W:.4f} {H:.4f}">\n{desc}{body}\n</svg>\n')


# =============================================================================
# More export formats: PDF, EPS, HPGL, G-code
# =============================================================================
GCODE_DEFAULTS = dict(cut_power=1000, cut_feed=600, cut_passes=1, fold_power=200, fold_feed=1500, fold_passes=1,
                      engrave_power=250, engrave_feed=3000, engrave_passes=1)


def _flatten(d, units="mm"):
    """{layer: [polyline, ...]} with arcs flattened to <= 0.01 mm chord error."""
    tol = 0.01 / (25.4 if units == "in" else 1.0)
    out = {CUT: [], FOLD: [], ENGRAVE: []}
    for it in d.items:
        if it[0] == "L":
            out[it[-1]].append([it[1], it[2]])
        else:
            _, c, r, a0, a1, layer = it
            span = (a1 - a0) % 360 or 360
            step = math.degrees(2 * math.acos(max(0.0, 1 - tol / r))) if r > tol else 30.0
            n = max(2, int(math.ceil(span / max(step, 0.5))))
            out[layer].append([(c[0] + r * math.cos(math.radians(a0 + span * k / n)),
                                c[1] + r * math.sin(math.radians(a0 + span * k / n))) for k in range(n + 1)])
    return out


def _ascii(s):
    return s.encode("ascii", "replace").decode("ascii").replace("\n", " ")


def to_pdf(d, units="mm", margin=5.0, notes=(), look=None):
    """Vector PDF at true size (1 page, exact line weights in pt). Returns bytes."""
    lk = look or resolve_look()
    k = 72 / 25.4 if units == "mm" else 72.0
    mg = margin if units == "mm" else margin / 25.4
    x0, y0, x1, y1 = d.bounds()
    x0 -= mg; y0 -= mg; x1 += mg; y1 += mg
    W, H = (x1 - x0) * k, (y1 - y0) * k
    fl = _flatten(d, units)
    cs = ["1 J 1 j"]
    for layer, hx, wt in ((FOLD, lk["fold_hex"], lk["fold_pt"]), (ENGRAVE, lk["engrave_hex"], lk["engrave_pt"]),
                          (CUT, lk["cut_hex"], lk["cut_pt"])):
        cs.append(f"{wt:g} w")
        cs.append(" ".join(f"{c:.4f}".rstrip("0").rstrip(".") or "0" for c in _rgb01(hx)) + " RG")
        for pl in fl[layer]:
            pts = [f"{(p[0] - x0) * k:.3f} {(p[1] - y0) * k:.3f}" for p in pl]
            cs.append(pts[0] + " m " + " ".join(q + " l" for q in pts[1:]) + " S")
    stream = ("\n".join(cs)).encode("ascii")
    esc = lambda s: _ascii(s).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W:.2f} {H:.2f}] /Contents 4 0 R /Resources << >> >>".encode(),
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            f"<< /Title (BoxForge dieline) /Subject ({esc(' | '.join(notes))}) /Creator (BoxForge) >>".encode()]
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xr = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info 5 0 R >>\nstartxref\n{xr}\n%%EOF\n".encode()
    return bytes(out)


def to_eps(d, units="mm", margin=5.0, notes=(), look=None):
    """Encapsulated PostScript at true size (opens in Illustrator / Inkscape / Ghostscript).
    Coordinates are pre-scaled to points, so setlinewidth is the exact weight in pt."""
    lk = look or resolve_look()
    k = 72 / 25.4 if units == "mm" else 72.0
    mg = margin if units == "mm" else margin / 25.4
    x0, y0, x1, y1 = d.bounds()
    x0 -= mg; y0 -= mg; x1 += mg; y1 += mg
    W, H = (x1 - x0) * k, (y1 - y0) * k
    o = ["%!PS-Adobe-3.0 EPSF-3.0", f"%%BoundingBox: 0 0 {int(math.ceil(W))} {int(math.ceil(H))}",
         "%%Creator: BoxForge", "%%EndComments"]
    o += ["% " + _ascii(n) for n in notes]
    o += ["1 setlinecap 1 setlinejoin"]
    X = lambda x: (x - x0) * k
    Y = lambda y: (y - y0) * k
    for layer, hx, wt in ((FOLD, lk["fold_hex"], lk["fold_pt"]), (ENGRAVE, lk["engrave_hex"], lk["engrave_pt"]),
                          (CUT, lk["cut_hex"], lk["cut_pt"])):
        o.append(f"{wt:g} setlinewidth")
        o.append(" ".join(f"{c:.4f}".rstrip("0").rstrip(".") or "0" for c in _rgb01(hx)) + " setrgbcolor")
        for it in d.items:
            if it[-1] != layer:
                continue
            if it[0] == "L":
                o.append(f"newpath {X(it[1][0]):.4f} {Y(it[1][1]):.4f} moveto {X(it[2][0]):.4f} "
                         f"{Y(it[2][1]):.4f} lineto stroke")
            else:
                _, c, r, a0, a1, _l = it
                if a1 <= a0:
                    a1 += 360
                o.append(f"newpath {X(c[0]):.4f} {Y(c[1]):.4f} {r * k:.4f} {a0:.4f} {a1:.4f} arc stroke")
    o.append("showpage")
    return "\n".join(o) + "\n"


def to_hpgl(d, units="mm", notes=()):
    """HPGL (.plt), 40 units/mm. Pen 3 = ENGRAVE, pen 2 = FOLD, pen 1 = CUT. Origin = bottom-left of the sheet."""
    s = 40.0 if units == "mm" else 1016.0
    x0, y0, _x1, _y1 = d.bounds()
    fl = _flatten(d, units)
    o = ["IN;"]
    for layer, pen in ((FOLD, 2), (ENGRAVE, 3), (CUT, 1)):
        o.append(f"SP{pen};")
        for pl in fl[layer]:
            pts = [(int(round((p[0] - x0) * s)), int(round((p[1] - y0) * s))) for p in pl]
            o.append(f"PU{pts[0][0]},{pts[0][1]};PD" + ",".join(f"{x},{y}" for x, y in pts[1:]) + ";")
    o += ["PU;", "SP0;"]
    return "\n".join(o) + "\n"


def to_gcode(d, units="mm", notes=(), **kw):
    """GRBL-style laser G-code in mm (M4 dynamic power). Engraving first, then scores, then cuts. Origin = bottom-left."""
    p = dict(GCODE_DEFAULTS)
    p.update(kw)
    m = 25.4 if units == "in" else 1.0
    x0, y0, _x1, _y1 = d.bounds()
    fx = lambda v: (v - x0) * m
    fy = lambda v: (v - y0) * m
    out = [f"( {_ascii(n).replace('(', '[').replace(')', ']')} )" for n in notes]
    out.append("( GRBL laser mode: set $32=1 first so S power follows motion; M4 needs it. Not tested on every controller. )")
    out += ["G21 G90 G17", "M5"]
    for layer, pw, fd, ps in ((ENGRAVE, p["engrave_power"], p["engrave_feed"], p["engrave_passes"]),
                              (FOLD, p["fold_power"], p["fold_feed"], p["fold_passes"]),
                              (CUT, p["cut_power"], p["cut_feed"], p["cut_passes"])):
        prims = []
        for it in d.items:
            if it[-1] != layer:
                continue
            if it[0] == "L":
                prims.append(("L", (fx(it[1][0]), fy(it[1][1])), (fx(it[2][0]), fy(it[2][1])), None, 0))
            else:
                _, c, r, a0, a1, _l = it
                pa = (fx(c[0] + r * math.cos(math.radians(a0))), fy(c[1] + r * math.sin(math.radians(a0))))
                pb = (fx(c[0] + r * math.cos(math.radians(a1))), fy(c[1] + r * math.sin(math.radians(a1))))
                prims.append(("A", pa, pb, (fx(c[0]), fy(c[1])), r * m))
        if not prims:
            continue
        out.append(f"( {'SCORE' if layer == FOLD else 'ENGRAVE' if layer == ENGRAVE else 'CUT'} layer: S{int(pw)} F{fd:g} x{int(ps)} pass(es) )")
        out.append(f"M4 S{int(pw)}")
        for n in range(int(ps)):
            todo, cur = list(prims), (0.0, 0.0)
            while todo:
                best, bi, brev = None, 0, False
                for i, pr in enumerate(todo):
                    for rev in (False, True):
                        a = pr[2] if rev else pr[1]
                        dd = (a[0] - cur[0]) ** 2 + (a[1] - cur[1]) ** 2
                        if best is None or dd < best:
                            best, bi, brev = dd, i, rev
                kind, a, b, c, r = todo.pop(bi)
                if brev:
                    a, b = b, a
                if math.dist(a, cur) > 1e-4:
                    out.append(f"G0 X{a[0]:.3f} Y{a[1]:.3f}")
                if kind == "L":
                    out.append(f"G1 X{b[0]:.3f} Y{b[1]:.3f} F{fd:g}")
                else:
                    out.append(f"{'G2' if brev else 'G3'} X{b[0]:.3f} Y{b[1]:.3f} I{c[0] - a[0]:.3f} "
                               f"J{c[1] - a[1]:.3f} F{fd:g}")
                cur = b
        out.append("M5")
    out += ["G0 X0 Y0", "M2"]
    return "\n".join(out) + "\n"


# ---- export-format registry -------------------------------------------------
# To add a format: write `to_xxx(d, units, notes, look, gcode)`-style code, then register it
# once here.  The GUI export row, the CLI flag (--<flag>) and render_export() all read this list.
class ExportFormat:
    def __init__(self, kind, label, render, flag=None, weights=False, cli_rank=None):
        self.kind, self.label, self.render = kind, label, render
        self.flag = flag or kind          # CLI option name: --<flag> PATH
        self.cli_rank = cli_rank          # position among the CLI flags / "wrote" lines (default: GUI order)
        self.weights = weights            # True when custom cut/fold line weights apply


EXPORT_REGISTRY = []
EXPORT_BY_KIND = {}


def register_export(kind, label, render, flag=None, weights=False, cli_rank=None):
    """render(d, units, notes, gcode, look) -> str | bytes"""
    f = ExportFormat(kind, label, render, flag, weights, cli_rank)
    EXPORT_REGISTRY.append(f)
    EXPORT_BY_KIND[kind] = f
    _refresh_export_views()
    return f


def _refresh_export_views():
    """Keep the derived lists in step with the registry (they are edited in place so importers see the change)."""
    CLI_FORMATS[:] = sorted(EXPORT_REGISTRY, key=lambda f: f.cli_rank if f.cli_rank is not None else 99)
    EXPORT_FORMATS[:] = [(f.kind, f.label) for f in EXPORT_REGISTRY]
    WEIGHT_FORMATS[:] = [f.kind for f in EXPORT_REGISTRY if f.weights]


CLI_FORMATS, EXPORT_FORMATS, WEIGHT_FORMATS = [], [], []         # flag order / GUI row / formats with line weights


register_export("dxf", "DXF", lambda d, u, n, g, lk: to_dxf(d, u, n, lk), cli_rank=1)
register_export("svg", "SVG", lambda d, u, n, g, lk: to_svg(d, u, notes=n, look=lk), weights=True, cli_rank=0)
register_export("pdf", "PDF", lambda d, u, n, g, lk: to_pdf(d, u, notes=n, look=lk), weights=True, cli_rank=2)
register_export("eps", "EPS", lambda d, u, n, g, lk: to_eps(d, u, notes=n, look=lk), weights=True, cli_rank=3)
register_export("plt", "HPGL", lambda d, u, n, g, lk: to_hpgl(d, u, n), cli_rank=4)
register_export("nc", "G-code", lambda d, u, n, g, lk: to_gcode(d, u, n, **(g or {})), flag="gcode", cli_rank=5)
