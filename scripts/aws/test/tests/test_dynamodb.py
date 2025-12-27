"""
Test 3: DynamoDB Table Schema

Validates:
- Table exists and is ACTIVE
- Partition key (thread_id) configured correctly
- Sort key (checkpoint_id) configured correctly
- GSI (user_id-last_activity-index) exists
- Basic CRUD operations work
"""

import pytest
import time
import uuid


@pytest.mark.integration
def test_dynamodb_table_exists(dynamodb_table):
    """Verify DynamoDB table exists and is accessible."""
    # boto3 Table resource validates existence
    assert dynamodb_table.table_name is not None


@pytest.mark.integration
def test_dynamodb_table_status(dynamodb_table, boto3_clients):
    """Verify table is in ACTIVE state."""
    dynamodb_client = boto3_clients['dynamodb_client']

    response = dynamodb_client.describe_table(
        TableName=dynamodb_table.table_name
    )

    table_status = response['Table']['TableStatus']
    assert table_status == 'ACTIVE', f"Table not active: {table_status}"


@pytest.mark.integration
def test_dynamodb_key_schema(dynamodb_table, boto3_clients):
    """Verify partition key (thread_id) and sort key (checkpoint_id)."""
    dynamodb_client = boto3_clients['dynamodb_client']

    response = dynamodb_client.describe_table(
        TableName=dynamodb_table.table_name
    )

    key_schema = response['Table']['KeySchema']

    # Convert to dict for easier checking
    keys = {item['AttributeName']: item['KeyType'] for item in key_schema}

    assert 'thread_id' in keys, "thread_id not found in key schema"
    assert keys['thread_id'] == 'HASH', "thread_id should be partition key (HASH)"

    assert 'checkpoint_id' in keys, "checkpoint_id not found in key schema"
    assert keys['checkpoint_id'] == 'RANGE', "checkpoint_id should be sort key (RANGE)"


@pytest.mark.integration
def test_dynamodb_gsi_exists(dynamodb_table, boto3_clients):
    """Verify GSI user_id-last_activity-index exists."""
    dynamodb_client = boto3_clients['dynamodb_client']

    response = dynamodb_client.describe_table(
        TableName=dynamodb_table.table_name
    )

    gsi_list = response['Table'].get('GlobalSecondaryIndexes', [])
    gsi_names = [gsi['IndexName'] for gsi in gsi_list]

    expected_gsi = 'user_id-last_activity-index'
    assert expected_gsi in gsi_names, f"GSI not found: {expected_gsi}"

    # Verify GSI structure
    gsi = next(g for g in gsi_list if g['IndexName'] == expected_gsi)

    assert gsi['IndexStatus'] == 'ACTIVE', f"GSI not active: {gsi['IndexStatus']}"

    # Verify GSI keys
    gsi_keys = {item['AttributeName']: item['KeyType'] for item in gsi['KeySchema']}

    assert 'user_id' in gsi_keys, "user_id not in GSI keys"
    assert gsi_keys['user_id'] == 'HASH', "user_id should be GSI partition key"

    assert 'last_activity' in gsi_keys, "last_activity not in GSI keys"
    assert gsi_keys['last_activity'] == 'RANGE', "last_activity should be GSI sort key"


@pytest.mark.integration
def test_dynamodb_put_item(dynamodb_table, cleanup_dynamodb_items):
    """Test putting item to DynamoDB."""
    thread_id = f"test-thread-{uuid.uuid4()}"
    checkpoint_id = f"checkpoint-{uuid.uuid4()}"

    # Register for cleanup
    cleanup_dynamodb_items(thread_id, checkpoint_id)

    # Put item
    dynamodb_table.put_item(
        Item={
            'thread_id': thread_id,
            'checkpoint_id': checkpoint_id,
            'user_id': 'test-user-123',
            'checkpoint': b'test checkpoint data',
            'created_at': int(time.time()),
            'expires_at': int(time.time()) + 3600,
            'last_activity': int(time.time()),
            'message_count': 1
        }
    )

    # Verify item was created
    response = dynamodb_table.get_item(
        Key={
            'thread_id': thread_id,
            'checkpoint_id': checkpoint_id
        }
    )

    assert 'Item' in response, "Item not found after put"
    assert response['Item']['user_id'] == 'test-user-123'


@pytest.mark.integration
def test_dynamodb_get_item(dynamodb_table, cleanup_dynamodb_items):
    """Test getting item from DynamoDB."""
    thread_id = f"test-thread-{uuid.uuid4()}"
    checkpoint_id = f"checkpoint-{uuid.uuid4()}"

    cleanup_dynamodb_items(thread_id, checkpoint_id)

    # Create item
    dynamodb_table.put_item(
        Item={
            'thread_id': thread_id,
            'checkpoint_id': checkpoint_id,
            'user_id': 'test-user-123',
            'created_at': int(time.time())
        }
    )

    # Get item
    response = dynamodb_table.get_item(
        Key={
            'thread_id': thread_id,
            'checkpoint_id': checkpoint_id
        }
    )

    assert 'Item' in response
    item = response['Item']

    assert item['thread_id'] == thread_id
    assert item['checkpoint_id'] == checkpoint_id
    assert item['user_id'] == 'test-user-123'


