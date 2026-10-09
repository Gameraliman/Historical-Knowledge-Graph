"""🧠 Graph Analytics (Neo4j GDS) — فقط In-Memory Projection و خروجی stream؛ داده‌ی اصلی تغییر نمی‌کند."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from config import settings
from graph import graph_builder as gb
from graph import graph_filters as gf
from gds import centrality, community_detection, gds_projection as proj, node_similarity, pagerank
from gds.algorithms import writeback_pagerank
from gds.gds_connection import GDS_MISSING, gds_status
from utils import caching
from utils.formatting import db_guard, fmt_int, header
from visualization import plotly_charts as pc
from visualization import pyvis_graph as pv


def _need_projection() -> str | None:
    name = st.session_state.get("gds_active")
    if not name:
        st.warning("⚠ Please create a GDS projection first.")
        return None
    return name


def _guard_run(fn, *a, **k):
    """خطای الگوریتم (مثلاً Louvain روی Projection جهت‌دار) را تمیز نشان می‌دهد."""
    try:
        return fn(*a, **k)
    except Exception as exc:  # noqa: BLE001
        text = str(getattr(exc, "message", exc))
        st.error(f"⚠ اجرای الگوریتم ناموفق بود: {text}")
        if "undirected" in text.lower() or "orientation" in text.lower():
            st.info("این الگوریتم به Projection با orientation = UNDIRECTED نیاز دارد.")
        return None


def _overlay(kind: str, title: str, df: pd.DataFrame, col: str) -> None:
    st.session_state["kg_overlay"] = {"kind": kind, "title": title, "values": dict(zip(df["id"], df[col]))}


def _show_graph(ids: list[str], overlay: dict | None, highlight: set | None = None, with_neighbors: bool = False,
                key: str = "g") -> None:
    g = gb.graph_from_ids(ids, with_neighbors=with_neighbors, max_nodes=500)
    pv.show(pv.build_html(g, height=620, overlay=overlay, highlight_nodes=highlight), 620)
    st.caption(f"{len(g['nodes'])} نود · {len(g['edges'])} رابطه. همین نتیجه در Graph Explorer هم قابل اعمال است (چک‌باکس «اعمال نتایج GDS»).")


@db_guard
def render() -> None:
    header("🧠 Graph Analytics", "Neo4j Graph Data Science — تحلیل ساختار گراف روی In-Memory Projection")
    ok, info = gds_status()
    if not ok:
        st.warning(GDS_MISSING)
        st.caption(info)
        return
    st.caption(f"GDS version {info} · Read-Only: الگوریتم‌ها در حالت stream اجرا می‌شوند و چیزی روی Neo4j نمی‌نویسند.")

    projections = proj.list_projections()
    names = [p["name"] for p in projections]
    if st.session_state.get("gds_active") not in names:
        st.session_state["gds_active"] = names[0] if names else None
    if names:
        st.selectbox("Projection فعال", names, key="gds_active")

    t_proj, t_pr, t_cen, t_com, t_sim, t_stat = st.tabs(
        ["🧱 Projection", "PageRank", "Centrality", "Community Detection", "Graph Node Similarity", "📈 آمار"])

    # ---------------- Projection ----------------
    with t_proj:
        st.markdown("#### Graph Projection")
        c1, c2 = st.columns(2)
        name = c1.text_input("Name", settings.GDS_DEFAULT_PROJECTION, key="gds_name")
        orient = c2.selectbox("Orientation", proj.ORIENTATIONS, key="gds_orient",
                              help="Louvain/Leiden/Closeness/Betweenness معمولاً UNDIRECTED می‌خواهند.")
        labels = caching.cached_labels()
        node_labels = st.multiselect("Node Types", labels, default=labels, key="gds_labels", format_func=settings.label_fa)
        rels = gf.rel_type_filter("gds_rels")
        st.caption("نوع رابطه‌ی Neo4j همیشه `RELATION` است؛ انتخاب بالا (در صورت پر بودن) روی خاصیت `type` فیلتر می‌کند. خالی = All.")
        b1, b2 = st.columns(2)
        if b1.button("Create Projection", type="primary", use_container_width=True):
            r = _guard_run(proj.create_projection, name.strip(), node_labels, orient, rels)
            if r:
                st.success(f"ساخته شد: {fmt_int(r['nodes'])} نود، {fmt_int(r['relationships'])} رابطه ({r['ms']} ms)")
                st.session_state["gds_active"] = name.strip()
                st.rerun()
        if names:
            target = st.selectbox("Projection برای Drop / Refresh", names, key="gds_target")
            if b2.button("Drop Projection", use_container_width=True):
                _guard_run(proj.drop_projection, target)
                st.rerun()
            if st.button("🔄 Refresh Projection", use_container_width=False):
                r = _guard_run(proj.refresh_projection, target)
                if r:
                    st.success(f"به‌روز شد: {fmt_int(r['nodes'])} نود، {fmt_int(r['relationships'])} رابطه")
        st.markdown("#### Projectionهای موجود")
        if projections:
            st.dataframe(pd.DataFrame(projections), hide_index=True, use_container_width=True)
        else:
            st.caption("هنوز Projection ساخته نشده است.")

    # ---------------- PageRank ----------------
    with t_pr:
        c1, c2, c3 = st.columns(3)
        it = c1.number_input("Iterations", 1, 200, 20, key="pr_it")
        damp = c2.number_input("Damping Factor", 0.05, 0.99, 0.85, 0.01, key="pr_d")
        topk = c3.number_input("Top K (نمایش)", 5, 200, 20, key="pr_k")
        if st.button("Run PageRank", type="primary"):
            p = _need_projection()
            if p:
                df = _guard_run(pagerank.run_pagerank, p, int(it), float(damp), 1000)
                if df is not None:
                    st.session_state["gds_pr"] = df
        df = st.session_state.get("gds_pr")
        if df is not None and not df.empty:
            top = df.head(int(topk))
            st.dataframe(top[["rank", "name", "type", "score"]].rename(columns={"rank": "Rank", "name": "Entity", "type": "نوع", "score": "Score"}),
                         hide_index=True, use_container_width=True)
            st.plotly_chart(pc.hbar_typed(top, "name", "score", "type", "PageRank — Top Nodes"), use_container_width=True)
            if st.button("Show PageRank on Graph"):
                _overlay("score", "PageRank", df, "score")
                _show_graph(top["id"].tolist(), st.session_state["kg_overlay"], set(top["id"].head(5)), with_neighbors=True)
            if settings.ALLOW_GDS_WRITEBACK:
                with st.expander("⚠ ذخیره‌ی PageRank روی Neo4j (تغییر داده‌ی اصلی)"):
                    prop = st.text_input("نام خاصیت", "gds_pagerank")
                    if st.checkbox("می‌دانم این کار روی Neo4j خاصیت جدید می‌نویسد") and st.button("ذخیره"):
                        p = _need_projection()
                        r = p and _guard_run(writeback_pagerank, p, int(it), float(damp), prop)
                        if r:
                            st.success(f"{r['nodePropertiesWritten']} خاصیت نوشته شد.")

    # ---------------- Centrality ----------------
    with t_cen:
        c1, c2 = st.columns(2)
        algo = c1.selectbox("Centrality Algorithm", list(centrality.ALGORITHMS), key="cen_algo")
        k = c2.number_input("Top K", 5, 200, 20, key="cen_k")
        if st.button("Run", key="cen_run", type="primary"):
            p = _need_projection()
            if p:
                df = _guard_run(centrality.run_centrality, p, algo, int(k))
                if df is not None:
                    st.session_state["gds_cen"] = (algo, df)
        res = st.session_state.get("gds_cen")
        if res and not res[1].empty:
            algo_name, df = res
            a, b, c = st.tabs(["Table", "Bar Chart", "Graph Highlight"])
            a.dataframe(df[["rank", "name", "type", "score"]].rename(columns={"rank": "Rank", "name": "Entity", "type": "نوع", "score": "Score"}),
                        hide_index=True, use_container_width=True)
            b.plotly_chart(pc.hbar_typed(df, "name", "score", "type", f"{algo_name} Centrality"), use_container_width=True)
            with c:
                _show_graph(df["id"].tolist(), None, set(df["id"]), with_neighbors=True)

    # ---------------- Community ----------------
    with t_com:
        algo = st.selectbox("Algorithm", list(community_detection.ALGORITHMS), key="com_algo")
        if st.button("Run", key="com_run", type="primary"):
            p = _need_projection()
            if p:
                out = _guard_run(community_detection.run_communities, p, algo)
                if out is not None:
                    st.session_state["gds_com"] = out
        out = st.session_state.get("gds_com")
        if out and not out[0].empty:
            nodes_df, summary = out
            st.dataframe(summary.rename(columns={"community": "Community", "nodes": "Number of Nodes"}).head(200),
                         hide_index=True, use_container_width=True, height=240)
            st.plotly_chart(pc.community_sizes(summary), use_container_width=True)
            c1, c2 = st.columns(2)
            n_comm = c1.slider("تعداد جامعه‌ی بزرگ برای نمایش", 1, 10, 5, key="com_n")
            per = c2.slider("حداکثر نود از هر جامعه", 10, 150, 60, 10, key="com_per")
            if st.button("Visualize Communities"):
                _overlay("community", "Community", nodes_df, "community")
                big = summary["community"].head(n_comm).tolist()
                ids: list[str] = []
                for cid in big:
                    ids += nodes_df[nodes_df["community"] == cid].sort_values("degree", ascending=False)["id"].head(per).tolist()
                _show_graph(ids, st.session_state["kg_overlay"])

    # ---------------- Similarity ----------------
    with t_sim:
        st.markdown("#### Graph Node Similarity")
        st.caption("پیدا کردن نودهایی که از نظر همسایه‌ها و ساختار گراف مشابه‌اند (شباهت ساختاری؛ ابزار یکی‌سازی Entity نیست).")
        c1, c2, c3 = st.columns(3)
        k = c1.number_input("topK برای هر نود", 1, 50, 10, key="sim_k")
        cut = c2.number_input("حداقل شباهت", 0.0, 1.0, 0.5, 0.05, key="sim_c")
        n = c3.number_input("حداکثر جفت (topN)", 10, 2000, 200, 50, key="sim_n")
        if st.button("Run", key="sim_run", type="primary"):
            p = _need_projection()
            if p:
                df = _guard_run(node_similarity.run_similarity, p, int(k), float(cut), int(n))
                if df is not None:
                    st.session_state["gds_sim"] = df
        df = st.session_state.get("gds_sim")
        if df is not None:
            if df.empty:
                st.info("جفتی با این آستانه پیدا نشد؛ حداقل شباهت را کمتر کنید.")
            else:
                st.dataframe(df[["node1", "node2", "similarity"]].rename(columns={"node1": "Node 1", "node2": "Node 2", "similarity": "Similarity"}),
                             hide_index=True, use_container_width=True)

    # ---------------- Stats ----------------
    with t_stat:
        totals = caching.cached_totals()
        active = next((p for p in projections if p["name"] == st.session_state.get("gds_active")), None)
        a, b, c, d = st.columns(4)
        a.metric("Graph Nodes", fmt_int(totals["nodes"]))
        b.metric("Graph Relationships", fmt_int(totals["relationships"]))
        c.metric("Projection Nodes", fmt_int(active["nodes"]) if active else "—")
        d.metric("Projection Relationships", fmt_int(active["relationships"]) if active else "—")
        last = st.session_state.get("gds_last")
        e, f = st.columns(2)
        e.metric("Last Algorithm", last["algorithm"] if last else "—")
        f.metric("Execution Time", f"{last['seconds']} s" if last else "—")
