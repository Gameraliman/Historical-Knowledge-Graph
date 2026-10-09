"""تست‌های بدون نیاز به Neo4j:  python -m pytest tests"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.security import check_read_only  # noqa: E402


def test_read_only_blocks_writes():
    for bad in ["CREATE (n)", "MATCH (n) DETACH DELETE n", "MATCH (n) SET n.x=1", "MERGE (n:A)",
                "MATCH (n) REMOVE n.x", "DROP INDEX x", "CALL apoc.cypher.doIt('x',{})",
                "CALL gds.pageRank.write('g',{})", "LOAD CSV FROM 'x' AS r RETURN r", "MATCH (n) RETURN n; MATCH (m) RETURN m"]:
        assert not check_read_only(bad)[0], bad


def test_read_only_allows_reads():
    for good in ["MATCH (n:Person) RETURN n LIMIT 25", "MATCH (n) WHERE n.name = 'SET CREATE' RETURN n",
                 "CALL db.labels()", "CALL gds.pageRank.stream('g') YIELD nodeId RETURN nodeId", "MATCH (n) RETURN n.set"]:
        assert check_read_only(good)[0], good


def test_parse_year():
    from visualization.timeline import parse_year
    assert parse_year("۱۳۵۷") == (1978, "شمسی")
    assert parse_year("۱۲۷۲ قمری")[1] == "قمری"
    assert parse_year("۱۹۱۴ میلادی") == (1914, "میلادی")
    assert parse_year("دوره قاجار")[0] is None


def test_wiki_text_helpers():
    from ingest.wiki_fetcher import clean_text, split_chunks
    assert clean_text("== سرتیتر ==\n\nمتن اول\n  متن دوم  ") == "متن اول\nمتن دوم"
    text = "\n".join(["جمله‌ی اول است. جمله‌ی دوم است." * 40] * 6)
    chunks = split_chunks(text, 1000)
    assert chunks and all(len(c) <= 1000 for c in chunks)
    assert split_chunks("کوتاه", 1000) == ["کوتاه"]


def test_llm_json_parsing():
    from ingest.llm_extractor import parse_json, valid_relation
    raw = '<think>فکر</think>```json\n{"pages": [{"pageid": "1", "relations": []}]}\n```'
    assert parse_json(raw)["pages"][0]["pageid"] == "1"
    assert valid_relation({"subject": ["الف", "Person"], "relation": "پدر", "object": ["ب", "Person"]})
    assert not valid_relation({"subject": ["الف"], "relation": "پدر", "object": ["ب", "Person"]})


def test_wiki_link_resolution():
    from ingest import entity_links as el
    links = el.parse_wikitext_links("[[عباس میرزا نایب‌السلطنه|عباس میرزا]] [[پرونده:x.jpg|thumb]] [[محمود|م]] [[محمود (۲)|م]]")
    d = el.build_dictionary(links, "فتحعلی‌شاه")
    rels = [{"subject": ["عباس میرزا", "Person"], "relation": "پسر", "object": ["م", "Person"]}]
    assert el.apply_to_relations(rels, d) == 1
    assert rels[0]["subject"][0] == "عباس میرزا نایب‌السلطنه" and rels[0]["object"][0] == "م"  # مبهم: دست نخورد


def test_mailbox_flow(tmp_path):
    from mailbox import mailbox_manager as mm
    mm.MAILBOX_FILE = tmp_path / "mailbox.json"
    r = mm.create_request("ali", "فتحعلی‌شاه", wiki={"status": "found", "title": "فتحعلی‌شاه", "pageid": 77})
    assert mm.find_open_by_pageid(77)["id"] == r["id"] and len(mm.pending_requests()) == 1
    mm.decide(r["id"], "admin", True)
    mm.update_request(r["id"], job={"stage": "queued"})
    mm.update_request(r["id"], job={"stage": "done", "stats": {"edges": 3}})
    got = mm.get_request(r["id"])
    assert got["status"] == mm.APPROVED and got["job"]["stage"] == "done" and not mm.pending_requests()


def test_entity_resolution_candidates_and_groups():
    from resolution import candidates as c, merge as m
    rows = [("1", "فتحعلی‌شاه", 9), ("2", "فتحعلی شاه", 3), ("3", "عباس میرزا", 7), ("4", "عباس میرزا نایب‌السلطنه", 5),
            ("5", "محمود میرزا (قاجار)", 2), ("6", "محمود میرزا", 4), ("7", "تهران", 1)]
    nodes = {i: c.make_node({"id": i, "name": n, "type": "Person", "sc": sc, "pids": [1], "titles": [], "deg": sc}) for i, n, sc in rows}
    snap = {"nodes": nodes, "adj": {}}
    got = {(nodes[p["a_id"]]["name"], nodes[p["b_id"]]["name"]): p["reason"] for p in c.generate_candidates(snap, ["Person"], 0.5, 50)}
    assert got[("فتحعلی‌شاه", "فتحعلی شاه")] == "exact_norm"
    assert any(r == "token_subset" for r in got.values()) and not any("تهران" in a + b for a, b in got)
    groups = m.plan_groups([{"a_id": "1", "b_id": "2", "keep_id": "1"}], snap, {frozenset({"1", "2"})})
    assert groups[0]["keep_id"] == "1" and groups[0]["drop_ids"] == ["2"] and groups[0]["blocked"]
    assert m.merge_map([{"ok": True, "label": "Person", "kept": "الف", "dropped": "ب"}]) == {"Person": {"ب": "الف"}}


def test_layered_modes_and_expansion(monkeypatch):
    from database import queries as q
    from graph import graph_builder as gb
    edges = [("S", "A"), ("S", "B"), ("S", "C"), ("A", "A1"), ("A", "A2"), ("B", "B1"), ("A1", "B1")]
    nodes = {n: {"id": n, "name": n, "type": "Person", "source_count": 1} for n in "S A B C A1 A2 B1".split()}
    adj = {}
    for a, b in edges:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    monkeypatch.setattr(q, "nodes_by_ids", lambda ids: [nodes[i] for i in ids])
    monkeypatch.setattr(q, "neighbors_layer", lambda f, ex, rt, nt, lim: [nodes[b] for b in sorted({b for a in f for b in adj[a]} - set(ex))][:lim])
    monkeypatch.setattr(q, "layer_links", lambda f, b: [{"a": a, "b": x} for a in f for x in adj[a] if x in b])
    monkeypatch.setattr(q, "edges_among", lambda ids, rt, lim: [{"id": f"{a}-{b}", "source": a, "target": b, "type": "r", "source_count": 1}
                                                                for a, b in edges if a in ids and b in ids])
    cum = gb.build_subgraph(["S"], 2, [], [], 100, mode="cumulative")
    exact = gb.build_subgraph(["S"], 2, [], [], 100, mode="exact")
    assert set(cum["nodes"]) == {"S", "A", "B", "C", "A1", "A2", "B1"}
    assert set(exact["nodes"]) == {"S", "A", "B", "A1", "A2", "B1"} and "A1-B1" not in exact["edges"]   # بدون C و یال هم‌لایه‌ای
    # گسترش ۲ لایه از نودی که همسایه‌هایش از قبل نمایش داده شده‌اند
    g = gb.build_subgraph(["S"], 1, [], [], 100)
    new_nodes, new_edges, _ = gb.expansion(g, "S", 2, [], [], 100)
    assert {n["id"] for n in new_nodes} == {"A1", "A2", "B1"}
