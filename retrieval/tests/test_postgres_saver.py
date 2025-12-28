"""Unit tests for PostgresCheckpointerSaver.

Uses pytest-postgresql or mocking to test without real PostgreSQL infrastructure.
"""

import os
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock

from chat.checkpointers.postgres_saver import (
    PostgresCheckpointerSaver,
    PooledPostgresCheckpointerSaver,
)


# Test fixtures
@pytest.fixture
def mock_connection():
    """Create a mock psycopg connection."""
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    return mock_conn


@pytest.fixture
def mock_postgres_saver():
    """Create a mock PostgresSaver from langgraph."""
    mock_saver = MagicMock()
    mock_saver.setup = MagicMock()
    mock_saver.get_tuple = MagicMock(return_value=None)
    mock_saver.list = MagicMock(return_value=iter([]))
    mock_saver.put = MagicMock(return_value={"configurable": {"thread_id": "test"}})
    mock_saver.put_writes = MagicMock()
    return mock_saver


@pytest.fixture
def sample_checkpoint():
    """Sample checkpoint for testing."""
    return {
        "v": 1,
        "id": "test-checkpoint-123",
        "ts": datetime.utcnow().isoformat(),
        "channel_values": {
            "messages": ["Hello", "World"],
            "state": {"counter": 1}
        },
        "channel_versions": {
            "__start__": 2,
            "messages": 3
        },
        "versions_seen": {
            "__input__": {},
            "__start__": {"__start__": 1}
        }
    }


@pytest.fixture
def sample_metadata():
    """Sample metadata for testing."""
    return {
        "user_id": "user123",
        "source": "test",
        "score": 0.95
    }


@pytest.fixture
def sample_config():
    """Sample config for testing."""
    return {
        "configurable": {
            "thread_id": "user123#session456",
            "checkpoint_ns": ""
        }
    }


class TestPostgresCheckpointerSaverInit:
    """Test PostgresCheckpointerSaver initialization."""

    def test_init_with_connection_string(self):
        """Test initialization with explicit connection string."""
        with patch('chat.checkpointers.postgres_saver.Connection') as mock_conn_class:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn_class.connect.return_value = mock_conn

            saver = PostgresCheckpointerSaver(
                connection_string="postgresql://test:test@localhost:5432/test"
            )
            assert saver._connection_string == "postgresql://test:test@localhost:5432/test"
            assert saver._setup_done is False

    def test_init_without_connection_string_uses_secrets(self):
        """Test initialization without connection string uses aws_secrets."""
        with patch('chat.checkpointers.postgres_saver.Connection') as mock_conn_class:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn_class.connect.return_value = mock_conn

            with patch('utils.aws_secrets.get_database_url') as mock_get_url:
                mock_get_url.return_value = "postgresql://secret:pass@host:5432/db"

                saver = PostgresCheckpointerSaver()
                assert saver._connection_string == "postgresql://secret:pass@host:5432/db"


