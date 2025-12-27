"""
Unit tests for PostgreSQL BM25 retriever.

Tests the PostgresBM25Retriever with mocked PostgreSQL connections.
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
def mock_ssm():
    """Mock AWS SSM client."""
    with patch("retrieval.postgres_bm25.boto3.client") as mock_client:
        mock_ssm = Mock()
        mock_ssm.get_parameter = Mock(
            return_value={
                "Parameter": {
                    "Value": "postgresql://user:pass@localhost:5432/db"
                }
            }
        )
        mock_client.return_value = mock_ssm
        yield mock_ssm


@pytest.fixture
def bm25_retriever(mock_psycopg2, mock_ssm):
    """Create PostgresBM25Retriever with mocked dependencies."""
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
        assert bm25_retriever.table_name == "collections_documents"
        assert bm25_retriever.connection_string == "postgresql://user:pass@localhost:5432/db"
        assert bm25_retriever.user_id is None
        assert bm25_retriever.category_filter is None

    def test_initialization_with_parameter_store(self, mock_psycopg2, mock_ssm):
        """Test initialization with AWS Parameter Store."""
        retriever = PostgresBM25Retriever(
            use_parameter_store=True,
            parameter_name="/test/connection"
        )
        assert retriever.connection_string == "postgresql://user:pass@localhost:5432/db"
        mock_ssm.get_parameter.assert_called_once()

    def test_format_query_for_tsquery(self, bm25_retriever):
        """Test query formatting for tsquery."""
        # Single word
        assert bm25_retriever._format_query_for_tsquery("food") == "food"

        # Multiple words
        assert bm25_retriever._format_query_for_tsquery("delicious food") == "delicious & food"

        # With special characters
        assert bm25_retriever._format_query_for_tsquery("food & drink!") == "food & drink"

        # With hyphens (should be preserved)
        assert bm25_retriever._format_query_for_tsquery("farm-to-table") == "farm-to-table"

    def test_get_relevant_documents(self, bm25_retriever, mock_psycopg2):
        """Test retrieving relevant documents."""
        _, mock_conn, mock_cursor = mock_psycopg2

        # Mock search results
        mock_cursor.fetchall.return_value = [
            {
                "item_id": "1",
                "content": "Delicious food photo",
                "metadata": json.dumps({
                    "item_id": "1",
                    "category": "Food",
                    "headline": "Tasty Meal"
                }),
                "score": 2.5
            },
            {
                "item_id": "2",
                "content": "Another food item",
                "metadata": json.dumps({
                    "item_id": "2",
                    "category": "Food",
                    "headline": "Snack Time"
                }),
                "score": 1.8
            }
        ]

        results = bm25_retriever._get_relevant_documents("food")

        assert len(results) == 2
        assert results[0].metadata["item_id"] == "1"
        assert results[0].metadata["score"] == 2.5
        assert results[0].metadata["score_type"] == "bm25"
        assert results[1].metadata["item_id"] == "2"

    def test_get_relevant_documents_with_user_filter(self, mock_psycopg2, mock_ssm):
        """Test retrieval with user_id filter."""
        _, mock_conn, mock_cursor = mock_psycopg2

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

        assert "metadata->>'user_id' = %s" in sql
        assert "user123" in params

    def test_get_relevant_documents_with_category_filter(self, mock_psycopg2, mock_ssm):
        """Test retrieval with category filter."""
        _, mock_conn, mock_cursor = mock_psycopg2

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

        assert "metadata->>'category' = %s" in sql
        assert "Food" in params

    def test_get_relevant_documents_with_min_score(self, bm25_retriever, mock_psycopg2):
        """Test filtering by minimum relevance score."""
        _, mock_conn, mock_cursor = mock_psycopg2

        bm25_retriever.min_relevance_score = 2.0

        # Mock results with varying scores
        mock_cursor.fetchall.return_value = [
            {
                "item_id": "1",
                "content": "High score",
                "metadata": json.dumps({"item_id": "1"}),
                "score": 2.5
            },
            {
                "item_id": "2",
                "content": "Low score",
                "metadata": json.dumps({"item_id": "2"}),
                "score": 1.5
            }
        ]

        results = bm25_retriever._get_relevant_documents("test")

        # Should only return document with score >= 2.0
        assert len(results) == 1
        assert results[0].metadata["item_id"] == "1"

    def test_add_document(self, bm25_retriever, mock_psycopg2):
        """Test adding a document to the BM25 index."""
        _, mock_conn, mock_cursor = mock_psycopg2

        metadata = {
            "item_id": "test-123",
            "category": "Food",
            "headline": "Test"
        }

        success = bm25_retriever.add_document(
            item_id="test-123",
            content="Test content",
            metadata=metadata
        )

        assert success is True
        mock_cursor.execute.assert_called_once()

        # Check SQL contains UPSERT logic
        call_args = mock_cursor.execute.call_args
        sql = call_args[0][0]
        assert "INSERT INTO" in sql
        assert "ON CONFLICT" in sql
        assert "DO UPDATE SET" in sql

    def test_add_document_with_user_id(self, mock_psycopg2, mock_ssm):
        """Test adding document with user_id set."""
        _, mock_conn, mock_cursor = mock_psycopg2

        retriever = PostgresBM25Retriever(
            connection_string="postgresql://user:pass@localhost:5432/db",
            use_parameter_store=False,
            user_id="user123"
        )

        metadata = {"item_id": "test-123", "category": "Food"}

        retriever.add_document(
            item_id="test-123",
            content="Test content",
            metadata=metadata
        )

        # Verify user_id was added to metadata
        call_args = mock_cursor.execute.call_args
        params = call_args[0][1]
        metadata_json = params[2]
        parsed_metadata = json.loads(metadata_json)
        assert parsed_metadata["user_id"] == "user123"

    def test_add_document_error_handling(self, bm25_retriever, mock_psycopg2):
        """Test error handling when adding document fails."""
        _, mock_conn, mock_cursor = mock_psycopg2

        # Mock to raise an exception
        mock_cursor.execute.side_effect = Exception("Database error")

        success = bm25_retriever.add_document(
            item_id="test-123",
            content="Test content",
            metadata={"item_id": "test-123"}
        )

        assert success is False

    def test_create_table_if_not_exists(self, bm25_retriever, mock_psycopg2):
        """Test creating the BM25 table."""
        _, mock_conn, mock_cursor = mock_psycopg2

        success = bm25_retriever.create_table_if_not_exists()

        assert success is True
        mock_cursor.execute.assert_called_once()

        # Check SQL contains table creation
        call_args = mock_cursor.execute.call_args
        sql = call_args[0][0]
        assert "CREATE TABLE IF NOT EXISTS" in sql
        assert "tsvector" in sql
        assert "CREATE INDEX" in sql

    def test_get_table_stats(self, bm25_retriever, mock_psycopg2):
        """Test getting table statistics."""
        _, mock_conn, mock_cursor = mock_psycopg2

        mock_cursor.fetchone.return_value = {"count": 42}

        stats = bm25_retriever.get_table_stats()

        assert stats["table_name"] == "collections_documents"
        assert stats["document_count"] == 42

    def test_get_table_stats_error_handling(self, bm25_retriever, mock_psycopg2):
        """Test error handling in get_table_stats."""
        _, mock_conn, mock_cursor = mock_psycopg2

        # Mock to raise an exception
        mock_cursor.execute.side_effect = Exception("Database error")

        stats = bm25_retriever.get_table_stats()

        assert "error" in stats
        assert stats["table_name"] == "collections_documents"

    def test_retrieval_error_handling(self, bm25_retriever, mock_psycopg2):
        """Test error handling during retrieval."""
        _, mock_conn, mock_cursor = mock_psycopg2

        # Mock to raise an exception
        mock_cursor.execute.side_effect = Exception("Search error")

        results = bm25_retriever._get_relevant_documents("test query")

        assert results == []

    def test_metadata_as_dict_not_string(self, bm25_retriever, mock_psycopg2):
        """Test handling metadata that's already a dict."""
        _, mock_conn, mock_cursor = mock_psycopg2

        # Mock result with metadata as dict (not JSON string)
        mock_cursor.fetchall.return_value = [
            {
                "item_id": "1",
                "content": "Test",
                "metadata": {"item_id": "1", "category": "Food"},  # Already a dict
                "score": 2.0
            }
        ]

        results = bm25_retriever._get_relevant_documents("test")

        assert len(results) == 1
        assert results[0].metadata["category"] == "Food"
