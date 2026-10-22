# =============================================================================
# Chain fold model for the insert: flat slabs joined by true arc strips (see fold_rsc)
# =============================================================================
INS_MIN_TURN = 0.02          # radians: a fold that has barely started is drawn as a 1 degree bend, never a huge radius


def _ins_bend(P, d, n, theta, K, t, bn):
    """Turn the outside-face point P (tangent d, board side n) through `theta` while the arc keeps the neutral length
    `bn` (a longer arc for a smaller turn). Returns (P', d', n', outer radius, the turn actually used)."""
    th = max(theta, INS_MIN_TURN)
    R = bn / th
    rho = R + (1.0 - K) * t
    c, s = math.cos(th), math.sin(th)
    C = (P[0] + n[0] * rho, P[1] + n[1] * rho)
    d2 = (c * d[0] + s * n[0], c * d[1] + s * n[1])
    n2 = (c * n[0] - s * d[0], c * n[1] - s * d[1])
    return (C[0] - n2[0] * rho, C[1] - n2[1] * rho), d2, n2, rho, th


def _ins_plan(m, q, t, ri, K, pA, pC, turn=None):
    """Plan view (X along the wall, Z out from it, board on the +Z side) of the folded strip: the wall panel centred on
    X = 0 with its outside face on Z = 0, and for each blade the start of its arc, the arc, and where its flat part starts."""
    turn = INS_TURN if turn is None else turn
    rn = ri + K * t
    bn = turn * rn
    b = m - bn
    lam = q - bn / 2.0
    out = dict(bn=bn, b=b, lam=lam)
    for key, P, d, p in (("A", (-b / 2.0, 0.0), (-1.0, 0.0), pA), ("C", (b / 2.0, 0.0), (1.0, 0.0), pC)):
        P2, d2, n2, rho, th = _ins_bend(P, d, (0.0, 1.0), turn * p, K, t, bn)
        out[key] = dict(P=P, d=d, P2=P2, d2=d2, n2=n2, rho=rho, th=th)
    return out


def _ins_pieces(meta, bn, lam, flip):
    """The convex pieces of one blade's flat part, in (u along the blade from the arc, v up) with the joints between
    them: [(name suffix, polygon, [joint segments])]. The blade is cut at its slot into three plates so each plate is
    convex enough for the draw-order sort. `flip` mirrors it top to bottom (the second blade's slot is cut from the
    bottom)."""
    Hs = meta["Hs"]
    h = max(0.0, meta["relief"] / 2.0 - bn / 2.0)          # how far the slit reaches past the end of the bend
    d, sw = Hs / 2.0, meta["slot"]
    uc = meta["slot_from_crease"] - bn / 2.0
    uL, uR = uc - sw / 2.0, uc + sw / 2.0
    r0, r1, vf = Hs / 4.0, 3.0 * Hs / 4.0, Hs - d
    P = [("0", [(0, 0), (uL, 0), (uL, vf), (uL, Hs), (0, Hs), (0, r1), (h, r1), (h, r0), (0, r0)],
          [((0, 0), (0, r0)), ((0, r1), (0, Hs)), ((uL, 0), (uL, vf))]),
         ("1", [(uL, 0), (uR, 0), (uR, vf), (uL, vf)], [((uL, 0), (uL, vf)), ((uR, 0), (uR, vf))]),
         ("2", [(uR, 0), (lam, 0), (lam, Hs), (uR, Hs), (uR, vf)], [((uR, 0), (uR, vf))])]
    if not flip:
        return P
    fl = lambda p: (p[0], Hs - p[1])
    return [(n, [fl(p) for p in poly], [(fl(a), fl(b)) for a, b in js]) for n, poly, js in P]


def _clip_u(poly, lim, below):
    """The part of the convex polygon `poly` (u, v) with u <= lim (`below`) or u >= lim."""
    sg = 1.0 if below else -1.0
    out = []
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        ia, ib = sg * (a[0] - lim) <= 1e-12, sg * (b[0] - lim) <= 1e-12
        if ia:
            out.append(a)
        if ia != ib:
            f = (lim - a[0]) / (b[0] - a[0])
            out.append((lim, a[1] + f * (b[1] - a[1])))
    return out


def _clip_band(poly, ua, ub):
    """The parts of the convex polygon `poly` (u, v) outside the band ua < u < ub: a list of 0, 1 or 2 convex polygons."""
    out = []
    for part in (_clip_u(poly, ua, True), _clip_u(poly, ub, False)):
        if len(part) >= 3 and abs(sum(part[i][0] * part[(i + 1) % len(part)][1] - part[(i + 1) % len(part)][0] * part[i][1]
                                      for i in range(len(part)))) > 1e-9:
            out.append(part)
    return out


