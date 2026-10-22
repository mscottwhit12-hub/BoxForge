# =============================================================================
# Bend engine
# =============================================================================
# Presets are typical starting values for a scored / creased sheet, NOT measured data: calibrate against a test fold
# of your own board. ri = inside radius as a multiple of the board thickness, k = neutral-axis (K) factor,
# springback = degrees the fold relaxes back at 90 degrees (scaled with the angle).
BEND_MATERIALS = {
    "corrugated": dict(label="Corrugated board, scored", ri=0.25, k=0.40, springback=4.0),
    "paperboard": dict(label="Paperboard / chipboard, creased", ri=0.50, k=0.42, springback=6.0),
    "acrylic": dict(label="Acrylic, heat-bent", ri=1.50, k=0.40, springback=3.0),
    "plastic": dict(label="Thin plastic sheet, scored", ri=1.00, k=0.38, springback=8.0),
}
BEND_DEFAULT = "corrugated"


class BendSpec:
    """Bend parameters in millimetres. ri = inside radius, k = neutral-axis factor, springback = degrees at 90."""

    def __init__(self, t, ri=None, k=None, springback=None, material=BEND_DEFAULT):
        mat = BEND_MATERIALS.get(material) or BEND_MATERIALS[BEND_DEFAULT]
        self.material = material if material in BEND_MATERIALS else BEND_DEFAULT
        self.t = float(t)
        self.ri = max(0.0, float(mat["ri"] * self.t if ri is None else ri))
        self.k = min(0.5, max(0.0, float(mat["k"] if k is None else k)))
        self.springback = float(mat["springback"] if springback is None else springback)

    @property
    def ro(self):
        return self.ri + self.t

    def __repr__(self):
        return f"BendSpec(t={self.t:g}, ri={self.ri:g}, k={self.k:g}, {self.material})"


def bend_spec_from(spec):
    """BendSpec (mm) for a Spec: spec.bend_r is the inside radius in the user's units (None = material preset)."""
    mmk = 25.4 if spec.units == "in" else 1.0
    r = getattr(spec, "bend_r", None)
    return BendSpec(spec.t * mmk, None if r is None else r * mmk, getattr(spec, "bend_k", None),
                    None, getattr(spec, "material", BEND_DEFAULT))


def bend_calc(bs, angle_deg):
    """Textbook sheet bend for a fold of `angle_deg` (0 = flat, 90 = right angle). All lengths in mm.
    rho = neutral radius, ba = bend allowance (arc length of the neutral axis), ossb = outside setback (virtual sharp
    corner to the tangent point), bd = bend deduction (2 ossb - ba), strain_* = outer / inner fibre strain."""
    a = min(max(float(angle_deg), 0.0), 179.0)
    th = math.radians(a)
    rho = bs.ri + bs.k * bs.t
    ba = th * rho
    ossb = bs.ro * math.tan(th / 2)
    return dict(angle=a, rho=rho, ba=ba, ossb=ossb, bd=2 * ossb - ba, arc_out=th * bs.ro, arc_in=th * bs.ri,
                strain_out=(bs.ro - rho) / rho if rho > 1e-9 else 0.0,
                strain_in=(bs.ri - rho) / rho if rho > 1e-9 else -1.0,
                tangent=ossb, commanded=a + bs.springback * a / 90.0)


def bend_profile(bs, angle_deg, n=24):
    """2-D section of one bend: dict(outside, inside, neutral) polylines in mm, bend centre at (0, 0), the
    first flat leg arriving along +x at the start of the arc and the arc turning towards +y by `angle_deg`."""
    th = math.radians(min(max(float(angle_deg), 0.0), 179.0))
    out = {}
    for key, r in (("outside", bs.ro), ("inside", bs.ri), ("neutral", bs.ri + bs.k * bs.t)):
        out[key] = [(r * math.sin(th * i / n), -r * math.cos(th * i / n)) for i in range(n + 1)]
    return out


def _poly_area(poly):
    return abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                   for i in range(len(poly)))) / 2.0


def fold_kind(p, panels_by_name):
    par = panels_by_name.get(p.parent)
    if p.name == "glue":
        return "glue flap"
    if is_insert(p):
        return "insert fold"
    if p.role == "body":
        return "wall"
    if par is not None and par.role == "body":
        return "closing flap"
    return "other"


def bend_table(panels, bs, units="mm", prog=1.0):
    """One row per fold: name, parent, kind, hinge length (mm), target angle, and the bend maths at that angle."""
    mmk = 25.4 if units == "in" else 1.0
    by = {p.name: p for p in panels}
    rows = []
    for p in panels:
        if p.parent is None or not p.hinge:
            continue
        (ax, ay), (bx, by_) = p.hinge
        c = bend_calc(bs, p.angle * prog)
        segs = getattr(p, "fold_segs", None) or [p.hinge]          # a slit through the middle leaves only the end hinges
        c.update(name=p.name, parent=p.parent, kind=fold_kind(p, by),
                 length=sum(math.hypot(q[1][0] - q[0][0], q[1][1] - q[0][1]) for q in segs) * mmk)
        rows.append(c)
    return rows


