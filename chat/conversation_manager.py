"""Conversation manager for multi-turn agentic chat with DynamoDB checkpointing."""

import os
import logging
from typing import Optional, Dict, Any
from datetime import datetime

from chat.checkpointers.dynamodb_saver import DynamoDBSaver
from config.chat_config import CONVERSATION_TTL_HOURS

logger = logging.getLogger(__name__)


class ConversationManager:
    """Manages conversation state persistence using LangGraph's DynamoDBSaver.

    Provides multi-tenant support via {user_id}#{session_id} thread IDs.
    """

    def __init__(
        self,
        table_name: Optional[str] = None,
        ttl_hours: Optional[int] = None,
        region_name: Optional[str] = None,
        user_id: str = "default"
    ):
        """Initialize conversation manager.

        Args:
            table_name: DynamoDB table (default: DYNAMODB_CHECKPOINT_TABLE env var)
            ttl_hours: Checkpoint TTL in hours (default: CONVERSATION_TTL_HOURS)
            region_name: AWS region (default: AWS_REGION env var)
            user_id: User ID for multi-tenancy
        """
        self.table_name = table_name or os.getenv("DYNAMODB_CHECKPOINT_TABLE", "langgraph-checkpoints")
        self.ttl_hours = ttl_hours or CONVERSATION_TTL_HOURS
        self.region_name = region_name or os.getenv("AWS_REGION")
        self.user_id = user_id
        self._checkpointer = None

        logger.info(
            f"Initialized ConversationManager: table={self.table_name}, "
            f"ttl={self.ttl_hours}h, user={self.user_id}"
        )

    def get_checkpointer(self) -> DynamoDBSaver:
        """Get or create the DynamoDBSaver checkpointer."""
        if self._checkpointer is None:
            self._checkpointer = DynamoDBSaver(
                table_name=self.table_name,
                ttl_hours=self.ttl_hours,
                region_name=self.region_name
            )
        return self._checkpointer

    def get_thread_config(self, session_id: str) -> Dict[str, Any]:
        """Get LangGraph config with multi-tenant thread ID: {user_id}#{session_id}

        Args:
            session_id: Session identifier

        Returns:
            Config dict for LangGraph with thread_id
        """
        return {
            "configurable": {
                "thread_id": f"{self.user_id}#{session_id}",
            }
        }

    def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session metadata from checkpoint.

        Args:
            session_id: Session identifier

        Returns:
            Dict with session info or None if not found
        """
        try:
            config = self.get_thread_config(session_id)
            checkpoint_tuple = self.get_checkpointer().get_tuple(config)

            if checkpoint_tuple:
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

    def delete_session(self, session_id: str) -> bool:
        """Delete session and all its checkpoints.

        Args:
            session_id: Session identifier

        Returns:
            True if deleted successfully
        """
        try:
            thread_id = f"{self.user_id}#{session_id}"
            self.get_checkpointer().delete_thread(thread_id)
            logger.info(f"Deleted session {session_id} for user {self.user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete session: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get basic configuration info.

        Note: Use CloudWatch metrics for detailed statistics.
        """
        return {
            "backend": "dynamodb",
            "table_name": self.table_name,
            "ttl_hours": self.ttl_hours,
            "region": self.region_name,
            "user_id": self.user_id,
        }