def _ins_band(OA, euA, enA, OC, euC, enC, t, lamC, slotA, slotC, sw):
    """The stretch (ua, ub) of blade A (outside-face origin OA, direction euA, board side enA, all in the horizontal
    plane as (x, z)) that lies inside the board of blade C, provided the two cross on C's flat part; else None. Cutting
    that stretch out of A (and the matching one out of C) leaves plates that do not overlap, which the draw-order sort
    can then place exactly."""
    n = (enC[0], enC[2])
    a0 = n[0] * (OA[0] - OC[0]) + n[1] * (OA[2] - OC[2])
    beta = n[0] * euA[0] + n[1] * euA[2]
    gamma = n[0] * enA[0] + n[1] * enA[2]
    if abs(beta) < 1e-6:
        return None
    lo_h, hi_h = min(0.0, gamma * t), max(0.0, gamma * t)
    u1, u2 = (-a0 - hi_h) / beta, (t - a0 - lo_h) / beta
    ua, ub = min(u1, u2), max(u1, u2)
    um = (ua + ub) / 2.0
    X = (OA[0] + um * euA[0] + 0.5 * t * enA[0], OA[2] + um * euA[2] + 0.5 * t * enA[2])
    uc = (X[0] - OC[0]) * euC[0] + (X[1] - OC[2]) * euC[2]
    if uc < -t or uc > lamC + t:
        return None
    if abs(um - slotA) <= sw / 2.0 and abs(uc - slotC) <= sw / 2.0:   # the crossing sits in both slots: they interlock
        return None
    return ua - 1e-6, ub + 1e-6


def insert_footprint(panels, t, ri=None, k=None):
    """(half the depth Z of the folded insert) from its plan view at full fold: used to centre it in a box."""
    by = {p.name: p for p in panels}
    mt = by["ib"].meta
    nr, nk = insert_nominal_bend(t)
    ri = nr if ri is None else max(0.0, ri)
    K = nk if k is None else k
    pl = _ins_plan(mt["m"], mt["q"], t, ri, K, 1.0, 1.0, mt.get("turn"))
    zs = []
    for key in "AC":
        e = pl[key]
        tip = (e["P2"][0] + e["d2"][0] * pl["lam"], e["P2"][1] + e["d2"][1] * pl["lam"])
        zs += [tip[1], tip[1] + t * e["n2"][1]]
    return max(zs)


def fold_insert(panels, t, prog_of, lift_of=None, ri=None, k=None, info=None, lose=True, flute=None,
                origin=(0.0, 0.0, 0.0)):
    """Thick, bent model of the insert strip: the wall panel is a flat slab on the wall, each of the two folds a true
    arc strip (two of them, one for each hinge quarter; the slit between them is open), and each blade three flat plates
    cut at its slot. `origin` moves the whole model (the wall panel's outside face centre at its base). Faces
    [(panel, kind, [3-D points], role)] like solid_faces, or None when the panels are not an insert strip."""
    by = {p.name: p for p in panels}
    if any(n not in by for n in INS_NAMES) or t <= 0 or by["ib"].meta is None:
        return None
    mt = by["ib"].meta
    nr, nk = insert_nominal_bend(t)
    K = nk if k is None else k
    ri = nr if ri is None else max(0.0, ri)
    Hs = mt["Hs"]
    clamp = lambda v: min(1.0, max(0.0, v))
    pA, pC = clamp(prog_of(by["ia"], 1, 1)), clamp(prog_of(by["ic"], 1, 1))
    pl = _ins_plan(mt["m"], mt["q"], t, ri, K, pA, pC, mt.get("turn"))
    bn, b, lam = pl["bn"], pl["b"], pl["lam"]
    ox, oy, oz = origin
    Y = (0.0, 1.0, 0.0)
    faces = _Faces()
    faces.flute = flute
    h = max(0.0, mt["relief"] / 2.0 - bn / 2.0)
    r0, r1 = Hs / 4.0, 3.0 * Hs / 4.0
    # --- wall panel
    B = [(0, 0), (b, 0), (b, r0), (b - h, r0), (b - h, r1), (b, r1), (b, Hs), (0, Hs), (0, r1), (h, r1), (h, r0), (0, r0)]
    joints = [((0, 0), (0, r0)), ((0, r1), (0, Hs)), ((b, 0), (b, r0)), ((b, r1), (b, Hs))]
    _fm_slab(faces, B, (-b / 2.0 + ox, oy, oz), (1.0, 0.0, 0.0), Y, (0.0, 0.0, 1.0), t, "ib", "body", joints)
    # --- the two folds and blades
    place = {}
    for key, name, flip in (("A", "ia", False), ("C", "ic", True)):
        e = pl[key]
        P2, d2, n2 = e["P2"], e["d2"], e["n2"]
        place[name] = (flip, (P2[0] + ox, oy, P2[1] + oz), (d2[0], 0.0, d2[1]), (n2[0], 0.0, n2[1]))
    sl = mt["slot_from_crease"] - bn / 2.0                          # slot centre along a blade's flat part
    for key, name, flip in (("A", "ia", False), ("C", "ic", True)):
        e = pl[key]
        P, d = e["P"], e["d"]
        for j, (a0, a1) in enumerate(((0.0, r0), (r1, Hs))):          # the hinge quarters; the slit between is open
            _fm_arc(faces, f"{name}~t{j}.bend", "body", t, P, d, (0.0, 1.0), e["rho"], e["th"], (ox, oy, oz),
                    (1.0, 0.0, 0.0), (0.0, 0.0, 1.0), Y, a0, a1)
        _, O, eu, en = place[name]
        oname = "ic" if name == "ia" else "ia"
        _, O2, eu2, en2 = place[oname]
        band = _ins_band(O, eu, en, O2, eu2, en2, t, lam, sl, sl, mt["slot"])   # where the other blade passes through this one
        for suffix, poly, js in _ins_pieces(mt, bn, lam, flip):
            parts = _clip_band(poly, *band) if band else [poly]
            for k_, part in enumerate(parts):
                _fm_slab(faces, part, O, eu, Y, en, t, f"{name}~{suffix}{'ab'[k_] if band else ''}", "body", js)
    if info is not None:
        info.update(bn=bn, b=b, lam=lam)
    return faces
