# Collections Application - Architecture

## Overview

Collections is a serverless AI-powered image analysis and search system built on AWS. It uses computer vision models to analyze images, generates semantic embeddings for search, and provides natural language query capabilities through conversational AI.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          User Layer                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │   Web App   │  │   Postman   │  │  CLI Script │            │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘            │
│         │                 │                 │                    │
│         └─────────────────┴─────────────────┘                    │
│                           │                                      │
│                    JWT Authentication                            │
└───────────────────────────┼──────────────────────────────────────┘
                            │
┌───────────────────────────┼──────────────────────────────────────┐
│                     AWS API Gateway                              │
│           HTTPS Endpoint with JWT Authorizer                     │
└───────────────────────────┬──────────────────────────────────────┘
                            │
┌───────────────────────────┼──────────────────────────────────────┐
│                      API Lambda (FastAPI)                        │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  • JWT Validation (Cognito)                              │  │
│  │  • Multi-tenancy (user_id extraction)                    │  │
│  │  • CRUD Operations                                        │  │
│  │  • Search (BM25, Vector, Hybrid, Agentic)                │  │
│  │  • Chat (LangGraph)                                       │  │
│  └──────────────────────────────────────────────────────────┘  │
└───────┬─────────────┬──────────────┬──────────────┬─────────────┘
        │             │              │              │
        v             v              v              v
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ PostgreSQL   │ │  DynamoDB    │ │  S3 Bucket   │ │   Cognito    │
│  (RDS)       │ │ (Checkpoints)│ │   (Images)   │ │ (User Pool)  │
│              │ │              │ │              │ │              │
│ • Items      │ │ • Sessions   │ │ • Original   │ │ • Users      │
│ • Analyses   │ │ • Threads    │ │ • Thumbnails │ │ • JWT Tokens │
│ • Embeddings │ │ • State      │ │              │ │              │
│              │ │              │ │              │ │              │
│ Extensions:  │ │ TTL: 4 hrs   │ │ Encrypted    │ │ MFA Ready    │
│ • pgvector   │ │              │ │              │ │              │
│ • tsvector   │ │              │ │              │ │              │
└──────────────┘ └──────────────┘ └──────┬───────┘ └──────────────┘
                                          │
                                          │ S3 Event
                                          v
                                   ┌──────────────────┐
                                   │ Image Processor  │
                                   │     Lambda       │
                                   └────────┬─────────┘
                                            │
                                     ImageProcessed
                                        Event
                                            │
                                            v
                                   ┌──────────────┐
                                   │ EventBridge  │
                                   └──────┬───────┘
                                          │
                             ┌────────────┴────────────┐
                             │                         │
                             v                         v
                      ┌─────────────┐          ┌─────────────┐
                      │  Analyzer   │          │  Embedder   │
                      │   Lambda    │          │   Lambda    │
                      └──────┬──────┘          └──────┬──────┘
                             │                         │
                             │ AnalysisComplete Event  │
                             │                         │
                             └────────────┬────────────┘
                                          │
                                          v
                                   ┌──────────────┐
                                   │ PostgreSQL   │
                                   └──────────────┘
