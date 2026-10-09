"""استخراج Entity/Relation با Groq؛ Prompt و منطق parse عیناً از T8-3mm.py."""
from __future__ import annotations

import json
import re
import time
from typing import Callable

from config import settings
from ingest import entity_links

# Prompt اصلی شما (بدون تغییر). {text} با replace جایگزین می‌شود چون JSON نمونه آکولاد دارد.
PROMPT = """
در ادامه متن کامل چند صفحه آمده است. هر صفحه با یک PAGE_ID مشخص شده است.
هر صفحه را جداگانه و مستقل بخوان و تحلیل کن (روابط صفحات را با هم قاطی نکن).

{text}

{links}

از هر صفحه، تمام روابط موجود را استخراج کن.

هر رابطه باید به صورت زیر باشد:

Subject, Relation, Object

همچنین نوع Subject و Object را مشخص کن.

Types:
- Person
- Location
- Organization
- Event
- Time

فقط روابطی را استخراج کن که مستقیماً توسط متن همان صفحه پشتیبانی می‌شوند.
هیچ رابطه‌ای را حدس نزن و اطلاعاتی خارج از متن اضافه نکن.
روابط را به زبان فارسی بنویس.

در مرحله دوم (یکسان‌سازی موجودیت‌ها — Entity Resolution):
الف) ابتدا با پیوندهای ویکی: subject و object هر رابطه را با فهرست «پیوندهای ویکی همین صفحه» مقایسه کن.
اگر نام (یا بدل/عبارتی که به آن ارجاع می‌دهد) در آن فهرست بود، دقیقاً همان نام استاندارد را بنویس و برای آن نام جدید نساز.
ب) فقط اگر در فهرست پیوندها پیدا نشد:
subject و object های استخراج‌شده هر صفحه را در کل متن همان صفحه بررسی کن.
اگر یک subject یا object به صورت بدل، معادل، ضمیر یا ارجاع به موجودیتی آمده باشد که قبلاً در متن با نام اصلی معرفی شده است، نام اصلی را جایگزین کن.

فقط و فقط خروجی را با فرمت JSON زیر برگردان (برای هر صفحه یک آیتم، با همان PAGE_ID ورودی):

{
  "pages": [
    {
      "pageid": "PAGE_ID",
      "relations": [
        {
          "subject": ["SubjectName", "SubjectType"],
          "relation": "Relation",
          "object": ["ObjectName", "ObjectType"]
        }
      ]
    }
  ]
}
"""


class LLMNotConfigured(Exception):
    pass


def parse_json(result: str) -> dict:
    result = re.sub(r"<think>.*?</think>", "", result or "", flags=re.S).strip()
    if result.startswith("```json"):
        result = result[7:]
    elif result.startswith("```"):
        result = result[3:]
    if result.endswith("```"):
        result = result[:-3]
    result = result.strip()
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        start, end = result.find("{"), result.rfind("}")
        if start != -1 and end > start:
            return json.loads(result[start:end + 1])
        raise


def build_block(page: dict, text: str) -> str:
    return f"=== PAGE_ID: {page['pageid']} | TITLE: {page['title']} ===\n{text}\n=== END PAGE ==="


def _client():
    if not settings.GROQ_API_KEY:
        raise LLMNotConfigured("GROQ_API_KEY تنظیم نشده است (env یا Secrets).")
    try:
        import groq
    except ImportError as exc:
        raise LLMNotConfigured("پکیج groq نصب نیست: pip install groq") from exc
    return groq, groq.Groq(api_key=settings.GROQ_API_KEY)


def call_model(prompt_text: str) -> str:
    """فراخوانی مدل با تلاش مجدد هنگام قطع اتصال/محدودیت نرخ (مثل call_model در T8-3mm.py)."""
    groq, client = _client()
    retryable = (groq.APIConnectionError, groq.APITimeoutError, groq.RateLimitError)
    last = None
    for attempt in range(1, settings.LLM_MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=settings.GROQ_MODEL, temperature=0, max_tokens=8000,
                messages=[{"role": "user", "content": prompt_text}])
            return resp.choices[0].message.content or ""
        except retryable as exc:
            last = exc
            if attempt < settings.LLM_MAX_RETRIES:
                time.sleep(settings.LLM_RETRY_DELAY)
    raise last


def valid_relation(r) -> bool:
    try:
        s, o, rel = r["subject"], r["object"], r["relation"]
        return (isinstance(s, list) and len(s) >= 2 and isinstance(o, list) and len(o) >= 2
                and all(isinstance(x, str) and x.strip() for x in (s[0], s[1], o[0], o[1], rel)))
    except (KeyError, TypeError):
        return False


def extract_chunks(page: dict, chunks: list[str], on_progress: Callable[[int, int], None] | None = None,
                   delay: float = 0, link_dict: dict | None = None) -> tuple[list[dict], list[str], dict]:
    """(روابط یکتا، هشدارها، آمار). هر بخش یک درخواست است؛ بین درخواست‌ها delay ثانیه صبر می‌شود.
    link_dict (اختیاری): فرهنگ لغت پیوندهای ویکی برای یکسان‌سازی موجودیت‌ها (مرحله‌ی «الف»)."""
    relations: list[dict] = []
    warnings: list[str] = []
    stats = {"link_replaced": 0}
    seen = set()
    for i, chunk in enumerate(chunks, 1):
        if on_progress:
            on_progress(i, len(chunks))
        prompt = (PROMPT.replace("{text}", build_block(page, chunk))
                  .replace("{links}", entity_links.block_for_chunk(chunk, link_dict)))
        raw = call_model(prompt)
        try:
            data = parse_json(raw)
        except json.JSONDecodeError:
            warnings.append(f"بخش {i}: خروجی مدل JSON معتبر نبود و نادیده گرفته شد.")
            continue
        items = {str(p.get("pageid")): p for p in data.get("pages", []) if isinstance(p, dict)}
        item = items.get(str(page["pageid"])) or (next(iter(items.values())) if len(items) == 1 else None)
        if not item or "relations" not in item:
            warnings.append(f"بخش {i}: در پاسخ مدل رابطه‌ای برای این صفحه نبود.")
            continue
        for r in item["relations"]:
            if not valid_relation(r):
                continue
            norm = {"subject": [r["subject"][0].strip(), r["subject"][1].strip()], "relation": r["relation"].strip(),
                    "object": [r["object"][0].strip(), r["object"][1].strip()]}
            stats["link_replaced"] += entity_links.apply_to_relations([norm], link_dict)
            key = (tuple(norm["subject"]), norm["relation"], tuple(norm["object"]))
            if key not in seen:
                seen.add(key)
                relations.append(norm)
        if delay and i < len(chunks):
            time.sleep(delay)
    return relations, warnings, stats
