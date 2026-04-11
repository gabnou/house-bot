import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "shopping_list.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

VALID_CATEGORIES = {'food', 'other', 'clothing', 'health'}

CATEGORY_EMOJI = {
    'food': '🍎',
    'other': '🛍️',
    'clothing': '👕',
    'health': '💊',
}


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA_PATH.read_text())
    logger.info("✅ Database initialized.")


def add_item(name: str, category: str) -> str:
    category = category.lower()
    if category not in VALID_CATEGORIES:
        return f"❌ Invalid category: '{category}'. Use: {', '.join(sorted(VALID_CATEGORIES))}."

    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM items WHERE name = ? AND status = 'pending'",
            (name.lower(),)
        ).fetchone()

        if existing:
            return f"⚠️ '{name}' is already on the list."

        conn.execute(
            "INSERT INTO items (name, category) VALUES (?, ?)",
            (name.lower(), category)
        )
    return f"✅ '{name}' added ({category})."


def add_and_mark_bought(name: str, category: str = "other") -> str:
    """Add an item directly as 'bought' (for items bought but not on the list)."""
    category = category.lower()
    if category not in VALID_CATEGORIES:
        category = "other"
    with get_conn() as conn:
        cur = conn.execute(
            """UPDATE items SET status = 'bought', updated_at = CURRENT_TIMESTAMP
               WHERE name = ? AND status = 'pending'""",
            (name.lower(),)
        )
        if cur.rowcount > 0:
            return f"✅ '{name}' marked as bought."
        conn.execute(
            "INSERT INTO items (name, category, status) VALUES (?, ?, 'bought')",
            (name.lower(), category)
        )
    return f"✅ '{name}' added and marked as bought."


def remove_item(name: str) -> str:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM items WHERE name = ? AND status = 'pending'",
            (name.lower(),)
        )
    if cur.rowcount == 0:
        return f"⚠️ '{name}' not found on the list."
    return f"🗑️ '{name}' removed from the list."


def mark_bought(name: str) -> str:
    with get_conn() as conn:
        cur = conn.execute(
            """UPDATE items SET status = 'bought', updated_at = CURRENT_TIMESTAMP
               WHERE name = ? AND status = 'pending'""",
            (name.lower(),)
        )
    if cur.rowcount == 0:
        return f"⚠️ '{name}' not found or already marked as bought."
    return f"✅ '{name}' marked as bought."


def show_list(category: str = None) -> str:
    with get_conn() as conn:
        if category:
            rows = conn.execute(
                """SELECT name, category FROM items
                   WHERE status = 'pending' AND category = ?
                   ORDER BY name""",
                (category.lower(),)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT name, category FROM items
                   WHERE status = 'pending'
                   ORDER BY category, name"""
            ).fetchall()

    if not rows:
        if category:
            return f"🛒 No pending items in '{category}'."
        return "🛒 The list is empty!"

    groups = {}
    for r in rows:
        groups.setdefault(r["category"], []).append(r["name"])

    parts = []
    for cat in sorted(groups.keys()):
        emoji = CATEGORY_EMOJI.get(cat, '📦')
        items = "\n".join(f"  • {i}" for i in groups[cat])
        parts.append(f"{emoji} *{cat.capitalize()}:*\n{items}")

    return "\n\n".join(parts)


def recent_bought(limit: int = 10) -> str:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT name, category, updated_at FROM items
               WHERE status = 'bought'
               ORDER BY updated_at DESC
               LIMIT ?""",
            (limit,)
        ).fetchall()

    if not rows:
        return ""

    lines = ["🧾 *Recently bought:*"]
    for r in rows:
        emoji = CATEGORY_EMOJI.get(r["category"], "📦")
        lines.append(f"  {emoji} {r['name']}")
    return "\n".join(lines)


def clear_list() -> str:
    with get_conn() as conn:
        cur = conn.execute(
            """UPDATE items SET status = 'bought', updated_at = CURRENT_TIMESTAMP
               WHERE status = 'pending'"""
        )
    if cur.rowcount == 0:
        return "🛒 The list was already empty."
    return f"🧹 List cleared. {cur.rowcount} items marked as bought."


def get_pending_items() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT name FROM items WHERE status = 'pending' ORDER BY LENGTH(name) DESC"
        ).fetchall()
    return [r["name"] for r in rows]
