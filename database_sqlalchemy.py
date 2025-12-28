"""
SQLAlchemy-based database operations for PostgreSQL.

This module replaces the SQLite-based database.py with PostgreSQL support.
All functions now require user_id for multi-tenancy.

Key changes from SQLite version:
- Uses SQLAlchemy ORM instead of sqlite3
- All functions require user_id parameter
- JSONB support for raw_response
- pgvector support for embeddings
- Full-text search via PostgreSQL tsvector
"""

import json
import uuid
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional, Generator

from sqlalchemy import select, func, delete, or_, text
from sqlalchemy.orm import Session, joinedload

from database_orm.models import Item, Analysis, Embedding
from database_orm.connection import get_session, init_connection

logger = logging.getLogger(__name__)


def init_db():
    """
    Initialize database connection.

    Note: Schema creation is handled by Alembic migrations.
    This function only initializes the connection.
    """
    init_connection()
    logger.info("Database connection initialized")


# Context manager compatibility with original database.py
@contextmanager
def get_db() -> Generator[Session, None, None]:
    """
    Get database session (compatibility wrapper).

    Yields:
        SQLAlchemy Session instance
    """
    with get_session() as session:
        yield session


def create_item(
    item_id: str,
    filename: str,
    original_filename: str,
    file_path: str,
    file_size: int,
    mime_type: str,
    user_id: str
) -> dict:
    """
    Create a new item in the database.

    Args:
        item_id: Unique identifier for the item
        filename: Stored filename
        original_filename: Original uploaded filename
        file_path: Path to stored file
        file_size: Size in bytes
        mime_type: MIME type
        user_id: User identifier (required for multi-tenancy)

    Returns:
        Dictionary representation of created item
    """
    with get_session() as session:
        item = Item(
            id=item_id,
            user_id=user_id,
            filename=filename,
            original_filename=original_filename,
            file_path=file_path,
            file_size=file_size,
            mime_type=mime_type
        )
        session.add(item)
        session.commit()
        session.refresh(item)

        return _item_to_dict(item)


def get_item(item_id: str, user_id: str) -> Optional[dict]:
    """
    Get an item by ID.

    Args:
        item_id: Item identifier
        user_id: User identifier (for security)

    Returns:
        Dictionary representation of item or None
    """
    with get_session() as session:
        stmt = select(Item).filter_by(id=item_id, user_id=user_id)
        item = session.scalar(stmt)
        return _item_to_dict(item) if item else None


