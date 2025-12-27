# AWS Migration Implementation Plan
## Collections-Local Image Analysis Application

**Document Version**: 1.0
**Created**: December 27, 2024
**Timeline**: 7-14 days (urgent)
**Budget**: $25-50/month

---

## Executive Summary

This is a standalone implementation guide for migrating the collections-local application from local development to AWS cloud infrastructure. This document provides enough detail that a different Claude Code instance (or developer) can execute the migration without access to the original planning conversation.

**Key Migration Goals:**
1. Maintain all current functionality (image analysis, search, chat)
2. Add multi-tenant user authentication (AWS Cognito)
3. Migrate from SQLite → PostgreSQL (RDS)
4. Migrate from ChromaDB → pgvector
5. Migrate from SQLite checkpoints → DynamoDB checkpoints
6. Deploy on serverless AWS infrastructure (Lambda, API Gateway, S3)
7. Stay within $25-50/month budget

**Critical Success Factors:**
- DynamoDB for conversation checkpoints (not PostgreSQL)
- pgvector for vector search (not Pinecone or OpenSearch)
- No VPC (public RDS for cost savings)
- Manual multi-tenancy (explicit WHERE clauses, no RLS)

---

## Part 1: Context and Background

### Project Overview

**Application Name**: Collections-Local
**Purpose**: AI-powered image collection management and analysis system
**Current State**: Local development (FastAPI + SQLite + ChromaDB)
**Target State**: AWS serverless production (Lambda + RDS + DynamoDB + S3)

**Core Features:**
1. **Image Upload & Storage**: Users upload images for AI analysis
2. **Vision AI Analysis**: Claude Sonnet/GPT-4o analyze image content
3. **Vector Embeddings**: VoyageAI generates semantic embeddings
4. **Search**: BM25, vector, hybrid (RRF fusion), and agentic search
5. **Multi-Turn Chat**: LangGraph-powered conversational agent with memory
6. **Web Search**: Tavily integration for external knowledge

### Current Technology Stack

| Component | Technology | Details |
|-----------|-----------|---------|
| **API Framework** | FastAPI 0.109+ | Async ASGI web framework |
| **Database** | SQLite 3 | 2 databases: collections.db, collections_golden.db |
| **Conversation State** | SQLite (conversations.db) | LangGraph SqliteSaver checkpoints |
| **Vector Store** | ChromaDB 0.4+ | File-based persistence (data/chroma_*/) |
| **Embeddings** | VoyageAI (voyage-3.5-lite) | 1024-dimensional vectors |
| **Image Storage** | Local filesystem | data/images/ directory |
| **LLM Providers** | Anthropic (Claude Sonnet 4.5), OpenAI (GPT-4o) | Vision analysis |
| **Search** | SQLite FTS5 (BM25), ChromaDB (vector), hybrid (RRF) | Multiple search modes |
| **Agent Framework** | LangGraph 0.2+ | ReAct agent with tools |
| **Tracing** | LangSmith | Observability and evaluation |

**Key Files:**
- `main.py` (1,302 lines) - FastAPI application with all endpoints
- `database.py` (664 lines) - SQLite database operations
- `llm.py` (253 lines) - AI analysis with LangSmith tracing
- `embeddings.py` (211 lines) - VoyageAI embedding generation
- `retrieval/chroma_manager.py` (399 lines) - ChromaDB vector store
- `retrieval/langchain_retrievers.py` (240 lines) - LangChain retrievers
- `retrieval/agentic_search.py` (319 lines) - Single-turn agentic search
- `chat/agentic_chat.py` (392 lines) - Multi-turn conversational chat
- `chat/conversation_manager.py` (314 lines) - SQLite checkpoint management

### Migration Goals and Constraints

**Goals:**
1. ✅ Multi-tenancy with user authentication
2. ✅ Scalable serverless architecture
3. ✅ Production-ready reliability
4. ✅ Cost-optimized ($25-50/month)
5. ✅ Maintain search quality
6. ✅ Preserve conversation state
7. ✅ Fast deployment (1-2 weeks)

