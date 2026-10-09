"""همه‌ی Queryهای Cypher (Parameterized، Read-Only).

Schema (مطابق scripts/import_to_neo4j.py):
  (:Person|Location|Organization|Event|Time|... {name, source_pageids, source_titles, source_urls, source_count})
  (a)-[:RELATION {type, source_pageids, source_titles, source_urls, source_count}]->(b)
"""
from __future__ import annotations

from typing import Any

from config import settings
from database.neo4j_connection import run_read

# نرمال‌سازی سمت Cypher: نیم‌فاصله→فاصله، ی/ک/ه عربی→فارسی، حروف کوچک
_NORM = ("toLower(replace(replace(replace(replace({v}, '\u200c', ' '), '\u064a', '\u06cc'), "
         "'\u0643', '\u06a9'), '\u0629', '\u0647'))")


def norm(expr: str) -> str:
    return _NORM.format(v=expr)


_NODE_RET = ("elementId({v}) AS id, {v}.name AS name, labels({v})[0] AS type, "
             "coalesce({v}.source_count, 0) AS source_count")


# ============================ آمار ============================
def totals() -> dict[str, int]:
    n = run_read("MATCH (n) RETURN count(n) AS c")[0]["c"]
    r = run_read("MATCH ()-[r]->() RETURN count(r) AS c")[0]["c"]
    rt = run_read("MATCH ()-[r:RELATION]->() RETURN count(DISTINCT r.type) AS c")[0]["c"]
    sp = run_read("MATCH (n) UNWIND coalesce(n.source_pageids, []) AS p RETURN count(DISTINCT p) AS c")[0]["c"]
    return {"nodes": n, "relationships": r, "relation_types": rt, "source_pages": sp}


def labels() -> list[str]:
    return [r["label"] for r in run_read("CALL db.labels() YIELD label RETURN label ORDER BY label")]


def counts_by_label() -> list[dict]:
    return run_read("MATCH (n) RETURN labels(n)[0] AS type, count(*) AS count ORDER BY count DESC")


def rel_type_counts(limit: int = 500) -> list[dict]:
    return run_read("MATCH ()-[r:RELATION]->() RETURN r.type AS type, count(*) AS count "
                    "ORDER BY count DESC LIMIT $limit", {"limit": limit})


def top_degree(k: int = 20, node_type: str | None = None) -> list[dict]:
    return run_read(
        "MATCH (n) WHERE $t IS NULL OR labels(n)[0] = $t "
        "WITH n, COUNT { (n)--() } AS degree ORDER BY degree DESC LIMIT $k "
        f"RETURN {_NODE_RET.format(v='n')}, degree",
        {"k": k, "t": node_type})


# ============================ جستجو ============================
def search_nodes(term: str, types: list[str] | None = None, limit: int = 30) -> list[dict]:
    return run_read(
        "MATCH (n) WHERE n.name IS NOT NULL "
        "AND (size($types) = 0 OR labels(n)[0] IN $types) "
        f"WITH n, {norm('n.name')} AS nn WHERE nn CONTAINS $term "
        f"RETURN {_NODE_RET.format(v='n')}, COUNT {{ (n)--() }} AS degree, "
        "CASE WHEN nn = $term THEN 0 WHEN nn STARTS WITH $term THEN 1 ELSE 2 END AS rank "
        "ORDER BY rank, degree DESC, size(nn) LIMIT $limit",
        {"term": term, "types": types or [], "limit": limit})


def search_relation_types(term: str, limit: int = 30) -> list[dict]:
    return run_read(
        f"MATCH ()-[r:RELATION]->() WHERE {norm('r.type')} CONTAINS $term "
        "RETURN r.type AS type, count(*) AS count ORDER BY count DESC LIMIT $limit",
        {"term": term, "limit": limit})


def nodes_by_ids(ids: list[str]) -> list[dict]:
    return run_read(f"MATCH (n) WHERE elementId(n) IN $ids RETURN {_NODE_RET.format(v='n')}", {"ids": ids})