@pytest.mark.integration
def test_dynamodb_query_by_thread(dynamodb_table, cleanup_dynamodb_items):
    """Test querying all checkpoints for a thread."""
    thread_id = f"test-thread-{uuid.uuid4()}"

    # Create multiple checkpoints
    checkpoint_ids = []
    for i in range(3):
        checkpoint_id = f"checkpoint-{i}-{uuid.uuid4()}"
        checkpoint_ids.append(checkpoint_id)

        cleanup_dynamodb_items(thread_id, checkpoint_id)

        dynamodb_table.put_item(
            Item={
                'thread_id': thread_id,
                'checkpoint_id': checkpoint_id,
                'user_id': 'test-user-123',
                'created_at': int(time.time()) + i
            }
        )

    # Query by thread_id
    from boto3.dynamodb.conditions import Key

    response = dynamodb_table.query(
        KeyConditionExpression=Key('thread_id').eq(thread_id)
    )

    items = response['Items']
    assert len(items) == 3, f"Expected 3 items, got {len(items)}"

    # Verify all checkpoint_ids are present
    retrieved_ids = {item['checkpoint_id'] for item in items}
    assert set(checkpoint_ids) == retrieved_ids


@pytest.mark.integration
def test_dynamodb_delete_item(dynamodb_table):
    """Test deleting item from DynamoDB."""
    thread_id = f"test-thread-{uuid.uuid4()}"
    checkpoint_id = f"checkpoint-{uuid.uuid4()}"

    # Create item
    dynamodb_table.put_item(
        Item={
            'thread_id': thread_id,
            'checkpoint_id': checkpoint_id,
            'user_id': 'test-user-123'
        }
    )

    # Verify exists
    response = dynamodb_table.get_item(
        Key={
            'thread_id': thread_id,
            'checkpoint_id': checkpoint_id
        }
    )
    assert 'Item' in response

    # Delete item
    dynamodb_table.delete_item(
        Key={
            'thread_id': thread_id,
            'checkpoint_id': checkpoint_id
        }
    )

    # Verify deleted
    response = dynamodb_table.get_item(
        Key={
            'thread_id': thread_id,
            'checkpoint_id': checkpoint_id
        }
    )
    assert 'Item' not in response


@pytest.mark.integration
def test_dynamodb_batch_write(dynamodb_table, cleanup_dynamodb_items):
    """Test batch writing items."""
    thread_id = f"test-thread-{uuid.uuid4()}"
    checkpoint_ids = [f"checkpoint-{i}-{uuid.uuid4()}" for i in range(5)]

    # Register for cleanup
    for checkpoint_id in checkpoint_ids:
        cleanup_dynamodb_items(thread_id, checkpoint_id)

    # Batch write
    with dynamodb_table.batch_writer() as batch:
        for checkpoint_id in checkpoint_ids:
            batch.put_item(
                Item={
                    'thread_id': thread_id,
                    'checkpoint_id': checkpoint_id,
                    'user_id': 'test-user-123',
                    'created_at': int(time.time())
                }
            )

    # Verify all items were written
    from boto3.dynamodb.conditions import Key

    response = dynamodb_table.query(
        KeyConditionExpression=Key('thread_id').eq(thread_id)
    )

    assert len(response['Items']) == 5


@pytest.mark.integration
def test_dynamodb_gsi_query(dynamodb_table, cleanup_dynamodb_items):
    """Test querying using GSI."""
    user_id = f"test-user-{uuid.uuid4()}"
    thread_ids = []

    # Create multiple threads for same user
    for i in range(3):
        thread_id = f"{user_id}#session-{i}"
        checkpoint_id = f"checkpoint-{uuid.uuid4()}"

        thread_ids.append(thread_id)
        cleanup_dynamodb_items(thread_id, checkpoint_id)

        dynamodb_table.put_item(
            Item={
                'thread_id': thread_id,
                'checkpoint_id': checkpoint_id,
                'user_id': user_id,
                'last_activity': int(time.time()) + i,
                'created_at': int(time.time())
            }
        )

    # Query using GSI
    from boto3.dynamodb.conditions import Key

    response = dynamodb_table.query(
        IndexName='user_id-last_activity-index',
        KeyConditionExpression=Key('user_id').eq(user_id)
    )

    items = response['Items']
    assert len(items) >= 3, f"Expected at least 3 items, got {len(items)}"

    # Verify all thread_ids are present
    retrieved_thread_ids = {item['thread_id'] for item in items}
    assert set(thread_ids).issubset(retrieved_thread_ids)


@pytest.mark.integration
def test_dynamodb_conditional_put(dynamodb_table, cleanup_dynamodb_items):
    """Test conditional put (prevent overwrites)."""
    from botocore.exceptions import ClientError

    thread_id = f"test-thread-{uuid.uuid4()}"
    checkpoint_id = f"checkpoint-{uuid.uuid4()}"

    cleanup_dynamodb_items(thread_id, checkpoint_id)

    # Put initial item
    dynamodb_table.put_item(
        Item={
            'thread_id': thread_id,
            'checkpoint_id': checkpoint_id,
            'user_id': 'test-user-123',
            'version': 1
        }
    )

    # Try to put again with condition (should fail)
    from boto3.dynamodb.conditions import Attr

    with pytest.raises(ClientError) as exc_info:
        dynamodb_table.put_item(
            Item={
                'thread_id': thread_id,
                'checkpoint_id': checkpoint_id,
                'user_id': 'test-user-123',
                'version': 2
            },
            ConditionExpression=Attr('thread_id').not_exists()
        )

    # Verify error is conditional check failure
    error_code = exc_info.value.response['Error']['Code']
    assert error_code == 'ConditionalCheckFailedException'
