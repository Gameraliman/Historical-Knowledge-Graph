"""Wiki Import (فقط ادمین): نام صفحه‌ی ویکی ← دریافت متن ← استخراج با LLM ← پیش‌نمایش ← ریختن در Neo4j."""
from __future__ import annotations

import time

import pandas as pd
import requests
import streamlit as st

from config import settings
from ingest import entity_links, llm_extractor, neo4j_ingest, wiki_fetcher
from views import ingest_review
from utils.formatting import db_guard, fmt_int, header

K = "wi_results"


def _extract_titles(titles: list[str], delay: float, max_chars: int, use_links: bool = True,
                    resolve_redirects: bool = True, strip_parens: bool = False) -> list[dict]:
    results = []
    prog = st.progress(0.0, text="شروع…")
    for i, title in enumerate(titles):
        prog.progress(i / len(titles), text=f"({i + 1}/{len(titles)}) دریافت «{title}»…")
        item = {"query": title, "error": None, "warnings": [], "relations": []}
        try:
            page = wiki_fetcher.fetch_page(title)
            if not page:
                item["error"] = "صفحه در ویکی‌پدیا پیدا نشد."
            else:
                item.update(page)
                text = wiki_fetcher.clean_text(page["text"])
                chunks = wiki_fetcher.split_chunks(text, max_chars)
                item["chars"], item["chunks"] = len(text), len(chunks)
                if not chunks:
                    item["error"] = "متن صفحه خالی است."
                else:
                    link_dict = None
                    if use_links:
                        prog.progress(i / len(titles), text=f"({i + 1}/{len(titles)}) دریافت پیوندهای ویکی «{title}»…")
                        try:
                            links = entity_links.fetch_links(page["title"])
                            redirects = (entity_links.resolve_redirects([t for _, t in links])
                                         if resolve_redirects and links else None)
                            link_dict = entity_links.build_dictionary(links, page["title"], redirects, strip_parens)
                            item["link_count"] = len(links)
                            item["canonical"] = link_dict["canonical"]
                        except (requests.RequestException, ValueError, KeyError) as exc:
                            item["warnings"].append(f"دریافت پیوندهای ویکی ناموفق بود؛ فقط یکسان‌سازی با متن انجام شد ({exc}).")

                    def cb(c, n, t=title):
                        prog.progress(i / len(titles), text=f"({i + 1}/{len(titles)}) استخراج «{t}» — بخش {c}/{n}…")
                    item["relations"], warns, stats = llm_extractor.extract_chunks(page, chunks, cb, delay, link_dict)
                    item["warnings"] += warns
                    item["link_replaced"] = stats["link_replaced"]
        except llm_extractor.LLMNotConfigured as exc:
            item["error"] = str(exc)
            results.append(item)
            break
        except requests.RequestException as exc:
            item["error"] = f"خطای شبکه/ویکی‌پدیا: {exc}"
        except Exception as exc:  # noqa: BLE001  (خطای مدل و ...)
            item["error"] = f"خطای استخراج: {exc}"
        results.append(item)
        if i < len(titles) - 1:
            time.sleep(1.0)  # ادب نسبت به سرور ویکی‌پدیا
    prog.progress(1.0, text="تمام شد.")
    return results


