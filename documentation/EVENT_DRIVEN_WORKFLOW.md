# Event-Driven Lambda Workflow

This document describes the event-driven architecture for processing images in the collections application using AWS Lambda, S3, and EventBridge.

## Overview

The workflow consists of three Lambda functions that process images asynchronously:

1. **Image Processor** - Triggered by S3 uploads, creates thumbnails
2. **Analyzer** - Triggered by EventBridge, runs LLM analysis
3. **Embedder** - Triggered by EventBridge, generates embeddings

## Architecture Diagram

```
S3 Upload
   |
   v
Image Processor Lambda
   |
   | (publishes ImageProcessed event)
   v
EventBridge
   |
   v
Analyzer Lambda
   |
   | (publishes AnalysisComplete event)
   v
EventBridge
   |
   v
Embedder Lambda
   |
   v
PostgreSQL (pgvector)
```

## Lambda Functions

### 1. Image Processor Lambda

**Trigger**: S3 ObjectCreated event for `.jpg`, `.jpeg`, `.png` files

**Purpose**: Create thumbnails from uploaded images

**Implementation**: `/workspaces/collections-local/lambdas/image_processor/handler.py`

**Workflow**:
1. Parse S3 event to extract bucket and key
2. Skip thumbnail files (avoid infinite loop)
3. Download image from S3
4. Create thumbnail (max 800x800) using Pillow
5. Upload thumbnail to S3 at `{user_id}/thumbnails/{filename}`
6. Publish `ImageProcessed` event to EventBridge

**Event Published**:
```json
{
  "Source": "collections.imageprocessor",
  "DetailType": "ImageProcessed",
  "Detail": {
    "item_id": "item123",
    "user_id": "user456",
    "bucket": "collections-images-dev-123456789",
    "original_key": "user456/item123.jpg",
    "thumbnail_key": "user456/thumbnails/item123.jpg"
  }
}
```

**Dependencies**:
- `boto3` - AWS SDK
- `pillow` - Image processing

**Environment Variables**:
- `BUCKET_NAME` - S3 bucket name
- `EVENT_BUS_NAME` - EventBridge bus name (default: "default")

**Error Handling**:
- Returns 500 status code on errors
- Logs errors with full stack trace
- Cleans up temporary files in all cases

### 2. Analyzer Lambda

**Trigger**: EventBridge event with DetailType `ImageProcessed`

**Purpose**: Analyze images using AI vision models

**Implementation**: `/workspaces/collections-local/lambdas/analyzer/handler.py`

**Workflow**:
1. Parse EventBridge event to extract image details
2. Initialize database connection (from Parameter Store)
3. Get API keys from Parameter Store
4. Download image from S3
5. Call `llm.analyze_image()` with image path
6. Store analysis in PostgreSQL using SQLAlchemy
7. Publish `AnalysisComplete` event to EventBridge

**Event Published**:
```json
{
  "Source": "collections.analyzer",
  "DetailType": "AnalysisComplete",
  "Detail": {
    "item_id": "item123",
    "analysis_id": "analysis789",
    "user_id": "user456"
  }
}
```

**Dependencies**:
- `boto3` - AWS SDK
- `anthropic` - Anthropic Claude API
- `openai` - OpenAI API
- `langchain-anthropic` - LangChain Anthropic integration
- `langchain-openai` - LangChain OpenAI integration
- `langsmith` - LangSmith tracing
- `sqlalchemy` - ORM
- `psycopg2-binary` - PostgreSQL driver

**Reused Code**:
- `llm.py` - LLM analysis module (copied, NO CHANGES)
- `database/` - Database models and connection (copied, NO CHANGES)

**Environment Variables**:
- `BUCKET_NAME` - S3 bucket name
- `EVENT_BUS_NAME` - EventBridge bus name
- `DATABASE_HOST` - PostgreSQL host
- `DATABASE_PORT` - PostgreSQL port (default: 5432)
- `DATABASE_NAME` - Database name (default: collections)

**Parameter Store Keys**:
- `/collections/DATABASE_URL` - PostgreSQL connection string
- `/collections/ANTHROPIC_API_KEY` - Anthropic API key
- `/collections/OPENAI_API_KEY` - OpenAI API key (optional)
- `/collections/LANGSMITH_API_KEY` - LangSmith API key (optional)

**Error Handling**:
- Returns 500 status code on errors
- Logs errors with full stack trace
- Cleans up downloaded images in all cases
- Does NOT publish AnalysisComplete event on errors

### 3. Embedder Lambda

**Trigger**: EventBridge event with DetailType `AnalysisComplete`

**Purpose**: Generate embeddings for semantic search

**Implementation**: `/workspaces/collections-local/lambdas/embedder/handler.py`

