"""بازبینی روابط استخراج‌شده قبل از انتقال به Neo4j (مشترک بین «Wiki Import» دستی و Mailbox)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ingest import entity_links, neo4j_ingest


def review_df(relations: list[dict], canonical) -> pd.DataFrame:
    """جدول بازبینی. ستون «لینک»: طرفی از رابطه که نام استاندارد ویکی دارد؛ «موجود/جدید»: وجود نود با همان نوع و نام در گراف."""
    clean, nodes, _ = neo4j_ingest.normalize(relations)
    exist = neo4j_ingest.existing_nodes(list(nodes))
    canon = {entity_links.norm(c) for c in (canonical or [])}

    def via(r):
        s_ok, o_ok = entity_links.norm(r["subject"][0]) in canon, entity_links.norm(r["object"][0]) in canon
        return "S+O" if s_ok and o_ok else "S" if s_ok else "O" if o_ok else "—"

    return pd.DataFrame([{
        "✔": True, "لینک": via(r), "Subject": r["subject"][0], "نوع S": r["subject"][1],
        "S": "موجود" if (r["subject"][1], r["subject"][0]) in exist else "جدید",
        "Relation": r["relation"], "Object": r["object"][0], "نوع O": r["object"][1],
        "O": "موجود" if (r["object"][1], r["object"][0]) in exist else "جدید"} for r in clean])


def review_editor(relations: list[dict], canonical, key: str) -> pd.DataFrame | None:
    """جدول قابل‌ویرایش (فقط ستون ✔)؛ ردیف‌های انتخاب‌شده را برمی‌گرداند. اگر رابطه‌ی معتبری نباشد None."""
    df = review_df(relations, canonical)
    if df.empty:
        st.info("رابطه‌ی معتبری استخراج نشد.")
        return None
    edited = st.data_editor(df, hide_index=True, use_container_width=True, key=key,
                            disabled=[c for c in df.columns if c != "✔"], height=min(420, 60 + 35 * len(df)))
    chosen = edited[edited["✔"]]
    st.caption(f"{len(chosen)} از {len(df)} رابطه انتخاب شده است. «موجود» = نودی با همان نوع و نام دقیق از قبل در گراف هست "
               "(رابطه به همان نود وصل می‌شود)؛ «جدید» = نود تازه ساخته می‌شود.")
    return chosen


def to_relations(df: pd.DataFrame) -> list[dict]:
    return [{"subject": [r["Subject"], r["نوع S"]], "relation": r["Relation"], "object": [r["Object"], r["نوع O"]]}
            for r in df.to_dict("records")]