# ============================ همسایگی / گراف ============================
def neighbors_layer(frontier: list[str], exclude: list[str], rel_types: list[str],
                    node_types: list[str], limit: int) -> list[dict]:
    return run_read(
        "MATCH (a)-[r:RELATION]-(b) WHERE elementId(a) IN $ids AND NOT elementId(b) IN $exclude "
        "AND (size($rel_types) = 0 OR r.type IN $rel_types) "
        "AND (size($node_types) = 0 OR labels(b)[0] IN $node_types) "
        f"WITH DISTINCT b RETURN {_NODE_RET.format(v='b')} ORDER BY source_count DESC LIMIT $limit",
        {"ids": frontier, "exclude": exclude, "rel_types": rel_types,
         "node_types": node_types, "limit": limit})


def layer_links(frontier: list[str], layer_ids: list[str]) -> list[dict]:
    """جفت‌های (والد در لایه‌ی قبل، فرزند در لایه‌ی جدید) برای ساختن مسیرهای لایه‌به‌لایه."""
    if not frontier or not layer_ids:
        return []
    return run_read("MATCH (a)-[:RELATION]-(b) WHERE elementId(a) IN $f AND elementId(b) IN $b "
                    "RETURN DISTINCT elementId(a) AS a, elementId(b) AS b", {"f": frontier, "b": layer_ids})


def edges_among(ids: list[str], rel_types: list[str], limit: int) -> list[dict]:
    return run_read(
        "MATCH (a)-[r:RELATION]->(b) WHERE elementId(a) IN $ids AND elementId(b) IN $ids "
        "AND (size($rel_types) = 0 OR r.type IN $rel_types) "
        "RETURN elementId(r) AS id, elementId(a) AS source, elementId(b) AS target, r.type AS type, "
        "coalesce(r.source_count, 0) AS source_count LIMIT $limit",
        {"ids": ids, "rel_types": rel_types, "limit": limit})


def count_filtered(node_types: list[str], rel_types: list[str]) -> dict[str, int]:
    n = run_read("MATCH (n) WHERE size($t) = 0 OR labels(n)[0] IN $t RETURN count(n) AS c",
                 {"t": node_types})[0]["c"]
    r = run_read(
        "MATCH (a)-[r:RELATION]->(b) WHERE (size($t) = 0 OR (labels(a)[0] IN $t AND labels(b)[0] IN $t)) "
        "AND (size($rt) = 0 OR r.type IN $rt) RETURN count(r) AS c",
        {"t": node_types, "rt": rel_types})[0]["c"]
    return {"nodes": n, "relationships": r}


def all_nodes(node_types: list[str], limit: int) -> list[dict]:
    return run_read(
        f"MATCH (n) WHERE size($t) = 0 OR labels(n)[0] IN $t RETURN {_NODE_RET.format(v='n')} LIMIT $limit",
        {"t": node_types, "limit": limit})


def all_edges(node_types: list[str], rel_types: list[str], limit: int) -> list[dict]:
    return run_read(
        "MATCH (a)-[r:RELATION]->(b) WHERE (size($t) = 0 OR (labels(a)[0] IN $t AND labels(b)[0] IN $t)) "
        "AND (size($rt) = 0 OR r.type IN $rt) "
        "RETURN elementId(r) AS id, elementId(a) AS source, elementId(b) AS target, r.type AS type, "
        "coalesce(r.source_count, 0) AS source_count LIMIT $limit",
        {"t": node_types, "rt": rel_types, "limit": limit})


# ============================ Inspector ============================
def node_detail(node_id: str) -> dict | None:
    rows = run_read(
        "MATCH (n) WHERE elementId(n) = $id RETURN elementId(n) AS id, labels(n) AS labels, "
        "properties(n) AS props, COUNT { (n)--() } AS degree, COUNT { (n)-->() } AS out_degree, "
        "COUNT { (n)<--() } AS in_degree", {"id": node_id})
    return rows[0] if rows else None


