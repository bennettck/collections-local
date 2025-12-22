# AWS Cloud Migration Plan - Collections Local

## Executive Summary

Migrate the collections-local image analysis application from local development to AWS cloud using provider-native serverless services with user authentication and multi-tenancy.

### Target Architecture
- **Auth**: AWS Cognito (user management, JWT tokens)
- **API**: Lambda + API Gateway (FastAPI via Mangum)
- **Database**: RDS PostgreSQL (public, no VPC) with JSONB + pgvector
- **Storage**: S3 (images with per-user isolation)
- **Workflow**: Event-driven Lambda functions (EventBridge)
- **Secrets**: AWS Systems Manager Parameter Store (FREE)
- **Infrastructure**: AWS CDK (Python)

### Estimated Monthly Cost
- **RDS PostgreSQL** (db.t4g.micro, public): $15-20
- **Lambda**: $5-15 (first 1M requests free)
- **API Gateway** (HTTP API): $1-2
- **S3**: $0.50
- **CloudWatch Logs**: $1-2
- **Parameter Store**: FREE
- **Total**: ~$22-40/month (small team usage)

**Savings from simplified architecture:**
- No VPC/NAT Gateway: Saves $32/month
- No RDS Proxy needed: Saves $11/month
- No users table sync complexity

### Key Simplifications

This plan uses a **pragmatic, simplified approach** for a small-scale application:

1. **No VPC** - Public RDS with security groups (saves $32/month, faster Lambda cold starts)
2. **No RLS** - Manual `WHERE user_id = ?` filters instead of Row-Level Security (easier to debug)
3. **No Users Table** - Use Cognito `sub` directly (no sync complexity, simpler schema)
4. **Manual Multi-tenancy** - Extract user_id from JWT → add to all queries (straightforward, explicit)

**Trade-off**: Slightly more code (manual filters) in exchange for:
- Lower cost (~$20-30/month vs ~$60-70/month)
- Simpler architecture (no VPC, no connection pooling complexity)
- Easier debugging (explicit WHERE clauses vs invisible RLS)
- Faster cold starts (Lambda not in VPC)

---

## Architecture Overview

### Lambda Function Division

```
┌─────────────────────────────────────────────────────┐
│  1. API Lambda (FastAPI)                            │
│     - All HTTP endpoints (GET/POST/DELETE)          │
│     - Manual workflow triggers                      │
│     - User authentication (JWT validation)          │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  2. Image Processor Lambda                          │
│     - Triggered by S3 upload event                  │
│     - Resize images, create thumbnails              │
│     - Publishes "ImageProcessed" event              │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  3. Analysis Lambda                                  │
│     - Triggered by EventBridge event                │
│     - Calls Claude/GPT vision APIs                  │
│     - Stores analysis in PostgreSQL                 │
│     - Publishes "AnalysisComplete" event            │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  4. Embedding Lambda                                 │
│     - Triggered by EventBridge event                │
│     - Calls VoyageAI for vector embeddings          │
│     - Stores in PostgreSQL (pgvector)               │
└─────────────────────────────────────────────────────┘
```

### Automated Workflow

```
User uploads image (POST /items)
    ↓
API Lambda → S3.put_object()
    ↓
S3 Event → Image Processor Lambda
    ↓
EventBridge: "ImageProcessed" → Analysis Lambda
    ↓
EventBridge: "AnalysisComplete" → Embedding Lambda
    ↓
Complete
```

### Manual Workflow (Independent Calls)

```
POST /items/{id}/analyze     → Direct invoke Analysis Lambda
POST /items/{id}/resize-only → Direct invoke Image Processor Lambda
POST /vector-index/rebuild   → Batch invoke Embedding Lambda
```

---

## Database Schema Changes

### Multi-Tenancy with Manual Filtering (Simplified)

