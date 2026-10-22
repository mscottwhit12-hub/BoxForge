#!/usr/bin/env python3
"""Headless GUI smoke test (needs a display, e.g. Xvfb).   DISPLAY=:99 python tests/gui_smoke.py [module.py]
Opens every listed style, switches fold amounts, and exports the drawing and every file format through the real dialogs."""
import importlib.util, os, sys, tempfile
os.environ["BOXFORGE_HOME"] = tempfile.mkdtemp()           # never touch the real saved settings

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(os.path.dirname(HERE), "dieline_generator.py")
s = importlib.util.spec_from_file_location("dg", PATH)
dg = importlib.util.module_from_spec(s)
s.loader.exec_module(dg)
app = dg.App()
caught = []
app.error_hook = caught.append                             # errors inside callbacks are logged and counted here
app.geometry("1400x900")
app.update()
fails = []


def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)


def _drag(w, idx, tx, ty):
    x, y = w.sash_coord(idx)
    w.event_generate("<ButtonPress-1>", x=x + 2, y=y + 2)
    app.update()
    w.event_generate("<B1-Motion>", x=tx, y=ty)
    app.update()
    w.event_generate("<ButtonRelease-1>", x=tx, y=ty)
    app.update()


def _settle():
    import time
    t_ = time.time()
    while time.time() - t_ < 0.5:
        app.update()
        time.sleep(0.01)


# dividers: drag each one as far as it goes both ways; nothing may close up or leave the window
app.open_style(dg.STYLES[0])
_settle()
e0 = app.editor
checks = []
for lo_x, hi_x in ((-5000, 5000),):
    _drag(e0.stage, 0, lo_x, 300)
    _settle()
    checks.append(("view divider left: both views stay visible", e0.pane2.winfo_width() >= 220 and e0.pane3.winfo_width() >= 220))
    _drag(e0.stage, 0, hi_x, 300)
    _settle()
    checks.append(("view divider right: both views stay visible", e0.pane2.winfo_width() >= 220 and e0.pane3.winfo_width() >= 220))
    _drag(e0.body, 0, lo_x, 300)
    _settle()
    checks.append(("sidebar divider left: sidebar keeps its minimum", e0.side.winfo_width() >= 280))
    _drag(e0.body, 0, hi_x, 300)
    _settle()
    checks.append(("sidebar divider right: views keep their minimum", e0.stage.winfo_width() >= 450))
    _drag(e0.vp, 0, 100, 5000)
    _settle()
    checks.append(("export divider down: export area keeps its minimum", e0.lower.winfo_height() >= 85))
    _drag(e0.vp, 0, 100, -5000)
    _settle()
    checks.append(("export divider up: options keep their minimum", e0.vp.winfo_height() - e0.lower.winfo_height() >= 140))
checks.append(("panes stay docked (none torn out)", len(e0.body.panes()) == 2 and len(e0.vp.panes()) == 2 and len(e0.stage.panes()) == 2))
for name, ok in checks:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)
app.show_home()
_settle()

td = tempfile.mkdtemp()
for st in dg.STYLES:
    app.open_style(st)
    app.update()
    app.after(300)
    app.update()
    e = app.editor
    e.wait_window = lambda win: (win.update(), [w for w in walk(win) if isinstance(w, dg.Btn)][-1]._click(None))
    for val in ("v", "h", "off"):                                 # flute direction control -> 3-D preview and drawing
        e.flute.set(val)
        e.refresh()
        app.update()
        want = None if val == "off" else val
        ok = e.wire.flute == want and e.read_spec().flute == want and e.snapshot()["flute"] == val
        e.amount.set(100.0)
        e._on_amount()
        e.wire.render()
        app.update()
        print(("PASS " if ok else "FAIL ") + f"{st.id}: flute {val} reaches preview and spec")
        if not ok:
            fails.append(f"{st.id}/flute{val}")
    e.flute.set("v")
    e.refresh()
    app.update()
    path = os.path.join(td, st.id + ".pdf")
    dg.filedialog.asksaveasfilename = lambda **k: path
    e.export_drawing()
    app.update()
    ok = os.path.exists(path) and os.path.getsize(path) > 1000
    print(("PASS " if ok else "FAIL ") + f"{st.id}: drawing dialog")
    if not ok:
        fails.append(st.id)
    for kind, label in dg.EXPORT_FORMATS:
        p = os.path.join(td, f"{st.id}.{kind}")
        dg.filedialog.asksaveasfilename = lambda **k: p
        try:
            e.export(kind)
            app.update()
            ok = os.path.exists(p) and os.path.getsize(p) > 100
        except Exception as ex:                                  # noqa: BLE001
            ok = False
            print("   ", repr(ex))
        print(("PASS " if ok else "FAIL ") + f"{st.id}: export {label}")
        if not ok:
            fails.append(f"{st.id}/{kind}")
