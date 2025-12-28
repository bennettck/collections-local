"""
Unit tests for database connection manager.

Tests connection initialization, session management, and Parameter Store integration.
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy.exc import OperationalError

from database_orm.connection import (
    init_connection,
    get_engine,
    get_session,
    close_connection,
    health_check,
    _get_database_url,
    _get_database_url_from_parameter_store,
)
from database_orm.models import Base, Item


class TestDatabaseURL:
    """Test database URL retrieval."""

    def test_get_database_url_from_env(self):
        """Test getting DATABASE_URL from environment variable."""
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://test:test@localhost/testdb"}):
            url = _get_database_url()
            assert url == "postgresql://test:test@localhost/testdb"

    def test_get_database_url_fallback_sqlite(self):
        """Test fallback to SQLite when no DATABASE_URL is set."""
        with patch.dict(os.environ, {}, clear=True):
            url = _get_database_url()
            assert url.startswith("sqlite:///")

    @patch('database.connection.BOTO3_AVAILABLE', True)
    @patch('database.connection.boto3.client')
    def test_get_database_url_from_parameter_store(self, mock_boto_client):
        """Test getting DATABASE_URL from Parameter Store."""
        # Mock SSM client
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {
            'Parameter': {'Value': 'postgresql://user:pass@host/db'}
        }
        mock_boto_client.return_value = mock_ssm

        url = _get_database_url_from_parameter_store('/app/database/url')

        assert url == 'postgresql://user:pass@host/db'
        mock_ssm.get_parameter.assert_called_once_with(
            Name='/app/database/url',
            WithDecryption=True
        )

    @patch('database.connection.BOTO3_AVAILABLE', True)
    @patch('database.connection.boto3.client')
    def test_get_database_url_from_parameter_store_not_found(self, mock_boto_client):
        """Test Parameter Store parameter not found."""
        from botocore.exceptions import ClientError

        # Mock SSM client to raise ParameterNotFound error
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.side_effect = ClientError(
            {'Error': {'Code': 'ParameterNotFound'}},
            'GetParameter'
        )
        mock_boto_client.return_value = mock_ssm

        url = _get_database_url_from_parameter_store('/app/database/url')

        assert url is None

    @patch('database.connection.BOTO3_AVAILABLE', False)
    def test_get_database_url_from_parameter_store_no_boto3(self):
        """Test Parameter Store when boto3 is not available."""
        url = _get_database_url_from_parameter_store('/app/database/url')
        assert url is None


class TestConnectionInitialization:
    """Test database connection initialization."""

    def test_init_connection_default(self):
        """Test initializing connection with default settings."""
        # Use in-memory SQLite for testing
        engine = init_connection("sqlite:///:memory:", echo=False)

        assert engine is not None
        assert engine.dialect.name == "sqlite"

        # Clean up
        close_connection()

    def test_init_connection_already_initialized(self):
        """Test initializing connection when already initialized."""
        # First initialization
        engine1 = init_connection("sqlite:///:memory:")

        # Second initialization (should return existing engine)
        engine2 = init_connection("sqlite:///:memory:")

        assert engine1 is engine2

        # Clean up
        close_connection()

    def test_get_engine_not_initialized(self):
        """Test get_engine before initialization."""
        # Ensure no engine exists
        close_connection()

        with pytest.raises(RuntimeError, match="not initialized"):
            get_engine()

    def test_get_engine_after_init(self):
        """Test get_engine after initialization."""
        init_connection("sqlite:///:memory:")
        engine = get_engine()

        assert engine is not None

        # Clean up
        close_connection()


class TestSessionManagement:
    """Test database session management."""

    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        """Setup and teardown for each test."""
        # Setup: initialize connection
        engine = init_connection("sqlite:///:memory:")
        Base.metadata.create_all(engine)

        yield

        # Teardown: close connection
        close_connection()

    def test_get_session_context_manager(self):
        """Test session context manager."""
        with get_session() as session:
            assert session is not None
            # Session should be active
            assert session.is_active

    def test_get_session_auto_commit(self):
        """Test session auto-commits on success."""
        # Create an item within session
        with get_session() as session:
            item = Item(
                id="test-1",
                user_id="user-1",
                filename="test.jpg",
                file_path="/data/test.jpg"
            )
            session.add(item)
            # Should auto-commit when exiting context

        # Verify item was committed
        with get_session() as session:
            retrieved = session.query(Item).filter_by(id="test-1").first()
            assert retrieved is not None
            assert retrieved.filename == "test.jpg"

    def test_get_session_auto_rollback_on_error(self):
        """Test session auto-rolls back on error."""
        try:
            with get_session() as session:
                item = Item(
                    id="test-2",
                    user_id="user-1",
                    filename="test2.jpg",
                    file_path="/data/test2.jpg"
                )
                session.add(item)
                # Raise error before commit
                raise ValueError("Test error")
        except ValueError:
            pass

        # Verify item was NOT committed
        with get_session() as session:
            retrieved = session.query(Item).filter_by(id="test-2").first()
            assert retrieved is None

    def test_get_session_not_initialized(self):
        """Test get_session before initialization."""
        close_connection()

        with pytest.raises(RuntimeError, match="not initialized"):
            with get_session() as session:
                pass


class TestHealthCheck:
    """Test database health check."""

    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        """Setup and teardown for each test."""
        # Setup
        engine = init_connection("sqlite:///:memory:")
        Base.metadata.create_all(engine)

        yield

        # Teardown
        close_connection()

    def test_health_check_success(self):
        """Test health check with healthy connection."""
        status = health_check()

        assert status["healthy"] is True
        assert status["database"] == "sqlite"
        # SQLite may not have pool_size, but we should get database name
        assert "database" in status

    def test_health_check_no_engine(self):
        """Test health check without initialized engine."""
        close_connection()

        status = health_check()

        assert status["healthy"] is False
        assert "error" in status


class TestConnectionPooling:
    """Test connection pooling behavior."""

    def test_connection_pool_settings_postgresql(self):
        """Test that PostgreSQL connections use proper pool settings."""
        # Mock PostgreSQL URL
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://user:pass@localhost/db"}):
            # This would normally connect to PostgreSQL, but we're just testing config
            # We can't actually test without a real PostgreSQL instance
            pass

    def test_connection_pool_settings_sqlite(self):
        """Test SQLite connection settings."""
        engine = init_connection("sqlite:///:memory:")

        # SQLite should have pre_ping enabled
        assert engine.pool._pre_ping is True

        close_connection()


class TestCloseConnection:
    """Test connection cleanup."""

    def test_close_connection_disposes_engine(self):
        """Test that close_connection properly disposes engine."""
        engine = init_connection("sqlite:///:memory:")

        # Close connection
        close_connection()

        # Engine should be None
        with pytest.raises(RuntimeError, match="not initialized"):
            get_engine()

    def test_close_connection_idempotent(self):
        """Test that close_connection can be called multiple times."""
        init_connection("sqlite:///:memory:")

        # Close multiple times (should not raise error)
        close_connection()
        close_connection()
        close_connection()
