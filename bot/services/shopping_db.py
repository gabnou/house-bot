import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "db" / "shoppinglist.db"
SCHEMA_PATH = Path(__file__).parent / "db" / "shoppinglist_schema.sql"

BUILTIN_CATEGORIES = {'food', 'other', 'clothing', 'health'}

CATEGORY_EMOJI = {
    'food': '🍎',
    'other': '🛍️',
    'clothing': '👕',
    'health': '💊',
}


def get_known_categories() -> list:
    """Return all distinct categories from pending items, always including built-ins."""
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT category FROM items WHERE status = 'pending' ORDER BY category"
            ).fetchall()
        db_cats = {r["category"] for r in rows}
    except Exception:
        db_cats = set()
    return sorted(BUILTIN_CATEGORIES | db_cats)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_db():
    """Drop the hardcoded category CHECK constraint if it still exists in the live DB.

    SQLite cannot ALTER a constraint, so we recreate the table when needed.
    This runs once at startup and is a no-op if the constraint is already gone.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='items'"
        ).fetchone()
        if row and "CHECK" in (row["sql"] or "").upper():
            logger.info("Migrating DB: removing category CHECK constraint …")
            conn.executescript("""
                PRAGMA foreign_keys = OFF;
                BEGIN;
                CREATE TABLE IF NOT EXISTS items_new (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT NOT NULL,
                    category    TEXT NOT NULL,
                    status      TEXT NOT NULL DEFAULT 'pending'
                                     CHECK(status IN ('pending', 'bought')),
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO items_new SELECT id, name, category, status, created_at, updated_at FROM items;
                DROP TABLE items;
                ALTER TABLE items_new RENAME TO items;
                COMMIT;
                PRAGMA foreign_keys = ON;
            """)
            logger.info("✅ DB migration complete.")


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA_PATH.read_text())
    _migrate_db()
    logger.info("✅ Database initialized.")


def add_item(name: str, category: str) -> str:
    category = category.lower()
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


def get_pending_items_by_category(category: str) -> list:
    """Return [{id, name}] for all pending items in a given category."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name FROM items WHERE status = 'pending' AND category = ?",
            (category.lower(),)
        ).fetchall()
    return [{"id": r["id"], "name": r["name"]} for r in rows]


def get_all_pending_items_with_category() -> list:
    """Return [{id, name, category}] for all pending items."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, category FROM items WHERE status = 'pending' ORDER BY category, name"
        ).fetchall()
    return [{"id": r["id"], "name": r["name"], "category": r["category"]} for r in rows]


def update_item_category(item_id: int, new_category: str) -> None:
    """Update the category of a single item."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE items SET category = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_category.lower(), item_id)
        )
