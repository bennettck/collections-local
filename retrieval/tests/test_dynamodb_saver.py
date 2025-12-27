"""Unit tests for DynamoDBSaver checkpoint implementation.

Uses moto to mock DynamoDB for testing without AWS infrastructure.
"""

import os
import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from moto import mock_aws
import boto3

from chat.checkpointers.dynamodb_saver import DynamoDBSaver
from langgraph.checkpoint.base import CheckpointTuple


# Test fixtures
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
def saver(dynamodb_table):
    """Create a DynamoDBSaver instance for testing."""
    with mock_aws():
        return DynamoDBSaver(
            table_name='test-checkpoints',
            ttl_hours=4,
            region_name='us-east-1'
        )


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


class TestDynamoDBSaverInit:
    """Test DynamoDBSaver initialization."""

    def test_init_with_defaults(self):
        """Test initialization with default parameters."""
        with mock_aws():
            # Create table first
            dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
            dynamodb.create_table(
                TableName='test-table',
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

            saver = DynamoDBSaver(table_name='test-table')
            assert saver.table_name == 'test-table'
            assert saver.ttl_hours == 4
            assert saver.table is not None

    def test_init_with_custom_ttl(self):
        """Test initialization with custom TTL."""
        with mock_aws():
            # Create table first
            dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
            dynamodb.create_table(
                TableName='test-table',
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

            saver = DynamoDBSaver(table_name='test-table', ttl_hours=8)
            assert saver.ttl_hours == 8


class TestDynamoDBSaverTTL:
    """Test TTL calculation."""

    def test_calculate_ttl(self, saver):
        """Test TTL calculation returns future timestamp."""
        ttl = saver._calculate_ttl()

        # TTL should be in the future
        current_time = int(datetime.utcnow().timestamp())
        assert ttl > current_time

        # TTL should be approximately 4 hours from now
        expected_ttl = current_time + (4 * 3600)
        assert abs(ttl - expected_ttl) < 60  # Within 1 minute


class TestDynamoDBSaverThreadID:
    """Test thread ID extraction."""

    def test_get_thread_id_success(self, saver):
        """Test successful thread ID extraction."""
        config = {
            "configurable": {
                "thread_id": "user123#session456"
            }
        }
        thread_id = saver._get_thread_id(config)
        assert thread_id == "user123#session456"

    def test_get_thread_id_missing_raises_error(self, saver):
        """Test that missing thread_id raises ValueError."""
        config = {"configurable": {}}

        with pytest.raises(ValueError, match="thread_id must be provided"):
            saver._get_thread_id(config)


class TestDynamoDBSaverPut:
    """Test checkpoint storage."""

    def test_put_checkpoint(self, saver, sample_checkpoint, sample_metadata, sample_config):
        """Test storing a checkpoint."""
        result_config = saver.put(
            config=sample_config,
            checkpoint=sample_checkpoint,
            metadata=sample_metadata,
            new_versions={}
        )

        # Verify returned config
        assert result_config["configurable"]["thread_id"] == "user123#session456"
        assert result_config["configurable"]["checkpoint_id"] == "test-checkpoint-123"

        # Verify checkpoint was stored in DynamoDB
        response = saver.table.get_item(
            Key={
                'thread_id': 'user123#session456',
                'sort_key': '#test-checkpoint-123'
            }
        )

        assert 'Item' in response
        item = response['Item']
        assert item['thread_id'] == 'user123#session456'
        assert item['checkpoint_id'] == 'test-checkpoint-123'
        assert 'expires_at' in item
        assert 'checkpoint_data' in item

    def test_put_checkpoint_with_parent(self, saver, sample_checkpoint, sample_metadata):
        """Test storing a checkpoint with parent reference."""
        config = {
            "configurable": {
                "thread_id": "user123#session456",
                "checkpoint_ns": "",
                "checkpoint_id": "parent-checkpoint-123"
            }
        }

        sample_checkpoint["id"] = "child-checkpoint-456"

        result_config = saver.put(
            config=config,
            checkpoint=sample_checkpoint,
            metadata=sample_metadata,
            new_versions={}
        )

        # Verify parent checkpoint ID is stored
        response = saver.table.get_item(
            Key={
                'thread_id': 'user123#session456',
                'sort_key': '#child-checkpoint-456'
            }
        )

        assert 'Item' in response
        assert response['Item']['parent_checkpoint_id'] == 'parent-checkpoint-123'


class TestDynamoDBSaverGet:
    """Test checkpoint retrieval."""

    def test_get_tuple_latest(self, saver, sample_checkpoint, sample_metadata, sample_config):
        """Test retrieving the latest checkpoint."""
        # Store a checkpoint
        saver.put(sample_config, sample_checkpoint, sample_metadata, {})

        # Retrieve it
        tuple_result = saver.get_tuple(sample_config)

        assert tuple_result is not None
        assert isinstance(tuple_result, CheckpointTuple)
        assert tuple_result.checkpoint is not None
        assert tuple_result.metadata is not None

    def test_get_tuple_specific_checkpoint(self, saver, sample_checkpoint, sample_metadata):
        """Test retrieving a specific checkpoint by ID."""
        # Store a checkpoint
        config = {
            "configurable": {
                "thread_id": "user123#session456",
                "checkpoint_ns": ""
            }
        }
        saver.put(config, sample_checkpoint, sample_metadata, {})

        # Retrieve specific checkpoint
        get_config = {
            "configurable": {
                "thread_id": "user123#session456",
                "checkpoint_ns": "",
                "checkpoint_id": "test-checkpoint-123"
            }
        }

        tuple_result = saver.get_tuple(get_config)

        assert tuple_result is not None
        assert tuple_result.checkpoint["id"] == "test-checkpoint-123"

    def test_get_tuple_not_found(self, saver):
        """Test retrieving non-existent checkpoint returns None."""
        config = {
            "configurable": {
                "thread_id": "nonexistent",
                "checkpoint_ns": "",
                "checkpoint_id": "nonexistent"
            }
        }

        tuple_result = saver.get_tuple(config)
        assert tuple_result is None

    def test_get_checkpoint(self, saver, sample_checkpoint, sample_metadata, sample_config):
        """Test get() method returns checkpoint."""
        # Store a checkpoint
        saver.put(sample_config, sample_checkpoint, sample_metadata, {})

        # Retrieve it using get()
        checkpoint = saver.get(sample_config)

        assert checkpoint is not None
        assert checkpoint["id"] == "test-checkpoint-123"


class TestDynamoDBSaverList:
    """Test checkpoint listing."""

    def test_list_checkpoints(self, saver, sample_metadata):
        """Test listing checkpoints for a thread."""
        config = {
            "configurable": {
                "thread_id": "user123#session456",
                "checkpoint_ns": ""
            }
        }

        # Store multiple checkpoints
        for i in range(3):
            checkpoint = {
                "v": 1,
                "id": f"checkpoint-{i}",
                "ts": datetime.utcnow().isoformat(),
                "channel_values": {"counter": i},
                "channel_versions": {"__start__": i},
                "versions_seen": {}
            }
            saver.put(config, checkpoint, sample_metadata, {})

        # List checkpoints
        checkpoints = list(saver.list(config))

        assert len(checkpoints) == 3
        assert all(isinstance(cp, CheckpointTuple) for cp in checkpoints)

    def test_list_with_limit(self, saver, sample_metadata):
        """Test listing checkpoints with limit."""
        config = {
            "configurable": {
                "thread_id": "user123#session456",
                "checkpoint_ns": ""
            }
        }

        # Store multiple checkpoints
        for i in range(5):
            checkpoint = {
                "v": 1,
                "id": f"checkpoint-{i}",
                "ts": datetime.utcnow().isoformat(),
                "channel_values": {"counter": i},
                "channel_versions": {"__start__": i},
                "versions_seen": {}
            }
            saver.put(config, checkpoint, sample_metadata, {})

        # List with limit
        checkpoints = list(saver.list(config, limit=2))

        assert len(checkpoints) <= 2

    def test_list_empty_thread(self, saver):
        """Test listing checkpoints for empty thread."""
        config = {
            "configurable": {
                "thread_id": "empty-thread",
                "checkpoint_ns": ""
            }
        }

        checkpoints = list(saver.list(config))
        assert len(checkpoints) == 0


class TestDynamoDBSaverDelete:
    """Test checkpoint deletion."""

    def test_delete_thread(self, saver, sample_metadata):
        """Test deleting all checkpoints for a thread."""
        thread_id = "user123#session456"
        config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": ""
            }
        }

        # Store multiple checkpoints
        for i in range(3):
            checkpoint = {
                "v": 1,
                "id": f"checkpoint-{i}",
                "ts": datetime.utcnow().isoformat(),
                "channel_values": {"counter": i},
                "channel_versions": {"__start__": i},
                "versions_seen": {}
            }
            saver.put(config, checkpoint, sample_metadata, {})

        # Verify checkpoints exist
        checkpoints_before = list(saver.list(config))
        assert len(checkpoints_before) == 3

        # Delete thread
        saver.delete_thread(thread_id)

        # Verify checkpoints are gone
        checkpoints_after = list(saver.list(config))
        assert len(checkpoints_after) == 0


