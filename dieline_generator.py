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
import datetime
import math
import os
import sys
from types import SimpleNamespace

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
# App support: version, per-user folder, error log, saved settings, console set-up, app icon
# =============================================================================
import json
import time
import traceback

__version__ = "0.2.6"
APP_NAME = "BoxForge"


def user_dir():
    """Folder for the log and the saved settings (BOXFORGE_HOME overrides it, which the tests use)."""
    env = os.environ.get("BOXFORGE_HOME")
    if env:
        return env
    if sys.platform == "win32":
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP_NAME)
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~/Library/Application Support"), APP_NAME)
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), APP_NAME.lower())


def log_path():
    return os.path.join(user_dir(), "boxforge.log")


def settings_path():
    return os.path.join(user_dir(), "settings.json")


def log_error(text):
    """Append an error report to the log file. Never raises: a problem writing the log must not hide the real one."""
    try:
        os.makedirs(user_dir(), exist_ok=True)
        p = log_path()
        if os.path.exists(p) and os.path.getsize(p) > 200000:           # keep the file small: drop the older half
            with open(p, "rb") as fh:
                tail = fh.read()[-100000:]
            with open(p, "wb") as fh:
                fh.write(tail)
        with open(p, "a", encoding="utf-8", errors="replace") as fh:
            fh.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')}  {APP_NAME} {__version__}  "
                     f"Python {sys.version.split()[0]}  {sys.platform}\n{text.rstrip()}\n\n")
        return True
    except OSError:
        return False


# ------------------------------------------------------------------ saved settings ----
def _same_kind(default, v):
    if isinstance(default, bool):
        return isinstance(v, bool)
    if isinstance(default, (int, float)):
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    return isinstance(default, str) and isinstance(v, str)


def _merge_known(defaults, loaded):
    """defaults updated with the entries of `loaded` that have a known key and the right kind of value."""
    out = dict(defaults)
    if isinstance(loaded, dict):
        for k, d in defaults.items():
            if k in loaded and _same_kind(d, loaded[k]):
                out[k] = float(loaded[k]) if isinstance(d, float) else loaded[k]
    return out


_SNAP_CHOICES = {"units": ("mm", "in"), "mode": ("inner", "outer", "manufacturer"), "flute": ("off", "v", "h"),
                 "view": ("dieline", "split", "fold3d")}


def clean_snapshot(d):
    """One style's saved editor values, with anything odd dropped (so a damaged file can never break the editor)."""
    out = {}
    if not isinstance(d, dict):
        return out
    for k, v in d.items():
        if not isinstance(k, str) or len(k) > 40 or not isinstance(v, (str, bool)) or (isinstance(v, str) and len(v) > 80):
            continue
        if k in _SNAP_CHOICES and v not in _SNAP_CHOICES[k]:
            continue
        out[k] = v
    return out


def load_settings():
    """The saved settings as a dict ({} when there is no usable file)."""
    try:
        with open(settings_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data):
    try:
        os.makedirs(user_dir(), exist_ok=True)
        tmp = settings_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
        os.replace(tmp, settings_path())
        return True
    except (OSError, TypeError, ValueError):
        return False


# ------------------------------------------------------------------ project files ----
PROJECT_EXT = ".boxforge"
RECENT_MAX = 8
PROJECT_FORMAT = 1
_MAX_PROJECT_BYTES = 20_000_000


def _num(v, lo=-1e9, hi=1e9):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and lo <= v <= hi


def project_to_text(style_id, state):
    """One editor's whole state (sizes, options, windows and zones with their artwork) as the text of a project file."""
    feats = []
    for kd, cx, cy, w, h, r, art, ol, rot in state["feats"]:
        f = dict(kind=kd, cx=cx, cy=cy, w=w, h=h, r=r, outline=bool(ol), rot=rot)
        if art is not None:
            f["art"] = dict(name=art.name, polys=[[[list(q) for q in pl], bool(c)] for pl, c in art.polys])
        feats.append(f)
    data = dict(app=APP_NAME, format=PROJECT_FORMAT, version=__version__, style=style_id,
                vars=state["vars"], units=state["units"], mode=state["mode"], folds=state["folds"], perf=state["perf"],
                flute=state["flute"], flags=state["flags"], look=state["look"], dash=state["dash"], features=feats)
    return json.dumps(data, indent=1)


def _clean_feature(d):
    if not isinstance(d, dict) or d.get("kind") not in FEATURE_KINDS:
        return None
    if not all(_num(d.get(k)) for k in ("cx", "cy", "w", "h")) or d["w"] <= 0 or d["h"] <= 0:
        return None
    r = d.get("r", 0.0)
    art = None
    a = d.get("art")
    if isinstance(a, dict) and isinstance(a.get("polys"), list) and 0 < len(a["polys"]) <= 5000:
        polys = []
        for item in a["polys"]:
            try:
                pl, closed = item
                pts = [(float(q[0]), float(q[1])) for q in pl]
            except (TypeError, ValueError, IndexError):
                polys = None
                break
            if len(pts) < 2 or len(pts) > 20000 or not all(_num(c) for q in pts for c in q):
                polys = None
                break
            polys.append((pts, bool(closed)))
        if polys:
            art = Artwork(polys, str(a.get("name", ""))[:80])
    rot = d.get("rot", 0)
    return (d["kind"], float(d["cx"]), float(d["cy"]), float(d["w"]), float(d["h"]), float(r) if _num(r) else 0.0, art,
            bool(d.get("outline", d["kind"] == "info")), 90 if rot == 90 else 0)


def project_from_text(text):
    """Parse a project file: (style_id, state-overlay dict) or raises ValueError with a message for the person.
    Anything unknown or oddly typed is dropped, so a hand-edited or damaged file cannot break the editor."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"This is not a BoxForge project file ({exc}).") from None
    if not isinstance(data, dict) or data.get("app") != APP_NAME or "style" not in data:
        raise ValueError("This is not a BoxForge project file.")
    fmt = data.get("format")
    if not isinstance(fmt, int) or fmt > PROJECT_FORMAT:
        raise ValueError("This project was saved by a newer version of BoxForge. Update BoxForge to open it.")
    sid = data["style"]
    if sid not in STYLE_BY_ID:
        raise ValueError(f"This project uses a box style ('{sid}') that this version does not have.")
    st = {}
    vs = clean_snapshot(data.get("vars"))
    st["vars"] = {k: v for k, v in vs.items() if isinstance(v, str)}
    for key, ok in (("units", ("mm", "in")), ("mode", ("inner", "outer", "manufacturer")), ("flute", ("off", "v", "h"))):
        if data.get(key) in ok:
            st[key] = data[key]
    for key in ("folds", "perf"):
        if isinstance(data.get(key), bool):
            st[key] = data[key]
    for key in ("flags", "dash", "look"):
        d = data.get(key)
        st[key] = {k: v for k, v in d.items() if isinstance(k, str) and len(k) < 40 and (
            isinstance(v, (bool, str)) or _num(v))} if isinstance(d, dict) else {}
    feats = [_clean_feature(f) for f in data.get("features", [])[:200]] if isinstance(data.get("features"), list) else []
    st["feats"] = [f for f in feats if f is not None]
    return sid, st


def read_project(path):
    try:
        if os.path.getsize(path) > _MAX_PROJECT_BYTES:
            raise ValueError("This file is too big to be a BoxForge project.")
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise ValueError(f"Could not read the file: {exc.strerror or exc}.") from None
    except UnicodeDecodeError:
        raise ValueError("This is not a BoxForge project file.") from None
    return project_from_text(text)


def write_project(path, style_id, state):
    """Write a project file (to a temporary name first, so a failed save never leaves half a file)."""
    text = project_to_text(style_id, state)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise ValueError(f"Could not save the file: {exc.strerror or exc}.") from None


# ------------------------------------------------------------------ console and screen ----
def safe_streams():
    """A windowed program has no console: sys.stdout / sys.stderr are None and a print() could fail. Give them
    somewhere harmless to go, and make a console that cannot show a character print a '?' instead of failing."""
    for name in ("stdout", "stderr"):
        s = getattr(sys, name)
        if s is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
        else:
            try:
                s.reconfigure(errors="replace")
            except (AttributeError, ValueError, OSError):
                pass


def attach_console():
    """Command-line use of a windowed Windows program: write to the console it was started from, if there is one."""
    if sys.platform == "win32" and (getattr(sys, "frozen", False) or sys.stdout is None):
        try:
            import ctypes
            if ctypes.windll.kernel32.AttachConsole(-1):                # -1 = the parent process's console
                sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
                sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace")
        except Exception:                                               # noqa: BLE001 - no console is not an error
            pass
    safe_streams()


def enable_dpi_awareness():
    """Windows: tell the system this program draws itself at the screen's real resolution, so text and drawings are
    sharp on a scaled (125-200 %) screen instead of being enlarged as a soft picture. The window sizes itself to the
    screen (init_scale). BOXFORGE_SCALE=1 (or BOXFORGE_DPI=0) keeps the old behaviour."""
    if sys.platform != "win32" or os.environ.get("BOXFORGE_DPI") == "0":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)              # the system's DPI
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:                                                   # noqa: BLE001 - never stop the program starting
        pass


# ------------------------------------------------------------------ app icon ----
_ICON_FACES = (                                    # an isometric box on a 64 x 64 grid: top, left, right
    ([(32, 3), (57, 17), (32, 31), (7, 17)], 0.38),
    ([(7, 17), (32, 31), (32, 61), (7, 46)], 0.0),
    ([(32, 31), (57, 17), (57, 46), (32, 61)], -0.32),
)


def _inside(poly, x, y):
    s = 0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        c = (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)
        if c:
            if s and (c > 0) != (s > 0):
                return False
            s = c
    return True


def icon_pixels(n=64):
    """The app icon as n rows of (r, g, b, a) tuples; the same drawing is used for the window and the .ico file."""
    base = T["accent"].lstrip("#")
    r0, g0, b0 = int(base[0:2], 16), int(base[2:4], 16), int(base[4:6], 16)

    def shade(f):
        if f >= 0:
            return tuple(int(c + (255 - c) * f) for c in (r0, g0, b0))
        return tuple(int(c * (1 + f)) for c in (r0, g0, b0))
    cols = [shade(f) for _, f in _ICON_FACES]
    k, ss = 64.0 / n, 3
    rows = []
    for py in range(n):
        row = []
        for px in range(n):
            hit, tot = [0, 0, 0], 0
            for sy in range(ss):
                for sx in range(ss):
                    x, y = (px + (sx + 0.5) / ss) * k, (py + (sy + 0.5) / ss) * k
                    for i, (poly, _) in enumerate(_ICON_FACES):
                        if _inside(poly, x, y):
                            hit[i] += 1
                            tot += 1
                            break
            if tot * 2 < ss * ss:
                row.append((0, 0, 0, 0))
            else:
                c = cols[max(range(3), key=lambda i: hit[i])]
                row.append((c[0], c[1], c[2], 255))
        rows.append(row)
    return rows


def icon_photo(master, n=64):
    img = tk.PhotoImage(master=master, width=n, height=n)
    rows = icon_pixels(n)
    img.put(" ".join("{" + " ".join("#%02x%02x%02x" % px[:3] for px in row) + "}" for row in rows))
    for y, row in enumerate(rows):
        for x, px in enumerate(row):
            if px[3] == 0:
                img.transparency_set(x, y, True)
    return img
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
                 sheet=(None, None), kerf=0.0, perf=False, look=None, features=(), perf_dash=5.0, perf_tie=2.0, tol=None):
        self.material, self.bend_r, self.bend_k = BEND_DEFAULT, None, None   # bend model: preset, inside radius (user units), K
        self.tol = tol or {}      # drawing tolerance overrides in mm, e.g. {"panel": 1.0}; missing = automatic
        self.perf_dash, self.perf_tie = perf_dash, perf_tie   # dashed-fold cut length and uncut bridge, in mm
        self.features = list(features)   # Feature objects (windows, info / logo zones)
        self.look = look          # {cut_color, fold_color, cut_weight, fold_weight}; None = defaults
        self.flute = None        # corrugated flute direction on the flat sheet: "v" (along the sheet's y axis), "h" (x) or None
        self.perf = perf         # draw fold lines as dashed cuts (perforation) instead of scored lines
        self.kerf = kerf         # laser beam width in the user's units; 0 = no compensation
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
        self.look = None
        self.nominal = None
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
# Styles: base class, registry
# =============================================================================
class Style:
    id = name = code = blurb = ""
    status = "standard"            # calibrated | standard | experimental
    defaults = dict(L=150.0, W=100.0, H=120.0, t=2.0)
    options = []                   # [(key, label)]  blank = automatic
    toggles = []                   # [(key, label, default)]
    count_keys = ()                # keys of `options` that are whole numbers (a number of parts), shown with the sizes, 0 allowed
    ratio_dims = ("L", "W", "H")
    flat_parts = False             # no folds at all: the bend-data page is left out
    square = False                 # only a square footprint: the window ties Width to Length
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
    def crease_for(self, spec):
        """Crease-to-crease sizes for a whole job; styles whose sizes depend on an option override this."""
        return self.crease(spec.L, spec.W, spec.H, spec.t, spec.mode)

    def inner_for(self, spec, Lc, Wc, Hc):
        return self.inner(Lc, Wc, Hc, spec.t)

    def inner(self, Lc, Wc, Hc, t):
        return Lc - t, Wc - t, Hc - t

    def resolve(self, c):
        return {}

    def check(self, c, r, issues):
        pass

    def build(self, c, r):
        raise NotImplementedError
    # --- hooks the 3-D preview, the drawing sheet and the window read; override them in a new style ---------------
    rounded_folds = False          # has a chain model for the rounded-fold preview (see fold_rsc / fold_tray)
    tol_keys = ("panel", "flap", "overall_len", "overall_h", "box")   # drawing tolerances this style uses
    draw_sub = ""                  # drawing sheet sub-title (falls back to `code`)
    draw_cap = ""                  # tag in the drawing sheet caption
    step_text = {}                 # fold-steps captions by stage: flat / partial / folded
    step_amount = None             # slider position of the "partly folded" step (None = SEQ_WALLS)
    anchor_panel = None            # the solid preview needs this panel to exist (None = no requirement)
    closing_report = False         # the bend page also reports how the chain model closes (slotted box)

    def dim_field(self, dm, res, spec):
        """Which sidebar box a dimension record `dm` (see dimensions) controls, as (key, value now) so that the dimension
        can be edited on the drawing: typing a new value changes the box by the same amount. `value now` is None for L, W,
        H and t (their current box text is used). None = the dimension is not a single box (a sum or a derived size)."""
        return None

    _PANEL_NAMES = {"p": "WALL ", "glue": "GLUE FLAP", "top": "TOP FLAP ", "bot": "BOTTOM FLAP ", "ib": "INSERT BLADE 1",
                    "ia": "INSERT WALL", "ic": "INSERT BLADE 2", "gl": "DIVIDER ALONG ", "gw": "DIVIDER ACROSS ",
                    "key": "KEY PLATE", "s": "SLOT PLATE "}

    def panel_label(self, name):
        """Short readable name of the panel `name`, for the labels on the dieline."""
        pre = ""
        if name[:2] in ("b_", "l_"):                       # lid & base: two trays on one sheet
            pre, name = ("BASE " if name[0] == "b" else "LID "), name[2:]
            names = {"bottom": "FLOOR" if pre == "BASE " else "TOP", "front": "FRONT WALL", "back": "BACK WALL",
                     "left": "LEFT WALL", "right": "RIGHT WALL", "cfl": "CORNER FLAP", "cfr": "CORNER FLAP",
                     "cbl": "CORNER FLAP", "cbr": "CORNER FLAP"}
            return pre + names.get(name, name.upper())
        for stem in ("glue", "key", "top", "bot", "ib", "ia", "ic", "gl", "gw", "p", "s"):
            if name.startswith(stem) and (name == stem or name[len(stem):].isdigit()):
                return self._PANEL_NAMES[stem] + name[len(stem):]
        return name.upper().replace("_", " ")

    def dimensions(self, res, spec):
        """Dimension records for the flat-blank drawing (see rsc_dimensions for the record format)."""
        raise NotImplementedError

    def size_rows(self, c):
        """Rows [(label, value)] of the drawing's size table. `c` carries Li/Wi/Hi (inside), Lc/Wc/Hc (crease),
        t, a (resolved options), tri / tol / fnum (formatters), flat and units."""
        return [("Inside L × W × H", c.tri(c.Li, c.Wi, c.Hi) + c.tol("box")),
                ("Outside L × W × H", c.tri(c.Lc + c.t, c.Wc + c.t, c.Hc + c.t) + c.tol("box")),
                ("Crease L × W × H", c.tri(c.Lc, c.Wc, c.Hc)), c.flat,
                ("Board thickness", c.fnum(c.t, c.units)), ("Units", c.units)]

    def drawing_notes(self, res, units):
        """Extra note lines for the drawing sheet (fold order, style specifics)."""
        return []

    def option_enabled(self, key, flags):
        """False when the option `key` only matters for a switch that is off (its box is greyed out)."""
        return True

    def toggle_conflict(self, key, on):
        """Switches to turn off when switch `key` is turned on (none by default)."""
        return []

    def toggle_hint(self, key, vals):
        """None when the on/off option `key` can be used with the sizes typed so far (`vals`: parsed L, W, H, t; None
        for one that is not a number), else a short reason shown under it. The option is then left out."""
        return None

    def table_rows(self, res):
        """Rows in the drawing's size table (the sheet makes room for more than the usual nine)."""
        return 9

    def step_views(self, res):
        """The fold-steps page's views: [(stage, heading, caption)]. Stages other than flat / partial / folded need
        `stage_amount`."""
        return list(STEP_VIEWS)

    def stage_amount(self, stage):
        """Slider position (0..1) of a custom fold-steps stage, or None."""
        return None

    def toggle_view(self, key):
        """Slider position (0..1) to show when the switch `key` is turned on, or None to leave the preview alone."""
        return None

    def view_amount(self, res):
        """Slider position (0..1) the drawing's folded 3-D view is shown at; 1 = fully folded."""
        return 1.0

    def view_heading(self, res):
        """Header of the drawing's folded 3-D view (a style can change it with what is shown)."""
        return self.view_title

    view_title = "FOLDED BOX (NOT TO SCALE)"       # drawing sheet: the folded 3-D view's header
    table_title = "BOX SIZES"                       # ... and the size table's
    steps_note = ("(not to scale; board drawn at full thickness, so the closed box can read up to one board "
                  "larger than the size table)")   # fold steps page sub-title tail

    def view_caption(self, res, units):
        """Line under the folded 3-D view on the drawing sheet."""
        Li, Wi, Hi = res.info["inner"]
        return f"{_fnum(Li, units)} × {_fnum(Wi, units)} × {_fnum(Hi, units)} {units} inside"

    def bend_notes(self, rep):
        """Replacement for the first two notes on the bend data page (None = the slotted-box wording about the
        deduction its crease sizes already contain)."""
        return None

    def tol_note(self, f, units):
        """Tolerance sentence for the drawing's notes (`f` formats a tolerance key in the drawing's units); None =
        the standard slotted-box wording chosen by `tol_keys`."""
        return None

    def fold_sequence(self, panels, t, amount):
        """(prog_of, lift_of, layer) for the solid preview at slider position `amount` (0..1)."""
        raise NotImplementedError



def _auto(c, key, default):
    v = c.o.get(key)
    return default if v is None else v


def half_lap_tol(res, tv):
    """Tolerance (mm) for a half-lap slot dimension: the style's own slot tolerance on its own sheet, and a fixed
    +/-0.1 when the part rides on a slotted-box sheet, whose flap-slot rule (+/-1.5) is far too loose for a half-lap."""
    return 0.1 if res.style.id == "rsc" else tv["slot"]


STYLES = []                        # styles listed in the menu, in menu order
STYLE_BY_ID = {}                   # every registered style, listed or not


def register_style(style, listed=True):
    """Add a style to the app. It then shows up in the menu (when `listed`) and in --style on the command line."""
    STYLE_BY_ID[style.id] = style
    if listed:
        STYLES.append(style)
    return style
# =============================================================================
# Style: Slotted Box (RSC), FEFCO 0201
# =============================================================================
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
    options = [("glue", "Glue flap width"), ("slot", "Slot width"), ("flap", "Flap length"),
               ("gnl", "Cross divider: along the length"), ("gnw", "Cross divider: across the width")]
    count_keys = ("gnl", "gnw")
    toggles = [("insert", "Add a matching diagonal insert", False),
               ("insert_grid", "Add a matching cross divider", False)]
    exclusive = (("insert", "insert_grid"),)              # switches that cannot both be on
    mode_help = {
        "inner": "Inside of the box (FEFCO internal size: crease centre − 1 board; height − 2 boards).",
        "outer": "Outside of the closed box.",
        "manufacturer": "Centre-of-crease sizes straight onto the blank.",
    }

    def crease(self, L, W, H, t, mode):
        return {"inner": (L + t, W + t, H + 2 * t),
                "outer": (L - t, W - t, H - 2 * t),
                "manufacturer": (L, W, H)}[mode]

    def inner(self, Lc, Wc, Hc, t):
        return Lc - t, Wc - t, Hc - 2 * t

    def resolve(self, c):
        t, Lc, Wc = c.t, c.Lc, c.Wc
        glue = _auto(c, "glue", max(3 * t, min(c.mm_(25), 0.4 * min(Lc, Wc))))
        r = dict(glue=glue, slot=_auto(c, "slot", max(2 * t, c.mm_(1.0))), flap=_auto(c, "flap", (min(Lc, Wc) - t) / 2))
        if c.flags.get("insert") and not c.flags.get("insert_grid"):     # an insert sized from this box's inside dimensions
            r["ins"] = STYLE_BY_ID["insert"].resolve(insert_ctx(c))
            r["ins_kind"] = "diag"
        elif c.flags.get("insert_grid") and not c.flags.get("insert"):
            c2 = insert_ctx(c)
            c2.o = {k: c.o.get(k) for k in ("gnl", "gnw") if c.o.get(k) is not None}
            r["ins"] = STYLE_BY_ID["grid"].resolve(c2, keys=("gnl", "gnw"))
            r["ins_kind"] = "grid"
        return r

    def check(self, c, r, iss):
        t = c.t
        if r["slot"] >= min(c.Lc, c.Wc) * 0.5:
            iss.append(Issue("error", "Slot width is too large for the smallest panel.", ("slot",)))
        if r["glue"] < 3 * t:
            iss.append(Issue("error", f"Manufacturer's joint must be at least 3× the board thickness ({fmt(3 * t)}).",
                             ("glue", "t")))
        elif r["glue"] < c.mm_(12):
            iss.append(Issue("warn", "Manufacturer's joint is narrow (<12 mm); the glue bond may be weak.", ("glue",)))
        if r["glue"] > 0.5 * min(c.Lc, c.Wc) + 1e-9:
            iss.append(Issue("error", f"The glue flap ({fmt(r['glue'])}) is wider than half the narrowest wall "
                                      f"({fmt(min(c.Lc, c.Wc))}): it would run past the next corner and block that wall "
                                      f"from closing.", ("glue",)))
        elif r["glue"] > 0.4 * min(c.Lc, c.Wc) + 1e-9 and r["glue"] > c.mm_(40):
            iss.append(Issue("warn", "A glue flap this wide wastes board; 25-40 mm is usual.", ("glue",)))
        if c.spec.flute == "h":
            iss.append(Issue("warn", "Flutes run horizontally around the walls: the box loses much of its stacking "
                                     "strength and the flap creases run along the flutes, so they may fold off-line. "
                                     "Corrugated cartons are normally cut with the flutes vertical.", ("flute",)))
        if r["slot"] < t:
            iss.append(Issue("warn", "Slots narrower than the board thickness can make the flaps catch on each "
                                     "other when folding.", ("slot", "t")))
        if c.flags.get("insert") and c.flags.get("insert_grid"):
            iss.append(Issue("error", "Choose either the diagonal insert or the cross divider, not both.", ()))
        elif r.get("ins_kind") == "grid":
            n0 = len(iss)
            STYLE_BY_ID["grid"].check(insert_ctx(c), r["ins"], iss)
            for i in iss[n0:]:                                # the counts are called gnl / gnw here
                i.fields = tuple({"nl": "gnl", "nw": "gnw"}.get(f, f) for f in i.fields)
        elif r.get("ins"):
            tmp = []
            STYLE_BY_ID["insert"].check(insert_ctx(c), r["ins"], tmp)
            long_ = [i for i in tmp if getattr(i, "code", "") == "too_long"]
            if long_:                                     # a box that is fine without it stays exportable
                r["ins"], r["ins_kind"] = None, None
                iss.append(Issue("warn", "The diagonal insert was left out: " + long_[0].msg, ("insert",)))
                tmp = [i for i in tmp if i not in long_]
            iss.extend(tmp)
        half = (min(c.Lc, c.Wc) - t) / 2                  # half the smaller inside size: facing flaps just meet
        if r["flap"] > half + 1e-6:
            iss.append(Issue("warn", "Flaps longer than half the smaller inside size (length or width) collide in "
                                     "the middle of the box.", ("flap",)))
        elif r["flap"] < 0.9 * half:
            iss.append(Issue("warn", "Flaps shorter than ~half the smaller inside size (length or width) leave a "
                                     "gap in the closed box.", ("flap",)))

    def toggle_hint(self, key, vals):
        if key == "insert":
            L, W = vals.get("L"), vals.get("W")
            if L and W and max(L, W) > INS_MAX_RATIO * min(L, W):
                return ("A diagonal insert needs a box no longer than %g times its width: use the cross divider "
                        "instead." % INS_MAX_RATIO)
        return None

    def option_enabled(self, key, flags):
        return bool(flags.get("insert_grid")) if key in ("gnl", "gnw") else True

    def toggle_conflict(self, key, on):
        """Switches to turn off when `key` is turned on."""
        return [b if a == key else a for a, b in self.exclusive if key in (a, b)] if on else []

    def has_insert(self, res):
        ins = res.info.get("auto", {}).get("ins")
        return bool(ins) and not ins.get("bad_count") and ins.get("Hs", 1) > 0

    def insert_kind(self, res):
        return res.info.get("auto", {}).get("ins_kind")

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
        ins = r.get("ins")
        if ins:                                            # the insert strip, cut from the same sheet below the box
            gap = max(c.mm_(8), 2 * t)
            if r.get("ins_kind") == "grid":
                if not ins.get("bad_count") and ins["Hs"] > 0:
                    P += STYLE_BY_ID["grid"].box_layout(ins, Lc + Wc, -fl - gap, 2 * (Lc + Wc), max(c.mm_(5), 2 * t))[0]
            else:
                ox = (Lc + Wc) - (ins["m"] + 2 * ins["q"]) / 2
                P += insert_panels(ins, ins["Hs"], ins["slot"], ins["relief"], ox, -fl - gap - ins["Hs"])
        return P, None

    rounded_folds = True
    tol_keys = ("panel", "flap", "slot", "glue", "overall_len", "overall_h", "box")
    draw_sub = "Regular slotted container  ·  FEFCO 0201"
    draw_cap = "FEFCO 0201"
    anchor_panel = "p1"
    closing_report = True

    def dimensions(self, res, spec):
        dims = rsc_dimensions(res, spec)
        if self.has_insert(res):                           # the insert's dimensions go below it; no room for the slot dim
            dims = [d for d in dims if d.get("tag") != "slot"] + (
                STYLE_BY_ID["grid"].box_dims(res, spec) if self.insert_kind(res) == "grid" else insert_dims_below(res, spec))
        return dims

    def dim_field(self, dm, res, spec):
        tag = dm.get("tag", "")
        key = {"glue": "glue", "slot": "slot", "flap_top": "flap", "flap_bot": "flap", "panel1": "L", "panel3": "L",
               "panel2": "W", "panel4": "W", "panel_h": "H"}.get(tag)
        if tag == "height":                                # the insert's / dividers' height follows the box height
            return "H", None
        if tag == "slot_depth":                            # half of that height
            return "H", None, 2.0
        if tag.startswith("div_gl"):
            return "L", None
        if tag.startswith("div_gw"):
            return "W", None
        if key is None or (tag == "slot" and self.has_insert(res)):
            return None
        return key, (None if key in ("L", "W", "H") else dm["v"])

    def size_rows(self, c):
        rows = [("Inside L × W × H", c.tri(c.Li, c.Wi, c.Hi) + c.tol("box")),
                ("Outside L × W × H", c.tri(c.Lc + c.t, c.Wc + c.t, c.Hc + 2 * c.t) + c.tol("box")),
                ("Crease L × W × H", c.tri(c.Lc, c.Wc, c.Hc)), c.flat,
                ("Board thickness", c.fnum(c.t, c.units)),
                ("Glue flap", c.fnum(c.a["glue"], c.units) + c.tol("glue")),
                ("Slot width", c.fnum(c.a["slot"], c.units) + c.tol("slot")),
                ("Flap length", c.fnum(c.a["flap"], c.units) + c.tol("flap"))]
        ins = c.a.get("ins")
        if ins and c.a.get("ins_kind") == "grid":
            if not ins.get("bad_count"):
                rows += STYLE_BY_ID["grid"].in_box_rows(c, ins)
        elif ins:
            rows += [("Insert blade / wall / blade", c.tri(ins["q"], ins["m"], ins["q"])),
                     ("Insert fits L × W × H", insert_fit_tri(c, ins))]
        if ins and not ins.get("bad_count"):
            rows.append(("Divider slot width (cut)" if c.a.get("ins_kind") == "grid"
                         else "Insert slot width (cut)", c.fnum(ins["slot"] * ins.get("kslot", 1.0), c.units) + c.tol_mm(0.1)))
        return rows + [("Units", c.units)]

    def table_rows(self, res):
        return 12 if self.has_insert(res) else 9

    def toggle_view(self, key):
        return SEQ_INS_DROP if key in ("insert", "insert_grid") else None         # insert down in the open box, flaps still open

    def view_heading(self, res):
        if self.has_insert(res):                           # shown before the flaps close, so the insert can be seen
            return ("BOX WITH DIVIDERS  -  FLAPS OPEN (NOT TO SCALE)" if self.insert_kind(res) == "grid"
                    else "BOX WITH INSERT  -  FLAPS OPEN (NOT TO SCALE)")
        return self.view_title

    def view_amount(self, res):
        return SEQ_INS_DROP if self.has_insert(res) else 1.0   # insert down in the open box: the insert shows inside

    def drawing_notes(self, res, units):
        notes = [f"Slots (6 off) {_fnum(res.info['auto']['slot'], units)} wide, cut through."]
        if self.has_insert(res):
            notes.append("The slot tolerance in note 2 applies to these flap slots only; the insert / divider half-lap slots "
                         "are held to the tighter tolerance in the size table (Insert slot width).")
        if self.insert_kind(res) == "grid":
            notes.append(STYLE_BY_ID["grid"].box_note())
        elif self.has_insert(res):
            notes.append("Insert (cut from the same sheet, below the box): fold both creases away from the printed side "
                         "to the fold angle, slide the two blades together at their slots (one cut from the top, one from the "
                         "bottom) and stand it in the box with the wall panel against one wall, before the top flaps "
                         "are closed. The fold slits stay cut through; the top and bottom quarters of each crease are "
                         "the hinges.")
        return notes

    def fold_sequence(self, panels, t, amount):
        return rsc_sequence(panels, t, amount)

    def step_views(self, res):
        if not self.has_insert(res):
            return list(STEP_VIEWS)
        return [STEP_VIEWS[0],
                ("above",) + (("STEP 2  -  DIVIDERS ASSEMBLED", STYLE_BY_ID["grid"].step_heads[1]) if self.insert_kind(res) == "grid" else
                              ("STEP 2  -  INSERT FOLDED", "Walls and glue flap folded; the insert folded into its X, above the box.")),
                ("down", "STEP 3  -  " + ("DIVIDERS IN THE BOX" if self.insert_kind(res) == "grid" else "INSERT IN THE BOX"),
                 "The " + ("dividers" if self.insert_kind(res) == "grid" else "insert") + " lowered into the open box; flaps still open."),
                ("folded", "STEP 4  -  FULLY FOLDED", STEP_VIEWS[2][2])]

    def stage_amount(self, stage):
        return {"above": SEQ_INS_FOLD, "down": SEQ_INS_DROP}.get(stage)


SEQ_WALLS, SEQ_MINOR = 0.50, 0.75      # slider fraction where the walls are done / the shorter flaps are done
# With an insert the walls AND the insert's folds take the first stretch together (the insert folds into its X over
# the box while the glue flap is being attached), then the insert goes down into the box, then the flaps close.
SEQ_INS_FOLD, SEQ_INS_DROP, SEQ_INS_MINOR = 0.34, 0.58, 0.79


def rsc_sequence(panels, t, amount):
    """Fold order of a real slotted box for slider position `amount` (0..1): all four walls and the glue flap
    together, then the two shorter flaps (facing each other) at the same time, then the two longer flaps together.
    With an insert strip on the sheet: walls, glue flap and the insert's folds together (the insert hovering above the
    open box), then the insert lowered into the box, then the flaps as before. The insert's height above its final
    place is `prog_of.insert_hover` (1 = hovering, 0 = in place).
    Returns (prog_of, lift_of, layer) for panel_transforms / solid_faces / iso_solid_polys (layer None while the
    flaps are still open, since sorting by depth is then enough)."""
    lift = stage_lift(panels, t)
    major = lift.major if lift else set()
    clamp = lambda v: min(1.0, max(0.0, v))
    has_ins = any(is_insert(p) for p in panels)
    a_w, a_d, a_m = (SEQ_INS_FOLD, SEQ_INS_DROP, SEQ_INS_MINOR) if has_ins else (SEQ_WALLS, SEQ_WALLS, SEQ_MINOR)

    def prog_of(p, d, m):
        if p.role == "body" or p.name == "glue" or is_insert(p):
            return clamp(amount / a_w)
        if p.name in major:
            return clamp((amount - a_m) / (1.0 - a_m))
        return clamp((amount - a_d) / (a_m - a_d))
    prog_of.insert_hover = (1.0 - clamp((amount - a_w) / (a_d - a_w))) if has_ins else 0.0
    layer = None
    if amount > a_d and lift:
        layer = {pn.name: ((0.5 if pn.name in major else 0) if pn.name.startswith("bot") else
                           (3 if pn.name in major else 2) if pn.name.startswith("top") else 1) for pn in panels}
    return prog_of, lift, layer


def rsc_dimensions(res, spec):
    """Dimension list for the RSC flat blank, in user units. kind 'h' / 'v'; row 1 / 2 = distance from the
    blank (row -1 = below it); a, b = the two measured positions; ref = where the extension lines start."""
    pn = {p.name: p for p in res.panels}
    tv = res.info["tol"]["values"]
    glue, p1, p2, p3, p4 = (_bbox(pn[k]) for k in ("glue", "p1", "p2", "p3", "p4"))
    top1, top2, bot1 = (_bbox(pn[k]) for k in ("top1", "top2", "bot1"))
    yb, yt = p1[1], p1[3]
    ftop, fbot = top1[3], bot1[1]
    xs = [p1[0], p2[0], p3[0], p4[0], p4[2]]
    out = [dict(kind="h", row=1, a=glue[0], b=xs[0], v=xs[0] - glue[0], tol=tv["glue"], ref=ftop, tag="glue")]
    for i in range(4):
        out.append(dict(kind="h", row=1, a=xs[i], b=xs[i + 1], v=xs[i + 1] - xs[i], tol=tv["panel"], ref=ftop,
                        tag=f"panel{i + 1}"))
    out.append(dict(kind="h", row=2, a=glue[0], b=xs[4], v=xs[4] - glue[0], tol=tv["overall_len"], ref=ftop,
                    tag="overall_len"))
    out.append(dict(kind="h", row=-1, a=top1[2], b=top2[0], v=top2[0] - top1[2], tol=tv["slot"], ref=fbot,
                    tag="slot", note="TYP"))
    out.append(dict(kind="v", row=1, a=fbot, b=yb, v=yb - fbot, tol=tv["flap"], ref=xs[4], tag="flap_bot"))
    out.append(dict(kind="v", row=1, a=yb, b=yt, v=yt - yb, tol=tv["panel"], ref=xs[4], tag="panel_h"))
    out.append(dict(kind="v", row=1, a=yt, b=ftop, v=ftop - yt, tol=tv["flap"], ref=xs[4], tag="flap_top"))
    out.append(dict(kind="v", row=2, a=fbot, b=ftop, v=ftop - fbot, tol=tv["overall_h"], ref=xs[4], tag="overall_h"))
    return out


register_style(RSC())
# =============================================================================
# Style: Lid & Base (telescope box)
# =============================================================================
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


class Telescope(Style):
    id, name = "telescope", "Lid & Base"
    code = "FEFCO 0301 style"
    blurb = "Two-piece telescope box: a tray base and a slightly larger tray lid that slides over it. One sheet, two trays."
    status = "standard"
    view_up = "z"
    defaults = dict(L=150.0, W=100.0, H=60.0, t=2.0)
    options = [("lidh", "Lid depth (outside)"), ("clr", "Lid clearance"), ("flap", "Corner flap width")]
    height_label = "Base height"
    zero_ok = ("clr", "flap")                  # a press-fit lid and a tray without corner flaps are both allowed
    mode_help = {
        "inner": "Inside of the BASE tray (the lid is sized from it).",
        "outer": "Outside of the BASE tray.",
        "manufacturer": "Centre-of-crease sizes of the BASE tray.",
    }

    # The left / right walls stand one board outside the base sheet plane (see telescope_sequence), so the base is 2t
    # longer outside than its crease length. Corner flaps lie inside those walls, so with flaps the clear length
    # BETWEEN the flaps is 2t shorter than the crease length. W has neither effect.
    def crease(self, L, W, H, t, mode, flaps=True):
        return {"inner": (L + (2 * t if flaps else 0.0), W + t, H + t / 2), "outer": (L - 2 * t, W - t, H - t / 2),
                "manufacturer": (L, W, H)}[mode]

    def inner(self, Lc, Wc, Hc, t, flaps=True):
        return Lc - (2 * t if flaps else 0.0), Wc - t, Hc - t / 2

    @staticmethod
    def _flaps(spec):
        return spec.opts.get("flap") != 0

    def crease_for(self, spec):
        return self.crease(spec.L, spec.W, spec.H, spec.t, spec.mode, self._flaps(spec))

    def inner_for(self, spec, Lc, Wc, Hc):
        return self.inner(Lc, Wc, Hc, spec.t, self._flaps(spec))

    def resolve(self, c):
        t, Hc = c.t, c.Hc
        clr = _auto(c, "clr", max(c.mm_(0.6), 0.25 * t))
        lidh = _auto(c, "lidh", max(3 * t, 0.4 * Hc))
        return dict(clr=clr, lidh=lidh, flap=_auto(c, "flap", min(max(c.t, Hc - c.t), 0.45 * c.Wc)),
                    Llc=c.Lc + 4 * t + clr, Wlc=c.Wc + 2 * t + clr, Hlc=lidh - t / 2)

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

    rounded_folds = True
    draw_sub = "Telescope lid and base  ·  FEFCO 0301 style"
    draw_cap = "LID AND BASE"
    step_text = {"flat": "As cut: base and lid trays with their corner flaps open.",
                 "partial": "Corner flaps folded in first, walls half way up.",
                 "folded": "Both trays folded; the lid slides over the base."}
    step_amount = 0.62

    def dimensions(self, res, spec):
        return telescope_dimensions(res, spec)

    def dim_field(self, dm, res, spec):
        tag, kind, au = dm.get("tag", ""), dm.get("kind"), res.info.get("auto", {})
        if tag == "b_bottom" and kind == "h":
            return "L", None
        if tag in ("b_left", "b_right") and kind == "h":
            return "H", None
        if tag == "b_flap" and "flap" in au:
            return "flap", dm["v"]
        if (tag in ("l_left", "l_right") and kind == "h") or (tag in ("l_front", "l_back") and kind == "v"):
            return ("lidh", au["lidh"]) if "lidh" in au else None
        if tag == "l_bottom" and "clr" in au:
            return "clr", au["clr"]
        return None

    def size_rows(self, c):
        a, t = c.a, c.t
        return [("Base inside L × W × H", c.tri(c.Li, c.Wi, c.Hi) + c.tol("box")),
                ("Base outside L × W × H", c.tri(c.Lc + 2 * t, c.Wc + t, c.Hc + t / 2) + c.tol("box")),
                ("Lid crease L × W × H", c.tri(a["Llc"], a["Wlc"], a["Hlc"])), c.flat,
                ("Board thickness", c.fnum(t, c.units)),
                ("Lid clearance", c.fnum(a["clr"], c.units)),
                ("Lid depth (outside)", c.fnum(a["lidh"], c.units)),
                ("Corner flap width", c.fnum(a["flap"], c.units) + c.tol("flap")),
                ("Units", c.units)]

    def drawing_notes(self, res, units):
        return ["Base inside length is the clear length between the corner flaps. Two trays on one sheet. Fold the four corner flaps of each tray first, then the walls, so the "
                "flaps end up inside the left and right walls. The lid slides over the base with the "
                f"clearance shown ({_fnum(res.info['auto']['clr'], units)})."]

    def fold_sequence(self, panels, t, amount):
        return telescope_sequence(panels, t, amount)


