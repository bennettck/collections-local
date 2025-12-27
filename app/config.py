"""
Configuration module for loading secrets from AWS Parameter Store.

This module provides a cached, thread-safe mechanism for loading configuration
from AWS Systems Manager Parameter Store, with fallback to environment variables
for local development.
"""

import os
import logging
from typing import Optional, Dict, Any
from functools import lru_cache
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when configuration cannot be loaded."""
    pass


class Config:
    """
    Configuration manager for AWS Parameter Store and environment variables.

    Provides cached access to secrets stored in AWS Systems Manager Parameter Store,
    with automatic fallback to environment variables for local development.

    Usage:
        config = Config()
        anthropic_key = config.get("ANTHROPIC_API_KEY")
        db_host = config.get("DATABASE_HOST")
    """

    def __init__(self, parameter_prefix: str = "/collections", use_local: bool = None):
        """
        Initialize configuration manager.

        Args:
            parameter_prefix: Prefix for Parameter Store keys (default: /collections)
            use_local: Force local mode (env vars only). If None, auto-detect based on AWS_REGION.
        """
        self.parameter_prefix = parameter_prefix
        self._cache: Dict[str, Any] = {}

        # Auto-detect local vs AWS environment
        if use_local is None:
            self.use_local = os.getenv("AWS_REGION") is None
        else:
            self.use_local = use_local

        # Initialize SSM client for AWS environments
        self.ssm_client = None
        if not self.use_local:
            try:
                self.ssm_client = boto3.client("ssm")
                logger.info("Initialized AWS SSM client for Parameter Store")
            except Exception as e:
                logger.warning(f"Failed to initialize SSM client, falling back to env vars: {e}")
                self.use_local = True

    def get(self, key: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
        """
        Get configuration value from Parameter Store or environment variables.

        Order of precedence:
        1. Cache (if already loaded)
        2. Parameter Store (if in AWS environment)
        3. Environment variable
        4. Default value

        Args:
            key: Configuration key (e.g., "ANTHROPIC_API_KEY")
            default: Default value if not found
            required: Raise ConfigError if not found and no default

        Returns:
            Configuration value as string

        Raises:
            ConfigError: If required=True and value not found
        """
        # Check cache first
        if key in self._cache:
            return self._cache[key]

        value = None

        # Try Parameter Store if in AWS environment
        if not self.use_local and self.ssm_client:
            try:
                value = self._get_from_parameter_store(key)
            except Exception as e:
                logger.warning(f"Failed to get {key} from Parameter Store: {e}")

        # Fallback to environment variable
        if value is None:
            value = os.getenv(key)

        # Use default if still not found
        if value is None:
            value = default

        # Raise error if required and not found
        if value is None and required:
            raise ConfigError(f"Required configuration key '{key}' not found")

        # Cache the value
        if value is not None:
            self._cache[key] = value

        return value

    def _get_from_parameter_store(self, key: str) -> Optional[str]:
        """
        Fetch value from AWS Parameter Store.

        Args:
            key: Parameter key (e.g., "ANTHROPIC_API_KEY")

        Returns:
            Parameter value or None if not found
        """
        parameter_name = f"{self.parameter_prefix}/{key}"

        try:
            response = self.ssm_client.get_parameter(
                Name=parameter_name,
                WithDecryption=True  # Decrypt SecureString parameters
            )
            value = response["Parameter"]["Value"]
            logger.debug(f"Loaded {key} from Parameter Store")
            return value
        except ClientError as e:
            if e.response["Error"]["Code"] == "ParameterNotFound":
                logger.debug(f"Parameter {parameter_name} not found in Parameter Store")
                return None
            raise

    def get_database_config(self) -> Dict[str, str]:
        """
        Get database configuration.

        Returns:
            Dict with database connection parameters
        """
        # Check if DATABASE_URL is provided (full connection string)
        database_url = self.get("DATABASE_URL")
        if database_url and database_url != "WILL_BE_SET_BY_CDK":
            return {"DATABASE_URL": database_url}

        # Otherwise, build from individual components
        return {
            "DATABASE_HOST": self.get("DATABASE_HOST", required=True),
            "DATABASE_PORT": self.get("DATABASE_PORT", default="5432"),
            "DATABASE_NAME": self.get("DATABASE_NAME", default="collections"),
            "DATABASE_USERNAME": self.get("DATABASE_USERNAME", required=True),
            "DATABASE_PASSWORD": self.get("DATABASE_PASSWORD", required=True),
        }

    def get_cognito_config(self) -> Dict[str, str]:
        """
        Get Cognito configuration.

        Returns:
            Dict with Cognito parameters
        """
        return {
            "COGNITO_USER_POOL_ID": self.get("COGNITO_USER_POOL_ID", required=True),
            "COGNITO_CLIENT_ID": self.get("COGNITO_CLIENT_ID", required=True),
            "COGNITO_REGION": self.get("COGNITO_REGION", self.get("AWS_REGION", "us-east-1")),
        }

    def get_api_keys(self) -> Dict[str, Optional[str]]:
        """
        Get API keys for external services.

        Returns:
            Dict with API keys (may contain None values)
        """
        return {
            "ANTHROPIC_API_KEY": self.get("ANTHROPIC_API_KEY"),
            "OPENAI_API_KEY": self.get("OPENAI_API_KEY"),
            "VOYAGE_API_KEY": self.get("VOYAGE_API_KEY"),
            "TAVILY_API_KEY": self.get("TAVILY_API_KEY"),
            "LANGSMITH_API_KEY": self.get("LANGSMITH_API_KEY"),
        }

    def clear_cache(self):
        """Clear the configuration cache."""
        self._cache.clear()
        logger.info("Configuration cache cleared")


# Global singleton instance
@lru_cache(maxsize=1)
def get_config() -> Config:
    """
    Get the global Config instance (cached).

    Returns:
        Config singleton instance
    """
    return Config()
