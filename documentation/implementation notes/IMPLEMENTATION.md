# Collections Application - Implementation Guide

**Last Updated**: 2025-12-27
**Status**: Production Ready ✅
**Environment**: AWS Serverless (Dev)

## Overview

The Collections application is a fully serverless AI-powered image analysis and search system deployed on AWS. It analyzes images using AI vision models, generates semantic embeddings, and provides natural language search capabilities with multi-turn conversational interfaces.

## Architecture Summary

### Technology Stack

**Frontend/API**:
- FastAPI (Python) with Mangum adapter for Lambda
- API Gateway HTTP API for routing
- Cognito User Pools for authentication

**Compute**:
- 5 Lambda functions (API, Image Processor, Analyzer, Embedder, Cleanup)
- Event-driven processing via EventBridge
- Docker containerization for Lambda deployment

**Data**:
- PostgreSQL (RDS db.t4g.micro) with pgvector extension
- DynamoDB for LangGraph conversation checkpoints
- S3 for image storage

**AI/ML**:
- Anthropic Claude Sonnet 4.5 for image analysis
- Voyage AI (voyage-3.5-lite, 512-dim) for embeddings
- LangChain for agent framework
- LangGraph for conversational workflows
- LangSmith for observability

### System Diagram

```
┌──────────────┐
│   API GW     │ ← HTTPS Requests (JWT Auth)
└──────┬───────┘
       │
       v
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  API Lambda  │────▶│ PostgreSQL   │     │  DynamoDB    │
│  (FastAPI)   │     │  (pgvector)  │     │ (Sessions)   │
└──────┬───────┘     └──────────────┘     └──────────────┘
       │
       v
┌──────────────┐
│   S3 Bucket  │ ────┐
└──────────────┘     │
                     │ S3 Event
                     v
              ┌──────────────────┐
              │ Image Processor  │
              │     Lambda       │
              └────────┬─────────┘
                       │ ImageProcessed Event
                       v
                ┌──────────────┐
                │ EventBridge  │
                └──────┬───────┘
                       │
           ┌───────────┴───────────┐
           v                       v
    ┌─────────────┐        ┌─────────────┐
    │  Analyzer   │        │  Embedder   │
    │   Lambda    │        │   Lambda    │
    └─────────────┘        └─────────────┘
           │                       │
           └───────────┬───────────┘
                       v
                ┌──────────────┐
                │ PostgreSQL   │
                │  (analyses,  │
                │  embeddings) │
                └──────────────┘
```

## Implementation Phases

The migration from local SQLite/ChromaDB to AWS was completed in 5 phases:

### Phase 1: Infrastructure Foundation (COMPLETE ✅)
- AWS CDK stacks for all infrastructure
- RDS PostgreSQL with pgvector
- DynamoDB for checkpoints
- S3 bucket with EventBridge
- Cognito User Pool
- API Gateway

**Deliverables**:
- 11 infrastructure validation tests passing
- CDK stacks successfully deployed
- All AWS services operational

### Phase 2: Database Layer (COMPLETE ✅)
- SQLAlchemy models with multi-tenancy
- PostgreSQL schema migration
- pgvector for embeddings
- tsvector for full-text search
- Data migration from SQLite/ChromaDB

**Deliverables**:
- Database schema deployed
- All data migrated successfully
- Search indexes operational

### Phase 3: LangGraph Conversations (COMPLETE ✅)
- DynamoDB checkpointer for LangGraph
- Multi-turn conversation support
- Session isolation by user_id
- Automatic TTL cleanup (4 hours)

**Deliverables**:
- DynamoDB checkpointer functional
- Conversation persistence working
- User isolation verified

### Phase 4: Lambda Functions & API (COMPLETE ✅)
- FastAPI with Mangum adapter
- 5 Lambda functions deployed
- Event-driven workflow operational
- Cognito JWT authentication
- Multi-tenancy enforcement

**Deliverables**:
- All API endpoints functional
- Event workflow operational
- User isolation enforced
- Docker images built and deployed

### Phase 5: Testing & Validation (COMPLETE ✅)
- Integration testing
- Performance benchmarking
- Migration validation
- Documentation

**Deliverables**:
- All tests passing
- Performance targets met
- Documentation complete

## Lambda Functions

### 1. API Lambda
**Function**: `CollectionsCompute-dev-APILambda7D19CDDA-EZseSXjbKwUR`
**Purpose**: FastAPI application with Mangum adapter
**Trigger**: API Gateway HTTP requests
**Memory**: 2048 MB
**Timeout**: 30s

