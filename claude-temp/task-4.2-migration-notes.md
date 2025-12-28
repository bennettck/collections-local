# Task 4.2 Migration Notes: Update main.py to Use PostgreSQL Retrievers

## Summary
Task 4.1 has deprecated `retrieval/langchain_retrievers.py` for PostgreSQL deployments. The following files need to be updated in Task 4.2 to use the PostgreSQL retrievers instead.

## Files Requiring Updates

### 1. main.py (PRIMARY)
**Lines affected:** 643, 647, 671, 675, 693, 695

**Current search types using deprecated retrievers:**
- `"hybrid-lc"` (line 641-667) → Uses `HybridLangChainRetriever`
- `"vector-lc"` (line 669-689) → Uses `VectorLangChainRetriever`
- `"bm25-lc"` (line 691-708) → Uses `BM25LangChainRetriever`
- `"agentic"` → Uses `agentic_search.AgenticSearchOrchestrator` (which internally uses `HybridLangChainRetriever`)

**Migration mapping:**
- `HybridLangChainRetriever` → `PostgresHybridRetriever`
- `VectorLangChainRetriever` → `VectorOnlyRetriever`
- `BM25LangChainRetriever` → `PostgresBM25Retriever`

**Key differences to handle:**

1. **User ID filtering:**
   - Old: No user_id parameter (uses SQLite database)
   - New: Requires `user_id` parameter for multi-tenancy
   - Action: Pass `user_id = get_user_id_from_request(request)`

2. **Vector store parameter:**
   - Old: `vector_store` parameter (accepts ChromaDB/PGVector manager)
   - New: `pgvector_manager` parameter (PGVectorStoreManager only)
   - Action: Rename parameter when calling PostgresHybridRetriever/VectorOnlyRetriever

3. **Connection string:**
   - Old: Implicit (uses database.py global connection)
   - New: Auto-loaded from database_orm.connection.get_connection_string()
   - Action: No action needed (handled in __init__)

4. **BM25 differences:**
   - Old: Uses SQLite FTS5 via `database.search_items()`
   - New: Uses PostgreSQL full-text search with tsvector
   - Action: Test BM25 search results for parity

### 2. retrieval/agentic_search.py
**Lines affected:** 13, 67

Uses `HybridLangChainRetriever` in `AgenticSearchOrchestrator.__init__`

**Migration:**
- Import: `from retrieval.langchain_retrievers import HybridLangChainRetriever`
- Change to: `from retrieval import PostgresHybridRetriever`
- Update initialization with `user_id` and `pgvector_manager` parameters

### 3. chat/agentic_chat.py
**Lines affected:** 17, 73

Uses `HybridLangChainRetriever` in `AgenticChatOrchestrator.__init__`

**Migration:**
- Import: `from retrieval.langchain_retrievers import HybridLangChainRetriever`
- Change to: `from retrieval import PostgresHybridRetriever`
- Update initialization with `user_id` and `pgvector_manager` parameters

### 4. Test Files (Lower Priority)
These files mock the retrievers, so updates are less critical but should be aligned:
- `tests/test_chat.py` (lines 232, 251, 288, 315)
- `tests/test_agentic_search.py` (lines 154, 155, 156)
- `tests/test_search_endpoint.py` (lines 96, 123, 150, 323, 348, 376, 423)

## PostgreSQL Retriever API Reference

### PostgresHybridRetriever
```python
from retrieval import PostgresHybridRetriever

retriever = PostgresHybridRetriever(
    top_k=10,
    bm25_top_k=20,
    vector_top_k=20,
    bm25_weight=0.3,
    vector_weight=0.7,
    rrf_c=15,
    user_id="user123",  # NEW: Required for multi-tenancy
    category_filter="photos",
    min_relevance_score=0.0,
    min_similarity_score=0.0,
    pgvector_manager=pgvector_mgr,  # NEW: Renamed from vector_store
    connection_string=None,  # Optional: auto-loaded if not provided
)
```

### VectorOnlyRetriever
```python
from retrieval import VectorOnlyRetriever

retriever = VectorOnlyRetriever(
    top_k=10,
    user_id="user123",  # NEW: Required for multi-tenancy
    category_filter="photos",
    min_similarity_score=0.0,
    pgvector_manager=pgvector_mgr,  # NEW: Required
)
```

### PostgresBM25Retriever
```python
from retrieval import PostgresBM25Retriever

retriever = PostgresBM25Retriever(
    top_k=10,
    user_id="user123",  # NEW: Required for multi-tenancy
    category_filter="photos",
    min_relevance_score=0.0,
    connection_string=None,  # Optional: auto-loaded if not provided
)
```

## Testing Strategy

1. **Local SQLite mode:** Should continue using langchain_retrievers.py (no changes)
2. **PostgreSQL mode:** Should use new retrievers and see deprecation warnings
3. **Search parity:** Verify that search results are comparable between old and new retrievers
4. **User isolation:** Verify that user_id filtering works correctly

## Environment Detection

The deprecation warning in langchain_retrievers.py triggers when:
- `DB_SECRET_ARN` is set (AWS Secrets Manager mode), OR
- `DATABASE_URL` starts with "postgresql"

This allows local SQLite development to continue using the old retrievers without warnings.

## Completion Checklist for Task 4.2

- [ ] Update main.py search endpoint (3 search types)
- [ ] Update retrieval/agentic_search.py
- [ ] Update chat/agentic_chat.py
- [ ] Update tests (optional, can use mocks)
- [ ] Test in PostgreSQL mode
- [ ] Test in SQLite mode (backwards compatibility)
- [ ] Verify user isolation works
- [ ] Verify search result quality
- [ ] Update documentation
