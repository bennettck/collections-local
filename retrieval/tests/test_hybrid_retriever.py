"""
Unit tests for PostgreSQL hybrid retriever.

Tests the PostgresHybridRetriever and VectorOnlyRetriever with mocked components.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from retrieval.hybrid_retriever import PostgresHybridRetriever, VectorOnlyRetriever
from retrieval.pgvector_store import PGVectorStoreManager
from retrieval.postgres_bm25 import PostgresBM25Retriever


class MockRetriever(BaseRetriever):
    """Mock retriever for testing that properly extends BaseRetriever."""

    _documents: list = []
    search_kwargs: dict = {}

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, documents=None, search_kwargs=None):
        super().__init__()
        self._documents = documents or []
        self.search_kwargs = search_kwargs or {}

    def _get_relevant_documents(self, query: str, *, run_manager=None):
        return self._documents


@pytest.fixture
def mock_pgvector_manager():
    """Mock PGVectorStoreManager."""
    manager = Mock(spec=PGVectorStoreManager)

    # Mock as_retriever - return a proper MockRetriever instance
    mock_retriever = MockRetriever(
        documents=[
            Document(
                page_content="Vector result 1",
                metadata={"item_id": "v1", "category": "Food"}
            ),
            Document(
                page_content="Vector result 2",
                metadata={"item_id": "v2", "category": "Art"}
            )
        ],
        search_kwargs={"k": 20, "filter": None}
    )
    manager.as_retriever.return_value = mock_retriever

    # Mock similarity_search_with_score
    manager.similarity_search_with_score.return_value = [
        (
            Document(
                page_content="Vector result 1",
                metadata={"item_id": "v1", "category": "Food"}
            ),
            0.2  # Distance
        ),
        (
            Document(
                page_content="Vector result 2",
                metadata={"item_id": "v2", "category": "Art"}
            ),
            0.4
        )
    ]

    return manager


@pytest.fixture
def mock_bm25_retriever():
    """Mock PostgresBM25Retriever."""
    with patch("retrieval.hybrid_retriever.PostgresBM25Retriever") as mock_bm25:
        # Return a proper MockRetriever instance
        mock_instance = MockRetriever([
            Document(
                page_content="BM25 result 1",
                metadata={"item_id": "b1", "category": "Food", "score": 2.5, "score_type": "bm25"}
            ),
            Document(
                page_content="BM25 result 2",
                metadata={"item_id": "b2", "category": "Nature", "score": 1.8, "score_type": "bm25"}
            )
        ])
        mock_bm25.return_value = mock_instance
        yield mock_bm25


@pytest.fixture
def mock_ensemble_retriever():
    """Mock EnsembleRetriever."""
    with patch("retrieval.hybrid_retriever.EnsembleRetriever") as mock_ensemble:
        mock_instance = Mock()
        mock_instance.invoke.return_value = [
            Document(
                page_content="Hybrid result 1",
                metadata={"item_id": "h1", "category": "Food"}
            ),
            Document(
                page_content="Hybrid result 2",
                metadata={"item_id": "h2", "category": "Art"}
            )
        ]
        mock_ensemble.return_value = mock_instance
        yield mock_ensemble


class TestPostgresHybridRetriever:
    """Tests for PostgresHybridRetriever."""

    def test_initialization(self, mock_pgvector_manager):
        """Test initialization of PostgresHybridRetriever."""
        retriever = PostgresHybridRetriever(
            pgvector_manager=mock_pgvector_manager,
            connection_string="postgresql://test",
            use_parameter_store=False,
            top_k=10,
            bm25_weight=0.3,
            vector_weight=0.7,
            rrf_c=15
        )

        assert retriever.top_k == 10
        assert retriever.bm25_weight == 0.3
        assert retriever.vector_weight == 0.7
        assert retriever.rrf_c == 15
        assert retriever.pgvector_manager == mock_pgvector_manager

    def test_get_relevant_documents(
        self,
        mock_pgvector_manager,
        mock_bm25_retriever
    ):
        """Test hybrid retrieval."""
        with patch("retrieval.hybrid_retriever.EnsembleRetriever") as mock_ensemble:
            # Create MockRetriever instances for the EnsembleRetriever
            mock_bm25_instance = MockRetriever([
                Document(page_content="BM25 result", metadata={"item_id": "b1"})
            ])
            mock_vector_instance = MockRetriever([
                Document(page_content="Vector result", metadata={"item_id": "v1"})
            ])

            # Mock the ensemble retriever to return combined results
            mock_ensemble_instance = Mock()
            mock_ensemble_instance.invoke.return_value = [
                Document(
                    page_content="Hybrid result 1",
                    metadata={"item_id": "h1"}
                ),
                Document(
                    page_content="Hybrid result 2",
                    metadata={"item_id": "h2"}
                )
            ]
            mock_ensemble.return_value = mock_ensemble_instance

            retriever = PostgresHybridRetriever(
                pgvector_manager=mock_pgvector_manager,
                connection_string="postgresql://test",
                use_parameter_store=False,
                top_k=10
            )

            results = retriever._get_relevant_documents("test query")

            assert len(results) == 2
            assert results[0].metadata["item_id"] == "h1"
            assert results[0].metadata["score_type"] == "hybrid_rrf"
            assert "rrf_score" in results[0].metadata

            # Verify EnsembleRetriever was called
            mock_ensemble.assert_called_once()

    def test_get_relevant_documents_with_filters(
        self,
        mock_pgvector_manager,
        mock_bm25_retriever,
        mock_ensemble_retriever
    ):
        """Test hybrid retrieval with user and category filters."""
        retriever = PostgresHybridRetriever(
            pgvector_manager=mock_pgvector_manager,
            connection_string="postgresql://test",
            use_parameter_store=False,
            user_id="user123",
            category_filter="Food",
            top_k=5
        )

        results = retriever._get_relevant_documents("test query")

        # Verify BM25 retriever was created with filters
        mock_bm25_retriever.assert_called_once()
        call_kwargs = mock_bm25_retriever.call_args[1]
        assert call_kwargs["user_id"] == "user123"
        assert call_kwargs["category_filter"] == "Food"

        # Verify PGVector retriever was called with filters
        mock_pgvector_manager.as_retriever.assert_called()
        call_kwargs = mock_pgvector_manager.as_retriever.call_args[1]
        assert call_kwargs["search_kwargs"]["filter"]["user_id"] == "user123"
        assert call_kwargs["search_kwargs"]["filter"]["category"] == "Food"

    def test_get_relevant_documents_limits_to_top_k(
        self,
        mock_pgvector_manager,
        mock_bm25_retriever
    ):
        """Test that results are limited to top_k."""
        with patch("retrieval.hybrid_retriever.EnsembleRetriever") as mock_ensemble:
            # Mock ensemble to return many results
            mock_ensemble_instance = Mock()
            mock_ensemble_instance.invoke.return_value = [
                Document(
                    page_content=f"Result {i}",
                    metadata={"item_id": f"h{i}"}
                )
                for i in range(20)
            ]
            mock_ensemble.return_value = mock_ensemble_instance

            retriever = PostgresHybridRetriever(
                pgvector_manager=mock_pgvector_manager,
                connection_string="postgresql://test",
                use_parameter_store=False,
                top_k=5
            )

            results = retriever._get_relevant_documents("test query")

            assert len(results) == 5

    def test_get_relevant_documents_error_no_pgvector_manager(
        self,
        mock_bm25_retriever,
        mock_ensemble_retriever
    ):
        """Test error when pgvector_manager is not provided."""
        retriever = PostgresHybridRetriever(
            connection_string="postgresql://test",
            use_parameter_store=False
        )

        results = retriever._get_relevant_documents("test query")

        assert results == []

    def test_get_relevant_documents_error_handling(
        self,
        mock_pgvector_manager,
        mock_bm25_retriever,
        mock_ensemble_retriever
    ):
        """Test error handling during retrieval."""
        # Mock ensemble to raise an exception
        mock_ensemble_retriever.return_value.invoke.side_effect = Exception("Retrieval error")

        retriever = PostgresHybridRetriever(
            pgvector_manager=mock_pgvector_manager,
            connection_string="postgresql://test",
            use_parameter_store=False
        )

        results = retriever._get_relevant_documents("test query")

        assert results == []

    def test_rrf_scores_calculated(
        self,
        mock_pgvector_manager,
        mock_bm25_retriever,
        mock_ensemble_retriever
    ):
        """Test that RRF scores are calculated for each document."""
        retriever = PostgresHybridRetriever(
            pgvector_manager=mock_pgvector_manager,
            connection_string="postgresql://test",
            use_parameter_store=False,
            top_k=5,
            rrf_c=15
        )

        results = retriever._get_relevant_documents("test query")

        # Check that RRF scores were added
        for i, doc in enumerate(results, start=1):
            expected_score = 1.0 / (15 + i)
            assert doc.metadata["rrf_score"] == expected_score

    def test_ensemble_retriever_configuration(
        self,
        mock_pgvector_manager,
        mock_bm25_retriever
    ):
        """Test that EnsembleRetriever is configured correctly."""
        with patch("retrieval.hybrid_retriever.EnsembleRetriever") as mock_ensemble:
            # Mock the ensemble retriever
            mock_ensemble_instance = Mock()
            mock_ensemble_instance.invoke.return_value = [
                Document(page_content="Result", metadata={"item_id": "h1"})
            ]
            mock_ensemble.return_value = mock_ensemble_instance

            retriever = PostgresHybridRetriever(
                pgvector_manager=mock_pgvector_manager,
                connection_string="postgresql://test",
                use_parameter_store=False,
                bm25_weight=0.4,
                vector_weight=0.6,
                rrf_c=20
            )

            retriever._get_relevant_documents("test query")

            # Verify EnsembleRetriever configuration
            call_kwargs = mock_ensemble.call_args[1]
            assert call_kwargs["weights"] == [0.4, 0.6]
            assert call_kwargs["c"] == 20
            assert call_kwargs["id_key"] == "item_id"


class TestVectorOnlyRetriever:
    """Tests for VectorOnlyRetriever."""

    def test_initialization(self, mock_pgvector_manager):
        """Test initialization of VectorOnlyRetriever."""
        retriever = VectorOnlyRetriever(
            pgvector_manager=mock_pgvector_manager,
            top_k=10,
            user_id="user123",
            category_filter="Food",
            min_similarity_score=0.7
        )

        assert retriever.top_k == 10
        assert retriever.user_id == "user123"
        assert retriever.category_filter == "Food"
        assert retriever.min_similarity_score == 0.7

    def test_get_relevant_documents(self, mock_pgvector_manager):
        """Test vector-only retrieval."""
        retriever = VectorOnlyRetriever(
            pgvector_manager=mock_pgvector_manager,
            top_k=5
        )

        results = retriever._get_relevant_documents("test query")

        assert len(results) == 2
        assert results[0].metadata["item_id"] == "v1"
        assert results[0].metadata["score_type"] == "similarity"
        assert "score" in results[0].metadata

        # Verify similarity_search_with_score was called
        mock_pgvector_manager.similarity_search_with_score.assert_called_once_with(
            "test query",
            k=5,
            filter=None
        )

    def test_get_relevant_documents_with_filters(self, mock_pgvector_manager):
        """Test vector retrieval with filters."""
        retriever = VectorOnlyRetriever(
            pgvector_manager=mock_pgvector_manager,
            top_k=5,
            user_id="user123",
            category_filter="Food"
        )

        results = retriever._get_relevant_documents("test query")

        # Verify filter was passed
        call_kwargs = mock_pgvector_manager.similarity_search_with_score.call_args[1]
        assert call_kwargs["filter"]["user_id"] == "user123"
        assert call_kwargs["filter"]["category"] == "Food"

    def test_get_relevant_documents_with_min_similarity(self, mock_pgvector_manager):
        """Test filtering by minimum similarity score."""
        # Mock results with varying distances
        mock_pgvector_manager.similarity_search_with_score.return_value = [
            (
                Document(
                    page_content="High similarity",
                    metadata={"item_id": "v1"}
                ),
                0.2  # Low distance = high similarity
            ),
            (
                Document(
                    page_content="Low similarity",
                    metadata={"item_id": "v2"}
                ),
                1.5  # High distance = low similarity
            )
        ]

        retriever = VectorOnlyRetriever(
            pgvector_manager=mock_pgvector_manager,
            top_k=5,
            min_similarity_score=0.6
        )

        results = retriever._get_relevant_documents("test query")

        # Should only return document with high similarity
        # Similarity = 1 - (distance / 2)
        # For distance=0.2: similarity = 1 - (0.2/2) = 0.9 (> 0.6) ✓
        # For distance=1.5: similarity = 1 - (1.5/2) = 0.25 (< 0.6) ✗
        assert len(results) == 1
        assert results[0].metadata["item_id"] == "v1"

    def test_similarity_score_calculation(self, mock_pgvector_manager):
        """Test that similarity scores are calculated correctly from distances."""
        retriever = VectorOnlyRetriever(
            pgvector_manager=mock_pgvector_manager,
            top_k=5
        )

        results = retriever._get_relevant_documents("test query")

        # Check similarity calculation
        # Distance 0.2 -> Similarity = 1 - (0.2 / 2) = 0.9
        assert abs(results[0].metadata["score"] - 0.9) < 0.01

        # Distance 0.4 -> Similarity = 1 - (0.4 / 2) = 0.8
        assert abs(results[1].metadata["score"] - 0.8) < 0.01

    def test_get_relevant_documents_error_no_pgvector_manager(self):
        """Test error when pgvector_manager is not provided."""
        retriever = VectorOnlyRetriever(top_k=5)

        results = retriever._get_relevant_documents("test query")

        assert results == []

    def test_get_relevant_documents_error_handling(self, mock_pgvector_manager):
        """Test error handling during retrieval."""
        # Mock to raise an exception
        mock_pgvector_manager.similarity_search_with_score.side_effect = Exception("Search error")

        retriever = VectorOnlyRetriever(
            pgvector_manager=mock_pgvector_manager,
            top_k=5
        )

        results = retriever._get_relevant_documents("test query")

        assert results == []

    def test_empty_filter_dict(self, mock_pgvector_manager):
        """Test that empty filter dict is passed as None."""
        retriever = VectorOnlyRetriever(
            pgvector_manager=mock_pgvector_manager,
            top_k=5
            # No user_id or category_filter
        )

        results = retriever._get_relevant_documents("test query")

        # Verify None was passed for filter
        call_kwargs = mock_pgvector_manager.similarity_search_with_score.call_args[1]
        assert call_kwargs["filter"] is None