def list_items(
    user_id: str,
    category: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> list[dict]:
    """
    List items with optional category filter.

    Args:
        user_id: User identifier
        category: Optional category filter
        limit: Maximum number of items
        offset: Offset for pagination

    Returns:
        List of item dictionaries
    """
    with get_session() as session:
        stmt = select(Item).filter_by(user_id=user_id)

        if category:
            # Join with analyses to filter by category
            stmt = (
                stmt.join(Analysis, Item.id == Analysis.item_id)
                .filter(Analysis.category == category)
                .distinct()
            )

        stmt = stmt.order_by(Item.created_at.desc()).limit(limit).offset(offset)
        items = session.scalars(stmt).all()

        return [_item_to_dict(item) for item in items]


def count_items(user_id: str, category: Optional[str] = None) -> int:
    """
    Count total items with optional category filter.

    Args:
        user_id: User identifier
        category: Optional category filter

    Returns:
        Count of items
    """
    with get_session() as session:
        if category:
            stmt = (
                select(func.count(func.distinct(Item.id)))
                .join(Analysis, Item.id == Analysis.item_id)
                .filter(Item.user_id == user_id, Analysis.category == category)
            )
        else:
            stmt = select(func.count(Item.id)).filter_by(user_id=user_id)

        return session.scalar(stmt) or 0


def delete_item(item_id: str, user_id: str) -> bool:
    """
    Delete an item (cascades to analyses and embeddings).

    Args:
        item_id: Item identifier
        user_id: User identifier (for security)

    Returns:
        True if deleted, False if not found
    """
    with get_session() as session:
        stmt = delete(Item).filter_by(id=item_id, user_id=user_id)
        result = session.execute(stmt)
        session.commit()
        return result.rowcount > 0


def create_analysis(
    analysis_id: str,
    item_id: str,
    user_id: str,
    result: dict,
    provider_used: str,
    model_used: str,
    trace_id: Optional[str] = None
) -> dict:
    """
    Create a new analysis for an item.

    Args:
        analysis_id: Unique identifier for analysis
        item_id: Item being analyzed
        user_id: User identifier
        result: Analysis result dictionary
        provider_used: AI provider name
        model_used: Model name
        trace_id: Optional tracing identifier

    Returns:
        Dictionary representation of created analysis
    """
    with get_session() as session:
        # Get next version number
        stmt = (
            select(func.max(Analysis.version))
            .filter_by(item_id=item_id, user_id=user_id)
        )
        max_version = session.scalar(stmt) or 0
        version = max_version + 1

        analysis = Analysis(
            id=analysis_id,
            item_id=item_id,
            user_id=user_id,
            version=version,
            category=result.get("category"),
            summary=result.get("summary"),
            raw_response=result,
            provider_used=provider_used,
            model_used=model_used,
            trace_id=trace_id
        )

        session.add(analysis)
        session.commit()
        session.refresh(analysis)

        return _analysis_to_dict(analysis)


def get_analysis(analysis_id: str, user_id: str) -> Optional[dict]:
    """
    Get an analysis by ID.

    Args:
        analysis_id: Analysis identifier
        user_id: User identifier (for security)

    Returns:
        Dictionary representation of analysis or None
    """
    with get_session() as session:
        stmt = select(Analysis).filter_by(id=analysis_id, user_id=user_id)
        analysis = session.scalar(stmt)
        return _analysis_to_dict(analysis) if analysis else None


def get_latest_analysis(item_id: str, user_id: str) -> Optional[dict]:
    """
    Get the latest analysis for an item.

    Args:
        item_id: Item identifier
        user_id: User identifier

    Returns:
        Dictionary representation of latest analysis or None
    """
    with get_session() as session:
        stmt = (
            select(Analysis)
            .filter_by(item_id=item_id, user_id=user_id)
            .order_by(Analysis.version.desc())
            .limit(1)
        )
        analysis = session.scalar(stmt)
        return _analysis_to_dict(analysis) if analysis else None


def get_item_analyses(item_id: str, user_id: str) -> list[dict]:
    """
    Get all analyses for an item.

    Args:
        item_id: Item identifier
        user_id: User identifier

    Returns:
        List of analysis dictionaries ordered by version (newest first)
    """
    with get_session() as session:
        stmt = (
            select(Analysis)
            .filter_by(item_id=item_id, user_id=user_id)
            .order_by(Analysis.version.desc())
        )
        analyses = session.scalars(stmt).all()
        return [_analysis_to_dict(a) for a in analyses]


def batch_get_items_with_analyses(
    item_ids: list[str],
    user_id: str
) -> dict[str, dict]:
    """
    Fetch multiple items with their latest analyses in a single optimized query.

    Args:
        item_ids: List of item IDs to fetch
        user_id: User identifier

    Returns:
        Dict mapping item_id -> combined data with 'analysis' field
    """
    if not item_ids:
        return {}

    with get_session() as session:
        # Load items with their analyses eagerly
        stmt = (
            select(Item)
            .filter(Item.id.in_(item_ids), Item.user_id == user_id)
            .options(joinedload(Item.analyses))
        )
        items = session.scalars(stmt).unique().all()

        results = {}
        for item in items:
            item_dict = _item_to_dict(item)

            # Get latest analysis
            if item.analyses:
                latest = max(item.analyses, key=lambda a: a.version)
                item_dict['analysis'] = _analysis_to_dict(latest)
            else:
                item_dict['analysis'] = None

            results[item.id] = item_dict

        return results


def search_items(
    query: str,
    user_id: str,
    top_k: int = 10,
    category_filter: Optional[str] = None,
    min_relevance_score: float = 0.0
) -> list[tuple[str, float]]:
    """
    Search items using PostgreSQL full-text search.

    Args:
        query: Search query string
        user_id: User identifier
        top_k: Maximum number of results
        category_filter: Optional category filter
        min_relevance_score: Minimum relevance score (0.0-1.0)

    Returns:
        List of (item_id, score) tuples ordered by relevance
    """
    with get_session() as session:
        # Create tsquery from search query
        tsquery = func.plainto_tsquery('english', query)

        # Build query with ts_rank for scoring
        stmt = (
            select(
                Analysis.item_id,
                func.ts_rank(Analysis.search_vector, tsquery).label('score')
            )
            .filter(
                Analysis.user_id == user_id,
                Analysis.search_vector.op('@@')(tsquery)
            )
        )

        if category_filter:
            stmt = stmt.filter(Analysis.category == category_filter)

        # Get only latest analysis per item
        subq = (
            select(
                Analysis.item_id,
                func.max(Analysis.version).label('max_version')
            )
            .filter(Analysis.user_id == user_id)
            .group_by(Analysis.item_id)
            .subquery()
        )

        stmt = (
            stmt.join(
                subq,
                (Analysis.item_id == subq.c.item_id) &
                (Analysis.version == subq.c.max_version)
            )
            .order_by(text('score DESC'))
            .limit(top_k)
        )

        results = session.execute(stmt).all()

        # Filter by minimum score
        filtered = [(r.item_id, float(r.score)) for r in results if r.score >= min_relevance_score]

        return filtered


def rebuild_search_index() -> dict:
    """
    Rebuild search index (for PostgreSQL this is a no-op).

    Search vectors are automatically maintained by triggers.

    Returns:
        Status dictionary
    """
    with get_session() as session:
        stmt = select(func.count(Analysis.id))
        count = session.scalar(stmt) or 0

        return {
            "num_documents": count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": "PostgreSQL search vectors are automatically maintained by triggers"
        }


def get_search_status() -> dict:
    """Get current search index status."""
    with get_session() as session:
        # Count analyses with search vectors
        stmt = select(func.count(Analysis.id)).filter(Analysis.search_vector.isnot(None))
        indexed_count = session.scalar(stmt) or 0

        # Count total analyses
        stmt = select(func.count(Analysis.id))
        total_analyses = session.scalar(stmt) or 0

        # Count total items
        stmt = select(func.count(Item.id))
        total_items = session.scalar(stmt) or 0

        return {
            "doc_count": indexed_count,
            "total_items": total_items,
            "items_with_analysis": total_analyses,
            "items_without_analysis": total_items - total_analyses,
            "is_loaded": indexed_count > 0,
            "index_coverage": indexed_count / total_analyses if total_analyses > 0 else 0.0
        }


def create_embedding(
    item_id: str,
    analysis_id: str,
    user_id: str,
    embedding: list[float],
    model: str,
    source_fields: dict,
    category: Optional[str] = None
) -> str:
    """
    Create embedding record and insert vector.

    Args:
        item_id: Item identifier
        analysis_id: Analysis identifier
        user_id: User identifier
        embedding: Vector embedding as list of floats
        model: Embedding model name
        source_fields: Dictionary of fields used for embedding
        category: Optional category (unused, kept for compatibility)

    Returns:
        The ID of the created embedding record
    """
    with get_session() as session:
        embedding_id = str(uuid.uuid4())

        emb = Embedding(
            id=embedding_id,
            item_id=item_id,
            analysis_id=analysis_id,
            user_id=user_id,
            vector=embedding,
            embedding_model=model,
            embedding_dimensions=len(embedding),
            embedding_source=source_fields
        )

        session.add(emb)
        session.commit()

        return embedding_id


def get_embedding(item_id: str, user_id: str) -> Optional[dict]:
    """
    Get latest embedding for an item.

    Args:
        item_id: Item identifier
        user_id: User identifier

    Returns:
        Dictionary containing embedding metadata, or None
    """
    with get_session() as session:
        stmt = (
            select(Embedding)
            .filter_by(item_id=item_id, user_id=user_id)
            .order_by(Embedding.created_at.desc())
            .limit(1)
        )
        embedding = session.scalar(stmt)
        return _embedding_to_dict(embedding) if embedding else None


def get_vector_index_status() -> dict:
    """Get statistics about the vector index."""
    with get_session() as session:
        # Count items with analyses
        stmt = select(func.count(func.distinct(Analysis.item_id)))
        total_analyzed = session.scalar(stmt) or 0

        # Count embeddings
        stmt = select(func.count(Embedding.id))
        total_embeddings = session.scalar(stmt) or 0

        return {
            "total_analyzed_items": total_analyzed,
            "total_embeddings": total_embeddings,
            "coverage": (total_embeddings / total_analyzed * 100) if total_analyzed > 0 else 0
        }


# Helper functions to convert ORM objects to dictionaries

def _item_to_dict(item: Optional[Item]) -> Optional[dict]:
    """Convert Item ORM object to dictionary."""
    if not item:
        return None

    return {
        "id": item.id,
        "user_id": item.user_id,
        "filename": item.filename,
        "original_filename": item.original_filename,
        "file_path": item.file_path,
        "file_size": item.file_size,
        "mime_type": item.mime_type,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _analysis_to_dict(analysis: Optional[Analysis]) -> Optional[dict]:
    """Convert Analysis ORM object to dictionary."""
    if not analysis:
        return None

    return {
        "id": analysis.id,
        "item_id": analysis.item_id,
        "user_id": analysis.user_id,
        "version": analysis.version,
        "category": analysis.category,
        "summary": analysis.summary,
        "raw_response": analysis.raw_response or {},
        "provider_used": analysis.provider_used,
        "model_used": analysis.model_used,
        "trace_id": analysis.trace_id,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
    }


def _embedding_to_dict(embedding: Optional[Embedding]) -> Optional[dict]:
    """Convert Embedding ORM object to dictionary."""
    if not embedding:
        return None

    return {
        "id": embedding.id,
        "item_id": embedding.item_id,
        "analysis_id": embedding.analysis_id,
        "user_id": embedding.user_id,
        "embedding_model": embedding.embedding_model,
        "embedding_dimensions": embedding.embedding_dimensions,
        "embedding_source": json.dumps(embedding.embedding_source) if embedding.embedding_source else "{}",
        "created_at": embedding.created_at.isoformat() if embedding.created_at else None,
    }


# Thread-local context compatibility (not needed for SQLAlchemy but kept for API compatibility)
@contextmanager
def database_context(db_path: str):
    """
    Compatibility wrapper for database_context.

    In SQLAlchemy version, this is a no-op since we use DATABASE_URL instead.
    """
    # This is just for API compatibility with the old database.py
    yield
