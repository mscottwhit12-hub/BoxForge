# =============================================================================
# Window cut-outs and info / logo zones
# =============================================================================
FEATURE_KINDS = ("window", "info", "logo")


class Feature:
    """A window (cut hole) or an info / logo zone (engraved) placed freely on the flat sheet.
    All lengths are in the user's units; (cx, cy) is the centre in dieline coordinates."""

    def __init__(self, kind, cx, cy, w, h, r=0.0, art=None, outline=None, rot=0):
        if kind not in FEATURE_KINDS:
            raise ValueError(f"Unknown feature kind '{kind}'.")
        self.kind, self.cx, self.cy, self.w, self.h, self.r = kind, cx, cy, w, h, r
        self.art = art                                   # Artwork (always mm) or None
        self.outline = (kind == "info") if outline is None else outline   # draw the zone border
        self.rot = rot                                   # 0 or 90 (artwork turned a quarter turn)

    def label(self):
        return {"window": "Window", "info": "Info zone", "logo": "Logo zone"}[self.kind]


def _rrect_pts(cx, cy, w, h, r, n=6):
    r = max(0.0, min(r, w / 2, h / 2))
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    if r <= 1e-9:
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    pts = []
    for (ccx, ccy), a0 in (((x1 - r, y0 + r), -90), ((x1 - r, y1 - r), 0), ((x0 + r, y1 - r), 90), ((x0 + r, y0 + r), 180)):
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            pts.append((ccx + r * math.cos(a), ccy + r * math.sin(a)))
    return pts


def _pip(p, poly):
    x, y, inside = p[0], p[1], False
    for i in range(len(poly)):
        a, b = poly[i], poly[i - 1]
        if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
            inside = not inside
    return inside


