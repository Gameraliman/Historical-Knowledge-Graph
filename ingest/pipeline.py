"""فرایند بعد از تأیید ادمین: دریافت صفحه ← پیوندهای ویکی ← استخراج با LLM (+یکسان‌سازی) ← «بازبینی» ← (تأیید ادمین) ← ایمپورت به Neo4j.

خودکار فقط تا پایان استخراج است؛ انتقال به Neo4j بعد از بازبینی و تأیید صریح ادمین انجام می‌شود (مثل روش دستی).

هر Job در یک Thread پس‌زمینه (یکی‌یکی، صف‌شده) اجرا و وضعیتش در mailbox.json به‌روز می‌شود تا UI قفل نکند.
این ماژول از Streamlit استفاده نمی‌کند.
"""
from __future__ import annotations

import json
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests

from config import settings
from ingest import entity_links, llm_extractor, neo4j_ingest, wiki_fetcher
from mailbox import mailbox_manager as mm

STAGES = ["queued", "fetching", "links", "extracting", "review", "importing", "done"]
STAGE_FA = {"queued": "در صف", "fetching": "دریافت صفحه", "links": "پیوندهای ویکی", "extracting": "استخراج روابط (LLM)",
            "review": "منتظر بازبینی و تأیید انتقال به Neo4j", "importing": "ریختن در Neo4j", "done": "انجام شد",
            "failed": "ناموفق", "discarded": "کنار گذاشته شد"}
ACTIVE = {"queued", "fetching", "links", "extracting", "importing"}

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kg-pipeline")
_running: set[str] = set()
_lock = threading.Lock()


def _stamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _set(request_id: str, stage: str, message: str = "", **extra) -> None:
    job = {"stage": stage, "message": message, "updated_at": _stamp(), **extra}
    if stage in ("done", "failed"):
        job["finished_at"] = _stamp()
    mm.update_request(request_id, job=job)


def extraction_path(request_id: str):
    return settings.EXTRACTIONS_DIR / f"{request_id}.json"


