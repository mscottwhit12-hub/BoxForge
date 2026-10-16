#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BoxForge - box dieline studio for laser / die cutting
=====================================================
Pick a box style, type length / width / height / material thickness (inner, outer or maker
dimensions), preview the flat dieline and the folded box in 3-D, then export SVG or DXF.

    python dieline_generator.py                       open the app
    python dieline_generator.py --style rsc --L 200 --W 150 --H 120 --t 3 --dxf box.dxf

* Only needs Python 3.8+ (tkinter ships with Python; no other packages).
* DXF/SVG layers:  CUT = blue,  FOLD = red.
* Impossible designs are blocked (red), questionable ones are allowed with notes (amber)
  and the notes are saved inside the exported file.
"""
import math
import os
import sys

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, font as tkfont
    HAVE_TK = True
except ImportError:                                  # still lets the command-line mode work
    HAVE_TK = False

    class _Stub:
        def __getattr__(self, name):
            return type(name, (), {})
    tk = filedialog = messagebox = tkfont = _Stub()

# =============================================================================
# ENGINE
# =============================================================================
CUT, FOLD = "CUT", "FOLD"


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

    def __init__(self, name, verts=None, parent=None, hinge=None, angle=90.0, role="body", poly=None):
        self.name, self.parent, self.hinge, self.angle, self.role = name, parent, hinge, angle, role
        if poly is not None:
            self.elems, self.poly = [], list(poly)
        else:
            self.elems, self.poly = fillet_outline(verts)


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
            segs.append((pn.hinge[0], pn.hinge[1], "hinge"))

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


# =============================================================================
# Issues / results
# =============================================================================
class Issue:
    def __init__(self, level, msg, fields=()):
        self.level, self.msg, self.fields = level, msg, tuple(fields)

    def __repr__(self):
        return f"{self.level.upper()}: {self.msg}"


class Spec:
    def __init__(self, L, W, H, t, mode="inner", units="mm", opts=None, folds=True, flags=None,
                 sheet=(None, None)):
        self.L, self.W, self.H, self.t, self.mode, self.units = L, W, H, t, mode, units
        self.opts = opts or {}
        self.folds = folds
        self.flags = flags or {}
        self.sheet = sheet


class Ctx:
    """Everything a style needs while building (all lengths in the user's units)."""

    def __init__(self, spec, Lc, Wc, Hc):
        self.spec = spec
        self.Lc, self.Wc, self.Hc, self.t = Lc, Wc, Hc, spec.t
        self.mm = 25.4 if spec.units == "in" else 1.0       # millimetres per user unit
        self.o = spec.opts
        self.folds = spec.folds
        self.flags = spec.flags
        self.mode = spec.mode

    def mm_(self, x_mm):
        """A length given in millimetres, expressed in the user's units."""
        return x_mm / self.mm


class Result:
    def __init__(self, style, spec):
        self.style, self.spec = style, spec
        self.issues = []
        self.drawing = None
        self.panels = None
        self.info = {}

    @property
    def errors(self):
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self):
        return [i for i in self.issues if i.level == "warn"]

    @property
    def ok(self):
        return not self.errors

    def notes(self):
        return [f"{'NOTE' if i.level == 'warn' else i.level.upper()}: {i.msg}"
                for i in self.issues if i.level in ("warn", "error")]


def fmt(v, nd=2):
    s = f"{v:.{nd}f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


# =============================================================================
# Styles
# =============================================================================
class Style:
    id = name = code = blurb = ""
    status = "standard"            # calibrated | standard | experimental
    defaults = dict(L=150.0, W=100.0, H=120.0, t=2.0)
    options = []                   # [(key, label)]  blank = automatic
    toggles = []                   # [(key, label, default)]
    ratio_dims = ("L", "W", "H")
    height_label = "Height"
    view_up = "y"                  # which folded axis points up in the 3-D preview
    mode_help = {
        "inner": "Inside of the finished box (what fits in it).",
        "outer": "Outside of the finished box.",
        "manufacturer": "Centre-of-crease (fold-to-fold) panel sizes.",
    }

    # fold-to-fold (crease centre) sizes from the user's numbers
    def crease(self, L, W, H, t, mode):
        k = {"inner": t, "outer": -t, "manufacturer": 0.0}[mode]
        return L + k, W + k, H + k

    # inside dimensions from crease sizes
    def inner(self, Lc, Wc, Hc, t):
        return Lc - t, Wc - t, Hc - t

    def resolve(self, c):
        return {}

    def check(self, c, r, issues):
        pass

    def build(self, c, r):
        raise NotImplementedError


def _auto(c, key, default):
    v = c.o.get(key)
    return default if v is None else v


# -----------------------------------------------------------------------------
class TuckTop(Style):
    id, name = "tucktop", "Tuck-Top Box"
    code = "Hinged lid · dust flaps"
    blurb = "Back-hinged lid with a front lip, rounded tuck flap and dust flaps. Calibrated against a reference dieline."
    status = "calibrated"
    options = [("dust", "Dust flap width"), ("outer", "Outer side flap width"),
               ("tuck", "Tuck flap length"), ("clear", "Lip side clearance")]
    toggles = [("slots", "Corner relief slots", True)]

    def resolve(self, c):
        Lc, Wc, Hc, t = c.Lc, c.Wc, c.Hc, c.t
        th = _auto(c, "tuck", max(2.2 * t, min(Wc, 0.9 * Hc, Hc - 2.5 * t)))
        r = dict(g=t,
                 dw=_auto(c, "dust", min(Wc * 0.5 + t, 0.9 * Hc)),
                 fw=_auto(c, "outer", Wc),
                 th=th,
                 c=_auto(c, "clear", t),
                 lip=Hc + t * 0.5,
                 tc=t * 0.4)
        r["taper"] = 0.11 * th
        r["ww"] = th - t
        r["ytop"] = Hc + Wc + r["lip"]
        return r

    def check(self, c, r, iss):
        Lc, Wc, Hc, t = c.Lc, c.Wc, c.Hc, c.t
        if Lc - 2 * r["c"] <= 0:
            iss.append(Issue("error", "Lip side clearance is too large for this length.", ("L", "clear")))
        if r["th"] <= 2 * t:
            iss.append(Issue("error", f"Tuck flap must be longer than 2× the board thickness ({fmt(2 * t)}).",
                             ("tuck", "t")))
        elif r["th"] > Hc - 2 * t:
            iss.append(Issue("warn", "Tuck flap is longer than the box is deep, so it will buckle against the "
                                     "bottom panel. Shorten it or increase the height.", ("tuck", "H")))
        if r["dw"] > Hc:
            iss.append(Issue("warn", "Dust flaps are taller than the box; they will stick out of the sides.",
                             ("dust", "H")))
        if r["dw"] < 3 * t:
            iss.append(Issue("warn", "Dust flaps are very narrow for this board thickness.", ("dust", "t")))
        if r["fw"] > Lc:
            iss.append(Issue("warn", "Outer side flaps are wider than the front face and will overlap.",
                             ("outer", "L")))
        if max(Lc, Hc) / max(Wc, 1e-9) > 6 or Wc / max(min(Lc, Hc), 1e-9) > 4:
            iss.append(Issue("warn", "Extreme proportions: the lid / tuck geometry is unproven at this "
                                     "aspect ratio. Check the 3-D preview and cut a test piece.", ("L", "W", "H")))

    def build(self, c, r):
        Lc, Wc, Hc, t = c.Lc, c.Wc, c.Hc, c.t
        drawing = tucktop_drawing(Lc, Wc, Hc, t, r, c.folds, c.flags.get("slots", True))
        return tucktop_panels(Lc, Wc, Hc, t, r), drawing


def tucktop_drawing(L, W, H, t, r, folds=True, slots=True):
    """Hand-built dieline, calibrated against the reference screenshot."""
    g, dw, fw, th, c = r["g"], r["dw"], r["fw"], r["th"], r["c"]
    lip, tc, taper, ww, ytop = r["lip"], r["tc"], r["taper"], r["ww"], r["ytop"]
    d = Drawing()

    def fld(p, q):
        if folds:
            d.line(p, q, FOLD)

    fld((0, H), (L, H))
    fld((0, 0), (L, 0))
    sh = H / 3
    ys0, ys1 = H / 2 - sh / 2, H / 2 + sh / 2
    for x in (0, L):
        if slots:
            d.rect(x - t / 2, ys0, x + t / 2, ys1, CUT)
            fld((x, 0), (x, ys0)); fld((x, ys1), (x, H))
        else:
            fld((x, 0), (x, H))

    for sign, edge in ((-1, 0.0), (1, L)):
        ex = lambda u, s=sign, e=edge: e + s * u
        far = W + g + fw
        d.line((ex(far), H), (ex(0), H), CUT)
        d.line((ex(far), 0), (ex(0), 0), CUT)
        if slots:
            s_b, h_b = t * 0.5, sh / 2
            R_b = (h_b ** 2 + s_b ** 2) / (2 * s_b)
            th_b = math.degrees(math.asin(min(1.0, h_b / R_b)))
            a_c = 0 if sign > 0 else 180
            d.line((ex(far), 0), (ex(far), ys0), CUT)
            d.line((ex(far), ys1), (ex(far), H), CUT)
            d.arc((ex(far) + sign * (s_b - R_b), H / 2), R_b, a_c - th_b, a_c + th_b, CUT)
        else:
            d.line((ex(far), 0), (ex(far), H), CUT)
        fld((ex(W), 0), (ex(W), H))
        fld((ex(W + g), 0), (ex(W + g), H))
        d.line((ex(dw), H), (ex(dw), H + W), CUT)
        fld((ex(0), H), (ex(0), H + W))
        d.line((ex(dw), H + W), (ex(-c), H + W), CUT)
        d.line((ex(dw), 0), (ex(dw), -W), CUT)
        fld((ex(0), 0), (ex(0), -W))
        yb = H + W + tc
        d.line((ex(-c), H + W), (ex(-c), yb), CUT)
        fld((ex(-c), yb), (ex(-c), ytop))
        oh = 0.41 * (ytop - yb)
        pts = [(ex(-c), yb), (ex(W - c), yb), (ex(W - c), yb + oh), (ex(-c), ytop)]
        d.polyline(pts, [0, 0.2 * W, 0.16 * W, 0], CUT)

    d.line((-dw, -W), (L + dw, -W), CUT)
    fld((c, H + W), (L - c, H + W))
    fld((c, ytop), (L - c, ytop))
    d.line((0, ytop), (c, ytop), CUT)
    d.line((L - c, ytop), (L, ytop), CUT)
    fld((0, ytop), (0, ytop + th))
    fld((L, ytop), (L, ytop + th))
    R = th
    ph = math.degrees(math.acos(max(-1.0, min(1.0, ww / R))))
    ay = math.sqrt(max(0.0, R * R - ww * ww))
    for sgn, x_h in ((-1, 0.0), (1, L)):
        x_o = x_h + sgn * ww
        d.line((x_h, ytop), (x_o, ytop + taper), CUT)
        d.line((x_o, ytop + taper), (x_o, ytop + ay), CUT)
        if sgn < 0:
            d.arc((x_h, ytop), R, 90, 180 - ph, CUT)
        else:
            d.arc((x_h, ytop), R, ph, 90, CUT)
    d.line((0, ytop + th), (L, ytop + th), CUT)
    return d