```sql
-- Items (with user_id from Cognito JWT)
CREATE TABLE items (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,             -- Cognito sub from JWT token
    filename TEXT NOT NULL,
    original_filename TEXT,
    file_path TEXT NOT NULL,           -- s3://bucket/{user_id}/images/{uuid}.jpg
    thumbnail_path TEXT,               -- s3://bucket/{user_id}/thumbnails/{uuid}.jpg
    file_size INTEGER,
    mime_type TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_items_user_id ON items(user_id);

-- Analyses (JSONB instead of TEXT)
CREATE TABLE analyses (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,             -- Cognito sub from JWT token
    version INTEGER DEFAULT 1,
    category TEXT,
    summary TEXT,
    raw_response JSONB,                -- Changed from TEXT to JSONB
    provider_used TEXT,
    model_used TEXT,
    trace_id TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_analyses_user_id ON analyses(user_id);

-- Embeddings with pgvector
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE embeddings (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,             -- Cognito sub from JWT token
    analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    embedding vector(1024),
    embedding_model TEXT NOT NULL,
    embedding_dimensions INTEGER NOT NULL,
    embedding_source JSONB,             -- Changed from TEXT to JSONB
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_embeddings_item_id ON embeddings(item_id);
CREATE INDEX idx_embeddings_user_id ON embeddings(user_id);

-- PostgreSQL Full-Text Search (replaces SQLite FTS5)
ALTER TABLE analyses ADD COLUMN search_vector tsvector;

CREATE INDEX idx_analyses_search ON analyses USING GIN(search_vector);

-- Update function for search vector
CREATE OR REPLACE FUNCTION update_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', COALESCE(NEW.summary, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(NEW.category, '')), 'B');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER analyses_search_update
    BEFORE INSERT OR UPDATE ON analyses
    FOR EACH ROW
    EXECUTE FUNCTION update_search_vector();
```

---

## Secrets Management

### AWS Systems Manager Parameter Store (FREE)

All secrets stored in Parameter Store as encrypted parameters:

```
/collections/anthropic-api-key      (SecureString)
/collections/openai-api-key         (SecureString)
/collections/voyage-api-key         (SecureString)
/collections/langsmith-api-key      (SecureString)
/collections/database-url           (SecureString) - Auto-generated by RDS
```

### Configuration (Lambda Environment Variables)

Non-sensitive configuration injected by CDK:

```
LANGSMITH_PROJECT=collections-local
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_PROMPT_NAME=collections-app-initial
VOYAGE_EMBEDDING_MODEL=voyage-3.5-lite
BUCKET_NAME={auto-generated by CDK}
DB_SECRET_ARN={auto-generated by RDS}
```

---

## Code Migration Strategy

### How Much Code Changes?

The good news: **Most of your existing code works with minimal changes**. Here's the breakdown:

#### ✅ **Copy/Paste Files (No changes needed)**

These files work as-is in Lambda:

1. **`llm.py`** - LLM analysis logic
   - Anthropic/OpenAI API calls → unchanged
   - LangSmith integration → unchanged
   - Just ensure environment variables come from Parameter Store instead of .env

2. **`embeddings.py`** - Vector embedding generation
   - VoyageAI API calls → unchanged
   - Embedding logic → unchanged

3. **`models.py`** - Pydantic models
   - Request/response schemas → unchanged

4. **Most of `database.py`** - Database functions
   - SQL queries → mostly unchanged (just swap SQLite → PostgreSQL syntax)
   - Connection logic → needs update for PostgreSQL

#### 🔧 **Files That Need Modifications**

**1. `main.py` → API Lambda**

**Changes needed:**
```python
# ADD: Mangum adapter for Lambda
from mangum import Mangum

app = FastAPI(...)

# ADD: Lambda handler
handler = Mangum(app)

# ADD: Auth middleware
from middleware.auth import authenticate
app.middleware("http")(authenticate)

# CHANGE: All endpoints - add user_id filtering
# Before:
items = list_items(category=category, limit=limit, offset=offset)

# After:
items = list_items(
    user_id=request.state.user_id,  # NEW
    category=category,
    limit=limit,
    offset=offset
)

# CHANGE: File uploads - S3 instead of local filesystem
# Before:
async with aiofiles.open(file_path, "wb") as f:
    await f.write(content)

# After:
s3_client.put_object(
    Bucket=BUCKET_NAME,
    Key=f"{user_id}/images/{filename}",
    Body=content
)

# CHANGE: Image serving - pre-signed URLs
# Before:
return FileResponse(file_path)

# After:
url = s3_client.generate_presigned_url(
    'get_object',
    Params={'Bucket': BUCKET_NAME, 'Key': key},
    ExpiresIn=3600
)
return {"url": url}
```

**Estimate**: ~30-40 lines changed out of 981 lines (3-4% of file)

---

**2. `database.py` → PostgreSQL Updates**