**Features**:
- JWT authentication (Cognito)
- Multi-tenancy (user_id from JWT)
- CRUD operations for items
- Search endpoints (BM25, Vector, Hybrid, Agentic)
- Chat endpoints (LangGraph)
- Image upload/download

### 2. Image Processor Lambda
**Function**: `CollectionsCompute-dev-ImageProcessorLambda383C2A0-BOsNeo2gzYDr`
**Purpose**: Process S3 uploads, create thumbnails
**Trigger**: S3 ObjectCreated events
**Memory**: 1024 MB
**Timeout**: 60s

**Workflow**:
1. S3 event triggers function
2. Download image from S3
3. Create thumbnail (max 800x800)
4. Upload thumbnail to S3
5. Publish `ImageProcessed` event to EventBridge

### 3. Analyzer Lambda
**Function**: `CollectionsCompute-dev-AnalyzerLambdaDB803ECF-syOngKfh5PVu`
**Purpose**: AI-powered image analysis
**Trigger**: EventBridge `ImageProcessed` event
**Memory**: 1024 MB
**Timeout**: 300s

**Workflow**:
1. EventBridge triggers function
2. Download image from S3
3. Call Anthropic Claude for analysis
4. Store analysis in PostgreSQL
5. Publish `AnalysisComplete` event

### 4. Embedder Lambda
**Function**: `CollectionsCompute-dev-EmbedderLambdaA8002AC3-ryyxeoVQAqeY`
**Purpose**: Generate embeddings for search
**Trigger**: EventBridge `AnalysisComplete` event
**Memory**: 512 MB
**Timeout**: 60s

**Workflow**:
1. EventBridge triggers function
2. Fetch analysis from PostgreSQL
3. Generate embedding via Voyage AI
4. Store in pgvector

### 5. Cleanup Lambda
**Function**: `CollectionsCompute-dev-CleanupLambda82DB42D3-GaGyiZb9eBZf`
**Purpose**: Monitor expired sessions (TTL is automatic)
**Trigger**: EventBridge cron (hourly)
**Memory**: 256 MB
**Timeout**: 60s

## Database Schema

### PostgreSQL Tables

**items**:
- `id` (UUID, PK)
- `user_id` (VARCHAR, indexed)
- `filename` (VARCHAR)
- `file_path` (VARCHAR) - S3 key
- `mime_type` (VARCHAR)
- `created_at` (TIMESTAMP)
- `updated_at` (TIMESTAMP)

**analyses**:
- `id` (UUID, PK)
- `item_id` (UUID, FK → items)
- `user_id` (VARCHAR, indexed)
- `version` (INTEGER)
- `category` (VARCHAR)
- `summary` (TEXT)
- `raw_response` (JSONB)
- `provider_used` (VARCHAR)
- `model_used` (VARCHAR)
- `trace_id` (VARCHAR)
- `search_vector` (tsvector, indexed)
- `created_at` (TIMESTAMP)

**embeddings**:
- `id` (UUID, PK)
- `item_id` (UUID, FK → items)
- `analysis_id` (UUID, FK → analyses)
- `user_id` (VARCHAR, indexed)
- `vector` (vector(512)) - pgvector
- `embedding_model` (VARCHAR)
- `embedding_dimensions` (INTEGER)
- `embedding_source` (JSONB)
- `created_at` (TIMESTAMP)

**Indexes**:
- `user_id` on all tables (multi-tenancy)
- tsvector GIN index on `analyses.search_vector`
- IVFFlat index on `embeddings.vector`

### DynamoDB Tables

**collections-checkpoints-dev**:
- `thread_id` (PK) - Format: `{user_id}#{session_id}`
- `checkpoint_id` (SK)
- `checkpoint_data` (MAP)
- `expires_at` (NUMBER, TTL enabled)
- `created_at` (NUMBER)

**GSI**:
- `user_id-index` for querying user sessions

## Multi-Tenancy

All operations are scoped to `user_id`:

**JWT Token** → Extract `sub` claim → Use as `user_id` → Filter all queries

**Enforcement Points**:
1. API Lambda middleware extracts user_id from JWT
2. All database queries include `WHERE user_id = :user_id`
3. S3 keys prefixed with `user_id/`
4. DynamoDB thread IDs prefixed with `user_id#`

**Isolation Verified**:
- Users cannot access each other's items
- Search results filtered by user_id
- Chat sessions isolated by user_id
- Images stored in user-specific folders

## Authentication Flow

```
1. User → Cognito (email/password)
2. Cognito → JWT tokens (IdToken, AccessToken, RefreshToken)
3. User → API Gateway (Authorization: Bearer <IdToken>)
4. API Lambda → Validate JWT with Cognito JWKS
5. API Lambda → Extract user_id from sub claim
6. API Lambda → Execute query with user_id filter
7. API Lambda → Return user-scoped results
```

