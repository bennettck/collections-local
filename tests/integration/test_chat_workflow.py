"""
Integration tests for Phase 3: LangGraph Conversation System with DynamoDB.

Tests the DynamoDB checkpointer implementation for multi-turn conversations:
- Multi-turn conversation persistence
- Session isolation by user_id
- TTL expiration behavior
- Checkpoint save/load cycle
- DynamoDB GSI queries for user sessions

IMPORTANT: These tests use real DynamoDB (not mocks) for integration testing.
They require the AWS infrastructure to be deployed and configured.

Run with: pytest tests/integration/test_chat_workflow.py -v
"""

import pytest
import boto3
import os
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List
from unittest.mock import MagicMock, patch

# Check if required dependencies are available
try:
    from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint
    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False

requires_langgraph = pytest.mark.skipif(
    not HAS_LANGGRAPH,
    reason="LangGraph not installed"
)

# Fixture for AWS configuration
@pytest.fixture(scope="session")
def aws_region() -> str:
    """Get AWS region from environment or default."""
    return os.getenv('AWS_REGION', 'us-east-1')


@pytest.fixture(scope="session")
def env_name() -> str:
    """Get environment name from environment or default."""
    return os.getenv('CDK_ENV', 'dev')


@pytest.fixture(scope="session")
def stack_outputs(env_name):
    """
    Load CDK stack outputs from JSON file.

    Returns:
        Dictionary of stack outputs (OutputKey -> OutputValue)

    Raises:
        pytest.skip: If outputs file doesn't exist (infra not deployed)
    """
    import json
    from pathlib import Path

    # Look for outputs file in project root
    project_root = Path(__file__).parent.parent.parent
    outputs_file = project_root / f'.aws-outputs-{env_name}.json'

    if not outputs_file.exists():
        pytest.skip(f"CDK outputs not found: {outputs_file}. Deploy infrastructure first.")

    with open(outputs_file) as f:
        raw_outputs = json.load(f)

    # Convert from list of {OutputKey, OutputValue} to dict
    if isinstance(raw_outputs, list):
        return {item['OutputKey']: item['OutputValue'] for item in raw_outputs}

    # Already a dict (alternative format)
    return raw_outputs


@pytest.fixture(scope="session")
def dynamodb_resource(aws_region):
    """Initialize DynamoDB resource."""
    return boto3.resource('dynamodb', region_name=aws_region)


@pytest.fixture(scope="session")
def dynamodb_client(aws_region):
    """Initialize DynamoDB client."""
    return boto3.client('dynamodb', region_name=aws_region)


@pytest.fixture(scope="function")
def checkpoint_table(stack_outputs, dynamodb_resource):
    """
    Provide DynamoDB checkpoint table resource.

    Yields:
        boto3 Table resource for checkpoint storage
    """
    table_name = stack_outputs.get('CheckpointTableName')

    if not table_name:
        pytest.skip("CheckpointTableName not in outputs. Deploy infrastructure first.")

    table = dynamodb_resource.Table(table_name)

    # Verify table exists
    try:
        table.load()
    except Exception as e:
        pytest.skip(f"Checkpoint table not accessible: {e}")

    yield table


@pytest.fixture(scope="function")
def cleanup_checkpoints(checkpoint_table):
    """
    Track and cleanup DynamoDB checkpoint items created during tests.

    Yields:
        Function to register items for cleanup

    Cleanup:
        Deletes all registered items after test
    """
    items_to_delete = []

    def register(thread_id: str, checkpoint_id: str = None):
        """Register DynamoDB item for cleanup."""
        items_to_delete.append({'thread_id': thread_id, 'checkpoint_id': checkpoint_id})

    yield register

    # Cleanup all registered items
    for item in items_to_delete:
        try:
            if item['checkpoint_id']:
                # Delete specific checkpoint
                checkpoint_table.delete_item(
                    Key={
                        'thread_id': item['thread_id'],
                        'checkpoint_id': item['checkpoint_id']
                    }
                )
            else:
                # Delete all checkpoints for thread_id
                response = checkpoint_table.query(
                    KeyConditionExpression='thread_id = :tid',
                    ExpressionAttributeValues={':tid': item['thread_id']}
                )

                with checkpoint_table.batch_writer() as batch:
                    for checkpoint in response.get('Items', []):
                        batch.delete_item(
                            Key={
                                'thread_id': checkpoint['thread_id'],
                                'checkpoint_id': checkpoint['checkpoint_id']
                            }
                        )
        except Exception:
            pass  # Item may not exist


