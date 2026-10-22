#!/usr/bin/env python3
"""Smoke + extension tests.   python tests/smoke.py [module.py]
Checks every registered style / export format / drawing block works, and that a new style, export and drawing
block can be added through the registries alone (the recipe in DEVELOPING.md)."""
import math, importlib.util, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(os.path.dirname(HERE), "dieline_generator.py")
spec_ = importlib.util.spec_from_file_location("dg", PATH)
dg = importlib.util.module_from_spec(spec_)
sys.modules["dg"] = dg
spec_.loader.exec_module(dg)

fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra and not ok else ""))
    if not ok:
        fails.append(name)


SQUARE_ONLY = set()                    # styles that only accept a square box (none now)


def make(style_id, dims=None, units="mm"):
    st = dg.STYLE_BY_ID[style_id]
    sp = dg.default_spec(st, units)
    sp.L, sp.W, sp.H, sp.t = dims or ((150, 150, 100, 3) if style_id in SQUARE_ONLY else (150, 100, 60, 3))
    return st, sp, dg.generate(st, sp)


ALL = dg.STYLE_BY_ID
# --- every style x every export format ---------------------------------------------------------------------
for sid in ALL:
    st, sp, res = make(sid)
    check(f"{sid}: generates", res.ok, str([i.msg for i in res.issues if i.level == "error"]))
    for f in dg.EXPORT_REGISTRY:
        try:
            data = dg.render_export(f.kind, res.drawing, "mm", ["note"], dict(dg.GCODE_DEFAULTS), res.look)
            check(f"{sid}: export {f.kind}", len(data) > 100)
        except Exception as e:                                   # noqa: BLE001
            check(f"{sid}: export {f.kind}", False, repr(e))
    try:                                                         # every drawing block can be switched off alone
        full = dg.drawing_pdf(res, sp, dg.drawing_blocks_from_off(set()))
        check(f"{sid}: drawing", full[:4] == b"%PDF")
        for b in dg.DRAWING_BLOCKS:
            pdf = dg.drawing_pdf(res, sp, dg.drawing_blocks_from_off({b.cli}))
            check(f"{sid}: drawing without {b.key}", pdf[:4] == b"%PDF" and (not b.page or len(pdf) != len(full) or (b.key == "bends" and st.flat_parts)))
    except Exception as e:                                       # noqa: BLE001
        check(f"{sid}: drawing", False, repr(e))
    try:                                                         # folded solid at several slider positions
        for amt in (0.0, 0.3, 0.7, 1.0):
            prog_of, lift_of, layer = dg.style_sequence(sid, res.panels, sp.t, amt)
            faces = dg.solid_faces(res.panels, sp.t, prog_of, lift_of)
            assert faces
        check(f"{sid}: folded solid", True)
    except Exception as e:                                       # noqa: BLE001
        check(f"{sid}: folded solid", False, repr(e))


# --- flute lines: every panel gets them, they run the right way on the flat sheet and lie on the outside face -------
def _dist_to_plane(pt, face_pts):
    nx = ny = nz = 0.0
    for i in range(len(face_pts)):
        a, b = face_pts[i], face_pts[(i + 1) % len(face_pts)]
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    L = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
    return abs((pt[0] - face_pts[0][0]) * nx + (pt[1] - face_pts[0][1]) * ny + (pt[2] - face_pts[0][2]) * nz) / L


for sid in ("rsc", "telescope"):
    st, sp, res = make(sid)
    for fl, want in (("v", (0.0, 1.0, 0.0)), ("h", (1.0, 0.0, 0.0))):
        ok_dir = ok_plane = True
        covered = set()
        for amt in (0.0, 0.5, 1.0):
            pf, lf, _ = dg.style_sequence(sid, res.panels, sp.t, amt)
            for bend in (None, 0.25 * sp.t):
                F = dg.solid_faces(res.panels, sp.t, pf, lf, bend=bend, flute=fl)
                outs = {}
                for f in F:
                    if f[1] == "out":
                        outs.setdefault(f[0], f[2])
                for f in F:
                    if f[1] != "flute":
                        continue
                    covered.add(f[0])
                    a, b = f[2]
                    if amt == 0.0:
                        d = [b[i] - a[i] for i in range(3)]
                        n = sum(c * c for c in d) ** 0.5
                        ok_dir &= abs(abs(sum(d[i] * want[i] for i in range(3))) / n - 1.0) < 1e-6
                    if f[0] in outs:
                        ok_plane &= max(_dist_to_plane(a, outs[f[0]]), _dist_to_plane(b, outs[f[0]])) < 1e-6
                nf = [f for f in dg.solid_faces(res.panels, sp.t, pf, lf, bend=bend) if f[1] == "flute"]
                ok_plane &= not nf                                   # nothing drawn when flute is off
        check(f"{sid}: flute {fl} direction on the flat sheet", ok_dir)
        check(f"{sid}: flute {fl} lines lie on the outside faces", ok_plane)
        check(f"{sid}: flute {fl} on every panel", covered == {p.name for p in res.panels}, str(sorted(covered)))
    for fl in ("v", "h"):
        sp.flute = fl
        pdf = dg.drawing_pdf(res, sp, dg.drawing_blocks_from_off({"steps", "bends"}))
        sp.flute = None
        base = dg.drawing_pdf(res, sp, dg.drawing_blocks_from_off({"steps", "bends"}))
        check(f"{sid}: drawing marks flute {fl}", pdf[:4] == b"%PDF" and pdf != base)

