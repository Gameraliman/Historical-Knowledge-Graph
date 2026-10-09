"""مرحله ۴: برنامه‌ریزی گروه‌های ادغام و اعمال آن‌ها روی Neo4j (هر ادغام یک تراکنش همه‌یا‌هیچ).

ادغام (keep ← drop): رابطه‌های drop به keep منتقل می‌شوند (رابطه‌ی هم‌نوعِ تکراری یکی می‌شود و منابعش ادغام می‌شود)،
رابطه‌ی بین خود این دو و حلقه‌ها حذف می‌شود، منابع و نام drop به keep (و خاصیت `aliases`) اضافه می‌شود و drop حذف می‌شود.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict

from config import settings
from database.neo4j_connection import run_in_write_tx, run_read

_SRC = """
WITH {r}, {t}, coalesce({t}.source_pageids, []) AS ids0, coalesce({t}.source_titles, []) AS t0, coalesce({t}.source_urls, []) AS u0
WITH {r}, {t}, ids0, t0, u0,
     [i IN range(0, size(coalesce({r}.source_pageids, [])) - 1) WHERE NOT {r}.source_pageids[i] IN ids0 | i] AS idx
SET {t}.source_pageids = ids0 + [i IN idx | {r}.source_pageids[i]],
    {t}.source_titles  = t0  + [i IN idx | coalesce({r}.source_titles[i], '')],
    {t}.source_urls    = u0  + [i IN idx | coalesce({r}.source_urls[i], '')]
SET {t}.source_count = size({t}.source_pageids)
"""

Q_CHECK = ("MATCH (k) WHERE elementId(k) = $keep MATCH (d) WHERE elementId(d) = $drop "
           "RETURN labels(k)[0] AS kl, labels(d)[0] AS dl, k.name AS kname, d.name AS dname")

Q_OUT = ("MATCH (d)-[r:RELATION]->(o) WHERE elementId(d) = $drop AND elementId(o) <> $keep AND elementId(o) <> $drop "
         "AND r.type IS NOT NULL MATCH (k) WHERE elementId(k) = $keep "
         "MERGE (k)-[nr:RELATION {type: r.type}]->(o) " + _SRC.format(r="r", t="nr") + " DELETE r RETURN count(*) AS moved")

Q_IN = ("MATCH (o)-[r:RELATION]->(d) WHERE elementId(d) = $drop AND elementId(o) <> $keep AND elementId(o) <> $drop "
        "AND r.type IS NOT NULL MATCH (k) WHERE elementId(k) = $keep "
        "MERGE (o)-[nr:RELATION {type: r.type}]->(k) " + _SRC.format(r="r", t="nr") + " DELETE r RETURN count(*) AS moved")

Q_NODE = ("MATCH (k) WHERE elementId(k) = $keep MATCH (d) WHERE elementId(d) = $drop "
          "WITH k, d, coalesce(k.source_pageids, []) AS ids0, coalesce(k.source_titles, []) AS t0, "
          "coalesce(k.source_urls, []) AS u0, coalesce(k.aliases, []) AS a0 "
          "WITH k, d, ids0, t0, u0, a0, "
          "[i IN range(0, size(coalesce(d.source_pageids, [])) - 1) WHERE NOT d.source_pageids[i] IN ids0 | i] AS idx "
          "SET k.source_pageids = ids0 + [i IN idx | d.source_pageids[i]], "
          "k.source_titles = t0 + [i IN idx | coalesce(d.source_titles[i], '')], "
          "k.source_urls = u0 + [i IN idx | coalesce(d.source_urls[i], '')], "
          "k.aliases = reduce(acc = a0, x IN coalesce(d.aliases, []) + [d.name] | "
          "CASE WHEN x IN acc OR x = k.name THEN acc ELSE acc + x END) "
          "SET k.source_count = size(k.source_pageids) "
          "WITH k, d DETACH DELETE d RETURN k.name AS name")


class MergeAborted(Exception):
    pass


def plan_groups(pairs: list[dict], snap: dict, denied: set[frozenset]) -> list[dict]:
    """
    pairs: [{a_id, b_id, keep_id}] جفت‌های تأییدشده. جفت‌های زنجیره‌ای (A=B و B=C) در یک گروه جمع می‌شوند.
    اگر داخل یک گروه جفتی باشد که قبلاً «different» داوری شده، گروه blocked می‌شود (باید دستی حل شود).
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    tally = Counter()
    for p in pairs:
        parent[find(p["a_id"])] = find(p["b_id"])
        tally[p["keep_id"]] += 1
    comps: dict[str, set] = defaultdict(set)
    for p in pairs:
        comps[find(p["a_id"])].update((p["a_id"], p["b_id"]))
    nodes, groups = snap["nodes"], []
    for members in comps.values():
        keep = max(members, key=lambda i: (tally[i], nodes[i]["sc"], nodes[i]["deg"]))
        conflicts = [tuple(sorted(nodes[i]["name"] for i in pr)) for pr in denied if pr <= members]
        groups.append({"keep_id": keep, "drop_ids": sorted(m for m in members if m != keep), "label": nodes[keep]["type"],
                       "blocked": bool(conflicts), "conflicts": conflicts})
    return groups


