"""بخش‌های آکاردئون صفحه‌ی Bloom: جستجو، فیلتر/نمایش، موجودیت و گسترش، یابنده‌ی مسیر، داده‌ها."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from config import settings
from database import queries as q
from graph import graph_builder as gb
from graph import graph_filters as gf
from graph import graph_state as gstate
from utils import caching
from utils.formatting import fmt_int, normalize_text
from views import bloom_actions as ba
from views import widgets


MODE_LABELS = {gb.MODE_CUMULATIVE: "همه‌ی لایه‌ها تا N", gb.MODE_EXACT: "فقط لایه‌ی N (با نودهای اتصال‌دهنده)"}


# =========================================================== جستجو و شروع
def sec_search(ctx: dict) -> None:
    labels = caching.cached_labels()
    st.text_input("نام موجودیت", key="bl_term", placeholder="مثلاً: عباس میرزا", on_change=ba.do_search)
    c1, c2 = st.columns(2)
    c1.selectbox("نوع", ["All"] + labels, key="bl_type", format_func=lambda t: t if t == "All" else settings.label_fa(t))
    c2.selectbox("عمق (Depth)", list(range(1, settings.MAX_DEPTH + 1)), index=1, key="bl_depth")
    st.radio("نمایش لایه‌ها", [gb.MODE_CUMULATIVE, gb.MODE_EXACT], key="bl_mode",
             format_func=lambda m: MODE_LABELS[m], help="«فقط لایه‌ی N» لایه‌ی N را با نودهای اتصال‌دهنده‌اش نشان می‌دهد.")
    st.number_input("حداکثر نود در هر لایه", 20, settings.HARD_MAX_NODES, settings.DEFAULT_MAX_NODES, 50, key="bl_max")
    st.button("🔍 جستجو", key="bb_search", type="primary", on_click=ba.do_search, use_container_width=True)

    t1, t2, t3 = st.tabs(["نتایج", "⭐ نشانک‌ها", "🕘 اخیر"])
    with t1:
        results = st.session_state.get("bl_results") or []
        if not results:
            st.caption("هنوز جستجویی انجام نشده است.")
        else:
            ids = [r["id"] for r in results]
            if st.session_state.get("bl_result_pick") not in ids:
                st.session_state.pop("bl_result_pick", None)
            by_id = {r["id"]: r for r in results}
            pick = st.selectbox("نتایج جستجو", ids, key="bl_result_pick",
                                format_func=lambda i: f"{by_id[i]['name']} · {by_id[i]['type']} · {by_id[i]['degree']} رابطه")
            st.button("🎯 نمایش همسایگی", key="bb_open_pick", on_click=ba.open_node, args=(by_id[pick],), use_container_width=True)
    with t2:
        books = list(st.session_state.get("kg_bookmarks", {}).values())
        if not books:
            st.caption("از بخش «موجودیت»، دکمه‌ی نشانک را بزنید.")
        for b in books:
            st.button(f"⭐ {b['name']}", key=f"bb_bm_{b['id']}", on_click=ba.open_node, args=(b,), use_container_width=True)
    with t3:
        recents = st.session_state.get("kg_recent", [])
        if not recents:
            st.caption("هنوز موردی نیست.")
        for r in recents:
            st.button(r["name"], key=f"bb_rc_{r['id']}", on_click=ba.open_node, args=(r,), use_container_width=True)


# =========================================================== فیلتر و نمایش
def sec_filters(ctx: dict) -> None:
    st.markdown("**نوع نود**")
    gf.node_type_filter("bl_ft")
    st.markdown("**نوع رابطه**")
    gf.rel_type_filter("bl_rels")
    st.markdown("**نمایش گراف**")
    st.checkbox("Physics", value=True, key="bl_physics")
    st.checkbox("Show Labels", value=True, key="bl_labels")
    st.checkbox("Show Relationship Labels", value=False, key="bl_elabels")
    st.checkbox("پس‌زمینه‌ی تیره", value=False, key="bl_dark")
    st.slider("ارتفاع گراف", 450, 1000, 760, 50, key="bl_height")
    overlay = st.session_state.get("kg_overlay")
    if overlay:
        st.checkbox(f"🎨 اعمال نتایج GDS: {overlay.get('title', '')}", value=True, key="bl_overlay_on")
    st.caption("فیلتر نوع نود روی گراف جاری فوراً اعمال می‌شود و برای جستجو و گسترش‌های بعدی هم به‌کار می‌رود.")


# =========================================================== موجودیت و گسترش
def sec_entity(ctx: dict) -> None:
    fg, ids = ctx["fg"], ctx["ids"]
    if not ids:
        st.info("ابتدا گرافی باز کنید (جستجو یا «نمایش کل گراف»).")
        return
    sel = st.selectbox("موجودیت انتخاب‌شده (از گراف)", ids, key="bl_selected",
                       format_func=lambda i: f"{fg['nodes'][i]['name']} · {fg['nodes'][i]['type']}")
    node = fg["nodes"][sel]
    a, b = st.columns([2, 1])
    a.radio("تعداد لایه", [1, 2, 3], horizontal=True, key="bl_layers", format_func=lambda x: f"{x} لایه")
    b.button("➕ Expand", key="bb_expand", on_click=ba.do_expand, args=(node,), use_container_width=True, type="primary")
    st.radio("نوع گسترش", [gb.MODE_CUMULATIVE, gb.MODE_EXACT], key="bl_xmode", format_func=lambda m: MODE_LABELS[m],
             help="گسترش از میان نودهای از قبل نمایش‌داده‌شده هم عبور می‌کند؛ فقط نودهای جدید اضافه می‌شوند.")
    c1, c2, c3 = st.columns(3)
    is_book = sel in st.session_state.get("kg_bookmarks", {})
    c1.button("⭐ حذف" if is_book else "☆ نشانک", key="bb_bm", on_click=ba.do_bookmark, args=(node,), use_container_width=True)
    c2.button("🧭 مبدأ مسیر", key="bb_from", on_click=ba.set_path_end, args=("from", node), use_container_width=True)
    c3.button("🏁 مقصد مسیر", key="bb_to", on_click=ba.set_path_end, args=("to", node), use_container_width=True)

    t1, t2, t3 = st.tabs(["پروفایل", "رابطه‌ها", "Relationship Inspector"])
    with t1:
        widgets.render_node_detail(sel, key="bl", show_relations=False)
    rels = q.node_relations(sel, 1000)
    with t2:
        if not rels:
            st.caption("رابطه‌ای ثبت نشده است.")
        else:
            df = pd.DataFrame(rels)
            st.caption(f"{len(df)} رابطه")
            summary = df.groupby(["relation", "outgoing"]).size().reset_index(name="count").sort_values("count", ascending=False)
            summary["جهت"] = summary["outgoing"].map({True: "خروجی ←", False: "→ ورودی"})
            st.dataframe(summary[["relation", "جهت", "count"]].rename(columns={"relation": "رابطه", "count": "تعداد"}),
                         hide_index=True, use_container_width=True, height=min(260, 45 + 35 * len(summary)))
            flt = st.multiselect("فیلتر نوع رابطه", sorted(df["relation"].unique()), key=f"bl_relf_{sel}")
            shown = df[df["relation"].isin(flt)] if flt else df
            st.dataframe(shown.assign(جهت=shown["outgoing"].map({True: "←", False: "→"}))[
                ["جهت", "relation", "other", "other_type", "source_count"]].rename(
                columns={"relation": "رابطه", "other": "موجودیت", "other_type": "نوع", "source_count": "منابع"}),
                hide_index=True, use_container_width=True, height=300)
    with t3:
        if not rels:
            st.caption("رابطه‌ای نیست.")
        else:
            rids = [r["rel_id"] for r in rels[:200]]
            if st.session_state.get("bl_rel_pick") not in rids:
                st.session_state.pop("bl_rel_pick", None)
            by = {r["rel_id"]: r for r in rels}
            rid = st.selectbox("رابطه", rids, key="bl_rel_pick",
                               format_func=lambda i: f"{'←' if by[i]['outgoing'] else '→'} {by[i]['relation']} · {by[i]['other']}")
            st.button("🕸 نمایش این رابطه روی گراف", key="bb_show_rel", on_click=ba.show_relation, args=(rid,), use_container_width=True)
            widgets.render_edge_detail(rid)


# =========================================================== یابنده‌ی مسیر
def _path_text(p: dict) -> str:
    nodes, parts = p["nodes"], []
    for i, r in enumerate(p["rels"]):
        arrow = f" —[{r['type']}]→ " if r["source"] == nodes[i]["id"] else f" ←[{r['type']}]— "
        parts.append(nodes[i]["name"] + arrow)
    return "".join(parts) + nodes[-1]["name"]


def sec_path(ctx: dict) -> None:
    a = widgets.entity_picker("From (مبدأ)", "bl_pf_from")
    b = widgets.entity_picker("To (مقصد)", "bl_pf_to")
    c1, c2 = st.columns(2)
    max_len = c1.slider("Maximum Length", 1, 6, 5, key="bl_pf_len")
    k = c2.slider("حداکثر مسیر", 1, 30, 10, key="bl_pf_k")
    mode = st.radio("حالت", ["کوتاه‌ترین مسیرها", "همه‌ی مسیرها (حداکثر طول ۴)"], key="bl_pf_mode", horizontal=True)
    if st.button("🧭 Find Path", key="bb_pf_go", type="primary", use_container_width=True):
        if not a or not b:
            st.warning("هر دو موجودیت را انتخاب کنید.")
        elif a["id"] == b["id"]:
            st.warning("مبدأ و مقصد یکسان‌اند.")
        else:
            with st.spinner("در حال جستجوی مسیر…"):
                paths = q.find_paths(a["id"], b["id"], max_len, k, mode.startswith("کوتاه"))
            st.session_state["bl_pf_result"] = {"paths": paths, "a": a["name"], "b": b["name"]}
            st.session_state["bl_pf_pick"] = 0
            if paths:
                ba.apply_path(paths, 0)          # مسیر اول فوراً روی گراف می‌آید
    res = st.session_state.get("bl_pf_result")
    if not res:
        return
    paths = res["paths"]
    if not paths:
        st.info("مسیری با این محدودیت پیدا نشد؛ طول مجاز را بیشتر کنید.")
        return
    st.success(f"{len(paths)} مسیر بین «{res['a']}» و «{res['b']}» — مسیر انتخاب‌شده روی گراف Highlight می‌شود.")
    if st.session_state.get("bl_pf_pick", 0) >= len(paths):
        st.session_state["bl_pf_pick"] = 0
    idx = st.selectbox("مسیر", range(len(paths)), key="bl_pf_pick", format_func=lambda i: f"مسیر {i + 1} — طول {paths[i]['length']}")
    d1, d2 = st.columns(2)
    d1.button("🕸 نمایش روی گراف", key="bb_pf_apply", on_click=ba.apply_path, args=(paths, idx), use_container_width=True, type="primary")
    d2.button("✖ پاک‌کردن Highlight", key="bb_pf_clear", on_click=ba.clear_highlight, use_container_width=True)
    t1, t2 = st.tabs(["Text", "Table"])
    with t1:
        for i, p in enumerate(paths, 1):
            st.markdown(f"**{i}.** {_path_text(p)} _(طول {p['length']})_")
    with t2:
        st.dataframe(pd.DataFrame([{"#": i, "طول": p["length"], "مسیر": _path_text(p)} for i, p in enumerate(paths, 1)]),
                     hide_index=True, use_container_width=True)


# =========================================================== داده‌ها (Data Explorer)
def _pager(prefix: str, total: int, size: int) -> int:
    pages = max(1, -(-total // size))
    if st.session_state.get(f"{prefix}_page", 1) > pages:
        st.session_state[f"{prefix}_page"] = pages
    c1, c2 = st.columns([1, 2])
    page = c1.number_input("صفحه", 1, pages, 1, key=f"{prefix}_page")
    c2.caption(f"{fmt_int(total)} مورد · صفحه‌ی {page} از {pages}")
    return (int(page) - 1) * size


def _join(v) -> str:
    return " | ".join(map(str, v)) if isinstance(v, list) else (v or "")


def sec_data(ctx: dict) -> None:
    labels = caching.cached_labels()
    tn, tr = st.tabs(["Nodes", "Relationships"])
    with tn:
        search = normalize_text(st.text_input("جستجو در نام", key="bl_dn_q"))
        types = st.multiselect("نوع", labels, key="bl_dn_types", format_func=settings.label_fa)
        c1, c2 = st.columns(2)
        sort = c1.selectbox("مرتب‌سازی", ["name", "type", "source_count", "degree"], key="bl_dn_sort")
        size = c2.selectbox("اندازه‌ی صفحه", [10, 25, 50, 100], index=1, key="bl_dn_size")
        total = q.explorer_nodes(search, types, sort, 0, 1)[1]
        skip = _pager("bl_dn", total, size)
        rows, _ = q.explorer_nodes(search, types, sort, skip, size)
        df = pd.DataFrame([{"Name": r["name"], "Type": r["type"], "Degree": r["degree"], "Sources": r["source_count"]} for r in rows])
        ev = st.dataframe(df, hide_index=True, use_container_width=True, height=330, on_select="rerun",
                          selection_mode="single-row", key="bt_nodes")
        sel = ev.selection.rows if ev and ev.selection else []
        if sel and sel[0] < len(rows):
            r = rows[sel[0]]
            st.button(f"🎯 نمایش «{r['name']}» روی گراف", key="bb_dn_open", on_click=ba.open_node,
                      args=({"id": r["id"], "name": r["name"], "type": r["type"]},), use_container_width=True, type="primary")
        if st.button("📦 آماده‌سازی CSV (حداکثر ۱۰۰٬۰۰۰ ردیف)", key="bb_dn_export"):
            ex = pd.DataFrame(q.export_nodes(search, types))
            for c in ("source_titles", "source_urls"):
                if c in ex:
                    ex[c] = ex[c].map(_join)
            st.session_state["bl_dn_csv"] = ex.to_csv(index=False).encode("utf-8-sig")
        if st.session_state.get("bl_dn_csv"):
            st.download_button("⬇ nodes.csv", st.session_state["bl_dn_csv"], "nodes.csv", "text/csv", key="bt_dn_dl")
    with tr:
        search = normalize_text(st.text_input("جستجو در نام مبدأ/مقصد", key="bl_dr_q"))
        rel_q = normalize_text(st.text_input("جستجو در نوع رابطه", key="bl_dr_rq"))
        s_types = st.multiselect("نوع مبدأ", labels, key="bl_dr_st", format_func=settings.label_fa)
        d_types = st.multiselect("نوع مقصد", labels, key="bl_dr_dt", format_func=settings.label_fa)
        c1, c2 = st.columns(2)
        sort = c1.selectbox("مرتب‌سازی", ["relation", "source", "source_count"], key="bl_dr_sort")
        size = c2.selectbox("اندازه‌ی صفحه", [10, 25, 50, 100], index=1, key="bl_dr_size")
        total = q.explorer_relationships(search, rel_q, s_types, d_types, sort, 0, 1)[1]
        skip = _pager("bl_dr", total, size)
        rows, _ = q.explorer_relationships(search, rel_q, s_types, d_types, sort, skip, size)
        df = pd.DataFrame([{"Source": r["source"], "Relationship": r["relation"], "Target": r["target"], "Sources": r["source_count"]}
                           for r in rows])
        ev = st.dataframe(df, hide_index=True, use_container_width=True, height=330, on_select="rerun",
                          selection_mode="single-row", key="bt_rels")
        sel = ev.selection.rows if ev and ev.selection else []
        if sel and sel[0] < len(rows):
            r = rows[sel[0]]
            st.button("🕸 نمایش این رابطه روی گراف", key="bb_dr_open", on_click=ba.show_relation, args=(r["id"],),
                      use_container_width=True, type="primary")
        if st.button("📦 آماده‌سازی CSV (حداکثر ۱۰۰٬۰۰۰ ردیف)", key="bb_dr_export"):
            ex = pd.DataFrame(q.export_relationships(search, rel_q, s_types, d_types))
            for c in ("source_titles", "source_urls"):
                if c in ex:
                    ex[c] = ex[c].map(_join)
            st.session_state["bl_dr_csv"] = ex.to_csv(index=False).encode("utf-8-sig")
        if st.session_state.get("bl_dr_csv"):
            st.download_button("⬇ relationships.csv", st.session_state["bl_dr_csv"], "relationships.csv", "text/csv", key="bt_dr_dl")