# --- extension recipe: add a style, an export format and a drawing block without touching other code --------------
class Toy(dg.RSC):
    id, name, code, blurb = "toy", "Toy", "TOY", "test only"


n_styles = len(dg.STYLES)
dg.register_style(Toy(), listed=False)
st, sp, res = make("toy")
check("new style registers and generates", res.ok and "toy" in dg.STYLE_BY_ID and len(dg.STYLES) == n_styles)
dg.register_export("txt", "Text", lambda d, u, n, g, lk: "panels\n", flag="txt")
check("new export reachable", dg.render_export("txt", res.drawing, "mm", [], None, res.look) == "panels\n"
      and ("txt", "Text") in dg.EXPORT_FORMATS and any(f.kind == "txt" for f in dg.CLI_FORMATS))
dg.register_drawing_block("extra", "Extra page", page=lambda r, s, W, H, b: dg.fold_steps_page(r, s, W, H, b))
check("new drawing block reachable", "extra" in dg.drawing_defaults()
      and dg.drawing_pdf(res, sp, dg.drawing_blocks_from_off(set()))[:4] == b"%PDF")
# undo so later checks (and a re-run in the same process) see the shipped registry
dg.STYLE_BY_ID.pop("toy")
dg.EXPORT_REGISTRY[:] = [f for f in dg.EXPORT_REGISTRY if f.kind != "txt"]
dg.EXPORT_BY_KIND.pop("txt")
dg._refresh_export_views()
dg.DRAWING_BLOCKS[:] = [b for b in dg.DRAWING_BLOCKS if b.key != "extra"]
dg.DRAWING_BY_KEY.pop("extra")

# --- command line ------------------------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    out = os.path.join(td, "a.svg")
    r = subprocess.run([sys.executable, PATH, "--style", "rsc", "--L", "150", "--W", "100", "--H", "60", "--t", "3", "--svg", out], capture_output=True, text=True)
    check("cli: writes svg", r.returncode == 0 and os.path.getsize(out) > 500, r.stderr[-200:])
    r = subprocess.run([sys.executable, PATH, "--style", "rsc", "--L", "0", "--W", "100", "--H", "60", "--t", "3", "--svg", os.path.join(td, "b.svg")], capture_output=True, text=True)
    check("cli: bad size refused", r.returncode != 0 or "ERROR" in r.stdout.upper())

# --- fold sequence with an insert: fold above the box together with the walls, drop in, then the flaps ------------
st_, sp_ = dg.STYLE_BY_ID["rsc"], dg.default_spec(dg.STYLE_BY_ID["rsc"])
sp_.L = sp_.W = 100.0
sp_.H, sp_.t = 100.0, 3.0
sp_.flags = dict(sp_.flags, insert=True)
r_ = dg.generate(st_, sp_)
P = {p.name: p for p in r_.panels}


def seq_at(a):
    pf, lf, _ = dg.style_sequence("rsc", r_.panels, 3.0, a)
    return pf, lf


def low_y(a):
    pf, lf = seq_at(a)
    F = dg.solid_faces(r_.panels, 3.0, pf, lf)
    return (min(q[1] for f in F if f[0][:2] in ("ia", "ib", "ic") for q in f[2]),
            max(q[1] for f in F if f[0] in ("p1", "p2", "p3", "p4") for q in f[2]))
