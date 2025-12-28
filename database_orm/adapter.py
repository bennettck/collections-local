"""
Database adapter interface for Collections Local.

Provides an abstract interface that both SQLite and PostgreSQL
implementations can fulfill, enabling gradual migration and
environment-based backend selection.
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from datetime import datetime


class DatabaseAdapter(ABC):
    """Abstract base class for database operations.

    All methods require user_id for multi-tenancy support.
    """

    @abstractmethod
    def init_db(self) -> None:
        """Initialize database schema."""
        pass

    @abstractmethod
    def create_item(
        self,
        user_id: str,
        item_id: str,
        filename: str,
        file_path: str,
        file_size: Optional[int] = None,
        mime_type: Optional[str] = None,
        original_filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new item.

        Args:
            user_id: User identifier (required for multi-tenancy)
            item_id: Unique identifier for the item
            filename: Stored filename
            file_path: Path to stored file
            file_size: Size in bytes (optional)
            mime_type: MIME type (optional)
            original_filename: Original uploaded filename (optional)

        Returns:
            Dictionary representation of created item
        """
        pass

    @abstractmethod
    def get_item(self, user_id: str, item_id: str) -> Optional[Dict[str, Any]]:
        """Get item by ID.

        Args:
            user_id: User identifier (for security)
            item_id: Item identifier

        Returns:
            Dictionary representation of item or None
        """
        pass

    @abstractmethod
    def list_items(
        self,
        user_id: str,
        limit: int = 100,
        offset: int = 0,
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List items for a user.

        Args:
            user_id: User identifier
            limit: Maximum number of items (default: 100)
            offset: Offset for pagination (default: 0)
            category: Optional category filter

        Returns:
            List of item dictionaries
        """
        pass

    @abstractmethod
    def count_items(self, user_id: str, category: Optional[str] = None) -> int:
        """Count items for a user.

        Args:
            user_id: User identifier
            category: Optional category filter

        Returns:
            Count of items
        """
        pass

    @abstractmethod
    def delete_item(self, user_id: str, item_id: str) -> bool:
        """Delete an item.

        Args:
            user_id: User identifier (for security)
            item_id: Item identifier

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    def create_analysis(
        self,
        user_id: str,
        item_id: str,
        analysis_id: str,
        raw_response: Dict[str, Any],
        provider_used: Optional[str] = None,
        model_used: Optional[str] = None,
        trace_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create analysis for an item.

        Args:
            user_id: User identifier
            item_id: Item being analyzed
            analysis_id: Unique identifier for analysis
            raw_response: Analysis result dictionary
            provider_used: AI provider name (optional)
            model_used: Model name (optional)
            trace_id: Optional tracing identifier

        Returns:
            Dictionary representation of created analysis
        """
        pass

    @abstractmethod
    def get_analysis(self, user_id: str, analysis_id: str) -> Optional[Dict[str, Any]]:
        """Get analysis by ID.

        Args:
            user_id: User identifier (for security)
            analysis_id: Analysis identifier

        Returns:
            Dictionary representation of analysis or None
        """
        pass

    @abstractmethod
    def get_latest_analysis(self, user_id: str, item_id: str) -> Optional[Dict[str, Any]]:
        """Get latest analysis for an item.

        Args:
            user_id: User identifier
            item_id: Item identifier

        Returns:
            Dictionary representation of latest analysis or None
        """
        pass

    @abstractmethod
    def get_item_analyses(self, user_id: str, item_id: str) -> List[Dict[str, Any]]:
        """Get all analyses for an item.

        Args:
            user_id: User identifier
            item_id: Item identifier

        Returns:
            List of analysis dictionaries ordered by version (newest first)
        """
        pass

    @abstractmethod
    def search_items(
        self,
        user_id: str,
        query: str,
        limit: int = 10,
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search items using full-text search.

        Args:
            user_id: User identifier
            query: Search query string
            limit: Maximum number of results (default: 10)
            category: Optional category filter

        Returns:
            List of item dictionaries with relevance scores
        """
        pass

    # Note: Embedding methods (create_embedding, get_embedding) have been removed.
    # Embeddings are now handled by langchain-postgres (PGVectorStoreManager).
    # See retrieval/pgvector_store.py for the new embedding storage interface.


def get_database_adapter() -> DatabaseAdapter:
    """
    Factory function to get the appropriate database adapter.

    Selection logic:
    1. If DB_SECRET_ARN or DATABASE_URL with postgresql:// -> PostgreSQLAdapter
    2. Otherwise -> SQLiteAdapter (for local development)

    Returns:
        DatabaseAdapter instance
    """
    import os

    # Check for PostgreSQL indicators
    db_secret = os.getenv("DB_SECRET_ARN")
    db_url = os.getenv("DATABASE_URL", "")

    if db_secret or db_url.startswith("postgresql"):
        from database.postgres_adapter import PostgreSQLAdapter
        return PostgreSQLAdapter()
    else:
        from database.sqlite_adapter import SQLiteAdapter
        return SQLiteAdapter()