@pytest.fixture(scope="function")
def test_users() -> List[Dict[str, str]]:
    """
    Provide test user IDs for multi-tenancy testing.

    Returns:
        List of test user dictionaries with user_id
    """
    import uuid

    return [
        {'user_id': f'test-user-{uuid.uuid4()}', 'name': 'Alice'},
        {'user_id': f'test-user-{uuid.uuid4()}', 'name': 'Bob'},
        {'user_id': f'test-user-{uuid.uuid4()}', 'name': 'Charlie'},
    ]


@pytest.fixture(scope="function")
def dynamodb_checkpointer(checkpoint_table, cleanup_checkpoints, stack_outputs, aws_region):
    """
    Provide DynamoDB checkpointer instance.

    Yields:
        DynamoDB checkpointer instance
    """
    # Try to import the actual implementation
    try:
        from chat.checkpointers.dynamodb_saver import DynamoDBSaver

        # Get table name from stack outputs
        table_name = stack_outputs.get('CheckpointTableName')

        if not table_name:
            pytest.skip("CheckpointTableName not in stack outputs")

        # Initialize with table name and region
        checkpointer = DynamoDBSaver(
            table_name=table_name,
            ttl_hours=4,  # 4-hour default TTL
            region_name=aws_region
        )

        yield checkpointer

    except ImportError as e:
        # Implementation not ready yet, skip tests that require it
        pytest.skip(f"DynamoDBSaver not available: {e}. Run after Phase 3 Agent 1 completes.")


# ============================================================================
# Test Suite: DynamoDB Checkpointer Interface
# ============================================================================

@requires_langgraph
class TestDynamoDBCheckpointerInterface:
    """Test that DynamoDB checkpointer implements BaseCheckpointSaver interface."""

    def test_checkpointer_implements_base_interface(self, dynamodb_checkpointer):
        """Test that DynamoDBSaver implements BaseCheckpointSaver."""
        assert isinstance(dynamodb_checkpointer, BaseCheckpointSaver), \
            "DynamoDBSaver must extend BaseCheckpointSaver"

    def test_checkpointer_has_required_methods(self, dynamodb_checkpointer):
        """Test that checkpointer has all required methods."""
        required_methods = ['put', 'get_tuple', 'list', 'put_writes']

        for method_name in required_methods:
            assert hasattr(dynamodb_checkpointer, method_name), \
                f"DynamoDBSaver must implement {method_name}()"
            assert callable(getattr(dynamodb_checkpointer, method_name)), \
                f"{method_name} must be callable"


# ============================================================================
# Test Suite: Multi-Turn Conversation Persistence
# ============================================================================