def tucktop_panels(L, W, H, t, r):
    g, dw, fw, th, c = r["g"], r["dw"], r["fw"], r["th"], r["c"]
    lip, tc, taper, ww, ytop = r["lip"], r["tc"], r["taper"], r["ww"], r["ytop"]
    P = []
    P.append(Panel("back", rect_verts(0, 0, L, H)))
    for sign, edge in ((-1, 0.0), (1, L)):
        ex = lambda u, s=sign, e=edge: e + s * u
        tag = "L" if sign < 0 else "R"
        P.append(Panel("side" + tag, [(ex(0), 0), (ex(W), 0), (ex(W), H), (ex(0), H)], "back",
                       ((ex(0), 0), (ex(0), H))))
        P.append(Panel("strip" + tag, [(ex(W), 0), (ex(W + g), 0), (ex(W + g), H), (ex(W), H)], "side" + tag,
                       ((ex(W), 0), (ex(W), H)), 45, "flap"))
        P.append(Panel("outer" + tag, [(ex(W + g), 0), (ex(W + g + fw), 0), (ex(W + g + fw), H), (ex(W + g), H)],
                       "strip" + tag, ((ex(W + g), 0), (ex(W + g), H)), 45, "flap"))
    P.append(Panel("bottom", rect_verts(0, -W, L, 0), "back", ((0, 0), (L, 0))))
    P.append(Panel("lid", rect_verts(0, H, L, H + W), "back", ((0, H), (L, H))))
    P.append(Panel("lip", rect_verts(c, H + W, L - c, ytop), "lid", ((c, H + W), (L - c, H + W))))
    for sign, edge in ((-1, 0.0), (1, L)):
        ex = lambda u, s=sign, e=edge: e + s * u
        tag = "L" if sign < 0 else "R"
        P.append(Panel("bdust" + tag, [(ex(0), -W), (ex(dw), -W), (ex(dw), 0), (ex(0), 0)], "bottom",
                       ((ex(0), -W), (ex(0), 0)), 90, "flap"))
        P.append(Panel("ldust" + tag, [(ex(0), H), (ex(dw), H), (ex(dw), H + W), (ex(0), H + W)], "lid",
                       ((ex(0), H), (ex(0), H + W)), 90, "flap"))
        yb = H + W + tc
        oh = 0.41 * (ytop - yb)
        P.append(Panel("tab" + tag, [(ex(-c), yb, 0), (ex(W - c), yb, 0.2 * W), (ex(W - c), yb + oh, 0.16 * W),
                                     (ex(-c), ytop, 0)], "lip", ((ex(-c), yb), (ex(-c), ytop)), 90, "flap"))
    P.append(Panel("tuck", rect_verts(0, ytop, L, ytop + th), "lip", ((c, ytop), (L - c, ytop)), 90, "flap"))
    R = th
    ay = math.sqrt(max(0.0, R * R - ww * ww))
    a_end = math.atan2(ay, ww)
    for sgn, x_h in ((-1, 0.0), (1, L)):
        x_o = x_h + sgn * ww
        pts = [(x_h, ytop), (x_o, ytop + taper), (x_o, ytop + ay)]
        for k in range(1, 11):
            ang = a_end + (math.pi / 2 - a_end) * k / 10
            pts.append((x_h + sgn * R * math.cos(ang), ytop + R * math.sin(ang)))
        P.append(Panel("wing" + ("L" if sgn < 0 else "R"), poly=pts, parent="tuck",
                       hinge=((x_h, ytop), (x_h, ytop + th)), angle=90, role="flap"))
    return P


# -----------------------------------------------------------------------------
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
    options = [("glue", "Glue flap width"), ("slot", "Slot width"), ("flap", "Flap length")]
    mode_help = {
        "inner": "Inside of the box (FEFCO internal size: crease centre − 1 board; height − 2 boards).",
        "outer": "Outside of the closed box.",
        "manufacturer": "Centre-of-crease sizes straight onto the blank.",
    }

    def crease(self, L, W, H, t, mode):
        return {"inner": (L + t, W + t, H + 2 * t),
                "outer": (L - t, W - t, H - t),
                "manufacturer": (L, W, H)}[mode]

    def inner(self, Lc, Wc, Hc, t):
        return Lc - t, Wc - t, Hc - 2 * t

    def resolve(self, c):
        t, Lc, Wc = c.t, c.Lc, c.Wc
        glue = _auto(c, "glue", max(3 * t, min(c.mm_(25), 0.4 * min(Lc, Wc))))
        return dict(glue=glue, slot=_auto(c, "slot", max(2 * t, c.mm_(1.0))), flap=_auto(c, "flap", Wc / 2))

    def check(self, c, r, iss):
        t = c.t
        if r["slot"] >= min(c.Lc, c.Wc) * 0.5:
            iss.append(Issue("error", "Slot width is too large for the smallest panel.", ("slot",)))
        if r["glue"] < 3 * t:
            iss.append(Issue("error", f"Manufacturer's joint must be at least 3× the board thickness ({fmt(3 * t)}).",
                             ("glue", "t")))
        elif r["glue"] < c.mm_(12):
            iss.append(Issue("warn", "Manufacturer's joint is narrow (<12 mm); the glue bond may be weak.", ("glue",)))
        if r["slot"] < t:
            iss.append(Issue("warn", "Slots narrower than the board thickness can make the flaps catch on each "
                                     "other when folding.", ("slot", "t")))
        if r["flap"] > c.Wc / 2 + 1e-6:
            iss.append(Issue("warn", "Flaps longer than half the width collide in the middle of the box.", ("flap",)))
        elif r["flap"] < 0.45 * c.Wc:
            iss.append(Issue("warn", "Flaps shorter than ~half the width leave a gap in the closed box.", ("flap",)))

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
        return P, None


# -----------------------------------------------------------------------------
class Sleeve(Style):
    id, name = "sleeve", "Sleeve / Tube"
    code = "Open both ends"
    blurb = "A four-wall wrap with a glued seam. Slips over a tray or product to make a slipcase or belly band."
    status = "standard"
    defaults = dict(L=150.0, W=100.0, H=60.0, t=2.0)
    options = [("glue", "Glue flap width")]
    ratio_dims = ("L", "W")
    height_label = "Length (open ends)"

    def crease(self, L, W, H, t, mode):
        k = {"inner": t, "outer": -t, "manufacturer": 0.0}[mode]
        return L + k, W + k, H

    def inner(self, Lc, Wc, Hc, t):
        return Lc - t, Wc - t, Hc

    def resolve(self, c):
        return dict(glue=_auto(c, "glue", max(3 * c.t, min(c.mm_(20), 0.4 * min(c.Lc, c.Wc)))))

    def check(self, c, r, iss):
        if r["glue"] < 3 * c.t:
            iss.append(Issue("error", f"Seam flap must be at least 3× the board thickness ({fmt(3 * c.t)}).",
                             ("glue", "t")))
        elif r["glue"] < c.mm_(10):
            iss.append(Issue("warn", "Seam flap is narrow (<10 mm); the glue bond may be weak.", ("glue",)))
        if c.Hc < 2 * c.t:
            iss.append(Issue("error", "Sleeve length must be at least 2× the board thickness.", ("H", "t")))

    def build(self, c, r):
        P, _ = _loop_bodies(c.Lc, c.Wc, c.Hc, r["glue"])
        return P, None


# -----------------------------------------------------------------------------
def tray_panels(Lc, Wc, Hc, fw, rf, ox=0.0, oy=0.0, pre=""):
    """Open tray: bottom + 4 walls + 4 corner flaps hinged on the front/back walls."""
    def X(x): return x + ox
    def Y(y): return y + oy
    n = lambda s: pre + s
    P = [Panel(n("bottom"), rect_verts(X(0), Y(0), X(Lc), Y(Wc)))]
    P.append(Panel(n("front"), rect_verts(X(0), Y(-Hc), X(Lc), Y(0)), n("bottom"), ((X(0), Y(0)), (X(Lc), Y(0)))))
    P.append(Panel(n("back"), rect_verts(X(0), Y(Wc), X(Lc), Y(Wc + Hc)), n("bottom"),
                   ((X(0), Y(Wc)), (X(Lc), Y(Wc)))))
    P.append(Panel(n("left"), rect_verts(X(-Hc), Y(0), X(0), Y(Wc)), n("bottom"), ((X(0), Y(0)), (X(0), Y(Wc)))))
    P.append(Panel(n("right"), rect_verts(X(Lc), Y(0), X(Lc + Hc), Y(Wc)), n("bottom"),
                   ((X(Lc), Y(0)), (X(Lc), Y(Wc)))))
    if fw > 0:
        P.append(Panel(n("cfl"), [(X(0), Y(-Hc), 0), (X(0), Y(0), 0), (X(-fw), Y(0), 0), (X(-fw), Y(-Hc), rf)],
                       n("front"), ((X(0), Y(-Hc)), (X(0), Y(0))), 90, "flap"))
        P.append(Panel(n("cfr"), [(X(Lc), Y(-Hc), 0), (X(Lc + fw), Y(-Hc), rf), (X(Lc + fw), Y(0), 0), (X(Lc), Y(0), 0)],
                       n("front"), ((X(Lc), Y(-Hc)), (X(Lc), Y(0))), 90, "flap"))
        P.append(Panel(n("cbl"), [(X(0), Y(Wc), 0), (X(0), Y(Wc + Hc), 0), (X(-fw), Y(Wc + Hc), rf), (X(-fw), Y(Wc), 0)],
                       n("back"), ((X(0), Y(Wc)), (X(0), Y(Wc + Hc))), 90, "flap"))
        P.append(Panel(n("cbr"), [(X(Lc), Y(Wc), 0), (X(Lc + fw), Y(Wc), 0), (X(Lc + fw), Y(Wc + Hc), rf),
                                  (X(Lc), Y(Wc + Hc), 0)],
                       n("back"), ((X(Lc), Y(Wc)), (X(Lc), Y(Wc + Hc))), 90, "flap"))
    return P