def _bend_ri_user(spec):
    """Inside bend radius in the user's units for a Spec."""
    return bend_spec_from(spec).ri / (25.4 if spec.units == "in" else 1.0)


def bend_report(res, spec, bs=None):
    """Everything the engine knows about folding and using the board for a generated result (all mm / mm2)."""
    bs = bs or bend_spec_from(spec)
    mmk = 25.4 if spec.units == "in" else 1.0
    panels = res.panels or []
    rows = bend_table(panels, bs, spec.units)
    kinds = {}
    for r in rows:
        g = kinds.setdefault((r["kind"], round(r["angle"])), dict(kind=r["kind"], count=0, length=0.0, angle=r["angle"], ba=r["ba"],
                                              ossb=r["ossb"], bd=r["bd"], commanded=r["commanded"]))
        g["count"] += 1
        g["length"] += r["length"]
    xs = [q[0] * mmk for p in panels for q in p.poly]
    ys = [q[1] * mmk for p in panels for q in p.poly]
    bw, bh = (max(xs) - min(xs), max(ys) - min(ys)) if xs else (0.0, 0.0)
    net = sum(_poly_area([(q[0] * mmk, q[1] * mmk) for q in p.poly]) for p in panels)
    cut_len = 0.0
    if res.drawing is not None:
        for it in res.drawing.items:
            if it[-1] != CUT:
                continue
            if it[0] == "L":
                cut_len += math.dist(it[1], it[2]) * mmk
            else:
                sw = (it[4] - it[3]) % 360 or 360
                cut_len += math.radians(sw) * it[2] * mmk
    zone = sum(r["ba"] * r["length"] for r in rows)
    kerf = (spec.kerf or 0.0) * mmk
    sw, sh = spec.sheet if spec.sheet else (None, None)
    nest = None
    if sw and sh and bw > 0 and bh > 0:
        sw, sh = sw * mmk, sh * mmk
        n1 = int(sw // bw) * int(sh // bh)
        n2 = int(sw // bh) * int(sh // bw)
        n = max(n1, n2)
        nest = dict(sheet=(sw, sh), per_sheet=n, utilisation=(n * net / (sw * sh)) if n else 0.0)
    # What the dieline already assumes: its crease-to-crease sizes are (outside size - t) for a 90 degree fold, so it
    # builds in a bend deduction of one board. Compare it with what the bend model predicts for the same fold.
    ninety = bend_calc(bs, 90.0)
    implied_ba = 2 * ninety["ossb"] - bs.t
    k_impl = ((implied_ba / (math.pi / 2)) - bs.ri) / bs.t if bs.t > 0 else 0.0
    return dict(spec=bs, folds=rows, groups=list(kinds.values()),
                usage=dict(blank_w=bw, blank_h=bh, blank_area=bw * bh, net_area=net, waste_area=bw * bh - net,
                           utilisation=net / (bw * bh) if bw * bh else 0.0, cut_length=cut_len,
                           kerf_area=cut_len * kerf, bend_zone_area=zone, volume=net * bs.t,
                           fold_length=sum(r["length"] for r in rows), nest=nest),
                dieline=dict(implied_bd=bs.t, model_bd=ninety["bd"], crease_delta=ninety["bd"] - bs.t,
                             implied_ba=implied_ba, implied_k=k_impl))


def bend_report_text(rep, units="mm"):
    """Plain-text version of bend_report (for the CLI)."""
    bs, u = rep["spec"], rep["usage"]
    L = ["BEND MODEL  (%s; ri %.2f mm = %.2f x board, K %.2f, board %.2f mm)" % (
        BEND_MATERIALS[bs.material]["label"], bs.ri, bs.ri / bs.t if bs.t else 0, bs.k, bs.t),
         "  kind          folds  length mm  angle  BA mm  setback mm  BD mm  commanded"]
    for g in rep["groups"]:
        L.append("  %-13s %5d %10.1f %6.1f %6.2f %11.2f %6.2f %9.1f" % (
            g["kind"], g["count"], g["length"], g["angle"], g["ba"], g["ossb"], g["bd"], g["commanded"]))
    L += ["MATERIAL",
          "  blank %.1f x %.1f mm   board used %.0f mm2 of %.0f mm2 (%.0f%%)   waste in the blank %.0f mm2" % (
              u["blank_w"], u["blank_h"], u["net_area"], u["blank_area"], 100 * u["utilisation"], u["waste_area"]),
          "  cut length %.0f mm   kerf loss %.1f mm2   bend zones %.0f mm2   board volume %.0f mm3" % (
              u["cut_length"], u["kerf_area"], u["bend_zone_area"], u["volume"])]
    if u["nest"]:
        n = u["nest"]
        L.append("  sheet %.0f x %.0f mm: %d blanks, %.0f%% of the sheet used" % (
            n["sheet"][0], n["sheet"][1], n["per_sheet"], 100 * n["utilisation"]))
    d = rep["dieline"]
    L.append("DIELINE CHECK  the dieline's 90 degree folds assume a bend deduction of %.2f mm (K %.2f for this radius); "
             "the bend model gives %.2f mm.%s Dimensions are not changed." % (
                 d["implied_bd"], d["implied_k"], d["model_bd"],
                 " (A K above 0.5 is not physical: the dieline allows more than a fold of this radius uses.)"
                 if d["implied_k"] > 0.5 else ""))
    return "\n".join(L)


# ----- 3-D: rounded folds ----------------------------------------------------
def _solve3(a, b, c, rhs):
    """Solve [a; b; c] x = rhs (rows are 3-vectors); None when singular."""
    det = a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])
    if abs(det) < 1e-12:
        return None

    def d3(r0, r1, r2, k):
        m = [list(a), list(b), list(c)]
        for i, v in enumerate((r0, r1, r2)):
            m[i][k] = v
        return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
    return tuple(d3(rhs[0], rhs[1], rhs[2], k) / det for k in range(3))