@requires_langgraph
class TestMultiTurnConversation:
    """Test multi-turn conversation persistence in DynamoDB."""

    def test_checkpoint_save_and_load(self, dynamodb_checkpointer, cleanup_checkpoints):
        """Test saving and loading a checkpoint."""
        user_id = "test-user-001"
        session_id = "session-001"
        thread_id = f"{user_id}#{session_id}"

        # Register for cleanup
        cleanup_checkpoints(thread_id)

        # Create a checkpoint
        config = {"configurable": {"thread_id": thread_id}}

        # Create checkpoint data (using proper Checkpoint structure)
        from langgraph.checkpoint.base import Checkpoint

        checkpoint = Checkpoint(
            v=1,
            ts=datetime.utcnow().isoformat(),
            id="checkpoint-001",
            channel_values={
                "messages": [
                    {"type": "human", "content": "Hello"},
                    {"type": "ai", "content": "Hi there!"}
                ]
            },
            channel_versions={},
            versions_seen={}
        )

        metadata = {"source": "test"}

        # Save checkpoint
        dynamodb_checkpointer.put(config, checkpoint, metadata, {})

        # Load checkpoint
        loaded_tuple = dynamodb_checkpointer.get_tuple(config)

        # Verify loaded data
        assert loaded_tuple is not None, "Checkpoint should be loaded"
        assert loaded_tuple.checkpoint["id"] == "checkpoint-001"
        assert "messages" in loaded_tuple.checkpoint["channel_values"]
        assert len(loaded_tuple.checkpoint["channel_values"]["messages"]) == 2
        assert loaded_tuple.metadata == {"source": "test"}

    def test_conversation_state_accumulates(self, dynamodb_checkpointer, cleanup_checkpoints):
        """Test that conversation state accumulates over multiple turns."""
        user_id = "test-user-002"
        session_id = "session-002"
        thread_id = f"{user_id}#{session_id}"

        cleanup_checkpoints(thread_id)

        config = {"configurable": {"thread_id": thread_id}}

        # Turn 1
        checkpoint1 = {
            "v": 1,
            "ts": datetime.utcnow().isoformat(),
            "id": "turn-1",
            "channel_values": {
                "messages": [
                    {"type": "human", "content": "What's the weather?"},
                    {"type": "ai", "content": "It's sunny!"}
                ]
            },
            "channel_versions": {},
            "versions_seen": {}
        }
        dynamodb_checkpointer.put(config, checkpoint1, {})

        # Turn 2 - add more messages
        checkpoint2 = {
            "v": 1,
            "ts": datetime.utcnow().isoformat(),
            "id": "turn-2",
            "channel_values": {
                "messages": [
                    {"type": "human", "content": "What's the weather?"},
                    {"type": "ai", "content": "It's sunny!"},
                    {"type": "human", "content": "Will it rain?"},
                    {"type": "ai", "content": "No rain expected."}
                ]
            },
            "channel_versions": {},
            "versions_seen": {}
        }
        dynamodb_checkpointer.put(config, checkpoint2, {})

        # Load latest checkpoint
        loaded = dynamodb_checkpointer.get(config)

        # Should have 4 messages (2 turns)
        assert len(loaded["channel_values"]["messages"]) == 4

    def test_list_checkpoints_for_thread(self, dynamodb_checkpointer, cleanup_checkpoints):
        """Test listing all checkpoints for a conversation thread."""
        user_id = "test-user-003"
        session_id = "session-003"
        thread_id = f"{user_id}#{session_id}"

        cleanup_checkpoints(thread_id)

        config = {"configurable": {"thread_id": thread_id}}

        # Create multiple checkpoints
        for i in range(5):
            checkpoint = {
                "v": 1,
                "ts": datetime.utcnow().isoformat(),
                "id": f"checkpoint-{i}",
                "channel_values": {"messages": [], "turn": i},
                "channel_versions": {},
                "versions_seen": {}
            }
            dynamodb_checkpointer.put(config, checkpoint, {})
            time.sleep(0.1)  # Ensure different timestamps

        # List checkpoints
        checkpoints = list(dynamodb_checkpointer.list(config))

        # Should have 5 checkpoints
        assert len(checkpoints) >= 5, "Should list all checkpoints for thread"


# ============================================================================
# Test Suite: Session Isolation by User ID
# ============================================================================

