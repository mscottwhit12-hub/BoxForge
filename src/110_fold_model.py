# =============================================================================
# Chain fold model for the slotted box: flat panels joined by true arc strips
# =============================================================================
def _vadd(a, b, s=1.0):
    return (a[0] + b[0] * s, a[1] + b[1] * s, a[2] + b[2] * s)


def _vdot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vcross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _fm_face(faces, name, kind, pts, role, want):
    """Append a polygon, wound so its normal agrees with `want`; degenerate polygons are dropped."""
    nx = ny = nz = 0.0
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    if nx * nx + ny * ny + nz * nz < 1e-18:
        return
    if nx * want[0] + ny * want[1] + nz * want[2] < 0:
        pts = pts[::-1]
    faces.append((name, kind, pts, role))


def _fm_on_seg(p, q, a, b, eps=1e-7):
    """True when the segment p-q lies on the segment a-b."""
    ab = (b[0] - a[0], b[1] - a[1])
    L = math.hypot(*ab)
    if L < 1e-12:
        return False
    for r in (p, q):
        if abs((r[0] - a[0]) * ab[1] - (r[1] - a[1]) * ab[0]) / L > eps:
            return False
        k = ((r[0] - a[0]) * ab[0] + (r[1] - a[1]) * ab[1]) / (L * L)
        if k < -eps or k > 1 + eps:
            return False
    return True


class _Faces(list):
    """Face list that also carries the flute setting (direction, spacing) for _fm_slab."""
    flute = None


def _fm_slab(faces, poly, O, eu, ev, en, t, name, role, skip=(), su="x"):
    """Thick flat piece: the 2-D outline `poly` (u, v) on the plane through O spanned by eu, ev (the outside face);
    the board extends t along en. Edges lying on a segment of `skip` are joints to a neighbouring piece (no face).
    `su` is the flat sheet's axis ("x" or "y") that the piece's u axis runs along (v is the other one); it decides
    which way the flute lines go when `faces` carries a flute setting."""
    P = [(float(u), float(v)) for u, v in poly]
    if len(P) < 3:
        return
    if sum(P[i][0] * P[(i + 1) % len(P)][1] - P[(i + 1) % len(P)][0] * P[i][1] for i in range(len(P))) < 0:
        P.reverse()
    P3 = lambda u, v, h: tuple(O[i] + eu[i] * u + ev[i] * v + en[i] * h for i in range(3))
    p0 = [P3(u, v, 0.0) for u, v in P]
    p1 = [P3(u, v, t) for u, v in P]
    _fm_face(faces, name, "out", p0, role, tuple(-c for c in en))
    _fm_face(faces, name, "in", p1, role, en)
    for i in range(len(P)):
        j = (i + 1) % len(P)
        du, dv = P[j][0] - P[i][0], P[j][1] - P[i][1]
        if abs(du) + abs(dv) < 1e-12:
            continue
        if any(_fm_on_seg(P[i], P[j], a, b) for a, b in skip):
            continue
        want = tuple(eu[c] * dv - ev[c] * du for c in range(3))
        _fm_face(faces, name, "edge", [p0[i], p0[j], p1[j], p1[i]], role, want)
    fl = getattr(faces, "flute", None)
    if fl:
        for a, b in _hatch(P, 0 if (fl[0] == "v") == (su == "x") else 1, fl[1], 0.35 * fl[1]):
            faces.append((name, "flute", [P3(a[0], a[1], 0.0), P3(b[0], b[1], 0.0)], role))


def _fm_bend2d(P, d, n, rn, theta, K, t, ba):
    """Turn the outside-face point P (tangent d, board side n) through `theta` keeping the neutral length `ba`.
    Returns (P', d', n', rho_o, centre)."""
    R = rn if theta >= math.pi / 2 - 1e-9 else ba / max(theta, 1e-4)
    rho = R + (1.0 - K) * t
    c, s = math.cos(theta), math.sin(theta)
    C = (P[0] + n[0] * rho, P[1] + n[1] * rho)
    d2 = (c * d[0] + s * n[0], c * d[1] + s * n[1])
    n2 = (c * n[0] - s * d[0], c * n[1] - s * d[1])
    P2 = (C[0] - n2[0] * rho, C[1] - n2[1] * rho)
    return P2, d2, n2, rho, C


