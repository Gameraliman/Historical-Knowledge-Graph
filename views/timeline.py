"""Timeline تاریخی از گره‌های مرتبط با Time (سال از متن شمسی/قمری/میلادی استخراج می‌شود)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from config import settings
from database import queries as q
from views import widgets
from utils import caching
from utils.formatting import db_guard, fmt_int, header
from visualization import timeline as tl


@db_guard
def render() -> None:
    header("Timeline", "خط زمانی رویدادهای تاریخی")
    labels = [t for t in caching.cached_labels() if t != "Time"]
    c1, c2, c3 = st.columns([2, 1.2, 2])
    types = c1.multiselect("نوع Entity", labels, default=["Event"] if "Event" in labels else labels[:1], key="tl_types",
                           format_func=settings.label_fa)
    cal = c2.radio("تقویم محور", ["شمسی", "میلادی"], horizontal=True, key="tl_cal")
    text = c3.text_input("فیلتر نام", key="tl_text")
    if not types:
        st.info("حداقل یک نوع انتخاب کنید.")
        return
    rows = caching.cached_time_links(tuple(types))
    df = tl.build_dataframe(rows)
    st.caption(f"{fmt_int(len(rows))} ارتباط با گره‌های Time پیدا شد؛ برای {fmt_int(len(df))} مورد سال قابل‌تشخیص بود "
               "(عبارت‌هایی مثل «دوره قاجار» فاقد سال‌اند و رسم نمی‌شوند).")
    if df.empty:
        st.warning("هیچ رویدادی با سال قابل‌تشخیص پیدا نشد.")
        return
    lo, hi = int(df["j_year" if cal == "شمسی" else "g_year"].min()), int(df["j_year" if cal == "شمسی" else "g_year"].max())
    rng = st.slider("بازه‌ی سال", lo, hi, (lo, hi), key="tl_range")
    col = "j_year" if cal == "شمسی" else "g_year"
    view = df[(df[col] >= rng[0]) & (df[col] <= rng[1])]
    if text.strip():
        view = view[view["name"].str.contains(text.strip(), case=False, regex=False)]
    if len(view) > 2000:
        view = view.sort_values("source_count", ascending=False).head(2000)
        st.caption("⚠ فقط ۲۰۰۰ مورد با بیشترین منبع نمایش داده می‌شود.")
    if view.empty:
        st.info("موردی با این فیلتر نیست.")
        return
    fig = tl.make_figure(view, cal)
    event = st.plotly_chart(fig, use_container_width=True, on_select="rerun", selection_mode="points", key="tl_chart")
    picked = None
    pts = (event or {}).get("selection", {}).get("points", []) if event else []
    if pts and pts[0].get("customdata"):
        picked = pts[0]["customdata"][0]
    st.caption("روی یک نقطه کلیک کنید، یا از فهرست زیر انتخاب کنید.")
    if not picked:
        opts = view.sort_values(col).drop_duplicates("id")
        picked = st.selectbox("رویداد", opts["id"].tolist(), index=None, placeholder="انتخاب رویداد…", key="tl_pick",
                              format_func=lambda i: f"{opts.set_index('id').loc[i, 'name']} — {opts.set_index('id').loc[i, 'time_text']}")
    if not picked:
        return
    st.divider()
    a, b = st.columns([1.2, 1])
    with a:
        widgets.render_node_detail(picked, key="tl", show_relations=False)
    with b:
        rels = pd.DataFrame(q.node_relations(picked, 500))
        for kind, title in (("Person", "👤 اشخاص"), ("Location", "📍 مکان‌ها"), ("Organization", "🏛 سازمان‌ها"), ("Time", "🕓 زمان‌ها")):
            sub = rels[rels["other_type"] == kind] if not rels.empty else rels
            st.markdown(f"**{title} ({len(sub)})**")
            if len(sub):
                st.dataframe(sub[["relation", "other"]].rename(columns={"relation": "رابطه", "other": "Entity"}),
                             hide_index=True, use_container_width=True, height=min(220, 40 + 35 * len(sub)))
