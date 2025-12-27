"""
Cleanup Lambda function for monitoring DynamoDB TTL-based session cleanup.

This Lambda is triggered hourly by EventBridge cron to monitor expired sessions.
Actual deletion is handled automatically by DynamoDB's TTL feature on the
'expires_at' attribute.

Key responsibilities:
- Scan DynamoDB for expired sessions
- Log cleanup statistics (count of expired items)
- Report on session lifecycle metrics

DynamoDB Schema:
- Table: collections-checkpoints-{env}
- Partition key: thread_id (STRING) - Format: {user_id}#{session_id}
- Sort key: checkpoint_id (STRING)
- TTL attribute: expires_at (NUMBER) - Unix timestamp
- GSI: user_id-last_activity-index
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List

import boto3
from boto3.dynamodb.conditions import Attr

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize DynamoDB client
dynamodb = boto3.resource('dynamodb')


def get_table_name() -> str:
    """
    Get DynamoDB table name from environment variable.

    Returns:
        str: Table name

    Raises:
        ValueError: If CHECKPOINT_TABLE_NAME is not set
    """
    table_name = os.environ.get('CHECKPOINT_TABLE_NAME')
    if not table_name:
        raise ValueError("CHECKPOINT_TABLE_NAME environment variable not set")
    return table_name


def scan_expired_sessions(table_name: str) -> Dict[str, Any]:
    """
    Scan DynamoDB table for expired sessions.

    Note: DynamoDB TTL handles actual deletion automatically. This scan is
    for monitoring and reporting purposes only.

    Args:
        table_name: DynamoDB table name

    Returns:
        Dict with statistics:
        - expired_count: Number of expired items found
        - expired_items: List of expired thread IDs
        - scan_timestamp: Current timestamp
        - oldest_expired: Oldest expiration timestamp found
        - newest_expired: Newest expiration timestamp found
    """
    table = dynamodb.Table(table_name)
    current_time = int(time.time())

    expired_items = []
    expired_timestamps = []

    try:
        # Scan for items with expires_at < current_time
        # Note: TTL may take up to 48 hours to delete items, so we may find
        # expired items that haven't been deleted yet
        response = table.scan(
            FilterExpression=Attr('expires_at').lt(current_time) & Attr('expires_at').exists()
        )

        # Process items
        for item in response.get('Items', []):
            thread_id = item.get('thread_id', 'unknown')
            expires_at = item.get('expires_at', 0)
            expired_items.append({
                'thread_id': thread_id,
                'checkpoint_id': item.get('checkpoint_id', 'unknown'),
                'expires_at': expires_at,
                'expired_ago_seconds': current_time - expires_at,
            })
            expired_timestamps.append(expires_at)

        # Handle pagination
        while 'LastEvaluatedKey' in response:
            response = table.scan(
                FilterExpression=Attr('expires_at').lt(current_time) & Attr('expires_at').exists(),
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            for item in response.get('Items', []):
                thread_id = item.get('thread_id', 'unknown')
                expires_at = item.get('expires_at', 0)
                expired_items.append({
                    'thread_id': thread_id,
                    'checkpoint_id': item.get('checkpoint_id', 'unknown'),
                    'expires_at': expires_at,
                    'expired_ago_seconds': current_time - expires_at,
                })
                expired_timestamps.append(expires_at)

        # Calculate statistics
        stats = {
            'expired_count': len(expired_items),
            'scan_timestamp': current_time,
            'scan_time_iso': datetime.fromtimestamp(current_time).isoformat(),
        }

        if expired_timestamps:
            oldest_expired = min(expired_timestamps)
            newest_expired = max(expired_timestamps)
            stats.update({
                'oldest_expired': oldest_expired,
                'oldest_expired_iso': datetime.fromtimestamp(oldest_expired).isoformat(),
                'oldest_expired_ago_hours': (current_time - oldest_expired) / 3600,
                'newest_expired': newest_expired,
                'newest_expired_iso': datetime.fromtimestamp(newest_expired).isoformat(),
                'newest_expired_ago_hours': (current_time - newest_expired) / 3600,
            })

        # Add sample of expired items (limit to 10 for logging)
        stats['sample_expired_items'] = expired_items[:10]

        return stats

    except Exception as e:
        logger.error(f"Error scanning DynamoDB table: {str(e)}")
        raise


def get_table_metrics(table_name: str) -> Dict[str, Any]:
    """
    Get basic table metrics using DynamoDB describe_table.

    Args:
        table_name: DynamoDB table name

    Returns:
        Dict with table metrics:
        - item_count: Approximate item count
        - table_size_bytes: Table size in bytes
        - table_status: Table status
    """
    client = boto3.client('dynamodb')

    try:
        response = client.describe_table(TableName=table_name)
        table_info = response['Table']

        return {
            'item_count': table_info.get('ItemCount', 0),
            'table_size_bytes': table_info.get('TableSizeBytes', 0),
            'table_status': table_info.get('TableStatus', 'unknown'),
        }
    except Exception as e:
        logger.error(f"Error getting table metrics: {str(e)}")
        return {
            'item_count': -1,
            'table_size_bytes': -1,
            'table_status': 'error',
            'error': str(e),
        }


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for cleanup monitoring.

    This function is triggered hourly by EventBridge cron. It scans the
    DynamoDB checkpoint table for expired sessions and logs statistics.

    Actual deletion is handled by DynamoDB TTL automatically.

    Args:
        event: EventBridge cron event
        context: Lambda context

    Returns:
        Dict with status code and cleanup statistics
    """
    logger.info(f"Starting cleanup monitoring at {datetime.now().isoformat()}")
    logger.info(f"Event: {json.dumps(event)}")

    try:
        # Get table name
        table_name = get_table_name()
        logger.info(f"Monitoring table: {table_name}")

        # Get table metrics
        table_metrics = get_table_metrics(table_name)
        logger.info(f"Table metrics: {json.dumps(table_metrics, indent=2)}")

        # Scan for expired sessions
        expired_stats = scan_expired_sessions(table_name)
        logger.info(f"Expired sessions statistics: {json.dumps(expired_stats, indent=2)}")

        # Log summary
        summary = {
            'table_name': table_name,
            'table_item_count': table_metrics.get('item_count', 0),
            'expired_count': expired_stats['expired_count'],
            'scan_timestamp': expired_stats['scan_time_iso'],
        }

        if expired_stats['expired_count'] > 0:
            logger.info(
                f"Found {expired_stats['expired_count']} expired sessions. "
                f"Oldest expired {expired_stats.get('oldest_expired_ago_hours', 0):.2f} hours ago. "
                f"Newest expired {expired_stats.get('newest_expired_ago_hours', 0):.2f} hours ago."
            )
            logger.info(
                "Note: DynamoDB TTL handles automatic deletion. "
                "These items may be deleted within 48 hours of expiration."
            )
        else:
            logger.info("No expired sessions found.")

        # Return success response
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Cleanup monitoring completed successfully',
                'summary': summary,
                'expired_stats': expired_stats,
                'table_metrics': table_metrics,
            }, indent=2)
        }

    except Exception as e:
        logger.error(f"Cleanup monitoring failed: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'message': 'Cleanup monitoring failed',
                'error': str(e),
            })
        }
