# =============================================================================
# Kerf compensation
#   Material is on the LEFT of every boundary edge (panels are walked counter-clockwise), so shifting each
#   boundary edge to its RIGHT by d = kerf/2 moves the cut away from the part: outer edges grow, holes shrink,
#   concave arcs lose radius.  Edges shared by two panels are hinges (fold, untouched) or slits (zero-width
#   cut, untouched).  Fold / slit ends that sat on the outline are re-attached to the shifted outline.
# =============================================================================
def _arc_pt(c, r, deg):
    a = math.radians(deg)
    return (c[0] + r * math.cos(a), c[1] + r * math.sin(a))


def _loop_area(els):
    pts = []
    for e in els:
        if e[0] == "L":
            pts.append(e[1])
        else:
            c, r, p, q, ccw = e[1], e[2], e[3], e[4], e[5]
            a0, a1 = _ang(c, p), _ang(c, q)
            sw = (a1 - a0) % (2 * math.pi) if ccw else -((a0 - a1) % (2 * math.pi))
            pts.extend((c[0] + r * math.cos(a0 + sw * k / 8), c[1] + r * math.sin(a0 + sw * k / 8))
                       for k in range(8))
    n = len(pts)
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))


def _reverse_loop(els):
    return [["L", e[2], e[1]] if e[0] == "L" else ["A", e[1], e[2], e[4], e[3], not e[5]] for e in reversed(els)]


def _orient_ccw(els):
    return els if _loop_area(els) >= 0 else _reverse_loop(els)


class KPanel:
    """Outline-only panel used for kerf: `dirs` is a connected loop of ['L', p, q] / ['A', c, r, p, q, ccw]
    elements (any orientation; hole=True keeps it as given, material outside)."""

    def __init__(self, name, dirs, hinge=None, hole=False):
        self.name, self.dirs, self.hinge, self.hole = name, dirs, hinge, hole


def _directed_outline(pn):
    """Panel outline as counter-clockwise elements: ['L', p, q] or ['A', centre, r, p, q, ccw]."""
    if isinstance(pn, KPanel):
        return list(pn.dirs) if pn.hole else _orient_ccw(pn.dirs)
    els = pn.elems
    n = len(els)
    if n == 0:
        raise ValueError("panel without an outline")

    def ends(e):
        return (e[1], e[2]) if e[0] == "L" else (_arc_pt(e[1], e[2], e[3]), _arc_pt(e[1], e[2], e[4]))

    out, cur = [], None
    for i, e in enumerate(els):
        a, b = ends(e)
        if e[0] == "L":
            out.append(["L", a, b])
            cur = b
            continue
        if cur is None:
            nx = ends(els[(i + 1) % n])
            fwd = min(math.dist(b, nx[0]), math.dist(b, nx[1])) <= min(math.dist(a, nx[0]), math.dist(a, nx[1]))
        else:
            fwd = math.dist(cur, a) <= math.dist(cur, b)
        p, q = (a, b) if fwd else (b, a)
        out.append(["A", e[1], e[2], p, q, fwd])
        cur = q
    return _orient_ccw(out)


def _el_s(e):
    return e[1] if e[0] == "L" else e[3]


def _el_e(e):
    return e[2] if e[0] == "L" else e[4]


def _ang(c, p):
    return math.atan2(p[1] - c[1], p[0] - c[0])


def _in_arc(e, pt):
    c, p, q, ccw = e[1], e[3], e[4], e[5]
    ap, aq, ax = _ang(c, p), _ang(c, q), _ang(c, pt)
    if ccw:
        return (ax - ap) % (2 * math.pi) <= (aq - ap) % (2 * math.pi) + 1e-9
    return (ap - ax) % (2 * math.pi) <= (ap - aq) % (2 * math.pi) + 1e-9


def _closest_on(e, P):
    """Nearest point of a directed element to P."""
    if e[0] == "L":
        p, q = e[1], e[2]
        dx, dy = q[0] - p[0], q[1] - p[1]
        L2 = dx * dx + dy * dy
        u = 0.0 if L2 == 0 else max(0.0, min(1.0, ((P[0] - p[0]) * dx + (P[1] - p[1]) * dy) / L2))
        return (p[0] + u * dx, p[1] + u * dy)
    c, r = e[1], e[2]
    dd = math.dist(P, c)
    if dd > 1e-12:
        X = (c[0] + (P[0] - c[0]) * r / dd, c[1] + (P[1] - c[1]) * r / dd)
        if _in_arc(e, X):
            return X
    return e[3] if math.dist(P, e[3]) <= math.dist(P, e[4]) else e[4]


