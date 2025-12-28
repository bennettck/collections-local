# Implementation Plan: Architecture Consolidation

**Created:** 2025-12-28
**Reference:** [ARCHITECTURE_REVIEW.md](./ARCHITECTURE_REVIEW.md)
**Executor:** Claude Code with up to 3 sub-agents

---

## Overview

This plan consolidates the dual SQLite/PostgreSQL and ChromaDB/PGVector implementations into a single, clean architecture using PostgreSQL as the sole backend.

**Execution Strategy:**
- 5 Phases executed sequentially
- Within each phase, tasks can be parallelized across up to 3 sub-agents
- Each task includes verification steps
- Rollback points defined between phases

---

## Pre-Flight Checklist

Before starting, verify:
- [ ] Git branch is clean (`git status`)
- [ ] All tests pass (`pytest tests/`)
- [ ] Database backups exist
- [ ] Environment variables documented

---

## Phase 1: Create Shared Utilities (Foundation)

**Goal:** Create shared utilities that will be used across all consolidated code.

**Duration:** ~30 minutes
**Parallelizable:** Yes (3 sub-agents)

### Task 1.1: Create Document Builder Utility
**Assigned to:** Sub-agent 1
**Files to create:** `utils/document_builder.py`

```python
# Create utils/document_builder.py with single implementation of:
# - create_flat_document(raw_response: dict) -> str
# - create_langchain_document(raw_response: dict, item_id: str, filename: str) -> Document
```

**Steps:**
1. Create `utils/document_builder.py`
2. Extract logic from `embeddings.py:184-219` (the canonical implementation)
3. Add type hints and docstrings
4. Add unit tests in `utils/tests/test_document_builder.py`

**Verification:**
```bash
pytest utils/tests/test_document_builder.py -v
```

### Task 1.2: Consolidate Connection Management
**Assigned to:** Sub-agent 2
**Files to modify:** `database/connection.py`, `utils/aws_secrets.py`

**Steps:**
1. Ensure `database/connection.py` is the single source for connection management
2. Add helper function `get_connection_string()` for retrievers to use
3. Remove duplicate Parameter Store logic from:
   - `retrieval/pgvector_store.py:92-115`
   - `retrieval/postgres_bm25.py:68-91`
4. Update those files to import from `database/connection.py`

**Verification:**
```bash
pytest database/tests/test_connection.py -v
```

### Task 1.3: Create Database Adapter Interface
**Assigned to:** Sub-agent 3
**Files to create:** `database/adapter.py`

**Steps:**
1. Create `database/adapter.py` with interface that both local (SQLite) and production (PostgreSQL) can implement
2. Define abstract methods matching `database_sqlalchemy.py` signatures (with `user_id`)
3. This allows gradual migration of `main.py` imports

**Verification:**
```bash
python -c "from database.adapter import DatabaseAdapter; print('OK')"
```

---

## Phase 2: Consolidate Database Layer

**Goal:** Merge dual database implementations into single SQLAlchemy-based implementation.

**Duration:** ~1 hour
**Parallelizable:** Partially (2 sub-agents)

### Task 2.1: Update main.py Database Imports
**Assigned to:** Sub-agent 1
**Files to modify:** `main.py`

**Steps:**
1. Create import shim that routes to correct implementation based on environment:
   ```python
   # At top of main.py
   import os
   if os.getenv("DB_SECRET_ARN") or os.getenv("DATABASE_URL"):
       from database_sqlalchemy import (...)
   else:
       from database import (...)
   ```

2. Add `user_id` parameter handling:
   - Extract from Cognito JWT in authenticated requests
   - Use "default" for local development

3. Update all database function calls to include `user_id`

**Files affected:**
- `main.py` - All database function calls need `user_id` parameter