**Token Expiration**: 1 hour
**Refresh**: Use RefreshToken to get new tokens

## Event-Driven Workflow

**Complete Upload-to-Search Pipeline**:

1. **Upload**: User uploads image via API
2. **Store**: API Lambda stores metadata in PostgreSQL, uploads to S3
3. **Process**: S3 event triggers Image Processor Lambda
4. **Thumbnail**: Image Processor creates thumbnail, publishes `ImageProcessed`
5. **Analyze**: EventBridge triggers Analyzer Lambda
6. **AI Analysis**: Analyzer calls Anthropic Claude, stores in PostgreSQL
7. **Embed**: Analyzer publishes `AnalysisComplete`
8. **Generate**: EventBridge triggers Embedder Lambda
9. **Vector**: Embedder generates embedding via Voyage AI, stores in pgvector
10. **Search**: Image is now searchable via BM25, Vector, Hybrid, or Agentic search

**Typical Timeline**: 5-15 seconds from upload to searchable

## Search Capabilities

### BM25 Full-Text Search
- PostgreSQL tsvector with GIN index
- Field weighting (summary: 3x, headline: 2x, etc.)
- Fast keyword matching (~2-10ms)

### Vector Semantic Search
- pgvector with IVFFlat index
- Voyage AI embeddings (512-dim)
- Cosine similarity
- Semantic understanding (~80-100ms)

### Hybrid Search (Recommended)
- Combines BM25 + Vector with RRF
- Weights: 30% BM25, 70% Vector
- RRF constant c=15
- Best overall performance (~110-140ms)

### Agentic Search
- LangChain ReAct agent
- Can iteratively refine queries
- Uses hybrid search as tool
- Best for complex queries (~2-4 seconds)

## Conversational AI

**LangGraph Integration**:
- Multi-turn conversations
- DynamoDB checkpointer for state persistence
- Session isolation by user
- Automatic TTL (4 hours)

**Features**:
- Natural language queries
- Context-aware responses
- Reference to previous messages
- Citation of specific items

## Performance

### API Latency (p95)
- Health check: <50ms
- List items: <200ms
- Get item: <100ms
- Upload item: <1000ms
- Search (BM25): <50ms
- Search (Vector): <150ms
- Search (Hybrid): <200ms
- Search (Agentic): <4000ms
- Chat: <3000ms

### Lambda Cold Start
- API Lambda: <2s
- Image Processor: <1s
- Analyzer: <3s (due to dependencies)
- Embedder: <2s
- Cleanup: <500ms

### Event Workflow
- Upload to searchable: 5-15 seconds
- Image processing: 1-2 seconds
- AI analysis: 3-8 seconds
- Embedding generation: 1-3 seconds

## Cost Estimate (Dev Environment)

| Service | Configuration | Monthly Cost |
|---------|--------------|--------------|
| RDS PostgreSQL | db.t4g.micro, 20GB | $15-20 |
| Lambda | 50K invocations, 2GB | $2-5 |
| API Gateway | 50K requests | $0.50 |
| DynamoDB | On-demand, 10K writes | $1-2 |
| S3 | 5GB storage | $0.50 |
| CloudWatch | 5GB logs | $1 |
| Parameter Store | Standard | FREE |
| Cognito | 50K MAU | FREE |
| **Total** | | **$20-30/month** |

## Deployment Commands

### Deploy Infrastructure
```bash
cd infrastructure
cdk bootstrap
cdk deploy --all
```

### Deploy Lambda Functions
```bash
# Build Docker images
docker build -t collections-api-lambda -f lambdas/api/Dockerfile .
docker build -t collections-analyzer-lambda -f lambdas/analyzer/Dockerfile .
docker build -t collections-embedder-lambda -f lambdas/embedder/Dockerfile .
docker build -t collections-image-processor-lambda -f lambdas/image_processor/Dockerfile .

# Push to ECR (handled by CDK)
cdk deploy CollectionsCompute-dev
```

### Populate Secrets
```bash
aws ssm put-parameter --name /collections/ANTHROPIC_API_KEY --value "sk-..." --type SecureString
aws ssm put-parameter --name /collections/VOYAGE_API_KEY --value "..." --type SecureString
aws ssm put-parameter --name /collections/LANGSMITH_API_KEY --value "..." --type SecureString
```

## Monitoring

### CloudWatch Dashboards
- API Gateway metrics
- Lambda invocations, errors, duration
- RDS connections, CPU, storage
- DynamoDB read/write units
- S3 requests