def impact(drop_ids: list[str]) -> dict[str, dict]:
    if not drop_ids:
        return {}
    rows = run_read("UNWIND $ids AS id MATCH (d) WHERE elementId(d) = id "
                    "RETURN id, COUNT { (d)-->() } AS out_deg, COUNT { (d)<--() } AS in_deg", {"ids": drop_ids})
    return {r["id"]: r for r in rows}


def merge_pair(keep_id: str, drop_id: str, expect_label: str, keep_name: str, drop_name: str) -> dict:
    """یک ادغام در یک تراکنش. اگر نودها تغییر کرده باشند (نام/Label) بدون هیچ تغییری متوقف می‌شود."""
    def work(tx):
        chk = tx.run(Q_CHECK, keep=keep_id, drop=drop_id).single()
        if not chk or chk["kl"] != expect_label or chk["dl"] != expect_label or chk["kname"] != keep_name or chk["dname"] != drop_name:
            raise MergeAborted("نودها دیگر با داده‌ی تحلیل‌شده یکی نیستند (گراف تغییر کرده)؛ تحلیل را دوباره اجرا کنید.")
        out = tx.run(Q_OUT, keep=keep_id, drop=drop_id).single()["moved"]
        inc = tx.run(Q_IN, keep=keep_id, drop=drop_id).single()["moved"]
        tx.run(Q_NODE, keep=keep_id, drop=drop_id).single()
        return {"moved_out": out, "moved_in": inc}
    return run_in_write_tx(work)


def apply_groups(groups: list[dict], snap: dict, who: str) -> list[dict]:
    """گروه‌های غیرمسدود را اعمال می‌کند و هر ادغام را در data/er_merge_log.jsonl ثبت می‌کند."""
    from datetime import datetime, timezone
    nodes, log = snap["nodes"], []
    settings.ER_MERGE_LOG.parent.mkdir(parents=True, exist_ok=True)
    for g in groups:
        if g["blocked"]:
            continue
        k = nodes[g["keep_id"]]
        for d_id in g["drop_ids"]:
            d = nodes[d_id]
            entry = {"ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"), "by": who,
                     "label": g["label"], "kept": k["name"], "dropped": d["name"], "ok": True}
            try:
                entry.update(merge_pair(g["keep_id"], d_id, g["label"], k["name"], d["name"]))
            except MergeAborted as exc:
                entry.update(ok=False, error=str(exc))
            log.append(entry)
            with settings.ER_MERGE_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return log


def merge_map(log: list[dict]) -> dict[str, dict[str, str]]:
    """{label: {نام حذف‌شده: نام باقی‌مانده}} برای استفاده در ایمپورت دسته‌ای (--merge-map)."""
    m: dict[str, dict[str, str]] = defaultdict(dict)
    for e in log:
        if e.get("ok"):
            m[e["label"]][e["dropped"]] = e["kept"]
    return dict(m)