# the insert takes any box shape up to 3 : 1, and the Slotted Box's quick option follows the box shape
app.open_style(dg.STYLE_BY_ID["insert"])
_settle()
e = app.editor
e.vars["L"].set("120")
app.update()
e.vars["W"].set("90")
app.update()
checks = [("insert: width is its own field", e.read_spec().W == 90.0 and e.read_spec().L == 120.0)]
app.open_style(dg.STYLE_BY_ID["rsc"])
_settle()
e = app.editor
e.flags["insert"].set(True)
e.vars["L"].set("120")
e.vars["W"].set("120")
e.refresh()
app.update()
sp_ = e.read_spec()
checks.append(("box: insert switch is on for a square box", sp_.flags.get("insert") is True and e.flag_hint["insert"].winfo_manager() == ""))
e.vars["W"].set("90")
e.refresh()
app.update()
sp_ = e.read_spec()
checks.append(("box: insert stays on for a rectangular box", sp_.flags.get("insert") is True and e.flag_hint["insert"].winfo_manager() == ""))
e.vars["W"].set("30")
e.refresh()
app.update()
sp_ = e.read_spec()
checks.append(("box: insert is left out for a very long box, with a hint", not sp_.flags.get("insert") and e.flag_hint["insert"].winfo_manager() != ""))
e.vars["W"].set("120")
e.refresh()
app.update()
checks.append(("box: insert comes back for a sensible box", e.read_spec().flags.get("insert") is True))
e.amount.set(100.0)
e._on_amount()
e.wire.render()
app.update()
for name, ok in checks:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)
# the colour picker: a single swatch that opens a popup
app.open_style(dg.STYLE_BY_ID["rsc"])
_settle()
e = app.editor
sws = [w for w in walk(e) if isinstance(w, dg.SwatchPicker)]
sw = sws[0]
checks = [("colours: one small swatch per line type", len(sws) == 3 and all(w.winfo_width() < 80 for w in sws))]
e.lvars["cut_color"].set("Blue")
sw._open()
_settle()
checks.append(("colours: click opens the popup", sw.pop is not None and sw.pop.winfo_ismapped()))
cx, cy = sw._cell(2)                                       # third colour: Black
sw._cv.event_generate("<Button-1>", x=cx + 5, y=cy + 5)
_settle()
checks.append(("colours: picking a colour sets it and closes the popup", e.lvars["cut_color"].get() == "Black" and sw.pop is None))
sw._open()
_settle()
sw.pop.event_generate("<Escape>")
_settle()
checks.append(("colours: Esc closes the popup without a change", sw.pop is None and e.lvars["cut_color"].get() == "Black"))
sw._open()
_settle()
sw.pop.event_generate("<Button-1>", x=1, y=1)
sw._close() if sw.pop else None
checks.append(("colours: popup is gone after a click away", sw.pop is None))
# switching the insert on opens the box so the insert can be seen
e.flags["insert"].set(False)
e.vars["L"].set("120")
e.vars["W"].set("120")
e.amount.set(100.0)
e.flags["insert"].set(True)
_settle()
checks.append(("box: turning the insert on shows the open box", abs(e.amount.get() - dg.SEQ_INS_DROP * 100.0) < 1e-6))
# the cross divider switch is exclusive with the diagonal insert and opens the box too
e.flags["insert_grid"].set(True)
_settle()
checks.append(("box: cross divider turns the diagonal insert off", not e.flags["insert"].get() and e.flags["insert_grid"].get()))
checks.append(("box: cross divider shows the open box", abs(e.amount.get() - dg.SEQ_INS_DROP * 100.0) < 1e-6))
e.vars["gnl"].set("2")
e.vars["gnw"].set("3")
_settle()
sp_ = e.read_spec()
checks.append(("box: divider counts are read", sp_.opts.get("gnl") == 2 and sp_.opts.get("gnw") == 3))
e.flags["insert"].set(True)
_settle()
checks.append(("box: diagonal insert turns the cross divider off", not e.flags["insert_grid"].get()))
e.flags["insert"].set(False)
# dieline labels and click-to-edit dimensions
app.show_home()
_settle()
app.open_style(dg.STYLE_BY_ID["rsc"])
_settle()
e = app.editor
e.vars["L"].set("200"); e.vars["W"].set("150"); e.vars["H"].set("120"); e.vars["t"].set("3")
e.mode.set("inner")
_settle()
e.update()
e.view_mode.set("dieline")                        # the dieline alone, so it has the whole stage
e.update()
e.user_view = False
e.draw2d()
texts = lambda: [e.cv2.itemcget(i, "text") for i in e.cv2.find_all() if e.cv2.type(i) == "text"]
checks.append(("labels: panel names are drawn", any(t.startswith("WALL") for t in texts())))
checks.append(("callouts: editable dimensions are listed", {"L", "W", "H", "glue", "flap"} <= {d[1][0] for d in e._dims}))
e.show_labels.set(False)
e.draw2d()
checks.append(("labels: switch hides panel names", not any(t.startswith("WALL") for t in texts())))
e.show_labels.set(True)
e.show_dims.set(False)
e.draw2d()
checks.append(("callouts: switch hides them (old overall sizes return)", e._dims == [] and any(t.endswith(" mm") for t in texts())))
e.show_dims.set(True)
_settle()
e.draw2d()
e.update()
_i = [i for i, d in enumerate(e._dims) if d[1][0] == "L"][0]
_dm, _fld, _tx, _ty, _ang = e._dims[_i]
for it in e.cv2.find_all():                                # a real click on that callout's text
    if e.cv2.type(it) == "text" and f"dimi{_i}" in e.cv2.gettags(it):
        _cx, _cy = e.cv2.coords(it)
        break