def _pt_seg(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def _seg_seg(a, b, c, d):
    def o(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return o(a, b, c) * o(a, b, d) < 0 and o(c, d, a) * o(c, d, b) < 0


def _poly_dist(pts, segs):
    """Smallest distance between the closed polyline `pts` and any segment (0 when they cross)."""
    m = float("inf")
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        for c, d in segs:
            if _seg_seg(a, b, c, d):
                return 0.0
            m = min(m, _pt_seg(a, c, d), _pt_seg(b, c, d), _pt_seg(c, a, b), _pt_seg(d, a, b))
    return m


def _poly_poly_dist(p, q):
    return _poly_dist(p, [(q[i], q[(i + 1) % len(q)]) for i in range(len(q))])


def _loop_len_edges(poly):
    return [(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly))]


def _poly_area(poly):
    return abs(sum(poly[i - 1][0] * poly[i][1] - poly[i][0] * poly[i - 1][1] for i in range(len(poly)))) / 2


def _drawing_segments(d):
    out = []
    for it in d.items:
        if it[0] == "L":
            out.append((it[1], it[2]))
        else:
            _, c, r, a0, a1, _l = it
            sw = (a1 - a0) % 360 or 360
            n = max(3, int(sw / 10))
            pts = [_arc_pt(c, r, a0 + sw * i / n) for i in range(n + 1)]
            out += list(zip(pts, pts[1:]))
    return out


def panel_centres(panels):
    """[(name, cx, cy, w, h, area)] for the panels big enough to carry a feature, biggest first."""
    rows = []
    for p in panels:
        xs, ys = [q[0] for q in p.poly], [q[1] for q in p.poly]
        rows.append((p.name, (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, max(xs) - min(xs),
                     max(ys) - min(ys), _poly_area(p.poly)))
    rows.sort(key=lambda r: -r[5])
    if rows:
        rows = [r for r in rows if r[5] >= 0.2 * rows[0][5]]
    return rows


def apply_features(drawing, panels, feats, t, mm, kerf, iss):
    """Add the features to `drawing` (in place) and append Issues. Returns the number of features added.
    Structural rules (errors stop the export):
      * the feature must sit wholly on ONE panel, clear of its edges, folds and slits;
      * windows keep a rim of at least max(3 mm, 2 x board thickness) to every other cut or fold line;
      * a window may take at most 65 % of its panel (warning above 50 %), corner radius at most half the
        short side (warning below 1 mm, where cardboard tears);
      * windows keep a rim to each other, zones may not overlap a window."""
    if not feats:
        return 0
    segs = _drawing_segments(drawing)
    cand = [p for p in panels if _poly_area(p.poly) >= 0.2 * max(_poly_area(q.poly) for q in panels)]
    rim_w = max(3.0 / mm, 2 * t)
    rim_z = max(1.0 / mm, 0.5 * t)
    placed = []                                                     # (feature, outline pts, host name)
    n_ok = 0
    win_area = {}
    for i, f in enumerate(feats, 1):
        tag = f"{f.label()} {i}"
        key = ("feat",)
        vals = (f.cx, f.cy, f.w, f.h, f.r)
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vals):
            iss.append(Issue("error", f"{tag}: position and size must be numbers.", key))
            continue
        if f.w <= 0 or f.h <= 0 or f.r < 0:
            iss.append(Issue("error", f"{tag}: width and height must be positive and the corner radius not negative.", key))
            continue
        w, h, r = f.w, f.h, f.r
        win = f.kind == "window"
        if win:
            if min(w, h) < max(3.0 / mm, 2 * t):
                iss.append(Issue("error", f"{tag}: a window narrower than {fmt(max(3.0 / mm, 2 * t))} "
                                          f"{'in' if mm > 1 else 'mm'} will not hold its rim. Make it bigger.", key))
                continue
            if r > min(w, h) / 2 + 1e-9:
                iss.append(Issue("error", f"{tag}: the corner radius cannot exceed half the short side "
                                          f"({fmt(min(w, h) / 2)}).", key))
                continue
            if 0 < r < 1.0 / mm:
                iss.append(Issue("warn", f"{tag}: corners tighter than 1 mm tend to tear in cardboard; use a "
                                         f"slightly larger radius.", key))
            if r == 0:
                iss.append(Issue("warn", f"{tag}: square corners concentrate stress and can split. A radius of 2 mm "
                                         f"or more is safer.", key))
        out = _rrect_pts(f.cx, f.cy, w, h, r if win else 0.0)
        host = next((p for p in cand if _pip((f.cx, f.cy), p.poly)), None)
        if host is None:
            iss.append(Issue("error", f"{tag}: the centre is not on a panel big enough to carry it. Move it onto a "
                                      f"main face.", key))
            continue
        rim = rim_w if win else rim_z
        if not all(_pip(p, host.poly) for p in out) or _poly_dist(out, _loop_len_edges(host.poly)) < rim - 1e-9:
            iss.append(Issue("error", f"{tag}: it runs across the edge of the '{host.name}' panel or comes closer "
                                      f"than {fmt(rim)} {'in' if mm > 1 else 'mm'} to an edge. Keep it fully inside one "
                                      f"panel; a hole over a fold or cut line breaks the box.", key))
            continue
        gap = _poly_dist(out, segs)
        if gap < rim - 1e-9:
            iss.append(Issue("error", f"{tag}: it is only {fmt(gap)} {'in' if mm > 1 else 'mm'} from an existing cut or "
                                      f"fold line (needs {fmt(rim)}). Move it toward the middle of the panel.", key))
            continue
        bad = False
        for g, og, hn, gtag in placed:
            if g.kind == "window" or win:
                need = rim_w if (g.kind == "window" and win) else rim_z
                if _poly_poly_dist(out, og) < need - 1e-9 or _pip(out[0], og) or _pip(og[0], out):
                    iss.append(Issue("error", f"{tag}: too close to or overlapping {gtag}. Keep "
                                              f"{fmt(need)} {'in' if mm > 1 else 'mm'} apart.", key))
                    bad = True
                    break
            elif _poly_poly_dist(out, og) < 1e-9 or _pip(out[0], og) or _pip(og[0], out):
                iss.append(Issue("warn", f"{tag}: overlaps {gtag}; the engraving will be doubled up.", key))
        if bad:
            continue
        if win:
            a = _poly_area(out) if r == 0 else w * h - (4 - math.pi) * r * r
            frac = (win_area.get(host.name, 0.0) + a) / _poly_area(host.poly)
            win_area[host.name] = win_area.get(host.name, 0.0) + a
            if frac > 0.65:
                iss.append(Issue("error", f"{tag}: windows would take {frac * 100:.0f}% of the '{host.name}' panel "
                                          f"(limit 65%). The panel would sag and crush.", key))
                continue
            if frac > 0.5:
                iss.append(Issue("warn", f"Windows take {frac * 100:.0f}% of the '{host.name}' panel; the box will "
                                         f"be noticeably weaker. A film patch or thicker board helps.", key))
            # kerf: a hole shrinks by half the kerf on every side
            k2 = kerf / 2
            if w - kerf <= 0 or h - kerf <= 0:
                iss.append(Issue("error", f"{tag}: smaller than the kerf.", key))
                continue
            _emit_rrect(drawing, f.cx, f.cy, w - kerf, h - kerf, max(0.0, r - k2), CUT)
        else:
            if f.outline:
                _emit_rrect(drawing, f.cx, f.cy, w, h, 0.0, ENGRAVE)
            if f.art is not None:
                _emit_art(drawing, f, mm, iss, tag, rim_z)
            elif not f.outline:
                iss.append(Issue("warn", f"{tag}: no artwork and no border, so nothing will be marked.", key))
        placed.append((f, out, host.name, tag))
        n_ok += 1
    return n_ok


def _emit_rrect(d, cx, cy, w, h, r, layer):
    r = max(0.0, min(r, w / 2, h / 2))
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    d.line((x0 + r, y0), (x1 - r, y0), layer)
    d.line((x1, y0 + r), (x1, y1 - r), layer)
    d.line((x1 - r, y1), (x0 + r, y1), layer)
    d.line((x0, y1 - r), (x0, y0 + r), layer)
    if r > 1e-9:
        d.arc((x1 - r, y0 + r), r, 270, 360, layer)
        d.arc((x1 - r, y1 - r), r, 0, 90, layer)
        d.arc((x0 + r, y1 - r), r, 90, 180, layer)
        d.arc((x0 + r, y0 + r), r, 180, 270, layer)


def _emit_art(d, f, mm, iss, tag, pad):
    a = f.art
    aw, ah = (a.h, a.w) if f.rot == 90 else (a.w, a.h)
    aw, ah = aw / mm, ah / mm                                      # to user units
    avail_w, avail_h = f.w - 2 * pad, f.h - 2 * pad
    if avail_w <= 0 or avail_h <= 0:
        iss.append(Issue("error", f"{tag}: zone too small for artwork.", ("feat",)))
        return
    s = min(avail_w / aw, avail_h / ah) if aw > 0 and ah > 0 else (avail_w / aw if aw > 0 else avail_h / ah)
    ox, oy = f.cx - aw * s / 2, f.cy - ah * s / 2

    def tr(p):
        x, y = (a.h - p[1], p[0]) if f.rot == 90 else p              # quarter turn CCW
        return (ox + x / mm * s, oy + y / mm * s)
    for pl, closed in a.polys:
        pts = [tr(p) for p in pl]
        for p, q in zip(pts, pts[1:] + ([pts[0]] if closed else [])):
            d.line(p, q, ENGRAVE)
    if s < 0.25:
        iss.append(Issue("info", f"{tag}: artwork scaled down to {s * 100:.0f}% to fit.", ()))