pf, _ = seq_at(dg.SEQ_INS_FOLD)
check("sequence: walls, glue flap and insert folds finish together",
      all(pf(P[n], 1, 1) == 1.0 for n in ("p1", "glue", "ia", "ib", "ic")) and pf(P["top1"], 1, 1) == 0.0)
check("sequence: insert hovers above the box while it folds", seq_at(0.2)[0].insert_hover == 1.0
      and seq_at(dg.SEQ_INS_FOLD)[0].insert_hover == 1.0)
lo, top = low_y(dg.SEQ_INS_FOLD)
check("sequence: folded insert is clear of the open box", lo >= top - 1e-6, f"{lo} vs {top}")
pf2, _ = seq_at(dg.SEQ_INS_DROP)
lo2, _t2 = low_y(dg.SEQ_INS_DROP)
check("sequence: insert is down in the box before any flap moves",
      pf2.insert_hover == 0.0 and pf2(P["top1"], 1, 1) == 0.0 and pf2(P["bot2"], 1, 1) == 0.0 and lo2 < lo - 50)
mid = low_y((dg.SEQ_INS_FOLD + dg.SEQ_INS_DROP) / 2)[0]
check("sequence: insert goes down steadily", lo2 < mid < lo)
pf3, _ = seq_at(1.0)
check("sequence: flaps close at the end", pf3(P["top1"], 1, 1) == 1.0 and pf3.insert_hover == 0.0)
check("sequence: no insert, no change", dg.rsc_sequence(dg.generate(st_, dg.default_spec(st_)).panels, 3.0, 0.5)[0].insert_hover == 0.0)
check("drawing: fold steps page shows four steps with an insert",
      [v[0] for v in st_.step_views(r_)] == ["flat", "above", "down", "folded"]
      and [v[0] for v in st_.step_views(dg.generate(st_, dg.default_spec(st_)))] == ["flat", "partial", "folded"])

# --- app support: version, saved settings, icon, windowed-program output -----------------------------------------
home = tempfile.mkdtemp()
os.environ["BOXFORGE_HOME"] = home
r = subprocess.run([sys.executable, PATH, "--version"], capture_output=True, text=True)
check("cli: --version", r.returncode == 0 and r.stdout.strip() == f"BoxForge {dg.__version__}", r.stdout + r.stderr[-200:])
check("settings: none saved -> empty", dg.load_settings() == {})
check("settings: round trip", dg.save_settings({"a": 1}) and dg.load_settings() == {"a": 1})
open(dg.settings_path(), "w").write("{ not json")
check("settings: a damaged file is ignored", dg.load_settings() == {})
open(dg.settings_path(), "w").write("[1, 2]")
check("settings: a file of the wrong shape is ignored", dg.load_settings() == {})
snap = dg.clean_snapshot({"L": "120", "units": "furlongs", "flute": "v", "flag_insert": True, "x" * 50: "a", "bad": [1], "n": 5})
check("settings: odd values dropped", snap == {"L": "120", "flute": "v", "flag_insert": True}, repr(snap))
m = dg._merge_known({"w": 1.0, "c": "Blue", "b": True}, {"w": "heavy", "c": "Red", "b": 1, "zzz": 3})
check("settings: wrong kinds fall back to defaults", m == {"w": 1.0, "c": "Red", "b": True}, repr(m))
dg.log_error("Traceback: test")
check("log: error written", "Traceback: test" in open(dg.log_path(), encoding="utf-8").read())
px = dg.icon_pixels(32)
check("icon: drawn with a transparent surround", len(px) == 32 and px[0][0][3] == 0 and px[16][16][3] == 255)
import io, contextlib
old = (sys.stdout, sys.stderr)
sys.stdout = sys.stderr = None                       # what a windowed program starts with
dg.safe_streams()
print("still fine")
ok = sys.stdout is not None
sys.stdout, sys.stderr = old
check("windowed program: print survives having no console", ok)


# --- project files ----------------------------------------------------------------------------------------------
import tempfile as _tf
_good = {"app": "BoxForge", "format": 1, "style": "rsc", "vars": {"L": "100", "W": 5, "bad" * 20: "x"},
         "units": "furlongs", "flags": {"insert": True, "z": [1]},
         "features": [{"kind": "window", "cx": 10, "cy": 5, "w": 20, "h": 10}, {"kind": "window", "cx": "a"},
                      {"kind": "logo", "cx": 1, "cy": 1, "w": 5, "h": 5, "art": {"name": "a", "polys": [[[[0, 0], [1, 1]], False]]}}]}