**Changes needed:**
```python
# CHANGE: Connection string
# Before:
conn = sqlite3.connect(db_path)

# After:
import psycopg2
conn = psycopg2.connect(os.environ['DATABASE_URL'])

# CHANGE: Query syntax (minor)
# Before (SQLite):
cursor.execute("INSERT ... RETURNING *")
row = cursor.fetchone()

# After (PostgreSQL):
cursor.execute("INSERT ... RETURNING *")
row = cursor.fetchone()  # Same!

# CHANGE: JSON handling
# Before (SQLite):
json.dumps(raw_response)  # Store as TEXT

# After (PostgreSQL):
raw_response  # JSONB natively supported, no dumps needed

# ADD: user_id parameter to all queries
# Before:
def list_items(category=None, limit=50, offset=0):
    query = "SELECT * FROM items WHERE ..."

# After:
def list_items(user_id: str, category=None, limit=50, offset=0):
    query = "SELECT * FROM items WHERE user_id = %s AND ..."
    params = [user_id]

# CHANGE: FTS search
# Before (SQLite FTS5):
FROM items_fts WHERE items_fts MATCH ?

# After (PostgreSQL tsvector):
FROM analyses WHERE search_vector @@ to_tsquery(?)

# CHANGE: Vector search
# Before (sqlite-vec):
vec_distance(embedding, ?)

# After (pgvector):
embedding <-> ?
```

**Estimate**: ~100-150 lines changed out of ~800 lines (12-18% of file)

---

**3. NEW: `app/middleware/auth.py`**

**Create new file** (~50 lines):
```python
from fastapi import Request, HTTPException
from jose import jwt, JWTError
import requests

COGNITO_JWKS_URL = "https://cognito-idp.{region}.amazonaws.com/{pool}/.well-known/jwks.json"

async def authenticate(request: Request, call_next):
    # Skip health checks
    if request.url.path == "/health":
        return await call_next(request)

    # Extract JWT token
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(401, "Missing auth")

    token = auth_header.split(" ")[1]

    # Verify and extract user_id
    claims = jwt.decode(token, ...)
    request.state.user_id = claims["sub"]

    return await call_next(request)
```

---

**4. NEW: `app/config.py`**

**Create new file** (~40 lines):
```python
import boto3
import os

# Load secrets from Parameter Store
def get_secret(name: str) -> str:
    ssm = boto3.client('ssm')
    response = ssm.get_parameter(Name=name, WithDecryption=True)
    return response['Parameter']['Value']

# Set environment variables from secrets
os.environ['ANTHROPIC_API_KEY'] = get_secret('/collections/anthropic-api-key')
os.environ['OPENAI_API_KEY'] = get_secret('/collections/openai-api-key')
os.environ['VOYAGE_API_KEY'] = get_secret('/collections/voyage-api-key')
os.environ['DATABASE_URL'] = get_secret('/collections/database-url')
```

---

#### 📦 **New Lambda Functions (Extract from existing code)**

**1. Image Processor Lambda** (~80 lines)
- Extract image resizing logic (if you have it) OR add new
- S3 event handler
- Publish EventBridge event

**2. Analyzer Lambda** (~60 lines)
- Reuse `llm.py` (copy/paste!)
- EventBridge handler
- Call `analyze_image()` from existing code

**3. Embedder Lambda** (~50 lines)
- Reuse `embeddings.py` (copy/paste!)
- EventBridge handler
- Call `generate_embedding()` from existing code

---

### Summary: Code Changes by File

| File | Status | Lines Changed | Effort |
|------|--------|---------------|--------|
| `llm.py` | ✅ Copy/paste | 0 | None |
| `embeddings.py` | ✅ Copy/paste | 0 | None |
| `models.py` | ✅ Copy/paste | 0 | None |
| `main.py` | 🔧 Modify | ~40 / 981 (4%) | Low |
| `database.py` | 🔧 Modify | ~120 / 800 (15%) | Medium |
| `middleware/auth.py` | ✨ New | ~50 | Low |
| `config.py` | ✨ New | ~40 | Low |
| `lambdas/image_processor/` | ✨ New | ~80 | Low |
| `lambdas/analyzer/` | ✨ New (reuses llm.py) | ~60 | Low |
| `lambdas/embedder/` | ✨ New (reuses embeddings.py) | ~50 | Low |

**Total new code**: ~280 lines
**Total modified code**: ~160 lines
**Reused unchanged code**: ~1500+ lines

---

### Migration Complexity: **LOW-MEDIUM**

Most of your business logic (LLM analysis, embeddings, search) **works as-is**. The main changes are:
1. Database connection (SQLite → PostgreSQL)
2. Authentication (add JWT middleware)
3. File storage (local filesystem → S3)
4. Add `user_id` filters to queries

