"""چرخه‌ی عمر Projection در حافظه‌ی GDS (Create / List / Drop / Refresh). داده‌ی اصلی تغییر نمی‌کند."""
from __future__ import annotations

import streamlit as st

from database.neo4j_connection import run_gds

ORIENTATIONS = ("UNDIRECTED", "NATURAL", "REVERSE")


def list_projections() -> list[dict]:
    return run_gds(
        "CALL gds.graph.list() YIELD graphName, nodeCount, relationshipCount, creationTime, memoryUsage "
        "RETURN graphName AS name, nodeCount AS nodes, relationshipCount AS relationships, "
        "toString(creationTime) AS created, memoryUsage AS memory ORDER BY name")


def exists(name: str) -> bool:
    return bool(run_gds("CALL gds.graph.exists($n) YIELD exists RETURN exists", {"n": name})[0]["exists"])


def create_projection(name: str, node_labels: list[str], orientation: str = "UNDIRECTED",
                      rel_types: list[str] | None = None) -> dict:
    """
    rel_types خالی ⇒ همه‌ی رابطه‌ها (Native Projection روی نوع :RELATION).
    در غیر این صورت فقط رابطه‌هایی که خاصیت `type` آن‌ها در لیست است (Aggregation Projection).
    """
    if orientation not in ORIENTATIONS:
        raise ValueError("orientation نامعتبر است.")
    if exists(name):
        raise ValueError(f"Projection با نام «{name}» از قبل وجود دارد. ابتدا Drop کنید یا نام دیگری بدهید.")
    if not node_labels:
        raise ValueError("حداقل یک نوع نود انتخاب کنید.")
    if not rel_types:
        rows = run_gds(
            "CALL gds.graph.project($n, $labels, {RELATION: {orientation: $o}}) "
            "YIELD graphName, nodeCount, relationshipCount, projectMillis "
            "RETURN graphName AS name, nodeCount AS nodes, relationshipCount AS relationships, projectMillis AS ms",
            {"n": name, "labels": node_labels, "o": orientation})
    else:
        rows = run_gds(
            "MATCH (s)-[r:RELATION]->(t) WHERE any(l IN labels(s) WHERE l IN $labels) "
            "AND any(l IN labels(t) WHERE l IN $labels) AND r.type IN $types "
            "WITH gds.graph.project($n, s, t, {sourceNodeLabels: labels(s), targetNodeLabels: labels(t)}, "
            "{undirectedRelationshipTypes: CASE WHEN $o = 'UNDIRECTED' THEN ['*'] ELSE [] END}) AS g "
            "RETURN g.graphName AS name, g.nodeCount AS nodes, g.relationshipCount AS relationships, "
            "g.projectMillis AS ms",
            {"n": name, "labels": node_labels, "types": rel_types, "o": orientation})
    cfg = {"labels": node_labels, "orientation": orientation, "rel_types": rel_types or []}
    st.session_state.setdefault("gds_cfg", {})[name] = cfg
    list_cache_clear()
    return rows[0]


def drop_projection(name: str) -> None:
    run_gds("CALL gds.graph.drop($n, false) YIELD graphName RETURN graphName", {"n": name})
    st.session_state.get("gds_cfg", {}).pop(name, None)
    list_cache_clear()


def refresh_projection(name: str) -> dict:
    """Drop + Create با همان تنظیمات (بعد از تغییر Graph اصلی)."""
    cfg = st.session_state.get("gds_cfg", {}).get(name)
    if not cfg:
        raise ValueError("تنظیمات این Projection در این Session موجود نیست؛ آن را Drop و دوباره Create کنید.")
    drop_projection(name)
    return create_projection(name, cfg["labels"], cfg["orientation"], cfg["rel_types"])


def list_cache_clear() -> None:
    st.session_state["gds_last_list"] = None
