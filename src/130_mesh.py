# =============================================================================
# Solid slab mesh of the flat blank (for STL / 3MF): board thickness, windows cut through,
# dashed folds as slots, half-round fold grooves on the outside (top) face. No dependencies.
# =============================================================================
GROOVE_FRAC = 1.0 / 3.0      # groove depth as a fraction of the board thickness
SLOT_MIN_MM = 0.3            # narrowest slot modelled for a dashed fold when the kerf is smaller
GROOVE_SEGS = 10             # facets across a groove
_EPS = 1e-9


class Mesh:
    """Triangle mesh in millimetres: verts [(x, y, z)], tris [(i, j, k)] counter-clockwise seen from outside."""

    def __init__(self):
        self.verts, self.tris, self.info = [], [], {}
        self._key = {}

    def vid(self, x, y, z):
        k = (round(x * 1e5), round(y * 1e5), round(z * 1e5))
        i = self._key.get(k)
        if i is None:
            i = self._key[k] = len(self.verts)
            self.verts.append((x, y, z))
        return i

    def add(self, a, b, c):
        if a != b and b != c and a != c:
            self.tris.append((a, b, c))

    def volume(self):
        v = 0.0
        for a, b, c in self.tris:
            p, q, r = self.verts[a], self.verts[b], self.verts[c]
            v += (p[0] * (q[1] * r[2] - q[2] * r[1]) - p[1] * (q[0] * r[2] - q[2] * r[0])
                  + p[2] * (q[0] * r[1] - q[1] * r[0]))
        return v / 6.0

    def open_edges(self):
        """Directed edges that are not matched by their reverse (0 for a watertight, consistently wound mesh)."""
        cnt = {}
        for a, b, c in self.tris:
            for e in ((a, b), (b, c), (c, a)):
                cnt[e] = cnt.get(e, 0) + 1
        return [e for e, n in cnt.items() if n != 1 or (e[1], e[0]) not in cnt]


def _poly_flat(it, tol=0.05):
    """Drawing item -> polyline points (arcs flattened to the given chord tolerance, mm-agnostic units)."""
    if it[0] == "L":
        return [it[1], it[2]]
    _, c, r, a0, a1, _l = it
    span = (a1 - a0) % 360 or 360
    step = 2 * math.degrees(math.acos(max(0.0, 1 - tol / r))) if r > tol else 30.0
    n = max(2, math.ceil(span / max(step, 1.0)))
    return [_arc_pt(c, r, a0 + span * k / n) for k in range(n + 1)]


def _area2(pts):
    return sum(pts[i - 1][0] * pts[i][1] - pts[i][0] * pts[i - 1][1] for i in range(len(pts)))


def _cut_loops_and_dashes(d, tol=1e-3):
    """Chain the CUT items of a drawing. -> (closed loops as point lists, open single segments). Plain outlines
    (the slotted box) are chained directly; drawings where cut lines meet in T-junctions and end in slits
    (the lid and base) go through the general planar version below."""
    try:
        return _cut_loops_simple(d, tol)
    except ValueError:
        return _cut_loops_planar(d, tol)