@db_guard
def render() -> None:
    header("Wiki Import", "استخراج Entity و Relation از صفحه‌ی ویکی‌پدیا و ریختن در Neo4j")
    if not settings.ALLOW_WIKI_IMPORT:
        st.warning("ایمپورت از ویکی غیرفعال است (ALLOW_WIKI_IMPORT=false).")
        return
    if not settings.GROQ_API_KEY:
        st.warning("⚠ کلید Groq تنظیم نشده است: `GROQ_API_KEY` را در `.env` یا Secrets بگذارید "
                   "(نام قبلی `GROQ_API_KEY_6` هم پذیرفته می‌شود).")
    st.info(f"مدل: `{settings.GROQ_MODEL}` · روش: دریافت متن از fa.wikipedia.org ← استخراج با همان Prompt اسکریپت شما ← "
            "پیش‌نمایش و تأیید ← ایمپورت افزایشی (بدون Merge/Entity Resolution خودکار).")

    use_links = st.checkbox("یکسان‌سازی موجودیت‌ها با پیوندهای ویکی (سپس بررسی کل متن برای بقیه)", value=True, key="wi_links",
                            help="مرحله‌ی الف: نام‌ها با [[پیوندهای]] صفحه به عنوان استاندارد وصل می‌شوند. مرحله‌ی ب: آنچه در "
                                 "پیوندها نبود، با بررسی کل متن (بدل/ضمیر/ارجاع) یکسان می‌شود.")
    if use_links:
        l1, l2 = st.columns(2)
        resolve_redirects = l1.checkbox("رفع Redirect عنوان‌ها (درخواست‌های بیشتر به ویکی‌پدیا)", value=True, key="wi_redir")
        strip_parens = l2.checkbox("حذف توضیح داخل پرانتز از نام استاندارد", value=False, key="wi_strip",
                                   help="«محمود میرزا (پسر فتحعلی‌شاه)» ← «محمود میرزا». ممکن است دو شخص همنام یکی شوند.")
    else:
        resolve_redirects = strip_parens = False
    titles_text = st.text_area("نام صفحه‌ی ویکی‌پدیا (هر خط یک صفحه)", height=110, key="wi_titles",
                               placeholder="فتحعلی‌شاه\nآقامحمدخان قاجار")
    c1, c2, c3 = st.columns(3)
    delay = c1.number_input("وقفه بین درخواست‌های مدل (ثانیه)", 0, 120, 5, key="wi_delay",
                            help="برای محدودیت نرخ Groq؛ اسکریپت اصلی شما ۶۰ ثانیه می‌گذاشت.")
    max_chars = c2.number_input("حداکثر کاراکتر هر بخش", 1000, 12000, settings.WIKI_MAX_CHARS, 500, key="wi_chars")
    c3.metric("هیچ سقفی برای طول صفحه نیست", "کل متن", help="صفحه‌ی بلند به چند بخش تقسیم و همه‌ی بخش‌ها استخراج می‌شوند.")

    titles = list(dict.fromkeys(t.strip() for t in titles_text.splitlines() if t.strip()))
    if st.button(f"1) دریافت و استخراج ({len(titles)} صفحه)", type="primary", disabled=not titles):
        st.session_state[K] = _extract_titles(titles, float(delay), int(max_chars),
                                                   use_links, resolve_redirects, strip_parens)

    results = st.session_state.get(K)
    if not results:
        return
    st.divider()
    st.markdown("### 2) بازبینی نتایج")
    st.caption("ردیف‌های اشتباه را با برداشتن تیک «✔» کنار بگذارید. «موجود» یعنی نودی با همان نوع و نامِ دقیق از قبل در گراف هست "
               "و رابطه به همان نود وصل می‌شود؛ «جدید» نود تازه می‌سازد.")
    selected: dict[int, pd.DataFrame] = {}
    for i, item in enumerate(results):
        label = item.get("title") or item["query"]
        if item["error"]:
            st.error(f"«{label}»: {item['error']}")
            continue
        seen = neo4j_ingest.page_node_count(item["pageid"])
        with st.expander(f"{label} — {len(item['relations'])} رابطه", expanded=len(results) == 1):
            st.markdown(f"[{item['title']}]({item['source']}) · Page ID: `{item['pageid']}` · "
                        f"{item['chars']:,} کاراکتر · {item['chunks']} بخش")
            if item.get("link_count") is not None:
                st.caption(f"🔗 {item['link_count']} پیوند ویکی در صفحه بود؛ {item.get('link_replaced', 0)} نام پس از پاسخ مدل "
                           "به‌صورت قطعی با پیوندها یکسان شد. ستون «لینک»: طرفی از رابطه که نام استاندارد ویکی دارد.")
            if seen:
                st.warning(f"این صفحه قبلاً در گراف هست ({seen} نود به آن ارجاع دارند). ایمپورت مجدد داده‌ی تکراری نمی‌سازد، "
                           "اما رابطه‌های جدید اضافه می‌شوند.")
            for w in item["warnings"]:
                st.caption(f"⚠ {w}")
            chosen = ingest_review.review_editor(item["relations"], item.get("canonical"), f"wi_edit_{i}")
            if chosen is not None:
                selected[i] = chosen

    total = sum(len(d) for d in selected.values())
    st.markdown("### 3) ریختن در Neo4j")
    st.caption("نیازمند دسترسی نوشتن برای کاربر Neo4j است. پس از ایمپورت، Projectionهای GDS را Refresh کنید.")
    ok = st.checkbox(f"تأیید می‌کنم {fmt_int(total)} رابطه در Neo4j نوشته شود", key="wi_confirm")
    if st.button("🚀 ایمپورت به Neo4j", type="primary", disabled=not (ok and total)):
        done, summary = [], []
        for i, df in selected.items():
            if df.empty:
                continue
            item = results[i]
            rels = ingest_review.to_relations(df)
            stats = neo4j_ingest.import_relations(item, rels)
            summary.append({"صفحه": item["title"], "رابطه": stats["edges"], "نود": stats["nodes"], "نود جدید": stats["new_nodes"]})
            done.append(i)
        st.cache_data.clear()
        for key in [k for k in st.session_state if str(k).startswith("wi_edit_")]:
            del st.session_state[key]
        st.session_state[K] = [r for j, r in enumerate(results) if j not in done]
        st.session_state["wi_summary"] = summary
        st.rerun()
    if st.session_state.get("wi_summary"):
        st.success("ایمپورت انجام شد؛ کش آمار پاک شد.")
        st.dataframe(pd.DataFrame(st.session_state.pop("wi_summary")), hide_index=True, use_container_width=True)