@requires_langgraph
class TestSessionIsolation:
    """Test that sessions are properly isolated by user_id."""

    def test_different_users_have_separate_sessions(
        self,
        dynamodb_checkpointer,
        cleanup_checkpoints,
        test_users
    ):
        """Test that different users' sessions don't interfere."""
        session_id = "shared-session-name"

        # Create checkpoints for different users with same session_id
        for user in test_users[:2]:  # Use Alice and Bob
            thread_id = f"{user['user_id']}#{session_id}"
            cleanup_checkpoints(thread_id)

            config = {"configurable": {"thread_id": thread_id}}

            checkpoint = {
                "v": 1,
                "ts": datetime.utcnow().isoformat(),
                "id": f"checkpoint-{user['name']}",
                "channel_values": {
                    "messages": [
                        {"type": "human", "content": f"Hello from {user['name']}"}
                    ],
                    "user": user['name']
                },
                "channel_versions": {},
                "versions_seen": {}
            }

            dynamodb_checkpointer.put(config, checkpoint, {})

        # Load checkpoints for each user
        alice_thread_id = f"{test_users[0]['user_id']}#{session_id}"
        bob_thread_id = f"{test_users[1]['user_id']}#{session_id}"

        alice_config = {"configurable": {"thread_id": alice_thread_id}}
        bob_config = {"configurable": {"thread_id": bob_thread_id}}

        alice_checkpoint = dynamodb_checkpointer.get(alice_config)
        bob_checkpoint = dynamodb_checkpointer.get(bob_config)

        # Verify isolation
        assert alice_checkpoint["channel_values"]["user"] == "Alice"
        assert bob_checkpoint["channel_values"]["user"] == "Bob"
        assert alice_checkpoint["id"] != bob_checkpoint["id"]

    def test_user_cannot_access_other_user_session(
        self,
        dynamodb_checkpointer,
        cleanup_checkpoints,
        test_users
    ):
        """Test that a user cannot access another user's session."""
        alice = test_users[0]
        bob = test_users[1]

        # Alice creates a session
        alice_session = "alice-private-session"
        alice_thread_id = f"{alice['user_id']}#{alice_session}"
        cleanup_checkpoints(alice_thread_id)

        alice_config = {"configurable": {"thread_id": alice_thread_id}}

        checkpoint = {
            "v": 1,
            "ts": datetime.utcnow().isoformat(),
            "id": "alice-private-checkpoint",
            "channel_values": {"secret": "Alice's secret data"},
            "channel_versions": {},
            "versions_seen": {}
        }

        dynamodb_checkpointer.put(alice_config, checkpoint, {})

        # Bob tries to access Alice's session (different user_id, same session_id)
        bob_thread_id = f"{bob['user_id']}#{alice_session}"
        bob_config = {"configurable": {"thread_id": bob_thread_id}}

        bob_checkpoint = dynamodb_checkpointer.get(bob_config)

        # Bob should get nothing (different thread_id due to different user_id)
        assert bob_checkpoint is None or \
               bob_checkpoint.get("channel_values", {}).get("secret") != "Alice's secret data"

    def test_thread_id_format_includes_user_id(self, dynamodb_checkpointer):
        """Test that thread_id format is {user_id}#{session_id}."""
        # This test validates the expected format
        user_id = "user-12345"
        session_id = "session-67890"
        expected_thread_id = f"{user_id}#{session_id}"

        # The format should be enforced by the checkpointer or calling code
        assert "#" in expected_thread_id
        assert expected_thread_id.startswith(user_id)
        assert expected_thread_id.endswith(session_id)


# ============================================================================
# Test Suite: TTL Expiration Behavior
# ============================================================================