def _cut_loops_planar(d, tol=1e-3):
    """General version: split every cut line where another one ends on it, drop slits (lines that end free inside
    the material or on the outline) as dashes, and chain what is left into closed loops."""
    segs = []
    for it in d.items:
        if it[-1] != CUT:
            continue
        pl = _poly_flat(it)
        for i in range(len(pl) - 1):
            if math.dist(pl[i], pl[i + 1]) > tol:
                segs.append((pl[i], pl[i + 1], it[0] == "L"))
    nodes, key = [], {}

    def node(pt):
        k = (round(pt[0] / tol), round(pt[1] / tol))
        for dx in (0, -1, 1):
            for dy in (0, -1, 1):
                j = key.get((k[0] + dx, k[1] + dy))
                if j is not None and abs(nodes[j][0] - pt[0]) < tol and abs(nodes[j][1] - pt[1]) < tol:
                    return j
        key[k] = len(nodes)
        nodes.append(pt)
        return len(nodes) - 1
    raw = [(node(a), node(b), ln) for a, b, ln in segs]
    pts = list(range(len(nodes)))
    edges = {}
    for a, b, ln in raw:
        pa, pb = nodes[a], nodes[b]
        L = math.dist(pa, pb)
        on = []
        for c in pts:
            if c in (a, b):
                continue
            pc = nodes[c]
            u = ((pc[0] - pa[0]) * (pb[0] - pa[0]) + (pc[1] - pa[1]) * (pb[1] - pa[1])) / (L * L)
            if 0 < u < 1 and math.dist(pc, (pa[0] + u * (pb[0] - pa[0]), pa[1] + u * (pb[1] - pa[1]))) < tol * 2:
                on.append((u, c))
        chain = [a] + [c for _, c in sorted(on)] + [b]
        for i in range(len(chain) - 1):
            if chain[i] != chain[i + 1]:
                e = frozenset((chain[i], chain[i + 1]))
                edges[e] = edges.get(e, True) and ln
    adj = {}
    for e in edges:
        for n in e:
            adj.setdefault(n, set()).add(e)
    pruned, work = [], [n for n in adj if len(adj[n]) == 1]
    while work:
        n = work.pop()
        if len(adj.get(n, ())) != 1:
            continue
        e = next(iter(adj[n]))
        pruned.append(e)
        for m in e:
            adj[m].discard(e)
            if len(adj[m]) == 1:
                work.append(m)
    dashes = []
    left = list(pruned)
    while left:                                              # group touching slit pieces, one dash per straight run
        comp = [left.pop()]
        grew = True
        while grew:
            grew = False
            for e in list(left):
                if any(e & c for c in comp):
                    comp.append(e)
                    left.remove(e)
                    grew = True
        for e in comp:
            if not edges[e]:
                raise ValueError("an open curved cut cannot be modelled")
        ends = sorted({n for e in comp for n in e})
        P = [nodes[n] for n in ends]
        far = max(((P[i], P[j]) for i in range(len(P)) for j in range(i + 1, len(P))), key=lambda ab: math.dist(*ab))
        ux, uy = far[1][0] - far[0][0], far[1][1] - far[0][1]
        Ln = math.hypot(ux, uy) or 1.0
        if all(abs((q[0] - far[0][0]) * uy - (q[1] - far[0][1]) * ux) / Ln < tol * 2 for q in P):
            dashes.append(far)
        else:
            dashes.extend((nodes[min(e)], nodes[max(e)]) for e in comp)
    live = {e for n in adj for e in adj[n]}
    nb = {}
    for e in live:
        a, b = tuple(e)
        nb.setdefault(a, []).append(b)
        nb.setdefault(b, []).append(a)
    if any(len(v) != 2 for v in nb.values()):
        raise ValueError("cut lines touch or do not close; cannot build a solid from them")
    loops, seen = [], set()
    for start in nb:
        if start in seen:
            continue
        loop, prev, cur = [], None, start
        while cur not in seen:
            seen.add(cur)
            loop.append(nodes[cur])
            nxt = [m for m in nb[cur] if m != prev]
            prev, cur = cur, (nxt[0] if nxt else nb[cur][0])
        loops.append(loop)
    return loops, dashes


def _cut_loops_simple(d, tol=1e-3):
    items = [it for it in d.items if it[-1] == CUT
             and not (it[0] == "L" and abs(it[1][0] - it[2][0]) < tol and abs(it[1][1] - it[2][1]) < tol)]
    nodes = []

    def node(p):
        for i, q in enumerate(nodes):
            if abs(q[0] - p[0]) < tol and abs(q[1] - p[1]) < tol:
                return i
        nodes.append(p)
        return len(nodes) - 1
    edges = []                                      # (node a, node b, polyline)
    for it in items:
        pl = _poly_flat(it)
        edges.append((node(pl[0]), node(pl[-1]), pl))
    adj = {}
    for k, (a, b, _) in enumerate(edges):
        adj.setdefault(a, []).append(k)
        adj.setdefault(b, []).append(k)
    used, loops, dashes = [False] * len(edges), [], []
    for k0, (a0, b0, pl0) in enumerate(edges):
        if used[k0]:
            continue
        if len(adj[a0]) == 1 and len(adj[b0]) == 1 and a0 != b0:     # isolated segment = a dash
            used[k0] = True
            if it_is_line(items[k0]):
                dashes.append((pl0[0], pl0[-1]))
                continue
            raise ValueError("an open curved cut cannot be modelled")
        pts, cur, k = list(pl0), b0, k0
        used[k0] = True
        while cur != a0:
            nxt = [j for j in adj[cur] if not used[j]]
            if not nxt or len(adj[cur]) != 2:
                raise ValueError("cut lines touch or do not close; cannot build a solid from them")
            j = nxt[0]
            used[j] = True
            a, b, pl = edges[j]
            pl = pl if a == cur else pl[::-1]
            pts.extend(pl[1:])
            cur = b if a == cur else a
        loops.append(pts[:-1])
    return loops, dashes