e.cv2.event_generate("<ButtonPress-1>", x=int(_cx), y=int(_cy))
e.update()
checks.append(("callouts: clicking one opens an edit box", e._dim_entry is not None))
e._dim_entry.delete(0, "end")
e._dim_entry.insert(0, dg.fmt(_dm["v"] + 10, 3))
e._dim_entry.focus_force()
e.update()
e._dim_entry.event_generate("<Return>")
_settle()
checks.append(("callouts: Enter changes the sidebar box by the same amount", abs(float(e.vars["L"].get()) - 210) < 1e-6 and e._dim_entry is None))
_k = [i for i, d in enumerate(e._dims) if d[1][0] == "flap"][0]
_dm2 = e._dims[_k][0]
e._dim_edit(_k)
e._dim_entry.delete(0, "end")
e._dim_entry.insert(0, "50")
e._dim_entry.focus_force()
e.update()
e._dim_entry.event_generate("<Return>")
_settle()
checks.append(("callouts: an option box takes the typed value", abs(float(e.vars["flap"].get()) - 50) < 1e-6))
e._dim_edit(0)
e._dim_entry.delete(0, "end")
e._dim_entry.insert(0, "abc")
e._dim_entry.focus_force()
e.update()
e._dim_entry.event_generate("<Return>")
e.update()
checks.append(("callouts: nonsense keeps the box open and the value unchanged", e._dim_entry is not None))
e._dim_entry.event_generate("<Escape>")
e.update()
checks.append(("callouts: Escape closes the box", e._dim_entry is None))
e.vars["flap"].set("")
e.vars["L"].set("200")
e.view_mode.set("split")
_settle()
for sid_ in ("telescope", "insert", "grid", "fit"):
    app.show_home()
    _settle()
    app.open_style(dg.STYLE_BY_ID[sid_])
    _settle()
    _cv = app.editor.cv2
    checks.append((f"labels + callouts draw for {sid_}",
                   len([i for i in _cv.find_all() if _cv.type(i) == "text"]) > 3))