class TestDynamoDBSaverPutWrites:
    """Test storing intermediate writes."""

    def test_put_writes(self, saver, sample_checkpoint, sample_metadata):
        """Test storing intermediate writes."""
        config = {
            "configurable": {
                "thread_id": "user123#session456",
                "checkpoint_ns": "",
            }
        }

        # Store a checkpoint first
        result_config = saver.put(config, sample_checkpoint, sample_metadata, {})

        # Add writes
        writes = [
            ("channel1", {"data": "value1"}),
            ("channel2", {"data": "value2"})
        ]

        saver.put_writes(
            config=result_config,
            writes=writes,
            task_id="task-123"
        )

        # Verify writes were stored
        tuple_result = saver.get_tuple(result_config)
        assert tuple_result is not None
        assert len(tuple_result.pending_writes) > 0


class TestDynamoDBSaverSerialization:
    """Test serialization/deserialization."""

    def test_metadata_decimal_conversion(self, saver):
        """Test that float values in metadata are converted to Decimal."""
        metadata = {
            "score": 0.95,
            "confidence": 0.87,
            "count": 10
        }

        serialized = saver._serialize_metadata(metadata)

        assert isinstance(serialized["score"], Decimal)
        assert isinstance(serialized["confidence"], Decimal)
        assert serialized["count"] == 10

    def test_metadata_decimal_deserialization(self, saver):
        """Test that Decimal values are converted back to float."""
        metadata = {
            "score": Decimal("0.95"),
            "confidence": Decimal("0.87"),
            "count": 10
        }

        deserialized = saver._deserialize_metadata(metadata)

        assert isinstance(deserialized["score"], float)
        assert isinstance(deserialized["confidence"], float)
        assert deserialized["score"] == 0.95
        assert deserialized["count"] == 10


