#!/usr/bin/env python3
"""See-through check of the 3-D preview.   python tests/order_check.py [module.py]
Renders the folded solid the way the editor does (same projection, back-face culling and plate_order), once with the
painter's order and once with an exact per-pixel depth test, and counts pixels where the painter shows a surface that
is really behind another. Needs numpy and Pillow (skipped when they are missing)."""
import importlib.util, math, os, sys
try:
    import numpy as np
    from PIL import Image, ImageDraw
except ImportError:
    print("SKIP order_check (needs numpy and Pillow)")
    sys.exit(0)
HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(os.path.dirname(HERE), "dieline_generator.py")
_s = importlib.util.spec_from_file_location("dg", PATH)
dg = importlib.util.module_from_spec(_s)
sys.modules["dg"] = dg
_s.loader.exec_module(dg)


def build(style_id, dims=(150, 100, 60, 3), bendx=0.25, flags=None, opts=None):
    st = dg.STYLE_BY_ID[style_id]; sp = dg.default_spec(st, "mm"); sp.L, sp.W, sp.H, sp.t = dims
    sp.flags = dict(sp.flags, **(flags or {}))
    sp.opts = dict(sp.opts, **(opts or {}))
    res = dg.generate(st, sp); return st, sp, res

def faces_at(st, sp, res, amount, sharp=False):
    pf, lift, layer = dg.style_sequence(st.id, res.panels, sp.t, amount)
    bend = None if (sharp or not st.rounded_folds) else 0.25 * sp.t
    return dg.solid_faces(res.panels, sp.t, pf, lift, bend=bend, bend_k=None, bend_len=True)

def tri_n(a, b, c):
    ux, uy, uz = b[0]-a[0], b[1]-a[1], b[2]-a[2]; vx, vy, vz = c[0]-a[0], c[1]-a[1], c[2]-a[2]
    nx, ny, nz = uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx; L = math.sqrt(nx*nx+ny*ny+nz*nz) or 1
    return nx/L, ny/L, nz/L

def zcheck(st, faces, yaw, pitch, W=480, H=320, zoom=1.0, tol=2e-3, want_img=False):
    orient = (lambda q: (q[0], q[2], -q[1])) if st.view_up == "z" else (lambda q: q)
    allp = [orient(q) for f in faces for q in f[2]]
    xs, ys, zs = zip(*allp)
    c0 = ((min(xs)+max(xs))/2, (min(ys)+max(ys))/2, (min(zs)+max(zs))/2)
    R = max(1e-6, max(math.dist(c0, q) for q in allp)); scale = min(W, H)*0.40*zoom/R
    cyw, syw, cp, sp_ = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch); dcam = 4.2*R
    conv, plates = [], {}
    for name, kind, pts, role in faces:
        sc, cam = [], []
        for q in pts:
            x, y, z = orient(q); x, y, z = x-c0[0], y-c0[1], z-c0[2]
            x1, z1 = cyw*x+syw*z, -syw*x+cyw*z; y2, z2 = cp*y-sp_*z1, sp_*y+cp*z1
            f = dcam/(dcam-z2); sc.append((W/2+x1*scale*f, H/2-y2*scale*f)); cam.append((x1, y2, z2))
        conv.append((name, kind, role, sc, cam)); plates.setdefault(name, []).append((kind, cam))
    rank = dg.plate_order(plates, (0.0, 0.0, dcam))
    out = []
    for name, kind, role, sc, cam in conv:
        a2 = sum(sc[i][0]*sc[(i+1)%len(sc)][1]-sc[(i+1)%len(sc)][0]*sc[i][1] for i in range(len(sc)))
        if a2 >= 0: continue
        out.append(((rank.get(name, 0), sum(c[2] for c in cam)/len(cam)), name, kind, sc, cam))
    out.sort(key=lambda r: r[0])
    names = sorted({o[1] for o in out}); nid = {n: i+1 for i, n in enumerate(names)}
    painter = np.zeros((H, W), np.int32); zbuf = np.full((H, W), -1e18); zid = np.zeros((H, W), np.int32)
    pz = np.full((H, W), -1e18)
    uu = (np.arange(W)[None, :]+0.5-W/2)/scale; vv = -(np.arange(H)[:, None]+0.5-H/2)/scale
    for _, name, kind, sc, cam in out:
        m = Image.new("L", (W, H), 0); ImageDraw.Draw(m).polygon(sc, fill=1); m = np.array(m, bool)
        if not m.any(): continue
        n = dg._newell(cam)
        d = n[0]*cam[0][0]+n[1]*cam[0][1]+n[2]*cam[0][2]
        a = 1.0
        # n0*u*(1-z/D)+n1*v*(1-z/D)+n2*z = d  ->  z*(n2-(n0*u+n1*v)/D) = d-(n0*u+n1*v)
        t = n[0]*uu+n[1]*vv; den = n[2]-t/dcam
        with np.errstate(divide="ignore", invalid="ignore"):
            z = (d-t)/den
        z = np.where(np.abs(den) < 1e-9, -1e18, z)
        painter[m] = nid[name]; pz[m] = z[m]
        better = m & (z > zbuf); zbuf[better] = z[better]; zid[better] = nid[name]
    cov = painter > 0
    bad = cov & (pz < zbuf - tol*R)
    pairs = {}
    ys_, xs_ = np.nonzero(bad)
    for y, x in zip(ys_, xs_):
        key = (names[painter[y, x]-1], names[zid[y, x]-1]); pairs[key] = pairs.get(key, 0)+1
    img = None
    if want_img:
        img = np.zeros((H, W, 3), np.uint8); img[cov] = (60, 60, 60); img[bad] = (255, 40, 40)
    return int(bad.sum()), int(cov.sum()), pairs, img


