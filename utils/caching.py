"""کش Streamlit برای Queryهای سنگین و پرتکرار."""
from __future__ import annotations

import streamlit as st

from config import settings
from database import queries as q


@st.cache_data(ttl=settings.CACHE_TTL, show_spinner=False)
def cached_totals():
    return q.totals()


@st.cache_data(ttl=settings.CACHE_TTL, show_spinner=False)
def cached_labels():
    return q.labels()


@st.cache_data(ttl=settings.CACHE_TTL, show_spinner=False)
def cached_counts_by_label():
    return q.counts_by_label()


@st.cache_data(ttl=settings.CACHE_TTL, show_spinner=False)
def cached_rel_types(limit: int = 500):
    return q.rel_type_counts(limit)


@st.cache_data(ttl=settings.CACHE_TTL, show_spinner=False)
def cached_top_degree(k: int = 20, node_type: str | None = None):
    return q.top_degree(k, node_type)


@st.cache_data(ttl=settings.CACHE_TTL, show_spinner=False)
def cached_source_pages():
    return q.source_pages()


@st.cache_data(ttl=settings.CACHE_TTL, show_spinner=False)
def cached_time_links(types: tuple[str, ...]):
    return q.time_links(list(types))


@st.cache_data(ttl=60, show_spinner=False)
def cached_connection():
    from database.neo4j_connection import check_connection
    return check_connection()
