"""GUI Compare-tab tests: drive FetchlyApp._compare_crawls headlessly.

Follows the tkinter test pattern from test_viz.py (importorskip + skip when no
display). The two file dialogs are monkeypatched to return temp CSV paths.
"""

import pytest


def _write_csv(path, rows):
    import csv
    fields = ("url", "status_code", "title", "meta_description",
              "canonical_url", "redirected_to", "word_count")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


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


def _run_compare(app, monkeypatch, old_path, new_path):
    from fetchly.gui import app as app_module
    paths = iter([old_path, new_path])
    monkeypatch.setattr(app_module.filedialog, "askopenfilename",
                        lambda *a, **k: next(paths))
    app._compare_crawls()


def _rows(app):
    tree = app.compare_tree
    return [tree.item(i, "values") for i in tree.get_children()]


def test_compare_reports_added_removed_changed(app, monkeypatch, tmp_path):
    old = tmp_path / "old.csv"
    new = tmp_path / "new.csv"
    _write_csv(old, [
        {"url": "https://s.com/a", "status_code": "200", "word_count": "100"},
        {"url": "https://s.com/b", "status_code": "200", "word_count": "50"}])
    _write_csv(new, [
        {"url": "https://s.com/a", "status_code": "404", "word_count": "100"},
        {"url": "https://s.com/c", "status_code": "200", "word_count": "80"}])

    _run_compare(app, monkeypatch, str(old), str(new))

    rows = _rows(app)
    assert ("Added", "", "https://s.com/c", "", "") in rows
    assert ("Removed", "", "https://s.com/b", "", "") in rows
    assert ("Changed", "status_code", "https://s.com/a", "200", "404") in rows
    # One changed field for /a -> exactly three rows total.
    assert len(rows) == 3
    idx = app.notebook.index(app._compare_tab)
    assert app.notebook.tab(idx, "text") == "Compare (3)"


def test_compare_identical_reports_is_empty(app, monkeypatch, tmp_path):
    csv_rows = [{"url": "https://s.com/a", "status_code": "200"}]
    old = tmp_path / "old.csv"
    new = tmp_path / "new.csv"
    _write_csv(old, csv_rows)
    _write_csv(new, csv_rows)

    _run_compare(app, monkeypatch, str(old), str(new))

    assert _rows(app) == []
    idx = app.notebook.index(app._compare_tab)
    assert app.notebook.tab(idx, "text") == "Compare"


def test_compare_non_report_csv_shows_error(app, monkeypatch, tmp_path):
    bad = tmp_path / "bad.csv"
    with open(bad, "w", encoding="utf-8") as fh:
        fh.write("name,value\nfoo,bar\n")
    good = tmp_path / "good.csv"
    _write_csv(good, [{"url": "https://s.com/a", "status_code": "200"}])

    errors = []
    monkeypatch.setattr(app, "_show_error",
                        lambda title, msg: errors.append((title, msg)))
    _run_compare(app, monkeypatch, str(bad), str(good))

    assert errors and errors[0][0] == "Cannot compare"
    assert _rows(app) == []
