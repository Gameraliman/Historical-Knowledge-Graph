"""Query Console شبیه Neo4j Browser. فقط Read-Only (بررسی متنی + Session با READ_ACCESS)."""
from __future__ import annotations

import time

import pandas as pd
import streamlit as st
from neo4j.graph import Node, Path, Relationship
from neo4j.exceptions import Neo4jError

from config import settings
from database.neo4j_connection import run_read
from graph import graph_builder as gb
from utils.formatting import db_guard, header
from utils.security import check_read_only
from visualization import pyvis_graph as pv

SAMPLES = {
    "۲۵ شخص": "MATCH (n:Person)\nRETURN n\nLIMIT 25",
    "همسایه‌های یک Entity (گراف)": "MATCH p=(a {name: 'تهران'})-[:RELATION]-(b)\nRETURN p\nLIMIT 50",
    "رابطه‌های پرتکرار": "MATCH ()-[r:RELATION]->()\nRETURN r.type AS relation, count(*) AS count\nORDER BY count DESC\nLIMIT 25",
    "نودهای پرارتباط": "MATCH (n)\nRETURN n.name AS name, labels(n)[0] AS type, COUNT { (n)--() } AS degree\nORDER BY degree DESC\nLIMIT 25",
    "پدر ← فرزند": "MATCH (a:Person)-[r:RELATION {type: 'پدر'}]->(b:Person)\nRETURN a, r, b\nLIMIT 40",
}


def _py(v):
    if isinstance(v, Node):
        return {"_id": v.element_id, "_labels": list(v.labels), **dict(v)}
    if isinstance(v, Relationship):
        return {"_id": v.element_id, "_type": v.type, **dict(v)}
    if isinstance(v, Path):
        return " → ".join(str(n.get("name", n.element_id)) for n in v.nodes)
    if isinstance(v, (list, tuple)):
        return [_py(x) for x in v]
    if isinstance(v, dict):
        return {k: _py(x) for k, x in v.items()}
    return v


@db_guard
def render() -> None:
    header("Query Console", "اجرای Cypher فقط‌خواندنی — شبیه Neo4j Browser")
    c1, c2 = st.columns([3, 1])
    sample = c2.selectbox("نمونه Query", ["—"] + list(SAMPLES), key="qc_sample")
    if sample != "—" and st.session_state.get("qc_last_sample") != sample:
        st.session_state["qc_text"] = SAMPLES[sample]
        st.session_state["qc_last_sample"] = sample
    st.session_state.setdefault("qc_text", SAMPLES["۲۵ شخص"])
    with c1:
        st.markdown('<div class="ltr">', unsafe_allow_html=True)
        query = st.text_area("Cypher Query", key="qc_text", height=170)
        st.markdown("</div>", unsafe_allow_html=True)
    max_rows = c2.number_input("حداکثر ردیف", 10, settings.CONSOLE_MAX_ROWS, 500, 50)
    if st.button("▶ Run", type="primary"):
        ok, reason = check_read_only(query)
        if not ok:
            st.error(f"🚫 {reason}")
        else:
            t0 = time.perf_counter()
            try:
                records = run_read(query, max_rows=int(max_rows), raw=True)
                st.session_state["qc_result"] = {"records": records, "seconds": time.perf_counter() - t0, "limit": int(max_rows)}
            except Neo4jError as exc:
                st.error(f"⚠ خطای Cypher: {exc.message if hasattr(exc, 'message') else exc}")
                st.session_state["qc_result"] = None
    res = st.session_state.get("qc_result")
    if not res:
        with st.expander("راهنمای Schema"):
            st.markdown("- نودها: `(:Person|Location|Organization|Event|Time|Role|Work|Title|Object|Group|Quantity|Document {name, source_pageids, source_titles, source_urls, source_count})`\n"
                        "- رابطه‌ها: `[:RELATION {type, source_pageids, source_titles, source_urls, source_count}]` — نام واقعی رابطه در `r.type` است.")
        return
    records = res["records"]
    st.caption(f"{len(records)} ردیف · {res['seconds']:.2f} ثانیه" + (" · ⚠ به سقف ردیف رسید" if len(records) >= res["limit"] else ""))
    t1, t2, t3 = st.tabs(["📊 Table", "🕸 Graph", "📝 Text"])
    with t1:
        if records:
            df = pd.DataFrame([{k: _py(v) for k, v in r.items()} for r in records])
            st.dataframe(df.astype(str) if df.map(lambda x: isinstance(x, (dict, list))).any().any() else df,
                         use_container_width=True, hide_index=True)
            st.download_button("⬇ CSV", df.to_csv(index=False).encode("utf-8-sig"), "query_result.csv", "text/csv")
        else:
            st.info("نتیجه‌ای برنگشت.")
    with t2:
        g = gb.graph_from_records(records)
        if g["nodes"]:
            pv.show(pv.build_html(g, height=560, show_edge_labels=True), 560)
        else:
            st.info("نتیجه شامل Node/Relationship/Path نیست؛ در Query مثلاً `RETURN n` یا `RETURN p` بنویسید.")
    with t3:
        st.code("\n".join(str({k: _py(v) for k, v in r.items()}) for r in records[:200]), language="text")
