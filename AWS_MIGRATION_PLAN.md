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

## Development Tooling & Automation

### Overview

Comprehensive development scripts and Makefile to streamline AWS infrastructure management, deployment, testing, and data seeding.

### Tooling Philosophy

**Design Principles**:
- ✅ Single entry point (Makefile) for all operations
- ✅ Focus on dev environment initially (can expand to staging/prod later)
- ✅ Leverage existing automation (evaluate_retrieval.py, export_db.py)
- ✅ Fast iteration (quick Lambda updates without full CDK deploy)
- ✅ Safety first (confirmations, dry-run modes, rollback support)

**User Decisions**:
- Dev environment only initially
- Local scripts only (no CI/CD)
- Scripted secrets population (from .env)
- Extend existing `evaluate_retrieval.py` for AWS

### Makefile - Primary Developer Interface

**Key Make Targets**:

```makefile
# Infrastructure Management
make infra-bootstrap       # CDK bootstrap AWS account
make infra-deploy          # Deploy CDK stack
make infra-diff            # Show infrastructure changes before deploy
make infra-destroy         # Destroy stack (with safety confirmation)

# Secrets Management
make secrets-populate      # Push secrets from .env to Parameter Store
make secrets-export        # Pull secrets from Parameter Store to local .env

# Database Operations
make db-connect            # Open psql connection to RDS
make db-migrate            # Run schema migrations
make db-seed-golden        # Seed golden dataset (55 items from existing golden DB)
make db-seed-full          # Seed full production data
make db-reset              # Drop and recreate schema (with confirmation)

# Lambda Deployment
make lambda-deploy-api     # Deploy API Lambda only (fast, 2-minute update)
make lambda-deploy-all     # Deploy all Lambda functions
make lambda-logs FUNC=api  # Tail CloudWatch logs for specific function

# Cognito User Management
make cognito-create-user   # Create single test user, save token
make cognito-get-token     # Get fresh JWT token from existing user

# S3 Image Management
make s3-upload-images      # Upload local images to S3 with user_id prefix
make s3-download-images    # Download S3 images locally

# Testing & Validation
make test-infra            # Run 10-step infrastructure validation
make test-api              # Test all API endpoints with auth
make test-e2e              # End-to-end workflow test
make test-all              # Run all tests and generate report

# Evaluation & Comparison
make eval-aws              # Run retrieval evaluation against AWS API
make eval-compare          # Compare local vs AWS evaluation metrics

# Data Migration
make migrate-db            # Migrate SQLite → PostgreSQL
make migrate-images        # Migrate local images → S3
make migrate-validate      # Verify migration data integrity

# Utilities
make status                # Show current AWS resources and their status
make clean                 # Clean local build artifacts
make help                  # Display all available commands
```

**Features**:
- Color-coded output (green=success, red=error, yellow=warning)
- Prerequisite checking (AWS CLI, CDK, psql, jq, python)
- Safety confirmations for destructive operations
- Auto-loads environment from CDK outputs

### Scripts Organization

```
scripts/
├── aws/                              # AWS-specific automation
│   ├── infra/
│   │   ├── deploy.sh                 # CDK deploy wrapper with safety checks
│   │   ├── destroy.sh                # CDK destroy with confirmation
│   │   ├── diff.sh                   # Show infrastructure changes
│   │   └── bootstrap.sh              # CDK bootstrap
│   │
│   ├── lambda/
│   │   ├── deploy-api.sh             # Deploy API Lambda only (fast)
│   │   ├── deploy-all.sh             # Deploy all Lambda functions
│   │   └── logs.sh                   # Tail CloudWatch logs
│   │
│   ├── db/
│   │   ├── connect.sh                # psql connection helper
│   │   ├── seed.sh                   # Seed test data (golden/full/schema)
│   │   └── reset.sh                  # Drop + recreate schema
│   │
│   ├── cognito/
│   │   ├── create-user.sh            # Create test user, get JWT token
│   │   └── get-token.sh              # Get fresh JWT token
│   │
│   ├── s3/
│   │   ├── upload-images.sh          # Upload local images to S3
│   │   └── download-images.sh        # Download S3 images locally
│   │
│   ├── secrets/
│   │   ├── populate.sh               # Push secrets to Parameter Store
│   │   └── export.sh                 # Pull secrets to .env
│   │
│   └── test/
│       ├── test-infrastructure.sh    # 10-step infrastructure validation
│       ├── test-api.sh               # API endpoint tests with auth
│       └── test-e2e.sh               # End-to-end workflow test
│
├── migrate/                          # Migration utilities
│   ├── sqlite-to-postgres.py         # SQLite → PostgreSQL with transformations
│   ├── images-to-s3.py               # Local filesystem → S3
│   └── validate-migration.py         # Verify data integrity post-migration
│
└── [existing scripts remain]
    ├── export_db.py                  # Keep existing
    ├── import_db.py                  # Keep existing
    ├── evaluate_retrieval.py         # Extend for AWS (see below)
    └── setup_golden_db.py            # Keep existing
```

