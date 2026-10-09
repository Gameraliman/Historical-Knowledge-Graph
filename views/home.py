"""داشبورد اصلی: آمار مستقیم از Neo4j."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from config import settings
from utils import caching
from utils.formatting import db_guard, header, stat_card
from visualization import plotly_charts as pc


@db_guard
def render() -> None:
    header("Historical Knowledge Graph", "داشبورد آماری گراف دانش تاریخی")
    totals = caching.cached_totals()
    by_type = {r["type"]: r["count"] for r in caching.cached_counts_by_label()}

    cards = [(f"{settings.NODE_TYPE_FA.get(t, t)} · {t}", by_type.get(t, 0), settings.color_of(t))
             for t in settings.HOME_CARD_TYPES]
    cards.append(("روابط · Relations", totals["relationships"], "#344054"))
    cols = st.columns(len(cards))
    for col, (label, value, color) in zip(cols, cards):
        col.markdown(stat_card(label, value, color), unsafe_allow_html=True)
    st.write("")
    extra = st.columns(4)
    extra[0].markdown(stat_card("کل نودها", totals["nodes"], "#018bff"), unsafe_allow_html=True)
    extra[1].markdown(stat_card("انواع متفاوت رابطه", totals["relation_types"], "#7B6FD6"), unsafe_allow_html=True)
    extra[2].markdown(stat_card("صفحات منبع (Wikipedia)", totals["source_pages"], "#57C7A5"), unsafe_allow_html=True)
    others = sum(v for k, v in by_type.items() if k not in settings.HOME_CARD_TYPES)
    extra[3].markdown(stat_card("سایر انواع (نقش، اثر، عنوان، …)", others, "#A5ABB6"), unsafe_allow_html=True)
    st.write("")

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(pc.bar_by_type(pd.DataFrame(caching.cached_counts_by_label()), "تعداد نودها بر اساس نوع"),
                        use_container_width=True)
    with c2:
        rel = pd.DataFrame(caching.cached_rel_types(15))
        st.plotly_chart(pc.hbar(rel.head(15), "type", "count", "۱۵ رابطه‌ی پرتکرار", "#7B6FD6"), use_container_width=True)

    top = pd.DataFrame(caching.cached_top_degree(20, None))
    st.plotly_chart(pc.hbar_typed(top, "name", "degree", "type", "Top Nodes بر اساس Degree"), use_container_width=True)
    with st.expander("جدول Top Nodes"):
        st.dataframe(top[["name", "type", "degree", "source_count"]].rename(
            columns={"name": "Entity", "type": "نوع", "degree": "Degree", "source_count": "منابع"}),
            hide_index=True, use_container_width=True)
    st.caption("برای به‌روزرسانی آمار پس از ایمپورت جدید: منوی ⋮ ← Clear cache.")
