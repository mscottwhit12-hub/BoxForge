#!/usr/bin/env python3
"""Run everything:  python tests/run.py   (set DISPLAY, e.g. Xvfb, to include the GUI test)."""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
steps = [("bundle up to date", [sys.executable, os.path.join(ROOT, "build.py"), "--check"]),
         ("golden output", [sys.executable, os.path.join(HERE, "golden.py"), "check"]),
         ("smoke + extension", [sys.executable, os.path.join(HERE, "smoke.py")]),
         ("3-D see-through", [sys.executable, os.path.join(HERE, "order_check.py")])]
try:
    import tkinter                              # noqa: F401
except ImportError:
    tkinter = None
if os.environ.get("DISPLAY") and tkinter:
    steps.append(("GUI", [sys.executable, os.path.join(HERE, "gui_smoke.py")]))
bad = 0
for name, cmd in steps:
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(("ok    " if r.returncode == 0 else "FAILED"), name)
    if r.returncode:
        bad += 1
        print((r.stdout + r.stderr)[-1500:])
sys.exit(1 if bad else 0)
