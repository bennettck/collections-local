# Collections - Features Guide

## Overview

Collections provides AI-powered image analysis and natural language search with multi-turn conversational capabilities.

## Core Features

### 1. Image Analysis

**AI-Powered Analysis**:
- Automatic categorization (Travel, Food, Beauty, etc.)
- Text extraction (OCR)
- Object detection
- Theme and emotion recognition
- Summary generation
- Metadata extraction (social media posts)

**Providers**:
- Anthropic Claude Sonnet 4.5 (default)
- OpenAI GPT-4o (alternative)

**Process**:
```
Upload Image → S3 Storage → Image Processor → AI Analysis → Database Storage → Search Index
```

**Timeline**: 5-15 seconds from upload to searchable

### 2. Search Capabilities

#### BM25 Full-Text Search
**Best for**: Exact keyword matching, abbreviations

**How it works**:
- PostgreSQL tsvector with GIN index
- Weighted fields (summary: 3x, headline: 2x, text: 2x)
- Boolean operators support (AND, OR, NOT)
- Fast execution (~2-10ms)

**Example**:
```json
{
  "query": "Tokyo Tower restaurant",
  "search_type": "bm25-lc",
  "top_k": 5
}
```

**Use cases**:
- Finding specific locations
- Matching exact brand names
- OCR text search
- Hashtag search

#### Vector Semantic Search
**Best for**: Conceptual queries, synonyms, related topics

**How it works**:
- Voyage AI embeddings (voyage-3.5-lite, 512 dimensions)
- pgvector with IVFFlat index
- Cosine similarity scoring
- Execution time (~80-100ms)

**Example**:
```json
{
  "query": "Japanese beauty products perfume",
  "search_type": "vector-lc",
  "min_similarity_score": 0.6
}
```

**Use cases**:
- "Show me luxury items" (finds high-end products)
- "Cozy cafes" (finds warm, intimate settings)
- "Japanese culture" (finds travel, food, traditions)
- Multilingual queries (semantic understanding)

#### Hybrid Search (Recommended)
**Best for**: Production use, general queries

**How it works**:
- Combines BM25 + Vector search
- Reciprocal Rank Fusion (RRF) algorithm
- Weighted: 30% BM25, 70% Vector
- RRF constant c=15
- Execution time (~110-140ms)

**Example**:
```json
{
  "query": "authentic local food experiences Tokyo",
  "search_type": "hybrid-lc",
  "top_k": 10
}
```

**Benefits**:
- Best overall precision and recall
- Handles both exact and conceptual queries
- Optimized weights for this dataset
- ~88% Recall@5

#### Agentic Search
**Best for**: Complex, multi-part queries

**How it works**:
- LangChain ReAct agent with Claude Sonnet 4.5
- Iterative query refinement
- Can call hybrid search multiple times
- Explains reasoning process
- Execution time (~2-4 seconds, max 3 iterations)

**Example**:
```json
{
  "query": "Find affordable Japanese perfumes and compare with luxury brands",
  "search_type": "agentic",
  "top_k": 10
}
```

**Use cases**:
- Complex multi-faceted queries
- Comparative searches
- Ambiguous queries needing clarification
- Queries requiring context understanding

**Agent capabilities**:
- Query decomposition
- Iterative refinement
- Context-aware adjustments
- Explains search strategy

**Optimizations**:
- Eager first search (runs immediately)
- Reduced verbosity prompts
- Batch database queries
- Semantic guidance in prompts
- Maximum 3 iterations (prevents runaway)

**Performance improvements**:
- 65-75% faster than initial implementation
- Average 2-4 seconds (down from 8-12 seconds)

### 3. AI-Powered Answers

**Feature**: Generate natural language answers from search results

**How it works**:
- Retrieves top-k relevant items
- Constructs context from metadata
- Calls LLM (default: Claude Sonnet 4.5)
- Returns answer with citations

**Example Response**:
```json
{
  "answer": "Based on your collection, you have 5 items about Tokyo, including...",
  "answer_confidence": 0.85,
  "citations": ["1", "2", "3"],
  "retrieval_time_ms": 125.3,
  "answer_time_ms": 3241.7
}
```

**Features**:
- Citation numbers reference specific items
- Confidence score (0-1)
- Handles "no results" gracefully
- Supports follow-up questions in chat mode

### 4. Conversational Search (Chat)

**Technology**: LangGraph with DynamoDB checkpointing

**Features**:
- Multi-turn conversations
- Context awareness (remembers previous exchanges)
- Session persistence (4-hour TTL)
- User isolation (separate sessions per user)

**Architecture**:
```
User Message → API Lambda → LangGraph Agent
     ↓
Load Session State from DynamoDB
     ↓
Process Message (can call search tools)
     ↓
Generate Response
     ↓
Save State to DynamoDB (TTL: 4 hours)
     ↓
Return Response
```

