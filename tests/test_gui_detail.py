"""Issue-detail popup and entry-keybinding tests.

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


def _descendants(widget, cls):
    found = []
    for child in widget.winfo_children():
        if isinstance(child, cls):
            found.append(child)
        found.extend(_descendants(child, cls))
    return found


def test_issue_detail_popup_full_text_and_severity_badge(app):
    import tkinter as tk

    long_detail = "broken link to https://example.com/" + "x" * 300
    row = app.issues_tree.insert(
        "", "end", values=("error", "broken_link", "https://s.com/a", long_detail))
    app.issues_tree.selection_set(row)
    app.issues_tree.focus(row)

    class Event:
        widget = app.issues_tree
    app._show_issue_detail(Event())

    wins = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)]
    assert len(wins) == 1
    body = _descendants(wins[0], tk.Text)[0].get("1.0", "end")
    assert long_detail in body            # value shown untruncated
    assert "DETAIL" in body               # field labels rendered small-caps
    badges = [lbl for lbl in _descendants(wins[0], tk.Label)
              if "ERROR" in str(lbl.cget("text"))]
    assert badges                         # severity badge present
    wins[0].destroy()


def test_pages_row_popup_with_status_badge(app):
    import tkinter as tk

    row = app.tree.insert("", "end", values=(
        "404", "1", "230", "", "Old pricing", "https://s.com/old-pricing"))
    app.tree.selection_set(row)
    app.tree.focus(row)

    class Event:
        widget = app.tree
    app._show_issue_detail(Event())

    wins = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)]
    assert len(wins) == 1
    body = _descendants(wins[0], tk.Text)[0].get("1.0", "end")
    assert "https://s.com/old-pricing" in body
    assert "TITLE" in body
    badges = [lbl for lbl in _descendants(wins[0], tk.Label)
              if "HTTP 404" in str(lbl.cget("text"))]
    assert badges
    wins[0].destroy()


def test_pages_tree_opens_popup_on_double_click_binding(app):
    assert app.tree.bind("<Double-1>")
    assert app.tree.bind("<Return>")


def test_treeview_item_layout_has_no_focus_ring(app):
    # Tk 8.6 (Windows) draws a dotted focus rectangle via the Treeitem.focus
    # element; the theme rebuilds the item layout without it.
    layout = str(app.root.tk.call("ttk::style", "layout", "Treeview.Item"))
    assert "focus" not in layout


def test_treeview_border_does_not_darken_on_focus(app):
    # clam ships a `focus -> #4a6984` bordercolor map that outlines the whole
    # table in near-black when it has keyboard focus; the theme pins the
    # hairline border color in every state.
    from fetchly.gui.theme import PALETTE
    mapping = str(app.root.tk.call("ttk::style", "map", "Treeview", "-bordercolor"))
    assert "#4a6984" not in mapping
    assert PALETTE["border"] in mapping


def test_enter_in_url_entry_starts_crawl(app):
    assert app.url_entry.bind("<Return>")
    calls = []
    app._start = lambda: calls.append(1)
    app._start_from_entry()                       # empty box -> ignored
    assert calls == []
    app.url_var.set("example.com")
    app._start_from_entry()
    assert calls == [1]
    app.start_btn.configure(state="disabled")     # crawl running
    app._start_from_entry()
    assert calls == [1]                           # no restart mid-crawl


def test_empty_url_shows_styled_error_dialog(app):
    import tkinter as tk

    app.url_var.set("   ")
    app._start()

    assert app.engine is None                     # nothing started
    wins = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)]
    assert len(wins) == 1
    assert wins[0].title() == "No start URL"
    from tkinter import ttk
    buttons = [b for b in _descendants(wins[0], ttk.Button)
               if b.cget("text") == "OK"]
    assert buttons and str(buttons[0].cget("style")) == "Accent.TButton"
    badges = [lbl for lbl in _descendants(wins[0], tk.Label)
              if "ERROR" in str(lbl.cget("text"))]
    assert badges                                 # header badge, detail-popup style
    wins[0].destroy()


def test_command_bindings_gated_to_macos(app):
    # On Windows Tk the Command modifier does not exist, so <Command-y>
    # degrades to a plain "y" binding whose "break" swallows the letter.
    import tkinter as tk
    from tkinter import ttk
    from fetchly.gui.app import EntryHistory

    var = tk.StringVar()
    entry = ttk.Entry(app.root, textvariable=var)
    EntryHistory(entry, var)
    aqua = app.root.tk.call("tk", "windowingsystem") == "aqua"
    for seq in ("<Command-z>", "<Command-y>", "<Command-Shift-Z>"):
        assert bool(entry.bind(seq)) == aqua
    assert entry.bind("<Control-z>")
    assert entry.bind("<Control-y>")
    assert entry.bind("<Control-Shift-Z>")