def _dot3(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _clip_half(poly, a, n, dist):
    """Keep the part of `poly` with (p - a) . n >= dist (Sutherland-Hodgman)."""
    out = []
    for i in range(len(poly)):
        p, q = poly[i], poly[(i + 1) % len(poly)]
        dp = (p[0] - a[0]) * n[0] + (p[1] - a[1]) * n[1] - dist
        dq = (q[0] - a[0]) * n[0] + (q[1] - a[1]) * n[1] - dist
        if dp >= 0:
            out.append(p)
        if (dp >= 0) != (dq >= 0):
            s = dp / (dp - dq)
            out.append((p[0] + (q[0] - p[0]) * s, p[1] + (q[1] - p[1]) * s))
    return out


def _notch_pieces(pieces, A, B, n, dist):
    """Cut the strip of depth `dist` (along the unit normal n, into the panel) beside the hinge segment A-B out of
    every convex piece. A piece splits into at most three convex pieces: before the hinge, after it, and the part
    of the middle that is deeper than `dist`."""
    Lh = math.dist(A, B)
    if Lh < 1e-9 or dist <= 1e-9:
        return pieces
    u = ((B[0] - A[0]) / Lh, (B[1] - A[1]) / Lh)
    mu = (-u[0], -u[1])
    out = []
    for pc in pieces:
        for part in (_clip_half(pc, A, mu, 0.0), _clip_half(pc, A, u, Lh),
                     _clip_half(_clip_half(_clip_half(pc, A, u, 0.0), A, mu, -Lh), A, n, dist)):
            if len(part) >= 3 and _poly_area(part) > 1e-9:
                out.append(part)
    return out


def _merge_pieces(pieces, eps=1e-7):
    """Join convex pieces that share edges into one outline (edges shared by two pieces cancel)."""
    pieces = [list(pc) for pc in pieces if len(pc) >= 3]
    if not pieces:
        return []
    if len(pieces) == 1:
        return pieces[0]
    key = lambda q: (round(q[0] / eps), round(q[1] / eps))
    pts = {}
    ccw = []
    for pc in pieces:
        if sum(pc[i][0] * pc[(i + 1) % len(pc)][1] - pc[(i + 1) % len(pc)][0] * pc[i][1] for i in range(len(pc))) < 0:
            pc = pc[::-1]
        ccw.append(pc)
        for q in pc:
            pts[key(q)] = q
    verts = list(pts.values())
    edges = {}
    for pc in ccw:
        for i in range(len(pc)):
            a, b = pc[i], pc[(i + 1) % len(pc)]
            la = math.dist(a, b)
            if la < eps:
                continue
            on = []
            for w in verts:
                if key(w) in (key(a), key(b)):
                    continue
                t_ = ((w[0] - a[0]) * (b[0] - a[0]) + (w[1] - a[1]) * (b[1] - a[1])) / (la * la)
                if 0 < t_ < 1 and abs((w[0] - a[0]) * (b[1] - a[1]) - (w[1] - a[1]) * (b[0] - a[0])) / la < eps * 10:
                    on.append((t_, w))
            chain = [a] + [w for _, w in sorted(on, key=lambda x: x[0])] + [b]
            for c0, c1 in zip(chain, chain[1:]):
                k0, k1 = key(c0), key(c1)
                if (k1, k0) in edges and edges[(k1, k0)] > 0:
                    edges[(k1, k0)] -= 1
                else:
                    edges[(k0, k1)] = edges.get((k0, k1), 0) + 1
    left = {}
    for (k0, k1), c in edges.items():
        for _ in range(c):
            left.setdefault(k0, []).append(k1)
    loops = []
    while left:
        k0 = next(iter(left))
        loop = [k0]
        cur = k0
        while True:
            nxt = left[cur].pop()
            if not left[cur]:
                del left[cur]
            if nxt == k0:
                break
            loop.append(nxt)
            cur = nxt
            if cur not in left:
                break
        if len(loop) >= 3:
            loops.append([pts[k] for k in loop])
    if not loops:
        return max(ccw, key=_poly_area)
    poly = max(loops, key=_poly_area)
    out = []
    n = len(poly)
    for i in range(n):                                       # drop collinear vertices
        a, b, c = poly[i - 1], poly[i], poly[(i + 1) % n]
        if abs((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])) > 1e-9 * max(1.0, math.dist(a, c)):
            out.append(b)
    return out if len(out) >= 3 else poly


