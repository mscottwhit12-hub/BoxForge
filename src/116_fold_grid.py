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
