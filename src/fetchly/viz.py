"""Generate a self-contained HTML visualization of the crawl link graph.

The page inlines the vendored force-graph library (MIT, see
vendor/FORCE-GRAPH-LICENSE.txt) plus the crawl data, so the file opens
offline in any browser with no external requests.
"""

import json
import os
from collections import Counter
from urllib.parse import urlparse

# Status palette: paired with text labels in the legend chips and the URL
# readout, so meaning never rides on color alone.
STATUS_COLORS = {"ok": "#0ca30c", "redirect": "#fab219", "broken": "#d03b3b"}


def _label(url: str) -> str:
    parts = urlparse(url)
    return (parts.path or "/") + (("?" + parts.query) if parts.query else "")


def _status(result) -> str:
    if result.error or result.status_code >= 400:
        return "broken"
    if result.redirect_hops:
        return "redirect"
    return "ok"


def _vendor_js() -> str:
    path = os.path.join(os.path.dirname(__file__), "vendor", "force-graph.min.js")
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def write_graph(path: str, results) -> int:
    """Write the crawl graph HTML; returns the number of nodes."""
    index = {r.url: i for i, r in enumerate(results)}
    # Out-degree: how many crawled pages were discovered on this one.
    # In-degree is ~1 by construction (each page has one found_on), so
    # out-degree is what distinguishes hub pages.
    out_deg = Counter(r.found_on for r in results if r.found_on)
    nodes = [{"id": i, "label": _label(r.url), "url": r.url,
              "status": _status(r), "deg": out_deg.get(r.url, 0)}
             for i, r in enumerate(results)]
    edges = [{"source": index[r.found_on], "target": index[r.url]}
             for r in results if r.found_on and r.found_on in index]
    data = json.dumps({"nodes": nodes, "links": edges}).replace("</", "<\\/")

    html = _TEMPLATE.replace("__LIB__", _vendor_js()).replace("__DATA__", data)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return len(nodes)


