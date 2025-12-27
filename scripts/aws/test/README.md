# AWS Infrastructure Testing Framework

Comprehensive automated testing framework using boto3 and pytest to validate AWS infrastructure deployment.

## Overview

This testing framework validates that all AWS infrastructure components are deployed correctly and functional. It runs **AFTER** the CDK stacks are deployed to the dev environment.

### Key Features

- **Library-First Development**: Uses boto3 for all AWS interactions, pytest for testing
- **11 Comprehensive Tests**: Validates all infrastructure components
- **Automatic Cleanup**: Fixtures handle resource cleanup after tests
- **Detailed Reporting**: Generates markdown reports with test results
- **Environment Support**: Configurable for dev, test, and prod environments

## Architecture

```
scripts/aws/test/
├── __init__.py
├── test_infrastructure.py         # Main test orchestrator
├── conftest.py                     # Pytest fixtures
├── requirements.txt                # Dependencies
├── pytest.ini                      # Pytest configuration
├── tests/
│   ├── __init__.py
│   ├── test_rds_connection.py     # Test 1: RDS connectivity + basic SQL
│   ├── test_pgvector.py           # Test 2: pgvector extension
│   ├── test_dynamodb.py           # Test 3: DynamoDB table schema
│   ├── test_dynamodb_ttl.py       # Test 4: DynamoDB TTL
│   ├── test_parameter_store.py    # Test 5: Parameter Store CRUD
│   ├── test_cognito.py            # Test 6: Cognito user pool + JWT
│   ├── test_s3.py                 # Test 7: S3 bucket operations
│   ├── test_lambda_invoke.py      # Test 8: Lambda invocation
│   ├── test_lambda_rds.py         # Test 9: Lambda → RDS connectivity
│   ├── test_lambda_secrets.py     # Test 10: Lambda → Parameter Store
│   ├── test_api_gateway.py        # Test 11: API Gateway routing
│   └── test_eventbridge.py        # Test 12: EventBridge rules
└── README.md                       # This file
```

## The 11 Validation Tests

### 1. RDS Connection (`test_rds_connection.py`)
- ✅ RDS instance accessible
- ✅ PostgreSQL version verification
- ✅ SSL connection enforcement
- ✅ Basic SQL operations (CREATE, INSERT, SELECT, DELETE)
- ✅ JSONB support
- ✅ Transaction support

### 2. pgvector Extension (`test_pgvector.py`)
- ✅ Extension installed
- ✅ Vector column creation
- ✅ Cosine distance operator (`<->`)
- ✅ L2 distance operator (`<+>`)
- ✅ Inner product operator (`<#>`)
- ✅ IVFFlat index creation
- ✅ Large vectors (1024 dimensions)

### 3. DynamoDB Table (`test_dynamodb.py`)
- ✅ Table exists and is ACTIVE
- ✅ Partition key (thread_id) configured
- ✅ Sort key (checkpoint_id) configured
- ✅ GSI (user_id-last_activity-index) exists
- ✅ CRUD operations work
- ✅ Batch write operations
- ✅ Conditional puts

### 4. DynamoDB TTL (`test_dynamodb_ttl.py`)
- ✅ TTL enabled
- ✅ TTL attribute is 'expires_at'

### 5. Parameter Store (`test_parameter_store.py`)
- ✅ Create parameters
- ✅ Read parameters (with decryption)
- ✅ Update parameters
- ✅ Delete parameters
- ✅ SecureString encryption
- ✅ Batch operations

### 6. Cognito User Pool (`test_cognito.py`)
- ✅ User pool exists
- ✅ Create test users
- ✅ Get user attributes (sub claim)
- ✅ Update user attributes
- ✅ Disable/enable users
- ✅ Delete users

### 7. S3 Bucket (`test_s3.py`)
- ✅ Bucket exists and accessible
- ✅ Upload files
- ✅ Download files
- ✅ List objects
- ✅ Delete objects
- ✅ Object metadata
- ✅ Pre-signed URLs
- ✅ Multipart upload

### 8. Lambda Invocation (`test_lambda_invoke.py`)
- ✅ Lambda function exists
- ✅ Basic invocation works
- ✅ CloudWatch logs created
- ✅ Function configuration valid

### 9. Lambda → RDS (`test_lambda_rds.py`)
- ✅ Security groups allow Lambda → RDS
- ✅ RDS endpoint accessible
- ✅ Network configuration verified

### 10. Lambda → Secrets (`test_lambda_secrets.py`)
- ✅ Lambda has IAM role
- ✅ IAM policies attached
- ✅ Parameter Store access permissions

### 11. API Gateway (`test_api_gateway.py`)
- ✅ API Gateway exists
- ✅ Health endpoint accessible
- ✅ Returns valid JSON responses
- ✅ CORS headers (if configured)
- ✅ 404 handling

### 12. EventBridge (`test_eventbridge.py`)
- ✅ EventBridge rules exist
- ✅ Rules have Lambda targets
- ✅ Rules are enabled
- ✅ Cleanup schedule configured

## Installation

### Prerequisites

- Python 3.12+
- AWS CLI configured with credentials
- CDK infrastructure deployed (`.aws-outputs-{env}.json` file must exist)

### Install Dependencies

```bash
cd scripts/aws/test
pip install -r requirements.txt
```

## Usage

### Run All Tests

```bash
# Run all infrastructure tests for dev environment
python test_infrastructure.py --env dev
```

### Run Specific Test

