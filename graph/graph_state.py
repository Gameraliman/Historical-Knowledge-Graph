"""حفظ وضعیت گراف در Session (Undo / Reset / نشانک / تاریخچه‌ی جستجو)."""
from __future__ import annotations

import streamlit as st

from graph import graph_builder as gb

K_GRAPH, K_HIST, K_FOCUS, K_BOOK, K_RECENT, K_OVERLAY = (
    "kg_graph", "kg_history", "kg_focus", "kg_bookmarks", "kg_recent", "kg_overlay")


def init() -> None:
    st.session_state.setdefault(K_GRAPH, gb.new_graph())
    st.session_state.setdefault(K_HIST, [])       # هر عضو: گسترش‌های قابل Undo
    st.session_state.setdefault(K_FOCUS, None)
    st.session_state.setdefault(K_BOOK, {})
    st.session_state.setdefault("kg_trail", [])   # مسیر کاربر: جستجو → گسترش → ...
    st.session_state.setdefault(K_RECENT, [])
    st.session_state.setdefault(K_OVERLAY, None)


def graph() -> dict:
    init()
    return st.session_state[K_GRAPH]


def set_graph(g: dict, focus: str | None = None, label: str = "") -> None:
    init()
    st.session_state[K_GRAPH] = g
    st.session_state[K_HIST] = []
    st.session_state[K_FOCUS] = focus
    st.session_state["kg_trail"] = [label] if label else []


def add_expansion(nodes: list[dict], edges: list[dict], label: str) -> tuple[int, int]:
    g = graph()
    added_n, added_e = gb.merge(g, nodes, edges)
    st.session_state[K_HIST].append({"nodes": added_n, "edges": added_e, "label": label})
    st.session_state["kg_trail"].append(label)
    return len(added_n), len(added_e)


def undo() -> bool:
    g, hist = graph(), st.session_state[K_HIST]
    if not hist:
        return False
    last = hist.pop()
    for i in last["edges"]:
        g["edges"].pop(i, None)
    for i in last["nodes"]:
        g["nodes"].pop(i, None)
    if st.session_state["kg_trail"]:
        st.session_state["kg_trail"].pop()
    if st.session_state[K_FOCUS] not in g["nodes"]:
        st.session_state[K_FOCUS] = next(iter(g["nodes"]), None)
    return True


def reset() -> None:
    init()
    st.session_state[K_GRAPH] = gb.new_graph()
    st.session_state[K_HIST] = []
    st.session_state[K_FOCUS] = None
    st.session_state["kg_trail"] = []
    st.session_state[K_OVERLAY] = None


def toggle_bookmark(node: dict) -> bool:
    init()
    b = st.session_state[K_BOOK]
    if node["id"] in b:
        del b[node["id"]]
        return False
    b[node["id"]] = {"id": node["id"], "name": node["name"], "type": node["type"]}
    return True


def add_recent(node: dict) -> None:
    init()
    r = [x for x in st.session_state[K_RECENT] if x["id"] != node["id"]]
    r.insert(0, {"id": node["id"], "name": node["name"], "type": node["type"]})
    st.session_state[K_RECENT] = r[:12]
