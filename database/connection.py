"""
Database connection manager with AWS Parameter Store integration.

This module provides:
- SQLAlchemy engine creation with connection pooling
- Session management via context managers
- DATABASE_URL loading from AWS Systems Manager Parameter Store
- Proper error handling and connection health checks
"""

import os
import logging
from contextlib import contextmanager
from typing import Optional, Generator
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import Pool

# Optional boto3 import for AWS Parameter Store
try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False

logger = logging.getLogger(__name__)

# Global engine and session factory
_engine: Optional[Engine] = None
_SessionFactory: Optional[sessionmaker] = None


def _get_database_url_from_parameter_store(parameter_name: str) -> Optional[str]:
    """
    Retrieve DATABASE_URL from AWS Systems Manager Parameter Store.

    Args:
        parameter_name: Name of the parameter in Parameter Store

    Returns:
        Database URL string or None if not found/error

    Raises:
        RuntimeError: If boto3 is not available
    """
    if not BOTO3_AVAILABLE:
        logger.warning("boto3 not available, cannot fetch from Parameter Store")
        return None

    try:
        ssm = boto3.client('ssm')
        response = ssm.get_parameter(
            Name=parameter_name,
            WithDecryption=True  # Decrypt SecureString parameters
        )
        database_url = response['Parameter']['Value']
        logger.info(f"Successfully retrieved DATABASE_URL from Parameter Store: {parameter_name}")
        return database_url

    except NoCredentialsError:
        logger.warning("AWS credentials not configured, skipping Parameter Store")
        return None

    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'ParameterNotFound':
            logger.warning(f"Parameter not found in Parameter Store: {parameter_name}")
        else:
            logger.error(f"Error retrieving parameter from Parameter Store: {e}")
        return None

    except Exception as e:
        logger.error(f"Unexpected error retrieving DATABASE_URL from Parameter Store: {e}")
        return None


def _get_database_url() -> str:
    """
    Get DATABASE_URL with secure credential management.

    Priority (Architect Pattern):
    1. DATABASE_URL environment variable (direct override for testing)
    2. AWS Secrets Manager (via DB_SECRET_ARN env var) - RECOMMENDED FOR PRODUCTION
    3. AWS Parameter Store (via PARAMETER_STORE_DB_URL env var) - DEPRECATED
    4. Fallback to SQLite for local development

    Returns:
        Database URL string

    Raises:
        ValueError: If no database URL can be determined
    """
    # Check direct environment variable first (testing/local override)
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        logger.info("Using DATABASE_URL from environment variable")
        return database_url

    # Try Secrets Manager if configured (RECOMMENDED)
    if os.getenv("DB_SECRET_ARN"):
        try:
            from utils.aws_secrets import get_database_url as get_url_from_secrets
            database_url = get_url_from_secrets()
            if database_url:
                logger.info("Using DATABASE_URL from AWS Secrets Manager")
                return database_url
        except Exception as e:
            logger.warning(f"Failed to retrieve DATABASE_URL from Secrets Manager: {e}")
            # Continue to next fallback

    # Try Parameter Store if configured (DEPRECATED - use Secrets Manager)
    parameter_name = os.getenv("PARAMETER_STORE_DB_URL")
    if parameter_name:
        database_url = _get_database_url_from_parameter_store(parameter_name)
        if database_url:
            logger.warning("Using Parameter Store for DATABASE_URL - DEPRECATED, migrate to Secrets Manager")
            return database_url
        logger.warning(f"Failed to retrieve DATABASE_URL from Parameter Store: {parameter_name}")

    # Fallback to SQLite for local development
    logger.warning("No DATABASE_URL found, falling back to SQLite for local development")
    sqlite_path = os.getenv("DATABASE_PATH", "./data/collections.db")
    return f"sqlite:///{sqlite_path}"