**Constraints:**
1. ⚠️ Budget: $25-50/month maximum
2. ⚠️ Timeline: 7-14 days (urgent)
3. ⚠️ No VPC (cost savings)
4. ⚠️ Simplified multi-tenancy (no RLS)
5. ⚠️ Minimal code changes preferred

**User Requirements (Confirmed):**
- **Checkpoint Storage**: DynamoDB (not PostgreSQL)
- **Vector Search**: pgvector in RDS (not Pinecone/OpenSearch)
- **Timeline**: Urgent (1-2 weeks)
- **Budget**: Minimal ($25-50/month)

---

## Part 2: Current vs Target Architecture

### Side-by-Side Comparison

| Aspect | Current (Local) | Target (AWS) |
|--------|----------------|--------------|
| **API Server** | Uvicorn (localhost:8000) | Lambda + API Gateway (HTTP API) |
| **Database** | SQLite (collections.db) | RDS PostgreSQL (db.t4g.micro, public) |
| **Conversation State** | SQLite (conversations.db) | DynamoDB (on-demand pricing) |
| **Vector Store** | ChromaDB (file-based) | pgvector extension in PostgreSQL |
| **BM25 Search** | SQLite FTS5 | PostgreSQL tsvector + GIN index |
| **Image Storage** | Local filesystem (data/images/) | S3 bucket (per-user prefixes) |
| **Authentication** | None | AWS Cognito (JWT tokens) |
| **Secrets** | .env file | Parameter Store (SecureString) |
| **Deployment** | Manual (`uvicorn main:app`) | AWS CDK (Infrastructure as Code) |
| **Scaling** | Single process | Auto-scaling (Lambda, DynamoDB) |
| **Cost** | $0 (local dev) | $29-52/month (production) |

### Technology Mapping

#### Database Layer

```
SQLite → PostgreSQL RDS

collections.db               →  PostgreSQL Database
├─ items table              →  items (+ user_id column)
├─ analyses table           →  analyses (+ user_id, JSONB for raw_response)
├─ embeddings table         →  embeddings (+ user_id, vector(1024) type)
└─ items_fts (FTS5)         →  analyses.search_vector (tsvector + GIN index)

conversations.db             →  DynamoDB Table: collections-chat-checkpoints
├─ chat_sessions            →  Thread ID: {user_id}#{session_id}
├─ checkpoints (LangGraph)  →  Checkpoint data + TTL (4 hours)
└─ checkpoint_writes        →  Automatic TTL cleanup

collections_golden.db        →  Same PostgreSQL (separate user_id)
```

#### Vector Store Layer

```
ChromaDB → pgvector

data/chroma_prod/           →  PostgreSQL embeddings table
├─ chroma.sqlite3           →  (deleted, data migrated)
├─ collections_vectors      →  embeddings.embedding vector(1024)
├─ Cosine similarity        →  vector_cosine_ops (<-> operator)
└─ File persistence         →  Database persistence

Migration script: scripts/migrate/chroma_to_pgvector.py
```

#### Application Layer

```
FastAPI (Uvicorn) → FastAPI (Lambda via Mangum)

main.py                      →  Lambda handler via Mangum adapter
├─ @app.get("/items")        →  + user_id filtering
├─ @app.post("/chat")        →  + DynamoDB checkpointer
├─ @app.post("/search")      →  + pgvector retriever
└─ File uploads              →  S3 uploads (boto3)

New: middleware/auth.py      →  Cognito JWT validation
```

### Detailed File-by-File Change Summary

#### High Priority: Must Change

**1. `retrieval/chroma_manager.py` → DELETE**
- **Action**: Delete this file entirely
- **Replacement**: Create `retrieval/pgvector_manager.py`
- **Reason**: ChromaDB is incompatible with Lambda (file-based storage)
- **Lines**: 399 lines deleted, ~300 lines new file

