"""
Database API wrapper that routes to SQLite or PostgreSQL backend.

This module provides a unified interface that works with both:
- database.py (SQLite, no user_id)
- database_sqlalchemy.py (PostgreSQL, requires user_id)

The backend is selected based on environment variables:
- If DB_SECRET_ARN or DATABASE_URL (postgresql) is set -> PostgreSQL
- Otherwise -> SQLite

For PostgreSQL, user_id is required. For SQLite, user_id is ignored.
"""

import os
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# Determine which database backend to use
_use_postgres = bool(
    os.getenv("DB_SECRET_ARN") or
    os.getenv("DATABASE_URL", "").startswith("postgresql")
)

if _use_postgres:
    # PostgreSQL backend (requires user_id)
    logger.info("Using PostgreSQL backend (database_sqlalchemy)")
    from database_sqlalchemy import (
        init_db as _init_db,
        create_item as _create_item,
        get_item as _get_item,
        list_items as _list_items,
        count_items as _count_items,
        delete_item as _delete_item,
        create_analysis as _create_analysis,
        get_analysis as _get_analysis,
        get_latest_analysis as _get_latest_analysis,
        get_item_analyses as _get_item_analyses,
        search_items as _search_items,
        create_embedding as _create_embedding,
        get_embedding as _get_embedding,
    )
else:
    # SQLite backend (no user_id)
    logger.info("Using SQLite backend (database_sqlite_legacy)")
    from database_sqlite_legacy import (
        init_db as _init_db,
        create_item as _create_item,
        get_item as _get_item,
        list_items as _list_items,
        count_items as _count_items,
        delete_item as _delete_item,
        create_analysis as _create_analysis,
        get_analysis as _get_analysis,
        get_latest_analysis as _get_latest_analysis,
        get_item_analyses as _get_item_analyses,
        search_items as _search_items,
        create_embedding as _create_embedding,
        get_embedding as _get_embedding,
        rebuild_search_index as _rebuild_search_index,
        get_search_status as _get_search_status,
        get_vector_index_status as _get_vector_index_status,
        get_db as _get_db,
        _create_search_document as __create_search_document,
    )


def use_postgres() -> bool:
    """Check if PostgreSQL backend is active."""
    return _use_postgres


def init_db():
    """Initialize database."""
    return _init_db()


def create_item(
    item_id: str,
    filename: str,
    original_filename: str,
    file_path: str,
    file_size: int,
    mime_type: str,
    user_id: Optional[str] = None
) -> dict:
    """
    Create a new item.

    Args:
        item_id: Unique identifier
        filename: Stored filename
        original_filename: Original uploaded filename
        file_path: Path to stored file
        file_size: Size in bytes
        mime_type: MIME type
        user_id: User identifier (required for PostgreSQL, ignored for SQLite)

    Returns:
        Dictionary representation of created item
    """
    if _use_postgres:
        if not user_id:
            raise ValueError("user_id is required when using PostgreSQL backend")
        return _create_item(
            item_id=item_id,
            filename=filename,
            original_filename=original_filename,
            file_path=file_path,
            file_size=file_size,
            mime_type=mime_type,
            user_id=user_id
        )
    else:
        return _create_item(
            item_id=item_id,
            filename=filename,
            original_filename=original_filename,
            file_path=file_path,
            file_size=file_size,
            mime_type=mime_type
        )