class Tray(Style):
    id, name = "tray", "Folding Tray"
    code = "Glued corner flaps"
    blurb = "Open-top tray from one blank. Corner flaps fold inside the end walls and are glued or taped."
    status = "standard"
    view_up = "z"
    defaults = dict(L=150.0, W=100.0, H=40.0, t=2.0)
    options = [("flap", "Corner flap width")]
    mode_help = {
        "inner": "Inside of the tray (floor to rim = height).",
        "outer": "Outside of the tray.",
        "manufacturer": "Centre-of-crease sizes (wall length = crease to rim).",
    }

    def crease(self, L, W, H, t, mode):
        return {"inner": (L + t, W + t, H + t / 2), "outer": (L - t, W - t, H - t / 2),
                "manufacturer": (L, W, H)}[mode]

    def inner(self, Lc, Wc, Hc, t):
        return Lc - t, Wc - t, Hc - t / 2

    def resolve(self, c):
        return dict(flap=_auto(c, "flap", min(max(c.t, c.Hc - c.t), 0.45 * c.Wc)))

    def check(self, c, r, iss):
        fw = r["flap"]
        if fw > c.Hc + 1e-6:
            iss.append(Issue("warn", "Corner flaps wider than the wall height will poke past the rim.", ("flap",)))
        if fw < 2 * c.t:
            iss.append(Issue("warn", "Corner flaps are very narrow; the glue area is small.", ("flap", "t")))
        if 2 * fw > c.Wc:
            iss.append(Issue("warn", "Front and back corner flaps overlap each other on the end wall. Make the "
                                     "flaps narrower or the tray wider.", ("flap", "W")))

    def build(self, c, r):
        rf = min(0.25 * c.Hc, 4 * c.t)
        return tray_panels(c.Lc, c.Wc, c.Hc, r["flap"], rf), None


# -----------------------------------------------------------------------------
class Telescope(Style):
    id, name = "telescope", "Lid & Base"
    code = "FEFCO 0301 style"
    blurb = "Two-piece telescope box: a tray base and a slightly larger tray lid that slides over it. One sheet, two trays."
    status = "standard"
    view_up = "z"
    defaults = dict(L=150.0, W=100.0, H=60.0, t=2.0)
    options = [("lidh", "Lid depth (outside)"), ("clr", "Lid clearance"), ("flap", "Corner flap width")]
    height_label = "Base height"
    mode_help = {
        "inner": "Inside of the BASE tray (the lid is sized from it).",
        "outer": "Outside of the BASE tray.",
        "manufacturer": "Centre-of-crease sizes of the BASE tray.",
    }

    def crease(self, L, W, H, t, mode):
        return {"inner": (L + t, W + t, H + t / 2), "outer": (L - t, W - t, H - t / 2),
                "manufacturer": (L, W, H)}[mode]

    def inner(self, Lc, Wc, Hc, t):
        return Lc - t, Wc - t, Hc - t / 2

    def resolve(self, c):
        t, Hc = c.t, c.Hc
        clr = _auto(c, "clr", max(c.mm_(0.6), 0.25 * t))
        lidh = _auto(c, "lidh", max(3 * t, 0.4 * Hc))
        return dict(clr=clr, lidh=lidh, flap=_auto(c, "flap", min(max(c.t, Hc - c.t), 0.45 * c.Wc)),
                    Llc=c.Lc + 2 * t + clr, Wlc=c.Wc + 2 * t + clr, Hlc=lidh - t / 2)

    def check(self, c, r, iss):
        t = c.t
        if r["clr"] < 0:
            iss.append(Issue("error", "Lid clearance cannot be negative.", ("clr",)))
        elif r["clr"] < c.mm_(0.3):
            iss.append(Issue("warn", "Lid clearance under 0.3 mm is tighter than most laser / die cutting can hold; "
                                     "the lid may not go on.", ("clr",)))
        elif r["clr"] > 2 * t:
            iss.append(Issue("warn", "Lid clearance is more than 2× the board thickness; the lid will be loose.",
                             ("clr", "t")))
        if r["lidh"] < 2.5 * t:
            iss.append(Issue("error", f"Lid depth must be at least 2.5× the board thickness ({fmt(2.5 * t)}).",
                             ("lidh", "t")))
        elif r["lidh"] > c.Hc:
            iss.append(Issue("warn", "Lid is deeper than the base; it will bottom out on the table before closing.",
                             ("lidh", "H")))
        elif r["lidh"] < c.Hc / 4:
            iss.append(Issue("warn", "Shallow lid (<¼ of the base height): little overlap, so it may slip off.",
                             ("lidh",)))
        fw = r["flap"]
        if 2 * fw > c.Wc:
            iss.append(Issue("warn", "Base corner flaps overlap each other. Make them narrower.", ("flap", "W")))

    def build(self, c, r):
        t = c.t
        rf = min(0.25 * c.Hc, 4 * t)
        base = tray_panels(c.Lc, c.Wc, c.Hc, r["flap"], rf, 0, 0, "b_")
        gap = max(c.mm_(8), 2 * t)
        ox = c.Lc + c.Hc + gap + r["Hlc"]
        oy = (c.Wc - r["Wlc"]) / 2
        fwl = min(r["flap"] * 0.9 + t, r["Hlc"])
        lid = tray_panels(r["Llc"], r["Wlc"], r["Hlc"], fwl, min(0.25 * r["Hlc"], 4 * t), ox, oy, "l_")
        return base + lid, None


# -----------------------------------------------------------------------------
class Mailer(Style):
    id, name = "mailer", "Roll-End Mailer"
    code = "FEFCO 0427 style"
    blurb = "One-piece mailer: rolled double-wall ends, hinged lid and a front tuck. Simplified layout - prototype first."
    status = "experimental"
    view_up = "z"
    defaults = dict(L=180.0, W=120.0, H=50.0, t=2.0)
    options = [("tuck", "Lid tuck length"), ("dust", "Lid side flap"), ("roll", "Roll-over width"),
               ("flap", "Corner flap width")]
    mode_help = {
        "inner": "Inside of the mailer (ends are 3 board layers thick).",
        "outer": "Outside of the closed mailer.",
        "manufacturer": "Centre-of-crease sizes of the bottom panel and wall height.",
    }

    def crease(self, L, W, H, t, mode):
        return {"inner": (L + 5 * t, W + t, H + t / 2), "outer": (L - t, W - t, H - 1.5 * t),
                "manufacturer": (L, W, H)}[mode]

    def inner(self, Lc, Wc, Hc, t):
        return Lc - 5 * t, Wc - t, Hc - t / 2

    def resolve(self, c):
        t, Hc = c.t, c.Hc
        return dict(tuck=_auto(c, "tuck", max(2 * t, 0.7 * Hc)),
                    dust=_auto(c, "dust", max(2 * t, 0.8 * Hc)),
                    roll=_auto(c, "roll", max(t, Hc - 2 * t)),
                    flap=_auto(c, "flap", min(max(t, Hc - 2 * t), 0.45 * c.Wc)),
                    ct=2 * t)

    def check(self, c, r, iss):
        t = c.t
        iss.append(Issue("info", "Experimental style: this layout follows the roll-end / tuck-front idea "
                                 "(unbroken base, double-layer ends, locking cover) but has no lock slots. "
                                 "Cut a prototype before committing to board.", ()))
        if r["tuck"] > c.Hc:
            iss.append(Issue("warn", "Lid tuck is longer than the front wall; it will hit the base.", ("tuck", "H")))
        if r["roll"] > c.Hc - t:
            iss.append(Issue("warn", "Roll-over panels are too tall and will hit the base panel.", ("roll", "H")))
        if 2 * r["flap"] > c.Wc:
            iss.append(Issue("warn", "Front and back corner flaps overlap on the end walls.", ("flap", "W")))
        if r["dust"] > c.Hc:
            iss.append(Issue("warn", "Lid side flaps are taller than the box.", ("dust", "H")))
        mm = c.mm
        i = self.inner(c.Lc, c.Wc, c.Hc, t)
        if i[2] > i[0] + 1e-9:
            iss.append(Issue("warn", "Depth exceeds length - roll-end mailers are normally wider than they are deep.",
                             ("H", "L")))
        if i[0] * mm < 76 or i[1] * mm < 76 or i[2] * mm < 25:
            iss.append(Issue("warn", "Smaller than ~76 x 76 x 25 mm: one commercial maker quotes this as the minimum "
                                     "size for this style. Folds may not seat.", ("L", "W", "H")))

    def build(self, c, r):
        Lc, Wc, Hc, t = c.Lc, c.Wc, c.Hc, c.t
        fw, ro, ct = r["flap"], r["roll"], r["ct"]
        rf = min(0.25 * Hc, 4 * t)
        P = tray_panels(Lc, Wc, Hc, fw, rf)
        # roll-over panels fold back over the end walls (and the corner flaps)
        P.append(Panel("rollL", rect_verts(-Hc - ro, 0, -Hc, Wc), "left", ((-Hc, 0), (-Hc, Wc)), 175, "flap"))
        P.append(Panel("rollR", rect_verts(Lc + Hc, 0, Lc + Hc + ro, Wc), "right", ((Lc + Hc, 0), (Lc + Hc, Wc)),
                       175, "flap"))
        # lid hinged on the back wall
        yl = Wc + Hc
        lid_d = Wc + t
        P.append(Panel("lid", rect_verts(0, yl, Lc, yl + lid_d), "back", ((0, yl), (Lc, yl))))
        P.append(Panel("tuck", [(ct, yl + lid_d, 0), (Lc - ct, yl + lid_d, 0), (Lc - ct - 0.4 * r["tuck"], yl + lid_d + r["tuck"], rf),
                                (ct + 0.4 * r["tuck"], yl + lid_d + r["tuck"], rf)],
                       "lid", ((ct, yl + lid_d), (Lc - ct, yl + lid_d)), 90, "flap"))
        dust = r["dust"]
        P.append(Panel("ldustL", [(0, yl, 0), (-dust, yl + 0.15 * lid_d, 0), (-dust, yl + 0.85 * lid_d, rf),
                                  (0, yl + lid_d, 0)], "lid", ((0, yl), (0, yl + lid_d)), 90, "flap"))
        P.append(Panel("ldustR", [(Lc, yl, 0), (Lc, yl + lid_d, 0), (Lc + dust, yl + 0.85 * lid_d, rf),
                                  (Lc + dust, yl + 0.15 * lid_d, 0)], "lid", ((Lc, yl), (Lc, yl + lid_d)), 90,
                       "flap"))
        return P, None


