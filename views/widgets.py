"""ویجت‌های مشترک بین صفحه‌ها: Inspector نود/رابطه، انتخاب Entity، نمایش منابع."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from config import settings
from database import queries as q
from graph import graph_search as gs
from utils.formatting import type_chip


def render_sources(props: dict) -> None:
    """منابع (صفحات ویکی‌پدیا) را با لینک قابل کلیک نشان می‌دهد."""
    ids = props.get("source_pageids") or []
    titles = props.get("source_titles") or []
    urls = props.get("source_urls") or []
    if not ids:
        st.caption("منبعی ثبت نشده است.")
        return
    st.markdown(f"**منابع ({len(ids)})**")
    for pid, title, url in list(zip(ids, titles, urls))[:50]:
        link = f"[{title or 'بدون عنوان'}]({url})" if url else (title or "بدون عنوان")
        st.markdown(f"- Wikipedia · {link} · Page ID: `{pid}`")
    if len(ids) > 50:
        st.caption(f"… و {len(ids) - 50} منبع دیگر")


def _props_table(props: dict) -> pd.DataFrame:
    skip = {"source_pageids", "source_titles", "source_urls"}
    return pd.DataFrame([{"property": k, "value": str(v)} for k, v in props.items() if k not in skip])


def render_node_detail(node_id: str, key: str = "nd", show_relations: bool = True) -> dict | None:
    """Node Inspector. خروجی: جزئیات نود (یا None)."""
    d = q.node_detail(node_id)
    if not d:
        st.warning("نود پیدا نشد (ممکن است Graph اصلی تغییر کرده باشد).")
        return None
    props, ntype = d["props"], (d["labels"] or ["Entity"])[0]
    st.markdown(f"#### {props.get('name', '')}")
    st.markdown(type_chip(settings.label_fa(ntype), settings.color_of(ntype)), unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.metric("رابطه‌ها", d["degree"])
    c2.metric("خروجی", d["out_degree"])
    c3.metric("ورودی", d["in_degree"])
    st.markdown("**Properties**")
    st.dataframe(_props_table(props), hide_index=True, use_container_width=True)
    render_sources(props)
    if show_relations:
        rels = q.node_relations(node_id, 300)
        if rels:
            st.markdown(f"**رابطه‌ها ({len(rels)}{'+' if len(rels) >= 300 else ''})**")
            df = pd.DataFrame([{"جهت": "←" if r["outgoing"] else "→", "رابطه": r["relation"], "Entity": r["other"],
                                "نوع": r["other_type"], "منابع": r["source_count"]} for r in rels])
            st.dataframe(df, hide_index=True, use_container_width=True, height=260)
    return {"id": node_id, "name": props.get("name", ""), "type": ntype}


def render_edge_detail(rel_id: str) -> None:
    """Relationship Inspector."""
    e = q.edge_detail(rel_id)
    if not e:
        st.warning("رابطه پیدا نشد.")
        return
    st.markdown("**RELATIONSHIP**")
    st.markdown(f"**Source:** {e['source']} {type_chip(e['source_type'], settings.color_of(e['source_type']))}",
                unsafe_allow_html=True)
    st.markdown(f"**Type:** `{e['type']}`")
    st.markdown(f"**Target:** {e['target']} {type_chip(e['target_type'], settings.color_of(e['target_type']))}",
                unsafe_allow_html=True)
    st.dataframe(_props_table(e["props"]), hide_index=True, use_container_width=True)
    render_sources(e["props"])


def entity_picker(label: str, key: str, types: list[str] | None = None) -> dict | None:
    """جستجو + انتخاب یک Entity. اگر `{key}_preset` در session باشد، به‌عنوان گزینه‌ی پیش‌فرض می‌آید."""
    preset = st.session_state.get(f"{key}_preset")
    term = st.text_input(f"{label} — جستجو", key=f"{key}_q", placeholder="نام را تایپ کنید و Enter بزنید")
    results = gs.search(term, types, 25) if term.strip() else []
    options = {r["id"]: r for r in results}
    if preset and preset["id"] not in options and not term.strip():
        options = {preset["id"]: {**preset, "degree": "", "source_count": ""}}
    if not options:
        st.caption("نتیجه‌ای نیست." if term.strip() else "برای شروع جستجو کنید.")
        return None
    ids = list(options)
    if st.session_state.get(f"{key}_sel") not in ids:     # گزینه‌ی قبلی دیگر در نتایج نیست
        st.session_state.pop(f"{key}_sel", None)
    idx = ids.index(preset["id"]) if preset and preset["id"] in ids else 0
    pick = st.selectbox(label, ids, index=idx, key=f"{key}_sel",
                        format_func=lambda i: f"{options[i]['name']} · {options[i]['type']}"
                                              + (f" · {options[i]['degree']} رابطه" if options[i].get('degree') != "" else ""))
    return options[pick]
