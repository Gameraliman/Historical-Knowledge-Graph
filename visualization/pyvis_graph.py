"""رندر گراف با Pyvis + نوار ابزار، جستجوی داخل گراف و Inspector سمت مرورگر.

نکته‌ی فنی: خروجی Pyvis یک صفحه‌ی HTML مستقل داخل iframe است. کلیک روی نود/یال، Inspector داخل همین
صفحه را باز می‌کند (بدون رفت‌وبرگشت به سرور). عملیات‌هایی که به Neo4j نیاز دارند (Expand، Find Paths،
منابع کامل) از Inspector سمت Streamlit انجام می‌شوند.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict

import streamlit.components.v1 as components
from pyvis.network import Network

from config import settings
from utils.formatting import short

_HEAT = ((255, 224, 138), (232, 56, 79))


def _heat(x: float) -> str:
    c = [round(a + (b - a) * x) for a, b in zip(*_HEAT)]
    return "#%02x%02x%02x" % tuple(c)


def _options(n_nodes: int, physics: bool, dark: bool, font: str) -> dict:
    big = n_nodes > 1500
    return {
        "interaction": {"hover": True, "tooltipDelay": 120, "multiselect": True, "keyboard": True,
                        "hideEdgesOnDrag": big, "navigationButtons": False},
        "physics": {
            "enabled": physics,
            "solver": "forceAtlas2Based",
            "forceAtlas2Based": {"gravitationalConstant": -45 if big else -70, "centralGravity": 0.01,
                                 "springLength": 110, "springConstant": 0.07, "damping": 0.55, "avoidOverlap": 0.4},
            "stabilization": {"enabled": True, "iterations": 100 if big else 200, "updateInterval": 25},
        },
        "nodes": {"shape": "dot", "borderWidth": 2,
                  "font": {"face": font, "size": 14, "color": "#e5e7eb" if dark else "#1f2937"}},
        "edges": {"arrows": {"to": {"enabled": True, "scaleFactor": 0.5}}, "width": 1, "selectionWidth": 2,
                  "smooth": False if big else {"enabled": True, "type": "dynamic"},
                  "font": {"size": 11, "face": font, "align": "middle", "strokeWidth": 0,
                           "color": "#cbd5e1" if dark else "#475569"}},
    }


def build_html(graph: dict, *, height: int = 720, physics: bool = True, show_labels: bool = True,
               show_edge_labels: bool = False, overlay: dict | None = None, highlight_nodes: set | None = None,
               highlight_edges: set | None = None, focus_id: str | None = None, dark: bool = False) -> str:
    nodes, edges = graph["nodes"], graph["edges"]
    highlight_nodes = highlight_nodes or set()
    highlight_edges = highlight_edges or set()
    font = "Vazirmatn, Tahoma, sans-serif"
    bg = "#0f172a" if dark else "#ffffff"
    net = Network(height=f"{height}px", width="100%", bgcolor=bg, font_color="#e5e7eb" if dark else "#1f2937",
                  directed=True, notebook=False, cdn_resources="in_line")
    net.set_options(json.dumps(_options(len(nodes), physics, dark, font)))

    # ---- رنگ و اندازه‌ی نودها ----
    values = (overlay or {}).get("values", {})
    vmax = max(values.values(), default=0) or 1
    vmin = min(values.values(), default=0)
    comm_rank: dict = {}
    if overlay and overlay.get("kind") == "community":
        counts = Counter(values.values())
        comm_rank = {c: i for i, (c, _) in enumerate(counts.most_common())}
    degree = Counter()
    for e in edges.values():
        degree[e["source"]] += 1
        degree[e["target"]] += 1

    for nid, n in nodes.items():
        base = settings.color_of(n["type"])
        size = 10 + min(18, 3 * math.log2(1 + n.get("source_count", 0)))
        fill = base
        border = base
        if overlay and nid in values:
            v = values[nid]
            if overlay["kind"] == "community":
                fill = settings.COMMUNITY_PALETTE[comm_rank.get(v, 0) % len(settings.COMMUNITY_PALETTE)]
                border = fill
            else:
                x = (v - vmin) / (vmax - vmin) if vmax > vmin else 0.5
                fill, size = _heat(x), 10 + 50 * x
        elif overlay:
            fill, size = "#d1d5db", 8
        bw = 2
        if nid in highlight_nodes or nid == focus_id:
            border, bw, size = "#FFC107", 5, size + 6
        title = f"{n['name']}\nنوع: {settings.label_fa(n['type'])}\nتعداد منبع: {n.get('source_count', 0)}"
        if overlay and nid in values:
            title += f"\n{overlay.get('title', 'مقدار')}: {values[nid]:.5g}"
        net.add_node(nid, label=short(n["name"], 26) if show_labels else "", title=title, size=size,
                     color={"background": fill, "border": border, "highlight": {"background": fill, "border": "#FFC107"},
                            "hover": {"background": fill, "border": "#FFC107"}},
                     borderWidth=bw, full=short(n["name"], 26), fullname=n["name"], ntype=n["type"],
                     sc=n.get("source_count", 0))

    # ---- یال‌ها (یال‌های موازی منحنی می‌شوند) ----
    pair_count: dict = defaultdict(int)
    big = len(nodes) > 1500
    edge_base = "#64748b" if dark else "#9aa4b2"
    for eid, e in edges.items():
        key = tuple(sorted((e["source"], e["target"])))
        k = pair_count[key]
        pair_count[key] += 1
        in_path = eid in highlight_edges
        dim = bool(highlight_edges) and not in_path
        color = "#EF4444" if in_path else ("#d1d5db" if dim else edge_base)
        opts = dict(id=eid, label=short(e["type"], 22) if show_edge_labels else "", title=f"{e['type']}\nمنبع: {e.get('source_count', 0)}",
                    color={"color": color, "highlight": "#018bff", "hover": "#018bff"}, c0=color,
                    width=4 if in_path else 1, full=short(e["type"], 22), ftype=e["type"], esc=e.get("source_count", 0))
        if k and not big:
            opts["smooth"] = {"enabled": True, "type": "curvedCW" if k % 2 else "curvedCCW", "roundness": 0.15 * ((k + 1) // 2)}
        net.add_edge(e["source"], e["target"], **opts)

    html = net.generate_html(notebook=False)
    legend = _legend(nodes, overlay, comm_rank)
    extra = (_EXTRA.replace("__HEIGHT__", str(height)).replace("__BG__", bg)
             .replace("__LEGEND__", legend).replace("__FOCUS__", json.dumps(focus_id))
             .replace("__SHOW_L__", "true" if show_labels else "false")
             .replace("__SHOW_E__", "true" if show_edge_labels else "false")
             .replace("__PHYS__", "true" if physics else "false"))
    return html.replace("</body>", extra + "</body>") if "</body>" in html else html + extra


def _legend(nodes: dict, overlay: dict | None, comm_rank: dict) -> str:
    if overlay and overlay.get("kind") == "community":
        items = [f'<span><i style="background:{settings.COMMUNITY_PALETTE[r % len(settings.COMMUNITY_PALETTE)]}"></i>جامعه {c}</span>'
                 for c, r in list(comm_rank.items())[:10]]
    elif overlay:
        items = [f'<span><i style="background:linear-gradient(90deg,{_heat(0)},{_heat(1)});width:34px"></i>'
                 f'{overlay.get("title", "")} (کم ← زیاد)</span>']
    else:
        types = sorted({n["type"] for n in nodes.values()})
        items = [f'<span><i style="background:{settings.color_of(t)}"></i>{settings.NODE_TYPE_FA.get(t, t)}</span>' for t in types]
    return "".join(items)


_EXTRA = r"""
<style>
 body{margin:0;background:__BG__;font-family:Vazirmatn,Tahoma,sans-serif}
 .card{border:none!important;margin:0!important} #mynetwork{height:__HEIGHT__px!important;border:none!important;background:__BG__!important}
 #kgBar{position:absolute;top:8px;right:8px;left:8px;z-index:10;display:flex;flex-wrap:wrap;gap:6px;align-items:center;direction:rtl;
   background:rgba(255,255,255,.94);border:1px solid #e3e8ef;border-radius:10px;padding:6px 8px;font-size:12px;box-shadow:0 2px 8px rgba(0,0,0,.08)}
 #kgBar button{border:1px solid #cbd5e1;background:#fff;border-radius:6px;padding:3px 9px;cursor:pointer;font-family:inherit;font-size:12px}
 #kgBar button:hover{background:#eff6ff;border-color:#018bff} #kgBar input[type=text]{border:1px solid #cbd5e1;border-radius:6px;padding:3px 8px;min-width:150px;font-family:inherit;font-size:12px}
 #kgPanel{position:absolute;top:58px;left:10px;width:300px;max-height:calc(100% - 120px);overflow:auto;z-index:11;display:none;direction:rtl;
   background:#fff;border:1px solid #e3e8ef;border-radius:10px;padding:12px;font-size:13px;box-shadow:0 4px 16px rgba(0,0,0,.15);color:#1f2937}
 #kgPanel h4{margin:0 0 6px;font-size:14px} #kgPanel .k{color:#667085;font-size:12px} #kgPanel .row{margin:4px 0}
 #kgPanel .x{position:absolute;top:6px;right:8px;cursor:pointer;color:#98a2b3} #kgPanel ul{margin:4px 0;padding-right:18px;max-height:170px;overflow:auto}
 .chip{display:inline-block;color:#fff;border-radius:10px;padding:1px 9px;font-size:11px}
 #kgLegend{position:absolute;bottom:8px;right:8px;z-index:10;direction:rtl;background:rgba(255,255,255,.92);border:1px solid #e3e8ef;border-radius:8px;
   padding:5px 9px;font-size:11px;display:flex;flex-wrap:wrap;gap:10px;max-width:70%;color:#1f2937} #kgLegend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-left:4px;vertical-align:middle}
</style>
<div id="kgBar">
 <button id="kgFit">⤢ تطبیق</button><button id="kgReset">⟳ بازنشانی دید</button><button id="kgFull">⛶ تمام‌صفحه</button><button id="kgTab">↗ تب جدید</button>
 <label><input type="checkbox" id="kgPhys"> فیزیک</label><label><input type="checkbox" id="kgLbl"> برچسب گره‌ها</label><label><input type="checkbox" id="kgElbl"> برچسب رابطه‌ها</label>
 <input type="text" id="kgFind" placeholder="🔎 یافتن گره در گراف (Enter)">
</div>
<div id="kgPanel"></div><div id="kgLegend">__LEGEND__</div>
<script>
(function(){
 var FOCUS=__FOCUS__, panel=document.getElementById('kgPanel');
 var COLORS=""" + json.dumps(settings.NODE_COLORS) + r""";
 function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
 function norm(s){return String(s||'').replace(/\u200c/g,' ').replace(/\u064a/g,'\u06cc').replace(/\u0643/g,'\u06a9').toLowerCase()}
 document.getElementById('kgPhys').checked=__PHYS__;
 document.getElementById('kgLbl').checked=__SHOW_L__;
 document.getElementById('kgElbl').checked=__SHOW_E__;
 function chip(t){return '<span class="chip" style="background:'+(COLORS[t]||'#b0b7c3')+'">'+esc(t)+'</span>'}
 function clearHL(){
   nodes.update(nodes.getIds().map(function(i){return {id:i,opacity:1}}));
   edges.update(edges.getIds().map(function(i){var e=edges.get(i);return {id:i,color:{color:e.c0,highlight:'#018bff',hover:'#018bff',opacity:1}}}));
 }
 function highlight(id){
   var ce=network.getConnectedEdges(id), cn=network.getConnectedNodes(id); cn.push(id);
   nodes.update(nodes.getIds().map(function(i){return {id:i,opacity:cn.indexOf(i)>=0?1:0.15}}));
   edges.update(edges.getIds().map(function(i){var e=edges.get(i);return {id:i,color:{color:e.c0,highlight:'#018bff',hover:'#018bff',opacity:ce.indexOf(i)>=0?1:0.08}}}));
 }
 function showNode(id){
   var n=nodes.get(id), ce=network.getConnectedEdges(id), li='';
   ce.slice(0,60).forEach(function(eid){var e=edges.get(eid), out=e.from===id, o=nodes.get(out?e.to:e.from);
     li+='<li>'+(out?'← ':'→ ')+'<b>'+esc(e.ftype)+'</b> '+esc(o?o.fullname:'')+'</li>'});
   panel.innerHTML='<span class="x" onclick="this.parentNode.style.display=\'none\'">✕</span><h4>'+esc(n.fullname)+'</h4>'
    +'<div class="row">'+chip(n.ntype)+'</div><div class="row"><span class="k">تعداد منبع:</span> '+esc(n.sc)+'</div>'
    +'<div class="row"><span class="k">رابطه‌ها در نمای فعلی:</span> '+ce.length+'</div><ul>'+li+'</ul>'
    +'<div class="k">برای Expand / مسیریابی / منابع کامل از پنل «Inspector» کنار گراف استفاده کنید.</div>';
   panel.style.display='block';
 }
 function showEdge(id){
   var e=edges.get(id), a=nodes.get(e.from), b=nodes.get(e.to);
   panel.innerHTML='<span class="x" onclick="this.parentNode.style.display=\'none\'">✕</span><h4>رابطه</h4>'
    +'<div class="row"><span class="k">مبدأ:</span> '+esc(a.fullname)+' '+chip(a.ntype)+'</div>'
    +'<div class="row"><span class="k">نوع:</span> <b>'+esc(e.ftype)+'</b></div>'
    +'<div class="row"><span class="k">مقصد:</span> '+esc(b.fullname)+' '+chip(b.ntype)+'</div>'
    +'<div class="row"><span class="k">تعداد منبع:</span> '+esc(e.esc)+'</div>';
   panel.style.display='block';
 }
 network.on('click',function(p){
   if(p.nodes.length){showNode(p.nodes[0]);highlight(p.nodes[0]);}
   else if(p.edges.length){showEdge(p.edges[0]);}
   else{panel.style.display='none';clearHL();}
 });
 document.getElementById('kgFit').onclick=function(){network.fit({animation:true})};
 document.getElementById('kgReset').onclick=function(){network.unselectAll();clearHL();panel.style.display='none';network.fit({animation:true})};
 document.getElementById('kgPhys').onchange=function(){network.setOptions({physics:{enabled:this.checked}})};
 document.getElementById('kgLbl').onchange=function(){var s=this.checked;nodes.update(nodes.get().map(function(n){return {id:n.id,label:s?n.full:''}}))};
 document.getElementById('kgElbl').onchange=function(){var s=this.checked;edges.update(edges.get().map(function(e){return {id:e.id,label:s?e.full:''}}))};
 document.getElementById('kgFull').onclick=function(){try{var el=document.documentElement;(el.requestFullscreen||el.webkitRequestFullscreen).call(el)}catch(e){alert('حالت تمام‌صفحه در این مرورگر/محیط در دسترس نیست؛ از «تب جدید» استفاده کنید.')}};
 document.getElementById('kgTab').onclick=function(){try{var u=URL.createObjectURL(new Blob(['<!DOCTYPE html>'+document.documentElement.outerHTML],{type:'text/html'}));window.open(u,'_blank')}catch(e){alert('باز کردن تب جدید مسدود شد؛ دکمه‌ی دانلود HTML را بزنید.')}};
 document.getElementById('kgFind').onkeydown=function(ev){
   if(ev.key!=='Enter')return; var q=norm(this.value); if(!q)return;
   var hit=nodes.get().filter(function(n){return norm(n.fullname).indexOf(q)>=0})[0];
   if(hit){network.selectNodes([hit.id]);network.focus(hit.id,{scale:1.3,animation:true});showNode(hit.id);highlight(hit.id)}
 };
 if(FOCUS&&nodes.get(FOCUS)){
   var go=function(){network.selectNodes([FOCUS]);network.focus(FOCUS,{scale:1.1,animation:true})};
   network.once('stabilized',go); setTimeout(go,1800);
 }
})();
</script>
"""


def show(html: str, height: int = 720) -> None:
    components.html(html, height=height + 6, scrolling=False)
