"""
Integration tests for API endpoints.

These tests are designed to run against the deployed AWS infrastructure
with real Cognito authentication, S3, and PostgreSQL.

To run these tests:
    pytest tests/integration/test_api_endpoints.py -v

Prerequisites:
- Infrastructure deployed (cdk deploy)
- API_BASE_URL environment variable set (e.g., https://xxx.execute-api.us-east-1.amazonaws.com)
- COGNITO_USER_POOL_ID environment variable set
- COGNITO_CLIENT_ID environment variable set
- Test user credentials configured
"""

import os
import uuid
import pytest
import requests
from pathlib import Path
from typing import Dict, Any


# Test configuration
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID")
COGNITO_CLIENT_ID = os.getenv("COGNITO_CLIENT_ID")
TEST_USER_EMAIL = os.getenv("TEST_USER_EMAIL")
TEST_USER_PASSWORD = os.getenv("TEST_USER_PASSWORD")


@pytest.fixture(scope="module")
def auth_token():
    """
    Get Cognito JWT token for test user.

    In real implementation, this would use boto3 to authenticate:
    - cognito-idp.initiate_auth() with USER_PASSWORD_AUTH
    - Return the IdToken from the response

    For now, this is a placeholder that returns None (tests will be skipped).
    """
    if not all([COGNITO_USER_POOL_ID, COGNITO_CLIENT_ID, TEST_USER_EMAIL, TEST_USER_PASSWORD]):
        pytest.skip("Cognito credentials not configured - set environment variables")

    # TODO: Implement actual Cognito authentication
    # import boto3
    # client = boto3.client('cognito-idp')
    # response = client.initiate_auth(
    #     ClientId=COGNITO_CLIENT_ID,
    #     AuthFlow='USER_PASSWORD_AUTH',
    #     AuthParameters={
    #         'USERNAME': TEST_USER_EMAIL,
    #         'PASSWORD': TEST_USER_PASSWORD
    #     }
    # )
    # return response['AuthenticationResult']['IdToken']

    pytest.skip("Cognito authentication not yet implemented")


@pytest.fixture(scope="module")
def headers(auth_token):
    """HTTP headers with authentication."""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }


@pytest.fixture
def sample_image_path():
    """Path to a sample test image."""
    test_images_dir = Path(__file__).parent.parent / "fixtures" / "images"
    if not test_images_dir.exists():
        pytest.skip("Test images directory not found")

    image_files = list(test_images_dir.glob("*.jpg")) + list(test_images_dir.glob("*.png"))
    if not image_files:
        pytest.skip("No test images found")

    return image_files[0]


