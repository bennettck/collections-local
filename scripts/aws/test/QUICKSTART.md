# Quick Start Guide - AWS Infrastructure Testing

Get started testing your AWS infrastructure in 5 minutes.

## Prerequisites

- ✅ AWS infrastructure deployed via CDK
- ✅ `.aws-outputs-dev.json` file exists in project root
- ✅ AWS credentials configured (`aws configure`)

## Installation

```bash
# Navigate to test directory
cd scripts/aws/test

# Install dependencies
pip install -r requirements.txt
```

## Run Tests

### Option 1: Run All Tests (Recommended)

```bash
python test_infrastructure.py --env dev
```

**Expected Output:**
```
========================================================================
Starting Infrastructure Validation Tests
========================================================================

1. RDS Connection: Running...
✅ 1. RDS Connection: PASSED

2. pgvector Extension: Running...
✅ 2. pgvector Extension: PASSED

3. DynamoDB Table: Running...
✅ 3. DynamoDB Table: PASSED

...

========================================================================
Test Summary
========================================================================
Total Tests: 11
Passed: 11
Failed: 0

🎉 All infrastructure tests passed!

Test report: reports/infra-test-dev-20251227_103000.md
```

### Option 2: Run Specific Test

```bash
# Test RDS connection only
python test_infrastructure.py --env dev --test rds_connection

# Test DynamoDB only
python test_infrastructure.py --env dev --test dynamodb_table
```

### Option 3: Use pytest Directly

```bash
# Run all tests with pytest
pytest -v

# Run specific test file
pytest tests/test_rds_connection.py -v

# Run only RDS tests
pytest tests/test_rds_connection.py tests/test_pgvector.py -v
```

## Common Scenarios

### Scenario 1: Fresh Infrastructure Deployment

```bash
# 1. Deploy infrastructure
cd infrastructure
cdk deploy --context env=dev

# 2. Run tests
cd ../scripts/aws/test
python test_infrastructure.py --env dev

# 3. Check report
cat reports/infra-test-dev-*.md
```

### Scenario 2: Test Specific Component

```bash
# Test only database components
pytest tests/test_rds_connection.py tests/test_pgvector.py -v

# Test only Lambda components
pytest tests/test_lambda_*.py -v

# Test only storage components
pytest tests/test_s3.py tests/test_parameter_store.py -v
```

### Scenario 3: CI/CD Pipeline

```bash
# Run tests with JUnit XML output for CI
pytest --junitxml=test-results.xml

# Run with coverage
pytest --cov=. --cov-report=html
```

## Troubleshooting

### Issue: "CDK outputs not found"

**Error:**
```
FileNotFoundError: CDK outputs file not found: .aws-outputs-dev.json
```

**Solution:**
```bash
# Deploy infrastructure first
cd infrastructure
cdk deploy --context env=dev

# Verify outputs file exists
ls -la .aws-outputs-dev.json
```

### Issue: "AWS credentials not configured"

**Error:**
```
Unable to locate credentials
```

**Solution:**
```bash
# Configure AWS CLI
aws configure

# Or use environment variables
export AWS_ACCESS_KEY_ID=xxx
export AWS_SECRET_ACCESS_KEY=xxx
export AWS_REGION=us-east-1
```

### Issue: "Connection timeout"

**Error:**
```
psycopg2.OperationalError: timeout expired
```

**Solution:**
```bash
# Check security group allows your IP
aws rds describe-db-instances --db-instance-identifier collections-dev

# Test connection manually
psql -h <rds-endpoint> -U postgres -d collections
```

### Issue: Test failures

**Solution:**
```bash
# Run tests with verbose output
pytest -v -s

# Check specific test
pytest tests/test_rds_connection.py::test_rds_connection_basic -v -s

# View full error traceback
pytest --tb=long
```

## Understanding Test Results

### All Tests Pass ✅

```
========================================================================
Test Summary
========================================================================
Total Tests: 11
Passed: 11
Failed: 0

🎉 All infrastructure tests passed!
```

**Action:** Infrastructure is healthy, proceed with deployment.

### Some Tests Fail ❌

```
========================================================================
Test Summary
========================================================================
Total Tests: 11
Passed: 8
Failed: 3

⚠️  3 test(s) failed. See details above.
```

**Action:** Review failed tests and fix infrastructure issues before proceeding.

### Test Report

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
...
```

## Next Steps

1. ✅ **All tests pass**: Proceed with data migration
   ```bash
   # Migrate database
   python scripts/migrate/sqlite_to_postgres.py --env dev

   # Migrate vectors
   python scripts/migrate/chromadb_to_pgvector.py --env dev
   ```

2. ❌ **Some tests fail**: Fix infrastructure issues
   ```bash
   # Review failed tests
   cat reports/infra-test-dev-*.md

   # Fix issues in CDK code
   vim infrastructure/stacks/...

   # Redeploy
   cdk deploy --context env=dev

   # Re-run tests
   python test_infrastructure.py --env dev
   ```

3. 📊 **Generate detailed report**:
   ```bash
   # Generate custom report
   python test_infrastructure.py --env dev --report my-report.md

   # View report
   cat my-report.md
   ```

## Test Coverage

The framework tests **11 critical infrastructure components**:

1. **RDS Connection** - Database accessibility and SQL operations
2. **pgvector Extension** - Vector operations for embeddings
3. **DynamoDB Table** - Conversation checkpoint storage
4. **DynamoDB TTL** - Automatic cleanup configuration
5. **Parameter Store** - Secrets management
6. **Cognito User Pool** - User authentication
7. **S3 Bucket** - File storage and operations
8. **Lambda Invoke** - Function execution
9. **Lambda → RDS** - Database connectivity from Lambda
10. **Lambda → Secrets** - Parameter Store access from Lambda
11. **API Gateway** - HTTP API routing
12. **EventBridge** - Event-driven workflows

## Resources

- 📖 [Full README](README.md) - Detailed documentation
- 🏗️ [AWS Migration Plan](/AWS_MIGRATION_PLAN.md) - Infrastructure overview
- 📋 [Implementation Plan](/IMPLEMENTATION_PLAN.md) - Deployment guide

## Support

For issues or questions:

1. Check test output and error messages
2. Review test reports in `reports/` directory
3. Consult README.md for detailed documentation
4. Check AWS CloudWatch logs for service-specific issues
