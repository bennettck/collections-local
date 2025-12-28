# Architectural Review: collections-local

**Review Date:** 2025-12-28
**Reviewer:** Claude Code (Opus 4.5)
**Scope:** Full codebase architecture analysis

---

## Executive Summary

This codebase has significant architectural issues stemming from an incomplete migration from local development (SQLite + ChromaDB) to AWS production (PostgreSQL + PGVector). The result is **dual implementations across multiple layers**, creating maintenance burden, confusion, and violations of the foundational library-first philosophy.

**Estimated Dead/Duplicate Code:** ~2,500+ lines

---

## Critical Issues

### 1. Dual Vector Store Implementations (ChromaDB + PGVector)

**Files involved:**
- `retrieval/chroma_manager.py` - ChromaVectorStoreManager (403 lines)
- `retrieval/pgvector_store.py` - PGVectorStoreManager (327 lines)

**Problem:** Two complete vector store implementations exist that do nearly identical work:

| Feature | ChromaDB | PGVector |
|---------|----------|----------|
| `_create_flat_document()` | Lines 226-262 | Lines 253-306 (`create_flat_document`) |
| `similarity_search()` | Lines 264-284 | Lines 140-164 |
| `similarity_search_with_score()` | Lines 286-309 | Lines 166-191 |
| `as_retriever()` | Lines 311-322 | Lines 193-204 |
| `add_document()` | Lines 183-224 | Lines 117-138 |
| `delete_collection()` | Lines 324-351 | Lines 206-222 |
| `get_collection_stats()` | Lines 353-374 | Lines 224-250 |

**Anti-pattern:** The `main.py` still uses variables named `prod_chroma_manager` and `golden_chroma_manager` (lines 85-86, 126, 146) but actually instantiates `PGVectorStoreManager`:

```python
# main.py:132-137
prod_chroma_manager = PGVectorStoreManager(
    collection_name=prod_chroma_config["collection_name"],
    embedding_model=LANGCHAIN_EMBEDDING_MODEL,
    ...
)
```

**Impact:** Confusing naming, dead code, maintenance burden.

---

### 2. Dual Database Implementations (SQLite + PostgreSQL)

**Files involved:**
- `database.py` - SQLite implementation (762 lines)
- `database_sqlalchemy.py` - PostgreSQL/SQLAlchemy implementation (609 lines)

**Both files implement identical functions:**

| Function | database.py (SQLite) | database_sqlalchemy.py (PostgreSQL) |
|----------|---------------------|-------------------------------------|
| `init_db()` | Lines 75-142 | Lines 31-39 |
| `create_item()` | Lines 235-252 | Lines 55-93 |
| `get_item()` | Lines 255-259 | Lines 96-110 |
| `list_items()` | Lines 262-279 | Lines 113-145 |
| `count_items()` | Lines 282-293 | Lines 148-169 |
| `delete_item()` | Lines 296-300 | Lines 172-187 |
| `create_analysis()` | Lines 303-333 | Lines 190-240 |
| `get_analysis()` | Lines 336-344 | Lines 243-257 |
| `get_latest_analysis()` | Lines 347-358 | Lines 260-279 |
| `get_item_analyses()` | Lines 361-373 | Lines 282-300 |
| `batch_get_items_with_analyses()` | Lines 376-471 | Lines 303-342 |
| `search_items()` | Lines 589-646 | Lines 345-410 |
| `rebuild_search_index()` | Lines 511-553 | Lines 413-430 |
| `get_search_status()` | Lines 649-673 | Lines 433-455 |
| `create_embedding()` | Lines 676-718 | Lines 458-499 |
| `get_embedding()` | Lines 721-741 | Lines 502-521 |
| `get_vector_index_status()` | Lines 744-761 | Lines 524-539 |

**Critical difference:** `database_sqlalchemy.py` requires `user_id` for multi-tenancy, but `database.py` doesn't. The `main.py` imports from `database.py` (line 36-53), meaning **production code uses the wrong implementation without multi-tenancy**.

---

### 3. Dual Retriever Implementations

**Files involved:**
- `retrieval/langchain_retrievers.py` - For ChromaDB (240 lines)
- `retrieval/hybrid_retriever.py` - For PostgreSQL (288 lines)
- `retrieval/postgres_bm25.py` - PostgreSQL BM25 (322 lines)

