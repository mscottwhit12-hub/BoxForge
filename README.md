# BoxForge

Dieline generator for cardboard and laser-cut boxes. Pick a box style, type the size and board thickness, and get a
dimensioned dieline you can export for a laser cutter, die maker or plotter. No dependencies: it is plain Python with
tkinter.

**Download:** grab `BoxForge-windows.zip` or `BoxForge-macos.zip` from the [latest release](../../releases/latest).
Windows: unzip and run `BoxForge.exe`. macOS: unzip, then right-click `BoxForge.app` and choose Open the first time
(the app is not signed, so macOS asks before running it).

## What it does
- **Styles:** Slotted Box (RSC), Lid & Base, Diagonal Insert, Cross / grid divider, Slot-fit test coupon.
- **Live preview:** flat dieline with panel labels and dimension callouts (click a callout to change its size), plus a
  3-D fold preview with a fold slider.
- **Exports:** SVG, DXF, PDF, EPS, HPGL, G-code, an engineering drawing PDF (tolerances, size table, fold steps,
  bend data) and 3D models (3MF / STL).
- **Also:** kerf compensation, windows and logo zones, dashed folds, inch and mm, project files (`.boxforge`).

## Run from source
```
python dieline_generator.py            # opens the window
python dieline_generator.py --help     # command line
```

## Develop
The app is built from the parts in `src/` into the single file `dieline_generator.py`. Edit `src/`, then run
`python build.py`; never edit the bundle. See `DEVELOPING.md` and `tests/` (`python tests/run.py`).

## Releases
Pushing a tag that starts with `v` (for example `v0.2.6`) makes GitHub build the Windows and macOS apps and attach them
to a release (`.github/workflows/release.yml`).

MIT licence.
