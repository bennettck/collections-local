# Use pysqlite3 for extension support (falls back to sqlite3 if not available)
try:
    import pysqlite3.dbapi2 as sqlite3
except ImportError:
    import sqlite3

import sqlite_vec
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

        # Note: vec_items virtual table should be created separately after sqlite-vec is loaded
        # See init_vector_table() function below


@contextmanager
def get_db():
    """Get database connection with row factory and vec extension loaded."""
    active_path = _get_active_db_path()
    conn = sqlite3.connect(active_path)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
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

        return {
            "doc_count": doc_count,
            "total_items": total_items,
            "is_loaded": doc_count > 0,
            "index_coverage": doc_count / total_items if total_items > 0 else 0.0
        }


def init_vector_table(embedding_dimensions: int = 512):
    """
    Initialize the vec_items virtual table for vector storage.

    Must be called after sqlite-vec extension is loaded.

    Args:
        embedding_dimensions: Vector dimensions (512 for voyage-3.5-lite,
                             1024 for voyage-3.5)
    """
    with get_db() as conn:
        conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_items USING vec0(
                item_id TEXT PRIMARY KEY,
                embedding float[{embedding_dimensions}] distance_metric=cosine,
                category TEXT
            )
        """)


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

        # Store vector with metadata (sqlite-vec)
        # Serialize embedding for sqlite-vec
        # Use INSERT OR REPLACE to handle cases where embedding already exists
        serialized_embedding = sqlite_vec.serialize_float32(embedding)
        conn.execute(
            "INSERT OR REPLACE INTO vec_items (item_id, embedding, category) VALUES (?, ?, ?)",
            (item_id, serialized_embedding, category)
        )

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


def vector_search_items(
    query_embedding: list[float],
    top_k: int = 10,
    category_filter: Optional[str] = None,
    min_similarity_score: float = 0.0
) -> list[tuple[str, float]]:
    """
    Search items using vector similarity.

    Uses sqlite-vec's KNN search with metadata filtering for optimal performance.
    Returns list of (item_id, similarity_score) tuples.

    Note: sqlite-vec with cosine distance returns distance values where:
    - distance = 1 - cosine_similarity
    - Lower distance = higher similarity
    - We convert to similarity score (0-1) where 1 is most similar

    Args:
        query_embedding: Query vector (must match table dimensions)
        top_k: Number of results to return
        category_filter: Optional category to filter by (uses metadata column)
        min_similarity_score: Minimum similarity threshold (0-1)

    Returns:
        List of (item_id, similarity_score) tuples sorted by similarity (descending)
    """
    with get_db() as conn:
        # Serialize query embedding for sqlite-vec
        serialized_query = sqlite_vec.serialize_float32(query_embedding)

        # Build query with metadata filtering (no JOIN needed)
        if category_filter:
            query = """
                SELECT
                    item_id,
                    distance
                FROM vec_items
                WHERE embedding MATCH ?
                  AND k = ?
                  AND category = ?
            """
            rows = conn.execute(query, (serialized_query, top_k, category_filter)).fetchall()
        else:
            query = """
                SELECT
                    item_id,
                    distance
                FROM vec_items
                WHERE embedding MATCH ?
                  AND k = ?
            """
            rows = conn.execute(query, (serialized_query, top_k)).fetchall()

        # Convert distance to similarity and filter by threshold
        # For cosine distance: similarity = 1 - distance
        results = []
        for row in rows:
            item_id = row["item_id"]
            distance = row["distance"]
            similarity = 1.0 - distance

            if similarity >= min_similarity_score:
                results.append((item_id, similarity))

    return results


def rebuild_vector_index(
    embedding_model: str = "voyage-3.5-lite",
    batch_size: int = 128
):
    """
    Rebuild the vector search index for all analyzed items.
    Generates embeddings for items that don't have them.

    Uses batch processing to minimize API calls and avoid rate limits.

    Args:
        embedding_model: VoyageAI model to use for embeddings
        batch_size: Number of documents to embed per API request (max 128)

    Returns:
        Dict with embedded_count, skipped_count, total_processed
    """
    from embeddings import generate_embeddings_batch, _create_embedding_document
    import logging

    logger = logging.getLogger(__name__)

    with get_db() as conn:
        cursor = conn.cursor()

        # Get LATEST analysis for each item that needs embeddings
        # Only one embedding per item_id since vec_items uses item_id as PRIMARY KEY
        # INNER JOIN with items to exclude orphaned analyses (where item was deleted)
        cursor.execute("""
            SELECT a.item_id, a.id as analysis_id, a.raw_response
            FROM analyses a
            INNER JOIN items i ON a.item_id = i.id
            LEFT JOIN embeddings e ON a.item_id = e.item_id
            WHERE a.raw_response IS NOT NULL
              AND e.id IS NULL
              AND a.id = (
                  SELECT id FROM analyses
                  WHERE item_id = a.item_id
                  ORDER BY version DESC
                  LIMIT 1
              )
            ORDER BY a.created_at DESC
        """)

        rows = cursor.fetchall()

    if not rows:
        logger.info("No items need embeddings")
        return {
            "embedded_count": 0,
            "skipped_count": 0,
            "total_processed": 0
        }

    # Prepare batch data
    items_to_embed = []
    skipped_count = 0
    for row in rows:
        item_id = row["item_id"]
        analysis_id = row["analysis_id"]
        raw_response = json.loads(row["raw_response"])
        category = raw_response.get("category")

        try:
            embedding_doc = _create_embedding_document(raw_response)
            # Skip empty documents
            if not embedding_doc or not embedding_doc.strip():
                logger.warning(f"Skipping {item_id}: empty embedding document")
                skipped_count += 1
                continue
            items_to_embed.append({
                "item_id": item_id,
                "analysis_id": analysis_id,
                "embedding_doc": embedding_doc,
                "category": category,
                "raw_response": raw_response
            })
        except Exception as e:
            logger.error(f"Error creating embedding document for {item_id}: {e}")
            skipped_count += 1

    if not items_to_embed:
        return {
            "embedded_count": 0,
            "skipped_count": 0,
            "total_processed": 0
        }

    # Generate embeddings in batches
    embedded_count = 0
    total_batches = (len(items_to_embed) + batch_size - 1) // batch_size

    logger.info(f"Generating embeddings for {len(items_to_embed)} items in {total_batches} batches")

    for batch_idx in range(0, len(items_to_embed), batch_size):
        batch = items_to_embed[batch_idx:batch_idx + batch_size]
        batch_docs = [item["embedding_doc"] for item in batch]

        try:
            # Generate embeddings for entire batch in one API call
            embeddings = generate_embeddings_batch(
                batch_docs,
                model=embedding_model,
                batch_size=len(batch)  # Use actual batch size
            )

            # Store all embeddings
            source_fields = {
                "weighting_strategy": "bm25_mirror",
                "fields": ["summary", "headline", "extracted_text", "category", "themes", "objects"]
            }

            for item, embedding in zip(batch, embeddings):
                try:
                    create_embedding(
                        item_id=item["item_id"],
                        analysis_id=item["analysis_id"],
                        embedding=embedding,
                        model=embedding_model,
                        source_fields=source_fields,
                        category=item["category"]
                    )
                    embedded_count += 1

                except Exception as e:
                    logger.error(f"Error storing embedding for {item['item_id']}: {e}")

            logger.info(f"Batch {batch_idx//batch_size + 1}/{total_batches}: "
                       f"Embedded {len(batch)} items ({embedded_count} total)")

        except Exception as e:
            logger.error(f"Error generating embeddings for batch {batch_idx//batch_size + 1}: {e}")

    return {
        "embedded_count": embedded_count,
        "skipped_count": skipped_count,
        "total_processed": embedded_count + skipped_count
    }


def get_vector_index_status() -> dict:
    """Get statistics about the vector index."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Count items with analyses
        cursor.execute("SELECT COUNT(DISTINCT item_id) FROM analyses")
        total_analyzed = cursor.fetchone()[0]

        # Count embeddings
        cursor.execute("SELECT COUNT(*) FROM embeddings")
        total_embeddings = cursor.fetchone()[0]

        # Count vector entries
        cursor.execute("SELECT COUNT(*) FROM vec_items")
        total_vectors = cursor.fetchone()[0]

    return {
        "total_analyzed_items": total_analyzed,
        "total_embeddings": total_embeddings,
        "total_vectors": total_vectors,
        "coverage": (total_embeddings / total_analyzed * 100) if total_analyzed > 0 else 0
    }