@event.listens_for(Pool, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    """Enable foreign keys for SQLite connections."""
    if 'sqlite' in str(type(dbapi_conn)):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def init_connection(database_url: Optional[str] = None, echo: bool = False) -> Engine:
    """
    Initialize database connection and create engine.

    This should be called once at application startup.

    Args:
        database_url: Optional database URL (uses auto-detection if not provided)
        echo: Whether to echo SQL statements (default: False)

    Returns:
        SQLAlchemy Engine instance

    Example:
        >>> engine = init_connection()
        >>> # Or with explicit URL
        >>> engine = init_connection("postgresql://user:pass@host/db")
    """
    global _engine, _SessionFactory

    if _engine is not None:
        logger.warning("Engine already initialized, returning existing engine")
        return _engine

    # Get database URL
    url = database_url or _get_database_url()

    # Create engine with connection pooling
    # Using pre_ping=True to handle stale connections
    engine_kwargs = {
        "echo": echo,
        "pool_pre_ping": True,  # Verify connections before using them
    }

    # For PostgreSQL, use specific pool settings
    # SQLite doesn't support these pool arguments
    if url.startswith("postgresql"):
        engine_kwargs.update({
            "pool_size": 10,        # Connection pool size
            "max_overflow": 20,     # Max connections beyond pool_size
            "pool_recycle": 3600,  # Recycle connections after 1 hour
        })

    _engine = create_engine(url, **engine_kwargs)

    # Create session factory
    _SessionFactory = sessionmaker(
        bind=_engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False  # Don't expire objects after commit
    )

    logger.info(f"Database engine initialized: {url.split('@')[-1] if '@' in url else 'sqlite'}")
    return _engine


def get_engine() -> Engine:
    """
    Get the global SQLAlchemy engine.

    Returns:
        SQLAlchemy Engine instance

    Raises:
        RuntimeError: If engine not initialized (call init_connection first)
    """
    if _engine is None:
        raise RuntimeError(
            "Database engine not initialized. Call init_connection() first."
        )
    return _engine


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Context manager for database sessions.

    Provides automatic session lifecycle management:
    - Creates session
    - Commits on success
    - Rolls back on error
    - Closes session in all cases

    Yields:
        SQLAlchemy Session instance

    Example:
        >>> with get_session() as session:
        ...     item = session.query(Item).filter_by(id=item_id).first()
        ...     # session automatically committed on exit

    Raises:
        RuntimeError: If session factory not initialized
    """
    if _SessionFactory is None:
        raise RuntimeError(
            "Session factory not initialized. Call init_connection() first."
        )

    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def close_connection():
    """
    Close all database connections and dispose of the engine.

    This should be called at application shutdown.
    """
    global _engine, _SessionFactory

    if _engine is not None:
        _engine.dispose()
        _engine = None
        _SessionFactory = None
        logger.info("Database connections closed")


def health_check() -> dict:
    """
    Check database connection health.

    Returns:
        Dictionary with health status information

    Example:
        >>> status = health_check()
        >>> print(status)
        {'healthy': True, 'database': 'postgresql', 'pool_size': 10}
    """
    if _engine is None:
        return {
            "healthy": False,
            "error": "Engine not initialized"
        }

    try:
        with get_session() as session:
            # Execute a simple query to verify connection
            session.execute(text("SELECT 1"))

        # Get pool statistics
        pool = _engine.pool
        pool_stats = {
            "healthy": True,
            "database": _engine.dialect.name,
        }

        # Add pool statistics if available (not all pools support these methods)
        try:
            pool_stats["pool_size"] = pool.size()
            pool_stats["checked_in"] = pool.checkedin()
            pool_stats["checked_out"] = pool.checkedout()
            pool_stats["overflow"] = pool.overflow()
        except (TypeError, AttributeError):
            # SQLite SingletonThreadPool doesn't support these methods
            pass

        return pool_stats

    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return {
            "healthy": False,
            "error": str(e)
        }