### Key Scripts Detailed

#### 1. scripts/aws/infra/deploy.sh

**Purpose**: Safe CDK deployment with validation

```bash
#!/bin/bash
# Features:
# - Check AWS credentials
# - Show stack diff before deploy
# - Confirm deployment
# - Capture CDK outputs (RDS endpoint, API URL, bucket name)
# - Save outputs to .aws-outputs.json for other scripts

# Usage:
./scripts/aws/infra/deploy.sh

# Output example:
# ✅ AWS credentials valid
# 📋 Stack changes:
# [CDK diff output]
#
# Deploy these changes? [y/N]: y
# 🚀 Deploying stack...
# ✅ Stack deployed successfully
# 📝 Saved outputs to .aws-outputs.json
```

#### 2. scripts/aws/secrets/populate.sh

**Purpose**: Populate Parameter Store from .env

```bash
#!/bin/bash
# Features:
# - Read secrets from .env file
# - Create/update Parameter Store parameters
# - Use SecureString encryption
# - Safety: Check if parameters exist, confirm overwrite
# - Support for dry-run mode

# Secrets to populate:
# - /collections/anthropic-api-key
# - /collections/openai-api-key
# - /collections/voyage-api-key
# - /collections/langsmith-api-key
# - /collections/database-url (auto-generated by RDS)

# Usage:
./scripts/aws/secrets/populate.sh            # Interactive mode
./scripts/aws/secrets/populate.sh --dry-run  # Preview only
./scripts/aws/secrets/populate.sh --force    # Overwrite existing
```

#### 3. scripts/aws/db/seed.sh

**Purpose**: Seed RDS database with test data

```bash
#!/bin/bash
# Options:
# --schema-only   : Just create tables (empty database)
# --golden        : Seed with 55-item golden dataset
# --full          : Seed with all production data

# Workflow:
# 1. Connect to RDS (credentials from Parameter Store)
# 2. Create test user in Cognito (if needed), get 'sub'
# 3. Import data with user_id from Cognito sub
# 4. Verify counts match source

# Usage:
./scripts/aws/db/seed.sh --golden

# Output:
# 🔑 Using Cognito user: testuser@example.com (sub: 12345678-...)
# 📊 Importing 55 items from golden dataset...
# ✅ Items imported: 55/55
# ✅ Analyses imported: 55/55
# ✅ Embeddings imported: 55/55
# 🎉 Database seeded successfully!
```

#### 4. scripts/aws/cognito/create-user.sh

**Purpose**: Create test user and obtain JWT token

```bash
#!/bin/bash
# Features:
# - Create user in Cognito
# - Auto-confirm (admin operation)
# - Fetch JWT token
# - Save token to .test-user-token
# - Save user_id (sub) to .test-user-id

# Usage:
./scripts/aws/cognito/create-user.sh \
  --email testuser@example.com \
  --password Test123!

# Output:
# ✅ User created: testuser@example.com
# 👤 User ID (sub): 12345678-1234-1234-1234-123456789012
# 🔑 JWT Token: eyJraWQiOiJ...
#
# Credentials saved:
# - .test-user-token (for API requests)
# - .test-user-id (for database operations)
#
# To use in API calls:
# export TOKEN=$(cat .test-user-token)
# curl -H "Authorization: Bearer $TOKEN" $API_URL/items
```

#### 5. scripts/aws/test/test-infrastructure.sh

**Purpose**: Comprehensive 10-step infrastructure validation

