# =============================================================================
# Home / menu screen
# =============================================================================
class Card(tk.Frame):
    def __init__(self, master, style, on_open):
        super().__init__(master, bg=T["card"], highlightthickness=1, highlightbackground=T["border"], cursor="hand2")
        self.style_, self.on_open = style, on_open
        self.thumb = tk.Canvas(self, width=330, height=150, bg=T["thumb"], highlightthickness=0)
        self.thumb.pack(fill="x", padx=1, pady=(1, 0))
        body = tk.Frame(self, bg=T["card"])
        body.pack(fill="x", padx=16, pady=(10, 12))
        tk.Label(body, text=style.name, font=F(14, "bold"), fg=T["text"], bg=T["card"], anchor="w").pack(fill="x")
        chips = tk.Frame(body, bg=T["card"])
        chips.pack(fill="x", pady=(6, 8))
        txt, col = STATUS_CHIP[style.status]
        if style.code:
            chip(chips, style.code, T["muted"]).pack(side="left", padx=(0, 6))
        chip(chips, txt, T[col]).pack(side="left")
        tk.Label(body, text=style.blurb, font=F(9), fg=T["muted"], bg=T["card"], wraplength=300, justify="left",
                 anchor="w").pack(fill="x")
        res = generate(style, default_spec(style))
        self.wire = Wire3D(self.thumb, style.view_up)
        self.wire.set_panels(res.panels)
        self.wire.yaw = -0.62 + (hash(style.id) % 100) / 40.0
        self._bind_all(self)

    def _bind_all(self, w):
        w.bind("<Enter>", self._enter, add="+")
        w.bind("<Leave>", self._leave, add="+")
        w.bind("<Button-1>", lambda e: self.on_open(self.style_), add="+")
        for c in w.winfo_children():
            self._bind_all(c)

    def _enter(self, e):
        self.config(highlightbackground=T["border_h"])
        self.hover = True

    def _leave(self, e):
        x, y = self.winfo_pointerxy()
        w = self.winfo_containing(x, y)
        inside = False
        while w is not None:
            if w is self:
                inside = True
                break
            w = w.master
        if not inside:
            self.config(highlightbackground=T["border"])
            self.hover = False

    hover = False


class Home(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=T["bg"])
        self.app, self.cards, self._job = app, [], None
        rail = tk.Frame(self, bg=T["rail"], width=68)
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        logo = tk.Canvas(rail, width=44, height=44, bg=T["rail"], highlightthickness=0)
        logo.pack(pady=(18, 22))
        logo.create_polygon(22, 5, 39, 14, 39, 32, 22, 41, 5, 32, 5, 14, fill=T["accent"], outline="")
        logo.create_polygon(22, 5, 39, 14, 22, 23, 5, 14, fill=mix(T["accent"], "#ffffff", 0.35), outline="")
        logo.create_line(22, 23, 22, 41, fill="#ffffff", width=1)
        if SCALE != 1.0:
            logo.scale("all", 0, 0, SCALE, SCALE)
        for glyph, label, cmd in (("⌂", "Home", None), ("ⓘ", "Limits", app.show_limits), ("?", "About", app.show_about)):
            b = tk.Label(rail, text=glyph, font=F(18), fg=T["text"] if cmd is None else T["muted"], bg=T["rail"],
                         cursor="hand2", pady=6)
            b.pack(fill="x")
            if cmd:
                b.bind("<Button-1>", lambda e, c=cmd: c())
                b.bind("<Enter>", lambda e, w=b: w.config(fg=T["text"]))
                b.bind("<Leave>", lambda e, w=b: w.config(fg=T["muted"]))
            tk.Label(rail, text=label, font=F(8), fg=T["dim"], bg=T["rail"]).pack(pady=(0, 10))

        main = tk.Frame(self, bg=T["bg"])
        main.pack(side="left", fill="both", expand=True)
        head = tk.Frame(main, bg=T["bg"])
        head.pack(fill="x", padx=40, pady=(30, 4))
        tk.Label(head, text="BoxForge", font=F(11, "bold"), fg=T["accent_h"], bg=T["bg"]).pack(anchor="w")
        tk.Label(head, text="What are you making today?", font=F(26, "bold"), fg=T["text"], bg=T["bg"]).pack(anchor="w")
        tk.Label(head, text="Pick a box style. Type your dimensions, preview the dieline and the folded box, "
                            "then export SVG or DXF for your laser or cutter.", font=F(10), fg=T["muted"],
                 bg=T["bg"]).pack(anchor="w", pady=(2, 0))
        Btn(head, "Open project…", app.open_project, "ghost", size=9, padx=14, pady=6).pack(anchor="w", pady=(12, 0))
        self.recent_host = tk.Frame(main, bg=T["bg"])
        self.recent_host.pack(fill="x", padx=40)
        self.sf = ScrollFrame(main, T["bg"], bar=True)             # the cards scroll when they do not all fit
        self.sf.pack(fill="both", expand=True, padx=(34, 20), pady=(16, 14))
        self.grid_host = self.sf.inner
        for s in STYLES:
            self.cards.append(Card(self.grid_host, s, app.open_style))
        self.cols = 0
        self.sf.cv.bind("<Configure>", self._reflow, add="+")

    def refresh_recent(self):
        """The list of recent projects under the heading (hidden when there are none)."""
        for w in self.recent_host.winfo_children():
            w.destroy()
        shown = [p for p in self.app.recent if os.path.exists(p)][:5]
        if not shown:
            return
        tk.Label(self.recent_host, text="RECENT PROJECTS", font=F(8, "bold"), fg=T["dim"], bg=T["bg"]).pack(anchor="w", pady=(10, 4))
        for p in shown:
            row = tk.Frame(self.recent_host, bg=T["bg"], cursor="hand2")
            row.pack(fill="x")
            a = tk.Label(row, text=os.path.splitext(os.path.basename(p))[0], font=F(10, "bold"), fg=T["text"], bg=T["bg"],
                         cursor="hand2")
            a.pack(side="left")
            b = tk.Label(row, text="   " + os.path.dirname(p), font=F(9), fg=T["dim"], bg=T["bg"], cursor="hand2")
            b.pack(side="left")
            for w in (row, a, b):
                w.bind("<Button-1>", lambda e, q=p: self.app.open_project(q))
                w.bind("<Enter>", lambda e, w=a: w.config(fg=T["accent_h"]))
                w.bind("<Leave>", lambda e, w=a: w.config(fg=T["text"]))

    def _reflow(self, e):
        cols = 3 if e.width >= S(1020) else 2 if e.width >= S(680) else 1
        if cols == self.cols:
            return
        self.cols = cols
        for c in self.cards:
            c.grid_forget()
        for i in range(6):
            self.grid_host.grid_columnconfigure(i, weight=0)
        for i, c in enumerate(self.cards):
            c.grid(row=i // cols, column=i % cols, padx=8, pady=8, sticky="nsew")
        for i in range(cols):
            self.grid_host.grid_columnconfigure(i, weight=1, uniform="c")

    def start(self):
        self.stop()
        self._tick()

    def stop(self):
        if self._job:
            self.after_cancel(self._job)
            self._job = None

    def _tick(self):
        for c in self.cards:
            c.wire.yaw += 0.03 if c.hover else 0.011
            c.wire.render()
        self._job = self.after(40, self._tick)


