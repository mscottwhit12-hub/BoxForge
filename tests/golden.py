#!/usr/bin/env python3
"""Golden-output safety net: records / checks hashes of everything the app produces.

    python tests/golden.py record  [module.py]   write tests/golden.json from the given module (default: dieline_generator.py)
    python tests/golden.py check   [module.py]   compare the module against tests/golden.json

Covers the command line (SVG DXF PDF EPS PLT G-code, drawing sheet, STL, 3MF) for a matrix of styles / sizes /
options, plus the folded-solid faces and 3-D draw order at several fold amounts. A refactor is output-identical
when `check` passes."""
import hashlib, importlib.util, json, os, re, subprocess, sys, tempfile, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GOLD = os.path.join(HERE, "golden.json")

CASES = []
for sid in ("rsc", "telescope"):
    for dims in ("150,100,60,3", "80,80,80,2", "300,60,40,1"):
        CASES.append([sid, dims, []])
    CASES.append([sid, "3.5,3.5,3.5,0.18", ["--units", "in"]])
    CASES.append([sid, "150,100,60,3", ["--mode", "outer", "--kerf", "0.2"]])
    CASES.append([sid, "150,100,60,3", ["--dashed", "--bend-radius", "1.5", "--bend-report"]])
    CASES.append([sid, "120,90,50,2", ["--no-folds", "--cut-color", "Red", "--fold-weight", "2",
                                         "--dwg-off", "steps,bends", "--tol-panel", "0.5"]])
CASES.append(["rsc", "150,100,60,3", ["--window", "p2,40,30,5", "--info", "p1,60,20"]])
CASES.append(["rsc", "150,100,60,3", ["--flute", "vertical"]])
CASES.append(["insert", "150,150,100,3", []])
CASES.append(["insert", "3.5,3.5,3.5,0.15", ["--units", "in", "--kerf", "0.1"]])
CASES.append(["rsc", "150,150,100,3", ["--insert"]])
CASES.append(["rsc", "240,160,90,3", ["--insert-grid", "--opt", "gnl=2", "--opt", "gnw=3"]])
CASES.append(["insert", "240,160,100,3", []])
CASES.append(["rsc", "200,120,100,3", ["--insert"]])
CASES.append(["fit", "30,30,15,3", []])
CASES.append(["fit", "30,30,15,3", ["--opt", "count=8", "--opt", "step=0.05"]])
CASES.append(["grid", "200,150,120,3", []])
CASES.append(["grid", "240,160,90,3", ["--opt", "nl=2", "--opt", "nw=3"]])
CASES.append(["rsc", "3.5,3.5,3.5,0.15", ["--insert", "--units", "in", "--flute", "vertical"]])
CASES.append(["telescope", "150,100,60,3", ["--flute", "horizontal"]])
FORMATS = (("--svg", "a.svg"), ("--dxf", "a.dxf"), ("--pdf", "a.pdf"), ("--eps", "a.eps"), ("--plt", "a.plt"),
           ("--gcode", "a.nc"), ("--drawing", "d.pdf"), ("--stl", "m.stl"), ("--3mf", "m.3mf"))
DATE = re.compile(rb"20\d\d-\d\d-\d\d|D:20\d{12}[^)]*|CreationDate[^\n]*|/ID *\[[^\]]*\]")


