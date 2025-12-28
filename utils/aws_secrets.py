"""
AWS Secrets Manager integration for secure credential management.

This module provides cached access to database credentials from AWS Secrets Manager,
following the architect pattern for secure credential handling in Lambda environments.
"""

import os
import json
import logging
from functools import lru_cache
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Optional boto3 import for AWS Secrets Manager
try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    logger.warning("boto3 not available - AWS Secrets Manager integration disabled")


@lru_cache(maxsize=1)
def get_database_credentials() -> Dict[str, str]:
    """
    Fetch and cache database credentials from AWS Secrets Manager.

    Uses LRU cache to avoid repeated API calls within the same Lambda execution.
    The cache is cleared between Lambda invocations automatically.

    Returns:
        Dictionary containing database credentials:
        - username: Database username
        - password: Database password
        - host: Database host
        - port: Database port
        - dbname: Database name
        - engine: Database engine (postgres)

    Raises:
        RuntimeError: If boto3 is not available or credentials cannot be retrieved

    Environment Variables:
        DB_SECRET_ARN: ARN of the Secrets Manager secret containing credentials
    """
    if not BOTO3_AVAILABLE:
        raise RuntimeError(
            "boto3 not available - cannot fetch credentials from Secrets Manager. "
            "Install boto3 or set DATABASE_URL environment variable."
        )

    secret_arn = os.environ.get("DB_SECRET_ARN")
    if not secret_arn:
        raise RuntimeError(
            "DB_SECRET_ARN environment variable not set. "
            "Cannot fetch database credentials from Secrets Manager."
        )

    try:
        client = boto3.client('secretsmanager')
        response = client.get_secret_value(SecretId=secret_arn)

        # Parse the secret JSON
        secret_string = response['SecretString']
        credentials = json.loads(secret_string)

        logger.info(f"Successfully retrieved database credentials from Secrets Manager")
        return credentials

    except NoCredentialsError as e:
        raise RuntimeError(
            "AWS credentials not configured. "
            "Ensure Lambda has proper IAM role with secretsmanager:GetSecretValue permission."
        ) from e

    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'ResourceNotFoundException':
            raise RuntimeError(
                f"Secret not found: {secret_arn}. "
                "Verify the secret ARN is correct and the secret exists."
            ) from e
        elif error_code == 'AccessDeniedException':
            raise RuntimeError(
                f"Access denied to secret: {secret_arn}. "
                "Ensure Lambda role has secretsmanager:GetSecretValue permission."
            ) from e
        else:
            raise RuntimeError(
                f"Failed to retrieve secret from Secrets Manager: {e}"
            ) from e

    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Invalid JSON in secret {secret_arn}. "
            "Secret must contain valid JSON with database credentials."
        ) from e

    except Exception as e:
        raise RuntimeError(
            f"Unexpected error retrieving database credentials: {e}"
        ) from e


def get_database_url(use_ssl: bool = True) -> str:
    """
    Construct PostgreSQL database URL from Secrets Manager credentials.

    This function provides three fallback strategies:
    1. Use DATABASE_URL environment variable if set (testing/local override)
    2. Fetch credentials from Secrets Manager using DB_SECRET_ARN
    3. Construct URL from individual DATABASE_* environment variables (legacy)

    Args:
        use_ssl: Whether to require SSL connections (default: True)

    Returns:
        PostgreSQL connection URL string

    Example:
        >>> url = get_database_url()
        >>> # Returns: postgresql://user:pass@host:5432/dbname?sslmode=require
    """
    # Strategy 1: Direct DATABASE_URL override (for testing/local development)
    if database_url := os.getenv("DATABASE_URL"):
        logger.info("Using DATABASE_URL from environment variable")
        return database_url

    # Strategy 2: Fetch from Secrets Manager (recommended for production)
    try:
        creds = get_database_credentials()

        username = creds['username']
        password = creds['password']
        host = creds['host']
        port = creds['port']
        dbname = creds.get('dbname', 'collections')

        # Construct PostgreSQL URL
        ssl_mode = "?sslmode=require" if use_ssl else ""
        url = f"postgresql://{username}:{password}@{host}:{port}/{dbname}{ssl_mode}"

        logger.info(f"Constructed database URL from Secrets Manager credentials")
        return url

    except RuntimeError as e:
        # Log the error but continue to legacy fallback
        logger.warning(f"Failed to get credentials from Secrets Manager: {e}")

    # Strategy 3: Legacy fallback - construct from individual env vars
    host = os.getenv("DATABASE_HOST")
    port = os.getenv("DATABASE_PORT", "5432")
    dbname = os.getenv("DATABASE_NAME", "collections")
    username = os.getenv("DATABASE_USER", "postgres")
    password = os.getenv("DATABASE_PASSWORD")

    if not host:
        raise RuntimeError(
            "Cannot construct database URL: DATABASE_HOST not set. "
            "Set either DATABASE_URL, DB_SECRET_ARN, or DATABASE_HOST."
        )

    if not password:
        logger.warning(
            "DATABASE_PASSWORD not set - connection may fail. "
            "Use DB_SECRET_ARN for secure credential management."
        )

    ssl_mode = "?sslmode=require" if use_ssl else ""
    url = f"postgresql://{username}:{password or ''}@{host}:{port}/{dbname}{ssl_mode}"

    logger.info("Using legacy DATABASE_* environment variables for connection")
    return url


def clear_credentials_cache() -> None:
    """
    Clear the cached database credentials.

    Useful for testing or if credentials are rotated during Lambda execution.
    Note: Lambda cold starts automatically clear the cache.
    """
    get_database_credentials.cache_clear()
    logger.info("Cleared database credentials cache")