**Verification:**
```bash
# Local test (SQLite path)
unset DB_SECRET_ARN && python -c "from main import app; print('Local OK')"

# Simulate production (would use PostgreSQL)
DB_SECRET_ARN=test python -c "from main import app; print('Prod OK')" 2>/dev/null || echo "Expected - no real secret"
```

### Task 2.2: Archive Legacy SQLite Code
**Assigned to:** Sub-agent 2
**Files to modify:** `database.py`

**Steps:**
1. Rename `database.py` → `database_sqlite_legacy.py`
2. Add deprecation warning at top of file:
   ```python
   import warnings
   warnings.warn(
       "database_sqlite_legacy.py is deprecated. Use database_sqlalchemy.py for new code.",
       DeprecationWarning
   )
   ```
3. Update any remaining imports that need SQLite for local dev

**Verification:**
```bash
python -c "import database_sqlite_legacy" 2>&1 | grep -q "DeprecationWarning" && echo "OK"
```

### Task 2.3: Update Lambda Handlers
**Assigned to:** Sub-agent 1 (after 2.1)
**Files to modify:**
- `lambdas/embedder/handler.py`
- `lambdas/analyzer/handler.py`

**Steps:**
1. Remove duplicate `embeddings.py` from Lambda directories
2. Update imports to use shared modules via Lambda layers
3. Ensure Lambdas use `database/connection.py` for connections

---

## Phase 3: Consolidate Vector Store Layer

**Goal:** Remove ChromaDB, use PGVector exclusively.

**Duration:** ~1 hour
**Parallelizable:** Yes (3 sub-agents)

### Task 3.1: Update PGVector Store Manager
**Assigned to:** Sub-agent 1
**Files to modify:** `retrieval/pgvector_store.py`

**Steps:**
1. Import `create_flat_document` from `utils/document_builder.py`
2. Remove local `create_flat_document` method (lines 253-306)
3. Import connection string helper from `database/connection.py`
4. Remove `_load_connection_string_from_parameter_store` method (lines 92-115)
5. Add `user_id` filtering to all search methods

**Verification:**
```bash
pytest retrieval/tests/test_pgvector_store.py -v
```

### Task 3.2: Rename Chroma References
**Assigned to:** Sub-agent 2
**Files to modify:** Multiple

**Global rename operations:**
```
prod_chroma_manager → prod_vector_store
golden_chroma_manager → golden_vector_store
chroma_manager → vector_store
get_current_chroma_manager → get_current_vector_store
ChromaVectorStoreManager → (delete references)
```

**Files to update:**
- `main.py` - Lines 85-86, 126-153, 205-210, 497-510, 557-600, 805-814, 876-880
- `chat/agentic_chat.py` - Lines 41, 58, 83
- `retrieval/agentic_search.py` - Lines 37, 52, 77
- `retrieval/langchain_retrievers.py` - Lines 122, 182, 198-204
- `config/langchain_config.py` - Rename config keys

### Task 3.3: Archive ChromaDB Code
**Assigned to:** Sub-agent 3
**Files to modify/delete:**

**Steps:**
1. Move `retrieval/chroma_manager.py` → `retrieval/archive/chroma_manager_deprecated.py`
2. Move `retrieval/vector_migration.py` → `retrieval/archive/vector_migration.py`
3. Delete `data/chroma_prod/` directory
4. Delete `data/chroma_golden/` directory
5. Remove `langchain-chroma` from `requirements.txt`

**Verification:**
```bash
python -c "from retrieval.pgvector_store import PGVectorStoreManager; print('OK')"
grep -q "langchain-chroma" requirements.txt && echo "FAIL: chroma still in requirements" || echo "OK"
```

---

## Phase 4: Consolidate Retriever Layer

**Goal:** Use PostgreSQL-based retrievers exclusively.

**Duration:** ~1 hour
**Parallelizable:** Yes (2 sub-agents)

### Task 4.1: Update Retrievers to Use PostgreSQL
**Assigned to:** Sub-agent 1
**Files to modify:** `retrieval/langchain_retrievers.py`