**2. `retrieval/pgvector_manager.py` → CREATE NEW**
- **Action**: Create new file replacing ChromaVectorStoreManager
- **Key Methods**:
  - `__init__(database_url, embedding_model)`
  - `build_index(batch_size=128)` - Batch indexing
  - `add_document(item_id, raw_response, filename)` - Real-time sync
  - `similarity_search(query, k, user_id)` - Cosine similarity with user filter
- **Dependencies**: psycopg2, langchain-voyageai
- **Cosine Similarity**: Must use `<->` operator (not L2 distance)

**3. `database.py` → MODIFY (15-20% of file)**
- **Action**: Update for PostgreSQL compatibility
- **Changes**:
  - Replace `sqlite3` with `psycopg2`
  - Add `user_id` parameter to all query functions
  - Update `INSERT` syntax (SQLite → PostgreSQL)
  - Replace FTS5 queries with tsvector queries
  - Add pgvector integration for embeddings table
- **Lines Changed**: ~100-150 / 664 total

**4. `retrieval/langchain_retrievers.py` → MODIFY**
- **Action**: Update retrievers to use pgvector
- **Changes**:
  - `VectorLangChainRetriever`: Use PgVectorManager instead of ChromaVectorStoreManager
  - `BM25LangChainRetriever`: PostgreSQL tsvector queries
  - `HybridLangChainRetriever`: Same RRF logic, new backends
  - Add `user_id` parameter to all retrievers
- **Lines Changed**: ~50 / 240 total

**5. `chat/conversation_manager.py` → MODIFY**
- **Action**: Replace SqliteSaver with DynamoDB checkpointer
- **Changes**:
  - Replace `langgraph-checkpoint-sqlite` with custom DynamoDB checkpointer
  - Update `get_checkpointer()` to return DynamoDBCheckpointer
  - Update `get_thread_config()` to prefix with user_id
  - Remove manual cleanup logic (DynamoDB TTL handles it)
- **Lines Changed**: ~80 / 314 total

**6. `chat/agentic_chat.py` → MODIFY**
- **Action**: Remove ChromaDB dependency, add user_id
- **Changes**:
  - Replace `chroma_manager` with `pgvector_manager`
  - Add `user_id` parameter to `chat()` method
  - Pass `user_id` to retriever initialization
- **Lines Changed**: ~20 / 392 total

**7. `main.py` → MODIFY (3-5% of file)**
- **Action**: Add authentication, S3 storage, user_id filtering
- **Changes**:
  - Add Mangum adapter: `handler = Mangum(app)`
  - Add auth middleware: `app.middleware("http")(authenticate)`
  - Update all endpoints to add `user_id = request.state.user_id`
  - Replace file uploads with S3 (boto3.client('s3').put_object())
  - Replace file serving with pre-signed URLs
- **Lines Changed**: ~40-60 / 1,302 total

#### Medium Priority: New Files

**8. `middleware/auth.py` → CREATE NEW (~60 lines)**
- **Purpose**: Cognito JWT validation
- **Key Functions**:
  - `authenticate(request, call_next)` - Middleware function
  - JWKS fetching and caching
  - JWT decoding and validation
  - Extract `user_id` from `sub` claim
  - Set `request.state.user_id`

**9. `chat/checkpointers/dynamodb_checkpointer.py` → CREATE NEW (~150 lines)**
- **Purpose**: DynamoDB-compatible LangGraph checkpointer
- **Implements**: `BaseCheckpointSaver` interface
- **Key Methods**:
  - `put(config, checkpoint, metadata)` - Save with TTL
  - `get(config)` - Load checkpoint
  - `list(config)` - List checkpoints for thread
- **TTL**: Automatic 4-hour expiration

**10. `config/aws_config.py` → CREATE NEW (~50 lines)**
- **Purpose**: AWS-specific configuration
- **Functions**:
  - `load_secrets_from_parameter_store()` - Load API keys
  - `get_s3_client()` - S3 client singleton
  - `get_dynamodb_resource()` - DynamoDB resource singleton
