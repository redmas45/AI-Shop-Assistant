"""
SQLite database connection helpers.
Uses WAL mode for concurrent reads from multiple threads.
"""
import sqlite3
import threading
from pathlib import Path
from contextlib import contextmanager
from typing import Generator

import config

# Thread-local storage for connections
_local = threading.local()


def _get_connection() -> sqlite3.Connection:
    """Return a thread-local SQLite connection, creating one if needed."""
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(
            str(config.DB_PATH),
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn = conn
    return _local.conn


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Context manager that yields a DB connection and commits/rolls back."""
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db() -> None:
    """Create tables from schema.sql if they don't exist."""
    schema_path = Path(__file__).parent / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")
    with get_db() as conn:
        conn.executescript(schema_sql)


def get_all_products(limit: int = 10000, offset: int = 0) -> list[dict]:
    """Return an even mix of active products across categories."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT p.*, c.name AS category_name, c.slug AS category_slug
            FROM (
                SELECT *,
                       ROW_NUMBER() OVER(PARTITION BY category_id ORDER BY RANDOM()) as rn
                FROM products
                WHERE is_active = 1
            ) p
            JOIN categories c ON p.category_id = c.id
            WHERE p.rn <= 1000
            ORDER BY RANDOM()
            LIMIT ? OFFSET ?
            """,
            (limit, offset)
        ).fetchall()
    return [dict(row) for row in rows]


def get_products_by_ids(ids: list[int]) -> list[dict]:
    """Return products matching given IDs."""
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT p.*, c.name AS category_name, c.slug AS category_slug
            FROM products p
            JOIN categories c ON p.category_id = c.id
            WHERE p.id IN ({placeholders}) AND p.is_active = 1
            """,
            ids,
        ).fetchall()
    return [dict(row) for row in rows]


def get_products_by_category(category_name: str, limit: int = 50) -> list[dict]:
    """Return active products matching the given category name."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT p.*, c.name AS category_name, c.slug AS category_slug
            FROM products p
            JOIN categories c ON p.category_id = c.id
            WHERE (c.name = ? OR p.tags LIKE ?) AND p.is_active = 1
            LIMIT ?
            """,
            (category_name, f'%"{category_name}"%', limit),
        ).fetchall()
    return [dict(row) for row in rows]



def product_exists(product_id: int) -> bool:
    """Check whether a product ID exists and is active."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM products WHERE id = ? AND is_active = 1", (product_id,)
        ).fetchone()
    return row is not None


# ── Cart Helpers ──────────────────────────────────────────────────────────────

def get_cart_items() -> list[dict]:
    """Return all items in the cart with product details."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT c.id as cart_id, c.quantity, CAST(c.added_at AS TEXT) as added_at, p.*, cat.name AS category_name, cat.slug AS category_slug
            FROM cart c
            JOIN products p ON c.product_id = p.id
            JOIN categories cat ON p.category_id = cat.id
            ORDER BY c.added_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def add_to_cart(product_id: int, quantity: int = 1) -> int:
    """Add a product to the cart or increment quantity if it exists."""
    with get_db() as conn:
        # Check if already in cart
        row = conn.execute("SELECT id, quantity FROM cart WHERE product_id = ?", (product_id,)).fetchone()
        if row:
            new_qty = row["quantity"] + quantity
            conn.execute("UPDATE cart SET quantity = ? WHERE id = ?", (new_qty, row["id"]))
            return row["id"]
        else:
            cursor = conn.execute(
                "INSERT INTO cart (product_id, quantity) VALUES (?, ?)",
                (product_id, quantity)
            )
            return cursor.lastrowid


def update_cart_quantity(product_id: int, quantity: int) -> bool:
    """Update quantity of a specific product in the cart. If <= 0, remove it."""
    with get_db() as conn:
        row = conn.execute("SELECT id FROM cart WHERE product_id = ?", (product_id,)).fetchone()
        if not row:
            return False
            
        if quantity <= 0:
            cursor = conn.execute("DELETE FROM cart WHERE id = ?", (row["id"],))
        else:
            cursor = conn.execute("UPDATE cart SET quantity = ? WHERE id = ?", (quantity, row["id"]))
            
        return cursor.rowcount > 0
def remove_from_cart(cart_id: int) -> bool:
    """Remove a specific item from the cart."""
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM cart WHERE id = ?", (cart_id,))
        return cursor.rowcount > 0


def clear_cart() -> None:
    """Empty the cart."""
    with get_db() as conn:
        conn.execute("DELETE FROM cart")

# ── User Profile Helpers ──────────────────────────────────────────────────────

def get_user_profile() -> dict:
    """Return the current user profile (address, payment_method)."""
    with get_db() as conn:
        row = conn.execute("SELECT address, payment_method FROM user_profile WHERE id = 1").fetchone()
        if row:
            return dict(row)
        return {"address": None, "payment_method": None}

def update_user_profile(address: str, payment_method: str) -> None:
    """Update or insert the user profile."""
    with get_db() as conn:
        row = conn.execute("SELECT id FROM user_profile WHERE id = 1").fetchone()
        if row:
            conn.execute(
                "UPDATE user_profile SET address = ?, payment_method = ? WHERE id = 1",
                (address, payment_method)
            )
        else:
            conn.execute(
                "INSERT INTO user_profile (id, address, payment_method) VALUES (1, ?, ?)",
                (address, payment_method)
            )