def load_extraction(request_id: str) -> dict | None:
    try:
        return json.loads(extraction_path(request_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def import_reviewed(request_id: str, relations: list[dict]) -> dict:
    """بعد از تأیید ادمین: روابط بازبینی‌شده را به Neo4j منتقل می‌کند. اگر شکست بخورد، به بازبینی برمی‌گردد (نتیجه‌ی استخراج حفظ است)."""
    info = load_extraction(request_id)
    if not info:
        raise RuntimeError("نتیجه‌ی استخراج پیدا نشد؛ فرایند را دوباره اجرا کنید.")
    page = {"pageid": info["Pageid"], "title": info["Title"], "source": info["Source"]}
    with _lock:
        _running.add(request_id)
    try:
        _set(request_id, "importing", f"ریختن {len(relations)} رابطه در Neo4j…")
        res = neo4j_ingest.import_relations(page, relations)
        _set(request_id, "done", "پس از تأیید ادمین وارد گراف شد.",
             stats={**res, "relations": len(relations), "link_replaced": info.get("link_replaced", 0),
                    "pageid": page["pageid"], "warnings": info.get("warnings", [])})
        return res
    except Exception as exc:  # noqa: BLE001
        _set(request_id, "review", f"انتقال به Neo4j ناموفق بود: {exc}. دوباره تلاش کنید.")
        raise
    finally:
        with _lock:
            _running.discard(request_id)


def discard(request_id: str) -> None:
    _set(request_id, "discarded", "ادمین نتایج استخراج را کنار گذاشت؛ چیزی به Neo4j منتقل نشد.")


def run_job(request_id: str) -> None:
    """بدنه‌ی Job (در Thread). هر خطا به‌صورت وضعیت failed ثبت می‌شود."""
    item = mm.get_request(request_id)
    if not item:
        return
    title = (item.get("wiki") or {}).get("title") or item["topic"]
    try:
        _set(request_id, "fetching", f"دریافت «{title}» از ویکی‌پدیا…")
        page = wiki_fetcher.fetch_page(title)
        if not page:
            raise RuntimeError("صفحه در ویکی‌پدیا پیدا نشد.")
        text = wiki_fetcher.clean_text(page["text"])
        chunks = wiki_fetcher.split_chunks(text, settings.WIKI_MAX_CHARS)
        if not chunks:
            raise RuntimeError("متن صفحه خالی است.")

        link_dict, warnings = None, []
        _set(request_id, "links", "دریافت پیوندهای ویکی برای یکسان‌سازی موجودیت‌ها…")
        try:
            links = entity_links.fetch_links(page["title"])
            redirects = entity_links.resolve_redirects([t for _, t in links]) if links else None
            link_dict = entity_links.build_dictionary(links, page["title"], redirects)
        except (requests.RequestException, ValueError, KeyError) as exc:
            warnings.append(f"پیوندهای ویکی دریافت نشد؛ فقط یکسان‌سازی با متن انجام شد ({exc}).")

        def progress(i, n):
            _set(request_id, "extracting", f"استخراج با LLM — بخش {i} از {n}")

        _set(request_id, "extracting", f"استخراج با LLM — {len(chunks)} بخش")
        relations, warns, stats = llm_extractor.extract_chunks(page, chunks, progress, settings.AUTO_LLM_DELAY, link_dict)
        warnings += warns

        info = {"Pageid": page["pageid"], "Title": page["title"], "Source": page["source"], "relations": relations,
                "warnings": warnings, "chars": len(text), "chunks": len(chunks), "link_count": len(links) if link_dict else None,
                "link_replaced": stats["link_replaced"], "canonical": sorted(link_dict["canonical"]) if link_dict else []}
        settings.EXTRACTIONS_DIR.mkdir(parents=True, exist_ok=True)       # همه‌ی اطلاعات برای بازبینی ادمین ذخیره می‌شود
        extraction_path(request_id).write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
        if not relations:
            raise RuntimeError("هیچ رابطه‌ی معتبری استخراج نشد. " + " ".join(warnings))
        _set(request_id, "review", f"استخراج تمام شد ({len(relations)} رابطه)؛ منتظر بازبینی و تأیید ادمین برای انتقال به Neo4j.",
             stats={"relations": len(relations), "chars": len(text), "chunks": len(chunks), "link_replaced": stats["link_replaced"],
                    "warnings": warnings})
    except Exception as exc:  # noqa: BLE001
        _set(request_id, "failed", str(exc) or exc.__class__.__name__, error=traceback.format_exc(limit=3))
    finally:
        with _lock:
            _running.discard(request_id)


def start_job(request_id: str) -> bool:
    """Job را صف می‌کند. اگر همین درخواست الان در حال اجراست False."""
    with _lock:
        if request_id in _running:
            return False
        _running.add(request_id)
    mm.update_request(request_id, job={"stage": "queued", "message": "در صف اجرا…", "started_at": _stamp(),
                                       "updated_at": _stamp(), "finished_at": None, "stats": None, "error": None})
    _executor.submit(run_job, request_id)
    return True


def reconcile() -> None:
    """Jobهای فعالی که پردازششان قطع شده (ری‌استارت سرور) را ناموفق علامت می‌زند."""
    now = datetime.now(timezone.utc).astimezone()
    for x in mm.load_mailbox()["requests"]:
        job = x.get("job") or {}
        if job.get("stage") in ACTIVE and x["id"] not in _running:
            try:
                age = (now - datetime.fromisoformat(job["updated_at"])).total_seconds() / 60
            except (KeyError, ValueError):
                age = 1e9
            if age > settings.JOB_STALE_MINUTES or not _running:
                _set(x["id"], "failed", "فرایند قطع شد (احتمالاً ری‌استارت برنامه). «تلاش دوباره» را بزنید.")