_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Fetchly crawl graph</title>
<style>
 body{margin:0;font:13px system-ui,sans-serif;background:#fafafa;overflow:hidden}
 #panel{position:fixed;top:10px;left:10px;z-index:10;background:rgba(255,255,255,.95);
        border:1px solid #d5d5d5;border-radius:8px;padding:10px 12px;max-width:46ch;
        box-shadow:0 1px 4px rgba(0,0,0,.08)}
 #panel h1{font-size:14px;margin:0 0 2px}
 #hint{color:#777;font-size:11.5px;margin-bottom:8px}
 #search{width:100%;box-sizing:border-box;padding:5px 8px;border:1px solid #ccc;
         border-radius:5px;font:12px system-ui,sans-serif;margin-bottom:2px}
 #matches{color:#777;font-size:11px;min-height:1.1em;margin-bottom:6px}
 #chips{display:flex;gap:6px;margin-bottom:6px}
 .chip{display:flex;align-items:center;gap:5px;padding:3px 9px;border:1px solid #ccc;
       border-radius:12px;cursor:pointer;user-select:none;background:#fff;font-size:12px}
 .chip i{width:9px;height:9px;border-radius:50%;display:inline-block}
 .chip.off{opacity:.4}.chip.off i{background:#999!important}
 #readout{color:#555;font-family:ui-monospace,monospace;font-size:11.5px;
          overflow-wrap:anywhere;min-height:1.2em;max-height:3.6em;overflow:hidden}
</style></head><body>
<div id="panel">
 <h1>Fetchly crawl graph</h1>
 <div id="hint">Scroll to zoom &middot; drag background to pan &middot; drag nodes &middot; click a node to open its URL</div>
 <input id="search" type="search" placeholder="Find URL&hellip; (Enter jumps to first match)" autocomplete="off">
 <div id="matches">&nbsp;</div>
 <div id="chips"></div>
 <div id="readout">&nbsp;</div>
</div>
<div id="graph"></div>
<script>__LIB__</script>
<script>
const DATA = __DATA__;
const COLORS = {ok:'#0ca30c', redirect:'#fab219', broken:'#d03b3b'};
const DIM = {ok:'rgba(12,163,12,.12)', redirect:'rgba(250,178,25,.12)', broken:'rgba(208,59,59,.12)'};

// Neighbor lookup for hover-focus.
const byId = new Map(DATA.nodes.map(n => [n.id, n]));
for (const n of DATA.nodes) { n.neighbors = new Set(); n.links = new Set(); }
for (const l of DATA.links) {
  const s = byId.get(l.source), t = byId.get(l.target);
  s.neighbors.add(t); t.neighbors.add(s); s.links.add(l); t.links.add(l);
}

const active = {ok:true, redirect:true, broken:true};
let hoverNode = null, hoverLinks = new Set();
let searchMatches = new Set();
const readout = document.getElementById('readout');

function currentData() {
  const nodes = DATA.nodes.filter(n => active[n.status]);
  const keep = new Set(nodes.map(n => n.id));
  const id = o => typeof o === 'object' ? o.id : o;  // force-graph mutates endpoints into objects
  const links = DATA.links.filter(l => keep.has(id(l.source)) && keep.has(id(l.target)));
  return {nodes, links};
}

function focusActive() { return hoverNode !== null || searchMatches.size > 0; }
function inFocus(n) {
  if (hoverNode && (n === hoverNode || hoverNode.neighbors.has(n))) return true;
  return searchMatches.has(n);
}

const G = window.G = new ForceGraph(document.getElementById('graph'))
  .graphData(currentData())
  .autoPauseRedraw(false)  // hover/search recolor via accessors; keep repainting
  .backgroundColor('#fafafa')
  .nodeRelSize(3.5)
  .nodeVal(n => 1 + Math.min(n.deg, 60))
  .nodeLabel(n => n.url)
  .nodeColor(n => focusActive() && !inFocus(n) ? DIM[n.status] : COLORS[n.status])
  .linkColor(l => {
    if (hoverLinks.has(l)) return 'rgba(60,60,60,.85)';
    return focusActive() ? 'rgba(0,0,0,.04)' : 'rgba(0,0,0,.12)';
  })
  .linkWidth(l => hoverLinks.has(l) ? 1.6 : 1)
  .nodeCanvasObjectMode(() => 'after')
  .nodeCanvasObject((n, ctx, scale) => {
    // Labels only when zoomed in or the node is in the current focus set.
    const focused = focusActive() && inFocus(n);
    if (scale < 1.5 && !focused) return;
    if (focusActive() && !focused) return;
    const label = n.label.length > 36 ? n.label.slice(0, 35) + '\\u2026' : n.label;
    const size = 11 / scale;
    ctx.font = size + 'px system-ui, sans-serif';
    ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
    const x = n.x + Math.sqrt(1 + Math.min(n.deg, 60)) * 3.5 + 3 / scale;
    ctx.lineWidth = 3 / scale; ctx.lineJoin = 'round';
    ctx.strokeStyle = 'rgba(250,250,250,.9)';
    ctx.strokeText(label, x, n.y);
    ctx.fillStyle = '#333';
    ctx.fillText(label, x, n.y);
  })
  .onNodeHover(n => {
    hoverNode = n || null;
    hoverLinks = n ? n.links : new Set();
    readout.innerHTML = n ? n.status + ' &mdash; ' + n.url.replace(/&/g,'&amp;').replace(/</g,'&lt;') : '&nbsp;';
    document.getElementById('graph').style.cursor = n ? 'pointer' : null;
  })
  .onNodeClick(n => window.open(n.url, '_blank'))
  .cooldownTime(6000);

let fitted = false;
G.onEngineStop(() => { if (!fitted) { fitted = true; G.zoomToFit(400, 60); } });

// Legend / filter chips with live counts.
const counts = {ok:0, redirect:0, broken:0};
for (const n of DATA.nodes) counts[n.status]++;
const chips = document.getElementById('chips');
for (const s of ['ok', 'redirect', 'broken']) {
  const c = document.createElement('div');
  c.className = 'chip';
  c.innerHTML = '<i style="background:' + COLORS[s] + '"></i>' + s + ' (' + counts[s] + ')';
  c.title = 'Click to show/hide ' + s + ' pages';
  c.onclick = () => { active[s] = !active[s]; c.classList.toggle('off', !active[s]);
                      G.graphData(currentData()); };
  chips.appendChild(c);
}

// Search: live highlight, Enter jumps to the first match.
const search = document.getElementById('search');
const matchesEl = document.getElementById('matches');
search.addEventListener('input', () => {
  const q = search.value.trim().toLowerCase();
  searchMatches = new Set();
  if (q) for (const n of DATA.nodes)
    if (active[n.status] && n.url.toLowerCase().includes(q)) searchMatches.add(n);
  matchesEl.textContent = q ? searchMatches.size + ' match' +
    (searchMatches.size === 1 ? '' : 'es') : '\\u00a0';
});
search.addEventListener('keydown', e => {
  if (e.key !== 'Enter' || !searchMatches.size) return;
  const n = searchMatches.values().next().value;
  G.centerAt(n.x, n.y, 600);
  G.zoom(3, 600);
});
</script></body></html>"""