Everything else is **copy/paste**!

---

## Project Structure

```
collections-cloud/
├── infrastructure/                  # AWS CDK infrastructure
│   ├── app.py                      # Main CDK stack definition
│   ├── requirements.txt            # aws-cdk-lib, constructs
│   ├── cdk.json                    # CDK configuration
│   └── README.md                   # Deployment instructions
│
├── app/                            # API Lambda (FastAPI)
│   ├── main.py                     # FastAPI app with Mangum handler
│   ├── database.py                 # PostgreSQL connection + RLS
│   ├── llm.py                      # AI analysis (existing code)
│   ├── embeddings.py               # Vector generation (existing code)
│   ├── config.py                   # NEW: Secrets/config management
│   ├── middleware/
│   │   └── auth.py                 # NEW: Cognito JWT validation
│   ├── Dockerfile                  # Container for Lambda
│   └── requirements.txt
│
├── lambdas/
│   ├── image_processor/
│   │   ├── handler.py              # S3 event handler
│   │   ├── requirements.txt        # Pillow, boto3
│   │   └── README.md
│   │
│   ├── analyzer/
│   │   ├── handler.py              # EventBridge handler
│   │   ├── Dockerfile              # Shares modules from app/
│   │   └── requirements.txt
│   │
│   └── embedder/
│       ├── handler.py              # EventBridge handler
│       └── requirements.txt        # voyageai, boto3, psycopg2
│
├── scripts/
│   ├── deploy.sh                   # CDK deployment script
│   ├── populate_secrets.sh         # Populate Parameter Store
│   ├── migrate_sqlite_to_postgres.py
│   └── migrate_images_to_s3.py
│
├── data/                           # Local development only
│   ├── collections.db              # Will be migrated to RDS
│   ├── collections_golden.db       # Will be migrated to RDS
│   └── images/                     # Will be migrated to S3
│
└── AWS_MIGRATION_PLAN.md           # This document
```

---

## CDK Infrastructure Code

### Main Stack (infrastructure/app.py)

Key components that CDK will create:

1. **RDS PostgreSQL** - db.t4g.micro (public) with automatic backups, SSL required
2. **S3 Bucket** - Images with EventBridge notifications enabled
3. **Cognito User Pool** - User authentication
4. **API Gateway** (HTTP API) - Routes to API Lambda
5. **4 Lambda Functions** - API, Image Processor, Analyzer, Embedder
6. **EventBridge Rules** - Workflow automation
7. **IAM Roles** - Least-privilege permissions
8. **Parameter Store Parameters** - Secrets storage (populated manually)
9. **CloudWatch Log Groups** - Centralized logging
10. **Security Groups** - RDS accessible only from Lambda + your IP

---

## Authentication & Multi-Tenancy Implementation

### Simplified Approach (No RLS, No Users Table)

**Middleware extracts user_id from JWT:**

```python
# app/middleware/auth.py
from fastapi import Request, HTTPException
from jose import jwt, JWTError
import requests

COGNITO_REGION = "us-east-1"
COGNITO_USER_POOL_ID = "us-east-1_XXXXXXXXX"
COGNITO_JWKS_URL = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}/.well-known/jwks.json"

@app.middleware("http")
async def authenticate(request: Request, call_next):
    # Skip auth for health checks
    if request.url.path in ["/health", "/docs"]:
        return await call_next(request)

    # Extract token
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization")

    token = auth_header.split(" ")[1]

    # Verify JWT and extract user_id
    try:
        # Download JWKS (cache this in production)
        jwks = requests.get(COGNITO_JWKS_URL).json()

        # Decode and verify token
        claims = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            audience=COGNITO_CLIENT_ID
        )

        # Store user_id in request state
        request.state.user_id = claims["sub"]  # Cognito user UUID

    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    return await call_next(request)
```

**Add user_id to all database queries:**

```python
# app/main.py

@app.get("/items")
async def get_items(request: Request, db: Database = Depends(get_db)):
    user_id = request.state.user_id

    items = await db.fetch_all(
        "SELECT * FROM items WHERE user_id = :user_id ORDER BY created_at DESC",
        {"user_id": user_id}
    )
    return items

@app.post("/items/{item_id}/analyze")
async def analyze_item(item_id: str, request: Request, db: Database = Depends(get_db)):
    user_id = request.state.user_id

    # Verify item belongs to user
    item = await db.fetch_one(
        "SELECT * FROM items WHERE id = :item_id AND user_id = :user_id",
        {"item_id": item_id, "user_id": user_id}
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Proceed with analysis...
```