def _on_cut(p, q, A, B, n, dist, eps=1e-7):
    """True when edge p-q lies on the cut line (depth `dist` from hinge A-B) within the hinge's extent."""
    Lh = math.dist(A, B)
    if Lh < 1e-9:
        return False
    u = ((B[0] - A[0]) / Lh, (B[1] - A[1]) / Lh)
    for r in (p, q):
        v = (r[0] - A[0]) * n[0] + (r[1] - A[1]) * n[1]
        a = (r[0] - A[0]) * u[0] + (r[1] - A[1]) * u[1]
        if abs(v - dist) > eps or a < -eps or a > Lh + eps:
            return False
    return True


def bend_fillets(panels, tf, t, ri, nseg=10, max_ro=None, k=None, allow=True):
    """Rounded folds for a folded model whose panels sit at `tf` ({name: (R, offset)} from panel_transforms).
    Every hinge gets an arc strip (outside radius ri + t, inside radius ri) and the two panels are trimmed back to the
    arc's tangent lines, so the outside envelope of the sharp model is only ever shaved, never enlarged. When the
    requested radius does not fit at the current fold angle it is enlarged up to `max_ro`, else the fold stays sharp.
    Where two folds meet at a box corner the arc strip stops where the neighbouring trim begins.
    With `allow` the bend's material is taken out of the leaf panels (closing flaps and the glue flap): the real flap
    has length - BA/2 of flat board past the tangent point, so its tip is cut back by BA/2 - trim (never lengthened).
    Returns (trims, strips, skipped, tips): trims {panel: [(hinge end A, hinge end B, flat unit normal into the panel,
    distance)]}, strips [(name, role, [(kind, [3-D points])])], skipped [panel names], tips {panel: (flat point,
    flat unit normal, distance)} half-planes (keep (p - A) . n >= distance) that shorten the tips."""
    by = {p.name: p for p in panels}
    folds, skipped = [], []
    max_ro = max_ro if max_ro is not None else ri + 4 * t
    for p in panels:
        if p.parent is None or not p.hinge or p.parent not in tf or p.name not in tf:
            continue
        (ax, ay), (bx, by_) = p.hinge
        Lh = math.hypot(bx - ax, by_ - ay)
        if Lh < 1e-9:
            continue
        ux, uy = (bx - ax) / Lh, (by_ - ay) / Lh
        cx = sum(q[0] for q in p.poly) / len(p.poly)
        cy = sum(q[1] for q in p.poly) / len(p.poly)
        side = 1.0 if ((cx - ax) * (-uy) + (cy - ay) * ux) > 0 else -1.0
        sx, sy = -uy * side, ux * side                       # flat unit vector from the hinge into the child
        Rc, tc = tf[p.name]
        Rp, tp = tf[p.parent]
        T = lambda R, o, x, y: tuple(v + w for v, w in zip(_matvec(R, (x, y, 0.0)), o))
        wc, wp = _matvec(Rc, (sx, sy, 0.0)), _matvec(Rp, (sx, sy, 0.0))
        nc, npar = _matvec(Rc, (0.0, 0.0, 1.0)), _matvec(Rp, (0.0, 0.0, 1.0))
        d = _matvec(Rc, (ux, uy, 0.0))
        phi = math.acos(max(-1.0, min(1.0, _dot3(wp, wc))))
        if phi < math.radians(1.0) or phi > math.radians(175.0):
            continue
        mx, my = (ax + bx) / 2, (ay + by_) / 2
        Hc, Hp = T(Rc, tc, mx, my), T(Rp, tp, mx, my)
        V = _solve3(npar, nc, d, (_dot3(npar, Hp), _dot3(nc, Hc), _dot3(d, Hc)))
        if V is None:
            skipped.append(p.name)
            continue
        dvp = _dot3((V[0] - Hp[0], V[1] - Hp[1], V[2] - Hp[2]), wp)
        dvc = _dot3((V[0] - Hc[0], V[1] - Hc[1], V[2] - Hc[2]), wc)
        tn = math.tan(phi / 2)
        need = max(-dvc, dvp, 0.0) / tn if tn > 1e-9 else 1e9    # smallest outside radius with both trims >= 0
        ro = max(ri + t, need * 1.0001)
        if ro > max_ro + 1e-9:
            skipped.append(p.name)
            continue
        To = ro * tn
        trim_p, trim_c = To - dvp, To + dvc
        if trim_p < -1e-6 or trim_c < -1e-6:
            skipped.append(p.name)
            continue
        folds.append(dict(p=p, A=(ax, ay), B=(bx, by_), u=(ux, uy), s=(sx, sy), Lh=Lh, ro=ro, To=To, phi=phi, V=V,
                          wp=wp, nc=nc, npar=npar, d=d, Hc=Hc, Ha=T(Rc, tc, ax, ay), Hb=T(Rc, tc, bx, by_),
                          trim_p=max(0.0, trim_p), trim_c=max(0.0, trim_c)))
    trims, strips, tips = {}, [], {}
    kf = BEND_MATERIALS[BEND_DEFAULT]["k"] if k is None else k
    parents = {p.parent for p in panels if p.parent}
    for f in folds:
        p = f["p"]
        if allow and p.name not in parents and p.poly:         # a leaf: closing flap or glue flap
            ba = f["phi"] * ((f["ro"] - t) + kf * t)
            cut = max(0.0, ba / 2 - f["trim_c"])
            sx, sy = f["s"]
            tip = max((q[0] - f["A"][0]) * sx + (q[1] - f["A"][1]) * sy for q in p.poly)
            if cut > 1e-9 and cut < 0.6 * tip:
                tips[p.name] = (f["A"], (-sx, -sy), -(tip - cut))
        A, B, u, Lh = f["A"], f["B"], f["u"], f["Lh"]
        lo, hi = 0.0, Lh                                        # the arc strip covers the whole hinge
        # both panels lose a notch along the hinge only, so the corner columns of the walls stay whole
        trims.setdefault(p.parent, []).append((A, B, (-f["s"][0], -f["s"][1]), f["trim_p"]))
        trims.setdefault(p.name, []).append((A, B, f["s"], f["trim_c"]))
        ro, rin, To, phi, V = f["ro"], f["ro"] - t, f["To"], f["phi"], f["V"]
        wp, nc, npar, d, Hc = f["wp"], f["nc"], f["npar"], f["d"], f["Hc"]
        Ha, Hb = f["Ha"], f["Hb"]
        Ha2 = tuple(Ha[i] + d[i] * lo for i in range(3))
        Hb2 = tuple(Ha[i] + d[i] * hi for i in range(3))
        sec = lambda X: tuple(V[i] + d[i] * _dot3(d, (X[0] - Hc[0], X[1] - Hc[1], X[2] - Hc[2])) for i in range(3))
        Va, Vb = sec(Ha2), sec(Hb2)
        a0 = (-npar[0], -npar[1], -npar[2])
        a1 = (-nc[0], -nc[1], -nc[2])
        sp = math.sin(phi)

        def vdir(tau, a0=a0, a1=a1, phi=phi, sp=sp):
            u0, u1 = math.sin((1 - tau) * phi) / sp, math.sin(tau * phi) / sp
            return tuple(u0 * a0[i] + u1 * a1[i] for i in range(3))

        def arc_pts(Vx, r, wp=wp, To=To, npar=npar, ro=ro, vdir=vdir):
            P1 = tuple(Vx[i] - wp[i] * To for i in range(3))
            O = tuple(P1[i] + npar[i] * ro for i in range(3))
            return [tuple(O[i] + vdir(j / nseg)[i] * r for i in range(3)) for j in range(nseg + 1)]
        oa, ob = arc_pts(Va, ro), arc_pts(Vb, ro)
        ia, ib = arc_pts(Va, rin), arc_pts(Vb, rin)

        def facing(pts, want):
            n = _newell(pts)
            return pts if _dot3(n, want) >= 0 else pts[::-1]
        faces = []
        for j in range(nseg):
            vm = vdir((j + 0.5) / nseg)
            faces.append(("out", facing([oa[j], oa[j + 1], ob[j + 1], ob[j]], vm)))
            faces.append(("in", facing([ia[j], ia[j + 1], ib[j + 1], ib[j]], (-vm[0], -vm[1], -vm[2]))))
        dh = tuple(Hb2[i] - Ha2[i] for i in range(3))
        faces.append(("edge", facing(oa + ia[::-1], (-dh[0], -dh[1], -dh[2]))))
        faces.append(("edge", facing(ob + ib[::-1], dh)))
        strips.append((p.name + ".bend", p.role, faces))
    return trims, strips, skipped, tips


