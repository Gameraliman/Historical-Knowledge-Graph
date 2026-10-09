"""
Operation 3 - Topic Processing Hook

این فایل عمداً به صورت اسکلت قرار داده شده است.
بعداً منطق واقعی Operation3 پروژه خودت را در تابع run_operation3 قرار بده.

ورودی:
    topic -> موضوعی که در categories.json ثبت شده است.

خروجی پیشنهادی:
    در صورت موفقیت True و در صورت خطا False/Exception.

نکته:
    فعلاً هیچ پردازش واقعی انجام نمی‌شود تا منطق اصلی خودت را اینجا قرار بدهی.
"""

from __future__ import annotations

import sys


def run_operation3(topic: str) -> None:
    # ================================================================
    # TODO: منطق واقعی Operation3 را اینجا قرار بده.
    #
    # نمونه ساختار آینده:
    #
    # 1) دریافت topic
    # 2) اجرای pipeline مربوط به استخراج/پردازش داده
    # 3) ذخیره خروجی در محل موردنظر
    # 4) در صورت نیاز به‌روزرسانی Neo4j
    #
    # مثال:
    # process_topic(topic)
    # update_neo4j(topic)
    # ================================================================

    print(f"[Operation3 placeholder] topic={topic}")


def main() -> None:
    if len(sys.argv) < 2:
        print("Operation3: topic was not provided.", file=sys.stderr)
        raise SystemExit(1)

    topic = sys.argv[1].strip()
    if not topic:
        print("Operation3: topic is empty.", file=sys.stderr)
        raise SystemExit(1)

    run_operation3(topic)


if __name__ == "__main__":
    main()
