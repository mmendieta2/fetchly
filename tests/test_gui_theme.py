"""Light/dark theme tests: palette parity, system detection, runtime toggle.

Follows the headless tkinter pattern from test_gui_compare.py (importorskip +
skip when no display).
"""

import pytest


@pytest.fixture
def app():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    from fetchly.gui.theme import apply_theme
    from fetchly.gui.app import FetchlyApp
    apply_theme(root)
    app = FetchlyApp(root)
    yield app
    root.destroy()


def test_palettes_have_identical_keys():
    from fetchly.gui import theme
    assert set(theme.LIGHT) == set(theme.DARK)


def test_detect_system_mode_returns_valid_value():
    from fetchly.gui.theme import detect_system_mode
    assert detect_system_mode() in ("light", "dark")


def test_apply_theme_dark_mutates_palette_in_place(app):
    from tkinter import ttk
    from fetchly.gui import theme

    palette_ref = theme.PALETTE          # importers hold this exact object
    theme.apply_theme(app.root, mode="dark")
    assert theme.current_mode() == "dark"
    assert theme.PALETTE is palette_ref
    assert theme.PALETTE["bg"] == theme.DARK["bg"]
    style = ttk.Style(app.root)
    assert style.lookup("TFrame", "background") == theme.DARK["bg"]


def test_checkbutton_focus_on_indicator_not_label(app):
    # clam draws a ring hugging the label text via the Checkbutton.focus
    # element; the theme drops it and marks focus on the indicator border.
    from fetchly.gui.theme import PALETTE
    layout = str(app.root.tk.call("ttk::style", "layout", "TCheckbutton"))
    assert "focus" not in layout
    mapping = str(app.root.tk.call("ttk::style", "map", "TCheckbutton",
                                   "-upperbordercolor"))
    assert PALETTE["accent"] in mapping


def test_toggle_flips_mode_and_restyles_widgets(app):
    from fetchly.gui import theme

    start = theme.current_mode()
    app._toggle_theme()
    flipped = theme.current_mode()
    assert flipped != start
    expected = theme.DARK if flipped == "dark" else theme.LIGHT
    assert str(app.tree.tag_configure("odd", "background")) == expected["surface"]
    assert str(app._spinner.cget("foreground")) == expected["accent"]
    assert str(app.graph_view.canvas.cget("background")) == expected["canvas"]
    label = "☀  Light" if flipped == "dark" else "☾  Dark"
    assert str(app.theme_btn.cget("text")) == label

    app._toggle_theme()                  # and back
    assert theme.current_mode() == start
