#!/usr/bin/env python3
"""
h3m_gui.py — a map viewer for Heroes of Might & Magic III .h3m files.

Load a map, see every tile, hover for what sits on it, and run the same
exports the command-line tool offers.

Requires only the Python standard library (tkinter). Keep h3m.py and
h3m_render.py in the same folder.

    python3 h3m_gui.py                 # then File > Open
    python3 h3m_gui.py MyMap.h3m       # open straight away
"""

import csv
import json
import os
import sys
import traceback

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:
    sys.exit(
        "tkinter is not installed.\n"
        "  Debian/Ubuntu : sudo apt install python3-tk\n"
        "  Fedora        : sudo dnf install python3-tkinter\n"
        "  macOS/Windows : reinstall Python from python.org (tkinter is included)"
    )

import h3m
import h3m_render as render
import h3m_balance as balance
import h3m_report as report
import h3m_army as army

RULER_W, RULER_H = 34, 18      # ruler gutter thickness
RULER_MIN_GAP = 26             # least pixels between ruler labels

BALANCE_COLORS = {
    "much too weak": "#3b6bff", "weak": "#4bc0ff", "on curve": "#3fd07a",
    "strong": "#ffa62b", "much too strong": "#ff3b30",
    "random quantity": "#9a9aa5",
}

BG = "#1e1e22"
PANEL = "#26262c"
FG = "#e6e6e6"
ACCENT = "#7cc4ff"
MONO = ("Menlo", 11) if sys.platform == "darwin" else ("Consolas", 10)
UI = ("Segoe UI", 10) if sys.platform.startswith("win") else ("Helvetica", 11)

ZOOMS = [1, 2, 3, 4, 6, 8, 12, 16]


