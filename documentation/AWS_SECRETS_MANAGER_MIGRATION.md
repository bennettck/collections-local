# AWS Secrets Manager Migration

## Overview

This document describes the migration from insecure database credential handling to the architect-recommended AWS Secrets Manager pattern.

## Problem Statement

The `/items` endpoint was returning a 500 error in AWS Lambda with the following root cause:

```python
File "/var/task/database.py", line 127, in get_db
    conn = sqlite3.connect(active_path)
```

**Root Cause**: The Lambda function was attempting to connect to a SQLite database file (`./data/collections.db`) that doesn't exist in the Lambda filesystem, because:

1. No `DATABASE_URL` was provided
2. Database credentials were passed as individual environment variables (`DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`) without username/password
3. The code fell back to SQLite for local development

## Architect-Recommended Solution

Implement AWS Secrets Manager for secure credential management with automatic rotation support.

### Why Secrets Manager vs Parameter Store?

| Feature | Secrets Manager | Parameter Store |
|---------|----------------|-----------------|
| **Purpose** | Purpose-built for credentials | General configuration |
| **Rotation** | Automatic (especially for RDS) | Manual only |
| **RDS Integration** | Built-in | None |
| **Security** | Encrypted at rest + IAM + audit | Encrypted at rest + IAM |
| **Cost** | $0.40/month/secret + $0.05/10K API | Free (Standard tier) |
| **Best Practice** | ✅ Recommended for DB credentials | ⚠️ Not recommended for secrets |

### Implementation Details

## Changes Made

### 1. Infrastructure (CDK) - `infrastructure/stacks/compute_stack.py`

**Before**:
```python
self.common_env = {
    "DATABASE_HOST": database.db_instance_endpoint_address,
    "DATABASE_PORT": str(database.db_instance_endpoint_port),
    "DATABASE_NAME": "collections",
}
```

**After**:
```python
self.common_env = {
    # Database credentials via Secrets Manager (secure approach)
    "DB_SECRET_ARN": db_credentials.secret_arn,
    # Legacy environment variables (for backwards compatibility)
    "DATABASE_HOST": database.db_instance_endpoint_address,
    "DATABASE_PORT": str(database.db_instance_endpoint_port),
    "DATABASE_NAME": "collections",
}
```

**Permissions** (already configured):
```python
self.db_credentials.grant_read(self.api_lambda)  # Line 201
```

### 2. Database Credentials Helper - `utils/aws_secrets.py` (NEW)

Created a secure credential fetching module with:

- **LRU caching**: Avoid repeated API calls within Lambda execution
- **Automatic cache clearing**: Between Lambda cold starts
- **Graceful fallbacks**: For local development
- **Comprehensive error handling**: With actionable error messages

**Key Functions**:

```python
@lru_cache(maxsize=1)
def get_database_credentials() -> Dict[str, str]:
    """Fetch and cache credentials from Secrets Manager."""
    # Returns: {username, password, host, port, dbname, engine}

def get_database_url(use_ssl: bool = True) -> str:
    """Construct PostgreSQL URL with 3-tier fallback strategy."""
    # 1. DATABASE_URL env var (testing override)
    # 2. Secrets Manager via DB_SECRET_ARN (PRODUCTION)
    # 3. Individual DATABASE_* env vars (legacy)
```

### 3. SQLAlchemy Connection - `database/connection.py`

Updated `_get_database_url()` to add Secrets Manager support:

**Priority Order**:
1. `DATABASE_URL` environment variable (testing/local override)
2. **AWS Secrets Manager** via `DB_SECRET_ARN` (RECOMMENDED)
3. AWS Parameter Store via `PARAMETER_STORE_DB_URL` (DEPRECATED)
4. SQLite fallback for local development

### 4. Main Database Module - `database.py`

Updated `get_db()` context manager to support both SQLite and PostgreSQL:

**Before**: SQLite only
```python
conn = sqlite3.connect(active_path)
```

**After**: Database-aware
```python
if os.getenv("DB_SECRET_ARN"):
    # PostgreSQL for Lambda/production
    conn = psycopg2.connect(
        host=creds['host'],
        port=creds['port'],
        database=creds['dbname'],
        user=creds['username'],
        password=creds['password'],
        sslmode='require',
        cursor_factory=psycopg2.extras.RealDictCursor
    )
else:
    # SQLite for local development
    conn = sqlite3.connect(active_path)
```

## Deployment Steps

### 1. Deploy Infrastructure Changes

```bash
cd infrastructure
cdk deploy CollectionsCompute-dev --require-approval never
```

