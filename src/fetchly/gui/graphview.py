"""Live crawl-graph tab for the Tkinter GUI.

Renders the link graph on a tk.Canvas with a small force layout, adding
nodes as PageCrawled events arrive so the graph visibly grows during the
crawl. Pure stdlib — the vendored force-graph library is only used by the
HTML export (viz.py).

The physics lives in module-level functions operating on plain dicts so it
can be unit-tested without a display.
"""

import math
import random
import tkinter as tk
import webbrowser
from tkinter import ttk
from urllib.parse import urlparse

from ..viz import STATUS_COLORS, _label, _status
from .theme import PALETTE

SPRING_LENGTH = 60.0
SPRING_K = 0.02
REPULSION = 1800.0
CENTER_PULL = 0.002
DAMPING = 0.85
SETTLED_SPEED = 0.08     # below this max speed the layout is considered cool
HEAT_TICKS = 150         # how long a touched node keeps simulating
FULL_SIM_LIMIT = 300     # up to here every node stays hot
PHYSICS_LIMIT = 1000     # above here new nodes are just placed, no physics

ROOT_OUTLINE = "#e0a800"    # gold ring marking the start-URL / main-domain node
GLOW_COLOR = "#1f8fff"      # activity ripple on just-crawled nodes (not a status hue)
GLOW_TICKS = 24             # ripple lifetime, in glow ticks
GLOW_MS = 55                # ripple tick interval

# Palette lookups happen at draw time (not import time) so the graph follows
# a light/dark theme switch; restyle() recolors items already on the canvas.


def _bg():
    return PALETTE["canvas"]   # canvas background; node outlines blend into it


def _edge_color():
    return PALETTE["border"]


def spawn_position(parent, k):
    """Position for the k-th child of a node (or of the origin if None)."""
    golden = 2.399963  # radians; fans children out without overlap
    angle = k * golden
    r = SPRING_LENGTH * (0.6 + 0.15 * (k % 5))
    px, py = (parent["x"], parent["y"]) if parent else (0.0, 0.0)
    return (px + math.cos(angle) * r + random.uniform(-4, 4),
            py + math.sin(angle) * r + random.uniform(-4, 4))


def step_layout(nodes, edges, hot):
    """Advance the simulation one tick for the nodes in `hot` (indices).

    Returns the max speed among simulated nodes (0.0 if none).
    """
    if not hot:
        return 0.0
    fx = {i: 0.0 for i in hot}
    fy = {i: 0.0 for i in hot}
    for i in hot:
        a = nodes[i]
        for j, b in enumerate(nodes):
            if i == j:
                continue
            dx, dy = a["x"] - b["x"], a["y"] - b["y"]
            d2 = dx * dx + dy * dy + 0.01
            f = min(REPULSION / d2, 6.0)
            d = math.sqrt(d2)
            fx[i] += dx / d * f
            fy[i] += dy / d * f
    for s, t in edges:
        if s not in fx and t not in fx:
            continue
        a, b = nodes[s], nodes[t]
        dx, dy = b["x"] - a["x"], b["y"] - a["y"]
        d = math.sqrt(dx * dx + dy * dy) + 0.01
        f = (d - SPRING_LENGTH) * SPRING_K
        if s in fx:
            fx[s] += dx / d * f
            fy[s] += dy / d * f
        if t in fx:
            fx[t] -= dx / d * f
            fy[t] -= dy / d * f
    top = 0.0
    for i in hot:
        n = nodes[i]
        n["vx"] = (n["vx"] + fx[i] - n["x"] * CENTER_PULL) * DAMPING
        n["vy"] = (n["vy"] + fy[i] - n["y"] * CENTER_PULL) * DAMPING
        n["x"] += n["vx"]
        n["y"] += n["vy"]
        top = max(top, abs(n["vx"]), abs(n["vy"]))
    return top


def node_radius(deg):
    return 4.0 + 1.6 * math.sqrt(min(deg, 60))


