"""Auth middleware for Cognito JWT validation."""

from .auth import CognitoAuthMiddleware

__all__ = ["CognitoAuthMiddleware"]
