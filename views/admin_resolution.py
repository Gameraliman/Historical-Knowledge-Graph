"""Entity Resolution کل گراف (ادمین): اسکن ← داوری LLM روی موارد مشکوک ← بازبینی ← پیش‌نمایش ← اعمال (با تأیید صریح)."""
from __future__ import annotations

import json
import math

import pandas as pd
import streamlit as st

from config import settings
from ingest import llm_extractor
from resolution import adjudicate, candidates, merge
from utils import caching
from utils.formatting import db_guard, fmt_int, header


def _cands_with_verdicts(cands: list[dict], snap: dict, cache: dict, auto: bool) -> list[tuple[dict, dict | None]]:
    out = []
    for p in cands:
        a, b = snap["nodes"][p["a_id"]], snap["nodes"][p["b_id"]]
        v = cache.get(candidates.cache_key(a, b))
        if v is None and auto and p["reason"] == "exact_norm":
            v = adjudicate.auto_verdict(p, snap)
        out.append((p, v))
    return out


@db_guard
def render() -> None:
    header("Entity Resolution (کل گراف)", "اسکن کل گراف ← داوری LLM روی موارد مشکوک ← ادغام با تأیید شما")
    st.info("🛡 مراحل ۱ تا ۳ فقط می‌خوانند و تصمیم‌ها را پیشنهاد می‌دهند. ادغام نودها (مرحله‌ی ۴) حذف داده است: فقط وقتی "
            "`ALLOW_GRAPH_MERGE=true` باشد، با تأیید صریح و **بعد از گرفتن Backup/Snapshot** اجرا می‌شود و برگشت خودکار ندارد.")
    if not settings.GROQ_API_KEY:
        st.warning("⚠ `GROQ_API_KEY` تنظیم نشده؛ اسکن و بازبینی دستی کار می‌کند ولی داوری LLM نه.")

    result = st.session_state.get("er_result")
    if result:
        st.success("ادغام‌ها اعمال شد. تحلیل را دوباره اجرا کنید؛ Projectionهای GDS را Refresh کنید.")
        st.dataframe(pd.DataFrame(result["log"]), hide_index=True, use_container_width=True)
        c1, c2 = st.columns(2)
        c1.download_button("⬇ merge map (برای import_to_neo4j --merge-map)", json.dumps(result["map"], ensure_ascii=False, indent=1).encode("utf-8"),
                           "entity_merge_map.json", "application/json")
        c2.download_button("⬇ لاگ ادغام", json.dumps(result["log"], ensure_ascii=False, indent=1).encode("utf-8"), "er_merge_log.json", "application/json")
        if st.button("بستن این نتیجه"):
            st.session_state.pop("er_result")
            st.rerun()

    # ============================ ۱) اسکن ============================
    st.markdown("### ۱) اسکن کل گراف")
    labels = caching.cached_labels()
    types = st.multiselect("نوع نودهایی که بررسی شوند", labels, default=[t for t in labels if t not in ("Time", "Quantity")],
                           help="زمان و مقدار به‌صورت پیش‌فرض کنار گذاشته شده‌اند؛ شباهت املایی تاریخ‌ها معنی ندارد.")
    c1, c2 = st.columns(2)
    min_score = c1.slider("حداقل امتیاز شباهت", 0.5, 1.0, 0.6, 0.05)
    max_pairs = c2.number_input("حداکثر جفت کاندید", 50, 3000, 300, 50)
    if st.button("🔍 اسکن کل گراف", type="primary"):
        with st.spinner("در حال خواندن گراف و یافتن جفت‌های مشکوک…"):
            snap = candidates.load_snapshot()
            st.session_state["er_snap"] = snap
            st.session_state["er_cands"] = candidates.generate_candidates(snap, types, float(min_score), int(max_pairs))
            st.session_state["er_scanned"] = True
    snap, cands = st.session_state.get("er_snap"), st.session_state.get("er_cands")
    if not snap:
        return
    if not cands:
        st.success("جفت مشکوکی با این آستانه پیدا نشد.")
        return
    cache = adjudicate.load_cache()
    auto = st.checkbox("جفت‌هایی که فقط در نیم‌فاصله/ی و ک عربی/ارقام/اعراب فرق دارند خودکار «یکی» حساب شوند (بدون LLM)", value=True)
    items = _cands_with_verdicts(cands, snap, cache, auto)
    todo = [p for p, v in items if v is None]
    reasons = pd.Series([p["reason"] for p in cands]).value_counts()
    m = st.columns(4)
    m[0].metric("نودهای اسکن‌شده", fmt_int(len(snap["nodes"])))
    m[1].metric("جفت کاندید", fmt_int(len(cands)))
    m[2].metric("داوری‌شده (کش/خودکار)", fmt_int(len(cands) - len(todo)))
    m[3].metric("منتظر LLM", fmt_int(len(todo)))
    st.caption("دلیل کاندید: " + " · ".join(f"{adjudicate.REASON_FA.get(k, k)}: {v}" for k, v in reasons.items()))
    with st.expander("گزارش: نام یکسان با نوع‌های متفاوت (فقط اطلاع؛ ادغام نمی‌شود)"):
        cross = candidates.cross_label_same_names(snap)
        st.dataframe(pd.DataFrame(cross), hide_index=True, use_container_width=True) if cross else st.caption("موردی نیست.")

    # ============================ ۲) داوری LLM ============================
    st.markdown("### ۲) داوری LLM روی موارد مشکوک")
    c1, c2, c3 = st.columns(3)
    batch = c1.number_input("جفت در هر درخواست", 1, 20, 8)
    delay = c2.number_input("وقفه بین درخواست‌ها (ثانیه)", 0, 120, 5)
    limit = c3.number_input("حداکثر جفت در این اجرا", 8, 1000, 80, 8, help="بعد از هر دسته نتیجه ذخیره می‌شود؛ می‌توانید چند بار اجرا کنید.")
    n_run = min(len(todo), int(limit))
    if st.button(f"🤖 داوری {n_run} جفت (~{math.ceil(n_run / int(batch)) if n_run else 0} درخواست)", disabled=not (todo and settings.GROQ_API_KEY)):
        prog = st.progress(0.0, text="شروع…")
        try:
            stats = adjudicate.run_adjudication(todo[:n_run], snap, cache, int(batch), float(delay),
                                                lambda i, n: prog.progress((i - 1) / n, text=f"دسته {i} از {n}…"))
            prog.progress(1.0, text="تمام شد.")
            st.success(f"{stats['answered']} پاسخ از {stats['asked']} جفت دریافت و ذخیره شد.")
        except llm_extractor.LLMNotConfigured as exc:
            st.error(str(exc))
        except Exception as exc:  # noqa: BLE001
            st.error(f"خطا در داوری: {exc}. نتیجه‌ی دسته‌های قبلی ذخیره شده است؛ دوباره اجرا کنید.")
        cache = adjudicate.load_cache()
        items = _cands_with_verdicts(cands, snap, cache, auto)

    # ============================ ۳) بازبینی ============================
    st.markdown("### ۳) بازبینی")
    thr = st.slider("آستانه‌ی اطمینان برای تیک خودکار «ادغام»", 0.5, 1.0, 0.85, 0.05)
    view = st.radio("نمایش", ["همه", "یکی (same)", "نامطمئن (unsure)", "متفاوت (different)", "بدون داوری"], horizontal=True)
    keep_map = {"همه": None, "یکی (same)": "same", "نامطمئن (unsure)": "unsure", "متفاوت (different)": "different", "بدون داوری": "—"}[view]
    rows = []
    for p, v in items:
        dec = v["decision"] if v else "—"
        if keep_map and dec != keep_map:
            continue
        a, b = snap["nodes"][p["a_id"]], snap["nodes"][p["b_id"]]
        side = "B" if v and candidates.ernorm(v["keep"]).replace(" ", "") == b["nospace"] else "A"
        rows.append({"ادغام": bool(v and dec == "same" and v["confidence"] >= thr), "ردِ دائمی": False, "A": a["name"], "B": b["name"],
                     "نوع": p["label"], "تصمیم": dec, "اطمینان": v["confidence"] if v else None, "حفظ": side,
                     "دلیل": (v or {}).get("reason", ""), "امتیاز": p["score"], "صفحه مشترک": p["shared_pages"], "pid": p["pid"]})
    if not rows:
        st.info("موردی با این فیلتر نیست.")
        return
    edited = st.data_editor(
        pd.DataFrame(rows), hide_index=True, use_container_width=True, height=min(520, 60 + 36 * len(rows)),
        disabled=[c for c in rows[0] if c not in ("ادغام", "ردِ دائمی", "حفظ")],
        column_config={"حفظ": st.column_config.SelectboxColumn("حفظ", options=["A", "B"], help="کدام نود (و نامش) باقی بماند"),
                       "اطمینان": st.column_config.NumberColumn(format="%.2f")}, key=f"bt_er_editor_{keep_map}_{thr}")
    by_pid = {p["pid"]: p for p in cands}
    with st.expander("🔎 شواهد یک جفت"):
        pid = st.selectbox("جفت", [r["pid"] for r in rows], format_func=lambda i: f"{snap['nodes'][by_pid[i]['a_id']]['name']}  ⟷  {snap['nodes'][by_pid[i]['b_id']]['name']}")
        e1, e2 = st.columns(2)
        e1.markdown("**A**\n\n" + adjudicate.node_evidence(snap["nodes"][by_pid[pid]["a_id"]], snap))
        e2.markdown("**B**\n\n" + adjudicate.node_evidence(snap["nodes"][by_pid[pid]["b_id"]], snap))
    if edited["ردِ دائمی"].any() and st.button("🚫 ثبت ردهای دائمی (دیگر پیشنهاد نشود)"):
        for r in edited[edited["ردِ دائمی"]].to_dict("records"):
            p = by_pid[r["pid"]]
            a, b = snap["nodes"][p["a_id"]], snap["nodes"][p["b_id"]]
            cache[candidates.cache_key(a, b)] = {"decision": "different", "confidence": 1.0, "keep": a["name"], "reason": "ردِ دستی ادمین", "source": "human"}
        adjudicate.save_cache(cache)
        st.rerun()

    # ============================ ۴) پیش‌نمایش و اعمال ============================
    st.markdown("### ۴) پیش‌نمایش و اعمال")
    st.caption("فقط ردیف‌هایی که در جدول بالا (با فیلتر «نمایش» فعلی) دیده می‌شوند و تیک «ادغام» دارند در نظر گرفته می‌شوند.")
    chosen = edited[edited["ادغام"] & ~edited["ردِ دائمی"]]
    pairs, merging = [], set()
    for r in chosen.to_dict("records"):
        p = by_pid[r["pid"]]
        pairs.append({"a_id": p["a_id"], "b_id": p["b_id"], "keep_id": p["a_id"] if r["حفظ"] == "A" else p["b_id"]})
        merging.add(frozenset((p["a_id"], p["b_id"])))
    denied = set()
    for p, v in items:
        if v and v["decision"] == "different" and frozenset((p["a_id"], p["b_id"])) not in merging:
            denied.add(frozenset((p["a_id"], p["b_id"])))
    if not pairs:
        st.caption("هیچ جفتی برای ادغام انتخاب نشده است.")
        return
    groups = merge.plan_groups(pairs, snap, denied)
    imp = merge.impact([d for g in groups for d in g["drop_ids"]])
    nodes = snap["nodes"]
    st.dataframe(pd.DataFrame([{
        "وضعیت": "⛔ مسدود (تعارض)" if g["blocked"] else "✅ آماده", "نوع": g["label"], "نود باقی‌مانده": nodes[g["keep_id"]]["name"],
        "ادغام می‌شوند": " ، ".join(nodes[d]["name"] for d in g["drop_ids"]),
        "رابطه‌های منتقل‌شونده": sum(imp.get(d, {}).get("out_deg", 0) + imp.get(d, {}).get("in_deg", 0) for d in g["drop_ids"]),
        "تعارض": " | ".join(" ≠ ".join(c) for c in g["conflicts"])} for g in groups]), hide_index=True, use_container_width=True)
    ready = [g for g in groups if not g["blocked"]]
    if not settings.ALLOW_GRAPH_MERGE:
        st.warning("اعمال ادغام غیرفعال است. برای فعال‌سازی `ALLOW_GRAPH_MERGE=true` را تنظیم کنید (پیش‌فرض: false).")
    confirm = st.text_input("برای تأیید، عبارت MERGE را تایپ کنید", key="er_confirm")
    backup = st.checkbox("از دیتابیس Backup/Snapshot گرفته‌ام و می‌دانم ادغام برگشت خودکار ندارد", key="er_backup")
    if st.button(f"⚠ اعمال {len(ready)} گروه ادغام", type="primary",
                 disabled=not (settings.ALLOW_GRAPH_MERGE and ready and confirm.strip() == "MERGE" and backup)):
        who = (st.session_state.get("user") or {}).get("username", "admin")
        with st.spinner("در حال ادغام…"):
            log = merge.apply_groups(ready, snap, who)
        st.cache_data.clear()
        st.session_state["er_result"] = {"log": log, "map": merge.merge_map(log)}
        for k in ("er_snap", "er_cands", "er_confirm", "er_backup"):
            st.session_state.pop(k, None)
        st.rerun()