def _mix(hex_a, hex_b, t):
    """Blend two #rrggbb colors; t=1 returns a, t=0 returns b."""
    a = [int(hex_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(hex_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(
        round(a[k] * t + b[k] * (1 - t)) for k in range(3))


class GraphView(ttk.Frame):
    """Canvas widget showing the crawl graph live."""

    TICK_MS = 50

    def __init__(self, parent):
        super().__init__(parent)
        header = ttk.Frame(self)
        header.pack(fill="x", padx=6, pady=(6, 2))
        self._domain_var = tk.StringVar(value="")
        self._legend_marks = []
        root_dot = tk.Label(header, text="◉", fg=ROOT_OUTLINE, bg=PALETTE["bg"])
        root_dot.pack(side="left")
        self._legend_marks.append(root_dot)
        ttk.Label(header, textvariable=self._domain_var,
                  font=("TkDefaultFont", 9, "bold")).pack(side="left", padx=(2, 14))
        self._count_vars = {}
        for status, color in STATUS_COLORS.items():
            dot = tk.Label(header, text="●", fg=color, bg=PALETTE["bg"])
            dot.pack(side="left")
            self._legend_marks.append(dot)
            var = tk.StringVar(value=f"{status} 0")
            ttk.Label(header, textvariable=var).pack(side="left", padx=(0, 10))
            self._count_vars[status] = var
        ttk.Button(header, text="Fit", width=4, command=self._fit).pack(side="right")
        ttk.Label(header, text="scroll: zoom · drag: pan/move · "
                  "double-click: open").pack(side="right", padx=8)

        self.canvas = tk.Canvas(self, background=_bg(), highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self._readout = tk.StringVar()
        ttk.Label(self, textvariable=self._readout, font=("TkFixedFont", 9)
                  ).pack(fill="x", padx=6, pady=(0, 4))

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", self._on_double)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<MouseWheel>", self._on_wheel)          # Windows/macOS
        self.canvas.bind("<Button-4>", lambda e: self._zoom(e, 1.15))  # X11
        self.canvas.bind("<Button-5>", lambda e: self._zoom(e, 1 / 1.15))
        self.canvas.bind("<Configure>", self._on_configure, add="+")
        self.reset()

    # ---- data ----------------------------------------------------------

    def reset(self):
        self.nodes = []
        self.edges = []
        self._index = {}          # url -> node index
        self._children = {}       # node index -> child count (for spawning)
        self._hot = {}            # node index -> remaining heat ticks
        self._item_node = {}      # canvas oval id -> node index
        self._edge_by_line = {}   # canvas line id -> (source idx, target idx)
        self._counts = dict.fromkeys(STATUS_COLORS, 0)
        self._drag_node = None
        self._dragging_bg = False
        self._hover = None
        self._label_items = ()
        self._autofit = True
        self._zoom_level = 1.0
        self._ox = self._oy = 0.0   # world origin offset (screen px)
        self._running = False
        self._root_idx = None       # the start-URL node (main domain)
        self._root_label = None     # persistent canvas label on the root node
        self._glowing = {}          # idx -> remaining glow ticks (activity ripple)
        self._glow_running = False
        self._empty_item = None     # centered "no data yet" hint
        self.canvas.delete("all")
        self._show_empty()
        for status, var in self._count_vars.items():
            var.set(f"{status} 0")
        self._domain_var.set("")
        self._readout.set("")

    def _show_empty(self):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        # An unmapped Tk canvas reports 1, not 0 — fall back so the hint isn't
        # jammed into the corner (the <Configure> handler recenters it later).
        w = w if w > 1 else 800
        h = h if h > 1 else 600
        self._empty_item = self.canvas.create_text(
            w / 2, h / 2, justify="center", fill=PALETTE["muted"],
            font=("TkDefaultFont", 11),
            text="The link graph grows here as pages are crawled.")

    def _on_configure(self, _event=None):
        if self._empty_item is not None:
            self.canvas.coords(self._empty_item,
                               self.canvas.winfo_width() / 2,
                               self.canvas.winfo_height() / 2)

    def add_result(self, result, glow=True):
        if result.url in self._index:
            return
        if self._empty_item is not None:
            self.canvas.delete(self._empty_item)
            self._empty_item = None
        idx = len(self.nodes)
        pidx = self._index.get(result.found_on)
        parent = self.nodes[pidx] if pidx is not None else None
        k = self._children.get(pidx, 0)
        self._children[pidx] = k + 1
        x, y = spawn_position(parent, k)
        status = _status(result)
        node = {"x": x, "y": y, "vx": 0.0, "vy": 0.0, "url": result.url,
                "label": _label(result.url), "status": status, "deg": 0,
                "oval": None, "lines": [], "glow_item": None}
        self.nodes.append(node)
        self._index[result.url] = idx
        self._counts[status] += 1
        self._count_vars[status].set(f"{status} {self._counts[status]}")

        # First page with no discoverer is the start URL: mark it the main domain.
        is_root = pidx is None and self._root_idx is None
        if is_root:
            self._root_idx = idx
            self._domain_var.set(urlparse(result.url).netloc or result.url)

        if pidx is not None:
            line = self.canvas.create_line(0, 0, 0, 0, fill=_edge_color())
            self.canvas.tag_lower(line)
            self.edges.append((pidx, idx, line))
            self._edge_by_line[line] = (pidx, idx)
            parent["lines"].append(line)
            node["lines"].append(line)
            parent["deg"] += 1
            self._resize_oval(pidx)
        outline, width = (ROOT_OUTLINE, 3) if is_root else (_bg(), 1)
        oval = self.canvas.create_oval(0, 0, 0, 0, fill=STATUS_COLORS[status],
                                       outline=outline, width=width)
        node["oval"] = oval
        self._item_node[oval] = idx
        if is_root:
            self._root_label = self.canvas.create_text(
                0, 0, text=self._domain_var.get(), anchor="s",
                fill=PALETTE["text"], font=("TkDefaultFont", 10, "bold"))
        self._place(idx)
        if glow:
            self._start_glow(idx)

        if len(self.nodes) <= PHYSICS_LIMIT:
            self._heat(idx)
            if pidx is not None:
                self._heat(pidx)
            self._ensure_running()

    def load(self, results):
        self.reset()
        for r in results:
            self.add_result(r, glow=False)

    # ---- simulation ----------------------------------------------------

    def _heat(self, idx):
        if len(self.nodes) <= FULL_SIM_LIMIT:
            for i in range(len(self.nodes)):
                self._hot[i] = HEAT_TICKS
        else:
            self._hot[idx] = HEAT_TICKS

    def _ensure_running(self):
        if not self._running:
            self._running = True
            self.after(self.TICK_MS, self._tick)

    def _tick(self):
        if not self.winfo_exists():
            return
        hot = [i for i, t in self._hot.items() if t > 0 and
               self.nodes[i] is not self._drag_node]
        edges = [(s, t) for s, t, _line in self.edges]
        top = step_layout(self.nodes, edges, hot)
        for i in hot:
            self._hot[i] -= 1
            self._place(i)
        if self._autofit:
            self._fit(animate=False)
        if hot and top > SETTLED_SPEED:
            self.after(self.TICK_MS, self._tick)
        else:
            self._hot.clear()
            self._running = False

    # ---- activity ripple ("crawler is here") ---------------------------

    def _start_glow(self, idx):
        n = self.nodes[idx]
        if n["glow_item"] is None:
            n["glow_item"] = self.canvas.create_oval(
                0, 0, 0, 0, outline=GLOW_COLOR, width=2, fill="")
        self._glowing[idx] = GLOW_TICKS
        self._position_glow(idx)
        if not self._glow_running:
            self._glow_running = True
            self.after(GLOW_MS, self._glow_tick)

    def _position_glow(self, idx):
        n = self.nodes[idx]
        item = n["glow_item"]
        if item is None:
            return
        frac = self._glowing.get(idx, 0) / GLOW_TICKS   # 1 (new) -> 0 (faded)
        sx, sy = self._screen(n["x"], n["y"])
        r = node_radius(n["deg"]) * math.sqrt(self._zoom_level) + 4 + (1 - frac) * 14
        self.canvas.coords(item, sx - r, sy - r, sx + r, sy + r)
        self.canvas.itemconfigure(item, outline=_mix(GLOW_COLOR, _bg(), frac),
                                  width=max(1.0, 2.5 * frac + 0.5))

    def _glow_tick(self):
        if not self.winfo_exists():
            return
        for idx in list(self._glowing):
            self._glowing[idx] -= 1
            if self._glowing[idx] <= 0:
                del self._glowing[idx]
                item = self.nodes[idx]["glow_item"]
                if item is not None:
                    self.canvas.delete(item)
                    self.nodes[idx]["glow_item"] = None
            else:
                self._position_glow(idx)
        if self._glowing:
            self.after(GLOW_MS, self._glow_tick)
        else:
            self._glow_running = False

    # ---- rendering -----------------------------------------------------

    def _screen(self, x, y):
        return (self._ox + x * self._zoom_level, self._oy + y * self._zoom_level)

    def _world(self, sx, sy):
        return ((sx - self._ox) / self._zoom_level, (sy - self._oy) / self._zoom_level)

    def _place(self, idx):
        n = self.nodes[idx]
        sx, sy = self._screen(n["x"], n["y"])
        r = node_radius(n["deg"]) * math.sqrt(self._zoom_level)
        self.canvas.coords(n["oval"], sx - r, sy - r, sx + r, sy + r)
        for line in n["lines"]:
            s, t = self._edge_by_line[line]
            a, b = self.nodes[s], self.nodes[t]
            ax, ay = self._screen(a["x"], a["y"])
            bx, by = self._screen(b["x"], b["y"])
            self.canvas.coords(line, ax, ay, bx, by)
        if n["glow_item"] is not None:
            self._position_glow(idx)
        if idx == self._root_idx:
            self._position_root_label()

    def _position_root_label(self):
        if self._root_idx is None or self._root_label is None:
            return
        n = self.nodes[self._root_idx]
        sx, sy = self._screen(n["x"], n["y"])
        r = node_radius(n["deg"]) * math.sqrt(self._zoom_level)
        self.canvas.coords(self._root_label, sx, sy - r - 4)
        self.canvas.tag_raise(self._root_label)

    def _redraw_all(self):
        for s, t, line in self.edges:
            a, b = self.nodes[s], self.nodes[t]
            ax, ay = self._screen(a["x"], a["y"])
            bx, by = self._screen(b["x"], b["y"])
            self.canvas.coords(line, ax, ay, bx, by)
        for i, n in enumerate(self.nodes):
            sx, sy = self._screen(n["x"], n["y"])
            r = node_radius(n["deg"]) * math.sqrt(self._zoom_level)
            self.canvas.coords(n["oval"], sx - r, sy - r, sx + r, sy + r)
        for idx in self._glowing:
            self._position_glow(idx)
        self._position_root_label()

    def _resize_oval(self, idx):
        n = self.nodes[idx]
        sx, sy = self._screen(n["x"], n["y"])
        r = node_radius(n["deg"]) * math.sqrt(self._zoom_level)
        self.canvas.coords(n["oval"], sx - r, sy - r, sx + r, sy + r)

    def _fit(self, animate=True):
        if not self.nodes:
            return
        # Before the canvas is mapped, winfo_*() report 1, not 0; fall back to
        # a sane size so the fit math never yields a negative zoom.
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w <= 1 or h <= 1:
            w, h = 800, 600
        xs = [n["x"] for n in self.nodes]
        ys = [n["y"] for n in self.nodes]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        span = max(x1 - x0, y1 - y0, 1.0)
        self._zoom_level = max(0.05, min((w - 60) / span, (h - 60) / span, 2.0))
        self._ox = w / 2 - (x0 + x1) / 2 * self._zoom_level
        self._oy = h / 2 - (y0 + y1) / 2 * self._zoom_level
        if animate:
            self._autofit = True
        self._redraw_all()

    # ---- interaction ---------------------------------------------------

    def _node_at(self, sx, sy):
        for item in self.canvas.find_overlapping(sx - 2, sy - 2, sx + 2, sy + 2):
            if item in self._item_node:
                return self._item_node[item]
        return None

    def _zoom(self, event, factor):
        self._autofit = False
        wx, wy = self._world(event.x, event.y)
        self._zoom_level = max(0.05, min(self._zoom_level * factor, 8.0))
        self._ox = event.x - wx * self._zoom_level
        self._oy = event.y - wy * self._zoom_level
        self._redraw_all()

    def _on_wheel(self, event):
        self._zoom(event, 1.15 if event.delta > 0 else 1 / 1.15)

    def _on_press(self, event):
        idx = self._node_at(event.x, event.y)
        if idx is not None:
            self._drag_node = self.nodes[idx]
            self._drag_idx = idx
        else:
            self._dragging_bg = True
        self._last = (event.x, event.y)

    def _on_drag(self, event):
        dx, dy = event.x - self._last[0], event.y - self._last[1]
        self._last = (event.x, event.y)
        if self._drag_node is not None:
            n = self._drag_node
            n["x"] += dx / self._zoom_level
            n["y"] += dy / self._zoom_level
            n["vx"] = n["vy"] = 0.0
            self._place(self._drag_idx)
            if len(self.nodes) <= PHYSICS_LIMIT:
                self._heat(self._drag_idx)
                self._ensure_running()
        elif self._dragging_bg:
            self._autofit = False
            self._ox += dx
            self._oy += dy
            self._redraw_all()

    def _on_release(self, _event):
        self._drag_node = None
        self._dragging_bg = False

    def _on_double(self, event):
        idx = self._node_at(event.x, event.y)
        if idx is not None:
            webbrowser.open(self.nodes[idx]["url"])

    def _on_motion(self, event):
        if self._drag_node is not None or self._dragging_bg:
            return
        idx = self._node_at(event.x, event.y)
        if idx == self._hover:
            return
        # un-highlight previous hover
        if self._hover is not None and self._hover < len(self.nodes):
            for line in self.nodes[self._hover]["lines"]:
                self.canvas.itemconfigure(line, fill=_edge_color(), width=1)
        for item in self._label_items:
            self.canvas.delete(item)
        self._label_items = ()
        self._hover = idx
        if idx is None:
            self._readout.set("")
            self.canvas.configure(cursor="")
            return
        n = self.nodes[idx]
        self._readout.set(f"{n['status']} — {n['url']}")
        self.canvas.configure(cursor="hand2")
        for line in n["lines"]:
            self.canvas.itemconfigure(line, fill=PALETTE["muted"], width=2)
            self.canvas.tag_raise(line)
            self.canvas.tag_raise(n["oval"])
        sx, sy = self._screen(n["x"], n["y"])
        r = node_radius(n["deg"]) * math.sqrt(self._zoom_level)
        text = self.canvas.create_text(sx + r + 4, sy, text=n["label"],
                                       anchor="w", fill=PALETTE["text"],
                                       font=("TkDefaultFont", 9))
        box = self.canvas.create_rectangle(self.canvas.bbox(text),
                                           fill=PALETTE["surface"],
                                           outline=PALETTE["border"])
        self.canvas.tag_raise(text, box)
        self._label_items = (box, text)

    def restyle(self):
        """Re-apply palette colors after a light/dark theme switch."""
        self.canvas.configure(background=_bg())
        for mark in self._legend_marks:
            mark.configure(bg=PALETTE["bg"])
        for line in self._edge_by_line:
            self.canvas.itemconfigure(line, fill=_edge_color(), width=1)
        self._hover = None                       # hover colors were reset above
        for item in self._label_items:
            self.canvas.delete(item)
        self._label_items = ()
        for oval, idx in self._item_node.items():
            if idx != self._root_idx:
                self.canvas.itemconfigure(oval, outline=_bg())
        if self._root_label is not None:
            self.canvas.itemconfigure(self._root_label, fill=PALETTE["text"])
        if self._empty_item is not None:
            self.canvas.itemconfigure(self._empty_item, fill=PALETTE["muted"])