def telescope_sequence(panels, t, amount):
    """Lid & Base: in each tray the four corner flaps fold first, then the four walls fold up together so the
    flaps end up against the inside of the left / right walls. The left / right walls stand one board outside the base so the front and
    back walls end against them."""
    clamp = lambda v: min(1.0, max(0.0, v))

    def prog_of(p, d, m):
        n = p.name[2:] if p.name[1:2] == "_" else p.name
        if n.startswith("c"):
            return clamp(amount / 0.25)
        return clamp((amount - 0.25) / 0.75) if p.parent else 0.0

    def lift_of(p, prog):
        n = p.name[2:] if p.name[1:2] == "_" else p.name
        if n == "left":
            return (-t * prog, 0.0, 0.0)
        if n == "right":
            return (t * prog, 0.0, 0.0)
        if n in ("cfl", "cbl"):
            return (0.0, 0.0, 0.5 * t * prog)
        if n in ("cfr", "cbr"):
            return (0.0, 0.0, 0.5 * t * prog)
        return None
    return prog_of, lift_of, None


def telescope_dimensions(res, spec):
    """Dimension list for the two-tray telescope blank: widths of the base and lid trays across the top, heights of
    the lid tray down the right-hand side (the base heights are in the size table)."""
    pn = {p.name: p for p in res.panels}
    tv = res.info["tol"]["values"]
    bb = {k: _bbox(v) for k, v in pn.items()}
    out = []
    for pre in ("b_", "l_"):
        top = max(bb[pre + n][3] for n in ("back", "cbl", "cbr"))
        low = min(bb[pre + n][1] for n in ("front", "cfl", "cfr"))
        for nm, key in (("left", "panel"), ("bottom", "panel"), ("right", "panel")):
            b = bb[pre + nm]
            out.append(dict(kind="h", row=1, a=b[0], b=b[2], v=b[2] - b[0], tol=tv[key], ref=top, yref=top,      # from the top of the drawing, so the line
                            tag=pre + nm))                                 # does not run along a flap hinge
        x0, x1 = min(bb[pre + "left"][0], bb[pre + "cfl"][0]), max(bb[pre + "right"][2], bb[pre + "cfr"][2])
        out.append(dict(kind="h", row=2, a=x0, b=x1, v=x1 - x0, tol=tv["overall_len"], ref=bb[pre + "back"][3], yref=top,
                        tag=pre + "overall"))
        f = bb[pre + "cfl"]
        out.append(dict(kind="h", row=-1, a=f[0], b=f[2], v=f[2] - f[0], tol=tv["flap"], ref=f[1], yref=low,
                        tag=pre + "flap", note="FLAP"))
    xr = bb["l_cfr"][2]
    for nm, key in (("front", "panel"), ("bottom", "panel"), ("back", "panel")):
        b = bb["l_" + nm]
        out.append(dict(kind="v", row=1, a=b[1], b=b[3], v=b[3] - b[1], tol=tv[key], ref=xr, xref=xr,
                        tag="l_" + nm))
    y0, y1 = bb["l_front"][1], bb["l_back"][3]
    out.append(dict(kind="v", row=2, a=y0, b=y1, v=y1 - y0, tol=tv["overall_h"], ref=xr, xref=xr,
                    tag="l_overall_h"))
    return out


register_style(Telescope())
# =============================================================================
# Style: Insert (diagonal X divider) - one folded strip, for square and rectangular boxes
# =============================================================================
# The strip has three panels in a row: a blade, a wall panel and a blade. The wall panel stands against one wall of
# the box (the shorter wall); each blade folds back off one end of it and runs corner to corner, so the two blades
# cross at the centre of the box in an X. A slot cut from the top of one blade and from the bottom of the other lets
# them slide together (a half lap). The fold lines carry a slit through the middle half of their height so the thick
# board can turn through the fold angle; the top and bottom quarters stay joined and act as hinges.
INS_TURN = 0.75 * math.pi       # the fold angle in a square box: 135 degrees (the blade ends up 45 degrees to the wall panel)
INS_MAX_RATIO = 3.0             # longest box (length / width) the diagonal insert is offered for
INS_NAMES = ("ia", "ib", "ic")   # blade, wall panel, blade (the wall panel is the root; list it first)
_SQ2 = math.sqrt(2.0)


def insert_nominal_bend(t):
    """(inside radius, K) the insert is sized with. Fixed on purpose: the dieline must not move when the 3-D preview's
    bend radius is changed."""
    m = BEND_MATERIALS[BEND_DEFAULT]
    return m["ri"] * t, m["k"]


def insert_fold_length(t, turn=INS_TURN):
    """Neutral length of board one fold uses up (the width a hinge slit has to be at least)."""
    ri, K = insert_nominal_bend(t)
    return turn * (ri + K * t)


def insert_geometry(Sw, t, Sl=None):
    """Sizes of the strip for a space `Sw` wide (the wall panel's wall) and `Sl` long (Sl >= Sw; a square when omitted),
    the clear size the insert may use, all in the same units as t.
    Plan view of the folded insert, board outside face against the wall: the wall panel lies along the wall, each fold
    is a true arc of outside radius rho = ri + t, and each blade's far corner just touches the corner of the space
    (its outer face the wall that faces it, the inner face the side wall). With phi the blade's angle to the wall
    (atan Sl / Sw, 45 degrees in a square) each fold turns through turn = 180 degrees - phi, and
        lam blade flat length       = (Sl - (1 + cos phi) rho) / sin phi
        b   wall panel flat length  = 2 lam cos phi - Sw - 2 rho sin phi + 2 t sin phi
    With bn = the neutral length of one fold, m = b + bn (crease to crease on the wall panel) and q = lam + bn / 2
    (crease to the end of a blade). `sc` is how far from the start of a blade's flat part the two blades cross, and
    `kslot` how much wider than the board a slot has to be because the blades cross at an angle."""
    Sl = Sw if Sl is None else Sl
    ri, K = insert_nominal_bend(t)
    rn, rho = ri + K * t, ri + t
    phi = math.atan2(Sl, Sw)
    turn = math.pi - phi
    c, sn_ = math.cos(phi), math.sin(phi)
    bn = turn * rn
    lam = (Sl - (1 + c) * rho) / sn_
    b = 2 * lam * c - Sw - 2 * rho * sn_ + 2 * t * sn_
    return dict(ri=ri, K=K, rn=rn, rho=rho, bn=bn, b=b, lam=lam, m=b + bn, q=lam + bn / 2,
                sc=(b / 2 + rho * sn_ - t * sn_ / 2) / c, turn=turn, phi=phi, Sw=Sw, Sl=Sl,
                kslot=1.0 / max(1e-6, abs(math.sin(2 * phi))))


def insert_panels(g, Hs, slot, relief, ox=0.0, oy=0.0, pre=""):
    """The three panels of the strip at (ox, oy), height Hs. `g` from insert_geometry. Slot of width `slot`, half the
    height deep, from the top of the first blade and from the bottom of the second; fold slits `relief` wide and half
    the height tall, centred on the folds."""
    q, m, bn, sc = g["q"], g["m"], g["bn"], g["sc"]
    turn = g.get("turn", INS_TURN)
    slot = slot * g.get("kslot", 1.0)               # blades crossing at an angle need a longer slot in each
    x1 = ox + q
    x2 = x1 + m
    x3 = x2 + q
    h, d, sw = relief / 2.0, Hs / 2.0, slot
    r0, r1 = oy + Hs / 4.0, oy + 3.0 * Hs / 4.0
    y0, y1 = oy, oy + Hs
    ca = x1 - (bn / 2.0 + sc)                    # slot centre on the first blade
    cc = x2 + (bn / 2.0 + sc)                    # ... and on the second
    A = [(ox, y0), (x1, y0), (x1, r0), (x1 - h, r0), (x1 - h, r1), (x1, r1), (x1, y1),
         (ca + sw / 2, y1), (ca + sw / 2, y1 - d), (ca - sw / 2, y1 - d), (ca - sw / 2, y1), (ox, y1)]
    B = [(x1, y0), (x2, y0), (x2, r0), (x2 - h, r0), (x2 - h, r1), (x2, r1), (x2, y1), (x1, y1), (x1, r1),
         (x1 + h, r1), (x1 + h, r0), (x1, r0)]
    C = [(x2, y0), (cc - sw / 2, y0), (cc - sw / 2, y0 + d), (cc + sw / 2, y0 + d), (cc + sw / 2, y0), (x3, y0),
         (x3, y1), (x2, y1), (x2, r1), (x2 + h, r1), (x2 + h, r0), (x2, r0)]
    pB = Panel(pre + "ib", B, None, None, 90.0, "body")
    pA = Panel(pre + "ia", A, pre + "ib", ((x1, y0), (x1, y1)), round(math.degrees(turn), 9), "body")
    pC = Panel(pre + "ic", C, pre + "ib", ((x2, y0), (x2, y1)), round(math.degrees(turn), 9), "body")
    pA.fold_segs = [((x1, y0), (x1, r0)), ((x1, r1), (x1, y1))]
    pC.fold_segs = [((x2, y0), (x2, r0)), ((x2, r1), (x2, y1))]
    pB.meta = dict(kind="diag", Hs=Hs, q=q, m=m, relief=relief, slot=slot, bn=bn, slot_from_crease=bn / 2.0 + sc,
                   turn=turn, Li=g.get("Sl", 0.0), Wi=g.get("Sw", 0.0))
    for pn in (pA, pB, pC):
        pn.group = "insert"
    return [pB, pA, pC]


class Insert(Style):
    zero_ok = ("clr", "hclr")
    auto_tol = {"slot": 0.1}                   # half-lap slots are cut to the board, not die-cut flap slots
    id, name = "insert", "Insert (diagonal X)"
    code = "Box insert"
    blurb = ("A divider that stands inside a square or rectangular box: one folded strip whose two blades cross "
             "corner to corner in an X and lock together at their slots. Sized from the box's inside dimensions.")
    status = "experimental"
    defaults = dict(L=150.0, W=150.0, H=120.0, t=3.0)
    options = [("clr", "Fit clearance (across the box)"), ("hclr", "Height clearance"), ("slot", "Slot width"),
               ("relief", "Fold slit width")]
    height_label = "Box inside height"
    view_up = "y"
    mode_help = {
        "inner": "Inside of the box the insert goes into (the Slotted Box's inside size).",
        "outer": "Outside of the closed Slotted Box it goes into.",
        "manufacturer": "Centre-of-crease sizes of the Slotted Box it goes into.",
    }

    # the box it goes into is a Slotted Box (RSC): same size rules
    def crease(self, L, W, H, t, mode):
        return STYLE_BY_ID["rsc"].crease(L, W, H, t, mode)

    def inner(self, Lc, Wc, Hc, t):
        return STYLE_BY_ID["rsc"].inner(Lc, Wc, Hc, t)

    def resolve(self, c):
        t = c.t
        Li, Wi, Hi = self.inner(c.Lc, c.Wc, c.Hc, t)
        clr = _auto(c, "clr", t + max(c.mm_(0.5), 0.25 * t))        # one board for the box's glue flap, plus a little play
        hclr = _auto(c, "hclr", max(c.mm_(1.0), 0.25 * t))
        slot = _auto(c, "slot", t + max(c.mm_(0.3), 0.05 * t))
        Sw, Sl, Hs = min(Li, Wi) - clr, max(Li, Wi) - clr, Hi - hclr
        if Sw <= 0:                                           # no room at all: sizes that check() reports as an error
            return dict(clr=clr, hclr=hclr, slot=slot, relief=0.0, Sw=Sw, Sl=Sl, Hs=Hs, too_small=True, b=0.0, lam=0.0,
                        bn=0.0, m=0.0, q=0.0, turn=INS_TURN)
        g = insert_geometry(Sw, t, Sl)
        relief = _auto(c, "relief", insert_fold_length(t, g["turn"]))
        return dict(clr=clr, hclr=hclr, slot=slot, relief=relief, Hs=Hs, long_side="L" if Li >= Wi else "W", **g)

    def check(self, c, r, iss):
        t = c.t
        Li, Wi, Hi = self.inner(c.Lc, c.Wc, c.Hc, t)
        if r.get("too_small") or r["b"] < 1.5 * t or r["lam"] < 3 * t:
            iss.append(Issue("error", "The box is too small for an insert at this board thickness. Reduce the "
                                      "thickness or enlarge the box.", ("L", "W", "t")))
            return
        if r["Sl"] > INS_MAX_RATIO * r["Sw"]:
            iss.append(Issue("error", f"The box is too long and narrow for a diagonal insert (length to width "
                                      f"{r['Sl'] / r['Sw']:.1f} : 1, the most is {INS_MAX_RATIO:g} : 1). Use the cross "
                                      f"divider instead.", ("L", "W")))
            iss[-1].code = "too_long"
            return
        if r["clr"] < 0 or r["hclr"] < 0:
            iss.append(Issue("error", "Clearances cannot be negative.", ("clr", "hclr")))
        elif r["clr"] < t:
            iss.append(Issue("warn", "Less than one board thickness of clearance across the box: the glue flap inside "
                                     "the Slotted Box can stop the insert going in.", ("clr", "t")))
        if r["Hs"] < 4 * t:
            iss.append(Issue("error", f"Insert height ({fmt(r['Hs'])}) is under 4× the board thickness. Raise the "
                                      f"box height or lower the height clearance.", ("H", "hclr", "t")))
        if r["slot"] < t:
            iss.append(Issue("error", "Slots narrower than the board: the two blades cannot slide together.",
                             ("slot", "t")))
        elif r["slot"] > 1.5 * t:
            iss.append(Issue("warn", "Slots wider than 1.5× the board make the crossing loose.", ("slot", "t")))
        if r["relief"] < r["bn"] - 1e-9:
            iss.append(Issue("error", f"Fold slits must be at least {fmt(r['bn'], 3)} wide, the length of board a "
                                      f"fold uses up, or they would not clear the bend.", ("relief",)))
        elif r["relief"] > r["m"] / 3:
            iss.append(Issue("warn", "Very wide fold slits leave the wall panel short.", ("relief",)))

    def build(self, c, r):
        return insert_panels(r, r["Hs"], r["slot"], r["relief"]), None

    rounded_folds = False
    tol_keys = ("panel", "slot", "overall_len", "overall_h")
    draw_sub = "Diagonal X insert, single folded strip"
    draw_cap = "BOX INSERT"
    anchor_panel = "ib"
    step_text = {"flat": "As cut: the strip with its slots and fold slits.",
                 "partial": "Both folds half way: the blades swing in off the wall panel.",
                 "folded": "Both creases folded and the blades slid together at the slots, corner to corner."}
    step_amount = 0.55

    view_title = "FOLDED INSERT (NOT TO SCALE)"
    table_title = "INSERT SIZES"
    steps_note = "(not to scale; board drawn at full thickness)"

    def view_caption(self, res, units):
        Li, Wi, Hi = res.info["inner"]
        return f"fits a box {_fnum(Li, units)} × {_fnum(Wi, units)} × {_fnum(Hi, units)} {units} inside"

    def bend_notes(self, rep):
        ri, K = insert_nominal_bend(1.0)
        return ["The dieline is not changed by this page. The insert is sized with a fixed bend model (inside radius "
                f"{ri:g} × board, K {K:g}): each fold is a true arc, and each blade just reaches the corner of the box.",
                "Changing the radius or K-factor here shows how the real fold behaves; it does not move any crease."]

    def tol_note(self, f, units):
        return f"Tolerances (± {units}): panels / scores {f('panel')}; slots {f('slot')}; blank {f('overall_len')} x {f('overall_h')}."

    def dimensions(self, res, spec):
        return insert_dimensions(res, spec)

    def dim_field(self, dm, res, spec):
        tag, au = dm.get("tag"), res.info.get("auto", {})
        if tag == "slot" and "slot" in au:
            return "slot", au["slot"], 1.0 / au.get("kslot", 1.0)       # the cut slot is wider than the box value on a long box
        if tag == "height":
            return "H", None
        if tag == "slot_depth":
            return "H", None, 2.0
        return None

    def size_rows(self, c):
        a, u = c.a, c.units
        return [("Box inside L × W × H", c.tri(c.Li, c.Wi, c.Hi)),
                ("Insert fits L × W × H", insert_fit_tri(c, a)),
                ("Blade / wall / blade", c.tri(a["q"], a["m"], a["q"])), c.flat,
                ("Board thickness", c.fnum(c.t, u)),
                ("Fit clearance", c.fnum(a["clr"], u)),
                ("Slot width (cut)", c.fnum(a["slot"] * a.get("kslot", 1.0), u) + c.tol("slot")),
                ("Fold slit width", c.fnum(a["relief"], u)),
                ("Units", u)]

    def drawing_notes(self, res, units):
        a = res.info["auto"]
        return [f"Fold both creases the same way, away from the printed outside, until each blade stands at "
                f"{math.degrees(a['phi']):.0f}° to the wall panel (a {math.degrees(a['turn']):.0f}° fold). The wall panel "
                f"goes flat against the shorter wall of the box.",
                "Slide the blades together at the slots: the slot cut from the top of one blade meets the slot cut from "
                "the bottom of the other, so they cross at the centre of the box.",
                "The fold slits are cut through, 1/2 of the height at the middle of each crease; the top and bottom "
                "quarters stay as hinges."]

    def fold_sequence(self, panels, t, amount):
        return insert_sequence(panels, t, amount)


def insert_fit_tri(c, a):
    """'L × W × H' of the space the insert fits, in the box's own orientation."""
    Sl, Sw = a["Sl"], a["Sw"]
    return c.tri(*((Sl, Sw) if a.get("long_side", "L") == "L" else (Sw, Sl)), a["Hs"])


def insert_ctx(c):
    """Build context for an insert that rides along with a Slotted Box: the same sizes, but none of the box's own
    advanced options (the box's slot width is not the insert's)."""
    c2 = Ctx(c.spec, c.Lc, c.Wc, c.Hc)
    c2.o = {}
    return c2


def insert_dims_below(res, spec):
    return insert_dimensions(res, spec, below=True)


def insert_sequence(panels, t, amount):
    """Both blades fold together, 0 -> 1 over the whole slider."""
    clamp = lambda v: min(1.0, max(0.0, v))

    def prog_of(p, d, m):
        return clamp(amount) if p.name[-2:] in ("ia", "ic") else 0.0
    return prog_of, None, None


def insert_dimensions(res, spec, below=False):
    """Dimension records for the flat strip (see rsc_dimensions for the format). `below`: the strip sits under a box,
    so its widths go on the rows below it and the slot (listed in the size table) is left out."""
    pn = {p.name: p for p in res.panels if p.name in INS_NAMES}
    tv = res.info["tol"]["values"]
    a, b, c = (_bbox(pn[k]) for k in ("ia", "ib", "ic"))
    top, bot = b[3], b[1]
    r1, r2, edge = (-1, -2, bot) if below else (1, 2, top)
    out = [dict(kind="h", row=r1, a=a[0], b=a[2], v=a[2] - a[0], tol=tv["panel"], ref=edge, tag="blade1"),
           dict(kind="h", row=r1, a=b[0], b=b[2], v=b[2] - b[0], tol=tv["panel"], ref=edge, tag="wall"),
           dict(kind="h", row=r1, a=c[0], b=c[2], v=c[2] - c[0], tol=tv["panel"], ref=edge, tag="blade2"),
           dict(kind="h", row=r2, a=a[0], b=c[2], v=c[2] - a[0], tol=tv["overall_len"], ref=edge, tag="overall_len")]
    xs = sorted(q[0] for q in pn["ic"].poly if abs(q[1] - (bot + (top - bot) / 2)) < 1e-6)     # the slot floor corners
    if len(xs) >= 2 and not below:
        out.append(dict(kind="h", row=-1, a=xs[0], b=xs[-1], v=xs[-1] - xs[0], tol=half_lap_tol(res, tv), ref=bot, tag="slot",
                        note="SLOT"))
    out.append(dict(kind="v", row=2, a=bot, b=top, v=top - bot, tol=tv["overall_h"], ref=c[2], tag="height"))
    out.append(dict(kind="v", row=1, a=bot, b=bot + (top - bot) / 2, v=(top - bot) / 2, tol=half_lap_tol(res, tv), ref=c[2],
                    tag="slot_depth"))                       # the shorter one inside, so no line runs through a label
    return out


register_style(Insert())
# =============================================================================
# Style: Cross / grid divider - flat slotted panels that cross at half-lap slots, for any rectangular box
# =============================================================================
# Dividers run along the length of the box ("lengthwise", slots cut from their top) and across its width
# ("crosswise", slots cut from their bottom). Each lengthwise divider has one slot per crosswise divider and the other
# way round, so the two sets slide together into a grid of equal compartments. Every divider is its own flat piece:
# nothing is folded. One lengthwise and one crosswise divider make a simple cross.
GRID_MAX = 9                      # most dividers each way
GRID_PREFIX = {"l": "gl", "w": "gw"}


def _grid_count(c, key, default=1):
    v = c.o.get(key)
    if v is None:
        return default
    return int(round(v)) if abs(v - round(v)) < 1e-9 else v           # a non-whole number is reported by check()


def grid_geometry(Li, Wi, Hi, t, nl, nw, clr, hclr, slot):
    """Sizes of the dividers for a box with inside length Li, width Wi and height Hi, all in the same units as t.
    `nl` dividers run along the length (spaced across the width), `nw` run across the width (spaced along the length).
    The compartments are equal, each divider's board counted. Returns a dict (see the keys below)."""
    Lp, Wp, Hs = Li - clr, Wi - clr, Hi - hclr
    cw = (Wi - nl * t) / (nl + 1)                          # clear width of a compartment across the box
    cl = (Li - nw * t) / (nw + 1)                          # clear length of a compartment along the box
    zs = [(j + 1) * cw + (j + 0.5) * t - Wi / 2.0 for j in range(nl)]       # lengthwise dividers: centre across, from the middle
    xs = [(i + 1) * cl + (i + 0.5) * t - Li / 2.0 for i in range(nw)]       # crosswise dividers: centre along, from the middle
    return dict(Lp=Lp, Wp=Wp, Hs=Hs, nl=nl, nw=nw, cl=cl, cw=cw, zs=zs, xs=xs, slot=slot, d=Hs / 2.0,
                slots_l=[x + Lp / 2.0 for x in xs],        # slot centres along a lengthwise divider (from its end)
                slots_w=[z + Wp / 2.0 for z in zs],        # ... and along a crosswise one
                Li=Li, Wi=Wi)


def _grid_outline(x0, y0, L, Hs, slots, sw, d, from_top):
    """One divider (a rectangle L x Hs at (x0, y0)) with a slot of width sw and depth d at each position in `slots`."""
    pts = [(x0, y0), (x0 + L, y0)]
    if from_top:
        pts.append((x0 + L, y0 + Hs))
        for u in sorted(slots, reverse=True):
            pts += [(x0 + u + sw / 2, y0 + Hs), (x0 + u + sw / 2, y0 + Hs - d), (x0 + u - sw / 2, y0 + Hs - d),
                    (x0 + u - sw / 2, y0 + Hs)]
        pts.append((x0, y0 + Hs))
    else:
        pts = [(x0, y0)]
        for u in sorted(slots):
            pts += [(x0 + u - sw / 2, y0), (x0 + u - sw / 2, y0 + d), (x0 + u + sw / 2, y0 + d), (x0 + u + sw / 2, y0)]
        pts += [(x0 + L, y0), (x0 + L, y0 + Hs), (x0, y0 + Hs)]
    return pts


def grid_items(g, crosswise_first=False):
    """[(name, role, index, length, slots)] of every divider: the lengthwise ones first (or last)."""
    a = [(f"gl{j + 1}", "l", j, g["Lp"], g["slots_l"]) for j in range(g["nl"])]
    b = [(f"gw{i + 1}", "w", i, g["Wp"], g["slots_w"]) for i in range(g["nw"])]
    return b + a if crosswise_first else a + b


def grid_panels(g, x0=0.0, y0=0.0, wmax=None, step=1.0, gap=0.0):
    """The divider panels laid out in rows from (x0, y0): left to right, a new row when the next one would pass
    x0 + wmax. A row is placed `step` x (height + gap) above the previous one (step = -1 puts the rows going down;
    the first row's bottom edge is at y0 either way)."""
    Hs, sw, d = g["Hs"], g["slot"], g["d"]
    out, x, row = [], x0, 0
    for name, role, idx, L, slots in grid_items(g, step < 0):      # rows going down: the crosswise ones on top, so that
        # in the 3-D model (where the sheet stands on its edge) the lengthwise dividers are always the lowest row
        if wmax is not None and x > x0 and x + L > x0 + wmax + 1e-9:
            x, row = x0, row + 1
        y = y0 + step * row * (Hs + gap)
        pn = Panel(name, _grid_outline(x, y, L, Hs, slots, sw, d, role == "l"), None, None, 90.0, "body")
        pn.group = "insert"
        pn.meta = dict(kind="grid", role=role, idx=idx, L=L, Hs=Hs, slots=list(slots), slot=sw, d=d,
                       nl=g["nl"], nw=g["nw"], zs=list(g["zs"]), xs=list(g["xs"]), Li=g["Li"], Wi=g["Wi"])
        out.append(pn)
        x += L + gap
    return out


def grid_size(g, gap, wmax):
    """(width, height, rows) of the laid-out dividers."""
    x, row, width = 0.0, 0, 0.0
    for name, role, idx, L, slots in grid_items(g, True):
        if wmax is not None and x > 0 and x + L > wmax + 1e-9:
            x, row = 0.0, row + 1
        x += L + gap
        width = max(width, x - gap)
    return width, (row + 1) * g["Hs"] + row * gap, row + 1


def grid_pieces(L, Hs, slots, sw, d, from_top):
    """The convex pieces one divider is drawn in (3-D preview): [(suffix, polygon (u, v), joints)]. The solid half is
    cut into a strip between each pair of slot centres and the slotted half into a column between each pair of slots.
    Every piece then lies wholly on one side of each crossing divider, which keeps the draw order exact where
    several dividers interlock."""
    cuts = sorted(slots)
    ub = [0.0]
    for u in cuts:
        ub += [u - sw / 2, u + sw / 2]
    ub.append(L)
    cols = [(ub[i], ub[i + 1]) for i in range(0, len(ub), 2) if ub[i + 1] - ub[i] > 1e-9]
    vlo, vhi = (0.0, Hs - d) if from_top else (d, Hs)          # the solid half
    v_int = vhi if from_top else vlo                           # where the slotted half meets it
    c0, c1 = (Hs - d, Hs) if from_top else (0.0, d)            # the slotted half
    bounds = [0.0] + cuts + [L]
    out, k = [], 0
    for a, b in zip(bounds, bounds[1:]):
        ins = [c for ca, cb in cols for c in (ca, cb) if a + 1e-9 < c < b - 1e-9]
        if from_top:
            poly = [(a, vlo), (b, vlo), (b, vhi)] + [(c, vhi) for c in sorted(set(ins), reverse=True)] + [(a, vhi)]
        else:
            poly = [(a, vlo)] + [(c, vlo) for c in sorted(set(ins))] + [(b, vlo), (b, vhi), (a, vhi)]
        joints = [((a, vlo), (a, vhi))] * (a > 1e-9) + [((b, vlo), (b, vhi))] * (b < L - 1e-9)
        joints += [((max(ca, a), v_int), (min(cb, b), v_int)) for ca, cb in cols if min(cb, b) > max(ca, a) + 1e-9]
        out.append((str(k), poly, joints))
        k += 1
    for ca, cb in cols:
        out.append((str(k), [(ca, c0), (cb, c0), (cb, c1), (ca, c1)], [((ca, v_int), (cb, v_int))]))
        k += 1
    return out


class Grid(Style):
    zero_ok = ("clr", "hclr")
    flat_parts = True
    auto_tol = {"slot": 0.1}                   # half-lap slots are cut to the board, not die-cut flap slots
    id, name = "grid", "Cross / grid divider"
    code = "Box divider"
    blurb = ("Slotted dividers that cross in a grid inside any rectangular box: one or more along the length, one or "
             "more across the width, sliding together at half-lap slots. Sized from the box's inside dimensions.")
    status = "experimental"
    defaults = dict(L=200.0, W=150.0, H=120.0, t=3.0)
    options = [("nl", "Dividers along the length"), ("nw", "Dividers across the width"),
               ("clr", "Fit clearance (along and across)"), ("hclr", "Height clearance"), ("slot", "Slot width")]
    count_keys = ("nl", "nw")
    height_label = "Box inside height"
    view_up = "y"
    mode_help = {
        "inner": "Inside of the box the dividers go into (the Slotted Box's inside size).",
        "outer": "Outside of the closed Slotted Box they go into.",
        "manufacturer": "Centre-of-crease sizes of the Slotted Box they go into.",
    }
    insert_blurb = "cross divider"

    def crease(self, L, W, H, t, mode):
        return STYLE_BY_ID["rsc"].crease(L, W, H, t, mode)

    def inner(self, Lc, Wc, Hc, t):
        return STYLE_BY_ID["rsc"].inner(Lc, Wc, Hc, t)

    def resolve(self, c, keys=("nl", "nw")):
        t = c.t
        Li, Wi, Hi = self.inner(c.Lc, c.Wc, c.Hc, t)
        nl, nw = _grid_count(c, keys[0]), _grid_count(c, keys[1])
        clr = _auto(c, "clr", t + max(c.mm_(0.5), 0.25 * t))
        hclr = _auto(c, "hclr", max(c.mm_(1.0), 0.25 * t))
        slot = _auto(c, "slot", t + max(c.mm_(0.3), 0.05 * t))
        if not (isinstance(nl, int) and isinstance(nw, int)) or nl < 0 or nw < 0 or nl > GRID_MAX or nw > GRID_MAX:
            return dict(bad_count=True, nl=nl, nw=nw, clr=clr, hclr=hclr, slot=slot, Li=Li, Wi=Wi, Hi=Hi)
        g = grid_geometry(Li, Wi, Hi, t, nl, nw, clr, hclr, slot)
        return dict(clr=clr, hclr=hclr, **g)

    def check(self, c, r, iss):
        t = c.t
        if r.get("bad_count"):
            iss.append(Issue("error", f"The number of dividers must be a whole number from 0 to {GRID_MAX} in each "
                                      f"direction.", ("nl", "nw")))
            return
        if r["nl"] + r["nw"] < 1:
            iss.append(Issue("error", "Add at least one divider.", ("nl", "nw")))
            return
        if r["nl"] == 0 or r["nw"] == 0:
            iss.append(Issue("warn", "Dividers in one direction only cross nothing: they have no slots to hold them "
                                     "upright and will lean or fall over. Add dividers in the other direction too.",
                             ("nl", "nw")))
        if r["clr"] < 0 or r["hclr"] < 0:
            iss.append(Issue("error", "Clearances cannot be negative.", ("clr", "hclr")))
        elif r["clr"] < t:
            iss.append(Issue("warn", "Less than one board thickness of clearance: the glue flap inside the Slotted "
                                     "Box can stop the dividers going in.", ("clr", "t")))
        if r["Lp"] < 3 * t or r["Wp"] < 3 * t:
            iss.append(Issue("error", "The box is too small for dividers at this board thickness.", ("L", "W", "t")))
            return
        if r["Hs"] < 4 * t:
            iss.append(Issue("error", f"Divider height ({fmt(r['Hs'])}) is under 4× the board thickness. Raise the box "
                                      f"height or lower the height clearance.", ("H", "hclr", "t")))
        if r["slot"] < t:
            iss.append(Issue("error", "Slots narrower than the board: the dividers cannot slide together.", ("slot", "t")))
        elif r["slot"] > 1.5 * t:
            iss.append(Issue("warn", "Slots wider than 1.5× the board make the crossings loose.", ("slot", "t")))
        for nm, cl, n, L, slots in (("along the length", r["cl"], r["nw"], r["Lp"], r["slots_l"]),
                                    ("across the width", r["cw"], r["nl"], r["Wp"], r["slots_w"])):
            if n and slots:
                lig = min([b - a - r["slot"] for a, b in zip(slots, slots[1:])] or [9e9])
                end = min(slots[0] - r["slot"] / 2, L - slots[-1] - r["slot"] / 2)
                if min(lig, end) < 1.5 * t - 1e-9:
                    iss.append(Issue("error", f"The compartments {nm} are too narrow ({fmt(cl)}): the slots would "
                                              f"leave less than 1.5 boards of material between them. Use fewer "
                                              f"dividers or a larger box.", ("nl", "nw", "slot", "t")))
        if r["cl"] < 8 * t or r["cw"] < 8 * t:
            iss.append(Issue("info", "Very small compartments (under 8 boards wide).", ("nl", "nw")))

    def build(self, c, r):
        g = r
        gap = max(c.mm_(5), 2 * c.t)
        wmax = 2.05 * max(g["Lp"], g["Wp"]) + gap
        return grid_panels(g, 0.0, 0.0, wmax, 1.0, gap), None

    rounded_folds = False
    tol_keys = ("panel", "slot", "overall_len", "overall_h")
    draw_sub = "Cross / grid divider, flat slotted panels"
    draw_cap = "BOX DIVIDER"
    anchor_panel = None
    step_text = {"flat": "As cut: every divider flat, lengthwise ones (slots on top) and crosswise ones (slots below).",
                 "partial": "The lengthwise dividers stand in place; the crosswise ones are turned and held above them.",
                 "folded": "The crosswise dividers lowered so each pair of slots meets: a grid of equal compartments."}
    step_amount = 0.5
    view_title = "ASSEMBLED DIVIDERS (NOT TO SCALE)"
    table_title = "DIVIDER SIZES"
    steps_note = "(not to scale; board drawn at full thickness)"
    step_heads = ("INSERT ASSEMBLED", "Walls and glue flap folded; the dividers slotted together above the box.")

    def view_caption(self, res, units):
        Li, Wi, Hi = res.info["inner"]
        return f"fits a box {_fnum(Li, units)} × {_fnum(Wi, units)} × {_fnum(Hi, units)} {units} inside"

    def bend_notes(self, rep):
        return ["The dividers are flat panels: there are no folds, so this page does not change the dieline.",
                "The bend settings only affect a box this divider is added to."]

    def tol_note(self, f, units):
        return f"Tolerances (± {units}): panels {f('panel')}; slots {f('slot')}; blank {f('overall_len')} x {f('overall_h')}."

    def dimensions(self, res, spec):
        return grid_dimensions(res, spec)

    def dim_field(self, dm, res, spec):
        tag = dm.get("tag", "")
        if tag.startswith("div_gl"):
            return "L", None
        if tag.startswith("div_gw"):
            return "W", None
        if tag == "height":
            return "H", None
        if tag == "slot_depth":
            return "H", None, 2.0
        return None

    def size_rows(self, c):
        a, u = c.a, c.units
        rows = [("Box inside L × W × H", c.tri(c.Li, c.Wi, c.Hi))]
        rows += self.in_box_rows(c, a)
        return rows + [c.flat, ("Board thickness", c.fnum(c.t, u)),
                       ("Fit clearance", c.fnum(a["clr"], u)),
                       ("Slot width", c.fnum(a["slot"], u) + c.tol("slot")),
                       ("Slot depth", c.fnum(a["d"], u)),
                       ("Units", u)]

    extra_rows = 2

    def in_box_rows(self, c, a):
        """Two table rows: the dividers and the compartments they make (also used when added to a Slotted Box)."""
        rows = []
        parts = []
        if a["nl"]:
            parts.append(f"{a['nl']} × {_fnum(a['Lp'], c.units)}")
        if a["nw"]:
            parts.append(f"{a['nw']} × {_fnum(a['Wp'], c.units)}")
        rows.append(("Dividers (along / across)", " + ".join(parts) + f"  ×  {_fnum(a['Hs'], c.units)} high"))
        rows.append((f"Compartments ({(a['nl'] + 1) * (a['nw'] + 1)})",
                     f"{_fnum(a['cl'], c.units)} × {_fnum(a['cw'], c.units)}"))
        return rows

    def drawing_notes(self, res, units):
        a = res.info["auto"]
        fm = lambda v: _fnum(v, units)
        notes = ["Stand the lengthwise dividers (slots cut from the top) in the box, then lower the crosswise dividers "
                 "(slots cut from the bottom) over them so every pair of slots meets and the tops finish level."]
        if a["nw"]:
            notes.append("Slot centres along each lengthwise divider, from one end: " + ", ".join(fm(v) for v in a["slots_l"])
                         + f"  (slot {fm(a['slot'])} wide, {fm(a['d'])} deep).")
        if a["nl"]:
            notes.append("Slot centres along each crosswise divider, from one end: " + ", ".join(fm(v) for v in a["slots_w"])
                         + f"  (slot {fm(a['slot'])} wide, {fm(a['d'])} deep).")
        return notes

    def fold_sequence(self, panels, t, amount):
        return grid_sequence(panels, t, amount)

    # ---- how it sits on the sheet of a Slotted Box ---------------------------------------------------------
    def box_layout(self, g, ox_centre, y_top, wmax, gap):
        """The divider panels placed below a box blank: rows going down from y_top, left edge at ox_centre - wmax / 2."""
        wid, hgt, rows = grid_size(g, gap, wmax)
        return grid_panels(g, ox_centre - wid / 2.0, y_top - g["Hs"], wmax, -1.0, gap), hgt

    def box_dims(self, res, spec):
        return grid_dimensions(res, spec, below=True)

    def box_note(self):
        return ("Dividers (cut from the same sheet, below the box): stand the lengthwise ones in the box, lower the "
                "crosswise ones over them so the slots meet, and fit the assembly before the top flaps are closed.")