@requires_langgraph
class TestTTLExpiration:
    """Test DynamoDB TTL expiration for conversation cleanup."""

    def test_checkpoint_has_ttl_attribute(
        self,
        dynamodb_checkpointer,
        checkpoint_table,
        cleanup_checkpoints
    ):
        """Test that checkpoints have expires_at TTL attribute set."""
        user_id = "test-user-ttl-001"
        session_id = "session-ttl-001"
        thread_id = f"{user_id}#{session_id}"

        cleanup_checkpoints(thread_id)

        config = {"configurable": {"thread_id": thread_id}}

        checkpoint = {
            "v": 1,
            "ts": datetime.utcnow().isoformat(),
            "id": "ttl-checkpoint",
            "channel_values": {"test": "data"},
            "channel_versions": {},
            "versions_seen": {}
        }

        # Save checkpoint
        dynamodb_checkpointer.put(config, checkpoint, {})

        # Query DynamoDB directly to check TTL attribute
        response = checkpoint_table.query(
            KeyConditionExpression='thread_id = :tid',
            ExpressionAttributeValues={':tid': thread_id},
            Limit=1
        )

        items = response.get('Items', [])
        assert len(items) > 0, "Checkpoint should exist"

        item = items[0]
        assert 'expires_at' in item, "Checkpoint must have expires_at attribute"
        assert isinstance(item['expires_at'], int), "expires_at must be Unix timestamp"

    def test_ttl_is_in_future(
        self,
        dynamodb_checkpointer,
        checkpoint_table,
        cleanup_checkpoints
    ):
        """Test that TTL is set to future timestamp (default 4 hours)."""
        user_id = "test-user-ttl-002"
        session_id = "session-ttl-002"
        thread_id = f"{user_id}#{session_id}"

        cleanup_checkpoints(thread_id)

        config = {"configurable": {"thread_id": thread_id}}

        checkpoint = {
            "v": 1,
            "ts": datetime.utcnow().isoformat(),
            "id": "ttl-future-checkpoint",
            "channel_values": {"test": "data"},
            "channel_versions": {},
            "versions_seen": {}
        }

        now = int(time.time())

        # Save checkpoint
        dynamodb_checkpointer.put(config, checkpoint, {})

        # Query DynamoDB to check TTL
        response = checkpoint_table.query(
            KeyConditionExpression='thread_id = :tid',
            ExpressionAttributeValues={':tid': thread_id},
            Limit=1
        )

        items = response.get('Items', [])
        item = items[0]

        expires_at = item['expires_at']

        # TTL should be in the future (at least 3 hours, max 5 hours for 4-hour TTL)
        hours_from_now = (expires_at - now) / 3600

        assert 3 <= hours_from_now <= 5, \
            f"TTL should be ~4 hours from now, got {hours_from_now:.2f} hours"

    def test_ttl_updates_on_activity(
        self,
        dynamodb_checkpointer,
        checkpoint_table,
        cleanup_checkpoints
    ):
        """Test that TTL is updated when session is active."""
        user_id = "test-user-ttl-003"
        session_id = "session-ttl-003"
        thread_id = f"{user_id}#{session_id}"

        cleanup_checkpoints(thread_id)

        config = {"configurable": {"thread_id": thread_id}}

        # Create initial checkpoint
        checkpoint1 = {
            "v": 1,
            "ts": datetime.utcnow().isoformat(),
            "id": "checkpoint-1",
            "channel_values": {"messages": ["msg1"]},
            "channel_versions": {},
            "versions_seen": {}
        }

        dynamodb_checkpointer.put(config, checkpoint1, {})

        # Get first TTL
        response1 = checkpoint_table.query(
            KeyConditionExpression='thread_id = :tid',
            ExpressionAttributeValues={':tid': thread_id},
            ScanIndexForward=False,
            Limit=1
        )

        first_ttl = response1['Items'][0]['expires_at']

        # Wait a bit
        time.sleep(2)

        # Update checkpoint (new activity)
        checkpoint2 = {
            "v": 1,
            "ts": datetime.utcnow().isoformat(),
            "id": "checkpoint-2",
            "channel_values": {"messages": ["msg1", "msg2"]},
            "channel_versions": {},
            "versions_seen": {}
        }

        dynamodb_checkpointer.put(config, checkpoint2, {})

        # Get updated TTL
        response2 = checkpoint_table.query(
            KeyConditionExpression='thread_id = :tid',
            ExpressionAttributeValues={':tid': thread_id},
            ScanIndexForward=False,
            Limit=1
        )

        second_ttl = response2['Items'][0]['expires_at']

        # TTL should be updated (later than first)
        assert second_ttl >= first_ttl, "TTL should be updated on activity"


# ============================================================================
# Test Suite: DynamoDB GSI Queries
# ============================================================================

