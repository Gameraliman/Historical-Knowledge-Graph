"""دریافت متن صفحه‌ی ویکی‌پدیا (مطابق wiki_data_exteract.py) و آماده‌سازی متن (مطابق T8-3mm.py)."""
from __future__ import annotations

import datetime
import re
from urllib.parse import quote

import requests

from config import settings


def fetch_page(title: str) -> dict | None:
    """صفحه را با API ویکی‌پدیا می‌گیرد. اگر وجود نداشته باشد None."""
    params = {"action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1,
              "format": "json", "titles": title}
    resp = requests.get(settings.WIKI_API_URL, params=params, timeout=30,
                        headers={"User-Agent": settings.WIKI_USER_AGENT})
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})
    if not pages:
        return None
    page = next(iter(pages.values()))
    if "missing" in page or page.get("pageid") is None:
        return None
    page_title = page.get("title", title)
    return {
        "title": page_title,
        "pageid": page.get("pageid"),
        "source": settings.WIKI_WIKI_BASE + quote(page_title.replace(" ", "_")),
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "text": page.get("extract", ""),
    }


def clean_text(text: str) -> str:
    """سرتیترهای «== ... ==» و خط‌های خالی حذف می‌شوند (مثل T8-3mm.py)."""
    lines = []
    for line in (text or "").split("\n"):
        line = line.strip()
        if not line or line.startswith("=="):
            continue
        lines.append(line)
    return "\n".join(lines)


def split_chunks(text: str, max_chars: int) -> list[str]:
    """متن بلند را روی مرز خط/جمله به بخش‌های ≤ max_chars تقسیم می‌کند."""
    if len(text) <= max_chars:
        return [text] if text else []
    pieces: list[str] = []
    for line in text.split("\n"):
        if len(line) <= max_chars:
            pieces.append(line)
            continue
        sentences = re.split(r"(?<=[.!؟?؛])\s+", line)
        buf = ""
        for s in sentences:
            while len(s) > max_chars:                       # جمله‌ی بسیار بلند: برش سخت
                if buf:
                    pieces.append(buf)
                    buf = ""
                pieces.append(s[:max_chars])
                s = s[max_chars:]
            if len(buf) + len(s) + 1 > max_chars and buf:
                pieces.append(buf)
                buf = s
            else:
                buf = f"{buf} {s}".strip()
        if buf:
            pieces.append(buf)
    chunks, cur = [], ""
    for p in pieces:
        if cur and len(cur) + len(p) + 1 > max_chars:
            chunks.append(cur)
            cur = p
        else:
            cur = f"{cur}\n{p}" if cur else p
    if cur:
        chunks.append(cur)
    return chunks


# ----------------------- بررسی وجود صفحه (برای درخواست موضوع) -----------------------
def check_title(title: str) -> dict:
    """
    بررسی خودکار وجود صفحه در ویکی‌پدیا. status: found | missing | disambiguation | error
    (Redirect دنبال می‌شود و عنوان استاندارد برمی‌گردد.)
    """
    out = {"status": "error", "title": title.strip(), "pageid": None, "url": None, "note": "",
           "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    try:
        resp = requests.get(settings.WIKI_API_URL, headers={"User-Agent": settings.WIKI_USER_AGENT}, timeout=20, params={
            "action": "query", "titles": title.strip(), "redirects": 1, "prop": "pageprops|info|extracts", "inprop": "url",
            "ppprop": "disambiguation", "explaintext": 1, "format": "json", "formatversion": 2})
        resp.raise_for_status()
        pages = resp.json().get("query", {}).get("pages", [])
        if not pages:
            out.update(status="missing", note="صفحه‌ای پیدا نشد.")
            return out
        page = pages[0]
        out["title"] = page.get("title", out["title"])
        if page.get("missing") or page.get("invalid") or page.get("pageid") is None:
            out.update(status="missing", note="صفحه‌ای با این عنوان در ویکی‌پدیا وجود ندارد.")
            return out
        text = clean_text(page.get("extract") or "")       # همان متنی که به مدل داده می‌شود
        out.update(pageid=page["pageid"], url=settings.WIKI_WIKI_BASE + quote(out["title"].replace(" ", "_")),
                   chars=len(text), chunks=len(split_chunks(text, settings.WIKI_MAX_CHARS)))
        if "disambiguation" in (page.get("pageprops") or {}):
            out.update(status="disambiguation", note="این یک صفحه‌ی ابهام‌زدایی است؛ صفحه‌ی مشخصی را انتخاب کنید.")
        else:
            out.update(status="found")
        return out
    except (requests.RequestException, ValueError) as exc:
        out["note"] = f"بررسی ویکی‌پدیا ناموفق بود: {exc}"
        return out


def suggest_titles(query: str, limit: int = 6) -> list[str]:
    """پیشنهاد عنوان‌های مشابه (opensearch) وقتی صفحه پیدا نشد یا مبهم بود."""
    try:
        resp = requests.get(settings.WIKI_API_URL, headers={"User-Agent": settings.WIKI_USER_AGENT}, timeout=20, params={
            "action": "opensearch", "search": query.strip(), "limit": limit, "namespace": 0, "format": "json"})
        resp.raise_for_status()
        return [t for t in resp.json()[1] if t][:limit]
    except (requests.RequestException, ValueError, IndexError):
        return []