def grid_sequence(panels, t, amount):
    """All dividers share one progress, 0 -> 1 over the whole slider (see fold_grid for what moves when)."""
    clamp = lambda v: min(1.0, max(0.0, v))

    def prog_of(p, d, m):
        return clamp(amount) if is_insert(p) else 0.0
    return prog_of, None, None


def grid_dimensions(res, spec, below=False):
    """Dimension records for the divider sheet: the first row of dividers, the blank's size, the height and the slot depth."""
    pans = [p for p in res.panels if is_insert(p)]
    tv = res.info["tol"]["values"]
    bb = {p.name: _bbox(p) for p in pans}
    top = max(b[3] for b in bb.values())
    bot = min(b[1] for b in bb.values())
    edge_y = bot if below else top                       # the row next to the dimensions: the bottom one when they go below
    first = [(p.name, bb[p.name]) for p in pans if abs((bb[p.name][1] if below else bb[p.name][3]) - edge_y) < 1e-6]
    r1, r2, edge = (-1, -2, bot) if below else (1, 2, top)
    out = []
    for nm, b in first[:3]:
        out.append(dict(kind="h", row=r1, a=b[0], b=b[2], v=b[2] - b[0], tol=tv["panel"], ref=edge, tag="div_" + nm))
    xl = min(b[0] for b in bb.values())
    xr = max(b[2] for b in bb.values())
    out.append(dict(kind="h", row=r2, a=xl, b=xr, v=xr - xl, tol=tv["overall_len"], ref=edge, tag="overall_len"))
    ref = xr
    f = first[0][1]
    out.append(dict(kind="v", row=2, a=f[1], b=f[3], v=f[3] - f[1], tol=tv["overall_h"], ref=ref, tag="height"))
    out.append(dict(kind="v", row=1, a=f[1], b=f[1] + (f[3] - f[1]) / 2, v=(f[3] - f[1]) / 2, tol=half_lap_tol(res, tv), ref=ref,
                    tag="slot_depth"))
    return out


register_style(Grid())
# =============================================================================
# Style: Slot-fit test - a small sheet of slotted plates to find the slot width that suits the board
# =============================================================================
# Board thickness varies and so does the cut width of a laser, so the right slot width for a half-lap joint is found by
# trying it. The sheet holds a plain key plate (the board edge to push in) and N plates whose slots grow in steps from
# exactly the board thickness. The number of small notches along the bottom edge of a plate says which slot it is.
# The slot that lets the key slide in with a light push and no wobble is the one to use as the "Slot width" option.
FIT_MAX = 12


def fit_widths(t, step, n):
    return [t + i * step for i in range(n)]


def _fit_outline(x0, y0, L, H, slot, d, notches, nt):
    """A plate L x H at (x0, y0): slot of width `slot` and depth `d` cut down from the top at the middle, and `notches`
    small square notches (side nt) along the bottom edge."""
    pts = [(x0, y0)]
    if notches:
        gap = (L - 2 * nt * notches) / (notches + 1)
        x = x0
        for _ in range(notches):
            x += gap
            pts += [(x, y0), (x, y0 + nt), (x + nt, y0 + nt), (x + nt, y0)]
            x += nt
        # (the notch width is nt; the spacing above keeps two notch widths per notch so they stay well apart)
    pts += [(x0 + L, y0), (x0 + L, y0 + H)]
    if slot:
        cx = x0 + L / 2.0
        pts += [(cx + slot / 2, y0 + H), (cx + slot / 2, y0 + H - d), (cx - slot / 2, y0 + H - d), (cx - slot / 2, y0 + H)]
    pts.append((x0, y0 + H))
    return pts


class FitTest(Style):
    zero_ok = ("step",)
    flat_parts = True
    auto_tol = {"slot": 0.02}                  # half-lap slots are cut to the board, not die-cut flap slots
    id, name = "fit", "Slot-fit test"
    code = "Test coupon"
    blurb = ("A small sheet of slotted plates whose slots grow in steps from the board thickness, plus a key plate to "
             "push in: cut it on your board, find the slot that fits, and use that width in the dividers and inserts.")
    status = "experimental"
    defaults = dict(L=30.0, W=30.0, H=15.0, t=3.0)
    options = [("count", "Number of slots"), ("step", "Slot width step")]
    count_keys = ("count",)
    height_label = "Slot depth"
    ratio_dims = ("L", "W")                    # the generic "smallest dimension" check applies to the plates only
    view_up = "y"
    mode_help = {k: "Sizes as typed: plate width (length), plate height (width) and slot depth (height)."
                 for k in ("inner", "outer", "manufacturer")}

    def crease(self, L, W, H, t, mode):
        return L, W, H

    def inner(self, Lc, Wc, Hc, t):
        return Lc, Wc, Hc

    def resolve(self, c):
        t = c.t
        step = _auto(c, "step", max(c.mm_(0.1), 0.02 * t))
        n = c.o.get("count")
        n = 6 if n is None else (int(round(n)) if abs(n - round(n)) < 1e-9 else n)
        return dict(step=step, n=n, pw=c.Lc, ph=c.Wc, d=c.Hc, nt=max(c.mm_(1.5), 0.5 * t))

    def check(self, c, r, iss):
        t = c.t
        if not isinstance(r["n"], int) or not 2 <= r["n"] <= FIT_MAX:
            iss.append(Issue("error", f"The number of slots must be a whole number from 2 to {FIT_MAX}.", ("count",)))
            return
        if r["step"] <= 0:
            iss.append(Issue("error", "The slot width step must be above zero.", ("step",)))
            return
        if r["pw"] < 8 * t or r["ph"] < r["d"] + 2 * t:
            iss.append(Issue("error", "The plates are too small: make them at least 8 boards wide and 2 boards taller "
                                      "than the slot is deep.", ("L", "W", "H", "t")))
            return
        if r["d"] < t:
            iss.append(Issue("error", "The slot depth must be at least one board.", ("H", "t")))
            return
        need = 2 * r["nt"] * r["n"] + r["nt"] * (r["n"] + 1)
        if need > r["pw"]:
            iss.append(Issue("error", "The plates are too narrow for the number of marking notches.", ("L", "count")))
        if r["n"] * r["step"] > t:
            iss.append(Issue("info", "The widest slot is more than a board wider than the board.", ("count", "step")))

    PER_ROW = 4

    def build(self, c, r):
        t, pw, ph, d, n = c.t, r["pw"], r["ph"], r["d"], r["n"]
        gap = max(c.mm_(5), 2 * t)
        out = []
        items = [("key", 0.0, 0)] + [(f"s{i + 1}", w, i + 1) for i, w in enumerate(fit_widths(t, r["step"], n))]
        for k, (nm, w, notches) in enumerate(items):
            row, col = divmod(k, self.PER_ROW)
            x, y = col * (pw + gap), -row * (ph + gap)
            if nm == "key":                        # the plain plate to push in: as tall as a slot is deep, plus a handle
                pts = [(x, y), (x + pw, y), (x + pw, y + ph), (x, y + ph)]
            else:
                pts = _fit_outline(x, y, pw, ph, w, d, notches, r["nt"])
            out.append(Panel(nm, pts, None, None, 90.0, "body"))
        return out, None

    rounded_folds = False
    tol_keys = ("panel", "slot", "overall_len", "overall_h")
    draw_sub = "Slot-fit test coupon"
    draw_cap = "SLOT TEST"
    anchor_panel = None
    step_text = {"flat": "As cut: the key plate and the numbered plates, flat.",
                 "partial": "As cut: the key plate and the numbered plates, flat.",
                 "folded": "As cut: the key plate and the numbered plates, flat."}
    step_amount = 0.5
    view_title = "TEST PLATES (NOT TO SCALE)"
    table_title = "TEST SIZES"
    steps_note = "(not to scale; board drawn at full thickness)"

    def view_caption(self, res, units):
        a = res.info["auto"]
        t = res.spec.t
        return f"{a['n']} slots, {_fnum(t, units)} to {_fnum(t + (a['n'] - 1) * a['step'], units)} {units} wide"

    def bend_notes(self, rep):
        return ["The test plates are flat: there are no folds, so this page does not change the dieline."]

    def tol_note(self, f, units):
        return f"Tolerances (± {units}): plates {f('panel')}; slots {f('slot')}; blank {f('overall_len')} x {f('overall_h')}."

    def dim_field(self, dm, res, spec):
        tag = dm.get("tag", "")
        if tag.startswith("plate"):
            return "L", None
        if tag == "height":
            return "W", None
        return None

    def dimensions(self, res, spec):
        pans = list(res.panels)
        tv = res.info["tol"]["values"]
        bb = {p.name: _bbox(p) for p in pans}
        top = max(b[3] for b in bb.values())
        first = sorted((b for b in bb.values() if abs(b[3] - top) < 1e-6), key=lambda b: b[0])
        out = [dict(kind="h", row=1, a=b[0], b=b[2], v=b[2] - b[0], tol=tv["panel"], ref=top, tag="plate%d" % i)
               for i, b in enumerate(first[:2])]
        xl, xr = min(b[0] for b in bb.values()), max(b[2] for b in bb.values())
        out.append(dict(kind="h", row=2, a=xl, b=xr, v=xr - xl, tol=tv["overall_len"], ref=top, tag="overall_len"))
        f = first[0]
        out.append(dict(kind="v", row=1, a=f[1], b=f[3], v=f[3] - f[1], tol=tv["overall_h"], ref=xr, tag="height"))
        return out

    def size_rows(self, c):
        a, u = c.a, c.units
        ws = fit_widths(c.t, a["step"], a["n"])
        return [("Plate L × H", f"{_fnum(a['pw'], u)} × {_fnum(a['ph'], u)}"),
                ("Slot depth", c.fnum(a["d"], u)), c.flat, ("Board thickness", c.fnum(c.t, u)),
                ("Slot widths", f"{_fnum(ws[0], u)} to {_fnum(ws[-1], u)}, step {_fnum(a['step'], u)}"),
                ("Number of slots", str(a["n"])), ("Units", u)]

    def drawing_notes(self, res, units):
        a = res.info["auto"]
        return ["Push the edge of the key plate into each numbered slot. The number of notches on a plate's bottom edge "
                "is its slot number (1 = the narrowest).",
                "Use the narrowest slot the key slides into with a light push and no rattle as the 'Slot width' option of "
                "the dividers and inserts. Test on the board you will really cut: laser kerf and board thickness vary."]

    def fold_sequence(self, panels, t, amount):
        return (lambda p, d, m: 0.0), None, None


register_style(FitTest())
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
    counts = tuple(getattr(style, "count_keys", ())) + tuple(getattr(style, "zero_ok", ()))
    for key, v in spec.opts.items():
        if v is not None and (not math.isfinite(v) or v < 0 or (v == 0 and key not in counts)):
            iss.append(Issue("error", "Advanced values must be positive numbers (leave blank for automatic).", (key,)))
    kerf = spec.kerf or 0.0
    if not math.isfinite(kerf) or kerf < 0:
        iss.append(Issue("error", "Kerf must be zero or a positive number.", ("kerf",)))
    if spec.perf:
        for key, lo, hi, nm in (("perf_dash", 1.0, 20.0, "Dash length"), ("perf_tie", 0.5, 10.0, "Bridge spacing")):
            v = getattr(spec, key)
            if not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
                iss.append(Issue("error", f"{nm} must be between {lo:g} and {hi:g} mm.", (key,)))
    try:
        res.look = resolve_look(spec.look)
        if res.look["cut_pt"] == res.look["fold_pt"]:
            iss.append(Issue("warn", "Cut and fold lines have the same weight. Software that sorts by line "
                                     "weight will not tell them apart.", ("cut_weight", "fold_weight")))
        if res.look["cut_hex"] == res.look["fold_hex"]:
            iss.append(Issue("info", "Cut and fold lines have the same colour.", ()))
    except (ValueError, TypeError) as exc:
        res.look = resolve_look()
        bad = ("cut_weight", "fold_weight", "engrave_weight") if "weight" in str(exc) else ()
        iss.append(Issue("error", f"Line settings: {exc}.", bad))
    for key, label in (("L", "Length"), ("W", "Width"), ("H", style.height_label)):
        v = getattr(spec, key) * mm
        if v > 10000:
            iss.append(Issue("error", f"{label} is over 10 metres: check the units and the decimal point.", (key,)))
        elif v > 2500:
            iss.append(Issue("warn", f"{label} is over 2.5 metres. Check the units and the decimal point.", (key,)))
    if res.errors:
        return res

    t = spec.t
    try:
        Lc, Wc, Hc = style.crease_for(spec)
    except KeyError:
        iss.append(Issue("error", "Unknown dimension mode.", ()))
        return res
    c = Ctx(spec, Lc, Wc, Hc)
    Li, Wi, Hi = style.inner_for(spec, Lc, Wc, Hc)
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
        hand_drawn = drawing is not None
        if drawing is None:
            drawing = panels_to_drawing(panels, spec.folds)
        res.nominal = drawing
        kpan = panels
        if kerf > 0 and hand_drawn:
            kpan = style.kerf_panels(c, r) if hasattr(style, "kerf_panels") else None
            if kpan is None:
                iss.append(Issue("warn", "Kerf compensation is not available for this style yet; the dieline is "
                                         "at nominal size.", ("kerf",)))
        if kerf > 0 and kpan is not None:
            if kerf * mm > 1.0:
                iss.append(Issue("warn", "Kerf over 1 mm is unusual for a laser (typically 0.1-0.5 mm). Check the "
                                         "units.", ("kerf",)))
            try:
                drawing = kerf_drawing(kpan, drawing, kerf)
                res.info["kerf"] = kerf
                sw_ = getattr(drawing, "swallowed", [])
                if sw_:
                    iss.append(Issue("warn", f"The kerf is wider than a few tiny gaps in this layout, so {len(sw_)} very "
                                             f"short cut edge(s) were merged into their neighbours (near "
                                             f"{', '.join(f'({x:g}, {y:g})' for x, y in sw_[:3])}). Check those "
                                             f"corners on a test cut.", ("kerf",)))
                iss.append(Issue("info", f"Kerf compensation applied: cut lines moved {fmt(kerf / 2, 3)} "
                                         f"{spec.units} away from the parts (half the {fmt(kerf, 3)} kerf).", ()))
            except ValueError as exc:
                iss.append(Issue("error", f"Kerf compensation failed: {exc}. Reduce the kerf or enlarge the "
                                          f"small features.", ("kerf",)))
                return res
        if spec.perf and spec.folds:
            dash_mm, tie_mm = spec.perf_dash, spec.perf_tie
            drawing, nd, ns = perforate(drawing, dash_mm / mm, tie_mm / mm, res.info.get("kerf", 0.0))
            res.info["perf"] = (nd, ns)
            msg = (f"Fold lines drawn as dashed cuts ({nd} lines, {dash_mm:g} mm cuts with {tie_mm:g} mm bridges).")
            if ns:
                msg += f" {ns} short fold line{'s' if ns > 1 else ''} kept as scored lines."
            iss.append(Issue("info", msg, ()))
            if t * mm > 3 and tie_mm < 3:
                iss.append(Issue("warn", f"Dashed folds on thick board leave weak {tie_mm:g} mm bridges; test a "
                                         f"sample, board over 3 mm may need longer bridges.", ("t",)))
            if tie_mm > dash_mm:
                iss.append(Issue("warn", f"The bridges ({tie_mm:g} mm) are longer than the cuts ({dash_mm:g} mm), so "
                                         f"the fold may not bend cleanly. Lengthen the dashes or shorten the "
                                         f"bridges.", ("perf_dash", "perf_tie")))
        if spec.features:
            nf = apply_features(drawing, panels, spec.features, t, mm, kerf, iss)
            res.info["features"] = nf
            if any(f.kind != "window" for f in spec.features) and res.look["engrave_pt"] in (res.look["cut_pt"], res.look["fold_pt"]):
                iss.append(Issue("warn", "Engrave lines share a weight with cut or fold lines, so software that sorts "
                                         "by line weight cannot separate them.", ("engrave_weight",)))
            if nf:
                iss.append(Issue("info", f"{nf} window / zone feature{'s' if nf > 1 else ''} added.", ()))
        if True:                                           # tolerances for the drawing sheet (every style)
            fx0, fy0, fx1, fy1 = drawing.bounds()
            tv, ta, ti = resolve_tolerances(t * mm, (fx1 - fx0) * mm, (fy1 - fy0) * mm, spec.tol,
                                            getattr(style, "auto_tol", None))
            res.info["tol"] = dict(values=tv, auto=ta)
            for lvl, msg, key in ti:
                iss.append(Issue(lvl, msg, ("tol_" + key,)))
            if res.errors:
                return res
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
# Line colours and weights
#   Every preset is an exact AutoCAD colour-index (ACI) colour, so DXF exports carry the same colour.
#   Weights are written exactly (points) into SVG, PDF and EPS; DXF (R12), HPGL and G-code cannot carry them.
# =============================================================================
LINE_COLORS = [("Blue", "#0000FF", 5), ("Red", "#FF0000", 1), ("Black", "#000000", 7), ("Green", "#00FF00", 3),
               ("Cyan", "#00FFFF", 4), ("Magenta", "#FF00FF", 6), ("Yellow", "#FFFF00", 2),
               ("Orange", "#FF7F00", 30), ("Amber", "#FFBF00", 40), ("Lime", "#7FFF00", 70),
               ("Spring green", "#00FF7F", 110), ("Sky blue", "#007FFF", 150), ("Violet", "#7F00FF", 190),
               ("Pink", "#FF007F", 230), ("Gray", "#808080", 8), ("Light gray", "#C0C0C0", 9)]
LOOK_DEFAULTS = dict(cut_color="Blue", fold_color="Red", cut_weight=0.1, fold_weight=1.0,
                     engrave_color="Green", engrave_weight=0.5)
WEIGHT_NOTE = "Custom line weights apply to SVG, PDF and EPS only."


def resolve_look(look=None):
    """Validate a {cut_color, fold_color, cut_weight, fold_weight} dict -> hex / ACI / points for the writers."""
    lk = dict(LOOK_DEFAULTS)
    lk.update({k: v for k, v in (look or {}).items() if v is not None})
    by = {n.lower(): (h, a, n) for n, h, a in LINE_COLORS}
    out = {}
    for layer in ("cut", "fold", "engrave"):
        key = str(lk[layer + "_color"]).strip().lower()
        if key not in by:
            raise ValueError(f"unknown {layer} colour '{lk[layer + '_color']}'")
        out[layer + "_hex"], out[layer + "_aci"], out[layer + "_name"] = by[key]
        w = float(lk[layer + "_weight"])
        if not math.isfinite(w) or w <= 0:
            raise ValueError(f"{layer} weight must be a number greater than zero")
        out[layer + "_pt"] = w
    return out


def _rgb01(hexs):
    return tuple(int(hexs[i:i + 2], 16) / 255 for i in (1, 3, 5))


def view_color(hexs):
    """Colour used on the dark preview canvas: dark presets are lightened so they stay visible."""
    r, g, b = (int(hexs[i:i + 2], 16) for i in (1, 3, 5))
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    if lum < 0.45:
        t = 0.45 if lum < 0.1 else 0.3
        r, g, b = (round(c + (255 - c) * t) for c in (r, g, b))
        if lum < 0.05:
            r = g = b = 225
    return f"#{r:02x}{g:02x}{b:02x}"


# =============================================================================
# Exporters
# =============================================================================
def to_dxf(d, units="mm", notes=(), look=None):
    lk = look or resolve_look()
    out = []
    w = lambda code, val: out.extend([str(code), str(val)])
    f = lambda v: f"{v:.5f}"
    w(999, "BoxForge DXF - drawing units: " + ("millimetres" if units == "mm" else "inches")
      + " (also stored in $INSUNITS; some importers ignore it, so check the scale on import)")
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
    w(0, "TABLE"); w(2, "LAYER"); w(70, 3)
    for name, col in ((CUT, lk["cut_aci"]), (FOLD, lk["fold_aci"]), (ENGRAVE, lk["engrave_aci"])):
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


def _chain_segs(segs, eps=1e-3):
    """Join segments (p, q, arc) that share endpoints into chains, reversing where needed.
    An arc is (radius, large_flag, sweep_flag); reversing one flips its sweep.
    Slits that end free (a cut that stops inside the board, or runs out onto an outline) are set aside first, so the
    segments left form closed loops and each comes out as one closed chain; the slits follow as open chains of their own."""
    segs = list(segs)
    pts = [pt for sg in segs for pt in sg[:2]]
    out = []
    for a, b, arc in segs:                            # split a line wherever another segment's end lands on it (a T-junction)
        if arc is None:
            L2 = (b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2
            cuts = []
            for pt in pts:
                if L2 > 0:
                    u = ((pt[0] - a[0]) * (b[0] - a[0]) + (pt[1] - a[1]) * (b[1] - a[1])) / L2
                    if 0 < u < 1 and math.dist(pt, (a[0] + u * (b[0] - a[0]), a[1] + u * (b[1] - a[1]))) < eps \
                            and math.dist(pt, a) > eps and math.dist(pt, b) > eps:
                        cuts.append((u, pt))
            if cuts:
                cuts.sort()
                chain_pts = [a] + [pt for _, pt in cuts] + [b]
                for k in range(len(chain_pts) - 1):
                    if math.dist(chain_pts[k], chain_pts[k + 1]) > eps:
                        out.append((chain_pts[k], chain_pts[k + 1], None))
                continue
        out.append((a, b, arc))
    segs = out
    n = len(segs)

    def flip(sg):
        a, b, arc = sg
        return (b, a, None if arc is None else (arc[0], arc[1], 1 - arc[2]))

    def heading(a, b):
        return math.atan2(b[1] - a[1], b[0] - a[0])

    core = set(range(n))
    changed = True
    while changed:                                     # peel off segments with a free end, repeatedly
        changed = False
        for i in sorted(core):
            for pt in segs[i][:2]:
                if not any(j != i and (math.dist(segs[j][0], pt) < eps or math.dist(segs[j][1], pt) < eps) for j in core):
                    core.discard(i)
                    changed = True
                    break

    def build(allowed):
        used = {i: False for i in allowed}

        def pick(point, direction):
            best, bi, bflip = None, None, False
            for i in allowed:
                if used[i]:
                    continue
                sg = segs[i]
                for fl, (p, q) in ((False, (sg[0], sg[1])), (True, (sg[1], sg[0]))):
                    if math.dist(p, point) < eps:
                        turn = abs((heading(p, q) - direction + math.pi) % (2 * math.pi) - math.pi)
                        if best is None or turn < best:
                            best, bi, bflip = turn, i, fl
            return bi, bflip

        out = []
        for i0 in sorted(allowed):
            if used[i0]:
                continue
            used[i0] = True
            chain = [segs[i0]]
            while not (len(chain) > 1 and math.dist(chain[-1][1], chain[0][0]) < eps):
                i, fl = pick(chain[-1][1], heading(*chain[-1][:2]))
                if i is None:
                    break
                used[i] = True
                chain.append(flip(segs[i]) if fl else segs[i])
            if not (len(chain) > 1 and math.dist(chain[-1][1], chain[0][0]) < eps):
                while True:                            # an open chain: also grow it backwards from its start
                    i, fl = pick(chain[0][0], heading(chain[0][1], chain[0][0]))
                    if i is None:
                        break
                    used[i] = True
                    chain.insert(0, segs[i] if fl else flip(segs[i]))
            out.append(chain)
        return out

    return build(core) + build(set(range(n)) - core)


def to_svg(d, units="mm", margin=5.0, notes=(), look=None):
    """SVG at true size. Coordinates are in points (1 user unit = 1 pt), so stroke-width is the exact weight in pt."""
    lk = look or resolve_look()
    k = 72 / 25.4 if units == "mm" else 72.0
    x0, y0, x1, y1 = d.bounds()
    mg = margin if units == "mm" else margin / 25.4
    x0 -= mg; y0 -= mg; x1 += mg; y1 += mg
    W, H = (x1 - x0) * k, (y1 - y0) * k
    X = lambda x: (x - x0) * k
    Y = lambda y: (y1 - y) * k
    groups = {CUT: [], FOLD: [], ENGRAVE: []}
    segs = {CUT: [], FOLD: [], ENGRAVE: []}
    for it in d.items:
        if it[0] == "L":
            _, p, q, layer = it
            segs[layer].append((tuple(p), tuple(q), None))
        else:
            _, c, r, a0, a1, layer = it
            span = (a1 - a0) % 360
            sx, sy = c[0] + r * math.cos(math.radians(a0)), c[1] + r * math.sin(math.radians(a0))
            ex_, ey = c[0] + r * math.cos(math.radians(a1)), c[1] + r * math.sin(math.radians(a1))
            segs[layer].append(((sx, sy), (ex_, ey), (r, 1 if span > 180 else 0, 0)))
    eps = 0.001 / (25.4 if units == "in" else 1.0)     # 1 micron: the rebuilt edges differ by ~1e-6 in an inch job
    for layer, sl in segs.items():
        for chain in _chain_segs(sl, eps):
            a = chain[0][0]
            dstr = f"M {X(a[0]):.4f} {Y(a[1]):.4f}"
            for (pa, pb, arc) in chain:
                if arc is None:
                    dstr += f" L {X(pb[0]):.4f} {Y(pb[1]):.4f}"
                else:
                    r_, large, sweep = arc
                    dstr += f" A {r_ * k:.4f} {r_ * k:.4f} 0 {large} {sweep} {X(pb[0]):.4f} {Y(pb[1]):.4f}"
            closed = math.dist(chain[0][0], chain[-1][1]) < eps and len(chain) > 1
            groups[layer].append(f'<path d="{dstr}{" Z" if closed else ""}"/>')
    spec = {CUT: (lk["cut_hex"], lk["cut_pt"]), FOLD: (lk["fold_hex"], lk["fold_pt"]),
            ENGRAVE: (lk["engrave_hex"], lk["engrave_pt"])}
    body = "\n".join(
        f'<g id="{key}" fill="none" stroke="{spec[key][0]}" stroke-width="{spec[key][1]:g}" '
        f'stroke-linecap="round">\n' + "\n".join(v) + "\n</g>" for key, v in groups.items() if v or key != ENGRAVE)
    desc = f"<desc>{_xml(' | '.join(notes))}</desc>\n" if notes else ""
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.4f}pt" height="{H:.4f}pt" '
            f'viewBox="0 0 {W:.4f} {H:.4f}">\n{desc}{body}\n</svg>\n')


# =============================================================================
# More export formats: PDF, EPS, HPGL, G-code
# =============================================================================
GCODE_DEFAULTS = dict(cut_power=1000, cut_feed=600, cut_passes=1, fold_power=200, fold_feed=1500, fold_passes=1,
                      engrave_power=250, engrave_feed=3000, engrave_passes=1)


def _flatten(d, units="mm"):
    """{layer: [polyline, ...]} with arcs flattened to <= 0.01 mm chord error."""
    tol = 0.01 / (25.4 if units == "in" else 1.0)
    out = {CUT: [], FOLD: [], ENGRAVE: []}
    for it in d.items:
        if it[0] == "L":
            out[it[-1]].append([it[1], it[2]])
        else:
            _, c, r, a0, a1, layer = it
            span = (a1 - a0) % 360 or 360
            step = math.degrees(2 * math.acos(max(0.0, 1 - tol / r))) if r > tol else 30.0
            n = max(2, int(math.ceil(span / max(step, 0.5))))
            out[layer].append([(c[0] + r * math.cos(math.radians(a0 + span * k / n)),
                                c[1] + r * math.sin(math.radians(a0 + span * k / n))) for k in range(n + 1)])
    return out


def _ascii(s):
    return s.encode("ascii", "replace").decode("ascii").replace("\n", " ")


