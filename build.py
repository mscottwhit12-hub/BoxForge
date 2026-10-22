#!/usr/bin/env python3
"""Bundle src/*.py (in file-name order) into the single file dieline_generator.py.

    python build.py            write dieline_generator.py
    python build.py --check    exit 1 if dieline_generator.py is not what the parts build

The parts share ONE namespace (they are concatenated, not imported), so a function in any part can call a
function in any other part, exactly as in the single file. Edit the parts, then run this."""
import glob, os, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "dieline_generator.py")


def bundle():
    parts = sorted(glob.glob(os.path.join(ROOT, "src", "[0-9][0-9][0-9]_*.py")))
    return "".join(open(p, encoding="utf-8").read() for p in parts)


if __name__ == "__main__":
    text = bundle()
    if "--check" in sys.argv:
        same = os.path.exists(OUT) and open(OUT, encoding="utf-8").read() == text
        print("up to date" if same else "dieline_generator.py is out of date: run python build.py")
        raise SystemExit(0 if same else 1)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("wrote", OUT, f"({text.count(chr(10))} lines from {len(glob.glob(os.path.join(ROOT, 'src', '*.py')))} parts)")