def it_is_line(it):
    return it[0] == "L"


def _pip2(p, poly):
    x, y, ins = p[0], p[1], False
    for i in range(len(poly)):
        a, b = poly[i], poly[i - 1]
        if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
            ins = not ins
    return ins


def _trapezoids(loops):
    """Even-odd trapezoid decomposition of a region bounded by `loops` (outer + holes, any orientation).
    Returns convex CCW polygons (4 corners plus any extra points on their horizontal sides, so neighbouring
    trapezoids share identical vertices - no T-junctions)."""
    import bisect
    snap = lambda v: round(v * 1e7) / 1e7
    edges = []
    for lp in loops:
        pts = [(snap(x), snap(y)) for x, y in lp]
        for i in range(len(pts)):
            a, b = pts[i - 1], pts[i]
            if a[1] != b[1]:
                edges.append((a, b) if a[1] < b[1] else (b, a))        # lower end first
    ys = sorted({p[1] for lp in loops for p in ((snap(x), snap(y)) for x, y in lp)})
    edges.sort(key=lambda e: e[0][1])
    xat = lambda e, y: e[0][0] + (y - e[0][1]) * (e[1][0] - e[0][0]) / (e[1][1] - e[0][1])
    active, ei, traps = [], 0, []
    for k in range(len(ys) - 1):
        y0, y1 = ys[k], ys[k + 1]
        while ei < len(edges) and edges[ei][0][1] <= y0:
            active.append(edges[ei])
            ei += 1
        active = [e for e in active if e[1][1] > y0]
        ym = (y0 + y1) / 2
        act = sorted(active, key=lambda e: xat(e, ym))
        if len(act) % 2:
            raise ValueError("the blank outline is not a clean closed region")
        for i in range(0, len(act), 2):
            l, r = act[i], act[i + 1]
            traps.append([y0, y1, xat(l, y0), xat(r, y0), xat(l, y1), xat(r, y1)])
    # points to add on each horizontal line so neighbours match
    line = {}
    for y0, y1, bl, br, tl, tr in traps:
        line.setdefault(y0, set()).update((bl, br))
        line.setdefault(y1, set()).update((tl, tr))
    srt = {y: sorted(v) for y, v in line.items()}

    def between(y, a, b):
        xs = srt[y]
        i, j = bisect.bisect_right(xs, a + 1e-9), bisect.bisect_left(xs, b - 1e-9)
        return xs[i:j]
    out = []
    for y0, y1, bl, br, tl, tr in traps:
        poly = [(bl, y0)] + [(x, y0) for x in between(y0, bl, br)] + [(br, y0), (tr, y1)]
        poly += [(x, y1) for x in reversed(between(y1, tl, tr))] + [(tl, y1)]
        p = _clean_piece(poly, min_area2=1e-12)
        if p:
            out.append(p)
    return out