def panel_transforms(panels, t, prog_of, lift_of=None, fit=True):
    """{panel name: (R, offset)} placing each flat panel in the folded model: p -> R p + offset. `prog_of(panel,
    depth, maxdepth)` is the panel's own fold progress 0..1 about its hinge. With `fit` each folded panel is also
    moved one board thickness off its parent (along the parent's inward normal; the glue flap then lies flat against
    the inside of the last wall) so thick panels sit against each other instead of passing through; the folded
    box is then the inside size + 2 boards. `lift_of(panel, progress)` may add a final shift (stacked flaps)."""
    depth = {}
    for p in panels:
        depth[p.name] = 0 if p.parent is None else depth[p.parent] + 1
    maxd = max(max(depth.values()), 1)
    xf, out, progs = {}, {}, {}
    for p in panels:
        shift = None
        if p.parent is None:
            R, tt = _I3, (0.0, 0.0, 0.0)
        else:
            Rp, tp = xf[p.parent]
            (ax, ay), (bx, by) = p.hinge
            L = math.hypot(bx - ax, by - ay)
            ux, uy = (bx - ax) / L, (by - ay) / L
            cx = sum(q[0] for q in p.poly) / len(p.poly)
            cy = sum(q[1] for q in p.poly) / len(p.poly)
            side = 1.0 if ((cx - ax) * (-uy) + (cy - ay) * ux) > 0 else -1.0
            prog = prog_of(p, depth[p.name], maxd)
            progs[p.name] = prog
            shift = lift_of(p, prog) if lift_of else None
            Rot = _rot_axis((ux, uy, 0.0), math.radians(p.angle) * side * prog)
            q0 = (ax, ay, 0.0)
            Rq = _matvec(Rot, q0)
            R = _matmul(Rp, Rot)
            sh = _matvec(Rp, (q0[0] - Rq[0], q0[1] - Rq[1], q0[2] - Rq[2]))
            tt = (sh[0] + tp[0], sh[1] + tp[1], sh[2] + tp[2])
            if fit:
                nrm = _matvec(Rp, (0.0, 0.0, 1.0))             # parent's inward normal
                tt = (tt[0] + t * prog * nrm[0], tt[1] + t * prog * nrm[1], tt[2] + t * prog * nrm[2])
        if shift and getattr(lift_of, "inherit", False):        # the shift carries every panel hinged to this one
            tt = (tt[0] + shift[0], tt[1] + shift[1], tt[2] + shift[2])
            shift = None
        xf[p.name] = (R, tt)
        out[p.name] = (R, tt if not shift else (tt[0] + shift[0], tt[1] + shift[1], tt[2] + shift[2]))
    if fit:
        _centre_flaps(panels, xf, out, progs)
    return out


