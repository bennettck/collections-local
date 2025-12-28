# Collections Documentation

Complete documentation for the Collections AI-powered image analysis and search application.

## Quick Links

### Getting Started
- **[Quick Start Guide](../QUICKSTART.md)** - Get up and running in 5 minutes
- **[Credentials](../CREDENTIALS.md)** - AWS credentials and access information

### Core Documentation
- **[Architecture](./ARCHITECTURE.md)** - System architecture and design
- **[Features](./FEATURES.md)** - Search, chat, and AI capabilities
- **[API Reference](./API.md)** - Local development API (PostgreSQL with pgvector)

### Development
- **[Evaluation](./EVALUATION.md)** - Search evaluation and metrics
- **[Golden Dataset](./GOLDEN_DATASET.md)** - Creating evaluation datasets
- **[LangSmith](./LANGSMITH.md)** - Observability and tracing

### AWS Deployment
- **[Credentials](./CREDENTIALS.md)** - AWS credentials and configuration
- **[Quick Start Guide](./QUICKSTART.md)** - Get up and running with AWS deployment
- **[AWS Secrets Manager](./AWS_SECRETS_MANAGER_MIGRATION.md)** - Secrets management setup

### Testing
- **[Postman Collections](./postman/)** - API testing with Postman

## Documentation Structure

```
documentation/
├── README.md (this file)
├── ARCHITECTURE.md ..................... System architecture
├── FEATURES.md ......................... Features guide
├── API.md .............................. Local API reference (PostgreSQL)
├── CREDENTIALS.md ...................... AWS credentials & configuration
├── QUICKSTART.md ....................... AWS deployment quick start
├── EVALUATION.md ....................... Search evaluation
├── GOLDEN_DATASET.md ................... Dataset curation
├── LANGSMITH.md ........................ LLM observability
├── AWS_SECRETS_MANAGER_MIGRATION.md .... AWS secrets setup
└── postman/
    ├── README.md ....................... Postman guide
    ├── collections-local.* ............. Local collection
    └── collections-aws.* ............... AWS collection
```

## Document Summaries

### ARCHITECTURE.md
Complete system architecture including:
- Technology stack
- AWS infrastructure
- Lambda functions
- Database schema
- Event-driven workflows
- Security model
- Scalability strategies
- Monitoring and observability

**Read this if**: You need to understand how the system works

### FEATURES.md
Feature documentation including:
- Image analysis capabilities
- Search types (BM25, Vector, Hybrid, Agentic)
- AI-powered answers
- Conversational search (chat)
- Multi-tenancy
- Event-driven processing
- Performance metrics

**Read this if**: You want to know what the system can do

### API.md (Local)
API reference for local development:
- Health endpoints
- Items CRUD
- Analysis endpoints
- Search endpoints (BM25, Vector, Hybrid, Agentic)
- Golden dataset curation
- PostgreSQL with pgvector

**Read this if**: You're developing locally

### CREDENTIALS.md + QUICKSTART.md
AWS deployment documentation:
- Authentication with Cognito
- Multi-tenant endpoints
- S3 image access
- Chat endpoints
- LangGraph conversation state (PostgreSQL checkpoints)

**Read this if**: You're using the AWS deployment

### EVALUATION.md
Search evaluation documentation:
- Test query creation
- Evaluation metrics
- Benchmark results
- Search type comparison
- Quality assessment

**Read this if**: You're evaluating search quality

### GOLDEN_DATASET.md
Dataset curation guide:
- Web-based curation tool
- Analysis comparison
- Similarity scoring
- Quality assurance
- Export format

**Read this if**: You're creating evaluation datasets

### LANGSMITH.md
LLM observability with LangSmith:
- Tracing setup
- Prompt management
- Cost tracking
- Performance monitoring
- Debugging workflows

**Read this if**: You're monitoring LLM usage

## By Use Case

### I want to...

**Get started quickly**
→ [Quick Start Guide](../QUICKSTART.md)

**Understand the system architecture**
→ [Architecture](./ARCHITECTURE.md)

**Learn about search capabilities**
→ [Features](./FEATURES.md)

**Test the API**
→ [Postman Collections](./postman/)

**Deploy to AWS**
→ [Quick Start Guide](./QUICKSTART.md) and [Credentials](./CREDENTIALS.md)

**Evaluate search quality**
→ [Evaluation](./EVALUATION.md)

**Create test datasets**
→ [Golden Dataset](./GOLDEN_DATASET.md)

**Monitor LLM costs**
→ [LangSmith](./LANGSMITH.md)

**Understand authentication**
→ [Credentials](./CREDENTIALS.md) and [Quick Start Guide](./QUICKSTART.md)

**Learn about multi-tenancy**
→ [Architecture](./ARCHITECTURE.md#multi-tenancy)

**Optimize search performance**
→ [Features](./FEATURES.md#search-comparison)

## Documentation Updates

**Last Updated**: 2025-12-28

**Recent Changes**:
- Complete PostgreSQL migration - all SQLite/ChromaDB references removed
- Updated to PostgreSQL with pgvector for vector storage
- LangGraph checkpoints now use PostgreSQL (langgraph-checkpoint-postgres)
- Updated embedding dimensions from 512 to 1024 (voyage-3.5-lite)
- Consolidated documentation structure

**Architecture**:
- Database: PostgreSQL with pgvector extension
- Vector Store: PGVector (1024-dimensional embeddings)
- Conversation State: PostgreSQL checkpoints (langgraph-checkpoint-postgres)
- Custom Retrievers: PostgresHybridRetriever, PostgresBM25Retriever, VectorOnlyRetriever

## Contributing to Documentation

When updating documentation:

1. **Architecture changes** → Update ARCHITECTURE.md
2. **New features** → Update FEATURES.md
3. **API changes** → Update API.md
4. **Search improvements** → Update FEATURES.md and EVALUATION.md
5. **AWS deployment changes** → Update QUICKSTART.md and CREDENTIALS.md

Keep documentation:
- Clear and concise
- Up-to-date with code
- Well-organized with headers
- Cross-referenced
- Example-rich

## Getting Help

- **Quick questions**: Check [Quick Start](../QUICKSTART.md)
- **Technical details**: Check [Architecture](./ARCHITECTURE.md)
- **API usage**: Check [API Reference](./API.md)
- **Search help**: Check [Features](./FEATURES.md)
- **AWS issues**: Check [Credentials](../CREDENTIALS.md)

---

**Documentation Version**: 2.0 (Consolidated)
**Last Updated**: 2025-12-27
**Status**: Current and Maintained
