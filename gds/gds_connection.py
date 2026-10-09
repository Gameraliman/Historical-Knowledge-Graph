"""بررسی در دسترس بودن Neo4j GDS."""
from __future__ import annotations

import streamlit as st

from database.neo4j_connection import Neo4jUnavailable, run_gds

GDS_MISSING = ("⚠ Neo4j GDS is not available.\n\nGraph Explorer will continue to work, "
               "but Graph Analytics is temporarily unavailable.")


@st.cache_data(ttl=60, show_spinner=False)
def gds_status() -> tuple[bool, str]:
    """(در دسترس بودن، نسخه یا پیام خطا)."""
    try:
        rows = run_gds("RETURN gds.version() AS v")
        return True, rows[0]["v"]
    except Neo4jUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001  (Procedure/function وجود ندارد)
        return False, str(exc)