```

## Core Components

### 1. API Gateway + Lambda (API Layer)

**Purpose**: HTTP API with JWT authentication

**Components**:
- API Gateway HTTP API (regional endpoint)
- Cognito User Pool Authorizer
- FastAPI application with Mangum adapter
- Multi-tenancy middleware

**Key Features**:
- HTTPS-only endpoints
- JWT token validation
- Rate limiting (100 req/min per user)
- CORS support
- Request/response logging

### 2. Compute Layer (Lambda Functions)

**API Lambda**: Main application server
- Runtime: Python 3.11
- Memory: 2048 MB
- Timeout: 30s
- Concurrent executions: 100 (dev)
- Deployment: Docker container

**Image Processor Lambda**: Image thumbnail creation
- Runtime: Python 3.11
- Memory: 1024 MB
- Timeout: 60s
- Trigger: S3 ObjectCreated events
- Dependencies: Pillow, boto3

**Analyzer Lambda**: AI-powered image analysis
- Runtime: Python 3.11
- Memory: 1024 MB
- Timeout: 300s (5 min)
- Trigger: EventBridge `ImageProcessed` event
- Dependencies: anthropic, langchain, sqlalchemy

**Embedder Lambda**: Semantic embedding generation
- Runtime: Python 3.11
- Memory: 512 MB
- Timeout: 60s
- Trigger: EventBridge `AnalysisComplete` event
- Dependencies: voyageai, pgvector, sqlalchemy

**Cleanup Lambda**: Session monitoring
- Runtime: Python 3.11
- Memory: 256 MB
- Timeout: 60s
- Trigger: EventBridge cron (hourly)
- Purpose: Monitor DynamoDB TTL cleanup

### 3. Data Layer

**PostgreSQL (RDS)**:
- Instance: db.t4g.micro (2 vCPU, 1 GB RAM)
- Storage: 20 GB gp2
- Multi-AZ: No (dev), Yes (prod)
- Backup: 7-day retention
- Extensions: pgvector, pg_trgm
- Connection pooling: 100 connections

**Tables**:
- `items` - Image metadata
- `analyses` - AI analysis results
- `embeddings` - Vector embeddings (512-dim)
- `users` - User profiles (future)

**Indexes**:
- `user_id` on all tables (B-tree)
- `search_vector` GIN index (analyses table)
- `vector` IVFFlat index (embeddings table)

**DynamoDB**:
- Table: `collections-checkpoints-dev`
- Billing: On-demand
- TTL: Enabled on `expires_at` (4 hours)
- GSI: `user_id-index`
- Purpose: LangGraph conversation state

**S3**:
- Bucket: `collections-images-dev-{account-id}`
- Encryption: SSE-S3
- Versioning: Disabled (dev), Enabled (prod)
- Public access: Blocked
- Structure:
  - `{user_id}/` - Original images
  - `{user_id}/thumbnails/` - Processed thumbnails

### 4. Event Processing

**EventBridge**:
- Bus: Default event bus
- Rules:
  - `ImageProcessed` → Analyzer Lambda
  - `AnalysisComplete` → Embedder Lambda
  - Cron schedule → Cleanup Lambda

**Event Flow**:
```
Upload → S3 → Image Processor → EventBridge → Analyzer → EventBridge → Embedder → PostgreSQL
```

**Event Schemas**:
```json
// ImageProcessed
{
  "Source": "collections.imageprocessor",
  "DetailType": "ImageProcessed",
  "Detail": {
    "item_id": "uuid",
    "user_id": "uuid",
    "bucket": "bucket-name",
    "original_key": "user/item.jpg",
    "thumbnail_key": "user/thumbnails/item.jpg"
  }
}

// AnalysisComplete
{
  "Source": "collections.analyzer",
  "DetailType": "AnalysisComplete",
  "Detail": {
    "item_id": "uuid",
    "analysis_id": "uuid",
    "user_id": "uuid"
  }
}
```

### 5. Authentication & Authorization

**Cognito User Pool**:
- Pool ID: `us-east-1_SGF7r9htD`
- Client ID: `1tce0ddbsbm254e9r9p4jar1em`
- Password policy: Min 8 chars, uppercase, lowercase, number, special char
- MFA: Optional (future: required)
- Token expiration: 1 hour

**JWT Structure**:
```json
{
  "sub": "user-uuid-12345",  // Used as user_id
  "email": "user@example.com",
  "email_verified": true,
  "cognito:username": "user@example.com",
  "aud": "1tce0ddbsbm254e9r9p4jar1em",
  "iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_SGF7r9htD",
  "iat": 1703001234,
  "exp": 1703004834
}
```

**Multi-Tenancy**:
- User ID: Extracted from JWT `sub` claim
- Enforcement: Middleware adds `user_id` to request context
- Queries: All include `WHERE user_id = :user_id`
- S3 Keys: Prefixed with `{user_id}/`
- DynamoDB: Thread IDs prefixed with `{user_id}#`

## Data Flow

### 1. Image Upload Flow

