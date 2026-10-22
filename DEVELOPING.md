# Developing BoxForge

`dieline_generator.py` is the single file you run and ship. **Do not edit it** - it is generated.
Edit the parts in `src/` and rebuild:

    python3 build.py            # src/NNN_*.py  ->  dieline_generator.py
    python3 build.py --check    # exit 1 if the bundle is stale
    python3 tests/run.py        # bundle check + golden output + smoke/extension (+ GUI when DISPLAY is set)

The parts are concatenated in filename order into **one namespace** (they are not imported), so a name defined in
an earlier part is visible to every later one. Keep the number prefixes in dependency order.

## Layout

| part | what lives there |
|---|---|
| 000 header | imports |
| 005 support | version, per-user folder, error log, saved settings, project files, console handling, DPI awareness, app icon |
| 010 core | geometry helpers, `Panel`, drawing primitives |
| 020 kerf, 030 results | kerf offsetting, `Result` / `Issue` |
| 040 style base | `Style` hooks and the style registry |
| 041-046 styles | one file per box style (panels, class, dimensions, fold sequence): 043 diagonal X insert, 044 cross / grid divider, 046 slot-fit test sheet |
| 050 generate | `generate(style, spec)` and `default_spec` |
| 060 export | file writers and the **export registry** |
| 070-090 | SVG import, windows/zones, tolerances |
| 100 bend, 110 fold model, 115 fold insert, 116 fold grid | folded-solid maths and per-style fold chains; 115 is the insert's own chain, 116 the grid dividers' (flat slabs that move and slide together) |
| 120 drawing | engineering sheet and the **drawing-block registry** |
| 130 mesh | STL / 3MF |
| 140-180 gui_* | theme, widgets, home, editor, app |
| 190 cli | command line |

## Safety net

`tests/golden.py` hashes the output of the CLI (every format, drawing, STL/3MF), the folded-solid faces and the
3-D draw order for a matrix of styles and options. A refactor that must not change output is correct only when
`python3 tests/golden.py check` prints `IDENTICAL`. When output is *meant* to change, run
`python3 tests/golden.py record` and review the diff of `tests/golden.json`.

`tests/order_check.py` renders the folded solid with the painter's order and with an exact depth test and counts
see-through pixels (needs numpy + Pillow). Run it after touching `plate_order`, `solid_faces` or a style's fold chain.

## Add a box style

1. Create `src/04N_style_name.py` (pick a free number between 040 and 050).
2. Write the panel builder (`Panel(name, poly, parent, hinge, angle, role)` chain) and a `Style` subclass:
   - required: `id`, `name`, `code`, `blurb`, `defaults`, `resolve`, `check`, `build`, `dimensions`, `fold_sequence`
   - optional hooks: `options`, `toggles`, `size_rows`, `drawing_notes`, `tol_keys`, `rounded_folds`, `step_amount`,
     `step_text`, `step_hide`, `anchor_panel`, `closing_report` (see the comments in `040_style_base.py`)
3. End the file with `register_style(MyStyle())` (`listed=False` registers it for `--style` but hides it from the menu).
4. `python3 build.py && python3 tests/run.py`. Add the style to `CASES` in `tests/golden.py` and re-record.

The menu, `--style`, drawing sheet, fold-steps page and 3-D preview all pick it up from the registry.
`tests/smoke.py` runs every registered style through every export and drawing block automatically.

## Add an export format

In `060_export.py` write `to_xxx(d, units, notes, ...)` and register it once:

    register_export("xyz", "XYZ", lambda d, units, notes, gcode, look: to_xyz(d, units, notes),
                    flag="xyz", weights=False)   # weights=True if cut/fold line weights apply

The editor's export row, the `--xyz PATH` option and `render_export()` read the registry.

## Add a drawing block or page

In `120_drawing.py`:

    register_drawing_block("key", "Label in the export dialog", cli="name-for---dwg-off", page=my_page, note="help text")

- `page=None`: a block drawn on the main sheet - add it to `_draw_blocks` (and `sheet_layout` if it needs space).
- `page=fn(res, spec, W, H, blocks)`: an extra PDF page; return what `fold_steps_page` returns.

The export dialog switch, `--dwg-off` and the default options come from the registry. Title-block text fields are
`DRAWING_FIELDS`.

## Diagonal X insert