def to_pdf(d, units="mm", margin=5.0, notes=(), look=None):
    """Vector PDF at true size (1 page, exact line weights in pt). Returns bytes."""
    lk = look or resolve_look()
    k = 72 / 25.4 if units == "mm" else 72.0
    mg = margin if units == "mm" else margin / 25.4
    x0, y0, x1, y1 = d.bounds()
    x0 -= mg; y0 -= mg; x1 += mg; y1 += mg
    W, H = (x1 - x0) * k, (y1 - y0) * k
    fl = _flatten(d, units)
    cs = ["1 J 1 j"]
    for layer, hx, wt in ((FOLD, lk["fold_hex"], lk["fold_pt"]), (ENGRAVE, lk["engrave_hex"], lk["engrave_pt"]),
                          (CUT, lk["cut_hex"], lk["cut_pt"])):
        cs.append(f"{wt:g} w")
        cs.append(" ".join(f"{c:.4f}".rstrip("0").rstrip(".") or "0" for c in _rgb01(hx)) + " RG")
        for pl in fl[layer]:
            pts = [f"{(p[0] - x0) * k:.3f} {(p[1] - y0) * k:.3f}" for p in pl]
            cs.append(pts[0] + " m " + " ".join(q + " l" for q in pts[1:]) + " S")
    stream = ("\n".join(cs)).encode("ascii")
    esc = lambda s: _ascii(s).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W:.2f} {H:.2f}] /Contents 4 0 R /Resources << >> >>".encode(),
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            f"<< /Title (BoxForge dieline) /Subject ({esc(' | '.join(notes))}) /Creator (BoxForge) >>".encode()]
    out = bytearray(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xr = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info 5 0 R >>\nstartxref\n{xr}\n%%EOF\n".encode()
    return bytes(out)


def to_eps(d, units="mm", margin=5.0, notes=(), look=None):
    """Encapsulated PostScript at true size (opens in Illustrator / Inkscape / Ghostscript).
    Coordinates are pre-scaled to points, so setlinewidth is the exact weight in pt."""
    lk = look or resolve_look()
    k = 72 / 25.4 if units == "mm" else 72.0
    mg = margin if units == "mm" else margin / 25.4
    x0, y0, x1, y1 = d.bounds()
    x0 -= mg; y0 -= mg; x1 += mg; y1 += mg
    W, H = (x1 - x0) * k, (y1 - y0) * k
    o = ["%!PS-Adobe-3.0 EPSF-3.0", f"%%BoundingBox: 0 0 {int(math.ceil(W))} {int(math.ceil(H))}",
         "%%Creator: BoxForge", "%%EndComments"]
    o += ["% " + _ascii(n) for n in notes]
    o += ["1 setlinecap 1 setlinejoin"]
    X = lambda x: (x - x0) * k
    Y = lambda y: (y - y0) * k
    for layer, hx, wt in ((FOLD, lk["fold_hex"], lk["fold_pt"]), (ENGRAVE, lk["engrave_hex"], lk["engrave_pt"]),
                          (CUT, lk["cut_hex"], lk["cut_pt"])):
        o.append(f"{wt:g} setlinewidth")
        o.append(" ".join(f"{c:.4f}".rstrip("0").rstrip(".") or "0" for c in _rgb01(hx)) + " setrgbcolor")
        for it in d.items:
            if it[-1] != layer:
                continue
            if it[0] == "L":
                o.append(f"newpath {X(it[1][0]):.4f} {Y(it[1][1]):.4f} moveto {X(it[2][0]):.4f} "
                         f"{Y(it[2][1]):.4f} lineto stroke")
            else:
                _, c, r, a0, a1, _l = it
                if a1 <= a0:
                    a1 += 360
                o.append(f"newpath {X(c[0]):.4f} {Y(c[1]):.4f} {r * k:.4f} {a0:.4f} {a1:.4f} arc stroke")
    o.append("showpage")
    return "\n".join(o) + "\n"


def to_hpgl(d, units="mm", notes=()):
    """HPGL (.plt), 40 units/mm. Pen 3 = ENGRAVE, pen 2 = FOLD, pen 1 = CUT. Origin = bottom-left of the sheet."""
    s = 40.0 if units == "mm" else 1016.0
    x0, y0, _x1, _y1 = d.bounds()
    fl = _flatten(d, units)
    o = ["IN;"]
    for layer, pen in ((FOLD, 2), (ENGRAVE, 3), (CUT, 1)):
        o.append(f"SP{pen};")
        for pl in fl[layer]:
            pts = [(int(round((p[0] - x0) * s)), int(round((p[1] - y0) * s))) for p in pl]
            o.append(f"PU{pts[0][0]},{pts[0][1]};PD" + ",".join(f"{x},{y}" for x, y in pts[1:]) + ";")
    o += ["PU;", "SP0;"]
    return "\n".join(o) + "\n"


def to_gcode(d, units="mm", notes=(), **kw):
    """GRBL-style laser G-code in mm (M4 dynamic power). Engraving first, then scores, then cuts. Origin = bottom-left."""
    p = dict(GCODE_DEFAULTS)
    p.update(kw)
    m = 25.4 if units == "in" else 1.0
    x0, y0, _x1, _y1 = d.bounds()
    fx = lambda v: (v - x0) * m
    fy = lambda v: (v - y0) * m
    out = [f"( {_ascii(n).replace('(', '[').replace(')', ']')} )" for n in notes]
    out.append("( GRBL laser mode: set $32=1 first so S power follows motion; M4 needs it. Not tested on every controller. )")
    out += ["G21 G90 G17", "M5"]
    for layer, pw, fd, ps in ((ENGRAVE, p["engrave_power"], p["engrave_feed"], p["engrave_passes"]),
                              (FOLD, p["fold_power"], p["fold_feed"], p["fold_passes"]),
                              (CUT, p["cut_power"], p["cut_feed"], p["cut_passes"])):
        prims = []
        for it in d.items:
            if it[-1] != layer:
                continue
            if it[0] == "L":
                prims.append(("L", (fx(it[1][0]), fy(it[1][1])), (fx(it[2][0]), fy(it[2][1])), None, 0))
            else:
                _, c, r, a0, a1, _l = it
                pa = (fx(c[0] + r * math.cos(math.radians(a0))), fy(c[1] + r * math.sin(math.radians(a0))))
                pb = (fx(c[0] + r * math.cos(math.radians(a1))), fy(c[1] + r * math.sin(math.radians(a1))))
                prims.append(("A", pa, pb, (fx(c[0]), fy(c[1])), r * m))
        if not prims:
            continue
        out.append(f"( {'SCORE' if layer == FOLD else 'ENGRAVE' if layer == ENGRAVE else 'CUT'} layer: S{int(pw)} F{fd:g} x{int(ps)} pass(es) )")
        out.append(f"M4 S{int(pw)}")
        for n in range(int(ps)):
            todo, cur = list(prims), (0.0, 0.0)
            while todo:
                best, bi, brev = None, 0, False
                for i, pr in enumerate(todo):
                    for rev in (False, True):
                        a = pr[2] if rev else pr[1]
                        dd = (a[0] - cur[0]) ** 2 + (a[1] - cur[1]) ** 2
                        if best is None or dd < best:
                            best, bi, brev = dd, i, rev
                kind, a, b, c, r = todo.pop(bi)
                if brev:
                    a, b = b, a
                if math.dist(a, cur) > 1e-4:
                    out.append(f"G0 X{a[0]:.3f} Y{a[1]:.3f}")
                if kind == "L":
                    out.append(f"G1 X{b[0]:.3f} Y{b[1]:.3f} F{fd:g}")
                else:
                    out.append(f"{'G2' if brev else 'G3'} X{b[0]:.3f} Y{b[1]:.3f} I{c[0] - a[0]:.3f} "
                               f"J{c[1] - a[1]:.3f} F{fd:g}")
                cur = b
        out.append("M5")
    out += ["G0 X0 Y0", "M2"]
    return "\n".join(out) + "\n"


# ---- export-format registry -------------------------------------------------
# To add a format: write `to_xxx(d, units, notes, look, gcode)`-style code, then register it
# once here.  The GUI export row, the CLI flag (--<flag>) and render_export() all read this list.
class ExportFormat:
    def __init__(self, kind, label, render, flag=None, weights=False, cli_rank=None):
        self.kind, self.label, self.render = kind, label, render
        self.flag = flag or kind          # CLI option name: --<flag> PATH
        self.cli_rank = cli_rank          # position among the CLI flags / "wrote" lines (default: GUI order)
        self.weights = weights            # True when custom cut/fold line weights apply


EXPORT_REGISTRY = []
EXPORT_BY_KIND = {}


def register_export(kind, label, render, flag=None, weights=False, cli_rank=None):
    """render(d, units, notes, gcode, look) -> str | bytes"""
    f = ExportFormat(kind, label, render, flag, weights, cli_rank)
    EXPORT_REGISTRY.append(f)
    EXPORT_BY_KIND[kind] = f
    _refresh_export_views()
    return f


def _refresh_export_views():
    """Keep the derived lists in step with the registry (they are edited in place so importers see the change)."""
    CLI_FORMATS[:] = sorted(EXPORT_REGISTRY, key=lambda f: f.cli_rank if f.cli_rank is not None else 99)
    EXPORT_FORMATS[:] = [(f.kind, f.label) for f in EXPORT_REGISTRY]
    WEIGHT_FORMATS[:] = [f.kind for f in EXPORT_REGISTRY if f.weights]


CLI_FORMATS, EXPORT_FORMATS, WEIGHT_FORMATS = [], [], []         # flag order / GUI row / formats with line weights


register_export("dxf", "DXF", lambda d, u, n, g, lk: to_dxf(d, u, n, lk), cli_rank=1)
register_export("svg", "SVG", lambda d, u, n, g, lk: to_svg(d, u, notes=n, look=lk), weights=True, cli_rank=0)
register_export("pdf", "PDF", lambda d, u, n, g, lk: to_pdf(d, u, notes=n, look=lk), weights=True, cli_rank=2)
register_export("eps", "EPS", lambda d, u, n, g, lk: to_eps(d, u, notes=n, look=lk), weights=True, cli_rank=3)
register_export("plt", "HPGL", lambda d, u, n, g, lk: to_hpgl(d, u, n), cli_rank=4)
register_export("nc", "G-code", lambda d, u, n, g, lk: to_gcode(d, u, n, **(g or {})), flag="gcode", cli_rank=5)
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


# =============================================================================
# Drawing tolerances (RSC). Values in millimetres, plus/minus.
# =============================================================================
TOL_LABELS = {
    "panel": "Panel width / height (score to score)",
    "flap": "Flap length (score to cut)",
    "slot": "Slot width",
    "glue": "Glue flap width",
    "overall_len": "Overall blank length",
    "overall_h": "Overall blank height",
    "box": "Finished box size",
}
TOL_MIN_MM, TOL_MAX_MM = 0.1, 10.0


def _r05(x):
    """Round to the nearest 0.5 mm (halves round up)."""
    return math.floor(x * 2 + 0.5) / 2


def auto_tolerances(t_mm, len_mm, h_mm):
    """Typical corrugated-converter tolerances, +/- mm, scaled with board thickness.
    Score-to-score +/-1.5 mm on ~3 mm board (rising ~0.2 mm per mm of board), flaps and slots slightly looser
    because they are cut, glue flap and overall blank about twice the score tolerance, +0.5 mm per 500 mm of
    blank beyond 1 m."""
    panel = _r05(max(1.0, 1.0 + 0.2 * t_mm))
    extra = lambda size: 0.5 * math.floor(max(0.0, size - 1000.0) / 500.0)
    return {
        "panel": panel,
        "flap": panel + 0.5,
        "slot": _r05(max(1.0, 0.25 * t_mm + 0.5)),
        "glue": _r05(max(2.0, 2 * panel)),
        "overall_len": _r05(2 * panel + extra(len_mm)),
        "overall_h": _r05(2 * panel + extra(h_mm)),
        "box": _r05(2 * panel),
    }


def resolve_tolerances(t_mm, len_mm, h_mm, override=None, style_auto=None):
    """-> (values, auto_flags, issues[(level, msg, key)]). `override` maps key -> mm (None/blank = automatic)."""
    vals = auto_tolerances(t_mm, len_mm, h_mm)
    vals.update(style_auto or {})                      # a style whose parts are cut tighter than a die-cut flap slot
    auto = {k: True for k in vals}
    issues = []
    for k, v in (override or {}).items():
        if k not in vals or v is None:
            continue
        if not isinstance(v, (int, float)) or not math.isfinite(v) or not TOL_MIN_MM <= v <= TOL_MAX_MM:
            issues.append(("error", f"{TOL_LABELS.get(k, k)} tolerance must be between {TOL_MIN_MM:g} and "
                                    f"{TOL_MAX_MM:g} mm.", k))
            continue
        vals[k], auto[k] = float(v), False
        if v < 0.25:
            issues.append(("warn", f"{TOL_LABELS[k]} tolerance of ±{v:g} mm is tighter than corrugated board can "
                                   f"reliably hold.", k))
        elif v > 5:
            issues.append(("warn", f"{TOL_LABELS[k]} tolerance of ±{v:g} mm is very loose.", k))
    return vals, auto, issues


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
# =============================================================================
# 3-D model of the cross / grid divider: flat slotted panels that move into place and slide together
# =============================================================================
def _smooth(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


def fold_grid(panels, t, prog_of, box=None, hover=0.0, flute=None):
    """Thick model of the dividers at progress p = prog_of (0 = lying flat as cut, 1 = assembled). Each panel is a slab:
        0.0 - 0.2   the lengthwise dividers move out across the box, each to its own place
        0.2 - 0.4   they come down to the floor; the crosswise ones rise, still in a sheet, clear of the others
        0.4 - 0.6   all slide to the middle along the box; the crosswise ones turn a quarter turn to cross
        0.6 - 1.0   the crosswise dividers are lowered over the lengthwise ones until the slots meet
    `box` = (cx, y, cz, top, ext) of the box they go into (None = alone, centred on the origin standing on y = 0);
    `hover` (1 = held above the open box, 0 = in place) lifts everything by that share of the way over its walls.
    Returns _Faces [(panel, kind, points, role)] or None."""
    pans = [p for p in panels if p.meta and p.meta.get("kind") == "grid"]
    if not pans or t <= 0:
        return None
    m0 = pans[0].meta
    Hs = m0["Hs"]
    clamp = lambda v: min(1.0, max(0.0, v))
    p = clamp(prog_of(pans[0], 1, 1))
    cx, ybase, cz, top, ext = box if box else (0.0, 0.0, 0.0, Hs, None)
    along_x = True                                           # the box's length runs along x unless its walls say otherwise
    if ext is not None:
        lx, lz = ext[1] - ext[0], ext[3] - ext[2]
        along_x = abs(lx - m0["Li"]) + abs(lz - m0["Wi"]) <= abs(lz - m0["Li"]) + abs(lx - m0["Wi"]) + 1e-9
    ax = (1.0, 0.0, 0.0) if along_x else (0.0, 0.0, 1.0)     # along the box's length
    bx = (0.0, 0.0, 1.0) if along_x else (1.0, 0.0, 0.0)     # across its width
    Y = (0.0, 1.0, 0.0)
    y_rest = ybase + (hover * (top - ybase + 0.12 * Hs) if (box and hover > 0.0) else 0.0)
    boxes = [_bbox(pn) for pn in pans]
    xmin, ymin = min(b[0] for b in boxes), min(b[1] for b in boxes)
    xmax = max(b[2] for b in boxes)
    lay_cx = (xmin + xmax) / 2.0
    cross_y = [y_rest + (bb[1] - ymin) for pn, bb in zip(pans, boxes) if pn.meta["role"] == "w"]
    shift = max(0.0, y_rest + 1.12 * Hs - min(cross_y)) if cross_y else 0.0   # a crosswise sheet rises this far
    s_b, s_y = _smooth(p / 0.2), _smooth((p - 0.2) / 0.2)
    s_a, s_d = _smooth((p - 0.4) / 0.2), _smooth((p - 0.6) / 0.4)
    faces = _Faces()
    faces.flute = flute
    for pn, bb in zip(pans, boxes):
        m = pn.meta
        L = m["L"]
        a_flat = (bb[0] + bb[2]) / 2.0 - lay_cx                # where it lies on the sheet (relative to the middle)
        y_flat = y_rest + (bb[1] - ymin)
        if m["role"] == "l":
            b = m["zs"][m["idx"]] * s_b
            y = y_flat + (y_rest - y_flat) * s_y
            a = a_flat * (1.0 - s_a)
            eu, en = ax, bx
        else:
            b = 0.0
            y_hi = y_flat + shift
            y = y_flat + shift * s_y if p < 0.6 else y_hi + (y_rest - y_hi) * s_d
            a = a_flat + (m["xs"][m["idx"]] - a_flat) * s_a
            ph = 0.5 * math.pi * s_a
            eu = tuple(math.cos(ph) * ax[i] + math.sin(ph) * bx[i] for i in range(3))
            en = tuple(math.cos(ph) * bx[i] - math.sin(ph) * ax[i] for i in range(3))
        c = tuple((cx, 0.0, cz)[i] + ax[i] * a + bx[i] * b + Y[i] * (y + Hs / 2.0) for i in range(3))
        O = tuple(c[i] - eu[i] * L / 2.0 - Y[i] * Hs / 2.0 - en[i] * t / 2.0 for i in range(3))
        for suffix, poly, js in grid_pieces(L, Hs, m["slots"], m["slot"], m["d"], m["role"] == "l"):
            _fm_slab(faces, poly, O, eu, Y, en, t, f"{pn.name}~{suffix}", "body", js)
    return faces
# =============================================================================
# Engineering drawing sheet (PDF) for the Slotted Box (RSC)
# =============================================================================
_HV_W = {"F1": [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584, 761, 556, 556, 222, 556, 333, 1000, 556, 556, 333, 1000, 667, 333, 1000, 556, 611, 556, 556, 222, 222, 333, 333, 350, 556, 1000, 333, 1000, 500, 333, 944, 556, 500, 667, 278, 333, 556, 556, 556, 556, 260, 556, 333, 737, 370, 556, 584, 333, 737, 333, 400, 584, 333, 333, 333, 556, 537, 278, 333, 333, 365, 556, 834, 834, 834, 611, 667, 667, 667, 667, 667, 667, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278, 722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611, 556, 556, 556, 556, 556, 556, 889, 500, 556, 556, 556, 556, 278, 278, 278, 278, 556, 556, 556, 556, 556, 556, 556, 584, 611, 556, 556, 556, 556, 500, 556, 500],
         "F2": [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584, 761, 556, 556, 278, 556, 500, 1000, 556, 556, 333, 1000, 667, 333, 1000, 556, 611, 556, 556, 278, 278, 500, 500, 350, 556, 1000, 333, 1000, 556, 333, 944, 556, 500, 667, 278, 333, 556, 556, 556, 556, 280, 556, 333, 737, 370, 556, 584, 333, 737, 333, 400, 584, 333, 333, 333, 611, 556, 278, 333, 333, 365, 556, 834, 834, 834, 611, 722, 722, 722, 722, 722, 722, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278, 722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611, 556, 556, 556, 556, 556, 556, 889, 556, 556, 556, 556, 556, 278, 278, 278, 278, 611, 611, 611, 611, 611, 611, 611, 584, 611, 611, 611, 611, 611, 556, 611, 556]}


def _text_w(s, size_pt, bold=False):
    """Width of `s` in mm for Helvetica at `size_pt` (cp1252 metrics)."""
    tab = _HV_W["F2" if bold else "F1"]
    tot = 0
    for b in s.encode("cp1252", "replace"):
        tot += tab[b - 32] if 32 <= b <= 255 else 556
    return tot / 1000.0 * size_pt * 25.4 / 72


def _pdf_str(s):
    return s.encode("cp1252", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class PdfSheet:
    """Tiny vector PDF page (mm, origin bottom-left) with Helvetica text. Dependency-free."""

    def __init__(self, w, h, title="", subject=""):
        self.w, self.h, self.title, self.subject = w, h, title, subject
        self.cs = ["1 J 1 j"]

    @staticmethod
    def _n(v):
        return f"{v:.3f}".rstrip("0").rstrip(".") or "0"

    def _p(self, x, y):
        k = 72 / 25.4
        return f"{self._n(x * k)} {self._n(y * k)}"

    def style(self, w_pt=0.5, rgb=(0, 0, 0), dash=None):
        a, b, c = rgb
        d = "[" + " ".join(self._n(v * 72 / 25.4) for v in dash) + "] 0 d" if dash else "[] 0 d"
        self.cs.append(f"{self._n(w_pt)} w {a:g} {b:g} {c:g} RG {a:g} {b:g} {c:g} rg {d}")

    def line(self, a, b):
        self.cs.append(f"{self._p(*a)} m {self._p(*b)} l S")

    def poly(self, pts, fill=False):
        s = f"{self._p(*pts[0])} m " + " ".join(self._p(*q) + " l" for q in pts[1:])
        self.cs.append(s + (" h f" if fill else " S"))

    def rect(self, x, y, w, h):
        self.cs.append(f"{self._p(x, y)} {self._n(w * 72 / 25.4)} {self._n(h * 72 / 25.4)} re S")

    def arc(self, c, r, a0, a1):
        sw = (a1 - a0) % 360 or 360
        n = max(1, math.ceil(sw / 90 - 1e-9))
        step = math.radians(sw / n)
        t0 = math.radians(a0)
        kk = 4 / 3 * math.tan(step / 4)
        p = lambda t: (c[0] + r * math.cos(t), c[1] + r * math.sin(t))
        q = lambda t: (-r * math.sin(t), r * math.cos(t))
        out = [f"{self._p(*p(t0))} m"]
        for i in range(n):
            ta, tb = t0 + i * step, t0 + (i + 1) * step
            pa, pb, da, db = p(ta), p(tb), q(ta), q(tb)
            out.append(f"{self._p(pa[0] + kk * da[0], pa[1] + kk * da[1])} "
                       f"{self._p(pb[0] - kk * db[0], pb[1] - kk * db[1])} {self._p(*pb)} c")
        self.cs.append(" ".join(out) + " S")

    def arrow(self, tip, direction, length=2.5, width=0.9):
        ux, uy = direction
        n = math.hypot(ux, uy)
        ux, uy = ux / n, uy / n
        bx, by = tip[0] - ux * length, tip[1] - uy * length
        self.poly([tip, (bx - uy * width, by + ux * width), (bx + uy * width, by - ux * width)], fill=True)

    def text(self, x, y, s, size=8.0, anchor="l", rot=0, bold=False):
        """Baseline text at (x, y) mm. anchor l/c/r, rot in degrees."""
        w = _text_w(s, size, bold)
        dx = {"l": 0.0, "c": -w / 2, "r": -w}[anchor]
        th = math.radians(rot)
        c, sn = math.cos(th), math.sin(th)
        kk = 72 / 25.4
        self.cs.append(f"BT /{'F2' if bold else 'F1'} {self._n(size)} Tf {c:.5f} {sn:.5f} {-sn:.5f} {c:.5f} "
                       f"{self._n((x + dx * c) * kk)} {self._n((y + dx * sn) * kk)} Tm ({_pdf_str(s)}) Tj ET")

    def fpoly(self, pts, fill_rgb, stroke_rgb=(0, 0, 0), w_pt=0.25):
        """Filled polygon with a thin outline (colours are 0..1 RGB)."""
        f, k = fill_rgb, stroke_rgb
        s = f"q {self._n(w_pt)} w {f[0]:.3f} {f[1]:.3f} {f[2]:.3f} rg {k[0]:.3f} {k[1]:.3f} {k[2]:.3f} RG [] 0 d "
        s += f"{self._p(*pts[0])} m " + " ".join(self._p(*q) + " l" for q in pts[1:]) + " h B Q"
        self.cs.append(s)

    def to_bytes(self, more=()):
        """PDF bytes; `more` = further PdfSheet pages appended after this one."""
        kk = 72 / 25.4
        pages = [self] + list(more)
        font = lambda n: f"<< /Type /Font /Subtype /Type1 /BaseFont /{n} /Encoding /WinAnsiEncoding >>".encode()
        kids = " ".join(f"{6 + 2 * i} 0 R" for i in range(len(pages)))
        objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
                f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode(),
                font("Helvetica"), font("Helvetica-Bold"),
                f"<< /Title ({_pdf_str(self.title)}) /Subject ({_pdf_str(self.subject)}) "
                f"/Creator (BoxForge) >>".encode("latin-1")]
        for i, pg in enumerate(pages):
            stream = "\n".join(pg.cs).encode("latin-1")
            objs.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {pg.w * kk:.2f} {pg.h * kk:.2f}] "
                         f"/Contents {7 + 2 * i} 0 R /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>").encode())
            objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        out = bytearray(b"%PDF-1.4\n")
        offs = []
        for i, o in enumerate(objs, 1):
            offs.append(len(out))
            out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
        xr = len(out)
        out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
        for o in offs:
            out += f"{o:010d} 00000 n \n".encode()
        out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info 5 0 R >>\nstartxref\n{xr}\n%%EOF\n".encode()
        return bytes(out)


SHEETS_MM = [("A4", 297, 210), ("A3", 420, 297), ("A2", 594, 420), ("A1", 841, 594), ("A0", 1189, 841)]
SHEETS_IN = [("ANSI A", 279.4, 215.9), ("ANSI B", 431.8, 279.4), ("ANSI C", 558.8, 431.8),
             ("ANSI D", 863.6, 558.8), ("ANSI E", 1117.6, 863.6)]
SCALE_RATIOS = [1, 2, 2.5, 4, 5, 8, 10, 15, 20, 25, 40, 50, 75, 100]
FRAME = 8.0            # border inset from the sheet edge (mm)
TITLE_H = 34.0         # title block strip height (mm)
SIDE_W = 82.0          # right-hand column for the table / notes / 3-D view (mm)
DIM_ROW1, DIM_ROW2 = 8.0, 20.0
DIM_TXT = 8.0          # dimension text size (pt)


# ---- drawing registry -------------------------------------------------------
# Switchable parts of the drawing sheet.  `page` is None for blocks drawn on the main sheet by
# _draw_blocks; extra PDF pages set page=builder(res, spec, W, H, blocks) -> page.
class DrawingBlock:
    def __init__(self, key, label, cli=None, page=None, note=""):
        self.key, self.label, self.page = key, label, page
        self.cli = cli or key             # name accepted by --dwg-off (the key itself is always accepted too)
        self.note = note                  # help text shown after the CLI name


DRAWING_BLOCKS = []
DRAWING_BY_KEY = {}


def register_drawing_block(key, label, cli=None, page=None, note=""):
    b = DrawingBlock(key, label, cli, page, note)
    DRAWING_BLOCKS.append(b)
    DRAWING_BY_KEY[key] = b
    return b


# Title-block text fields: (key, GUI label, label printed on the sheet)
DRAWING_FIELDS = [("part", "Part name", "Part"), ("number", "Drawing no.", "No."), ("rev", "Revision", "Rev"),
                  ("by", "Drawn by", "By"), ("company", "Company", "Company")]


def drawing_defaults():
    d = {b.key: True for b in DRAWING_BLOCKS}
    d.update({k: "" for k, _, _ in DRAWING_FIELDS})
    return d


def drawing_blocks_from_off(off, fields=None):
    """Build the `blocks` dict from a set of names left out (CLI --dwg-off) and the title-block text."""
    off = set(off)
    out = {b.key: not (off & {b.key, b.cli}) for b in DRAWING_BLOCKS}
    out.update(fields or {})
    return out


def _title_info(blocks):
    return "   ".join(f"{lab}: {blocks[k]}" for k, _, lab in DRAWING_FIELDS if blocks.get(k))


register_drawing_block("title", "Title block")
register_drawing_block("table", "Box size table")
register_drawing_block("notes", "Legend and notes")
register_drawing_block("view3d", "Folded 3-D view", cli="view")


def sheet_layout(units, ext_w, ext_h, blocks, table_rows=None):
    """Smallest standard sheet where the dieline plus its dimension rows fit at 1:5 or better (else the biggest).
    ext_w / ext_h = dieline size in user units. Returns dict(sheet, w, h, ratio, area, side, bottom)."""
    sheets = SHEETS_IN if units == "in" else SHEETS_MM
    mmk = 25.4 if units == "in" else 1.0
    side = SIDE_W if any(blocks.get(k) for k in ("table", "notes", "view3d")) else 0.0
    bottom = TITLE_H if blocks.get("title") else 7.0
    table_h = 7.0 + max(TABLE_ROWS, table_rows or 0) * 5.0
    need = (VIEW_H if blocks.get("view3d") else 0) + (table_h if blocks.get("table") else 0) + \
           (NOTES_MIN if blocks.get("notes") else 0)
    pick = None
    for i, (nm, sw, sh) in enumerate(sheets):
        ax0, ay0 = FRAME + 6 + 22, FRAME + bottom + 6 + 14   # 22 = room for the glue-flap label; 14 = slot row
        ax1, ay1 = sw - FRAME - side - 6 - (DIM_ROW2 + 8), sh - FRAME - 6 - (DIM_ROW2 + 8)
        best = next((r for r in SCALE_RATIOS if ext_w * mmk / r <= ax1 - ax0 and ext_h * mmk / r <= ay1 - ay0), None)
        last = i == len(sheets) - 1
        if sh - 2 * FRAME - bottom < need and not last:     # side column would be too short for its blocks
            continue
        if best is not None and (best <= 5 or last):
            pick = (nm, sw, sh, best, (ax0, ay0, ax1, ay1))
            break
        if last:
            pick = (nm, sw, sh, SCALE_RATIOS[-1], (ax0, ay0, ax1, ay1))
    nm, sw, sh, r, area = pick
    return dict(sheet=nm, w=sw, h=sh, ratio=r, area=area, side=side, bottom=bottom, table_h=table_h)


def _fnum(v, units):
    return (f"{v:.3f}" if units == "in" else f"{v:.2f}").rstrip("0").rstrip(".")


def _dim_label(v, tol_mm, units):
    """'150.5 ±1.5' in the drawing's units (tolerance converted from mm)."""
    t = tol_mm / 25.4 if units == "in" else tol_mm
    return f"{_fnum(v, units)} ±{_fnum(t, units)}"


def _bbox(p):
    xs, ys = [q[0] for q in p.poly], [q[1] for q in p.poly]
    return min(xs), min(ys), max(xs), max(ys)


def style_dimensions(res, spec):
    return res.style.dimensions(res, spec)


def _doc_drawing(res, spec):
    """Nominal (uncompensated) geometry plus any windows / zones, for documentation."""
    d = Drawing()
    d.items = list(res.nominal.items)
    if spec.features:
        mmk = 25.4 if spec.units == "in" else 1.0
        apply_features(d, res.panels, spec.features, spec.t, mmk, 0.0, [])
    return d


# -----------------------------------------------------------------------------
# Optional sheet blocks: title block, size table, legend + notes, folded 3-D view
# -----------------------------------------------------------------------------
VIEW_H, TABLE_ROWS, NOTES_MIN = 56.0, 9, 80.0
TABLE_H = 7.0 + TABLE_ROWS * 5.0
GREY = (0.45, 0.45, 0.45)


def _wrap(text, width, size):
    """Greedy word wrap using Helvetica metrics; returns lines that fit `width` mm."""
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if _text_w(trial, size) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _section(pdf, x, y, w, h, title):
    """Framed section with a small caps header; returns the y of the content top."""
    pdf.style(0.35)
    pdf.rect(x, y, w, h)
    pdf.line((x, y + h - 5.5), (x + w, y + h - 5.5))
    pdf.text(x + 2, y + h - 3.9, title, 6.5, "l", bold=True)
    return y + h - 5.5


def _cell(pdf, x, y, w, h, label, value, size=9.0, bold=False):
    pdf.text(x + 1.8, y + h - 3.0, label, 5.5, "l")
    pdf.text(x + 1.8, y + 2.2, value, size, "l", bold=bold)


def _title_block(pdf, lay, res, spec, opts, units):
    W, bot = lay["w"], lay["bottom"]
    x0, y0, x1, y1 = FRAME, FRAME, W - FRAME, FRAME + bot
    pdf.style(0.7)
    pdf.rect(x0, y0, x1 - x0, bot)
    wtot = x1 - x0
    cols = [0.0, 0.34, 0.60, 0.74, 0.88, 1.0]
    xs = [x0 + c * wtot for c in cols]
    pdf.style(0.35)
    for xx in xs[1:-1]:
        pdf.line((xx, y0), (xx, y1))
    mid = y0 + bot / 2
    for i in (2, 3, 4):
        pdf.line((xs[i], mid), (xs[i + 1], mid))
    pdf.line((xs[1], mid), (xs[2], mid))
    t = spec.t
    Li, Wi, Hi = res.info["inner"]
    part = opts.get("part") or res.style.name
    # col 0: title
    pdf.text(xs[0] + 2, y1 - 5.5, opts.get("company") or "BoxForge", 7, "l")
    pdf.text(xs[0] + 2, y1 - 13.5, part, 13, "l", bold=True)
    pdf.text(xs[0] + 2, y1 - 19.5, res.style.draw_sub or res.style.code, 7.5, "l")
    pdf.text(xs[0] + 2, y0 + 3, "DIELINE DRAWING - FLAT BLANK", 6.5, "l")
    # col 1: size + board
    h = bot / 2
    _cell(pdf, xs[1], mid, xs[2] - xs[1], h, f"INSIDE SIZE  L × W × H  ({spec.mode.upper()} INPUT)",
          f"{_fnum(Li, units)} × {_fnum(Wi, units)} × {_fnum(Hi, units)} {units}")
    _cell(pdf, xs[1], y0, xs[2] - xs[1], h, "BOARD THICKNESS", f"{_fnum(t, units)} {units}")
    # col 2: scale / units
    _cell(pdf, xs[2], mid, xs[3] - xs[2], h, "SCALE", f"1:{lay['ratio']:g}")
    _cell(pdf, xs[2], y0, xs[3] - xs[2], h, "UNITS", "millimetres" if units == "mm" else "inches")
    # col 3: sheet / date
    _cell(pdf, xs[3], mid, xs[4] - xs[3], h, "SHEET", lay["sheet"])
    _cell(pdf, xs[3], y0, xs[4] - xs[3], h, "DATE", opts.get("date") or datetime.date.today().isoformat())
    # col 4: drawing no / rev
    _cell(pdf, xs[4], mid, xs[5] - xs[4], h, "DRAWING NO.", opts.get("number") or "-")
    _cell(pdf, xs[4], y0, xs[5] - xs[4], h, "REV  /  DRAWN BY",
          f"{opts.get('rev') or '-'}  /  {opts.get('by') or '-'}")


def _size_table(pdf, x, y, w, h, res, spec, units):
    top = _section(pdf, x, y, w, h, res.style.table_title)
    t = spec.t
    Li, Wi, Hi = res.info["inner"]
    Lc, Wc, Hc = res.info["crease"]
    tv = res.info["tol"]["values"]
    fx0, fy0, fx1, fy1 = _doc_drawing(res, spec).bounds()
    tol = lambda key: f" ±{_fnum(tv[key] / 25.4 if units == 'in' else tv[key], units)}"
    tri = lambda a, b, c: f"{_fnum(a, units)} × {_fnum(b, units)} × {_fnum(c, units)}"
    a = res.info["auto"]
    flat = ("Flat blank", f"{_fnum(fx1 - fx0, units)} × {_fnum(fy1 - fy0, units)}")
    tol_mm = lambda mm: f" ±{_fnum(mm / 25.4 if units == 'in' else mm, units)}"
    ctx = SimpleNamespace(Li=Li, Wi=Wi, Hi=Hi, Lc=Lc, Wc=Wc, Hc=Hc, t=t, a=a, tri=tri, tol=tol, tol_mm=tol_mm, fnum=_fnum,
                          flat=flat, units=units)
    rows = res.style.size_rows(ctx)
    pdf.style(0.18, GREY)
    for i, (k, v) in enumerate(rows):
        yy = top - (i + 1) * 5.0
        if i:
            pdf.line((x, yy + 5.0), (x + w, yy + 5.0))
        pdf.style(0.2)
        pdf.text(x + 2, yy + 1.5, k, 6.5, "l")
        pdf.text(x + w - 2, yy + 1.5, v, 6.5, "r", bold=True)
        pdf.style(0.18, GREY)


def _inside(poly, x, y):
    c = False
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) / (y2 - y1) * (x2 - x1):
            c = not c
    return c


def _flute_marker(pdf, T, k, res, spec):
    """FLUTE DIRECTION label with a double-headed arrow, set in the flat blank along the flute direction (vertical:
    the sheet's y axis, horizontal: x). Put in the largest panel that has clear room (no window or zone, inside
    the outline), at the largest of three text sizes that fits; when nothing fits the legend note still states
    the direction."""
    fl = getattr(spec, "flute", None)
    if fl not in ("v", "h"):
        return
    txt = "FLUTE DIRECTION"
    vert = fl == "v"
    zones = [(T(g.cx, g.cy), math.hypot(g.w, g.h) / 2 * k) for g in spec.features]
    panels = sorted((p for p in res.panels if len(p.poly) >= 3),
                    key=lambda p: (p.role != "body", -_poly_area([(q[0], q[1]) for q in p.poly])))
    for size in (6.5, 5.5, 4.8):
        L = _text_w(txt, size, True)
        cap = size * 25.4 / 72 * 0.72
        bw, bh = (cap + 4.4, L + 3.0) if vert else (L + 3.0, cap + 4.4)          # label box in sheet mm
        for p in panels:
            poly = [T(q[0], q[1]) for q in p.poly]
            xs, ys = [q[0] for q in poly], [q[1] for q in poly]
            cx0, cy0 = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
            span = (max(xs) - min(xs), max(ys) - min(ys))
            tries = ((0, 0),) + tuple((sx * span[0] * f, sy * span[1] * f) for f in (0.12, 0.24)
                                      for sx, sy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)))
            for dx, dy in tries:
                cx, cy = cx0 + dx, cy0 + dy
                corners = [(cx + sx * bw / 2, cy + sy * bh / 2) for sx in (-1, 1) for sy in (-1, 1)]
                if not all(_inside(poly, a, b) for a, b in corners):
                    continue
                if any(math.hypot(cx - zc[0], cy - zc[1]) < zr + math.hypot(bw, bh) / 2 for zc, zr in zones):
                    continue
                pdf.style(0.3)
                if vert:
                    xa, xt = cx + cap / 2 + 1.0, cx + cap / 2 - 0.4       # arrow, then the text's baseline to its left
                    pdf.line((xa, cy - L / 2), (xa, cy + L / 2))
                    pdf.arrow((xa, cy + L / 2 + 0.6), (0, 1), 2.0, 0.8)
                    pdf.arrow((xa, cy - L / 2 - 0.6), (0, -1), 2.0, 0.8)
                    pdf.text(xt - 0.4, cy - L / 2, txt, size, "l", rot=90, bold=True)
                else:
                    ya, yt = cy - cap / 2 - 1.0, cy - cap / 2 + 0.6
                    pdf.line((cx - L / 2, ya), (cx + L / 2, ya))
                    pdf.arrow((cx + L / 2 + 0.6, ya), (1, 0), 2.0, 0.8)
                    pdf.arrow((cx - L / 2 - 0.6, ya), (-1, 0), 2.0, 0.8)
                    pdf.text(cx, yt, txt, size, "c", bold=True)
                return


def _legend_notes(pdf, x, y, w, h, res, spec, units, has_engrave):
    top = _section(pdf, x, y, w, h, "LEGEND AND NOTES")
    yy = top - 5.0
    # legend: cut / crease / engrave + flute arrow
    items = [("CUT", 0.6, (0, 0, 0), None), ("CREASE (FOLD)", 0.35, (0, 0, 0), (3.0, 1.2))]
    if has_engrave:
        items.append(("ENGRAVE (ZONE)", 0.18, GREY, None))
    for name, wpt, rgb, dash in items:
        pdf.style(wpt, rgb, dash)
        pdf.line((x + 3, yy + 1.1), (x + 17, yy + 1.1))
        pdf.style(0.2)
        pdf.text(x + 20, yy, name, 6.5, "l")
        yy -= 4.6
    # flute direction arrow (vertical on the sheet unless the designer set it horizontal)
    ax = x + w - 12
    pdf.style(0.35)
    if getattr(spec, "flute", None) == "h":
        ay = top - 8.2
        pdf.line((ax - 5.2, ay), (ax + 5.2, ay))
        pdf.arrow((ax + 6.0, ay), (1, 0), 2.2, 0.8)
        pdf.arrow((ax - 6.0, ay), (-1, 0), 2.2, 0.8)
        pdf.text(ax, top - 12.6, "FLUTES", 5.5, "c")
    else:
        pdf.line((ax, top - 14), (ax, top - 4.5))
        pdf.arrow((ax, top - 3.7), (0, 1), 2.2, 0.8)
        pdf.arrow((ax, top - 14.8), (0, -1), 2.2, 0.8)
        pdf.text(ax, top - 18.8, "FLUTES", 5.5, "c")
    yy -= 3.0
    pdf.style(0.18, GREY)
    pdf.line((x, yy + 3.2), (x + w, yy + 3.2))
    yy -= 2.0
    tv = res.info["tol"]
    v, au = tv["values"], tv["auto"]
    f = lambda k: _fnum(v[k] / 25.4 if units == "in" else v[k], units)
    keys = res.style.tol_keys
    if res.style.tol_note(f, units):
        tol_txt = res.style.tol_note(f, units)
    elif "slot" in keys:
        tol_txt = (f"Tolerances (± {units}): panels / scores {f('panel')}; flaps {f('flap')}; slots {f('slot')}; "
                   f"glue flap {f('glue')}; blank {f('overall_len')} x {f('overall_h')}; finished box {f('box')}.")
    else:
        tol_txt = (f"Tolerances (± {units}): panels / scores {f('panel')}; flaps {f('flap')}; "
                   f"blank {f('overall_len')} x {f('overall_h')}; finished box {f('box')}.")
    notes = [f"All dimensions in {units}, crease to crease unless noted.",
             tol_txt + ("" if all(au[k] for k in keys) else " Some values set by the designer."),
             {"v": "Flutes run vertically on the flat sheet (up-down), as marked FLUTE DIRECTION on the dieline.",
              "h": "Flutes run horizontally on the flat sheet (left-right), as marked FLUTE DIRECTION on the dieline."
              }.get(getattr(spec, "flute", None), "Flutes run parallel to the box height unless otherwise stated.")]
    notes.extend(res.style.drawing_notes(res, units))
    if res.info.get("kerf"):
        notes.append(f"Shown at nominal size. Laser kerf {_fnum(res.info['kerf'], units)} is compensated in the "
                     f"cutting file only.")
    nw = sum(1 for g in spec.features if g.kind == "window")
    nz = len(spec.features) - nw
    if nw or nz:
        notes.append(f"{nw} window(s), {nz} engraved zone(s) as shown.")
    size = 6.0
    pdf.style(0.2)
    for i, n in enumerate(notes, 1):
        lines = _wrap(n, w - 8, size)
        pdf.text(x + 2, yy, f"{i}.", size, "l")
        for ln in lines:
            if yy < y + 2:
                return
            pdf.text(x + 6, yy, ln, size, "l")
            yy -= 3.2
        yy -= 0.8


def _view3d_solid(pdf, x, y, w, h, res, spec):
    """The folded box as thick board in the correct fold order (flaps stacked, nothing seen through); False when the
    panels are not a slotted-box blank (the caller then draws the thin-sheet view)."""
    if not spec.t or spec.t <= 0:
        return False
    sid = res.style.id
    pf, lift, layer = style_sequence(sid, res.panels, spec.t, res.style.view_amount(res))
    try:
        faces = solid_faces(res.panels, spec.t, pf, lift, bend=_bend_ri_user(spec) if res.style.rounded_folds else None,
                            bend_k=bend_spec_from(spec).k)
    except Exception:
        return False
    if not faces or (res.style.anchor_panel and not any(f[0] == res.style.anchor_panel for f in faces)):
        return False
    up = res.style.view_up
    polys = iso_solid_polys(faces, up, layer=layer)
    xs = [q[0] for _, pts, *_ in polys for q in pts]
    ys = [q[1] for _, pts, *_ in polys for q in pts]
    if not xs:
        return False
    box_w, box_h = w - 8, h - 5.5 - 8
    s = min(box_w / max(max(xs) - min(xs), 1e-9), box_h / max(max(ys) - min(ys), 1e-9))
    cx0 = x + w / 2 - s * (min(xs) + max(xs)) / 2
    cy0 = y + (h - 5.5) / 2 + 1.0 - s * (min(ys) + max(ys)) / 2
    for _, pts, kind, role, lit, smooth in polys:
        g = (0.80 + 0.17 * lit) if kind == "out" else (0.58 + 0.2 * lit) if kind == "in" else (0.68 + 0.2 * lit)
        if role != "body":
            g = min(1.0, g + 0.03)
        col = (g, g, g)
        pdf.fpoly([(cx0 + a * s, cy0 + b * s) for a, b in pts], col, col if smooth else (0.15, 0.15, 0.15), 0.22)
    return True


def _view3d(pdf, x, y, w, h, res, spec, units):
    top = _section(pdf, x, y, w, h, res.style.view_heading(res))
    if _view3d_solid(pdf, x, y, w, h, res, spec):
        pdf.style(0.2)
        pdf.text(x + w / 2, y + 2.0, res.style.view_caption(res, units), 6, "c")
        return
    polys = fold_panels(res.panels, 1.0)
    up = res.style.view_up
    orient = (lambda p: (p[0], p[2], -p[1])) if up == "z" else (lambda p: p)
    yaw, pitch = -0.62, 0.5
    cy_, sy_, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)

    def proj(q):
        a, b, c = orient(q)
        x1, z1 = cy_ * a + sy_ * c, -sy_ * a + cy_ * c
        return x1, cp * b - sp * z1, sp * b + cp * z1
    pr = {n: [proj(q) for q in pts] for n, pts in polys.items()}
    allp = [q for pts in pr.values() for q in pts]
    mnx, mxx = min(q[0] for q in allp), max(q[0] for q in allp)
    mny, mxy = min(q[1] for q in allp), max(q[1] for q in allp)
    box_w, box_h = w - 8, h - 5.5 - 8
    s = min(box_w / max(mxx - mnx, 1e-9), box_h / max(mxy - mny, 1e-9))
    cx0 = x + w / 2 - s * (mnx + mxx) / 2
    cy0 = y + (h - 5.5) / 2 + 1.0 - s * (mny + mxy) / 2
    roles = {p.name: p.role for p in res.panels}
    order = sorted(pr, key=lambda n: sum(q[2] for q in pr[n]) / len(pr[n]))
    for n in order:
        pts = [(cx0 + q[0] * s, cy0 + q[1] * s) for q in pr[n]]
        shade = 0.93 if roles[n] == "body" else 0.97
        pdf.cs.append(f"{shade} {shade} {shade} rg")
        pdf.cs.append(pdf._p(*pts[0]) + " m " + " ".join(pdf._p(*q) + " l" for q in pts[1:]) + " h f")
        pdf.style(0.3)
        pdf.poly(pts + [pts[0]])
    pdf.style(0.2)
    pdf.text(x + w / 2, y + 2.0, res.style.view_caption(res, units), 6, "c")


def _draw_blocks(pdf, lay, res, spec, blocks, units, has_engrave):
    """Place the enabled blocks. Side column order: folded view, size table, legend + notes."""
    W, H = lay["w"], lay["h"]
    if blocks.get("title"):
        _title_block(pdf, lay, res, spec, blocks, units)
    on = [k for k in ("view3d", "table", "notes") if blocks.get(k)]
    if not on:
        return
    x = W - FRAME - lay["side"]
    top = H - FRAME
    bottom = FRAME + lay["bottom"]
    pdf.style(0.7)
    pdf.line((x, bottom), (x, top))
    fixed = {"view3d": VIEW_H, "table": lay.get("table_h", TABLE_H)}
    free = (top - bottom) - sum(fixed[k] for k in on if k in fixed)
    for k in on:
        h = fixed.get(k, free)
        top -= h
        bx, bw = x, lay["side"]
        if k == "view3d":
            _view3d(pdf, bx, top, bw, h, res, spec, units)
        elif k == "table":
            _size_table(pdf, bx, top, bw, h, res, spec, units)
        else:
            _legend_notes(pdf, bx, top, bw, h, res, spec, units, has_engrave)


STEP_VIEWS = [("flat", "STEP 1  -  FLAT", "As cut: all panels, glue flap and flaps unfolded."),
              ("partial", "STEP 2  -  PARTLY FOLDED", "Walls and glue flap folded into the box; flaps still open."),
              ("folded", "STEP 3  -  FULLY FOLDED", "Flaps closed.")]
def step_amount(style, stage):
    """Slider position of a fold-steps stage (flat / partial / folded) for `style`."""
    if stage == "flat":
        return 0.0
    if stage == "folded":
        return 1.0
    custom = style.stage_amount(stage)
    if custom is not None:
        return custom
    return style.step_amount if style.step_amount is not None else SEQ_WALLS


def _newell(pts):
    nx = ny = nz = 0.0
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    L = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return nx / L, ny / L, nz / L


def _ins_plate(name):
    """A flat plate of an insert blade (ia~0 ... ic~2): its slot walls and floor can separate it from the other blade."""
    return name[:2] in ("ia", "ic", "gl", "gw") and "~" in name and not name.endswith(".bend")