This will:
- Add `DB_SECRET_ARN` environment variable to all Lambda functions
- Maintain existing `secretsmanager:GetSecretValue` permissions

### 2. Verify Secret Exists

```bash
# Get secret ARN from stack outputs
aws cloudformation describe-stacks \
  --stack-name CollectionsDB-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`DatabaseSecretArn`].OutputValue' \
  --output text

# Verify secret content
aws secretsmanager get-secret-value \
  --secret-id <SECRET_ARN> \
  --query SecretString \
  --output text | jq .
```

Expected output:
```json
{
  "username": "postgres",
  "password": "<generated-password>",
  "engine": "postgres",
  "host": "<rds-endpoint>",
  "port": 5432,
  "dbname": "collections"
}
```

### 3. Test the Fix

```bash
# Test /items endpoint
curl 'https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com/items?limit=50&offset=0' \
  --header 'Authorization: Bearer <YOUR_TOKEN>'
```

**Expected**: 200 OK with items list (or empty array if no items)

## Verification

### Check Lambda Logs

```bash
aws logs tail /aws/lambda/CollectionsCompute-dev-APILambda7D19CDDA-<suffix> \
  --follow --since 1m
```

**Success indicators**:
```
Successfully retrieved database credentials from Secrets Manager
Constructed database URL from Secrets Manager credentials
```

**Failure indicators**:
```
Failed to retrieve DATABASE_URL from Secrets Manager: ...
RuntimeError: DB_SECRET_ARN environment variable not set
```

### Verify Environment Variables

```bash
aws lambda get-function-configuration \
  --function-name <LAMBDA_NAME> \
  --query 'Environment.Variables.DB_SECRET_ARN'
```

Should return the secret ARN.

## Local Development

The implementation maintains full backwards compatibility for local development:

```bash
# Local .env file
DATABASE_PATH=./data/collections.db

# No DB_SECRET_ARN set → uses SQLite
python -m uvicorn main:app --reload
```

## Security Benefits

### Before (Insecure)
- ❌ Database password in Parameter Store (plaintext in CloudFormation)
- ❌ No automatic rotation
- ❌ Password visible in CDK code (`unsafe_unwrap()`)

### After (Secure)
- ✅ Credentials in Secrets Manager (encrypted)
- ✅ Automatic rotation support
- ✅ No credentials in environment variables
- ✅ IAM-based access control
- ✅ CloudTrail audit logging
- ✅ Cached for performance (LRU cache)

## Rollback Plan

If issues occur, the code maintains backwards compatibility:

1. **Remove `DB_SECRET_ARN`** from Lambda environment variables
2. **Add `DATABASE_URL`** directly (temporary):
   ```bash
   aws lambda update-function-configuration \
     --function-name <LAMBDA_NAME> \
     --environment Variables='{
       "DATABASE_URL": "postgresql://user:pass@host:5432/db?sslmode=require"
     }'
   ```

3. Investigate and fix Secrets Manager issues

## Troubleshooting

### Error: "psycopg2 not available"

**Cause**: psycopg2-binary not installed in Lambda environment

**Fix**: Rebuild and redeploy Lambda with updated dependencies:
```bash
docker build -t collections-api .
cdk deploy CollectionsCompute-dev
```

### Error: "Secret not found"

**Cause**: Secret ARN is incorrect or secret doesn't exist

**Fix**: Verify secret ARN matches the one created by RDS:
```bash
aws secretsmanager list-secrets \
  --query 'SecretList[?contains(Name, `collections`)].ARN'
```

### Error: "Access denied to secret"

**Cause**: Lambda role missing `secretsmanager:GetSecretValue` permission

**Fix**: CDK automatically grants this at line 201 of compute_stack.py. Redeploy:
```bash
cdk deploy CollectionsCompute-dev
```

## Future Enhancements

1. **Automatic Credential Rotation**:
   ```python
   # Enable in database_stack.py
   self.db_credentials.add_rotation_schedule(
       "RotationSchedule",
       automatically_after=Duration.days(30)
   )
   ```

2. **Remove Parameter Store Usage** (lines 191-208 in database_stack.py):
   - Delete insecure database URL parameter
   - Migrate all secrets to Secrets Manager

3. **Connection Pooling**:
   - Implement RDS Proxy for connection pooling
   - Reduces connection overhead in serverless environment

## References

- [AWS Secrets Manager Best Practices](https://docs.aws.amazon.com/secretsmanager/latest/userguide/best-practices.html)
- [RDS Secret Rotation](https://docs.aws.amazon.com/secretsmanager/latest/userguide/rotate-secrets_turn-on-for-db.html)
- [Lambda + Secrets Manager](https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars.html#configuration-envvars-retrieve)
