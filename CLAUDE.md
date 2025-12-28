# CLAUDE.md

## Development Philosophy
IMPORTANT: Library-first development. Use foundational libraries and their proven methods before writing custom code. If custom code is required, explain why and get user approval before proceeding.

## Foundational Libraries
- langchain
- langsmith
- langgraph
- fastapi
- uvicorn
- boto3
- sqlalchemy
- psycopg2 (PostgreSQL adapter)
- pgvector (vector similarity search)

## Workflow Rules
- Test during development AND at feature completion — tests must exercise actual code paths
- Use up to 3 sub-agents to parallelize tasks (coding, testing, documentation, etc)
- Use `./claude-temp/` for intermediate/debugging files; clean up on completion
- Update `./documentation/` upon feature completion
- Use MCP server `context7` when planning to verify current library best practices
- Plans must take a holistic view to ensure alignment with project goals and architecture

## On Completion
- Summarize any deviations from the approved plan
- Confirm documentation updated
- Confirm temp files cleaned

## Project Overview
This is the `collections-local` project - an AI-powered image analysis and semantic search system built on AWS serverless architecture.

## Architecture Stack

### Database & Storage
- **Production Database**: PostgreSQL (AWS RDS) with pgvector extension
- **Local Development**: SQLite (deprecated, for compatibility only)
- **Vector Store**: PGVector (PostgreSQL extension, replaces ChromaDB)
- **Conversation State**: DynamoDB checkpointer (current), langgraph-checkpoint-postgres (planned)
- **Image Storage**: AWS S3

### Search & Retrieval
- **BM25 Search**: PostgreSQL full-text search (tsvector/tsquery)
- **Vector Search**: PGVector with cosine similarity (IVFFlat index)
- **Hybrid Search**: RRF fusion of BM25 + Vector (30% / 70% weights)
- **Custom Retrievers**: PostgresHybridRetriever, PostgresBM25Retriever, VectorOnlyRetriever

### AI & LLM
- **Analysis**: Anthropic Claude Sonnet 4.5
- **Embeddings**: Voyage AI (voyage-3.5-lite, 512 dimensions)
- **Chat**: LangGraph with ReAct agent
- **Observability**: LangSmith tracing

## Development Practices

### Database Development
- Use PostgreSQL for production-like testing
- SQLite is deprecated (compatibility mode only)
- Custom retrievers are PostgreSQL-native (not LangChain defaults)
- Always test with user_id filtering for multi-tenancy

### Custom Code
- Custom retrievers required for PostgreSQL BM25 + PGVector integration
- LangChain's default retrievers don't support our RRF hybrid approach
- Custom DynamoDB checkpointer required until langgraph-checkpoint-postgres v1.0

### Testing Guidelines
- Test search with actual PostgreSQL backend
- Test multi-tenancy isolation
- Test event-driven pipeline (image upload → analysis → embedding)
- Use golden dataset for evaluation

## Development Commands
```bash
# Local development
uvicorn main:app --reload

# Run tests
pytest tests/

# Deploy to AWS
cd infrastructure && cdk deploy --all

# Test AWS API
python scripts/test_api_access.py --user testuser1
```
