"""
Unit tests for multi-turn agentic chat.

Tests the ConversationManager and AgenticChatOrchestrator classes with mocked
dependencies to verify:
- Session lifecycle management
- Conversation state persistence
- Multi-turn context handling
- Cleanup and expiration logic
"""

import pytest
import sqlite3
import tempfile
import os
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

# Check if langgraph is available
try:
    from langgraph.checkpoint.sqlite import SqliteSaver
    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False

# Check if pydantic is available
try:
    from pydantic import BaseModel
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False

requires_langgraph = pytest.mark.skipif(
    not HAS_LANGGRAPH,
    reason="LangGraph not installed"
)

requires_pydantic = pytest.mark.skipif(
    not HAS_PYDANTIC,
    reason="Pydantic not installed"
)


@requires_langgraph
class TestConversationManager:
    """Unit tests for ConversationManager."""

    @pytest.fixture
    def temp_db_path(self):
        """Create a temporary database file."""
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        yield path
        # Cleanup
        if os.path.exists(path):
            os.remove(path)
        # Also remove WAL files if present
        for suffix in ['-wal', '-shm']:
            wal_path = path + suffix
            if os.path.exists(wal_path):
                os.remove(wal_path)

    @pytest.fixture
    def conversation_manager(self, temp_db_path):
        """Create a ConversationManager with temp database."""
        from chat.conversation_manager import ConversationManager
        return ConversationManager(db_path=temp_db_path)

    def test_init_creates_database(self, temp_db_path):
        """Test that initialization creates the database file."""
        from chat.conversation_manager import ConversationManager
        manager = ConversationManager(db_path=temp_db_path)

        assert os.path.exists(temp_db_path)

        # Verify tables exist
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        assert 'chat_sessions' in tables

    def test_get_thread_config_creates_session(self, conversation_manager):
        """Test that get_thread_config creates a new session."""
        session_id = "test-session-123"
        config = conversation_manager.get_thread_config(session_id)

        assert config["configurable"]["thread_id"] == f"session_{session_id}"

        # Verify session was created
        session_info = conversation_manager.get_session_info(session_id)
        assert session_info is not None
        assert session_info["session_id"] == session_id
        assert session_info["message_count"] == 1

    def test_get_thread_config_updates_existing_session(self, conversation_manager):
        """Test that get_thread_config updates existing session."""
        session_id = "test-session-456"

        # First call creates session
        conversation_manager.get_thread_config(session_id)
        info1 = conversation_manager.get_session_info(session_id)
        assert info1["message_count"] == 1

        # Second call updates message count
        conversation_manager.get_thread_config(session_id)
        info2 = conversation_manager.get_session_info(session_id)
        assert info2["message_count"] == 2

    def test_list_sessions_returns_sessions(self, conversation_manager):
        """Test that list_sessions returns created sessions."""
        # Create some sessions
        for i in range(3):
            conversation_manager.get_thread_config(f"session-{i}")

        sessions = conversation_manager.list_sessions()

        assert len(sessions) == 3
        session_ids = {s["session_id"] for s in sessions}
        assert session_ids == {"session-0", "session-1", "session-2"}

    def test_list_sessions_respects_limit(self, conversation_manager):
        """Test that list_sessions respects the limit parameter."""
        for i in range(10):
            conversation_manager.get_thread_config(f"session-{i}")

        sessions = conversation_manager.list_sessions(limit=5)
        assert len(sessions) == 5

    def test_delete_session_removes_session(self, conversation_manager):
        """Test that delete_session removes the session."""
        session_id = "to-delete"
        conversation_manager.get_thread_config(session_id)

        assert conversation_manager.get_session_info(session_id) is not None

        deleted = conversation_manager.delete_session(session_id)

        assert deleted is True
        assert conversation_manager.get_session_info(session_id) is None

    def test_delete_nonexistent_session_returns_false(self, conversation_manager):
        """Test that deleting nonexistent session returns False."""
        deleted = conversation_manager.delete_session("nonexistent")
        assert deleted is False

    def test_cleanup_expired_sessions(self, conversation_manager, temp_db_path):
        """Test that cleanup removes expired sessions."""
        # Create a session
        session_id = "old-session"
        conversation_manager.get_thread_config(session_id)

        # Manually backdate the session
        conn = sqlite3.connect(temp_db_path)
        old_time = (datetime.utcnow() - timedelta(hours=5)).isoformat()
        conn.execute(
            "UPDATE chat_sessions SET last_activity = ? WHERE session_id = ?",
            (old_time, session_id)
        )
        conn.commit()
        conn.close()

        # Cleanup with 4-hour TTL should remove it
        removed = conversation_manager.cleanup_expired_sessions(ttl_hours=4)

        assert removed == 1
        assert conversation_manager.get_session_info(session_id) is None

    def test_cleanup_keeps_recent_sessions(self, conversation_manager):
        """Test that cleanup keeps recent sessions."""
        session_id = "recent-session"
        conversation_manager.get_thread_config(session_id)

        # Cleanup with 4-hour TTL should keep it
        removed = conversation_manager.cleanup_expired_sessions(ttl_hours=4)

        assert removed == 0
        assert conversation_manager.get_session_info(session_id) is not None

    def test_get_stats_returns_correct_counts(self, conversation_manager):
        """Test that get_stats returns correct statistics."""
        # Create some sessions
        for i in range(3):
            conversation_manager.get_thread_config(f"session-{i}")
            # Add extra messages
            conversation_manager.get_thread_config(f"session-{i}")

        stats = conversation_manager.get_stats()

        assert stats["total_sessions"] == 3
        assert stats["total_messages"] == 6  # 3 sessions * 2 messages each

    def test_checkpointer_creation(self, conversation_manager):
        """Test that get_checkpointer returns a valid checkpointer."""
        checkpointer = conversation_manager.get_checkpointer()

        assert checkpointer is not None
        # Checkpointer should be reused
        checkpointer2 = conversation_manager.get_checkpointer()
        assert checkpointer is checkpointer2