**Example Conversation**:
```
User: "What items do I have about Tokyo?"
Bot: "You have 5 items about Tokyo, including restaurants, travel spots..."

User: "Which ones are about food?"
Bot: "3 of those are food-related: Tofuya Ukai restaurant..."

User: "Tell me more about the first one"
Bot: "Tofuya Ukai is a traditional Japanese restaurant beneath Tokyo Tower..."
```

**Session Management**:
- Session ID format: `{user_id}#{session_id}`
- Automatic TTL: 4 hours of inactivity
- Manual deletion: `DELETE /chat/sessions/{id}`
- List sessions: `GET /chat/sessions`

**Benefits**:
- Natural conversation flow
- No need to repeat context
- Can ask follow-up questions
- Understands pronouns and references

### 5. Multi-Tenancy

**User Isolation**:
- Each user's data completely separated
- User ID extracted from JWT token (`sub` claim)
- All queries filtered by `user_id`
- Cannot access other users' data

**Enforcement**:
- Middleware extracts user_id from JWT
- Database queries include `WHERE user_id = :user_id`
- S3 keys prefixed: `{user_id}/item.jpg`
- DynamoDB thread IDs: `{user_id}#{session_id}`

**Verified**:
- Cross-user access blocked
- Search results scoped to user
- Chat sessions isolated
- Image access restricted

### 6. Event-Driven Processing

**Upload Pipeline**:
1. User uploads image via API
2. Stored in S3: `{user_id}/{item_id}.jpg`
3. S3 event triggers Image Processor Lambda
4. Thumbnail created: `{user_id}/thumbnails/{item_id}.jpg`
5. `ImageProcessed` event published
6. Analyzer Lambda analyzes with AI
7. `AnalysisComplete` event published
8. Embedder Lambda generates vector
9. Stored in pgvector for search

**Benefits**:
- Asynchronous processing
- Scalable (Lambda auto-scales)
- Fault-tolerant (retries on failure)
- Decoupled components

**Timeline**:
- Image processing: 1-2 seconds
- AI analysis: 3-8 seconds
- Embedding generation: 1-3 seconds
- **Total**: 5-15 seconds to searchable

### 7. Advanced Search Features

**Category Filtering**:
```json
{
  "query": "delicious food",
  "category_filter": "Food",
  "search_type": "vector-lc"
}
```

**Similarity Thresholds**:
```json
{
  "query": "perfume",
  "search_type": "vector-lc",
  "min_similarity_score": 0.7
}
```

**Custom Answer Models**:
```json
{
  "query": "Tokyo restaurants",
  "include_answer": true,
  "answer_model": "gpt-4o"
}
```

**Search Without Answers** (faster):
```json
{
  "query": "beauty products",
  "include_answer": false
}
```

## Search Comparison

| Feature | BM25 | Vector | Hybrid | Agentic |
|---------|------|--------|--------|---------|
| **Speed** | ~5ms | ~100ms | ~130ms | ~3s |
| **Precision** | High (exact) | Medium | High | High |
| **Recall** | Medium | High | Highest | High |
| **Use Case** | Keywords | Semantic | General | Complex |
| **Cost** | Low | Medium | Medium | High |
| **Best For** | Exact terms | Concepts | Production | Multi-part |

**Recommendation**: Use **Hybrid** for most queries, **Agentic** for complex questions

## Performance Metrics

### Search Latency (p95)
- BM25: <50ms
- Vector: <150ms
- Hybrid: <200ms
- Agentic: <4000ms

### Answer Generation
- Standard search + answer: ~4-5 seconds
- Agentic search + answer: ~2-8 seconds

### End-to-End Workflow
- Upload to searchable: 5-15 seconds
- Image processing: 1-2 seconds
- AI analysis: 3-8 seconds
- Embedding: 1-3 seconds

## Feature Availability

| Feature | Local Dev | AWS Deployment |
|---------|-----------|----------------|
| Image Upload | ✅ | ✅ |
| AI Analysis | ✅ | ✅ (Event-driven) |
| BM25 Search | ✅ | ✅ |
| Vector Search | ✅ (SQLite-vec) | ✅ (pgvector) |
| Hybrid Search | ✅ | ✅ |
| Agentic Search | ✅ | ✅ |
| Chat (LangGraph) | ✅ (SQLite) | ✅ (DynamoDB) |
| Multi-Tenancy | ❌ | ✅ |
| Authentication | ❌ | ✅ (Cognito) |
| Event Processing | ❌ | ✅ |
| Golden Dataset | ✅ | ❌ |
| Database Routing | ✅ | ❌ |

---

**Last Updated**: 2025-12-27
**Version**: 1.0
**Environment**: AWS Production
