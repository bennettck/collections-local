# Phase 4: API Lambda with Mangum Adapter - Implementation Summary

## Overview

Successfully implemented the FastAPI + Mangum adapter for deploying the Collections API to AWS Lambda with Cognito JWT authentication.

**Implementation Date**: December 27, 2025
**Status**: ✅ Complete - All tests passing

---

## Components Implemented

### 1. App Directory Structure

```
app/
├── __init__.py              # Package initialization
├── config.py                # AWS Parameter Store configuration loader
├── Dockerfile               # Lambda container image definition
└── middleware/
    ├── __init__.py          # Middleware package initialization
    └── auth.py              # Cognito JWT authentication middleware
```

### 2. Configuration Management (`app/config.py`)

**Purpose**: Load secrets from AWS Systems Manager Parameter Store with fallback to environment variables for local development.

**Key Features**:
- ✅ Thread-safe caching of Parameter Store values
- ✅ Automatic fallback to environment variables
- ✅ Auto-detection of local vs AWS environment
- ✅ Helper methods for database, Cognito, and API key configuration
- ✅ Support for SecureString decryption

**Usage Example**:
```python
from app.config import get_config

config = get_config()
anthropic_key = config.get("ANTHROPIC_API_KEY")
db_config = config.get_database_config()
cognito_config = config.get_cognito_config()
```

**API**:
- `Config.get(key, default=None, required=False)` - Get configuration value
- `Config.get_database_config()` - Get database connection parameters
- `Config.get_cognito_config()` - Get Cognito User Pool configuration
- `Config.get_api_keys()` - Get all API keys
- `Config.clear_cache()` - Clear the configuration cache

**Environment Detection**:
- If `AWS_REGION` is not set → Uses local mode (env vars only)
- If `AWS_REGION` is set → Uses Parameter Store with env var fallback

---

### 3. Cognito Authentication Middleware (`app/middleware/auth.py`)

**Purpose**: Validate JWT tokens from AWS Cognito User Pools and extract user identity.

**Key Features**:
- ✅ JWT signature validation using Cognito JWKS
- ✅ Token expiration checking
- ✅ User ID extraction from 'sub' claim
- ✅ Public endpoint exemption (health checks, docs, static files)
- ✅ Can be disabled for local development
- ✅ Cached JWKS fetching for performance

**Protected Endpoints**:
All endpoints except:
- `/health`
- `/docs`
- `/openapi.json`
- `/redoc`
- `/static/*`

**Usage in Endpoints**:
```python
from fastapi import Request, Depends
from app.middleware.auth import get_current_user

@app.get("/items")
async def list_items(
    request: Request,
    user_id: str = Depends(get_current_user)
):
    # user_id is automatically extracted from JWT
    # Filter items by user_id
    ...
```

**How It Works**:
1. Extracts JWT from `Authorization: Bearer <token>` header
2. Fetches Cognito JWKS from AWS
3. Validates JWT signature using public key
4. Checks token expiration and claims
5. Extracts `user_id` from `sub` claim
6. Stores `user_id` in `request.state.user_id` for downstream use

**Error Responses**:
- `401 Unauthorized` - Missing or invalid token
- `401 Unauthorized` - Expired token
- `401 Unauthorized` - Missing 'sub' claim
- `500 Internal Server Error` - JWKS fetch failure

---

### 4. Lambda Container Image (`app/Dockerfile`)

**Purpose**: Create a Lambda-compatible container image for deploying the FastAPI application.

**Base Image**: `public.ecr.aws/lambda/python:3.12`

**Key Features**:
- ✅ PostgreSQL client libraries installed
- ✅ All Python dependencies from requirements.txt
- ✅ Application code copied
- ✅ Temporary directories created for Lambda runtime
- ✅ Optimized for Lambda cold start performance

**Build Command**:
```bash
docker build -f app/Dockerfile -t collections-api:latest .
```

**Lambda Handler**: `main.handler` (Mangum adapter)

---

### 5. Mangum Integration (`main.py`)

**Changes Made**:
1. ✅ Added `from mangum import Mangum` import
2. ✅ Added Cognito authentication middleware (conditionally enabled)
3. ✅ Created `handler = Mangum(app, lifespan="off")` at end of file

**Cognito Integration**:
```python
# Only enabled when COGNITO_USER_POOL_ID is set (AWS environment)
cognito_user_pool_id = os.getenv("COGNITO_USER_POOL_ID")
cognito_enabled = cognito_user_pool_id and cognito_user_pool_id != "WILL_BE_SET_BY_CDK"

if cognito_enabled:
    from app.middleware.auth import CognitoAuthMiddleware

    app.add_middleware(
        CognitoAuthMiddleware,
        user_pool_id=cognito_user_pool_id,
        region=cognito_region,
        client_id=cognito_client_id,
        enabled=True,
    )
```