**The retrieval layer has THREE implementations:**

1. **`HybridLangChainRetriever`** (`langchain_retrievers.py:167-239`) - Uses `BM25LangChainRetriever` (SQLite FTS5) + `VectorLangChainRetriever` (ChromaDB)

2. **`PostgresHybridRetriever`** (`hybrid_retriever.py:23-216`) - Uses `PostgresBM25Retriever` + `PGVectorStoreManager`

3. **`VectorOnlyRetriever`** (`hybrid_retriever.py:219-287`) - Uses PGVector alone

**But `main.py` only uses `HybridLangChainRetriever`** (line 588-600), which connects to the SQLite/ChromaDB backends despite calling it "chroma_manager" that's actually a PGVectorStoreManager.

---

### 4. Triplicate Embedding Document Creation

The function `_create_embedding_document()` / `_create_flat_document()` is duplicated in **6 places**:

| Location | Lines |
|----------|-------|
| `embeddings.py` | 184-219 |
| `retrieval/chroma_manager.py` | 226-262 |
| `retrieval/pgvector_store.py` | 253-306 |
| `database.py` (`_create_search_document`) | 474-508 |
| `lambdas/embedder/handler.py` | 182-209 |
| `lambdas/embedder/embeddings.py` | 175-210 |

All six implementations do the **exact same thing**: concatenate summary, headline, category, subcategories, extracted_text, key_interest, themes, objects, emotions, vibes, location_tags, and hashtags.

---

### 5. Duplicate Embeddings Module in Lambdas

**Files:**
- `embeddings.py` (root) - 220 lines
- `lambdas/embedder/embeddings.py` - 211 lines

These are **nearly identical** but with key differences:

| Feature | Root | Lambda |
|---------|------|--------|
| Client initialization | Lazy (`_get_voyage_client()`) | Eager (global `voyage_client`) |
| Error handling | Fails at runtime if no key | Raises on import |

**The Lambda copies should import from root, not duplicate.**

---

## Library Underutilization Issues

### 6. Custom DynamoDB Checkpointer Instead of LangGraph's Built-in

**File:** `chat/checkpointers/dynamodb_saver.py` (623 lines)

**Problem:** LangGraph provides `langgraph-checkpoint-postgres` which could be used with your PostgreSQL RDS. Instead, a custom 623-line DynamoDBSaver was written.

**Library alternatives:**
- `langgraph-checkpoint-postgres` - Built for PostgreSQL
- `langgraph-checkpoint-dynamodb` - If DynamoDB is truly needed (community package exists)

**Your custom implementation:**
- Manually handles serialization/deserialization (lines 84-168)
- Manually implements all BaseCheckpointSaver methods
- Has incomplete async support (lines 584-618 just call sync methods)

---

### 7. Custom Conversation Manager Instead of LangGraph State

**File:** `chat/conversation_manager.py` (220 lines)

**Problem:** LangGraph's state management handles conversation memory natively. The custom `ConversationManager` wraps `DynamoDBSaver` but adds little value over direct LangGraph usage.

**Lines 89-125** (`get_session_info`) reimplements what LangGraph provides:
```python
checkpoint_tuple = checkpointer.get_tuple(config)
if checkpoint_tuple:
    state = checkpoint_tuple.checkpoint.get("channel_values", {})
    messages = state.get("messages", [])
```

This is just accessing LangGraph's native state format manually.

---

### 8. Raw psycopg2 Instead of SQLAlchemy

**File:** `retrieval/postgres_bm25.py`

**Lines 147-149:**
```python
with psycopg2.connect(self.connection_string) as conn:
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(sql, final_params)
```

**Problem:** The codebase has SQLAlchemy configured (`database/connection.py`) but `postgres_bm25.py` uses raw psycopg2, bypassing connection pooling.

---

### 9. Duplicate Connection String Loading

Connection string retrieval is implemented in **4 places**:

| Location | Lines |
|----------|-------|
| `database/connection.py` | 35-76 (`_get_database_url_from_parameter_store`) |
| `retrieval/pgvector_store.py` | 92-115 (`_load_connection_string_from_parameter_store`) |
| `retrieval/postgres_bm25.py` | 68-91 (`_load_connection_string_from_parameter_store`) |
| `utils/aws_secrets.py` | (referenced but uses Secrets Manager) |

All do the same: call `boto3.client('ssm').get_parameter()`.

