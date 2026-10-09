"""ریختن روابط استخراج‌شده در Neo4j با همان Schema اسکریپت import_to_neo4j.py.

تفاوت با اسکریپت دسته‌ای: اینجا ایمپورت «افزایشی» است؛ منبع (pageid/title/url) به لیست منابعِ نود/رابطه‌ی
موجود اضافه می‌شود و جایگزین آن نمی‌شود. اجرای دوباره‌ی همان صفحه داده‌ی تکراری نمی‌سازد (idempotent).
هیچ Merge/Entity Resolution خودکاری انجام نمی‌شود: فقط کلید (Label + name) دقیقاً مثل ایمپورتر.
"""
from __future__ import annotations

import re
from collections import defaultdict

from database.neo4j_connection import run_read, run_write

ALLOWED_LABELS = {"Person", "Location", "Organization", "Event", "Time", "Role", "Work", "Title",
                  "Object", "Group", "Quantity", "Document"}


def safe_label(label: str) -> str:
    label = (label or "").strip()
    if label in ALLOWED_LABELS:
        return label
    cleaned = re.sub(r"[^A-Za-z0-9_]", "", label)
    return cleaned if cleaned else "Entity"


def normalize(relations: list[dict]) -> tuple[list[dict], dict, dict]:
    """(روابط تمیز، نودهای یکتا {(label,name)}، یال‌های یکتا). متن خالی/نامعتبر حذف می‌شود."""
    clean, nodes, edges = [], {}, {}
    for r in relations:
        s_name, s_type = r["subject"][0].strip(), safe_label(r["subject"][1])
        o_name, o_type = r["object"][0].strip(), safe_label(r["object"][1])
        rel = r["relation"].strip()
        if not (s_name and o_name and rel):
            continue
        clean.append({"subject": [s_name, s_type], "relation": rel, "object": [o_name, o_type]})
        nodes[(s_type, s_name)] = True
        nodes[(o_type, o_name)] = True
        edges[(s_type, s_name, rel, o_type, o_name)] = True
    return clean, nodes, edges


def existing_nodes(keys: list[tuple[str, str]]) -> set[tuple[str, str]]:
    """کدام (label, name)ها از قبل در گراف هستند (برای نمایش «جدید/موجود»)."""
    if not keys:
        return set()
    rows = run_read(
        "UNWIND $rows AS row MATCH (n) WHERE n.name = row.name AND row.label IN labels(n) "
        "RETURN DISTINCT row.label AS label, row.name AS name",
        {"rows": [{"label": lb, "name": nm} for lb, nm in keys]})
    return {(r["label"], r["name"]) for r in rows}


def alias_map(keys: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """نام‌هایی که «نام دیگرِ» (aliases) یک نود هستند ← نام اصلی نود (نتیجه‌ی ادغام‌های Entity Resolution)."""
    if not keys:
        return {}
    rows = run_read(
        "UNWIND $rows AS row MATCH (n) WHERE row.label IN labels(n) AND row.name IN coalesce(n.aliases, []) "
        "RETURN row.label AS label, row.name AS name, n.name AS canonical",
        {"rows": [{"label": lb, "name": nm} for lb, nm in keys]})
    return {(r["label"], r["name"]): r["canonical"] for r in rows}


def page_node_count(pageid) -> int:
    """چند نود از قبل به این صفحه (pageid) ارجاع دارند."""
    return run_read("MATCH (n) WHERE $pid IN n.source_pageids RETURN count(n) AS c", {"pid": pageid})[0]["c"]


_APPEND_SOURCE = """
WITH {v}, row, coalesce({v}.source_pageids, []) AS ids, coalesce({v}.source_titles, []) AS ts,
     coalesce({v}.source_urls, []) AS us
WITH {v}, row, ids, ts, us, row.pid IN ids AS seen
SET {v}.source_pageids = CASE WHEN seen THEN ids ELSE ids + [row.pid] END,
    {v}.source_titles  = CASE WHEN seen THEN ts  ELSE ts  + [row.title] END,
    {v}.source_urls    = CASE WHEN seen THEN us  ELSE us  + [row.url] END
SET {v}.source_count = size({v}.source_pageids)
"""


def import_relations(page: dict, relations: list[dict]) -> dict:
    """روابط یک صفحه را در Neo4j می‌ریزد. خروجی: آمار."""
    _, nodes0, _ = normalize(relations)
    exist0 = existing_nodes(list(nodes0))
    amap = alias_map([k for k in nodes0 if k not in exist0])      # جلوگیری از ساخته‌شدن دوباره‌ی نودهای ادغام‌شده
    if amap:
        relations = [{**r, "subject": [amap.get((safe_label(r["subject"][1]), r["subject"][0].strip()), r["subject"][0]), r["subject"][1]],
                      "object": [amap.get((safe_label(r["object"][1]), r["object"][0].strip()), r["object"][0]), r["object"][1]]}
                     for r in relations]
    _, nodes, edges = normalize(relations)
    if not edges:
        return {"nodes": 0, "new_nodes": 0, "edges": 0}
    before = existing_nodes(list(nodes))
    src = {"pid": page["pageid"], "title": page["title"], "url": page["source"]}

    for lb in sorted({k[0] for k in nodes}):
        run_write(f"CREATE CONSTRAINT {lb.lower()}_name_unique IF NOT EXISTS "
                  f"FOR (n:`{lb}`) REQUIRE n.name IS UNIQUE")

    by_label = defaultdict(list)
    for lb, name in nodes:
        by_label[lb].append({"name": name, **src})
    for lb, rows in by_label.items():
        run_write(f"UNWIND $rows AS row MERGE (n:`{lb}` {{name: row.name}}) " + _APPEND_SOURCE.format(v="n"),
                  {"rows": rows})

    by_pair = defaultdict(list)
    for (s_lb, s_name, rel, o_lb, o_name) in edges:
        by_pair[(s_lb, o_lb)].append({"s": s_name, "o": o_name, "type": rel, **src})
    for (s_lb, o_lb), rows in by_pair.items():
        run_write(f"UNWIND $rows AS row MATCH (a:`{s_lb}` {{name: row.s}}) MATCH (b:`{o_lb}` {{name: row.o}}) "
                  "MERGE (a)-[r:RELATION {type: row.type}]->(b) " + _APPEND_SOURCE.format(v="r"),
                  {"rows": rows})
    return {"nodes": len(nodes), "new_nodes": len(set(nodes) - before), "edges": len(edges)}