- **Environment**: Detects Lambda vs local automatically

#### Low Priority: Scripts

**11. `scripts/migrate/chroma_to_pgvector.py` → CREATE NEW**
- **Purpose**: Migrate ChromaDB embeddings to pgvector
- **Steps**: Export → Transform → Batch Insert → Validate
- **Estimated Lines**: ~200

**12. `scripts/migrate/sqlite_to_postgres.py` → CREATE NEW**
- **Purpose**: Migrate SQLite data to PostgreSQL
- **Steps**: Export → Add user_id → Transform schema → Import
- **Estimated Lines**: ~250

**13. `scripts/migrate/images_to_s3.py` → CREATE NEW**
- **Purpose**: Upload local images to S3
- **Steps**: Upload → Update database paths → Generate thumbnails
- **Estimated Lines**: ~150

**14. `scripts/aws/secrets/populate.sh` → UPDATE**
- **Action**: Add TAVILY_API_KEY to secrets list
- **Lines Changed**: +5 lines

---

## Part 3: Prerequisites and Setup

### Required AWS Services

**Account Setup:**
1. AWS Account with billing configured
2. AWS CLI installed and configured (`aws configure`)
3. IAM user with AdministratorAccess (for initial setup)
4. AWS CDK CLI installed (`npm install -g aws-cdk`)

**Service Checklist:**
- [x] AWS Cognito - User authentication
- [x] RDS PostgreSQL - Application database
- [x] DynamoDB - Conversation checkpoints
- [x] S3 - Image storage
- [x] Lambda - Compute (API + workflow functions)
- [x] API Gateway (HTTP API) - API endpoint
- [x] Parameter Store (SSM) - Secrets management
- [x] EventBridge - Cron jobs and event routing
- [x] CloudWatch - Logs and monitoring
- [x] IAM - Permissions and roles

### Required Tools

**Local Development:**
```bash
# Python 3.11+
python --version  # Should be 3.11 or higher

# AWS CLI
aws --version  # aws-cli/2.x

# AWS CDK
cdk --version  # 2.x

# PostgreSQL client (for testing)
psql --version  # 14+

# jq (for JSON processing in scripts)
jq --version
```

**Python Dependencies:**
```bash
# Install requirements
pip install -r requirements.txt

# Additional AWS dependencies
pip install boto3 psycopg2-binary mangum
```

### Environment Variables

Create `.env.aws` file (DO NOT commit to Git):

```bash
# AWS Configuration
AWS_REGION=us-east-1
AWS_ACCOUNT_ID=123456789012  # Your AWS account ID

# Database (after RDS deployment)
DATABASE_URL=postgresql://user:pass@host:5432/collections

# DynamoDB (after deployment)
CHECKPOINT_TABLE_NAME=collections-chat-checkpoints

# S3 (after deployment)
BUCKET_NAME=collections-images-abc123

# Cognito (after deployment)
COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
COGNITO_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx

# Secrets (for local testing - will be in Parameter Store)
ANTHROPIC_API_KEY=sk-ant-xxx
OPENAI_API_KEY=sk-xxx
VOYAGE_API_KEY=pa-xxx
TAVILY_API_KEY=tvly-xxx  # NEW
LANGSMITH_API_KEY=lsv2_xxx

# For migration scripts
TEST_USER_ID=us-east-1:12345678-1234-1234-1234-123456789012  # Cognito sub
```

### Testing Strategy

**Phase-Based Testing:**

**Phase 1** (Infrastructure):
- ✅ RDS connection test (psql)
- ✅ DynamoDB table access
- ✅ S3 bucket upload/download
- ✅ Parameter Store read/write
- ✅ Cognito user creation and JWT token

**Phase 2** (Application):
- ✅ Lambda function invocation
- ✅ API Gateway routing
- ✅ Database queries with user_id filtering
- ✅ pgvector cosine similarity search
- ✅ DynamoDB checkpoint save/load

