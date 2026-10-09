"""Source / Evidence: صفحات ویکی‌پدیا که گراف از آن‌ها ساخته شده و رابطه‌های استخراج‌شده از هر صفحه."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from database import queries as q
from utils import caching
from utils.formatting import db_guard, fmt_int, header, normalize_text


@db_guard
def render() -> None:
    header("Sources / Evidence", "منابع و شواهد (صفحات Wikipedia)")
    df = pd.DataFrame(caching.cached_source_pages())
    if df.empty:
        st.info("منبعی در گراف ثبت نشده است.")
        return
    st.caption(f"{fmt_int(len(df))} صفحه‌ی منبع")
    term = normalize_text(st.text_input("جستجو در عنوان صفحه", key="src_q"))
    view = df[df["title"].map(normalize_text).str.contains(term, regex=False)] if term else df
    st.dataframe(view.rename(columns={"pageid": "Page ID", "title": "Page", "url": "URL", "nodes": "تعداد نود"}),
                 hide_index=True, use_container_width=True, height=320,
                 column_config={"URL": st.column_config.LinkColumn("URL")})
    if view.empty:
        return
    pick = st.selectbox("صفحه برای مشاهده‌ی رابطه‌های استخراج‌شده", view["pageid"].tolist(), index=None, key="src_pick",
                        format_func=lambda i: f"{view.set_index('pageid').loc[i, 'title']} ({i})")
    if pick is None:
        return
    row = view.set_index("pageid").loc[pick]
    st.markdown(f"**Source:** Wikipedia · **Page:** [{row['title']}]({row['url']}) · **Page ID:** `{pick}`")
    rels = pd.DataFrame(q.relations_of_page(int(pick)))
    st.caption(f"{len(rels)} رابطه از این صفحه استخراج شده است.")
    if not rels.empty:
        st.dataframe(rels.rename(columns={"source": "Source", "source_type": "نوع مبدأ", "relation": "Relationship",
                                          "target": "Target", "target_type": "نوع مقصد"}),
                     hide_index=True, use_container_width=True)
