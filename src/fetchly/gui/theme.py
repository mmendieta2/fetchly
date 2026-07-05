"""Visual theme for the Fetchly GUI.

Tkinter's default ttk theme looks dated and inconsistent across platforms.
This module layers a small, self-contained design system on top of the
built-in ``clam`` theme: one cohesive light palette, a clean UI font picked
from what the system actually has, and restyled ttk widgets (accent primary
button, flat cards, quieter tables and tabs).

Everything here is pure stdlib Tk — no extra dependencies. Call
``apply_theme(root)`` once after creating the root window; other GUI modules
import :data:`PALETTE` and :data:`FONTS` so the whole app shares one look.
"""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# -- palette --------------------------------------------------------------
# A soft, cool light theme. Kept in one dict so colors are referenced by
# meaning (surface, accent, …) instead of scattered hex literals.
PALETTE = {
    "bg": "#e4e8ee",          # window background (slightly deep to cut glare)
    "surface": "#fbfcfe",     # entries, tables, cards (off-white, not stark)
    "surface_alt": "#e9edf2",  # striped rows, headings, hovers
    "border": "#c3ccd6",      # hairline borders
    "border_strong": "#93a0b0",  # button outlines — visible against bg and fill
    "text": "#161c24",        # primary text (near-black slate, strong contrast)
    "muted": "#454f5e",       # secondary / hint text (darkened for readability)
    "disabled_fg": "#8a95a4",  # text on disabled controls (dimmed but legible)
    "accent": "#245bd0",      # primary action, focus, selection accent
    "accent_hover": "#1f4fbb",
    "accent_active": "#1a44a3",
    "on_accent": "#ffffff",
    "select": "#cfe0fb",      # table row selection background
    "error": "#b23025",       # error rows / severity (text-tuned deep red)
    "warning": "#9a6410",     # warning rows / severity (text-tuned amber)
    "canvas": "#eef1f5",      # graph canvas background
    # Status hues shared with the Graph tab (viz.STATUS_COLORS) and the
    # root/main-domain marker, so the Pages table and the graph agree at a
    # glance. Kept verbatim from viz.py / graphview.py.
    "gold": "#e0a800",             # start-URL / main-domain marker
    "status_ok": "#0ca30c",        # 2xx pages (graph "ok")
    "status_redirect": "#fab219",  # redirected pages (graph "redirect")
    "status_broken": "#d03b3b",    # 4xx/5xx / errors (graph "broken")
}

# One vertical/horizontal rhythm for the whole GUI, referenced by name so
# padding is consistent instead of ad-hoc per widget.
SPACING = {"xs": 2, "sm": 4, "md": 8, "lg": 12, "xl": 16}

# Preferred UI font families, best first; the first one the system actually
# has installed wins. Falls back to whatever TkDefaultFont resolves to.
_FONT_CANDIDATES = (
    "Segoe UI", "SF Pro Text", "Helvetica Neue", "Inter",
    "Cantarell", "Noto Sans", "Ubuntu", "DejaVu Sans",
)

# Filled in by apply_theme(); other modules read this for tk (non-ttk) widgets.
FONTS = {"family": "TkDefaultFont", "base": 10}

# Tk discards PhotoImages with no live reference, which would blank the tab
# backgrounds; keep them alive for the process lifetime here.
_TAB_IMAGES = []


def _tab_image(root, fill, underline=None, w=16, h=30, uh=3):
    """A tiny tab-background image: solid *fill*, optional accent *underline*
    band along the bottom. Stretched as a 9-slice so the underline stays a
    fixed height at any tab width (see the border= in element_create)."""
    img = tk.PhotoImage(master=root, width=w, height=h)
    img.put(fill, to=(0, 0, w, h))
    if underline:
        img.put(underline, to=(0, h - uh, w, h))
    _TAB_IMAGES.append(img)
    return img


def _pick_family() -> str:
    available = {f.lower() for f in tkfont.families()}
    for name in _FONT_CANDIDATES:
        if name.lower() in available:
            return name
    return tkfont.nametofont("TkDefaultFont").actual("family")


