"""ساخت Subgraph از Neo4j. ساختار گراف: {"nodes": {id: {...}}, "edges": {id: {...}}, "meta": {...}}"""
from __future__ import annotations

from collections import defaultdict

from config import settings
from database import queries as q


def new_graph() -> dict:
    return {"nodes": {}, "edges": {}, "meta": {"truncated_nodes": False, "truncated_edges": False}}


def _node(row: dict) -> dict:
    return {"id": row["id"], "name": row["name"] or "(بدون نام)", "type": row["type"] or "Entity",
            "source_count": row.get("source_count", 0)}


def _edge(row: dict) -> dict:
    return {"id": row["id"], "source": row["source"], "target": row["target"],
            "type": row["type"] or "RELATION", "source_count": row.get("source_count", 0)}


def merge(graph: dict, nodes: list[dict], edges: list[dict]) -> tuple[list[str], list[str]]:
    """نودها/یال‌های جدید را اضافه می‌کند و شناسه‌های تازه‌اضافه‌شده را برمی‌گرداند."""
    added_n, added_e = [], []
    for n in nodes:
        if n["id"] not in graph["nodes"]:
            graph["nodes"][n["id"]] = n
            added_n.append(n["id"])
    for e in edges:
        if e["id"] not in graph["edges"] and e["source"] in graph["nodes"] and e["target"] in graph["nodes"]:
            graph["edges"][e["id"]] = e
            added_e.append(e["id"])
    return added_n, added_e


MODE_CUMULATIVE, MODE_EXACT = "cumulative", "exact"


def layered(seed_ids: list[str], depth: int, mode: str, node_types: list[str], rel_types: list[str],
            per_layer: int, existing_ids: list[str] | None = None) -> dict:
    """
    BFS لایه‌به‌لایه از seedها.
      cumulative: همه‌ی لایه‌های ۱ تا depth.
      exact     : فقط لایه‌ی depth + نودهای اتصال‌دهنده‌ی لازم (والدهای لایه‌های قبل) و فقط یال‌های بین لایه‌های متوالی.
    پیمایش از میان نودهای از قبل نمایش‌داده‌شده (existing_ids) هم می‌گذرد؛ سقف per_layer فقط روی نودهای «جدید» هر لایه است.
    خروجی: {"nodes": [...], "dag": set[frozenset]|None, "layer_counts": [..], "truncated": bool}
    """
    depth = max(1, min(int(depth), settings.MAX_DEPTH))
    per_layer = max(1, min(int(per_layer), settings.HARD_MAX_NODES))
    existing = set(existing_ids or [])
    info = {r["id"]: _node(r) for r in q.nodes_by_ids(seed_ids)}
    layers: list[list[str]] = [list(info)]
    seen = set(info)
    parents: dict[str, set] = defaultdict(set)
    layer_of = {i: 0 for i in info}
    truncated = False
    for k in range(1, depth + 1):
        frontier = layers[-1]
        if not frontier:
            layers.append([])
            continue
        rows = q.neighbors_layer(frontier, list(seen), rel_types, node_types, min(per_layer + len(existing), 20000))
        new_layer, added = [], 0
        for r in rows:
            n = _node(r)
            seen.add(n["id"])
            if n["id"] not in existing:
                if added >= per_layer:
                    truncated = True
                    continue
                added += 1
            info[n["id"]] = n
            layer_of[n["id"]] = k
            new_layer.append(n["id"])
        layers.append(new_layer)
        for link in q.layer_links(frontier, new_layer):
            parents[link["b"]].add(link["a"])
        if len(rows) >= min(per_layer + len(existing), 20000):
            truncated = True

    if mode == MODE_EXACT:
        keep = set(layers[0])
        stack = list(layers[depth]) if len(layers) > depth else []
        keep |= set(stack)
        while stack:
            for p in parents.get(stack.pop(), ()):
                if p not in keep:
                    keep.add(p)
                    stack.append(p)
        dag = {frozenset((p, b)) for b in keep for p in parents.get(b, ()) if p in keep}
        selected = [i for i in info if i in keep]
    else:
        dag, selected = None, list(info)
    counts = [sum(1 for i in selected if layer_of.get(i) == k) for k in range(len(layers))]
    return {"nodes": [info[i] for i in selected], "dag": dag, "layer_counts": counts, "truncated": truncated}


def _filter_dag(edges: list[dict], dag: set | None) -> list[dict]:
    return edges if dag is None else [e for e in edges if frozenset((e["source"], e["target"])) in dag]