def _centre_flaps(panels, xf, out, progs):
    """The walls of a thick box are offset from each other by one board (they wrap round like a pinwheel), so the
    flaps hinged to them would sit one board off-centre and the facing flaps would not line up. Slide each closing
    flap along its hinge so it is centred on the box, scaled by its fold progress."""
    by = {p.name: p for p in panels}
    body_all = [p for p in panels if p.role == "body" and p.name in xf]
    if not body_all:
        return

    def root_of(p):
        while p.parent:
            p = by[p.parent]
        return p.name
    for p in panels:
        par = by.get(p.parent) if p.parent else None
        if p.role == "body" or p.name == "glue" or par is None or par.role != "body" or not progs.get(p.name):
            continue
        rt = root_of(p)
        body = [b for b in body_all if root_of(b) == rt] or body_all      # only this tray / piece of the sheet
        Rp, tp = xf[par.name]
        (ax, ay), (bx, by_) = p.hinge
        Lh = math.hypot(bx - ax, by_ - ay)
        if Lh < 1e-9:
            continue
        d = _matvec(Rp, ((bx - ax) / Lh, (by_ - ay) / Lh, 0.0))
        mid = _matvec(Rp, ((ax + bx) / 2, (ay + by_) / 2, 0.0))
        mid = (mid[0] + tp[0], mid[1] + tp[1], mid[2] + tp[2])
        lo, hi = 1e18, -1e18
        for b in body:
            Rb, tb = xf[b.name]
            for q in b.poly:
                v = _matvec(Rb, (q[0], q[1], 0.0))
                pr = (v[0] + tb[0]) * d[0] + (v[1] + tb[1]) * d[1] + (v[2] + tb[2]) * d[2]
                lo, hi = min(lo, pr), max(hi, pr)
        off = ((lo + hi) / 2 - (mid[0] * d[0] + mid[1] * d[1] + mid[2] * d[2])) * progs[p.name] * progs.get(par.name, 1.0)
        R, tt = out[p.name]
        out[p.name] = (R, (tt[0] + off * d[0], tt[1] + off * d[1], tt[2] + off * d[2]))


def _hatch(poly, idx, s, inset):
    """Parallel lines of constant coordinate `idx` (0 = u, 1 = v) at odd multiples of s/2, clipped to the polygon
    (even-odd rule), each shortened by `inset` at both ends. Returns [((u0, v0), (u1, v1))]."""
    n = len(poly)
    if n < 3 or s <= 0:
        return []
    o = 1 - idx
    cs = [q[idx] for q in poly]
    lo, hi = min(cs), max(cs)
    if (hi - lo) / s > 4000:
        return []
    out = []
    c = (math.ceil(lo / s - 0.5) + 0.5) * s
    while c < hi:
        if c > lo:
            xs = []
            for i in range(n):
                a, b = poly[i], poly[(i + 1) % n]
                ca, cb = a[idx], b[idx]
                if ca <= c < cb or cb <= c < ca:           # half-open, so a vertex on the line counts once
                    xs.append(a[o] + (c - ca) / (cb - ca) * (b[o] - a[o]))
            xs.sort()
            for j in range(0, len(xs) - 1, 2):
                a0, a1 = xs[j] + inset, xs[j + 1] - inset
                if a1 - a0 >= s:
                    p0, p1 = [0.0, 0.0], [0.0, 0.0]
                    p0[idx] = p1[idx] = c
                    p0[o], p1[o] = a0, a1
                    out.append((tuple(p0), tuple(p1)))
        c += s
    return out


