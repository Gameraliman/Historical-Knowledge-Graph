"""یکسان‌سازی موجودیت‌ها با پیوندهای ویکی (Wiki Links).

ایده: در ویکی‌نویسی `[[عنوان صفحه|متن نمایشی]]` نام‌های مختلفِ یک موجودیت را به عنوان استاندارد صفحه وصل می‌کند.
از آن یک «فرهنگ لغت نام ← نام استاندارد» می‌سازیم و (۱) به مدل در Prompt می‌دهیم، (۲) بعد از پاسخ مدل هم
به‌صورت قطعی روی subject/object اعمال می‌کنیم. هر چه در فهرست نبود، به مرحله‌ی «بررسی کل متن» در Prompt می‌رسد.
"""
from __future__ import annotations

import re
import time

import requests

from config import settings

_LINK_RE = re.compile(r"\[\[([^\[\]|]+)(?:\|([^\[\]]*))?\]\]")
_TAG_RE = re.compile(r"<[^>]+>")
_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")


def norm(text: str) -> str:
    t = str(text or "").replace("\u200c", " ").replace("\u064a", "\u06cc").replace("\u0643", "\u06a9")
    return re.sub(r"\s+", " ", t).strip().lower()


def _get(params: dict) -> dict:
    r = requests.get(settings.WIKI_API_URL, params={**params, "format": "json", "formatversion": 2},
                     headers={"User-Agent": settings.WIKI_USER_AGENT}, timeout=30)
    r.raise_for_status()
    return r.json()


def parse_wikitext_links(wikitext: str) -> list[tuple[str, str]]:
    """[(متن نمایشی، عنوان هدف)] از ویکی‌متن. پیوندهای فضای‌نام‌دار (پرونده:، رده:، الگو:، میان‌ویکی) حذف می‌شوند."""
    out = []
    for m in _LINK_RE.finditer(wikitext or ""):
        target = m.group(1).split("#")[0].replace("_", " ").strip()
        if not target or ":" in target:
            continue
        display = _TAG_RE.sub("", m.group(2) or "").strip() or target
        out.append((re.sub(r"\s+", " ", display), re.sub(r"\s+", " ", target)))
    return out


def fetch_links(title: str) -> list[tuple[str, str]]:
    data = _get({"action": "parse", "page": title, "prop": "wikitext", "redirects": 1})
    return parse_wikitext_links(data.get("parse", {}).get("wikitext", ""))


def resolve_redirects(titles: list[str], delay: float = 0.3) -> dict[str, str]:
    """{عنوان ← عنوان نهایی بعد از Redirect}. ۵۰ عنوان در هر درخواست."""
    mapping: dict[str, str] = {}
    titles = list(dict.fromkeys(titles))
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        q = _get({"action": "query", "titles": "|".join(batch), "redirects": 1}).get("query", {})
        step1 = {n["from"]: n["to"] for n in q.get("normalized", [])}
        step2 = {r["from"]: r["to"] for r in q.get("redirects", [])}
        for t in batch:
            n = step1.get(t, t)
            mapping[t] = step2.get(n, n)
        if delay and i + 50 < len(titles):
            time.sleep(delay)
    return mapping


def build_dictionary(links: list[tuple[str, str]], page_title: str, redirects: dict[str, str] | None = None,
                     strip_parens: bool = False) -> dict:
    """
    خروجی: {"aliases": {norm(alias): (alias, canonical)}, "ambiguous": set, "canonical": {norm(canonical)}}
    نام مبهم (یک متن نمایشی که به چند صفحه‌ی متفاوت وصل شده) حذف می‌شود تا اشتباهی یکی نشود.
    """
    def canon(t: str) -> str:
        t = (redirects or {}).get(t, t)
        return _PAREN_RE.sub("", t).strip() or t if strip_parens else t

    cand: dict[str, set] = {}
    shown: dict[str, str] = {}
    for display, target in links + [(page_title, page_title)]:
        c = canon(target)
        for alias in {display, target, c}:
            k = norm(alias)
            if len(k) >= 2:
                cand.setdefault(k, set()).add(c)
                shown.setdefault(k, alias)
    aliases, ambiguous = {}, set()
    for k, cs in cand.items():
        if len(cs) == 1:
            aliases[k] = (shown[k], next(iter(cs)))
        else:
            ambiguous.add(k)
    return {"aliases": aliases, "ambiguous": ambiguous,
            "canonical": {norm(c) for _, c in aliases.values()}, "main": canon(page_title)}


def block_for_chunk(chunk: str, d: dict | None, cap: int = 120) -> str:
    """بخش «پیوندهای ویکی» برای Prompt: فقط ورودی‌هایی که نامشان واقعاً در همین بخشِ متن آمده است."""
    if not d:
        return "پیوندهای ویکی: (در دسترس نیست؛ مرحله‌ی «الف» را رد کن و فقط مرحله‌ی «ب» را انجام بده.)"
    text = norm(chunk)
    maps, same = [], []
    for k, (alias, canonical) in sorted(d["aliases"].items(), key=lambda kv: -len(kv[0])):
        if k in text:
            (same if k == norm(canonical) else maps).append((alias, canonical))
    maps, same = maps[:cap], same[:cap]
    lines = [f"موضوع اصلی صفحه (نام استاندارد): «{d['main']}»"]
    if maps:
        lines.append("پیوندهای متنی ← نام استاندارد:")
        lines += [f"«{a}» ← «{c}»" for a, c in maps]
    if same:
        lines.append("نام‌های استانداردی که در این بخش آمده‌اند: " + "، ".join(f"«{c}»" for _, c in same))
    if not maps and not same:
        lines.append("(پیوند ویکی‌ای در این بخش نیست.)")
    return "پیوندهای ویکی همین صفحه:\n" + "\n".join(lines)


def apply_to_relations(relations: list[dict], d: dict | None) -> int:
    """قطعی (بدون LLM): نام‌هایی که دقیقاً مطابق یک متن نمایشی غیرمبهم‌اند به نام استاندارد تبدیل می‌شوند. تعداد تغییرها."""
    if not d:
        return 0
    changed = 0
    for r in relations:
        for side in ("subject", "object"):
            hit = d["aliases"].get(norm(r[side][0]))
            if hit and hit[1] != r[side][0]:
                r[side][0] = hit[1]
                changed += 1
    return changed
