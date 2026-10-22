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