def flute_spacing(panels, t):
    """Distance between the flute lines drawn on the folded preview, in panel units."""
    xs = [q[0] for p in panels for q in p.poly]
    ys = [q[1] for p in panels for q in p.poly]
    if not xs:
        return max(2.0 * t, 1.0)
    return max(2.0 * t, max(max(xs) - min(xs), max(ys) - min(ys)) / 80.0)


FM_FLAP_PARTS = 1        # flap bends are cut into this many plates for the draw-order sort
CHAIN_FOLD = True        # slotted box with rounded folds: build the chain model (fold_rsc) instead of trimming a sharp one


def solid_faces(panels, t, prog_of, lift_of=None, fit=True, bend=None, info=None, bend_k=None, bend_len=True,
                flute=None, _flute_sp=None):
    """Faces [(panel, kind, [3-D points], role)] of thick panels (see panel_transforms for the folding). The sheet
    plane is the OUTSIDE face; the board extends `t` toward the inside of the box. `bend` = inside bend radius in
    the same units as the panels (None = sharp folds): hinges become arc strips and the panels are trimmed to them
    (see bend_fillets); `bend_k` is the K-factor and `bend_len` takes the bend's material out of the flap lengths.
    `info`, if a dict, receives {"skipped": [panels left sharp]}. `flute` ("v" or "h") adds faint corrugation lines
    on the outside faces as faces of kind "flute" ([name, "flute", [p0, p1], role]): "v" runs them along the flat
    sheet's y axis, "h" along x, so they show which way the board's flutes run on the folded box."""
    fl = (flute, _flute_sp or flute_spacing(panels, t)) if flute in ("v", "h") else None
    if any(is_insert(p) for p in panels):                          # an insert, alone or with a box
        return _solid_with_insert(panels, t, prog_of, lift_of, fit, bend, info, bend_k, bend_len, flute, fl)
    if bend is not None and fit and CHAIN_FOLD:
        fr = fold_rsc(panels, t, prog_of, lift_of, ri=max(0.0, bend), k=bend_k, info=None, lose=bend_len, flute=fl)
        if fr is None:
            fr = fold_tray(panels, t, prog_of, lift_of, ri=max(0.0, bend), k=bend_k, info=None, lose=bend_len, flute=fl)
        if fr is not None:
            if info is not None:
                info["skipped"] = []
            return fr
    faces = []
    tf = panel_transforms(panels, t, prog_of, lift_of, fit)
    trims, strips, tips = {}, [], {}
    if bend is not None and fit:
        trims, strips, skipped, tips = bend_fillets(panels, tf, t, max(0.0, bend), k=bend_k, allow=bend_len)
        if info is not None:
            info["skipped"] = skipped
    for p in panels:
        R, ttf = tf[p.name]

        def T3(x, y, z, R=R, tt=ttf):
            v = _matvec(R, (x, y, z))
            return (v[0] + tt[0], v[1] + tt[1], v[2] + tt[2])
        poly = list(p.poly)
        if len(poly) < 3:
            continue
        if sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
               for i in range(len(poly))) < 0:
            poly.reverse()                                 # counter-clockwise in the flat sheet
        cuts = trims.get(p.name, [])
        if cuts or p.name in tips:
            pieces = [poly]
            for A0, B0, n0, dist in cuts:                  # trimmed back to the tangent lines of the arcs
                pieces = _notch_pieces(pieces, A0, B0, n0, dist)
            if p.name in tips:
                pieces = [_clip_half(pc, *tips[p.name]) for pc in pieces]
            poly = _merge_pieces(pieces)
        if len(poly) < 3:
            continue
        outer = [T3(x, y, 0.0) for x, y in poly]
        inner = [T3(x, y, t) for x, y in poly]
        faces.append((p.name, "out", outer[::-1], p.role))   # outside face looks along -z
        faces.append((p.name, "in", inner, p.role))
        for i in range(len(poly)):
            j = (i + 1) % len(poly)
            if math.dist(poly[i], poly[j]) < 1e-9:
                continue
            if any(_on_cut(poly[i], poly[j], A0, B0, n0, dist) for A0, B0, n0, dist in cuts):
                continue                                   # this edge is closed by the arc strip
            faces.append((p.name, "edge", [outer[i], outer[j], inner[j], inner[i]], p.role))
        if fl:                                             # flute lines run along the sheet's y (v) or x (h)
            for a, b in _hatch(poly, 0 if fl[0] == "v" else 1, fl[1], 0.35 * fl[1]):
                faces.append((p.name, "flute", [T3(a[0], a[1], 0.0), T3(b[0], b[1], 0.0)], p.role))
    for nm, role, fls in strips:
        for kind, pts in fls:
            faces.append((nm, kind, pts, role))
    return faces


