"""
DEPRECATED: Legacy SQLite database implementation.

This module is deprecated and maintained only for local development compatibility.
For production use, see database_sqlalchemy.py which provides:
- PostgreSQL support via SQLAlchemy
- Multi-tenancy via user_id parameter
- Better connection pooling
- JSONB support for analysis data

This file will be removed in a future version.
"""

import warnings
warnings.warn(
    "database_sqlite_legacy is deprecated. Use database_sqlalchemy for new code. "
    "This module is only for local development without PostgreSQL.",
    DeprecationWarning,
    stacklevel=2
)

import sqlite3
import os
import json
import uuid
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
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


def _parse_json_field(value):
    """
    Parse a JSON field that might be a string (SQLite) or already parsed (PostgreSQL).

    Args:
        value: JSON field value from database

    Returns:
        Parsed dictionary or empty dict if None/empty
    """
    if not value:
        return {}
    if isinstance(value, dict):
        # Already parsed (PostgreSQL with RealDictCursor)
        return value
    if isinstance(value, str):
        # String that needs parsing (SQLite)
        return json.loads(value)
    # Fallback for unexpected types
    return {}


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

        # Embeddings table for vector search metadata
        conn.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                analysis_id TEXT NOT NULL,
                embedding_model TEXT NOT NULL,
                embedding_dimensions INTEGER NOT NULL,
                embedding_source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
                FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
            )
        """)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_item_id ON embeddings(item_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_analysis_id ON embeddings(analysis_id)")



class DatabaseConnectionWrapper:
    """Wrapper that adapts SQL queries for SQLite or PostgreSQL."""

    def __init__(self, conn, use_postgres=False):
        self._conn = conn
        self._use_postgres = use_postgres
        # For PostgreSQL, create a cursor that will be reused
        self._cursor = conn.cursor() if use_postgres else None

    def execute(self, query, params=None):
        """Execute query with parameter adaptation."""
        if self._use_postgres:
            # PostgreSQL: use cursor with %s parameters
            adapted_query = query.replace('?', '%s') if params else query
            if params:
                self._cursor.execute(adapted_query, params)
            else:
                self._cursor.execute(adapted_query)
            return self._cursor
        else:
            # SQLite: use connection directly with ? parameters
            if params:
                return self._conn.execute(query, params)
            else:
                return self._conn.execute(query)

    def executescript(self, script):
        """Execute SQL script (SQLite only)."""
        if self._use_postgres:
            # For PostgreSQL, execute as a single statement
            self._cursor.execute(script)
            return self._cursor
        else:
            return self._conn.executescript(script)

    def commit(self):
        return self._conn.commit()

    def close(self):
        if self._cursor:
            self._cursor.close()
        return self._conn.close()

    def __getattr__(self, name):
        """Delegate other methods to underlying connection."""
        return getattr(self._conn, name)


@contextmanager
def get_db():
    """Get database connection with row factory."""
    # Check if we should use PostgreSQL (AWS Lambda with Secrets Manager)
    if os.getenv("DB_SECRET_ARN"):
        # PostgreSQL via AWS Secrets Manager
        import psycopg2
        import psycopg2.extras
        from utils.aws_secrets import get_database_credentials

        creds = get_database_credentials()
        conn = psycopg2.connect(
            host=creds['host'],
            port=creds['port'],
            database=creds.get('dbname', 'collections'),
            user=creds['username'],
            password=creds['password'],
            sslmode='require',
            cursor_factory=psycopg2.extras.RealDictCursor
        )

        try:
            wrapped = DatabaseConnectionWrapper(conn, use_postgres=True)
            yield wrapped
            conn.commit()
        finally:
            conn.close()
    else:
        # SQLite for local development
        active_path = _get_active_db_path()
        conn = sqlite3.connect(active_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            wrapped = DatabaseConnectionWrapper(conn, use_postgres=False)
            yield wrapped
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
            result["raw_response"] = _parse_json_field(result["raw_response"])
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
            result["raw_response"] = _parse_json_field(result["raw_response"])
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
            result["raw_response"] = _parse_json_field(result["raw_response"])
            results.append(result)
        return results


def batch_get_items_with_analyses(item_ids: list[str]) -> dict[str, dict]:
    """
    Fetch multiple items with their latest analyses in a single optimized query.

    This replaces the inefficient pattern of calling get_item() and get_latest_analysis()
    separately for each item (2N queries) with a single JOIN query.

    Args:
        item_ids: List of item IDs to fetch

    Returns:
        Dict mapping item_id -> combined data with keys:
            - All fields from items table (id, filename, file_path, etc.)
            - 'analysis' field containing the latest analysis data with parsed raw_response

    Example:
        data = batch_get_items_with_analyses(['item1', 'item2'])
        item_data = data['item1']
        filename = item_data['filename']
        category = item_data['analysis']['raw_response']['category']
    """
    if not item_ids:
        return {}

    with get_db() as conn:
        # Use a subquery to get the latest analysis version for each item
        # Then JOIN with items and analyses to get all data in one query
        placeholders = ','.join(['?'] * len(item_ids))

        query = f"""
            SELECT
                i.*,
                a.id as analysis_id,
                a.version,
                a.category,
                a.summary,
                a.raw_response,
                a.provider_used,
                a.model_used,
                a.trace_id,
                a.created_at as analysis_created_at
            FROM items i
            LEFT JOIN (
                SELECT a1.*
                FROM analyses a1
                INNER JOIN (
                    SELECT item_id, MAX(version) as max_version
                    FROM analyses
                    WHERE item_id IN ({placeholders})
                    GROUP BY item_id
                ) a2 ON a1.item_id = a2.item_id AND a1.version = a2.max_version
            ) a ON i.id = a.item_id
            WHERE i.id IN ({placeholders})
        """

        # Execute with item_ids repeated twice (once for each IN clause)
        rows = conn.execute(query, item_ids + item_ids).fetchall()

        results = {}
        for row in rows:
            row_dict = dict(row)
            item_id = row_dict['id']

            # Split into item data and analysis data
            item_data = {
                'id': row_dict['id'],
                'filename': row_dict['filename'],
                'original_filename': row_dict.get('original_filename'),
                'file_path': row_dict['file_path'],
                'file_size': row_dict.get('file_size'),
                'mime_type': row_dict.get('mime_type'),
                'created_at': row_dict['created_at'],
                'updated_at': row_dict['updated_at']
            }

            # Parse and attach analysis data if it exists
            if row_dict.get('analysis_id'):
                analysis_data = {
                    'id': row_dict['analysis_id'],
                    'item_id': item_id,
                    'version': row_dict['version'],
                    'category': row_dict['category'],
                    'summary': row_dict['summary'],
                    'raw_response': json.loads(row_dict['raw_response']) if row_dict['raw_response'] else {},
                    'provider_used': row_dict.get('provider_used'),
                    'model_used': row_dict.get('model_used'),
                    'trace_id': row_dict.get('trace_id'),
                    'created_at': row_dict.get('analysis_created_at')
                }
                item_data['analysis'] = analysis_data
            else:
                item_data['analysis'] = None

            results[item_id] = item_data

        return results


def _create_search_document(raw_response: dict) -> str:
    """
    Create flat search document from analysis data (no field weighting).

    This method concatenates all fields ONCE (no repetition).
    Modern embedding models handle field importance implicitly.
    """
    parts = []

    # Extract all fields once (no weighting/repetition)
    parts.append(raw_response.get("summary", ""))
    parts.append(raw_response.get("headline", ""))
    parts.append(raw_response.get("category", ""))
    parts.append(" ".join(raw_response.get("subcategories", [])))

    # Image details
    image_details = raw_response.get("image_details", {})
    if isinstance(image_details.get("extracted_text"), list):
        parts.append(" ".join(image_details.get("extracted_text", [])))
    else:
        parts.append(image_details.get("extracted_text", ""))

    parts.append(image_details.get("key_interest", ""))
    parts.append(" ".join(image_details.get("themes", [])))
    parts.append(" ".join(image_details.get("objects", [])))
    parts.append(" ".join(image_details.get("emotions", [])))
    parts.append(" ".join(image_details.get("vibes", [])))

    # Media metadata
    media_metadata = raw_response.get("media_metadata", {})
    parts.append(" ".join(media_metadata.get("location_tags", [])))
    parts.append(" ".join(media_metadata.get("hashtags", [])))

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

    # Filter out empty tokens and very short tokens (< 2 chars) that might cause FTS5 issues
    tokens = [t for t in tokens if len(t) >= 2]

    # If empty, return empty string
    if not tokens:
        return ""

    # If single token, return quoted
    if len(tokens) == 1:
        return f'"{tokens[0]}"'

    # Join tokens with OR operator for FTS5, quote each token to prevent syntax errors
    return " OR ".join(f'"{token}"' for token in tokens)


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

        # Count items with analysis (these are indexable)
        items_with_analysis = conn.execute("""
            SELECT COUNT(DISTINCT i.id) as count
            FROM items i
            INNER JOIN analyses a ON i.id = a.item_id
        """).fetchone()["count"]

        return {
            "doc_count": doc_count,
            "total_items": total_items,
            "items_with_analysis": items_with_analysis,
            "items_without_analysis": total_items - items_with_analysis,
            "is_loaded": doc_count > 0,
            "index_coverage": doc_count / items_with_analysis if items_with_analysis > 0 else 0.0
        }


def create_embedding(
    item_id: str,
    analysis_id: str,
    embedding: list[float],
    model: str,
    source_fields: dict,
    category: Optional[str] = None
) -> str:
    """
    Create embedding record and insert into vector table.

    Args:
        item_id: ID of the item being embedded
        analysis_id: ID of the analysis used to create the embedding
        embedding: Vector embedding as list of floats
        model: Name of the embedding model used
        source_fields: Dictionary of fields used to create the embedding
        category: Optional category for metadata filtering

    Returns:
        The ID of the created embedding record
    """
    with get_db() as conn:
        embedding_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Store metadata
        conn.execute("""
            INSERT INTO embeddings (
                id, item_id, analysis_id, embedding_model,
                embedding_dimensions, embedding_source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            embedding_id,
            item_id,
            analysis_id,
            model,
            len(embedding),
            json.dumps(source_fields),
            now
        ))

    return embedding_id


def get_embedding(item_id: str) -> Optional[dict]:
    """
    Get latest embedding for an item.

    Args:
        item_id: ID of the item

    Returns:
        Dictionary containing embedding metadata, or None if no embedding exists
    """
    with get_db() as conn:
        row = conn.execute("""
            SELECT * FROM embeddings
            WHERE item_id = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (item_id,)).fetchone()

        if row:
            return dict(row)
        return None


def get_vector_index_status() -> dict:
    """Get statistics about the vector index (embeddings metadata only)."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Count items with analyses
        cursor.execute("SELECT COUNT(DISTINCT item_id) FROM analyses")
        total_analyzed = cursor.fetchone()[0]

        # Count embeddings
        cursor.execute("SELECT COUNT(*) FROM embeddings")
        total_embeddings = cursor.fetchone()[0]

    return {
        "total_analyzed_items": total_analyzed,
        "total_embeddings": total_embeddings,
        "coverage": (total_embeddings / total_analyzed * 100) if total_analyzed > 0 else 0
    }
