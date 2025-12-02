import sqlite3
import os
import json
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

DATABASE_PATH = os.getenv("DATABASE_PATH", "./data/collections.db")


def init_db():
    """Initialize database with schema."""
    # Ensure data directory exists
    db_dir = os.path.dirname(DATABASE_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS items (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                original_filename TEXT,
                file_path TEXT NOT NULL,
                file_size INTEGER,
                mime_type TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                category TEXT,
                summary TEXT,
                raw_response TEXT,
                provider_used TEXT,
                model_used TEXT,
                trace_id TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_analyses_item_id ON analyses(item_id);
            CREATE INDEX IF NOT EXISTS idx_analyses_category ON analyses(category);
        """)

        # Migration: add provider_used column if it doesn't exist
        cursor = conn.execute("PRAGMA table_info(analyses)")
        columns = [row[1] for row in cursor.fetchall()]
        if "provider_used" not in columns:
            conn.execute("ALTER TABLE analyses ADD COLUMN provider_used TEXT")


@contextmanager
def get_db():
    """Get database connection with row factory."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def create_item(
    item_id: str,
    filename: str,
    original_filename: str,
    file_path: str,
    file_size: int,
    mime_type: str
) -> dict:
    """Create a new item in the database."""
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO items (id, filename, original_filename, file_path,
               file_size, mime_type, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (item_id, filename, original_filename, file_path, file_size, mime_type, now, now)
        )
    return get_item(item_id)


def get_item(item_id: str) -> Optional[dict]:
    """Get an item by ID."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return dict(row) if row else None


def list_items(category: str = None, limit: int = 50, offset: int = 0) -> list[dict]:
    """List items with optional category filter."""
    with get_db() as conn:
        if category:
            # Join with analyses to filter by category
            rows = conn.execute("""
                SELECT DISTINCT i.* FROM items i
                LEFT JOIN analyses a ON i.id = a.item_id
                WHERE a.category = ?
                ORDER BY i.created_at DESC
                LIMIT ? OFFSET ?
            """, (category, limit, offset)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM items ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset)
            ).fetchall()
        return [dict(row) for row in rows]


def count_items(category: str = None) -> int:
    """Count total items with optional category filter."""
    with get_db() as conn:
        if category:
            row = conn.execute("""
                SELECT COUNT(DISTINCT i.id) as count FROM items i
                LEFT JOIN analyses a ON i.id = a.item_id
                WHERE a.category = ?
            """, (category,)).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) as count FROM items").fetchone()
        return row["count"]


def delete_item(item_id: str) -> bool:
    """Delete an item (cascades to analyses)."""
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        return cursor.rowcount > 0


def create_analysis(
    analysis_id: str,
    item_id: str,
    result: dict,
    provider_used: str,
    model_used: str,
    trace_id: str = None
) -> dict:
    """Create a new analysis for an item."""
    with get_db() as conn:
        # Get next version number
        row = conn.execute(
            "SELECT MAX(version) as max_ver FROM analyses WHERE item_id = ?",
            (item_id,)
        ).fetchone()
        version = (row["max_ver"] or 0) + 1

        now = datetime.utcnow().isoformat()
        raw_response = json.dumps(result)

        conn.execute(
            """INSERT INTO analyses (id, item_id, version, category, summary,
               raw_response, provider_used, model_used, trace_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                analysis_id, item_id, version, result.get("category"),
                result.get("summary"), raw_response,
                provider_used, model_used, trace_id, now
            )
        )
    return get_analysis(analysis_id)


def get_analysis(analysis_id: str) -> Optional[dict]:
    """Get an analysis by ID."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
        if row:
            result = dict(row)
            result["raw_response"] = json.loads(result["raw_response"]) if result["raw_response"] else {}
            return result
        return None


def get_latest_analysis(item_id: str) -> Optional[dict]:
    """Get the latest analysis for an item."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM analyses WHERE item_id = ? ORDER BY version DESC LIMIT 1",
            (item_id,)
        ).fetchone()
        if row:
            result = dict(row)
            result["raw_response"] = json.loads(result["raw_response"]) if result["raw_response"] else {}
            return result
        return None


def get_item_analyses(item_id: str) -> list[dict]:
    """Get all analyses for an item."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM analyses WHERE item_id = ? ORDER BY version DESC",
            (item_id,)
        ).fetchall()
        results = []
        for row in rows:
            result = dict(row)
            result["raw_response"] = json.loads(result["raw_response"]) if result["raw_response"] else {}
            results.append(result)
        return results