```bash
#!/bin/bash
# Tests:
# 1. RDS connection (psql, create/drop test table, pgvector)
# 2. Parameter Store (create/read/delete test parameter)
# 3. Cognito (create user, get JWT, verify sub claim)
# 4. S3 (upload/download file, check EventBridge config)
# 5. Lambda invoke (basic hello world)
# 6. Lambda→RDS connection
# 7. Lambda→Parameter Store access
# 8. API Gateway routing
# 9. EventBridge→Lambda trigger (S3 upload)
# 10. End-to-end authenticated API call

# Usage:
./scripts/aws/test/test-infrastructure.sh

# Output:
# 🔍 Testing AWS Infrastructure...
#
# ✅ 1/10 RDS connection test passed
# ✅ 2/10 Parameter Store test passed
# ✅ 3/10 Cognito JWT test passed
# ✅ 4/10 S3 operations test passed
# ✅ 5/10 Lambda invoke test passed
# ✅ 6/10 Lambda→RDS test passed
# ✅ 7/10 Lambda→Parameter Store test passed
# ✅ 8/10 API Gateway test passed
# ✅ 9/10 EventBridge workflow test passed
# ✅ 10/10 Authenticated API test passed
#
# 🎉 All infrastructure tests passed!
#
# Test report: reports/infra-test-2025-12-22-143022.md
```

#### 6. scripts/migrate/sqlite-to-postgres.py

**Purpose**: Migrate SQLite database to PostgreSQL

```python
# Workflow:
# 1. Export SQLite to JSON (use existing export_db.py)
# 2. Transform schema:
#    - Add user_id column (from Cognito test user)
#    - Convert TEXT→JSONB for raw_response, embedding_source
#    - Convert sqlite-vec embeddings to pgvector format
#    - Add user_id indexes
# 3. Import to PostgreSQL
# 4. Validate counts match

# Usage:
python scripts/migrate/sqlite-to-postgres.py \
  --sqlite-db data/collections.db \
  --postgres-url $DATABASE_URL \
  --cognito-user-id $(cat .test-user-id) \
  --dataset golden  # or 'full'

# Output:
# 📊 Exporting SQLite database...
# ✅ Exported 55 items, 55 analyses, 55 embeddings
#
# 🔄 Transforming schema...
# ✅ Added user_id columns
# ✅ Converted TEXT→JSONB
# ✅ Converted embeddings to pgvector format
#
# 📤 Importing to PostgreSQL...
# ✅ Items: 55/55
# ✅ Analyses: 55/55
# ✅ Embeddings: 55/55
#
# ✅ Migration validation passed
# 🎉 Migration complete!
```

#### 7. scripts/migrate/images-to-s3.py

**Purpose**: Upload local images to S3 with user isolation

```python
# Workflow:
# For each image in data/images/:
#   - Upload to s3://bucket/{user_id}/images/{filename}
#   - Update database file_path column
#   - Optional: Generate thumbnail, upload to s3://.../thumbnails/

# Usage:
python scripts/migrate/images-to-s3.py \
  --images-dir data/images \
  --bucket-name $BUCKET_NAME \
  --user-id $(cat .test-user-id) \
  --generate-thumbnails  # Optional

# Output:
# 📁 Found 55 images in data/images/
#
# 📤 Uploading images...
# [1/55] ✅ uploaded: 12345678-uuid.jpg → s3://bucket/user-id/images/
# [2/55] ✅ uploaded: 87654321-uuid.png → s3://bucket/user-id/images/
# ...
# [55/55] ✅ uploaded: abcdef12-uuid.jpg → s3://bucket/user-id/images/
#
# 🖼️  Generating thumbnails...
# [55/55] ✅ thumbnail created
#
# 🗄️  Updating database file_path columns...
# ✅ Updated 55 records
#
# 🎉 Image migration complete!
```

### Extending Existing Scripts

#### Modify: scripts/evaluate_retrieval.py

**Changes to support AWS**:

```python
# 1. Add AWS API endpoint detection
if os.path.exists('.aws-outputs.json'):
    with open('.aws-outputs.json') as f:
        outputs = json.load(f)
        api_url = outputs.get('ApiUrl')
        if api_url:
            api_candidates.append(api_url)
            print(f"🔍 Found AWS API: {api_url}")

# 2. Add Cognito JWT authentication
if os.path.exists('.test-user-token'):
    with open('.test-user-token') as f:
        token = f.read().strip()
        headers['Authorization'] = f'Bearer {token}'
        print(f"🔑 Using JWT authentication")

# 3. Support remote image URLs (S3 pre-signed URLs)
# No changes needed - existing code handles URLs

# Usage remains the same:
python scripts/evaluate_retrieval.py

# Auto-detects:
# - Local API (http://localhost:8000)
# - AWS API (from .aws-outputs.json)
# - Adds JWT auth automatically if .test-user-token exists
```

**New Make target for comparison**:

```bash
# make eval-compare
# Runs evaluation against both local and AWS, compares metrics
#
# Output:
# 📊 Running evaluation against local API...
# ✅ Local evaluation complete: reports/eval_local_20251222_143022.md
#
# 📊 Running evaluation against AWS API...
# ✅ AWS evaluation complete: reports/eval_aws_20251222_143145.md
#
# 📈 Comparison:
# Metric              Local    AWS      Diff
# ------------------------------------------
# Precision@10        0.82     0.81     -0.01
# Recall@10           0.75     0.74     -0.01
# MRR                 0.88     0.87     -0.01
# NDCG@10             0.85     0.84     -0.01
# Avg Response Time   120ms    245ms    +125ms
#
# ⚠️  AWS is slightly slower (Lambda cold starts)
# ✅ Retrieval quality is comparable
```

### Configuration Files

#### .aws-outputs.json (Auto-generated by deploy.sh)

```json
{
  "RdsEndpoint": "collections-dev.xxxxx.us-east-1.rds.amazonaws.com",
  "ApiUrl": "https://xxxxxxxxxx.execute-api.us-east-1.amazonaws.com",
  "CognitoUserPoolId": "us-east-1_XXXXXXXXX",
  "CognitoClientId": "xxxxxxxxxxxxxxxxxxxxxxxxxx",
  "BucketName": "collections-dev-images-xxxxx",
  "DatabaseUrl": "postgresql://user:pass@host:5432/collections"
}
```

#### .gitignore additions

```gitignore
# AWS outputs and credentials
.aws-outputs.json
.test-user-token
.test-user-id

# CDK
infrastructure/cdk.out/
infrastructure/.cdk.staging/

# Environment configs with secrets
config/.env.aws
```

### Typical Development Workflows

#### Initial Setup (First Time)

```bash
# 1. Deploy infrastructure
make infra-deploy

# 2. Populate secrets from .env
make secrets-populate

# 3. Seed golden dataset
make db-seed-golden

# 4. Create test user
make cognito-create-user

# 5. Migrate images to S3
make migrate-images

# 6. Test everything
make test-all

# 7. Run evaluation
make eval-aws
```

**Time**: ~15-20 minutes for complete setup

#### Daily Development (Code Changes)

```bash
# 1. Make changes to Lambda code
vim app/main.py

# 2. Quick deploy (just Lambda, no CDK)
make lambda-deploy-api

# 3. Test API
make test-api

# 4. Check logs if needed
make lambda-logs FUNC=api

# 5. Run evaluation
make eval-aws
```

**Time**: ~2-3 minutes for code update and test

#### Testing After Infrastructure Changes

```bash
# 1. See what changed
make infra-diff

# 2. Deploy changes
make infra-deploy

# 3. Validate infrastructure
make test-infra

# 4. Test API
make test-api
```

**Time**: ~5-10 minutes

#### Comparing Local vs AWS

```bash
# Run evaluation on both and compare metrics
make eval-compare

# Shows side-by-side comparison of:
# - Retrieval quality metrics (Precision, Recall, MRR, NDCG)
# - Response times
# - Any differences in search results
```

#### Clean Slate Reset

```bash
# 1. Destroy all AWS resources
make infra-destroy

# 2. Clean local artifacts
make clean

# 3. Start fresh
make infra-deploy
make db-seed-golden
```

### Success Metrics

Good tooling enables:
1. ✅ Deploy full stack in < 10 minutes
2. ✅ Deploy Lambda code update in < 2 minutes
3. ✅ Seed test data in < 5 minutes
4. ✅ Run full test suite in < 3 minutes
5. ✅ Zero manual AWS Console clicks for common tasks
6. ✅ Easy comparison between local and AWS performance

### Files to Create

**Priority 1 - Essential** (Week 1):
1. `Makefile` - Primary developer interface
2. `scripts/aws/infra/deploy.sh` - CDK deployment wrapper
3. `scripts/aws/secrets/populate.sh` - Secrets management
4. `scripts/aws/db/seed.sh` - Database seeding
5. `scripts/aws/cognito/create-user.sh` - User creation
6. `scripts/aws/test/test-infrastructure.sh` - 10-step validation

**Priority 2 - High Value** (Week 2):
7. `scripts/migrate/sqlite-to-postgres.py` - Data migration
8. `scripts/migrate/images-to-s3.py` - Image migration
9. `scripts/aws/lambda/deploy-api.sh` - Fast Lambda updates
10. `scripts/aws/test/test-api.sh` - API testing

**Priority 3 - Quality of Life** (Week 3):
11. `scripts/aws/lambda/logs.sh` - CloudWatch log tailing
12. Extend `scripts/evaluate_retrieval.py` for AWS
13. Add comparison tooling (`make eval-compare`)

**Total**: ~1500 lines of new automation code

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