class TestPostgresCheckpointerSaverOperations:
    """Test checkpoint operations."""

    def test_get_tuple_returns_none_when_not_found(self):
        """Test get_tuple returns None for non-existent checkpoint."""
        with patch('chat.checkpointers.postgres_saver.Connection') as mock_conn_class:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn_class.connect.return_value = mock_conn

            with patch('chat.checkpointers.postgres_saver.PostgresSaver') as MockSaver:
                mock_saver_instance = MagicMock()
                mock_saver_instance.get_tuple.return_value = None
                mock_saver_instance.setup = MagicMock()
                MockSaver.return_value = mock_saver_instance

                saver = PostgresCheckpointerSaver(
                    connection_string="postgresql://test:test@localhost:5432/test"
                )

                config = {"configurable": {"thread_id": "user123#session456"}}
                result = saver.get_tuple(config)

                assert result is None
                mock_saver_instance.get_tuple.assert_called_once_with(config)

    def test_put_stores_checkpoint(self, sample_checkpoint, sample_metadata, sample_config):
        """Test put stores a checkpoint."""
        with patch('chat.checkpointers.postgres_saver.Connection') as mock_conn_class:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn_class.connect.return_value = mock_conn

            with patch('chat.checkpointers.postgres_saver.PostgresSaver') as MockSaver:
                mock_saver_instance = MagicMock()
                mock_saver_instance.put.return_value = sample_config
                mock_saver_instance.setup = MagicMock()
                MockSaver.return_value = mock_saver_instance

                saver = PostgresCheckpointerSaver(
                    connection_string="postgresql://test:test@localhost:5432/test"
                )

                result = saver.put(
                    sample_config,
                    sample_checkpoint,
                    sample_metadata,
                    {}
                )

                assert result == sample_config
                mock_saver_instance.put.assert_called_once_with(
                    sample_config, sample_checkpoint, sample_metadata, {}
                )

    def test_setup_called_on_first_use(self):
        """Test that setup is called on first use."""
        with patch('chat.checkpointers.postgres_saver.Connection') as mock_conn_class:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn_class.connect.return_value = mock_conn

            with patch('chat.checkpointers.postgres_saver.PostgresSaver') as MockSaver:
                mock_saver_instance = MagicMock()
                mock_saver_instance.get_tuple.return_value = None
                mock_saver_instance.setup = MagicMock()
                MockSaver.return_value = mock_saver_instance

                saver = PostgresCheckpointerSaver(
                    connection_string="postgresql://test:test@localhost:5432/test"
                )

                assert saver._setup_done is False

                # First call should trigger setup
                config = {"configurable": {"thread_id": "test"}}
                saver.get_tuple(config)

                mock_saver_instance.setup.assert_called_once()
                assert saver._setup_done is True

    def test_setup_not_called_on_subsequent_use(self):
        """Test that setup is only called once."""
        with patch('chat.checkpointers.postgres_saver.Connection') as mock_conn_class:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn_class.connect.return_value = mock_conn

            with patch('chat.checkpointers.postgres_saver.PostgresSaver') as MockSaver:
                mock_saver_instance = MagicMock()
                mock_saver_instance.get_tuple.return_value = None
                mock_saver_instance.setup = MagicMock()
                MockSaver.return_value = mock_saver_instance

                saver = PostgresCheckpointerSaver(
                    connection_string="postgresql://test:test@localhost:5432/test"
                )

                config = {"configurable": {"thread_id": "test"}}

                # First call
                saver.get_tuple(config)
                # Second call
                saver.get_tuple(config)

                # Setup should only be called once
                assert mock_saver_instance.setup.call_count == 1


class TestPostgresCheckpointerSaverDelete:
    """Test delete operations."""

    def test_delete_thread(self):
        """Test delete_thread removes checkpoints."""
        with patch('chat.checkpointers.postgres_saver.Connection') as mock_conn_class:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn_class.connect.return_value = mock_conn

            with patch('chat.checkpointers.postgres_saver.PostgresSaver') as MockSaver:
                mock_saver_instance = MagicMock()
                mock_saver_instance.setup = MagicMock()
                mock_saver_instance.conn = mock_conn
                MockSaver.return_value = mock_saver_instance

                saver = PostgresCheckpointerSaver(
                    connection_string="postgresql://test:test@localhost:5432/test"
                )

                saver.delete_thread("user123#session456")

                # Verify delete queries were executed
                assert mock_conn.execute.call_count == 3


class TestPooledPostgresCheckpointerSaver:
    """Test pooled connection implementation."""

    def test_init_with_pool_size(self):
        """Test initialization with custom pool size."""
        saver = PooledPostgresCheckpointerSaver(
            connection_string="postgresql://test:test@localhost:5432/test",
            pool_size=20
        )
        assert saver._pool_size == 20
        assert saver._pool is None  # Lazily initialized

    def test_close_pool(self):
        """Test closing the connection pool."""
        with patch('psycopg_pool.ConnectionPool') as MockPool:
            mock_pool = MagicMock()
            MockPool.return_value = mock_pool

            with patch('chat.checkpointers.postgres_saver.PostgresSaver') as MockSaver:
                mock_saver_instance = MagicMock()
                mock_saver_instance.setup = MagicMock()
                MockSaver.return_value = mock_saver_instance

                saver = PooledPostgresCheckpointerSaver(
                    connection_string="postgresql://test:test@localhost:5432/test"
                )

                # Force pool initialization
                saver._ensure_pool()

                # Close the pool
                saver.close()

                mock_pool.close.assert_called_once()
                assert saver._pool is None
                assert saver._saver is None


