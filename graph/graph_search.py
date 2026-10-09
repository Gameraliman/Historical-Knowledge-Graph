"""جستجوی نود و رابطه (با نرمال‌سازی فارسی)."""
from __future__ import annotations

from database import queries as q
from utils.formatting import normalize_text, split_terms


def search(term: str, types: list[str] | None = None, limit: int = 30) -> list[dict]:
    term = normalize_text(term)
    if not term:
        return []
    return q.search_nodes(term, types or [], limit)


def search_many(text: str, types: list[str] | None = None, per_term: int = 15) -> tuple[list[dict], list[dict], list[str]]:
    """جستجوی چندعبارتی (جداکننده: کاما، «،» یا خط جدید). خروجی: (Entityها، Relationها، شناسه‌ی بهترین Entity هر عبارت)."""
    entities: dict[str, dict] = {}
    relations: dict[str, dict] = {}
    defaults: list[str] = []
    for term in split_terms(text):
        t = normalize_text(term)
        found = q.search_nodes(t, types or [], per_term)
        for r in found:
            entities.setdefault(r["id"], r)
        # بهترین نتیجه‌ی هر عبارت (تطابق دقیق/شروع‌شونده؛ در نبود آن، اولین نتیجه) به‌عنوان مبدأ پیش‌فرض
        best = [r for r in found if r["rank"] == 0] or found[:1]
        defaults += [r["id"] for r in best]
        for r in q.search_relation_types(t, per_term):
            relations.setdefault(r["type"], r)
    return list(entities.values()), list(relations.values()), list(dict.fromkeys(defaults))