STYLES = [TuckTop(), RSC(), Tray(), Telescope(), Sleeve(), Mailer()]
STYLE_BY_ID = {s.id: s for s in STYLES}


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
    for key, v in spec.opts.items():
        if v is not None and (not math.isfinite(v) or v <= 0):
            iss.append(Issue("error", "Advanced values must be positive numbers (leave blank for automatic).", (key,)))
    if res.errors:
        return res

    t = spec.t
    try:
        Lc, Wc, Hc = style.crease(spec.L, spec.W, spec.H, t, spec.mode)
    except KeyError:
        iss.append(Issue("error", "Unknown dimension mode.", ()))
        return res
    c = Ctx(spec, Lc, Wc, Hc)
    Li, Wi, Hi = style.inner(Lc, Wc, Hc, t)
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
        if drawing is None:
            drawing = panels_to_drawing(panels, spec.folds)
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


# =============================================================================
# Exporters
# =============================================================================
def to_dxf(d, units="mm", notes=()):
    out = []
    w = lambda code, val: out.extend([str(code), str(val)])
    f = lambda v: f"{v:.5f}"
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
    w(0, "TABLE"); w(2, "LAYER"); w(70, 2)
    for name, col in ((CUT, 5), (FOLD, 1)):
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


def to_svg(d, units="mm", margin=5.0, notes=()):
    x0, y0, x1, y1 = d.bounds()
    mg = margin if units == "mm" else margin / 25.4
    x0 -= mg; y0 -= mg; x1 += mg; y1 += mg
    W, H = x1 - x0, y1 - y0
    sw = 0.1 if units == "mm" else 0.004
    X = lambda x: x - x0
    Y = lambda y: y1 - y
    groups = {CUT: [], FOLD: []}
    for it in d.items:
        if it[0] == "L":
            _, p, q, layer = it
            groups[layer].append(
                f'<line x1="{X(p[0]):.4f}" y1="{Y(p[1]):.4f}" x2="{X(q[0]):.4f}" y2="{Y(q[1]):.4f}"/>')
        else:
            _, c, r, a0, a1, layer = it
            span = (a1 - a0) % 360
            sx, sy = c[0] + r * math.cos(math.radians(a0)), c[1] + r * math.sin(math.radians(a0))
            ex_, ey = c[0] + r * math.cos(math.radians(a1)), c[1] + r * math.sin(math.radians(a1))
            large = 1 if span > 180 else 0
            groups[layer].append(
                f'<path d="M {X(sx):.4f} {Y(sy):.4f} A {r:.4f} {r:.4f} 0 {large} 0 {X(ex_):.4f} {Y(ey):.4f}"/>')
    colours = {CUT: "#0000ff", FOLD: "#ff0000"}
    body = "\n".join(
        f'<g id="{k}" fill="none" stroke="{colours[k]}" stroke-width="{sw}" stroke-linecap="round">\n'
        + "\n".join(v) + "\n</g>" for k, v in groups.items())
    desc = f"<desc>{_xml(' | '.join(notes))}</desc>\n" if notes else ""
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.3f}{units[:2]}" height="{H:.3f}{units[:2]}" '
            f'viewBox="0 0 {W:.4f} {H:.4f}">\n{desc}{body}\n</svg>\n')


# =============================================================================
# GUI
# =============================================================================
# =============================================================================
# Theme
# =============================================================================
T = dict(
    bg="#121217", rail="#0c0c10", panel="#1a1a21", panel2="#22222b", card="#1e1e26", card_h="#262633",
    thumb="#15151b", border="#2f2f3b", border_h="#8b5cf6", text="#ececf3", muted="#9a9ab0", dim="#6c6c80",
    accent="#8b5cf6", accent_h="#a07bff", good="#34d399", warn="#fbbf24", err="#f87171", info="#60a5fa",
    cut="#5b8cff", fold="#ff5d5d", canvas="#16161c", grid="#1f1f27",
    body="#67e8f9", body_dim="#1f5560", flap="#c4b5fd", flap_dim="#473a78",
)
FAMILY = "TkDefaultFont"


def init_fonts(root):
    global FAMILY
    try:
        fams = set(tkfont.families(root))
    except Exception:
        fams = set()
    for f in ("Segoe UI", "SF Pro Text", "Helvetica Neue", "Inter", "Ubuntu", "DejaVu Sans", "Helvetica", "Arial"):
        if f in fams:
            FAMILY = f
            return


def F(size=10, weight="normal"):
    return (FAMILY, size, weight)


def _rgb(h):
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def mix(c1, c2, t):
    a, b = _rgb(c1), _rgb(c2)
    t = max(0.0, min(1.0, t))
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def parse_num(s):
    """'12', '12.5', '1/2', '1 1/2' -> float; blank -> None; anything else raises ValueError."""
    s = (s or "").strip().replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    try:
        if "/" in s:
            parts = s.split()
            whole = float(parts[0]) if len(parts) == 2 else 0.0
            n, d = parts[-1].split("/")
            return whole + float(n) / float(d)
    except (ValueError, ZeroDivisionError):
        pass
    raise ValueError(s)


# =============================================================================
# Small widgets
# =============================================================================
class Btn(tk.Label):
    KINDS = {"primary": ("accent", "accent_h", "#ffffff"), "ghost": ("panel2", "border", "text"),
             "flat": ("panel", "panel2", "text")}

    def __init__(self, master, text, command=None, kind="ghost", size=10, padx=14, pady=8, bold=False, **kw):
        self.kind, self.command, self.enabled = kind, command, True
        bg, hov, fg = self.KINDS[kind]
        super().__init__(master, text=text, font=F(size, "bold" if bold or kind == "primary" else "normal"),
                         bg=T[bg], fg=fg if fg.startswith("#") else T[fg], padx=padx, pady=pady,
                         cursor="hand2", **kw)
        self.bind("<Enter>", lambda e=None: self._paint(True))
        self.bind("<Leave>", lambda e=None: self._paint(False))
        self.bind("<Button-1>", self._click)

    def _paint(self, hover):
        bg, hov, fg = self.KINDS[self.kind]
        if not self.enabled:
            self.config(bg=T["panel2"], fg=T["dim"], cursor="arrow")
            return
        self.config(bg=T[hov] if hover else T[bg], fg=fg if fg.startswith("#") else T[fg], cursor="hand2")

    def _click(self, e):
        if self.command and self.enabled:
            self.command()

    def set_enabled(self, on):
        self.enabled = on
        self._paint(False)


class Seg(tk.Frame):
    def __init__(self, master, options, var, size=9, bg=None):
        super().__init__(master, bg=T["panel2"], highlightthickness=1, highlightbackground=T["border"])
        self.var, self.labels = var, {}
        for val, text in options:
            lb = tk.Label(self, text=text, font=F(size), padx=11, pady=5, cursor="hand2")
            lb.pack(side="left")
            lb.bind("<Button-1>", lambda e, v=val: self.var.set(v))
            self.labels[val] = lb
        self.var.trace_add("write", lambda *a: self._paint())
        self._paint()

    def _paint(self):
        for v, lb in self.labels.items():
            on = self.var.get() == v
            lb.config(bg=T["accent"] if on else T["panel2"], fg="#ffffff" if on else T["muted"],
                      font=F(9, "bold" if on else "normal"))


class Switch(tk.Frame):
    def __init__(self, master, text, var):
        super().__init__(master, bg=T["panel"])
        self.var = var
        self.cv = tk.Canvas(self, width=34, height=18, bg=T["panel"], highlightthickness=0, cursor="hand2")
        self.cv.pack(side="left")
        self.lb = tk.Label(self, text=text, font=F(9), bg=T["panel"], fg=T["text"], cursor="hand2")
        self.lb.pack(side="left", padx=(8, 0))
        for w in (self.cv, self.lb):
            w.bind("<Button-1>", lambda e: self.var.set(not self.var.get()))
        self.var.trace_add("write", lambda *a: self._paint())
        self._paint()

    def _paint(self):
        on = self.var.get()
        c = self.cv
        c.delete("all")
        col = T["accent"] if on else T["border"]
        c.create_oval(1, 1, 17, 17, fill=col, outline=col)
        c.create_oval(17, 1, 33, 17, fill=col, outline=col)
        c.create_rectangle(9, 1, 25, 17, fill=col, outline=col)
        x = 25 if on else 9
        c.create_oval(x - 6, 3, x + 6, 15, fill="#ffffff", outline="#ffffff")


class ScrollFrame(tk.Frame):
    def __init__(self, master, bg, height=None):
        super().__init__(master, bg=bg)
        self.cv = tk.Canvas(self, bg=bg, highlightthickness=0, **({"height": height} if height else {}))
        self.cv.pack(fill="both", expand=True)
        self.inner = tk.Frame(self.cv, bg=bg)
        self.win = self.cv.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.cv.configure(scrollregion=self.cv.bbox("all")))
        self.cv.bind("<Configure>", lambda e: self.cv.itemconfigure(self.win, width=e.width))
        self.bind("<Enter>", lambda e: self._wheel_bind(True))
        self.bind("<Leave>", lambda e: self._wheel_bind(False))

    def _wheel_bind(self, on):
        if on:
            self.cv.bind_all("<MouseWheel>", self._wheel)
            self.cv.bind_all("<Button-4>", lambda e: self.cv.yview_scroll(-2, "units"))
            self.cv.bind_all("<Button-5>", lambda e: self.cv.yview_scroll(2, "units"))
        else:
            for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.cv.unbind_all(ev)

    def _wheel(self, e):
        if self.inner.winfo_height() > self.cv.winfo_height():
            self.cv.yview_scroll(int(-e.delta / 60) or (-1 if e.delta > 0 else 1), "units")


