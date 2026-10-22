# =============================================================================
# SVG artwork import (logo / info zones). SVG only, no dependencies.
# =============================================================================
import re as _re
import xml.etree.ElementTree as _ET

_UNIT_MM = {"": 25.4 / 96, "px": 25.4 / 96, "pt": 25.4 / 72, "pc": 25.4 / 6, "mm": 1.0, "cm": 10.0, "in": 25.4}
SVG_MAX_BYTES = 5_000_000
SVG_MAX_SEGS = 60000


class Artwork:
    """Imported vector art: polylines in mm, y-up, bounding box starting at (0, 0)."""

    def __init__(self, polys, name=""):
        self.name = name
        xs = [p[0] for pl, _ in polys for p in pl]
        ys = [p[1] for pl, _ in polys for p in pl]
        x0, y0 = min(xs), min(ys)
        self.polys = [([(x - x0, y - y0) for x, y in pl], closed) for pl, closed in polys]
        self.w, self.h = max(xs) - x0, max(ys) - y0

    def segs(self):
        return sum(len(pl) - 1 + (1 if c else 0) for pl, c in self.polys)


def _mat_mul(a, b):
    return (a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1],
            a[0] * b[2] + a[2] * b[3], a[1] * b[2] + a[3] * b[3],
            a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5])


def _mat_apply(m, p):
    return (m[0] * p[0] + m[2] * p[1] + m[4], m[1] * p[0] + m[3] * p[1] + m[5])


def _parse_transform(s):
    m = (1, 0, 0, 1, 0, 0)
    for name, args in _re.findall(r"(\w+)\s*\(([^)]*)\)", s or ""):
        a = [float(x) for x in _re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", args)]
        if name == "matrix" and len(a) == 6:
            t = tuple(a)
        elif name == "translate" and a:
            t = (1, 0, 0, 1, a[0], a[1] if len(a) > 1 else 0)
        elif name == "scale" and a:
            t = (a[0], 0, 0, a[1] if len(a) > 1 else a[0], 0, 0)
        elif name == "rotate" and a:
            c, sn = math.cos(math.radians(a[0])), math.sin(math.radians(a[0]))
            t = (c, sn, -sn, c, 0, 0)
            if len(a) == 3:
                t = _mat_mul(_mat_mul((1, 0, 0, 1, a[1], a[2]), t), (1, 0, 0, 1, -a[1], -a[2]))
        elif name == "skewX" and a:
            t = (1, 0, math.tan(math.radians(a[0])), 1, 0, 0)
        elif name == "skewY" and a:
            t = (1, math.tan(math.radians(a[0])), 0, 1, 0, 0)
        else:
            raise ValueError(f"Unsupported transform '{name}'.")
        m = _mat_mul(m, t)
    return m


def _length(s, default=None):
    if s is None:
        return default
    m = _re.fullmatch(r"\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([a-z%]*)\s*", s)
    if not m or m.group(2) == "%" or m.group(2) not in _UNIT_MM:
        return default
    return float(m.group(1)) * _UNIT_MM[m.group(2)]


def _bez(p0, p1, p2, p3, tol):
    d = math.dist(p0, p1) + math.dist(p1, p2) + math.dist(p2, p3)
    n = max(4, min(64, int(math.sqrt(d / tol) * 0.6) + 2))
    out = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        out.append((u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                    u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]))
    return out


