"""Bloom: گراف دانش در یک طرف، عملیات (جستجو، فیلتر، موجودیت/Expand، مسیر، داده‌ها) به‌صورت آکاردئون در طرف دیگر.

آکاردئون واقعی (هم‌زمان فقط یک بخش باز) با دکمه‌های سرتیتر ساخته شده است؛ هر عملیات مستقیماً روی همین گراف اعمال می‌شود.
"""
from __future__ import annotations

import streamlit as st

from graph import graph_filters as gf
from graph import graph_state as gstate
from utils import caching
from utils.formatting import db_guard, fmt_int, header
from views import bloom_actions as ba
from views import bloom_sections as sec
from visualization import pyvis_graph as pv

SECTIONS = [
    ("search", "🔎 جستجو و شروع", sec.sec_search),
    ("filters", "🎛 فیلتر و نمایش", sec.sec_filters),
    ("entity", "👤 موجودیت و گسترش (Expand)", sec.sec_entity),
    ("path", "🧭 یابنده‌ی مسیر (Path Finder)", sec.sec_path),
    ("data", "🗃 داده‌ها (Data Explorer)", sec.sec_data),
]


def _accordion(ctx: dict) -> None:
    current = st.session_state.get("bl_open")
    for key, title, fn in SECTIONS:
        is_open = current == key
        st.button(f"{'▾' if is_open else '▸'}  {title}", key=f"bb_acc_{key}", on_click=ba.toggle_section, args=(key,),
                  use_container_width=True, type="primary" if is_open else "secondary")
        if is_open:
            with st.container(border=True):
                fn(ctx)


@db_guard
def render() -> None:
    gstate.init()
    st.session_state.setdefault("bl_open", "search")
    ba.keep_widget_state()
    header("Bloom", "کاوش یکپارچه‌ی گراف دانش: جستجو، گسترش، مسیر و داده‌ها در یک صفحه")

    if st.session_state.get("bl_msg"):
        kind, text = st.session_state.pop("bl_msg")
        getattr(st, kind)(text)

    # ---- گراف جاری با فیلتر زنده ----
    labels = caching.cached_labels()
    sel_types = [t for t in labels if st.session_state.get(f"bl_ft_{t}", True)]
    graph = gstate.graph()
    fg = gf.apply(graph, sel_types, ba.active_rels())
    order = sorted(fg["nodes"].values(), key=lambda n: -n.get("source_count", 0))[:1500]
    ids = [n["id"] for n in order]
    focus = st.session_state.get("kg_focus")
    if focus in fg["nodes"] and focus not in ids:
        ids.insert(0, focus)
    if st.session_state.get("bl_selected") not in ids:
        st.session_state["bl_selected"] = focus if focus in ids else (ids[0] if ids else None)
        if st.session_state["bl_selected"] is None:
            st.session_state.pop("bl_selected", None)
    ctx = {"fg": fg, "ids": ids}
    height = st.session_state.get("bl_height", 760)

    panel, canvas = st.columns([1.1, 2], gap="medium")

    # ============================ پنل عملیات ============================
    with panel:
        st.button("🌐 نمایش کل گراف", key="bb_entire", on_click=ba.request_entire, use_container_width=True, type="primary")
        pending = st.session_state.get("bl_pending")
        if pending:
            st.warning(f"⚠ Graph contains:\n\n**{fmt_int(pending['nodes'])} Nodes** · **{fmt_int(pending['relationships'])} Relationships**\n\n"
                       "Rendering the entire graph may affect browser performance.")
            c1, c2 = st.columns(2)
            c1.button("Render Entire Graph", key="bb_render_all", type="primary", use_container_width=True, on_click=ba.render_entire)
            c2.button("Explore Limited Graph", key="bb_limited", use_container_width=True, on_click=ba.explore_limited)
        with st.container(height=height + 20, border=False):
            _accordion(ctx)

    # ============================ گراف دانش ============================
    with canvas:
        t1, t2, t3 = st.columns([1.1, 1, 3])
        t1.button("↩ Undo", key="bb_undo", on_click=ba.do_undo, use_container_width=True, disabled=not st.session_state.get("kg_history"))
        t2.button("⟳ Reset", key="bb_reset", on_click=ba.do_reset, use_container_width=True)
        t3.caption(f"{fmt_int(len(fg['nodes']))} نود · {fmt_int(len(fg['edges']))} رابطه"
                   + (" — ⚠ گراف به‌دلیل سقف کوتاه شده" if graph["meta"].get("truncated_nodes") else ""))
        trail = st.session_state.get("kg_trail", [])
        if trail:
            st.caption(" ⟵ ".join(trail[-6:]))

        if not graph["nodes"]:
            st.info("گراف خالی است. از پنل کنار، موجودیتی را جستجو کنید یا «نمایش کل گراف» را بزنید؛ یا از نودهای پرارتباط زیر شروع کنید.")
            top = caching.cached_top_degree(8, None)
            cols = st.columns(4)
            for i, r in enumerate(top):
                cols[i % 4].button(f"{r['name']} · {r['degree']}", key=f"bb_sg_{r['id']}", use_container_width=True,
                                   on_click=ba.open_node, args=(r,))
            return
        if not fg["nodes"]:
            st.warning("با فیلترهای فعلی نودی باقی نمی‌ماند.")
            return

        overlay = st.session_state.get("kg_overlay") if st.session_state.get("bl_overlay_on", True) else None
        hl = st.session_state.get("bl_hl") or {}
        html = pv.build_html(fg, height=height, physics=st.session_state.get("bl_physics", True),
                             show_labels=st.session_state.get("bl_labels", True),
                             show_edge_labels=st.session_state.get("bl_elabels", False), overlay=overlay,
                             highlight_nodes=set(hl.get("nodes", [])), highlight_edges=set(hl.get("edges", [])),
                             focus_id=st.session_state.get("kg_focus"), dark=st.session_state.get("bl_dark", False))
        pv.show(html, height)
        st.download_button("⬇ دانلود HTML گراف", html.encode("utf-8"), "graph.html", "text/html", key="bt_dl_graph")
