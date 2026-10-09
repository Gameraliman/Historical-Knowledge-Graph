"""صفحات مدیریتی پروژه‌ی پایه: کاربران، موضوع‌ها (Category)، صندوق نامه (Mailbox) و History."""
from __future__ import annotations

import streamlit as st

from auth.authentication import create_user, change_role, delete_user, load_users
from category.category_manager import add_category, load_categories
from config.settings import ROLE_ADMIN, ROLE_MAIN_ADMIN, ROLE_USER
from config import settings
from ingest import neo4j_ingest, pipeline, wiki_fetcher
from mailbox import mailbox_manager as mm
from views import ingest_review
from utils.formatting import header


def _me() -> dict:
    return st.session_state.user or {"username": "dev", "role": ROLE_MAIN_ADMIN}


def render_users() -> None:
    header("User Management", "مدیریت کاربران و نقش‌ها")
    role = _me()["role"]
    with st.form("newuser"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        r = st.selectbox("Role", [ROLE_ADMIN, ROLE_USER] if role == ROLE_MAIN_ADMIN else [ROLE_USER])
        ok = st.form_submit_button("Create", use_container_width=True)
    if ok:
        try:
            create_user(u, p, r)
            st.success("کاربر ساخته شد.")
        except Exception as e:  # noqa: BLE001
            st.error(str(e))
    data = load_users()
    if data:
        st.dataframe([{"username": x["username"], "role": x["role"], "active": x.get("active", True)} for x in data],
                     use_container_width=True, hide_index=True)
    if role == ROLE_MAIN_ADMIN and data:
        with st.form("changerole"):
            target = st.selectbox("User", [x["username"] for x in data])
            nr = st.selectbox("New role", [ROLE_ADMIN, ROLE_USER])
            ok = st.form_submit_button("Change Role")
        if ok:
            try:
                change_role(target, nr)
                st.success("Role تغییر کرد.")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(str(e))
    allowed = data if role == ROLE_MAIN_ADMIN else [x for x in data if x.get("role") == ROLE_USER]
    if allowed:
        with st.form("deluser"):
            target = st.selectbox("User to delete", [x["username"] for x in allowed])
            confirm = st.checkbox("تأیید حذف")
            ok = st.form_submit_button("Delete", use_container_width=True)
        if ok:
            if not confirm:
                st.warning("ابتدا حذف را تأیید کنید.")
            else:
                try:
                    delete_user(target)
                    st.success("کاربر حذف شد.")
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(str(e))


def render_categories() -> None:
    header("Category Management", "ثبت موضوع‌های جدید (اجرای Operation3)")
    with st.form("cat"):
        topic = st.text_input("Topic / Category")
        ok = st.form_submit_button("ثبت موضوع", use_container_width=True)
    if ok:
        try:
            _, res = add_category(topic, True)
            st.success("موضوع با موفقیت ثبت شد.")
            if res is None:
                st.info("Operation3 پیدا نشد؛ دسته‌بندی ذخیره شد.")
            elif res.returncode == 0:
                st.info("Operation3 با موفقیت اجرا شد.")
            else:
                st.warning("موضوع ثبت شد، اما Operation3 خطا داد: " + (res.stderr or res.stdout))
        except ValueError as e:
            st.error("این موضوع قبلاً ثبت شده است." if str(e) == "topic already registered" else str(e))
        except Exception as e:  # noqa: BLE001
            st.error(str(e))
    cats = load_categories()
    st.write(f"تعداد موضوع‌ها: **{len(cats)}**")
    if cats:
        st.dataframe({"Topics": cats}, use_container_width=True, hide_index=True)


_STATUS_FA = {mm.PENDING: "در انتظار تأیید", mm.APPROVED: "تأیید شد", mm.REJECTED: "رد شد",
              mm.AUTO_REJECTED: "رد خودکار"}
_WIKI_FA = {"found": "✅ صفحه وجود دارد", "missing": "❌ صفحه وجود ندارد", "disambiguation": "⚠ صفحه‌ی ابهام‌زدایی",
            "error": "⚠ بررسی ناموفق (مجدداً در زمان اجرا بررسی می‌شود)"}


def _size_line(w: dict) -> str:
    if w.get("chars") is None:
        return ""
    n = w.get("chunks", 0)
    return f"📏 {w['chars']:,} کاراکتر · ≈ {n} بخش {settings.WIKI_MAX_CHARS:,}‌کاراکتری (≈ {n} درخواست به LLM)"


def _wiki_line(x: dict) -> str:
    w = x.get("wiki") or {}
    if not w:
        return "—"
    line = _WIKI_FA.get(w.get("status"), w.get("status", "—"))
    line = f"{line} — [{w['title']}]({w['url']})" if w.get("url") else line
    size = _size_line(w)
    return f"{line}  \n{size}" if size else line


def _job_progress(job: dict) -> tuple[float, str]:
    stage = job.get("stage", "queued")
    if stage == "failed":
        return 1.0, f"❌ {job.get('message', '')}"
    idx = pipeline.STAGES.index(stage) if stage in pipeline.STAGES else 0
    return idx / (len(pipeline.STAGES) - 1), f"{pipeline.STAGE_FA.get(stage, stage)} — {job.get('message', '')}"


def _render_job(x: dict, admin: bool, key: str) -> None:
    job = x.get("job")
    if not job:
        return
    frac, text = _job_progress(job)
    st.progress(frac, text=text)
    stats = job.get("stats") or {}
    stage = job.get("stage")
    if stage in ("review", "done") and stats:
        st.caption(f"{stats.get('relations', 0)} رابطه استخراج شد · {stats.get('chars', 0):,} کاراکتر · {stats.get('chunks', 0)} بخش · "
                   f"{stats.get('link_replaced', 0)} نام با پیوند ویکی یکسان شد"
                   + (f" · {stats.get('nodes', 0)} نود ({stats.get('new_nodes', 0)} جدید) در Neo4j" if stage == "done" else ""))
        for w in stats.get("warnings", []):
            st.caption(f"⚠ {w}")
    if stage == "review" and not admin:
        st.info("استخراج تمام شد؛ ادمین پس از بازبینی، انتقال به گراف را تأیید می‌کند.")
    if admin and stage == "failed":
        if st.button("🔁 تلاش دوباره", key=f"retry_{key}"):
            pipeline.start_job(x["id"])
            st.rerun()


def _jobs_panel(admin: bool) -> None:
    """فهرست فرایندها؛ تا وقتی Job فعال هست هر ۵ ثانیه خودکار تازه می‌شود. وقتی استخراجی به «بازبینی» رسید یک‌بار کل صفحه تازه می‌شود."""
    pipeline.reconcile()
    rows = [x for x in mm.history() if x.get("job")]
    active = any((x["job"] or {}).get("stage") in pipeline.ACTIVE for x in rows)

    def body():
        items = [x for x in mm.history() if x.get("job")]
        seen = st.session_state.setdefault("_seen_review", set())
        ready = {x["id"] for x in items if x["job"].get("stage") == "review"}
        if ready - seen:                       # بخش بازبینی (بالاتر در صفحه) باید ظاهر شود
            seen |= ready
            st.rerun()
        st.markdown(f"### فرایندها ({len(items)})")
        if not items:
            st.caption("هنوز فرایندی اجرا نشده است.")
        for x in sorted(items, key=lambda r: r["job"].get("started_at") or "", reverse=True):
            with st.container(border=True):
                st.markdown(f"**{(x.get('wiki') or {}).get('title') or x['topic']}** · {x['username']}")
                _render_job(x, admin, "j" + x["id"])
                if (x["job"] or {}).get("stage") == "done" and x["id"] not in st.session_state.setdefault("_cache_cleared", set()):
                    st.cache_data.clear()                      # آمار داشبورد با داده‌ی جدید تازه شود
                    st.session_state["_cache_cleared"].add(x["id"])

    st.fragment(run_every=5 if active else None)(body)()


def _review_section(me: dict) -> None:
    """استخراج‌های آماده‌ی بازبینی: ادمین همه‌ی اطلاعات را می‌بیند و با تأیید او به Neo4j منتقل می‌شود."""
    items = [x for x in mm.history() if (x.get("job") or {}).get("stage") == "review"]
    st.markdown(f"### منتظر تأیید انتقال به Neo4j: {len(items)}")
    if not items:
        st.caption("استخراج بازبینی‌نشده‌ای نیست.")
        return
    st.caption("استخراج تمام شد. روابط را بازبینی کنید (ردیف‌های غلط را با برداشتن ✔ کنار بگذارید) و با تأیید شما به Neo4j منتقل می‌شوند.")
    for x in items:
        info = pipeline.load_extraction(x["id"])
        title = (x.get("wiki") or {}).get("title") or x["topic"]
        with st.expander(f"{title} — {len((info or {}).get('relations', []))} رابطه", expanded=len(items) == 1):
            if not info:
                st.error("فایل نتیجه‌ی استخراج پیدا نشد؛ فرایند را دوباره اجرا کنید.")
                if st.button("🔁 اجرای دوباره", key=f"rr_{x['id']}"):
                    pipeline.start_job(x["id"])
                    st.rerun()
                continue
            st.markdown(f"[{info['Title']}]({info['Source']}) · Page ID: `{info['Pageid']}` · درخواست‌کننده: {x['username']}  \n"
                        f"📏 {info.get('chars', 0):,} کاراکتر · {info.get('chunks', 0)} بخش · "
                        f"🔗 {info.get('link_count') if info.get('link_count') is not None else '—'} پیوند ویکی · "
                        f"{info.get('link_replaced', 0)} نام با پیوند ویکی یکسان شد")
            message = (x["job"] or {}).get("message", "")
            if "ناموفق" in message:
                st.error(message)
            try:
                seen = neo4j_ingest.page_node_count(info["Pageid"])
                if seen:
                    st.warning(f"این صفحه قبلاً در گراف هست ({seen} نود به آن ارجاع دارند)؛ انتقال مجدد داده‌ی تکراری نمی‌سازد.")
            except Exception:  # noqa: BLE001
                pass
            for w in info.get("warnings", []):
                st.caption(f"⚠ {w}")
            chosen = ingest_review.review_editor(info["relations"], info.get("canonical"), f"rv_edit_{x['id']}")
            ok = st.checkbox("تأیید می‌کنم روابط انتخاب‌شده به Neo4j منتقل شود", key=f"rv_ok_{x['id']}")
            c1, c2 = st.columns(2)
            if c1.button("✅ انتقال به Neo4j", key=f"rv_go_{x['id']}", type="primary", use_container_width=True,
                         disabled=not (ok and chosen is not None and len(chosen))):
                try:
                    with st.spinner("در حال انتقال به Neo4j…"):
                        res = pipeline.import_reviewed(x["id"], ingest_review.to_relations(chosen))
                    st.cache_data.clear()
                    st.success(f"منتقل شد: {res['edges']} رابطه، {res['nodes']} نود ({res['new_nodes']} جدید).")
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"انتقال ناموفق بود: {exc}")
            if c2.button("🗑 رد کردن نتایج (انتقال نده)", key=f"rv_no_{x['id']}", use_container_width=True):
                pipeline.discard(x["id"])
                st.rerun()