**Steps:**
1. Update `BM25LangChainRetriever` to use PostgreSQL FTS instead of SQLite FTS5:
   - Import and use logic from `retrieval/postgres_bm25.py`
   - Use `database/connection.py` for connections

2. Update `VectorLangChainRetriever` to use `PGVectorStoreManager`:
   - Remove ChromaDB references
   - Use `similarity_search_with_score` from PGVector

3. Update `HybridLangChainRetriever`:
   - Use updated BM25 and Vector retrievers
   - Ensure RRF fusion still works

**Verification:**
```bash
pytest retrieval/tests/test_hybrid_retriever.py -v
pytest retrieval/tests/test_postgres_bm25.py -v
```

### Task 4.2: Update Search Endpoint
**Assigned to:** Sub-agent 2
**Files to modify:** `main.py`

**Steps:**
1. Update search endpoint (lines 542-730) to use PostgreSQL retrievers
2. Remove SQLite FTS5 code paths
3. Simplify search type routing:
   - `"hybrid"` → `PostgresHybridRetriever`
   - `"vector"` → `VectorOnlyRetriever`
   - `"bm25"` → `PostgresBM25Retriever`
   - `"agentic"` → Uses hybrid retriever internally

4. Update `/search/config` endpoint to reflect PostgreSQL config

**Verification:**
```bash
# Integration test
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "search_type": "hybrid"}' | jq .
```

### Task 4.3: Archive Old Retriever Code
**Assigned to:** Sub-agent 1 (after 4.1)

**Steps:**
1. Consolidate `retrieval/postgres_bm25.py` into `retrieval/langchain_retrievers.py` if appropriate
2. Or keep separate but ensure no duplicate code
3. Remove any remaining SQLite FTS references
4. Update `retrieval/__init__.py` exports

---

## Phase 5: Consolidate Chat/Checkpointing Layer

**Goal:** Evaluate and potentially replace custom DynamoDB checkpointer.

**Duration:** ~45 minutes
**Parallelizable:** Partially

### Task 5.1: Evaluate LangGraph Checkpoint Options
**Assigned to:** Sub-agent 1
**Research task - no code changes**

**Steps:**
1. Check if `langgraph-checkpoint-postgres` is available and compatible
2. Test with existing RDS PostgreSQL
3. Compare feature set with custom `DynamoDBSaver`

**Decision point:**
- If PostgreSQL checkpointer works → Proceed to 5.2a
- If DynamoDB required → Proceed to 5.2b

### Task 5.2a: Migrate to PostgreSQL Checkpointer (if available)
**Assigned to:** Sub-agent 2
**Files to modify:** `chat/conversation_manager.py`, `chat/agentic_chat.py`

**Steps:**
1. Install `langgraph-checkpoint-postgres`
2. Update `ConversationManager` to use PostgreSQL checkpointer
3. Remove custom `DynamoDBSaver`
4. Archive `chat/checkpointers/dynamodb_saver.py`

### Task 5.2b: Keep DynamoDB Checkpointer (if required)
**Assigned to:** Sub-agent 2
**Files to modify:** `chat/checkpointers/dynamodb_saver.py`

**Steps:**
1. Document why DynamoDB is required
2. Improve async support (currently just wraps sync)
3. Add connection pooling if missing
4. Consider extracting to separate package for reuse

### Task 5.3: Simplify Conversation Manager
**Assigned to:** Sub-agent 3
**Files to modify:** `chat/conversation_manager.py`

**Steps:**
1. Remove methods that just wrap LangGraph functionality
2. Keep only multi-tenancy logic (`{user_id}#{session_id}` thread IDs)
3. Simplify `get_session_info` to use LangGraph state directly

**Verification:**
```bash
pytest retrieval/tests/test_conversation_manager_dynamodb.py -v
```

---

## Phase 6: Cleanup and Documentation

