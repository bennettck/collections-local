"""PostgreSQL-based checkpoint saver for LangGraph conversations.

Uses langgraph-checkpoint-postgres for serverless-compatible PostgreSQL
checkpoint persistence with multi-tenant support.
"""

import logging
import os
from contextlib import contextmanager
from typing import Optional

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


class PostgresCheckpointerSaver:
    """PostgreSQL checkpoint saver wrapper for LangGraph agents.

    Wraps langgraph-checkpoint-postgres PostgresSaver with:
    - Multi-tenant thread IDs: {user_id}#{session_id}
    - Automatic table setup on first use
    - Connection management via AWS Secrets Manager or DATABASE_URL

    Attributes:
        connection_string: PostgreSQL connection string
        _setup_done: Whether tables have been created
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
    ):
        """Initialize the PostgreSQL checkpoint saver.

        Args:
            connection_string: PostgreSQL connection string. If None, uses
                get_database_url() from utils.aws_secrets.
        """
        if connection_string:
            self._connection_string = connection_string
        else:
            # Get connection string from environment/Secrets Manager
            from utils.aws_secrets import get_database_url
            self._connection_string = get_database_url(use_ssl=True)

        self._setup_done = False
        self._saver: Optional[PostgresSaver] = None

        logger.info("Initialized PostgresCheckpointerSaver")

    def _get_connection_string(self) -> str:
        """Get the PostgreSQL connection string.

        Returns:
            PostgreSQL connection string.
        """
        return self._connection_string

    @contextmanager
    def _get_saver(self):
        """Get a PostgresSaver instance with proper connection handling.

        Yields:
            PostgresSaver instance ready for use.
        """
        conn_string = self._get_connection_string()

        # Use psycopg connection directly with required parameters
        with Connection.connect(
            conn_string,
            autocommit=True,
            row_factory=dict_row,
        ) as conn:
            saver = PostgresSaver(conn)

            # Setup tables on first use
            if not self._setup_done:
                saver.setup()
                self._setup_done = True
                logger.info("PostgreSQL checkpoint tables created/verified")

            yield saver

    def get_tuple(self, config):
        """Fetch a checkpoint tuple from PostgreSQL.

        Args:
            config: Configuration specifying which checkpoint to retrieve.

        Returns:
            CheckpointTuple or None if not found.
        """
        with self._get_saver() as saver:
            return saver.get_tuple(config)

    def list(self, config, *, filter=None, before=None, limit=None):
        """List checkpoints from PostgreSQL matching criteria.

        Args:
            config: Base configuration for filtering checkpoints.
            filter: Additional filtering criteria for metadata.
            before: List checkpoints created before this configuration.
            limit: Maximum number of checkpoints to return.

        Yields:
            CheckpointTuple objects matching criteria.
        """
        with self._get_saver() as saver:
            yield from saver.list(config, filter=filter, before=before, limit=limit)

    def put(self, config, checkpoint, metadata, new_versions):
        """Store a checkpoint in PostgreSQL.

        Args:
            config: Configuration for the checkpoint.
            checkpoint: The checkpoint to store.
            metadata: Additional metadata for the checkpoint.
            new_versions: New channel versions as of this write.

        Returns:
            Updated configuration after storing the checkpoint.
        """
        with self._get_saver() as saver:
            return saver.put(config, checkpoint, metadata, new_versions)

    def put_writes(self, config, writes, task_id, task_path=""):
        """Store intermediate writes linked to a checkpoint.

        Args:
            config: Configuration of the related checkpoint.
            writes: List of (channel, value) writes to store.
            task_id: Identifier for the task creating the writes.
            task_path: Path of the task creating the writes.
        """
        with self._get_saver() as saver:
            saver.put_writes(config, writes, task_id, task_path)

    def delete_thread(self, thread_id: str) -> None:
        """Delete all checkpoints for a thread.

        Args:
            thread_id: The thread ID whose checkpoints should be deleted.
        """
        with self._get_saver() as saver:
            # PostgresSaver doesn't have a direct delete method,
            # so we execute raw SQL
            saver.conn.execute(
                "DELETE FROM checkpoints WHERE thread_id = %s",
                (thread_id,)
            )
            saver.conn.execute(
                "DELETE FROM checkpoint_writes WHERE thread_id = %s",
                (thread_id,)
            )
            saver.conn.execute(
                "DELETE FROM checkpoint_blobs WHERE thread_id = %s",
                (thread_id,)
            )
            logger.info(f"Deleted checkpoints for thread {thread_id}")

    # Async methods - delegate to sync versions for now
    async def aget_tuple(self, config):
        """Async version - delegates to sync."""
        return self.get_tuple(config)

    async def alist(self, config, *, filter=None, before=None, limit=None):
        """Async version - delegates to sync."""
        for item in self.list(config, filter=filter, before=before, limit=limit):
            yield item

    async def aput(self, config, checkpoint, metadata, new_versions):
        """Async version - delegates to sync."""
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config, writes, task_id, task_path=""):
        """Async version - delegates to sync."""
        self.put_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        """Async version - delegates to sync."""
        self.delete_thread(thread_id)


class PooledPostgresCheckpointerSaver:
    """PostgreSQL checkpoint saver using connection pooling.

    Uses langgraph-checkpoint-postgres PostgresSaver with connection pooling
    for better performance in high-concurrency scenarios.

    Attributes:
        connection_string: PostgreSQL connection string
        pool_size: Maximum connections in pool
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
        pool_size: int = 10,
    ):
        """Initialize the pooled PostgreSQL checkpoint saver.

        Args:
            connection_string: PostgreSQL connection string. If None, uses
                get_database_url() from utils.aws_secrets.
            pool_size: Maximum number of connections in the pool.
        """
        if connection_string:
            self._connection_string = connection_string
        else:
            from utils.aws_secrets import get_database_url
            self._connection_string = get_database_url(use_ssl=True)

        self._pool_size = pool_size
        self._pool = None
        self._saver = None
        self._setup_done = False

        logger.info(f"Initialized PooledPostgresCheckpointerSaver with pool_size={pool_size}")

    def _ensure_pool(self):
        """Ensure connection pool is initialized."""
        if self._pool is None:
            from psycopg_pool import ConnectionPool

            self._pool = ConnectionPool(
                self._connection_string,
                min_size=1,
                max_size=self._pool_size,
                kwargs={"autocommit": True, "row_factory": dict_row},
            )
            self._saver = PostgresSaver(self._pool)

            if not self._setup_done:
                self._saver.setup()
                self._setup_done = True
                logger.info("PostgreSQL checkpoint tables created/verified (pooled)")

    def get_tuple(self, config):
        """Fetch a checkpoint tuple from PostgreSQL."""
        self._ensure_pool()
        return self._saver.get_tuple(config)

    def list(self, config, *, filter=None, before=None, limit=None):
        """List checkpoints from PostgreSQL matching criteria."""
        self._ensure_pool()
        yield from self._saver.list(config, filter=filter, before=before, limit=limit)

    def put(self, config, checkpoint, metadata, new_versions):
        """Store a checkpoint in PostgreSQL."""
        self._ensure_pool()
        return self._saver.put(config, checkpoint, metadata, new_versions)

    def put_writes(self, config, writes, task_id, task_path=""):
        """Store intermediate writes linked to a checkpoint."""
        self._ensure_pool()
        self._saver.put_writes(config, writes, task_id, task_path)

    def delete_thread(self, thread_id: str) -> None:
        """Delete all checkpoints for a thread."""
        self._ensure_pool()
        with self._pool.connection() as conn:
            conn.execute(
                "DELETE FROM checkpoints WHERE thread_id = %s",
                (thread_id,)
            )
            conn.execute(
                "DELETE FROM checkpoint_writes WHERE thread_id = %s",
                (thread_id,)
            )
            conn.execute(
                "DELETE FROM checkpoint_blobs WHERE thread_id = %s",
                (thread_id,)
            )
        logger.info(f"Deleted checkpoints for thread {thread_id}")

    def close(self):
        """Close the connection pool."""
        if self._pool:
            self._pool.close()
            self._pool = None
            self._saver = None
            logger.info("Closed PostgreSQL connection pool")

    # Async methods
    async def aget_tuple(self, config):
        """Async version - delegates to sync."""
        return self.get_tuple(config)

    async def alist(self, config, *, filter=None, before=None, limit=None):
        """Async version - delegates to sync."""
        for item in self.list(config, filter=filter, before=before, limit=limit):
            yield item

    async def aput(self, config, checkpoint, metadata, new_versions):
        """Async version - delegates to sync."""
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config, writes, task_id, task_path=""):
        """Async version - delegates to sync."""
        self.put_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        """Async version - delegates to sync."""
        self.delete_thread(thread_id)