---

## Architecture Inconsistencies

### 10. Naming Confusion: Chroma vs PGVector

Throughout the codebase, "chroma" naming persists despite using PGVector:

| File | Variable/Function | Actual Type |
|------|-------------------|-------------|
| `main.py:85` | `prod_chroma_manager` | PGVectorStoreManager |
| `main.py:86` | `golden_chroma_manager` | PGVectorStoreManager |
| `main.py:205` | `get_current_chroma_manager()` | Returns PGVectorStoreManager |
| `config/langchain_config.py:26-39` | `"chroma"` config section | Used for PGVector |
| `chat/agentic_chat.py:41` | `chroma_manager` parameter | Actually PGVectorStoreManager |
| `retrieval/agentic_search.py:37` | `chroma_manager` parameter | Actually PGVectorStoreManager |

---

### 11. Multi-tenancy Not Implemented in Main API

**Problem:** `database_sqlalchemy.py` requires `user_id` everywhere, but `main.py` imports from `database.py` which has no `user_id`:

```python
# main.py:36-53 - Imports from database.py (no user_id)
from database import (
    init_db, create_item, get_item, list_items, ...
)

# But database_sqlalchemy.py requires user_id:
def get_item(item_id: str, user_id: str) -> Optional[dict]:
```

**Impact:** Multi-tenancy is designed but not wired up.

---

### 12. Inconsistent Search Types Routing

`main.py` search endpoint (lines 542-730) supports:
- `"agentic"` → Uses `HybridLangChainRetriever` (ChromaDB-based)
- `"hybrid-lc"` → Uses `HybridLangChainRetriever` (ChromaDB-based)
- `"vector-lc"` → Uses `VectorLangChainRetriever` (ChromaDB-based)
- `"bm25-lc"` → Uses `BM25LangChainRetriever` (SQLite FTS5)

**None of these use the PostgreSQL implementations** (`PostgresHybridRetriever`, `PostgresBM25Retriever`).

---

### 13. Orphaned Migration Scripts

**Files in `retrieval/`:**
- `vector_migration.py` - ChromaDB to PGVector migration
- `chroma_manager.py` - Still fully functional but unused

These should either be removed or the migration completed.

---

## Summary Table

| Issue | Severity | Files Affected | Lines of Dead Code |
|-------|----------|----------------|-------------------|
| Dual vector stores | 🔴 Critical | 2 | ~400 |
| Dual database implementations | 🔴 Critical | 2 | ~600 |
| Dual retriever implementations | 🔴 Critical | 3 | ~300 |
| 6x document creation functions | 🟠 High | 6 | ~250 |
| Custom DynamoDB checkpointer | 🟠 High | 1 | ~623 |
| Duplicate embeddings module | 🟠 High | 2 | ~200 |
| Raw psycopg2 usage | 🟡 Medium | 1 | - |
| 4x connection string loading | 🟡 Medium | 4 | ~100 |

**Total estimated dead/duplicate code: ~2,500+ lines**

---

## Target Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         main.py                              │
│                    (FastAPI Application)                     │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  database/      │ │  retrieval/     │ │  chat/          │
│  (SQLAlchemy)   │ │  (LangChain)    │ │  (LangGraph)    │
└─────────────────┘ └─────────────────┘ └─────────────────┘
         │                   │                   │
         └───────────────────┼───────────────────┘
                             ▼
              ┌─────────────────────────────────┐
              │     PostgreSQL (RDS)             │
              │  - Items/Analyses (JSONB)        │
              │  - Embeddings (pgvector)         │
              │  - FTS (tsvector)                │
              │  - Checkpoints (if needed)       │
              └─────────────────────────────────┘
```

**Components to Remove:**
- SQLite support in production code paths
- ChromaDB entirely
- Custom DynamoDB checkpointer (evaluate langgraph-checkpoint-postgres)
- Duplicate modules in lambdas

**Components to Consolidate:**
- Single database implementation (database_sqlalchemy.py)
- Single vector store implementation (pgvector_store.py)
- Single retriever implementation (PostgresHybridRetriever)
- Single document creation function (utils/document_builder.py)
- Single connection management (database/connection.py)

---

## Related Documents

- [ARCHITECTURE.md](./ARCHITECTURE.md) - Current architecture documentation
- [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md) - Detailed refactoring plan
