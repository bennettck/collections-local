"""Conversation manager for multi-turn agentic chat.

Handles PostgreSQL checkpointing for serverless deployment with multi-tenancy support.
"""

import os
import logging
from typing import Optional, Dict, Any, Union
from datetime import datetime

from chat.checkpointers.postgres_saver import (
    PostgresCheckpointerSaver,
    PooledPostgresCheckpointerSaver,
)

from config.chat_config import (
    CONVERSATION_TTL_HOURS,
)

logger = logging.getLogger(__name__)

# Type alias for the checkpointer types we support
CheckpointerType = Union[PostgresCheckpointerSaver, PooledPostgresCheckpointerSaver]


class ConversationManager:
    """Manages conversation state persistence using PostgreSQL.

    Uses langgraph-checkpoint-postgres for checkpointing agent state,
    with multi-tenant support via {user_id}#{session_id} thread IDs.
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
        ttl_hours: Optional[int] = None,
        user_id: str = "default",
        use_pooling: bool = False,
        pool_size: int = 10,
    ):
        """Initialize the conversation manager.

        Args:
            connection_string: PostgreSQL connection string. If None, uses
                get_database_url() from utils.aws_secrets.
            ttl_hours: Hours until checkpoint expires (for cleanup).
            user_id: User ID for multi-tenancy (default: "default").
            use_pooling: Whether to use connection pooling.
            pool_size: Maximum connections in pool (if use_pooling=True).
        """
        self.connection_string = connection_string
        self.ttl_hours = ttl_hours or CONVERSATION_TTL_HOURS
        self.user_id = user_id
        self.use_pooling = use_pooling
        self.pool_size = pool_size

        # Create checkpointer lazily
        self._checkpointer: Optional[CheckpointerType] = None

        logger.info(
            f"Initialized ConversationManager with PostgreSQL, "
            f"ttl_hours={self.ttl_hours}, user_id={self.user_id}, "
            f"use_pooling={self.use_pooling}"
        )

    def get_checkpointer(self) -> CheckpointerType:
        """Get or create the PostgreSQL checkpointer.

        Returns:
            PostgresCheckpointerSaver or PooledPostgresCheckpointerSaver instance
            for LangGraph agent persistence.
        """
        if self._checkpointer is None:
            if self.use_pooling:
                self._checkpointer = PooledPostgresCheckpointerSaver(
                    connection_string=self.connection_string,
                    pool_size=self.pool_size,
                )
            else:
                self._checkpointer = PostgresCheckpointerSaver(
                    connection_string=self.connection_string,
                )
        return self._checkpointer

    def get_thread_config(self, session_id: str) -> Dict[str, Any]:
        """Get LangGraph config for a conversation thread.

        Creates a multi-tenant thread ID: {user_id}#{session_id}

        Args:
            session_id: Client-provided session identifier.

        Returns:
            Config dict for LangGraph invoke() with thread_id.
        """
        # Multi-tenant thread ID format
        thread_id = f"{self.user_id}#{session_id}"

        return {
            "configurable": {
                "thread_id": thread_id,
            }
        }

    def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session metadata.

        Args:
            session_id: Session identifier.

        Returns:
            Dict with basic session info or None if not found.
        """
        try:
            config = self.get_thread_config(session_id)
            checkpointer = self.get_checkpointer()

            # Try to get the latest checkpoint
            checkpoint_tuple = checkpointer.get_tuple(config)

            if checkpoint_tuple:
                # Count messages in checkpoint state
                state = checkpoint_tuple.checkpoint.get("channel_values", {})
                messages = state.get("messages", [])

                return {
                    "session_id": session_id,
                    "message_count": len(messages),
                    "last_activity": datetime.utcnow().isoformat(),
                    "created_at": checkpoint_tuple.checkpoint.get("ts"),
                }

            return None

        except Exception as e:
            logger.error(f"Failed to get session info: {e}")
            return None

    def list_sessions(self, limit: int = 50) -> list:
        """List active sessions.

        Note: Listing all sessions requires a table scan which can be expensive.
        Consider using direct session lookup when possible.

        Args:
            limit: Maximum number of sessions to return.

        Returns:
            List of session info dicts (limited implementation).
        """
        logger.warning(
            "list_sessions() requires table scan. "
            "Consider using direct session lookup when possible."
        )
        return []

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and its checkpoints.

        Args:
            session_id: Session identifier.

        Returns:
            True if session was deleted, False if not found.
        """
        try:
            thread_id = f"{self.user_id}#{session_id}"
            checkpointer = self.get_checkpointer()

            # Delete all checkpoints for this thread
            checkpointer.delete_thread(thread_id)

            logger.info(f"Deleted session {session_id} for user {self.user_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete session: {e}")
            return False

    def cleanup_expired_sessions(self, ttl_hours: Optional[int] = None) -> int:
        """Remove sessions older than TTL.

        Note: Unlike DynamoDB, PostgreSQL does not have native TTL.
        This method can be called periodically to clean up old sessions.

        Args:
            ttl_hours: Hours after which sessions expire.

        Returns:
            Number of sessions cleaned up.
        """
        from datetime import timedelta
        from psycopg import Connection
        from psycopg.rows import dict_row

        hours = ttl_hours or self.ttl_hours
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        cutoff_ts = cutoff.isoformat()

        try:
            # Get connection string
            if self.connection_string:
                conn_string = self.connection_string
            else:
                from utils.aws_secrets import get_database_url
                conn_string = get_database_url(use_ssl=True)

            with Connection.connect(
                conn_string,
                autocommit=True,
                row_factory=dict_row,
            ) as conn:
                # Delete old checkpoints (those with ts < cutoff)
                # The checkpoints table has a 'checkpoint' JSONB column with 'ts' field
                result = conn.execute(
                    """
                    DELETE FROM checkpoints
                    WHERE thread_id LIKE %s
                    AND (checkpoint->>'ts')::timestamp < %s::timestamp
                    """,
                    (f"{self.user_id}#%", cutoff_ts)
                )
                deleted = result.rowcount

                logger.info(f"Cleaned up {deleted} expired checkpoints for user {self.user_id}")
                return deleted

        except Exception as e:
            logger.error(f"Failed to cleanup expired sessions: {e}")
            return 0

    def enforce_max_sessions(self) -> int:
        """Remove oldest sessions if count exceeds maximum.

        Note: Session limits should be enforced at the application level
        or via API Gateway throttling.

        Returns:
            0 (not implemented)
        """
        logger.warning(
            "enforce_max_sessions() not implemented. "
            "Enforce limits at the application level or via API Gateway."
        )
        return 0

    def get_stats(self) -> Dict[str, Any]:
        """Get conversation manager statistics.

        Returns:
            Dict with configuration info.
        """
        return {
            "backend": "postgres",
            "ttl_hours": self.ttl_hours,
            "user_id": self.user_id,
            "use_pooling": self.use_pooling,
            "pool_size": self.pool_size if self.use_pooling else None,
        }

    def close(self) -> None:
        """Close the checkpointer connection/pool.

        Should be called when the ConversationManager is no longer needed.
        """
        if self._checkpointer is not None:
            if hasattr(self._checkpointer, 'close'):
                self._checkpointer.close()
            self._checkpointer = None
            logger.info("Closed ConversationManager checkpointer")
