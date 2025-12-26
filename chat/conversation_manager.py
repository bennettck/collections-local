"""Conversation manager for multi-turn agentic chat.

Handles SQLite checkpointing, session lifecycle, and cleanup.
"""

import os
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from config.chat_config import (
    CONVERSATION_DB_PATH,
    CONVERSATION_TTL_HOURS,
    MAX_CONVERSATIONS,
)

logger = logging.getLogger(__name__)


class ConversationManager:
    """Manages conversation state persistence using SQLite.

    Uses LangGraph's SqliteSaver for checkpointing agent state,
    with additional session management and cleanup capabilities.
    """

    def __init__(self, db_path: Optional[str] = None):
        """Initialize the conversation manager.

        Args:
            db_path: Path to SQLite database. Defaults to CONVERSATION_DB_PATH.
        """
        self.db_path = db_path or CONVERSATION_DB_PATH

        # Ensure directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize SQLite connection with WAL mode for better concurrency
        self._init_database()

        # Create checkpointer
        self._checkpointer = None

    def _init_database(self):
        """Initialize database with WAL mode and session tracking table."""
        conn = sqlite3.connect(self.db_path)
        try:
            # Enable WAL mode for better concurrent access
            conn.execute("PRAGMA journal_mode=WAL")

            # Create session tracking table (separate from LangGraph's tables)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    last_activity TEXT NOT NULL,
                    message_count INTEGER DEFAULT 0
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def get_checkpointer(self) -> SqliteSaver:
        """Get or create the SqliteSaver checkpointer.

        Returns:
            SqliteSaver instance for LangGraph agent persistence.
        """
        if self._checkpointer is None:
            # Use connection string with WAL mode
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            self._checkpointer = SqliteSaver(conn)
        return self._checkpointer

    def get_thread_config(self, session_id: str) -> Dict[str, Any]:
        """Get LangGraph config for a conversation thread.

        Args:
            session_id: Client-provided session identifier.

        Returns:
            Config dict for LangGraph invoke() with thread_id.
        """
        thread_id = f"session_{session_id}"

        # Update session tracking
        self._touch_session(session_id)

        return {
            "configurable": {
                "thread_id": thread_id,
            }
        }

    def _touch_session(self, session_id: str):
        """Update session last_activity timestamp, create if not exists."""
        now = datetime.utcnow().isoformat()
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            # Try to update existing session
            cursor.execute("""
                UPDATE chat_sessions
                SET last_activity = ?, message_count = message_count + 1
                WHERE session_id = ?
            """, (now, session_id))

            if cursor.rowcount == 0:
                # Session doesn't exist, create it
                cursor.execute("""
                    INSERT INTO chat_sessions (session_id, created_at, last_activity, message_count)
                    VALUES (?, ?, ?, 1)
                """, (session_id, now, now))

            conn.commit()
        finally:
            conn.close()

    def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session metadata.

        Args:
            session_id: Session identifier.

        Returns:
            Dict with session info or None if not found.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT session_id, created_at, last_activity, message_count
                FROM chat_sessions WHERE session_id = ?
            """, (session_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        finally:
            conn.close()

    def list_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List active sessions ordered by last activity.

        Args:
            limit: Maximum number of sessions to return.

        Returns:
            List of session info dicts.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT session_id, created_at, last_activity, message_count
                FROM chat_sessions
                ORDER BY last_activity DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and its checkpoints.

        Args:
            session_id: Session identifier.

        Returns:
            True if session was deleted, False if not found.
        """
        thread_id = f"session_{session_id}"
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Delete from session tracking
            cursor.execute("DELETE FROM chat_sessions WHERE session_id = ?", (session_id,))
            deleted = cursor.rowcount > 0

            # Delete checkpoints (LangGraph tables)
            # Note: Table names depend on LangGraph version
            for table in ["checkpoints", "checkpoint_writes", "checkpoint_blobs"]:
                try:
                    cursor.execute(f"DELETE FROM {table} WHERE thread_id = ?", (thread_id,))
                except sqlite3.OperationalError:
                    # Table might not exist yet
                    pass

            conn.commit()
            return deleted
        finally:
            conn.close()

    def cleanup_expired_sessions(self, ttl_hours: Optional[int] = None) -> int:
        """Remove sessions older than TTL.

        Args:
            ttl_hours: Hours after which sessions expire. Defaults to CONVERSATION_TTL_HOURS.

        Returns:
            Number of sessions cleaned up.
        """
        ttl = ttl_hours or CONVERSATION_TTL_HOURS
        cutoff = (datetime.utcnow() - timedelta(hours=ttl)).isoformat()

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Find expired sessions
            cursor.execute("""
                SELECT session_id FROM chat_sessions WHERE last_activity < ?
            """, (cutoff,))
            expired_sessions = [row[0] for row in cursor.fetchall()]

            if not expired_sessions:
                return 0

            # Delete session tracking entries
            cursor.execute("""
                DELETE FROM chat_sessions WHERE last_activity < ?
            """, (cutoff,))

            # Delete associated checkpoints
            for session_id in expired_sessions:
                thread_id = f"session_{session_id}"
                for table in ["checkpoints", "checkpoint_writes", "checkpoint_blobs"]:
                    try:
                        cursor.execute(f"DELETE FROM {table} WHERE thread_id = ?", (thread_id,))
                    except sqlite3.OperationalError:
                        pass

            conn.commit()

            logger.info(f"Cleaned up {len(expired_sessions)} expired sessions")
            return len(expired_sessions)
        finally:
            conn.close()

    def enforce_max_sessions(self) -> int:
        """Remove oldest sessions if count exceeds MAX_CONVERSATIONS.

        Returns:
            Number of sessions removed.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get current count
            cursor.execute("SELECT COUNT(*) FROM chat_sessions")
            count = cursor.fetchone()[0]

            if count <= MAX_CONVERSATIONS:
                return 0

            # Find oldest sessions to remove
            excess = count - MAX_CONVERSATIONS
            cursor.execute("""
                SELECT session_id FROM chat_sessions
                ORDER BY last_activity ASC
                LIMIT ?
            """, (excess,))
            to_remove = [row[0] for row in cursor.fetchall()]

            # Delete them
            for session_id in to_remove:
                self.delete_session(session_id)

            logger.info(f"Removed {len(to_remove)} sessions to enforce max limit")
            return len(to_remove)
        finally:
            conn.close()

    def get_stats(self) -> Dict[str, Any]:
        """Get conversation manager statistics.

        Returns:
            Dict with session counts and database info.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM chat_sessions")
            total_sessions = cursor.fetchone()[0]

            cursor.execute("SELECT SUM(message_count) FROM chat_sessions")
            total_messages = cursor.fetchone()[0] or 0

            # Get database file size
            db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0

            return {
                "total_sessions": total_sessions,
                "total_messages": total_messages,
                "database_size_bytes": db_size,
                "database_path": self.db_path,
                "ttl_hours": CONVERSATION_TTL_HOURS,
                "max_sessions": MAX_CONVERSATIONS,
            }
        finally:
            conn.close()