```
User → API Gateway → API Lambda
          ↓
    Validate JWT
          ↓
    Extract user_id
          ↓
    Generate item_id
          ↓
    Upload to S3: {user_id}/{item_id}.jpg
          ↓
    Insert to PostgreSQL items table
          ↓
    Return item metadata to user
          ↓
    S3 Event → Image Processor Lambda
          ↓
    Create thumbnail
          ↓
    Upload thumbnail: {user_id}/thumbnails/{item_id}.jpg
          ↓
    Publish ImageProcessed event
          ↓
    EventBridge → Analyzer Lambda
          ↓
    Download image from S3
          ↓
    Call Anthropic Claude API
          ↓
    Store analysis in PostgreSQL
          ↓
    Publish AnalysisComplete event
          ↓
    EventBridge → Embedder Lambda
          ↓
    Fetch analysis from PostgreSQL
          ↓
    Call Voyage AI API
          ↓
    Store embedding in PostgreSQL (pgvector)
          ↓
    Image now searchable!
```

**Timeline**: 5-15 seconds from upload to searchable

### 2. Search Flow

```
User → API Gateway → API Lambda
          ↓
    Validate JWT
          ↓
    Extract user_id
          ↓
    Parse search request (query, type, filters)
          ↓
    Execute search with user_id filter
          ↓
    BM25: PostgreSQL FTS query (tsvector)
    Vector: PostgreSQL similarity query (pgvector)
    Hybrid: Combine results with RRF
    Agentic: LangChain ReAct agent
          ↓
    Generate AI answer (optional)
          ↓
    Return results to user
```

**Latency**:
- BM25: ~2-10ms
- Vector: ~80-100ms
- Hybrid: ~110-140ms
- Agentic: ~2-4 seconds

### 3. Chat Flow

```
User → API Gateway → API Lambda
          ↓
    Validate JWT
          ↓
    Extract user_id
          ↓
    Load or create session
          ↓
    Fetch checkpoint from DynamoDB
    Key: {user_id}#{session_id}
          ↓
    Execute LangGraph workflow
          ↓
    Call search tools (if needed)
          ↓
    Generate response
          ↓
    Save checkpoint to DynamoDB
    TTL: current_time + 4 hours
          ↓
    Return response to user
```

**Latency**: ~2-5 seconds
**Session Lifetime**: 4 hours of inactivity

## Security Architecture

### Defense in Depth

**Layer 1: Network**
- HTTPS-only (TLS 1.2+)
- API Gateway regional endpoint
- S3 private buckets
- RDS security groups

**Layer 2: Authentication**
- Cognito User Pool
- JWT token validation
- Token expiration (1 hour)
- Refresh token rotation

**Layer 3: Authorization**
- Multi-tenancy enforcement
- User-scoped queries
- IAM least-privilege roles
- Resource-level permissions

**Layer 4: Data**
- Encryption at rest (S3, RDS, DynamoDB)
- Encryption in transit (TLS)
- Secure parameter storage (SSM)
- No hardcoded secrets

### IAM Roles

**API Lambda Role**:
- S3: Read/Write to bucket
- DynamoDB: Read/Write to checkpoints table
- Secrets Manager: Read database credentials
- SSM Parameter Store: Read parameters
- RDS: Connect to database
- CloudWatch Logs: Write logs

**Image Processor Role**:
- S3: Read/Write to bucket
- EventBridge: Put events
- CloudWatch Logs: Write logs

**Analyzer Role**:
- S3: Read from bucket
- EventBridge: Put events
- Secrets Manager: Read credentials
- SSM Parameter Store: Read parameters
- RDS: Connect to database
- CloudWatch Logs: Write logs

**Embedder Role**:
- Secrets Manager: Read credentials
- SSM Parameter Store: Read parameters
- RDS: Connect to database
- CloudWatch Logs: Write logs

**Cleanup Role**:
- DynamoDB: Scan checkpoints table
- CloudWatch Logs: Write logs

## Scalability

### Current Limits (Dev)

- API Gateway: 10,000 requests/second (soft limit)
- Lambda concurrent executions: 1,000 (regional)
- RDS connections: 100 (instance limit)
- DynamoDB: On-demand (unlimited)
- S3: Unlimited requests

### Scaling Strategies

**Horizontal Scaling**:
- Lambda: Auto-scales to concurrent executions limit
- API Gateway: Auto-scales
- DynamoDB: Auto-scales with on-demand
- S3: Unlimited