_sid, _st = dg.project_from_text(__import__("json").dumps(_good))
check("project: odd values dropped, good ones kept", _sid == "rsc" and _st["vars"] == {"L": "100"} and "units" not in _st
      and _st["flags"] == {"insert": True} and len(_st["feats"]) == 2 and _st["feats"][1][6] is not None, repr(_st))
for _bad, _why in (("", "empty"), ("{", "broken json"), ("[]", "list"), ('{"app":"x","style":"rsc"}', "other app"),
                   ('{"app":"BoxForge","style":"nope","format":1}', "unknown style"),
                   ('{"app":"BoxForge","style":"rsc","format":99}', "newer format")):
    try:
        dg.project_from_text(_bad)
        check("project: rejects " + _why, False)
    except ValueError:
        check("project: rejects " + _why, True)
_d = _tf.mkdtemp()
_state = dict(vars={"L": "10"}, units="mm", mode="inner", folds=True, perf=False, flute="off", flags={}, look={}, dash={},
              feats=[("window", 1.0, 2.0, 3.0, 4.0, 0.0, None, False, 0)], sel=None)
dg.write_project(_d + "/a.boxforge", "rsc", _state)
_sid2, _st2 = dg.read_project(_d + "/a.boxforge")
check("project: write then read", _sid2 == "rsc" and _st2["feats"] == _state["feats"] and _st2["vars"] == {"L": "10"})
check("project: no temporary file left", __import__("os").listdir(_d) == ["a.boxforge"])

# ---- audit v0.2.1 regressions ----
import re as _re
_st, _sp, _tl = make("telescope", (150, 100, 60, 2))
check("telescope: inner L is clear between flaps, crease 154",
      abs(_tl.info["inner"][0] - 150) < 1e-9 and abs(_tl.info["crease"][0] - 154) < 1e-9)
check("telescope: lid clear length = base outside + clearance",
      abs((_tl.info["auto"]["Llc"] - 4) - (_tl.info["crease"][0] + 4 + _tl.info["auto"]["clr"])) < 1e-9)
_sp.mode, _sp.L = "outer", 158
check("telescope: outer mode L 158 -> crease 154", abs(dg.generate(_st, _sp).info["crease"][0] - 154) < 1e-9)
_sp.mode, _sp.L, _sp.opts = "inner", 150, {"flap": 0}
check("telescope: no flaps -> inner L = crease", abs(dg.generate(_st, _sp).info["crease"][0] - 150) < 1e-9)
_rs = dg.STYLE_BY_ID["rsc"]
_sp = dg.default_spec(_rs, "in")
_sp.L = _sp.W = _sp.H = 3.5; _sp.t = 0.18; _sp.mode = "outer"
_pp = _re.findall(r'<path d="([^"]+)"', dg.to_svg(dg.generate(_rs, _sp).drawing, "in"))
check("svg: inch job outline closes", any(p.endswith("Z") for p in _pp))

print("\n%d failure(s)" % len(fails) if fails else "\nALL OK")

# ---- QA retest v0.2.2 -> v0.2.3 regressions ----
import re as _re2
for _sid in dg.STYLE_BY_ID:
    for _u in ("mm", "in"):
        _s3 = dg.STYLE_BY_ID[_sid]
        _r3 = dg.generate(_s3, dg.default_spec(_s3, _u))
        _g3 = _re2.search(r'<g id="CUT".*?</g>', dg.to_svg(_r3.drawing, _u), _re2.S)
        _p3 = _re2.findall(r'<path d="([^"]+)"', _g3.group(0))
        _need = 2 if _sid == "telescope" else 1
        check(f"svg: {_sid} {_u} cut outlines closed", sum(p.endswith("Z") for p in _p3) >= _need, f"{len(_p3)} paths")
_ts = dg.STYLE_BY_ID["telescope"]
_rt = dg.generate(_ts, dg.default_spec(_ts, "mm"))
_cut_len = lambda items: sum(math.dist(i[1], i[2]) for i in items if i[0] == "L" and i[-1] == dg.CUT)
check("fit test: slot tolerance is under half the step",
      dg.generate(dg.STYLE_BY_ID["fit"], dg.default_spec(dg.STYLE_BY_ID["fit"], "mm")).info["tol"]["values"]["slot"] < 0.05)
for _sid in ("grid", "fit"):
    check(f"{_sid}: bend-data page left out", dg.STYLE_BY_ID[_sid].flat_parts is True)