def _ray_hits(O, u, e):
    """Parameters t where O + t*u meets element e."""
    out = []
    if e[0] == "L":
        p, q = e[1], e[2]
        dx, dy = q[0] - p[0], q[1] - p[1]
        den = u[0] * dy - u[1] * dx
        if abs(den) < 1e-12:
            return out
        wx, wy = p[0] - O[0], p[1] - O[1]
        t = (wx * dy - dx * wy) / den
        s = (wx * u[1] - wy * u[0]) / den
        if -1e-7 <= s <= 1 + 1e-7:
            out.append(t)
        return out
    c, r = e[1], e[2]
    m = (O[0] - c[0], O[1] - c[1])
    b = m[0] * u[0] + m[1] * u[1]
    disc = b * b - (m[0] * m[0] + m[1] * m[1] - r * r)
    if disc < 0:
        return out
    for t in (-b - math.sqrt(disc), -b + math.sqrt(disc)):
        if _in_arc(e, (O[0] + t * u[0], O[1] + t * u[1])):
            out.append(t)
    return out


def _line_isect(p1, q1, p2, q2):
    d1, d2 = (q1[0] - p1[0], q1[1] - p1[1]), (q2[0] - p2[0], q2[1] - p2[1])
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) <= 1e-9 * math.hypot(*d1) * math.hypot(*d2):
        return None
    t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / den
    return (p1[0] + t * d1[0], p1[1] + t * d1[1])


def _el_isect(a, b, V):
    """Intersection of two offset elements (lines extended to infinite lines, arcs to full circles) nearest V."""
    if a[0] == "L" and b[0] == "L":
        return _line_isect(a[1], a[2], b[1], b[2])
    if a[0] == "L" or b[0] == "L":
        ln, ar = (a, b) if a[0] == "L" else (b, a)
        c, r = ar[1], ar[2]
        p, q = ln[1], ln[2]
        L = math.dist(p, q)
        if L < 1e-12:
            return None
        ux, uy = (q[0] - p[0]) / L, (q[1] - p[1]) / L
        m = (p[0] - c[0], p[1] - c[1])
        bq = m[0] * ux + m[1] * uy
        disc = bq * bq - (m[0] * m[0] + m[1] * m[1] - r * r)
        if disc < 0:
            return None
        pts = [(p[0] + t * ux, p[1] + t * uy) for t in (-bq - math.sqrt(disc), -bq + math.sqrt(disc))]
        return min(pts, key=lambda x: math.dist(x, V))
    c1, r1, c2, r2 = a[1], a[2], b[1], b[2]
    D = math.dist(c1, c2)
    if D < 1e-12 or D > r1 + r2 or D < abs(r1 - r2):
        return None
    aa = (r1 * r1 - r2 * r2 + D * D) / (2 * D)
    h2 = r1 * r1 - aa * aa
    if h2 < 0:
        return None
    ex_, ey_ = (c2[0] - c1[0]) / D, (c2[1] - c1[1]) / D
    mid = (c1[0] + aa * ex_, c1[1] + aa * ey_)
    h = math.sqrt(h2)
    pts = [(mid[0] - h * ey_, mid[1] + h * ex_), (mid[0] + h * ey_, mid[1] - h * ex_)]
    return min(pts, key=lambda x: math.dist(x, V))


def _boundary_and_slits(panels):
    """Outline pieces (material on the left) and slit segments from the panels' coincident edges."""
    lines, arcs, hinges = [], [], []
    for pn in panels:
        for e in _directed_outline(pn):
            (lines if e[0] == "L" else arcs).append(e)
        if pn.hinge:
            hinges.append((pn.hinge[0], pn.hinge[1]))
    groups = {}

    def add(p, q, kind):
        p = (round(p[0], 5), round(p[1], 5))
        q = (round(q[0], 5), round(q[1], 5))
        L = math.dist(p, q)
        if L < 1e-7:
            return
        ux, uy, sg = (q[0] - p[0]) / L, (q[1] - p[1]) / L, 1
        if ux < -1e-9 or (abs(ux) <= 1e-9 and uy < 0):
            ux, uy, sg = -ux, -uy, -1
        c = -uy * p[0] + ux * p[1]
        s0, s1 = sorted((ux * p[0] + uy * p[1], ux * q[0] + uy * q[1]))
        groups.setdefault((round(ux, 4), round(uy, 4)), []).append((c, s0, s1, kind, sg, ux, uy))

    for e in lines:
        add(e[1], e[2], "edge")
    for h in hinges:
        add(h[0], h[1], "hinge")

    bel, slits = [], []
    for items in groups.values():
        items.sort()
        clusters, cur = [], [items[0]]
        for it in items[1:]:
            if abs(it[0] - cur[-1][0]) < 5e-4:
                cur.append(it)
            else:
                clusters.append(cur)
                cur = [it]
        clusters.append(cur)
        for cl in clusters:
            c = sum(i[0] for i in cl) / len(cl)
            ux, uy = cl[0][5], cl[0][6]
            pt = lambda a: (a * ux - c * uy, a * uy + c * ux)
            pts = sorted({round(v, 5) for i in cl for v in (i[1], i[2])})
            runs = []
            for a, b in zip(pts, pts[1:]):
                if b - a < 1e-6:
                    continue
                mid = (a + b) / 2
                cov = [i for i in cl if i[1] <= mid <= i[2]]
                if not cov or any(i[3] == "hinge" for i in cov):
                    continue
                plus = sum(1 for i in cov if i[3] == "edge" and i[4] > 0)
                minus = sum(1 for i in cov if i[3] == "edge" and i[4] < 0)
                if plus and minus and plus == minus:
                    cls = "S"
                elif plus != minus:
                    cls = "B+" if plus > minus else "B-"
                else:
                    continue
                if runs and runs[-1][2] == cls and abs(runs[-1][1] - a) < 1e-6:
                    runs[-1][1] = b
                else:
                    runs.append([a, b, cls])
            for a, b, cls in runs:
                if cls == "S":
                    slits.append((pt(a), pt(b)))
                elif cls == "B+":
                    bel.append(["L", pt(a), pt(b)])
                else:
                    bel.append(["L", pt(b), pt(a)])
    return bel + arcs, slits


