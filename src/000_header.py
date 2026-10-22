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