**Vertical Scaling**:
- RDS: Increase instance size (db.t4g.micro → db.t4g.medium)
- Lambda: Increase memory (2GB → 10GB max)

**Optimization**:
- Connection pooling for RDS
- Lambda reserved concurrency for critical functions
- CloudFront CDN for image delivery
- Read replicas for RDS (prod)
- ElastiCache for frequently accessed data

## Monitoring & Observability

### Metrics

**API Gateway**:
- Request count
- 4xx/5xx errors
- Latency (p50, p90, p99)
- Integration latency

**Lambda**:
- Invocations
- Errors
- Duration
- Throttles
- Concurrent executions
- Iterator age (for event sources)

**RDS**:
- CPU utilization
- Database connections
- Read/Write IOPS
- Storage space
- Query performance

**DynamoDB**:
- Consumed read/write units
- Throttled requests
- Table size
- TTL deleted items

### Logging

**CloudWatch Log Groups**:
- `/aws/lambda/CollectionsCompute-dev-APILambda*`
- `/aws/lambda/CollectionsCompute-dev-ImageProcessorLambda*`
- `/aws/lambda/CollectionsCompute-dev-AnalyzerLambda*`
- `/aws/lambda/CollectionsCompute-dev-EmbedderLambda*`
- `/aws/lambda/CollectionsCompute-dev-CleanupLambda*`
- `/aws/apigateway/collections-api-dev`

**Log Retention**: 7 days (dev), 30 days (prod)

**Structured Logging**:
```json
{
  "timestamp": "2025-12-27T12:00:00.000Z",
  "level": "INFO",
  "request_id": "abc-123-def",
  "user_id": "user-456",
  "function": "search",
  "duration_ms": 123,
  "message": "Search completed successfully"
}
```

### Tracing

**LangSmith**:
- LLM API calls
- Token usage
- Latency
- Error rates
- Cost tracking

**Future**: AWS X-Ray for distributed tracing

## Disaster Recovery

### Backup Strategy

**RDS**:
- Automated backups: Daily
- Retention: 7 days
- Point-in-time recovery: Yes

**S3**:
- Versioning: Enabled (prod)
- Cross-region replication: Future
- Lifecycle policies: Delete old versions after 90 days

**DynamoDB**:
- Point-in-time recovery: Enabled
- Retention: 35 days
- On-demand backups: Manual

### Recovery Procedures

**RDS Failure**:
1. Restore from latest automated backup
2. Point-in-time recovery to specific time
3. Estimated RTO: 15 minutes
4. Estimated RPO: 5 minutes

**S3 Bucket Deletion**:
1. Restore from versioning (if enabled)
2. Restore from backup (if cross-region replication enabled)
3. Estimated RTO: 1 hour
4. Estimated RPO: Near-zero

**Lambda Failure**:
1. Redeploy from Docker image
2. Estimated RTO: 5 minutes
3. No data loss

## Cost Optimization

### Current Architecture Costs

**Monthly (Dev Environment)**:
- RDS: $15-20 (db.t4g.micro)
- Lambda: $2-5 (50K invocations)
- API Gateway: $0.50 (50K requests)
- DynamoDB: $1-2 (on-demand)
- S3: $0.50 (5GB storage)
- CloudWatch: $1 (5GB logs)
- **Total**: ~$20-30/month

### Optimization Strategies

**Lambda**:
- Right-size memory for each function
- Use ARM64 (Graviton2) for 20% cost savings
- Reserved concurrency only where needed
- Keep warm with scheduled pings (if needed)

**RDS**:
- Use Reserved Instances for prod (40-60% savings)
- Aurora Serverless for variable workloads
- Stop dev instances during off-hours

**S3**:
- Lifecycle policies to Glacier for old images
- Intelligent-Tiering for automatic cost optimization
- Delete unnecessary thumbnails

**DynamoDB**:
- On-demand for dev (variable traffic)
- Provisioned for prod (predictable traffic)
- Enable auto-scaling

**Data Transfer**:
- Use CloudFront for image delivery
- Keep data in same region
- Compress responses

---

**Architecture Version**: 1.0
**Last Updated**: 2025-12-27
**Environment**: AWS (us-east-1)
**Status**: Production Ready