`Insert` (`043_style_insert.py`) is one strip of three panels: `ib` (the wall panel, the root), and the blades `ia` and
`ic`, folded at the wall panel's two ends (135 degrees in a square box; 180 degrees minus `atan(length / width)` in a rectangular one, at most 3 : 1). Two blades run corner to corner and cross in half-lap slots.
Every size comes from the box's **inside** space `Sw` x `Sl` (`insert_geometry(Sw, t, Sl)`, closed form; the wall panel goes on the shorter wall and the slots widen by `1 / sin(2 phi)` because the blades cross at an angle); the insert is deliberately not a copy
of any hand-made strip. It sizes itself with a fixed nominal bend (`ri = 0.25 t`, `K = 0.40`) so the cut sizes do not
move with the preview's bend radius.

- `square = True` (not used by any style now) would mark a style that only takes a square box; the editor then mirrors Width from Length.
- The Slotted Box has the toggle `insert`. `RSC.build` appends `insert_panels(...)` below the box, centred, and
  `dimensions`, `size_rows`, `table_rows`, `view_amount` and `drawing_notes` change when it is on. The editor drops a
  toggle that `Style.toggle_hint` says the sizes cannot use (a box longer than 3 : 1) and shows the reason. `toggle_conflict` makes the diagonal insert and the cross divider exclusive.
- The CLI turns every style toggle into a flag (`--insert`).
- `Panel.fold_segs` limits the drawn crease to the hinge tabs (the fold slits are through-cuts); `Panel.meta` carries the
  insert's numbers to the fold model.
- `115_fold_insert.py` builds the folded model: flat slabs plus true arc strips (`_ins_bend` keeps the neutral length
  while the turn varies). Each blade is cut into three convex plates, so `plate_order` can sort them. Names with `~`
  (`ia~0`, `ia~t0.bend`) belong to the panel before the `~`; `~` names draw smooth.
- Fold order with the insert on (`rsc_sequence`): walls, glue flap and the insert's folds together (0 - 0.34, insert held above the open box), then the insert is lowered (0.34 - 0.58, `prog_of.insert_hover` 1 -> 0, applied in `_solid_with_insert`), then the shorter flaps (to 0.79) and the longer flaps. The fold-steps page then has four views (`Style.step_views` / `stage_amount`).
- Inside a box the insert is centred (`_insert_origin` in `100_bend.py`) and stands one board above the wall bottom.
- `Style` hooks added for it: `square`, `toggle_hint`, `table_rows`, `view_amount`, `view_title`, `table_title`,
  `steps_note`, `view_caption`, `bend_notes`, `tol_note`. Override only what differs.
- Tests: golden cases (`insert`, `rsc --insert`), `order_check` (insert, box + insert), `gui_smoke` (square mirror, toggle).

## Packaging as an app (PyInstaller)

Build from the single file, as a windowed app, with the icon from `python tools/make_icon.py` (writes `assets/boxforge.ico` and
`.png` from the same drawing the window uses):

    pyinstaller --noconfirm --windowed --name BoxForge --icon assets/boxforge.ico dieline_generator.py

Not built or run from here (this workspace is Linux): try the result on Windows and macOS before release.

- **Settings and log** live in the user's folder (`%APPDATA%\BoxForge`, `~/Library/Application Support/BoxForge`,
  `~/.config/boxforge`): `settings.json` (sizes per box, line colours and weights, G-code, drawing options) and
  `boxforge.log`. Saved on close and when going back to the home screen; read at start-up with every value checked, so a
  damaged file is ignored. `BOXFORGE_HOME` overrides the folder (the tests use it). About -> "Reset saved settings" clears it.
- **Errors**: `App.report_callback_exception` writes a traceback to the log and shows one dialog (at most one per 3 s).
  Tests set `app.error_hook` to catch them instead.
- **Command line from a windowed app**: `main()` calls `attach_console()` (Windows: attach to the parent console, so the
  output shows when started from a terminal; the prompt may return before the output ends). `safe_streams()` makes
  `print` safe when there is no console at all. `BoxForge.exe --version` prints the version.
- **High-DPI**: `enable_dpi_awareness()` (Windows) runs before the window exists; `init_scale()` (`140_gui_theme.py`) reads the
  screen's DPI (`BOXFORGE_SCALE=1.5` forces a scale, `BOXFORGE_DPI=0` turns awareness off, macOS never scales). Above 120 %
  it patches Tk so every pixel option (padding, canvas / frame sizes, wrap lengths) and every pack / grid / place pixel value
  is multiplied by `SCALE`; hand-drawn coordinates and window sizes call `S()` themselves. At 100 % nothing is patched.
  Checked at 150 % and 200 % on a virtual screen; not on a real Windows machine.
