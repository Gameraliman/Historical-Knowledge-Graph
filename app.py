"""Historical Knowledge Graph Explorer — نقطه‌ی ورود (ورود کاربر + ناوبری بر اساس نقش).

نکته: صفحه‌ها عمداً در پوشه‌ی `views/` هستند (نه `pages/`)؛ Streamlit پوشه‌ی `pages/` را خودکار
به‌عنوان منو نشان می‌دهد، حتی قبل از ورود کاربر.
"""
import streamlit as st

st.set_page_config(page_title="Historical Knowledge Graph", page_icon="🔷", layout="wide",
                   initial_sidebar_state="expanded")

from auth.authentication import authenticate  # noqa: E402
from config import settings  # noqa: E402
from graph import graph_state  # noqa: E402
from views import (about, admin, admin_ingest, admin_resolution, bloom, gds_analytics, home,  # noqa: E402
                   query_console, smart_search, sources, timeline)
from utils import caching  # noqa: E402
from utils.formatting import inject_css  # noqa: E402

inject_css()
if "user" not in st.session_state:
    st.session_state.user = (None if settings.AUTH_ENABLED
                             else {"username": "dev", "role": settings.ROLE_MAIN_ADMIN})


def login() -> None:
    # قبل از ورود هیچ منو/سایدبار/لینکی نمایش داده نمی‌شود
    st.markdown("<style>[data-testid='stSidebar'],[data-testid='stSidebarCollapsedControl'],"
                "[data-testid='collapsedControl'],[data-testid='stSidebarNav']{display:none!important}</style>",
                unsafe_allow_html=True)
    st.markdown("## 🔷 Historical Knowledge Graph")
    st.caption("برای ورود، نام کاربری و رمز عبور را وارد کنید.")
    with st.form("login"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        ok = st.form_submit_button("ورود", use_container_width=True, type="primary")
    if ok:
        user = authenticate(u, p)
        if user:
            st.session_state.user = user
            st.rerun()
        st.error("نام کاربری یا رمز عبور اشتباه است.")


if st.session_state.user is None:
    login()
    st.stop()

role = st.session_state.user["role"]
is_admin = role in settings.ADMIN_ROLES
graph_state.init()

# ---------------- صفحه‌ها ----------------
def P(fn, title, icon, key):
    return st.Page(fn, title=title, icon=icon, url_path=key)

explore = [P(home.render, "Dashboard", "🏠", "home"),
           P(bloom.render, "Bloom", "🌸", "bloom"),
           P(smart_search.render, "جستجوی Entity/Relation", "🔎", "smart_search"),
           P(timeline.render, "Timeline", "⏳", "timeline"),
           P(sources.render, "Sources", "📚", "sources")]
analytics = []
if is_admin:
    analytics = [P(gds_analytics.render, "Graph Analytics (GDS)", "🧠", "gds_analytics"),
                 P(query_console.render, "Query Console", "⌨️", "query_console")]
if is_admin:
    manage = [P(admin.render_users, "User Management", "👥", "users"),
              P(admin.render_categories, "Category Management", "🗂️", "categories"),
              P(admin_ingest.render, "Wiki Import", "📥", "wiki_import"),
              P(admin_resolution.render, "Entity Resolution", "🧩", "entity_resolution"),
              P(admin.render_mailbox, "Mailbox", "📬", "mailbox"),
              P(admin.render_history, "History", "📜", "history")]
else:
    manage = [P(admin.render_request, "Request Topic", "📝", "request"),
              P(admin.render_my_history, "My History", "📜", "my_history")]
other = [P(about.render, "About", "ℹ️", "about")]

sections = {"کاوش": explore}
if analytics:
    sections["تحلیل"] = analytics
sections["مدیریت"] = manage
sections["سامانه"] = other
pg = st.navigation(sections)
st.session_state["_nav"] = {p.url_path: p for group in sections.values() for p in group}

with st.sidebar:
    st.success(f"{st.session_state.user['username']}\nRole: {role}")
    ok, err = caching.cached_connection()
    if not ok:
        st.error("⚠ Neo4j connection failed.")
        st.caption(err[:200])
    if settings.AUTH_ENABLED and st.button("خروج", use_container_width=True):
        st.session_state.user = None
        st.rerun()

pg.run()