def get_item(item_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    """
    Get an item by ID.

    Args:
        item_id: Item identifier
        user_id: User identifier (required for PostgreSQL, ignored for SQLite)

    Returns:
        Dictionary representation of item or None
    """
    if _use_postgres:
        if not user_id:
            raise ValueError("user_id is required when using PostgreSQL backend")
        return _get_item(item_id=item_id, user_id=user_id)
    else:
        return _get_item(item_id=item_id)


def list_items(
    category: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user_id: Optional[str] = None
) -> list[dict]:
    """
    List items with optional filtering.

    Args:
        category: Optional category filter
        limit: Maximum number of items
        offset: Offset for pagination
        user_id: User identifier (required for PostgreSQL, ignored for SQLite)

    Returns:
        List of item dictionaries
    """
    if _use_postgres:
        if not user_id:
            raise ValueError("user_id is required when using PostgreSQL backend")
        return _list_items(
            user_id=user_id,
            category=category,
            limit=limit,
            offset=offset
        )
    else:
        return _list_items(
            category=category,
            limit=limit,
            offset=offset
        )


def count_items(category: Optional[str] = None, user_id: Optional[str] = None) -> int:
    """
    Count total items with optional category filter.

    Args:
        category: Optional category filter
        user_id: User identifier (required for PostgreSQL, ignored for SQLite)

    Returns:
        Count of items
    """
    if _use_postgres:
        if not user_id:
            raise ValueError("user_id is required when using PostgreSQL backend")
        return _count_items(user_id=user_id, category=category)
    else:
        return _count_items(category=category)


def delete_item(item_id: str, user_id: Optional[str] = None) -> bool:
    """
    Delete an item.

    Args:
        item_id: Item identifier
        user_id: User identifier (required for PostgreSQL, ignored for SQLite)

    Returns:
        True if deleted, False if not found (SQLite returns None)
    """
    if _use_postgres:
        if not user_id:
            raise ValueError("user_id is required when using PostgreSQL backend")
        return _delete_item(item_id=item_id, user_id=user_id)
    else:
        _delete_item(item_id=item_id)
        return True  # SQLite version doesn't return a value


def create_analysis(
    analysis_id: str,
    item_id: str,
    result: dict,
    provider_used: str,
    model_used: str,
    trace_id: Optional[str] = None,
    user_id: Optional[str] = None
) -> dict:
    """
    Create a new analysis for an item.

    Args:
        analysis_id: Unique identifier for analysis
        item_id: Item being analyzed
        result: Analysis result dictionary
        provider_used: AI provider name
        model_used: Model name
        trace_id: Optional tracing identifier
        user_id: User identifier (required for PostgreSQL, ignored for SQLite)

    Returns:
        Dictionary representation of created analysis
    """
    if _use_postgres:
        if not user_id:
            raise ValueError("user_id is required when using PostgreSQL backend")
        return _create_analysis(
            analysis_id=analysis_id,
            item_id=item_id,
            user_id=user_id,
            result=result,
            provider_used=provider_used,
            model_used=model_used,
            trace_id=trace_id
        )
    else:
        return _create_analysis(
            analysis_id=analysis_id,
            item_id=item_id,
            result=result,
            provider_used=provider_used,
            model_used=model_used,
            trace_id=trace_id
        )


def get_analysis(analysis_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    """
    Get an analysis by ID.

    Args:
        analysis_id: Analysis identifier
        user_id: User identifier (required for PostgreSQL, ignored for SQLite)

    Returns:
        Dictionary representation of analysis or None
    """
    if _use_postgres:
        if not user_id:
            raise ValueError("user_id is required when using PostgreSQL backend")
        return _get_analysis(analysis_id=analysis_id, user_id=user_id)
    else:
        return _get_analysis(analysis_id=analysis_id)


def get_latest_analysis(item_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    """
    Get the latest analysis for an item.

    Args:
        item_id: Item identifier
        user_id: User identifier (required for PostgreSQL, ignored for SQLite)

    Returns:
        Dictionary representation of latest analysis or None
    """
    if _use_postgres:
        if not user_id:
            raise ValueError("user_id is required when using PostgreSQL backend")
        return _get_latest_analysis(item_id=item_id, user_id=user_id)
    else:
        return _get_latest_analysis(item_id=item_id)


def get_item_analyses(item_id: str, user_id: Optional[str] = None) -> list[dict]:
    """
    Get all analyses for an item.

    Args:
        item_id: Item identifier
        user_id: User identifier (required for PostgreSQL, ignored for SQLite)

    Returns:
        List of analysis dictionaries ordered by version (newest first)
    """
    if _use_postgres:
        if not user_id:
            raise ValueError("user_id is required when using PostgreSQL backend")
        return _get_item_analyses(item_id=item_id, user_id=user_id)
    else:
        return _get_item_analyses(item_id=item_id)


def search_items(
    query: str,
    limit: int = 10,
    category: Optional[str] = None,
    user_id: Optional[str] = None
) -> list[tuple]:
    """
    Search items using full-text search.

    Args:
        query: Search query string
        limit: Maximum number of results
        category: Optional category filter
        user_id: User identifier (required for PostgreSQL, ignored for SQLite)

    Returns:
        List of (item_id, score) tuples
    """
    if _use_postgres:
        if not user_id:
            raise ValueError("user_id is required when using PostgreSQL backend")
        return _search_items(
            user_id=user_id,
            query=query,
            limit=limit,
            category=category
        )
    else:
        return _search_items(
            query=query,
            limit=limit,
            category=category
        )


def create_embedding(
    item_id: str,
    analysis_id: str,
    embedding: list,
    model: str,
    source_fields: dict,
    category: Optional[str] = None,
    user_id: Optional[str] = None
) -> dict:
    """
    Store an embedding.

    Args:
        item_id: Item identifier
        analysis_id: Analysis identifier
        embedding: Vector embedding as list of floats
        model: Embedding model name
        source_fields: Dictionary of fields used for embedding
        category: Optional category
        user_id: User identifier (required for PostgreSQL, ignored for SQLite)

    Returns:
        Dictionary representation of created embedding
    """
    if _use_postgres:
        if not user_id:
            raise ValueError("user_id is required when using PostgreSQL backend")
        # TODO: Implement create_embedding in database_sqlalchemy.py
        raise NotImplementedError("create_embedding not yet implemented for PostgreSQL")
    else:
        return _create_embedding(
            item_id=item_id,
            analysis_id=analysis_id,
            embedding=embedding,
            model=model,
            source_fields=source_fields,
            category=category
        )


def get_embedding(item_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    """
    Get embedding for an item.

    Args:
        item_id: Item identifier
        user_id: User identifier (required for PostgreSQL, ignored for SQLite)

    Returns:
        Dictionary containing embedding metadata, or None
    """
    if _use_postgres:
        if not user_id:
            raise ValueError("user_id is required when using PostgreSQL backend")
        # TODO: Implement get_embedding in database_sqlalchemy.py
        raise NotImplementedError("get_embedding not yet implemented for PostgreSQL")
    else:
        return _get_embedding(item_id=item_id)


# SQLite-only functions (not available in PostgreSQL yet)

def rebuild_search_index() -> dict:
    """
    Rebuild the FTS5 search index (SQLite only).

    Returns:
        Dictionary with rebuild statistics

    Raises:
        NotImplementedError: If PostgreSQL backend is active
    """
    if _use_postgres:
        raise NotImplementedError("rebuild_search_index not available for PostgreSQL")
    return _rebuild_search_index()


def get_search_status() -> dict:
    """
    Get search index status (SQLite only).

    Returns:
        Dictionary with search index statistics

    Raises:
        NotImplementedError: If PostgreSQL backend is active
    """
    if _use_postgres:
        raise NotImplementedError("get_search_status not available for PostgreSQL")
    return _get_search_status()


def get_vector_index_status() -> dict:
    """
    Get vector index statistics (SQLite only).

    Returns:
        Dictionary with vector index statistics

    Raises:
        NotImplementedError: If PostgreSQL backend is active
    """
    if _use_postgres:
        raise NotImplementedError("get_vector_index_status not available for PostgreSQL")
    return _get_vector_index_status()


def get_db():
    """
    Get database connection (SQLite only).

    Returns:
        Database connection context manager

    Raises:
        NotImplementedError: If PostgreSQL backend is active
    """
    if _use_postgres:
        raise NotImplementedError("get_db not available for PostgreSQL (use get_session instead)")
    return _get_db()


def _create_search_document(result: dict) -> str:
    """
    Create search document from analysis result (SQLite only).

    Args:
        result: Analysis result dictionary

    Returns:
        Search document string

    Raises:
        NotImplementedError: If PostgreSQL backend is active
    """
    if _use_postgres:
        raise NotImplementedError("_create_search_document not available for PostgreSQL")
    return __create_search_document(result)
