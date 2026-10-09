"""هسته‌ی اجرای الگوریتم‌های GDS در حالت stream (بدون نوشتن روی Neo4j) + زمان‌سنجی."""
from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from database.neo4j_connection import run_gds

# تبدیل شناسه‌ی داخلی GDS به نود واقعی و خواص نمایشی
NODE_COLS = ("elementId(n) AS id, n.name AS name, labels(n)[0] AS type, "
             "COUNT { (n)--() } AS degree")


def timed(algo: str, projection: str, query: str, params: dict) -> pd.DataFrame:
    start = time.perf_counter()
    rows = run_gds(query, params)
    elapsed = time.perf_counter() - start
    st.session_state["gds_last"] = {"algorithm": algo, "projection": projection, "seconds": round(elapsed, 3),
                                    "rows": len(rows)}
    return pd.DataFrame(rows)


def writeback_pagerank(projection: str, prop: str, iterations: int, damping: float) -> dict:
    """اختیاری و پیش‌فرض خاموش: ذخیره‌ی PageRank روی Neo4j. فقط با ALLOW_GDS_WRITEBACK=true و تأیید صریح."""
    from config import settings
    if not settings.ALLOW_GDS_WRITEBACK:
        raise PermissionError("ذخیره‌ی نتیجه‌ی GDS روی Neo4j غیرفعال است (ALLOW_GDS_WRITEBACK=false).")
    if not prop.replace("_", "").isalnum():
        raise ValueError("نام خاصیت نامعتبر است.")
    return run_gds("CALL gds.pageRank.write($g, {maxIterations: $it, dampingFactor: $d, writeProperty: $p}) "
                   "YIELD nodePropertiesWritten, ranIterations RETURN nodePropertiesWritten, ranIterations",
                   {"g": projection, "it": iterations, "d": damping, "p": prop})[0]
