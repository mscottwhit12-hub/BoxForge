# =============================================================================
# ENGINE
# =============================================================================
CUT, FOLD, ENGRAVE = "CUT", "FOLD", "ENGRAVE"


# =============================================================================
# 2-D drawing container
# =============================================================================
class Drawing:
    def __init__(self):
        self.items = []  # ('L', p, q, layer) | ('A', centre, r, a0, a1, layer)   (arcs run CCW a0 -> a1, degrees)

    def line(self, p, q, layer):
        if math.dist(p, q) > 1e-9:
            self.items.append(("L", p, q, layer))

    def arc(self, c, r, a0, a1, layer):
        self.items.append(("A", c, r, a0 % 360, a1 % 360, layer))

    def rect(self, x0, y0, x1, y1, layer):
        self.line((x0, y0), (x1, y0), layer)
        self.line((x1, y0), (x1, y1), layer)
        self.line((x1, y1), (x0, y1), layer)
        self.line((x0, y1), (x0, y0), layer)

    def polyline(self, pts, radii, layer):
        """Open poly-line with a fillet radius per vertex (ends ignored)."""
        n = len(pts)
        cur = pts[0]
        for i in range(1, n - 1):
            P, A, B, r = pts[i], pts[i - 1], pts[i + 1], radii[i]
            la, lb = math.dist(A, P), math.dist(P, B)
            if r <= 0 or la == 0 or lb == 0:
                self.line(cur, P, layer)
                cur = P
                continue
            u = ((A[0] - P[0]) / la, (A[1] - P[1]) / la)
            v = ((B[0] - P[0]) / lb, (B[1] - P[1]) / lb)
            cosang = max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1]))
            theta = math.acos(cosang)
            if theta < 1e-6 or theta > math.pi - 1e-6:
                self.line(cur, P, layer)
                cur = P
                continue
            t2 = math.tan(theta / 2)
            d = r / t2
            dmax = min(la / (2 if i > 1 else 1), lb / (2 if i < n - 2 else 1))
            if d > dmax:
                d = dmax
                r = d * t2
            bx, by = u[0] + v[0], u[1] + v[1]
            bl = math.hypot(bx, by)
            bx, by = bx / bl, by / bl
            dist_c = r / math.sin(theta / 2)
            C = (P[0] + bx * dist_c, P[1] + by * dist_c)
            T1 = (P[0] + u[0] * d, P[1] + u[1] * d)
            T2 = (P[0] + v[0] * d, P[1] + v[1] * d)
            cross = (P[0] - A[0]) * (B[1] - P[1]) - (P[1] - A[1]) * (B[0] - P[0])
            a1 = math.degrees(math.atan2(T1[1] - C[1], T1[0] - C[0]))
            a2 = math.degrees(math.atan2(T2[1] - C[1], T2[0] - C[0]))
            self.line(cur, T1, layer)
            if cross > 0:
                self.arc(C, r, a1, a2, layer)
            else:
                self.arc(C, r, a2, a1, layer)
            cur = T2
        self.line(cur, pts[-1], layer)

    def bounds(self):
        xs, ys = [], []
        for it in self.items:
            if it[0] == "L":
                for p in (it[1], it[2]):
                    xs.append(p[0]); ys.append(p[1])
            else:
                _, c, r, a0, a1, _l = it
                span = (a1 - a0) % 360 or 360
                for k in range(33):
                    a = math.radians(a0 + span * k / 32)
                    xs.append(c[0] + r * math.cos(a)); ys.append(c[1] + r * math.sin(a))
        if not xs:
            return 0.0, 0.0, 0.0, 0.0
        return min(xs), min(ys), max(xs), max(ys)

    def without_layer(self, layer):
        d = Drawing()
        d.items = [it for it in self.items if it[-1] != layer]
        return d