def _arc_pts(p0, rx, ry, phi, fa, fs, p1, tol):
    if rx == 0 or ry == 0 or p0 == p1:
        return [p1]
    rx, ry = abs(rx), abs(ry)
    c, s = math.cos(math.radians(phi)), math.sin(math.radians(phi))
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1, y1 = c * dx + s * dy, -s * dx + c * dy
    lam = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    den = rx * rx * y1 * y1 + ry * ry * x1 * x1
    co = math.sqrt(max(0, num / den)) * (-1 if fa == fs else 1)
    cx1, cy1 = co * rx * y1 / ry, -co * ry * x1 / rx
    cx, cy = c * cx1 - s * cy1 + (p0[0] + p1[0]) / 2, s * cx1 + c * cy1 + (p0[1] + p1[1]) / 2

    def ang(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a
    th1 = ang(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    dth = ang((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not fs and dth > 0:
        dth -= 2 * math.pi
    elif fs and dth < 0:
        dth += 2 * math.pi
    r = max(rx, ry)
    n = max(6, min(180, int(abs(dth) / (2 * math.acos(max(0.0, 1 - tol / r))) ) + 1)) if r > tol else 6
    out = []
    for i in range(1, n + 1):
        t = th1 + dth * i / n
        x, y = rx * math.cos(t), ry * math.sin(t)
        out.append((c * x - s * y + cx, s * x + c * y + cy))
    out[-1] = p1
    return out


def _path_polys(d, tol):
    toks = _re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", d)
    polys, cur, i, cmd = [], None, 0, None
    pos = start = (0.0, 0.0)
    lastc = lastq = None

    def num():
        nonlocal i
        if i >= len(toks) or toks[i].isalpha():
            raise ValueError("Malformed path data.")
        v = float(toks[i]); i += 1
        return v

    def flag():
        # arc flags may be glued to the next number ("a1 1 0 01.5 2")
        nonlocal i
        t = toks[i]
        if t in ("0", "1"):
            i += 1
            return int(t)
        if t[0] in "01" and len(t) > 1:
            toks[i] = t[1:] if t[1] != "." else "0" + t[1:]
            return int(t[0])
        raise ValueError("Malformed arc flag.")

    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]; i += 1
            if cmd in "Zz":
                if cur:
                    polys.append((cur, True))
                cur, pos, lastc, lastq = None, start, None, None
                continue
        elif cmd is None:
            raise ValueError("Malformed path data.")
        rel = cmd.islower()
        C = cmd.upper()
        ox, oy = pos if rel else (0.0, 0.0)
        if C == "M":
            pos = (ox + num(), oy + num())
            if cur:
                polys.append((cur, False))
            cur, start = [pos], pos
            cmd = "l" if rel else "L"
            lastc = lastq = None
            continue
        if cur is None:
            cur = [pos]
        if C == "L":
            pos = (ox + num(), oy + num()); cur.append(pos); lastc = lastq = None
        elif C == "H":
            pos = (ox + num() if rel else num(), pos[1]); cur.append(pos); lastc = lastq = None
        elif C == "V":
            pos = (pos[0], oy + num() if rel else num()); cur.append(pos); lastc = lastq = None
        elif C == "C":
            p1 = (ox + num(), oy + num()); p2 = (ox + num(), oy + num()); p3 = (ox + num(), oy + num())
            cur += _bez(pos, p1, p2, p3, tol); pos, lastc, lastq = p3, p2, None
        elif C == "S":
            p1 = (2 * pos[0] - lastc[0], 2 * pos[1] - lastc[1]) if lastc else pos
            p2 = (ox + num(), oy + num()); p3 = (ox + num(), oy + num())
            cur += _bez(pos, p1, p2, p3, tol); pos, lastc, lastq = p3, p2, None
        elif C in "QT":
            if C == "Q":
                q = (ox + num(), oy + num())
            else:
                q = (2 * pos[0] - lastq[0], 2 * pos[1] - lastq[1]) if lastq else pos
            p3 = (ox + num(), oy + num())
            p1 = (pos[0] + 2 / 3 * (q[0] - pos[0]), pos[1] + 2 / 3 * (q[1] - pos[1]))
            p2 = (p3[0] + 2 / 3 * (q[0] - p3[0]), p3[1] + 2 / 3 * (q[1] - p3[1]))
            cur += _bez(pos, p1, p2, p3, tol); pos, lastq, lastc = p3, q, None
        elif C == "A":
            rx, ry, ph = num(), num(), num()
            fa, fs = flag(), flag()
            p3 = (ox + num(), oy + num())
            cur += _arc_pts(pos, rx, ry, ph, fa, fs, p3, tol); pos, lastc, lastq = p3, None, None
        if len(cur) > SVG_MAX_SEGS:
            raise ValueError("Artwork is too detailed (too many segments). Simplify it first.")
    if cur:
        polys.append((cur, False))
    return polys


def import_svg(path_or_text, name="", tol=0.05):
    """Parse an SVG file (path) or text into an Artwork (mm, y-up). Raises ValueError with a plain message."""
    text = path_or_text
    if "<" not in path_or_text[:2000]:
        if os.path.getsize(path_or_text) > SVG_MAX_BYTES:
            raise ValueError("SVG file is too large (limit 5 MB).")
        with open(path_or_text, "rb") as f:
            text = f.read().decode("utf-8", "replace")
        name = name or os.path.basename(path_or_text)
    if "<!ENTITY" in text:
        raise ValueError("SVG with entity declarations is not supported.")
    try:
        root = _ET.fromstring(text)
    except _ET.ParseError as e:
        raise ValueError(f"Not a valid SVG file ({e}).")
    if not root.tag.endswith("svg"):
        raise ValueError("Not an SVG file.")
    # root scale: viewBox -> real units
    vb = root.get("viewBox")
    w, h = _length(root.get("width")), _length(root.get("height"))
    base = (1, 0, 0, 1, 0, 0)
    if vb:
        v = [float(x) for x in _re.split(r"[\s,]+", vb.strip())]
        if len(v) == 4 and v[2] > 0 and v[3] > 0:
            sx = (w / v[2]) if w else _UNIT_MM[""]
            sy = (h / v[3]) if h else (sx if not w else _UNIT_MM[""])
            if w and not h:
                sy = sx
            if h and not w:
                sx = sy
            base = (sx, 0, 0, sy, -v[0] * sx, -v[1] * sy)
    else:
        base = (_UNIT_MM[""], 0, 0, _UNIT_MM[""], 0, 0)
    polys = []

    def walk(el, m):
        tag = el.tag.split("}")[-1]
        if tag in ("defs", "clipPath", "mask", "symbol", "metadata", "title", "desc", "style", "script",
                   "image", "text", "use", "foreignObject", "pattern", "marker", "linearGradient", "radialGradient"):
            if tag in ("image", "text", "use"):
                skipped.add(tag)
            return
        if el.get("display") == "none":
            return
        m = _mat_mul(m, _parse_transform(el.get("transform")))
        f = lambda k, d=0.0: float(_length(el.get(k), None) / _UNIT_MM[""] if _length(el.get(k)) is not None else d)
        raw = []
        if tag == "path" and el.get("d"):
            raw = _path_polys(el.get("d"), tol / max(1e-9, math.sqrt(abs(m[0] * m[3] - m[1] * m[2]))))
        elif tag == "rect":
            x, y, rw, rh = f("x"), f("y"), f("width"), f("height")
            rx, ry = f("rx", -1), f("ry", -1)
            rx = ry if rx < 0 and ry >= 0 else rx
            ry = rx if ry < 0 else ry
            rx, ry = max(0, min(rx, rw / 2)), max(0, min(ry, rh / 2))
            if rw > 0 and rh > 0:
                if rx > 0 and ry > 0:
                    k = f"M{x+rx} {y}H{x+rw-rx}A{rx} {ry} 0 0 1 {x+rw} {y+ry}V{y+rh-ry}A{rx} {ry} 0 0 1 {x+rw-rx} {y+rh}" \
                        f"H{x+rx}A{rx} {ry} 0 0 1 {x} {y+rh-ry}V{y+ry}A{rx} {ry} 0 0 1 {x+rx} {y}Z"
                    raw = _path_polys(k, tol)
                else:
                    raw = [([(x, y), (x + rw, y), (x + rw, y + rh), (x, y + rh)], True)]
        elif tag in ("circle", "ellipse"):
            cx, cy = f("cx"), f("cy")
            rx = f("r") if tag == "circle" else f("rx")
            ry = rx if tag == "circle" else f("ry")
            if rx > 0 and ry > 0:
                raw = _path_polys(f"M{cx+rx} {cy}A{rx} {ry} 0 1 1 {cx-rx} {cy}A{rx} {ry} 0 1 1 {cx+rx} {cy}Z", tol)
        elif tag == "line":
            raw = [([(f("x1"), f("y1")), (f("x2"), f("y2"))], False)]
        elif tag in ("polyline", "polygon"):
            n = [float(x) for x in _re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", el.get("points", ""))]
            if len(n) >= 4:
                raw = [(list(zip(n[0::2], n[1::2])), tag == "polygon")]
        for pl, closed in raw:
            pts = [_mat_apply(m, p) for p in pl]
            if len(pts) >= 2:
                polys.append((pts, closed))
        for ch in el:
            walk(ch, m)

    skipped = set()
    walk(root, base)
    if not polys:
        raise ValueError("No usable shapes found. Convert text to outlines and embedded images to paths first.")
    polys = [([(x, -y) for x, y in pl], c) for pl, c in polys]  # SVG is y-down
    art = Artwork(polys, name)
    art.skipped = sorted(skipped)
    if art.w < 1e-6 and art.h < 1e-6:
        raise ValueError("Artwork has no size.")
    return art