def plate_order(plates, cam=None, geo=None, cam_geo=None, cache=None):
    """Back-to-front draw order of thick plates. `plates` = {name: [(kind, [(x, y, z) in camera space])]}; the camera
    looks down -z from `cam` = (x, y, z), or from infinity when None. Two plates are ordered when a plane of one
    (its outside or inside face) has one plate wholly on each side: the one on the camera's side is in front. That
    is exact for separated convex plates and removes the see-through errors of sorting by average depth. Pairs
    with no separating plane, and cycles, fall back to average depth. Returns {name: rank} (low rank = draw first).

    Which planes separate two plates does not depend on the camera, only which side of each the camera is on. So a
    live viewer can pass the same plates in model space as `geo` (with the camera's model-space position `cam_geo`)
    and a dict `cache` kept for as long as the model does not change: the separating planes are then found once and
    every frame only tests the camera against them. The result is the same as without the cache."""
    names = list(plates)
    if geo is None:
        geo, cam_geo = plates, cam
    if cache is None:
        cache = {}
    depth = {}
    for nm in names:
        pts = [q for _, f in plates[nm] for q in f]
        depth[nm] = sum(q[2] for q in pts) / max(1, len(pts))
    if "geom" not in cache:
        verts, planes, eplanes = {}, {}, {}
        for nm in names:
            pts = [q for _, f in geo[nm] for q in f]
            verts[nm] = pts
            pl, pe = [], []
            for kind, f in geo[nm]:
                if len(f) >= 3:
                    n = _newell(f)
                    p0 = f[0]
                    ds = [n[0] * (q[0] - p0[0]) + n[1] * (q[1] - p0[1]) + n[2] * (q[2] - p0[2]) for q in pts]
                    (pl if kind in ("out", "in") else pe).append((n, p0, min(ds), max(ds), nm))   # own extent cached
            planes[nm] = pl
            eplanes[nm] = pe
        allp = [q for nm in names for q in verts[nm]]
        ext = max((max(q[i] for q in allp) - min(q[i] for q in allp) for i in range(3)), default=1.0) if allp else 1.0
        cache["geom"] = (verts, planes, eplanes, 1e-5 * max(ext, 1e-9))
        cache["pairs"] = {}
    verts, planes, eplanes, eps = cache["geom"]
    pairs = cache["pairs"]

    def candidates(a, b):
        """Planes that put plate a wholly on one side and b on the other, best first, as (normal, offset, a_side):
        a is in front when (normal . camera - offset > 0) == (a_side > 0)."""
        extra = eplanes[a] + eplanes[b] if ((a[:3] in ("top", "bot") and b[:3] in ("top", "bot") and "." not in a + b)
                                            or (_ins_plate(a) and _ins_plate(b))) else []   # side faces split two flat plates
        va, vb = verts[a], verts[b]
        for n, p0, own_min, own_max, owner in planes[a] + planes[b] + extra:
            n0, n1, n2 = n
            if owner == a:                                  # this plane's own plate: extent was cached
                amin, amax = own_min, own_max
                db = [n0 * (q[0] - p0[0]) + n1 * (q[1] - p0[1]) + n2 * (q[2] - p0[2]) for q in vb]
                bmin, bmax = min(db), max(db)
            else:
                bmin, bmax = own_min, own_max
                da = [n0 * (q[0] - p0[0]) + n1 * (q[1] - p0[1]) + n2 * (q[2] - p0[2]) for q in va]
                amin, amax = min(da), max(da)
            if amin >= -eps and bmax <= eps and (amax > eps or bmin < -eps):
                yield n, n0 * p0[0] + n1 * p0[1] + n2 * p0[2], 1
            elif amax <= eps and bmin >= -eps and (amin < -eps or bmax > eps):
                yield n, n0 * p0[0] + n1 * p0[1] + n2 * p0[2], -1
        # Plates that meet at a fold have no face plane between them (their slabs touch or overlap at the bend).
        # The bisector of the two plates' face planes does separate them (end faces of a rounded fold are radial).
        for na, pa, *_ in planes[a][:2]:
            da0 = na[0] * pa[0] + na[1] * pa[1] + na[2] * pa[2]
            for nb, pb, *_ in planes[b][:2]:
                db0 = nb[0] * pb[0] + nb[1] * pb[1] + nb[2] * pb[2]
                for sg in (1.0, -1.0):
                    n = (na[0] + sg * nb[0], na[1] + sg * nb[1], na[2] + sg * nb[2])
                    ln = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
                    if ln < 1e-3:                           # parallel planes: no bisector in this sign
                        continue
                    n = (n[0] / ln, n[1] / ln, n[2] / ln)
                    d0 = (da0 + sg * db0) / ln
                    da = [n[0] * q[0] + n[1] * q[1] + n[2] * q[2] - d0 for q in va]
                    db = [n[0] * q[0] + n[1] * q[1] + n[2] * q[2] - d0 for q in vb]
                    amin, amax, bmin, bmax = min(da), max(da), min(db), max(db)
                    if amin >= -eps and bmax <= eps and (amax > eps or bmin < -eps):
                        yield n, d0, 1
                    elif amax <= eps and bmin >= -eps and (amin < -eps or bmax > eps):
                        yield n, d0, -1
        # Last resort for plates that slightly interpenetrate (a flap lying against a wall a little off the exact
        # fold angle): use the face plane that the two plates cross the least, when that overlap is a small part of a
        # board thickness.
        best = None
        for n, p0, own_min, own_max, owner in planes[a] + planes[b]:
            n0, n1, n2 = n
            vo = verts[b] if owner == a else verts[a]
            do = [n0 * (q[0] - p0[0]) + n1 * (q[1] - p0[1]) + n2 * (q[2] - p0[2]) for q in vo]
            lo, hi = min(do), max(do)
            viol = max(0.0, -lo)        # owner on the - side of its own plane: the other plate should be on the + side
            if hi > 0 and viol <= 0.3 * (own_max - own_min) and (best is None or viol < best[0]):
                best = (viol, n, p0, owner)
        if best is not None:
            _, n, p0, owner = best
            yield n, n[0] * p0[0] + n[1] * p0[1] + n[2] * p0[2], (-1 if owner == a else 1)

    def front_of(a, b):
        """True when plate a is in front of plate b (b must be drawn first); None when no plane decides."""
        ent = pairs.get((a, b))
        if ent is None:
            ent = pairs[(a, b)] = ([], candidates(a, b))
        done, gen = ent
        i = 0
        while True:
            if i == len(done):
                nxt = next(gen, None)
                if nxt is None:
                    return None
                done.append(nxt)
            n, c0, side = done[i]
            i += 1
            cs = n[2] if cam_geo is None else n[0] * cam_geo[0] + n[1] * cam_geo[1] + n[2] * cam_geo[2] - c0
            if abs(cs) < 1e-12:
                continue
            return (cs > 0) == (side > 0)
    # Only plates whose outlines overlap on screen constrain each other. A separating plane says "a is in front of b"
    # for the whole of space, but that relation is not transitive between plates that never overlap in the picture, and
    # such unneeded constraints form false cycles whose tie-break then draws a wall over a floor (see-through faces).
    box = {}
    for nm in names:
        sx, sy = [], []
        for _, f in plates[nm]:
            for q in f:
                fct = 1.0
                if cam is not None:
                    dz = cam[2] - q[2]
                    fct = cam[2] / dz if dz > 1e-9 else None
                if fct is None:
                    sx = None
                    break
                sx.append(q[0] * fct)
                sy.append(q[1] * fct)
            if sx is None:
                break
        box[nm] = (min(sx), max(sx), min(sy), max(sy)) if sx else None

    def overlap(a, b):
        ba, bb = box[a], box[b]
        if ba is None or bb is None:
            return True
        return not (ba[1] < bb[0] - eps or bb[1] < ba[0] - eps or ba[3] < bb[2] - eps or bb[3] < ba[2] - eps)
    before = {nm: set() for nm in names}                   # before[x] = plates that must be drawn before x
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if not overlap(a, b):
                continue
            r = front_of(a, b)
            if r is True:
                before[a].add(b)
            elif r is False:
                before[b].add(a)
    rank, left = {}, set(names)
    while left:
        ready = [nm for nm in left if not (before[nm] & left)]
        pick = min(ready or left, key=lambda nm: (len(before[nm] & left), depth[nm]))   # cycle: break it at the plate with the fewest unmet predecessors
        rank[pick] = len(rank)
        left.discard(pick)
    return rank


def iso_solid_polys(faces, up="y", yaw=-0.62, pitch=0.5, flip=False, layer=None):
    """Orthographic projection of solid_faces() output. Returns [(depth, [(x, y)], kind, role, light, smooth)], painter-sorted
    back to front, back faces dropped; y points up. `flip` turns the model 180 degrees about the vertical axis
    (used to show the outside of the flat blank). Plates are ordered by plate_order (separating planes); `layer` is
    ignored (False turns the ordering off)."""
    cyw, syw, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
    light = (-0.35, 0.55, 0.76)
    conv, plates = [], {}
    for name, kind, pts, role in faces:
        cam = []
        for q in pts:
            x, y, z = (q[0], q[2], -q[1]) if up == "z" else q
            if flip:
                x, z = -x, -z
            x1, z1 = cyw * x + syw * z, -syw * x + cyw * z
            cam.append((x1, cp * y - sp * z1, sp * y + cp * z1))
        conv.append((name, kind, role, cam))
        plates.setdefault(name, []).append((kind, cam))
    rank = plate_order(plates) if layer is not False else {}
    out = []
    for name, kind, role, cam in conv:
        a2 = sum(cam[i][0] * cam[(i + 1) % len(cam)][1] - cam[(i + 1) % len(cam)][0] * cam[i][1]
                 for i in range(len(cam)))
        if a2 <= 0:
            continue
        n = _newell(cam)
        lit = max(0.0, n[0] * light[0] + n[1] * light[1] + n[2] * light[2])
        out.append(((rank.get(name, 0), sum(c[2] for c in cam) / len(cam)),
                    [(c[0], c[1]) for c in cam], kind, role, lit, (name.endswith(".bend") or "~" in name) and kind != "edge"))
    out.sort(key=lambda r: r[0])
    return out


def _step_colour(kind, role, lit):
    base = (0.78, 0.85, 0.93) if role == "body" else (0.93, 0.88, 0.78)      # walls blue-grey, flaps warm grey
    k = (0.55 + 0.45 * lit) if kind == "out" else (0.40 + 0.35 * lit) if kind == "in" else (0.45 + 0.4 * lit)
    return tuple(min(1.0, c * k) for c in base)


def fold_steps_page(res, spec, W, H, blocks=None):
    """Second drawing page: the box as a thick solid in three steps (flat, partly folded, folded). Not to scale."""
    blocks = dict(blocks or {})
    units = spec.units
    mmk = 25.4 if units == "in" else 1.0
    t = spec.t * mmk
    # panels are in drawing units: scale to mm for a consistent thickness
    panels = res.panels
    pg = PdfSheet(W, H, title="BoxForge fold steps", subject="")
    pg.style(0.7)
    pg.rect(FRAME, FRAME, W - 2 * FRAME, H - 2 * FRAME)
    title = f"FOLD SEQUENCE  -  {res.style.name}"
    sid = res.style.id
    pg.style(0.3)
    pg.text(FRAME + 6, H - FRAME - 11, title, 12, "l", bold=True)
    sub = f"{fmt(spec.L)} x {fmt(spec.W)} x {fmt(spec.H)} {units}   board {fmt(spec.t)} {units}   {res.style.steps_note}"
    pg.text(FRAME + 6, H - FRAME - 17.5, sub, 8, "l")
    up = res.style.view_up
    top = H - FRAME - 24
    bot = FRAME + (22 if blocks.get("title") else 12)
    gap = 6.0
    views = res.style.step_views(res)
    cw = (W - 2 * FRAME - (len(views) + 1) * gap) / len(views)
    for i, (stage, head, note) in enumerate(views):
        cx0 = FRAME + gap + i * (cw + gap)
        pg.style(0.3, (0.5, 0.5, 0.5))
        pg.rect(cx0, bot, cw, top - bot)
        pf, lift, layer = style_sequence(sid, panels, spec.t, step_amount(res.style, stage))
        faces = solid_faces(panels, spec.t, pf, lift,
                            bend=_bend_ri_user(spec) if (blocks.get("bends") and res.style.rounded_folds) else None,
                            bend_k=bend_spec_from(spec).k)
        polys = iso_solid_polys(faces, up, flip=(stage == "flat"), layer=layer)
        xs = [q[0] for _, pts, *_ in polys for q in pts]
        ys = [q[1] for _, pts, *_ in polys for q in pts]
        pad = 8.0
        lab_h = 14.0
        sc = min((cw - 2 * pad) / max(1e-9, max(xs) - min(xs)), (top - bot - lab_h - 2 * pad) / max(1e-9, max(ys) - min(ys)))
        ox = cx0 + cw / 2 - (max(xs) + min(xs)) / 2 * sc
        oy = bot + lab_h + (top - bot - lab_h) / 2 - (max(ys) + min(ys)) / 2 * sc
        for _, pts, kind, role, lit, smooth in polys:
            col = _step_colour(kind, role, lit)
            pg.fpoly([(ox + x * sc, oy + y * sc) for x, y in pts], col, col if smooth else (0.15, 0.15, 0.15), 0.25)
        pg.style(0.3)
        pg.text(cx0 + cw / 2, bot + 8, head, 9, "c", bold=True)
        pg.text(cx0 + cw / 2, bot + 3.2, res.style.step_text.get(stage, note), 6.0 if len(views) > 3 else 6.5, "c")
    if blocks.get("title"):
        info = _title_info(blocks)
        if info:
            pg.text(FRAME + 6, FRAME + 5, info, 8, "l")
    return pg


def _section_poly(bs, angle, leg, n=20):
    """Board section of one bend as a closed polygon (mm): first leg along -x, arc about the origin, second leg."""
    th = math.radians(angle)
    out, inn = [], []
    for r, lst in ((bs.ro, out), (bs.ri, inn)):
        pts = [(-leg, -r)]
        pts += [(r * math.sin(th * i / n), -r * math.cos(th * i / n)) for i in range(n + 1)]
        e = pts[-1]
        pts.append((e[0] + math.cos(th) * leg, e[1] + math.sin(th) * leg))
        lst.extend(pts)
    return out + inn[::-1]


def bend_page(res, spec, W, H, blocks=None):
    """Third drawing page: bend sections at three fold angles, the fold table and the material usage."""
    blocks = dict(blocks or {})
    rep = bend_report(res, spec)
    bs, u = rep["spec"], rep["usage"]
    pg = PdfSheet(W, H, title="BoxForge bend data", subject="")
    pg.style(0.7)
    pg.rect(FRAME, FRAME, W - 2 * FRAME, H - 2 * FRAME)
    pg.style(0.3)
    pg.text(FRAME + 6, H - FRAME - 11, f"BEND DATA  -  {res.style.name}", 12, "l", bold=True)
    mat = BEND_MATERIALS[bs.material]["label"]
    inch = spec.units == "in"                                   # the page uses the job's units, like the other pages
    cv, ul, dp = (1.0 / 25.4, "in", 3) if inch else (1.0, "mm", 2)
    f2 = lambda v: f"{v * cv:.{dp}f}"
    f1 = lambda v: f"{v * cv:.{dp - 1}f}"
    f0 = lambda v: f"{v * cv:.1f}" if inch else f"{v * cv:.0f}"
    pg.text(FRAME + 6, H - FRAME - 17.5,
            f"{mat}   board {f2(bs.t)} {ul}   inside radius {f2(bs.ri)} {ul} ({bs.ri / bs.t if bs.t else 0:.2f} x board)   "
            f"K-factor {bs.k:.2f}   springback {bs.springback:g} deg at 90   (all values in {'inches' if inch else 'mm'})", 8, "l")
    top = H - FRAME - 24
    gap = 6.0
    # --- sections ---
    cw = (W - 2 * FRAME - 4 * gap) / 3
    sec_h = (top - FRAME) * 0.46
    ybot = top - sec_h
    for i, ang in enumerate((30.0, 60.0, 90.0)):
        cx0 = FRAME + gap + i * (cw + gap)
        pg.style(0.3, (0.5, 0.5, 0.5))
        pg.rect(cx0, ybot, cw, sec_h)
        leg = max(3 * bs.ro, 5 * bs.t)
        poly = _section_poly(bs, ang, leg)
        xs, ys = [q[0] for q in poly], [q[1] for q in poly]
        pad, lab = 10.0, 24.0
        sc = min((cw - 2 * pad) / max(1e-9, max(xs) - min(xs)), (sec_h - lab - 2 * pad) / max(1e-9, max(ys) - min(ys)), 14.0)
        ox = cx0 + cw / 2 - (max(xs) + min(xs)) / 2 * sc
        oy = ybot + lab + (sec_h - lab) / 2 - (max(ys) + min(ys)) / 2 * sc
        M = lambda q: (ox + q[0] * sc, oy + q[1] * sc)
        pg.fpoly([M(q) for q in poly], (0.80, 0.86, 0.93), (0.1, 0.1, 0.1), 0.5)
        prof = bend_profile(bs, ang)
        pg.style(0.25, (0.8, 0.1, 0.1), (1.6, 0.8))                 # neutral axis
        pg.poly([M(q) for q in prof["neutral"]])
        pg.style(0.25, (0.3, 0.3, 0.3), (2.0, 0.8))                 # virtual sharp corner (outside) and centre mark
        th = math.radians(ang)
        a, b = (0.0, -bs.ro), (bs.ro * math.sin(th), -bs.ro * math.cos(th))
        c = bend_calc(bs, ang)
        V = (-bs.ro * 0.0 - c["ossb"] * 0.0, 0.0)
        Vx = (a[0] + 0.0, a[1])
        # outside virtual corner: tangent point back along the legs by the setback
        vx = a[0] + c["ossb"]
        pg.line(M(a), M((vx, a[1])))
        pg.line(M((vx, a[1])), M(b))
        pg.style(0.25, (0, 0, 0))
        pg.line(M((-0.8, 0)), M((0.8, 0)))
        pg.line(M((0, -0.8)), M((0, 0.8)))
        pg.text(cx0 + cw / 2, ybot + lab - 6, f"{ang:g} deg FOLD", 9, "c", bold=True)
        pg.text(cx0 + cw / 2, ybot + lab - 11, f"bend allowance {f2(c['ba'])}   setback {f2(c['ossb'])}   "
                f"deduction {f2(c['bd'])}   commanded {c['commanded']:.1f} deg", 6.5, "c")
        pg.text(cx0 + cw / 2, ybot + lab - 15.5, f"fibre strain outside +{100 * c['strain_out']:.0f}%   "
                f"inside {100 * c['strain_in']:.0f}%", 6.5, "c")
        pg.text(cx0 + 4, ybot + sec_h - 6, f"Ro {f2(bs.ro)}   Ri {f2(bs.ri)}   t {f2(bs.t)}", 7, "l")
        pg.text(cx0 + 4, ybot + sec_h - 10.5, "red dashed = neutral axis; grey dashed = virtual sharp corner", 5.5, "l")
    # --- fold table ---
    y = ybot - 8
    pg.style(0.3)
    pg.text(FRAME + 6, y, "FOLDS", 9, "l", bold=True)
    cols = [("fold type", 0, "l"), ("count", 38, "r"), (f"hinge {ul}", 58, "r"), ("angle", 74, "r"), ("allowance", 94, "r"),
            ("setback", 112, "r"), ("deduction", 132, "r"), ("commanded", 154, "r")]
    x0 = FRAME + 6
    y -= 5.5
    for lab_, dx, an in cols:
        pg.text(x0 + dx, y, lab_, 6.8, an, bold=True)
    pg.style(0.2)
    pg.line((x0, y - 1.5), (x0 + 156, y - 1.5))
    for g in rep["groups"]:
        y -= 5.0
        vals = [g["kind"], f"{g['count']}", f0(g['length']), f"{g['angle']:.0f}", f2(g['ba']),
                f2(g['ossb']), f2(g['bd']), f"{g['commanded']:.1f}"]
        for (lab_, dx, an), v in zip(cols, vals):
            pg.text(x0 + dx, y, v, 7.2, an)
    # --- material usage ---
    x1 = FRAME + 6 + 175
    y2 = ybot - 8
    pg.text(x1, y2, "MATERIAL", 9, "l", bold=True)
    ar = (lambda a_: f"{a_ / 645.16:.1f} in2") if inch else (lambda a_: f"{a_ / 100:.0f} cm2")
    rows = [("Blank", f"{f1(u['blank_w'])} x {f1(u['blank_h'])} {ul}  ({ar(u['blank_area'])})"),
            ("Board in the parts", f"{ar(u['net_area'])}  ({100 * u['utilisation']:.0f}% of the blank)"),
            ("Waste inside the blank", ar(u['waste_area'])),
            ("Cut length", f"{f0(u['cut_length'])} {ul}"),
            ("Kerf loss", f"{u['kerf_area'] / 645.16:.3f} in2" if inch else f"{u['kerf_area']:.1f} mm2"),
            ("Bend zones (neutral width x hinge)", ar(u['bend_zone_area'])),
            ("Board volume", f"{u['volume'] / 16387.064:.1f} in3" if inch else f"{u['volume'] / 1000:.0f} cm3")]
    if u["nest"]:
        n = u["nest"]
        rows.append(("Blanks per sheet", f"{n['per_sheet']}  ({100 * n['utilisation']:.0f}% of {f0(n['sheet'][0])} x {f0(n['sheet'][1])} {ul})"))
    for lab_, v in rows:
        y2 -= 5.0
        pg.text(x1, y2, lab_, 7.2, "l")
        pg.text(x1 + 62, y2, v, 7.2, "l")
    # --- notes ---
    d = rep["dieline"]
    yn = min(y, y2) - 9
    pg.style(0.3)
    pg.text(FRAME + 6, yn, "NOTES", 9, "l", bold=True)
    notes = res.style.bend_notes(rep) or [
             f"The dieline is not changed by this page. Its crease-to-crease sizes already build in a bend deduction of "
             f"{f2(d['implied_bd'])} {ul} per 90 deg fold (equivalent to K {d['implied_k']:.2f} at this radius);",
             f"the bend model above predicts {f2(d['model_bd'])} {ul}. The crease-to-crease sizes on the dieline govern; "
             f"the model figure is an estimate of the real fold and does not move any crease."]
    notes += ["Fibre strain is a solid-sheet estimate: scored corrugated board crushes at the score instead of stretching, "
              "so read it as a comparison between folds, not a measured property."]
    notes += ["Radius, K-factor and springback are typical starting values for the material, not measurements: fold a "
             "test sample of your own board and adjust them."]
    try:                                                   # how the folded model closes (3-D preview and fold steps)
        if not res.style.closing_report:
            raise ValueError("closing numbers are for the slotted box")
        mmk = 25.4 if spec.units == "in" else 1.0
        inf = {}
        fold_rsc(res.panels, spec.t, lambda p, d, m: 1.0, None, ri=_bend_ri_user(spec), k=bs.k, info=inf)
        if inf:
            notes.append(f"Folded model: the loop of four bends closes by moving walls 1 and 3 by {f2(inf['e'] * mmk)} {ul} "
                         f"(half a board) against each other;")
            notes.append(f"the unbent wall's free end is taken {f2(inf['g'] * mmk)} {ul} to sit flush with the outside of the "
                         f"glue-flap wall, and each flap loses BA/2 = {f2(inf['ba'] / 2 * mmk)} {ul}.")
    except Exception:
        pass
    for i, nt in enumerate(notes):
        pg.text(FRAME + 6, yn - 5 - i * 4.5, nt, 7, "l")
    if blocks.get("title"):
        info = _title_info(blocks)
        if info:
            pg.text(FRAME + 6, FRAME + 5, info, 8, "l")
    return pg


register_drawing_block("steps", "Fold steps page (3-D: flat, partly folded, folded)", page=fold_steps_page,
                       note="the 3-D fold steps page")      # page 2
register_drawing_block("bends", "Bend data page (fold sections, radius, material use)", page=bend_page,
                       note="the bend data page")            # page 3


def drawing_pdf(res, spec, blocks=None):
    """Dimensioned engineering sheet for an RSC result. Returns PDF bytes."""
    if "tol" not in res.info or res.nominal is None or not res.panels:
        raise ValueError("No drawing sheet could be made for this box.")
    blocks = dict(blocks or {})
    units = spec.units
    mmk = 25.4 if units == "in" else 1.0
    d = _doc_drawing(res, spec)
    x0, y0, x1, y1 = d.bounds()
    lay = sheet_layout(units, x1 - x0, y1 - y0, blocks, res.style.table_rows(res))
    W, H, ratio = lay["w"], lay["h"], lay["ratio"]
    ax0, ay0, ax1, ay1 = lay["area"]
    k = mmk / ratio                                        # model unit -> sheet mm
    ox = ax0 + (ax1 - ax0 - (x1 - x0) * k) / 2 - x0 * k    # dieline centred in the free area
    oy = ay0 + (ay1 - ay0 - (y1 - y0) * k) / 2 - y0 * k
    T = lambda x, y: (ox + x * k, oy + y * k)
    pdf = PdfSheet(W, H, title=f"BoxForge drawing - {res.style.name}",
                   subject=f"{spec.L:g} x {spec.W:g} x {spec.H:g} {units}")
    pdf.style(0.7)
    pdf.rect(FRAME, FRAME, W - 2 * FRAME, H - 2 * FRAME)
    # geometry: cuts heavy, creases dashed, engraving light grey
    for layer, wpt, rgb, dash in ((ENGRAVE, 0.18, (0.45, 0.45, 0.45), None), (FOLD, 0.35, (0, 0, 0), (3.0, 1.2)),
                                  (CUT, 0.6, (0, 0, 0), None)):
        pdf.style(wpt, rgb, dash)
        for it in d.items:
            if it[-1] != layer:
                continue
            if it[0] == "L":
                pdf.line(T(*it[1]), T(*it[2]))
            else:
                pdf.arc(T(*it[1]), it[2] * k, it[3], it[4])
    # dimensions
    pdf.style(0.2)
    gap, over = 1.2, 1.5
    th = DIM_TXT * 25.4 / 72 * 0.72                        # cap height in mm (approx)
    n_crowd = 0
    for dm in style_dimensions(res, spec):
        label = _dim_label(dm["v"], dm["tol"], units) + (f" {dm['note']}" if dm.get("note") else "")
        tw = _text_w(label, DIM_TXT)
        if dm["kind"] == "h":
            a, b = T(dm["a"], 0)[0], T(dm["b"], 0)[0]
            yo = T(0, dm["ref"])[1]
            yb0 = T(0, dm.get("yref", dm["ref"]))[1]
            sgn = 1 if dm["row"] > 0 else -1
            yl = yb0 + sgn * (DIM_ROW1 if abs(dm["row"]) == 1 else DIM_ROW2)
            for xx in (a, b):
                pdf.line((xx, yo + sgn * gap), (xx, yl + sgn * over))
            lo, hi = min(a, b), max(a, b)
            pdf.line((lo, yl), (hi, yl))
            if hi - lo >= 6.0:
                pdf.arrow((lo, yl), (-1, 0))
                pdf.arrow((hi, yl), (1, 0))
            else:                                          # short span: arrows outside, pointing in
                pdf.arrow((lo, yl), (1, 0))
                pdf.arrow((hi, yl), (-1, 0))
                pdf.line((lo - 3, yl), (lo, yl))
                pdf.line((hi, yl), (hi + 3, yl))
            cx = (lo + hi) / 2
            ty = yl + 1.2 if sgn > 0 else yl - 1.2 - th
            if tw > hi - lo - 2:                           # text wider than its span
                if sgn < 0:                                # downward row: beside the dimension
                    pdf.text(hi + 4.5, yl - th / 2, label, DIM_TXT, "l")
                    continue
                if dm["tag"] == "glue":                    # leftmost: out to the left, where there is room
                    pdf.text(lo - 4.5, yl - th / 2, label, DIM_TXT, "r")
                    continue
                ty += (th + 1.4) * (n_crowd % 2)           # neighbours alternate between two text heights
                n_crowd += 1
            pdf.text(cx, ty, label, DIM_TXT, "c")
        else:
            a, b = T(0, dm["a"])[1], T(0, dm["b"])[1]
            xo = T(dm["ref"], 0)[0]
            xl = T(dm.get("xref", dm["ref"]), 0)[0] + (DIM_ROW1 if dm["row"] == 1 else DIM_ROW2)
            for yy in (a, b):
                pdf.line((xo + gap, yy), (xl + over, yy))
            lo, hi = min(a, b), max(a, b)
            pdf.line((xl, lo), (xl, hi))
            if hi - lo >= 6.0:
                pdf.arrow((xl, lo), (0, -1))
                pdf.arrow((xl, hi), (0, 1))
            else:
                pdf.arrow((xl, lo), (0, 1))
                pdf.arrow((xl, hi), (0, -1))
                pdf.line((xl, lo - 3), (xl, lo))
                pdf.line((xl, hi), (xl, hi + 3))
            avail = hi - lo - 2 * 2.5 - 1.0                # room between the arrowheads
            fs = DIM_TXT if tw <= avail else max(5.0, DIM_TXT * avail / tw)
            tw2 = _text_w(label, fs)
            pdf.text(xl - 1.2, (lo + hi) / 2 - tw2 / 2, label, fs, "l", rot=90)
    _flute_marker(pdf, T, k, res, spec)
    _draw_blocks(pdf, lay, res, spec, blocks, units, any(it[-1] == ENGRAVE for it in d.items))
    if not blocks.get("title"):                            # one-line caption when there is no title block
        cap = f"SCALE 1:{ratio:g}   UNITS: {units}   SHEET: {lay['sheet']}   {res.style.draw_cap}   DIMENSIONS ARE CREASE TO CREASE"
        pdf.style(0.2)
        pdf.text(FRAME + 3, FRAME + 3, cap, 7.0, "l")
    more = [b.page(res, spec, W, H, blocks) for b in DRAWING_BLOCKS
            if b.page and blocks.get(b.key) and not (b.key == "bends" and res.style.flat_parts)]
    return pdf.to_bytes(more=more) if more else pdf.to_bytes()


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

# =============================================================================
# Screen scaling: fixed pixel sizes (padding, panel widths, drawn coordinates) grow with the screen's DPI
# =============================================================================
SCALE = 1.0                   # 1.0 = a 96 dpi screen; 1.5 = 150 %, ...


def S(v):
    """A pixel size scaled for the screen (numbers, or a pair of them); whole pixels, never below 1 unless 0."""
    if isinstance(v, (tuple, list)):
        return tuple(S(x) for x in v)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or SCALE == 1.0 or v == 0:
        return v
    return max(1, int(round(v * SCALE)))


_PX_ALWAYS = ("padx", "pady", "ipadx", "ipady", "wraplength", "highlightthickness", "bd", "borderwidth", "sashwidth",
              "sashpad", "x", "y")
_PX_SIZED = ("Frame", "Canvas", "Toplevel", "LabelFrame", "PanedWindow", "Scrollbar", "Tk")   # width / height are pixels
_scaled_done = False


def detect_scale(root):
    """The scale for this screen: from the screen's resolution (dots per inch), or BOXFORGE_SCALE if set."""
    env = os.environ.get("BOXFORGE_SCALE")
    if env:
        try:
            return min(3.0, max(1.0, float(env)))
        except ValueError:
            pass
    if sys.platform == "darwin":                       # Tk on a Mac already works in points
        return 1.0
    try:
        sc = root.winfo_fpixels("1i") / 96.0
    except Exception:                                  # noqa: BLE001
        return 1.0
    return min(3.0, max(1.0, round(sc * 4) / 4.0)) if sc >= 1.2 else 1.0


def init_scale(root):
    """Set SCALE for this screen and, when it is above 100 %, make Tk apply it to every pixel size given as a widget
    option or to a geometry manager (pack / grid / place). Drawn coordinates and window sizes call S() themselves."""
    global SCALE, _scaled_done
    SCALE = detect_scale(root)
    if SCALE == 1.0 or _scaled_done:
        return SCALE
    _scaled_done = True
    try:
        root.tk.call("tk", "scaling", SCALE * 96.0 / 72.0)      # fonts are in points: they follow this
    except tk.TclError:
        pass

    def fix(cls_name, kw):
        for k in list(kw):
            if k in _PX_ALWAYS or (k in ("width", "height") and cls_name in _PX_SIZED):
                kw[k] = S(kw[k])
        return kw
    orig_init = tk.Widget.__init__

    def widget_init(self, master, widgetName, cnf={}, kw={}, extra=()):
        name = type(self).__name__
        base = next((c.__name__ for c in type(self).__mro__ if c.__module__ == "tkinter"), name)
        orig_init(self, master, widgetName, fix(base, dict(cnf)), fix(base, dict(kw)), extra)
    tk.Widget.__init__ = widget_init
    for cls, names in ((tk.Pack, ("pack", "pack_configure")), (tk.Grid, ("grid", "grid_configure")),
                       (tk.Place, ("place", "place_configure"))):
        for nm in names:
            f = getattr(cls, nm)

            def wrap(self, cnf={}, f=f, **kw):
                for k in ("padx", "pady", "ipadx", "ipady", "x", "y", "width", "height", "bordermode"):
                    if k in kw and k != "bordermode":
                        kw[k] = S(kw[k])
                    if k in cnf:
                        cnf = dict(cnf, **{k: S(cnf[k])})
                return f(self, cnf, **kw)
            setattr(cls, nm, wrap)
    return SCALE


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


def _decomma(t):
    """'1,234.5' and '1,234,567' lose their thousands separators; a lone comma is a decimal point, so '1,5' is 1.5 and
    '3,125' is 3.125 (not 3125: a size typed with a decimal comma is far more likely than one in thousands)."""
    def fix(m):
        if m.group(1).count(",") > 1 or m.group(2):
            return m.group(1).replace(",", "") + (m.group(2) or "")
        return m.group(0)
    t = _re.sub(r"(?<![\d.,])([1-9]\d{0,2}(?:,\d{3})+)(\.\d+)?(?![\d,])", fix, t)
    return t.replace(",", ".")


def parse_num(s):
    """'12', '12.5', '1/2', '1 1/2', '1,234.5' -> float; blank -> None; anything else (including nan/inf) raises ValueError."""
    s = _decomma((s or "").strip())
    if not s:
        return None
    try:
        v = float(s)
        if not math.isfinite(v):
            raise ValueError(s)
        return v
    except ValueError:
        pass
    try:
        if "/" in s:
            parts = s.split()
            whole = float(parts[0]) if len(parts) == 2 else 0.0
            n, d = parts[-1].split("/")
            frac = float(n) / float(d)
            if len(parts) == 2 and (parts[-1].startswith("-") or parts[-1].startswith("+")):
                raise ValueError(s)                       # '2 -3/4' is not a mixed number
            v = whole - frac if (len(parts) == 2 and parts[0].startswith("-")) else whole + frac
            if math.isfinite(v):
                return v
    except (ValueError, ZeroDivisionError):
        pass
    raise ValueError(s)


_CALC_UNITS = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "inch": 25.4, "inches": 25.4, "\"": 25.4,
               "ft": 304.8, "feet": 304.8, "'": 304.8}
_CALC_WORDS = (("divided by", "/"), ("multiplied by", "*"), ("times", "*"), ("minus", "-"), ("plus", "+"),
               ("over", "/"), ("less", "-"), ("add", "+"), ("\u00d7", "*"), ("\u00f7", "/"), ("\u2212", "-"))
_CALC_TOKEN = _re.compile(r"\s*(?:(\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+)|([A-Za-z\"']+)|(.))")


def calc_eval(text, cur, unit="mm"):
    """Small calculator for the input boxes. + - * / ( ), numbers with an optional length unit (mm cm m in ft),
    and `cur` / `current` for the box's present value. A leading operator works on the present value:
    '-2 in', '*2.5', '/2'. Numbers without a unit are in `unit` ('mm', 'in' or None = no units allowed).
    Returns a float; raises ValueError with a short reason."""
    t = _decomma((text or "").strip().lower())
    for w, sym in _CALC_WORDS:
        t = t.replace(w, f" {sym} ")
    if not t:
        raise ValueError("empty")
    if t[0] in "+-*/" and cur is not None:
        t = "cur " + t
    toks, pos = [], 0
    while pos < len(t):
        m = _CALC_TOKEN.match(t, pos)
        if not m or m.end() == pos:
            break
        pos = m.end()
        num, word, sym = m.groups()
        if num is not None:
            toks.append(("n", float(num)))
        elif word is not None:
            toks.append(("w", word))
        elif sym.strip():
            toks.append(("o", sym))
    k = {"mm": 1.0, "in": 25.4}.get(unit)
    i = 0

    def peek():
        return toks[i] if i < len(toks) else (None, None)

    def atom():
        """Returns (value, unit factor or None). A number with a unit is returned unconverted; term() applies the
        unit to the whole product/quotient, so '10/4 in' and '10 in / 4' agree."""
        nonlocal i
        kind, v = peek()
        if kind == "n":
            i += 1
            k2, w = peek()
            if (k2 == "w" and w in _CALC_UNITS) or (k2 == "o" and w in ("\"", "'")):
                i += 1
                if k is None:
                    raise ValueError("units are not used in this box")
                return v, _CALC_UNITS[w] / k
            return v, None
        if kind == "w" and v in ("cur", "current", "now"):
            i += 1
            if cur is None:
                raise ValueError("there is no current value")
            return cur, 1.0
        if kind == "o" and v == "(":
            i += 1
            x = expr()
            if peek() != ("o", ")"):
                raise ValueError("missing )")
            i += 1
            return x, None
        raise ValueError("can't read " + (repr(v) if v is not None else "the end of that"))

    def factor():
        nonlocal i
        kind, v = peek()
        if kind == "o" and v in "+-":
            i += 1
            x, u = factor()
            return (-x if v == "-" else x), u
        return atom()

    def term():
        nonlocal i
        x, uc = factor()
        while peek()[0] == "o" and peek()[1] in "*/":
            op = toks[i][1]
            i += 1
            y, yc = factor()
            if op == "/":
                if y == 0:
                    raise ValueError("divide by zero")
                x /= y
                if yc is not None:
                    if uc is None:
                        uc = yc                    # '10/4 in': the unit belongs to the whole term
                    else:
                        x *= uc / yc               # length / length is a plain ratio
                        uc = None
            else:
                x *= y
                if yc is not None:
                    if uc is not None:
                        raise ValueError("can't multiply two lengths; use a plain number")
                    uc = yc
        return x * uc if uc is not None else x

    def expr():
        nonlocal i
        x = term()
        while peek()[0] == "o" and peek()[1] in "+-":
            op = toks[i][1]
            i += 1
            y = term()
            x = x + y if op == "+" else x - y
        return x

    x = expr()
    if i != len(toks):
        raise ValueError("can't read " + repr(toks[i][1]))
    if not math.isfinite(x):
        raise ValueError("not a finite number")
    return x


def is_plain_number(text):
    """True when parse_num already understands the text (12, 12.5, 1/2, 1 1/2) and it is not a relative edit."""
    t = (text or "").strip()
    if t[:1] in ("+", "-", "*", "/"):
        return False
    try:
        parse_num(t)
        return True
    except ValueError:
        return False


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
        self.enabled = True
        self.cv = tk.Canvas(self, width=34, height=18, bg=T["panel"], highlightthickness=0, cursor="hand2")   # scaled by init_scale
        self.cv.pack(side="left")
        self.lb = tk.Label(self, text=text, font=F(9), bg=T["panel"], fg=T["text"], cursor="hand2")
        self.lb.pack(side="left", padx=(8, 0))
        for w in (self.cv, self.lb):
            w.bind("<Button-1>", lambda e: self.var.set(not self.var.get()) if self.enabled else None)
        self._tid = self.var.trace_add("write", lambda *a: self._paint())
        self.bind("<Destroy>", self._gone)
        self._paint()

    def _gone(self, e):
        if e.widget is self:
            try:
                self.var.trace_remove("write", self._tid)
            except (tk.TclError, ValueError):
                pass

    def set_enabled(self, enabled):
        """Grey the switch out (it keeps its value but cannot be clicked)."""
        self.enabled = bool(enabled)
        self.lb.config(fg=T["text"] if enabled else T["dim"], cursor="hand2" if enabled else "arrow")
        self.cv.config(cursor="hand2" if enabled else "arrow")
        self._paint()

    def _paint(self):
        on = self.var.get()
        c = self.cv
        c.delete("all")
        col = T["accent"] if (on and self.enabled) else T["border"]
        c.create_oval(1, 1, 17, 17, fill=col, outline=col)
        c.create_oval(17, 1, 33, 17, fill=col, outline=col)
        c.create_rectangle(9, 1, 25, 17, fill=col, outline=col)
        x = 25 if on else 9
        c.create_oval(x - 6, 3, x + 6, 15, fill="#ffffff", outline="#ffffff")
        if SCALE != 1.0:
            c.scale("all", 0, 0, SCALE, SCALE)