**Vector search with user isolation:**

```python
@app.post("/search")
async def search(query: str, request: Request, db: Database = Depends(get_db)):
    user_id = request.state.user_id

    # Generate query embedding
    query_embedding = await generate_embedding(query)

    # Search only user's embeddings
    results = await db.fetch_all("""
        SELECT e.*, i.filename, a.summary
        FROM embeddings e
        JOIN items i ON e.item_id = i.id
        JOIN analyses a ON e.analysis_id = a.id
        WHERE e.user_id = :user_id
        ORDER BY e.embedding <-> :query_vector
        LIMIT 10
    """, {"user_id": user_id, "query_vector": query_embedding})

    return results
```

**Logging with user context:**

```python
import logging

logger = logging.getLogger(__name__)

@app.post("/items")
async def create_item(request: Request, file: UploadFile, db: Database = Depends(get_db)):
    user_id = request.state.user_id

    # Log with user context
    logger.info(
        "Creating item",
        extra={"user_id": user_id, "filename": file.filename}
    )

    # Create item...
    await db.execute(
        "INSERT INTO items (id, user_id, filename, ...) VALUES (:id, :user_id, ...)",
        {"id": item_id, "user_id": user_id, ...}
    )
```

---

## Migration Phases

### Phase 1: Infrastructure Setup & Validation

**Goal**: Deploy AWS infrastructure with CDK and validate each component

Tasks:
1. Install CDK and bootstrap AWS account
2. Create CDK stack definition (infrastructure/app.py)
   - Public RDS PostgreSQL with security groups
   - S3 bucket with EventBridge notifications
   - Cognito User Pool
   - API Gateway + Lambda functions
3. Deploy infrastructure: `cdk deploy`
4. **Test each component** (see testing checklist below)
5. Populate Parameter Store with API keys
6. Enable pgvector extension on RDS
7. Run schema creation scripts (simplified, no RLS)

**Deliverable**: Fully deployed and validated AWS infrastructure

---

### Infrastructure Testing Checklist

Run these tests after `cdk deploy` to validate infrastructure before migrating data:

#### 1. RDS PostgreSQL Connection Test
```bash
# From your local machine (add your IP to security group first)
psql -h <rds-endpoint>.rds.amazonaws.com -U postgres -d collections

# Test basic operations
CREATE TABLE test_table (id TEXT PRIMARY KEY, data TEXT);
INSERT INTO test_table VALUES ('test1', 'hello');
SELECT * FROM test_table;
DROP TABLE test_table;

# Test pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE test_embeddings (id TEXT, vec vector(3));
INSERT INTO test_embeddings VALUES ('1', '[1,2,3]');
SELECT * FROM test_embeddings ORDER BY vec <-> '[1,2,4]' LIMIT 1;
DROP TABLE test_embeddings;

# Verify SSL connection
\conninfo  # Should show SSL connection
```

**Expected result**: Successful connection, table operations work, pgvector works

---

#### 2. Parameter Store Test
```bash
# Populate test secret
aws ssm put-parameter \
  --name /collections/test-secret \
  --value "test-value" \
  --type SecureString

# Read it back
aws ssm get-parameter \
  --name /collections/test-secret \
  --with-decryption \
  --query 'Parameter.Value' \
  --output text

# Delete test parameter
aws ssm delete-parameter --name /collections/test-secret
```

**Expected result**: Can store and retrieve encrypted parameters

---

#### 3. Cognito User Pool Test
```bash
# Create test user
aws cognito-idp sign-up \
  --client-id <app-client-id> \
  --username testuser@example.com \
  --password TempPassword123! \
  --user-attributes Name=email,Value=testuser@example.com

# Confirm user (admin)
aws cognito-idp admin-confirm-sign-up \
  --user-pool-id <user-pool-id> \
  --username testuser@example.com

# Get JWT token
aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id <app-client-id> \
  --auth-parameters USERNAME=testuser@example.com,PASSWORD=TempPassword123!

# Decode JWT and verify 'sub' claim
echo "<id-token>" | cut -d'.' -f2 | base64 -d | jq .sub
```

**Expected result**: User created, JWT token obtained, `sub` claim present

---

