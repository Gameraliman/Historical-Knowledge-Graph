"""Callbackها و منطق وضعیت صفحه‌ی Bloom. کلیدهای ویجت‌های پایدار با `bl_` و دکمه‌ها/جدول‌ها با `bb_`/`bt_` شروع می‌شوند."""
from __future__ import annotations

import functools

import streamlit as st
from neo4j.exceptions import Neo4jError

from config import settings
from database import queries as q
from database.neo4j_connection import Neo4jUnavailable
from graph import graph_builder as gb
from graph import graph_search as gs
from graph import graph_state as gstate
from utils import caching
from utils.formatting import fmt_int


def msg(kind: str, text: str) -> None:
    st.session_state["bl_msg"] = (kind, text)


def safe_cb(fn):
    """خطای Neo4j در Callback به پیام تبدیل می‌شود (برنامه Crash نمی‌کند)."""
    @functools.wraps(fn)
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        except Neo4jUnavailable as exc:
            msg("error", f"⚠ Neo4j connection failed. {exc}")
        except Neo4jError as exc:
            msg("error", f"⚠ خطای Neo4j: {exc}")
    return wrapper


def active_types() -> list[str]:
    """انواع نود فعال برای Queryها ([] یعنی همه)."""
    labels = caching.cached_labels()
    sel = [t for t in labels if st.session_state.get(f"bl_ft_{t}", True)]
    return [] if len(sel) == len(labels) else sel


def active_rels() -> list[str]:
    return list(st.session_state.get("bl_rels", []))


def keep_widget_state() -> None:
    """ویجت‌های بخش‌های بسته‌ی آکاردئون رندر نمی‌شوند و Streamlit مقدارشان را فراموش می‌کند؛ اینجا نگه داشته می‌شود."""
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith("bl_"):
            st.session_state[k] = st.session_state[k]


# ----------------------------- آکاردئون -----------------------------
def toggle_section(key: str) -> None:
    st.session_state["bl_open"] = None if st.session_state.get("bl_open") == key else key


def open_section(key: str) -> None:
    st.session_state["bl_open"] = key


# ----------------------------- جستجو / نمایش -----------------------------
@safe_cb
def open_node(node: dict, depth: int | None = None) -> None:
    depth = depth or st.session_state.get("bl_depth", 2)
    mode = st.session_state.get("bl_mode", gb.MODE_CUMULATIVE)
    g = gb.build_subgraph([node["id"]], depth, active_types(), active_rels(),
                          st.session_state.get("bl_max", settings.DEFAULT_MAX_NODES), mode=mode)
    gstate.set_graph(g, focus=node["id"], label=f"جستجو: {node['name']}")
    gstate.add_recent(node)
    st.session_state["bl_selected"] = node["id"]
    st.session_state["bl_pending"] = None
    st.session_state["bl_hl"] = None
    note = " (به‌دلیل سقف تعداد، گراف کوتاه‌شده است)" if g["meta"]["truncated_nodes"] else ""
    msg("success", f"{fmt_int(len(g['nodes']))} نود و {fmt_int(len(g['edges']))} رابطه بارگذاری شد. "
                   f"({layers_text(g['meta'].get('layer_counts', []))}){note}")


def layers_text(counts: list[int]) -> str:
    return " · ".join(f"{'مبدأ' if k == 0 else f'لایه {k}'}: {c}" for k, c in enumerate(counts))


@safe_cb
def do_search() -> None:
    term = st.session_state.get("bl_term", "")
    t = st.session_state.get("bl_type", "All")
    results = gs.search(term, [] if t == "All" else [t], 30)
    st.session_state["bl_results"] = results
    if not results:
        msg("warning", "نودی با این عبارت پیدا نشد.")
        return
    open_node(results[0])


@safe_cb
def do_expand(node: dict) -> None:
    layers = st.session_state.get("bl_layers", 1)
    mode = st.session_state.get("bl_xmode", gb.MODE_CUMULATIVE)
    nodes, edges, counts = gb.expansion(gstate.graph(), node["id"], layers, active_types(), active_rels(),
                                        st.session_state.get("bl_max", settings.DEFAULT_MAX_NODES), mode)
    what = f"فقط لایه {layers}" if mode == gb.MODE_EXACT else f"{layers} لایه"
    n, e = gstate.add_expansion(nodes, edges, f"گسترش {what}: {node['name']}")
    st.session_state["kg_focus"] = node["id"]
    gstate.add_recent(node)
    msg("success" if n or e else "info",
        f"{n} نود و {e} رابطه‌ی جدید اضافه شد. ({layers_text(counts)})" if n or e
        else f"در این لایه نود یا رابطه‌ی جدیدی نیست. ({layers_text(counts)})")