def make_paned(parent, orient):
    """A split container whose divider the user can drag. Panes keep a minimum size, so none can be closed up, and
    they cannot be pulled out into a window of their own (a PanedWindow has no such feature)."""
    return tk.PanedWindow(parent, orient=orient, sashwidth=7, sashrelief="flat", bg=T["border"], bd=0,
                          opaqueresize=True, showhandle=False,
                          sashcursor="sb_h_double_arrow" if orient == "horizontal" else "sb_v_double_arrow")


class ScrollFrame(tk.Frame):
    def __init__(self, master, bg, height=None, bar=False):
        super().__init__(master, bg=bg)
        self.cv = tk.Canvas(self, bg=bg, highlightthickness=0, **({"height": height} if height else {}))
        if bar:      # slim draggable scroll indicator
            self.bar = tk.Canvas(self, width=8, bg=bg, highlightthickness=0, cursor="hand2")   # scaled by init_scale
            self.bar.pack(side="right", fill="y")
            self.cv.configure(yscrollcommand=self._on_scroll)
            self.bar.bind("<Button-1>", self._bar_drag)
            self.bar.bind("<B1-Motion>", self._bar_drag)
        self.cv.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.cv, bg=bg)
        self.win = self.cv.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.cv.configure(scrollregion=self.cv.bbox("all")))
        self.cv.bind("<Configure>", lambda e: self.cv.itemconfigure(self.win, width=e.width))
        self.bind("<Enter>", lambda e: self._wheel_bind(True))
        self.bind("<Leave>", lambda e: self._wheel_bind(False))

    def _on_scroll(self, lo, hi):
        self.bar.delete("all")
        lo, hi = float(lo), float(hi)
        if hi - lo < 0.999:
            h = max(self.bar.winfo_height(), 1)
            self.bar.create_rectangle(1, lo * h + 1, S(7), hi * h - 1, fill=T["dim"], outline="")

    def _bar_drag(self, e):
        h = max(self.bar.winfo_height(), 1)
        lo, hi = self.cv.yview()
        self.cv.yview_moveto(max(0.0, min(1.0, e.y / h - (hi - lo) / 2)))

    def reveal(self, widget):
        """Scroll so `widget` is fully visible (used when a control appears below the fold)."""
        self.update_idletasks()
        total = max(self.inner.winfo_height(), 1)
        top = widget.winfo_rooty() - self.inner.winfo_rooty()
        bot = top + widget.winfo_height()
        lo, hi = self.cv.yview()
        view = self.cv.winfo_height()
        if bot > hi * total:
            self.cv.yview_moveto(max(0.0, min(1.0, (bot - view) / total)))
        elif top < lo * total:
            self.cv.yview_moveto(max(0.0, top / total))

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