def _fm_arc(faces, name, role, t, P, d, n, rho, theta, O, X2, Y2, axis, a0, a1, parts=1):
    """Arc strip: annular sector (outer radius rho, board t) swept along `axis` from a0 to a1. (P, d, n) are the
    2-D start (outside-face point, tangent, board side) in the plane spanned by X2, Y2 about O. With `parts` > 1 the
    strip is cut into that many separate (nearly convex) plates, which the draw-order sort can place individually."""
    C = (P[0] + n[0] * rho, P[1] + n[1] * rho)
    ri = max(0.0, rho - t)
    N = max(2, int(math.ceil(10 * theta / (math.pi / 2))))
    parts = max(1, min(parts, N))
    to3 = lambda p, q, s: tuple(O[i] + X2[i] * p + Y2[i] * q + axis[i] * s for i in range(3))
    sv = lambda f: (-math.cos(f) * n[0] + math.sin(f) * d[0], -math.cos(f) * n[1] + math.sin(f) * d[1])
    out, inn = [], []
    for i in range(N + 1):
        f = theta * i / N
        s = sv(f)
        out.append((C[0] + rho * s[0], C[1] + rho * s[1]))
        inn.append((C[0] + ri * s[0], C[1] + ri * s[1]))
    dir3 = lambda v: tuple(X2[i] * v[0] + Y2[i] * v[1] for i in range(3))
    base = name[:-5] if name.endswith(".bend") else name
    for g in range(parts):
        i0, i1 = g * N // parts, (g + 1) * N // parts
        nm = name if parts == 1 else f"{base}~{g}.bend"
        for i in range(i0, i1):
            sm = sv(theta * (i + 0.5) / N)
            w = dir3(sm)
            _fm_face(faces, nm, "out", [to3(*out[i], a0), to3(*out[i + 1], a0), to3(*out[i + 1], a1),
                                        to3(*out[i], a1)], role, w)
            if ri > 1e-9:
                _fm_face(faces, nm, "in", [to3(*inn[i], a0), to3(*inn[i + 1], a0), to3(*inn[i + 1], a1),
                                           to3(*inn[i], a1)], role, tuple(-c for c in w))
        # the radial end caps are joints to the neighbouring flat pieces: no faces there
        ring = lambda s: [to3(*q, s) for q in out[i0:i1 + 1]] + [to3(*q, s) for q in inn[i0:i1 + 1][::-1]]
        _fm_face(faces, nm, "edge", ring(a0), role, tuple(-c for c in axis))
        _fm_face(faces, nm, "edge", ring(a1), role, axis)


_FM_ARC_X, _FM_ARC_Y = (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)     # plan plane: (x, z), swept along y