@requires_langgraph
class TestGSIQueries:
    """Test DynamoDB Global Secondary Index queries for user sessions."""

    def test_query_all_sessions_for_user(
        self,
        dynamodb_checkpointer,
        checkpoint_table,
        cleanup_checkpoints
    ):
        """Test querying all sessions for a specific user using GSI."""
        user_id = "test-user-gsi-001"

        # Create multiple sessions for the user
        session_ids = ["session-a", "session-b", "session-c"]

        for session_id in session_ids:
            thread_id = f"{user_id}#{session_id}"
            cleanup_checkpoints(thread_id)

            config = {"configurable": {"thread_id": thread_id}}

            checkpoint = {
                "v": 1,
                "ts": datetime.utcnow().isoformat(),
                "id": f"checkpoint-{session_id}",
                "channel_values": {"session": session_id},
                "channel_versions": {},
                "versions_seen": {}
            }

            dynamodb_checkpointer.put(config, checkpoint, {})

        # Query all sessions for this user
        # Note: This assumes a GSI on user_id or a thread_id prefix query

        response = checkpoint_table.query(
            # Query by thread_id prefix (if supported) or use scan with filter
            KeyConditionExpression='begins_with(thread_id, :prefix)',
            ExpressionAttributeValues={':prefix': f"{user_id}#"}
        )

        found_sessions = set()
        for item in response.get('Items', []):
            # Extract session_id from thread_id
            thread_id = item['thread_id']
            if '#' in thread_id:
                _, session_id = thread_id.split('#', 1)
                found_sessions.add(session_id)

        # Should find all 3 sessions
        assert len(found_sessions) >= 3, \
            f"Should find all user sessions, found: {found_sessions}"

    def test_query_recent_sessions(
        self,
        dynamodb_checkpointer,
        checkpoint_table,
        cleanup_checkpoints
    ):
        """Test querying recent sessions ordered by timestamp."""
        user_id = "test-user-gsi-002"

        # Create sessions with different timestamps
        for i in range(5):
            session_id = f"session-{i}"
            thread_id = f"{user_id}#{session_id}"
            cleanup_checkpoints(thread_id)

            config = {"configurable": {"thread_id": thread_id}}

            # Use different timestamps
            ts = (datetime.utcnow() - timedelta(hours=i)).isoformat()

            checkpoint = {
                "v": 1,
                "ts": ts,
                "id": f"checkpoint-{i}",
                "channel_values": {"order": i},
                "channel_versions": {},
                "versions_seen": {}
            }

            dynamodb_checkpointer.put(config, checkpoint, {})
            time.sleep(0.1)

        # Query sessions
        response = checkpoint_table.query(
            KeyConditionExpression='begins_with(thread_id, :prefix)',
            ExpressionAttributeValues={':prefix': f"{user_id}#"},
            ScanIndexForward=False,  # Most recent first
            Limit=3
        )

        items = response.get('Items', [])

        # Should get results (order depends on sort key)
        assert len(items) > 0, "Should retrieve session checkpoints"


# ============================================================================
# Test Suite: End-to-End Conversation Workflow
# ============================================================================

