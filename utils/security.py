"""بررسی Read-Only بودن Cypher. (لایه‌ی دوم: Session با READ_ACCESS در connection)."""
from __future__ import annotations

import re

FORBIDDEN = {
    "CREATE", "MERGE", "DELETE", "DETACH", "SET", "REMOVE", "DROP", "FOREACH", "LOAD",
    "ALTER", "GRANT", "DENY", "REVOKE", "RENAME", "START", "STOP", "TERMINATE", "ENABLE",
}
# فقط این Procedureها مجازند
ALLOWED_PROCEDURES = re.compile(
    r"^(db\.(labels|relationshipTypes|propertyKeys|schema\.\w+|stats\.\w+)"
    r"|dbms\.components"
    r"|gds\.(version|graph\.list|graph\.exists|\w+(\.\w+)*\.(stream|stats|estimate)))$",
    re.IGNORECASE,
)


def _strip(query: str) -> str:
    """کامنت‌ها، رشته‌ها و `backtick`ها را حذف می‌کند تا کلمه‌ها داخل متن فارسی اشتباه تشخیص داده نشوند."""
    q = re.sub(r"/\*.*?\*/", " ", query, flags=re.S)
    q = re.sub(r"//[^\n]*", " ", q)
    q = re.sub(r"'(?:\\.|[^'\\])*'", "''", q)
    q = re.sub(r'"(?:\\.|[^"\\])*"', '""', q)
    q = re.sub(r"`[^`]*`", "``", q)
    return q


def check_read_only(query: str) -> tuple[bool, str]:
    """(مجاز بودن، دلیل) را برمی‌گرداند."""
    if not query or not query.strip():
        return False, "Query خالی است."
    q = _strip(query).strip()
    if ";" in q.rstrip(";"):
        return False, "فقط یک Statement مجاز است."
    q = q.rstrip(";")
    for word in re.findall(r"(?<![\w.$`])([A-Za-z]+)(?![\w`])", q):
        if word.upper() in FORBIDDEN:
            return False, f"دستور «{word.upper()}» در Query Console مجاز نیست (فقط Read-Only)."
    for proc in re.findall(r"\bCALL\s+([A-Za-z_][\w.]*)", q, flags=re.I):
        if not ALLOWED_PROCEDURES.match(proc):
            return False, f"Procedure «{proc}» مجاز نیست."
    return True, ""