# =============================================================================
# Closed outline with optional corner fillets
# =============================================================================
def fillet_outline(verts, samples=8):
    """verts: [(x, y)] or [(x, y, r)] describing a closed polygon (r = corner fillet radius).
    Returns (elements, polygon). elements are ('L', p, q) / ('A', c, r, a0, a1); polygon is a point list."""
    n = len(verts)
    P = [(v[0], v[1]) for v in verts]
    R = [(v[2] if len(v) > 2 else 0.0) for v in verts]
    cut = [None] * n
    for i in range(n):
        if R[i] <= 0:
            continue
        A, M, B = P[i - 1], P[i], P[(i + 1) % n]
        la, lb = math.dist(A, M), math.dist(M, B)
        if la < 1e-9 or lb < 1e-9:
            continue
        u = ((A[0] - M[0]) / la, (A[1] - M[1]) / la)
        v = ((B[0] - M[0]) / lb, (B[1] - M[1]) / lb)
        theta = math.acos(max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1])))
        if theta < 1e-4 or theta > math.pi - 1e-4:
            continue
        t2 = math.tan(theta / 2)
        d = R[i] / t2
        da = la * (0.5 if R[i - 1] > 0 else 1.0)
        db = lb * (0.5 if R[(i + 1) % n] > 0 else 1.0)
        d = min(d, da, db)
        r = d * t2
        bx, by = u[0] + v[0], u[1] + v[1]
        bl = math.hypot(bx, by)
        bx, by = bx / bl, by / bl
        dc = r / math.sin(theta / 2)
        C = (M[0] + bx * dc, M[1] + by * dc)
        T1 = (M[0] + u[0] * d, M[1] + u[1] * d)
        T2 = (M[0] + v[0] * d, M[1] + v[1] * d)
        cross = (M[0] - A[0]) * (B[1] - M[1]) - (M[1] - A[1]) * (B[0] - M[0])
        cut[i] = (T1, T2, C, r, cross > 0)

    entry, exit_ = [], []
    for i in range(n):
        if cut[i]:
            entry.append(cut[i][0]); exit_.append(cut[i][1])
        else:
            entry.append(P[i]); exit_.append(P[i])
    elems, poly = [], []
    for i in range(n):
        e, x = entry[i], exit_[i - 1]
        if math.dist(x, e) > 1e-9:
            elems.append(("L", x, e))
        if cut[i]:
            T1, T2, C, r, left = cut[i]
            a1 = math.atan2(T1[1] - C[1], T1[0] - C[0])
            a2 = math.atan2(T2[1] - C[1], T2[0] - C[0])
            if left:
                sweep = (a2 - a1) % (2 * math.pi)
                elems.append(("A", C, r, math.degrees(a1) % 360, math.degrees(a2) % 360))
            else:
                sweep = -((a1 - a2) % (2 * math.pi))
                elems.append(("A", C, r, math.degrees(a2) % 360, math.degrees(a1) % 360))
            poly.append(T1)
            for k in range(1, samples):
                a = a1 + sweep * k / samples
                poly.append((C[0] + r * math.cos(a), C[1] + r * math.sin(a)))
            poly.append(T2)
        else:
            poly.append(P[i])
    return elems, poly


class Panel:
    """One flat panel. `hinge` is the fold line joining it to `parent` (dieline coordinates)."""

    fold_segs = None      # the parts of `hinge` that are really creased (None = the whole hinge); a slit leaves a gap
    meta = None           # style-specific numbers a fold model needs (the insert keeps its slot / relief sizes here)
    group = None          # "insert" marks the panels of an insert (they fold / move on their own, not with the box)

    def __init__(self, name, verts=None, parent=None, hinge=None, angle=90.0, role="body", poly=None):
        self.name, self.parent, self.hinge, self.angle, self.role = name, parent, hinge, angle, role
        if poly is not None:
            self.elems, self.poly = [], list(poly)
        else:
            self.elems, self.poly = fillet_outline(verts)


def is_insert(p):
    return getattr(p, "group", None) == "insert"


