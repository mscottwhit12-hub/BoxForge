# =============================================================================
# 3-D wireframe renderer
# =============================================================================
class Wire3D:
    def __init__(self, canvas, up="y", lw=1.5):
        self.cv, self.up, self.lw = canvas, up, lw
        self.panels = None
        self.amount = 1.0
        self.yaw, self.pitch, self.zoom = -0.62, 0.5, 1.0
        self.bend = None                                    # inside bend radius (panel units) for rounded folds, or None
        self.bend_k, self.bend_len = None, True             # K-factor; take the bend's length out of the flaps
        self.style_id = "rsc"                               # picks the fold order of the solid view
        self.flute = None                                   # "v" / "h": faint flute lines on the outside faces
        self.edges = False                                  # solid mode: dark outlines on the faces (off by default)
        self.items = {}
        self.center, self.radius = (0, 0, 0), 1.0
        self.shadow = None
        self.solid, self.thick = False, 0.0           # solid mode: panels drawn as slabs of board thickness
        self.seq = False                              # RSC: real fold order + thick panels that sit against each other
        self._layer = None
        self.fixed_frame = False                      # editor: frame the whole fold sequence once, so the camera never drifts
        self._frame_cache = None
        self._model = None                            # solid mode: everything that does not change while only the camera moves
        self._model_key = None

    def _frame(self):
        """(centre, radius) of a sphere around the model in every state of the fold, so that the picture keeps one framing
        from the flat sheet to the closed box instead of re-centring and re-scaling on each frame. Cached until the
        model itself changes (sizes, board, bends), not when only the fold amount or the camera does."""
        key = (id(self.panels), self.thick, self.bend, self.bend_k, self.bend_len, self.flute, self.seq, self.style_id,
               self.up)
        if self._frame_cache and self._frame_cache[0] == key:
            return self._frame_cache[1]
        keep = self.amount
        pts = []
        try:
            for a in (0.45, 0.55, 0.7, 0.85, 1.0, 1.0):
                self.amount = a
                if self.seq and self.thick > 0:
                    pts += [self._orient(q) for f in self.solid_faces(sharp=True) if f[1] == "out" for q in f[2]]
                else:
                    pts += [self._orient(q) for poly in fold_panels(self.panels, a).values() for q in poly]
        finally:
            self.amount = keep
        xs, ys, zs = zip(*pts)
        c = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2)
        res = (c, max(1e-6, max(math.dist(c, q) for q in pts)))
        n1 = len(pts) // 6                                  # the closed box (last sample): where the floor shadow goes
        fx, fy, fz = zip(*pts[-n1:])
        self._floor = ((min(fx) + max(fx)) / 2, min(ys), (min(fz) + max(fz)) / 2, max(max(fx) - min(fx), max(fz) - min(fz)) / 2)
        self._frame_cache = (key, res)
        return res

    def _shadow_box(self, c0, R, W, H, scale, cyw, syw, cp, sp, dcam):
        """Screen box (x0, y0, x1, y1) of the floor shadow. With a fixed frame it lies on the floor under the closed box;
        otherwise it keeps the old placement relative to the model's centre."""
        if self.fixed_frame and getattr(self, "_floor", None):
            fx, fy, fz, rr = self._floor
            x, y, z = fx - c0[0], fy - c0[1], fz - c0[2]
            x1, z1 = cyw * x + syw * z, -syw * x + cyw * z
            y2, z2 = cp * y - sp * z1, sp * y + cp * z1
            f = dcam / (dcam - z2)
            sx, sy = W / 2 + x1 * scale * f, H / 2 - y2 * scale * f
            sw = max(rr * 1.35, R * 0.18) * scale * f
            return sx - sw, sy - sw * 0.28, sx + sw, sy + sw * 0.28
        sw = R * 1.05 * scale
        cy = H / 2 + R * 0.78 * scale * 0.80
        return W / 2 - sw, cy - sw * 0.28, W / 2 + sw, cy + sw * 0.28

    def _orient(self, p):
        return (p[0], p[2], -p[1]) if self.up == "z" else p

    def set_panels(self, panels, up=None):
        if up:
            self.up = up
        self.cv.delete("all")
        self.items, self.shadow = {}, None
        self.panels = panels
        self._model = self._model_key = self._frame_cache = None
        if not panels:
            return
        pts = [self._orient(q) for poly in fold_panels(panels, 1.0).values() for q in poly]
        xs, ys, zs = zip(*pts)
        self.center = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2)
        self.radius = max(1e-6, max(math.dist(self.center, q) for q in pts))
        self.render()

    def render(self):
        if not self.panels:
            return
        cv = self.cv
        W = cv.winfo_width() if cv.winfo_width() > 10 else int(cv.cget("width"))
        H = cv.winfo_height() if cv.winfo_height() > 10 else int(cv.cget("height"))
        if self.solid and self.thick > 0:
            return self._render_solid(W, H)
        if self.items.get("_solid"):
            cv.delete("solid")
            self.items.pop("_solid", None)
            self.items = {}
        if self.seq and self.thick > 0:                   # wire view of the same model: outside face outlines
            polys = {nm: pts for nm, kind, pts, role in self.solid_faces(sharp=True) if kind == "out"}
        else:
            polys = fold_panels(self.panels, self.amount)
        # fit the model as it is *right now* (flat sheet and folded box differ a lot in size)
        if self.fixed_frame:
            (cx0, cy0, cz0), R = self._frame()
        else:
            allp = [self._orient(q) for poly in polys.values() for q in poly]
            xs, ys, zs = zip(*allp)
            cx0, cy0, cz0 = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2
            R = max(1e-6, max(math.dist((cx0, cy0, cz0), q) for q in allp))
        scale = min(W, H) * 0.40 * self.zoom / R
        cyw, syw = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        dcam = 4.2 * R
        if self.shadow is None:
            self.shadow = cv.create_oval(0, 0, 1, 1, fill=mix(T["thumb"], "#000000", 0.35), outline="")
            cv.tag_lower(self.shadow)
        # floor shadow
        floor = -R * 0.0
        cv.coords(self.shadow, *self._shadow_box((cx0, cy0, cz0), R, W, H, scale, cyw, syw, cp, sp, dcam))
        for pn in self.panels:
            sc, zs = [], []
            for q in polys[pn.name]:
                x, y, z = self._orient(q)
                x, y, z = x - cx0, y - cy0, z - cz0
                x1, z1 = cyw * x + syw * z, -syw * x + cyw * z
                y2, z2 = cp * y - sp * z1, sp * y + cp * z1
                f = dcam / (dcam - z2)
                sc.extend((W / 2 + x1 * scale * f, H / 2 - y2 * scale * f))
                zs.append(z2)
            sc.extend(sc[:2])
            depth = (sum(zs) / len(zs) / R + 1) / 2
            if pn.role == "body":
                col = mix(T["body_dim"], T["body"], depth * 1.1)
            else:
                col = mix(T["flap_dim"], T["flap"], depth * 1.1)
            it = self.items.get(pn.name)
            if it is None:
                self.items[pn.name] = cv.create_line(*sc, fill=col, width=self.lw, joinstyle="round",
                                                     capstyle="round")
            else:
                cv.coords(it, *sc)
                cv.itemconfigure(it, fill=col)


    def solid_faces(self, sharp=False):
        bend = None if sharp else self.bend
        if self.seq and self.thick > 0:
            pf, lift, self._layer = style_sequence(self.style_id, self.panels, self.thick, self.amount)
            return solid_faces(self.panels, self.thick, pf, lift, bend=bend, bend_k=self.bend_k, bend_len=self.bend_len,
                               flute=self.flute)
        self._layer = None
        return solid_faces(self.panels, self.thick,
                           lambda p, d, m: min(1.0, max(0.0, self.amount * m - (d - 1))), bend=bend,
                           bend_k=self.bend_k, bend_len=self.bend_len, flute=self.flute)

    def _solid_model(self):
        """The folded slabs, their centre and radius, and the plate-order cache. These depend on the fold amount, the
        board, the bends and so on but not on the camera, so turning the model reuses them instead of folding again."""
        key = (id(self.panels), self.amount, self.thick, self.bend, self.bend_k, self.bend_len, self.flute, self.seq,
               self.style_id, self.up)
        if self._model is not None and self._model_key == key:
            return self._model
        faces = self.solid_faces()
        if self.fixed_frame:
            c0, R = self._frame()
        else:
            allp = [self._orient(q) for f in faces for q in f[2]]
            xs, ys, zs = zip(*allp)
            c0 = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2)
            R = max(1e-6, max(math.dist(c0, q) for q in allp))
        local = []                                          # [(name, kind, role, [(x, y, z) about the centre])]
        geo = {}
        for name, kind, pts, role in faces:
            loc = [tuple(c - o for c, o in zip(self._orient(q), c0)) for q in pts]
            local.append((name, kind, role, loc))
            if kind != "flute":
                geo.setdefault(name, []).append((kind, loc))
        self._model = (local, geo, c0, R, {})
        self._model_key = key
        return self._model

    def _render_solid(self, W, H):
        cv = self.cv
        local, geo, c0, R, order_cache = self._solid_model()
        scale = min(W, H) * 0.40 * self.zoom / R
        cyw, syw = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        dcam = 4.2 * R
        cam_model = (-syw * cp * dcam, sp * dcam, cyw * cp * dcam)      # the camera (0, 0, dcam), turned back into model space
        cv.delete("all")
        self.items, self.shadow = {"_solid": True}, None
        cv.create_oval(*self._shadow_box(c0, R, W, H, scale, cyw, syw, cp, sp, dcam),
                       fill=mix(T["thumb"], "#000000", 0.35), outline="", tags="solid")
        light = (-0.35, 0.55, 0.76)
        conv, plates, flutes = [], {}, []
        for name, kind, role, pts in local:
            sc, zz, cam = [], [], []
            for q in pts:
                x, y, z = q
                x1, z1 = cyw * x + syw * z, -syw * x + cyw * z
                y2, z2 = cp * y - sp * z1, sp * y + cp * z1
                f = dcam / (dcam - z2)
                sc.append((W / 2 + x1 * scale * f, H / 2 - y2 * scale * f))
                zz.append(z2)
                cam.append((x1, y2, z2))
            if kind == "flute":                                # drawn after the outside face it sits on
                flutes.append((name, sc))
                continue
            conv.append((name, kind, role, sc, zz, cam))
            plates.setdefault(name, []).append((kind, cam))
        rank = plate_order(plates, (0.0, 0.0, dcam), geo, cam_model, order_cache)
        out, out_col = [], {}
        for name, kind, role, sc, zz, cam in conv:
            # face normal in camera space (screen y is flipped, so use the camera-space points)
            nrm = _tri_normal(cam[0], cam[1], cam[2])
            for k in range(2, len(cam) - 1):                  # robust for concave outlines: use best-conditioned triple
                if abs(nrm[2]) > 1e-6 or kind != "out":
                    break
                nrm = _tri_normal(cam[0], cam[k], cam[k + 1])
            if kind == "edge":
                nrm = _tri_normal(cam[0], cam[1], cam[2])
            # polygon orientation decides whether it faces the viewer: use the signed area on screen
            a2 = sum(sc[i][0] * sc[(i + 1) % len(sc)][1] - sc[(i + 1) % len(sc)][0] * sc[i][1] for i in range(len(sc)))
            if kind == "edge":
                if a2 >= 0:                                    # screen y points down: negative area = CCW seen from front
                    continue
            else:
                # faces list is wound CCW looking at the outside (out) / inside (in, reversed) in panel space,
                # transform keeps handedness, so the same test applies
                if a2 >= 0:
                    continue
            ndl = max(0.0, nrm[0] * light[0] + nrm[1] * light[1] + nrm[2] * light[2])
            base_o = T["body"] if role == "body" else T["flap"]
            base_i = T["body_dim"] if role == "body" else T["flap_dim"]
            if kind == "out":
                col = mix(base_i, base_o, 0.55 + 0.45 * ndl)
            elif kind == "in":
                col = mix(base_i, "#000000", 0.30 - 0.12 * ndl)
            else:
                col = mix(base_i, base_o, 0.25 + 0.4 * ndl)
            if kind == "out":
                out_col[name] = col
            out.append(((rank.get(name, 0), sum(zz) / len(zz)),
                        [c for xy in sc for c in xy], col, "bend" if (name.endswith(".bend") or "~" in name) and kind != "edge" else kind))
        for name, sc in flutes:                                # only on outside faces that face the viewer
            if name in out_col:
                out.append(((rank.get(name, 0), 1e18), [c for xy in sc for c in xy], mix(out_col[name], "#000000", 0.2),
                            "flute"))
        out.sort(key=lambda r: r[0])
        edge_col = mix(T["thumb"], "#000000", 0.55)
        for z, flat, col, kind in out:
            if kind == "flute":
                cv.create_line(*flat, fill=col, width=1, tags="solid")
                continue
            cv.create_polygon(*flat, fill=col, outline=col if (kind == "bend" or not self.edges) else edge_col, width=0.6,
                              joinstyle="round",
                              tags="solid")