def render_mailbox() -> None:
    header("Mailbox", "درخواست‌های موضوع کاربران — تأیید ادمین ⟵ اجرای خودکار فازهای بعدی")
    me = _me()
    if me["role"] == ROLE_USER:
        render_request()
        return
    pending = mm.pending_requests()
    st.markdown(f"### در انتظار تأیید: {len(pending)}")
    st.caption("درخواست‌ها هنگام ثبت در ویکی‌پدیا بررسی شده‌اند (طول متن را در کارت ببینید). با تأیید شما، خودکار تا پایان استخراج "
               "پیش می‌رود: ثبت موضوع ← دریافت صفحه ← پیوندهای ویکی ← استخراج روابط با LLM. سپس نتیجه برای بازبینی شما می‌آید و "
               "فقط با تأیید دوم شما به Neo4j منتقل می‌شود.")
    if not pending:
        st.info("درخواستی در انتظار نیست.")
    for x in pending:
        with st.container(border=True):
            st.write(f"**کاربر:** {x['username']} · **موضوع:** {x['topic']}")
            st.markdown(f"**ویکی‌پدیا:** {_wiki_line(x)}")
            st.caption(x["created_at"])
            a, b, c = st.columns([1, 1, 1])
            if a.button("✅ تایید و شروع استخراج", key="a" + x["id"], use_container_width=True, type="primary"):
                try:
                    mm.decide(x["id"], me["username"], True)
                    topic = (x.get("wiki") or {}).get("title") or x["topic"]
                    try:
                        add_category(topic, True)
                    except ValueError:
                        pass                                    # موضوع قبلاً ثبت شده بود
                    if settings.AUTO_PIPELINE_ON_APPROVE:
                        pipeline.start_job(x["id"])
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(str(e))
            if b.button("❌ عدم پذیرش", key="r" + x["id"], use_container_width=True):
                mm.decide(x["id"], me["username"], False)
                st.rerun()
            if (x.get("wiki") or {}).get("status") != "found" and c.button("🔄 بررسی مجدد ویکی", key="w" + x["id"], use_container_width=True):
                mm.update_request(x["id"], wiki=wiki_fetcher.check_title(x["topic"]))
                st.rerun()
    _review_section(me)
    _jobs_panel(admin=True)
    render_history(embedded=True)