def rect_verts(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


# =============================================================================
# Panels -> dieline (cut / fold classification)
# =============================================================================
def panels_to_drawing(panels, folds=True):
    """Every panel edge is a CUT unless it lies on a hinge, in which case it is a FOLD.
    Coincident edges of neighbouring panels are merged into a single line."""
    d = Drawing()
    segs = []
    for pn in panels:
        for e in pn.elems:
            if e[0] == "L":
                segs.append((e[1], e[2], "edge"))
            else:
                d.items.append(("A", e[1], e[2], e[3], e[4], CUT))
        if pn.hinge:
            for a, b in (pn.fold_segs or [pn.hinge]):
                segs.append((a, b, "hinge"))

    groups = {}
    for p, q, kind in segs:
        p = (round(p[0], 5), round(p[1], 5))
        q = (round(q[0], 5), round(q[1], 5))
        L = math.dist(p, q)
        if L < 1e-7:
            continue
        ux, uy = (q[0] - p[0]) / L, (q[1] - p[1]) / L
        if ux < -1e-9 or (abs(ux) <= 1e-9 and uy < 0):
            ux, uy = -ux, -uy
        c = -uy * p[0] + ux * p[1]
        s0, s1 = ux * p[0] + uy * p[1], ux * q[0] + uy * q[1]
        if s0 > s1:
            s0, s1 = s1, s0
        groups.setdefault((round(ux, 4), round(uy, 4)), []).append((c, s0, s1, kind, ux, uy))

    for items in groups.values():
        items.sort()
        clusters, cur = [], [items[0]]
        for it in items[1:]:
            if abs(it[0] - cur[-1][0]) < 5e-4:
                cur.append(it)
            else:
                clusters.append(cur); cur = [it]
        clusters.append(cur)
        for cl in clusters:
            c = sum(i[0] for i in cl) / len(cl)
            ux, uy = cl[0][4], cl[0][5]
            pts = sorted({round(v, 5) for i in cl for v in (i[1], i[2])})
            runs = []
            for a, b in zip(pts, pts[1:]):
                if b - a < 1e-6:
                    continue
                mid = (a + b) / 2
                cov = [i[3] for i in cl if i[1] <= mid <= i[2]]
                if not cov:
                    continue
                layer = FOLD if "hinge" in cov else CUT
                if runs and runs[-1][2] == layer and abs(runs[-1][1] - a) < 1e-6:
                    runs[-1][1] = b
                else:
                    runs.append([a, b, layer])
            for a, b, layer in runs:
                if layer == FOLD and not folds:
                    continue
                p = (a * ux - c * uy, a * uy + c * ux)
                q = (b * ux - c * uy, b * uy + c * ux)
                d.line(p, q, layer)
    return d


# =============================================================================
# Folding kinematics for the 3-D preview
# =============================================================================
def _matmul(A, B):
    return tuple(tuple(sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def _matvec(A, v):
    return tuple(sum(A[i][k] * v[k] for k in range(3)) for i in range(3))


def _rot_axis(u, th):
    ux, uy, uz = u
    c, s = math.cos(th), math.sin(th)
    C = 1 - c
    return ((c + ux * ux * C, ux * uy * C - uz * s, ux * uz * C + uy * s),
            (uy * ux * C + uz * s, c + uy * uy * C, uy * uz * C - ux * s),
            (uz * ux * C - uy * s, uz * uy * C + ux * s, c + uz * uz * C))


_I3 = ((1, 0, 0), (0, 1, 0), (0, 0, 1))


def fold_panels(panels, amount=1.0):
    """Return {panel name: [3-D points]} for a fold progress `amount` in 0..1 (staged parent -> child)."""
    depth = {}
    for p in panels:
        depth[p.name] = 0 if p.parent is None else depth[p.parent] + 1
    maxd = max(max(depth.values()), 1)
    xf, out = {}, {}
    for p in panels:
        if p.parent is None:
            R, t = _I3, (0.0, 0.0, 0.0)
        else:
            Rp, tp = xf[p.parent]
            (ax, ay), (bx, by) = p.hinge
            L = math.hypot(bx - ax, by - ay)
            ux, uy = (bx - ax) / L, (by - ay) / L
            cx = sum(q[0] for q in p.poly) / len(p.poly)
            cy = sum(q[1] for q in p.poly) / len(p.poly)
            side = 1.0 if ((cx - ax) * (-uy) + (cy - ay) * ux) > 0 else -1.0
            prog = min(1.0, max(0.0, amount * maxd - (depth[p.name] - 1)))
            Rot = _rot_axis((ux, uy, 0.0), math.radians(p.angle) * side * prog)
            q0 = (ax, ay, 0.0)
            Rq = _matvec(Rot, q0)
            R = _matmul(Rp, Rot)
            sh = _matvec(Rp, (q0[0] - Rq[0], q0[1] - Rq[1], q0[2] - Rq[2]))
            t = (sh[0] + tp[0], sh[1] + tp[1], sh[2] + tp[2])
        xf[p.name] = (R, t)
        pts = []
        for x, y in p.poly:
            v = _matvec(R, (x, y, 0.0))
            pts.append((v[0] + t[0], v[1] + t[1], v[2] + t[2]))
        out[p.name] = pts
    return out


# =============================================================================
# Geometry checks
# =============================================================================
def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _proper_cross(a1, a2, b1, b2, tol):
    la, lb = math.dist(a1, a2), math.dist(b1, b2)
    if la < 1e-9 or lb < 1e-9:
        return False
    d1, d2 = _cross(a1, a2, b1) / la, _cross(a1, a2, b2) / la
    d3, d4 = _cross(b1, b2, a1) / lb, _cross(b1, b2, a2) / lb
    return (d1 > tol and d2 < -tol or d1 < -tol and d2 > tol) and \
           (d3 > tol and d4 < -tol or d3 < -tol and d4 > tol)


def _point_in_poly(pt, poly):
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _dist_to_poly(pt, poly):
    best = 1e18
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        u = 0.0 if L2 == 0 else max(0.0, min(1.0, ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / L2))
        best = min(best, math.hypot(pt[0] - a[0] - u * dx, pt[1] - a[1] - u * dy))
    return best


def _strict_inside(pt, poly, tol):
    return _point_in_poly(pt, poly) and _dist_to_poly(pt, poly) > tol


def _samples(poly, tol):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    pts = list(poly)
    for i in range(1, 8):
        for j in range(1, 8):
            q = (x0 + (x1 - x0) * i / 8, y0 + (y1 - y0) * j / 8)
            if _strict_inside(q, poly, tol):
                pts.append(q)
    return pts


def overlapping_panels(panels, tol):
    """Names of panel pairs whose flat outlines overlap (touching edges are fine)."""
    bad = []
    boxes = []
    for p in panels:
        xs, ys = [q[0] for q in p.poly], [q[1] for q in p.poly]
        boxes.append((min(xs), min(ys), max(xs), max(ys)))
    cache = {}
    for i in range(len(panels)):
        for j in range(i + 1, len(panels)):
            a, b = boxes[i], boxes[j]
            if a[2] <= b[0] + tol or b[2] <= a[0] + tol or a[3] <= b[1] + tol or b[3] <= a[1] + tol:
                continue
            A, B = panels[i].poly, panels[j].poly
            hit = False
            for k in range(len(A)):
                for m in range(len(B)):
                    if _proper_cross(A[k], A[(k + 1) % len(A)], B[m], B[(m + 1) % len(B)], tol):
                        hit = True
                        break
                if hit:
                    break
            if not hit:
                for idx, (X, Y) in ((i, (A, B)), (j, (B, A))):
                    if idx not in cache:
                        cache[idx] = _samples(panels[idx].poly, tol)
                    if any(_strict_inside(pt, Y, tol) for pt in cache[idx]):
                        hit = True
                        break
            if hit:
                bad.append((panels[i].name, panels[j].name))
    return bad