**Workflow**:
1. Parse EventBridge event to extract analysis details
2. Initialize database connection (from Parameter Store)
3. Get API keys from Parameter Store
4. Fetch analysis from PostgreSQL
5. Generate embedding document from analysis data
6. Call `embeddings.generate_embedding()` with document
7. Store embedding in PostgreSQL with pgvector

**No Event Published** - End of workflow

**Dependencies**:
- `boto3` - AWS SDK
- `voyageai` - Voyage AI embeddings API
- `sqlalchemy` - ORM
- `psycopg2-binary` - PostgreSQL driver
- `pgvector` - pgvector support for SQLAlchemy

**Reused Code**:
- `embeddings.py` - Embeddings module (copied, NO CHANGES)
- `database/` - Database models and connection (copied, NO CHANGES)

**Environment Variables**:
- `DATABASE_HOST` - PostgreSQL host
- `DATABASE_PORT` - PostgreSQL port (default: 5432)
- `DATABASE_NAME` - Database name (default: collections)
- `VOYAGE_EMBEDDING_MODEL` - Voyage AI model name (optional)

**Parameter Store Keys**:
- `/collections/DATABASE_URL` - PostgreSQL connection string
- `/collections/VOYAGE_API_KEY` - Voyage AI API key

**Error Handling**:
- Returns 500 status code on errors
- Logs errors with full stack trace
- Validates analysis exists before processing
- Validates embedding document is not empty

## Event Flow

### Success Path

1. User uploads image to S3: `s3://bucket/user123/item456.jpg`
2. S3 triggers Image Processor Lambda
3. Image Processor creates thumbnail: `s3://bucket/user123/thumbnails/item456.jpg`
4. Image Processor publishes `ImageProcessed` event
5. EventBridge triggers Analyzer Lambda
6. Analyzer downloads image, analyzes with LLM, stores in PostgreSQL
7. Analyzer publishes `AnalysisComplete` event
8. EventBridge triggers Embedder Lambda
9. Embedder fetches analysis, generates embedding, stores in pgvector
10. Workflow complete

### Error Handling

Each Lambda handles errors independently:

- **Image Processor**: Returns 500, does not publish event
- **Analyzer**: Returns 500, does not publish event, cleans up downloaded image
- **Embedder**: Returns 500, does not create embedding

Failed events are automatically retried by Lambda (default: 2 retries). After retries are exhausted, events can be sent to a Dead Letter Queue (DLQ) for manual inspection.

## Database Schema

### Items Table

- `id` - Item identifier (UUID)
- `user_id` - User identifier
- `filename` - Stored filename
- `file_path` - S3 key
- `mime_type` - Content type
- `created_at` - Creation timestamp

### Analyses Table

- `id` - Analysis identifier (UUID)
- `item_id` - Foreign key to items
- `user_id` - User identifier
- `version` - Version number (increments for re-analysis)
- `category` - Primary category
- `summary` - Brief description
- `raw_response` - JSONB with full analysis
- `provider_used` - AI provider (anthropic/openai)
- `model_used` - Model name
- `trace_id` - LangSmith trace ID
- `search_vector` - tsvector for full-text search (auto-populated)
- `created_at` - Creation timestamp

### Embeddings Table

- `id` - Embedding identifier (UUID)
- `item_id` - Foreign key to items
- `analysis_id` - Foreign key to analyses
- `user_id` - User identifier
- `vector` - pgvector(1024) for embeddings
- `embedding_model` - Model name
- `embedding_dimensions` - Vector dimensions
- `embedding_source` - JSONB with source fields
- `created_at` - Creation timestamp

## Testing

Each Lambda has comprehensive unit tests:

### Image Processor Tests

- Parse S3 events (valid/invalid)
- Extract user_id from keys
- Create thumbnails (JPEG, PNG, RGBA)
- Handler success/error cases
- Skip thumbnails to avoid loops

**Run tests**:
```bash
cd lambdas/image_processor
pytest tests/test_handler.py -v
```

**Results**: 14 tests, all passing

### Analyzer Tests

- Parse EventBridge events (valid/invalid)
- Handler success/error cases
- S3 download errors
- LLM analysis errors

**Run tests**:
```bash
cd lambdas/analyzer
pytest tests/test_handler.py -v
```

**Results**: 7 tests, all passing

### Embedder Tests

- Parse EventBridge events (valid/invalid)
- Generate embedding vectors
- Handler success/error cases
- Analysis not found
- Embedding generation errors

**Run tests**:
```bash
cd lambdas/embedder
pytest tests/test_handler.py -v
```

**Results**: 10 tests, all passing

## Deployment

The Lambdas are deployed using AWS CDK in the `ComputeStack`:

```python
# infrastructure/stacks/compute_stack.py
self._create_image_processor_lambda()
self._create_analyzer_lambda()
self._create_embedder_lambda()
self._create_eventbridge_rules()
self._create_s3_notifications()
```

### Infrastructure Resources

- **S3 Bucket**: `collections-images-{env}-{account}`
- **EventBridge Bus**: Default bus
- **RDS PostgreSQL**: Shared database with pgvector extension
- **IAM Roles**: Least-privilege roles for each Lambda
- **CloudWatch Logs**: Log groups with configurable retention

### Permissions

Each Lambda has specific IAM permissions:

**Image Processor**:
- S3: read/write to bucket
- EventBridge: put events
- CloudWatch Logs: write logs

**Analyzer**:
- S3: read from bucket
- EventBridge: put events
- SSM Parameter Store: read parameters
- Secrets Manager: read database credentials
- CloudWatch Logs: write logs

**Embedder**:
- SSM Parameter Store: read parameters
- Secrets Manager: read database credentials
- CloudWatch Logs: write logs

## Monitoring

### CloudWatch Metrics

Each Lambda emits standard metrics:
- Invocations
- Duration
- Errors
- Throttles
- Concurrent Executions

### CloudWatch Logs

Logs are structured with:
- Timestamp
- Request ID
- Log level (INFO, WARNING, ERROR)
- Message
- Stack trace (for errors)

### Alarms

Consider setting up alarms for:
- Error rate > threshold
- Duration > timeout - 10s
- Throttles > 0
- Dead letter queue messages > 0

## Cost Optimization

### Lambda Optimization

- **Memory**: Right-sized for each function
  - Image Processor: 1024 MB (image processing)
  - Analyzer: 1024 MB (LLM API calls)
  - Embedder: 512 MB (embedding API calls)

- **Timeout**: Configured based on expected duration
  - Image Processor: 60s
  - Analyzer: 300s (LLM can be slow)
  - Embedder: 60s

- **Concurrency**: Shared concurrency pool (1000 per region)

### S3 Optimization

- **Lifecycle Rules**: Delete old thumbnails after 90 days (test/prod only)
- **Versioning**: Enabled in prod, disabled in dev
- **Storage Class**: Standard (for frequent access)

### Database Optimization

- **Connection Pooling**: Reuse connections across invocations
- **Indexes**: Optimized queries with proper indexes
- **pgvector**: IVFFlat index for fast similarity search

## Security

### Data Encryption

- **S3**: Server-side encryption (SSE-S3)
- **RDS**: Encryption at rest
- **Parameter Store**: SecureString parameters
- **Lambda**: Environment variables encrypted at rest

### Network Security

- **S3**: Private bucket, block public access
- **RDS**: VPC-only access
- **Lambda**: VPC deployment (optional for enhanced security)

### IAM Security

- **Least Privilege**: Each Lambda has minimal permissions
- **No Shared Roles**: Separate roles for each function
- **Resource-Level Permissions**: Scoped to specific resources

## Troubleshooting

### Common Issues

**Image Processor not triggered**:
- Check S3 event notification configuration
- Verify file extension matches filter (.jpg, .jpeg, .png)
- Check Lambda execution role permissions

**Analyzer fails to analyze**:
- Check Parameter Store for API keys
- Verify database connection string
- Check CloudWatch Logs for LLM errors

**Embedder fails to generate embeddings**:
- Verify analysis exists in database
- Check Voyage AI API key
- Verify pgvector extension is installed

### Debugging

1. Check CloudWatch Logs for each Lambda
2. Verify EventBridge rules are enabled
3. Test each Lambda individually using test events
4. Check database for records (items, analyses, embeddings)

### Test Events

Use AWS Lambda console to test with sample events:

**Image Processor**:
```json
{
  "Records": [
    {
      "s3": {
        "bucket": {"name": "test-bucket"},
        "object": {"key": "user123/item456.jpg"}
      }
    }
  ]
}
```

**Analyzer**:
```json
{
  "detail": {
    "item_id": "item456",
    "user_id": "user123",
    "bucket": "test-bucket",
    "original_key": "user123/item456.jpg"
  }
}
```

**Embedder**:
```json
{
  "detail": {
    "item_id": "item456",
    "analysis_id": "analysis789",
    "user_id": "user123"
  }
}
```

## Future Enhancements

- **Dead Letter Queues (DLQ)**: Capture failed events for replay
- **Step Functions**: Orchestrate workflow with better error handling
- **Batch Processing**: Process multiple images in parallel
- **Lambda Layers**: Share common dependencies (database models)
- **X-Ray Tracing**: Distributed tracing across Lambdas
- **SNS Notifications**: Alert on failures
- **SQS Queues**: Decouple EventBridge from Lambdas for better resilience