def do_undo() -> None:
    if not gstate.undo():
        msg("info", "گسترشی برای Undo وجود ندارد.")
    st.session_state["bl_hl"] = None


def do_reset() -> None:
    gstate.reset()
    for k in ("bl_results", "bl_pending", "bl_hl", "bl_selected"):
        st.session_state.pop(k, None)


# ----------------------------- نمایش کل گراف -----------------------------
@safe_cb
def request_entire() -> None:
    c = q.count_filtered(active_types(), active_rels())
    if c["nodes"] > settings.ENTIRE_WARN_NODES or c["relationships"] > settings.ENTIRE_WARN_EDGES:
        st.session_state["bl_pending"] = c
    else:
        render_entire()


@safe_cb
def render_entire() -> None:
    g = gb.entire_graph(active_types(), active_rels())
    gstate.set_graph(g, focus=None, label="کل گراف")
    st.session_state["bl_pending"] = None
    st.session_state["bl_hl"] = None
    st.session_state["bl_physics"] = len(g["nodes"]) <= 1500
    st.session_state["bl_labels"] = len(g["nodes"]) <= 1500
    note = " (سقف مطلق رسیدن شد)" if g["meta"]["truncated_nodes"] or g["meta"]["truncated_edges"] else ""
    msg("success", f"کل گراف: {fmt_int(len(g['nodes']))} نود، {fmt_int(len(g['edges']))} رابطه.{note}")


@safe_cb
def explore_limited() -> None:
    top = caching.cached_top_degree(15, None)
    g = gb.build_subgraph([r["id"] for r in top], 1, active_types(), active_rels(), settings.DEFAULT_MAX_NODES)
    gstate.set_graph(g, focus=None, label="گراف محدود (پرارتباط‌ترین نودها)")
    st.session_state["bl_pending"] = None
    msg("success", f"{len(g['nodes'])} نود و {len(g['edges'])} رابطه بارگذاری شد.")


# ----------------------------- نشانک / مسیر / داده‌ها -----------------------------
def do_bookmark(node: dict) -> None:
    on = gstate.toggle_bookmark(node)
    msg("success", f"«{node['name']}» {'به نشانک‌ها اضافه شد ⭐' if on else 'از نشانک‌ها حذف شد'}.")


def set_path_end(which: str, node: dict) -> None:
    """مبدأ یا مقصد یابنده‌ی مسیر را از گره‌ی انتخاب‌شده تنظیم و بخش مسیر را باز می‌کند."""
    st.session_state[f"bl_pf_{which}_preset"] = node
    st.session_state[f"bl_pf_{which}_q"] = ""
    open_section("path")


@safe_cb
def apply_path(paths: list[dict], idx: int) -> None:
    """مسیر انتخاب‌شده را به گراف جاری اضافه و Highlight می‌کند."""
    p = paths[idx]
    g = gstate.graph()
    new_nodes = [gb._node(n) for n in p["nodes"] if n["id"] not in g["nodes"]]
    all_ids = list(g["nodes"]) + [n["id"] for n in new_nodes]
    new_edges = [gb._edge(r) for r in p["rels"] if r["id"] not in g["edges"]
                 and r["source"] in all_ids and r["target"] in all_ids]
    # گره‌ها باید قبل از یال‌ها در گراف باشند
    n_added, e_added = gstate.add_expansion(new_nodes, new_edges, f"مسیر: {p['nodes'][0]['name']} ⟶ {p['nodes'][-1]['name']}")
    st.session_state["bl_hl"] = {"nodes": [n["id"] for n in p["nodes"]], "edges": [r["id"] for r in p["rels"]]}
    st.session_state["kg_focus"] = p["nodes"][0]["id"]


@safe_cb
def show_relation(rel_id: str) -> None:
    """رابطه‌ای از جدول داده‌ها را همراه دو سرش روی گراف می‌آورد."""
    e = q.edge_detail(rel_id)
    if not e:
        msg("warning", "رابطه پیدا نشد.")
        return
    nodes = [gb._node(r) for r in q.nodes_by_ids([e["source_id"], e["target_id"]])]
    edge = {"id": e["id"], "source": e["source_id"], "target": e["target_id"], "type": e["type"],
            "source_count": (e["props"] or {}).get("source_count", 0)}
    g = gstate.graph()
    if not g["nodes"]:
        gstate.set_graph(gb.new_graph(), label="از جدول داده‌ها")
    gstate.add_expansion(nodes, [edge], f"رابطه: {e['source']} — {e['type']} — {e['target']}")
    st.session_state["bl_hl"] = {"nodes": [e["source_id"], e["target_id"]], "edges": [e["id"]]}
    st.session_state["kg_focus"] = e["source_id"]
    msg("success", "رابطه روی گراف نمایش داده شد.")


def clear_highlight() -> None:
    st.session_state["bl_hl"] = None