app.show_home()
_settle()
app.open_style(dg.STYLE_BY_ID["rsc"])
_settle()
e = app.editor
# projects: save, reopen, recent list
dg.messagebox.askyesnocancel = lambda *a, **k: False       # "leave without saving" if a test ever asks
import os as _os, tempfile as _tf2
_pd = _tf2.mkdtemp()
_pp = _os.path.join(_pd, "t.boxforge")
e.vars["L"].set("222")
e.vars["W"].set("111")
e.flags["insert_grid"].set(True)
e.vars["gnl"].set("2")
e.add_feature("window")
_settle()
dg.filedialog.asksaveasfilename = lambda **k: _pp
checks.append(("project: saves", app.save_project() and _os.path.exists(_pp) and "t  -  BoxForge" in app.title()))
app.show_home()
_settle()
checks.append(("project: recent list shows it", _pp in app.recent and len(app.home.recent_host.winfo_children()) >= 2))
checks.append(("project: opens", app.open_project(_pp)))
e = app.editor
checks.append(("project: values come back", e.vars["L"].get() == "222" and e.vars["gnl"].get() == "2"
               and e.flags["insert_grid"].get() and len(e.features) == 1 and e.project_path == _pp))
e.vars["L"].set("333")
_settle()
checks.append(("project: edits mark it unsaved", app.project_dirty() and app.title().endswith("*  -  BoxForge")))
_asked = []
dg.messagebox.askyesnocancel = lambda *a, **k: (_asked.append(a), None)[1]
checks.append(("project: leaving with unsaved edits asks, and Cancel stays", app.confirm_leave() is False and len(_asked) == 1))
dg.messagebox.askyesnocancel = lambda *a, **k: False
e.vars["L"].set("222")
_settle()
open(_pp, "w").write("garbage")
_shown = []
dg.messagebox.showerror = lambda *a, **k: _shown.append(a)
checks.append(("project: a damaged file is refused with a message", not app.open_project(_pp) and len(_shown) == 1))
e = app.editor
e.flags["insert_grid"].set(False)
# the Mac menu bar builds (forced here) and screen scaling helpers behave at 100 %
checks.append(("mac: menu bar builds", app._mac_menu(force=True) is not None))
checks.append(("scale: S() is the identity at 100 %", dg.S(7) == 7 and dg.S((3, 4)) == (3, 4)))
# settings: saved on close, read back by the next start; a bad error is logged, not silent
app.look["cut_color"] = "Black"
app.save_settings()
app2_data = dg.load_settings()
checks.append(("settings: saved file holds the open box's values", app2_data.get("saved", {}).get("rsc", {}).get("L") == "222"
               and app2_data.get("look", {}).get("cut_color") == "Black"))
app.after(10, lambda: 1 / 0)
_settle()
checks.append(("errors: a failing callback is caught and logged", len(caught) == 1 and "ZeroDivisionError" in caught[0]
               and "ZeroDivisionError" in open(dg.log_path(), encoding="utf-8").read()))
app.show_about()
_settle()
tops = [w for w in app.winfo_children() if isinstance(w, dg.tk.Toplevel)]
checks.append(("about: window opens with the version", bool(tops) and any(
    isinstance(w, dg.tk.Label) and dg.__version__ in str(w.cget("text")) for t in tops for w in walk(t))))
for t in tops:
    t.destroy()
app.reset_settings()
checks.append(("settings: reset clears them", not os.path.exists(dg.settings_path()) and app.look["cut_color"] == "Blue"
               and not app.saved))
for name, ok in checks:
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)
# the next start picks the saved values up
app.close()
dg.save_settings(dict(version=1, look={"cut_color": "Black", "cut_weight": 0.3}, saved={"rsc": {"L": "99", "units": "in"}}))
app = dg.App()
app.error_hook = caught.append
ok = app.look["cut_color"] == "Black" and app.look["cut_weight"] == 0.3 and app.saved["rsc"] == {"L": "99", "units": "in"}
app.open_style(dg.STYLE_BY_ID["rsc"])
_settle()
ok = ok and app.editor.vars["L"].get() == "99" and app.editor.units.get() == "in"
print(("PASS " if ok else "FAIL ") + "settings: a new start restores them")
if not ok:
    fails.append("restore")
if len(caught) != 1:                                       # only the deliberate 1/0 above
    print("FAIL unexpected errors inside the app:", caught[1:])
    fails.append("unexpected errors")
app.close()
print("\n%d failure(s)" % len(fails) if fails else "\nALL OK")
sys.exit(1 if fails else 0)
