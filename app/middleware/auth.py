"""
Cognito JWT authentication middleware for FastAPI.

This middleware validates JWT tokens from AWS Cognito User Pools and extracts
the user_id from the token's 'sub' claim.
"""

import logging
from typing import Optional, Dict, Any
from functools import lru_cache
import boto3
from jose import jwt, JWTError
from jose.exceptions import ExpiredSignatureError, JWTClaimsError
from fastapi import Request, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
import requests

logger = logging.getLogger(__name__)

# HTTP Bearer security scheme
security = HTTPBearer(auto_error=False)


class CognitoAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware for validating AWS Cognito JWT tokens.

    This middleware:
    1. Extracts JWT from Authorization header
    2. Fetches Cognito JWKS (JSON Web Key Set) from AWS
    3. Validates JWT signature and claims
    4. Extracts user_id from 'sub' claim
    5. Stores user_id in request.state for downstream use

    Public endpoints (no auth required):
    - /health
    - /docs
    - /openapi.json
    - /static/*
    """

    # Public endpoints that don't require authentication
    PUBLIC_ENDPOINTS = {
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
    }

    def __init__(
        self,
        app,
        user_pool_id: str,
        region: str,
        client_id: Optional[str] = None,
        enabled: bool = True,
    ):
        """
        Initialize Cognito auth middleware.

        Args:
            app: FastAPI application
            user_pool_id: Cognito User Pool ID
            region: AWS region (e.g., "us-east-1")
            client_id: Cognito App Client ID (optional, for aud claim validation)
            enabled: Enable/disable auth (useful for local dev)
        """
        super().__init__(app)
        self.user_pool_id = user_pool_id
        self.region = region
        self.client_id = client_id
        self.enabled = enabled
        self.jwks_url = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/jwks.json"

        if not enabled:
            logger.warning("Cognito authentication is DISABLED - all requests will be allowed")

    async def dispatch(self, request: Request, call_next):
        """
        Process each request and validate JWT token.

        Args:
            request: FastAPI request
            call_next: Next middleware/endpoint in chain

        Returns:
            Response from next handler

        Raises:
            HTTPException: If authentication fails
        """
        from starlette.responses import JSONResponse

        # Skip auth for public endpoints
        if self._is_public_endpoint(request):
            return await call_next(request)

        # Skip auth if disabled (local dev)
        if not self.enabled:
            request.state.user_id = "local-dev-user"
            request.state.authenticated = False
            return await call_next(request)

        # Extract and validate token
        try:
            token = self._extract_token(request)
            if not token:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Missing authorization header"},
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # Validate JWT and extract claims
            claims = self._validate_token(token)

            # Extract user_id from 'sub' claim
            user_id = claims.get("sub")
            if not user_id:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Missing 'sub' claim in token"},
                    headers={"WWW-Authenticate": "Bearer"},
                )

            # Store user_id in request state for downstream use
            request.state.user_id = user_id
            request.state.authenticated = True
            request.state.token_claims = claims

            logger.debug(f"Authenticated user: {user_id}")

        except HTTPException as e:
            # Convert HTTPException to JSONResponse for middleware
            return JSONResponse(
                status_code=e.status_code,
                content={"detail": e.detail},
                headers=e.headers,
            )
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": f"Authentication failed: {str(e)}"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Continue to next handler
        return await call_next(request)

    def _is_public_endpoint(self, request: Request) -> bool:
        """
        Check if the request is for a public endpoint.

        Args:
            request: FastAPI request

        Returns:
            True if endpoint is public
        """
        path = request.url.path

        # Check exact matches
        if path in self.PUBLIC_ENDPOINTS:
            return True

        # Check prefix matches
        if path.startswith("/static/"):
            return True

        return False

    def _extract_token(self, request: Request) -> Optional[str]:
        """
        Extract JWT token from Authorization header.

        Args:
            request: FastAPI request

        Returns:
            JWT token string or None
        """
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return None

        # Parse "Bearer <token>" format
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None

        return parts[1]

    def _validate_token(self, token: str) -> Dict[str, Any]:
        """
        Validate JWT token against Cognito JWKS.

        Args:
            token: JWT token string

        Returns:
            Decoded token claims

        Raises:
            HTTPException: If token validation fails
        """
        try:
            # Get JWKS from Cognito
            jwks = self._get_jwks()

            # Decode token header to get key ID
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")
            if not kid:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing 'kid' in token header",
                )

            # Find matching key in JWKS
            key = self._find_jwk(jwks, kid)
            if not key:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Unable to find matching public key",
                )

            # Verify token signature and claims
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.client_id,  # Validate aud claim if client_id provided
                options={
                    "verify_signature": True,
                    "verify_aud": self.client_id is not None,
                    "verify_exp": True,
                }
            )

            # Validate token_use claim (should be 'access' or 'id')
            token_use = claims.get("token_use")
            if token_use not in ["access", "id"]:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid token_use: {token_use}",
                )

            return claims

        except ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
            )
        except JWTClaimsError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token claims: {str(e)}",
            )
        except JWTError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {str(e)}",
            )

    @lru_cache(maxsize=1)
    def _get_jwks(self) -> Dict[str, Any]:
        """
        Fetch JWKS from Cognito (cached).

        Returns:
            JWKS dictionary

        Raises:
            HTTPException: If JWKS fetch fails
        """
        try:
            response = requests.get(self.jwks_url, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch JWKS from {self.jwks_url}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to fetch token validation keys",
            )

    def _find_jwk(self, jwks: Dict[str, Any], kid: str) -> Optional[Dict[str, Any]]:
        """
        Find JWK by key ID.

        Args:
            jwks: JWKS dictionary
            kid: Key ID

        Returns:
            JWK dictionary or None
        """
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key
        return None


def get_current_user(request: Request) -> str:
    """
    Get the current authenticated user ID from request state.

    This is a dependency function that can be used in FastAPI endpoints:

    @app.get("/items")
    async def list_items(user_id: str = Depends(get_current_user)):
        # user_id is automatically extracted from JWT
        ...

    Args:
        request: FastAPI request

    Returns:
        User ID from JWT 'sub' claim

    Raises:
        HTTPException: If user is not authenticated
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user_id