# (label, style, dims, flags): views (of the grid below) allowed to show a real mismatch
CASES = [("rsc", "rsc", (150, 100, 60, 3), None, None, 2), ("telescope", "telescope", (150, 100, 60, 3), None, None, 1),
         ("insert", "insert", (150, 150, 100, 3), None, None, 0),
         ("rsc+insert", "rsc", (150, 150, 100, 3), {"insert": True}, None, 2),
         ("insert 240x160", "insert", (240, 160, 100, 3), None, None, 0),
         ("rsc+insert 160x240", "rsc", (160, 240, 100, 3), {"insert": True}, None, 2),
         ("rsc+insert 240x110", "rsc", (240, 110, 100, 3), {"insert": True}, None, 2),
         ("rsc+grid 2+3", "rsc", (240, 160, 90, 3), {"insert_grid": True}, {"gnl": 2, "gnw": 3}, 2),
         ("fit", "fit", (30, 30, 15, 3), None, None, 0),
         ("grid 1+1", "grid", (200, 150, 120, 3), None, None, 0),
         ("grid 2+3", "grid", (240, 160, 90, 3), None, {"nl": 2, "nw": 3}, 0)]
base = lambda n: n.split(".")[0].split("~")[0]      # a bent or cut-up part counts as its panel
bad_styles = []
for sid, style, dims, flags, opts, limit in CASES:
    st, sp, res = build(style, dims, flags=flags, opts=opts)
    bad = views = 0
    for amt in (0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0):
        fc = faces_at(st, sp, res, amt)
        for yaw in (-2.4, -1.6, -0.62, 1.2):
            for pit in (0.25, 0.7, -0.4):
                _, _, pr, _ = zcheck(st, fc, yaw, pit, tol=4e-3)
                views += 1
                if any(v >= 120 and base(k[0]) != base(k[1]) for k, v in pr.items()):
                    bad += 1
    ok = bad <= limit
    print(("PASS " if ok else "FAIL ") + f"{sid}: {bad}/{views} views with a see-through error (limit {limit})")
    if not ok:
        bad_styles.append(sid)
sys.exit(1 if bad_styles else 0)