def _tri_trap(poly):
    """Triangulate a convex piece (collinear boundary points allowed) by ear clipping, refusing any ear whose
    closing diagonal passes through another vertex of the piece, so no triangle edge skips a shared point
    (that would leave T-junctions and open edges). Returns index triples into `poly`, CCW."""
    n = len(poly)
    idx = list(range(n))
    out = []

    def on_seg(a, b, c):
        ax, ay = poly[a]; bx, by = poly[b]; cx, cy = poly[c]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 < 1e-18:
            return False
        if abs(dx * (cy - ay) - dy * (cx - ax)) > 1e-9 * (L2 ** 0.5):
            return False
        t = ((cx - ax) * dx + (cy - ay) * dy) / L2
        return 1e-9 < t < 1 - 1e-9

    guard = 0
    while len(idx) > 3:
        guard += 1
        if guard > 4 * n * n:
            raise ValueError("slab triangulation failed: %r" % (poly,))
        m = len(idx)
        pick = None
        for pass_ in (0, 1):
            for k in range(m):
                a, b, c = idx[k - 1], idx[k], idx[(k + 1) % m]
                (ax, ay), (bx, by), (cx, cy) = poly[a], poly[b], poly[c]
                if (bx - ax) * (cy - ay) - (by - ay) * (cx - ax) <= 1e-12:
                    continue
                if pass_ == 0 and any(on_seg(a, c, v) for v in range(n) if v not in (a, b, c)):
                    continue
                pick = k
                break
            if pick is not None:
                break
        if pick is None:
            raise ValueError("slab triangulation stuck: %r" % (poly,))
        out.append((idx[pick - 1], idx[pick], idx[(pick + 1) % m]))
        del idx[pick]
    a, b, c = idx
    (ax, ay), (bx, by), (cx, cy) = poly[a], poly[b], poly[c]
    if abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax)) > 1e-12:
        out.append((a, b, c))
    return out


def _split_poly(poly, axis, c):
    """Split a convex polygon by the line coord[axis] = c -> (low piece or None, high piece or None)."""
    lo, hi = [], []
    n = len(poly)
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        sp, sq = p[axis] - c, q[axis] - c
        if abs(sp) < _EPS:
            sp = 0.0
        if abs(sq) < _EPS:
            sq = 0.0
        if sp <= 0:
            lo.append(p)
        if sp >= 0:
            hi.append(p)
        if sp * sq < 0:
            t = sp / (sp - sq)
            m = (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))
            m = tuple(c if k == axis else m[k] for k in (0, 1))
            lo.append(m)
            hi.append(m)
    return (lo if len(lo) >= 3 else None), (hi if len(hi) >= 3 else None)


def _slice_pieces(tris, xs, ys):
    """Cut every triangle by all vertical (x = const) and horizontal lines -> convex pieces."""
    import bisect
    xs, ys = sorted(set(xs)), sorted(set(ys))
    out = []
    stack = [list(t) for t in tris]
    while stack:
        p = stack.pop()
        x0, x1 = min(q[0] for q in p), max(q[0] for q in p)
        y0, y1 = min(q[1] for q in p), max(q[1] for q in p)
        i = bisect.bisect_right(xs, x0 + _EPS)
        if i < len(xs) and xs[i] < x1 - _EPS:
            lo, hi = _split_poly(p, 0, xs[i])
            stack.extend(q for q in (lo, hi) if q)
            continue
        j = bisect.bisect_right(ys, y0 + _EPS)
        if j < len(ys) and ys[j] < y1 - _EPS:
            lo, hi = _split_poly(p, 1, ys[j])
            stack.extend(q for q in (lo, hi) if q)
            continue
        p = _clean_piece(p)
        if p:
            out.append(p)
    return out


def _clean_piece(p, tol=1e-7, min_area2=1e-8):
    """Drop repeated points and zero-width spikes; None if nothing of area is left."""
    changed = True
    while changed and len(p) >= 3:
        changed = False
        q = []
        for pt in p:
            if q and abs(q[-1][0] - pt[0]) < tol and abs(q[-1][1] - pt[1]) < tol:
                changed = True
                continue
            q.append(pt)
        if len(q) > 1 and abs(q[0][0] - q[-1][0]) < tol and abs(q[0][1] - q[-1][1]) < tol:
            q.pop()
            changed = True
        n = len(q)
        r = []
        for i in range(n):
            a, c = q[i - 1], q[(i + 1) % n]
            if abs(a[0] - c[0]) < tol and abs(a[1] - c[1]) < tol:      # spike a-b-a
                changed = True
                continue
            r.append(q[i])
        p = r
    if len(p) < 3 or abs(_area2(p)) < min_area2:
        return None
    return p


def _dash_rect(p, q, w):
    L = math.dist(p, q)
    ux, uy = (q[0] - p[0]) / L, (q[1] - p[1]) / L
    e = w / 2
    a, b = (p[0] - ux * e, p[1] - uy * e), (q[0] + ux * e, q[1] + uy * e)
    nx, ny = -uy * e, ux * e
    return [(a[0] - nx, a[1] - ny), (b[0] - nx, b[1] - ny), (b[0] + nx, b[1] + ny), (a[0] + nx, a[1] + ny)]