def node_relations(node_id: str, limit: int = 200) -> list[dict]:
    return run_read(
        "MATCH (n)-[r:RELATION]-(m) WHERE elementId(n) = $id "
        "RETURN elementId(r) AS rel_id, r.type AS relation, startNode(r) = n AS outgoing, "
        "elementId(m) AS other_id, m.name AS other, labels(m)[0] AS other_type, "
        "coalesce(r.source_count, 0) AS source_count ORDER BY source_count DESC, relation LIMIT $limit",
        {"id": node_id, "limit": limit})


def edge_detail(rel_id: str) -> dict | None:
    rows = run_read(
        "MATCH (a)-[r:RELATION]->(b) WHERE elementId(r) = $id "
        "RETURN elementId(r) AS id, r.type AS type, properties(r) AS props, "
        "elementId(a) AS source_id, a.name AS source, labels(a)[0] AS source_type, "
        "elementId(b) AS target_id, b.name AS target, labels(b)[0] AS target_type", {"id": rel_id})
    return rows[0] if rows else None


# ============================ مسیر ============================
_PATH_RET = ("RETURN [x IN nodes(p) | {id: elementId(x), name: x.name, type: labels(x)[0], "
             "source_count: coalesce(x.source_count, 0)}] AS nodes, "
             "[r IN relationships(p) | {id: elementId(r), type: r.type, source: elementId(startNode(r)), "
             "target: elementId(endNode(r)), source_count: coalesce(r.source_count, 0)}] AS rels, "
             "length(p) AS length")


def find_paths(a: str, b: str, max_len: int, k: int, shortest_only: bool) -> list[dict]:
    max_len = max(1, min(int(max_len), 6))
    if shortest_only:
        q = (f"MATCH (a) WHERE elementId(a) = $a MATCH (b) WHERE elementId(b) = $b "
             f"MATCH p = allShortestPaths((a)-[:RELATION*..{max_len}]-(b)) {_PATH_RET} LIMIT $k")
    else:
        max_len = min(max_len, 4)
        q = (f"MATCH (a) WHERE elementId(a) = $a MATCH (b) WHERE elementId(b) = $b "
             f"MATCH p = (a)-[:RELATION*1..{max_len}]-(b) {_PATH_RET} ORDER BY length LIMIT $k")
    return run_read(q, {"a": a, "b": b, "k": k}, timeout=60)


# ============================ Timeline ============================
def time_links(node_types: list[str], limit: int = 50000) -> list[dict]:
    return run_read(
        "MATCH (e)-[r:RELATION]-(t:Time) WHERE labels(e)[0] IN $types AND labels(e)[0] <> 'Time' "
        "RETURN elementId(e) AS id, e.name AS name, labels(e)[0] AS type, "
        "coalesce(e.source_count, 0) AS source_count, t.name AS time_text, r.type AS relation LIMIT $limit",
        {"types": node_types, "limit": limit})


# ============================ منابع ============================
def source_pages() -> list[dict]:
    return run_read(
        "MATCH (n) WHERE n.source_pageids IS NOT NULL "
        "UNWIND range(0, size(n.source_pageids) - 1) AS i "
        "RETURN n.source_pageids[i] AS pageid, n.source_titles[i] AS title, n.source_urls[i] AS url, "
        "count(*) AS nodes ORDER BY nodes DESC")


def relations_of_page(pageid: Any, limit: int = 1000) -> list[dict]:
    return run_read(
        "MATCH (a)-[r:RELATION]->(b) WHERE $pid IN r.source_pageids "
        "RETURN a.name AS source, labels(a)[0] AS source_type, r.type AS relation, "
        "b.name AS target, labels(b)[0] AS target_type LIMIT $limit", {"pid": pageid, "limit": limit})


# ============================ Data Explorer ============================
_SORTS_N = {"name": "name", "type": "type", "source_count": "source_count DESC, name", "degree": "degree DESC"}