**Phase 3** (Integration):
- ✅ End-to-end image upload → analysis → embedding
- ✅ Multi-turn chat with state persistence
- ✅ Search accuracy validation (pgvector vs ChromaDB)
- ✅ Multi-user isolation testing

**Phase 4** (Performance):
- ✅ Cold start latency (<3 seconds)
- ✅ Search latency (<500ms)
- ✅ Chat response latency (<3 seconds)
- ✅ Cost validation ($25-50/month)

---

## Part 4: Implementation Roadmap

### 7-Day Implementation Timeline

```
Week 1: Core Migration
├─ Day 1: Vector Search (pgvector)
├─ Day 2: BM25 Search (PostgreSQL FTS)
├─ Day 3: Chat System (DynamoDB checkpointer)
├─ Day 4: Authentication (Cognito + JWT middleware)
└─ Day 5: Infrastructure Deployment (CDK)

Week 2: Data & Testing
├─ Day 6: Data Migration (ChromaDB, SQLite, Images)
└─ Day 7: Testing & Validation

Contingency: Days 8-14 for issues/optimization
```

### Daily Objectives and Deliverables

**Day 1: Vector Search Migration**
- **Objective**: Replace ChromaDB with pgvector
- **Deliverables**:
  - [x] `retrieval/pgvector_manager.py` created
  - [x] `database.py` updated for pgvector
  - [x] `retrieval/langchain_retrievers.py` updated
  - [x] Unit tests passing
- **Testing**: Cosine similarity queries work, user filtering works

**Day 2: BM25 Search Migration**
- **Objective**: Replace SQLite FTS5 with PostgreSQL tsvector
- **Deliverables**:
  - [x] `database.py` updated with tsvector queries
  - [x] `BM25LangChainRetriever` updated
  - [x] Search trigger function created
- **Testing**: BM25 search quality comparable to SQLite FTS5

**Day 3: Chat System Migration**
- **Objective**: Replace SQLite checkpoints with DynamoDB
- **Deliverables**:
  - [x] `chat/checkpointers/dynamodb_checkpointer.py` created
  - [x] `chat/conversation_manager.py` updated
  - [x] `chat/agentic_chat.py` updated
- **Testing**: Multi-turn conversations persist correctly

**Day 4: Authentication and API Updates**
- **Objective**: Add Cognito JWT authentication
- **Deliverables**:
  - [x] `middleware/auth.py` created
  - [x] `main.py` updated with auth and user_id
  - [x] S3 upload/download implemented
- **Testing**: JWT validation works, user isolation enforced

**Day 5: Infrastructure Deployment**
- **Objective**: Deploy AWS infrastructure via CDK
- **Deliverables**:
  - [x] `infrastructure/app.py` CDK stack
  - [x] RDS PostgreSQL deployed
  - [x] DynamoDB table created
  - [x] Lambda functions deployed
  - [x] API Gateway configured
- **Testing**: All infrastructure components accessible

**Day 6: Data Migration**
- **Objective**: Migrate data from local to AWS
- **Deliverables**:
  - [x] ChromaDB → pgvector migration complete
  - [x] SQLite → PostgreSQL migration complete
  - [x] Images → S3 migration complete
- **Testing**: Data counts match, sample queries match

**Day 7: Testing and Validation**
- **Objective**: Comprehensive testing
- **Deliverables**:
  - [x] All infrastructure tests passing
  - [x] API endpoint tests passing
  - [x] Performance benchmarks complete
  - [x] Cost validation complete
- **Testing**: Production-ready confirmation

### Dependencies Between Tasks

```
Critical Path:
Day 1 (pgvector) → Day 4 (API updates) → Day 5 (deployment)
                ↘                      ↗
Day 2 (BM25)    →  Day 6 (data migration) → Day 7 (testing)
                ↗
Day 3 (DynamoDB)
```

**Parallel Work Opportunities:**
- Days 1-3 can be done in parallel (3 agents)
- Day 4 can overlap with Days 1-3 (API changes independent)
- Day 6 steps can be parallelized (3 migration scripts)