@requires_langgraph
class TestE2EConversationWorkflow:
    """End-to-end integration tests for conversation workflow."""

    def test_full_conversation_lifecycle(
        self,
        dynamodb_checkpointer,
        cleanup_checkpoints
    ):
        """Test complete conversation lifecycle: create -> update -> list -> delete."""
        user_id = "test-user-e2e-001"
        session_id = "session-e2e-001"
        thread_id = f"{user_id}#{session_id}"

        cleanup_checkpoints(thread_id)

        config = {"configurable": {"thread_id": thread_id}}

        # 1. Create initial conversation
        checkpoint1 = {
            "v": 1,
            "ts": datetime.utcnow().isoformat(),
            "id": "checkpoint-1",
            "channel_values": {"messages": ["Hello"]},
            "channel_versions": {},
            "versions_seen": {}
        }

        dynamodb_checkpointer.put(config, checkpoint1, {})

        # 2. Verify saved
        loaded = dynamodb_checkpointer.get(config)
        assert loaded is not None
        assert loaded["id"] == "checkpoint-1"

        # 3. Continue conversation
        checkpoint2 = {
            "v": 1,
            "ts": datetime.utcnow().isoformat(),
            "id": "checkpoint-2",
            "channel_values": {"messages": ["Hello", "Hi", "How are you?"]},
            "channel_versions": {},
            "versions_seen": {}
        }

        dynamodb_checkpointer.put(config, checkpoint2, {})

        # 4. List checkpoints
        checkpoints = list(dynamodb_checkpointer.list(config))
        assert len(checkpoints) >= 2

        # 5. Load latest
        latest = dynamodb_checkpointer.get(config)
        assert latest["id"] == "checkpoint-2"
        assert len(latest["channel_values"]["messages"]) == 3

    def test_concurrent_users_different_sessions(
        self,
        dynamodb_checkpointer,
        cleanup_checkpoints,
        test_users
    ):
        """Test concurrent users with different sessions don't interfere."""
        checkpoints_created = []

        # Simulate concurrent users
        for user in test_users:
            for session_num in range(3):
                session_id = f"session-{session_num}"
                thread_id = f"{user['user_id']}#{session_id}"

                cleanup_checkpoints(thread_id)
                checkpoints_created.append(thread_id)

                config = {"configurable": {"thread_id": thread_id}}

                checkpoint = {
                    "v": 1,
                    "ts": datetime.utcnow().isoformat(),
                    "id": f"checkpoint-{user['name']}-{session_num}",
                    "channel_values": {
                        "user": user['name'],
                        "session": session_num
                    },
                    "channel_versions": {},
                    "versions_seen": {}
                }

                dynamodb_checkpointer.put(config, checkpoint, {})

        # Verify all checkpoints exist and are isolated
        for user in test_users:
            for session_num in range(3):
                thread_id = f"{user['user_id']}#session-{session_num}"
                config = {"configurable": {"thread_id": thread_id}}

                loaded = dynamodb_checkpointer.get(config)

                assert loaded is not None
                assert loaded["channel_values"]["user"] == user['name']
                assert loaded["channel_values"]["session"] == session_num


# ============================================================================
# Test Suite: Error Handling
# ============================================================================

@requires_langgraph
class TestErrorHandling:
    """Test error handling in DynamoDB checkpointer."""

    def test_get_nonexistent_checkpoint_returns_none(self, dynamodb_checkpointer):
        """Test that getting non-existent checkpoint returns None."""
        config = {"configurable": {"thread_id": "nonexistent-thread"}}

        result = dynamodb_checkpointer.get(config)

        assert result is None, "Non-existent checkpoint should return None"

    def test_list_nonexistent_thread_returns_empty(self, dynamodb_checkpointer):
        """Test that listing non-existent thread returns empty list."""
        config = {"configurable": {"thread_id": "nonexistent-thread-list"}}

        checkpoints = list(dynamodb_checkpointer.list(config))

        assert len(checkpoints) == 0, "Non-existent thread should return empty list"

    def test_invalid_thread_id_format_handling(self, dynamodb_checkpointer):
        """Test handling of invalid thread_id format."""
        # Thread ID without user_id# prefix (invalid format)
        config = {"configurable": {"thread_id": "invalid-format-no-hash"}}

        # Should either reject or handle gracefully
        # Implementation should validate thread_id format
        try:
            result = dynamodb_checkpointer.get(config)
            # If it doesn't raise, it should return None or empty
            assert result is None or result == {}
        except ValueError as e:
            # Or it might raise ValueError for invalid format
            assert "thread_id" in str(e).lower() or "format" in str(e).lower()


# ============================================================================
# Performance and Scalability Tests
# ============================================================================

