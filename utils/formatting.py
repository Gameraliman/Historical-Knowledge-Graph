"""فارسی‌سازی (RTL)، نرمال‌سازی متن، CSS و ابزارهای نمایش."""
from __future__ import annotations

import functools
import re
from typing import Callable

import pandas as pd
import streamlit as st
from neo4j.exceptions import ClientError, Neo4jError

from database.neo4j_connection import Neo4jUnavailable

_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_TO_FA = {ord(str(i)): _FA_DIGITS[i] for i in range(10)}
_TO_FA.update({0x0660 + i: _FA_DIGITS[i] for i in range(10)})
_TO_EN = {ord(_FA_DIGITS[i]): str(i) for i in range(10)}
_TO_EN.update({0x0660 + i: str(i) for i in range(10)})


def normalize_text(text: str) -> str:
    """یکسان‌سازی ی/ک عربی، نیم‌فاصله، ارقام و حروف کوچک (مطابق عبارت Cypher در queries.py)."""
    t = str(text or "")
    t = t.replace("\u200c", " ").replace("\u064a", "\u06cc").replace("\u0643", "\u06a9")
    t = t.replace("\u0629", "\u0647").translate(_TO_FA)
    return re.sub(r"\s+", " ", t).strip().lower()


def to_latin_digits(text: str) -> str:
    return str(text).translate(_TO_EN)


def split_terms(text: str) -> list[str]:
    text = text.replace("،", ",").replace(";", ",").replace("؛", ",").replace("\n", ",")
    return [x.strip() for x in text.split(",") if x.strip()]


def short(text: str, n: int = 28) -> str:
    text = str(text or "")
    return text if len(text) <= n else text[: n - 1] + "…"


def fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def inject_css() -> None:
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;600;700&display=swap');
html, body, [class*="css"], .stApp { font-family: 'Vazirmatn', Tahoma, sans-serif !important; }
.stApp { direction: rtl; }
[data-testid="stSidebar"] { direction: rtl; }
.stApp textarea.ltr, .stApp .ltr textarea, .stApp .ltr input, .stApp code, .stApp pre { direction: ltr; text-align: left; }
.block-container { padding-top: 1.2rem; max-width: 100%; }
.kg-header { background: linear-gradient(90deg,#0b2447,#19376d 60%,#018bff); color:#fff; padding:14px 22px;
  border-radius:10px; margin-bottom:14px; display:flex; align-items:center; gap:12px; }
.kg-header h2 { margin:0; font-size:1.25rem; color:#fff; } .kg-header span { opacity:.8; font-size:.85rem; }
.kg-card { background:#fff; border:1px solid #e3e8ef; border-radius:10px; padding:14px 16px; text-align:center;
  box-shadow:0 1px 2px rgba(16,24,40,.05); }
.kg-card .num { font-size:1.7rem; font-weight:700; line-height:1.2; } .kg-card .lbl { color:#667085; font-size:.85rem; }
.kg-chip { display:inline-block; padding:2px 10px; border-radius:12px; color:#fff; font-size:.78rem; margin-left:6px; }
.kg-box { background:#f8fafc; border:1px solid #e3e8ef; border-radius:8px; padding:10px 12px; margin-bottom:8px; }
div[data-testid="stMetric"] { background:#f8fafc; border:1px solid #e3e8ef; border-radius:8px; padding:8px 12px; }
</style>
""",
        unsafe_allow_html=True,
    )


def header(title: str, subtitle: str = "") -> None:
    st.markdown(
        f'<div class="kg-header"><div style="font-size:1.6rem">🔷</div><div><h2>{title}</h2>'
        f"<span>{subtitle}</span></div></div>",
        unsafe_allow_html=True,
    )


def stat_card(label: str, value, color: str = "#018bff") -> str:
    return (f'<div class="kg-card" style="border-top:4px solid {color}"><div class="num">{fmt_int(value)}</div>'
            f'<div class="lbl">{label}</div></div>')


def type_chip(node_type: str, color: str) -> str:
    return f'<span class="kg-chip" style="background:{color}">{node_type}</span>'


def to_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def db_guard(fn: Callable) -> Callable:
    """هر صفحه‌ی وابسته به Neo4j با این دکوراتور Crash نمی‌کند و پیام مناسب نشان می‌دهد."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Neo4jUnavailable as exc:
            st.error("⚠ اتصال به Neo4j برقرار نشد. (Neo4j connection failed.)")
            st.caption(f"{exc}")
            st.code("NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD / NEO4J_DATABASE", language="text")
        except ClientError as exc:
            st.error(f"⚠ Neo4j خطای Query داد: {exc.message if hasattr(exc, 'message') else exc}")
        except Neo4jError as exc:
            st.error(f"⚠ خطای Neo4j: {exc}")

    return wrapper


def goto(page_key: str) -> None:
    """رفتن به یک صفحه (صفحه‌ها در app.py ثبت می‌شوند)."""
    page = st.session_state.get("_nav", {}).get(page_key)
    if page is not None:
        st.switch_page(page)
