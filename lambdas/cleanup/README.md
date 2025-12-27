# Cleanup Lambda

## Purpose

This Lambda function monitors DynamoDB TTL-based cleanup of expired conversation sessions. It is triggered hourly by EventBridge cron to provide visibility into session lifecycle and TTL deletion behavior.

**Important**: This Lambda does NOT perform the actual deletion of expired sessions. DynamoDB's built-in TTL feature handles automatic deletion based on the `expires_at` attribute.

## Functionality

### Monitoring
- Scans DynamoDB checkpoint table for expired sessions
- Logs cleanup statistics (count, oldest/newest expiration times)
- Reports table metrics (item count, size, status)

### Reporting
The Lambda logs the following information:
- Total count of expired sessions found
- Age of oldest and newest expired items
- Sample of expired thread IDs (up to 10)
- Table-level metrics from DynamoDB

### DynamoDB Schema

**Table**: `collections-checkpoints-{env}`

**Keys**:
- Partition key: `thread_id` (STRING) - Format: `{user_id}#{session_id}`
- Sort key: `checkpoint_id` (STRING)

**Attributes**:
- `expires_at` (NUMBER) - Unix timestamp, TTL attribute
- `user_id` (STRING) - GSI partition key
- `last_activity` (NUMBER) - GSI sort key

**TTL**: DynamoDB automatically deletes items when `expires_at` < current time (within 48 hours)

## Trigger

**EventBridge Cron**: Runs hourly
```
Schedule: rate(1 hour)
```

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `CHECKPOINT_TABLE_NAME` | DynamoDB table name | `collections-checkpoints-dev` |
| `ENVIRONMENT` | Environment name | `dev`, `test`, `prod` |

## Permissions

The Lambda requires the following IAM permissions:

```json
{
  "DynamoDB": [
    "dynamodb:Scan",
    "dynamodb:DescribeTable"
  ],
  "CloudWatch Logs": [
    "logs:CreateLogGroup",
    "logs:CreateLogStream",
    "logs:PutLogEvents"
  ]
}
```

## Response Format

```json
{
  "statusCode": 200,
  "body": {
    "message": "Cleanup monitoring completed successfully",
    "summary": {
      "table_name": "collections-checkpoints-dev",
      "table_item_count": 42,
      "expired_count": 3,
      "scan_timestamp": "2025-12-27T18:00:00"
    },
    "expired_stats": {
      "expired_count": 3,
      "oldest_expired_ago_hours": 2.5,
      "newest_expired_ago_hours": 0.5,
      "sample_expired_items": [...]
    },
    "table_metrics": {
      "item_count": 42,
      "table_size_bytes": 8192,
      "table_status": "ACTIVE"
    }
  }
}
```

## Testing

Run unit tests with pytest:

```bash
# From project root
pytest lambdas/cleanup/tests/ -v

# Run specific test
pytest lambdas/cleanup/tests/test_handler.py::TestHandler::test_handler_success_no_expired -v
```

## Local Development

### Install Dependencies

```bash
cd lambdas/cleanup
pip install -r requirements.txt
pip install pytest pytest-mock
```

### Run Tests

```bash
cd /workspaces/collections-local
PYTHONPATH=/workspaces/collections-local pytest lambdas/cleanup/tests/ -v
```

## Deployment

The Lambda is deployed automatically via CDK in `infrastructure/stacks/compute_stack.py`.

### Manual Testing (AWS)

```bash
# Invoke the Lambda manually
aws lambda invoke \
  --function-name collections-cleanup-lambda-dev \
  --region us-east-1 \
  --payload '{}' \
  response.json

# View logs
aws logs tail /aws/lambda/collections-cleanup-lambda-dev --follow
```

## Monitoring

### CloudWatch Metrics
- Invocations
- Duration
- Errors
- Throttles

### CloudWatch Logs
The Lambda logs detailed information about:
- Scan results
- Expired session counts
- Table metrics
- Errors and exceptions

### Alarms (Optional)
Consider setting up CloudWatch Alarms for:
- High error rate (> 5%)
- Unusually high expired item count (> 100)
- Lambda duration exceeding timeout

## TTL Behavior

DynamoDB TTL has the following characteristics:
- **Deletion timing**: Within 48 hours of expiration
- **Background process**: Runs automatically, no manual intervention
- **Cost**: Free (no additional charges for TTL deletes)
- **Metrics**: TTL delete count available in CloudWatch metrics

This Lambda provides visibility into TTL behavior since the deletion is asynchronous and may not happen immediately after expiration.

## Future Enhancements

Potential improvements:
1. Add CloudWatch custom metrics for expired counts
2. Send SNS notifications for unusually high expired counts
3. Export cleanup statistics to S3 for long-term analysis
4. Add user-level aggregation for expired sessions
5. Create CloudWatch dashboard for cleanup trends