def _chain_loops(bel):
    used = [False] * len(bel)
    loops = []
    for i0 in range(len(bel)):
        if used[i0]:
            continue
        used[i0] = True
        loop, start, cur = [bel[i0]], _el_s(bel[i0]), _el_e(bel[i0])
        while math.dist(cur, start) > 1e-4:
            nxt = next((j for j in range(len(bel)) if not used[j] and math.dist(_el_s(bel[j]), cur) < 1e-4), None)
            if nxt is None:
                raise ValueError("cut outline is not closed")
            used[nxt] = True
            loop.append(bel[nxt])
            cur = _el_e(bel[nxt])
        loops.append(loop)
    return loops


def _offset_once(loop, d, reach):
    """Offset one loop; returns (elements, index of a collapsed line or None). `reach` scales the miter limit."""
    out = []
    for e in loop:
        if e[0] == "L":
            p, q = e[1], e[2]
            L = math.dist(p, q)
            nx, ny = (q[1] - p[1]) / L * d, -(q[0] - p[0]) / L * d
            out.append(["L", (p[0] + nx, p[1] + ny), (q[0] + nx, q[1] + ny)])
        else:
            c, r, p, q, ccw = e[1], e[2], e[3], e[4], e[5]
            r2 = r + d if ccw else r - d
            if r2 < 1e-6:
                raise ValueError("kerf is larger than a corner radius")
            f = r2 / r
            out.append(["A", c, r2, (c[0] + (p[0] - c[0]) * f, c[1] + (p[1] - c[1]) * f),
                        (c[0] + (q[0] - c[0]) * f, c[1] + (q[1] - c[1]) * f), ccw])
    n = len(out)
    conn = {}
    for i in range(n):
        a, b = out[i], out[(i + 1) % n]
        ea, sb = _el_e(a), _el_s(b)
        if math.dist(ea, sb) < 1e-7:
            continue
        V = _el_e(loop[i])
        if a[0] == "L" and b[0] == "L":
            X = _line_isect(a[1], a[2], b[1], b[2])
            # trimming at a notch always meets exactly; only extension (outer corner) gets a miter limit
            ax, ay = a[2][0] - a[1][0], a[2][1] - a[1][1]
            extends = (X[0] - a[2][0]) * ax + (X[1] - a[2][1]) * ay > 1e-9 if X is not None else True
            if X is not None and (not extends or math.dist(X, V) <= 4 * d * reach + 1e-9):
                a[2] = X
                b[1] = X
                continue
        else:                       # a corner involving an arc (e.g. a bulge meeting a straight edge at an angle)
            X = _el_isect(a, b, V)
            if X is not None and math.dist(X, V) <= 4 * d * reach + 1e-9:
                a[2 if a[0] == "L" else 4] = X
                b[1 if b[0] == "L" else 3] = X
                continue
        conn[i] = ["L", ea, sb]
    for i, e in enumerate(out):
        if e[0] == "L":
            o = loop[i]
            ox, oy = o[2][0] - o[1][0], o[2][1] - o[1][1]
            nx, ny = e[2][0] - e[1][0], e[2][1] - e[1][1]
            if math.hypot(nx, ny) < 1e-9 or ox * nx + oy * ny <= 0:
                return None, i
    res = []
    for i, e in enumerate(out):
        res.append(e)
        if i in conn:
            res.append(conn[i])
    return res, None