def _set_fonts(root) -> None:
    family = _pick_family()
    FONTS["family"] = family
    sizes = {
        "TkDefaultFont": 10, "TkTextFont": 10, "TkMenuFont": 10,
        "TkHeadingFont": 10, "TkTooltipFont": 9, "TkSmallCaptionFont": 9,
        "TkIconFont": 10,
    }
    for name, size in sizes.items():
        try:
            f = tkfont.nametofont(name)
            f.configure(family=family, size=size)
        except Exception:
            pass


def apply_theme(root) -> dict:
    """Apply the Fetchly look to *root* and return the palette."""
    p = PALETTE
    _set_fonts(root)
    root.configure(background=p["bg"])
    # Tk's option database styles the non-ttk widgets (Menu, Text, Toplevel).
    root.option_add("*background", p["bg"])
    root.option_add("*Menu.activeBackground", p["accent"])
    root.option_add("*Menu.activeForeground", p["on_accent"])

    style = ttk.Style(root)
    style.theme_use("clam")
    family = FONTS["family"]
    bold = (family, 10, "bold")

    style.configure(".", background=p["bg"], foreground=p["text"],
                    fieldbackground=p["surface"], bordercolor=p["border"],
                    focuscolor=p["accent"], font=(family, 10))

    style.configure("TFrame", background=p["bg"])
    style.configure("Card.TFrame", background=p["surface"])
    style.configure("TLabel", background=p["bg"], foreground=p["text"])
    style.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"])
    style.configure("Title.TLabel", background=p["bg"], foreground=p["text"],
                    font=(family, 16, "bold"))
    style.configure("Subtitle.TLabel", background=p["bg"], foreground=p["muted"],
                    font=(family, 10))

    style.configure("TLabelframe", background=p["bg"], bordercolor=p["border"],
                    relief="solid", borderwidth=1, padding=8)
    style.configure("TLabelframe.Label", background=p["bg"],
                    foreground=p["muted"], font=bold)

    # Entries: white field, hairline border that lights up accent on focus.
    style.configure("TEntry", fieldbackground=p["surface"], foreground=p["text"],
                    bordercolor=p["border"], lightcolor=p["border"],
                    darkcolor=p["border"], insertcolor=p["text"],
                    padding=4, relief="flat")
    style.map("TEntry",
              bordercolor=[("focus", p["accent"])],
              lightcolor=[("focus", p["accent"])],
              darkcolor=[("focus", p["accent"])])

    # Default (secondary) button: white fill with a clearly visible outline so
    # it reads as a button on the grey background. Border turns accent on hover.
    # Disabled keeps the fill and outline (just dimmed text + a lighter border)
    # so a greyed-out button still plainly looks like a button, not empty space.
    style.configure("TButton", background=p["surface"], foreground=p["text"],
                    bordercolor=p["border_strong"], lightcolor=p["border_strong"],
                    darkcolor=p["border_strong"], relief="flat", borderwidth=1,
                    padding=(14, 7), focusthickness=0)
    style.map("TButton",
              background=[("disabled", p["surface"]),
                          ("pressed", p["surface_alt"]),
                          ("active", p["surface_alt"])],
              foreground=[("disabled", p["disabled_fg"])],
              bordercolor=[("disabled", p["border"]),
                           ("pressed", p["accent"]), ("active", p["accent"])],
              lightcolor=[("disabled", p["border"]),
                          ("pressed", p["accent"]), ("active", p["accent"])],
              darkcolor=[("disabled", p["border"]),
                         ("pressed", p["accent"]), ("active", p["accent"])])

    # Primary button: solid accent, white text. When disabled it stays a filled,
    # outlined button (a desaturated blue-grey) so it keeps its button shape.
    style.configure("Accent.TButton", background=p["accent"],
                    foreground=p["on_accent"], bordercolor=p["accent"],
                    lightcolor=p["accent"], darkcolor=p["accent"],
                    relief="flat", borderwidth=1, padding=(16, 7), font=bold)
    style.map("Accent.TButton",
              background=[("disabled", "#b6c1d3"),
                          ("pressed", p["accent_active"]),
                          ("active", p["accent_hover"])],
              foreground=[("disabled", "#54607a")],
              bordercolor=[("disabled", "#9aa6bd"),
                           ("pressed", p["accent_active"]),
                           ("active", p["accent_hover"])],
              lightcolor=[("disabled", "#b6c1d3"),
                          ("pressed", p["accent_active"]),
                          ("active", p["accent_hover"])],
              darkcolor=[("disabled", "#b6c1d3"),
                         ("pressed", p["accent_active"]),
                         ("active", p["accent_hover"])])

    style.configure("TCheckbutton", background=p["bg"], foreground=p["text"],
                    focusthickness=0, padding=2, indicatorforeground=p["on_accent"],
                    indicatorbackground=p["surface"], bordercolor=p["border"])
    style.map("TCheckbutton",
              background=[("active", p["bg"])],
              indicatorbackground=[("selected", p["accent"]),
                                   ("active", p["surface_alt"])],
              bordercolor=[("selected", p["accent"])],
              foreground=[("disabled", p["muted"])])

    # Notebook: the client area is a bordered panel; tabs are grey chips with
    # the active one raised to white and marked by a themed accent underline
    # along its bottom edge. Every state shares one size, padding, and font —
    # only the fill and underline change, so nothing shifts on select.
    uh = 3
    normal_img = _tab_image(root, p["surface_alt"])
    hover_img = _tab_image(root, p["border"])
    sel_img = _tab_image(root, p["surface"], p["accent"], uh=uh)
    try:
        style.element_create("Fetchly.Tab", "image", normal_img,
                             ("selected", sel_img),
                             ("active", "!selected", hover_img),
                             border=(2, 2, 2, uh), sticky="nswe")
    except tk.TclError:
        pass  # element persists across repeat apply_theme() calls
    style.layout("TNotebook.Tab", [
        ("Fetchly.Tab", {"sticky": "nswe", "children": [
            ("Notebook.padding", {"side": "top", "sticky": "nswe", "children": [
                ("Notebook.label", {"side": "top", "sticky": ""})]})]})])
    style.configure("TNotebook", background=p["bg"], borderwidth=1,
                    bordercolor=p["border"], lightcolor=p["border"],
                    darkcolor=p["border"], tabmargins=(3, 3, 3, 0))
    style.configure("TNotebook.Tab", padding=(16, 8), font=(family, 10),
                    foreground=p["muted"])
    # clam's own map raises (expands) the selected tab; force it flat so tabs
    # never change size between states.
    style.map("TNotebook.Tab",
              foreground=[("selected", p["text"]), ("active", p["text"])],
              expand=[("selected", (0, 0, 0, 0)), ("active", (0, 0, 0, 0))],
              padding=[("selected", (16, 8)), ("active", (16, 8))])

    # Tables: white surface, taller rows, quiet flat headings, blue selection.
    style.configure("Treeview", background=p["surface"],
                    fieldbackground=p["surface"], foreground=p["text"],
                    bordercolor=p["border"], borderwidth=0, rowheight=26,
                    font=(family, 10))
    style.map("Treeview",
              background=[("selected", p["select"])],
              foreground=[("selected", p["text"])])
    style.configure("Treeview.Heading", background=p["surface_alt"],
                    foreground=p["muted"], relief="flat", borderwidth=0,
                    padding=(8, 6), font=bold)
    style.map("Treeview.Heading",
              background=[("active", p["border"])])

    # Scrollbars: thin, no arrows, neutral thumb.
    for orient in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(orient, background=p["surface_alt"], troughcolor=p["bg"],
                        bordercolor=p["bg"], arrowcolor=p["muted"],
                        relief="flat", borderwidth=0)
        style.map(orient, background=[("active", p["border"])])

    return p
