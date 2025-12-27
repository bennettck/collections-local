"""
Unit tests for PGVector store.

Tests the PGVectorStoreManager with mocked PostgreSQL connections.
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from langchain_core.documents import Document

from retrieval.pgvector_store import PGVectorStoreManager


@pytest.fixture
def mock_voyage_embeddings():
    """Mock VoyageAI embeddings."""
    with patch("retrieval.pgvector_store.VoyageAIEmbeddings") as mock_embeddings:
        mock_instance = Mock()
        mock_instance.embed_query = Mock(return_value=[0.1] * 1024)
        mock_instance.embed_documents = Mock(return_value=[[0.1] * 1024])
        mock_embeddings.return_value = mock_instance
        yield mock_embeddings


@pytest.fixture
def mock_pgvector():
    """Mock PGVector store."""
    with patch("retrieval.pgvector_store.PGVector") as mock_pg:
        mock_instance = Mock()
        mock_instance.add_documents = Mock(return_value=["doc1", "doc2"])
        mock_instance.similarity_search = Mock(return_value=[])
        mock_instance.similarity_search_with_score = Mock(return_value=[])
        mock_instance.as_retriever = Mock(return_value=Mock())
        mock_instance._make_session = Mock()
        mock_pg.return_value = mock_instance
        yield mock_pg


@pytest.fixture
def mock_ssm():
    """Mock AWS SSM client."""
    with patch("retrieval.pgvector_store.boto3.client") as mock_client:
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
def pgvector_manager(mock_voyage_embeddings, mock_pgvector, mock_ssm):
    """Create PGVectorStoreManager with mocked dependencies."""
    with patch.dict("os.environ", {"VOYAGE_API_KEY": "test-key"}):
        manager = PGVectorStoreManager(
            connection_string="postgresql://user:pass@localhost:5432/db",
            use_parameter_store=False
        )
        return manager


class TestPGVectorStoreManager:
    """Tests for PGVectorStoreManager."""

    def test_initialization(self, pgvector_manager):
        """Test initialization of PGVectorStoreManager."""
        assert pgvector_manager.collection_name == "collections_vectors"
        assert pgvector_manager.embedding_model == "voyage-3.5-lite"
        assert pgvector_manager.vectorstore is not None
        assert pgvector_manager.embeddings is not None

    def test_initialization_with_parameter_store(
        self, mock_voyage_embeddings, mock_pgvector, mock_ssm
    ):
        """Test initialization with AWS Parameter Store."""
        with patch.dict("os.environ", {"VOYAGE_API_KEY": "test-key"}):
            manager = PGVectorStoreManager(
                use_parameter_store=True,
                parameter_name="/test/connection"
            )
            assert manager.connection_string == "postgresql://user:pass@localhost:5432/db"
            mock_ssm.get_parameter.assert_called_once()

    def test_add_documents(self, pgvector_manager):
        """Test adding documents to the vector store."""
        documents = [
            Document(
                page_content="Test content 1",
                metadata={"item_id": "1", "category": "Food"}
            ),
            Document(
                page_content="Test content 2",
                metadata={"item_id": "2", "category": "Art"}
            )
        ]

        doc_ids = pgvector_manager.add_documents(documents, ids=["1", "2"])

        assert doc_ids == ["doc1", "doc2"]
        pgvector_manager.vectorstore.add_documents.assert_called_once_with(
            documents, ids=["1", "2"]
        )

    def test_similarity_search(self, pgvector_manager):
        """Test similarity search."""
        # Mock return value
        mock_docs = [
            Document(
                page_content="Result 1",
                metadata={"item_id": "1", "category": "Food"}
            )
        ]
        pgvector_manager.vectorstore.similarity_search.return_value = mock_docs

        results = pgvector_manager.similarity_search("test query", k=5)

        assert len(results) == 1
        assert results[0].metadata["item_id"] == "1"
        pgvector_manager.vectorstore.similarity_search.assert_called_once_with(
            "test query", k=5, filter=None
        )

    def test_similarity_search_with_filter(self, pgvector_manager):
        """Test similarity search with metadata filter."""
        filter_dict = {"category": "Food", "user_id": "123"}

        pgvector_manager.similarity_search("test query", k=5, filter=filter_dict)

        pgvector_manager.vectorstore.similarity_search.assert_called_once_with(
            "test query", k=5, filter=filter_dict
        )

    def test_similarity_search_with_score(self, pgvector_manager):
        """Test similarity search with scores."""
        # Mock return value
        mock_results = [
            (
                Document(
                    page_content="Result 1",
                    metadata={"item_id": "1"}
                ),
                0.15  # Distance
            )
        ]
        pgvector_manager.vectorstore.similarity_search_with_score.return_value = mock_results

        results = pgvector_manager.similarity_search_with_score("test query", k=5)

        assert len(results) == 1
        doc, score = results[0]
        assert doc.metadata["item_id"] == "1"
        assert score == 0.15

    def test_as_retriever(self, pgvector_manager):
        """Test creating retriever interface."""
        retriever = pgvector_manager.as_retriever(search_kwargs={"k": 5})

        assert retriever is not None
        pgvector_manager.vectorstore.as_retriever.assert_called_once_with(
            search_kwargs={"k": 5}
        )

    def test_create_flat_document(self):
        """Test creating flat document from raw response."""
        raw_response = {
            "summary": "A beautiful sunset",
            "headline": "Sunset Photo",
            "category": "Nature",
            "subcategories": ["Landscape", "Sky"],
            "image_details": {
                "extracted_text": ["No text"],
                "key_interest": "Orange sky",
                "themes": ["peaceful", "calm"],
                "objects": ["sun", "clouds"],
                "emotions": ["serene"],
                "vibes": ["relaxing"]
            },
            "media_metadata": {
                "location_tags": ["beach"],
                "hashtags": ["sunset", "nature"]
            }
        }

        doc = PGVectorStoreManager.create_flat_document(
            raw_response,
            item_id="test-123",
            filename="sunset.jpg"
        )

        # Check that document was created
        assert isinstance(doc, Document)
        assert "sunset" in doc.page_content.lower()
        assert "nature" in doc.page_content.lower()

        # Check metadata
        assert doc.metadata["item_id"] == "test-123"
        assert doc.metadata["category"] == "Nature"
        assert doc.metadata["filename"] == "sunset.jpg"
        assert doc.metadata["image_url"] == "/images/sunset.jpg"

        # Check that raw_response is stored as JSON string
        assert isinstance(doc.metadata["raw_response"], str)
        parsed_response = json.loads(doc.metadata["raw_response"])
        assert parsed_response["summary"] == "A beautiful sunset"

    def test_create_flat_document_with_list_text(self):
        """Test creating flat document with text as list."""
        raw_response = {
            "summary": "Test",
            "headline": "Test",
            "category": "Test",
            "subcategories": [],
            "image_details": {
                "extracted_text": ["Line 1", "Line 2"],  # List format
                "key_interest": "",
                "themes": [],
                "objects": [],
                "emotions": [],
                "vibes": []
            },
            "media_metadata": {
                "location_tags": [],
                "hashtags": []
            }
        }

        doc = PGVectorStoreManager.create_flat_document(
            raw_response,
            item_id="test-123",
            filename="test.jpg"
        )

        assert "Line 1 Line 2" in doc.page_content

    def test_get_collection_stats_error_handling(self, pgvector_manager):
        """Test error handling in get_collection_stats."""
        # Mock _make_session to raise an exception
        pgvector_manager.vectorstore._make_session = Mock(
            side_effect=Exception("Database error")
        )

        stats = pgvector_manager.get_collection_stats()

        assert "error" in stats
        assert stats["collection_name"] == "collections_vectors"

    def test_similarity_search_error_handling(self, pgvector_manager):
        """Test error handling in similarity_search."""
        # Mock to raise an exception
        pgvector_manager.vectorstore.similarity_search = Mock(
            side_effect=Exception("Search error")
        )

        results = pgvector_manager.similarity_search("test query")

        assert results == []

    def test_missing_voyage_api_key(self, mock_pgvector, mock_ssm):
        """Test initialization fails without VOYAGE_API_KEY."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="VOYAGE_API_KEY"):
                PGVectorStoreManager(
                    connection_string="postgresql://test",
                    use_parameter_store=False
                )

    def test_missing_connection_string(self, mock_voyage_embeddings, mock_pgvector):
        """Test initialization fails without connection string."""
        with patch.dict("os.environ", {"VOYAGE_API_KEY": "test-key"}, clear=True):
            with pytest.raises(ValueError, match="No connection string"):
                PGVectorStoreManager(use_parameter_store=False)
