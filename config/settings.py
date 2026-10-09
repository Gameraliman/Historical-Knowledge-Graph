"""تنظیمات مرکزی: اتصال Neo4j، محدودیت‌ها، رنگ‌ها و نقش‌ها."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")


def _get(name: str, default: str = "") -> str:
    """اول Environment Variable، بعد Streamlit Secrets، بعد مقدار پیش‌فرض."""
    value = os.getenv(name)
    if value:
        return value
    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # secrets.toml وجود ندارد
        pass
    return default


def _bool(name: str, default: bool) -> bool:
    return _get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


# ---------------- Neo4j ----------------
NEO4J_URI = _get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = _get("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = _get("NEO4J_PASSWORD", "")
NEO4J_DATABASE = _get("NEO4J_DATABASE", "neo4j")

# ---------------- Auth / مدیریت (از پروژه‌ی پایه) ----------------
AUTH_ENABLED = _bool("AUTH_ENABLED", True)

# ---------------- محدودیت‌های Performance ----------------
MAX_DEPTH = 6
DEFAULT_MAX_NODES = 300
HARD_MAX_NODES = 5000          # سقف گره برای Subgraph
HARD_MAX_EDGES = 15000         # سقف یال برای Subgraph
ENTIRE_WARN_NODES = 3000       # بالاتر از این برای «کل گراف» هشدار داده می‌شود
ENTIRE_WARN_EDGES = 8000
ENTIRE_HARD_NODES = 60000      # سقف مطلق «کل گراف»
ENTIRE_HARD_EDGES = 200000
QUERY_TIMEOUT = 30             # ثانیه
CONSOLE_MAX_ROWS = 2000
CACHE_TTL = 600

# ---------------- GDS ----------------
GDS_DEFAULT_PROJECTION = "kg_projection"
# ذخیره‌ی نتیجه‌ی GDS روی Neo4j به‌صورت پیش‌فرض خاموش است (Read-Only).
ALLOW_GDS_WRITEBACK = _bool("ALLOW_GDS_WRITEBACK", False)

# ---------------- رنگ و برچسب نوع نودها (Configuration مرکزی) ----------------
NODE_COLORS = {
    "Person": "#4C8EDA",
    "Location": "#57C7A5",
    "Organization": "#F79767",
    "Event": "#F16667",
    "Time": "#C990C0",
    "Role": "#ECB5C9",
    "Work": "#D9C8AE",
    "Title": "#FFC454",
    "Object": "#8DCC93",
    "Group": "#A5ABB6",
    "Quantity": "#DA7194",
    "Document": "#569480",
}
FALLBACK_COLOR = "#B0B7C3"
NODE_TYPE_FA = {
    "Person": "شخص", "Location": "مکان", "Organization": "سازمان", "Event": "رویداد",
    "Time": "زمان", "Role": "نقش", "Work": "اثر", "Title": "عنوان", "Object": "شیء",
    "Group": "گروه", "Quantity": "مقدار", "Document": "سند",
}
COMMUNITY_PALETTE = [
    "#4C8EDA", "#F16667", "#57C7A5", "#F79767", "#C990C0", "#FFC454", "#8DCC93",
    "#DA7194", "#569480", "#A5ABB6", "#7B6FD6", "#E3A857", "#3FA7D6", "#EE6C4D",
    "#59CD90", "#FAC05E", "#9B5DE5", "#00BBF9", "#F15BB5", "#80B918",
]
HOME_CARD_TYPES = ["Person", "Location", "Organization", "Event", "Time"]

# ---------------- Wiki Import (ادمین) ----------------
ALLOW_WIKI_IMPORT = _bool("ALLOW_WIKI_IMPORT", True)
GROQ_API_KEY = _get("GROQ_API_KEY") or _get("GROQ_API_KEY_6")
GROQ_MODEL = _get("GROQ_MODEL", "qwen/qwen3.8-27b")   # همان مدل اسکریپت T8-3mm.py
WIKI_API_URL = _get("WIKI_API_URL", "https://fa.wikipedia.org/w/api.php")
WIKI_WIKI_BASE = "https://fa.wikipedia.org/wiki/"
WIKI_USER_AGENT = _get("WIKI_USER_AGENT", "KnowledgeGraphExplorer/1.0 (admin wiki import)")
WIKI_MAX_CHARS = 5000          # مثل MAX_CHARS در T8-3mm.py
LLM_MAX_RETRIES = 3
LLM_RETRY_DELAY = 20

# ---------------- فرایند خودکار بعد از تأیید ادمین ----------------
AUTO_PIPELINE_ON_APPROVE = _bool("AUTO_PIPELINE_ON_APPROVE", True)
AUTO_LLM_DELAY = 5             # ثانیه بین درخواست‌های مدل
JOB_STALE_MINUTES = 30         # Job فعالی که این‌قدر بدون به‌روزرسانی بماند «قطع‌شده» حساب می‌شود
EXTRACTIONS_DIR = BASE_DIR / "data" / "extractions"

# ---------------- Entity Resolution کل گراف (ادمین) ----------------
# تحلیل و داوری همیشه آزاد است؛ «اعمال ادغام روی Neo4j» (حذف نود) فقط با این پرچم فعال می‌شود.
ALLOW_GRAPH_MERGE = _bool("ALLOW_GRAPH_MERGE", False)
ER_STOP_DF = 40            # توکن‌هایی که در بیش از این تعداد نام آمده‌اند (مثل «میرزا») برای کاندیدیابی بلاک نمی‌شوند
ER_CACHE_FILE = BASE_DIR / "data" / "er_cache.json"
ER_MERGE_LOG = BASE_DIR / "data" / "er_merge_log.jsonl"

# ---------------- نقش‌ها ----------------
ROLE_MAIN_ADMIN = "main admin"
ROLE_ADMIN = "admin"
ROLE_USER = "user"
ADMIN_ROLES = {ROLE_MAIN_ADMIN, ROLE_ADMIN}


def color_of(node_type: str) -> str:
    return NODE_COLORS.get(node_type, FALLBACK_COLOR)


def label_fa(node_type: str) -> str:
    fa = NODE_TYPE_FA.get(node_type)
    return f"{fa} ({node_type})" if fa else node_type