class SwatchPicker(tk.Canvas):
    """One colour swatch with a drop-down arrow. Click it and a small popup of the preset line colours opens; click a
    colour to set `var` to its name (the popup closes), or click anywhere else / press Esc to close it unchanged."""

    def __init__(self, master, var, bg, cols=4, size=28, gap=6):
        self.sw = S(24)
        super().__init__(master, width=self.sw + S(22), height=self.sw + S(4), bg=bg, highlightthickness=0, cursor="hand2")
        self.var, self.cols, self.size, self.gap, self.pop = var, cols, S(size), S(gap), None
        self.bind("<Button-1>", self._toggle)
        self.bind("<Destroy>", lambda e: self._close() if e.widget is self else None)
        self._trace = var.trace_add("write", lambda *a: self.draw())
        self.draw()

    def _hex(self, name=None):
        name = self.var.get() if name is None else name
        return next((h for n, h, _ in LINE_COLORS if n == name), "#888888")

    def draw(self):
        try:
            self.delete("all")
        except tk.TclError:
            return
        self.create_rectangle(2, 2, 2 + self.sw, 2 + self.sw, fill=self._hex(), outline=T["border"], width=1)
        x, y = 2 + self.sw + S(10), 2 + self.sw / 2
        self.create_polygon(x - S(5), y - S(2), x + S(5), y - S(2), x, y + S(4), fill=T["muted"], outline="")

    def _cell(self, i):
        r, c = divmod(i, self.cols)
        return S(8) + c * (self.size + self.gap), S(8) + r * (self.size + self.gap)

    def _toggle(self, e=None):
        if self.pop is not None:
            self._close()
        else:
            self._open()

    def _open(self):
        rows = -(-len(LINE_COLORS) // self.cols)
        w = self.cols * (self.size + self.gap) - self.gap + S(16)
        h = rows * (self.size + self.gap) - self.gap + S(16) + S(22)
        pop = self.pop = tk.Toplevel(self, bg=T["border"])
        pop.overrideredirect(True)
        x, y = self.winfo_rootx(), self.winfo_rooty() + self.winfo_height() + 2
        x = max(0, min(x, self.winfo_screenwidth() - w - 2))
        if y + h > self.winfo_screenheight():                       # no room below: open above the swatch
            y = max(0, self.winfo_rooty() - h - 2)
        pop.geometry(f"{w}x{h}+{x}+{y}")
        inner = tk.Canvas(pop, width=w - 2, height=h - 2, bg=T["panel2"], highlightthickness=0, cursor="hand2")
        inner.place(x=1, y=1)
        self._cv, self._name_id = inner, None

        def paint(hover=None):
            inner.delete("all")
            cur = self.var.get()
            for i, (name, hx, _a) in enumerate(LINE_COLORS):
                cx, cy = self._cell(i)
                sel = name == cur
                inner.create_rectangle(cx, cy, cx + self.size, cy + self.size, fill=hx, width=3 if sel else 1,
                                       outline=T["text"] if sel else T["border"])
            inner.create_text(S(8), h - S(17), text=hover or cur, anchor="w", font=F(8), fill=T["muted"])

        def at(ev):
            for i, (name, _h, _a) in enumerate(LINE_COLORS):
                cx, cy = self._cell(i)
                if cx <= ev.x <= cx + self.size and cy <= ev.y <= cy + self.size:
                    return name
            return None

        def pick(ev):
            name = at(ev)
            if name:
                self.var.set(name)
                self._close()

        def move(ev):
            paint(at(ev))
        inner.bind("<Button-1>", pick)
        inner.bind("<Motion>", move)
        inner.bind("<Leave>", lambda ev: paint())
        paint()
        pop.bind("<Escape>", lambda ev: self._close())
        pop.bind("<Button-1>", lambda ev: self._close() if ev.widget is pop else None)   # a click outside the popup
        try:
            pop.update_idletasks()
            pop.wait_visibility()
            pop.grab_set()
            pop.focus_force()
        except tk.TclError:
            pass

    def _close(self):
        pop, self.pop = self.pop, None
        if pop is not None:
            try:
                pop.grab_release()
            except tk.TclError:
                pass
            try:
                pop.destroy()
            except tk.TclError:
                pass


class Slider(tk.Canvas):
    """Flat 0-100 slider bound to a DoubleVar."""

    def __init__(self, master, var, command, lo=0.0, hi=100.0, step=None):
        super().__init__(master, height=24, bg=T["panel"], highlightthickness=0, cursor="hand2")   # scaled by init_scale
        self.var, self.command, self.lo, self.hi, self.step = var, command, lo, hi, step
        self.bind("<Configure>", lambda e: self._paint())
        self.bind("<Button-1>", self._set)
        self.bind("<B1-Motion>", self._set)
        self.var.trace_add("write", lambda *a: self._paint())

    def _set(self, e):
        pad, w = S(12), max(self.winfo_width(), 40)
        v = self.lo + (self.hi - self.lo) * max(0.0, min(1.0, (e.x - pad) / (w - 2 * pad)))
        if self.step:
            v = round(v / self.step) * self.step
        self.var.set(round(max(self.lo, min(self.hi, v)), 6))
        self.command()

    def _paint(self):
        self.delete("all")
        pad, w, h = S(12), max(self.winfo_width(), 40), S(24)
        x = pad + (w - 2 * pad) * (self.var.get() - self.lo) / (self.hi - self.lo)
        self.create_line(pad, h / 2, w - pad, h / 2, fill=T["border"], width=S(4), capstyle="round")
        self.create_line(pad, h / 2, x, h / 2, fill=T["accent"], width=S(4), capstyle="round")
        r = S(8)
        self.create_oval(x - r, h / 2 - r, x + r, h / 2 + r, fill="#ffffff", outline=T["accent"], width=S(2))


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
        self.bend = None                                    # inside bend radius (panel units) for rounded folds, or None
        self.bend_k, self.bend_len = None, True             # K-factor; take the bend's length out of the flaps
        self.style_id = "rsc"                               # picks the fold order of the solid view
        self.flute = None                                   # "v" / "h": faint flute lines on the outside faces
        self.edges = False                                  # solid mode: dark outlines on the faces (off by default)
        self.items = {}
        self.center, self.radius = (0, 0, 0), 1.0
        self.shadow = None
        self.solid, self.thick = False, 0.0           # solid mode: panels drawn as slabs of board thickness
        self.seq = False                              # RSC: real fold order + thick panels that sit against each other
        self._layer = None
        self.fixed_frame = False                      # editor: frame the whole fold sequence once, so the camera never drifts
        self._frame_cache = None
        self._model = None                            # solid mode: everything that does not change while only the camera moves
        self._model_key = None

    def _frame(self):
        """(centre, radius) of a sphere around the model in every state of the fold, so that the picture keeps one framing
        from the flat sheet to the closed box instead of re-centring and re-scaling on each frame. Cached until the
        model itself changes (sizes, board, bends), not when only the fold amount or the camera does."""
        key = (id(self.panels), self.thick, self.bend, self.bend_k, self.bend_len, self.flute, self.seq, self.style_id,
               self.up)
        if self._frame_cache and self._frame_cache[0] == key:
            return self._frame_cache[1]
        keep = self.amount
        pts = []
        try:
            for a in (0.45, 0.55, 0.7, 0.85, 1.0, 1.0):
                self.amount = a
                if self.seq and self.thick > 0:
                    pts += [self._orient(q) for f in self.solid_faces(sharp=True) if f[1] == "out" for q in f[2]]
                else:
                    pts += [self._orient(q) for poly in fold_panels(self.panels, a).values() for q in poly]
        finally:
            self.amount = keep
        xs, ys, zs = zip(*pts)
        c = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2)
        res = (c, max(1e-6, max(math.dist(c, q) for q in pts)))
        n1 = len(pts) // 6                                  # the closed box (last sample): where the floor shadow goes
        fx, fy, fz = zip(*pts[-n1:])
        self._floor = ((min(fx) + max(fx)) / 2, min(ys), (min(fz) + max(fz)) / 2, max(max(fx) - min(fx), max(fz) - min(fz)) / 2)
        self._frame_cache = (key, res)
        return res

    def _shadow_box(self, c0, R, W, H, scale, cyw, syw, cp, sp, dcam):
        """Screen box (x0, y0, x1, y1) of the floor shadow. With a fixed frame it lies on the floor under the closed box;
        otherwise it keeps the old placement relative to the model's centre."""
        if self.fixed_frame and getattr(self, "_floor", None):
            fx, fy, fz, rr = self._floor
            x, y, z = fx - c0[0], fy - c0[1], fz - c0[2]
            x1, z1 = cyw * x + syw * z, -syw * x + cyw * z
            y2, z2 = cp * y - sp * z1, sp * y + cp * z1
            f = dcam / (dcam - z2)
            sx, sy = W / 2 + x1 * scale * f, H / 2 - y2 * scale * f
            sw = max(rr * 1.35, R * 0.18) * scale * f
            return sx - sw, sy - sw * 0.28, sx + sw, sy + sw * 0.28
        sw = R * 1.05 * scale
        cy = H / 2 + R * 0.78 * scale * 0.80
        return W / 2 - sw, cy - sw * 0.28, W / 2 + sw, cy + sw * 0.28

    def _orient(self, p):
        return (p[0], p[2], -p[1]) if self.up == "z" else p

    def set_panels(self, panels, up=None):
        if up:
            self.up = up
        self.cv.delete("all")
        self.items, self.shadow = {}, None
        self.panels = panels
        self._model = self._model_key = self._frame_cache = None
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
        if self.solid and self.thick > 0:
            return self._render_solid(W, H)
        if self.items.get("_solid"):
            cv.delete("solid")
            self.items.pop("_solid", None)
            self.items = {}
        if self.seq and self.thick > 0:                   # wire view of the same model: outside face outlines
            polys = {nm: pts for nm, kind, pts, role in self.solid_faces(sharp=True) if kind == "out"}
        else:
            polys = fold_panels(self.panels, self.amount)
        # fit the model as it is *right now* (flat sheet and folded box differ a lot in size)
        if self.fixed_frame:
            (cx0, cy0, cz0), R = self._frame()
        else:
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
        cv.coords(self.shadow, *self._shadow_box((cx0, cy0, cz0), R, W, H, scale, cyw, syw, cp, sp, dcam))
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


    def solid_faces(self, sharp=False):
        bend = None if sharp else self.bend
        if self.seq and self.thick > 0:
            pf, lift, self._layer = style_sequence(self.style_id, self.panels, self.thick, self.amount)
            return solid_faces(self.panels, self.thick, pf, lift, bend=bend, bend_k=self.bend_k, bend_len=self.bend_len,
                               flute=self.flute)
        self._layer = None
        return solid_faces(self.panels, self.thick,
                           lambda p, d, m: min(1.0, max(0.0, self.amount * m - (d - 1))), bend=bend,
                           bend_k=self.bend_k, bend_len=self.bend_len, flute=self.flute)

    def _solid_model(self):
        """The folded slabs, their centre and radius, and the plate-order cache. These depend on the fold amount, the
        board, the bends and so on but not on the camera, so turning the model reuses them instead of folding again."""
        key = (id(self.panels), self.amount, self.thick, self.bend, self.bend_k, self.bend_len, self.flute, self.seq,
               self.style_id, self.up)
        if self._model is not None and self._model_key == key:
            return self._model
        faces = self.solid_faces()
        if self.fixed_frame:
            c0, R = self._frame()
        else:
            allp = [self._orient(q) for f in faces for q in f[2]]
            xs, ys, zs = zip(*allp)
            c0 = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2)
            R = max(1e-6, max(math.dist(c0, q) for q in allp))
        local = []                                          # [(name, kind, role, [(x, y, z) about the centre])]
        geo = {}
        for name, kind, pts, role in faces:
            loc = [tuple(c - o for c, o in zip(self._orient(q), c0)) for q in pts]
            local.append((name, kind, role, loc))
            if kind != "flute":
                geo.setdefault(name, []).append((kind, loc))
        self._model = (local, geo, c0, R, {})
        self._model_key = key
        return self._model

    def _render_solid(self, W, H):
        cv = self.cv
        local, geo, c0, R, order_cache = self._solid_model()
        scale = min(W, H) * 0.40 * self.zoom / R
        cyw, syw = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        dcam = 4.2 * R
        cam_model = (-syw * cp * dcam, sp * dcam, cyw * cp * dcam)      # the camera (0, 0, dcam), turned back into model space
        cv.delete("all")
        self.items, self.shadow = {"_solid": True}, None
        cv.create_oval(*self._shadow_box(c0, R, W, H, scale, cyw, syw, cp, sp, dcam),
                       fill=mix(T["thumb"], "#000000", 0.35), outline="", tags="solid")
        light = (-0.35, 0.55, 0.76)
        conv, plates, flutes = [], {}, []
        for name, kind, role, pts in local:
            sc, zz, cam = [], [], []
            for q in pts:
                x, y, z = q
                x1, z1 = cyw * x + syw * z, -syw * x + cyw * z
                y2, z2 = cp * y - sp * z1, sp * y + cp * z1
                f = dcam / (dcam - z2)
                sc.append((W / 2 + x1 * scale * f, H / 2 - y2 * scale * f))
                zz.append(z2)
                cam.append((x1, y2, z2))
            if kind == "flute":                                # drawn after the outside face it sits on
                flutes.append((name, sc))
                continue
            conv.append((name, kind, role, sc, zz, cam))
            plates.setdefault(name, []).append((kind, cam))
        rank = plate_order(plates, (0.0, 0.0, dcam), geo, cam_model, order_cache)
        out, out_col = [], {}
        for name, kind, role, sc, zz, cam in conv:
            # face normal in camera space (screen y is flipped, so use the camera-space points)
            nrm = _tri_normal(cam[0], cam[1], cam[2])
            for k in range(2, len(cam) - 1):                  # robust for concave outlines: use best-conditioned triple
                if abs(nrm[2]) > 1e-6 or kind != "out":
                    break
                nrm = _tri_normal(cam[0], cam[k], cam[k + 1])
            if kind == "edge":
                nrm = _tri_normal(cam[0], cam[1], cam[2])
            # polygon orientation decides whether it faces the viewer: use the signed area on screen
            a2 = sum(sc[i][0] * sc[(i + 1) % len(sc)][1] - sc[(i + 1) % len(sc)][0] * sc[i][1] for i in range(len(sc)))
            if kind == "edge":
                if a2 >= 0:                                    # screen y points down: negative area = CCW seen from front
                    continue
            else:
                # faces list is wound CCW looking at the outside (out) / inside (in, reversed) in panel space,
                # transform keeps handedness, so the same test applies
                if a2 >= 0:
                    continue
            ndl = max(0.0, nrm[0] * light[0] + nrm[1] * light[1] + nrm[2] * light[2])
            base_o = T["body"] if role == "body" else T["flap"]
            base_i = T["body_dim"] if role == "body" else T["flap_dim"]
            if kind == "out":
                col = mix(base_i, base_o, 0.55 + 0.45 * ndl)
            elif kind == "in":
                col = mix(base_i, "#000000", 0.30 - 0.12 * ndl)
            else:
                col = mix(base_i, base_o, 0.25 + 0.4 * ndl)
            if kind == "out":
                out_col[name] = col
            out.append(((rank.get(name, 0), sum(zz) / len(zz)),
                        [c for xy in sc for c in xy], col, "bend" if (name.endswith(".bend") or "~" in name) and kind != "edge" else kind))
        for name, sc in flutes:                                # only on outside faces that face the viewer
            if name in out_col:
                out.append(((rank.get(name, 0), 1e18), [c for xy in sc for c in xy], mix(out_col[name], "#000000", 0.2),
                            "flute"))
        out.sort(key=lambda r: r[0])
        edge_col = mix(T["thumb"], "#000000", 0.55)
        for z, flat, col, kind in out:
            if kind == "flute":
                cv.create_line(*flat, fill=col, width=1, tags="solid")
                continue
            cv.create_polygon(*flat, fill=col, outline=col if (kind == "bend" or not self.edges) else edge_col, width=0.6,
                              joinstyle="round",
                              tags="solid")


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
        if SCALE != 1.0:
            logo.scale("all", 0, 0, SCALE, SCALE)
        for glyph, label, cmd in (("⌂", "Home", None), ("ⓘ", "Limits", app.show_limits), ("?", "About", app.show_about)):
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
        Btn(head, "Open project…", app.open_project, "ghost", size=9, padx=14, pady=6).pack(anchor="w", pady=(12, 0))
        self.recent_host = tk.Frame(main, bg=T["bg"])
        self.recent_host.pack(fill="x", padx=40)
        self.sf = ScrollFrame(main, T["bg"], bar=True)             # the cards scroll when they do not all fit
        self.sf.pack(fill="both", expand=True, padx=(34, 20), pady=(16, 14))
        self.grid_host = self.sf.inner
        for s in STYLES:
            self.cards.append(Card(self.grid_host, s, app.open_style))
        self.cols = 0
        self.sf.cv.bind("<Configure>", self._reflow, add="+")

    def refresh_recent(self):
        """The list of recent projects under the heading (hidden when there are none)."""
        for w in self.recent_host.winfo_children():
            w.destroy()
        shown = [p for p in self.app.recent if os.path.exists(p)][:5]
        if not shown:
            return
        tk.Label(self.recent_host, text="RECENT PROJECTS", font=F(8, "bold"), fg=T["dim"], bg=T["bg"]).pack(anchor="w", pady=(10, 4))
        for p in shown:
            row = tk.Frame(self.recent_host, bg=T["bg"], cursor="hand2")
            row.pack(fill="x")
            a = tk.Label(row, text=os.path.splitext(os.path.basename(p))[0], font=F(10, "bold"), fg=T["text"], bg=T["bg"],
                         cursor="hand2")
            a.pack(side="left")
            b = tk.Label(row, text="   " + os.path.dirname(p), font=F(9), fg=T["dim"], bg=T["bg"], cursor="hand2")
            b.pack(side="left")
            for w in (row, a, b):
                w.bind("<Button-1>", lambda e, q=p: self.app.open_project(q))
                w.bind("<Enter>", lambda e, w=a: w.config(fg=T["accent_h"]))
                w.bind("<Leave>", lambda e, w=a: w.config(fg=T["text"]))

    def _reflow(self, e):
        cols = 3 if e.width >= S(1020) else 2 if e.width >= S(680) else 1
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
        self.perf = tk.BooleanVar(value=sv.get("perf", False))
        self.flute = tk.StringVar(value=sv.get("flute", "off"))      # corrugated flute direction: off / v / h
        self.dvars = {k: (tk.BooleanVar if k in ("bend_on", "bend_len", "bend_edges") else tk.DoubleVar)(value=app.dash[k])
                      for k in ("perf_dash", "perf_tie", "bend_r", "bend_on", "bend_len", "bend_edges")}
        self.project_path = None                              # the project file this box was opened from / saved to
        self.flags = {k: tk.BooleanVar(value=sv.get("flag_" + k, d)) for k, _, d in style.toggles}
        self.vars = {}
        for k in ("L", "W", "H", "t"):
            self.vars[k] = tk.StringVar(value=sv.get(k, fmt(getattr(spec0, k), 3)))
        if style.square:                                      # a square-only style: Width follows Length
            self.vars["W"].set(self.vars["L"].get())
            self.vars["L"].trace_add("write", lambda *a: self.vars["W"].set(self.vars["L"].get()))
        for k, _ in style.options:
            self.vars[k] = tk.StringVar(value=sv.get(k, ""))
        self.vars["kerf"] = tk.StringVar(value=sv.get("kerf", ""))
        self.has_drawing = True                              # engineering drawing sheets: every style
        self.has_solid = True                                # board-thickness 3-D preview: every style
        if self.has_drawing:
            for k in TOL_LABELS:
                self.vars["tol_" + k] = tk.StringVar(value=sv.get("tol_" + k, ""))
        self.tol_open = tk.BooleanVar(value=False)
        self.vars["sheetw"] = tk.StringVar(value=sv.get("sheetw", ""))
        self.vars["sheeth"] = tk.StringVar(value=sv.get("sheeth", ""))
        lk = app.look                      # colours / weights are shared by every box in this session
        self.lvars = {k: tk.StringVar(value=lk[k] if k.endswith("color") else fmt(lk[k], 4))
                      for k in ("cut_color", "fold_color", "cut_weight", "fold_weight", "engrave_color", "engrave_weight")}
        self.features, self.sel = [], None            # windows / zones live for this editor session only
        self.fvars = {k: tk.StringVar() for k in ("cx", "cy", "w", "h", "r")}
        self._fplain = {}                                # last plain number in each window / zone box (for typed maths)

        def _keep(k):
            def f(*a):
                if is_plain_number(self.fvars[k].get()):
                    try:
                        self._fplain[k] = parse_num(self.fvars[k].get())
                    except ValueError:
                        pass
            return f
        for k, v in self.fvars.items():
            v.trace_add("write", _keep(k))
        self.f_outline, self.f_rot = tk.BooleanVar(value=False), tk.BooleanVar(value=False)
        self._floading, self._fdrag = False, None
        self.view_mode = tk.StringVar(value=sv.get("view", "split"))
        self.amount = tk.DoubleVar(value=100.0)
        for k, v in self.flags.items():                       # a switch that adds something inside the box starts with the box open
            if v.get() and style.toggle_view(k) is not None:
                self.amount.set(style.toggle_view(k) * 100.0)
        self.ents, self.auto_lbl = {}, {}
        self._last_units = self.units.get()

        self._build_top()
        body = self.body = make_paned(self, "horizontal")          # sidebar | views, divider draggable
        body.pack(fill="both", expand=True)
        self._build_sidebar(body)
        self._build_main(body)
        self._sash_drag = False
        for w_ in (self.body, self.vp, self.stage):
            w_.bind("<ButtonPress-1>", self._sash_press, add="+")
            w_.bind("<ButtonRelease-1>", self._sash_release, add="+")
        self.stage.bind("<Configure>", lambda e: self._apply_split(), add="+")
        self.side.bind("<Configure>", lambda e: self._fit_wraps(), add="+")
        self.after_idle(self._init_sashes)

        for v in list(self.vars.values()) + [self.mode, self.folds, self.perf, self.flute] + list(self.dvars.values()) + list(self.flags.values()) + list(self.lvars.values()):
            v.trace_add("write", lambda *a: self.schedule())
        for v in list(self.fvars.values()) + [self.f_outline, self.f_rot]:
            v.trace_add("write", lambda *a: self._fvar_changed())
        self.units.trace_add("write", self._on_units)
        self.view_mode.trace_add("write", lambda *a: self._layout_views())
        self._undo, self._redo, self._base, self._last_change, self._restoring = [], [], None, 0.0, False
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
        Btn(right, "Save", self.app.save_project, "ghost", size=9, padx=14, pady=6).pack(side="right", padx=(10, 0), pady=11)
        Seg(right, [("dieline", "Dieline"), ("split", "Split"), ("fold3d", "3-D fold")], self.view_mode).pack(
            side="right", pady=12)

    def _section(self, parent, text):
        tk.Label(parent, text=text, font=F(8, "bold"), fg=T["dim"], bg=T["panel"], anchor="w").pack(
            fill="x", padx=18, pady=(16, 6))

    def _calc_bind(self, entry, var, unit_of, toast=True, cur_fn=None):
        """Typed maths in a number box: evaluated on Enter or when the box loses focus (never while typing).
        `unit_of()` gives 'mm' / 'in' for length boxes or None for unitless ones."""
        last = {"v": None}

        def plain_now(*a):
            tx = var.get()
            if is_plain_number(tx):
                try:
                    last["v"] = parse_num(tx)
                except ValueError:
                    pass
        if cur_fn is None:                                   # remember the last plain value typed in this box
            plain_now()
            var.trace_add("write", plain_now)

        def commit(e=None):
            tx = var.get()
            if not tx.strip() or is_plain_number(tx):
                return
            try:
                r = calc_eval(tx, cur_fn() if cur_fn else last["v"], unit_of())
            except ValueError as exc:
                self.toast.config(text=f"Can't work that out: {exc}.", fg=T["err"])
                return
            var.set(fmt(r, 4 if self.units.get() == "in" else 3))
            self.toast.config(text=f"{tx.strip()}  =  {var.get()}", fg=T["muted"])
        entry.bind("<Return>", commit, add="+")
        entry.bind("<KP_Enter>", commit, add="+")
        entry.bind("<FocusOut>", commit, add="+")

    def _unit_for(self, key):
        return lambda: "mm" if key.startswith("tol_") else self.units.get()

    def _field(self, parent, key, label, unit=True):
        row = tk.Frame(parent, bg=T["panel"])
        row.pack(fill="x", padx=18, pady=3)
        row.grid_columnconfigure(0, weight=1)                        # a long label wraps; the entry keeps its size and column
        tk.Label(row, text=label, font=F(9), fg=T["text"], bg=T["panel"], anchor="w", justify="left",
                 wraplength=150).grid(row=0, column=0, sticky="w")
        right = tk.Frame(row, bg=T["panel"])
        right.grid(row=0, column=1, sticky="e")
        lbl = tk.Label(right, text="", font=F(8), fg=T["dim"], bg=T["panel"], width=9, anchor="e")
        lbl.pack(side="left", padx=(0, 6))
        e = tk.Entry(right, textvariable=self.vars[key], width=8, font=F(10), bg=T["panel2"], fg=T["text"],
                     insertbackground=T["text"], relief="flat", justify="right", highlightthickness=1,
                     highlightbackground=T["border"], highlightcolor=T["accent"])
        e.pack(side="left", ipady=4)
        self._calc_bind(e, self.vars[key], self._unit_for(key))
        self.ents[key], self.auto_lbl[key] = e, lbl

    def _lfield(self, parent, key, label, unit):
        row = tk.Frame(parent, bg=T["panel"])
        row.pack(fill="x", padx=18, pady=3)
        tk.Label(row, text=label, font=F(9), fg=T["text"], bg=T["panel"], anchor="w").pack(side="left")
        right = tk.Frame(row, bg=T["panel"])
        right.pack(side="right")
        tk.Label(right, text=unit, font=F(8), fg=T["dim"], bg=T["panel"], width=9, anchor="e").pack(
            side="left", padx=(0, 6))
        e = tk.Entry(right, textvariable=self.lvars[key], width=8, font=F(10), bg=T["panel2"], fg=T["text"],
                     insertbackground=T["text"], relief="flat", justify="right", highlightthickness=1,
                     highlightbackground=T["border"], highlightcolor=T["accent"])
        e.pack(side="left", ipady=4)
        if not key.endswith("color"):
            self._calc_bind(e, self.lvars[key], lambda: None)
        self.ents[key] = e

    def _color_row(self, parent, key, label):
        row = tk.Frame(parent, bg=T["panel"])
        row.pack(fill="x", padx=18, pady=(6, 2))
        tk.Label(row, text=label, font=F(9), fg=T["text"], bg=T["panel"], anchor="w").pack(side="left")
        SwatchPicker(row, self.lvars[key], T["panel"]).pack(side="right")
        tk.Label(row, textvariable=self.lvars[key], font=F(8), fg=T["dim"], bg=T["panel"], anchor="e").pack(
            side="right", padx=(0, 6))

    def _build_sidebar(self, parent):
        side = self.side = tk.Frame(parent, bg=T["panel"], width=1)
        parent.add(side, minsize=S(290), width=self.app.layout["side_w"], stretch="never")
        side.pack_propagate(False)
        vp = self.vp = make_paned(side, "vertical")                # options above, checks + export below
        vp.pack(fill="both", expand=True)
        top_pane = tk.Frame(vp, bg=T["panel"])
        self.lower = tk.Frame(vp, bg=T["panel"])
        vp.add(top_pane, minsize=S(150), stretch="always")
        vp.add(self.lower, minsize=S(92), stretch="never")
        low_sf = self.lower_sf = ScrollFrame(self.lower, T["panel"], height=60, bar=True)   # scrolls when the window is short
        low_sf.pack(fill="both", expand=True)
        low = low_sf.inner
        bottom = tk.Frame(low, bg=T["panel"])
        bottom.pack(side="bottom", fill="x", padx=16, pady=14)
        row = tk.Frame(bottom, bg=T["panel"])
        row.pack(fill="x")
        self.export_btns = []
        for i, (kind, label) in enumerate(EXPORT_FORMATS):
            if i == 2:
                row = tk.Frame(bottom, bg=T["panel"])
                row.pack(fill="x", pady=(6, 0))
            b = Btn(row, ("Export " + label) if i < 2 else label, lambda k=kind: self.export(k),
                    "primary" if i == 0 else "ghost", size=10 if i < 2 else 9, pady=10 if i < 2 else 6)
            b.pack(side="left", fill="x", expand=True, padx=(0, 6) if i not in (1, len(EXPORT_FORMATS) - 1) else 0)
            self.export_btns.append(b)
        if self.has_drawing:
            b = Btn(bottom, "Export Drawing (PDF)…", self.export_drawing, "ghost", size=9, pady=7)
            b.pack(fill="x", pady=(6, 0))
            self.export_btns.append(b)
            b = Btn(bottom, "Export 3D Model (3MF / STL)…", self.export_model3d, "ghost", size=9, pady=7)
            b.pack(fill="x", pady=(6, 0))
            self.export_btns.append(b)
        self.toast = tk.Label(bottom, text="", font=F(8), fg=T["good"], bg=T["panel"], wraplength=310, justify="left",
                              anchor="w")
        self.toast.pack(fill="x", pady=(8, 0))
        chk_wrap = tk.Frame(low, bg=T["panel"])
        chk_wrap.pack(side="bottom", fill="x")
        tk.Label(chk_wrap, text="CHECKS", font=F(8, "bold"), fg=T["dim"], bg=T["panel"], anchor="w").pack(
            fill="x", padx=18, pady=(10, 2))
        chk_sf = ScrollFrame(chk_wrap, T["panel"], height=72)
        chk_sf.pack(fill="x", padx=0)
        self.checks = chk_sf.inner
        tk.Frame(low, bg=T["border"], height=1).pack(side="bottom", fill="x")

        sf = self.side_sf = ScrollFrame(top_pane, T["panel"], bar=True)
        sf.pack(fill="both", expand=True)
        s = sf.inner
        hdr = tk.Frame(s, bg=T["panel"])
        hdr.pack(fill="x", padx=18, pady=(14, 0))
        tk.Label(hdr, text="Units", font=F(9), fg=T["text"], bg=T["panel"]).pack(side="left")
        Seg(hdr, [("mm", "mm"), ("in", "inch")], self.units).pack(side="right")

        self._section(s, "DIMENSIONS")
        self._field(s, "L", "Length")
        self._field(s, "W", "Width (same as length)" if self.style.square else "Width")
        if self.style.square:
            self.ents["W"].config(state="disabled", disabledbackground=T["panel"], disabledforeground=T["muted"])
        self._field(s, "H", self.style.height_label)
        self._field(s, "t", "Material thickness")

        self._section(s, "THESE DIMENSIONS ARE…")
        Seg(s, [("inner", "Inner"), ("outer", "Outer"), ("manufacturer", "Maker")], self.mode).pack(
            anchor="w", padx=18)
        self.mode_lbl = tk.Label(s, text="", font=F(8), fg=T["muted"], bg=T["panel"], wraplength=310, justify="left",
                                 anchor="w")
        self.mode_lbl.pack(fill="x", padx=18, pady=(6, 0))

        self._section(s, "OPTIONS")
        Switch(s, "Include fold lines", self.folds).pack(anchor="w", padx=18, pady=3)
        sw_perf = Switch(s, "Dashed cuts instead of fold lines", self.perf)
        sw_perf.pack(anchor="w", padx=18, pady=3)
        self.dash_box = tk.Frame(s, bg=T["panel"])
        self.dash_val = {}
        for key, label, lo, hi, step in (("perf_dash", "Dash length", 1.0, 20.0, 0.5),
                                          ("perf_tie", "Bridge spacing", 0.5, 10.0, 0.1)):
            row = tk.Frame(self.dash_box, bg=T["panel"])
            row.pack(fill="x", pady=(2, 0))
            tk.Label(row, text=label, font=F(9), fg=T["muted"], bg=T["panel"], anchor="w").pack(side="left")
            self.dash_val[key] = tk.Label(row, text="", font=F(9, "bold"), fg=T["text"], bg=T["panel"], anchor="e")
            self.dash_val[key].pack(side="right")
            Slider(self.dash_box, self.dvars[key], lambda: None, lo, hi, step).pack(fill="x")
        tk.Label(self.dash_box, text="Cut length and uncut bridge along each fold, in mm.", font=F(8), fg=T["dim"],
                 bg=T["panel"], anchor="w").pack(fill="x")
        self._sw_perf = sw_perf
        self.perf.trace_add("write", lambda *a: self._show_dash())
        for k, v in self.dvars.items():
            v.trace_add("write", lambda *a, k=k: self._dash_changed(k))
        self._show_dash()
        Switch(s, "Edge lines in the 3-D preview", self.dvars["bend_edges"]).pack(anchor="w", padx=18, pady=3)
        tk.Label(s, text="Flute direction (corrugated board)", font=F(9), fg=T["text"], bg=T["panel"], anchor="w").pack(
            fill="x", padx=18, pady=(8, 3))
        Seg(s, [("off", "Off"), ("v", "Vertical"), ("h", "Horizontal")], self.flute).pack(anchor="w", padx=18)
        tk.Label(s, text="Vertical = along the flat sheet's up-down axis. Shown as faint lines on the outside of the "
                         "3-D preview and as a label on the drawing.", font=F(8), fg=T["dim"], bg=T["panel"],
                 wraplength=310, justify="left", anchor="w").pack(fill="x", padx=18, pady=(4, 6))
        if self.style.rounded_folds:
            Switch(s, "Rounded folds in the 3-D preview", self.dvars["bend_on"]).pack(anchor="w", padx=18, pady=3)
            Switch(s, "Take bend length out of the flaps", self.dvars["bend_len"]).pack(anchor="w", padx=18, pady=3)
            brow = tk.Frame(s, bg=T["panel"])
            brow.pack(fill="x", padx=18, pady=(0, 4))
            r_ = tk.Frame(brow, bg=T["panel"])
            r_.pack(fill="x", pady=(2, 0))
            tk.Label(r_, text="Inside bend radius", font=F(9), fg=T["muted"], bg=T["panel"], anchor="w").pack(side="left")
            self.dash_val["bend_r"] = tk.Label(r_, text="", font=F(9, "bold"), fg=T["text"], bg=T["panel"], anchor="e")
            self.dash_val["bend_r"].pack(side="right")
            Slider(brow, self.dvars["bend_r"], lambda: None, 0.0, 3.0, 0.05).pack(fill="x")
            tk.Label(brow, text="In board thicknesses. Preview and the bend data page only; the dieline is unchanged.",
                     font=F(8), fg=T["dim"], bg=T["panel"], anchor="w", wraplength=300, justify="left").pack(fill="x")
            self._dash_changed("bend_r", schedule=False)
        self.flag_sw, self.flag_hint = {}, {}
        for key, label, _ in self.style.toggles:
            sw_ = Switch(s, label, self.flags[key])
            sw_.pack(anchor="w", padx=18, pady=3)
            hint = tk.Label(s, text="", font=F(8), fg=T["muted"], bg=T["panel"], wraplength=300, justify="left", anchor="w")
            self.flag_sw[key], self.flag_hint[key] = sw_, hint

            def _shown(*a, k=key):
                if self.flags[k].get():
                    for other in self.style.toggle_conflict(k, True):
                        if other in self.flags and self.flags[other].get():
                            self.flags[other].set(False)
                if self.flags[k].get() and not getattr(self, "_restoring", False) and self.style.toggle_view(k) is not None:
                    self.amount.set(self.style.toggle_view(k) * 100.0)
                    wire = getattr(self, "wire", None)
                    if wire is not None:
                        wire.pitch = max(wire.pitch, 0.9)          # look down into the open box
                    self._on_amount()
            self.flags[key].trace_add("write", _shown)

        self._section(s, "LASER KERF  ·  blank = off")
        self._field(s, "kerf", "Kerf (beam width)")
        tk.Label(s, text="Cut lines move half the kerf away from the part so it finishes at true size. A faint "
                 "dashed outline shows the original size.", font=F(8), fg=T["dim"], bg=T["panel"], wraplength=300,
                 justify="left", anchor="w").pack(fill="x", padx=18, pady=(2, 0))

        self._section(s, "WINDOWS & ZONES")
        fb = tk.Frame(s, bg=T["panel"])
        fb.pack(fill="x", padx=18)
        for kind, lab in (("window", "+ Window"), ("info", "+ Info zone"), ("logo", "+ Logo zone")):
            Btn(fb, lab, lambda k=kind: self.add_feature(k), "ghost", size=9, padx=8, pady=5).pack(
                side="left", expand=True, fill="x", padx=(0, 4))
        self.flist = tk.Frame(s, bg=T["panel"])
        self.flist.pack(fill="x", padx=18, pady=(6, 0))
        self.fedit = tk.Frame(s, bg=T["panel"])
        self.fedit.pack(fill="x")
        self._rebuild_features_ui()

        self._section(s, "LINE COLOURS  ·  preview and export")
        self._color_row(s, "cut_color", "Cut lines")
        self._color_row(s, "fold_color", "Fold lines")
        self._color_row(s, "engrave_color", "Engrave (zones)")
        self._section(s, "LINE WEIGHTS  ·  export only")
        self._lfield(s, "cut_weight", "Cut weight", "pt")
        self._lfield(s, "fold_weight", "Fold weight", "pt")
        self._lfield(s, "engrave_weight", "Engrave weight", "pt")
        tk.Label(s, text=WEIGHT_NOTE, font=F(8), fg=T["dim"], bg=T["panel"], wraplength=300, justify="left",
                 anchor="w").pack(fill="x", padx=18, pady=(4, 0))

        if self.style.options:
            self._section(s, "ADVANCED  ·  blank = automatic")
            for key, label in self.style.options:
                self._field(s, key, label)

        if self.has_drawing:
            hd = tk.Frame(s, bg=T["panel"], cursor="hand2")
            hd.pack(fill="x", padx=18, pady=(16, 6))
            self.tol_hd = hd
            self.tol_arrow = tk.Label(hd, text="▸", font=F(8, "bold"), fg=T["dim"], bg=T["panel"], cursor="hand2")
            self.tol_arrow.pack(side="left")
            tl = tk.Label(hd, text=" DRAWING TOLERANCES  ·  advanced", font=F(8, "bold"), fg=T["dim"], bg=T["panel"],
                          anchor="w", cursor="hand2")
            tl.pack(side="left")
            for w_ in (hd, self.tol_arrow, tl):
                w_.bind("<Button-1>", lambda e: self.tol_open.set(not self.tol_open.get()))
            self.tol_body = tk.Frame(s, bg=T["panel"])
            tk.Label(self.tol_body, text="± mm, used on the exported drawing sheet. Blank = industry standard for "
                     "this board.", font=F(8), fg=T["dim"], bg=T["panel"], wraplength=300, justify="left",
                     anchor="w").pack(fill="x", padx=18, pady=(0, 4))
            for k, lab in TOL_LABELS.items():
                if k not in self.style.tol_keys:                          # e.g. no slots / glue flap on some styles
                    continue
                self._field(self.tol_body, "tol_" + k, lab.split(" (")[0] + "  ±")
            self.tol_open.trace_add("write", lambda *a: self._tol_toggle())

        self._section(s, "MATERIAL SHEET  ·  optional")
        self._field(s, "sheetw", "Sheet width")
        self._field(s, "sheeth", "Sheet height")

        tk.Frame(s, bg=T["panel"], height=16).pack()

    # ------------------------------------------------------ windows & zones ----
    def _fnum(self, k):
        try:
            return parse_num(self.fvars[k].get())
        except ValueError:
            return None

    def add_feature(self, kind):
        if not self.res or not self.res.panels:
            self.toast.config(text="Fix the dimensions first, then add a window or zone.", fg=T["err"])
            return
        rows = panel_centres(self.res.panels)[:3]
        mm = 25.4 if self.units.get() == "in" else 1.0
        r = 4.0 / mm if kind == "window" else 0.0
        spec = self.read_spec()
        pick = None
        # try spots on the biggest faces until one passes every structural check
        for scale in (1.0, 0.7, 0.5):
            for name, cx, cy, pw, ph, _a in rows:
                fw, fh = (0.5 * pw, 0.3 * ph) if kind == "window" else (0.4 * pw, 0.22 * ph)
                for oy in (0, 0.27, -0.27, 0.0, 0.0):
                    for ox in (0, 0.25, -0.25):
                        if oy == 0.0 and ox == 0 and pick is not None:
                            continue
                        c = Feature(kind, cx + ox * pw, cy + oy * ph, fw * scale, fh * scale, r)
                        spec.features = self.features + [c]
                        g = generate(self.style, spec)
                        if g.ok and not any("overlaps" in i.msg for i in g.warnings):
                            pick = c
                            break
                    if pick:
                        break
                if pick:
                    break
            if pick:
                break
        if pick is None:
            name, cx, cy, pw, ph, _a = rows[0]
            pick = Feature(kind, cx, cy, 0.3 * pw, 0.2 * ph, r)
            self.toast.config(text="No free spot found; drag the new item onto a clear area.", fg=T["warn"])
        self.features.append(pick)
        self.sel = len(self.features) - 1
        self._rebuild_features_ui()
        self.refresh()

    def select_feature(self, i):
        self.sel = i
        self._rebuild_features_ui()
        self.draw2d()

    def del_feature(self, i):
        del self.features[i]
        self.sel = None if not self.features else min(self.sel or 0, len(self.features) - 1)
        self._rebuild_features_ui()
        self.refresh()

    def _rebuild_features_ui(self):
        for w in self.flist.winfo_children() + self.fedit.winfo_children():
            w.destroy()
        for i, f in enumerate(self.features):
            row = tk.Frame(self.flist, bg=T["panel2"] if i == self.sel else T["panel"])
            row.pack(fill="x", pady=1)
            cnt = sum(1 for g in self.features[:i + 1] if g.kind == f.kind)
            lb = tk.Label(row, text=f"{f.label()} {cnt}", anchor="w", font=F(9), fg=T["text"], bg=row.cget("bg"),
                          cursor="hand2", padx=8)
            lb.pack(side="left", fill="x", expand=True, ipady=4)
            lb.bind("<Button-1>", lambda e, i=i: self.select_feature(i))
            x = tk.Label(row, text="✕", font=F(9), fg=T["muted"], bg=row.cget("bg"), cursor="hand2", padx=8)
            x.pack(side="right", ipady=4)
            x.bind("<Button-1>", lambda e, i=i: self.del_feature(i))
        if self.sel is None or self.sel >= len(self.features):
            if not self.features:
                tk.Label(self.flist, text="Add a window (cut hole) or an info / logo zone (engraved). Drag it on the "
                         "dieline to place it.", font=F(8), fg=T["dim"], bg=T["panel"], wraplength=300, justify="left",
                         anchor="w").pack(fill="x")
            return
        f = self.features[self.sel]
        self._floading = True
        for k in ("cx", "cy", "w", "h", "r"):
            self.fvars[k].set(fmt(getattr(f, k), 3))
        self.f_outline.set(f.outline)
        self.f_rot.set(f.rot == 90)
        self._floading = False
        e = self.fedit
        labels = [("cx", "Centre X"), ("cy", "Centre Y"), ("w", "Width"), ("h", "Height")]
        if f.kind == "window":
            labels.append(("r", "Corner radius"))
        for k, lab in labels:
            row = tk.Frame(e, bg=T["panel"])
            row.pack(fill="x", padx=18, pady=2)
            tk.Label(row, text=lab, font=F(9), fg=T["text"], bg=T["panel"]).pack(side="left")
            fe = tk.Entry(row, textvariable=self.fvars[k], width=8, font=F(10), bg=T["panel2"], fg=T["text"],
                          insertbackground=T["text"], relief="flat", justify="right", highlightthickness=1,
                          highlightbackground=T["border"], highlightcolor=T["accent"])
            fe.pack(side="right", ipady=3)
            self._calc_bind(fe, self.fvars[k], lambda: self.units.get(), cur_fn=(lambda k=k: self._fplain.get(k)))
        if f.kind != "window":
            Switch(e, "Draw border", self.f_outline).pack(anchor="w", padx=18, pady=3)
            b = tk.Frame(e, bg=T["panel"])
            b.pack(fill="x", padx=18, pady=(2, 0))
            Btn(b, "Import SVG…", self.import_art, "ghost", size=9, padx=10, pady=4).pack(side="left")
            if f.art is not None:
                Btn(b, "Remove", self.remove_art, "ghost", size=9, padx=10, pady=4).pack(side="left", padx=(6, 0))
                Switch(e, "Turn artwork 90°", self.f_rot).pack(anchor="w", padx=18, pady=3)
                tk.Label(e, text=f"{f.art.name or 'artwork'}  ·  {f.art.w:.1f} × {f.art.h:.1f} mm, "
                         f"{f.art.segs()} segments", font=F(8), fg=T["dim"], bg=T["panel"], wraplength=300,
                         justify="left", anchor="w").pack(fill="x", padx=18, pady=(2, 0))
                if f.art.skipped:
                    tk.Label(e, text="Ignored: " + ", ".join(f.art.skipped) + " (convert to outlines first).",
                             font=F(8), fg=T["warn"], bg=T["panel"], wraplength=300, justify="left",
                             anchor="w").pack(fill="x", padx=18)
            tk.Label(e, text="Engraved with fine lines, the art is scaled to fit and centred in the zone. Filled "
                     "shapes are engraved as outlines.", font=F(8), fg=T["dim"], bg=T["panel"], wraplength=300,
                     justify="left", anchor="w").pack(fill="x", padx=18, pady=(4, 0))

    def _fvar_changed(self):
        if self._floading or self.sel is None or self.sel >= len(self.features):
            return
        f = self.features[self.sel]
        for k in ("cx", "cy", "w", "h", "r"):
            v = self._fnum(k)
            setattr(f, k, float("nan") if v is None else v)
        f.outline, f.rot = self.f_outline.get(), 90 if self.f_rot.get() else 0
        self.schedule()

    def import_art(self):
        if self.sel is None:
            return
        path = filedialog.askopenfilename(title="Import SVG artwork", filetypes=[("SVG artwork", "*.svg")])
        if not path:
            return
        try:
            art = import_svg(path)
        except (ValueError, OSError) as exc:
            self.toast.config(text=f"Could not import: {exc}", fg=T["err"])
            return
        self.features[self.sel].art = art
        self.toast.config(text=f"Imported {art.name}.", fg=T["good"])
        self._rebuild_features_ui()
        self.refresh()

    def remove_art(self):
        if self.sel is not None:
            self.features[self.sel].art = None
            self._rebuild_features_ui()
            self.refresh()

    def _to_draw(self, ex, ey):
        v = self.view
        return (ex - v["ox"]) / v["s"], (v["oy"] - ey) / v["s"]

    def _feat_at(self, ex, ey):
        x, y = self._to_draw(ex, ey)
        order = ([self.sel] if self.sel is not None else []) + list(range(len(self.features) - 1, -1, -1))
        for i in order:
            if i < len(self.features):
                f = self.features[i]
                if abs(x - f.cx) <= f.w / 2 and abs(y - f.cy) <= f.h / 2:
                    return i, x - f.cx, y - f.cy
        return None

    def _build_main(self, parent):
        main = tk.Frame(parent, bg=T["bg"])
        parent.add(main, minsize=S(460), stretch="always")
        self.stage = make_paned(main, "horizontal")                # dieline | 3-D preview, divider draggable
        self.stage.pack(fill="both", expand=True)

        self.pane2 = tk.Frame(self.stage, bg=T["canvas"])
        self.cv2 = tk.Canvas(self.pane2, bg=T["canvas"], highlightthickness=0, cursor="fleur")
        self.cv2.pack(fill="both", expand=True)
        self.cv2.bind("<Configure>", lambda e: self.draw2d())
        self.cv2.bind("<ButtonPress-1>", self._p2_down)
        self.cv2.bind("<B1-Motion>", self._p2_move)
        self.cv2.bind("<ButtonRelease-1>", self._p2_up)
        self.cv2.bind("<MouseWheel>", self._p2_wheel)
        self.cv2.bind("<Button-4>", lambda e: self._p2_zoom(e, 1.12))
        self.cv2.bind("<Button-5>", lambda e: self._p2_zoom(e, 1 / 1.12))
        self.cv2.bind("<Double-Button-1>", lambda e: self._fit())
        self.show_labels, self.show_dims = tk.BooleanVar(value=True), tk.BooleanVar(value=True)
        self._dims, self._dim_entry = [], None
        self._tog = []
        for txt, var in (("Panel labels", self.show_labels), ("Dimensions", self.show_dims)):
            self._tog.append(tk.Checkbutton(self.cv2, text=txt, variable=var, command=self.draw2d, font=F(8), bd=0,
                                            fg=T["muted"], bg=T["canvas"], activebackground=T["canvas"],
                                            activeforeground=T["text"], selectcolor=T["panel2"], highlightthickness=0,
                                            cursor="hand2"))
        self.cv2.tag_bind("dimedit", "<Enter>", lambda e: self.cv2.config(cursor="hand2"))
        self.cv2.tag_bind("dimedit", "<Leave>", lambda e: self.cv2.config(cursor="fleur"))

        self.pane3 = tk.Frame(self.stage, bg=T["thumb"])
        self.cv3 = tk.Canvas(self.pane3, bg=T["thumb"], highlightthickness=0, cursor="exchange")
        self.cv3.pack(fill="both", expand=True)
        self.wire = Wire3D(self.cv3, self.style.view_up, lw=1.6)
        self.wire.fixed_frame = True               # no re-centring or zoom pumping while the box folds
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
        self.solid_on = self.has_solid                        # opens in the solid (thickness) view
        if self.has_solid:                                    # solid board-thickness view
            self.btn_solid = Btn(bar, "▢ Wire" if self.solid_on else "◼ Solid", self.toggle_solid, "ghost", size=9,
                                 padx=10, pady=5)
            self.btn_solid.pack(side="right", padx=(0, 0), pady=8)
        sc = Slider(bar, self.amount, self._on_amount)
        sc.pack(side="left", fill="x", expand=True, pady=10, padx=(0, 10))

        self.status = tk.Label(main, text="", font=F(9), fg=T["muted"], bg=T["panel"], anchor="w", padx=16, pady=7)
        self.status.pack(fill="x", side="bottom")

    def _layout_views(self):
        m = self.view_mode.get()
        for p_ in (self.pane2, self.pane3):
            try:
                self.stage.forget(p_)
            except tk.TclError:
                pass
        for p_ in {"dieline": (self.pane2,), "fold3d": (self.pane3,)}.get(m, (self.pane2, self.pane3)):
            self.stage.add(p_, minsize=S(230), stretch="always")
        self.after(30, lambda: (self._apply_split(), self.draw2d(), self._render3d()))

    # ------------------------------------------------------------ dividers ----
    def _both_views(self):
        return len(self.stage.panes()) == 2

    def _apply_split(self):
        """Keep the dieline / 3-D divider at the remembered fraction when the window or the sidebar changes size."""
        if self._sash_drag or not self._both_views():
            return
        w = self.stage.winfo_width()
        if w > 100:
            try:
                self.stage.sash_place(0, int(w * self.app.layout["split"]), 0)
            except tk.TclError:
                pass

    def _init_sashes(self, tries=0):
        """Put every divider at its remembered place (the sidebar's checks + export area at its natural height
        the first time)."""
        lay = self.app.layout
        if self.vp.winfo_height() < 60 and tries < 30:
            self.after(40, lambda: self._init_sashes(tries + 1))
            return
        try:
            self.update_idletasks()
            self.body.sash_place(0, lay["side_w"], 0)
            nat = self.lower_sf.inner.winfo_reqheight()       # the checks + export stack at its natural height,
            low = lay["lower_h"] if lay["lower_h"] else min(nat, max(S(160), int(self.vp.winfo_height() * 0.42)))   # but never more than ~40 % of a short window
            self.vp.sash_place(0, 0, self.vp.winfo_height() - low - S(7))
        except tk.TclError:
            pass
        self._apply_split()
        self._fit_wraps()

    def _sash_press(self, e):
        w_ = e.widget
        try:
            self._sash_drag = bool(w_.identify(e.x, e.y))
        except (tk.TclError, AttributeError):
            self._sash_drag = False

    def _sash_release(self, e):
        if not self._sash_drag:
            return
        self._sash_drag = False
        lay = self.app.layout
        try:
            lay["side_w"] = self.body.sash_coord(0)[0]
            lay["lower_h"] = max(S(92), self.vp.winfo_height() - self.vp.sash_coord(0)[1] - S(7))
            if self._both_views() and self.stage.winfo_width() > 100:
                lay["split"] = min(0.8, max(0.2, self.stage.sash_coord(0)[0] / self.stage.winfo_width()))
        except tk.TclError:
            pass
        self._fit_wraps()

    def _fit_wraps(self):
        """Wrapped helper texts in the sidebar follow its width."""
        w = self.side.winfo_width()
        if w < 100:
            return

        def walk(wd):
            for c in wd.winfo_children():
                if isinstance(c, tk.Label):
                    try:
                        wl = int(float(c.cget("wraplength")))
                    except (tk.TclError, ValueError):
                        wl = 0
                    if wl:
                        base = getattr(c, "_wl0", None)
                        if base is None:
                            base = c._wl0 = wl
                        new = max(S(120), base + (w - S(352)))
                        if new != wl:
                            c.configure(wraplength=new)
                walk(c)
        walk(self.side)

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
        f = f_ = 1 / 25.4 if new == "in" else 25.4
        self._loading = True
        exact = getattr(self, "_mm_exact", None)
        if exact is None:
            exact = self._mm_exact = {}
        for k, v in self.vars.items():
            if k.startswith("tol_") or k in self.style.count_keys:     # tolerances are always mm; counts have no unit
                continue
            try:
                x = parse_num(v.get())
            except ValueError:
                continue
            if x is not None:
                txt = v.get()
                kept = exact.get(k)
                mm = kept[1] if kept and kept[0] == txt else x * (25.4 if old == "in" else 1.0)   # unchanged since the last
                new_txt = fmt(mm * (1 / 25.4 if new == "in" else 1.0), 4 if new == "in" else 3)        # switch: use the exact
                v.set(new_txt)                                                                           # value, not the text
                exact[k] = (new_txt, mm)
        for f in self.features:
            for k in ("cx", "cy", "w", "h", "r"):
                setattr(f, k, getattr(f, k) * f_)
        self._loading = False
        self._last_units = new
        self.user_view = False
        self._rebuild_features_ui()
        self.refresh()

    def _show_dash(self):
        if self.perf.get():
            self.dash_box.pack(fill="x", padx=18, pady=(0, 4), after=self._sw_perf)
            if getattr(self, "side_sf", None) is not None:
                self.after_idle(lambda: self.side_sf.reveal(self.dash_box))
        else:
            self.dash_box.pack_forget()
        for k in self.dvars:
            self._dash_changed(k, schedule=False)

    def _dash_changed(self, k, schedule=True):
        try:
            v = self.dvars[k].get()
        except tk.TclError:
            return
        self.app.dash[k] = v
        if k in self.dash_val:
            self.dash_val[k].config(text=f"{v:g} mm" if k.startswith("perf") else f"{v:.2f} x board")
        if k.startswith("bend") and schedule and getattr(self, "has_drawing", False) and not self._loading:
            self._sync_solid()
            self.wire.render()

    def snapshot(self):
        d = {k: v.get() for k, v in self.vars.items()}
        d.update(units=self.units.get(), mode=self.mode.get(), folds=self.folds.get(), perf=self.perf.get(),
                 flute=self.flute.get(), view=self.view_mode.get())
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
        flags = {}
        for k, v in self.flags.items():                       # an option the typed sizes cannot use is left out, with a reason
            why = self.style.toggle_hint(k, vals)
            flags[k] = bool(v.get()) and not why
            sw_, hint = self.flag_sw.get(k), self.flag_hint.get(k)
            if sw_ is not None:
                sw_.set_enabled(not why)
                if why:
                    hint.config(text=why)
                    hint.pack(fill="x", padx=18, after=sw_)
                else:
                    hint.pack_forget()
        spec = Spec(vals["L"], vals["W"], vals["H"], vals["t"], self.mode.get(), self.units.get(), opts,
                    self.folds.get(), flags, tuple(sh))
        spec.perf = self.perf.get()
        spec.flute = {"v": "v", "h": "h"}.get(self.flute.get())
        spec.perf_dash, spec.perf_tie = self.dvars["perf_dash"].get(), self.dvars["perf_tie"].get()
        spec.bend_r = max(0.0, self.dvars["bend_r"].get()) * spec.t if spec.t and math.isfinite(spec.t) else None
        spec.features = self.features
        if self.has_drawing:
            spec.tol = {}
            for k in TOL_LABELS:
                try:
                    tv = parse_num(self.vars["tol_" + k].get())
                except ValueError:
                    tv = float("nan")
                if tv is not None:
                    spec.tol[k] = tv
        try:
            kv = parse_num(self.vars["kerf"].get())
        except ValueError:
            kv = float("nan")
        spec.kerf = 0.0 if kv is None else kv
        look = dict(cut_color=self.lvars["cut_color"].get(), fold_color=self.lvars["fold_color"].get(),
                    engrave_color=self.lvars["engrave_color"].get())
        for k in ("cut_weight", "fold_weight", "engrave_weight"):
            try:
                v = parse_num(self.lvars[k].get())
            except ValueError:
                v = None
            look[k] = float("nan") if v is None else v
        spec.look = look
        for k, v in look.items():                       # remembered for the other boxes in this session only
            if not (isinstance(v, float) and not math.isfinite(v)):
                self.app.look[k] = v
        return spec

    # -------------------------------------------------------------- refresh ----
    # ----------------------------------------------------- undo / redo ----
    def _state(self):
        feats = [(f.kind, f.cx, f.cy, f.w, f.h, f.r, f.art, f.outline, f.rot) for f in self.features]
        return dict(vars={k: v.get() for k, v in self.vars.items()}, units=self.units.get(), mode=self.mode.get(),
                    folds=self.folds.get(), perf=self.perf.get(), flute=self.flute.get(),
                    flags={k: v.get() for k, v in self.flags.items()},
                    look={k: v.get() for k, v in self.lvars.items()},
                    dash={k: v.get() for k, v in self.dvars.items()}, feats=feats, sel=self.sel)

    def _track(self):
        """Remember the state before each burst of edits (typing, dragging a slider or a window = one step)."""
        if self._restoring:
            return
        import time
        cur = self._state()
        if self._base is None:
            self._base = cur
            return
        if cur == self._base:
            return
        now = time.monotonic()
        if now - self._last_change > 0.8:
            self._undo.append(self._base)
            del self._undo[:-100]
            self._redo.clear()
        self._last_change = now
        self._base = cur

    def _apply_state(self, st):
        self._restoring = self._loading = True
        try:
            for k, v in st["vars"].items():
                if k in self.vars:
                    self.vars[k].set(v)
            self.units.set(st["units"])
            self._last_units = st["units"]
            self.mode.set(st["mode"])
            self.folds.set(st["folds"])
            self.perf.set(st["perf"])
            self.flute.set(st.get("flute", "off"))
            for k, v in st["flags"].items():
                if k in self.flags:
                    self.flags[k].set(v)
            for k, v in st["look"].items():
                self.lvars[k].set(v)
            for k, v in st["dash"].items():
                self.dvars[k].set(v)
            self.features = [Feature(kd, cx, cy, w, h, r, art, ol, rot) for kd, cx, cy, w, h, r, art, ol, rot in st["feats"]]
            self.sel = st["sel"] if st["sel"] is not None and st["sel"] < len(self.features) else None
        finally:
            self._loading = False
        self._rebuild_features_ui()
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        self.refresh()
        self._restoring = False
        self._base = self._state()
        self._last_change = 0.0

    def _flush_pending(self):
        if self._job:                                       # an edit still waiting for its redraw: record it first
            self.after_cancel(self._job)
            self.refresh()

    def undo(self, e=None):
        self._flush_pending()
        if not self._undo:
            self.toast.config(text="Nothing to undo.", fg=T["muted"])
            return "break"
        self._redo.append(self._state())
        self._apply_state(self._undo.pop())
        self.toast.config(text=f"Undo  ({len(self._undo)} more)", fg=T["muted"])
        return "break"

    def redo(self, e=None):
        self._flush_pending()
        if not self._redo:
            self.toast.config(text="Nothing to redo.", fg=T["muted"])
            return "break"
        self._undo.append(self._state())
        self._apply_state(self._redo.pop())
        self.toast.config(text=f"Redo  ({len(self._redo)} more)", fg=T["muted"])
        return "break"

    def refresh(self):
        self._job = None
        self._track()
        if self.project_path:
            self.app._set_title()                             # shows a * while there are unsaved changes
        self.mode_lbl.config(text=self.style.mode_help.get(self.mode.get(), ""))
        spec = self.read_spec()
        res = generate(self.style, spec)
        self.res = res
        self._show_issues(res)
        self._show_autos(res)
        ok = res.ok
        for b in self.export_btns:
            b.set_enabled(ok)
        if res.panels:
            self._sync_solid(spec)
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
        self.after_idle(self._fit_wraps)

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

    def _tol_toggle(self):
        if self.tol_open.get():
            self.tol_body.pack(fill="x", after=self.tol_hd)
        else:
            self.tol_body.pack_forget()
        self.tol_arrow.config(text="▾" if self.tol_open.get() else "▸")

    def _show_autos(self, res):
        tol = res.info.get("tol")
        if self.has_drawing and tol:
            for k in TOL_LABELS:
                lbl = self.auto_lbl.get("tol_" + k)
                if lbl is not None:
                    lbl.config(text=f"auto {fmt(tol['values'][k], 2)}" if not self.vars["tol_" + k].get().strip() else "")
            if any(i.fields and i.fields[0].startswith("tol_") for i in res.issues if i.level != "info") \
                    and not self.tol_open.get():
                self.tol_open.set(True)
        auto = res.info.get("auto", {})
        flags = {k: v.get() for k, v in self.flags.items()}
        for key, _ in self.style.options:
            on = self.style.option_enabled(key, flags)                   # an option for a switch that is off is greyed out
            self.ents[key].config(state="normal" if on else "disabled", disabledbackground=T["panel"],
                                  disabledforeground=T["dim"])
            lbl = self.auto_lbl[key]
            val = auto.get(self._auto_key(key))
            if val is None and key in self.style.count_keys and isinstance(auto.get("ins"), dict):
                val = auto["ins"].get(key[1:])                           # the Slotted Box's divider counts: gnl -> nl
            if val is not None and not self.vars[key].get().strip():
                lbl.config(text=f"auto {fmt(val, 2)}")
            else:
                lbl.config(text="")

    def _auto_key(self, key):
        return {"lidh": "lidh", "clr": "clr"}.get(key, key)

    # ----------------------------------------------------------------- 2-D ----
    def _bounds(self):
        d = self.res.drawing
        return d.bounds() if d else None

    def _fit(self):
        self.user_view = False
        self.draw2d()

    def _p2_down(self, e):
        self._fdrag = None
        if self._dim_entry is not None:
            return
        for it in reversed(self.cv2.find_overlapping(e.x - 4, e.y - 4, e.x + 4, e.y + 4)):
            tg = [t for t in self.cv2.gettags(it) if t.startswith("dimi")]
            if tg and "dimedit" in self.cv2.gettags(it):
                self._drag = None
                self._dim_edit(int(tg[0][4:]))
                return
        hit = self._feat_at(e.x, e.y) if self.res is not None and self.res.drawing is not None else None
        if hit:
            i, dx, dy = hit
            if i != self.sel:
                self.select_feature(i)
            self._fdrag = (i, dx, dy)
            self._drag = None
            return
        self._drag = (e.x, e.y)

    def _p2_up(self, e):
        self._fdrag = None

    def _p2_move(self, e):
        if self._fdrag:
            i, dx, dy = self._fdrag
            x, y = self._to_draw(e.x, e.y)
            f = self.features[i]
            f.cx, f.cy = x - dx, y - dy
            self._floading = True
            self.fvars["cx"].set(fmt(f.cx, 3))
            self.fvars["cy"].set(fmt(f.cy, 3))
            self._floading = False
            self.schedule()
            return
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
        if self._dim_entry is not None:                       # a redraw while a dimension is being typed: drop the box
            try:
                self._dim_entry.destroy()
            except tk.TclError:
                pass
            self._dim_entry = None
        cv.delete("all")
        self._dims = []
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
            pad = S(112) if self.show_dims.get() else 64
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
        try:
            lk = resolve_look({k: v for k, v in self.app.look.items()})
        except (ValueError, TypeError):
            lk = resolve_look()
        cut_c, fold_c = view_color(lk["cut_hex"]), view_color(lk["fold_hex"])
        col = {CUT: cut_c, FOLD: fold_c, ENGRAVE: view_color(lk["engrave_hex"])}
        bad = not self.res.ok
        nom = self.res.nominal
        if nom is not None and self.res.info.get("kerf"):
            ghost = mix(T["dim"], T["canvas"], 0.2)
            for it in nom.items:
                if it[0] == "L":
                    _, p, q, _l = it
                    cv.create_line(X(p[0]), Y(p[1]), X(q[0]), Y(q[1]), fill=ghost, width=1, dash=(2, 3))
                else:
                    _, ce, r, a0, a1, _l = it
                    cv.create_arc(X(ce[0] - r), Y(ce[1] + r), X(ce[0] + r), Y(ce[1] - r), start=a0,
                                  extent=(a1 - a0) % 360 or 360, style="arc", outline=ghost, width=1, dash=(2, 3))
        for it in d.items:
            c = col[it[-1]]
            if bad:
                c = mix(c, T["canvas"], 0.55)
            lw = 1.6 if it[-1] == CUT else 1.3 if it[-1] == FOLD else 1.0
            if it[0] == "L":
                _, p, q, layer = it
                cv.create_line(X(p[0]), Y(p[1]), X(q[0]), Y(q[1]), fill=c, width=lw, capstyle="round")
            else:
                _, ce, r, a0, a1, layer = it
                span = (a1 - a0) % 360 or 360
                cv.create_arc(X(ce[0] - r), Y(ce[1] + r), X(ce[0] + r), Y(ce[1] - r), start=a0, extent=span,
                              style="arc", outline=c, width=lw)
        if self.sel is not None and self.sel < len(self.features):
            f = self.features[self.sel]
            if all(math.isfinite(q) for q in (f.cx, f.cy, f.w, f.h)):
                cv.create_rectangle(X(f.cx - f.w / 2), Y(f.cy + f.h / 2), X(f.cx + f.w / 2), Y(f.cy - f.h / 2),
                                    outline=T["accent"], dash=(4, 3), width=1)
        if self.show_labels.get():
            self._draw_labels(cv, X, Y, s)
        drew = self.show_dims.get() and self._draw_dims(cv, X, Y, u)
        # overall size callouts (the dimension callouts above already carry them)
        ax = T["dim"]
        if not drew:
            by = Y(y0) + S(22)
            cv.create_line(X(x0), by, X(x1), by, fill=ax, arrow="both")
            cv.create_text((X(x0) + X(x1)) / 2, by + S(12), text=f"{fmt(x1 - x0, 1)} {u}", fill=T["muted"], font=F(8))
            rx = X(x1) + S(22)
            cv.create_line(rx, Y(y0), rx, Y(y1), fill=ax, arrow="both")
            cv.create_text(rx + S(14), (Y(y0) + Y(y1)) / 2, text=f"{fmt(y1 - y0, 1)} {u}", fill=T["muted"], font=F(8),
                           angle=90)
        for i, tw in enumerate(self._tog):
            cv.create_window(S(12) + i * S(104), S(8), window=tw, anchor="nw")
        # legend
        lx, ly = S(18), H - S(20)
        cv.create_line(lx, ly, lx + S(22), ly, fill=cut_c, width=2)
        cv.create_text(lx + S(30), ly, text="Cut", fill=T["muted"], font=F(8), anchor="w")
        cv.create_line(lx + S(70), ly, lx + S(92), ly, fill=fold_c, width=2)
        cv.create_text(lx + S(100), ly, text="Fold / score", fill=T["muted"], font=F(8), anchor="w")
        if self.res.info.get("kerf"):
            cv.create_line(lx + S(300), ly, lx + S(322), ly, fill=T["dim"], dash=(2, 3))
            cv.create_text(lx + S(330), ly, text="Original size", fill=T["muted"], font=F(8), anchor="w")
        if any(it[-1] == ENGRAVE for it in d.items):
            cv.create_line(lx + S(190), ly, lx + S(212), ly, fill=col[ENGRAVE], width=2)
            cv.create_text(lx + S(220), ly, text="Engrave", fill=T["muted"], font=F(8), anchor="w")
        cv.create_text(W - S(14), H - S(20), text=("drag = pan · wheel = zoom · drag a window / zone to move it" if W > S(820) else ""), fill=T["dim"], font=F(8),
                       anchor="e")
        self._banner(cv, W)

    def _draw_labels(self, cv, X, Y, s):
        """Each panel's name and its crease-to-crease size, in the middle of the panel (left out when it would not fit)."""
        u = self.units.get()
        for p in self.res.panels or []:
            xs, ys = [q[0] for q in p.poly], [q[1] for q in p.poly]
            bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
            pw, ph = (bx1 - bx0) * s, (by1 - by0) * s
            name = self.style.panel_label(p.name)
            size = f"{fmt(bx1 - bx0, 1)} × {fmt(by1 - by0, 1)}"
            cx, cy = (X(bx0) + X(bx1)) / 2, (Y(by0) + Y(by1)) / 2
            if pw >= S(14) + 5.2 * len(name) and ph >= S(34):
                cv.create_text(cx, cy - S(6), text=name, fill=T["muted"], font=F(7, "bold"))
                if pw >= S(14) + 5.2 * len(size):
                    cv.create_text(cx, cy + S(6), text=size, fill=T["dim"], font=F(7))
            elif pw >= S(14) + 5.2 * len(name) and ph >= S(16):
                cv.create_text(cx, cy, text=name, fill=T["muted"], font=F(7, "bold"))
            elif ph >= S(14) + 5.2 * len(name) and pw >= S(16):      # tall and thin: read it sideways
                cv.create_text(cx, cy, text=name, fill=T["muted"], font=F(7, "bold"), angle=90)

    def _draw_dims(self, cv, X, Y, u):
        """Dimension callouts of the flat blank (the same ones as on the drawing sheet). A callout that is one sidebar box
        (a panel width, the flap, the glue flap ...) is drawn in the accent colour and can be clicked to change it."""
        res = self.res
        try:
            dims = self.style.dimensions(res, res.spec)
        except Exception:                                  # noqa: BLE001  (a blank that failed its checks has no callouts)
            return False
        if not dims:
            return False
        ax = T["dim"]
        row1, row2, gap, over = S(30), S(52), S(3), S(4)
        crowd = 0
        self._dims = []
        for dm in dims:
            try:
                fld = self.style.dim_field(dm, res, res.spec)
            except Exception:                              # noqa: BLE001
                fld = None
            label = _fnum(dm["v"], u) + (f" {dm['note']}" if dm.get("note") else "")
            col = T["accent"] if fld else T["muted"]
            tag = (f"dimi{len(self._dims)}", "dimedit") if fld else ()
            font = F(8, "bold") if fld else F(8)
            off = row1 if abs(dm["row"]) == 1 else row2
            if dm["kind"] == "h":
                a, b = X(dm["a"]), X(dm["b"])
                yo = Y(dm["ref"])
                yb0 = Y(dm.get("yref", dm["ref"]))
                sg = 1 if dm["row"] > 0 else -1
                yl = yb0 - sg * off
                for xx in (a, b):
                    cv.create_line(xx, yo - sg * gap, xx, yl - sg * over, fill=ax)
                lo, hi = min(a, b), max(a, b)
                cv.create_line(lo, yl, hi, yl, fill=ax, arrow="both", arrowshape=(S(7), S(8), S(3)))
                tx, ty = (lo + hi) / 2, yl - sg * S(10)
                if len(label) * S(6) > hi - lo - S(8):      # a span narrower than its text: neighbours alternate in height
                    ty -= sg * S(12) * (crowd % 2)
                    crowd += 1
                anchor, ang = "center", 0
            else:
                a, b = Y(dm["a"]), Y(dm["b"])
                xo = X(dm["ref"])
                xl = X(dm.get("xref", dm["ref"])) + off
                for yy in (a, b):
                    cv.create_line(xo + gap, yy, xl + over, yy, fill=ax)
                lo, hi = min(a, b), max(a, b)
                cv.create_line(xl, lo, xl, hi, fill=ax, arrow="both", arrowshape=(S(7), S(8), S(3)))
                tx, ty = xl + S(10), (lo + hi) / 2
                anchor, ang = "center", 90
            it = cv.create_text(tx, ty, text=label, fill=col, font=font, angle=ang, anchor=anchor, tags=tag)
            if fld:
                self._dims.append((dm, fld, tx, ty, ang))
        return True

    def _dim_edit(self, i):
        """Type a new value for callout `i`: a box opens on it, and Enter changes the matching sidebar box by the same
        amount (so a panel width in Inner mode still means the inside size), exactly as if it had been typed there."""
        dm, fld, tx, ty, ang = self._dims[i]
        key, now = fld[0], fld[1]
        scale = fld[2] if len(fld) > 2 else 1.0           # how far the box moves for one unit of the dimension
        u = self.units.get()
        var = self.vars[key]
        ent = tk.Entry(self.cv2, width=9, font=F(10), bg=T["panel2"], fg=T["text"], insertbackground=T["text"],
                       relief="flat", justify="center", highlightthickness=1, highlightbackground=T["accent"],
                       highlightcolor=T["accent"])
        ent.insert(0, fmt(dm["v"], 4 if u == "in" else 3))
        self._dim_entry = ent
        self.cv2.create_window(tx, ty, window=ent, anchor="center")

        def close(*_):
            if self._dim_entry is ent:
                self._dim_entry = None
            try:
                ent.destroy()
            except tk.TclError:
                pass

        def commit(*_):
            raw = ent.get()
            try:
                typed = parse_num(raw) if is_plain_number(raw) else calc_eval(raw, dm["v"], u)
                base = parse_num(var.get()) if now is None else now
                if base is None:
                    raise ValueError("that box is empty")
            except ValueError as exc:
                self.toast.config(text=f"Can't use that: {exc}.", fg=T["err"])
                return
            new = base + (typed - dm["v"]) * scale
            close()
            var.set(fmt(new, 4 if u == "in" else 3))
            self.toast.config(text=f"{dict(self._box_labels()).get(key, key)} set to {var.get()}", fg=T["muted"])
            self.schedule()

        ent.bind("<Return>", commit)
        ent.bind("<KP_Enter>", commit)
        ent.bind("<Escape>", close)
        ent.bind("<FocusOut>", close)
        ent.focus_set()
        ent.select_range(0, "end")

    def _box_labels(self):
        """[(key, label)] of the sidebar boxes, for messages."""
        return [("L", "Length"), ("W", "Width"), ("H", self.style.height_label), ("t", "Thickness")] + list(self.style.options)

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
        self._anim_t = time.perf_counter()
        self._step()

    def _step(self):
        now = time.perf_counter()                          # time-based: the fold takes the same ~1.7 s however long a frame takes
        dt = min(0.1, now - getattr(self, "_anim_t", now))
        self._anim_t = now
        v = self.amount.get() + (dt * 58.0 if dt > 0 else 1.4)
        if v >= 100:
            self.amount.set(100)
            self._on_amount()
            self._anim = None
            self.btn_play.config(text="▶  Fold")
            return
        self.amount.set(v)
        self._on_amount()
        self._anim = self.after(max(1, 16 - int((time.perf_counter() - now) * 1000)), self._step)

    def _sync_solid(self, spec=None):
        spec = spec or self.read_spec()
        t = spec.t if (spec.t and math.isfinite(spec.t)) else 0.0
        self.wire.solid = bool(self.solid_on and self.has_solid and t > 0)
        self.wire.seq = bool(self.has_solid and t > 0)
        self.wire.style_id = self.style.id
        self.wire.thick = t
        try:
            on = bool(self.dvars["bend_on"].get())
            self.wire.bend = self.dvars["bend_r"].get() * t if (on and t > 0 and self.style.rounded_folds) else None
            self.wire.bend_len = bool(self.dvars["bend_len"].get())
            self.wire.edges = bool(self.dvars["bend_edges"].get())
            self.wire.flute = getattr(spec, "flute", None)
        except (tk.TclError, KeyError):
            self.wire.bend = None

    def toggle_solid(self):
        self.solid_on = not self.solid_on
        self.btn_solid.config(text="◼ Solid" if not self.solid_on else "▢ Wire")
        self._sync_solid()
        self.wire.render()

    def toggle_spin(self):
        if self._spin:
            self.after_cancel(self._spin)
            self._spin = None
            self.btn_spin.config(text="⟳ Spin")
            return
        self.btn_spin.config(text="■ Stop")
        self._spin_t = time.perf_counter()
        self._spin_step()

    def _spin_step(self):
        now = time.perf_counter()                          # time-based, so the turn rate does not depend on frame time
        dt = min(0.1, now - getattr(self, "_spin_t", now))
        self._spin_t = now
        self.wire.yaw += 0.55 * dt if dt > 0 else 0.018
        self.wire.render()
        self._spin = self.after(max(1, 16 - int((time.perf_counter() - now) * 1000)), self._spin_step)

    def shutdown(self):
        for j in (self._job, self._anim, self._spin):
            if j:
                try:
                    self.after_cancel(j)
                except Exception:
                    pass

    # --------------------------------------------------------------- export ----
    def _gcode_dialog(self):
        win = tk.Toplevel(self, bg=T["panel"])
        win.title("G-code settings")
        win.transient(self.winfo_toplevel())
        win.resizable(False, False)
        tk.Label(win, text="GRBL-style laser job: M4 dynamic power, origin = bottom-left of the sheet.\n"
                           "Engraving runs first, then scores, then cuts. Test on scrap and lower the power if unsure.",
                 font=F(9), fg=T["muted"], bg=T["panel"], justify="left").grid(row=0, column=0, columnspan=2,
                                                                              padx=18, pady=(16, 8), sticky="w")
        rows = [("cut_power", "Cut power (S, 0-1000)"), ("cut_feed", "Cut speed (mm/min)"),
                ("cut_passes", "Cut passes"), ("fold_power", "Score power (S, 0-1000)"),
                ("fold_feed", "Score speed (mm/min)"), ("fold_passes", "Score passes"),
                ("engrave_power", "Engrave power (S, 0-1000)"), ("engrave_feed", "Engrave speed (mm/min)"),
                ("engrave_passes", "Engrave passes")]
        vs = {}
        for i, (k, lab) in enumerate(rows, 1):
            tk.Label(win, text=lab, font=F(9), fg=T["text"], bg=T["panel"]).grid(row=i, column=0, padx=(18, 10),
                                                                                  pady=3, sticky="w")
            vs[k] = tk.StringVar(value=fmt(self.app.gcode[k], 2))
            tk.Entry(win, textvariable=vs[k], width=9, font=F(10), bg=T["panel2"], fg=T["text"],
                     insertbackground=T["text"], relief="flat", justify="right").grid(row=i, column=1, padx=(0, 18),
                                                                                       pady=3, ipady=3)
        err = tk.Label(win, text="", font=F(8), fg=T["err"], bg=T["panel"])
        err.grid(row=11, column=0, columnspan=2, padx=18, sticky="w")
        out = {}

        def ok():
            try:
                v = {k: float(x.get().replace(",", ".")) for k, x in vs.items()}
            except ValueError:
                err.config(text="Enter numbers only.")
                return
            if not all(0 <= v[k] <= 1000 for k in ("cut_power", "fold_power", "engrave_power")):
                err.config(text="Power must be between 0 and 1000.")
                return
            if v["cut_feed"] <= 0 or v["fold_feed"] <= 0 or v["engrave_feed"] <= 0 \
                    or v["cut_passes"] < 1 or v["fold_passes"] < 1 or v["engrave_passes"] < 1:
                err.config(text="Speeds must be > 0 and passes >= 1.")
                return
            for k in ("cut_passes", "fold_passes", "engrave_passes"):
                v[k] = int(v[k])
            out.update(v)
            win.destroy()

        bar = tk.Frame(win, bg=T["panel"])
        bar.grid(row=12, column=0, columnspan=2, pady=(8, 16), padx=18, sticky="e")
        Btn(bar, "Cancel", win.destroy, "ghost", pady=6).pack(side="left", padx=(0, 8))
        Btn(bar, "Save G-code…", ok, "primary", pady=6).pack(side="left")
        win.update_idletasks()
        try:
            win.grab_set()
        except tk.TclError:
            pass
        self.wait_window(win)
        if out:
            self.app.gcode.update(out)
        return out or None

    def _drawing_dialog(self):
        o = self.app.drawing_opts
        win = tk.Toplevel(self, bg=T["panel"])
        win.title("Export drawing")
        win.transient(self.winfo_toplevel())
        win.resizable(False, False)
        tk.Label(win, text="Dimensioned dieline sheet (PDF). Choose what goes on it.", font=F(9), fg=T["muted"],
                 bg=T["panel"]).grid(row=0, column=0, columnspan=2, padx=18, pady=(16, 8), sticky="w")
        bv = {b.key: tk.BooleanVar(value=o.get(b.key, True)) for b in DRAWING_BLOCKS}
        for i, (k, lab) in enumerate(((b.key, b.label) for b in DRAWING_BLOCKS), 1):
            Switch(win, lab, bv[k]).grid(row=i, column=0, columnspan=2, padx=18, pady=3, sticky="w")
        tv = {}
        for j, (k, lab) in enumerate(((k, lab) for k, lab, _ in DRAWING_FIELDS), 7):
            tk.Label(win, text=lab, font=F(9), fg=T["text"], bg=T["panel"]).grid(row=j, column=0, padx=(18, 10),
                                                                                  pady=3, sticky="w")
            tv[k] = tk.StringVar(value=o[k])
            tk.Entry(win, textvariable=tv[k], width=22, font=F(10), bg=T["panel2"], fg=T["text"],
                     insertbackground=T["text"], relief="flat").grid(row=j, column=1, padx=(0, 18), pady=3, ipady=3)
        tk.Label(win, text="Text fields appear in the title block.", font=F(8), fg=T["dim"], bg=T["panel"]).grid(
            row=12, column=0, columnspan=2, padx=18, sticky="w")
        out = {}

        def ok():
            out.update({k: v.get() for k, v in bv.items()})
            out.update({k: v.get().strip() for k, v in tv.items()})
            win.destroy()

        bar = tk.Frame(win, bg=T["panel"])
        bar.grid(row=13, column=0, columnspan=2, pady=(8, 16), padx=18, sticky="e")
        Btn(bar, "Cancel", win.destroy, "ghost", pady=6).pack(side="left", padx=(0, 8))
        Btn(bar, "Save drawing…", ok, "primary", pady=6).pack(side="left")
        win.update_idletasks()
        try:
            win.grab_set()
        except tk.TclError:
            pass
        self.wait_window(win)
        if out:
            self.app.drawing_opts.update(out)
        return out or None

    def export_drawing(self):
        res = self.res
        if res is None or not res.ok or res.drawing is None:
            messagebox.showerror("Can't export yet", "\n\n".join(i.msg for i in (res.errors if res else [])) or
                                 "Fix the highlighted problems first.")
            return
        opts = self._drawing_dialog()
        if opts is None:
            return
        sp = res.spec
        name = f"{self.style.id}_{fmt(sp.L)}x{fmt(sp.W)}x{fmt(sp.H)}_{sp.units}_drawing.pdf"
        path = filedialog.asksaveasfilename(defaultextension=".pdf", initialfile=name,
                                            filetypes=[("PDF drawing", "*.pdf")])
        if not path:
            return
        try:
            data = drawing_pdf(res, sp, opts)
            with open(path, "wb") as fh:
                fh.write(data)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not save", str(exc))
            return
        self.toast.config(text=f"Saved drawing {os.path.basename(path)}", fg=T["good"])

    def export_model3d(self):
        res = self.res
        if res is None or not res.ok or res.drawing is None:
            messagebox.showerror("Can't export yet", "\n\n".join(i.msg for i in (res.errors if res else [])) or
                                 "Fix the highlighted problems first.")
            return
        sp = res.spec
        name = f"{self.style.id}_{fmt(sp.L)}x{fmt(sp.W)}x{fmt(sp.H)}_{sp.units}_blank.3mf"
        path = filedialog.asksaveasfilename(defaultextension=".3mf", initialfile=name,
                                            filetypes=[("3MF model", "*.3mf"), ("STL model", "*.stl")])
        if not path:
            return
        kind = "stl" if path.lower().endswith(".stl") else "3mf"
        try:
            data, m = model_export(res, sp, kind)
            if m.open_edges():
                raise ValueError("the solid model has gaps, so it was not saved")
            with open(path, "wb") as fh:
                fh.write(data)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not save", str(exc))
            return
        note = model_notes(m)
        self.toast.config(text=f"Saved {os.path.basename(path)}" + ("\n" + note[1] if len(note) > 1 else ""),
                          fg=T["good"] if len(note) == 1 else T["warn"])

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
        gc = None
        if kind == "nc":
            gc = self._gcode_dialog()
            if gc is None:
                return
        name = f"{self.style.id}_{fmt(sp.L)}x{fmt(sp.W)}x{fmt(sp.H)}_{sp.units}.{kind}"
        label = dict(EXPORT_FORMATS)[kind]
        path = filedialog.asksaveasfilename(defaultextension=f".{kind}", initialfile=name,
                                            filetypes=[(label + " file", f"*.{kind}")])
        if not path:
            return
        lk = res.look
        head = (f"BoxForge {self.style.name}: L{fmt(sp.L)} W{fmt(sp.W)} H{fmt(sp.H)} thickness {fmt(sp.t)} "
                f"{sp.units} ({sp.mode} dimensions). Layers: CUT {lk['cut_name'].lower()}, "
                f"FOLD {lk['fold_name'].lower()}."
                + (f" Line weights: cut {lk['cut_pt']:g} pt, fold {lk['fold_pt']:g} pt." if kind in WEIGHT_FORMATS
                   else ""))
        notes = [head] + res.notes()
        try:
            data = render_export(kind, res.drawing, sp.units, notes, gc, lk)
            if isinstance(data, bytes):
                with open(path, "wb") as fh:
                    fh.write(data)
            else:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(data)
        except OSError as exc:
            messagebox.showerror("Could not save", str(exc))
            return
        self.toast.config(text=f"Saved {os.path.basename(path)}" + (f"  ·  with {len(res.warnings)} note(s)"
                                                                      if res.warnings else "")
                          + ("" if kind in WEIGHT_FORMATS else "  ·  line weights not applied to this format"),
                          fg=T["good"])