_INS_ORIGIN = {}


def _insert_origin(rest, t, fit, bend, bend_k, bend_len):
    """Where an insert goes inside the folded box `rest`: (cx, y, cz, top, ext). (cx, cz) is the middle of the box's inside,
    y the floor the insert stands on (one board above the outside of the bottom), `top` the highest point of the open
    box (walls with their flaps standing) and ext = (xmin, xmax, zmin, zmax) the inside faces of the walls. Worked out
    from the box with all its walls up (flaps ignored), and remembered per box."""
    key = (tuple((p.name, len(p.poly), round(p.poly[0][0], 6), round(p.poly[0][1], 6)) for p in rest), round(t, 9),
           fit, bend, bend_k, bend_len)
    hit = _INS_ORIGIN.get(key)
    if hit:
        return hit
    walls_up = lambda p, d, m: 1.0 if (p.role == "body" or p.name == "glue") else 0.0
    fin = solid_faces(rest, t, walls_up, None, fit, bend, None, bend_k, bend_len)
    pos = {0: [], 2: []}
    ymin = None
    for nm, kind, pts, role in fin:
        if nm not in ("p1", "p2", "p3", "p4"):
            continue
        if kind == "out":
            ymin = min(q[1] for q in pts) if ymin is None else min(ymin, min(q[1] for q in pts))
        if kind != "in":
            continue
        for ax in (0, 2):
            v = [q[ax] for q in pts]
            if max(v) - min(v) < 1e-6 * max(1.0, t):
                pos[ax].append(v[0])
    if len(pos[0]) >= 2 and len(pos[2]) >= 2:
        ext = (min(pos[0]), max(pos[0]), min(pos[2]), max(pos[2]))
    else:                                                      # not a plain four-wall box: centre on what is there
        xs = [q[0] for f in fin for q in f[2]]
        zs = [q[2] for f in fin for q in f[2]]
        ext = (min(xs), max(xs), min(zs), max(zs))
    ytop = max(q[1] for f in fin for q in f[2])                # top of the standing walls and their open flaps
    out = ((ext[0] + ext[1]) / 2.0, (ymin or 0.0) + t, (ext[2] + ext[3]) / 2.0, ytop, ext)
    if len(_INS_ORIGIN) > 64:
        _INS_ORIGIN.clear()
    _INS_ORIGIN[key] = out
    return out


def _solid_with_insert(panels, t, prog_of, lift_of, fit, bend, info, bend_k, bend_len, flute, fl):
    """solid_faces for a blank that holds an insert: the box (or nothing) as usual, the insert from its own fold model
    standing inside it. They share one flute spacing. While `prog_of.insert_hover` > 0 the insert is held above the
    open box."""
    ins = [p for p in panels if is_insert(p)]
    rest = [p for p in panels if not is_insert(p)]
    kind = next((p.meta.get("kind", "diag") for p in ins if p.meta), "diag")
    ri = None if bend is None else max(0.0, bend)
    faces, box = [], None
    if rest:
        faces = solid_faces(rest, t, prog_of, lift_of, fit, bend, info, bend_k, bend_len, flute,
                            _flute_sp=fl[1] if fl else None)
        box = _insert_origin(rest, t, fit, bend, bend_k, bend_len)
    elif info is not None:
        info["skipped"] = []
    hover = getattr(prog_of, "insert_hover", 0.0)               # 1 = held above the box, 0 = in place
    ih = next((p.meta["Hs"] for p in ins if p.meta), 0.0)
    if kind == "grid":
        fi = fold_grid(ins, t, prog_of, box, hover, flute=fl)
    else:
        origin, turn_axis = (0.0, 0.0, 0.0), False
        if box is not None:
            depth = insert_footprint(ins, t, ri, bend_k)
            ox, oy, oz, ytop, ext = box
            if hover > 0.0:                                    # clear of the open flaps, then down by `hover` of that
                oy += hover * (ytop - oy + 0.12 * ih)
            origin = (ox, oy, oz - depth / 2.0)
            turn_axis = (ext[1] - ext[0]) > (ext[3] - ext[2]) * (1.0 + 1e-6) + 1e-9    # the long side of the box runs along x
            if turn_axis:                                      # the insert is built with its depth along z: turn it
                origin = (0.0, oy, -depth / 2.0)
        fi = fold_insert(ins, t, prog_of, None, ri=ri, k=bend_k, flute=fl, origin=origin)
        if fi and box is not None and turn_axis:               # quarter turn about the vertical, then to the box middle
            mv = lambda q: (q[2] + box[0], q[1], -q[0] + box[2])
            fi = [(nm, kd, [mv(q) for q in pts], rl) for nm, kd, pts, rl in fi]

    return list(faces) + (list(fi) if fi else [])