class TestDynamoDBSaverMultiTenancy:
    """Test multi-tenancy with user_id#session_id format."""

    def test_different_users_isolated(self, saver, sample_checkpoint, sample_metadata):
        """Test that different users' checkpoints are isolated."""
        # Store checkpoint for user1
        config1 = {
            "configurable": {
                "thread_id": "user1#session1",
                "checkpoint_ns": ""
            }
        }
        checkpoint1 = sample_checkpoint.copy()
        checkpoint1["id"] = "user1-checkpoint"
        saver.put(config1, checkpoint1, sample_metadata, {})

        # Store checkpoint for user2
        config2 = {
            "configurable": {
                "thread_id": "user2#session1",
                "checkpoint_ns": ""
            }
        }
        checkpoint2 = sample_checkpoint.copy()
        checkpoint2["id"] = "user2-checkpoint"
        saver.put(config2, checkpoint2, sample_metadata, {})

        # Verify user1 only sees their checkpoint
        user1_checkpoints = list(saver.list(config1))
        assert len(user1_checkpoints) == 1
        assert user1_checkpoints[0].checkpoint["id"] == "user1-checkpoint"

        # Verify user2 only sees their checkpoint
        user2_checkpoints = list(saver.list(config2))
        assert len(user2_checkpoints) == 1
        assert user2_checkpoints[0].checkpoint["id"] == "user2-checkpoint"