class TestAsyncMethods:
    """Test async method implementations."""

    @pytest.mark.asyncio
    async def test_aget_tuple_delegates_to_sync(self):
        """Test async get_tuple delegates to sync version."""
        with patch('chat.checkpointers.postgres_saver.Connection') as mock_conn_class:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn_class.connect.return_value = mock_conn

            with patch('chat.checkpointers.postgres_saver.PostgresSaver') as MockSaver:
                mock_saver_instance = MagicMock()
                mock_saver_instance.get_tuple.return_value = None
                mock_saver_instance.setup = MagicMock()
                MockSaver.return_value = mock_saver_instance

                saver = PostgresCheckpointerSaver(
                    connection_string="postgresql://test:test@localhost:5432/test"
                )

                config = {"configurable": {"thread_id": "test"}}
                result = await saver.aget_tuple(config)

                assert result is None
                mock_saver_instance.get_tuple.assert_called_once_with(config)

    @pytest.mark.asyncio
    async def test_aput_delegates_to_sync(self, sample_checkpoint, sample_metadata, sample_config):
        """Test async put delegates to sync version."""
        with patch('chat.checkpointers.postgres_saver.Connection') as mock_conn_class:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn_class.connect.return_value = mock_conn

            with patch('chat.checkpointers.postgres_saver.PostgresSaver') as MockSaver:
                mock_saver_instance = MagicMock()
                mock_saver_instance.put.return_value = sample_config
                mock_saver_instance.setup = MagicMock()
                MockSaver.return_value = mock_saver_instance

                saver = PostgresCheckpointerSaver(
                    connection_string="postgresql://test:test@localhost:5432/test"
                )

                result = await saver.aput(
                    sample_config, sample_checkpoint, sample_metadata, {}
                )

                assert result == sample_config


class TestConversationManagerIntegration:
    """Test integration with ConversationManager."""

    def test_conversation_manager_uses_postgres_saver(self):
        """Test ConversationManager creates PostgresCheckpointerSaver."""
        with patch('chat.checkpointers.postgres_saver.Connection') as mock_conn_class:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn_class.connect.return_value = mock_conn

            from chat.conversation_manager import ConversationManager

            manager = ConversationManager(
                connection_string="postgresql://test:test@localhost:5432/test",
                user_id="test_user"
            )

            checkpointer = manager.get_checkpointer()
            assert isinstance(checkpointer, PostgresCheckpointerSaver)

    def test_conversation_manager_uses_pooled_saver(self):
        """Test ConversationManager creates PooledPostgresCheckpointerSaver when pooling enabled."""
        from chat.conversation_manager import ConversationManager

        manager = ConversationManager(
            connection_string="postgresql://test:test@localhost:5432/test",
            user_id="test_user",
            use_pooling=True,
            pool_size=15
        )

        checkpointer = manager.get_checkpointer()
        assert isinstance(checkpointer, PooledPostgresCheckpointerSaver)
        assert checkpointer._pool_size == 15

    def test_thread_config_format(self):
        """Test thread config uses correct multi-tenant format."""
        from chat.conversation_manager import ConversationManager

        manager = ConversationManager(
            connection_string="postgresql://test:test@localhost:5432/test",
            user_id="user123"
        )

        config = manager.get_thread_config("session456")

        assert config == {
            "configurable": {
                "thread_id": "user123#session456"
            }
        }

    def test_get_stats(self):
        """Test get_stats returns correct backend info."""
        from chat.conversation_manager import ConversationManager

        manager = ConversationManager(
            connection_string="postgresql://test:test@localhost:5432/test",
            user_id="test_user",
            use_pooling=True,
            pool_size=20
        )

        stats = manager.get_stats()

        assert stats["backend"] == "postgres"
        assert stats["use_pooling"] is True
        assert stats["pool_size"] == 20
        assert stats["user_id"] == "test_user"
