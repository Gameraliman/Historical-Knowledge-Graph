#!/usr/bin/env python3
"""
انتقال فایل Extraction123_entity_resolved_corrected.json به Neo4j

- هر خط فایل یک JSON جداگانه است (JSON Lines) با کلیدهای: Pageid, Title, Source, relations
- هر نود با کلید (name + label) یکتا می‌شود
- روی هر نود، منابعش ذخیره می‌شود:
    source_urls      : لیست لینک صفحات ویکی‌پدیا که این نود در آن‌ها آمده
    source_titles    : لیست عنوان همان صفحات
    source_pageids   : لیست Pageid همان صفحات
    source_count     : تعداد منابع
- روی هر رابطه هم همین منابع ذخیره می‌شود
- اسکریپت idempotent است؛ چند بار اجرا کنید داده تکراری نمی‌سازد

نصب:    pip install neo4j
اجرا:   python import_to_neo4j.py --file Extraction123_entity_resolved_corrected.json \
            --uri bolt://localhost:7687 --user neo4j --password YOUR_PASSWORD
"""
import argparse
import json
import re
from collections import defaultdict

from neo4j import GraphDatabase

# برچسب‌های مجاز (برای جلوگیری از injection چون label را نمی‌شود پارامتر کرد)
ALLOWED_LABELS = {
    "Person", "Location", "Organization", "Event", "Time", "Role",
    "Work", "Title", "Object", "Group", "Quantity", "Document",
}
BATCH_SIZE = 30000


def safe_label(label: str) -> str:
    label = (label or "").strip()
    if label in ALLOWED_LABELS:
        return label
    # برچسب ناشناخته → تبدیل به شکل امن
    cleaned = re.sub(r"[^A-Za-z0-9_]", "", label)
    return cleaned if cleaned else "Entity"


def load_and_aggregate(path: str, merge_map=None):
    """فایل را می‌خواند و نودها/رابطه‌ها را همراه منابعشان تجمیع می‌کند."""
    nodes = {}   # (label, name) -> {"sources": {pageid: (title, url)}}
    edges = {}   # (s_label, s_name, rel, o_label, o_name) -> {"sources": {...}}

    def add_source(store, key, pageid, title, url):
        entry = store.setdefault(key, {"sources": {}})
        entry["sources"][pageid] = (title, url)

    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                page = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"[هشدار] خط {line_no} نامعتبر است و رد شد: {e}")
                continue

            pageid = page.get("Pageid")
            title = page.get("Title", "")
            url = page.get("Source", "")

            for r in page.get("relations", []):
                s_name, s_type = r["subject"][0], safe_label(r["subject"][1])
                o_name, o_type = r["object"][0], safe_label(r["object"][1])
                rel = r["relation"]
                # نتیجه‌ی Entity Resolution (از سامانه: Wiki/ER ← Export merge map): {label: {نام قدیمی: نام جدید}}
                if merge_map:
                    s_name = merge_map.get(s_type, {}).get(s_name, s_name)
                    o_name = merge_map.get(o_type, {}).get(o_name, o_name)

                add_source(nodes, (s_type, s_name), pageid, title, url)
                add_source(nodes, (o_type, o_name), pageid, title, url)
                add_source(edges, (s_type, s_name, rel, o_type, o_name),
                           pageid, title, url)
    return nodes, edges


def pack_sources(sources: dict):
    """تبدیل دیکشنری منابع به لیست‌های موازی (قابل ذخیره در Neo4j)."""
    ids = sorted(sources.keys(), key=lambda x: (x is None, x))
    return {
        "source_pageids": ids,
        "source_titles": [sources[i][0] for i in ids],
        "source_urls": [sources[i][1] for i in ids],
        "source_count": len(ids),
    }


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--uri", default="bolt://localhost:7687")
    ap.add_argument("--user", default="neo4j")
    ap.add_argument("--password", required=True)
    ap.add_argument("--database", default="neo4j")
    ap.add_argument("--merge-map", help="فایل JSON خروجی Entity Resolution سامانه: {label: {old_name: kept_name}}")
    ap.add_argument("--wipe", action="store_true",
                    help="قبل از ورود، کل دیتابیس پاک شود (مراقب باشید!)")
    args = ap.parse_args()

    merge_map = json.load(open(args.merge_map, encoding="utf-8")) if args.merge_map else None
    nodes, edges = load_and_aggregate(args.file, merge_map)
    print(f"نود یکتا: {len(nodes)} | رابطه یکتا: {len(edges)}")

    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
    with driver.session(database=args.database) as session:
        if args.wipe:
            session.run("MATCH (n) DETACH DELETE n")
            print("دیتابیس پاک شد.")

        # ---- constraint و index (برای هر label) ----
        labels = sorted({k[0] for k in nodes})
        for lb in labels:
            session.run(
                f"CREATE CONSTRAINT {lb.lower()}_name_unique IF NOT EXISTS "
                f"FOR (n:`{lb}`) REQUIRE n.name IS UNIQUE"
            )
        print("constraintها ساخته شد.")

        # ---- نودها (گروه‌بندی بر اساس label) ----
        by_label = defaultdict(list)
        for (lb, name), data in nodes.items():
            row = {"name": name}
            row.update(pack_sources(data["sources"]))
            by_label[lb].append(row)

        for lb, rows in by_label.items():
            query = f"""
            UNWIND $rows AS row
            MERGE (n:`{lb}` {{name: row.name}})
            SET n.source_pageids = row.source_pageids,
                n.source_titles  = row.source_titles,
                n.source_urls    = row.source_urls,
                n.source_count   = row.source_count
            """
            for batch in chunks(rows, BATCH_SIZE):
                session.run(query, rows=batch)
            print(f"  نود {lb}: {len(rows)}")

        # ---- رابطه‌ها ----
        # نام رابطه فارسی/متنوع است (~۴۵۰۰ نوع). پس همه را با نوع کلی :RELATION
        # می‌سازیم و نام واقعی را در خاصیت `type` نگه می‌داریم.
        by_pair = defaultdict(list)  # (s_label, o_label) -> rows
        for (s_lb, s_name, rel, o_lb, o_name), data in edges.items():
            row = {"s": s_name, "o": o_name, "type": rel}
            row.update(pack_sources(data["sources"]))
            by_pair[(s_lb, o_lb)].append(row)

        for (s_lb, o_lb), rows in by_pair.items():
            query = f"""
            UNWIND $rows AS row
            MATCH (a:`{s_lb}` {{name: row.s}})
            MATCH (b:`{o_lb}` {{name: row.o}})
            MERGE (a)-[r:RELATION {{type: row.type}}]->(b)
            SET r.source_pageids = row.source_pageids,
                r.source_titles  = row.source_titles,
                r.source_urls    = row.source_urls,
                r.source_count   = row.source_count
            """
            for batch in chunks(rows, BATCH_SIZE):
                session.run(query, rows=batch)
        print(f"رابطه‌ها وارد شد: {len(edges)}")

    driver.close()
    print("تمام شد ✅")


if __name__ == "__main__":
    main()