**Handler Creation**:
```python
# Mangum handler for AWS Lambda
handler = Mangum(app, lifespan="off")
```

**Why `lifespan="off"`**: Avoids lifespan issues in Lambda where the app may not have full startup/shutdown control.

---

### 6. Dependencies Added (`requirements.txt`)

```txt
# AWS Lambda adapter
mangum>=0.17.0
# JWT validation for Cognito
python-jose[cryptography]>=3.3.0
```

Note: `requests` was already present in requirements.txt.

---

### 7. Unit Tests (`tests/unit/test_auth_middleware.py`)

**Test Coverage**: 16 tests, 100% passing ✅

**Test Categories**:

1. **Public Endpoints** (2 tests)
   - ✅ Public endpoints accessible without auth
   - ✅ Static file endpoints accessible

2. **Token Validation** (7 tests)
   - ✅ Missing token rejection
   - ✅ Invalid header format rejection
   - ✅ Valid token acceptance
   - ✅ User ID extraction
   - ✅ Missing 'sub' claim rejection
   - ✅ Invalid token_use rejection
   - ✅ Expired token rejection

3. **JWKS Validation** (3 tests)
   - ✅ JWKS fetch failure handling
   - ✅ JWK key matching
   - ✅ No matching key handling

4. **Dependencies** (2 tests)
   - ✅ `get_current_user` dependency function
   - ✅ Unauthenticated access rejection

5. **Configuration** (2 tests)
   - ✅ Auth disabled mode (local dev)
   - ✅ Auth enabled mode (AWS)

**Running Tests**:
```bash
pytest tests/unit/test_auth_middleware.py -v
```

**Test Results**:
```
16 passed in 0.64s
```

---

## Implementation Architecture

### Request Flow (AWS Environment)

```
API Gateway (or Lambda URL)
    ↓
Lambda Runtime
    ↓
Mangum Handler (main.handler)
    ↓
FastAPI App
    ↓
CognitoAuthMiddleware
    ├─ Public endpoint? → Skip auth
    ├─ Extract JWT from Authorization header
    ├─ Fetch Cognito JWKS
    ├─ Validate JWT signature & claims
    └─ Extract user_id from 'sub' claim
    ↓
Store user_id in request.state
    ↓
Route Handler (with user_id available)
    ↓
Response
```

### Request Flow (Local Development)

```
Uvicorn Server
    ↓
FastAPI App
    ↓
CognitoAuthMiddleware (disabled)
    └─ Set user_id = "local-dev-user"
    ↓
Route Handler
    ↓
Response
```

---

## Configuration Management

### AWS Parameter Store Structure

All secrets stored under `/collections/` prefix:

```
/collections/ANTHROPIC_API_KEY
/collections/OPENAI_API_KEY
/collections/VOYAGE_API_KEY
/collections/TAVILY_API_KEY
/collections/LANGSMITH_API_KEY
/collections/DATABASE_HOST
/collections/DATABASE_PORT
/collections/DATABASE_NAME
/collections/DATABASE_USERNAME
/collections/DATABASE_PASSWORD
/collections/COGNITO_USER_POOL_ID
/collections/COGNITO_CLIENT_ID
/collections/COGNITO_REGION
```

### Environment Variables (Local Development)

Same keys as Parameter Store, loaded from `.env` file.

---

## Security Considerations

### JWT Validation

- ✅ Signature verification using Cognito public keys (RS256)
- ✅ Token expiration checking
- ✅ Audience claim validation (if client_id provided)
- ✅ Token use validation (must be 'access' or 'id')
- ✅ Issuer validation (Cognito User Pool URL)

### Secrets Management

- ✅ No secrets in code or environment variables (AWS)
- ✅ All secrets encrypted in Parameter Store
- ✅ Automatic decryption via IAM permissions
- ✅ Configuration caching to minimize API calls

### Least Privilege

The Lambda execution role requires:
- `ssm:GetParameter` - To read from Parameter Store
- `ssm:GetParameters` - To batch read parameters
- No write permissions required

---

## Deployment Workflow

### 1. Build Container Image

```bash
# Build the image
docker build -f app/Dockerfile -t collections-api:latest .

# Tag for ECR
docker tag collections-api:latest <account-id>.dkr.ecr.us-east-1.amazonaws.com/collections-api:latest

# Push to ECR
docker push <account-id>.dkr.ecr.us-east-1.amazonaws.com/collections-api:latest
```

### 2. Update Lambda Function

```bash
# Update Lambda function code (via CDK or AWS CLI)
aws lambda update-function-code \
  --function-name collections-api-lambda \
  --image-uri <account-id>.dkr.ecr.us-east-1.amazonaws.com/collections-api:latest
```

### 3. Populate Parameter Store