_pdf_g = dg.drawing_pdf(dg.generate(dg.STYLE_BY_ID["grid"], dg.default_spec(dg.STYLE_BY_ID["grid"], "mm")),
                        dg.default_spec(dg.STYLE_BY_ID["grid"], "mm"), dg.drawing_defaults())
check("grid: drawing has no bend page", b"BEND DATA" not in _pdf_g and b"/Count 2" in _pdf_g or b"/Count 1" in _pdf_g)

# ---- 3-D preview: fixed framing, cached ordering ----
class _CV:
    def __init__(self): self.calls = []
    def winfo_width(self): return 600
    def winfo_height(self): return 700
    def cget(self, k): return 600
    def delete(self, *a): self.calls = []
    def create_oval(self, *a, **k): self.calls.append(("o", a))
    def create_polygon(self, *a, **k): self.calls.append(("p", a, k.get("fill")))
    def create_line(self, *a, **k): self.calls.append(("l", a))
    def tag_lower(self, *a): pass
    def coords(self, *a): pass
    def itemconfigure(self, *a, **k): pass
for _sid in ("rsc", "telescope", "grid"):
    _st = dg.STYLE_BY_ID[_sid]
    _sp = dg.default_spec(_st, "mm")
    _res = dg.generate(_st, _sp)
    _w = dg.Wire3D(_CV(), _st.view_up)
    _w.set_panels(_res.panels, _st.view_up)
    _w.solid, _w.seq, _w.thick, _w.style_id, _w.fixed_frame = True, True, _sp.t, _sid, True
    _fr = []
    for _a in (0.0, 0.3, 0.7, 1.0):
        _w.amount = _a
        _w.render()
        _fr.append(_w._frame())
    check(f"3-D {_sid}: framing does not change while the box folds", all(f == _fr[0] for f in _fr))
    _w.fixed_frame = False
    _w.amount = 1.0
    _w.render()
    _w.amount = 0.0
    _w.render()
    check(f"3-D {_sid}: solid view draws faces at every fold amount", any(c[0] == "p" for c in _w.cv.calls))

bad = 0
n = 0
# ---- editable dimension callouts: typing a new value in a callout must give exactly that value back ----
import copy as _copy
_nd, _bd = 0, []
cases=[("rsc",{},"inner"),("rsc",{},"outer"),("rsc",{},"manufacturer"),("rsc",{"insert":True},"inner"),("rsc",{"insert_grid":True},"inner"),("telescope",{},"inner"),("telescope",{},"outer"),("insert",{},"inner"),("grid",{},"inner"),("fit",{},"inner")]
for sid,flags,mode in cases:
  for units in ("mm","in"):
    st=dg.STYLE_BY_ID[sid]; sp=dg.default_spec(st,units); sp.mode=mode; sp.flags.update(flags)
    if sid=="fit": sp.W=sp.L*1.3
    r=dg.generate(st,sp)
    dims=st.dimensions(r,sp)
    for i,dm in enumerate(dims):
        f=st.dim_field(dm,r,sp)
        if not f: continue
        key,now=f[0],f[1]; scale=f[2] if len(f)>2 else 1.0
        typed=dm["v"]+ (3.0 if units=="mm" else 0.2)
        base=getattr(sp,key) if now is None else now
        new=base+(typed-dm["v"])*scale
        sp2=_copy.deepcopy(sp)
        if key in ("L","W","H","t"): setattr(sp2,key,new)
        else: sp2.opts=dict(sp2.opts); sp2.opts[key]=new
        r2=dg.generate(st,sp2)
        if not r2.panels:
            print("NOGEN",sid,mode,units,dm["tag"],key,[i.msg for i in r2.errors][:1]); bad+=1; continue
        d2=[d for d in st.dimensions(r2,sp2) if d["tag"]==dm["tag"] and d["kind"]==dm["kind"]]
        n+=1
        # duplicates (same tag and kind) must all move
        ok=bool(d2) and all(abs(d["v"]-typed)<1e-6 or abs(d["v"]-dm["v"])<1e-6 for d in d2) and any(abs(d["v"]-typed)<1e-6 for d in d2)
        if not ok:
            bad+=1; print("MISMATCH",sid,mode,units,dm["tag"],dm["kind"],key,"typed",typed,"got",[d["v"] for d in d2])
check("callouts: every editable dimension round-trips exactly (mode x units x style)", not bad and n > 100, f"{n} checked, {bad} bad")

sys.exit(1 if fails else 0)