#### 4. S3 Bucket Test
```bash
# Upload test file
echo "test content" > test.txt
aws s3 cp test.txt s3://<bucket-name>/test-user-id/images/test.txt

# Download it back
aws s3 cp s3://<bucket-name>/test-user-id/images/test.txt downloaded.txt
cat downloaded.txt

# Check EventBridge notifications are enabled
aws s3api get-bucket-notification-configuration --bucket <bucket-name>

# Clean up
aws s3 rm s3://<bucket-name>/test-user-id/images/test.txt
rm test.txt downloaded.txt
```

**Expected result**: Upload/download works, EventBridge config present

---

#### 5. Lambda Function Test (Hello World)

**Deploy minimal test Lambda first:**

```python
# lambdas/test/handler.py
import json

def handler(event, context):
    return {
        "statusCode": 200,
        "body": json.dumps({"message": "Hello from Lambda!"})
    }
```

```bash
# Invoke Lambda directly (via AWS CLI)
aws lambda invoke \
  --function-name collections-test-lambda \
  --payload '{}' \
  response.json

cat response.json
```

**Expected result**: Lambda returns 200 with test message

---

#### 6. Lambda + RDS Connection Test

**Test Lambda can connect to RDS:**

```python
# lambdas/test_db/handler.py
import psycopg2
import os

def handler(event, context):
    try:
        conn = psycopg2.connect(
            host=os.environ['DB_HOST'],
            database=os.environ['DB_NAME'],
            user=os.environ['DB_USER'],
            password=os.environ['DB_PASSWORD']
        )
        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        version = cursor.fetchone()
        conn.close()

        return {
            "statusCode": 200,
            "body": f"Connected! PostgreSQL version: {version[0]}"
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "body": f"Error: {str(e)}"
        }
```

**Expected result**: Lambda successfully connects to RDS

---

#### 7. Lambda + Parameter Store Test

**Test Lambda can read secrets:**

```python
# lambdas/test_secrets/handler.py
import boto3
import json

def handler(event, context):
    ssm = boto3.client('ssm')

    try:
        response = ssm.get_parameter(
            Name='/collections/test-secret',
            WithDecryption=True
        )

        return {
            "statusCode": 200,
            "body": json.dumps({"secret": response['Parameter']['Value']})
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
```

**Expected result**: Lambda can read encrypted parameters

---

#### 8. API Gateway + Lambda Test

```bash
# Test API Gateway endpoint
curl -X GET <api-gateway-url>/health

# Should return Lambda response
```

**Expected result**: API Gateway routes to Lambda correctly

---

#### 9. EventBridge + Lambda Test

**Test S3 → EventBridge → Lambda workflow:**

```python
# lambdas/test_event/handler.py
import json

def handler(event, context):
    print(f"Received event: {json.dumps(event)}")
    return {"statusCode": 200, "body": "Event received"}
```

```bash
# Upload file to S3 (should trigger EventBridge)
aws s3 cp test.txt s3://<bucket-name>/test/test.txt

# Check CloudWatch Logs for Lambda execution
aws logs tail /aws/lambda/collections-image-processor --follow
```

**Expected result**: S3 upload triggers Lambda via EventBridge

---

#### 10. End-to-End Integration Test

**Final validation before data migration:**

```bash
# 1. Get Cognito JWT token (from test #3)
TOKEN="<jwt-token>"

# 2. Call API with authentication
curl -X GET <api-gateway-url>/health \
  -H "Authorization: Bearer $TOKEN"

# 3. Test database query via API
curl -X GET <api-gateway-url>/items \
  -H "Authorization: Bearer $TOKEN"

# Expected: Empty array [] (no data yet, but connection works)
```

**Expected result**: Authenticated API call returns valid response

---

### Testing Script

Create `scripts/test_infrastructure.sh`:

```bash
#!/bin/bash
set -e

echo "🔍 Testing AWS Infrastructure..."

# Load environment variables from CDK outputs
export REGION="us-east-1"
export DB_ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name CollectionsStack \
  --query 'Stacks[0].Outputs[?OutputKey==`RDSEndpoint`].OutputValue' \
  --output text)

export API_URL=$(aws cloudformation describe-stacks \
  --stack-name CollectionsStack \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' \
  --output text)

# Run tests
echo "✅ 1. Testing RDS connection..."
psql -h $DB_ENDPOINT -U postgres -d collections -c "SELECT 1;"

echo "✅ 2. Testing Parameter Store..."
aws ssm put-parameter --name /collections/test --value "test" --type String --overwrite
aws ssm get-parameter --name /collections/test

echo "✅ 3. Testing Lambda invoke..."
aws lambda invoke --function-name collections-api-lambda --payload '{}' /tmp/response.json
cat /tmp/response.json

echo "✅ 4. Testing API Gateway..."
curl -f $API_URL/health

echo ""
echo "🎉 All infrastructure tests passed!"
```