def _cluster_map(vals, tol=2e-3):
    """{round(v*1e4): representative} merging values whose gaps are <= tol (cluster span capped at 4 x tol)."""
    out, cur, first = {}, [], None
    for v in sorted({round(v * 1e4) for v in vals}):
        if cur and (v - cur[-1] > tol * 1e4 or v - first > 4 * tol * 1e4):
            cur, first = [], None
        if not cur:
            first = v
        cur.append(v)
        out[v] = first / 1e4
    return out


def slab_mesh(res, spec, groove=GROOVE_FRAC, slot_mm=None, segs=GROOVE_SEGS):
    """Solid mesh (mm) of the flat blank as cut: kerf-compensated outline, windows through, dashed folds as
    slots, half-round groove of depth `groove` x thickness along every fold on the outside (top) face."""
    if res.drawing is None:
        raise ValueError("nothing to model")
    mmk = 25.4 if spec.units == "in" else 1.0
    t = spec.t * mmk
    d = Drawing()
    d.items = [it[:1] + tuple(_scale_item(it, mmk)) for it in res.drawing.items]
    kerf = (res.info.get("kerf") or 0.0) * mmk
    sn = lambda v: round(v * 1e4) / 1e4                     # 0.1 micron grid: removes float noise from dimensions
    loops, dashes = _cut_loops_and_dashes(d)
    spt = lambda q: (sn(q[0]), sn(q[1]))
    loops = [[spt(q) for q in lp] for lp in loops]
    dashes = [(spt(a), spt(b)) for a, b in dashes]
    if not loops:
        raise ValueError("no closed cut outline found")
    loops.sort(key=lambda p: -abs(_area2(p)))
    # nesting: a loop inside an even number of others is a part outline, inside an odd number it is a cut-out
    depth = [sum(1 for j, o in enumerate(loops) if j != i and abs(_area2(o)) > abs(_area2(lp)) and _pip2(lp[0], o))
             for i, lp in enumerate(loops)]
    outers = [(lp if _area2(lp) > 0 else lp[::-1]) for lp, dp in zip(loops, depth) if dp % 2 == 0]
    holes = [(lp if _area2(lp) < 0 else lp[::-1]) for lp, dp in zip(loops, depth) if dp % 2 == 1]
    outer = outers[0]
    n_win = len(holes)
    inside_blank = lambda v: any(_pip2(v, o) for o in outers)
    # dashed folds -> slots; any slot that would touch the outline, a window or another slot is left out
    w = slot_mm if slot_mm is not None else max(kerf, SLOT_MIN_MM)
    margin = 0.25
    solid = outers + holes
    placed, dropped = [], 0
    for p, q in dashes:
        rect = _dash_rect(p, q, w)
        ok = all(inside_blank(v) for v in rect)
        if ok:
            bx0, bx1 = min(v[0] for v in rect) - margin, max(v[0] for v in rect) + margin
            by0, by1 = min(v[1] for v in rect) - margin, max(v[1] for v in rect) + margin
            for other in solid + [r for r, _ in placed]:
                ox0, ox1 = min(v[0] for v in other), max(v[0] for v in other)
                oy0, oy1 = min(v[1] for v in other), max(v[1] for v in other)
                if ox1 < bx0 or ox0 > bx1 or oy1 < by0 or oy0 > by1:
                    continue
                if _poly_poly_dist(rect, other) < margin or (not any(other is o for o in outers) and (_pip2(rect[0], other) or _pip2(other[0], rect))):
                    ok = False
                    break
        if ok:
            placed.append((rect[::-1] if _area2(rect) > 0 else rect, (p, q)))
        else:
            dropped += 1
    holes.extend(r for r, _ in placed)
    # lines that are only a micron or two apart (unit-conversion rounding, kerf offsets, slot edges) are one line
    allp = [q for lp in outers + holes for q in lp]
    for it in d.items:
        if it[0] == "L" and it[-1] == FOLD:
            allp += [spt(it[1]), spt(it[2])]
    cx, cy = _cluster_map([q[0] for q in allp]), _cluster_map([q[1] for q in allp])
    spt = lambda q: (cx.get(round(q[0] * 1e4), sn(q[0])), cy.get(round(q[1] * 1e4), sn(q[1])))
    outers = [[spt(q) for q in o] for o in outers]
    holes = [[spt(q) for q in h] for h in holes]
    trap = _trapezoids(outers + holes)
    # grooves: axis-aligned FOLD lines
    r_g = groove * t
    folds = []
    for it in d.items:
        if it[0] == "L" and it[-1] == FOLD:
            (x0, y0), (x1, y1) = spt(it[1]), spt(it[2])
            # kerf offsets can leave a fold a fraction of a millimetre off-axis (at one end only, where it meets a
            # chamfered flap): a nearly straight line is treated as its mean line
            dx, dy = abs(x0 - x1), abs(y0 - y1)
            near = lambda dev, ln: dev < max(5e-4, 0.01 * ln) or (dev <= 0.35 and dev <= 0.06 * ln)
            if near(dx, dy) and dx <= dy:
                folds.append(("v", sn((x0 + x1) / 2), min(y0, y1), max(y0, y1)))
            elif near(dy, dx):
                folds.append(("h", sn((y0 + y1) / 2), min(x0, x1), max(x0, x1)))
            else:
                raise ValueError("fold lines must be horizontal or vertical for the 3-D model")
    ramp = 1e-3
    xs, ys = [], []
    for kind, c, a, b in folds:
        across = [c - r_g * math.cos(math.pi * i / segs) for i in range(segs + 1)]
        along = [a - ramp, a, b, b + ramp]
        (xs if kind == "v" else ys).extend(across)
        (ys if kind == "v" else xs).extend(along)
    xs, ys = sorted({sn(v) for v in xs}), sorted({sn(v) for v in ys})

    def depth(x, y):
        best = 0.0
        for kind, c, a, b in folds:
            u, s = (x - c, y) if kind == "v" else (y - c, x)
            if abs(u) >= r_g or s < a - ramp or s > b + ramp:
                continue
            f = min(1.0, (s - a + ramp) / ramp, (b + ramp - s) / ramp)
            best = max(best, f * math.sqrt(max(0.0, r_g * r_g - u * u)))
        return best
    pieces = _slice_pieces(trap, xs, ys) if folds else trap
    pieces = [c for c in (_clean_piece([spt(q) for q in pc], 1e-9, 1e-9) for pc in pieces) if c]
    m = Mesh()
    top = lambda p: m.vid(p[0], p[1], t - depth(p[0], p[1]))
    bot = lambda p: m.vid(p[0], p[1], 0.0)
    edge_count = {}
    for p in pieces:
        if _area2(p) < 0:
            p = p[::-1]
        ti = [top(q) for q in p]
        bi = [bot(q) for q in p]
        for i, j, k in _tri_trap(p):
            m.add(ti[i], ti[j], ti[k])
            m.add(bi[i], bi[k], bi[j])
        keys = [(round(q[0] * 1e5), round(q[1] * 1e5)) for q in p]
        for k in range(len(p)):
            e = (keys[k], keys[(k + 1) % len(p)])
            if e[0] != e[1]:
                edge_count[e] = (p[k], p[(k + 1) % len(p)])
    for (ka, kb), (a, b) in edge_count.items():
        if (kb, ka) in edge_count:
            continue
        ta, tb, ba, bb = top(a), top(b), bot(a), bot(b)
        m.add(ba, bb, tb)
        m.add(ba, tb, ta)
    area = sum(abs(_area2(o)) for o in outers) / 2 - sum(abs(_area2(h)) / 2 for h in holes)
    m.info = dict(thickness=t, slots=len(placed), slots_dropped=dropped, windows=n_win,
                  grooves=len(folds), groove_depth=r_g, area=area, slot_width=w,
                  bbox=(min(v[0] for v in m.verts), min(v[1] for v in m.verts), max(v[0] for v in m.verts),
                        max(v[1] for v in m.verts)))
    return m