def build_subgraph(seed_ids: list[str], depth: int, node_types: list[str], rel_types: list[str],
                   max_nodes: int, max_edges: int | None = None, mode: str = MODE_CUMULATIVE) -> dict:
    g = new_graph()
    res = layered(seed_ids, depth, mode, node_types, rel_types, max_nodes)
    merge(g, res["nodes"], [])
    limit = max_edges or settings.HARD_MAX_EDGES
    edges = _filter_dag(q.edges_among(list(g["nodes"]), rel_types, limit), res["dag"])
    merge(g, [], [_edge(e) for e in edges])
    g["meta"] = {"truncated_nodes": res["truncated"], "truncated_edges": len(edges) >= limit,
                 "layer_counts": res["layer_counts"], "mode": mode}
    return g


def expansion(graph: dict, node_id: str, layers: int, node_types: list[str], rel_types: list[str],
              max_nodes: int, mode: str = MODE_CUMULATIVE) -> tuple[list[dict], list[dict], list[int]]:
    """همسایه‌های node_id را (cumulative: تا layers لایه، exact: فقط لایه‌ی layers) می‌گیرد؛ فقط موارد جدید + شمار لایه‌ها."""
    existing = list(graph["nodes"])
    res = layered([node_id], layers, mode, node_types, rel_types, max_nodes, existing)
    new_nodes = [n for n in res["nodes"] if n["id"] not in graph["nodes"]]
    ids = [n["id"] for n in res["nodes"]] if mode == MODE_EXACT else existing + [n["id"] for n in new_nodes]
    edges = _filter_dag(q.edges_among(ids, rel_types, settings.HARD_MAX_EDGES), res["dag"])
    new_edges = [_edge(e) for e in edges if e["id"] not in graph["edges"]]
    return new_nodes, new_edges, res["layer_counts"]


def entire_graph(node_types: list[str], rel_types: list[str]) -> dict:
    g = new_graph()
    nodes = q.all_nodes(node_types, settings.ENTIRE_HARD_NODES)
    merge(g, [_node(r) for r in nodes], [])
    edges = q.all_edges(node_types, rel_types, settings.ENTIRE_HARD_EDGES)
    merge(g, [], [_edge(e) for e in edges])
    g["meta"] = {"truncated_nodes": len(nodes) >= settings.ENTIRE_HARD_NODES,
                 "truncated_edges": len(edges) >= settings.ENTIRE_HARD_EDGES}
    return g


def graph_from_ids(ids: list[str], with_neighbors: bool = False, max_nodes: int = 400) -> dict:
    """گراف القاییِ مجموعه‌ای از نودها (برای نمایش نتایج GDS)."""
    g = new_graph()
    ids = list(dict.fromkeys(ids))[:max_nodes]
    nodes = [_node(r) for r in q.nodes_by_ids(ids)]
    merge(g, nodes, [])
    if with_neighbors and ids:
        res = layered(ids, 1, MODE_CUMULATIVE, [], [], max_nodes * 2, list(g["nodes"]))
        merge(g, [n for n in res["nodes"] if n["id"] not in g["nodes"]], [])
        g["meta"]["truncated_nodes"] = res["truncated"]
    edges = q.edges_among(list(g["nodes"]), [], settings.HARD_MAX_EDGES)
    merge(g, [], [_edge(e) for e in edges])
    return g


def graph_from_paths(paths: list[dict]) -> dict:
    g = new_graph()
    for p in paths:
        merge(g, [_node(n) for n in p["nodes"]], [])
    for p in paths:
        merge(g, [], [_edge(r) for r in p["rels"]])
    return g


def graph_from_records(records: list) -> dict:
    """از رکوردهای خام driver (Node/Relationship/Path) گراف می‌سازد (برای Query Console)."""
    from neo4j.graph import Node, Path, Relationship

    g = new_graph()
    rels = []

    def visit(v):
        if isinstance(v, Node):
            merge(g, [{"id": v.element_id, "name": str(v.get("name", v.element_id)),
                       "type": next(iter(v.labels), "Entity"), "source_count": v.get("source_count", 0)}], [])
        elif isinstance(v, Relationship):
            rels.append(v)
            visit(v.start_node)
            visit(v.end_node)
        elif isinstance(v, Path):
            for n in v.nodes:
                visit(n)
            for r in v.relationships:
                visit(r)
        elif isinstance(v, (list, tuple)):
            for x in v:
                visit(x)
        elif isinstance(v, dict):
            for x in v.values():
                visit(x)

    for rec in records:
        for v in rec.values():
            visit(v)
    for r in rels:
        merge(g, [], [{"id": r.element_id, "source": r.start_node.element_id, "target": r.end_node.element_id,
                       "type": str(r.get("type", r.type)), "source_count": r.get("source_count", 0)}])
    return g
