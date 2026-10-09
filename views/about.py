from __future__ import annotations

import streamlit as st

from config import settings
from utils.formatting import header


def render() -> None:
    header("About", "درباره‌ی سامانه و Schema داده")
    st.markdown(f"""
**Historical Knowledge Graph Explorer** — کاوشگر تعاملی گراف دانش تاریخی (Streamlit · Neo4j · GDS · Pyvis · Plotly).

### Schema در Neo4j (ساخته‌شده با `scripts/import_to_neo4j.py`)
- هر نود یک Label بر اساس نوعش دارد (`Person`, `Location`, `Organization`, `Event`, `Time`, `Role`, `Work`, …) و خاصیت‌های
  `name`, `source_pageids`, `source_titles`, `source_urls`, `source_count`.
- همه‌ی رابطه‌ها از نوع `:RELATION` هستند؛ نام واقعی (فارسی) در خاصیت `type` ذخیره شده است
  (حدود ۴٬۵۰۰ نوع)، به‌همراه همان فیلدهای منبع.

### اصل Read-Only
- Explorer و Query Console فقط می‌خوانند (Session در حالت `READ_ACCESS` + فهرست سفید دستورها).
- GDS فقط روی In-Memory Projection و در حالت `stream` اجرا می‌شود. ذخیره‌ی نتیجه روی Neo4j
  پیش‌فرض خاموش است (`ALLOW_GDS_WRITEBACK={settings.ALLOW_GDS_WRITEBACK}`).
- این نسخه Entity Resolution یا Merge/Delete خودکار ندارد. «Graph Node Similarity» فقط شباهت ساختاری را گزارش می‌کند.

### رنگ نودها
""")
    cols = st.columns(6)
    for i, (t, c) in enumerate(settings.NODE_COLORS.items()):
        cols[i % 6].markdown(f'<span class="kg-chip" style="background:{c}">{settings.NODE_TYPE_FA.get(t, t)} · {t}</span>',
                             unsafe_allow_html=True)