```bash
# Run only RDS connection test
python test_infrastructure.py --env dev --test rds_connection

# Run only DynamoDB tests
python test_infrastructure.py --env dev --test dynamodb
```

### Generate Test Report

```bash
# Generate report in custom location
python test_infrastructure.py --env dev --report reports/my-test-report.md
```

### Using pytest Directly

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_rds_connection.py

# Run with verbose output
pytest -v

# Run only integration tests
pytest -m integration

# Run with coverage
pytest --cov=. --cov-report=html
```

## Configuration

### Environment Variables

```bash
# Set environment name (dev, test, prod)
export CDK_ENV=dev

# Set AWS region
export AWS_REGION=us-east-1
```

### Required Files

The framework expects a CDK outputs file in the project root:

```
.aws-outputs-{env}.json
```

This file should contain:

```json
{
  "Region": "us-east-1",
  "RdsEndpoint": "collections-dev.xxxxx.rds.amazonaws.com",
  "DatabaseName": "collections",
  "RdsUsername": "postgres",
  "RdsPassword": "...",
  "CheckpointTableName": "collections-chat-checkpoints-dev",
  "BucketName": "collections-images-dev-xxxxx",
  "CognitoUserPoolId": "us-east-1_XXXXXXXXX",
  "CognitoClientId": "xxxxxxxxxx",
  "ApiLambdaName": "collections-api-lambda-dev",
  "ApiUrl": "https://xxxxx.execute-api.us-east-1.amazonaws.com"
}
```

## Test Fixtures

### Session-Scoped Fixtures

- `aws_region`: AWS region configuration
- `env_name`: Environment name (dev/test/prod)
- `stack_outputs`: CDK stack outputs dictionary
- `boto3_clients`: All boto3 client instances

### Function-Scoped Fixtures

- `rds_connection`: PostgreSQL connection (auto-cleanup)
- `dynamodb_table`: DynamoDB table resource
- `s3_bucket`: S3 bucket name
- `cognito_user_pool`: Cognito User Pool ID
- `test_user`: Test Cognito user (auto-cleanup)
- `cleanup_s3_objects`: S3 object cleanup handler
- `cleanup_ssm_parameters`: Parameter Store cleanup handler
- `cleanup_dynamodb_items`: DynamoDB item cleanup handler

## Test Report Example

After running tests, a markdown report is generated:

```markdown
# AWS Infrastructure Test Report

**Generated**: 2025-12-27 10:30:00 UTC
**Environment**: dev
**Region**: us-east-1

## Summary

- **Total Tests**: 11
- **Passed**: 11
- **Failed**: 0
- **Success Rate**: 100.0%

## Test Results

| # | Test | Status | Details |
|---|------|--------|---------|
| 1 | 1. RDS Connection | ✅ PASS | |
| 2 | 2. pgvector Extension | ✅ PASS | |
| 3 | 3. DynamoDB Table | ✅ PASS | |
| 4 | 4. DynamoDB TTL | ✅ PASS | |
| 5 | 5. Parameter Store | ✅ PASS | |
| 6 | 6. Cognito User Pool | ✅ PASS | |
| 7 | 7. S3 Bucket | ✅ PASS | |
| 8 | 8. Lambda Invoke | ✅ PASS | |
| 9 | 9. Lambda → RDS | ✅ PASS | |
| 10 | 10. API Gateway | ✅ PASS | |
| 11 | 11. EventBridge | ✅ PASS | |
```

## Troubleshooting

### "CDK outputs not found"

**Solution**: Run `cdk deploy` first to generate the outputs file.

```bash
cd infrastructure
cdk deploy --context env=dev
```

### "AWS credentials not configured"

**Solution**: Configure AWS CLI:

```bash
aws configure
```

### "Database password not found"

**Solution**: Password should be in outputs file or Parameter Store:

```bash
# Check Parameter Store
aws ssm get-parameter --name /collections/database-password --with-decryption
```

### Test timeouts

**Solution**: Increase timeout in pytest.ini or use `-s` flag for verbose output:

```bash
pytest -s tests/test_rds_connection.py
```

## Best Practices

### 1. Run Tests After Every Deployment

```bash
make infra-deploy ENV=dev
make test-infra ENV=dev
```

### 2. Use Cleanup Fixtures

Always register resources for cleanup:

```python
def test_my_feature(cleanup_s3_objects):
    key = 'test/my-file.txt'
    cleanup_s3_objects(key)  # Will be deleted after test

    # Upload file
    s3.put_object(Bucket=bucket, Key=key, Body=b'data')
```

### 3. Skip Tests When Resources Not Available

```python
def test_feature(stack_outputs):
    resource = stack_outputs.get('ResourceName')

    if not resource:
        pytest.skip("Resource not in outputs")

    # Test code
```

### 4. Test Both Success and Failure Cases

```python
def test_feature_success():
    # Test successful operation
    pass

def test_feature_failure():
    with pytest.raises(SomeException):
        # Test error handling
        pass
```

## Integration with CI/CD

### GitHub Actions Example

```yaml
name: Infrastructure Tests

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v2

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v1
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1

      - name: Install dependencies
        run: |
          pip install -r scripts/aws/test/requirements.txt

      - name: Run infrastructure tests
        run: |
          python scripts/aws/test/test_infrastructure.py --env dev
```

## Contributing

When adding new tests:

1. Create test file in `tests/` directory
2. Use pytest fixtures from `conftest.py`
3. Add integration marker: `@pytest.mark.integration`
4. Register cleanup for created resources
5. Update this README with test description

## License

This testing framework is part of the collections-local project.