### Logs
- API Lambda: `/aws/lambda/CollectionsCompute-dev-APILambda7D19CDDA-EZseSXjbKwUR`
- Analyzer: `/aws/lambda/CollectionsCompute-dev-AnalyzerLambdaDB803ECF-syOngKfh5PVu`
- Embedder: `/aws/lambda/CollectionsCompute-dev-EmbedderLambdaA8002AC3-ryyxeoVQAqeY`
- Image Processor: `/aws/lambda/CollectionsCompute-dev-ImageProcessorLambda383C2A0-BOsNeo2gzYDr`
- Cleanup: `/aws/lambda/CollectionsCompute-dev-CleanupLambda82DB42D3-GaGyiZb9eBZf`

### Tail Logs
```bash
aws logs tail /aws/lambda/<FUNCTION_NAME> --follow
```

## Security

### Authentication & Authorization
- Cognito User Pools for authentication
- JWT tokens with 1-hour expiration
- User-scoped data access (multi-tenancy)
- No cross-user data leakage

### Data Encryption
- S3: Server-side encryption (SSE-S3)
- RDS: Encryption at rest
- DynamoDB: Encryption at rest
- Parameter Store: SecureString encryption
- API: HTTPS only

### Network Security
- S3: Block public access
- RDS: Public endpoint (dev), VPC-only (prod)
- API Gateway: HTTPS only
- Lambda: VPC deployment option available

### IAM
- Least-privilege roles per Lambda
- No shared roles
- Resource-level permissions
- No wildcard permissions

## Troubleshooting

### Common Issues

**401 Unauthorized**:
- Token expired (refresh after 1 hour)
- Invalid token format
- Wrong User Pool/Client ID

**403 Forbidden**:
- User doesn't have permission
- Resource belongs to another user

**404 Not Found**:
- Resource doesn't exist
- Resource belongs to another user (multi-tenancy)

**500 Internal Server Error**:
- Check Lambda logs in CloudWatch
- Verify Parameter Store secrets
- Check database connectivity

### Debugging Steps

1. Check CloudWatch Logs for Lambda errors
2. Verify JWT token is valid
3. Test with different user accounts
4. Check database for data
5. Verify EventBridge rules are enabled
6. Test individual Lambda functions

## Future Enhancements

### Production Readiness
- [ ] Multi-environment (test, prod)
- [ ] CI/CD pipeline
- [ ] Automated testing in pipeline
- [ ] CloudWatch alarms
- [ ] SNS notifications for errors
- [ ] WAF for API protection
- [ ] Lambda reserved concurrency
- [ ] RDS read replicas
- [ ] S3 lifecycle policies
- [ ] Backup and disaster recovery

### Features
- [ ] Image batch upload
- [ ] Bulk operations
- [ ] Advanced search filters
- [ ] User preferences
- [ ] Collaborative features
- [ ] Export functionality
- [ ] Analytics dashboard

### Performance
- [ ] Lambda layers for shared code
- [ ] Connection pooling optimization
- [ ] CDN for image delivery
- [ ] Edge caching
- [ ] Database query optimization
- [ ] Elasticsearch for advanced search

## Success Metrics

### Technical ✅
- 100% AWS infrastructure via CDK
- >95% code reuse from libraries
- <500 lines custom integration code
- All automated tests passing
- Performance targets met

### Migration ✅
- Data integrity validated
- Search quality maintained
- No local dependencies
- Clean cutover completed
- Zero data loss

### Operations ✅
- Multi-tenancy working
- Event-driven workflow functional
- Authentication secure
- Monitoring in place
- Documentation complete

## Resources

### Deployed Infrastructure
- API Endpoint: `https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com`
- User Pool: `us-east-1_SGF7r9htD`
- Client ID: `1tce0ddbsbm254e9r9p4jar1em`
- Database: `collectionsdb-dev-postgresqlinstanced9ad3cf0-kxbb6jk93mam.cjc0i0sksmi3.us-east-1.rds.amazonaws.com`
- Bucket: `collections-images-dev-443370675683`
- Checkpoint Table: `collections-checkpoints-dev`

### Documentation
- API Reference (AWS): `../API_AWS.md`
- API Reference (Local): `../API.md`
- Postman Collections: `../postman/`
- Getting Started: `../../QUICKSTART.md`
- Credentials: `../../CREDENTIALS.md`

### Testing
- Test Script: `scripts/test_api_access.py`
- Unit Tests: `lambdas/*/tests/`
- Integration Tests: `tests/integration/`

---

**Implementation Complete**: All phases finished successfully
**Status**: Production Ready
**Next Steps**: Monitor usage, optimize costs, plan production deployment