def digest(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    if path.endswith(".3mf"):
        z = zipfile.ZipFile(path)
        raw = b"".join(n.encode() + z.read(n) for n in sorted(z.namelist()))
    return hashlib.sha256(DATE.sub(b"", raw)).hexdigest()[:16]


def run_cli(module, case):
    sid, dims, extra = case
    L, W, H, t = dims.split(",")
    with tempfile.TemporaryDirectory() as d:
        cmd = [sys.executable, module, "--style", sid, "--L", L, "--W", W, "--H", H, "--t", t] + extra
        for flag, name in FORMATS:
            cmd += [flag, os.path.join(d, name)]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        out = {"rc": p.returncode, "stdout": hashlib.sha256(DATE.sub(b"", p.stdout.replace(d, "").encode())).hexdigest()[:16]}
        for _, name in FORMATS:
            f = os.path.join(d, name)
            out[name] = digest(f) if os.path.exists(f) else None
        return out


def rnd(o):
    """repr with floats rounded, so the hash ignores noise below 1e-4."""
    if isinstance(o, float):
        return repr(round(o, 4))
    if isinstance(o, (list, tuple)):
        return "(" + ",".join(rnd(x) for x in o) + ")"
    return repr(o)


def api_hashes(module):
    spec = importlib.util.spec_from_file_location("dg_under_test", module)
    dg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dg)
    res = {}
    for sid in ("rsc", "telescope"):
        r = dg.generate(dg.STYLE_BY_ID[sid], dg.Spec(150, 100, 60, 3))
        for amt in (0.0, 0.2, 0.45, 0.7, 1.0):
            pf, lf, _ = dg.style_sequence(sid, r.panels, 3, amt)
            for bend in (None, 0.0, 3.0):
                F = dg.solid_faces(r.panels, 3, pf, lf, bend=bend)
                txt = repr([(f[0], f[1], [tuple(round(c, 5) for c in q) for q in f[2]], f[3]) for f in F])
                key = f"{sid}/{amt}/{bend}"
                res[key + "/faces"] = hashlib.sha256(txt.encode()).hexdigest()[:16]
                if bend is not None:                       # flute lines on the outside faces, both directions
                    for fl in ("v", "h"):
                        Ff = dg.solid_faces(r.panels, 3, pf, lf, bend=bend, flute=fl)
                        txt = repr([(f[0], f[1], [tuple(round(c, 5) for c in q) for q in f[2]], f[3]) for f in Ff])
                        res[key + f"/flute{fl}"] = hashlib.sha256(txt.encode()).hexdigest()[:16]
                for yaw, pit in ((-0.62, 0.5), (2.4, -0.3)):
                    polys = dg.iso_solid_polys(F, yaw=yaw, pitch=pit)
                    res[key + f"/order{yaw}"] = hashlib.sha256(rnd(polys).encode()).hexdigest()[:16]
    for sid, fl in (("insert", {}), ("rsc", {"insert": True}), ("grid", {}), ("rsc", {"insert_grid": True, "x": 0})):
        sp = dg.Spec(150, 150, 100, 3)
        sp.flags = dict(sp.flags, **{k: v for k, v in fl.items() if k != "x"})
        if sid == "grid" or "insert_grid" in fl:
            sp.opts = dict(sp.opts, **({"gnl": 2, "gnw": 2} if "insert_grid" in fl else {"nl": 2, "nw": 2}))
        r = dg.generate(dg.STYLE_BY_ID[sid], sp)
        for amt in (0.3, 1.0):
            pf, lf, _ = dg.style_sequence(sid, r.panels, 3, amt)
            F = dg.solid_faces(r.panels, 3, pf, lf, bend=0.75, bend_k=None, bend_len=True)
            txt = repr([(f[0], f[1], [tuple(round(c, 5) for c in q) for q in f[2]], f[3]) for f in F])
            res[f"{sid}{len(fl)}/{amt}/faces"] = hashlib.sha256(txt.encode()).hexdigest()[:16]
    for sid in ("rsc", "telescope"):                       # the drawing sheet straight from the API
        sp = dg.Spec(150, 100, 60, 3)
        r = dg.generate(dg.STYLE_BY_ID[sid], sp)
        res[sid + "/drawing"] = hashlib.sha256(DATE.sub(b"", dg.drawing_pdf(r, sp))).hexdigest()[:16]
        for kind in ("stl", "3mf"):
            data, _m = dg.model_export(r, sp, kind)
            if kind == "3mf":
                import io
                z = zipfile.ZipFile(io.BytesIO(data))
                data = b"".join(n.encode() + z.read(n) for n in sorted(z.namelist()))
            res[sid + "/" + kind] = hashlib.sha256(data).hexdigest()[:16]
    return res


def collect(module):
    out = {"cli": {}, "api": api_hashes(module)}
    for case in CASES:
        out["cli"][" ".join([case[0], case[1]] + case[2])] = run_cli(module, case)
    return out


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    module = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.join(ROOT, "dieline_generator.py")
    got = collect(module)
    if mode == "record":
        with open(GOLD, "w") as fh:
            json.dump(got, fh, indent=1, sort_keys=True)
        print("recorded", len(got["cli"]), "cli cases and", len(got["api"]), "api hashes")
        return 0
    want = json.load(open(GOLD))
    bad = []
    for k in want["cli"]:
        for f, v in want["cli"][k].items():
            if got["cli"].get(k, {}).get(f) != v:
                bad.append((k, f))
    for k, v in want["api"].items():
        if got["api"].get(k) != v:
            bad.append(("api", k))
    print("MISMATCH" if bad else "IDENTICAL", len(bad))
    for b in bad[:30]:
        print("  ", b)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