**Goal:** Remove dead code, update documentation.

**Duration:** ~30 minutes
**Parallelizable:** Yes (3 sub-agents)

### Task 6.1: Remove Dead Code
**Assigned to:** Sub-agent 1

**Files to delete/archive:**
- `lambdas/embedder/embeddings.py` (use shared module)
- `lambdas/analyzer/embeddings.py` (use shared module)
- `lambdas/*/database/` directories (use shared modules)

**Code to remove from remaining files:**
- SQLite-specific code paths in production files
- ChromaDB import statements
- Unused configuration options

### Task 6.2: Update Dependencies
**Assigned to:** Sub-agent 2
**Files to modify:** `requirements.txt`, Lambda `requirements.txt` files

**Steps:**
1. Remove unused dependencies:
   - `langchain-chroma`
   - `chromadb` (if present)
   - `langgraph-checkpoint-sqlite` (if not needed for local)

2. Add any missing dependencies

3. Update version constraints if needed

**Verification:**
```bash
pip install -r requirements.txt
python -c "import langchain; import langgraph; import langchain_postgres; print('OK')"
```

### Task 6.3: Update Documentation
**Assigned to:** Sub-agent 3
**Files to modify:**
- `documentation/ARCHITECTURE.md`
- `README.md`
- `CLAUDE.md`

**Steps:**
1. Update architecture diagrams
2. Remove references to ChromaDB/SQLite
3. Document new unified architecture
4. Update development setup instructions

---

## Verification Checklist

After completing all phases, verify:

### Unit Tests
```bash
pytest tests/unit/ -v
```

### Integration Tests
```bash
pytest tests/integration/ -v
```

### API Smoke Tests
```bash
# Start server
uvicorn main:app --reload &

# Test endpoints
curl http://localhost:8000/health | jq .
curl -X POST http://localhost:8000/search -H "Content-Type: application/json" -d '{"query":"test","search_type":"hybrid"}' | jq .
```

### Code Quality
```bash
# No import errors
python -c "from main import app"

# No duplicate implementations
grep -r "def _create_flat_document" --include="*.py" | wc -l  # Should be 1
grep -r "def _create_embedding_document" --include="*.py" | wc -l  # Should be 1 (or 0 if consolidated)
```

---

## Rollback Plan

If issues arise:

1. **Phase 1-2:** `git checkout -- database.py main.py`
2. **Phase 3:** `git checkout -- retrieval/`
3. **Phase 4:** `git checkout -- main.py retrieval/langchain_retrievers.py`
4. **Phase 5:** `git checkout -- chat/`

Full rollback: `git checkout HEAD~N` where N is number of commits

---

## Success Metrics

| Metric | Before | After |
|--------|--------|-------|
| Total Python files | 158 | ~140 |
| Lines of code | ~15,000 | ~12,500 |
| Duplicate functions | 15+ | 0 |
| Vector store implementations | 2 | 1 |
| Database implementations | 2 | 1 |
| Retriever implementations | 3 | 1 |

---

## Sub-Agent Assignment Summary

| Phase | Sub-Agent 1 | Sub-Agent 2 | Sub-Agent 3 |
|-------|-------------|-------------|-------------|
| 1 | Document Builder | Connection Management | Database Adapter |
| 2 | main.py imports | Archive SQLite | (wait) |
| 3 | PGVector update | Rename chroma refs | Archive ChromaDB |
| 4 | Update retrievers | Update search endpoint | (parallel with 1) |
| 5 | Research checkpointers | Migrate/keep checkpointer | Simplify ConversationManager |
| 6 | Remove dead code | Update dependencies | Update documentation |

---

## Execution Command

To execute this plan:

```
Please execute the implementation plan in documentation/IMPLEMENTATION_PLAN.md
Start with Phase 1, using up to 3 sub-agents in parallel where indicated.
Verify each phase before proceeding to the next.
```