def _pick_suggestion(title: str) -> None:
    st.session_state["req_topic"] = title
    st.session_state["req_suggest"] = []
    st.session_state["req_result"] = ("info", f"عنوان «{title}» انتخاب شد؛ «بررسی و ارسال درخواست» را بزنید.")


def _say(kind: str, text: str, suggest: list[str] | None = None) -> None:
    st.session_state["req_result"] = (kind, text)
    st.session_state["req_suggest"] = suggest or []


def _submit_topic(topic: str, me: dict) -> None:
    """بررسی خودکار ویکی‌پدیا و ثبت درخواست (نتیجه در session می‌ماند تا با rerun از بین نرود)."""
    with st.spinner("در حال بررسی صفحه در ویکی‌پدیا…"):
        wiki = wiki_fetcher.check_title(topic)
    status = wiki["status"]
    if status == "missing":
        mm.create_request(me["username"], topic, wiki=wiki, status=mm.AUTO_REJECTED, note="صفحه در ویکی‌پدیا وجود ندارد.")
        _say("error", f"❌ صفحه‌ای با عنوان «{topic}» در ویکی‌پدیا پیدا نشد؛ درخواست ثبت نشد.", wiki_fetcher.suggest_titles(topic))
    elif status == "disambiguation":
        _say("warning", f"«{wiki['title']}» صفحه‌ی ابهام‌زدایی است؛ لطفاً صفحه‌ی مشخصی را انتخاب کنید.", wiki_fetcher.suggest_titles(topic))
    elif status == "found":
        if mm.find_open_by_pageid(wiki["pageid"]):
            _say("info", "برای این صفحه قبلاً درخواستی ثبت شده و در جریان است.")
            return
        try:
            from ingest import neo4j_ingest
            if neo4j_ingest.page_node_count(wiki["pageid"]):
                mm.create_request(me["username"], topic, wiki=wiki, status=mm.AUTO_REJECTED, note="صفحه قبلاً در گراف وارد شده است.")
                _say("info", f"«{wiki['title']}» قبلاً در گراف دانش وجود دارد؛ نیازی به درخواست نیست.")
                return
        except Exception:  # noqa: BLE001  (Neo4j در دسترس نیست؛ ادمین بعداً بررسی می‌کند)
            pass
        mm.create_request(me["username"], topic, wiki=wiki)
        _say("success", f"✅ صفحه‌ی «{wiki['title']}» در ویکی‌پدیا وجود دارد ({wiki.get('chars', 0):,} کاراکتر، ≈ {wiki.get('chunks', 0)} بخش) "
                        "و درخواست برای تأیید ادمین ارسال شد.")
    else:
        mm.create_request(me["username"], topic, wiki=wiki)
        _say("warning", "بررسی ویکی‌پدیا الان ممکن نشد؛ درخواست ثبت شد و پیش از اجرا دوباره بررسی می‌شود.")