def explorer_nodes(search: str, types: list[str], sort: str, skip: int, limit: int) -> tuple[list[dict], int]:
    where = ("WHERE (size($types) = 0 OR labels(n)[0] IN $types) "
             f"AND ($q = '' OR {norm('n.name')} CONTAINS $q)")
    p = {"types": types, "q": search, "skip": skip, "limit": limit}
    total = run_read(f"MATCH (n) {where} RETURN count(n) AS c", p)[0]["c"]
    order = _SORTS_N.get(sort, "name")
    rows = run_read(
        f"MATCH (n) {where} WITH n, COUNT {{ (n)--() }} AS degree "
        f"RETURN {_NODE_RET.format(v='n')}, degree, n.source_titles AS titles, n.source_urls AS urls "
        f"ORDER BY {order} SKIP $skip LIMIT $limit", p)
    return rows, total


def explorer_relationships(search: str, rel_search: str, src_types: list[str], dst_types: list[str],
                           sort: str, skip: int, limit: int) -> tuple[list[dict], int]:
    where = ("WHERE (size($st) = 0 OR labels(a)[0] IN $st) AND (size($dt) = 0 OR labels(b)[0] IN $dt) "
             f"AND ($rq = '' OR {norm('r.type')} CONTAINS $rq) "
             f"AND ($q = '' OR {norm('a.name')} CONTAINS $q OR {norm('b.name')} CONTAINS $q)")
    p = {"st": src_types, "dt": dst_types, "rq": rel_search, "q": search, "skip": skip, "limit": limit}
    total = run_read(f"MATCH (a)-[r:RELATION]->(b) {where} RETURN count(r) AS c", p)[0]["c"]
    order = {"relation": "relation", "source": "source", "source_count": "source_count DESC, relation"}.get(sort, "relation")
    rows = run_read(
        f"MATCH (a)-[r:RELATION]->(b) {where} "
        "RETURN elementId(r) AS id, a.name AS source, labels(a)[0] AS source_type, r.type AS relation, "
        "b.name AS target, labels(b)[0] AS target_type, coalesce(r.source_count, 0) AS source_count, "
        f"r.source_titles AS titles, r.source_urls AS urls ORDER BY {order} SKIP $skip LIMIT $limit", p)
    return rows, total


def export_nodes(search: str, types: list[str], cap: int = 100000) -> list[dict]:
    return run_read(
        "MATCH (n) WHERE (size($types) = 0 OR labels(n)[0] IN $types) "
        f"AND ($q = '' OR {norm('n.name')} CONTAINS $q) "
        "RETURN elementId(n) AS id, labels(n)[0] AS type, n.name AS name, coalesce(n.source_count,0) AS source_count, "
        "n.source_titles AS source_titles, n.source_urls AS source_urls ORDER BY name LIMIT $cap",
        {"types": types, "q": search, "cap": cap}, timeout=120)


def export_relationships(search: str, rel_search: str, src_types: list[str], dst_types: list[str],
                         cap: int = 100000) -> list[dict]:
    return run_read(
        "MATCH (a)-[r:RELATION]->(b) WHERE (size($st) = 0 OR labels(a)[0] IN $st) "
        "AND (size($dt) = 0 OR labels(b)[0] IN $dt) "
        f"AND ($rq = '' OR {norm('r.type')} CONTAINS $rq) "
        f"AND ($q = '' OR {norm('a.name')} CONTAINS $q OR {norm('b.name')} CONTAINS $q) "
        "RETURN a.name AS source, labels(a)[0] AS source_type, r.type AS relation, b.name AS target, "
        "labels(b)[0] AS target_type, coalesce(r.source_count,0) AS source_count, "
        "r.source_titles AS source_titles, r.source_urls AS source_urls LIMIT $cap",
        {"st": src_types, "dt": dst_types, "rq": rel_search, "q": search, "cap": cap}, timeout=120)


def seeds_by_relation(rel_types: list[str], limit: int = 50) -> list[str]:
    rows = run_read(
        "MATCH (a)-[r:RELATION]->(b) WHERE r.type IN $types "
        "WITH a, b LIMIT $limit RETURN collect(DISTINCT elementId(a)) + collect(DISTINCT elementId(b)) AS ids",
        {"types": rel_types, "limit": limit})
    return list(dict.fromkeys(rows[0]["ids"]))[:limit] if rows else []
