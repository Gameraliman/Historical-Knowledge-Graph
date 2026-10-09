"""صندوق نامه‌ی درخواست موضوع (پایه‌ی شما) + نتیجه‌ی بررسی خودکار ویکی‌پدیا + وضعیت فرایند خودکار (Job).

ساختار هر درخواست: id, username, topic, status, created_at, reviewer, reviewed_at,
  wiki: {status: found|missing|disambiguation|error, title, pageid, url, checked_at, note}
  job : {stage, message, started_at, updated_at, finished_at, stats, error}
"""
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
MAILBOX_FILE = BASE_DIR / "data/mailbox.json"
PENDING, APPROVED, REJECTED, AUTO_REJECTED = "PENDING", "APPROVED", "REJECTED", "AUTO_REJECTED"
_LOCK = threading.RLock()   # Thread پس‌زمینه و UI هر دو روی فایل می‌نویسند


def _ensure():
    MAILBOX_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not MAILBOX_FILE.exists():
        MAILBOX_FILE.write_text(json.dumps({"requests": [], "history": []}, ensure_ascii=False, indent=2), encoding="utf-8")


def load_mailbox():
    _ensure()
    try:
        d = json.loads(MAILBOX_FILE.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            raise ValueError
        d.setdefault("requests", [])
        d.setdefault("history", [])
        return d
    except Exception:
        return {"requests": [], "history": []}


def save_mailbox(d):
    _ensure()
    tmp = MAILBOX_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(MAILBOX_FILE)


def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def create_request(username, topic, wiki=None, status=PENDING, note=None):
    topic = topic.strip()
    if not topic:
        raise ValueError("topic is empty")
    with _LOCK:
        d = load_mailbox()
        item = {"id": uuid.uuid4().hex, "username": username, "topic": topic, "status": status,
                "created_at": now(), "reviewer": None, "reviewed_at": None, "wiki": wiki or {}, "job": None}
        if note:
            item["note"] = note
        d["requests"].append(item)
        save_mailbox(d)
        return item


def get_request(request_id):
    return next((x for x in load_mailbox()["requests"] if x.get("id") == request_id), None)


def update_request(request_id, **fields):
    """فیلدهای سطح بالا را به‌روز می‌کند؛ برای job، دیکشنری ادغام می‌شود (Thread-safe)."""
    with _LOCK:
        d = load_mailbox()
        for x in d["requests"]:
            if x.get("id") == request_id:
                for k, v in fields.items():
                    if k == "job" and isinstance(v, dict) and isinstance(x.get("job"), dict):
                        x["job"].update(v)
                    else:
                        x[k] = v
                save_mailbox(d)
                return x
    raise ValueError("request not found")


def pending_requests():
    return [x for x in load_mailbox()["requests"] if x.get("status") == PENDING]


def user_requests(username):
    return [x for x in load_mailbox()["requests"] if x.get("username") == username]


def find_open_by_pageid(pageid):
    """درخواست در انتظار/تأییدشده‌ی دیگری با همین صفحه‌ی ویکی (برای جلوگیری از تکرار)."""
    for x in load_mailbox()["requests"]:
        if x.get("status") in (PENDING, APPROVED) and (x.get("wiki") or {}).get("pageid") == pageid:
            return x
    return None


def history():
    """همه‌ی درخواست‌های بررسی‌شده (تأیید/رد/ردِ خودکار) با آخرین وضعیت."""
    return [dict(x) for x in load_mailbox()["requests"] if x.get("status") != PENDING]


def decide(request_id, reviewer, approved):
    with _LOCK:
        d = load_mailbox()
        for x in d["requests"]:
            if x.get("id") == request_id and x.get("status") == PENDING:
                x["status"] = APPROVED if approved else REJECTED
                x["reviewer"] = reviewer
                x["reviewed_at"] = now()
                save_mailbox(d)
                return x
    raise ValueError("request not found or already reviewed")