```bash
# Use the Makefile command
make secrets-populate ENV=dev

# Or use AWS CLI
aws ssm put-parameter \
  --name /collections/ANTHROPIC_API_KEY \
  --value "sk-ant-..." \
  --type SecureString \
  --overwrite
```

---

## Testing Strategy

### Unit Tests (Implemented)

- ✅ Middleware authentication logic
- ✅ JWT token validation
- ✅ User ID extraction
- ✅ Public endpoint handling
- ✅ Error scenarios

### Integration Tests (Future)

- [ ] End-to-end API requests with real Cognito
- [ ] Lambda invocation tests
- [ ] Parameter Store integration
- [ ] Database connectivity

### Local Testing

```bash
# Run with auth disabled
export COGNITO_USER_POOL_ID=""
uvicorn main:app --reload

# Run with mock auth
export COGNITO_USER_POOL_ID="WILL_BE_SET_BY_CDK"
uvicorn main:app --reload
```

---

## Key Design Decisions

### 1. Middleware vs Dependency Injection

**Choice**: Middleware approach

**Rationale**:
- Applies globally to all routes (less boilerplate)
- Can return 401 before route handler executes
- Easier to exempt public endpoints
- Sets `request.state.user_id` for all handlers

### 2. Mangum lifespan="off"

**Choice**: Disabled lifespan events

**Rationale**:
- Lambda has limited control over app lifecycle
- Startup events may not complete before first request
- Database connections managed per-request
- Prevents startup timeout issues

### 3. Parameter Store Caching

**Choice**: In-memory cache with `@lru_cache`

**Rationale**:
- Reduces API calls to Parameter Store
- Improves Lambda cold start performance
- Simple implementation
- Cache cleared on Lambda container recycle

### 4. Local Development Mode

**Choice**: Auto-detect based on `AWS_REGION` env var

**Rationale**:
- No code changes required for local vs AWS
- Graceful fallback to environment variables
- Can be overridden with `use_local=True`
- Developer-friendly experience

---

## Next Steps (Not in Scope)

The following items are part of Phase 5+ and NOT implemented in this phase:

1. ❌ User ID filtering in database queries (Phase 5)
2. ❌ Multi-tenancy database schema changes (Phase 5)
3. ❌ API Gateway integration (Infrastructure team)
4. ❌ Cognito User Pool setup (Infrastructure team)
5. ❌ ECR repository creation (Infrastructure team)
6. ❌ Lambda function deployment (Infrastructure team)

---

## Success Criteria - ALL MET ✅

- ✅ app directory created with all modules
- ✅ Cognito JWT auth middleware working
- ✅ Parameter Store config loading implemented
- ✅ Dockerfile created for Lambda deployment
- ✅ Mangum handler added to main.py
- ✅ Unit tests passing (16/16 tests, 0.64s)
- ✅ All dependencies added to requirements.txt
- ✅ No breaking changes to existing functionality
- ✅ Local development still works (auth disabled mode)

---

## Files Created

```
app/
├── __init__.py                              # 7 lines
├── config.py                                # 215 lines
├── Dockerfile                               # 36 lines
└── middleware/
    ├── __init__.py                          # 5 lines
    └── auth.py                              # 326 lines

tests/unit/
├── __init__.py                              # 1 line
└── test_auth_middleware.py                  # 395 lines

Total: 985 lines of production + test code
```

## Files Modified

```
main.py                                      # +30 lines (Mangum handler)
requirements.txt                             # +4 lines (mangum, python-jose)
```

---

## Documentation References

- [AWS Lambda Python Base Images](https://docs.aws.amazon.com/lambda/latest/dg/python-image.html)
- [Mangum Documentation](https://mangum.io/)
- [AWS Cognito JWT Tokens](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-with-identity-providers.html)
- [AWS Parameter Store](https://docs.aws.amazon.com/systems-manager/latest/userguide/systems-manager-parameter-store.html)
- [FastAPI Middleware](https://fastapi.tiangolo.com/tutorial/middleware/)
- [python-jose](https://python-jose.readthedocs.io/)

---

## Summary

Phase 4 implementation is **complete and tested**. The API is now ready for Lambda deployment with:

1. ✅ **Mangum adapter** - Wraps FastAPI for Lambda compatibility
2. ✅ **Cognito authentication** - JWT validation with user ID extraction
3. ✅ **Parameter Store integration** - Secure secret management
4. ✅ **Lambda Dockerfile** - Container image for deployment
5. ✅ **Comprehensive tests** - 16 unit tests covering all scenarios
6. ✅ **Backward compatibility** - Local development still works

The implementation follows library-first principles (Mangum, python-jose, boto3) and includes thorough testing during development.

**Ready for**: Infrastructure deployment and Phase 5 (multi-tenancy user filtering).
