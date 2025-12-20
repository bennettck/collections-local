import sqlite3
import os
import json
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

DATABASE_PATH = os.getenv("DATABASE_PATH", "./data/collections.db")

# Thread-local storage for database path context override
_context = threading.local()


@contextmanager
def database_context(db_path: str):
    """
    Context manager to temporarily override database path.

    This allows scripts to use a different database without modifying
    the global DATABASE_PATH variable.

    Usage:
        with database_context("/path/to/other.db"):
            item = get_item(item_id)  # Uses overridden path

    Args:
        db_path: Path to database file to use within this context
    """
    previous = getattr(_context, 'db_path', None)
    _context.db_path = db_path
    try:
        yield
    finally:
        if previous is None:
            if hasattr(_context, 'db_path'):
                delattr(_context, 'db_path')
        else:
            _context.db_path = previous


def _get_active_db_path() -> str:
    """
    Get the active database path from thread-local context or default.

    Returns:
        Database path - either from context override or global DATABASE_PATH
    """
    return getattr(_context, 'db_path', DATABASE_PATH)


def init_db():
    """Initialize database with schema."""
    # Ensure data directory exists
    active_path = _get_active_db_path()
    db_dir = os.path.dirname(active_path)
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

            CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
                item_id UNINDEXED,
                content,
                tokenize='unicode61 remove_diacritics 2'
            );
        """)

        # Migration: add provider_used column if it doesn't exist
        cursor = conn.execute("PRAGMA table_info(analyses)")
        columns = [row[1] for row in cursor.fetchall()]
        if "provider_used" not in columns:
            conn.execute("ALTER TABLE analyses ADD COLUMN provider_used TEXT")


@contextmanager
def get_db():
    """Get database connection with row factory."""
    active_path = _get_active_db_path()
    conn = sqlite3.connect(active_path)
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


def _create_search_document(raw_response: dict) -> str:
    """
    Create weighted search document from analysis data.

    Fields are repeated according to their importance for search ranking.
    All fields from raw_response are included to ensure everything is searchable.
    """
    parts = []

    # High priority fields (3x weight)
    summary = raw_response.get("summary", "")
    parts.extend([summary] * 3)

    # High priority fields (2x weight)
    headline = raw_response.get("headline", "")
    image_details = raw_response.get("image_details", {})
    extracted_text = " ".join(image_details.get("extracted_text", []))
    parts.extend([headline, extracted_text] * 2)

    # Medium-high priority (1.5x weight)
    category = raw_response.get("category", "")
    subcategories = " ".join(raw_response.get("subcategories", []))
    key_interest = image_details.get("key_interest", "")
    # Add 1.5x by repeating once, then adding 0.5 more
    parts.extend([category, subcategories, key_interest])
    parts.extend([category, subcategories, key_interest])

    # Medium priority (1x weight)
    themes = " ".join(image_details.get("themes", []))
    objects = " ".join(image_details.get("objects", []))
    media_metadata = raw_response.get("media_metadata", {})
    location_tags = " ".join(media_metadata.get("location_tags", []))
    parts.extend([themes, objects, location_tags])

    # Low priority (0.5x weight)
    emotions = " ".join(image_details.get("emotions", []))
    vibes = " ".join(image_details.get("vibes", []))
    hashtags = " ".join(media_metadata.get("hashtags", []))
    parts.extend([emotions, vibes, hashtags])

    # Minimal priority (0.3x weight) - add once
    original_poster = media_metadata.get("original_poster", "")
    tagged_accounts = " ".join(media_metadata.get("tagged_accounts", []))
    audio_source = media_metadata.get("audio_source", "")
    likely_source = image_details.get("likely_source", "")
    visual_hierarchy = " ".join(image_details.get("visual_hierarchy", []))
    minimal_fields = f"{original_poster} {tagged_accounts} {audio_source} {likely_source} {visual_hierarchy}"
    parts.append(minimal_fields)

    # Join all parts, filtering out empty strings
    return " ".join([p for p in parts if p and p.strip()])


def rebuild_search_index() -> dict:
    """
    Rebuild FTS5 search index from current analyses.

    Returns dict with rebuild statistics.
    """
    with get_db() as conn:
        # Clear existing FTS data
        conn.execute("DELETE FROM items_fts")

        # Get all items with their latest analysis
        rows = conn.execute("""
            SELECT
                i.id as item_id,
                a.raw_response
            FROM items i
            LEFT JOIN analyses a ON i.id = a.item_id
            WHERE a.id = (
                SELECT id FROM analyses
                WHERE item_id = i.id
                ORDER BY version DESC
                LIMIT 1
            )
        """).fetchall()

        # Insert into FTS table
        indexed_count = 0
        for row in rows:
            item_id = row["item_id"]
            raw_response = json.loads(row["raw_response"]) if row["raw_response"] else {}

            if raw_response:
                search_doc = _create_search_document(raw_response)
                conn.execute(
                    "INSERT INTO items_fts(item_id, content) VALUES (?, ?)",
                    (item_id, search_doc)
                )
                indexed_count += 1

        return {
            "num_documents": indexed_count,
            "timestamp": datetime.utcnow().isoformat()
        }


def _preprocess_query(query: str) -> str:
    """
    Preprocess search query by removing punctuation and normalizing.

    Args:
        query: Raw search query

    Returns:
        Preprocessed query suitable for FTS5 with OR logic
    """
    import re

    # Remove punctuation (question marks, exclamation points, etc.)
    query = re.sub(r'[?!.,;:\'"()\[\]{}]', ' ', query)

    # Split into tokens and join with OR for better recall
    tokens = query.lower().split()

    # If empty or single token, return as-is
    if len(tokens) <= 1:
        return query.lower()

    # Join tokens with OR operator for FTS5
    return " OR ".join(tokens)


def search_items(query: str, top_k: int = 10, category_filter: Optional[str] = None, min_relevance_score: float = -1.0) -> list[tuple[str, float]]:
    """
    Search items using FTS5 BM25 ranking.

    Args:
        query: Search query string (will be preprocessed to remove stopwords)
        top_k: Maximum number of results to return
        category_filter: Optional category to filter results
        min_relevance_score: Minimum BM25 score threshold. Results with scores > this value
                           will be filtered out. Default -1.0 effectively disables filtering.
                           (Note: BM25 scores are negative; more negative = better match)

    Returns:
        List of (item_id, bm25_score) tuples, ordered by relevance
    """
    # Preprocess query to remove stopwords
    processed_query = _preprocess_query(query)

    with get_db() as conn:
        if category_filter:
            # Join with analyses table to filter by category
            rows = conn.execute("""
                SELECT
                    f.item_id,
                    bm25(items_fts) as score
                FROM items_fts f
                JOIN analyses a ON f.item_id = a.item_id
                WHERE items_fts MATCH ?
                AND a.category = ?
                AND a.id = (
                    SELECT id FROM analyses
                    WHERE item_id = f.item_id
                    ORDER BY version DESC
                    LIMIT 1
                )
                ORDER BY score
                LIMIT ?
            """, (processed_query, category_filter, top_k)).fetchall()
        else:
            # Simple search without category filter
            rows = conn.execute("""
                SELECT
                    item_id,
                    bm25(items_fts) as score
                FROM items_fts
                WHERE items_fts MATCH ?
                ORDER BY score
                LIMIT ?
            """, (processed_query, top_k)).fetchall()

        results = [(row["item_id"], row["score"]) for row in rows]

        # If no results or best match is weak, return empty list
        if not results or results[0][1] > min_relevance_score:
            return []

        # Filter out weak tail results
        return [r for r in results if r[1] < min_relevance_score]


def get_search_status() -> dict:
    """Get current search index status."""
    with get_db() as conn:
        # Count documents in FTS table
        row = conn.execute("SELECT COUNT(*) as count FROM items_fts").fetchone()
        doc_count = row["count"] if row else 0

        # Get total items for comparison
        total_items = conn.execute("SELECT COUNT(*) as count FROM items").fetchone()["count"]

        return {
            "doc_count": doc_count,
            "total_items": total_items,
            "is_loaded": doc_count > 0,
            "index_coverage": doc_count / total_items if total_items > 0 else 0.0
        }