**Run**: `chmod +x scripts/test_infrastructure.sh && ./scripts/test_infrastructure.sh`

---

### Phase 2: Database Migration

**Goal**: Migrate SQLite to PostgreSQL with simplified schema

Tasks:
1. Export SQLite data to CSV/JSON
2. Create test user in Cognito (use their `sub` as user_id for existing data)
3. Transform schema:
   - Add `user_id` columns (TEXT, no foreign key)
   - Change `raw_response` and `embedding_source` from TEXT → JSONB
   - Add indexes on `user_id` columns
4. Import data into RDS PostgreSQL
5. Test queries with manual `WHERE user_id = ?` filters
6. Test FTS search (PostgreSQL tsvector)
7. Test vector search (pgvector)

**Deliverable**: PostgreSQL with migrated data, no RLS complexity

---

### Phase 3: Code Adaptation

**Goal**: Adapt existing code for Lambda and multi-tenancy

Tasks:
1. Create `config.py` for secrets management (Parameter Store)
2. Update `database.py` for PostgreSQL connections
3. Add `middleware/auth.py` for Cognito JWT validation
   - Extract `sub` from JWT → store in `request.state.user_id`
4. Update ALL endpoints to add `WHERE user_id = ?` filters
   - GET /items → filter by user_id
   - POST /items → insert with user_id
   - Search endpoints → filter by user_id
5. Add Mangum adapter to FastAPI (ASGI → Lambda)
6. Create Dockerfile for API Lambda
7. Update search functions (FTS5 → PostgreSQL tsvector)
8. Update vector search (sqlite-vec → pgvector with user filtering)

**Deliverable**: Lambda-ready FastAPI application with manual multi-tenancy

---

### Phase 4: Lambda Functions (Week 2-3)

**Goal**: Create event-driven Lambda functions

Tasks:
1. Create Image Processor Lambda (resize, thumbnail)
2. Create Analyzer Lambda (vision AI analysis)
3. Create Embedder Lambda (vector generation)
4. Set up EventBridge event schemas
5. Test S3 → Image Processor trigger
6. Test EventBridge → Analyzer trigger
7. Test EventBridge → Embedder trigger
8. Test manual Lambda invocations from API

**Deliverable**: 4 working Lambda functions with event-driven workflow

---

### Phase 5: Storage Migration (Week 3)

**Goal**: Migrate images from local filesystem to S3

Tasks:
1. Write migration script (local → S3)
2. Organize S3 structure: `{user_id}/images/{uuid}.jpg`
3. Upload existing images with proper metadata
4. Update database `file_path` columns
5. Generate pre-signed URLs for image access
6. Update frontend to use S3 URLs
7. Delete local image files

**Deliverable**: All images in S3 with proper isolation

---

### Phase 6: Authentication (Week 3-4)

**Goal**: Implement user authentication and signup

Tasks:
1. Create Cognito User Pool (done via CDK)
2. Build signup/login UI (or use Cognito Hosted UI)
3. Integrate Cognito SDK in frontend
4. Implement JWT storage (localStorage)
5. Add Authorization header to all API requests
6. Test signup flow
7. Test login flow
8. Test multi-user data isolation

**Deliverable**: Working user authentication

---

### Phase 7: Testing & Optimization (Week 4)

**Goal**: Optimize performance and test thoroughly

Tasks:
1. Load test API endpoints
2. Optimize Lambda cold starts (container layers, SnapStart)
3. Add connection pooling for RDS
4. Implement caching (ElastiCache or in-memory)
5. Test concurrent users
6. Monitor costs and optimize
7. Set up CloudWatch alarms
8. Test golden dataset functionality

**Deliverable**: Production-ready application

---

### Phase 8: Deployment & Cutover (Week 5)

**Goal**: Launch to users

Tasks:
1. Create production environment (separate CDK stack)
2. Deploy frontend to S3 + CloudFront (optional)
3. Configure custom domain (Route 53)
4. Set up SSL certificate (ACM)
5. Final data migration
6. User onboarding documentation
7. Monitor for issues
8. Decommission local environment