def _offset_loop(loop, d, stats=None):
    """Offset a loop. A short edge that the kerf swallows entirely (a sliver narrower than the beam) is dropped
    and its neighbours are joined, which is what the laser would do anyway."""
    els, dropped = list(loop), 0
    while True:
        res, bad = _offset_once(els, d, 1 if not dropped else 12)
        if bad is None:
            return res
        if len(els) <= 4 or dropped >= 6:
            o = els[bad]
            raise ValueError(f"kerf is larger than the smallest feature (near x={o[1][0]:.2f}, y={o[1][1]:.2f})")
        if stats is not None:
            stats.append(_el_s(els[bad]))
        del els[bad]
        dropped += 1


def _adjust_end(P, O, nom, off, d):
    """Re-attach a fold / slit end P (other end O) that sat on the nominal outline to the shifted outline."""
    if min(math.dist(P, _closest_on(e, P)) for e in nom) > 2e-4:
        return P
    L = math.dist(P, O)
    if L < 1e-9:
        return P
    u = ((P[0] - O[0]) / L, (P[1] - O[1]) / L)
    best = None
    for e in off:
        for t in _ray_hits(O, u, e):
            if t > 1e-9 and abs(t - L) <= 15 * d + 1e-6 and (best is None or abs(t - L) < abs(best - L)):
                best = t
    if best is not None:
        return (O[0] + best * u[0], O[1] + best * u[1])
    X = min((_closest_on(e, P) for e in off), key=lambda x: math.dist(x, P))
    return X if math.dist(X, P) <= 3 * d + 1e-6 else P


def _flat_segments(dr, n=6):
    segs = []
    for it in dr.items:
        if it[-1] != CUT:
            continue
        if it[0] == "L":
            segs.append((it[1], it[2]))
        else:
            _, c, r, a0, a1, _l = it
            span = (a1 - a0) % 360 or 360
            pts = [_arc_pt(c, r, a0 + span * k / n) for k in range(n + 1)]
            segs.extend(zip(pts, pts[1:]))
    return segs


def kerf_drawing(panels, nominal, kerf):
    """Kerf-compensated copy of `nominal` (built from `panels`). Raises ValueError if it cannot be done."""
    d = kerf / 2.0
    bel, slits = _boundary_and_slits(panels)
    loops = _chain_loops(bel)
    swallowed = []
    off_loops = [_offset_loop(lp, d, swallowed) for lp in loops]
    nom = [e for lp in loops for e in lp]
    off = [e for lp in off_loops for e in lp]
    dr = Drawing()
    for e in off:
        if e[0] == "L":
            dr.line(e[1], e[2], CUT)
        else:
            a, b = math.degrees(_ang(e[1], e[3])), math.degrees(_ang(e[1], e[4]))
            dr.arc(e[1], e[2], *((a, b) if e[5] else (b, a)), CUT)
    for p, q in slits:
        dr.line(_adjust_end(p, q, nom, off, d), _adjust_end(q, p, nom, off, d), CUT)
    for it in nominal.items:
        if it[0] == "L" and it[3] == FOLD:
            dr.line(_adjust_end(it[1], it[2], nom, off, d), _adjust_end(it[2], it[1], nom, off, d), FOLD)
    segs = _flat_segments(dr)
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            if _proper_cross(segs[i][0], segs[i][1], segs[j][0], segs[j][1], 1e-6):
                raise ValueError("kerf makes cut lines cross (a slot or gap is narrower than the kerf)")
    dr.swallowed = [(round(x, 2), round(y, 2)) for x, y in swallowed]
    return dr


def perforate(d, dash, tie, kerf=0.0):
    """Replace every FOLD line with dashed CUT lines (tie, dash, tie, ..., tie).
    `tie` is the uncut bridge that should remain; the laser burns `kerf` off each dash end, so the drawn
    gap is tie + kerf. Lines too short to hold a dash stay as solid fold lines.
    Returns (new drawing, dashed line count, solid line count)."""
    out = Drawing()
    gap = tie + kerf
    nd = ns = 0
    for it in d.items:
        if not (it[0] == "L" and it[3] == FOLD):
            out.items.append(it)
            continue
        p, q = it[1], it[2]
        L = math.dist(p, q)
        n = int(round((L - gap) / (dash + gap)))
        while n > 1 and (L - (n + 1) * gap) / n < 0.5 * dash:
            n -= 1
        seg = (L - (n + 1) * gap) / n if n >= 1 else 0
        if n < 1 or seg < max(0.5 * dash, 1e-6):
            out.items.append(it)
            ns += 1
            continue
        ux, uy = (q[0] - p[0]) / L, (q[1] - p[1]) / L
        for k in range(n):
            a = gap + k * (seg + gap)
            out.line((p[0] + ux * a, p[1] + uy * a), (p[0] + ux * (a + seg), p[1] + uy * (a + seg)), CUT)
        nd += 1
    return out, nd, ns