@requires_langgraph
class TestAgenticChatOrchestrator:
    """Unit tests for AgenticChatOrchestrator."""

    @pytest.fixture
    def mock_chroma_manager(self):
        """Create a mock ChromaVectorStoreManager."""
        return MagicMock()

    @pytest.fixture
    def mock_conversation_manager(self):
        """Create a mock ConversationManager."""
        manager = MagicMock()
        manager.get_checkpointer.return_value = MagicMock()
        manager.get_thread_config.return_value = {
            "configurable": {"thread_id": "session_test"}
        }
        manager.get_session_info.return_value = {
            "session_id": "test",
            "message_count": 1,
            "created_at": datetime.utcnow().isoformat(),
            "last_activity": datetime.utcnow().isoformat()
        }
        return manager

    def test_orchestrator_initialization(self, mock_chroma_manager, mock_conversation_manager):
        """Test that orchestrator initializes correctly."""
        with patch('chat.agentic_chat.HybridLangChainRetriever'):
            with patch('chat.agentic_chat.ChatAnthropic'):
                with patch('chat.agentic_chat.create_react_agent'):
                    from chat.agentic_chat import AgenticChatOrchestrator

                    orchestrator = AgenticChatOrchestrator(
                        chroma_manager=mock_chroma_manager,
                        conversation_manager=mock_conversation_manager,
                        top_k=5,
                        category_filter="Food"
                    )

                    assert orchestrator.top_k == 5
                    assert orchestrator.category_filter == "Food"
                    assert orchestrator.chroma_manager == mock_chroma_manager
                    assert orchestrator.conversation_manager == mock_conversation_manager

    def test_chat_returns_response(self, mock_chroma_manager, mock_conversation_manager):
        """Test that chat returns a properly formatted response."""
        with patch('chat.agentic_chat.HybridLangChainRetriever') as mock_retriever:
            with patch('chat.agentic_chat.ChatAnthropic'):
                with patch('chat.agentic_chat.create_react_agent') as mock_agent:
                    # Setup mock agent to return events
                    mock_graph = MagicMock()
                    mock_message = MagicMock()
                    mock_message.type = 'ai'
                    mock_message.content = "Here are some results for your query."
                    mock_message.tool_calls = None

                    mock_graph.stream.return_value = [
                        {"agent": {"messages": [mock_message]}}
                    ]
                    mock_agent.return_value = mock_graph

                    from chat.agentic_chat import AgenticChatOrchestrator

                    orchestrator = AgenticChatOrchestrator(
                        chroma_manager=mock_chroma_manager,
                        conversation_manager=mock_conversation_manager
                    )

                    result = orchestrator.chat(
                        message="Show me food photos",
                        session_id="test-session"
                    )

                    assert "session_id" in result
                    assert "response" in result
                    assert "documents" in result
                    assert "reasoning" in result
                    assert "tools_used" in result
                    assert "conversation_turn" in result
                    assert "response_time_ms" in result

    def test_chat_uses_session_id(self, mock_chroma_manager, mock_conversation_manager):
        """Test that chat correctly uses the session_id."""
        with patch('chat.agentic_chat.HybridLangChainRetriever'):
            with patch('chat.agentic_chat.ChatAnthropic'):
                with patch('chat.agentic_chat.create_react_agent') as mock_agent:
                    mock_graph = MagicMock()
                    mock_message = MagicMock()
                    mock_message.type = 'ai'
                    mock_message.content = "Response"
                    mock_message.tool_calls = None
                    mock_graph.stream.return_value = [
                        {"agent": {"messages": [mock_message]}}
                    ]
                    mock_agent.return_value = mock_graph

                    from chat.agentic_chat import AgenticChatOrchestrator

                    orchestrator = AgenticChatOrchestrator(
                        chroma_manager=mock_chroma_manager,
                        conversation_manager=mock_conversation_manager
                    )

                    orchestrator.chat(message="Hello", session_id="unique-session")

                    # Verify get_thread_config was called with session_id
                    mock_conversation_manager.get_thread_config.assert_called_with("unique-session")

    def test_clear_session_delegates_to_manager(self, mock_chroma_manager, mock_conversation_manager):
        """Test that clear_session delegates to conversation manager."""
        with patch('chat.agentic_chat.HybridLangChainRetriever'):
            with patch('chat.agentic_chat.ChatAnthropic'):
                with patch('chat.agentic_chat.create_react_agent'):
                    from chat.agentic_chat import AgenticChatOrchestrator

                    orchestrator = AgenticChatOrchestrator(
                        chroma_manager=mock_chroma_manager,
                        conversation_manager=mock_conversation_manager
                    )

                    orchestrator.clear_session("test-session")

                    mock_conversation_manager.delete_session.assert_called_once_with("test-session")