# =============================================================================
# Application
# =============================================================================
LIMITS_TEXT = """How the checks work

RED  - blocks export. The geometry is impossible or would be cut wrong: an inside dimension that is zero or negative, the smallest inside dimension under 4x the board thickness, flaps that cannot fit, or cut outlines that overlap in the flat layout.

AMBER - allowed, but flagged. The design should work but is outside what we can vouch for (smallest dimension under 8x the board thickness, flaps near their limits, extreme proportions, very tight lid clearance...). The notes are saved inside the exported file (SVG <desc>, DXF/EPS/G-code comments, PDF subject).

BLUE - information only.

What the limits are based on
- Structure of each style follows the FEFCO / ECMA families: 0201 slotted box, 0301 telescope. Internal-size conventions come from the FEFCO measuring recommendation (inside length/breadth = crease-to-crease minus one board; height minus two boards).
- Neither FEFCO nor the converter guides found publish numeric limits for board thickness against panel size, so the 4x / 8x rules, slot widths and clearances are engineering rules of thumb, not a standard.

Always cut a test piece on your actual board before a full run: crease behaviour varies with flute, grain direction and score depth."""


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        init_scale(self)                             # before any widget is made
        init_fonts(self)
        self.title("BoxForge  -  Box Dieline Studio")
        self.configure(bg=T["bg"])
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{min(S(1380), sw - 40)}x{min(S(840), sh - 90)}")
        self.minsize(min(S(1100), sw - 40), min(S(700), sh - 90))
        self.saved = {}
        self.gcode = dict(GCODE_DEFAULTS)
        self.drawing_opts = drawing_defaults()       # session only
        self.layout = dict(side_w=S(352), lower_h=None, split=0.5)     # divider positions, kept for the session
        self.look = dict(LOOK_DEFAULTS)     # line colours / weights: shared across boxes
        self.dash = dict(perf_dash=5.0, perf_tie=2.0, bend_r=0.25, bend_on=True, bend_len=True, bend_edges=False)   # dash length / bridge (mm), bend radius (x board), rounded folds on: per session
        self.error_hook = None                       # tests set this to catch errors instead of showing the dialog
        self.recent = []                             # project files opened or saved lately, newest first
        self._last_err = 0.0
        self._load_settings()
        try:
            self._icon = icon_photo(self, 64)
            self.iconphoto(True, self._icon)
        except tk.TclError:                          # a Tk without PhotoImage transparency: keep the default icon
            pass
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.host = tk.Frame(self, bg=T["bg"])
        self.host.pack(fill="both", expand=True)
        self.home = Home(self.host, self)
        self.editor = None
        mac = sys.platform == "darwin"
        for seq, redo in ((("<Command-z>", False), ("<Command-Z>", True)) if mac else ()) + (
                ("<Control-z>", False), ("<Control-Z>", True), ("<Control-y>", True), ("<Control-Y>", True)):
            cb = (lambda e, r=redo: self._undo_key(r))
            self.bind(seq, cb)
            self.bind_class("Entry", seq, cb)                  # Entry's built-in binding for these keys would win
        mod = "Command" if sys.platform == "darwin" else "Control"
        self.bind(f"<{mod}-s>", lambda e: self.save_project())
        self.bind(f"<{mod}-S>", lambda e: self.save_project(True))
        self.bind(f"<{mod}-o>", lambda e: self.open_project())
        self._mac_menu()
        self.show_home()

    def _mac_menu(self, force=False):
        """macOS: the menu bar at the top of the screen (About under the BoxForge menu, File with Open / Save, Quit).
        Other systems keep the menu-free window."""
        if sys.platform != "darwin" and not force:
            return None
        bar = tk.Menu(self)
        appm = tk.Menu(bar, name="apple", tearoff=0)
        appm.add_command(label="About BoxForge", command=self.show_about)
        bar.add_cascade(menu=appm)
        filem = tk.Menu(bar, name="file", tearoff=0)
        filem.add_command(label="Open Project…", accelerator="Cmd+O", command=self.open_project)
        filem.add_command(label="Save", accelerator="Cmd+S", command=self.save_project)
        filem.add_command(label="Save As…", accelerator="Shift+Cmd+S", command=lambda: self.save_project(True))
        filem.add_separator()
        filem.add_command(label="Back to All Boxes", command=self.show_home)
        bar.add_cascade(label="File", menu=filem)
        self.config(menu=bar)
        if sys.platform == "darwin":
            self.createcommand("tk::mac::ShowAbout", self.show_about)
            self.createcommand("tk::mac::Quit", self.close)
        return bar

    # ---------------------------------------------------------------- projects ----
    def _remember(self, path):
        path = os.path.abspath(path)
        self.recent = [path] + [p for p in self.recent if p != path]
        del self.recent[RECENT_MAX:]
        self.home.refresh_recent()

    def _set_title(self):
        ed = self.editor
        nm = os.path.splitext(os.path.basename(ed.project_path))[0] if ed and ed.project_path else ""
        if nm and self.project_dirty():
            nm += " *"
        self.title(f"{nm}  -  BoxForge" if nm else "BoxForge  -  Box Dieline Studio")

    def project_dirty(self):
        """True when the open box came from / went to a project file and has been changed since."""
        ed = self.editor
        return bool(ed and ed.project_path and getattr(ed, "saved_state", None) is not None
                    and ed._state() != ed.saved_state)

    def confirm_leave(self):
        """Before the open project is closed or replaced: offer to save its unsaved changes. False = stay."""
        if not self.project_dirty():
            return True
        nm = os.path.basename(self.editor.project_path)
        ans = messagebox.askyesnocancel("Unsaved changes", f"Save the changes to {nm} before leaving it?", parent=self)
        if ans is None:
            return False
        return self.save_project() if ans else True

    def save_project(self, save_as=False):
        """Save the open box as a project file (asks for a name the first time, or always with `save_as`)."""
        ed = self.editor
        if ed is None:
            return False
        path = ed.project_path
        if save_as or not path:
            path = filedialog.asksaveasfilename(
                parent=self, title="Save project", defaultextension=PROJECT_EXT,
                initialdir=os.path.dirname(path) if path else None,
                initialfile=os.path.basename(path) if path else f"{ed.style.id}-box{PROJECT_EXT}",
                filetypes=[("BoxForge project", "*" + PROJECT_EXT), ("All files", "*.*")])
            if not path:
                return False
        try:
            write_project(path, ed.style.id, ed._state())
        except ValueError as exc:
            ed.toast.config(text=str(exc), fg=T["err"])
            return False
        ed.project_path = path
        ed.saved_state = ed._state()
        self._remember(path)
        self._set_title()
        ed.toast.config(text=f"Saved {os.path.basename(path)}.", fg=T["good"])
        return True

    def open_project(self, path=None):
        """Open a project file (asks which one when no path is given). Returns True when it opened."""
        if not path:
            path = filedialog.askopenfilename(parent=self, title="Open project",
                                              filetypes=[("BoxForge project", "*" + PROJECT_EXT), ("All files", "*.*")])
            if not path:
                return False
        try:
            sid, st = read_project(path)
        except ValueError as exc:
            self.recent = [p for p in self.recent if p != os.path.abspath(path)] if "Could not read" in str(exc) else self.recent
            self.home.refresh_recent()
            messagebox.showerror("Open project", f"{os.path.basename(path)}\n\n{exc}", parent=self)
            return False
        need = [k for k in ("L", "W", "H", "t") if k not in st["vars"]]
        if need:
            messagebox.showerror("Open project", f"{os.path.basename(path)}\n\nThe project has no value for "
                                 f"{', '.join(need)}, so it cannot be opened.", parent=self)
            return False
        if self.editor is not None and not self.confirm_leave():
            return False
        self.saved[sid] = {}                                  # start from the style's defaults, not the last session's
        self.open_style(STYLE_BY_ID[sid])
        ed = self.editor
        full = ed._state()
        full["vars"] = {k: ("" if k not in ("L", "W", "H", "t") else v) for k, v in full["vars"].items()}   # blank = automatic
        full["units"], full["mode"], full["flute"], full["folds"], full["perf"] = "mm", "inner", "off", True, False
        full["feats"] = []
        for k in ("units", "mode", "flute", "folds", "perf", "feats"):
            if k in st:
                full[k] = st[k]
        def compat(old, new):                                  # same kind of value as the editor's own
            if isinstance(old, bool) or isinstance(new, bool):
                return isinstance(old, bool) and isinstance(new, bool)
            if isinstance(old, str):
                return isinstance(new, str)
            return isinstance(new, (int, float))
        for k in ("vars", "flags", "dash", "look"):
            full[k] = {a: (st[k][a] if a in st[k] and compat(v, st[k][a]) else v) for a, v in full[k].items()}
        full["sel"] = None
        ed._apply_state(full)
        ed._undo.clear()
        ed._redo.clear()
        ed.project_path = os.path.abspath(path)
        ed.saved_state = ed._state()
        self._remember(path)
        self._set_title()
        ed.toast.config(text=f"Opened {os.path.basename(path)}.", fg=T["good"])
        return True

    # ---------------------------------------------------------------- settings ----
    def _load_settings(self):
        data = load_settings()
        self.look = _merge_known(self.look, data.get("look"))
        if self.look["cut_weight"] <= 0 or self.look["fold_weight"] <= 0 or self.look["engrave_weight"] <= 0:
            self.look = dict(LOOK_DEFAULTS)
        names = {n for n, _, _ in LINE_COLORS}
        for k in ("cut_color", "fold_color", "engrave_color"):
            if self.look[k] not in names:
                self.look[k] = LOOK_DEFAULTS[k]
        self.gcode = _merge_known(self.gcode, data.get("gcode"))
        self.dash = _merge_known(self.dash, data.get("dash"))
        for k in ("perf_dash", "perf_tie", "bend_r"):
            if self.dash[k] < 0:
                self.dash[k] = {"perf_dash": 5.0, "perf_tie": 2.0, "bend_r": 0.25}[k]
        self.drawing_opts = _merge_known(self.drawing_opts, data.get("drawing"))
        rc = data.get("recent")
        if isinstance(rc, list):
            self.recent = [x for x in rc if isinstance(x, str) and len(x) < 600][:RECENT_MAX]
        sv = data.get("saved")
        if isinstance(sv, dict):
            for sid, snap in sv.items():
                if sid in STYLE_BY_ID:
                    self.saved[sid] = clean_snapshot(snap)

    def save_settings(self):
        if self.editor is not None:
            self.saved[self.editor.style.id] = self.editor.snapshot()
        return save_settings(dict(version=1, look=self.look, gcode=self.gcode, dash=self.dash,
                                  drawing=self.drawing_opts, saved=self.saved, recent=self.recent))

    def reset_settings(self):
        """Forget everything that was saved and go back to the factory values (the open editor is closed)."""
        try:
            os.remove(settings_path())
        except OSError:
            pass
        self.saved = {}
        self.recent = []
        self.look = dict(LOOK_DEFAULTS)
        self.gcode = dict(GCODE_DEFAULTS)
        self.drawing_opts = drawing_defaults()
        self.dash = dict(perf_dash=5.0, perf_tie=2.0, bend_r=0.25, bend_on=True, bend_len=True, bend_edges=False)
        if self.editor is not None:
            self.editor.shutdown()
            self.editor.destroy()
            self.editor = None
            self.show_home()

    def close(self):
        if not self.confirm_leave():
            return
        try:
            self.save_settings()
        finally:
            for stop in (self.home.stop, getattr(self.editor, "shutdown", lambda: None)):   # no timer left running
                try:
                    stop()
                except Exception:                                # noqa: BLE001
                    pass
            self.destroy()

    # ------------------------------------------------------------------ errors ----
    def report_callback_exception(self, exc, val, tb):
        """Anything that goes wrong inside a button or a timer: write it to the log and tell the person, instead of
        failing silently (a packaged program has no console to print to)."""
        text = "".join(traceback.format_exception(exc, val, tb))
        log_error(text)
        try:
            print(text, file=sys.stderr)
        except Exception:                                       # noqa: BLE001
            pass
        if self.error_hook is not None:
            self.error_hook(text)
            return
        now = time.monotonic()
        if now - self._last_err < 3.0:                           # one failing timer must not bury the screen in dialogs
            return
        self._last_err = now
        try:
            messagebox.showerror(
                "BoxForge - something went wrong",
                f"{exc.__name__}: {val}\n\nNothing was lost that was already saved to a file. The details are in:\n"
                f"{log_path()}\n\nIf it keeps happening, send that file along with what you were doing.", parent=self)
        except Exception:                                       # noqa: BLE001
            pass

    def show_about(self):
        win = tk.Toplevel(self, bg=T["panel"])
        win.title("About BoxForge")
        win.resizable(False, False)
        win.transient(self)
        try:
            win.iconphoto(False, self._icon)
        except (AttributeError, tk.TclError):
            pass
        box = tk.Frame(win, bg=T["panel"])
        box.pack(padx=34, pady=26)
        logo = tk.Label(box, image=self._icon, bg=T["panel"]) if getattr(self, "_icon", None) else None
        if logo is not None:
            logo.pack()
        tk.Label(box, text="BoxForge", font=F(18, "bold"), fg=T["text"], bg=T["panel"]).pack(pady=(6, 0))
        tk.Label(box, text=f"Version {__version__}", font=F(10), fg=T["muted"], bg=T["panel"]).pack()
        tk.Label(box, text="Box dieline studio for laser and die cutting", font=F(10), fg=T["text"],
                 bg=T["panel"]).pack(pady=(10, 0))
        tk.Label(box, text=f"Python {sys.version.split()[0]}  ·  Tk {tk.TkVersion}\nSettings and error log: {user_dir()}",
                 font=F(8), fg=T["dim"], bg=T["panel"], justify="center", wraplength=360).pack(pady=(12, 14))
        row = tk.Frame(box, bg=T["panel"])
        row.pack()
        Btn(row, "Limits & sources", lambda: (win.destroy(), self.show_limits()), "ghost", size=9, padx=12,
            pady=6).pack(side="left", padx=4)

        def reset():
            if messagebox.askyesno("Reset saved settings", "Forget the saved sizes, line colours and other options and "
                                   "go back to the factory values?", parent=win):
                win.destroy()
                self.reset_settings()
        Btn(row, "Reset saved settings", reset, "ghost", size=9, padx=12, pady=6).pack(side="left", padx=4)
        Btn(row, "Close", win.destroy, "primary", size=9, padx=16, pady=6).pack(side="left", padx=4)
        win.bind("<Escape>", lambda e: win.destroy())

    def _undo_key(self, redo):
        if self.editor is not None:
            return self.editor.redo() if redo else self.editor.undo()
        return None

    def show_home(self):
        if self.editor and not self.confirm_leave():
            return
        if self.editor:
            self.saved[self.editor.style.id] = self.editor.snapshot()
            self.editor.shutdown()
            self.editor.destroy()
            self.editor = None
        self.title("BoxForge  -  Box Dieline Studio")
        self.home.refresh_recent()
        self.home.pack(fill="both", expand=True)
        self.home.start()

    def open_style(self, style):
        if self.editor is not None:                  # only one box is open at a time
            self.show_home()
        self.home.stop()
        self.home.pack_forget()
        self.editor = Editor(self.host, self, style, self.saved.get(style.id))
        self.editor.pack(fill="both", expand=True)
        self._set_title()

    def show_limits(self):
        win = tk.Toplevel(self, bg=T["panel"])
        win.title("Limits & sources")
        win.geometry(f"{S(720)}x{S(700)}")
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
        return 1
    enable_dpi_awareness()
    try:
        app = App()
    except Exception:                                    # noqa: BLE001 - the window itself could not start
        text = traceback.format_exc()
        log_error(text)
        try:
            print(text, file=sys.stderr)
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror("BoxForge could not start", f"The window could not be opened.\n\nDetails were saved to:\n{log_path()}")
            r.destroy()
        except Exception:                                # noqa: BLE001
            pass
        return 1
    app.mainloop()
    return 0


def parse_feature_arg(kind, text, panels):
    """'--window back,60,40,4' (centred on a panel) or '--window 100,80,60,40,4' (X,Y,W,H,R on the flat sheet).
    Zones take an optional .svg path and 'border' / 'noborder' as extra items."""
    parts = [x.strip() for x in text.split(",") if x.strip()]
    extras = [x for x in parts if x.lower() in ("border", "noborder") or x.lower().endswith(".svg")]
    parts = [x for x in parts if x not in extras]
    art = next((import_svg(x) for x in extras if x.lower().endswith(".svg")), None)
    outline = True if "border" in [x.lower() for x in extras] else False if "noborder" in [x.lower() for x in extras] else None
    try:
        float(parts[0])
        nums = [float(x) for x in parts]
        if len(nums) < 4:
            raise ValueError
        cx, cy, w, h = nums[:4]
        r = nums[4] if len(nums) > 4 else 0.0
    except ValueError:
        by = {n: (cx, cy) for n, cx, cy, *_ in panel_centres(panels or [])}
        if parts[0] not in by:
            raise SystemExit(f"--{kind}: '{parts[0]}' is not a panel big enough to carry a feature. "
                             f"Use --list-panels to see the names and centres.")
        cx, cy = by[parts[0]]
        nums = [float(x) for x in parts[1:]]
        if len(nums) < 2:
            raise SystemExit(f"--{kind}: need PANEL,W,H" + (",R" if kind == "window" else ""))
        w, h = nums[:2]
        r = nums[2] if len(nums) > 2 else 0.0
    return Feature(kind, cx, cy, w, h, r, art=art, outline=outline)


def main(argv=None):
    """No arguments -> open the GUI.  With arguments -> headless export (handy for batch jobs)."""
    import argparse
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        safe_streams()
        return run_gui() or 0
    attach_console()                                 # a windowed program: print to the console it was started from
    if argv == ["--version"]:
        print(f"{APP_NAME} {__version__}")
        return 0
    ap = argparse.ArgumentParser(description="BoxForge - generate a box dieline without the GUI.")
    ap.add_argument("--version", action="store_true", help="print the version and exit")
    ap.add_argument("--style", required=True, choices=sorted(s.id for s in STYLES), help="box style")
    for k in ("L", "W", "H", "t"):
        ap.add_argument(f"--{k}", type=float, required=True)
    ap.add_argument("--mode", choices=["inner", "outer", "manufacturer"], default="inner")
    ap.add_argument("--units", choices=["mm", "in"], default="mm")
    ap.add_argument("--no-folds", action="store_true", help="leave the fold lines out")
    names = [n for n, _, _ in LINE_COLORS]
    ap.add_argument("--cut-color", default=LOOK_DEFAULTS["cut_color"], type=str.title,
                    help="cut line colour: " + ", ".join(names))
    ap.add_argument("--fold-color", default=LOOK_DEFAULTS["fold_color"], type=str.title,
                    help="fold line colour (same presets)")
    ap.add_argument("--cut-weight", type=float, default=LOOK_DEFAULTS["cut_weight"],
                    help="cut line weight in pt (SVG/PDF/EPS only; default 0.1)")
    ap.add_argument("--fold-weight", type=float, default=LOOK_DEFAULTS["fold_weight"],
                    help="fold line weight in pt (SVG/PDF/EPS only; default 1)")
    ap.add_argument("--engrave-color", default=LOOK_DEFAULTS["engrave_color"], type=str.title,
                    help="engrave (zone) line colour (same presets)")
    ap.add_argument("--engrave-weight", type=float, default=LOOK_DEFAULTS["engrave_weight"],
                    help="engrave line weight in pt (SVG/PDF/EPS only; default 0.5)")
    ap.add_argument("--window", action="append", default=[], metavar="SPEC",
                    help="rounded window: PANEL,W,H[,R] or X,Y,W,H[,R] (flat-sheet coordinates); repeatable")
    ap.add_argument("--info", action="append", default=[], metavar="SPEC",
                    help="info zone: PANEL,W,H[,file.svg][,border] or X,Y,W,H[,...]; repeatable")
    ap.add_argument("--logo", action="append", default=[], metavar="SPEC",
                    help="logo zone: PANEL,W,H[,file.svg][,border] or X,Y,W,H[,...]; repeatable")
    seen_tg = {}
    for st_ in STYLES:                                   # a switch of a style becomes a flag: --insert
        for key, label, _ in st_.toggles:
            seen_tg.setdefault(key, label)
    for key, label in seen_tg.items():
        ap.add_argument("--" + key.replace("_", "-"), dest="tg_" + key, action="store_true", help=label)
    ap.add_argument("--list-panels", action="store_true", help="print panel names, centres and sizes, then exit")
    ap.add_argument("--drawing", metavar="FILE.pdf", help="write a dimensioned drawing sheet ")
    ap.add_argument("--dwg-off", default="", metavar="LIST",
                    help="drawing blocks to leave out, comma separated: " + ",".join(b.cli for b in DRAWING_BLOCKS)
                    + " (" + ", ".join(f"{b.cli} = {b.note}" for b in DRAWING_BLOCKS if b.note) + ")")
    for k, _, _ in DRAWING_FIELDS:
        ap.add_argument("--dwg-" + k, default="", help=f"drawing title block: {k}")
    for k, lab in TOL_LABELS.items():
        ap.add_argument("--tol-" + k.replace("_", "-"), type=float, default=None,
                        help=f"drawing tolerance +/- mm: {lab.lower()} (default: automatic)")
    ap.add_argument("--stl", metavar="FILE.stl", help="write the flat cut blank as a 3-D solid, binary STL")
    ap.add_argument("--3mf", dest="threemf", metavar="FILE.3mf", help="same, as a 3MF file ")
    ap.add_argument("--dashed", action="store_true", help="draw fold lines as dashed cuts (perforation)")
    ap.add_argument("--dash", type=float, default=5.0, metavar="MM",
                    help="dashed folds: length of each cut, 1-20 mm (default 5; needs --dashed)")
    ap.add_argument("--bridge", type=float, default=2.0, metavar="MM",
                    help="dashed folds: uncut bridge between cuts, 0.5-10 mm (default 2; needs --dashed)")
    ap.add_argument("--material", choices=sorted(BEND_MATERIALS), default=BEND_DEFAULT,
                    help="bend model preset (typical values, not measured): sets the default bend radius, K-factor, springback")
    ap.add_argument("--bend-radius", type=float, default=None, metavar="R",
                    help="inside bend radius in the chosen units (default: the material preset x board thickness)")
    ap.add_argument("--bend-k", type=float, default=None, metavar="K", help="neutral-axis K-factor 0..0.5 (default: material preset)")
    ap.add_argument("--bend-report", action="store_true",
                    help="print bend angles, bend allowance / deduction per fold type and material usage ")
    ap.add_argument("--kerf", type=float, default=0.0, help="laser kerf (beam width) in the chosen units; 0 = off")
    ap.add_argument("--opt", action="append", default=[], metavar="KEY=VALUE",
                    help="advanced option (e.g. glue=25); repeat as needed")
    ap.add_argument("--flute", choices=("off", "vertical", "horizontal"), default="off",
                    help="corrugated flute direction on the flat sheet: marked on the drawing (label and arrow) "
                         "- vertical = along the sheet's up-down axis")
    for f in CLI_FORMATS:
        ap.add_argument("--" + f.flag, help=f"write a .{f.flag} file")
    for k, v in GCODE_DEFAULTS.items():
        ap.add_argument("--" + k.replace("_", "-"), type=float, default=v, help="G-code " + k.replace("_", " "))
    a = ap.parse_args(argv)
    st = STYLE_BY_ID[a.style]
    spec = default_spec(st, a.units)
    spec.L, spec.W, spec.H, spec.t, spec.mode, spec.folds = a.L, a.W, a.H, a.t, a.mode, not a.no_folds
    spec.kerf = a.kerf
    for key, _, _ in st.toggles:
        spec.flags[key] = bool(getattr(a, "tg_" + key, False))
    for key in seen_tg:
        if getattr(a, "tg_" + key, False) and key not in {k for k, _, _ in st.toggles}:
            print(f"[NOTE ] --{key.replace('_', '-')} does not apply to {st.name}; it was ignored.")
    spec.material, spec.bend_r, spec.bend_k = a.material, a.bend_radius, a.bend_k
    spec.perf = a.dashed
    spec.flute = {"vertical": "v", "horizontal": "h"}.get(a.flute)
    spec.perf_dash, spec.perf_tie = a.dash, a.bridge
    if not a.dashed and (a.dash != 5.0 or a.bridge != 2.0):
        print("[NOTE ] --dash and --bridge only apply with --dashed; they were ignored.")
    spec.look = dict(cut_color=a.cut_color, fold_color=a.fold_color, cut_weight=a.cut_weight,
                     fold_weight=a.fold_weight, engrave_color=a.engrave_color, engrave_weight=a.engrave_weight)
    for kv in a.opt:
        k, _, v = kv.partition("=")
        spec.opts[k] = float(v)
    spec.tol = {k: getattr(a, "tol_" + k) for k in TOL_LABELS if getattr(a, "tol_" + k) is not None}
    if a.list_panels or a.window or a.info or a.logo:
        base = generate(st, spec)
        if a.list_panels:
            for n, cx, cy, w, h, _ in panel_centres(base.panels or []):
                nd = 3 if a.units == "in" else 2
                print(f"{n:10s} centre ({cx:.{nd}f}, {cy:.{nd}f})  size {w:.{nd}f} x {h:.{nd}f} {a.units}")
            return 0
        try:
            spec.features = [parse_feature_arg(k, t, base.panels) for k, lst in
                             (("window", a.window), ("info", a.info), ("logo", a.logo)) for t in lst]
        except (ValueError, OSError) as exc:
            raise SystemExit(f"Could not read a window / zone option: {exc}")
    res = generate(st, spec)
    for i in res.issues:
        print(f"[{i.level.upper():5s}] {i.msg}")
    if not res.ok:
        print("Not exported: fix the errors above.")
        return 1
    lk = res.look
    head = f"BoxForge {st.name} L{fmt(a.L, 3)} W{fmt(a.W, 3)} H{fmt(a.H, 3)} t{fmt(a.t, 3)} {a.units} ({a.mode})"
    gc = {k: getattr(a, k) for k in GCODE_DEFAULTS}
    for kind, path in ((f.kind, getattr(a, f.flag)) for f in CLI_FORMATS):
        if path:
            notes = [head + f". CUT {lk['cut_name']}, FOLD {lk['fold_name']}"
                     + (f"; line weights cut {lk['cut_pt']:g} pt, fold {lk['fold_pt']:g} pt." if kind in WEIGHT_FORMATS
                        else ".")] + res.notes()
            if kind not in WEIGHT_FORMATS and (a.cut_weight != LOOK_DEFAULTS["cut_weight"]
                                              or a.fold_weight != LOOK_DEFAULTS["fold_weight"]):
                print(f"[NOTE ] {WEIGHT_NOTE} Weights were not applied to {path}.")
            data = render_export(kind, res.drawing, a.units, notes, gc, lk)
            with open(path, "wb" if isinstance(data, bytes) else "w", **({} if isinstance(data, bytes) else {"encoding": "utf-8"})) as fh:
                fh.write(data)
            print("wrote", path)
    if a.bend_report:
        print(bend_report_text(bend_report(res, spec), a.units))
    if a.drawing:
        off = {x.strip() for x in a.dwg_off.split(",") if x.strip()}
        blocks = drawing_blocks_from_off(off, {k: getattr(a, "dwg_" + k) for k, _, _ in DRAWING_FIELDS})
        with open(a.drawing, "wb") as fh:
            fh.write(drawing_pdf(res, spec, blocks))
        print("wrote", a.drawing)
    for kind, path in (("stl", a.stl), ("3mf", a.threemf)):
        if path:
            data, m = model_export(res, spec, kind)
            if m.open_edges():
                print("[ERROR] the solid model has gaps; not written.")
                return 1
            with open(path, "wb") as fh:
                fh.write(data)
            print("wrote", path)
            for line in model_notes(m):
                print("[NOTE ]", line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

