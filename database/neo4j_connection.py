"""اتصال Neo4j: Driver یکتا (Singleton) و اجرای Queryهای Read-Only."""
from __future__ import annotations

from itertools import islice
from typing import Any

import threading
from neo4j import READ_ACCESS, GraphDatabase, Query
from neo4j.exceptions import AuthError, ServiceUnavailable

from config import settings


class Neo4jUnavailable(Exception):
    """اتصال به Neo4j برقرار نیست."""


_driver = None
_driver_lock = threading.Lock()


def get_driver():
    """Driver یکتا (Singleton). بدون وابستگی به Streamlit تا در Thread پس‌زمینه (Pipeline) هم امن باشد."""
    global _driver
    with _driver_lock:
        if _driver is None:
            _driver = GraphDatabase.driver(
                settings.NEO4J_URI, auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
                max_connection_lifetime=1800, connection_timeout=15)
        return _driver


def check_connection() -> tuple[bool, str]:
    try:
        get_driver().verify_connectivity()
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def run_read(query: str, params: dict | None = None, *, max_rows: int | None = None,
             timeout: float | None = None, raw: bool = False) -> list[Any]:
    """اجرای Query فقط‌خواندنی. Session در حالت READ_ACCESS است، پس نوشتن توسط خود Neo4j رد می‌شود."""
    q = Query(query, timeout=timeout or settings.QUERY_TIMEOUT)
    try:
        with get_driver().session(database=settings.NEO4J_DATABASE,
                                  default_access_mode=READ_ACCESS) as session:
            result = session.run(q, params or {})
            it = islice(result, max_rows) if max_rows else result
            rows = list(it) if raw else [r.data() for r in it]
            result.consume()
            return rows
    except (ServiceUnavailable, AuthError, OSError) as exc:
        raise Neo4jUnavailable(str(exc)) from exc


def run_gds(query: str, params: dict | None = None) -> list[dict]:
    """فقط برای Procedureهای ثابت GDS (project/stream/list/drop). ورودی کاربر هرگز به این تابع نمی‌رسد."""
    try:
        with get_driver().session(database=settings.NEO4J_DATABASE) as session:
            result = session.run(Query(query, timeout=300), params or {})
            rows = [r.data() for r in result]
            result.consume()
            return rows
    except (ServiceUnavailable, AuthError, OSError) as exc:
        raise Neo4jUnavailable(str(exc)) from exc


def run_write(query: str, params: dict | None = None) -> list[dict]:
    """فقط برای ایمپورت صریح ادمین (ingest/neo4j_ingest.py). Queryها ثابت‌اند و ورودی کاربر فقط پارامتر است."""
    try:
        with get_driver().session(database=settings.NEO4J_DATABASE) as session:
            result = session.run(Query(query, timeout=120), params or {})
            rows = [r.data() for r in result]
            result.consume()
            return rows
    except (ServiceUnavailable, AuthError, OSError) as exc:
        raise Neo4jUnavailable(str(exc)) from exc



def run_in_write_tx(work):
    """اجرای `work(tx)` در یک تراکنش نوشتن (همه‌یا‌هیچ). فقط برای ادغام صریح ادمین."""
    try:
        with get_driver().session(database=settings.NEO4J_DATABASE) as session:
            return session.execute_write(work)
    except (ServiceUnavailable, AuthError, OSError) as exc:
        raise Neo4jUnavailable(str(exc)) from exc