class MapViewer(tk.Tk):
    READ_ONLY = False

    def __init__(self, path=None, read_only=None):
        super().__init__()
        if read_only is not None:
            self.READ_ONLY = read_only
        self.title("HoMM3 Map Viewer" if self.READ_ONLY
                   else "HoMM3 Map Editor")
        self.geometry("1360x860")
        self.configure(bg=BG)

        self.map = None
        self.path = None
        self.level = 0
        self.zoom_i = 3                 # index into ZOOMS
        self.base_images = {}           # level -> PhotoImage at 1px per tile
        self.scaled = None
        self.tile_idx = {}
        self.terrain_idx = {}
        self.enabled = {}               # category -> BooleanVar
        self.pinned = False
        self.last_tile = None
        self.highlight = ""
        self.model = None            # corpus learned from reference maps
        self.suggestions = {}        # (x, y, z) -> list of suggestion records
        self._last_suggestions = None
        self.show_grid = False
        self.show_coords = False
        self.show_pass = False
        self.guard_region = None     # pocket a selected guard seals
        self.selected = None         # (x, y) of the pinned tile
        self.selected_span = []       # tiles the selected object covers
        self.edit_target = None      # (dict, label) currently being edited
        self.edit_widgets = {}
        self.balance_mode = tk.BooleanVar(value=False)

        self._build_menu()
        self._build_layout()
        self._show_placeholder()

        if path:
            self.after(80, lambda: self.load(path))

    # ------------------------------------------------------------------
    # layout
    # ------------------------------------------------------------------
    def _build_menu(self):
        bar = tk.Menu(self)

        fm = tk.Menu(bar, tearoff=0)
        fm.add_command(label="Open .h3m…", accelerator="Ctrl+O", command=self.open_dialog)
        fm.add_separator()
        fm.add_command(label="Quit", command=self.destroy)
        bar.add_cascade(label="File", menu=fm)

        ex = tk.Menu(bar, tearoff=0)
        ex.add_command(label="Objects → CSV…", command=lambda: self.export("objects"))
        ex.add_command(label="Creature stacks → CSV…", command=lambda: self.export("armies"))
        ex.add_command(label="Story & messages → Markdown…",
                       command=lambda: self.export("texts"))
        ex.add_command(label="Terrain tiles → CSV…", command=lambda: self.export("terrain"))
        ex.add_separator()
        ex.add_command(label="Full export → JSON…", command=lambda: self.export("full"))
        ex.add_command(label="Full export (slim + compact) → JSON…",
                       command=lambda: self.export("full_slim"))
        ex.add_separator()
        ex.add_command(label="Summary → text file…", command=lambda: self.export("summary"))
        ex.add_separator()
        ex.add_command(label="HTML analysis report…", command=self.export_html)
        ex.add_command(label="PDF analysis report…", command=self.export_pdf)
        ex.add_command(label="Export everything to a folder…", command=self.export_all)
        bar.add_cascade(label="Export", menu=ex)

        vm = tk.Menu(bar, tearoff=0)
        vm.add_command(label="Zoom in", accelerator="+", command=lambda: self.zoom(1))
        vm.add_command(label="Zoom out", accelerator="-", command=lambda: self.zoom(-1))
        vm.add_separator()
        vm.add_command(label="Toggle surface / underground", accelerator="Tab",
                       command=self.toggle_level)
        vm.add_separator()
        self.var_grid = tk.BooleanVar(value=False)
        self.var_coords = tk.BooleanVar(value=False)
        self.var_pass = tk.BooleanVar(value=False)
        vm.add_checkbutton(label="Grid", variable=self.var_grid,
                           command=self.toggle_grid)
        vm.add_checkbutton(label="Coordinate ruler", variable=self.var_coords,
                           command=self.toggle_coords)
        vm.add_checkbutton(label="Passability overlay", variable=self.var_pass,
                           command=self.toggle_pass)
        vm.add_separator()
        vm.add_command(label="Show all layers", command=lambda: self.set_all_layers(True))
        vm.add_command(label="Hide all layers", command=lambda: self.set_all_layers(False))
        bar.add_cascade(label="View", menu=vm)

        if not self.READ_ONLY:
            self._build_edit_menu(bar)

        self._build_balance_menu(bar)

        hm = tk.Menu(bar, tearoff=0)
        hm.add_command(label="About", command=self.about)
        bar.add_cascade(label="Help", menu=hm)
        self.config(menu=bar)
        self.bind("<Control-o>", lambda e: self.open_dialog())
        if not self.READ_ONLY:
            self.bind("<Control-s>", lambda e: self.save_map())
        self.bind("<Tab>", lambda e: self.toggle_level())
        self.bind("<plus>", lambda e: self.zoom(1))
        self.bind("<equal>", lambda e: self.zoom(1))
        self.bind("<minus>", lambda e: self.zoom(-1))

    def _build_edit_menu(self, bar):
        em = tk.Menu(bar, tearoff=0)
        em.add_command(label="Save map as .h3m…", accelerator="Ctrl+S",
                       command=self.save_map)
        em.add_command(label="Pending changes / undo…", command=self.show_pending)
        em.add_command(label="Discard all pending edits", command=self.discard_edits)
        em.add_separator()
        em.add_command(label="Story text editor…", command=self.text_editor)
        em.add_separator()
        em.add_command(label="Export story texts to a file…",
                       command=self.export_texts_file)
        em.add_command(label="Import edited story texts…",
                       command=self.import_texts_file)
        bar.add_cascade(label="Edit", menu=em)

    def _build_balance_menu(self, bar):
        bm = tk.Menu(bar, tearoff=0)
        bm.add_command(label="Load reference maps…", command=self.load_reference)
        bm.add_command(label="Analyse this map", command=self.run_balance)
        if not self.READ_ONLY:
            bm.add_command(label="Auto-balance creature counts…",
                           command=self.auto_balance_dialog)
        bm.add_separator()
        bm.add_checkbutton(label="Colour stacks by balance",
                           variable=self.balance_mode, command=self.draw_markers)
        bm.add_separator()
        bm.add_command(label="Balance report → Markdown…",
                       command=lambda: self.export_balance("report"))
        bm.add_command(label="Suggestions → CSV…",
                       command=lambda: self.export_balance("csv"))
        bar.add_cascade(label="Balance", menu=bm)

    def _build_layout(self):
        # ---- top bar ----
        top = tk.Frame(self, bg=PANEL, pady=6, padx=8)
        top.pack(side="top", fill="x")

        tk.Button(top, text="Open .h3m…", command=self.open_dialog,
                  bg="#3a3a44", fg=FG, relief="flat", padx=10).pack(side="left")

        self.level_btn = tk.Button(top, text="Surface", width=12, relief="flat",
                                   bg="#3a3a44", fg=FG, command=self.toggle_level)
        self.level_btn.pack(side="left", padx=(12, 4))

        tk.Button(top, text="−", width=3, bg="#3a3a44", fg=FG, relief="flat",
                  command=lambda: self.zoom(-1)).pack(side="left")
        self.zoom_lbl = tk.Label(top, text="4x", width=5, bg=PANEL, fg=FG, font=UI)
        self.zoom_lbl.pack(side="left")
        tk.Button(top, text="+", width=3, bg="#3a3a44", fg=FG, relief="flat",
                  command=lambda: self.zoom(1)).pack(side="left")

        tk.Label(top, text="  Highlight:", bg=PANEL, fg=FG, font=UI).pack(side="left")
        self.search = tk.Entry(top, width=24, bg="#15151a", fg=FG,
                               insertbackground=FG, relief="flat")
        self.search.pack(side="left", padx=4, ipady=3)
        self.search.bind("<KeyRelease>", self.on_search)

        # width=1 with fill/expand, for the same reason as the status bar: a
        # long map name must not enlarge the window's requested width.
        self.meta_lbl = tk.Label(top, text="No map loaded", bg=PANEL, fg=ACCENT,
                                 font=UI, anchor="e", width=1)
        self.meta_lbl.pack(side="right", fill="x", expand=True)

        # ---- status bar ----
        # Packed before the map and the side panel so that it spans the whole
        # window. A widget packed with side="left" claims a full-height strip,
        # so anything packed after it is confined to the cavity beside it.
        #
        # width=1 keeps the label's own text out of the geometry calculation.
        # Without it a long file path makes the window's requested width
        # enormous, pack has no leftover space to hand out, and the map canvas
        # never expands past its natural size.
        self.status = tk.Label(self, text="Ready", bg="#15151a", fg="#9a9aa5",
                               anchor="w", font=UI, padx=10, pady=4, width=1)
        self.status.pack(side="bottom", fill="x")

        # ---- right panel ----
        right = tk.Frame(self, bg=PANEL, width=360)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        tk.Label(right, text="TILE", bg=PANEL, fg=ACCENT, font=UI,
                 anchor="w").pack(fill="x", padx=10, pady=(10, 2))
        self.info = tk.Text(right, height=22, bg="#15151a", fg=FG, font=MONO,
                            relief="flat", wrap="word", padx=8, pady=8)
        self.info.pack(fill="both", expand=True, padx=10)
        self.info.insert("1.0", "Hover a tile to inspect it.\nClick to pin.")
        self.info.config(state="disabled")

        self.edit_hdr = tk.Label(right, text="EDIT  (click a tile to select)",
                                 bg=PANEL, fg=ACCENT, font=UI, anchor="w")
        edit_wrap = tk.Frame(right, bg=PANEL, height=300)
        self.edit_canvas = tk.Canvas(edit_wrap, bg=PANEL, highlightthickness=0)
        self.edit_frame = tk.Frame(self.edit_canvas, bg=PANEL)
        esb = tk.Scrollbar(edit_wrap, orient="vertical",
                           command=self.edit_canvas.yview)
        self.edit_canvas.configure(yscrollcommand=esb.set)
        self.edit_canvas.create_window((0, 0), window=self.edit_frame,
                                       anchor="nw")
        self.edit_frame.bind(
            "<Configure>",
            lambda e: self.edit_canvas.configure(
                scrollregion=self.edit_canvas.bbox("all")))
        if not self.READ_ONLY:
            self.edit_hdr.pack(fill="x", padx=10, pady=(12, 2))
            edit_wrap.pack(fill="both", expand=True, padx=10)
            edit_wrap.pack_propagate(False)
            esb.pack(side="right", fill="y")
            self.edit_canvas.pack(side="left", fill="both", expand=True)

        tk.Label(right, text="BALANCE", bg=PANEL, fg=ACCENT, font=UI,
                 anchor="w").pack(fill="x", padx=10, pady=(12, 2))
        self.bal_lbl = tk.Label(right, text="No reference maps loaded.",
                                bg=PANEL, fg="#9a9aa5", font=UI, anchor="w",
                                justify="left", wraplength=330)
        self.bal_lbl.pack(fill="x", padx=10)

        tk.Label(right, text="LAYERS", bg=PANEL, fg=ACCENT, font=UI,
                 anchor="w").pack(fill="x", padx=10, pady=(12, 2))
        self.layers = tk.Frame(right, bg=PANEL)
        self.layers.pack(fill="x", padx=10, pady=(0, 10))

        # ---- canvas, with ruler gutters ----
        # The rulers are separate canvases in a grid rather than text drawn on
        # the map, so the numbers stay put while the map scrolls under them and
        # never sit on top of terrain.
        self.wrap = tk.Frame(self, bg=BG)
        self.wrap.pack(side="left", fill="both", expand=True)
        self.wrap.grid_rowconfigure(1, weight=1)
        self.wrap.grid_columnconfigure(1, weight=1)

        self.ruler_corner = tk.Frame(self.wrap, bg=PANEL,
                                     width=RULER_W, height=RULER_H)
        self.ruler_top = tk.Canvas(self.wrap, bg=PANEL, height=RULER_H,
                                   highlightthickness=0)
        self.ruler_left = tk.Canvas(self.wrap, bg=PANEL, width=RULER_W,
                                    highlightthickness=0)
        self.canvas = tk.Canvas(self.wrap, bg=BG, highlightthickness=0)
        hbar = tk.Scrollbar(self.wrap, orient="horizontal",
                            command=self.canvas.xview)
        vbar = tk.Scrollbar(self.wrap, orient="vertical",
                            command=self.canvas.yview)
        self.canvas.config(xscrollcommand=self._on_xscroll,
                           yscrollcommand=self._on_yscroll)
        self.hbar, self.vbar = hbar, vbar

        self.canvas.grid(row=1, column=1, sticky="nsew")
        vbar.grid(row=1, column=2, sticky="ns")
        hbar.grid(row=2, column=1, sticky="ew")
        self.place_rulers()

        self.canvas.bind("<Configure>", self.on_canvas_resize)
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<MouseWheel>", self.on_wheel)          # win / mac
        self.canvas.bind("<Button-4>", lambda e: self.on_wheel(e, 1))   # linux
        self.canvas.bind("<Button-5>", lambda e: self.on_wheel(e, -1))

    def _show_placeholder(self):
        self.canvas.delete("all")
        self.canvas.create_text(
            420, 260, fill="#6a6a78", font=("Helvetica", 15),
            text="Open a .h3m map to begin\n\nFile > Open,  or  Ctrl+O")

    # ------------------------------------------------------------------
    # loading
    # ------------------------------------------------------------------
    def open_dialog(self):
        p = filedialog.askopenfilename(
            title="Open a Heroes III map",
            filetypes=[("HoMM3 maps", "*.h3m"), ("All files", "*.*")])
        if p:
            self.load(p)

    def load(self, path):
        self.status.config(text=f"Loading {os.path.basename(path)} …")
        self.update_idletasks()
        try:
            m = h3m.parse_file(path)
        except Exception as e:
            messagebox.showerror(
                "Could not read this map",
                f"{e}\n\nHorn of the Abyss and WoG maps are not supported.")
            self.status.config(text="Load failed")
            return

        self.map = m
        self.path = path
        self.level = 0
        self.base_images = {}
        self.pinned = False
        self.terrain_idx = render.build_terrain_index(m)
        self.tile_idx = render.build_tile_index(m)

        self._build_layer_toggles()
        self.clear_editor()
        self.render()

        left = m["_bytes_left"]
        self.meta_lbl.config(
            text=f"{m['name'] or os.path.basename(path)}  ·  {m['size']}x{m['size']}"
                 f"{' +u/g' if m['has_underground'] else ''}  ·  {m['version_name']}"
                 f"  ·  {len(m['objects'])} objects")
        playable = sum(1 for p in m["players"]
                       if p["can_be_human"] or p["can_be_computer"])
        self.status.config(
            text=f"Loaded {os.path.basename(path)} — {m['difficulty']}, "
                 f"{playable} players"
                 + ("  ·  clean parse (0 bytes left over)" if left == 0
                    else f"  ·  WARNING: {left} bytes left over, data may be wrong"))

    def _build_layer_toggles(self):
        for w in self.layers.winfo_children():
            w.destroy()
        present = set()
        for o in self.map["objects"]:
            c = render.categorize(o)
            if c:
                present.add(c)
        self.enabled = {}
        for key, (label, color, shape, _r) in render.CATEGORIES.items():
            if key not in present:
                continue
            var = tk.BooleanVar(value=(key != "other"))
            self.enabled[key] = var
            row = tk.Frame(self.layers, bg=PANEL)
            row.pack(fill="x")
            cb = tk.Checkbutton(row, text=f"  {label}", variable=var,
                                command=self.draw_markers, bg=PANEL, fg=FG,
                                selectcolor="#15151a", activebackground=PANEL,
                                activeforeground=FG, font=UI, anchor="w")
            cb.pack(side="left", fill="x", expand=True)
            swatch = tk.Canvas(row, width=14, height=14, bg=PANEL,
                               highlightthickness=0)
            swatch.create_rectangle(2, 2, 12, 12,
                                    fill=color or "#888888", outline="#000000")
            swatch.pack(side="right", padx=4)

    # ------------------------------------------------------------------
    # rendering
    # ------------------------------------------------------------------
    def base_image(self, level):
        if level in self.base_images:
            return self.base_images[level]
        rows = render.base_rows(self.map, level, self.terrain_idx,
                                self.tile_idx,
                                overlay="passability" if self.show_pass else None)
        img = tk.PhotoImage(width=self.map["size"], height=self.map["size"])
        img.put(" ".join("{" + " ".join(r) + "}" for r in rows))
        self.base_images[level] = img
        return img

    def render(self):
        if not self.map:
            return
        z = ZOOMS[self.zoom_i]
        base = self.base_image(self.level)
        self.scaled = base.zoom(z) if z > 1 else base
        size = self.map["size"] * z

        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.scaled, anchor="nw")
        self.map_px = size
        self.fit_view()
        self.draw_markers()
        self.draw_overlays()

        self.zoom_lbl.config(text=f"{z}x")
        self.level_btn.config(text="Underground" if self.level else "Surface")

    def select_tile(self, x, y):
        """Remember what is selected and outline it on the map."""
        self.selected = (x, y) if self.pinned else None
        self.selected_span = []
        self.guard_region = None
        if self.pinned:
            self.analyse_guard(x, y)
            for e in self.tile_idx.get((x, y, self.level), []):
                o = self.map["objects"][e["index"]]
                tpl = self.map["templates"][o["template_index"]]
                for dx, dy, blocked, visitable in h3m.footprint(tpl):
                    self.selected_span.append((o["x"] + dx, o["y"] + dy))
                if not h3m.footprint(tpl):
                    self.selected_span.append((o["x"], o["y"]))
                break
        self.draw_markers()

    def goto_tile(self, x, y, z=None):
        """Centre the map on a tile and select it, so a row in a list can be
        found on the map without hunting for the coordinates."""
        if not self.map:
            return
        if z is not None and z != self.level and self.map["has_underground"]:
            self.level = z
            self.render()
        self.scroll_to(x, y)
        self.pinned = True
        self.show_tile(x, y)
        self.select_tile(x, y)
        if not self.READ_ONLY:
            self.build_editor(x, y)

    def scroll_to(self, x, y):
        """Bring a tile into the middle of the view.

        Fractions are taken against the padded scroll region rather than the
        map itself, since fit_view() adds a margin when the map is smaller
        than the canvas.
        """
        self.canvas.update_idletasks()
        region = self.canvas.cget("scrollregion")
        if not region:
            return
        x0, y0, x1, y1 = (float(v) for v in region.split())
        width, height = (x1 - x0) or 1, (y1 - y0) or 1
        zf = ZOOMS[self.zoom_i]
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        fx = (x * zf - x0 - cw / 2) / width
        fy = (y * zf - y0 - ch / 2) / height
        self.canvas.xview_moveto(min(max(fx, 0.0), 1.0))
        self.canvas.yview_moveto(min(max(fy, 0.0), 1.0))

    def analyse_guard(self, x, y):
        """If a wandering monster is selected, work out what it seals off."""
        for e in self.tile_idx.get((x, y, self.level), []):
            o = self.map["objects"][e["index"]]
            if o["object_id"] in (54, 71, 72, 73, 74, 75, 162, 163, 164):
                try:
                    self.guard_region = balance.guarded_region(self.map, o)
                except Exception:
                    traceback.print_exc()
                    self.guard_region = None
                return

    def draw_selection(self):
        self.canvas.delete("sel")
        if not self.selected:
            return
        z = ZOOMS[self.zoom_i]
        if self.guard_region:
            for (tx, ty) in self.guard_region["pocket_tiles"]:
                self.canvas.create_rectangle(
                    tx * z, ty * z, (tx + 1) * z, (ty + 1) * z,
                    outline="", fill="#2f6f4f", stipple="gray25", tags="sel")
            for c in self.guard_region["contents"]:
                self.canvas.create_oval(
                    c["x"] * z - z, c["y"] * z - z,
                    (c["x"] + 1) * z + z, (c["y"] + 1) * z + z,
                    outline="#39ff6a", width=max(2, z // 4), tags="sel")
        for (tx, ty) in self.selected_span:
            self.canvas.create_rectangle(
                tx * z, ty * z, (tx + 1) * z, (ty + 1) * z,
                outline="#ffe14d", width=max(1, z // 6), tags="sel")
        sx, sy = self.selected
        pad = max(3, z)
        self.canvas.create_rectangle(
            sx * z - pad, sy * z - pad, (sx + 1) * z + pad, (sy + 1) * z + pad,
            outline="#ff3b30", width=max(2, z // 5), tags="sel")

    def draw_markers(self):
        if not self.map:
            return
        self.canvas.delete("marker")
        z = ZOOMS[self.zoom_i]
        hl = self.highlight.lower()
        for mk in render.markers(self.map, self.level):
            var = self.enabled.get(mk["category"])
            o = self.map["objects"][mk["index"]]
            matched = bool(hl) and (
                hl in o["name"].lower() or hl in h3m.detail_of(o).lower())
            if not matched and (var is None or not var.get()):
                continue
            cx = (mk["x"] + 0.5) * z
            cy = (mk["y"] + 0.5) * z
            r = max(1.5, mk["radius"] * z / 5.0)
            color = "#ffffff" if matched else mk["color"]
            outline = "#ff0000" if matched else "#000000"
            width = 2 if matched else 1
            if (self.balance_mode.get() and mk["category"] == "monster"
                    and not matched):
                recs = self.suggestions.get((mk["x"], mk["y"], self.level))
                if recs:
                    color = BALANCE_COLORS.get(recs[0]["status"], color)
                    r = max(r, z * 0.45)
            if matched:
                r = max(r, z * 0.6)
            shape = mk["shape"]
            if shape == "circle":
                self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                        fill=color, outline=outline,
                                        width=width, tags="marker")
            elif shape == "square":
                self.canvas.create_rectangle(cx - r, cy - r, cx + r, cy + r,
                                             fill=color, outline=outline,
                                             width=width, tags="marker")
            elif shape == "diamond":
                self.canvas.create_polygon(cx, cy - r, cx + r, cy, cx, cy + r,
                                           cx - r, cy, fill=color,
                                           outline=outline, width=width,
                                           tags="marker")
            else:
                self.canvas.create_polygon(cx, cy - r, cx + r, cy + r,
                                           cx - r, cy + r, fill=color,
                                           outline=outline, width=width,
                                           tags="marker")
        self.draw_selection()

    def fit_view(self):
        """Centre the map when it is smaller than the canvas.

        The map is always drawn from (0, 0), so a map narrower than the widget
        would otherwise sit against the left edge with bare canvas beside it.
        Padding the scroll region instead of moving the image keeps every
        drawing routine and the hover lookup in plain map coordinates, since
        canvasx/canvasy already account for the scroll offset.
        """
        px = getattr(self, "map_px", 0)
        if not px:
            return
        self.canvas.update_idletasks()
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        padx = max(0, (cw - px) // 2)
        pady = max(0, (ch - px) // 2)
        self.canvas.config(scrollregion=(-padx, -pady, px + padx, px + pady))
        self.draw_rulers()

    def on_canvas_resize(self, _event=None):
        self.fit_view()

    # ------------------------------------------------------------------
    # rulers
    # ------------------------------------------------------------------
    def place_rulers(self):
        """Show or hide the ruler gutters without disturbing the map."""
        if self.show_coords:
            self.ruler_corner.grid(row=0, column=0, sticky="nsew")
            self.ruler_top.grid(row=0, column=1, sticky="ew")
            self.ruler_left.grid(row=1, column=0, sticky="ns")
        else:
            self.ruler_corner.grid_remove()
            self.ruler_top.grid_remove()
            self.ruler_left.grid_remove()

    def _on_xscroll(self, first, last):
        self.hbar.set(first, last)
        if self.show_coords:
            self.ruler_top.xview_moveto(first)

    def _on_yscroll(self, first, last):
        self.vbar.set(first, last)
        if self.show_coords:
            self.ruler_left.yview_moveto(first)

    def ruler_step(self, z):
        """Tile interval between labels, so they never run together."""
        for step in (1, 2, 5, 10, 20, 25, 50):
            if step * z >= RULER_MIN_GAP:
                return step
        return 100

    def draw_rulers(self):
        self.ruler_top.delete("all")
        self.ruler_left.delete("all")
        if not self.map or not self.show_coords:
            return
        z = ZOOMS[self.zoom_i]
        size = self.map["size"]
        region = self.canvas.cget("scrollregion")
        if not region:
            return
        x0, y0, x1, y1 = (float(v) for v in region.split())
        self.ruler_top.config(scrollregion=(x0, 0, x1, RULER_H))
        self.ruler_left.config(scrollregion=(0, y0, RULER_W, y1))

        step = self.ruler_step(z)
        font = ("Helvetica", 8)
        for i in range(0, size, step):
            cx = i * z + z / 2
            self.ruler_top.create_text(cx, RULER_H / 2, text=str(i),
                                       fill="#cdd3e4", font=font)
            self.ruler_top.create_line(i * z, RULER_H - 3, i * z, RULER_H,
                                       fill="#5a6076")
            cy = i * z + z / 2
            self.ruler_left.create_text(RULER_W / 2, cy, text=str(i),
                                        fill="#cdd3e4", font=font)
            self.ruler_left.create_line(RULER_W - 3, i * z, RULER_W, i * z,
                                        fill="#5a6076")
        # keep the gutters aligned with wherever the map is scrolled to
        self.ruler_top.xview_moveto(self.canvas.xview()[0])
        self.ruler_left.yview_moveto(self.canvas.yview()[0])

    def toggle_grid(self):
        self.show_grid = self.var_grid.get()
        self.draw_overlays()

    def toggle_coords(self):
        self.show_coords = self.var_coords.get()
        self.place_rulers()
        self.update_idletasks()
        self.fit_view()
        self.draw_rulers()

    def toggle_pass(self):
        self.show_pass = self.var_pass.get()
        self.base_images = {}          # the overlay is baked into the image
        self.render()

    def draw_overlays(self):
        """Grid lines over the map, plus the ruler gutters beside it."""
        self.canvas.delete("grid")
        if not self.map:
            return
        z = ZOOMS[self.zoom_i]
        size = self.map["size"]
        px = size * z
        if self.show_grid:
            step = 1 if z >= 6 else (5 if z >= 3 else 10)
            for i in range(0, size + 1, step):
                heavy = (i % 10 == 0)
                col = "#8b93a8" if heavy else "#40465a"
                self.canvas.create_line(i * z, 0, i * z, px, fill=col,
                                        tags="grid")
                self.canvas.create_line(0, i * z, px, i * z, fill=col,
                                        tags="grid")
        self.draw_rulers()

    def zoom(self, delta):
        if not self.map:
            return
        new = max(0, min(len(ZOOMS) - 1, self.zoom_i + delta))
        if new != self.zoom_i:
            self.zoom_i = new
            self.render()

    def on_wheel(self, event, direction=None):
        if direction is None:
            direction = 1 if event.delta > 0 else -1
        if event.state & 0x0004:        # ctrl held -> zoom
            self.zoom(direction)
        else:
            self.canvas.yview_scroll(-direction * 3, "units")

    def toggle_level(self):
        if not self.map or not self.map["has_underground"]:
            return "break"
        self.level = 1 - self.level
        self.render()
        return "break"

    def set_all_layers(self, on):
        for v in self.enabled.values():
            v.set(on)
        self.draw_markers()

    def on_search(self, _e=None):
        self.highlight = self.search.get().strip()
        self.draw_markers()

    # ------------------------------------------------------------------
    # hover / click
    # ------------------------------------------------------------------
    def tile_at(self, event):
        if not self.map:
            return None
        z = ZOOMS[self.zoom_i]
        x = int(self.canvas.canvasx(event.x) // z)
        y = int(self.canvas.canvasy(event.y) // z)
        s = self.map["size"]
        if 0 <= x < s and 0 <= y < s:
            return x, y
        return None

    def on_motion(self, event):
        if self.pinned:
            return
        t = self.tile_at(event)
        if t is None or t == self.last_tile:
            return
        self.last_tile = t
        self.show_tile(*t)

    def on_click(self, event):
        t = self.tile_at(event)
        if t is None:
            return
        self.pinned = not self.pinned
        self.show_tile(*t)
        self.select_tile(*t)
        if self.READ_ONLY:
            return
        if self.pinned:
            self.build_editor(*t)
        else:
            self.clear_editor()

    # ------------------------------------------------------------------
    # editing
    # ------------------------------------------------------------------
    def clear_editor(self):
        for w in self.edit_frame.winfo_children():
            w.destroy()
        self.edit_widgets = {}
        self.slot_widgets = []
        self.edit_target = None
        self.edit_hdr.config(text="EDIT  (click a tile to select)")

    def build_editor(self, x, y):
        self.clear_editor()
        entries = self.tile_idx.get((x, y, self.level), [])
        target = None
        for e in entries:
            o = self.map["objects"][e["index"]]
            if h3m.editable_fields(o):
                target = o
                break
        if target is None:
            self.edit_hdr.config(text="EDIT  (nothing editable on this tile)")
            return

        self.edit_target = target
        self.edit_hdr.config(
            text=f"EDIT  {target['name']} ({target['x']},{target['y']},{target['z']})")

        for key in h3m.editable_fields(target):
            kind = target["_off"][key][0]
            row = tk.Frame(self.edit_frame, bg=PANEL)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=key.replace("_", " "), bg=PANEL, fg=FG,
                     font=UI, width=13, anchor="w").pack(side="left")
            current = target.get(key, "")
            choices = h3m.field_choices(key)
            if choices:
                shown = current
                if key in ("never_flees", "does_not_grow"):
                    shown = "Yes" if current else "No"
                var = tk.StringVar(value=str(shown))
                w = ttk.Combobox(row, textvariable=var, width=14,
                                 values=choices, state="readonly")
                w.pack(side="left", fill="x", expand=True)
                self.edit_widgets[key] = ("combo", var, kind)
            elif kind == "string":
                w = tk.Text(row, height=3, width=22, bg="#15151a", fg=FG,
                            insertbackground=FG, relief="flat", wrap="word")
                w.insert("1.0", current or "")
                w.pack(side="left", fill="x", expand=True)
                self.edit_widgets[key] = ("text", w, kind)
            else:
                var = tk.StringVar(value=str(int(current) if isinstance(current, bool)
                                             else current))
                w = tk.Entry(row, textvariable=var, bg="#15151a", fg=FG,
                             insertbackground=FG, relief="flat")
                w.pack(side="left", fill="x", expand=True)
                self.edit_widgets[key] = ("entry", var, kind)

        # creature stacks living inside this object: guards, garrisons,
        # hero armies, and the creatures handed out by events and boxes
        self.slot_widgets = []
        for group in ("guards", "army", "creatures"):
            slots = target.get(group) or []
            if not slots:
                continue
            tk.Label(self.edit_frame, text=group.upper(), bg=PANEL,
                     fg="#9297ab", font=UI, anchor="w").pack(fill="x", pady=(8, 0))
            for slot in slots:
                if "_off" not in slot:
                    continue
                row = tk.Frame(self.edit_frame, bg=PANEL)
                row.pack(fill="x", pady=1)
                cvar = tk.StringVar(value=slot["creature"] or "")
                cb = ttk.Combobox(row, textvariable=cvar, width=15,
                                  values=h3m.field_choices("creature_id"),
                                  state="readonly")
                cb.pack(side="left", fill="x", expand=True)
                nvar = tk.StringVar(value=str(slot["count"]))
                tk.Entry(row, textvariable=nvar, width=7, bg="#15151a", fg=FG,
                         insertbackground=FG, relief="flat").pack(side="left",
                                                                  padx=(4, 0))
                self.slot_widgets.append((slot, cvar, nvar))

        btns = tk.Frame(self.edit_frame, bg=PANEL)
        btns.pack(fill="x", pady=(8, 4))
        tk.Button(btns, text="Save", command=self.queue_edit,
                  bg="#2f6f4f", fg=FG, relief="flat", padx=14).pack(side="left")
        if getattr(self, "slot_widgets", None):
            tk.Button(btns, text="Fill to…", command=self.fill_army_dialog,
                      bg="#3f5b8a", fg=FG, relief="flat").pack(side="left")
        tk.Button(btns, text="Delete object", command=self.delete_selected,
                  bg="#7a2b2b", fg=FG, relief="flat").pack(side="left", padx=6)


    def queue_edit(self):
        if not self.edit_target:
            return
        queued = 0
        for key, (widget_kind, holder, kind) in self.edit_widgets.items():
            if widget_kind == "text":
                value = holder.get("1.0", "end-1c")
            else:
                value = holder.get()
            old = self.edit_target.get(key)
            if kind == "string":
                if value == (old or ""):
                    continue
            elif h3m.field_choices(key):
                shown_old = ("Yes" if old else "No") \
                    if key in ("never_flees", "does_not_grow") else str(old)
                if str(value) == shown_old:
                    continue
            else:
                try:
                    value = int(str(value).strip())
                except ValueError:
                    messagebox.showerror(
                        "Not a number",
                        f"{key.replace('_', ' ')} needs a whole number.")
                    return
                if value == (int(old) if isinstance(old, bool) else old):
                    continue
            try:
                h3m.edit(self.map, self.edit_target, key, value)
                queued += 1
            except h3m.EditError as e:
                messagebox.showerror("Cannot make that change", str(e))
                return
        for slot, cvar, nvar in getattr(self, "slot_widgets", []):
            try:
                if cvar.get() and cvar.get() != slot["creature"]:
                    h3m.edit(self.map, slot, "creature_id", cvar.get())
                    queued += 1
                new_count = int(str(nvar.get()).strip())
                if new_count != slot["count"]:
                    h3m.edit(self.map, slot, "count", new_count)
                    queued += 1
            except ValueError:
                messagebox.showerror("Not a number",
                                     "Creature amounts need whole numbers.")
                return
            except h3m.EditError as e:
                messagebox.showerror("Cannot make that change", str(e))
                return
        self.report_pending(extra=f"queued {queued} change(s)")

    def delete_selected(self):
        if not self.edit_target:
            return
        o = self.edit_target
        if not messagebox.askyesno(
                "Remove this object?",
                f"Remove {o['name']} at ({o['x']},{o['y']},{o['z']})?\n\n"
                "This is queued like any other change and can be undone from "
                "Edit > Pending changes until you save."):
            return
        try:
            h3m.delete_object(self.map, o)
        except h3m.EditError as e:
            messagebox.showerror("Cannot remove this", str(e))
            return
        self.clear_editor()
        self.report_pending(extra="object queued for removal")

    def fill_army_dialog(self):
        """Set the counts in the selected stack to hit a total."""
        if not self.slot_widgets:
            return
        win = tk.Toplevel(self)
        win.title("Fill stack to a total")
        win.configure(bg=PANEL)
        win.geometry("560x420")

        tk.Label(win, bg=PANEL, fg=FG, font=UI, anchor="w", justify="left",
                 wraplength=520,
                 text="Counts are spread in proportion to weekly growth, so "
                      "the result reads as an army rather than a pile of the "
                      "cheapest creature."
                 ).pack(fill="x", padx=14, pady=(12, 8))

        row = tk.Frame(win, bg=PANEL)
        row.pack(fill="x", padx=14)
        metric = tk.StringVar(value="hp")
        for label, val in (("Total hit points", "hp"), ("Total power", "power")):
            tk.Radiobutton(row, text=label, variable=metric, value=val,
                           bg=PANEL, fg=FG, selectcolor="#15151a", font=UI,
                           activebackground=PANEL, activeforeground=FG
                           ).pack(side="left", padx=(0, 12))
        amount = tk.StringVar(value="10000")
        tk.Entry(row, textvariable=amount, width=12, bg="#15151a", fg=FG,
                 relief="flat", insertbackground=FG).pack(side="left")

        norm = tk.Frame(win, bg=PANEL)
        norm.pack(fill="x", padx=14, pady=6)
        tk.Button(norm, text="Use the map's norm for a garrison",
                  bg="#3a3a44", fg=FG, relief="flat",
                  command=lambda: self._fill_from_norm(metric, amount)
                  ).pack(side="left")

        tilt_row = tk.Frame(win, bg=PANEL)
        tilt_row.pack(fill="x", padx=14, pady=(4, 0))
        tk.Label(tilt_row, text="Mix", bg=PANEL, fg=FG, font=UI).pack(side="left")
        tilt = tk.DoubleVar(value=0.0)
        tk.Scale(tilt_row, from_=-1.5, to=1.5, resolution=0.1,
                 orient="horizontal", variable=tilt, bg=PANEL, fg=FG,
                 troughcolor="#15151a", highlightthickness=0, length=280,
                 showvalue=True).pack(side="left", padx=8)
        tk.Label(tilt_row, text="low tiers  ←→  high tiers", bg=PANEL,
                 fg="#9297ab", font=UI).pack(side="left")

        out = tk.Text(win, height=11, bg="#15151a", fg=FG, font=MONO,
                      relief="flat", wrap="none")
        out.pack(fill="both", expand=True, padx=14, pady=10)

        state = {"result": None}

        def preview():
            ids = []
            for slot, cvar, _n in self.slot_widgets:
                try:
                    ids.append(h3m._coerce("creature_id", cvar.get()))
                except Exception:
                    pass
            try:
                target = float(amount.get())
            except ValueError:
                messagebox.showerror("Not a number", "Give a numeric total.")
                return
            res = army.compose(ids, target, metric.get(),
                               tier_tilt=float(tilt.get()))
            state["result"] = res
            out.delete("1.0", "end")
            out.insert("1.0", army.describe(res))

        def apply_now():
            if not state["result"]:
                preview()
            res = state["result"]
            if not res or not res["slots"]:
                return
            for (slot, cvar, nvar), s in zip(self.slot_widgets, res["slots"]):
                nvar.set(str(s["count"]))
            win.destroy()
            self.queue_edit()

        b = tk.Frame(win, bg=PANEL)
        b.pack(fill="x", padx=14, pady=(0, 14))
        tk.Button(b, text="Preview", command=preview, bg="#3a3a44", fg=FG,
                  relief="flat").pack(side="left")
        tk.Button(b, text="Apply and queue", command=apply_now, bg="#2f6f4f",
                  fg=FG, relief="flat").pack(side="left", padx=8)
        preview()

    def _fill_from_norm(self, metric, amount):
        if not self.model:
            messagebox.showinfo("No reference maps",
                                "Load reference maps first so the norm is known.")
            return
        t = army.norm_target(self.map, self.model, "garrison", metric.get())
        if not t:
            messagebox.showinfo("No norm available",
                                "This map has too few stacks to infer a norm.")
            return
        amount.set(str(int(t)))

    def show_pending(self):
        if not self.map:
            return
        entries = h3m.pending_edits(self.map)
        win = tk.Toplevel(self)
        win.title("Pending changes")
        win.configure(bg=PANEL)
        win.geometry("620x460")
        tk.Label(win, text="Nothing is written until you save. Undo anything "
                           "you do not want.", bg=PANEL, fg=FG, font=UI,
                 anchor="w", wraplength=580).pack(fill="x", padx=12, pady=10)
        canvas = tk.Canvas(win, bg=PANEL, highlightthickness=0)
        frame = tk.Frame(canvas, bg=PANEL)
        sb = tk.Scrollbar(win, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True, padx=12, pady=(0, 12))
        canvas.create_window((0, 0), window=frame, anchor="nw")
        frame.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        def rebuild():
            for w in frame.winfo_children():
                w.destroy()
            items = h3m.pending_edits(self.map)
            if not items:
                tk.Label(frame, text="No pending changes.", bg=PANEL,
                         fg="#9297ab", font=UI).pack(anchor="w")
            for entry in items:
                row = tk.Frame(frame, bg=PANEL)
                row.pack(fill="x", pady=2)
                tk.Button(row, text="undo", bg="#3a3a44", fg=FG, relief="flat",
                          command=lambda e=entry: (h3m.revert_edit(self.map, e),
                                                   rebuild(),
                                                   self.report_pending())
                          ).pack(side="left", padx=(0, 8))
                tk.Label(row, text=entry["label"], bg=PANEL, fg=FG, font=UI,
                         anchor="w", justify="left", wraplength=460
                         ).pack(side="left", fill="x", expand=True)
        rebuild()

    def auto_balance_dialog(self):
        if not self.map:
            messagebox.showinfo("No map", "Open a map first.")
            return
        if not self.model:
            messagebox.showinfo("No reference maps",
                                "Load reference maps first: "
                                "Balance > Load reference maps…")
            return
        win = tk.Toplevel(self)
        win.title("Auto-balance creature counts")
        win.configure(bg=PANEL)
        win.geometry("760x600")

        top = tk.Frame(win, bg=PANEL)
        top.pack(fill="x", padx=14, pady=12)
        tk.Label(top, text="Only touch stacks between", bg=PANEL, fg=FG,
                 font=UI).pack(side="left")
        lo = tk.StringVar(value="0.5")
        hi = tk.StringVar(value="5.0")
        tk.Entry(top, textvariable=lo, width=6, bg="#15151a", fg=FG,
                 relief="flat", insertbackground=FG).pack(side="left", padx=4)
        tk.Label(top, text="x and", bg=PANEL, fg=FG, font=UI).pack(side="left")
        tk.Entry(top, textvariable=hi, width=6, bg="#15151a", fg=FG,
                 relief="flat", insertbackground=FG).pack(side="left", padx=4)
        tk.Label(top, text="x of the norm", bg=PANEL, fg=FG,
                 font=UI).pack(side="left")

        top2 = tk.Frame(win, bg=PANEL)
        top2.pack(fill="x", padx=14, pady=(0, 6))
        tk.Label(top2, text="Aim for", bg=PANEL, fg=FG, font=UI).pack(side="left")
        scale = tk.StringVar(value="1.0")
        tk.Entry(top2, textvariable=scale, width=6, bg="#15151a", fg=FG,
                 relief="flat", insertbackground=FG).pack(side="left", padx=4)
        tk.Label(top2, text="x the norm  (1.0 = match it, 1.15 = 15% harder)",
                 bg=PANEL, fg=FG, font=UI).pack(side="left")

        top3 = tk.Frame(win, bg=PANEL)
        top3.pack(fill="x", padx=14)
        do_random = tk.BooleanVar(value=False)
        tk.Checkbutton(top3, variable=do_random, bg=PANEL, fg=FG, font=UI,
                       selectcolor="#15151a", activebackground=PANEL,
                       activeforeground=FG, anchor="w",
                       text="Also give a fixed amount to stacks set to "
                            "Quantity: Random"
                       ).pack(fill="x")

        note = tk.Label(win, bg=PANEL, fg="#9297ab", font=UI, anchor="w",
                        justify="left", wraplength=720,
                        text="Stacks far outside the window are usually "
                             "deliberate set pieces, so they are left alone "
                             "by default. Widen the range to include them.")
        note.pack(fill="x", padx=14)

        listwrap = tk.Frame(win, bg=PANEL)
        listwrap.pack(fill="both", expand=True, padx=14, pady=10)
        canvas = tk.Canvas(listwrap, bg=PANEL, highlightthickness=0)
        inner = tk.Frame(canvas, bg=PANEL)
        sb = tk.Scrollbar(listwrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        state = {"plan": []}

        def preview():
            try:
                a, b = float(lo.get()), float(hi.get())
            except ValueError:
                messagebox.showerror("Not a number",
                                     "The window bounds need to be numbers.")
                return
            try:
                sc = float(scale.get())
            except ValueError:
                messagebox.showerror("Not a number",
                                     "The multiplier needs to be a number.")
                return
            state["plan"] = balance.plan_auto_balance(
                self.map, self.model, self.path or "", a, b, scale=sc,
                include_random=bool(do_random.get()))
            for w in inner.winfo_children():
                w.destroy()
            if not state["plan"]:
                tk.Label(inner, text="Nothing falls inside that window.",
                         bg=PANEL, fg="#9297ab", font=UI).pack(anchor="w")
            for c in state["plan"][:400]:
                var = tk.BooleanVar(value=True)
                c["_var"] = var
                row = tk.Frame(inner, bg=PANEL)
                row.pack(fill="x", anchor="w")
                tk.Button(row, text="show", bg="#3a3a44", fg=FG, relief="flat",
                          font=UI, padx=6,
                          command=lambda cc=c: self.goto_tile(cc["x"], cc["y"],
                                                              cc["z"])
                          ).pack(side="left", padx=(0, 6))
                amount = ("random → " + str(c["new_count"])
                          if c["old_count"] == 0
                          else f"{c['old_count']} → {c['new_count']}")
                tk.Checkbutton(
                    row, variable=var, bg=PANEL, fg=FG, selectcolor="#15151a",
                    activebackground=PANEL, activeforeground=FG, font=UI,
                    anchor="w",
                    text=f"({c['x']},{c['y']},{c['z']})  {c['creature']}  "
                         f"{amount}   [{c['ratio']}x, guarding {c['reward']}]"
                ).pack(side="left", fill="x", expand=True)
            count.config(text=f"{len(state['plan'])} stack(s) would change")

        def apply_now():
            plan = state["plan"]
            for c in plan:
                c["apply"] = bool(c.get("_var").get()) if c.get("_var") else True
            done = balance.apply_auto_balance(self.map, plan)
            out = filedialog.asksaveasfilename(
                title="Save the auto-balance report",
                initialfile=f"{self._stem()}_autobalance.md",
                defaultextension=".md")
            if out:
                with open(out, "w") as f:
                    f.write(balance.auto_balance_report(
                        self.map, plan, lo.get(), hi.get(), self.path or ""))
            messagebox.showinfo(
                "Queued",
                f"{len(done)} stack(s) queued.\n\n"
                "Nothing is written yet — review them under "
                "Edit > Pending changes, then Edit > Save map as…")
            self.report_pending(extra=f"auto-balance queued {len(done)}")
            win.destroy()

        btns = tk.Frame(win, bg=PANEL)
        btns.pack(fill="x", padx=14, pady=(0, 14))
        tk.Button(btns, text="Preview", command=preview, bg="#3a3a44", fg=FG,
                  relief="flat").pack(side="left")
        tk.Button(btns, text="Queue selected", command=apply_now,
                  bg="#2f6f4f", fg=FG, relief="flat").pack(side="left", padx=8)
        count = tk.Label(btns, text="", bg=PANEL, fg=ACCENT, font=UI)
        count.pack(side="left", padx=10)
        preview()

    @staticmethod
    def short_path(path, keep=2):
        """Trim a long path to its last few parts.

        The status bar clips at its right edge, so a full path would hide the
        filename, which is the part worth reading.
        """
        parts = str(path).replace("\\", "/").split("/")
        return path if len(parts) <= keep else ".../" + "/".join(parts[-keep:])

    def report_pending(self, extra=""):
        n = len(h3m.pending_edits(self.map)) if self.map else 0
        bits = [f"{n} pending edit(s)"] if n else ["no pending edits"]
        if extra:
            bits.insert(0, extra)
        self.status.config(text="  ·  ".join(bits)
                           + ("  —  Edit > Save map as… to write them" if n else ""))

    def discard_edits(self):
        if not self.map:
            return
        h3m.clear_edits(self.map)
        self.report_pending(extra="edits discarded")

    def save_map(self):
        if not self.map:
            messagebox.showinfo("No map", "Open a map first.")
            return
        n = len(h3m.pending_edits(self.map))
        out = filedialog.asksaveasfilename(
            initialfile=f"{self._stem()}_edited.h3m", defaultextension=".h3m",
            filetypes=[("HoMM3 maps", "*.h3m")])
        if not out:
            return
        if os.path.abspath(out) == os.path.abspath(self.path or ""):
            if not messagebox.askyesno(
                    "Overwrite the original?",
                    "This will overwrite the file you opened. Continue?"):
                return
        try:
            h3m.save(self.map, out)
        except h3m.EditError as e:
            messagebox.showerror("Refused to write the map", str(e))
            return
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("Save failed", str(e))
            return
        messagebox.showinfo(
            "Saved",
            f"Wrote {os.path.basename(out)} with {n} change(s).\n\n"
            "The map was re-parsed before writing and read back cleanly.")
        self.status.config(
            text=f"Saved {self.short_path(out)} ({n} change(s) applied)")

    def text_editor(self):
        """Edit every string in the map without leaving the program."""
        if not self.map:
            messagebox.showinfo("No map", "Open a map first.")
            return
        targets = h3m._text_targets(self.map)
        win = tk.Toplevel(self)
        win.title("Story text")
        win.configure(bg=PANEL)
        win.geometry("980x640")

        left = tk.Frame(win, bg=PANEL, width=380)
        left.pack(side="left", fill="y", padx=(12, 6), pady=12)
        left.pack_propagate(False)
        tk.Label(left, text="Filter", bg=PANEL, fg=FG, font=UI,
                 anchor="w").pack(fill="x")
        filt = tk.Entry(left, bg="#15151a", fg=FG, relief="flat",
                        insertbackground=FG)
        filt.pack(fill="x", pady=(2, 8), ipady=3)
        lb = tk.Listbox(left, bg="#15151a", fg=FG, relief="flat",
                        selectbackground="#3f5b8a", font=UI,
                        activestyle="none")
        sb = tk.Scrollbar(left, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        lb.pack(side="left", fill="both", expand=True)

        right = tk.Frame(win, bg=PANEL)
        right.pack(side="left", fill="both", expand=True, padx=(6, 12), pady=12)
        where = tk.Label(right, text="Pick an entry on the left", bg=PANEL,
                         fg=ACCENT, font=UI, anchor="w", justify="left",
                         wraplength=520)
        where.pack(fill="x")
        txt = tk.Text(right, bg="#15151a", fg=FG, font=MONO, relief="flat",
                      wrap="word", padx=8, pady=8, undo=True)
        txt.pack(fill="both", expand=True, pady=8)
        note = tk.Label(right, bg=PANEL, fg="#9297ab", font=UI, anchor="w",
                        justify="left", wraplength=520,
                        text="Text is stored with an explicit length, so it "
                             "can be any length you like. Line breaks are "
                             "kept. Changes are queued and written when you "
                             "save the map.")
        note.pack(fill="x")

        state = {"rows": [], "current": None}

        def refresh(*_a):
            needle = filt.get().strip().lower()
            lb.delete(0, "end")
            state["rows"] = []
            for tid, w, target, key in targets:
                text = target.get(key) or ""
                if needle and needle not in w.lower() and needle not in text.lower():
                    continue
                state["rows"].append((tid, w, target, key))
                mark = "* " if text.strip() else "  "
                lb.insert("end", mark + w[:60])
        filt.bind("<KeyRelease>", refresh)

        def load(*_a):
            sel = lb.curselection()
            if not sel:
                return
            commit()
            tid, w, target, key = state["rows"][sel[0]]
            state["current"] = (tid, w, target, key)
            loc = h3m.text_location(self.map, tid)
            if loc:
                where.config(text=f"{w}\n(highlighted on the map)")
                self.goto_tile(loc["x"], loc["y"], loc["z"])
                win.lift()
            else:
                where.config(text=f"{w}\n(belongs to the map, not a place "
                                  f"on it)")
            txt.delete("1.0", "end")
            txt.insert("1.0", target.get(key) or "")
            txt.focus_set()
        lb.bind("<<ListboxSelect>>", load)

        def commit():
            cur = state.get("current")
            if not cur:
                return
            tid, w, target, key = cur
            new = txt.get("1.0", "end-1c")
            if new != (target.get(key) or ""):
                try:
                    h3m.edit(self.map, target, key, new, label=w)
                except h3m.EditError as e:
                    messagebox.showerror("Cannot change that text", str(e))
                    return
                self.report_pending(extra="text queued")

        def done():
            commit()
            win.destroy()

        b = tk.Frame(right, bg=PANEL)
        b.pack(fill="x", pady=(6, 0))
        tk.Button(b, text="Queue this text", command=commit, bg="#2f6f4f",
                  fg=FG, relief="flat").pack(side="left")
        tk.Button(b, text="Close", command=done, bg="#3a3a44", fg=FG,
                  relief="flat").pack(side="left", padx=8)
        refresh()

    def export_texts_file(self):
        if not self.map:
            return
        out = filedialog.asksaveasfilename(
            initialfile=f"{self._stem()}_texts.json", defaultextension=".json")
        if not out:
            return
        h3m.export_texts(self.map, out)
        self.status.config(
            text=f"Wrote {self.short_path(out)} — edit the 'text' values, "
                 f"then Edit > Import")

    def import_texts_file(self):
        if not self.map:
            return
        src = filedialog.askopenfilename(
            title="Pick the edited text file",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not src:
            return
        try:
            changes = h3m.import_texts(self.map, src)
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("Could not read that file", str(e))
            return
        if not changes:
            messagebox.showinfo("Nothing changed",
                                "No differences found against the loaded map.")
            return
        preview = "\n".join(f"• {c['where']}" for c in changes[:12])
        more = f"\n… and {len(changes) - 12} more" if len(changes) > 12 else ""
        messagebox.showinfo("Texts imported",
                            f"Queued {len(changes)} change(s):\n\n{preview}{more}"
                            "\n\nEdit > Save map as… to write them.")
        self.report_pending(extra=f"imported {len(changes)} text change(s)")

    def show_tile(self, x, y):
        lines = render.tile_info(self.map, x, y, self.level,
                               self.terrain_idx, self.tile_idx)
        for rec in self.suggestions.get((x, y, self.level), []):
            lines.append("")
            lines.append(f"BALANCE — {rec['creature']} (tier {rec['tier']})")
            now = "random" if rec["count"] == 0 else str(rec["count"])
            lines.append(f"  now {now}  →  suggested "
                         f"{rec['suggested_low']}-{rec['suggested_high']} "
                         f"(mid {rec['suggested_count']})")
            if rec["ratio"] is not None:
                lines.append(f"  {rec['status']} ({rec['ratio']}x the norm)")
            if rec.get("confidence"):
                extra = (f", reference maps vary {rec['corpus_spread']}x"
                         if rec.get("corpus_spread") else "")
                lines.append(f"  confidence: {rec['confidence']}{extra}")
            lines.append(f"  guarding: {rec['reward']} "
                         f"{rec['reward_object']}".rstrip())
            if self.guard_region:
                lines.append("  " + balance.describe_guarded(self.guard_region))
                for c in self.guard_region["contents"][:8]:
                    lines.append(f"      - {c['name']} ({c['x']},{c['y']}) "
                                 f"{c['summary'][:38]}")
            lines.append(f"  {rec['distance_to_start']} tiles from "
                         f"{rec['nearest_player']}'s start")
            flags = [f for f, on in (("ranged", rec["ranged"]),
                                     ("flying", rec["flying"])) if on]
            if flags:
                lines.append("  " + ", ".join(flags))
            lines.append(f"  basis: {rec['basis']} "
                         f"({rec['basis_samples']} corpus stacks)")
        if self.pinned:
            lines.append("")
            lines.append("— pinned, click again to unpin —")
        self.info.config(state="normal")
        self.info.delete("1.0", "end")
        self.info.insert("1.0", "\n".join(lines))
        self.info.config(state="disabled")

    # ------------------------------------------------------------------
    # exports
    # ------------------------------------------------------------------
    def _stem(self):
        return os.path.splitext(os.path.basename(self.path))[0]

    def export(self, kind):
        if not self.map:
            messagebox.showinfo("No map", "Open a map first.")
            return
        spec = {
            "objects":   (f"{self._stem()}_objects.csv", ".csv"),
            "armies":    (f"{self._stem()}_armies.csv", ".csv"),
            "texts":     (f"{self._stem()}_texts.md", ".md"),
            "terrain":   (f"{self._stem()}_terrain.csv", ".csv"),
            "full":      (f"{self._stem()}_full.json", ".json"),
            "full_slim": (f"{self._stem()}_full.json", ".json"),
            "summary":   (f"{self._stem()}_summary.txt", ".txt"),
        }[kind]
        out = filedialog.asksaveasfilename(initialfile=spec[0],
                                           defaultextension=spec[1])
        if not out:
            return
        try:
            self._write(kind, out)
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("Export failed", str(e))
            return
        self.status.config(text=f"Wrote {self.short_path(out)} "
                                f"({os.path.getsize(out) / 1000:.0f} KB)")

    def _write(self, kind, out):
        m = self.map
        if kind == "objects":
            rows = h3m.objects_table(m)
            with open(out, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader(); w.writerows(rows)
        elif kind == "armies":
            rows = h3m.armies_rows(m)
            if not rows:
                rows = [{"x": "", "y": "", "z": "", "source": "", "owner": "",
                         "creature_id": "", "creature": "", "count": "", "notes": ""}]
            with open(out, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader(); w.writerows(rows)
        elif kind == "texts":
            with open(out, "w") as f:
                f.write(h3m.texts_report(m, self.path))
        elif kind == "terrain":
            with open(out, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["x", "y", "z", "terrain", "terrain_id", "variant",
                            "river", "river_dir", "road", "road_dir", "flags"])
                for (x, y, z, t, tv, rv, rd, rt, rdd, fl) in m["terrain"]:
                    w.writerow([x, y, z,
                                h3m.TERRAIN[t] if t < len(h3m.TERRAIN) else t, t,
                                tv, h3m.RIVER[rv] if rv < len(h3m.RIVER) else rv,
                                rd, h3m.ROAD[rt] if rt < len(h3m.ROAD) else rt,
                                rdd, fl])
        elif kind in ("full", "full_slim"):
            slim = kind == "full_slim"
            ex = h3m.full_export(m, slim=slim)
            with open(out, "w") as f:
                json.dump(ex, f, indent=None if slim else 1, default=str)
        elif kind == "summary":
            with open(out, "w") as f:
                f.write(h3m.summarise(m, self.path))
        elif kind == "html":
            report.write(m, self.path or "", out,
                         suggestions=getattr(self, "_last_suggestions", None))

    def export_html(self):
        if not self.map:
            messagebox.showinfo("No map", "Open a map first.")
            return
        out = filedialog.asksaveasfilename(
            initialfile=f"{self._stem()}_report.html", defaultextension=".html")
        if not out:
            return
        self.status.config(text="Building report …")
        self.update_idletasks()
        try:
            report.write(self.map, self.path or "", out,
                         suggestions=getattr(self, "_last_suggestions", None))
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("Report failed", str(e))
            return
        self.status.config(text=f"Wrote {self.short_path(out)} "
                                f"({os.path.getsize(out)/1e6:.1f} MB)")
        if messagebox.askyesno("Report ready", "Open it in your browser?"):
            import webbrowser
            webbrowser.open("file://" + os.path.abspath(out))

    def export_pdf(self):
        """Print the HTML report to PDF with an installed browser."""
        if not self.map:
            messagebox.showinfo("No map", "Open a map first.")
            return
        if not report.find_browser():
            if not messagebox.askyesno(
                    "No browser found",
                    "No Chrome, Chromium or Edge was found to print with.\n\n"
                    "You can still get the same PDF by saving the HTML report "
                    "and using your browser's Print \u2192 Save as PDF.\n\n"
                    "Save the HTML report instead?"):
                return
            self.export_html()
            return
        out = filedialog.asksaveasfilename(
            initialfile=f"{self._stem()}_report.pdf", defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")])
        if not out:
            return
        self.status.config(text="Rendering PDF, this takes a few seconds …")
        self.update_idletasks()
        try:
            report.build_pdf(self.map, self.path or "", out,
                             suggestions=getattr(self, "_last_suggestions",
                                                 None))
        except report.PdfUnavailable as e:
            messagebox.showerror("Could not make the PDF", str(e))
            self.status.config(text="PDF failed")
            return
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("PDF failed", str(e))
            return
        self.status.config(text=f"Wrote {self.short_path(out)} "
                                f"({os.path.getsize(out) / 1e6:.1f} MB)")
        if messagebox.askyesno("PDF ready", "Open it?"):
            import webbrowser
            webbrowser.open("file://" + os.path.abspath(out))

    def export_all(self):
        if not self.map:
            messagebox.showinfo("No map", "Open a map first.")
            return
        folder = filedialog.askdirectory(title="Choose a folder for the exports")
        if not folder:
            return
        stem = self._stem()
        jobs = [("summary", f"{stem}_summary.txt"),
                ("objects", f"{stem}_objects.csv"),
                ("armies", f"{stem}_armies.csv"),
                ("texts", f"{stem}_texts.md"),
                ("terrain", f"{stem}_terrain.csv"),
                ("full_slim", f"{stem}_full.json"),
                ("html", f"{stem}_report.html")]
        written = []
        for kind, name in jobs:
            target = os.path.join(folder, name)
            try:
                self._write(kind, target)
                written.append(name)
            except Exception as e:
                traceback.print_exc()
                messagebox.showerror("Export failed", f"{name}: {e}")
                return
        self.status.config(
            text=f"Wrote {len(written)} files to {self.short_path(folder)}")
        messagebox.showinfo("Export complete",
                            "Wrote:\n\n" + "\n".join(written))

    def load_reference(self):
        paths = filedialog.askopenfilenames(
            title="Pick the maps to learn balance from",
            filetypes=[("HoMM3 maps", "*.h3m"), ("All files", "*.*")])
        if not paths:
            return
        self.status.config(text="Building balance model …")
        self.update_idletasks()
        try:
            self.model = balance.build_model(
                list(paths),
                progress=lambda s: (self.status.config(text=s),
                                    self.update_idletasks()))
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("Could not build the model", str(e))
            self.model = None
            return
        v = balance.validate_model(self.model)
        r = v["correlation"]
        self.bal_lbl.config(
            text=f"Corpus: {len(self.model['maps'])} maps, "
                 f"{self.model['sample_size']} stacks, "
                 f"{len(self.model['creature_power'])} creatures.\n"
                 f"Tier check r={r:.2f} — {v['verdict']}."
                 + ("\n\nOnly one map contributed real stacks, so treat the "
                    "curve as provisional."
                    if len({s['map'] for s in self.model['stacks']
                            if s['count'] > 0}) < 2 else ""),
            fg=FG)
        self.status.config(text=f"Model built from {len(paths)} map(s)")
        if self.map:
            self.run_balance()

    def run_balance(self):
        if not self.map:
            messagebox.showinfo("No map", "Open the map you want to check first.")
            return
        if not self.model:
            messagebox.showinfo(
                "No reference maps",
                "Load one or more reference maps first:\n"
                "Balance > Load reference maps…\n\n"
                "The more maps you feed it, the better the suggestions.")
            return
        sug = balance.suggest(self.map, self.model, self.path or "")
        self.suggestions = {}
        for rec in sug:
            self.suggestions.setdefault((rec["x"], rec["y"], rec["z"]), []).append(rec)
        self._last_suggestions = sug
        counts = {}
        for s in sug:
            counts[s["status"]] = counts.get(s["status"], 0) + 1
        self.balance_mode.set(True)
        self.draw_markers()
        summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        self.status.config(text=f"Balance: {len(sug)} stacks — {summary}")

    def export_balance(self, kind):
        if not getattr(self, "_last_suggestions", None):
            messagebox.showinfo("Nothing to export", "Run Balance > Analyse first.")
            return
        stem = self._stem()
        if kind == "report":
            out = filedialog.asksaveasfilename(
                initialfile=f"{stem}_balance.md", defaultextension=".md")
            if not out:
                return
            fair = balance.fairness(self._last_suggestions, self.map)
            with open(out, "w") as f:
                f.write(balance.report(self.map, self.model,
                                       self._last_suggestions, fair,
                                       self.path or ""))
        else:
            out = filedialog.asksaveasfilename(
                initialfile=f"{stem}_balance.csv", defaultextension=".csv")
            if not out:
                return
            with open(out, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=balance.SUGGESTION_FIELDS,
                                   extrasaction="ignore")
                w.writeheader()
                w.writerows(self._last_suggestions)
        self.status.config(text=f"Wrote {self.short_path(out)}")

    def about(self):
        messagebox.showinfo(
            "HoMM3 Map Viewer",
            "Reads Heroes of Might & Magic III maps (RoE, AB, SoD).\n\n"
            "Hover a tile to see what sits on it; click to pin.\n"
            "Ctrl + mouse wheel zooms, Tab switches surface/underground.\n\n"
            "Multi-tile objects are shown across their whole footprint, so a "
            "castle covers 5x3 tiles and its entrance tile is marked.")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    MapViewer(path).mainloop()


if __name__ == "__main__":
    main()
