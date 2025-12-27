"""
Test 4: DynamoDB TTL Configuration

Validates:
- TTL is enabled on the table
- TTL attribute is set to 'expires_at'
- TTL status is ENABLED or ENABLING
"""

import pytest


@pytest.mark.integration
def test_dynamodb_ttl_enabled(dynamodb_table, boto3_clients):
    """Verify TTL is enabled."""
    dynamodb_client = boto3_clients['dynamodb_client']

    response = dynamodb_client.describe_time_to_live(
        TableName=dynamodb_table.table_name
    )

    ttl_description = response['TimeToLiveDescription']
    ttl_status = ttl_description['TimeToLiveStatus']

    assert ttl_status in ['ENABLED', 'ENABLING'], \
        f"TTL not enabled: {ttl_status}"


@pytest.mark.integration
def test_dynamodb_ttl_attribute(dynamodb_table, boto3_clients):
    """Verify TTL attribute is 'expires_at'."""
    dynamodb_client = boto3_clients['dynamodb_client']

    response = dynamodb_client.describe_time_to_live(
        TableName=dynamodb_table.table_name
    )

    ttl_description = response['TimeToLiveDescription']
    ttl_status = ttl_description['TimeToLiveStatus']

    if ttl_status == 'ENABLED':
        ttl_attribute = ttl_description['AttributeName']
        assert ttl_attribute == 'expires_at', \
            f"Wrong TTL attribute: {ttl_attribute}"
    else:
        # TTL is still enabling, skip attribute check
        pytest.skip("TTL still enabling, cannot verify attribute")


@pytest.mark.integration
def test_dynamodb_ttl_functionality(dynamodb_table, cleanup_dynamodb_items):
    """
    Test TTL functionality (creates item with short TTL).

    Note: Actual TTL deletion happens within 48 hours, so this test
    only validates that items CAN have expires_at attribute.
    """
    import time
    import uuid

    thread_id = f"test-thread-{uuid.uuid4()}"
    checkpoint_id = f"checkpoint-{uuid.uuid4()}"

    cleanup_dynamodb_items(thread_id, checkpoint_id)

    # Create item with expires_at in the past (already expired)
    # DynamoDB TTL will delete this eventually (within 48 hours)
    now = int(time.time())
    expires_at = now - 3600  # Expired 1 hour ago

    dynamodb_table.put_item(
        Item={
            'thread_id': thread_id,
            'checkpoint_id': checkpoint_id,
            'user_id': 'test-user-123',
            'created_at': now,
            'expires_at': expires_at  # TTL attribute
        }
    )

    # Verify item was created (won't be deleted immediately)
    response = dynamodb_table.get_item(
        Key={
            'thread_id': thread_id,
            'checkpoint_id': checkpoint_id
        }
    )

    assert 'Item' in response
    assert response['Item']['expires_at'] == expires_at

    # Note: Item will be deleted by DynamoDB TTL process within 48 hours
    # We cannot test actual deletion in this test
