"""
Database API - PostgreSQL via SQLAlchemy.

This module provides a unified interface for database operations using PostgreSQL.
All operations require user_id for multi-tenancy support.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Import PostgreSQL backend
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
)


def init_db():
    """Initialize database schema."""
    return _init_db()


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
    Create a new item.

    Args:
        item_id: Unique identifier
        filename: Stored filename
        original_filename: Original uploaded filename
        file_path: Path to stored file
        file_size: Size in bytes
        mime_type: MIME type
        user_id: User identifier (required)

    Returns:
        Dictionary representation of created item
    """
    if not user_id:
        raise ValueError("user_id is required")
    return _create_item(
        item_id=item_id,
        filename=filename,
        original_filename=original_filename,
        file_path=file_path,
        file_size=file_size,
        mime_type=mime_type,
        user_id=user_id
    )


def get_item(item_id: str, user_id: str) -> Optional[dict]:
    """
    Get an item by ID.

    Args:
        item_id: Item identifier
        user_id: User identifier (required)

    Returns:
        Dictionary representation of item or None
    """
    if not user_id:
        raise ValueError("user_id is required")
    return _get_item(item_id=item_id, user_id=user_id)


def list_items(
    category: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user_id: str = None
) -> list[dict]:
    """
    List items with optional filtering.

    Args:
        category: Optional category filter
        limit: Maximum number of items
        offset: Offset for pagination
        user_id: User identifier (required)

    Returns:
        List of item dictionaries
    """
    if not user_id:
        raise ValueError("user_id is required")
    return _list_items(
        user_id=user_id,
        category=category,
        limit=limit,
        offset=offset
    )


def count_items(category: Optional[str] = None, user_id: str = None) -> int:
    """
    Count total items with optional category filter.

    Args:
        category: Optional category filter
        user_id: User identifier (required)

    Returns:
        Count of items
    """
    if not user_id:
        raise ValueError("user_id is required")
    return _count_items(user_id=user_id, category=category)


def delete_item(item_id: str, user_id: str) -> bool:
    """
    Delete an item.

    Args:
        item_id: Item identifier
        user_id: User identifier (required)

    Returns:
        True if deleted, False if not found
    """
    if not user_id:
        raise ValueError("user_id is required")
    return _delete_item(item_id=item_id, user_id=user_id)


def create_analysis(
    analysis_id: str,
    item_id: str,
    result: dict,
    provider_used: str,
    model_used: str,
    trace_id: Optional[str] = None,
    user_id: str = None
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
        user_id: User identifier (required)

    Returns:
        Dictionary representation of created analysis
    """
    if not user_id:
        raise ValueError("user_id is required")
    return _create_analysis(
        analysis_id=analysis_id,
        item_id=item_id,
        user_id=user_id,
        result=result,
        provider_used=provider_used,
        model_used=model_used,
        trace_id=trace_id
    )


def get_analysis(analysis_id: str, user_id: str) -> Optional[dict]:
    """
    Get an analysis by ID.

    Args:
        analysis_id: Analysis identifier
        user_id: User identifier (required)

    Returns:
        Dictionary representation of analysis or None
    """
    if not user_id:
        raise ValueError("user_id is required")
    return _get_analysis(analysis_id=analysis_id, user_id=user_id)


def get_latest_analysis(item_id: str, user_id: str) -> Optional[dict]:
    """
    Get the latest analysis for an item.

    Args:
        item_id: Item identifier
        user_id: User identifier (required)

    Returns:
        Dictionary representation of latest analysis or None
    """
    if not user_id:
        raise ValueError("user_id is required")
    return _get_latest_analysis(item_id=item_id, user_id=user_id)


def get_item_analyses(item_id: str, user_id: str) -> list[dict]:
    """
    Get all analyses for an item.

    Args:
        item_id: Item identifier
        user_id: User identifier (required)

    Returns:
        List of analysis dictionaries ordered by version (newest first)
    """
    if not user_id:
        raise ValueError("user_id is required")
    return _get_item_analyses(item_id=item_id, user_id=user_id)


def search_items(
    query: str,
    limit: int = 10,
    category: Optional[str] = None,
    user_id: str = None
) -> list[tuple]:
    """
    Search items using PostgreSQL full-text search.

    Args:
        query: Search query string
        limit: Maximum number of results
        category: Optional category filter
        user_id: User identifier (required)

    Returns:
        List of (item_id, score) tuples
    """
    if not user_id:
        raise ValueError("user_id is required")
    return _search_items(
        user_id=user_id,
        query=query,
        limit=limit,
        category=category
    )
