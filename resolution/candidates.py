"""مرحله ۱: یافتن جفت‌های مشکوک به تکراری در کل گراف (بدون LLM، فقط داخل یک Label)."""
from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

from config import settings
from database.neo4j_connection import run_read

_DIAC = re.compile("[\u064b-\u065f\u0670\u0640]")
_PAREN = re.compile(r"\s*[\(（][^)）]*[\)）]\s*$")
_DIGITS = {ord(str(i)): "۰۱۲۳۴۵۶۷۸۹"[i] for i in range(10)}
_DIGITS.update({0x0660 + i: "۰۱۲۳۴۵۶۷۸۹"[i] for i in range(10)})
_LETTERS = str.maketrans({"ي": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه", "أ": "ا", "إ": "ا", "ٱ": "ا", "\u200c": " "})


def ernorm(name: str) -> str:
    """اعراب/کشیده حذف، ی/ک/ه عربی، نیم‌فاصله→فاصله، ارقام فارسی، حروف کوچک."""
    t = _DIAC.sub("", str(name or "")).translate(_LETTERS).translate(_DIGITS)
    return re.sub(r"\s+", " ", t).strip().lower()


def base_of(key: str) -> str:
    return _PAREN.sub("", key).strip() or key


def make_node(row: dict) -> dict:
    key = ernorm(row["name"])
    return {**row, "pids": set(row.get("pids") or []), "key": key, "base": base_of(key), "nospace": key.replace(" ", "")}


def load_snapshot(cap_nodes: int = 300000, cap_edges: int = 600000) -> dict:
    """نودها و یال‌ها را یک‌بار می‌خواند: {"nodes": {id: {...}}, "adj": {id: [(other, relation, outgoing)]}}"""
    rows = run_read(
        "MATCH (n) WHERE n.name IS NOT NULL RETURN elementId(n) AS id, n.name AS name, labels(n)[0] AS type, "
        "coalesce(n.source_count, 0) AS sc, coalesce(n.source_pageids, []) AS pids, "
        "coalesce(n.source_titles, []) AS titles, COUNT { (n)--() } AS deg LIMIT $cap", {"cap": cap_nodes}, timeout=120)
    nodes = {r["id"]: make_node(r) for r in rows}
    adj: dict[str, list] = defaultdict(list)
    for e in run_read("MATCH (a)-[r:RELATION]->(b) RETURN elementId(a) AS a, elementId(b) AS b, r.type AS t LIMIT $cap",
                      {"cap": cap_edges}, timeout=120):
        adj[e["a"]].append((e["b"], e["t"], True))
        adj[e["b"]].append((e["a"], e["t"], False))
    return {"nodes": nodes, "adj": dict(adj)}


def cache_key(a: dict, b: dict) -> str:
    x, y = sorted((a["nospace"], b["nospace"]))
    return f"{a['type']}|{x}|{y}"


def score_pair(a: dict, b: dict) -> tuple[float, str] | None:
    if a["nospace"] == b["nospace"]:
        return 1.0, "exact_norm"
    ba, bb = a["base"].replace(" ", ""), b["base"].replace(" ", "")
    best: tuple[float, str] | None = None
    if ba == bb and len(ba) >= 3:
        best = (0.85, "paren_stripped")
    ta, tb = set(a["base"].split()), set(b["base"].split())
    if ta and tb and ta != tb:
        small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
        if small < big:
            ratio = len(small) / len(big)
            if len(small) >= 2:
                s = 0.65 + 0.25 * ratio
            elif len(next(iter(small))) >= 4:
                s = 0.55 + 0.2 * ratio
            else:
                s = 0
            if s and (best is None or s > best[0]):
                best = (s, "token_subset")
    if min(len(ba), len(bb)) >= 5 and abs(len(ba) - len(bb)) <= max(2, int(0.25 * max(len(ba), len(bb)))):
        sm = SequenceMatcher(None, ba, bb)
        if sm.real_quick_ratio() >= 0.88 and sm.quick_ratio() >= 0.88:
            ratio = sm.ratio()
            if ratio >= 0.88 and (best is None or ratio - 0.1 > best[0]):
                best = (ratio - 0.1, "fuzzy")
    return best


def generate_candidates(snap: dict, types: list[str], min_score: float = 0.6, max_pairs: int = 500) -> list[dict]:
    nodes, adj = snap["nodes"], snap["adj"]
    by_label: dict[str, list[str]] = defaultdict(list)
    for nid, n in nodes.items():
        if n["type"] in types:
            by_label[n["type"]].append(nid)
    out, seen = [], set()
    for label, ids in by_label.items():
        df: dict[str, int] = defaultdict(int)
        for nid in ids:
            for tok in set(nodes[nid]["base"].split()):
                df[tok] += 1
        blocks: dict[str, list[str]] = defaultdict(list)
        for nid in ids:
            n = nodes[nid]
            for tok in set(n["base"].split()):
                if len(tok) >= 3 and df[tok] <= settings.ER_STOP_DF:
                    blocks[f"t:{tok}"].append(nid)
            if len(n["nospace"]) >= 5:
                blocks[f"p:{n['nospace'][:4]}"].append(nid)
        for members in blocks.values():
            if len(members) < 2 or len(members) > 300:
                continue
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    key = (members[i], members[j]) if members[i] < members[j] else (members[j], members[i])
                    if key in seen:
                        continue
                    seen.add(key)
                    a, b = nodes[key[0]], nodes[key[1]]
                    hit = score_pair(a, b)
                    if not hit:
                        continue
                    na = {o for o, _, _ in adj.get(a["id"], [])} - {b["id"]}
                    nb = {o for o, _, _ in adj.get(b["id"], [])} - {a["id"]}
                    jac = len(na & nb) / len(na | nb) if (na | nb) else 0.0
                    shared = a["pids"] & b["pids"]
                    score = min(1.0, hit[0] + 0.15 * jac + (0.05 if shared else 0))
                    if score < min_score:
                        continue
                    first, second = sorted((a, b), key=lambda x: (-x["sc"], -x["deg"], x["name"]))
                    out.append({"a_id": first["id"], "b_id": second["id"], "label": label, "score": round(score, 3),
                                "reason": hit[1], "jaccard": round(jac, 3), "shared_pages": len(shared)})
    out.sort(key=lambda p: (-p["score"], p["label"]))
    out = out[:max_pairs]
    for i, p in enumerate(out, 1):
        p["pid"] = f"p{i}"
    return out


def cross_label_same_names(snap: dict, limit: int = 300) -> list[dict]:
    """فقط گزارش: نام یکسان با Labelهای متفاوت (ادغام نمی‌شود؛ تغییر نوع تصمیم جداگانه‌ای است)."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for n in snap["nodes"].values():
        groups[n["nospace"]].append(n)
    return [{"name": ns[0]["name"], "types": " / ".join(sorted({n["type"] for n in ns})), "نودها": len(ns)}
            for ns in groups.values() if len({n["type"] for n in ns}) > 1][:limit]
