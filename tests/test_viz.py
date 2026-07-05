"""Tests for the HTML graph export and the GUI graph layout math."""

import math

import pytest

from fetchly.gui.graphview import (SPRING_LENGTH, _mix, node_radius,
                                   spawn_position, step_layout)
from fetchly.models import PageResult
from fetchly.viz import write_graph


def _results():
    return [
        PageResult(url="https://ex.com/", status_code=200, depth=0),
        PageResult(url="https://ex.com/a", status_code=200, depth=1,
                   found_on="https://ex.com/"),
        PageResult(url="https://ex.com/b", status_code=301, redirect_hops=1,
                   depth=1, found_on="https://ex.com/"),
        PageResult(url="https://ex.com/c", status_code=404, depth=1,
                   found_on="https://ex.com/"),
        PageResult(url="https://ex.com/a/d", status_code=200, depth=2,
                   found_on="https://ex.com/a"),
    ]


def test_write_graph(tmp_path):
    path = tmp_path / "graph.html"
    count = write_graph(str(path), _results())
    assert count == 5
    html = path.read_text(encoding="utf-8")
    # Vendored library is inlined (self-contained, offline-capable file).
    assert "force-graph" in html and "ForceGraph" in html
    assert "<script src=" not in html and "http://" not in html.split("</script>")[-1]
    # Node data present, with statuses and out-degree for the hub page.
    assert '"url": "https://ex.com/a/d"' in html
    assert '"status": "redirect"' in html
    assert '"status": "broken"' in html
    root = next(n for n in html.split("{") if '"https://ex.com/"' in n)
    assert '"deg": 3' in "{" + root


def test_write_graph_escapes_closing_tags(tmp_path):
    path = tmp_path / "graph.html"
    results = [PageResult(url="https://ex.com/</script>", status_code=200)]
    write_graph(str(path), results)
    html = path.read_text(encoding="utf-8")
    assert "/<\\/script>" in html  # inline JSON cannot terminate the script tag


def test_spawn_position_fans_children_around_parent():
    parent = {"x": 100.0, "y": -50.0}
    positions = [spawn_position(parent, k) for k in range(8)]
    for x, y in positions:
        d = math.hypot(x - 100.0, y + 50.0)
        assert 0 < d < SPRING_LENGTH * 2
    # Children spread out rather than stacking on one spot.
    xs = {round(x) for x, _ in positions}
    assert len(xs) > 4


def test_step_layout_relaxes_edge_toward_rest_length():
    nodes = [
        {"x": 0.0, "y": 0.0, "vx": 0.0, "vy": 0.0},
        {"x": 5.0, "y": 0.0, "vx": 0.0, "vy": 0.0},  # far closer than rest length
    ]
    edges = [(0, 1)]
    for _ in range(200):
        step_layout(nodes, edges, [0, 1])
    d = math.hypot(nodes[1]["x"] - nodes[0]["x"], nodes[1]["y"] - nodes[0]["y"])
    assert SPRING_LENGTH * 0.5 < d < SPRING_LENGTH * 2


def test_step_layout_only_moves_hot_nodes():
    nodes = [
        {"x": 0.0, "y": 0.0, "vx": 0.0, "vy": 0.0},
        {"x": 5.0, "y": 5.0, "vx": 0.0, "vy": 0.0},
    ]
    step_layout(nodes, [(0, 1)], [1])
    assert (nodes[0]["x"], nodes[0]["y"]) == (0.0, 0.0)
    assert (nodes[1]["x"], nodes[1]["y"]) != (5.0, 5.0)
    assert step_layout(nodes, [], []) == 0.0


def test_node_radius_grows_sublinearly_and_caps():
    assert node_radius(0) < node_radius(4) < node_radius(16)
    assert node_radius(60) == node_radius(500)


def test_mix_endpoints_and_midpoint():
    assert _mix("#1f8fff", "#fafafa", 1) == "#1f8fff"
    assert _mix("#1f8fff", "#fafafa", 0) == "#fafafa"
    mid = _mix("#000000", "#ffffff", 0.5)
    assert mid == "#808080" or mid == "#7f7f7f"


@pytest.fixture
def graphview():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    from fetchly.gui.graphview import GraphView
    view = GraphView(root)
    yield view
    root.destroy()


def test_root_node_identifies_main_domain(graphview):
    graphview.add_result(PageResult(url="https://shop.ex.com/", status_code=200))
    graphview.add_result(PageResult(url="https://shop.ex.com/a", status_code=200,
                                    found_on="https://shop.ex.com/"))
    assert graphview._root_idx == 0
    assert graphview._domain_var.get() == "shop.ex.com"
    assert graphview._root_label is not None
    # A later childless page must not steal the root marker.
    graphview.add_result(PageResult(url="https://shop.ex.com/orphan", status_code=200))
    assert graphview._root_idx == 0


def test_fit_before_canvas_is_mapped_keeps_zoom_positive(graphview):
    # An unmapped canvas reports width/height of 1; the fit math must not
    # produce a negative zoom (would crash math.sqrt in node placement).
    assert graphview.canvas.winfo_width() <= 1
    for i in range(5):
        graphview.add_result(PageResult(
            url=f"https://ex.com/{i}", status_code=200,
            found_on="https://ex.com/0" if i else ""))
    graphview._fit(animate=False)
    assert graphview._zoom_level > 0
    graphview._resize_oval(0)   # exercises node_radius * sqrt(zoom)


def test_new_node_glows_and_bulk_load_does_not(graphview):
    graphview.add_result(PageResult(url="https://ex.com/", status_code=200))
    assert 0 in graphview._glowing
    assert graphview.nodes[0]["glow_item"] is not None

    graphview.load([PageResult(url="https://ex.com/", status_code=200),
                    PageResult(url="https://ex.com/a", status_code=200,
                               found_on="https://ex.com/")])
    # Bulk reload skips the activity ripple (would flood the canvas at once).
    assert graphview._glowing == {}
    assert all(n["glow_item"] is None for n in graphview.nodes)
    # Reset still clears the root marker and domain readout.
    graphview.reset()
    assert graphview._root_idx is None and graphview._domain_var.get() == ""