class TestHealthEndpoint:
    """Test health check endpoint (public, no auth required)."""

    def test_health_check(self):
        """Health endpoint should return 200 without authentication."""
        response = requests.get(f"{API_BASE_URL}/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data


class TestItemEndpoints:
    """Test item CRUD operations with authentication and S3 integration."""

    def test_create_item_with_s3_upload(self, headers, sample_image_path):
        """POST /items should upload to S3 and create database record."""
        with open(sample_image_path, "rb") as f:
            files = {"file": (sample_image_path.name, f, "image/jpeg")}
            response = requests.post(
                f"{API_BASE_URL}/items",
                headers={"Authorization": headers["Authorization"]},
                files=files
            )

        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert "filename" in data
        assert "created_at" in data

        # Store item_id for cleanup
        return data["id"]

    def test_create_item_unauthorized(self, sample_image_path):
        """POST /items without auth should return 401."""
        with open(sample_image_path, "rb") as f:
            files = {"file": (sample_image_path.name, f, "image/jpeg")}
            response = requests.post(
                f"{API_BASE_URL}/items",
                files=files
            )

        assert response.status_code == 401

    def test_list_items(self, headers):
        """GET /items should return paginated items for authenticated user."""
        response = requests.get(
            f"{API_BASE_URL}/items?limit=10&offset=0",
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)

    def test_get_item(self, headers):
        """GET /items/{item_id} should return item details."""
        # This assumes at least one item exists
        # In real test, create an item first
        pytest.skip("Requires item creation first")

    def test_get_item_unauthorized(self):
        """GET /items/{item_id} without auth should return 401."""
        fake_id = str(uuid.uuid4())
        response = requests.get(f"{API_BASE_URL}/items/{fake_id}")
        assert response.status_code == 401

    def test_user_isolation(self, headers):
        """User should only see their own items, not others'."""
        # This test requires multiple test users
        # TODO: Implement with second test user
        pytest.skip("Requires multiple test users")

    def test_delete_item(self, headers):
        """DELETE /items/{item_id} should delete from S3 and database."""
        # This requires creating an item first
        pytest.skip("Requires item creation first")


class TestAnalysisEndpoints:
    """Test analysis endpoints with LLM integration."""

    def test_analyze_item(self, headers):
        """POST /items/{item_id}/analyze should trigger LLM analysis."""
        # Requires an item to exist
        pytest.skip("Requires item creation first")

    def test_analyze_item_unauthorized(self):
        """Analysis without auth should return 401."""
        fake_id = str(uuid.uuid4())
        response = requests.post(f"{API_BASE_URL}/items/{fake_id}/analyze")
        assert response.status_code == 401


class TestSearchEndpoints:
    """Test search functionality with different search types."""

    def test_bm25_search(self, headers):
        """POST /search with BM25 should return results."""
        payload = {
            "query": "test query",
            "search_type": "bm25-lc",
            "top_k": 5
        }
        response = requests.post(
            f"{API_BASE_URL}/search",
            headers=headers,
            json=payload
        )

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "total_results" in data

    def test_vector_search(self, headers):
        """POST /search with vector search should return results."""
        payload = {
            "query": "test query",
            "search_type": "vector-lc",
            "top_k": 5
        }
        response = requests.post(
            f"{API_BASE_URL}/search",
            headers=headers,
            json=payload
        )

        assert response.status_code == 200
        data = response.json()
        assert "results" in data

    def test_hybrid_search(self, headers):
        """POST /search with hybrid search should return results."""
        payload = {
            "query": "test query",
            "search_type": "hybrid-lc",
            "top_k": 5
        }
        response = requests.post(
            f"{API_BASE_URL}/search",
            headers=headers,
            json=payload
        )

        assert response.status_code == 200
        data = response.json()
        assert "results" in data


class TestImageServing:
    """Test image serving with pre-signed URLs."""

    def test_serve_image_authenticated(self, headers):
        """GET /images/{filename} should return pre-signed URL or image."""
        # This test depends on having an uploaded image
        pytest.skip("Requires uploaded image")

    def test_serve_image_unauthorized(self):
        """Images should require authentication."""
        response = requests.get(f"{API_BASE_URL}/images/nonexistent.jpg")
        # Depending on implementation, this might return 401 or 404
        assert response.status_code in [401, 404]


class TestChatEndpoints:
    """Test multi-turn chat with DynamoDB checkpointing."""

    def test_chat_create_session(self, headers):
        """POST /chat should create new conversation session."""
        payload = {
            "message": "Hello, what items do I have?",
            "session_id": str(uuid.uuid4())
        }
        response = requests.post(
            f"{API_BASE_URL}/chat",
            headers=headers,
            json=payload
        )

        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert "message" in data

    def test_chat_multi_turn(self, headers):
        """Chat should maintain context across multiple turns."""
        session_id = str(uuid.uuid4())

        # First message
        response1 = requests.post(
            f"{API_BASE_URL}/chat",
            headers=headers,
            json={"message": "Show me landscape photos", "session_id": session_id}
        )
        assert response1.status_code == 200

        # Follow-up message (should have context)
        response2 = requests.post(
            f"{API_BASE_URL}/chat",
            headers=headers,
            json={"message": "Show me more", "session_id": session_id}
        )
        assert response2.status_code == 200

    def test_chat_unauthorized(self):
        """Chat without auth should return 401."""
        response = requests.post(
            f"{API_BASE_URL}/chat",
            json={"message": "test", "session_id": str(uuid.uuid4())}
        )
        assert response.status_code == 401


@pytest.mark.e2e
class TestEndToEndWorkflow:
    """
    End-to-end workflow tests.

    These tests exercise the full workflow:
    1. Upload image (POST /items)
    2. Trigger analysis (POST /items/{id}/analyze)
    3. Wait for embedding generation
    4. Search for the item
    """

    def test_complete_workflow(self, headers, sample_image_path):
        """
        Complete workflow: upload → analyze → embed → search.

        This is a long-running test that validates the entire pipeline.
        """
        import time

        # Step 1: Upload image
        with open(sample_image_path, "rb") as f:
            files = {"file": (sample_image_path.name, f, "image/jpeg")}
            response = requests.post(
                f"{API_BASE_URL}/items",
                headers={"Authorization": headers["Authorization"]},
                files=files
            )
        assert response.status_code == 200
        item_id = response.json()["id"]

        # Step 2: Trigger analysis
        response = requests.post(
            f"{API_BASE_URL}/items/{item_id}/analyze",
            headers=headers
        )
        assert response.status_code == 200

        # Step 3: Wait for embedding (async workflow)
        # In production, this would poll or use EventBridge notifications
        time.sleep(10)  # Wait for workflow to complete

        # Step 4: Search for the item
        response = requests.post(
            f"{API_BASE_URL}/search",
            headers=headers,
            json={
                "query": sample_image_path.stem,  # Search by filename
                "search_type": "vector-lc",
                "top_k": 10
            }
        )
        assert response.status_code == 200
        results = response.json()["results"]

        # Verify our item is in the results
        item_ids = [r["item_id"] for r in results]
        assert item_id in item_ids, "Uploaded item not found in search results"

        # Cleanup
        requests.delete(f"{API_BASE_URL}/items/{item_id}", headers=headers)


if __name__ == "__main__":
    """
    Run integration tests with verbose output.

    Usage:
        python tests/integration/test_api_endpoints.py
    """
    pytest.main([__file__, "-v", "-s"])