def fold_rsc(panels, t, prog_of, lift_of=None, ri=0.0, k=None, info=None, lose=True, flute=None):
    """Thick, bent model of the slotted box built as a chain: every wall is a flat slab, every fold a true arc strip of
    neutral length BA, so the sheet's own length is used up by the bends (flaps end BA/2 short of the sharp model).
    Faces [(panel, kind, [3-D points], role)] like solid_faces, or None when the panels are not an RSC blank.
    Mating comes first: the loop of four bends closes by shifting the folds along the sheet by t/4 (walls 1 and 3
    trade t/2), the free end of the unbent wall is taken flush with the outside of the glue-flap wall, and flaps are
    centred on the box. `info` receives the slack that mating needed. With `lose` False the flaps keep their sharp-model length."""
    by = {p.name: p for p in panels}
    names = [f"p{i}" for i in range(1, 5)]
    if any(n not in by for n in names) or "glue" not in by or t <= 0:
        return None
    K = BEND_MATERIALS[BEND_DEFAULT]["k"] if k is None else k
    ri = max(0.0, ri)
    rn = ri + K * t
    BA = (math.pi / 2) * rn
    HP = math.pi / 2
    walls = [by[n] for n in names]
    xr = [(min(q[0] for q in w.poly), max(q[0] for q in w.poly)) for w in walls]
    y0 = min(q[1] for q in walls[0].poly)
    Hc = max(q[1] for q in walls[0].poly) - y0
    pw = [min(1.0, max(0.0, prog_of(w, 1, 1))) for w in walls]
    pg = min(1.0, max(0.0, prog_of(by["glue"], 1, 1)))
    pm = sum(pw) / 4.0
    creases = [xr[0][0]] + [xr[i][1] for i in range(4)]                      # c0 .. c4
    wd = [xr[i][1] - xr[i][0] for i in range(4)]
    faces = _Faces()
    faces.flute = flute
    inf = info if info is not None else {}

    # --- closing the loop: the shift e (walls 1 and 3 trade e) and the free end g of the unbent wall
    def chain(e, g, theta_w, theta_g):
        P, d, n = (BA / 2 + e / 2, 0.0), (1.0, 0.0), (0.0, 1.0)
        out = []
        flat = [wd[0] - BA - e, wd[1] - BA, wd[2] - BA + e, wd[3] - BA / 2 + g]
        for i in range(4):
            out.append((P, d, n, flat[i]))
            P = (P[0] + d[0] * flat[i], P[1] + d[1] * flat[i])
            if i < 3:
                P, d, n, rho, C = _fm_bend2d(P, d, n, rn, theta_w[i], K, t, BA)
                out[-1] = out[-1] + (rho, C, P, d, n)
        return out
    full = [HP] * 3
    base = chain(0.0, 0.0, full, HP)
    Pg, dg, ng, _, _ = _fm_bend2d(base[0][0], (-1.0, 0.0), (0.0, 1.0), rn, HP, K, t, BA)
    x_glue = Pg[0]                                                          # outer face of the glue flap (x)
    x4 = base[3][0][0]                                                      # outer face of the unbent wall (x)
    e_full = (x4 - x_glue + t) / 2.0                                       # x4(e) = x4 - 3e/2, glue x(e) = x_glue + e/2
    z_end = base[3][0][1] + base[3][1][1] * base[3][3]                      # where the free end falls
    g_full = z_end if base[3][1][1] < 0 else 0.0                            # extend to the glue-flap wall's outside plane
    e = e_full * pm
    g = g_full * pm
    theta_w = [HP * pw[1], HP * pw[2], HP * pw[3]]
    theta_g = HP * pg
    ch = chain(e, g, theta_w, theta_g)
    inf.update(e=e_full, g=g_full, ba=BA, rn=rn)
    sheet0 = [creases[0] + BA / 2 + e_full * pm / 2, creases[1] - e_full * pm / 2 + BA / 2,
              creases[2] - e_full * pm / 2 + BA / 2, creases[3] + e_full * pm / 2 + BA / 2]
    Y = (0.0, 1.0, 0.0)
    pl3 = lambda p: (p[0], 0.0, p[1])
    rho_glue = (ri + t) * pg                                                # the glue bend's outer radius (full fold)
    # --- walls: slabs with a notch at every flap hinge
    flaps = {n: [] for n in names}
    for p in panels:
        if p.role == "flap" and p.name != "glue" and p.parent in flaps and p.hinge:
            flaps[p.parent].append(p)
    notches_of = {}
    lift = lambda p, q: (lift_of(p, q) if lift_of else None) or (0.0, 0.0, 0.0)
    # pre-pass: the box's extent along each wall, to centre the flaps on it
    pre = []
    for i, w in enumerate(walls):
        P, d, n, F = ch[i][:4]
        _fm_slab(pre, [(0.0, y0), (F, y0), (F, y0 + Hc), (0.0, y0 + Hc)], (P[0], 0.0, P[1]), (d[0], 0.0, d[1]), Y,
                 (n[0], 0.0, n[1]), t, w.name, w.role)
        if i < 3:
            Pa = (P[0] + d[0] * F, P[1] + d[1] * F)
            _fm_arc(pre, "x", "body", t, Pa, d, n, ch[i][4], theta_w[i], (0, y0, 0), _FM_ARC_X, _FM_ARC_Y, Y, 0.0, Hc)

    def shift_of(i, u0, u1, q):
        P, d, n, F = ch[i][:4]
        dw = (d[0], 0.0, d[1])
        proj = [_vdot(pt, dw) for f in pre for pt in f[2]]
        mid = _vdot((P[0], 0.0, P[1]), dw) + (u0 + u1) / 2.0
        s = ((min(proj) + max(proj)) / 2.0 - mid) * q
        return s
    for i, w in enumerate(walls):
        P, d, n, F = ch[i][:4]
        notches = []
        for fp in flaps[w.name]:
            (ax, ay), (bx, by_) = fp.hinge
            top = ay - y0 > Hc / 2
            q = min(1.0, max(0.0, prog_of(fp, 1, 1)))
            dy = lift(fp, q)[1]
            h0, h1 = sorted((ax, bx))
            sh = shift_of(i, h0 - sheet0[i], h1 - sheet0[i], q)
            far = F - rho_glue if i == 3 else F                           # keep clear of the glue flap's bend
            notches.append((fp, top, max(0.0, h0 - sheet0[i] + sh), min(far, h1 - sheet0[i] + sh), dy, q))
        notches.sort(key=lambda r: r[2])
        notches_of[w.name] = list(notches)
        # flap centring along the wall: slide each flap so the facing ones line up on the box centre
        poly = [(0.0, 0.0)]
        bottoms = [r for r in notches if not r[1]]
        tops = [r for r in notches if r[1]]
        for fp, top, u0, u1, dy, q in bottoms:
            u0, u1 = u0, u1
            poly += [(u0, 0.0), (u0, BA / 2 + dy), (u1, BA / 2 + dy), (u1, 0.0)]
        poly += [(F, 0.0), (F, Hc)]
        for fp, top, u0, u1, dy, q in sorted(tops, key=lambda r: -r[2]):
            poly += [(u1, Hc), (u1, Hc - BA / 2 + dy), (u0, Hc - BA / 2 + dy), (u0, Hc)]
        poly.append((0.0, Hc))
        poly = [(u, v + y0) for u, v in poly]
        joints = [((0.0, y0), (0.0, y0 + Hc))]                                # joint to the corner arc before the wall
        if i < 3:
            joints.append(((F, y0), (F, y0 + Hc)))                           # ... and after it (the last wall is free)
        for fp, top, u0, u1, dy, q in notches:                               # the flap's bend starts on the notch floor
            yy = y0 + (Hc - BA / 2 + dy if top else BA / 2 + dy)
            joints.append(((u0, yy), (u1, yy)))
        _fm_slab(faces, poly, (P[0], 0.0, P[1]), (d[0], 0.0, d[1]), Y, (n[0], 0.0, n[1]), t, w.name, w.role, joints)
        inf.setdefault("walls", {})[w.name] = dict(P=P, d=d, n=n, F=F)
    # --- corner arcs between walls
    for i in range(3):
        P, d, n, F, rho, C, P2, d2, n2 = ch[i]
        Pa = (P[0] + d[0] * F, P[1] + d[1] * F)
        _fm_arc(faces, walls[i + 1].name + ".bend", walls[i + 1].role, t, Pa, d, n, rho, theta_w[i], (0, y0, 0),
                _FM_ARC_X, _FM_ARC_Y, Y, 0.0, Hc)
    # --- glue flap: bends off the start of wall 1, folds in against the inside of the unbent wall
    gl = by["glue"]
    Ps = ch[0][0]
    Pg, dgv, ngv, rhog, Cg = _fm_bend2d(Ps, (-1.0, 0.0), (0.0, 1.0), rn, theta_g, K, t, BA)
    _fm_arc(faces, "glue.bend", gl.role, t, Ps, (-1.0, 0.0), (0.0, 1.0), rhog, theta_g, (0, y0, 0), _FM_ARC_X,
            _FM_ARC_Y, Y, 0.0, Hc)
    gstart = creases[0] + e_full * pm / 2 - BA / 2
    gpoly = [(gstart - x, y - y0) for x, y in gl.poly]                      # (w, y): w from the bend's end
    gpoly = [(w_, y_ + y0) for w_, y_ in _clip_half([(a, b) for a, b in gpoly], (0.0, 0.0), (1.0, 0.0), 0.0)]
    _fm_slab(faces, gpoly, (Pg[0], 0.0, Pg[1]), (dgv[0], 0.0, dgv[1]), Y, (ngv[0], 0.0, ngv[1]), t, "glue", gl.role,
             [((0.0, y0), (0.0, y0 + Hc))])
    # --- flaps
    boxlo = {}
    for i, w in enumerate(walls):
        P, d, n, F = ch[i][:4]
        for fp, top, u0, u1, dy, q in notches_of[w.name]:
            sh = shift_of(i, min(fp.hinge[0][0], fp.hinge[1][0]) - sheet0[i], max(fp.hinge[0][0], fp.hinge[1][0]) - sheet0[i], q)
            th = HP * q
            sg = 1.0 if top else -1.0
            hy = max(fp.hinge[0][1], fp.hinge[1][1]) if top else min(fp.hinge[0][1], fp.hinge[1][1])
            ys = (hy - y0) - sg * BA / 2 + dy                                  # where the wall column ends
            Pf, df, nf, rho, Cf = _fm_bend2d((0.0, ys + y0), (0.0, sg), (1.0, 0.0), rn, th, K, t, BA)
            nw = (n[0], 0.0, n[1])
            O = (P[0], 0.0, P[1])
            dw = (d[0], 0.0, d[1])
            _fm_arc(faces, fp.name + ".bend", fp.role, t, (0.0, ys + y0), (0.0, sg), (1.0, 0.0), rho, th, O, nw, Y, dw,
                    u0, u1, parts=FM_FLAP_PARTS)
            poly = [(x - sheet0[i] + sh, (yy - hy) * sg - (BA / 2 if lose else 0.0)) for x, yy in fp.poly]
            poly = _clip_half(poly, (0.0, 0.0), (0.0, 1.0), 0.0)
            poly = _clip_half(_clip_half(poly, (u0, 0.0), (1.0, 0.0), 0.0), (u1, 0.0), (-1.0, 0.0), 0.0)
            ev = tuple(nw[c] * df[0] + Y[c] * df[1] for c in range(3))
            en = tuple(nw[c] * nf[0] + Y[c] * nf[1] for c in range(3))
            Of = tuple(O[c] + nw[c] * Pf[0] + Y[c] * Pf[1] for c in range(3))
            _fm_slab(faces, poly, Of, dw, ev, en, t, fp.name, fp.role, [((u0, 0.0), (u1, 0.0))])
    return faces


