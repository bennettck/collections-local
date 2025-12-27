"""Conversation manager for multi-turn agentic chat.

Handles DynamoDB checkpointing for serverless deployment with multi-tenancy support.
"""

import os
import logging
from typing import Optional, Dict, Any
from datetime import datetime

from chat.checkpointers.dynamodb_saver import DynamoDBSaver

from config.chat_config import (
    CONVERSATION_TTL_HOURS,
)

logger = logging.getLogger(__name__)


class ConversationManager:
    """Manages conversation state persistence using DynamoDB.

    Uses LangGraph's DynamoDBSaver for checkpointing agent state,
    with multi-tenant support via {user_id}#{session_id} thread IDs.
    """

    def __init__(
        self,
        table_name: Optional[str] = None,
        ttl_hours: Optional[int] = None,
        region_name: Optional[str] = None,
        user_id: str = "default"
    ):
        """Initialize the conversation manager.

        Args:
            table_name: DynamoDB table name (defaults to env var DYNAMODB_CHECKPOINT_TABLE)
            ttl_hours: Hours until checkpoint expires (defaults to CONVERSATION_TTL_HOURS)
            region_name: AWS region name (defaults to env var AWS_REGION)
            user_id: User ID for multi-tenancy (default: "default")
        """
        self.table_name = table_name or os.getenv("DYNAMODB_CHECKPOINT_TABLE", "langgraph-checkpoints")
        self.ttl_hours = ttl_hours or CONVERSATION_TTL_HOURS
        self.region_name = region_name or os.getenv("AWS_REGION")
        self.user_id = user_id

        # Create checkpointer
        self._checkpointer = None

        logger.info(
            f"Initialized ConversationManager with table={self.table_name}, "
            f"ttl_hours={self.ttl_hours}, user_id={self.user_id}"
        )

    def get_checkpointer(self) -> DynamoDBSaver:
        """Get or create the DynamoDBSaver checkpointer.

        Returns:
            DynamoDBSaver instance for LangGraph agent persistence.
        """
        if self._checkpointer is None:
            self._checkpointer = DynamoDBSaver(
                table_name=self.table_name,
                ttl_hours=self.ttl_hours,
                region_name=self.region_name
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

        Note: With DynamoDB, session metadata is stored in checkpoints themselves.
        This method provides compatibility with the SQLite interface but returns
        minimal information.

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

        Note: With DynamoDB, listing sessions requires scanning the table which
        is expensive. This method is provided for compatibility but returns an
        empty list. Use CloudWatch or DynamoDB streams for monitoring instead.

        Args:
            limit: Maximum number of sessions to return (ignored).

        Returns:
            Empty list (not implemented for DynamoDB).
        """
        logger.warning(
            "list_sessions() not implemented for DynamoDB. "
            "Use CloudWatch metrics or DynamoDB streams for monitoring."
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

        Note: With DynamoDB, TTL is handled automatically by the DynamoDB TTL
        feature. This method is provided for compatibility but does nothing.

        Args:
            ttl_hours: Hours after which sessions expire (ignored).

        Returns:
            0 (TTL handled automatically by DynamoDB)
        """
        logger.info(
            "cleanup_expired_sessions() not needed for DynamoDB. "
            "TTL is handled automatically by DynamoDB's TTL feature."
        )
        return 0

    def enforce_max_sessions(self) -> int:
        """Remove oldest sessions if count exceeds maximum.

        Note: With DynamoDB, session limits should be enforced at the application
        level or via API Gateway throttling. This method is provided for
        compatibility but does nothing.

        Returns:
            0 (not implemented for DynamoDB)
        """
        logger.warning(
            "enforce_max_sessions() not implemented for DynamoDB. "
            "Enforce limits at the application level or via API Gateway."
        )
        return 0

    def get_stats(self) -> Dict[str, Any]:
        """Get conversation manager statistics.

        Note: With DynamoDB, detailed statistics require CloudWatch metrics.
        This method provides basic information.

        Returns:
            Dict with basic configuration info.
        """
        return {
            "backend": "dynamodb",
            "table_name": self.table_name,
            "ttl_hours": self.ttl_hours,
            "region": self.region_name,
            "user_id": self.user_id,
            "note": "Use CloudWatch metrics for detailed statistics"
        }
