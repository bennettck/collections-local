"""
Unit tests for Cognito JWT authentication middleware.

Tests cover:
- JWT token validation
- User ID extraction from 'sub' claim
- Unauthorized request handling
- Public endpoint access
- Mock token generation and validation
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from fastapi import FastAPI, Request, HTTPException
from fastapi.testclient import TestClient
from jose import jwt
import time
import json

from app.middleware.auth import CognitoAuthMiddleware, get_current_user


# Test configuration
TEST_USER_POOL_ID = "us-east-1_TestPool123"
TEST_REGION = "us-east-1"
TEST_CLIENT_ID = "test-client-id-123"
TEST_USER_ID = "test-user-12345"


# Mock JWKS response
MOCK_JWKS = {
    "keys": [
        {
            "alg": "RS256",
            "e": "AQAB",
            "kid": "test-key-id",
            "kty": "RSA",
            "n": "test-modulus",
            "use": "sig"
        }
    ]
}


@pytest.fixture
def app():
    """Create a test FastAPI app with auth middleware."""
    test_app = FastAPI()

    # Add auth middleware
    test_app.add_middleware(
        CognitoAuthMiddleware,
        user_pool_id=TEST_USER_POOL_ID,
        region=TEST_REGION,
        client_id=TEST_CLIENT_ID,
        enabled=True,
    )

    @test_app.get("/health")
    async def health():
        """Public endpoint."""
        return {"status": "healthy"}

    @test_app.get("/protected")
    async def protected(request: Request):
        """Protected endpoint that requires auth."""
        user_id = request.state.user_id
        return {"user_id": user_id, "authenticated": True}

    @test_app.get("/current-user")
    async def current_user_endpoint(request: Request):
        """Endpoint using get_current_user dependency."""
        user_id = get_current_user(request)
        return {"user_id": user_id}

    return test_app


@pytest.fixture
def app_disabled_auth():
    """Create a test FastAPI app with auth disabled."""
    test_app = FastAPI()

    test_app.add_middleware(
        CognitoAuthMiddleware,
        user_pool_id=TEST_USER_POOL_ID,
        region=TEST_REGION,
        client_id=TEST_CLIENT_ID,
        enabled=False,  # Disabled for local dev
    )

    @test_app.get("/protected")
    async def protected(request: Request):
        """Protected endpoint."""
        user_id = request.state.user_id
        return {"user_id": user_id, "authenticated": request.state.authenticated}

    return test_app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def client_disabled_auth(app_disabled_auth):
    """Create a test client with auth disabled."""
    return TestClient(app_disabled_auth)


@pytest.fixture
def mock_valid_token():
    """Create a mock valid JWT token."""
    # Mock token claims
    claims = {
        "sub": TEST_USER_ID,
        "token_use": "access",
        "aud": TEST_CLIENT_ID,
        "iss": f"https://cognito-idp.{TEST_REGION}.amazonaws.com/{TEST_USER_POOL_ID}",
        "exp": int(time.time()) + 3600,  # Expires in 1 hour
        "iat": int(time.time()),
    }

    # Create token with additional headers to include 'kid'
    # We'll mock the validation, so signature doesn't matter
    additional_headers = {"kid": "test-key-id"}
    token = jwt.encode(claims, "secret", algorithm="HS256", headers=additional_headers)
    return token, claims


class TestCognitoAuthMiddleware:
    """Test suite for Cognito authentication middleware."""

    def test_public_endpoint_no_auth_required(self, client):
        """Test that public endpoints don't require authentication."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    def test_protected_endpoint_without_token(self, client):
        """Test that protected endpoints reject requests without tokens."""
        response = client.get("/protected")
        assert response.status_code == 401
        assert "Missing authorization header" in response.json()["detail"]

    def test_protected_endpoint_with_invalid_header_format(self, client):
        """Test rejection of malformed Authorization headers."""
        # Missing "Bearer" prefix
        response = client.get("/protected", headers={"Authorization": "InvalidToken123"})
        assert response.status_code == 401

        # Empty header
        response = client.get("/protected", headers={"Authorization": ""})
        assert response.status_code == 401

    @patch("app.middleware.auth.CognitoAuthMiddleware._get_jwks")
    @patch("app.middleware.auth.jwt.decode")
    def test_protected_endpoint_with_valid_token(self, mock_jwt_decode, mock_get_jwks, client, mock_valid_token):
        """Test successful authentication with valid token."""
        token, claims = mock_valid_token

        # Mock JWKS fetch
        mock_get_jwks.return_value = MOCK_JWKS

        # Mock JWT decode to return our claims
        mock_jwt_decode.return_value = claims

        # Make request with valid token
        response = client.get(
            "/protected",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == TEST_USER_ID
        assert data["authenticated"] is True

    @patch("app.middleware.auth.CognitoAuthMiddleware._get_jwks")
    @patch("app.middleware.auth.jwt.decode")
    def test_user_id_extraction(self, mock_jwt_decode, mock_get_jwks, client, mock_valid_token):
        """Test that user_id is correctly extracted from 'sub' claim."""
        token, claims = mock_valid_token

        mock_get_jwks.return_value = MOCK_JWKS
        mock_jwt_decode.return_value = claims

        response = client.get(
            "/protected",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        assert response.json()["user_id"] == TEST_USER_ID

    @patch("app.middleware.auth.CognitoAuthMiddleware._get_jwks")
    @patch("app.middleware.auth.jwt.decode")
    def test_missing_sub_claim(self, mock_jwt_decode, mock_get_jwks, client, mock_valid_token):
        """Test rejection of tokens without 'sub' claim."""
        token, claims = mock_valid_token

        # Remove 'sub' claim
        claims_without_sub = {k: v for k, v in claims.items() if k != "sub"}

        mock_get_jwks.return_value = MOCK_JWKS
        mock_jwt_decode.return_value = claims_without_sub

        response = client.get(
            "/protected",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 401
        assert "Missing 'sub' claim" in response.json()["detail"]

    @patch("app.middleware.auth.CognitoAuthMiddleware._get_jwks")
    @patch("app.middleware.auth.jwt.decode")
    def test_invalid_token_use(self, mock_jwt_decode, mock_get_jwks, client, mock_valid_token):
        """Test rejection of tokens with invalid token_use claim."""
        token, claims = mock_valid_token

        # Set invalid token_use
        claims["token_use"] = "refresh"

        mock_get_jwks.return_value = MOCK_JWKS
        mock_jwt_decode.return_value = claims

        response = client.get(
            "/protected",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 401
        assert "Invalid token_use" in response.json()["detail"]

    @patch("app.middleware.auth.CognitoAuthMiddleware._get_jwks")
    @patch("app.middleware.auth.jwt.decode")
    def test_expired_token(self, mock_jwt_decode, mock_get_jwks, client, mock_valid_token):
        """Test rejection of expired tokens."""
        from jose.exceptions import ExpiredSignatureError

        token, claims = mock_valid_token

        mock_get_jwks.return_value = MOCK_JWKS
        mock_jwt_decode.side_effect = ExpiredSignatureError("Token has expired")

        response = client.get(
            "/protected",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 401
        assert "expired" in response.json()["detail"].lower()

    @patch("app.middleware.auth.CognitoAuthMiddleware._get_jwks")
    def test_jwks_fetch_failure(self, mock_get_jwks, client, mock_valid_token):
        """Test handling of JWKS fetch failures."""
        token, _ = mock_valid_token

        # Simulate JWKS fetch failure
        mock_get_jwks.side_effect = HTTPException(
            status_code=500,
            detail="Unable to fetch token validation keys"
        )

        response = client.get(
            "/protected",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 500

    def test_auth_disabled_mode(self, client_disabled_auth):
        """Test that auth can be disabled for local development."""
        response = client_disabled_auth.get("/protected")

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "local-dev-user"
        assert data["authenticated"] is False

    @patch("app.middleware.auth.CognitoAuthMiddleware._get_jwks")
    @patch("app.middleware.auth.jwt.decode")
    def test_get_current_user_dependency(self, mock_jwt_decode, mock_get_jwks, client, mock_valid_token):
        """Test the get_current_user dependency function."""
        token, claims = mock_valid_token

        mock_get_jwks.return_value = MOCK_JWKS
        mock_jwt_decode.return_value = claims

        response = client.get(
            "/current-user",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        assert response.json()["user_id"] == TEST_USER_ID

    def test_get_current_user_unauthenticated(self, client):
        """Test get_current_user raises error when not authenticated."""
        # This endpoint will fail because no token is provided
        response = client.get("/current-user")
        assert response.status_code == 401


class TestJWKSValidation:
    """Test JWKS key validation logic."""

    def test_find_jwk_with_matching_kid(self):
        """Test finding JWK with matching key ID."""
        middleware = CognitoAuthMiddleware(
            app=FastAPI(),
            user_pool_id=TEST_USER_POOL_ID,
            region=TEST_REGION,
        )

        jwk = middleware._find_jwk(MOCK_JWKS, "test-key-id")
        assert jwk is not None
        assert jwk["kid"] == "test-key-id"

    def test_find_jwk_with_no_matching_kid(self):
        """Test that None is returned when key ID doesn't match."""
        middleware = CognitoAuthMiddleware(
            app=FastAPI(),
            user_pool_id=TEST_USER_POOL_ID,
            region=TEST_REGION,
        )

        jwk = middleware._find_jwk(MOCK_JWKS, "non-existent-key-id")
        assert jwk is None


class TestPublicEndpoints:
    """Test public endpoint detection."""

    def test_exact_match_public_endpoints(self, client):
        """Test that exact match public endpoints are accessible."""
        public_endpoints = ["/health", "/docs", "/openapi.json", "/redoc"]

        for endpoint in public_endpoints:
            if endpoint in ["/docs", "/redoc"]:
                # These might return 200 or 404 depending on FastAPI setup
                response = client.get(endpoint)
                # Just verify we don't get 401 Unauthorized
                assert response.status_code != 401
            else:
                response = client.get(endpoint)
                assert response.status_code != 401

    def test_static_prefix_public_endpoints(self, client):
        """Test that /static/* endpoints are public."""
        # The endpoint might not exist, but it should not trigger auth error
        response = client.get("/static/test.css")
        # Should get 404 Not Found, not 401 Unauthorized
        assert response.status_code == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