def fold_tray(panels, t, prog_of, lift_of=None, ri=0.0, k=None, info=None, lose=True, flute=None):
    """Thick, bent model of a tray blank (bottom, four walls, four corner flaps), built as a chain like fold_rsc:
    every wall is a flat slab joined to the bottom by a true arc strip of neutral length BA, and each corner flap
    is a slab joined to its end of the front / back wall by a vertical arc strip. Mating comes first: the left and
    right walls stand outside the front / back walls' end arcs (their ends are carried out to the outside planes
    of those walls), the corner flaps lie flat against the inside of the left / right walls, and the crease of
    each flap moves in by one board so the wall gives that board of length to the flap. Builds every tray in the
    blank (the lid and the base of the telescope box). Faces like solid_faces, or None when there is no tray.
    `lift_of` is not used: the stacking is built into the geometry."""
    by = {p.name: p for p in panels}
    pres = [n[:-6] for n in by if n.endswith("bottom") and all(n[:-6] + s in by for s in ("front", "back", "left", "right"))]
    if not pres or t <= 0:
        return None
    K = BEND_MATERIALS[BEND_DEFAULT]["k"] if k is None else k
    ri = max(0.0, ri)
    rn = ri + K * t
    BA = (math.pi / 2) * rn
    HP = math.pi / 2
    a_o = rn * (1.0 - math.pi / 4) + (1.0 - K) * t        # outside face of a 90 degree wall, beyond its crease
    clamp = lambda v: min(1.0, max(0.0, v))
    faces = _Faces()
    faces.flute = flute
    inf = info if info is not None else {}
    inf.update(ba=BA, rn=rn, a_o=a_o)
    Z3 = (0.0, 0.0, 1.0)
    for pre in pres:
        bot = by[pre + "bottom"]
        x0, x1 = min(q[0] for q in bot.poly), max(q[0] for q in bot.poly)
        y0, y1 = min(q[1] for q in bot.poly), max(q[1] for q in bot.poly)
        spec = {      # outward direction, crease coordinate along it, hinge direction, hinge range, flap names
            "front": dict(o=(0.0, -1.0), c=-y0, h=(1.0, 0.0, 0.0), r=(x0, x1), fl=("cfl", "cfr")),
            "back": dict(o=(0.0, 1.0), c=y1, h=(1.0, 0.0, 0.0), r=(x0, x1), fl=("cbl", "cbr")),
            "left": dict(o=(-1.0, 0.0), c=-x0, h=(0.0, 1.0, 0.0), r=(y0, y1), fl=()),
            "right": dict(o=(1.0, 0.0), c=x1, h=(0.0, 1.0, 0.0), r=(y0, y1), fl=()),
        }
        geo = {}
        for n, sp in spec.items():
            w = by[pre + n]
            o, c = sp["o"], sp["c"]
            q = clamp(prog_of(w, 1, 1))
            th = HP * q
            Pw, dw, nw, rho, C = _fm_bend2d((-BA / 2, 0.0), (1.0, 0.0), (0.0, 1.0), rn, th, K, t, BA)
            qf = [clamp(prog_of(by[pre + f], 1, 1)) for f in sp["fl"] if pre + f in by]
            s_sh = t * (max(qf) if qf else 0.0) * q                 # the end flaps' creases move in by this
            lo, hi = sp["r"]
            if sp["fl"]:
                lo, hi = lo + BA / 2 + s_sh, hi - BA / 2 - s_sh
            else:
                lo, hi = lo - a_o * q, hi + a_o * q                 # carried out to the front / back outside planes
            H = max(p_[0] * o[0] + p_[1] * o[1] for p_ in w.poly) - c
            geo[n] = dict(th=th, Pw=Pw, dw=dw, nw=nw, rho=rho, lo=lo, hi=hi, H=H, s=s_sh)
        # ---- bottom: the flat part between the bend zones, its joint edges split where the arcs end
        fx0, fx1, fy0, fy1 = x0 + BA / 2, x1 - BA / 2, y0 + BA / 2, y1 - BA / 2
        poly = [(fx0, fy0)] + [(v, fy0) for v in (geo["front"]["lo"], geo["front"]["hi"]) if fx0 < v < fx1]
        poly += [(fx1, fy0), (fx1, fy1)] + [(v, fy1) for v in (geo["back"]["hi"], geo["back"]["lo"]) if fx0 < v < fx1]
        poly += [(fx0, fy1)]
        sk = [((geo["front"]["lo"], fy0), (geo["front"]["hi"], fy0)), ((fx1, fy0), (fx1, fy1)),
              ((geo["back"]["hi"], fy1), (geo["back"]["lo"], fy1)), ((fx0, fy1), (fx0, fy0))]
        _fm_slab(faces, poly, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), Z3, t, bot.name, bot.role, sk)
        # ---- walls: arc strip, slab, and the corner flaps (vertical arc strip + slab)
        for n, sp in spec.items():
            w = by[pre + n]
            g = geo[n]
            o = sp["o"]
            X2, ax = (o[0], o[1], 0.0), sp["h"]
            O = (o[0] * sp["c"], o[1] * sp["c"], 0.0)
            _fm_arc(faces, w.name + ".bend", w.role, t, (-BA / 2, 0.0), (1.0, 0.0), (0.0, 1.0), g["rho"], g["th"], O,
                    X2, Z3, ax, g["lo"], g["hi"])
            ev = tuple(X2[c] * g["dw"][0] + Z3[c] * g["dw"][1] for c in range(3))
            en = tuple(X2[c] * g["nw"][0] + Z3[c] * g["nw"][1] for c in range(3))
            O3 = tuple(O[c] + X2[c] * g["Pw"][0] + Z3[c] * g["Pw"][1] for c in range(3))
            Hs = max(g["H"] - BA / 2, 1e-6)
            _fm_slab(faces, [(g["lo"], 0.0), (g["hi"], 0.0), (g["hi"], Hs), (g["lo"], Hs)], O3, ax, ev, en, t, w.name,
                     w.role, [((g["lo"], 0.0), (g["hi"], 0.0))], su="x" if sp["h"][0] else "y")
            for end, fname in enumerate(sp["fl"]):
                fp = by.get(pre + fname)
                if fp is None:
                    continue
                th = HP * clamp(prog_of(fp, 1, 1))
                d0 = (-1.0, 0.0) if end == 0 else (1.0, 0.0)
                u_edge = g["lo"] if end == 0 else g["hi"]
                Pf, df, nf, rho_f, Cf = _fm_bend2d((u_edge, 0.0), d0, (0.0, 1.0), rn, th, K, t, BA)
                _fm_arc(faces, fp.name + ".bend", fp.role, t, (u_edge, 0.0), d0, (0.0, 1.0), rho_f, th, O3, ax, en, ev,
                        0.0, Hs, parts=FM_FLAP_PARTS)
                x_nom = sp["r"][end]
                pts = []
                for p_ in fp.poly:
                    wv = (x_nom - p_[0]) if end == 0 else (p_[0] - x_nom)             # away from the crease
                    vv = p_[0] * o[0] + p_[1] * o[1] - sp["c"]                         # up the wall
                    pts.append((max(wv, 0.0), vv))                                     # flap length as drawn (from the sharp crease)
                sh = BA / 2 if lose else 0.0
                pts = _clip_half(_clip_half([(wv - sh, vv - BA / 2) for wv, vv in pts], (0.0, 0.0), (1.0, 0.0), 0.0),
                                 (0.0, 0.0), (0.0, 1.0), 0.0)
                if len(pts) < 3:
                    continue
                dfl = tuple(ax[c] * df[0] + en[c] * df[1] for c in range(3))
                enf = tuple(ax[c] * nf[0] + en[c] * nf[1] for c in range(3))
                Of = tuple(O3[c] + ax[c] * Pf[0] + en[c] * Pf[1] for c in range(3))
                _fm_slab(faces, pts, Of, dfl, ev, enf, t, fp.name, fp.role, [((0.0, 0.0), (0.0, Hs))])
    return faces


