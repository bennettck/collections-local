"""
Unit tests for cleanup Lambda handler.

Tests the cleanup monitoring Lambda with mocked DynamoDB responses.
"""

import json
import os
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

import pytest
import boto3

# Set environment variable before importing handler
os.environ['CHECKPOINT_TABLE_NAME'] = 'test-checkpoints-table'

from lambdas.cleanup import handler as cleanup_handler


@pytest.fixture
def mock_env():
    """Mock environment variables."""
    with patch.dict(os.environ, {
        'CHECKPOINT_TABLE_NAME': 'test-checkpoints-table',
        'ENVIRONMENT': 'dev',
    }):
        yield


@pytest.fixture
def mock_dynamodb_table():
    """Mock DynamoDB table."""
    with patch('lambdas.cleanup.handler.dynamodb') as mock_dynamodb:
        mock_table = Mock()
        mock_dynamodb.Table.return_value = mock_table
        yield mock_table


@pytest.fixture
def mock_dynamodb_client():
    """Mock DynamoDB client for describe_table."""
    with patch('lambdas.cleanup.handler.boto3.client') as mock_client:
        mock_ddb_client = Mock()
        mock_client.return_value = mock_ddb_client
        yield mock_ddb_client


@pytest.fixture
def sample_expired_items():
    """Sample expired DynamoDB items."""
    current_time = int(time.time())
    return [
        {
            'thread_id': 'user123#session456',
            'checkpoint_id': 'checkpoint1',
            'expires_at': current_time - 3600,  # Expired 1 hour ago
            'user_id': 'user123',
            'last_activity': current_time - 7200,
        },
        {
            'thread_id': 'user123#session789',
            'checkpoint_id': 'checkpoint2',
            'expires_at': current_time - 7200,  # Expired 2 hours ago
            'user_id': 'user123',
            'last_activity': current_time - 10800,
        },
        {
            'thread_id': 'user456#session111',
            'checkpoint_id': 'checkpoint3',
            'expires_at': current_time - 1800,  # Expired 30 minutes ago
            'user_id': 'user456',
            'last_activity': current_time - 5400,
        },
    ]


@pytest.fixture
def sample_valid_items():
    """Sample valid (non-expired) DynamoDB items."""
    current_time = int(time.time())
    return [
        {
            'thread_id': 'user789#session222',
            'checkpoint_id': 'checkpoint4',
            'expires_at': current_time + 3600,  # Expires in 1 hour
            'user_id': 'user789',
            'last_activity': current_time - 600,
        },
    ]