@requires_pydantic
class TestChatModels:
    """Tests for chat data models."""

    def test_chat_request_validation(self):
        """Test ChatRequest validation."""
        from models import ChatRequest

        # Valid request
        request = ChatRequest(
            message="Hello",
            session_id="test-123",
            top_k=10
        )
        assert request.message == "Hello"
        assert request.session_id == "test-123"
        assert request.top_k == 10

    def test_chat_request_rejects_empty_message(self):
        """Test that ChatRequest rejects empty messages."""
        from models import ChatRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ChatRequest(
                message="",
                session_id="test-123"
            )

    def test_chat_response_structure(self):
        """Test ChatResponse structure."""
        from models import ChatResponse, ChatMessage
        from datetime import datetime

        response = ChatResponse(
            session_id="test-123",
            message=ChatMessage(
                role="assistant",
                content="Hello!",
                timestamp=datetime.utcnow()
            ),
            conversation_turn=1,
            response_time_ms=100.5
        )

        assert response.session_id == "test-123"
        assert response.message.role == "assistant"
        assert response.message.content == "Hello!"
        assert response.conversation_turn == 1

    def test_chat_message_roles(self):
        """Test ChatMessage role validation."""
        from models import ChatMessage
        from datetime import datetime
        from pydantic import ValidationError

        # Valid roles
        user_msg = ChatMessage(role="user", content="Hi", timestamp=datetime.utcnow())
        assistant_msg = ChatMessage(role="assistant", content="Hello", timestamp=datetime.utcnow())

        assert user_msg.role == "user"
        assert assistant_msg.role == "assistant"

        # Invalid role should raise
        with pytest.raises(ValidationError):
            ChatMessage(role="invalid", content="Test", timestamp=datetime.utcnow())


class TestChatConfiguration:
    """Tests for chat configuration."""

    def test_config_defaults(self):
        """Test that config has sensible defaults."""
        from config.chat_config import (
            CONVERSATION_TTL_HOURS,
            MAX_CONVERSATIONS,
            CHAT_MODEL,
            CHAT_TEMPERATURE
        )

        assert CONVERSATION_TTL_HOURS > 0
        assert MAX_CONVERSATIONS > 0
        assert CHAT_MODEL is not None
        assert 0 <= CHAT_TEMPERATURE <= 1

    def test_config_system_message(self):
        """Test that system message contains key instructions."""
        from config.chat_config import CHAT_SYSTEM_MESSAGE

        assert "conversation" in CHAT_SYSTEM_MESSAGE.lower()
        assert "search" in CHAT_SYSTEM_MESSAGE.lower()


# Fixtures for integration-style tests
@pytest.fixture
def sample_chat_session():
    """Provide sample chat session data."""
    return {
        "session_id": "integration-test-session",
        "messages": [
            {"role": "user", "content": "Show me beach photos"},
            {"role": "assistant", "content": "I found 5 beach photos..."},
            {"role": "user", "content": "Show me more like the first one"},
        ]
    }


def test_multi_turn_scenario(sample_chat_session):
    """Test a multi-turn conversation scenario."""
    # This is a placeholder for integration testing
    # In a real test, we would:
    # 1. Create a session
    # 2. Send multiple messages
    # 3. Verify context is maintained

    assert len(sample_chat_session["messages"]) == 3
    assert sample_chat_session["messages"][0]["role"] == "user"
    assert sample_chat_session["messages"][1]["role"] == "assistant"