class Slider(tk.Canvas):
    """Flat 0-100 slider bound to a DoubleVar."""

    def __init__(self, master, var, command):
        super().__init__(master, height=24, bg=T["panel"], highlightthickness=0, cursor="hand2")
        self.var, self.command = var, command
        self.bind("<Configure>", lambda e: self._paint())
        self.bind("<Button-1>", self._set)
        self.bind("<B1-Motion>", self._set)
        self.var.trace_add("write", lambda *a: self._paint())

    def _set(self, e):
        pad, w = 12, max(self.winfo_width(), 40)
        self.var.set(max(0.0, min(100.0, (e.x - pad) / (w - 2 * pad) * 100)))
        self.command()

    def _paint(self):
        self.delete("all")
        pad, w, h = 12, max(self.winfo_width(), 40), 24
        x = pad + (w - 2 * pad) * self.var.get() / 100.0
        self.create_line(pad, h / 2, w - pad, h / 2, fill=T["border"], width=4, capstyle="round")
        self.create_line(pad, h / 2, x, h / 2, fill=T["accent"], width=4, capstyle="round")
        self.create_oval(x - 8, h / 2 - 8, x + 8, h / 2 + 8, fill="#ffffff", outline=T["accent"], width=2)


def chip(master, text, color, bg=None):
    return tk.Label(master, text=text, font=F(8, "bold"), fg=color, bg=bg or T["card"], padx=7, pady=2,
                    highlightthickness=1, highlightbackground=mix(color, bg or T["card"], 0.62))


STATUS_CHIP = {"calibrated": ("CALIBRATED", "good"), "standard": ("STANDARD", "info"),
               "experimental": ("EXPERIMENTAL", "warn")}


# =============================================================================
# 3-D wireframe renderer
# =============================================================================
class Wire3D:
    def __init__(self, canvas, up="y", lw=1.5):
        self.cv, self.up, self.lw = canvas, up, lw
        self.panels = None
        self.amount = 1.0
        self.yaw, self.pitch, self.zoom = -0.62, 0.5, 1.0
        self.items = {}
        self.center, self.radius = (0, 0, 0), 1.0
        self.shadow = None

    def _orient(self, p):
        return (p[0], p[2], -p[1]) if self.up == "z" else p

    def set_panels(self, panels, up=None):
        if up:
            self.up = up
        self.cv.delete("all")
        self.items, self.shadow = {}, None
        self.panels = panels
        if not panels:
            return
        pts = [self._orient(q) for poly in fold_panels(panels, 1.0).values() for q in poly]
        xs, ys, zs = zip(*pts)
        self.center = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2)
        self.radius = max(1e-6, max(math.dist(self.center, q) for q in pts))
        self.render()

    def render(self):
        if not self.panels:
            return
        cv = self.cv
        W = cv.winfo_width() if cv.winfo_width() > 10 else int(cv.cget("width"))
        H = cv.winfo_height() if cv.winfo_height() > 10 else int(cv.cget("height"))
        polys = fold_panels(self.panels, self.amount)
        # fit the model as it is *right now* (flat sheet and folded box differ a lot in size)
        allp = [self._orient(q) for poly in polys.values() for q in poly]
        xs, ys, zs = zip(*allp)
        cx0, cy0, cz0 = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2
        R = max(1e-6, max(math.dist((cx0, cy0, cz0), q) for q in allp))
        scale = min(W, H) * 0.40 * self.zoom / R
        cyw, syw = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        dcam = 4.2 * R
        if self.shadow is None:
            self.shadow = cv.create_oval(0, 0, 1, 1, fill=mix(T["thumb"], "#000000", 0.35), outline="")
            cv.tag_lower(self.shadow)
        # floor shadow
        floor = -R * 0.0
        sw = R * 1.05 * scale
        cv.coords(self.shadow, W / 2 - sw, H / 2 + R * 0.78 * scale * 0.80 - sw * 0.28,
                  W / 2 + sw, H / 2 + R * 0.78 * scale * 0.80 + sw * 0.28)
        for pn in self.panels:
            sc, zs = [], []
            for q in polys[pn.name]:
                x, y, z = self._orient(q)
                x, y, z = x - cx0, y - cy0, z - cz0
                x1, z1 = cyw * x + syw * z, -syw * x + cyw * z
                y2, z2 = cp * y - sp * z1, sp * y + cp * z1
                f = dcam / (dcam - z2)
                sc.extend((W / 2 + x1 * scale * f, H / 2 - y2 * scale * f))
                zs.append(z2)
            sc.extend(sc[:2])
            depth = (sum(zs) / len(zs) / R + 1) / 2
            if pn.role == "body":
                col = mix(T["body_dim"], T["body"], depth * 1.1)
            else:
                col = mix(T["flap_dim"], T["flap"], depth * 1.1)
            it = self.items.get(pn.name)
            if it is None:
                self.items[pn.name] = cv.create_line(*sc, fill=col, width=self.lw, joinstyle="round",
                                                     capstyle="round")
            else:
                cv.coords(it, *sc)
                cv.itemconfigure(it, fill=col)


# =============================================================================
# Home / menu screen
# =============================================================================
class Card(tk.Frame):
    def __init__(self, master, style, on_open):
        super().__init__(master, bg=T["card"], highlightthickness=1, highlightbackground=T["border"], cursor="hand2")
        self.style_, self.on_open = style, on_open
        self.thumb = tk.Canvas(self, width=330, height=150, bg=T["thumb"], highlightthickness=0)
        self.thumb.pack(fill="x", padx=1, pady=(1, 0))
        body = tk.Frame(self, bg=T["card"])
        body.pack(fill="x", padx=16, pady=(10, 12))
        tk.Label(body, text=style.name, font=F(14, "bold"), fg=T["text"], bg=T["card"], anchor="w").pack(fill="x")
        chips = tk.Frame(body, bg=T["card"])
        chips.pack(fill="x", pady=(6, 8))
        txt, col = STATUS_CHIP[style.status]
        if style.code:
            chip(chips, style.code, T["muted"]).pack(side="left", padx=(0, 6))
        chip(chips, txt, T[col]).pack(side="left")
        tk.Label(body, text=style.blurb, font=F(9), fg=T["muted"], bg=T["card"], wraplength=300, justify="left",
                 anchor="w").pack(fill="x")
        res = generate(style, default_spec(style))
        self.wire = Wire3D(self.thumb, style.view_up)
        self.wire.set_panels(res.panels)
        self.wire.yaw = -0.62 + (hash(style.id) % 100) / 40.0
        self._bind_all(self)

    def _bind_all(self, w):
        w.bind("<Enter>", self._enter, add="+")
        w.bind("<Leave>", self._leave, add="+")
        w.bind("<Button-1>", lambda e: self.on_open(self.style_), add="+")
        for c in w.winfo_children():
            self._bind_all(c)

    def _enter(self, e):
        self.config(highlightbackground=T["border_h"])
        self.hover = True

    def _leave(self, e):
        x, y = self.winfo_pointerxy()
        w = self.winfo_containing(x, y)
        inside = False
        while w is not None:
            if w is self:
                inside = True
                break
            w = w.master
        if not inside:
            self.config(highlightbackground=T["border"])
            self.hover = False

    hover = False