- **Project files** (`.boxforge`, JSON; `project_to_text` / `project_from_text` in `005_support.py`): one box's whole editor
  state including windows, zones and artwork. Everything read is type-checked and unknown keys dropped; a newer `format` is
  refused. Ctrl/Cmd+S, Ctrl/Cmd+O, Save button, "Open project..." and a recent list (5 shown, 8 kept) on the home screen.
- **macOS**: `tools/make_icon.py` also writes `assets/boxforge.icns`; `App._mac_menu` builds the menu bar (About, File) and
  hooks Quit; Cmd shortcuts are bound next to the Ctrl ones.
- Version: `__version__` in `005_support.py`.

## Flute direction

`Spec.flute` is `None`, `"v"` (flutes along the flat sheet's y axis) or `"h"` (x). It never touches the cut files. It
reaches two places: `solid_faces(..., flute=)` adds faces of kind `"flute"` (two points, on a panel's outside face) that
the editor's 3-D view draws as faint lines, and `_flute_marker` in `120_drawing.py` sets the FLUTE DIRECTION label and
arrow on the dieline. A new style gets the lines for free as long as its slabs go through `_fm_slab` with the right `su`
(the sheet axis the slab's u runs along) or through the generic `solid_faces` path.

## Resizable layout

The editor is three nested `make_paned(...)` containers (`140_gui_theme.py`): sidebar | views, dieline | 3-D preview, and
options / (checks + export) inside the sidebar. Each pane has a `minsize`, so a divider can never close a pane, and a
`tk.PanedWindow` cannot tear panes out into their own window. Divider positions are kept in `App.layout` for the session.

## Rules the code relies on

- Sheet plane = outside face; board thickness extends +t inward.
- Never change how dimensions are derived from the user's inputs without saying so; golden hashes catch it.
- Preview-only changes (draw order, speed) must leave `golden.py check` at IDENTICAL.


## Cross / grid divider and the slot-fit test

- `Grid` (`044_style_grid.py`): lengthwise dividers (slots from the top) and crosswise ones (slots from the bottom) that
  slide together in a grid of equal compartments (`grid_geometry`). `count_keys = ("nl", "nw")` lets a count be 0. The Slotted
  Box adds one with the toggle `insert_grid` and the options `gnl` / `gnw` (`RSC.resolve` calls `Grid.resolve(c, keys=...)`).
- `116_fold_grid.py` moves the flat slabs (phases: out, down, slide and turn, lower); each divider is drawn as strips and
  columns (`grid_pieces`) so every piece lies on one side of each crossing divider and `plate_order` stays exact.
- `FitTest` (`046_style_fit.py`): a key plate and N plates with slots growing from the board thickness; the number of notches
  on a plate's bottom edge is its number. It has no folds.
- Tests: `order_check` cases `grid 1+1`, `grid 2+3`, `rsc+grid 2+3`, rectangular inserts, `fit`; golden CLI and API cases
  for each; `gui_smoke` covers the exclusive switches, counts, projects and the Mac menu.

## v0.2.1 audit fixes
- Telescope lid length uses `Lc + 4t + clr` (corner flaps sit inside the lid end walls); dimension extension lines avoid flap hinges.
- RSC outside height = `Hc + 2t`; glue-flap limits; horizontal-flute warning; too-long diagonal insert is dropped with a warning.
- Styles gained `view_heading`, `option_enabled`, `toggle_conflict`, `zero_ok`, `auto_tol` hooks (see `040_style_base.py`).
- Bend page honours the job's units; 10 m size ceiling; comma/mixed-number parsing fixed.
- GUI: home cards scroll, scaling at 125-200%, unsaved-project prompts, wrapped option labels.
- Exports: SVG chains segments into closed paths, DXF carries a units comment, G-code header notes GRBL `$32=1`.
- Declined: #3/#29 (convention calls kept as-is), #7 beyond a comment (DXF R12 has no reliable unit flag), #11 (flap width is already < wall height, so no relief needed).

## Dieline labels and click-to-edit dimensions (v0.2.6)
- The live dieline view shows panel labels (`Style.panel_label`) and the same dimension callouts as the drawing sheet.
- `Style.dim_field(dm, res, spec)` says which sidebar box a callout controls: `(key, value_now[, scale])`. `None` = derived.
  The edit rule is `box_new = box_now + (typed - callout_value) * scale`, so crease-to-crease callouts still work in
  Inner / Outer / Maker mode. `tests/smoke.py` regenerates after every such edit and checks the callout reads the typed value.