class TestGetTableName:
    """Tests for get_table_name function."""

    def test_get_table_name_success(self, mock_env):
        """Test getting table name from environment."""
        table_name = cleanup_handler.get_table_name()
        assert table_name == 'test-checkpoints-table'

    def test_get_table_name_missing(self):
        """Test error when CHECKPOINT_TABLE_NAME is not set."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="CHECKPOINT_TABLE_NAME environment variable not set"):
                cleanup_handler.get_table_name()


class TestScanExpiredSessions:
    """Tests for scan_expired_sessions function."""

    def test_scan_no_expired_sessions(self, mock_env, mock_dynamodb_table):
        """Test scanning when no expired sessions exist."""
        mock_dynamodb_table.scan.return_value = {
            'Items': [],
            'Count': 0,
        }

        stats = cleanup_handler.scan_expired_sessions('test-checkpoints-table')

        assert stats['expired_count'] == 0
        assert 'scan_timestamp' in stats
        assert 'scan_time_iso' in stats
        assert stats['sample_expired_items'] == []
        mock_dynamodb_table.scan.assert_called_once()

    def test_scan_with_expired_sessions(self, mock_env, mock_dynamodb_table, sample_expired_items):
        """Test scanning with expired sessions."""
        mock_dynamodb_table.scan.return_value = {
            'Items': sample_expired_items,
            'Count': len(sample_expired_items),
        }

        stats = cleanup_handler.scan_expired_sessions('test-checkpoints-table')

        assert stats['expired_count'] == 3
        assert 'oldest_expired' in stats
        assert 'newest_expired' in stats
        assert 'oldest_expired_ago_hours' in stats
        assert 'newest_expired_ago_hours' in stats
        assert len(stats['sample_expired_items']) == 3
        assert stats['sample_expired_items'][0]['thread_id'] == 'user123#session456'

    def test_scan_with_pagination(self, mock_env, mock_dynamodb_table, sample_expired_items):
        """Test scanning with pagination."""
        # First page
        mock_dynamodb_table.scan.side_effect = [
            {
                'Items': sample_expired_items[:2],
                'Count': 2,
                'LastEvaluatedKey': {'thread_id': 'user123#session789', 'checkpoint_id': 'checkpoint2'},
            },
            # Second page
            {
                'Items': [sample_expired_items[2]],
                'Count': 1,
            },
        ]

        stats = cleanup_handler.scan_expired_sessions('test-checkpoints-table')

        assert stats['expired_count'] == 3
        assert mock_dynamodb_table.scan.call_count == 2

    def test_scan_oldest_newest_calculation(self, mock_env, mock_dynamodb_table):
        """Test calculation of oldest and newest expired timestamps."""
        current_time = int(time.time())
        items = [
            {
                'thread_id': 'user1#session1',
                'checkpoint_id': 'cp1',
                'expires_at': current_time - 7200,  # 2 hours ago
            },
            {
                'thread_id': 'user2#session2',
                'checkpoint_id': 'cp2',
                'expires_at': current_time - 3600,  # 1 hour ago
            },
        ]

        mock_dynamodb_table.scan.return_value = {
            'Items': items,
            'Count': 2,
        }

        stats = cleanup_handler.scan_expired_sessions('test-checkpoints-table')

        # Oldest should be ~2 hours ago, newest ~1 hour ago
        assert 1.9 < stats['oldest_expired_ago_hours'] < 2.1
        assert 0.9 < stats['newest_expired_ago_hours'] < 1.1

    def test_scan_error_handling(self, mock_env, mock_dynamodb_table):
        """Test error handling during scan."""
        mock_dynamodb_table.scan.side_effect = Exception("DynamoDB error")

        with pytest.raises(Exception, match="DynamoDB error"):
            cleanup_handler.scan_expired_sessions('test-checkpoints-table')

    def test_scan_sample_limit(self, mock_env, mock_dynamodb_table):
        """Test that sample items are limited to 10."""
        current_time = int(time.time())
        # Create 15 expired items
        items = [
            {
                'thread_id': f'user{i}#session{i}',
                'checkpoint_id': f'cp{i}',
                'expires_at': current_time - 3600,
            }
            for i in range(15)
        ]

        mock_dynamodb_table.scan.return_value = {
            'Items': items,
            'Count': 15,
        }

        stats = cleanup_handler.scan_expired_sessions('test-checkpoints-table')

        assert stats['expired_count'] == 15
        # Sample should be limited to 10
        assert len(stats['sample_expired_items']) == 10


class TestGetTableMetrics:
    """Tests for get_table_metrics function."""

    def test_get_table_metrics_success(self, mock_env, mock_dynamodb_client):
        """Test successful retrieval of table metrics."""
        mock_dynamodb_client.describe_table.return_value = {
            'Table': {
                'ItemCount': 42,
                'TableSizeBytes': 1024,
                'TableStatus': 'ACTIVE',
            }
        }

        metrics = cleanup_handler.get_table_metrics('test-checkpoints-table')

        assert metrics['item_count'] == 42
        assert metrics['table_size_bytes'] == 1024
        assert metrics['table_status'] == 'ACTIVE'
        mock_dynamodb_client.describe_table.assert_called_once_with(
            TableName='test-checkpoints-table'
        )

    def test_get_table_metrics_error(self, mock_env, mock_dynamodb_client):
        """Test error handling when describe_table fails."""
        mock_dynamodb_client.describe_table.side_effect = Exception("Table not found")

        metrics = cleanup_handler.get_table_metrics('test-checkpoints-table')

        assert metrics['item_count'] == -1
        assert metrics['table_size_bytes'] == -1
        assert metrics['table_status'] == 'error'
        assert 'error' in metrics


class TestHandler:
    """Tests for Lambda handler function."""

    def test_handler_success_no_expired(
        self, mock_env, mock_dynamodb_table, mock_dynamodb_client
    ):
        """Test handler with no expired sessions."""
        # Mock table metrics
        mock_dynamodb_client.describe_table.return_value = {
            'Table': {
                'ItemCount': 10,
                'TableSizeBytes': 2048,
                'TableStatus': 'ACTIVE',
            }
        }

        # Mock scan results
        mock_dynamodb_table.scan.return_value = {
            'Items': [],
            'Count': 0,
        }

        # Create event and context
        event = {
            'source': 'aws.events',
            'detail-type': 'Scheduled Event',
        }
        context = Mock()
        context.function_name = 'cleanup-lambda'

        # Call handler
        response = cleanup_handler.handler(event, context)

        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['message'] == 'Cleanup monitoring completed successfully'
        assert body['summary']['expired_count'] == 0
        assert body['summary']['table_item_count'] == 10

    def test_handler_success_with_expired(
        self, mock_env, mock_dynamodb_table, mock_dynamodb_client, sample_expired_items
    ):
        """Test handler with expired sessions."""
        # Mock table metrics
        mock_dynamodb_client.describe_table.return_value = {
            'Table': {
                'ItemCount': 20,
                'TableSizeBytes': 4096,
                'TableStatus': 'ACTIVE',
            }
        }

        # Mock scan results
        mock_dynamodb_table.scan.return_value = {
            'Items': sample_expired_items,
            'Count': len(sample_expired_items),
        }

        # Create event and context
        event = {
            'source': 'aws.events',
            'detail-type': 'Scheduled Event',
        }
        context = Mock()

        # Call handler
        response = cleanup_handler.handler(event, context)

        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['summary']['expired_count'] == 3
        assert 'oldest_expired_ago_hours' in body['expired_stats']

    def test_handler_error_missing_env(self, mock_dynamodb_table, mock_dynamodb_client):
        """Test handler error when environment variable is missing."""
        with patch.dict(os.environ, {}, clear=True):
            event = {}
            context = Mock()

            response = cleanup_handler.handler(event, context)

            assert response['statusCode'] == 500
            body = json.loads(response['body'])
            assert body['message'] == 'Cleanup monitoring failed'
            assert 'error' in body

    def test_handler_error_dynamodb_failure(
        self, mock_env, mock_dynamodb_table, mock_dynamodb_client
    ):
        """Test handler error when DynamoDB operations fail."""
        # Mock table metrics to succeed
        mock_dynamodb_client.describe_table.return_value = {
            'Table': {
                'ItemCount': 10,
                'TableSizeBytes': 2048,
                'TableStatus': 'ACTIVE',
            }
        }

        # Mock scan to fail
        mock_dynamodb_table.scan.side_effect = Exception("DynamoDB connection error")

        event = {}
        context = Mock()

        response = cleanup_handler.handler(event, context)

        assert response['statusCode'] == 500
        body = json.loads(response['body'])
        assert 'error' in body

    def test_handler_logging(
        self, mock_env, mock_dynamodb_table, mock_dynamodb_client, caplog
    ):
        """Test that handler logs appropriate messages."""
        import logging
        caplog.set_level(logging.INFO)

        # Mock successful responses
        mock_dynamodb_client.describe_table.return_value = {
            'Table': {
                'ItemCount': 5,
                'TableSizeBytes': 1024,
                'TableStatus': 'ACTIVE',
            }
        }
        mock_dynamodb_table.scan.return_value = {
            'Items': [],
            'Count': 0,
        }

        event = {}
        context = Mock()

        cleanup_handler.handler(event, context)

        # Check that key log messages are present
        assert 'Starting cleanup monitoring' in caplog.text
        assert 'Monitoring table: test-checkpoints-table' in caplog.text
        assert 'No expired sessions found' in caplog.text


class TestIntegration:
    """Integration-style tests for the full cleanup flow."""

    def test_full_cleanup_flow_with_mixed_items(
        self, mock_env, mock_dynamodb_table, mock_dynamodb_client,
        sample_expired_items, sample_valid_items
    ):
        """Test full cleanup flow with both expired and valid items."""
        # Mock table metrics
        mock_dynamodb_client.describe_table.return_value = {
            'Table': {
                'ItemCount': 4,
                'TableSizeBytes': 8192,
                'TableStatus': 'ACTIVE',
            }
        }

        # Mock scan to return only expired items (filter works)
        mock_dynamodb_table.scan.return_value = {
            'Items': sample_expired_items,
            'Count': len(sample_expired_items),
        }

        event = {
            'source': 'aws.events',
            'detail-type': 'Scheduled Event',
            'time': datetime.now().isoformat(),
        }
        context = Mock()
        context.function_name = 'cleanup-lambda-dev'

        response = cleanup_handler.handler(event, context)

        assert response['statusCode'] == 200
        body = json.loads(response['body'])

        # Verify summary
        assert body['summary']['expired_count'] == 3
        assert body['summary']['table_item_count'] == 4

        # Verify expired stats
        assert body['expired_stats']['expired_count'] == 3
        assert 'oldest_expired_ago_hours' in body['expired_stats']
        assert 'newest_expired_ago_hours' in body['expired_stats']

        # Verify table metrics
        assert body['table_metrics']['item_count'] == 4
        assert body['table_metrics']['table_status'] == 'ACTIVE'