**Deliverable**: Live production system

---

## Cost Optimization Strategies

### Use Free Tiers
- ✅ Lambda: 1M requests/month free
- ✅ Cognito: 50K MAU free
- ✅ Parameter Store: Unlimited standard parameters
- ✅ CloudWatch: 5GB logs free
- ✅ S3: 5GB free (first 12 months)

### Right-Size Resources
- ✅ RDS: Start with db.t4g.micro ($15/month), public access
- ✅ Lambda: 1024-2048MB memory (pay per use), no VPC (faster cold starts)
- ✅ No VPC/NAT Gateway: Saves $32/month
- ✅ No RDS Proxy: Saves $11/month

### Security Without VPC Costs
- ✅ Security Groups: Whitelist only Lambda IPs + your dev IP
- ✅ SSL/TLS: Force encrypted connections to RDS
- ✅ IAM: Least-privilege roles for Lambda functions
- ✅ Secrets: Encrypted parameters in Parameter Store

### Monitoring
- Set up billing alarms ($30/month threshold for simplified architecture)
- Enable Cost Explorer
- Review monthly costs and optimize

---

## Rollback Plan

If migration fails or issues arise:

1. **Database**: Keep SQLite backups, can restore locally
2. **Images**: Keep local copies until S3 is verified
3. **Code**: Use Git branches (main = local, cloud = AWS)
4. **Infrastructure**: `cdk destroy` removes all AWS resources
5. **Cost**: Delete RDS, Lambdas to stop charges immediately

---

## Golden Dataset Strategy

**Recommended approach**: Test user account

1. Create `test@collections.local` user in Cognito
2. Upload curated golden dataset images to that user's account
3. Run evaluations filtered by `user_id = test-user-uuid`
4. Keeps everything in single database (no dual-database complexity)
5. FREE (no extra infrastructure)

**Alternative**: Separate RDS instance for testing (~$15/month)

---

## Key Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Cloud Provider | AWS | User has AWS experience, provider-native, mature serverless |
| Compute | Lambda | Cost-effective for bursty usage, auto-scales, pay-per-use |
| Database | RDS PostgreSQL (public) | JSONB for documents, pgvector for vectors, no VPC costs |
| Multi-tenancy | Manual WHERE filters | Simpler than RLS, easier to debug, no session variables |
| Users Table | None | Use Cognito `sub` directly, no sync complexity |
| Auth | Cognito | Provider-native, free tier, JWT tokens, MFA support |
| Secrets | Parameter Store | FREE vs $1.60/month for Secrets Manager |
| IaC | AWS CDK (Python) | Python-based, type-safe, AWS-official, higher-level than CloudFormation |
| API Gateway | HTTP API | Cheaper than REST API ($1/M vs $3.50/M requests) |
| Vector Search | pgvector | Keep search in-database, simpler than separate service |
| BM25 Search | PostgreSQL FTS | Good enough, avoids Elasticsearch costs |
| Network | Public RDS | Saves $32/month (NAT Gateway), simpler architecture |

---

## Next Steps

1. ✅ Review this plan
2. ⬜ Set up AWS account (if needed)
3. ⬜ Install AWS CLI and CDK
4. ⬜ Start Phase 1: Infrastructure setup
5. ⬜ Populate Parameter Store with existing API keys
6. ⬜ Deploy CDK stack
7. ⬜ Begin database migration

---

## Questions to Address

Before starting implementation:

- [ ] AWS account ready? (with admin access)
- [ ] Domain name for API? (or use AWS-generated URL)
- [ ] Region preference? (us-east-1 recommended for cost)
- [ ] Backup strategy? (RDS automated backups enabled by default)
- [ ] CI/CD needed? (GitHub Actions → CDK deploy)
- [ ] Monitoring requirements beyond CloudWatch?

---

## References

- AWS CDK Documentation: https://docs.aws.amazon.com/cdk/
- pgvector Extension: https://github.com/pgvector/pgvector
- Cognito JWT Validation: https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html
- Mangum (ASGI adapter): https://github.com/jordaneremieff/mangum
- Lambda Container Images: https://docs.aws.amazon.com/lambda/latest/dg/images-create.html

---

**Document Version**: 2.0 (Simplified)
**Last Updated**: 2025-12-22
**Author**: Migration Planning Session

**Changelog**:
- v2.0: Simplified architecture - removed VPC, RLS, and users table
- v1.0: Initial plan with VPC and Row-Level Security