---

## Part 5: Detailed Implementation Steps

### Day 1: Vector Search Migration

#### Step 1.1: Create `retrieval/pgvector_manager.py`

**Purpose**: Replace ChromaVectorStoreManager with PostgreSQL + pgvector

**Code Template**:

```python
"""
PostgreSQL + pgvector manager for vector search.
Replaces ChromaVectorStoreManager for AWS Lambda compatibility.
"""

import logging
import json
import os
from typing import List, Optional, Dict, Any
import psycopg2
from psycopg2.extras import execute_batch
from langchain_voyageai import VoyageAIEmbeddings

logger = logging.getLogger(__name__)


class PgVectorManager:
    """PostgreSQL + pgvector manager (replaces ChromaVectorStoreManager).

    Features:
    - Cosine similarity search (matches ChromaDB behavior)
    - User-based filtering for multi-tenancy
    - Batch indexing for performance
    - Real-time document updates
    """

    def __init__(
        self,
        database_url: str,
        embedding_model: str = "voyage-3.5-lite"
    ):
        """Initialize pgvector manager.

        Args:
            database_url: PostgreSQL connection string
            embedding_model: VoyageAI model name
        """
        self.database_url = database_url
        self.embedding_model = embedding_model

        # Initialize VoyageAI embeddings (same as ChromaDB)
        voyage_api_key = os.getenv("VOYAGE_API_KEY")
        if not voyage_api_key:
            raise ValueError("VOYAGE_API_KEY environment variable not set")

        self.embeddings = VoyageAIEmbeddings(
            voyage_api_key=voyage_api_key,
            model=embedding_model
        )

        logger.info(
            f"Initialized PgVectorManager with model={embedding_model}, "
            f"distance=cosine"
        )

    def _get_connection(self):
        """Get database connection."""
        return psycopg2.connect(self.database_url)

    def _create_flat_document(self, raw_response: dict) -> str:
        """Create flat document string (matches ChromaDB logic).

        Args:
            raw_response: Analysis data dictionary

        Returns:
            Concatenated string of all fields
        """
        parts = []

        # Same order as ChromaDB implementation
        parts.append(raw_response.get("summary", ""))
        parts.append(raw_response.get("headline", ""))
        parts.append(raw_response.get("category", ""))
        parts.append(" ".join(raw_response.get("subcategories", [])))

        # Image details
        image_details = raw_response.get("image_details", {})
        if isinstance(image_details.get("extracted_text"), list):
            parts.append(" ".join(image_details.get("extracted_text", [])))
        else:
            parts.append(image_details.get("extracted_text", ""))

        parts.append(image_details.get("key_interest", ""))
        parts.append(" ".join(image_details.get("themes", [])))
        parts.append(" ".join(image_details.get("objects", [])))
        parts.append(" ".join(image_details.get("emotions", [])))
        parts.append(" ".join(image_details.get("vibes", [])))

        # Media metadata
        media_metadata = raw_response.get("media_metadata", {})
        parts.append(" ".join(media_metadata.get("location_tags", [])))
        parts.append(" ".join(media_metadata.get("hashtags", [])))

        # Join all parts, filtering out empty strings
        return " ".join([p for p in parts if p and p.strip()])

    def build_index(self, user_id: str, batch_size: int = 128) -> int:
        """Build pgvector index from analyses.

        Args:
            user_id: User ID to index documents for
            batch_size: Number of documents to process at once

        Returns:
            Number of documents indexed
        """
        logger.info(f"Building pgvector index for user {user_id}")

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Fetch all items + analyses for user
            cursor.execute("""
                SELECT i.id, i.filename, a.id as analysis_id, a.raw_response
                FROM items i
                JOIN analyses a ON i.id = a.item_id
                WHERE i.user_id = %s
                  AND a.id = (
                    SELECT id FROM analyses
                    WHERE item_id = i.id
                    ORDER BY version DESC
                    LIMIT 1
                  )
            """, (user_id,))

            rows = cursor.fetchall()
            total_docs = len(rows)

            if total_docs == 0:
                logger.info("No documents to index")
                return 0

            # Process in batches
            for i in range(0, total_docs, batch_size):
                batch = rows[i:i + batch_size]

                # Create documents
                documents = []
                for row in batch:
                    item_id, filename, analysis_id, raw_response_str = row
                    raw_response = json.loads(raw_response_str)
                    content = self._create_flat_document(raw_response)
                    documents.append((item_id, analysis_id, content))

                # Generate embeddings
                texts = [doc[2] for doc in documents]
                embeddings = self.embeddings.embed_documents(texts)

                # Prepare insert data
                insert_data = []
                for (item_id, analysis_id, content), embedding in zip(documents, embeddings):
                    insert_data.append((
                        item_id,  # Use item_id as embedding id for simplicity
                        item_id,
                        user_id,
                        analysis_id,
                        embedding,  # List of floats
                        self.embedding_model,
                        len(embedding),
                        json.dumps({"source": "build_index"})
                    ))

                # Batch insert
                execute_batch(
                    cursor,
                    """
                    INSERT INTO embeddings (
                        id, item_id, user_id, analysis_id, embedding,
                        embedding_model, embedding_dimensions, embedding_source
                    ) VALUES (%s, %s, %s, %s, %s::vector, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        embedding = EXCLUDED.embedding,
                        embedding_model = EXCLUDED.embedding_model,
                        embedding_dimensions = EXCLUDED.embedding_dimensions,
                        embedding_source = EXCLUDED.embedding_source
                    """,
                    insert_data,
                    page_size=100
                )

                logger.info(f"Indexed {min(i + batch_size, total_docs)}/{total_docs} documents")

            conn.commit()
            logger.info(f"pgvector index built with {total_docs} documents")
            return total_docs

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to build index: {e}")
            raise
        finally:
            cursor.close()
            conn.close()

    def add_document(
        self,
        item_id: str,
        user_id: str,
        analysis_id: str,
        raw_response: dict,
        filename: str
    ) -> bool:
        """Add or update a single document in pgvector.

        Args:
            item_id: Item identifier
            user_id: User identifier
            analysis_id: Analysis identifier
            raw_response: Analysis data dictionary
            filename: Image filename

        Returns:
            True if successful, False otherwise
        """
        try:
            # Create flat document
            content = self._create_flat_document(raw_response)

            # Generate embedding
            embedding = self.embeddings.embed_query(content)

            # Insert/update
            conn = self._get_connection()
            cursor = conn.cursor()

            try:
                cursor.execute("""
                    INSERT INTO embeddings (
                        id, item_id, user_id, analysis_id, embedding,
                        embedding_model, embedding_dimensions, embedding_source
                    ) VALUES (%s, %s, %s, %s, %s::vector, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        embedding = EXCLUDED.embedding,
                        embedding_model = EXCLUDED.embedding_model,
                        embedding_dimensions = EXCLUDED.embedding_dimensions,
                        embedding_source = EXCLUDED.embedding_source
                """, (
                    item_id,  # Use item_id as embedding id
                    item_id,
                    user_id,
                    analysis_id,
                    embedding,
                    self.embedding_model,
                    len(embedding),
                    json.dumps({"source": "real_time_update"})
                ))

                conn.commit()
                logger.info(f"Added document to pgvector: {item_id}")
                return True

            finally:
                cursor.close()
                conn.close()

        except Exception as e:
            logger.error(f"Failed to add document to pgvector: {item_id}, error: {e}")
            return False

    def similarity_search(
        self,
        query: str,
        k: int = 10,
        user_id: Optional[str] = None,
        filter: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Execute cosine similarity search.

        Args:
            query: Search query string
            k: Number of results to return
            user_id: Filter by user ID (required for multi-tenancy)
            filter: Optional metadata filter dict (e.g., {"category": "Food"})

        Returns:
            List of result dictionaries with item_id, distance, metadata
        """
        try:
            # Generate query embedding
            query_embedding = self.embeddings.embed_query(query)

            conn = self._get_connection()
            cursor = conn.cursor()

            try:
                # Build WHERE clause
                where_clauses = []
                params = [query_embedding]

                if user_id:
                    where_clauses.append("e.user_id = %s")
                    params.append(user_id)

                if filter and "category" in filter:
                    where_clauses.append("a.category = %s")
                    params.append(filter["category"])

                where_clause = " AND ".join(where_clauses) if where_clauses else "TRUE"

                # CRITICAL: Use <-> for cosine distance (matches ChromaDB)
                query = f"""
                    SELECT
                        e.item_id,
                        e.embedding <-> %s::vector AS distance,
                        a.category,
                        a.summary,
                        i.filename
                    FROM embeddings e
                    JOIN analyses a ON e.analysis_id = a.id
                    JOIN items i ON e.item_id = i.id
                    WHERE {where_clause}
                    ORDER BY e.embedding <-> %s::vector
                    LIMIT %s
                """

                params.extend([query_embedding, k])
                cursor.execute(query, params)

                results = []
                for row in cursor.fetchall():
                    results.append({
                        "item_id": row[0],
                        "distance": float(row[1]),
                        "similarity": 1.0 - float(row[1]),  # Convert distance to similarity
                        "category": row[2],
                        "summary": row[3],
                        "filename": row[4],
                    })

                return results

            finally:
                cursor.close()
                conn.close()

        except Exception as e:
            logger.error(f"Similarity search failed: {e}")
            return []

    def get_stats(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Get vector store statistics.

        Args:
            user_id: Optional user ID to filter stats

        Returns:
            Dictionary with stats
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            try:
                where_clause = "WHERE user_id = %s" if user_id else ""
                params = [user_id] if user_id else []

                cursor.execute(f"""
                    SELECT COUNT(*), embedding_model
                    FROM embeddings
                    {where_clause}
                    GROUP BY embedding_model
                """, params)

                row = cursor.fetchone()
                if row:
                    return {
                        "document_count": row[0],
                        "embedding_model": row[1],
                        "backend": "pgvector",
                        "distance_metric": "cosine"
                    }
                else:
                    return {
                        "document_count": 0,
                        "embedding_model": self.embedding_model,
                        "backend": "pgvector",
                        "distance_metric": "cosine"
                    }

            finally:
                cursor.close()
                conn.close()

        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {"error": str(e)}
```