class Home(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=T["bg"])
        self.app, self.cards, self._job = app, [], None
        rail = tk.Frame(self, bg=T["rail"], width=68)
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        logo = tk.Canvas(rail, width=44, height=44, bg=T["rail"], highlightthickness=0)
        logo.pack(pady=(18, 22))
        logo.create_polygon(22, 5, 39, 14, 39, 32, 22, 41, 5, 32, 5, 14, fill=T["accent"], outline="")
        logo.create_polygon(22, 5, 39, 14, 22, 23, 5, 14, fill=mix(T["accent"], "#ffffff", 0.35), outline="")
        logo.create_line(22, 23, 22, 41, fill="#ffffff", width=1)
        for glyph, label, cmd in (("⌂", "Home", None), ("ⓘ", "Limits", app.show_limits)):
            b = tk.Label(rail, text=glyph, font=F(18), fg=T["text"] if cmd is None else T["muted"], bg=T["rail"],
                         cursor="hand2", pady=6)
            b.pack(fill="x")
            if cmd:
                b.bind("<Button-1>", lambda e, c=cmd: c())
                b.bind("<Enter>", lambda e, w=b: w.config(fg=T["text"]))
                b.bind("<Leave>", lambda e, w=b: w.config(fg=T["muted"]))
            tk.Label(rail, text=label, font=F(8), fg=T["dim"], bg=T["rail"]).pack(pady=(0, 10))

        main = tk.Frame(self, bg=T["bg"])
        main.pack(side="left", fill="both", expand=True)
        head = tk.Frame(main, bg=T["bg"])
        head.pack(fill="x", padx=40, pady=(30, 4))
        tk.Label(head, text="BoxForge", font=F(11, "bold"), fg=T["accent_h"], bg=T["bg"]).pack(anchor="w")
        tk.Label(head, text="What are you making today?", font=F(26, "bold"), fg=T["text"], bg=T["bg"]).pack(anchor="w")
        tk.Label(head, text="Pick a box style. Type your dimensions, preview the dieline and the folded box, "
                            "then export SVG or DXF for your laser or cutter.", font=F(10), fg=T["muted"],
                 bg=T["bg"]).pack(anchor="w", pady=(2, 0))
        self.grid_host = tk.Frame(main, bg=T["bg"])
        self.grid_host.pack(fill="both", expand=True, padx=34, pady=(16, 20))
        for s in STYLES:
            self.cards.append(Card(self.grid_host, s, app.open_style))
        self.cols = 0
        self.grid_host.bind("<Configure>", self._reflow)

    def _reflow(self, e):
        cols = 3 if e.width >= 1020 else 2 if e.width >= 680 else 1
        if cols == self.cols:
            return
        self.cols = cols
        for c in self.cards:
            c.grid_forget()
        for i in range(6):
            self.grid_host.grid_columnconfigure(i, weight=0)
        for i, c in enumerate(self.cards):
            c.grid(row=i // cols, column=i % cols, padx=8, pady=8, sticky="nsew")
        for i in range(cols):
            self.grid_host.grid_columnconfigure(i, weight=1, uniform="c")

    def start(self):
        self.stop()
        self._tick()

    def stop(self):
        if self._job:
            self.after_cancel(self._job)
            self._job = None

    def _tick(self):
        for c in self.cards:
            c.wire.yaw += 0.03 if c.hover else 0.011
            c.wire.render()
        self._job = self.after(40, self._tick)


# =============================================================================
# Editor
# =============================================================================
class Editor(tk.Frame):
    def __init__(self, master, app, style, saved=None):
        super().__init__(master, bg=T["bg"])
        self.app, self.style = app, style
        self.res = None
        self._job = None
        self._loading = True
        self.user_view = False
        self.view = dict(s=1.0, ox=0.0, oy=0.0)
        self._drag = None
        self._anim = None
        self._spin = None

        spec0 = default_spec(style)
        sv = saved or {}
        self.units = tk.StringVar(value=sv.get("units", "mm"))
        self.mode = tk.StringVar(value=sv.get("mode", "inner"))
        self.folds = tk.BooleanVar(value=sv.get("folds", True))
        self.flags = {k: tk.BooleanVar(value=sv.get("flag_" + k, d)) for k, _, d in style.toggles}
        self.vars = {}
        for k in ("L", "W", "H", "t"):
            self.vars[k] = tk.StringVar(value=sv.get(k, fmt(getattr(spec0, k), 3)))
        for k, _ in style.options:
            self.vars[k] = tk.StringVar(value=sv.get(k, ""))
        self.vars["sheetw"] = tk.StringVar(value=sv.get("sheetw", ""))
        self.vars["sheeth"] = tk.StringVar(value=sv.get("sheeth", ""))
        self.view_mode = tk.StringVar(value=sv.get("view", "split"))
        self.amount = tk.DoubleVar(value=100.0)
        self.ents, self.auto_lbl = {}, {}
        self._last_units = self.units.get()

        self._build_top()
        body = tk.Frame(self, bg=T["bg"])
        body.pack(fill="both", expand=True)
        self._build_sidebar(body)
        self._build_main(body)

        for v in list(self.vars.values()) + [self.mode, self.folds] + list(self.flags.values()):
            v.trace_add("write", lambda *a: self.schedule())
        self.units.trace_add("write", self._on_units)
        self.view_mode.trace_add("write", lambda *a: self._layout_views())
        self._loading = False
        self._layout_views()
        self.after(60, self.refresh)

    # ---------------------------------------------------------------- build ----
    def _build_top(self):
        top = tk.Frame(self, bg=T["panel"], height=54)
        top.pack(fill="x")
        top.pack_propagate(False)
        Btn(top, "←  All boxes", self.app.show_home, kind="flat", padx=16, pady=14).pack(side="left", padx=(6, 6))
        tk.Frame(top, bg=T["border"], width=1).pack(side="left", fill="y", pady=12)
        tk.Label(top, text=self.style.name, font=F(13, "bold"), fg=T["text"], bg=T["panel"]).pack(side="left", padx=(16, 10))
        if self.style.code:
            chip(top, self.style.code, T["muted"], T["panel"]).pack(side="left", padx=(0, 6))
        txt, col = STATUS_CHIP[self.style.status]
        chip(top, txt, T[col], T["panel"]).pack(side="left")
        right = tk.Frame(top, bg=T["panel"])
        right.pack(side="right", padx=14)
        Seg(right, [("dieline", "Dieline"), ("split", "Split"), ("fold3d", "3-D fold")], self.view_mode).pack(
            side="right", pady=12)

    def _section(self, parent, text):
        tk.Label(parent, text=text, font=F(8, "bold"), fg=T["dim"], bg=T["panel"], anchor="w").pack(
            fill="x", padx=18, pady=(16, 6))

    def _field(self, parent, key, label, unit=True):
        row = tk.Frame(parent, bg=T["panel"])
        row.pack(fill="x", padx=18, pady=3)
        tk.Label(row, text=label, font=F(9), fg=T["text"], bg=T["panel"], anchor="w").pack(side="left")
        right = tk.Frame(row, bg=T["panel"])
        right.pack(side="right")
        lbl = tk.Label(right, text="", font=F(8), fg=T["dim"], bg=T["panel"], width=9, anchor="e")
        lbl.pack(side="left", padx=(0, 6))
        e = tk.Entry(right, textvariable=self.vars[key], width=8, font=F(10), bg=T["panel2"], fg=T["text"],
                     insertbackground=T["text"], relief="flat", justify="right", highlightthickness=1,
                     highlightbackground=T["border"], highlightcolor=T["accent"])
        e.pack(side="left", ipady=4)
        self.ents[key], self.auto_lbl[key] = e, lbl

    def _build_sidebar(self, parent):
        side = tk.Frame(parent, bg=T["panel"], width=352)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        bottom = tk.Frame(side, bg=T["panel"])
        bottom.pack(side="bottom", fill="x", padx=16, pady=14)
        row = tk.Frame(bottom, bg=T["panel"])
        row.pack(fill="x")
        self.btn_dxf = Btn(row, "Export DXF", lambda: self.export("dxf"), "primary", pady=10)
        self.btn_dxf.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.btn_svg = Btn(row, "Export SVG", lambda: self.export("svg"), "ghost", pady=10)
        self.btn_svg.pack(side="left", fill="x", expand=True)
        self.toast = tk.Label(bottom, text="", font=F(8), fg=T["good"], bg=T["panel"], wraplength=310, justify="left",
                              anchor="w")
        self.toast.pack(fill="x", pady=(8, 0))
        chk_wrap = tk.Frame(side, bg=T["panel"])
        chk_wrap.pack(side="bottom", fill="x")
        tk.Label(chk_wrap, text="CHECKS", font=F(8, "bold"), fg=T["dim"], bg=T["panel"], anchor="w").pack(
            fill="x", padx=18, pady=(10, 2))
        chk_sf = ScrollFrame(chk_wrap, T["panel"], height=150)
        chk_sf.pack(fill="x", padx=0)
        self.checks = chk_sf.inner
        tk.Frame(side, bg=T["border"], height=1).pack(side="bottom", fill="x")

        sf = ScrollFrame(side, T["panel"])
        sf.pack(fill="both", expand=True)
        s = sf.inner
        hdr = tk.Frame(s, bg=T["panel"])
        hdr.pack(fill="x", padx=18, pady=(14, 0))
        tk.Label(hdr, text="Units", font=F(9), fg=T["text"], bg=T["panel"]).pack(side="left")
        Seg(hdr, [("mm", "mm"), ("in", "inch")], self.units).pack(side="right")

        self._section(s, "DIMENSIONS")
        self._field(s, "L", "Length")
        self._field(s, "W", "Width")
        self._field(s, "H", self.style.height_label)
        self._field(s, "t", "Material thickness")

        self._section(s, "THESE DIMENSIONS ARE…")
        Seg(s, [("inner", "Inner"), ("outer", "Outer"), ("manufacturer", "Maker")], self.mode).pack(
            anchor="w", padx=18)
        self.mode_lbl = tk.Label(s, text="", font=F(8), fg=T["muted"], bg=T["panel"], wraplength=310, justify="left",
                                 anchor="w")
        self.mode_lbl.pack(fill="x", padx=18, pady=(6, 0))

        if self.style.options:
            self._section(s, "ADVANCED  ·  blank = automatic")
            for key, label in self.style.options:
                self._field(s, key, label)

        self._section(s, "OPTIONS")
        Switch(s, "Include fold lines (red)", self.folds).pack(anchor="w", padx=18, pady=3)
        for key, label, _ in self.style.toggles:
            Switch(s, label, self.flags[key]).pack(anchor="w", padx=18, pady=3)

        self._section(s, "MATERIAL SHEET  ·  optional")
        self._field(s, "sheetw", "Sheet width")
        self._field(s, "sheeth", "Sheet height")

        tk.Frame(s, bg=T["panel"], height=16).pack()

    def _build_main(self, parent):
        main = tk.Frame(parent, bg=T["bg"])
        main.pack(side="left", fill="both", expand=True)
        self.stage = tk.Frame(main, bg=T["bg"])
        self.stage.pack(fill="both", expand=True)
        self.stage.grid_rowconfigure(0, weight=1)
        self.stage.grid_columnconfigure(0, weight=1, uniform="v")
        self.stage.grid_columnconfigure(1, weight=1, uniform="v")

        self.pane2 = tk.Frame(self.stage, bg=T["canvas"])
        self.cv2 = tk.Canvas(self.pane2, bg=T["canvas"], highlightthickness=0, cursor="fleur")
        self.cv2.pack(fill="both", expand=True)
        self.cv2.bind("<Configure>", lambda e: self.draw2d())
        self.cv2.bind("<ButtonPress-1>", self._p2_down)
        self.cv2.bind("<B1-Motion>", self._p2_move)
        self.cv2.bind("<MouseWheel>", self._p2_wheel)
        self.cv2.bind("<Button-4>", lambda e: self._p2_zoom(e, 1.12))
        self.cv2.bind("<Button-5>", lambda e: self._p2_zoom(e, 1 / 1.12))
        self.cv2.bind("<Double-Button-1>", lambda e: self._fit())

        self.pane3 = tk.Frame(self.stage, bg=T["thumb"])
        self.cv3 = tk.Canvas(self.pane3, bg=T["thumb"], highlightthickness=0, cursor="exchange")
        self.cv3.pack(fill="both", expand=True)
        self.wire = Wire3D(self.cv3, self.style.view_up, lw=1.6)
        self.cv3.bind("<Configure>", lambda e: self._render3d())
        self.cv3.bind("<ButtonPress-1>", lambda e: setattr(self, "_drag3", (e.x, e.y)))
        self.cv3.bind("<B1-Motion>", self._p3_move)
        self.cv3.bind("<MouseWheel>", lambda e: self._p3_zoom(1.1 if e.delta > 0 else 1 / 1.1))
        self.cv3.bind("<Button-4>", lambda e: self._p3_zoom(1.1))
        self.cv3.bind("<Button-5>", lambda e: self._p3_zoom(1 / 1.1))
        bar = tk.Frame(self.pane3, bg=T["panel"], height=46)
        bar.pack(fill="x", side="bottom")
        self.btn_play = Btn(bar, "▶  Fold", self.play, "ghost", size=9, padx=12, pady=5)
        self.btn_play.pack(side="left", padx=(12, 8), pady=8)
        self.btn_spin = Btn(bar, "⟳ Spin", self.toggle_spin, "ghost", size=9, padx=10, pady=5)
        self.btn_spin.pack(side="right", padx=12, pady=8)
        sc = Slider(bar, self.amount, self._on_amount)
        sc.pack(side="left", fill="x", expand=True, pady=10, padx=(0, 10))

        self.status = tk.Label(main, text="", font=F(9), fg=T["muted"], bg=T["panel"], anchor="w", padx=16, pady=7)
        self.status.pack(fill="x", side="bottom")

    def _layout_views(self):
        m = self.view_mode.get()
        self.pane2.grid_forget()
        self.pane3.grid_forget()
        if m == "dieline":
            self.pane2.grid(row=0, column=0, columnspan=2, sticky="nsew")
        elif m == "fold3d":
            self.pane3.grid(row=0, column=0, columnspan=2, sticky="nsew")
        else:
            self.pane2.grid(row=0, column=0, sticky="nsew")
            self.pane3.grid(row=0, column=1, sticky="nsew")
        self.after(30, lambda: (self.draw2d(), self._render3d()))

    # --------------------------------------------------------------- inputs ----
    def schedule(self):
        if self._loading:
            return
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(140, self.refresh)

    def _on_units(self, *a):
        if self._loading:
            return
        new, old = self.units.get(), self._last_units
        if new == old:
            return
        f = 1 / 25.4 if new == "in" else 25.4
        self._loading = True
        for k, v in self.vars.items():
            try:
                x = parse_num(v.get())
            except ValueError:
                continue
            if x is not None:
                v.set(fmt(x * f, 4 if new == "in" else 3))
        self._loading = False
        self._last_units = new
        self.user_view = False
        self.refresh()

    def snapshot(self):
        d = {k: v.get() for k, v in self.vars.items()}
        d.update(units=self.units.get(), mode=self.mode.get(), folds=self.folds.get(), view=self.view_mode.get())
        for k, v in self.flags.items():
            d["flag_" + k] = v.get()
        return d

    def read_spec(self):
        pre = []
        vals = {}
        for k in ("L", "W", "H", "t"):
            try:
                vals[k] = parse_num(self.vars[k].get())
            except ValueError:
                vals[k] = None
                pre.append((k, "not a number"))
            if vals[k] is None and not any(p[0] == k for p in pre):
                pre.append((k, "required"))
        opts = {}
        for k, _ in self.style.options:
            try:
                opts[k] = parse_num(self.vars[k].get())
            except ValueError:
                opts[k] = float("nan")
        sh = []
        for k in ("sheetw", "sheeth"):
            try:
                sh.append(parse_num(self.vars[k].get()))
            except ValueError:
                sh.append(None)
        spec = Spec(vals["L"], vals["W"], vals["H"], vals["t"], self.mode.get(), self.units.get(), opts,
                    self.folds.get(), {k: v.get() for k, v in self.flags.items()}, tuple(sh))
        return spec

    # -------------------------------------------------------------- refresh ----
    def refresh(self):
        self._job = None
        self.mode_lbl.config(text=self.style.mode_help.get(self.mode.get(), ""))
        spec = self.read_spec()
        res = generate(self.style, spec)
        self.res = res
        self._show_issues(res)
        self._show_autos(res)
        ok = res.ok
        self.btn_dxf.set_enabled(ok)
        self.btn_svg.set_enabled(ok)
        if res.panels:
            self.wire.set_panels(res.panels, self.style.view_up)
            self._on_amount(redraw=False)
        else:
            self.wire.set_panels(None)
        self.draw2d()
        self._render3d()
        u = spec.units
        if res.info.get("flat"):
            w, h = res.info["flat"]
            i = res.info["inner"]
            self.status.config(text=f"Flat sheet  {fmt(w, 1)} × {fmt(h, 1)} {u}     ·     Inside  "
                                    f"{fmt(i[0], 2)} × {fmt(i[1], 2)} × {fmt(i[2], 2)} {u}")
        else:
            self.status.config(text="")

    def _show_issues(self, res):
        for w in self.checks.winfo_children():
            w.destroy()
        for e in self.ents.values():
            e.config(highlightbackground=T["border"])
        order = {"error": 0, "warn": 1, "info": 2}
        issues = sorted(res.issues, key=lambda i: order[i.level])
        if not issues:
            row = tk.Frame(self.checks, bg=T["panel"])
            row.pack(fill="x", pady=2, padx=18)
            tk.Label(row, text="●", fg=T["good"], bg=T["panel"], font=F(9)).pack(side="left", anchor="n")
            tk.Label(row, text="Looks good - no problems found.", fg=T["muted"], bg=T["panel"], font=F(9)).pack(
                side="left", padx=(6, 0))
        colors = {"error": T["err"], "warn": T["warn"], "info": T["info"]}
        for i in issues:
            row = tk.Frame(self.checks, bg=T["panel"])
            row.pack(fill="x", pady=3, padx=18)
            tk.Label(row, text="●", fg=colors[i.level], bg=T["panel"], font=F(9)).pack(side="left", anchor="n")
            tk.Label(row, text=i.msg, fg=T["text"] if i.level != "info" else T["muted"], bg=T["panel"], font=F(9),
                     wraplength=285, justify="left", anchor="w").pack(side="left", padx=(6, 0), fill="x", expand=True)
            for f in i.fields:
                e = self.ents.get(f)
                if e is not None and (e.cget("highlightbackground") != colors["error"]):
                    e.config(highlightbackground=colors[i.level])
        if not res.ok:
            self.toast.config(text="Export is disabled until the red items are fixed.", fg=T["err"])
        elif self.toast.cget("fg") == T["err"]:
            self.toast.config(text="")

    def _show_autos(self, res):
        auto = res.info.get("auto", {})
        for key, _ in self.style.options:
            lbl = self.auto_lbl[key]
            val = auto.get(self._auto_key(key))
            if val is not None and not self.vars[key].get().strip():
                lbl.config(text=f"auto {fmt(val, 2)}")
            else:
                lbl.config(text="")

    def _auto_key(self, key):
        return {"dust": "dw", "outer": "fw", "tuck": "th", "clear": "c", "lidh": "lidh", "clr": "clr"}.get(key, key)

    # ----------------------------------------------------------------- 2-D ----
    def _bounds(self):
        d = self.res.drawing
        return d.bounds() if d else None

    def _fit(self):
        self.user_view = False
        self.draw2d()

    def _p2_down(self, e):
        self._drag = (e.x, e.y)

    def _p2_move(self, e):
        if self._drag:
            self.view["ox"] += e.x - self._drag[0]
            self.view["oy"] += e.y - self._drag[1]
            self._drag = (e.x, e.y)
            self.user_view = True
            self.draw2d()

    def _p2_wheel(self, e):
        self._p2_zoom(e, 1.12 if e.delta > 0 else 1 / 1.12)

    def _p2_zoom(self, e, k):
        v = self.view
        v["ox"] = e.x - (e.x - v["ox"]) * k
        v["oy"] = e.y - (e.y - v["oy"]) * k
        v["s"] *= k
        self.user_view = True
        self.draw2d()

    def draw2d(self):
        cv = self.cv2
        cv.delete("all")
        W, H = cv.winfo_width(), cv.winfo_height()
        if W < 20 or H < 20 or self.res is None:
            return
        d = self.res.drawing
        u = self.units.get()
        if d is None:
            cv.create_text(W / 2, H / 2, text="No dieline yet", fill=T["dim"], font=F(14))
            self._banner(cv, W)
            return
        x0, y0, x1, y1 = d.bounds()
        if not self.user_view:
            pad = 64
            s = min((W - 2 * pad) / max(x1 - x0, 1e-9), (H - 2 * pad) / max(y1 - y0, 1e-9))
            self.view.update(s=s, ox=(W - s * (x1 - x0)) / 2 - s * x0, oy=(H + s * (y1 - y0)) / 2 + s * y0)
        v = self.view
        s = v["s"]
        X = lambda x: v["ox"] + s * x
        Y = lambda y: v["oy"] - s * y
        # dot grid
        step = 20
        for gx in range(0, W, 40):
            for gy in range(0, H, 40):
                cv.create_rectangle(gx, gy, gx + 1, gy + 1, fill=T["grid"], outline="")
        col = {CUT: T["cut"], FOLD: T["fold"]}
        bad = not self.res.ok
        for it in d.items:
            c = col[it[-1]]
            if bad:
                c = mix(c, T["canvas"], 0.55)
            lw = 1.6 if it[-1] == CUT else 1.3
            if it[0] == "L":
                _, p, q, layer = it
                cv.create_line(X(p[0]), Y(p[1]), X(q[0]), Y(q[1]), fill=c, width=lw, capstyle="round")
            else:
                _, ce, r, a0, a1, layer = it
                span = (a1 - a0) % 360 or 360
                cv.create_arc(X(ce[0] - r), Y(ce[1] + r), X(ce[0] + r), Y(ce[1] - r), start=a0, extent=span,
                              style="arc", outline=c, width=lw)
        # overall size callouts
        ax = T["dim"]
        by = Y(y0) + 22
        cv.create_line(X(x0), by, X(x1), by, fill=ax, arrow="both")
        cv.create_text((X(x0) + X(x1)) / 2, by + 12, text=f"{fmt(x1 - x0, 1)} {u}", fill=T["muted"], font=F(8))
        rx = X(x1) + 22
        cv.create_line(rx, Y(y0), rx, Y(y1), fill=ax, arrow="both")
        cv.create_text(rx + 14, (Y(y0) + Y(y1)) / 2, text=f"{fmt(y1 - y0, 1)} {u}", fill=T["muted"], font=F(8), angle=90)
        # legend
        lx, ly = 18, H - 20
        cv.create_line(lx, ly, lx + 22, ly, fill=T["cut"], width=2)
        cv.create_text(lx + 30, ly, text="Cut", fill=T["muted"], font=F(8), anchor="w")
        cv.create_line(lx + 70, ly, lx + 92, ly, fill=T["fold"], width=2)
        cv.create_text(lx + 100, ly, text="Fold / score", fill=T["muted"], font=F(8), anchor="w")
        cv.create_text(W - 14, H - 20, text="drag = pan · wheel = zoom · double-click = fit", fill=T["dim"], font=F(8),
                       anchor="e")
        self._banner(cv, W)

    def _banner(self, cv, W):
        if self.res is None or self.res.ok:
            return
        errs = self.res.errors
        msg = errs[0].msg if errs else ""
        if len(errs) > 1:
            msg += f"   (+{len(errs) - 1} more)"
        t = cv.create_text(W / 2, 16, text="⚠  " + msg, fill="#ffffff", font=F(9, "bold"), width=max(W - 100, 120),
                           anchor="n", justify="center")
        bb = cv.bbox(t)
        r = cv.create_rectangle(bb[0] - 14, bb[1] - 7, bb[2] + 14, bb[3] + 7, fill=mix(T["err"], T["canvas"], 0.55),
                                outline=T["err"])
        cv.tag_lower(r, t)

    # ----------------------------------------------------------------- 3-D ----
    def _render3d(self):
        cv = self.cv3
        for it in cv.find_withtag("msg"):
            cv.delete(it)
        if self.res is None:
            return
        if self.wire.panels:
            self.wire.render()
            cv.create_text(16, 16, anchor="nw", text="drag = rotate · wheel = zoom", fill=T["dim"], font=F(8), tags="msg")
        else:
            W, H = cv.winfo_width(), cv.winfo_height()
            cv.create_text(W / 2, H / 2, text="No folded preview until the red items are fixed", fill=T["dim"],
                           font=F(12), tags="msg")

    def _on_amount(self, redraw=True):
        self.wire.amount = self.amount.get() / 100.0
        if redraw:
            self.wire.render()

    def _p3_move(self, e):
        x, y = self._drag3
        self.wire.yaw += (e.x - x) * 0.01
        self.wire.pitch = max(-1.45, min(1.45, self.wire.pitch + (e.y - y) * 0.01))
        self._drag3 = (e.x, e.y)
        self.wire.render()

    def _p3_zoom(self, k):
        self.wire.zoom = max(0.3, min(4.0, self.wire.zoom * k))
        self.wire.render()

    def play(self):
        if self._anim:
            self.after_cancel(self._anim)
            self._anim = None
            self.btn_play.config(text="▶  Fold")
            return
        if self.amount.get() >= 99.5:
            self.amount.set(0)
        self.btn_play.config(text="❚❚  Pause")
        self._step()

    def _step(self):
        v = self.amount.get() + 1.4
        if v >= 100:
            self.amount.set(100)
            self._on_amount()
            self._anim = None
            self.btn_play.config(text="▶  Fold")
            return
        self.amount.set(v)
        self._on_amount()
        self._anim = self.after(24, self._step)

    def toggle_spin(self):
        if self._spin:
            self.after_cancel(self._spin)
            self._spin = None
            self.btn_spin.config(text="⟳ Spin")
            return
        self.btn_spin.config(text="■ Stop")
        self._spin_step()

    def _spin_step(self):
        self.wire.yaw += 0.018
        self.wire.render()
        self._spin = self.after(33, self._spin_step)

    def shutdown(self):
        for j in (self._job, self._anim, self._spin):
            if j:
                try:
                    self.after_cancel(j)
                except Exception:
                    pass

    # --------------------------------------------------------------- export ----
    def export(self, kind):
        res = self.res
        if res is None or not res.ok or res.drawing is None:
            messagebox.showerror("Can't export yet", "\n\n".join(i.msg for i in (res.errors if res else [])) or
                                 "Fix the highlighted problems first.")
            return
        if res.warnings:
            body = "\n\n".join("• " + w.msg for w in res.warnings)
            if not messagebox.askyesno("Export with notes?",
                                       f"This design has {len(res.warnings)} note(s):\n\n{body}\n\n"
                                       f"They will also be saved inside the file. Export anyway?"):
                return
        sp = res.spec
        name = f"{self.style.id}_{fmt(sp.L)}x{fmt(sp.W)}x{fmt(sp.H)}_{sp.units}.{kind}"
        path = filedialog.asksaveasfilename(defaultextension=f".{kind}", initialfile=name,
                                            filetypes=[(kind.upper() + " file", f"*.{kind}")])
        if not path:
            return
        head = (f"BoxForge {self.style.name}: L{fmt(sp.L)} W{fmt(sp.W)} H{fmt(sp.H)} thickness {fmt(sp.t)} "
                f"{sp.units} ({sp.mode} dimensions). Layers: CUT blue, FOLD red.")
        notes = [head] + res.notes()
        data = to_dxf(res.drawing, sp.units, notes) if kind == "dxf" else to_svg(res.drawing, sp.units, notes=notes)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(data)
        except OSError as exc:
            messagebox.showerror("Could not save", str(exc))
            return
        self.toast.config(text=f"Saved {os.path.basename(path)}" + (f"  ·  with {len(res.warnings)} note(s)"
                                                                      if res.warnings else ""), fg=T["good"])


# =============================================================================
# Application
# =============================================================================
LIMITS_TEXT = """How the checks work

RED  - blocks export. The geometry is impossible or would be cut wrong: an inside dimension that is zero or negative, the smallest inside dimension under 4x the board thickness, flaps that cannot fit, or cut outlines that overlap in the flat layout.

AMBER - allowed, but flagged. The design should work but is outside what we can vouch for (smallest dimension under 8x the board thickness, flaps near their limits, extreme proportions, very tight lid clearance...). The notes are saved inside the exported file (SVG <desc>, DXF comments).

BLUE - information only.

What the limits are based on
- Structure of each style follows the FEFCO / ECMA families: 0201 slotted box, 0301 telescope, 0427 roll-end tray. Internal-size conventions come from the FEFCO measuring recommendation (inside length/breadth = crease-to-crease minus one board; height minus two boards).
- Neither FEFCO nor the converter guides found publish numeric limits for board thickness against panel size, so the 4x / 8x rules, slot widths and clearances are engineering rules of thumb, not a standard.
- The Tuck-Top is calibrated against a reference dieline. Roll-End Mailer is marked Experimental.

Always cut a test piece on your actual board before a full run: crease behaviour varies with flute, grain direction and score depth."""


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        init_fonts(self)
        self.title("BoxForge  -  Box Dieline Studio")
        self.configure(bg=T["bg"])
        self.geometry("1380x840")
        self.minsize(1100, 700)
        self.saved = {}
        self.host = tk.Frame(self, bg=T["bg"])
        self.host.pack(fill="both", expand=True)
        self.home = Home(self.host, self)
        self.editor = None
        self.show_home()

    def show_home(self):
        if self.editor:
            self.saved[self.editor.style.id] = self.editor.snapshot()
            self.editor.shutdown()
            self.editor.destroy()
            self.editor = None
        self.home.pack(fill="both", expand=True)
        self.home.start()

    def open_style(self, style):
        self.home.stop()
        self.home.pack_forget()
        self.editor = Editor(self.host, self, style, self.saved.get(style.id))
        self.editor.pack(fill="both", expand=True)

    def show_limits(self):
        win = tk.Toplevel(self, bg=T["panel"])
        win.title("Limits & sources")
        win.geometry("720x700")
        txt = tk.Text(win, wrap="word", bg=T["panel"], fg=T["text"], font=F(10), relief="flat", padx=22, pady=18,
                      insertbackground=T["text"], spacing3=6)
        txt.insert("1.0", LIMITS_TEXT)
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True)


