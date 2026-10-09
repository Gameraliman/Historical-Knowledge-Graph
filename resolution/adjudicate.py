"""مرحله ۲: داوری LLM روی جفت‌های مشکوک (دسته‌ای، با کش تصمیم‌ها در data/er_cache.json)."""
from __future__ import annotations

import json
import time
from typing import Callable

from config import settings
from ingest import llm_extractor
from resolution.candidates import cache_key

PROMPT = """
تو متخصص تاریخ ایران (به‌ویژه دوره‌ی قاجار) و گراف دانش هستی. در ادامه چند «جفت موجودیت» از یک گراف دانش آمده است.
برای هر جفت تعیین کن آیا A و B یک موجودیت واقعیِ واحد هستند (فقط املا، لقب، نام کوتاه‌شده یا نگارش متفاوتِ یک نام) یا دو موجودیت متفاوت.

قواعد:
- فقط وقتی «same» بگو که با اطمینان بالا یک موجودیت‌اند. نام مشترک یعنی یک شخص نیست: پدر و پسر یا افراد هم‌نام زیادند (مثلاً چند «محمود میرزا»).
- اگر شواهد کافی نیست «unsure» بگو؛ ادغام اشتباه از ادغام‌نکردن بدتر است.
- از شواهد (صفحات منبع، روابط، همسایه‌های مشترک، حضور در یک صفحه) استفاده کن. اختلاف در روابط خانوادگی، تاریخ‌ها یا مناصب نشانه‌ی «different» است.
- canonical: اگر same بود، کدام نام برای حفظ بهتر است: "a" یا "b" (نام کامل‌تر و رایج‌تر).
- دانش بیرونی را فقط برای تشخیص نام‌های رایج به‌کار ببر، نه برای ساختن شواهد.

{pairs}

فقط و فقط خروجی را با فرمت JSON زیر برگردان:

{
  "pairs": [
    {"id": "p1", "decision": "same|different|unsure", "confidence": 0.0, "canonical": "a|b", "reason": "یک جمله‌ی کوتاه فارسی"}
  ]
}
"""

REASON_FA = {"exact_norm": "تفاوت فقط در نیم‌فاصله/ی و ک عربی/ارقام/اعراب", "paren_stripped": "تفاوت فقط در توضیح داخل پرانتز",
             "token_subset": "یک نام زیرمجموعه‌ی کلمات نام دیگر است", "fuzzy": "املای بسیار شبیه"}


def load_cache() -> dict:
    try:
        return json.loads(settings.ER_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_cache(cache: dict) -> None:
    settings.ER_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = settings.ER_CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(settings.ER_CACHE_FILE)


def node_evidence(n: dict, snap: dict, max_rel: int = 8) -> str:
    nodes = snap["nodes"]
    rels = sorted(snap["adj"].get(n["id"], []), key=lambda r: -nodes[r[0]]["sc"] if r[0] in nodes else 0)[:max_rel]
    rel_txt = "؛ ".join(f"{'→' if out else '←'} {t} «{nodes[o]['name']}»" for o, t, out in rels if o in nodes) or "—"
    titles = "، ".join(list(dict.fromkeys(n.get("titles") or []))[:3]) or "—"
    return f"«{n['name']}» [{n['type']}] — تعداد منبع: {n['sc']} — صفحه‌ها: {titles} — روابط: {rel_txt}"


def pair_block(p: dict, snap: dict) -> str:
    a, b = snap["nodes"][p["a_id"]], snap["nodes"][p["b_id"]]
    return (f"[{p['pid']}]\nA: {node_evidence(a, snap)}\nB: {node_evidence(b, snap)}\n"
            f"شواهد گراف: شباهت همسایه‌ها={p['jaccard']}؛ صفحه‌ی مشترک={p['shared_pages']}؛ دلیل پیشنهاد: {REASON_FA.get(p['reason'], p['reason'])}")


def auto_verdict(p: dict, snap: dict) -> dict:
    a = snap["nodes"][p["a_id"]]
    return {"decision": "same", "confidence": 1.0, "keep": a["name"], "reason": REASON_FA["exact_norm"], "source": "auto"}


def adjudicate_batch(pairs: list[dict], snap: dict) -> dict[str, dict]:
    """یک درخواست LLM برای چند جفت. خروجی: {pid: verdict}."""
    prompt = PROMPT.replace("{pairs}", "\n\n".join(pair_block(p, snap) for p in pairs))
    data = llm_extractor.parse_json(llm_extractor.call_model(prompt))
    by_id = {p["pid"]: p for p in pairs}
    out = {}
    for item in data.get("pairs", []):
        pid = str(item.get("id"))
        if pid not in by_id or item.get("decision") not in ("same", "different", "unsure"):
            continue
        p = by_id[pid]
        try:
            conf = max(0.0, min(1.0, float(item.get("confidence", 0))))
        except (TypeError, ValueError):
            conf = 0.0
        keep_side = p["b_id"] if str(item.get("canonical")).lower() == "b" else p["a_id"]
        out[pid] = {"decision": item["decision"], "confidence": conf, "keep": snap["nodes"][keep_side]["name"],
                    "reason": str(item.get("reason", ""))[:300], "source": "llm"}
    return out


def run_adjudication(pairs: list[dict], snap: dict, cache: dict, batch_size: int = 8, delay: float = 5,
                     on_progress: Callable[[int, int], None] | None = None) -> dict:
    """جفت‌ها را دسته‌دسته داوری می‌کند و بعد از هر دسته کش را ذخیره می‌کند (قطع شدن = از دست رفتن فقط همان دسته)."""
    stats = {"asked": 0, "answered": 0}
    batches = [pairs[i:i + batch_size] for i in range(0, len(pairs), batch_size)]
    for i, batch in enumerate(batches, 1):
        if on_progress:
            on_progress(i, len(batches))
        verdicts = adjudicate_batch(batch, snap)
        stats["asked"] += len(batch)
        for p in batch:
            v = verdicts.get(p["pid"])
            if v:
                cache[cache_key(snap["nodes"][p["a_id"]], snap["nodes"][p["b_id"]])] = v
                stats["answered"] += 1
        save_cache(cache)
        if delay and i < len(batches):
            time.sleep(delay)
    return stats
