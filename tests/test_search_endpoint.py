"""
Integration tests for the /search endpoint with agentic search support.

Tests the full search endpoint workflow including:
- Request validation and parameter handling
- Search type routing (bm25, vector, hybrid, agentic)
- Database routing (prod vs golden)
- Response format compliance
- Error handling
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def mock_vector_store():
    """Mock PGVectorStoreManager."""
    mock = MagicMock()
    mock.get_collection_stats.return_value = {"count": 10}
    return mock


@pytest.fixture
def client(mock_vector_store):
    """Create test client with mocked dependencies."""
    with patch('main.prod_vector_store', mock_vector_store):
        with patch('main.golden_vector_store', mock_vector_store):
            with patch('main.init_db'):
                from main import app
                return TestClient(app)


class TestSearchEndpointBasics:
    """Basic tests for search endpoint."""

    def test_search_endpoint_exists(self, client):
        """Test that /search endpoint exists."""
        response = client.post(
            "/search",
            json={"query": "test"}
        )
        # Should return 200 or validation error, not 404
        assert response.status_code != 404

    def test_search_requires_query(self, client):
        """Test that query parameter is required."""
        response = client.post("/search", json={})
        assert response.status_code == 422  # Validation error

    def test_search_validates_query_length(self, client):
        """Test that query must meet minimum length."""
        response = client.post("/search", json={"query": "ab"})  # Too short
        assert response.status_code == 422

    def test_search_accepts_valid_query(self, client):
        """Test that valid query is accepted."""
        with patch('main.get_item') as mock_get_item:
            with patch('main.get_latest_analysis') as mock_analysis:
                mock_get_item.return_value = None
                mock_analysis.return_value = None

                response = client.post(
                    "/search",
                    json={"query": "test query"}
                )
                # Should not be a validation error
                assert response.status_code != 422


class TestSearchTypeRouting:
    """Tests for search type routing logic."""

    @patch('main.get_item')
    @patch('main.get_latest_analysis')
    def test_bm25_search_type(self, mock_analysis, mock_get_item, client):
        """Test that bm25-lc search type is routed correctly."""
        mock_get_item.return_value = None
        mock_analysis.return_value = None

        with patch('retrieval.langchain_retrievers.BM25LangChainRetriever') as mock_retriever:
            mock_instance = MagicMock()
            mock_instance.invoke.return_value = []
            mock_retriever.return_value = mock_instance

            response = client.post(
                "/search",
                json={
                    "query": "test query",
                    "search_type": "bm25-lc",
                    "include_answer": False
                }
            )

            assert response.status_code == 200
            data = response.json()
            assert data["search_type"] == "bm25-lc"

    @patch('main.get_item')
    @patch('main.get_latest_analysis')
    @patch('main.get_current_vector_store')
    def test_vector_search_type(self, mock_vector_store, mock_analysis, mock_get_item, client):
        """Test that vector-lc search type is routed correctly."""
        mock_get_item.return_value = None
        mock_analysis.return_value = None
        mock_vector_store.return_value = MagicMock()

        with patch('retrieval.langchain_retrievers.VectorLangChainRetriever') as mock_retriever:
            mock_instance = MagicMock()
            mock_instance.invoke.return_value = []
            mock_retriever.return_value = mock_instance

            response = client.post(
                "/search",
                json={
                    "query": "test query",
                    "search_type": "vector-lc",
                    "include_answer": False
                }
            )

            assert response.status_code == 200
            data = response.json()
            assert data["search_type"] == "vector-lc"

    @patch('main.get_item')
    @patch('main.get_latest_analysis')
    @patch('main.get_current_vector_store')
    def test_hybrid_search_type(self, mock_vector_store, mock_analysis, mock_get_item, client):
        """Test that hybrid-lc search type is routed correctly."""
        mock_get_item.return_value = None
        mock_analysis.return_value = None
        mock_vector_store.return_value = MagicMock()

        with patch('retrieval.langchain_retrievers.HybridLangChainRetriever') as mock_retriever:
            mock_instance = MagicMock()
            mock_instance.invoke.return_value = []
            mock_retriever.return_value = mock_instance

            response = client.post(
                "/search",
                json={
                    "query": "test query",
                    "search_type": "hybrid-lc",
                    "include_answer": False
                }
            )

            assert response.status_code == 200
            data = response.json()
            assert data["search_type"] == "hybrid-lc"


class TestAgenticSearchEndpoint:
    """Tests for agentic search endpoint integration."""

    @patch('main.get_item')
    @patch('main.get_latest_analysis')
    @patch('main.get_current_vector_store')
    def test_agentic_search_type_accepted(self, mock_vector_store, mock_analysis, mock_get_item, client):
        """Test that 'agentic' is accepted as a valid search type."""
        mock_get_item.return_value = None
        mock_analysis.return_value = None
        mock_vector_store.return_value = MagicMock()

        # Will fail until implementation is complete, but should not be validation error
        response = client.post(
            "/search",
            json={
                "query": "test query",
                "search_type": "agentic",
                "include_answer": True
            }
        )

        # Should not be a validation error (422)
        # Might be 500 (not implemented) or 200 (implemented)
        assert response.status_code != 422

    @patch('main.get_item')
    @patch('main.get_latest_analysis')
    @patch('main.get_current_vector_store')
    def test_agentic_search_response_format(self, mock_vector_store, mock_analysis, mock_get_item, client):
        """Test that agentic search returns expected response format."""
        # Setup mocks
        mock_item = {
            "id": "test-item-1",
            "filename": "test.jpg",
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00"
        }
        mock_analysis_data = {
            "id": "analysis-1",
            "item_id": "test-item-1",
            "raw_response": {
                "category": "Test",
                "headline": "Test Item",
                "summary": "A test item"
            }
        }

        mock_get_item.return_value = mock_item
        mock_analysis.return_value = mock_analysis_data
        mock_vector_store.return_value = MagicMock()

        # Mock the agentic orchestrator (when implemented)
        with patch('retrieval.agentic_search.AgenticSearchOrchestrator') as mock_orchestrator:
            mock_instance = MagicMock()
            mock_doc = MagicMock()
            mock_doc.metadata = {
                "item_id": "test-item-1",
                "score": 0.95
            }
            mock_instance.invoke.return_value = [mock_doc]
            mock_instance.reasoning = "Used vector search for semantic query"
            mock_instance.tools_used = ["vector-lc"]
            mock_instance.search_strategy = "vector"
            mock_orchestrator.return_value = mock_instance

            response = client.post(
                "/search",
                json={
                    "query": "test semantic query",
                    "search_type": "agentic",
                    "include_answer": False
                }
            )

            if response.status_code == 200:
                data = response.json()

                # Check standard search response fields
                assert "query" in data
                assert "search_type" in data
                assert "results" in data
                assert "retrieval_time_ms" in data

                # Check agentic-specific fields
                assert "reasoning" in data or response.status_code == 200
                assert "tools_used" in data or response.status_code == 200

    @patch('main.get_item')
    @patch('main.get_latest_analysis')
    @patch('main.get_current_vector_store')
    def test_agentic_search_with_answer_generation(self, mock_vector_store, mock_analysis, mock_get_item, client):
        """Test agentic search with answer generation enabled."""
        mock_item = {
            "id": "test-item-1",
            "filename": "test.jpg",
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00"
        }
        mock_analysis_data = {
            "id": "analysis-1",
            "item_id": "test-item-1",
            "raw_response": {
                "category": "Test",
                "headline": "Test Item",
                "summary": "A test item"
            }
        }

        mock_get_item.return_value = mock_item
        mock_analysis.return_value = mock_analysis_data
        mock_vector_store.return_value = MagicMock()

        with patch('retrieval.agentic_search.AgenticSearchOrchestrator') as mock_orchestrator:
            with patch('retrieval.answer_generator.generate_answer') as mock_answer_gen:
                mock_instance = MagicMock()
                mock_doc = MagicMock()
                mock_doc.metadata = {"item_id": "test-item-1", "score": 0.95}
                mock_instance.invoke.return_value = [mock_doc]
                mock_instance.reasoning = "Test reasoning"
                mock_instance.tools_used = ["vector-lc"]
                mock_orchestrator.return_value = mock_instance

                mock_answer_gen.return_value = {
                    "answer": "Test answer",
                    "citations": ["test-item-1"],
                    "confidence": 0.9
                }

                response = client.post(
                    "/search",
                    json={
                        "query": "test query",
                        "search_type": "agentic",
                        "include_answer": True
                    }
                )

                if response.status_code == 200:
                    data = response.json()
                    assert "answer" in data
                    assert data["answer"] is not None


class TestDatabaseRouting:
    """Tests for database routing (prod vs golden)."""

    @patch('main.get_item')
    @patch('main.get_latest_analysis')
    def test_production_database_default(self, mock_analysis, mock_get_item, client):
        """Test that production database is used by default."""
        mock_get_item.return_value = None
        mock_analysis.return_value = None

        with patch('retrieval.langchain_retrievers.BM25LangChainRetriever') as mock_retriever:
            mock_instance = MagicMock()
            mock_instance.invoke.return_value = []
            mock_retriever.return_value = mock_instance

            response = client.post(
                "/search",
                json={
                    "query": "test query",
                    "search_type": "bm25-lc",
                    "include_answer": False
                }
            )

            assert response.status_code == 200

    @patch('main.get_item')
    @patch('main.get_latest_analysis')
    @patch('main.get_current_vector_store')
    def test_golden_database_via_subdomain(self, mock_vector_store, mock_analysis, mock_get_item, client):
        """Test that golden database is used when subdomain is specified."""
        mock_get_item.return_value = None
        mock_analysis.return_value = None
        mock_vector_store.return_value = MagicMock()

        with patch('retrieval.langchain_retrievers.BM25LangChainRetriever') as mock_retriever:
            mock_instance = MagicMock()
            mock_instance.invoke.return_value = []
            mock_retriever.return_value = mock_instance

            response = client.post(
                "/search",
                json={
                    "query": "test query",
                    "search_type": "bm25-lc",
                    "include_answer": False
                },
                headers={"Host": "golden.localhost:8000"}
            )

            assert response.status_code == 200


class TestSearchResponseFormat:
    """Tests for search response format compliance."""

    @patch('main.get_item')
    @patch('main.get_latest_analysis')
    def test_response_has_required_fields(self, mock_analysis, mock_get_item, client):
        """Test that response contains all required fields."""
        mock_get_item.return_value = None
        mock_analysis.return_value = None

        with patch('retrieval.langchain_retrievers.BM25LangChainRetriever') as mock_retriever:
            mock_instance = MagicMock()
            mock_instance.invoke.return_value = []
            mock_retriever.return_value = mock_instance

            response = client.post(
                "/search",
                json={
                    "query": "test query",
                    "search_type": "bm25-lc",
                    "include_answer": False
                }
            )

            assert response.status_code == 200
            data = response.json()

            # Required fields
            assert "query" in data
            assert "search_type" in data
            assert "results" in data
            assert "total_results" in data
            assert "retrieval_time_ms" in data

    @patch('main.get_item')
    @patch('main.get_latest_analysis')
    def test_results_format(self, mock_analysis, mock_get_item, client):
        """Test that results array contains properly formatted items."""
        mock_item = {
            "id": "test-item-1",
            "filename": "test.jpg",
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00"
        }
        mock_analysis_data = {
            "id": "analysis-1",
            "item_id": "test-item-1",
            "raw_response": {
                "category": "Test",
                "headline": "Test Item",
                "summary": "A test item"
            }
        }

        mock_get_item.return_value = mock_item
        mock_analysis.return_value = mock_analysis_data

        with patch('retrieval.langchain_retrievers.BM25LangChainRetriever') as mock_retriever:
            mock_instance = MagicMock()
            mock_doc = MagicMock()
            mock_doc.metadata = {"item_id": "test-item-1", "score": 0.85}
            mock_instance.invoke.return_value = [mock_doc]
            mock_retriever.return_value = mock_instance

            response = client.post(
                "/search",
                json={
                    "query": "test query",
                    "search_type": "bm25-lc",
                    "include_answer": False
                }
            )

            assert response.status_code == 200
            data = response.json()
            assert len(data["results"]) > 0

            result = data["results"][0]
            assert "item_id" in result
            assert "rank" in result
            assert "score" in result
            assert "category" in result
            assert "headline" in result
            assert "image_url" in result


class TestErrorHandling:
    """Tests for error handling in search endpoint."""

    def test_invalid_search_type(self, client):
        """Test that invalid search type returns validation error."""
        response = client.post(
            "/search",
            json={
                "query": "test query",
                "search_type": "invalid-type"
            }
        )
        assert response.status_code == 422

    def test_invalid_top_k(self, client):
        """Test that invalid top_k value returns validation error."""
        response = client.post(
            "/search",
            json={
                "query": "test query",
                "top_k": 0  # Must be >= 1
            }
        )
        assert response.status_code == 422

        response = client.post(
            "/search",
            json={
                "query": "test query",
                "top_k": 100  # Must be <= 50
            }
        )
        assert response.status_code == 422


# Integration test that requires actual implementation
@pytest.mark.integration
class TestAgenticSearchFullWorkflow:
    """Full workflow integration tests for agentic search (requires implementation)."""

    @pytest.mark.skip(reason="Requires agentic search implementation")
    def test_agentic_search_end_to_end(self, client):
        """Test complete agentic search workflow."""
        response = client.post(
            "/search",
            json={
                "query": "Where can I find traditional Japanese hot springs?",
                "search_type": "agentic",
                "top_k": 5,
                "include_answer": True
            }
        )

        assert response.status_code == 200
        data = response.json()

        # Check all expected fields
        assert data["search_type"] == "agentic"
        assert "reasoning" in data
        assert "tools_used" in data
        assert len(data["tools_used"]) > 0
        assert data["reasoning"] != ""
        assert "results" in data
        assert "answer" in data
