"""Generate a self-contained HTML visualization of the crawl link graph.

No external resources: the force-directed layout is ~60 lines of inline
vanilla JS on a <canvas>, so the file opens offline in any browser.
"""

import json
from urllib.parse import urlparse


def _label(url: str) -> str:
    parts = urlparse(url)
    return (parts.path or "/") + (("?" + parts.query) if parts.query else "")


def _color(result) -> str:
    if result.error or result.status_code >= 400:
        return "#c0392b"   # red: broken
    if result.redirect_hops:
        return "#b9770e"   # amber: redirected
    return "#2471a3"       # blue: ok


def write_graph(path: str, results) -> int:
    """Write the crawl graph HTML; returns the number of nodes."""
    index = {r.url: i for i, r in enumerate(results)}
    nodes = [{"label": _label(r.url), "url": r.url, "color": _color(r),
              "depth": r.depth} for r in results]
    edges = [{"s": index[r.found_on], "t": index[r.url]}
             for r in results if r.found_on and r.found_on in index]
    data = json.dumps({"nodes": nodes, "edges": edges})

    html = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Fetchly crawl graph</title>
<style>
 body{margin:0;font:13px sans-serif;background:#fafafa}
 #info{position:fixed;top:8px;left:8px;background:#fff;border:1px solid #ccc;
       padding:6px 10px;border-radius:4px;max-width:60ch;word-break:break-all}
 .legend span{display:inline-block;width:10px;height:10px;border-radius:5px;margin:0 4px 0 10px}
</style></head><body>
<div id="info"><b>Fetchly crawl graph</b> — drag nodes, click to open URL.
 <span class="legend"><span style="background:#2471a3"></span>ok
 <span style="background:#b9770e"></span>redirect
 <span style="background:#c0392b"></span>broken</span>
 <div id="hover">&nbsp;</div></div>
<canvas id="c"></canvas>
<script>
const DATA = __DATA__;
const cv = document.getElementById('c'), ctx = cv.getContext('2d');
const hover = document.getElementById('hover');
let W, H; function resize(){W=cv.width=innerWidth;H=cv.height=innerHeight;}
resize(); addEventListener('resize', resize);
const N = DATA.nodes.map((n,i)=>({...n,
  x: W/2 + Math.cos(i*2.4)* (60+n.depth*90) + Math.random()*20,
  y: H/2 + Math.sin(i*2.4)* (60+n.depth*90) + Math.random()*20, vx:0, vy:0}));
const E = DATA.edges;
let drag=null, mx=0, my=0;
function step(){
  for(let a=0;a<N.length;a++)for(let b=a+1;b<N.length;b++){
    const dx=N[b].x-N[a].x, dy=N[b].y-N[a].y, d2=dx*dx+dy*dy+0.01, f=1800/d2;
    const fx=dx*f, fy=dy*f;
    N[a].vx-=fx; N[a].vy-=fy; N[b].vx+=fx; N[b].vy+=fy;
  }
  for(const e of E){
    const s=N[e.s], t=N[e.t], dx=t.x-s.x, dy=t.y-s.y;
    const d=Math.sqrt(dx*dx+dy*dy)+0.01, f=(d-90)*0.004;
    s.vx+=dx/d*f*d; s.vy+=dy/d*f*d; t.vx-=dx/d*f*d; t.vy-=dy/d*f*d;
  }
  for(const n of N){
    if(n===drag){n.x=mx;n.y=my;n.vx=n.vy=0;continue;}
    n.vx+=(W/2-n.x)*0.0005; n.vy+=(H/2-n.y)*0.0005;
    n.vx*=0.85; n.vy*=0.85; n.x+=n.vx; n.y+=n.vy;
  }
}
function draw(){
  ctx.clearRect(0,0,W,H);
  ctx.strokeStyle='#bbb';
  for(const e of E){ctx.beginPath();ctx.moveTo(N[e.s].x,N[e.s].y);
    ctx.lineTo(N[e.t].x,N[e.t].y);ctx.stroke();}
  for(const n of N){ctx.beginPath();ctx.fillStyle=n.color;
    ctx.arc(n.x,n.y,7,0,7);ctx.fill();}
  ctx.fillStyle='#333';
  if(N.length<=150) for(const n of N) ctx.fillText(n.label, n.x+9, n.y+4);
}
function tick(){step();draw();requestAnimationFrame(tick);} tick();
function at(x,y){return N.find(n=>(n.x-x)**2+(n.y-y)**2<100);}
cv.onmousemove=e=>{mx=e.clientX;my=e.clientY;
  const n=at(mx,my); hover.textContent=n?n.url:'\\u00a0';
  cv.style.cursor=n?'pointer':'default';};
cv.onmousedown=e=>{drag=at(e.clientX,e.clientY);};
cv.onmouseup=e=>{if(drag&&at(e.clientX,e.clientY)===drag&&!e.movementX)
  window.open(drag.url,'_blank'); drag=null;};
</script></body></html>"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html.replace("__DATA__", data))
    return len(nodes)