def run_gui():
    if not HAVE_TK:
        print("The window needs Python's tkinter, which isn't installed.\n"
              "  Windows/macOS: reinstall Python from python.org (tick 'tcl/tk').\n"
              "  Debian/Ubuntu: sudo apt install python3-tk\n"
              "The command-line mode still works:  python dieline_generator.py --help")
        return
    App().mainloop()


def main(argv=None):
    """No arguments -> open the GUI.  With arguments -> headless export (handy for batch jobs)."""
    import argparse
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        run_gui()
        return 0
    ap = argparse.ArgumentParser(description="BoxForge - generate a box dieline without the GUI.")
    ap.add_argument("--style", required=True, choices=sorted(STYLE_BY_ID), help="box style")
    for k in ("L", "W", "H", "t"):
        ap.add_argument(f"--{k}", type=float, required=True)
    ap.add_argument("--mode", choices=["inner", "outer", "manufacturer"], default="inner")
    ap.add_argument("--units", choices=["mm", "in"], default="mm")
    ap.add_argument("--no-folds", action="store_true", help="leave the fold lines out")
    ap.add_argument("--opt", action="append", default=[], metavar="KEY=VALUE",
                    help="advanced option (e.g. glue=25); repeat as needed")
    ap.add_argument("--svg"), ap.add_argument("--dxf")
    a = ap.parse_args(argv)
    st = STYLE_BY_ID[a.style]
    spec = default_spec(st, a.units)
    spec.L, spec.W, spec.H, spec.t, spec.mode, spec.folds = a.L, a.W, a.H, a.t, a.mode, not a.no_folds
    for kv in a.opt:
        k, _, v = kv.partition("=")
        spec.opts[k] = float(v)
    res = generate(st, spec)
    for i in res.issues:
        print(f"[{i.level.upper():5s}] {i.msg}")
    if not res.ok:
        print("Not exported: fix the errors above.")
        return 1
    notes = [f"BoxForge {st.name} L{fmt(a.L)} W{fmt(a.W)} H{fmt(a.H)} t{fmt(a.t)} {a.units} ({a.mode})"] + res.notes()
    if a.svg:
        open(a.svg, "w", encoding="utf-8").write(to_svg(res.drawing, a.units, notes=notes))
        print("wrote", a.svg)
    if a.dxf:
        open(a.dxf, "w", encoding="utf-8").write(to_dxf(res.drawing, a.units, notes))
        print("wrote", a.dxf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