def render_request() -> None:
    header("Request Topic", "ارسال درخواست موضوع جدید — بررسی خودکار ویکی‌پدیا")
    me = _me()
    with st.form("request"):
        topic = st.text_input("عنوان صفحه‌ی ویکی‌پدیا (فارسی)", key="req_topic")
        ok = st.form_submit_button("بررسی و ارسال درخواست", use_container_width=True)
    if ok:
        if not topic.strip():
            _say("warning", "موضوع را وارد کنید.")
        else:
            _submit_topic(topic.strip(), me)
    result = st.session_state.get("req_result")
    if result:
        getattr(st, result[0])(result[1])
    options = st.session_state.get("req_suggest") or []
    if options:
        st.caption("منظورتان یکی از این صفحه‌ها بود؟")
        cols = st.columns(min(3, len(options)))
        for i, t in enumerate(options):
            cols[i % len(cols)].button(t, key=f"sg_{i}", on_click=_pick_suggestion, args=(t,))
    render_my_history(embedded=True)


def render_history(embedded: bool = False) -> None:
    if not embedded:
        header("History", "تاریخچه‌ی درخواست‌ها")
        _jobs_panel(admin=True)
    h = mm.history()
    st.markdown("### History")
    if not h:
        st.info("History خالی است.")
        return
    st.dataframe([{"کاربر": x["username"], "موضوع": x["topic"], "ویکی": (x.get("wiki") or {}).get("status", "—"),
                   "وضعیت": _STATUS_FA.get(x["status"], x["status"]), "بررسی‌کننده": x.get("reviewer") or "—",
                   "فرایند": pipeline.STAGE_FA.get((x.get("job") or {}).get("stage"), "—"), "تاریخ": x["created_at"]}
                  for x in h], use_container_width=True, hide_index=True)


def render_my_history(embedded: bool = False) -> None:
    if not embedded:
        header("My History", "تاریخچه‌ی درخواست‌های من")
    rows = mm.user_requests(_me()["username"])
    st.markdown("### درخواست‌های من")
    st.button("🔄 تازه‌سازی وضعیت", key="my_refresh")
    if not rows:
        st.info("هنوز درخواستی ثبت نکرده‌اید.")
        return
    for x in sorted(rows, key=lambda r: r["created_at"], reverse=True):
        with st.container(border=True):
            st.markdown(f"**{x['topic']}** — {_STATUS_FA.get(x['status'], x['status'])}")
            st.markdown(f"ویکی‌پدیا: {_wiki_line(x)}")
            if x.get("note"):
                st.caption(x["note"])
            _render_job(x, False, "m" + x["id"])
