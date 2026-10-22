# =============================================================================
# Issues / results
# =============================================================================
class Issue:
    def __init__(self, level, msg, fields=()):
        self.level, self.msg, self.fields = level, msg, tuple(fields)

    def __repr__(self):
        return f"{self.level.upper()}: {self.msg}"


class Spec:
    def __init__(self, L, W, H, t, mode="inner", units="mm", opts=None, folds=True, flags=None,
                 sheet=(None, None), kerf=0.0, perf=False, look=None, features=(), perf_dash=5.0, perf_tie=2.0, tol=None):
        self.material, self.bend_r, self.bend_k = BEND_DEFAULT, None, None   # bend model: preset, inside radius (user units), K
        self.tol = tol or {}      # drawing tolerance overrides in mm, e.g. {"panel": 1.0}; missing = automatic
        self.perf_dash, self.perf_tie = perf_dash, perf_tie   # dashed-fold cut length and uncut bridge, in mm
        self.features = list(features)   # Feature objects (windows, info / logo zones)
        self.look = look          # {cut_color, fold_color, cut_weight, fold_weight}; None = defaults
        self.flute = None        # corrugated flute direction on the flat sheet: "v" (along the sheet's y axis), "h" (x) or None
        self.perf = perf         # draw fold lines as dashed cuts (perforation) instead of scored lines
        self.kerf = kerf         # laser beam width in the user's units; 0 = no compensation
        self.L, self.W, self.H, self.t, self.mode, self.units = L, W, H, t, mode, units
        self.opts = opts or {}
        self.folds = folds
        self.flags = flags or {}
        self.sheet = sheet


class Ctx:
    """Everything a style needs while building (all lengths in the user's units)."""

    def __init__(self, spec, Lc, Wc, Hc):
        self.spec = spec
        self.Lc, self.Wc, self.Hc, self.t = Lc, Wc, Hc, spec.t
        self.mm = 25.4 if spec.units == "in" else 1.0       # millimetres per user unit
        self.o = spec.opts
        self.folds = spec.folds
        self.flags = spec.flags
        self.mode = spec.mode

    def mm_(self, x_mm):
        """A length given in millimetres, expressed in the user's units."""
        return x_mm / self.mm


class Result:
    def __init__(self, style, spec):
        self.style, self.spec = style, spec
        self.issues = []
        self.drawing = None
        self.look = None
        self.nominal = None
        self.panels = None
        self.info = {}

    @property
    def errors(self):
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self):
        return [i for i in self.issues if i.level == "warn"]

    @property
    def ok(self):
        return not self.errors

    def notes(self):
        return [f"{'NOTE' if i.level == 'warn' else i.level.upper()}: {i.msg}"
                for i in self.issues if i.level in ("warn", "error")]


def fmt(v, nd=2):
    s = f"{v:.{nd}f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