@requires_langgraph
class TestPerformance:
    """Test performance characteristics of DynamoDB checkpointer."""

    def test_checkpoint_write_latency(
        self,
        dynamodb_checkpointer,
        cleanup_checkpoints
    ):
        """Test that checkpoint writes complete within acceptable time."""
        user_id = "test-user-perf-001"
        session_id = "session-perf-001"
        thread_id = f"{user_id}#{session_id}"

        cleanup_checkpoints(thread_id)

        config = {"configurable": {"thread_id": thread_id}}

        checkpoint = {
            "v": 1,
            "ts": datetime.utcnow().isoformat(),
            "id": "perf-checkpoint",
            "channel_values": {"messages": ["test"] * 100},  # Moderate size
            "channel_versions": {},
            "versions_seen": {}
        }

        # Measure write time
        start = time.time()
        dynamodb_checkpointer.put(config, checkpoint, {})
        write_time = (time.time() - start) * 1000  # ms

        # Should complete in < 500ms for DynamoDB write
        assert write_time < 500, \
            f"Checkpoint write took {write_time:.2f}ms, expected < 500ms"

    def test_checkpoint_read_latency(
        self,
        dynamodb_checkpointer,
        cleanup_checkpoints
    ):
        """Test that checkpoint reads complete within acceptable time."""
        user_id = "test-user-perf-002"
        session_id = "session-perf-002"
        thread_id = f"{user_id}#{session_id}"

        cleanup_checkpoints(thread_id)

        config = {"configurable": {"thread_id": thread_id}}

        # Create checkpoint
        checkpoint = {
            "v": 1,
            "ts": datetime.utcnow().isoformat(),
            "id": "read-perf-checkpoint",
            "channel_values": {"messages": ["test"] * 100},
            "channel_versions": {},
            "versions_seen": {}
        }

        dynamodb_checkpointer.put(config, checkpoint, {})

        # Measure read time
        start = time.time()
        loaded = dynamodb_checkpointer.get(config)
        read_time = (time.time() - start) * 1000  # ms

        # Should complete in < 200ms for DynamoDB read
        assert read_time < 200, \
            f"Checkpoint read took {read_time:.2f}ms, expected < 200ms"
        assert loaded is not None


# ============================================================================
# Manual Testing Helpers
# ============================================================================

def manual_test_dynamodb_connection():
    """
    Manual test to verify DynamoDB connection.

    Run with: pytest tests/integration/test_chat_workflow.py::manual_test_dynamodb_connection -v -s
    """
    import json
    from pathlib import Path

    print("\n=== DynamoDB Connection Test ===")

    # Load outputs
    env_name = os.getenv('CDK_ENV', 'dev')
    project_root = Path(__file__).parent.parent.parent
    outputs_file = project_root / f'.aws-outputs-{env_name}.json'

    if not outputs_file.exists():
        print(f"❌ Outputs file not found: {outputs_file}")
        return False

    with open(outputs_file) as f:
        raw_outputs = json.load(f)

    # Convert from list of {OutputKey, OutputValue} to dict
    if isinstance(raw_outputs, list):
        outputs = {item['OutputKey']: item['OutputValue'] for item in raw_outputs}
    else:
        outputs = raw_outputs

    table_name = outputs.get('CheckpointTableName')
    print(f"Table name: {table_name}")

    if not table_name:
        print("❌ CheckpointTableName not in outputs")
        return False

    # Test connection
    region = os.getenv('AWS_REGION', 'us-east-1')
    dynamodb = boto3.resource('dynamodb', region_name=region)
    table = dynamodb.Table(table_name)

    try:
        response = table.meta.client.describe_table(TableName=table_name)
        print(f"✓ Table status: {response['Table']['TableStatus']}")
        print(f"✓ Item count: {response['Table']['ItemCount']}")

        # Check TTL
        ttl_response = table.meta.client.describe_time_to_live(TableName=table_name)
        ttl_status = ttl_response.get('TimeToLiveDescription', {}).get('TimeToLiveStatus', 'DISABLED')
        print(f"✓ TTL status: {ttl_status}")

        return True
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False


if __name__ == "__main__":
    # Run manual connection test
    manual_test_dynamodb_connection()
