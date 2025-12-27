# Collections - AI-Powered Image Analysis & Search

AI-powered image analysis and semantic search application with conversational interfaces, deployed on AWS serverless architecture.

## Features

- **Image Analysis**: Automatic categorization, text extraction, object detection using Anthropic Claude
- **Semantic Search**: Vector similarity search with Voyage AI embeddings
- **Hybrid Search**: Combined keyword + semantic search with RRF fusion
- **Agentic Search**: Intelligent query refinement with LangChain agents
- **Conversational AI**: Multi-turn chat with LangGraph
- **Multi-Tenancy**: User-isolated data with Cognito authentication
- **Event-Driven**: Asynchronous processing with Lambda and EventBridge

## Quick Start

### AWS Deployment (Production)

1. **Get Credentials**: See [CREDENTIALS.md](./CREDENTIALS.md)
2. **Authenticate**:
   ```bash
   python scripts/test_api_access.py --user testuser1
   ```
3. **Test API**:
   ```bash
   curl -H "Authorization: Bearer $TOKEN" \
     https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com/health
   ```

See [QUICKSTART.md](./QUICKSTART.md) for detailed setup guide.

### Local Development

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

3. **Run Server**:
   ```bash
   uvicorn main:app --reload
   ```

4. **Test**:
   ```bash
   curl http://localhost:8000/health
   ```

## Documentation

### Core Guides
- **[Quick Start](./QUICKSTART.md)** - Get started in 5 minutes
- **[Credentials](./CREDENTIALS.md)** - AWS access and test users
- **[Architecture](./documentation/ARCHITECTURE.md)** - System design and components
- **[Features](./documentation/FEATURES.md)** - Search, chat, and AI capabilities

### API Reference
- **[API (Local)](./documentation/API.md)** - Local development API
- **[API (AWS)](./documentation/API_AWS.md)** - AWS deployment API
- **[Postman Collections](./documentation/postman/)** - API testing

### Development
- **[Evaluation](./documentation/EVALUATION.md)** - Search quality metrics
- **[Golden Dataset](./documentation/GOLDEN_DATASET.md)** - Dataset curation
- **[LangSmith](./documentation/LANGSMITH.md)** - LLM observability
- **[Implementation Guide](./documentation/implementation%20notes/IMPLEMENTATION.md)** - Full implementation details

## Architecture

```
API Gateway + Cognito Auth
         ↓
   API Lambda (FastAPI)
         ↓
    ┌────┴────┐
    ↓         ↓
PostgreSQL  DynamoDB
(pgvector)  (sessions)
    ↑
    │
S3 → Image Processor → Analyzer → Embedder
    (Event-Driven Processing)
```

**Technology Stack**:
- **Compute**: AWS Lambda, FastAPI, Mangum
- **Data**: PostgreSQL (pgvector), DynamoDB, S3
- **AI**: Anthropic Claude, Voyage AI, LangChain, LangGraph
- **Auth**: Cognito User Pools (JWT)

See [ARCHITECTURE.md](./documentation/ARCHITECTURE.md) for details.

## Search Capabilities

| Type | Use Case | Speed | Best For |
|------|----------|-------|----------|
| **BM25** | Keyword search | ~5ms | Exact terms, OCR text |
| **Vector** | Semantic search | ~100ms | Concepts, synonyms |
| **Hybrid** | General search | ~130ms | Production (recommended) |
| **Agentic** | Complex queries | ~3s | Multi-part questions |

See [FEATURES.md](./documentation/FEATURES.md) for details.

## Deployment

### Environments

- **Dev**: `https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com`
- **Test**: *(not yet deployed)*
- **Prod**: *(not yet deployed)*

### Infrastructure

Deployed using AWS CDK:
- API Gateway HTTP API
- 5 Lambda functions (API, Image Processor, Analyzer, Embedder, Cleanup)
- RDS PostgreSQL (db.t4g.micro) with pgvector
- DynamoDB for conversation state
- S3 for image storage
- Cognito for authentication
- EventBridge for event routing

### Deploy

```bash
cd infrastructure
cdk bootstrap
cdk deploy --all
```

See [Implementation Guide](./documentation/implementation%20notes/IMPLEMENTATION.md) for details.

## Testing

### API Testing

**Automated**:
```bash
python scripts/test_api_access.py
```

**Postman**:
- Import `documentation/postman/collections-aws.postman_collection.json`
- Import `documentation/postman/collections-aws.postman_environment.json`
- Set `id_token` variable
- Run collection

**Manual**:
```bash
# Get token
TOKEN=$(python scripts/test_api_access.py --token-only | jq -r .IdToken)

# Test endpoint
curl -H "Authorization: Bearer $TOKEN" \
  https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com/items
```

### Test Credentials

| Email | Password |
|-------|----------|
| testuser1@example.com | Collections2025! |
| testuser2@example.com | Collections2025! |
| demo@example.com | Collections2025! |

## Project Structure

```
.
├── lambdas/             # Lambda function code
│   ├── api/            # FastAPI application
│   ├── image_processor/
│   ├── analyzer/
│   ├── embedder/
│   └── cleanup/
├── infrastructure/      # AWS CDK infrastructure
│   └── stacks/
├── documentation/       # Documentation
│   ├── ARCHITECTURE.md
│   ├── FEATURES.md
│   ├── API.md
│   └── postman/
├── scripts/            # Utility scripts
│   └── test_api_access.py
├── tests/              # Test suites
├── QUICKSTART.md       # Getting started guide
├── CREDENTIALS.md      # Access credentials
└── README.md           # This file
```

## Cost

**Dev Environment**: ~$20-30/month
- RDS PostgreSQL: $15-20
- Lambda: $2-5
- API Gateway: $0.50
- DynamoDB: $1-2
- S3: $0.50
- Other: $1

See [Architecture](./documentation/ARCHITECTURE.md#cost-optimization) for optimization strategies.

## Development Workflow

### Local Development

1. Run local server: `uvicorn main:app --reload`
2. Test with local API: `curl http://localhost:8000/health`
3. Use golden dataset for evaluation: `curl http://golden.localhost:8000/health`

### AWS Development

1. Make code changes
2. Deploy to AWS: `cdk deploy`
3. Test with AWS API: `python scripts/test_api_access.py`
4. Check logs: `aws logs tail /aws/lambda/FUNCTION_NAME --follow`

## Support

- **Documentation**: `./documentation/README.md`
- **Quick Start**: `./QUICKSTART.md`
- **Credentials**: `./CREDENTIALS.md`
- **Issues**: Check CloudWatch Logs

## License

Private project - All rights reserved

---

**Status**: Production Ready ✅
**Last Updated**: 2025-12-27
**Environment**: AWS (us-east-1)
