# AWS Lambda Functions

This directory contains the Lambda functions for the event-driven image processing workflow.

## Directory Structure

```
lambdas/
├── image_processor/          # S3-triggered image processing
│   ├── handler.py            # Lambda handler
│   ├── requirements.txt      # Dependencies
│   └── tests/
│       └── test_handler.py   # Unit tests
├── analyzer/                 # EventBridge-triggered LLM analysis
│   ├── handler.py            # Lambda handler
│   ├── llm.py                # LLM module (copied from root)
│   ├── database/             # Database models (copied from root)
│   ├── requirements.txt      # Dependencies
│   └── tests/
│       └── test_handler.py   # Unit tests
├── embedder/                 # EventBridge-triggered embedding generation
│   ├── handler.py            # Lambda handler
│   ├── embeddings.py         # Embeddings module (copied from root)
│   ├── database/             # Database models (copied from root)
│   ├── requirements.txt      # Dependencies
│   └── tests/
│       └── test_handler.py   # Unit tests
└── cleanup/                  # Scheduled cleanup (existing)
    ├── handler.py            # Lambda handler
    └── requirements.txt      # Dependencies
```

## Lambda Functions

### 1. Image Processor

**Purpose**: Process uploaded images and create thumbnails

**Trigger**: S3 ObjectCreated event

**Workflow**:
- Parse S3 event
- Download image from S3
- Create thumbnail (800x800 max)
- Upload thumbnail back to S3
- Publish "ImageProcessed" event to EventBridge

**Tests**: 14 passing tests

### 2. Analyzer

**Purpose**: Analyze images using AI vision models

**Trigger**: EventBridge "ImageProcessed" event

**Workflow**:
- Parse EventBridge event
- Download image from S3
- Analyze with LLM (Claude/GPT)
- Store analysis in PostgreSQL
- Publish "AnalysisComplete" event to EventBridge

**Reuses**: `llm.py`, `database/` (NO CHANGES)

**Tests**: 7 passing tests

### 3. Embedder

**Purpose**: Generate embeddings for semantic search

**Trigger**: EventBridge "AnalysisComplete" event

**Workflow**:
- Parse EventBridge event
- Fetch analysis from PostgreSQL
- Generate embedding with Voyage AI
- Store embedding in pgvector

**Reuses**: `embeddings.py`, `database/` (NO CHANGES)

**Tests**: 10 passing tests

## Running Tests

Run all tests:
```bash
# Image Processor
cd lambdas/image_processor
pytest tests/test_handler.py -v

# Analyzer
cd lambdas/analyzer
pytest tests/test_handler.py -v

# Embedder
cd lambdas/embedder
pytest tests/test_handler.py -v
```

Run all Lambda tests at once:
```bash
pytest lambdas/*/tests/test_handler.py -v
```

## Deployment

Lambdas are deployed using AWS CDK:

```bash
cd infrastructure
cdk deploy CollectionsComputeStack-dev
```

This will:
- Package each Lambda with its dependencies
- Create IAM roles with least-privilege permissions
- Set up S3 event notifications
- Configure EventBridge rules
- Deploy to AWS Lambda

## Local Development

### Install Dependencies

Each Lambda has its own `requirements.txt`:

```bash
# Image Processor
cd lambdas/image_processor
pip install -r requirements.txt

# Analyzer
cd lambdas/analyzer
pip install -r requirements.txt

# Embedder
cd lambdas/embedder
pip install -r requirements.txt
```

### Test Locally

Use the test files in `tests/` directories to test handlers locally.

## Environment Variables

Each Lambda requires specific environment variables (set by CDK):

### Common Variables

- `ENVIRONMENT` - Environment name (dev/test/prod)
- `DATABASE_HOST` - PostgreSQL host
- `DATABASE_PORT` - PostgreSQL port
- `DATABASE_NAME` - Database name
- `CHECKPOINT_TABLE_NAME` - DynamoDB table for checkpoints

### Image Processor

- `BUCKET_NAME` - S3 bucket name
- `EVENT_BUS_NAME` - EventBridge bus name

### Analyzer

- `BUCKET_NAME` - S3 bucket name
- `EVENT_BUS_NAME` - EventBridge bus name

### Embedder

- `VOYAGE_EMBEDDING_MODEL` - Embedding model name (optional)

## Parameter Store Keys

Lambdas retrieve sensitive data from AWS Systems Manager Parameter Store:

- `/collections/DATABASE_URL` - PostgreSQL connection string
- `/collections/ANTHROPIC_API_KEY` - Anthropic API key
- `/collections/OPENAI_API_KEY` - OpenAI API key
- `/collections/LANGSMITH_API_KEY` - LangSmith API key
- `/collections/VOYAGE_API_KEY` - Voyage AI API key

## Architecture

See [EVENT_DRIVEN_WORKFLOW.md](../documentation/EVENT_DRIVEN_WORKFLOW.md) for detailed architecture documentation.

## Code Reuse Strategy

The analyzer and embedder Lambdas reuse existing code:

- **llm.py**: Copied to analyzer/ (NO CHANGES)
- **embeddings.py**: Copied to embedder/ (NO CHANGES)
- **database/**: Copied to both (NO CHANGES)

This ensures consistency with the existing codebase while enabling independent Lambda deployment.

## Monitoring

Each Lambda automatically:
- Logs to CloudWatch Logs
- Emits metrics to CloudWatch Metrics
- Supports AWS X-Ray tracing (when enabled)

Key metrics to monitor:
- Invocations
- Duration
- Errors
- Throttles
- Concurrent Executions

## Error Handling

Each Lambda implements:
- Try/catch error handling
- Structured logging with stack traces
- Resource cleanup (temporary files)
- Graceful failure (returns 500 status code)
- Does NOT publish events on failure

## Success Criteria

All Lambda implementations meet the requirements:

- Image Processor: S3 → Thumbnail → EventBridge
- Analyzer: EventBridge → LLM → PostgreSQL → EventBridge
- Embedder: EventBridge → Fetch Analysis → Generate Embedding → pgvector
- All unit tests passing (31 total tests)
- Code reuse: llm.py and embeddings.py copied without changes
- PostgreSQL integration with SQLAlchemy
- EventBridge-driven workflow
