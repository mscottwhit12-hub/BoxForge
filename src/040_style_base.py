# =============================================================================
# Styles: base class, registry
# =============================================================================
class Style:
    id = name = code = blurb = ""
    status = "standard"            # calibrated | standard | experimental
    defaults = dict(L=150.0, W=100.0, H=120.0, t=2.0)
    options = []                   # [(key, label)]  blank = automatic
    toggles = []                   # [(key, label, default)]
    count_keys = ()                # keys of `options` that are whole numbers (a number of parts), shown with the sizes, 0 allowed
    ratio_dims = ("L", "W", "H")
    flat_parts = False             # no folds at all: the bend-data page is left out
    square = False                 # only a square footprint: the window ties Width to Length
    height_label = "Height"
    view_up = "y"                  # which folded axis points up in the 3-D preview
    mode_help = {
        "inner": "Inside of the finished box (what fits in it).",
        "outer": "Outside of the finished box.",
        "manufacturer": "Centre-of-crease (fold-to-fold) panel sizes.",
    }

    # fold-to-fold (crease centre) sizes from the user's numbers
    def crease(self, L, W, H, t, mode):
        k = {"inner": t, "outer": -t, "manufacturer": 0.0}[mode]
        return L + k, W + k, H + k

    # inside dimensions from crease sizes
    def crease_for(self, spec):
        """Crease-to-crease sizes for a whole job; styles whose sizes depend on an option override this."""
        return self.crease(spec.L, spec.W, spec.H, spec.t, spec.mode)

    def inner_for(self, spec, Lc, Wc, Hc):
        return self.inner(Lc, Wc, Hc, spec.t)

    def inner(self, Lc, Wc, Hc, t):
        return Lc - t, Wc - t, Hc - t

    def resolve(self, c):
        return {}

    def check(self, c, r, issues):
        pass

    def build(self, c, r):
        raise NotImplementedError
    # --- hooks the 3-D preview, the drawing sheet and the window read; override them in a new style ---------------
    rounded_folds = False          # has a chain model for the rounded-fold preview (see fold_rsc / fold_tray)
    tol_keys = ("panel", "flap", "overall_len", "overall_h", "box")   # drawing tolerances this style uses
    draw_sub = ""                  # drawing sheet sub-title (falls back to `code`)
    draw_cap = ""                  # tag in the drawing sheet caption
    step_text = {}                 # fold-steps captions by stage: flat / partial / folded
    step_amount = None             # slider position of the "partly folded" step (None = SEQ_WALLS)
    anchor_panel = None            # the solid preview needs this panel to exist (None = no requirement)
    closing_report = False         # the bend page also reports how the chain model closes (slotted box)

    def dim_field(self, dm, res, spec):
        """Which sidebar box a dimension record `dm` (see dimensions) controls, as (key, value now) so that the dimension
        can be edited on the drawing: typing a new value changes the box by the same amount. `value now` is None for L, W,
        H and t (their current box text is used). None = the dimension is not a single box (a sum or a derived size)."""
        return None

    _PANEL_NAMES = {"p": "WALL ", "glue": "GLUE FLAP", "top": "TOP FLAP ", "bot": "BOTTOM FLAP ", "ib": "INSERT BLADE 1",
                    "ia": "INSERT WALL", "ic": "INSERT BLADE 2", "gl": "DIVIDER ALONG ", "gw": "DIVIDER ACROSS ",
                    "key": "KEY PLATE", "s": "SLOT PLATE "}

    def panel_label(self, name):
        """Short readable name of the panel `name`, for the labels on the dieline."""
        pre = ""
        if name[:2] in ("b_", "l_"):                       # lid & base: two trays on one sheet
            pre, name = ("BASE " if name[0] == "b" else "LID "), name[2:]
            names = {"bottom": "FLOOR" if pre == "BASE " else "TOP", "front": "FRONT WALL", "back": "BACK WALL",
                     "left": "LEFT WALL", "right": "RIGHT WALL", "cfl": "CORNER FLAP", "cfr": "CORNER FLAP",
                     "cbl": "CORNER FLAP", "cbr": "CORNER FLAP"}
            return pre + names.get(name, name.upper())
        for stem in ("glue", "key", "top", "bot", "ib", "ia", "ic", "gl", "gw", "p", "s"):
            if name.startswith(stem) and (name == stem or name[len(stem):].isdigit()):
                return self._PANEL_NAMES[stem] + name[len(stem):]
        return name.upper().replace("_", " ")

    def dimensions(self, res, spec):
        """Dimension records for the flat-blank drawing (see rsc_dimensions for the record format)."""
        raise NotImplementedError

    def size_rows(self, c):
        """Rows [(label, value)] of the drawing's size table. `c` carries Li/Wi/Hi (inside), Lc/Wc/Hc (crease),
        t, a (resolved options), tri / tol / fnum (formatters), flat and units."""
        return [("Inside L × W × H", c.tri(c.Li, c.Wi, c.Hi) + c.tol("box")),
                ("Outside L × W × H", c.tri(c.Lc + c.t, c.Wc + c.t, c.Hc + c.t) + c.tol("box")),
                ("Crease L × W × H", c.tri(c.Lc, c.Wc, c.Hc)), c.flat,
                ("Board thickness", c.fnum(c.t, c.units)), ("Units", c.units)]

    def drawing_notes(self, res, units):
        """Extra note lines for the drawing sheet (fold order, style specifics)."""
        return []

    def option_enabled(self, key, flags):
        """False when the option `key` only matters for a switch that is off (its box is greyed out)."""
        return True

    def toggle_conflict(self, key, on):
        """Switches to turn off when switch `key` is turned on (none by default)."""
        return []

    def toggle_hint(self, key, vals):
        """None when the on/off option `key` can be used with the sizes typed so far (`vals`: parsed L, W, H, t; None
        for one that is not a number), else a short reason shown under it. The option is then left out."""
        return None

    def table_rows(self, res):
        """Rows in the drawing's size table (the sheet makes room for more than the usual nine)."""
        return 9

    def step_views(self, res):
        """The fold-steps page's views: [(stage, heading, caption)]. Stages other than flat / partial / folded need
        `stage_amount`."""
        return list(STEP_VIEWS)

    def stage_amount(self, stage):
        """Slider position (0..1) of a custom fold-steps stage, or None."""
        return None

    def toggle_view(self, key):
        """Slider position (0..1) to show when the switch `key` is turned on, or None to leave the preview alone."""
        return None

    def view_amount(self, res):
        """Slider position (0..1) the drawing's folded 3-D view is shown at; 1 = fully folded."""
        return 1.0

    def view_heading(self, res):
        """Header of the drawing's folded 3-D view (a style can change it with what is shown)."""
        return self.view_title

    view_title = "FOLDED BOX (NOT TO SCALE)"       # drawing sheet: the folded 3-D view's header
    table_title = "BOX SIZES"                       # ... and the size table's
    steps_note = ("(not to scale; board drawn at full thickness, so the closed box can read up to one board "
                  "larger than the size table)")   # fold steps page sub-title tail

    def view_caption(self, res, units):
        """Line under the folded 3-D view on the drawing sheet."""
        Li, Wi, Hi = res.info["inner"]
        return f"{_fnum(Li, units)} × {_fnum(Wi, units)} × {_fnum(Hi, units)} {units} inside"

    def bend_notes(self, rep):
        """Replacement for the first two notes on the bend data page (None = the slotted-box wording about the
        deduction its crease sizes already contain)."""
        return None

    def tol_note(self, f, units):
        """Tolerance sentence for the drawing's notes (`f` formats a tolerance key in the drawing's units); None =
        the standard slotted-box wording chosen by `tol_keys`."""
        return None

    def fold_sequence(self, panels, t, amount):
        """(prog_of, lift_of, layer) for the solid preview at slider position `amount` (0..1)."""
        raise NotImplementedError



def _auto(c, key, default):
    v = c.o.get(key)
    return default if v is None else v


def half_lap_tol(res, tv):
    """Tolerance (mm) for a half-lap slot dimension: the style's own slot tolerance on its own sheet, and a fixed
    +/-0.1 when the part rides on a slotted-box sheet, whose flap-slot rule (+/-1.5) is far too loose for a half-lap."""
    return 0.1 if res.style.id == "rsc" else tv["slot"]


STYLES = []                        # styles listed in the menu, in menu order
STYLE_BY_ID = {}                   # every registered style, listed or not


def register_style(style, listed=True):
    """Add a style to the app. It then shows up in the menu (when `listed`) and in --style on the command line."""
    STYLE_BY_ID[style.id] = style
    if listed:
        STYLES.append(style)
    return style