def _scale_item(it, k):
    if it[0] == "L":
        return ((it[1][0] * k, it[1][1] * k), (it[2][0] * k, it[2][1] * k), it[3])
    return ((it[1][0] * k, it[1][1] * k), it[2] * k, it[3], it[4], it[5])


def _tri_normal(p, q, r):
    ux, uy, uz = q[0] - p[0], q[1] - p[1], q[2] - p[2]
    vx, vy, vz = r[0] - p[0], r[1] - p[1], r[2] - p[2]
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    L = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return nx / L, ny / L, nz / L


def mesh_to_stl(mesh, name="BoxForge"):
    """Binary STL (millimetres)."""
    import struct
    out = bytearray()
    hdr = ("BoxForge %s mm" % name).encode("ascii", "replace")[:80]
    out += hdr.ljust(80, b" ")
    out += struct.pack("<I", len(mesh.tris))
    for a, b, c in mesh.tris:
        p, q, r = mesh.verts[a], mesh.verts[b], mesh.verts[c]
        out += struct.pack("<3f", *_tri_normal(p, q, r))
        for v in (p, q, r):
            out += struct.pack("<3f", *v)
        out += b"\x00\x00"
    return bytes(out)


def mesh_to_3mf(mesh, name="BoxForge"):
    """3MF package (zip of XML, millimetres) as bytes."""
    import io
    import zipfile
    from xml.sax.saxutils import quoteattr
    vs = "".join('<vertex x="%.5f" y="%.5f" z="%.5f"/>' % v for v in mesh.verts)
    ts = "".join('<triangle v1="%d" v2="%d" v3="%d"/>' % t for t in mesh.tris)
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             '<metadata name="Title">%s</metadata><metadata name="Application">BoxForge</metadata>'
             '<resources><object id="1" type="model" name=%s><mesh><vertices>%s</vertices>'
             '<triangles>%s</triangles></mesh></object></resources>'
             '<build><item objectid="1"/></build></model>'
             % (name.replace("&", "and").replace("<", "").replace(">", ""), quoteattr(name), vs, ts))
    ctypes = ('<?xml version="1.0" encoding="UTF-8"?>\n'
              '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
              '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
              '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ctypes)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)
    return buf.getvalue()


def read_stl(data):
    """Binary STL back into a welded Mesh (for checks)."""
    import struct
    n = struct.unpack("<I", data[80:84])[0]
    if len(data) != 84 + 50 * n:
        raise ValueError("not a binary STL of the expected size")
    m = Mesh()
    for i in range(n):
        f = struct.unpack("<12f", data[84 + 50 * i:84 + 50 * i + 48])
        m.add(*(m.vid(f[3 + 3 * k], f[4 + 3 * k], f[5 + 3 * k]) for k in range(3)))
    return m


def read_3mf(data):
    import io
    import zipfile
    z = zipfile.ZipFile(io.BytesIO(data))
    root = _ET.fromstring(z.read("3D/3dmodel.model"))
    ns = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
    m = Mesh()
    ids = [m.vid(float(v.get("x")), float(v.get("y")), float(v.get("z"))) for v in root.iter(ns + "vertex")]
    for t in root.iter(ns + "triangle"):
        m.add(ids[int(t.get("v1"))], ids[int(t.get("v2"))], ids[int(t.get("v3"))])
    return m


def model_export(res, spec, kind):
    """(bytes, Mesh) for a 3-D file of the flat cut blank. kind: 'stl' or '3mf'."""
    m = slab_mesh(res, spec)
    nm = "BoxForge RSC %sx%sx%s t%s %s" % (fmt(spec.L), fmt(spec.W), fmt(spec.H), fmt(spec.t), spec.units)
    return (mesh_to_stl(m, nm) if kind == "stl" else mesh_to_3mf(m, nm)), m


def model_notes(m):
    i = m.info
    out = ["3-D model in millimetres: flat blank %.1f x %.1f x %.1f mm, %d fold grooves, %d slots, %d windows."
           % (i["bbox"][2] - i["bbox"][0], i["bbox"][3] - i["bbox"][1], i["thickness"], i["grooves"], i["slots"],
              i["windows"])]
    if i["slots_dropped"]:
        out.append("%d dashed-fold slot(s) or slit(s) between flaps were left out (they touch an outline edge or another cut), so those flaps are joined in the solid."
                   % i["slots_dropped"])
    return out


def render_export(kind, d, units, notes, gcode=None, look=None):
    """Return the file contents (str, or bytes for PDF) for an export kind."""
    try:
        f = EXPORT_BY_KIND[kind]
    except KeyError:
        raise ValueError(kind) from None
    return f.render(d, units, notes, gcode, look)


