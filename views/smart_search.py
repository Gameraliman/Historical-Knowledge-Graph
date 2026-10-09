"""جستجوی چندعبارتی Entity/Relation با انتخاب مبدأ و لایه (فقط لایه‌ی N یا همه‌ی لایه‌ها تا N)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from database import queries as q
from graph import graph_builder as gb
from graph import graph_search as gs
from utils.formatting import db_guard, header
from visualization import pyvis_graph as pv

MODE_LABELS = {gb.MODE_EXACT: "فقط لایه‌ی انتخاب‌شده (به‌همراه نودهای اتصال‌دهنده)", gb.MODE_CUMULATIVE: "همه‌ی لایه‌ها تا لایه‌ی انتخاب‌شده"}


@st.cache_data(ttl=300, show_spinner="در حال ساخت گراف…")
def _graph(seed_ids: tuple, layer: int, mode: str, per_layer: int) -> dict:
    return gb.build_subgraph(list(seed_ids), layer, [], [], per_layer, mode=mode)


@db_guard
def render() -> None:
    header("Entity & Relation Search", "چند Entity یا Relation را با کاما، «،» یا خط جدید وارد کنید")
    with st.form("smart_search"):
        text = st.text_area("عبارت‌ها", placeholder="محمدعلی فروغی، تهران، متولد شده در")
        ok = st.form_submit_button("Search", use_container_width=True, type="primary")
    if ok:
        if not text.strip():
            st.warning("عبارت جستجو را وارد کنید.")
        else:
            ents, rels, defaults = gs.search_many(text)
            st.session_state["ss_ents"], st.session_state["ss_rels"] = ents, rels
            st.session_state["ss_seeds"] = defaults             # مبدأ پیش‌فرض: بهترین نتیجه‌ی هر عبارت
    ents, rels = st.session_state.get("ss_ents"), st.session_state.get("ss_rels")
    if ents is None:
        return
    c1, c2 = st.columns(2)
    c1.markdown("### Entityهای شناسایی‌شده")
    if ents:
        c1.dataframe(pd.DataFrame(ents)[["name", "type", "degree"]], hide_index=True, use_container_width=True)
    else:
        c1.info("Entity پیدا نشد.")
    c2.markdown("### Relationهای شناسایی‌شده")
    if rels:
        c2.dataframe(pd.DataFrame(rels), hide_index=True, use_container_width=True)
    else:
        c2.info("Relation پیدا نشد.")

    by_id = {e["id"]: e for e in ents}
    seeds: list[str] = []
    if ents:
        st.session_state["ss_seeds"] = [i for i in st.session_state.get("ss_seeds", []) if i in by_id]
        seeds = st.multiselect("Entityهای مبدأ گراف", list(by_id), key="ss_seeds",
                               format_func=lambda i: f"{by_id[i]['name']} · {by_id[i]['type']} · {by_id[i]['degree']} رابطه",
                               help="به‌صورت پیش‌فرض بهترین نتیجه‌ی هر عبارت انتخاب شده است؛ هر Entity دیگر را هم می‌توانید اضافه کنید.")
    elif rels:
        seeds = q.seeds_by_relation([r["type"] for r in rels], 60)
        st.caption("فقط Relation پیدا شد؛ نودهای شرکت‌کننده در این رابطه‌ها مبدأ گراف‌اند.")
    if not seeds:
        st.warning("مبدأی برای ساخت گراف انتخاب نشده است.")
        return

    o1, o2, o3 = st.columns([1, 3, 2])
    layer = o1.selectbox("Layer", range(1, 7), index=1, key="ss_layer")
    mode = o2.radio("نمایش لایه‌ها", list(MODE_LABELS), format_func=MODE_LABELS.get, key="ss_mode")
    per_layer = o3.slider("حداکثر Node در هر لایه", 25, 300, 100, 25, key="ss_max")
    g = _graph(tuple(seeds), int(layer), mode, int(per_layer))
    counts = g["meta"].get("layer_counts", [])
    st.markdown(f"### Graph — {'فقط لایه‌ی' if mode == gb.MODE_EXACT else 'تا لایه‌ی'} {layer}")
    st.caption(f"{len(g['nodes'])} node / {len(g['edges'])} edge · " + " · ".join(
        f"{'مبدأ' if k == 0 else f'لایه {k}'}: {c}" for k, c in enumerate(counts))
        + (" · ⚠ برخی نودها به‌دلیل سقف هر لایه حذف شدند" if g["meta"].get("truncated_nodes") else ""))
    if not g["edges"]:
        st.info("در این لایه رابطه‌ای پیدا نشد؛ لایه یا مبدأ دیگری انتخاب کنید.")
    pv.show(pv.build_html(g, height=700, show_edge_labels=True, highlight_nodes=set(seeds)), 700)
