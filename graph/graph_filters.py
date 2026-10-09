"""فیلتر نوع نود و رابطه (اعمال زنده روی گراف جاری)."""
from __future__ import annotations

import streamlit as st

from config import settings
from utils import caching


def node_type_filter(key: str = "f_types") -> list[str]:
    """چک‌باکس‌های نوع نود. خروجی: انواع انتخاب‌شده."""
    available = caching.cached_labels()
    counts = {r["type"]: r["count"] for r in caching.cached_counts_by_label()}
    selected = []
    for t in available:
        if st.checkbox(f"{settings.label_fa(t)} · {counts.get(t, 0):,}", value=True, key=f"{key}_{t}"):
            selected.append(t)
    return selected


def rel_type_filter(key: str = "f_rels") -> list[str]:
    """انتخاب نوع رابطه (خالی = همه). نام رابطه‌ها در خاصیت `type` است."""
    opts = caching.cached_rel_types(400)
    labels = {r["type"]: f"{r['type']} ({r['count']})" for r in opts}
    return st.multiselect("نوع رابطه (خالی = همه)", list(labels), format_func=lambda x: labels[x], key=key,
                          help="۴۰۰ رابطه‌ی پرتکرار. برای جستجو داخل کادر تایپ کنید.")


def apply(graph: dict, node_types: list[str], rel_types: list[str]) -> dict:
    """گراف فیلترشده (بدون تغییر در گراف اصلی)."""
    nodes = {i: n for i, n in graph["nodes"].items() if not node_types or n["type"] in node_types}
    edges = {i: e for i, e in graph["edges"].items()
             if e["source"] in nodes and e["target"] in nodes and (not rel_types or e["type"] in rel_types)}
    return {"nodes": nodes, "edges": edges, "meta": graph.get("meta", {})}
