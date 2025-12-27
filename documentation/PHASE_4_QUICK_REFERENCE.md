# Phase 4: API Lambda - Quick Reference Guide

## Testing the Implementation

### Run Unit Tests
```bash
pytest tests/unit/test_auth_middleware.py -v
```

### Test App Module Components
```bash
python -c "
from app.config import Config, get_config
from app.middleware.auth import CognitoAuthMiddleware

config = Config(use_local=True)
print('✓ Config working')
print('✓ Auth middleware working')
"
```

### Test Mangum Handler
```bash
python -c "
from mangum import Mangum
from fastapi import FastAPI

app = FastAPI()
handler = Mangum(app, lifespan='off')
print('✓ Mangum handler created')
"
```

---

## Local Development

### Run with Auth Disabled (Default)
```bash
# No Cognito env vars set
uvicorn main:app --reload --port 8000
```

### Run with Mock Auth
```bash
# Set Cognito vars to placeholder values
export COGNITO_USER_POOL_ID="WILL_BE_SET_BY_CDK"
export COGNITO_CLIENT_ID="WILL_BE_SET_BY_CDK"
uvicorn main:app --reload --port 8000
```

---

## Using the Auth Middleware in Endpoints

### Option 1: Access from Request State
```python
@app.get("/items")
async def list_items(request: Request):
    user_id = request.state.user_id
    # Filter items by user_id
    return {"user_id": user_id}
```

### Option 2: Use Dependency Injection
```python
from fastapi import Depends
from app.middleware.auth import get_current_user

@app.get("/items")
async def list_items(user_id: str = Depends(get_current_user)):
    # user_id automatically extracted
    return {"user_id": user_id}
```

---

## Configuration Management

### Load Config in Your Code
```python
from app.config import get_config

# Get singleton instance
config = get_config()

# Get individual values
anthropic_key = config.get("ANTHROPIC_API_KEY")
db_host = config.get("DATABASE_HOST", required=True)

# Get structured configs
db_config = config.get_database_config()
cognito_config = config.get_cognito_config()
api_keys = config.get_api_keys()
```

### Force Local Mode
```python
from app.config import Config

# Override auto-detection
config = Config(use_local=True)
value = config.get("MY_KEY")  # Only checks env vars
```

---

## Building the Lambda Image

### Build Locally
```bash
docker build -f app/Dockerfile -t collections-api:latest .
```

### Test Locally
```bash
docker run -p 9000:8080 \
  -e AWS_REGION=us-east-1 \
  -e DATABASE_HOST=localhost \
  -e COGNITO_USER_POOL_ID=us-east-1_TestPool \
  collections-api:latest
```

### Invoke Locally
```bash
curl -X POST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -d '{
    "httpMethod": "GET",
    "path": "/health",
    "headers": {},
    "body": null
  }'
```

---

## Parameter Store Setup

### Populate from .env.dev
```bash
make secrets-populate ENV=dev
```

### Manual Parameter Creation
```bash
aws ssm put-parameter \
  --name /collections/ANTHROPIC_API_KEY \
  --value "sk-ant-..." \
  --type SecureString \
  --overwrite

aws ssm put-parameter \
  --name /collections/DATABASE_HOST \
  --value "collections-db.us-east-1.rds.amazonaws.com" \
  --type String \
  --overwrite
```

### List Parameters
```bash
aws ssm get-parameters-by-path \
  --path /collections/ \
  --recursive \
  --with-decryption
```

---

## Cognito Token Format

### Valid Authorization Header
```
Authorization: Bearer eyJraWQiOiJ...full-jwt-token...
```

### JWT Claims Structure
```json
{
  "sub": "user-uuid-12345",
  "token_use": "access",
  "aud": "client-id",
  "iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_PoolId",
  "exp": 1735344000,
  "iat": 1735340400
}
```

### Extract User ID
The `sub` claim contains the unique user ID:
```python
user_id = request.state.user_id  # Extracted from 'sub' claim
```

---

## Public Endpoints (No Auth Required)

The following endpoints are always accessible:
- `/health`
- `/docs`
- `/openapi.json`
- `/redoc`
- `/static/*`

---

## Error Responses

### Missing Token
```json
HTTP 401 Unauthorized
{
  "detail": "Missing authorization header"
}
```

### Invalid Token
```json
HTTP 401 Unauthorized
{
  "detail": "Invalid token: ..."
}
```

### Expired Token
```json
HTTP 401 Unauthorized
{
  "detail": "Token has expired"
}
```

### Missing Sub Claim
```json
HTTP 401 Unauthorized
{
  "detail": "Missing 'sub' claim in token"
}
```

---

## Debugging

### Enable Debug Logging
```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Or in your code
logger = logging.getLogger("app.middleware.auth")
logger.setLevel(logging.DEBUG)
```

### Check Middleware State
```python
@app.get("/debug")
async def debug(request: Request):
    return {
        "user_id": getattr(request.state, "user_id", None),
        "authenticated": getattr(request.state, "authenticated", None),
        "token_claims": getattr(request.state, "token_claims", None)
    }
```

### Test JWKS Fetch
```python
from app.middleware.auth import CognitoAuthMiddleware
from fastapi import FastAPI

middleware = CognitoAuthMiddleware(
    app=FastAPI(),
    user_pool_id="us-east-1_TestPool",
    region="us-east-1"
)

jwks = middleware._get_jwks()
print(jwks)
```

---

## Common Issues

### Issue: ImportError for database
**Cause**: Conflicting `database.py` file and `database/` package
**Solution**: This is expected - the new `database/` package is for future PostgreSQL migration

### Issue: Auth not working locally
**Cause**: Cognito env vars are set
**Solution**: Unset `COGNITO_USER_POOL_ID` or set to "WILL_BE_SET_BY_CDK"

### Issue: JWKS fetch failure
**Cause**: Network connectivity or invalid User Pool ID
**Solution**: Check AWS credentials and User Pool ID format

### Issue: Token validation fails
**Cause**: Clock skew or wrong region
**Solution**: Verify system time and Cognito region matches

---

## File Locations

```
app/
├── config.py              # Configuration loader
├── Dockerfile             # Lambda container image
└── middleware/
    └── auth.py            # Cognito JWT middleware

tests/unit/
└── test_auth_middleware.py  # Unit tests

documentation/
├── PHASE_4_API_LAMBDA_IMPLEMENTATION.md  # Full implementation guide
└── PHASE_4_QUICK_REFERENCE.md            # This file
```

---

## Next Phase Preview

Phase 5 will implement:
1. User ID filtering in database queries
2. Multi-tenancy row-level security
3. Migration scripts for existing data
4. Integration tests with real Cognito

NOT modifying:
- `app/config.py` (complete)
- `app/middleware/auth.py` (complete)
- `app/Dockerfile` (complete)
- `main.py` Mangum integration (complete)
