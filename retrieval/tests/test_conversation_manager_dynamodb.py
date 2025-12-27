"""Integration tests for ConversationManager with DynamoDB backend.

Tests the conversation manager's interface with DynamoDB checkpointer.
"""

import pytest
from moto import mock_aws
import boto3

from chat.conversation_manager import ConversationManager


@pytest.fixture
def dynamodb_table():
    """Create a mock DynamoDB table for testing."""
    with mock_aws():
        # Create DynamoDB client and table
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

        table = dynamodb.create_table(
            TableName='test-checkpoints',
            KeySchema=[
                {'AttributeName': 'thread_id', 'KeyType': 'HASH'},
                {'AttributeName': 'sort_key', 'KeyType': 'RANGE'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'thread_id', 'AttributeType': 'S'},
                {'AttributeName': 'sort_key', 'AttributeType': 'S'}
            ],
            BillingMode='PAY_PER_REQUEST'
        )

        yield table


@pytest.fixture
def conversation_manager(dynamodb_table):
    """Create a ConversationManager instance for testing."""
    with mock_aws():
        return ConversationManager(
            table_name='test-checkpoints',
            ttl_hours=4,
            region_name='us-east-1',
            user_id='test_user'
        )


class TestConversationManagerDynamoDB:
    """Test ConversationManager with DynamoDB backend."""

    def test_initialization(self, conversation_manager):
        """Test ConversationManager initialization."""
        assert conversation_manager.table_name == 'test-checkpoints'
        assert conversation_manager.ttl_hours == 4
        assert conversation_manager.user_id == 'test_user'

    def test_get_checkpointer(self, conversation_manager):
        """Test getting the checkpointer."""
        checkpointer = conversation_manager.get_checkpointer()
        assert checkpointer is not None
        assert checkpointer.table_name == 'test-checkpoints'

    def test_get_thread_config(self, conversation_manager):
        """Test getting thread config with multi-tenant format."""
        config = conversation_manager.get_thread_config('session123')

        assert 'configurable' in config
        assert 'thread_id' in config['configurable']
        # Should be in format: user_id#session_id
        assert config['configurable']['thread_id'] == 'test_user#session123'

    def test_multi_tenancy(self):
        """Test that different users get different thread IDs."""
        with mock_aws():
            # Create table
            dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
            dynamodb.create_table(
                TableName='test-checkpoints',
                KeySchema=[
                    {'AttributeName': 'thread_id', 'KeyType': 'HASH'},
                    {'AttributeName': 'sort_key', 'KeyType': 'RANGE'}
                ],
                AttributeDefinitions=[
                    {'AttributeName': 'thread_id', 'AttributeType': 'S'},
                    {'AttributeName': 'sort_key', 'AttributeType': 'S'}
                ],
                BillingMode='PAY_PER_REQUEST'
            )

            # Create managers for different users
            manager1 = ConversationManager(
                table_name='test-checkpoints',
                region_name='us-east-1',
                user_id='user1'
            )

            manager2 = ConversationManager(
                table_name='test-checkpoints',
                region_name='us-east-1',
                user_id='user2'
            )

            # Same session ID should create different thread IDs
            config1 = manager1.get_thread_config('session1')
            config2 = manager2.get_thread_config('session1')

            assert config1['configurable']['thread_id'] == 'user1#session1'
            assert config2['configurable']['thread_id'] == 'user2#session1'
            assert config1['configurable']['thread_id'] != config2['configurable']['thread_id']

    def test_delete_session(self, conversation_manager):
        """Test deleting a session."""
        # Deleting a non-existent session should still return True
        result = conversation_manager.delete_session('nonexistent')
        assert result == True

    def test_get_stats(self, conversation_manager):
        """Test getting conversation manager statistics."""
        stats = conversation_manager.get_stats()

        assert stats['backend'] == 'dynamodb'
        assert stats['table_name'] == 'test-checkpoints'
        assert stats['ttl_hours'] == 4
        assert stats['user_id'] == 'test_user'

    def test_compatibility_methods(self, conversation_manager):
        """Test compatibility methods return expected defaults."""
        # These methods are provided for API compatibility but don't
        # do anything with DynamoDB

        # list_sessions returns empty list
        sessions = conversation_manager.list_sessions()
        assert sessions == []

        # cleanup_expired_sessions returns 0 (handled by DynamoDB TTL)
        cleaned = conversation_manager.cleanup_expired_sessions()
        assert cleaned == 0

        # enforce_max_sessions returns 0 (not implemented)
        removed = conversation_manager.enforce_max_sessions()
        assert removed == 0

    def test_get_session_info_nonexistent(self, conversation_manager):
        """Test getting info for non-existent session."""
        info = conversation_manager.get_session_info('nonexistent')
        assert info is None
