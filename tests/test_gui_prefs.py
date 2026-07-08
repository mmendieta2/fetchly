"""GUI preference persistence: round-trip, credential exclusion, theme rule.

conftest's autouse fixture points FETCHLY_PREFS_FILE at a per-test temp file.
"""

import json
import os

import pytest

from fetchly.gui import prefs


def test_prefs_round_trip():
    prefs.save({"start_url": "https://example.com", "max_pages": "50",
                "render_js": True})
    assert prefs.load() == {"start_url": "https://example.com",
                            "max_pages": "50", "render_js": True}


def test_prefs_missing_and_corrupt_files_fall_back():
    assert prefs.load() == {}
    with open(os.environ["FETCHLY_PREFS_FILE"], "w", encoding="utf-8") as fh:
        fh.write("{not json")
    assert prefs.load() == {}


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


def test_settings_saved_and_reloaded(app):
    import tkinter as tk
    from fetchly.gui.app import FetchlyApp

    app.url_var.set("https://example.com")
    app.max_pages_var.set("77")
    app.render_js_var.set(True)
    app.login_fields_var.set("user=u;password=hunter2")
    app._save_prefs()

    on_disk = json.load(open(os.environ["FETCHLY_PREFS_FILE"], encoding="utf-8"))
    assert on_disk["start_url"] == "https://example.com"
    assert "hunter2" not in json.dumps(on_disk)   # credentials never persisted
    assert "theme" not in on_disk                 # never explicitly toggled

    root2 = tk.Tk()
    from fetchly.gui.theme import apply_theme
    apply_theme(root2)
    app2 = FetchlyApp(root2)
    try:
        assert app2.url_var.get() == "https://example.com"
        assert app2.max_pages_var.get() == "77"
        assert app2.render_js_var.get() is True
        assert app2.login_fields_var.get() == ""
    finally:
        root2.destroy()


def test_theme_saved_only_after_explicit_toggle(app):
    from fetchly.gui.theme import current_mode

    app._save_prefs()
    assert "theme" not in prefs.load()

    app._toggle_theme()                           # explicit choice, auto-saves
    assert prefs.load()["theme"] == current_mode()
    app._toggle_theme()                           # back, for test isolation