**Testing**:
```python
# test_pgvector_manager.py
import os
from retrieval.pgvector_manager import PgVectorManager

def test_pgvector_manager():
    # Ensure DATABASE_URL is set
    database_url = os.getenv("DATABASE_URL")
    assert database_url, "DATABASE_URL not set"

    # Initialize manager
    manager = PgVectorManager(database_url)

    # Test build_index (requires data in PostgreSQL)
    user_id = os.getenv("TEST_USER_ID")
    count = manager.build_index(user_id)
    print(f"Indexed {count} documents")

    # Test similarity search
    results = manager.similarity_search(
        "modern furniture",
        k=5,
        user_id=user_id
    )
    assert len(results) > 0, "No search results"
    assert "distance" in results[0]
    assert "similarity" in results[0]
    print(f"Search returned {len(results)} results")

    # Test stats
    stats = manager.get_stats(user_id)
    assert stats["document_count"] == count
    assert stats["distance_metric"] == "cosine"
    print(f"Stats: {stats}")

if __name__ == "__main__":
    test_pgvector_manager()
```

---

*(Due to length constraints, I'll continue the IMPLEMENTATION_PLAN.md with the remaining days in the next response)*

**File Saved**: IMPLEMENTATION_PLAN.md (Part 1 of 2)
**Status**: In Progress - Day 1 detailed, remaining days to follow
**Next**: Continue with Days 2-7 and remaining sections
