"""
Unit tests for PostgreSQL BM25 retriever.

Tests the PostgresBM25Retriever which queries the langchain_pg_embedding table
for full-text search using PostgreSQL tsvector/tsquery.

ARCHITECTURE NOTE:
- BM25 now queries langchain_pg_embedding (same table as vector search)
- This ensures data consistency between keyword and semantic search
- The 'document' column contains text for BM25 search
- The 'cmetadata' column contains user_id, category, etc.
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from langchain_core.documents import Document

from retrieval.postgres_bm25 import PostgresBM25Retriever


@pytest.fixture
def mock_psycopg2():
    """Mock psycopg2 connection and cursor."""
    with patch("retrieval.postgres_bm25.psycopg2") as mock_pg:
        # Mock connection and cursor
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # Setup cursor factory
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = {"count": 0}

        mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=False)

        mock_pg.connect.return_value = mock_conn

        yield mock_pg, mock_conn, mock_cursor


@pytest.fixture
def mock_connection():
    """Mock database connection module."""
    with patch("retrieval.postgres_bm25.get_connection_string") as mock_get_conn:
        mock_get_conn.return_value = "postgresql://user:pass@localhost:5432/db"
        yield mock_get_conn


@pytest.fixture
def bm25_retriever(mock_psycopg2, mock_connection):
    """Create PostgresBM25Retriever with mocked dependencies."""
    with patch("retrieval.postgres_bm25.get_vector_store_config") as mock_config:
        mock_config.return_value = {"collection_name": "collections_vectors_prod"}
        retriever = PostgresBM25Retriever(
            connection_string="postgresql://user:pass@localhost:5432/db",
            use_parameter_store=False,
            top_k=10
        )
        return retriever


class TestPostgresBM25Retriever:
    """Tests for PostgresBM25Retriever."""

    def test_initialization(self, bm25_retriever):
        """Test initialization of PostgresBM25Retriever."""
        assert bm25_retriever.top_k == 10
        assert bm25_retriever.collection_name == "collections_vectors_prod"
        assert bm25_retriever.connection_string == "postgresql://user:pass@localhost:5432/db"
        assert bm25_retriever.user_id is None
        assert bm25_retriever.category_filter is None

    def test_format_query_for_tsquery(self, bm25_retriever):
        """Test query formatting for tsquery (now uses OR operator)."""
        # Single word (skip single-char words)
        assert bm25_retriever._format_query_for_tsquery("food") == "food"

        # Multiple words - now joined with OR (|) for inclusive matching
        assert bm25_retriever._format_query_for_tsquery("delicious food") == "delicious | food"

        # With special characters (stripped)
        result = bm25_retriever._format_query_for_tsquery("food & drink!")
        assert "food" in result
        assert "drink" in result

        # With hyphens (should be preserved)
        assert bm25_retriever._format_query_for_tsquery("farm-to-table") == "farm-to-table"

        # Empty query
        assert bm25_retriever._format_query_for_tsquery("") == ""

    def test_get_relevant_documents(self, bm25_retriever, mock_psycopg2):
        """Test retrieving relevant documents from langchain_pg_embedding."""
        _, mock_conn, mock_cursor = mock_psycopg2

        # Mock search results (matching langchain_pg_embedding schema)
        mock_cursor.fetchall.return_value = [
            {
                "id": "uuid-1",
                "document": "Delicious food photo analysis",
                "cmetadata": {
                    "item_id": "item-1",
                    "user_id": "user123",
                    "category": "Food",
                    "headline": "Tasty Meal"
                },
                "score": 2.5
            },
            {
                "id": "uuid-2",
                "document": "Another food item analysis",
                "cmetadata": {
                    "item_id": "item-2",
                    "user_id": "user123",
                    "category": "Food",
                    "headline": "Snack Time"
                },
                "score": 1.8
            }
        ]

        results = bm25_retriever._get_relevant_documents("food")

        assert len(results) == 2
        assert results[0].metadata["item_id"] == "item-1"
        assert results[0].metadata["score"] == 2.5
        assert results[0].metadata["score_type"] == "bm25"
        assert results[1].metadata["item_id"] == "item-2"
        assert results[0].page_content == "Delicious food photo analysis"

    def test_get_relevant_documents_with_user_filter(self, mock_psycopg2, mock_connection):
        """Test retrieval with user_id filter."""
        _, mock_conn, mock_cursor = mock_psycopg2

        with patch("retrieval.postgres_bm25.get_vector_store_config") as mock_config:
            mock_config.return_value = {"collection_name": "collections_vectors_prod"}
            retriever = PostgresBM25Retriever(
                connection_string="postgresql://user:pass@localhost:5432/db",
                use_parameter_store=False,
                user_id="user123",
                top_k=5
            )

        mock_cursor.fetchall.return_value = []

        retriever._get_relevant_documents("test query")

        # Check that SQL was called with user_id filter
        call_args = mock_cursor.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]

        assert "cmetadata->>'user_id' = %s" in sql
        assert "user123" in params

    def test_get_relevant_documents_with_category_filter(self, mock_psycopg2, mock_connection):
        """Test retrieval with category filter."""
        _, mock_conn, mock_cursor = mock_psycopg2

        with patch("retrieval.postgres_bm25.get_vector_store_config") as mock_config:
            mock_config.return_value = {"collection_name": "collections_vectors_prod"}
            retriever = PostgresBM25Retriever(
                connection_string="postgresql://user:pass@localhost:5432/db",
                use_parameter_store=False,
                category_filter="Food",
                top_k=5
            )

        mock_cursor.fetchall.return_value = []

        retriever._get_relevant_documents("test query")

        # Check that SQL was called with category filter
        call_args = mock_cursor.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]

        assert "cmetadata->>'category' = %s" in sql
        assert "Food" in params

    def test_get_relevant_documents_with_min_score(self, bm25_retriever, mock_psycopg2):
        """Test filtering by minimum relevance score."""
        _, mock_conn, mock_cursor = mock_psycopg2

        bm25_retriever.min_relevance_score = 2.0

        # Mock results with varying scores
        mock_cursor.fetchall.return_value = [
            {
                "id": "uuid-1",
                "document": "High score content",
                "cmetadata": {"item_id": "item-1"},
                "score": 2.5
            },
            {
                "id": "uuid-2",
                "document": "Low score content",
                "cmetadata": {"item_id": "item-2"},
                "score": 1.5
            }
        ]

        results = bm25_retriever._get_relevant_documents("test")

        # Should only return document with score >= 2.0
        assert len(results) == 1
        assert results[0].metadata["item_id"] == "item-1"

    def test_collection_name_in_query(self, bm25_retriever, mock_psycopg2):
        """Test that collection name is included in the query."""
        _, mock_conn, mock_cursor = mock_psycopg2
        mock_cursor.fetchall.return_value = []

        bm25_retriever._get_relevant_documents("test")

        # Check that SQL joins with collection table
        call_args = mock_cursor.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]

        assert "langchain_pg_embedding" in sql
        assert "langchain_pg_collection" in sql
        assert "c.name = %s" in sql
        assert "collections_vectors_prod" in params

    def test_get_table_stats(self, bm25_retriever, mock_psycopg2):
        """Test getting table statistics."""
        _, mock_conn, mock_cursor = mock_psycopg2

        mock_cursor.fetchone.return_value = {"count": 42}

        stats = bm25_retriever.get_table_stats()

        assert stats["collection_name"] == "collections_vectors_prod"
        assert stats["document_count"] == 42
        assert stats["source_table"] == "langchain_pg_embedding"

    def test_get_table_stats_error_handling(self, bm25_retriever, mock_psycopg2):
        """Test error handling in get_table_stats."""
        _, mock_conn, mock_cursor = mock_psycopg2

        # Mock to raise an exception
        mock_cursor.execute.side_effect = Exception("Database error")

        stats = bm25_retriever.get_table_stats()

        assert "error" in stats
        assert stats["collection_name"] == "collections_vectors_prod"

    def test_retrieval_error_propagation(self, bm25_retriever, mock_psycopg2):
        """Test that errors are propagated (not silently swallowed)."""
        _, mock_conn, mock_cursor = mock_psycopg2

        # Mock to raise an exception
        mock_cursor.execute.side_effect = Exception("Search error")

        # Should raise the exception (not return empty list silently)
        with pytest.raises(Exception) as exc_info:
            bm25_retriever._get_relevant_documents("test query")

        assert "Search error" in str(exc_info.value)

    def test_metadata_as_dict_not_string(self, bm25_retriever, mock_psycopg2):
        """Test handling metadata that's already a dict (cmetadata is JSONB)."""
        _, mock_conn, mock_cursor = mock_psycopg2

        # Mock result with cmetadata as dict (normal for PostgreSQL JSONB)
        mock_cursor.fetchall.return_value = [
            {
                "id": "uuid-1",
                "document": "Test content",
                "cmetadata": {"item_id": "item-1", "category": "Food"},  # Already a dict
                "score": 2.0
            }
        ]

        results = bm25_retriever._get_relevant_documents("test")

        assert len(results) == 1
        assert results[0].metadata["category"] == "Food"

    def test_null_score_handling(self, bm25_retriever, mock_psycopg2):
        """Test handling of null scores from database."""
        _, mock_conn, mock_cursor = mock_psycopg2

        mock_cursor.fetchall.return_value = [
            {
                "id": "uuid-1",
                "document": "Content with null score",
                "cmetadata": {"item_id": "item-1"},
                "score": None  # NULL from database
            }
        ]

        results = bm25_retriever._get_relevant_documents("test")

        assert len(results) == 1
        assert results[0].metadata["score"] == 0.0  # Should default to 0.0

    def test_empty_document_handling(self, bm25_retriever, mock_psycopg2):
        """Test handling of empty/null document content."""
        _, mock_conn, mock_cursor = mock_psycopg2

        mock_cursor.fetchall.return_value = [
            {
                "id": "uuid-1",
                "document": None,  # NULL document
                "cmetadata": {"item_id": "item-1"},
                "score": 1.0
            }
        ]

        results = bm25_retriever._get_relevant_documents("test")

        assert len(results) == 1
        assert results[0].page_content == ""  # Should default to empty string
