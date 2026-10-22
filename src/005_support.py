
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