def stage_lift(panels, t):
    """lift_of for the closed box: the two longer flaps at each end are raised one board thickness (outward) so
    they rest on top of the two shorter ones instead of passing through them. Only the top / bottom flaps."""
    flaps = {}
    for p in panels:
        if p.parent and p.role == "flap" and p.name != "glue" and p.hinge:
            (ax, ay), (bx, by) = p.hinge
            flaps[p.name] = (math.hypot(bx - ax, by - ay), p)
    if not flaps:
        return None
    lens = [v[0] for v in flaps.values()]
    longest = max(lens)
    even = max(lens) - min(lens) < 1e-6                     # square footprint: pick the pair on walls p1 / p3
    mid_y = {n: (sum(q[1] for q in v[1].poly) / len(v[1].poly)) for n, v in flaps.items()}
    ys = [q[1] for p in panels if not is_insert(p) for q in p.poly]
    y_mid = (min(ys) + max(ys)) / 2
    major = {n for n, v in flaps.items() if (v[1].parent in ("p1", "p3") if even else v[0] >= longest - 1e-6)}

    def lift_of(p, prog):
        if p.name not in major:
            return None
        sgn = 1.0 if mid_y[p.name] > y_mid else -1.0      # top flaps rise, bottom flaps drop
        return (0.0, sgn * t * prog, 0.0)
    lift_of.major = major
    return lift_of


def style_sequence(style_id, panels, t, amount):
    """(prog_of, lift_of, layer) for the solid preview of any style."""
    return STYLE_BY_ID[style_id].fold_sequence(panels, t, amount)


def stage_progress(panels, stage):
    """prog_of for the drawing's three steps. flat: nothing folded. partial: the walls and the glue flap folded
    into the box shape with the top and bottom flaps still open. folded: everything closed."""
    if stage == "flat":
        return lambda p, d, m: 0.0
    if stage == "folded":
        return lambda p, d, m: 1.0
    if stage == "partial":
        return lambda p, d, m: 1.0 if (p.role == "body" or p.name == "glue") else 0.0
    raise ValueError("unknown stage " + repr(stage))


