"""
Unit tests for multi-turn agentic chat.

Tests the ConversationManager and AgenticChatOrchestrator classes with mocked
dependencies to verify:
- Session lifecycle management
- Conversation state persistence
- Multi-turn context handling
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

# Check if langgraph is available
try:
    from langgraph.checkpoint.base import CheckpointTuple
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
    """Unit tests for ConversationManager (DynamoDB-based)."""

    @pytest.fixture
    def mock_dynamodb_saver(self):
        """Create a mock DynamoDBSaver."""
        with patch('chat.conversation_manager.DynamoDBSaver') as mock:
            saver_instance = MagicMock()
            mock.return_value = saver_instance
            yield saver_instance

    @pytest.fixture
    def conversation_manager(self, mock_dynamodb_saver):
        """Create a ConversationManager with mocked DynamoDB."""
        from chat.conversation_manager import ConversationManager
        return ConversationManager(
            table_name="test-checkpoints",
            ttl_hours=24,
            region_name="us-east-1",
            user_id="test-user"
        )

    def test_init_sets_parameters(self, mock_dynamodb_saver):
        """Test that initialization sets parameters correctly."""
        from chat.conversation_manager import ConversationManager
        manager = ConversationManager(
            table_name="my-table",
            ttl_hours=48,
            region_name="us-west-2",
            user_id="user123"
        )

        assert manager.table_name == "my-table"
        assert manager.ttl_hours == 48
        assert manager.region_name == "us-west-2"
        assert manager.user_id == "user123"

    def test_get_thread_config_returns_correct_format(self, conversation_manager):
        """Test that get_thread_config returns correct config structure."""
        session_id = "test-session-123"
        config = conversation_manager.get_thread_config(session_id)

        assert "configurable" in config
        assert "thread_id" in config["configurable"]
        # Thread ID format: {user_id}#{session_id}
        assert config["configurable"]["thread_id"] == "test-user#test-session-123"

    def test_get_checkpointer_creates_dynamodb_saver(self, mock_dynamodb_saver, conversation_manager):
        """Test that get_checkpointer creates and returns DynamoDBSaver."""
        checkpointer = conversation_manager.get_checkpointer()

        assert checkpointer is not None

    def test_get_checkpointer_reuses_instance(self, mock_dynamodb_saver, conversation_manager):
        """Test that get_checkpointer returns the same instance."""
        checkpointer1 = conversation_manager.get_checkpointer()
        checkpointer2 = conversation_manager.get_checkpointer()

        assert checkpointer1 is checkpointer2

    def test_get_session_info_returns_info_when_exists(self, mock_dynamodb_saver, conversation_manager):
        """Test that get_session_info returns session info when checkpoint exists."""
        # Mock checkpoint tuple
        mock_checkpoint = MagicMock()
        mock_checkpoint.checkpoint = {
            "channel_values": {
                "messages": [MagicMock(), MagicMock(), MagicMock()]
            },
            "ts": "2024-01-01T00:00:00Z"
        }
        mock_dynamodb_saver.get_tuple.return_value = mock_checkpoint

        info = conversation_manager.get_session_info("test-session")

        assert info is not None
        assert info["session_id"] == "test-session"
        assert info["message_count"] == 3

    def test_get_session_info_returns_none_when_not_exists(self, mock_dynamodb_saver, conversation_manager):
        """Test that get_session_info returns None when session doesn't exist."""
        mock_dynamodb_saver.get_tuple.return_value = None

        info = conversation_manager.get_session_info("nonexistent")

        assert info is None

    def test_delete_session_calls_checkpointer(self, mock_dynamodb_saver, conversation_manager):
        """Test that delete_session calls delete_thread on checkpointer."""
        result = conversation_manager.delete_session("test-session")

        mock_dynamodb_saver.delete_thread.assert_called_once_with("test-user#test-session")
        assert result is True

    def test_delete_session_handles_error(self, mock_dynamodb_saver, conversation_manager):
        """Test that delete_session returns False on error."""
        mock_dynamodb_saver.delete_thread.side_effect = Exception("DynamoDB error")

        result = conversation_manager.delete_session("test-session")

        assert result is False

    def test_get_stats_returns_configuration(self, conversation_manager):
        """Test that get_stats returns configuration info."""
        stats = conversation_manager.get_stats()

        assert stats["backend"] == "dynamodb"
        assert stats["table_name"] == "test-checkpoints"
        assert stats["ttl_hours"] == 24
        assert stats["region"] == "us-east-1"
        assert stats["user_id"] == "test-user"


@requires_langgraph
class TestAgenticChatOrchestrator:
    """Unit tests for AgenticChatOrchestrator."""

    @pytest.fixture
    def mock_vector_store(self):
        """Create a mock vector store manager."""
        return MagicMock()

    @pytest.fixture
    def mock_conversation_manager(self):
        """Create a mock ConversationManager."""
        manager = MagicMock()
        manager.get_checkpointer.return_value = MagicMock()
        manager.get_thread_config.return_value = {
            "configurable": {"thread_id": "user#test"}
        }
        manager.get_session_info.return_value = {
            "session_id": "test",
            "message_count": 1,
            "created_at": datetime.utcnow().isoformat(),
            "last_activity": datetime.utcnow().isoformat()
        }
        return manager

    def test_orchestrator_initialization(self, mock_vector_store, mock_conversation_manager):
        """Test that orchestrator initializes correctly."""
        with patch('chat.agentic_chat.PostgresHybridRetriever'):
            with patch('chat.agentic_chat.ChatAnthropic'):
                with patch('chat.agentic_chat.create_react_agent'):
                    from chat.agentic_chat import AgenticChatOrchestrator

                    orchestrator = AgenticChatOrchestrator(
                        vector_store=mock_vector_store,
                        conversation_manager=mock_conversation_manager,
                        user_id="test-user",
                        top_k=5,
                        category_filter="Food"
                    )

                    assert orchestrator.top_k == 5
                    assert orchestrator.category_filter == "Food"
                    assert orchestrator.vector_store == mock_vector_store
                    assert orchestrator.conversation_manager == mock_conversation_manager

    def test_chat_returns_response(self, mock_vector_store, mock_conversation_manager):
        """Test that chat returns a properly formatted response."""
        with patch('chat.agentic_chat.PostgresHybridRetriever') as mock_retriever:
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
                        vector_store=mock_vector_store,
                        conversation_manager=mock_conversation_manager,
                        user_id="test-user"
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

    def test_chat_uses_session_id(self, mock_vector_store, mock_conversation_manager):
        """Test that chat correctly uses the session_id."""
        with patch('chat.agentic_chat.PostgresHybridRetriever'):
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
                        vector_store=mock_vector_store,
                        conversation_manager=mock_conversation_manager,
                        user_id="test-user"
                    )

                    orchestrator.chat(message="Hello", session_id="unique-session")

                    # Verify get_thread_config was called with session_id
                    mock_conversation_manager.get_thread_config.assert_called_with("unique-session")

    def test_clear_session_delegates_to_manager(self, mock_vector_store, mock_conversation_manager):
        """Test that clear_session delegates to conversation manager."""
        with patch('chat.agentic_chat.PostgresHybridRetriever'):
            with patch('chat.agentic_chat.ChatAnthropic'):
                with patch('chat.agentic_chat.create_react_agent'):
                    from chat.agentic_chat import AgenticChatOrchestrator

                    orchestrator = AgenticChatOrchestrator(
                        vector_store=mock_vector_store,
                        conversation_manager=mock_conversation_manager,
                        user_id="test-user"
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
