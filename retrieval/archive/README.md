# Archived Retrieval Modules

This directory contains deprecated modules that have been replaced by newer implementations.

## Archived Modules

- `chroma_manager_deprecated.py` - ChromaDB vector store (replaced by `pgvector_store.py`)
- `vector_migration_deprecated.py` - Migration script from ChromaDB to PGVector (no longer needed)

## Why Archived?

The project migrated from ChromaDB (local development) to PostgreSQL with pgvector
extension (AWS RDS compatible). These files are kept for reference only.

### Migration Timeline

- **Before**: ChromaDB with file-based persistence in `/data/chroma_prod` and `/data/chroma_golden`
- **After**: PostgreSQL with pgvector extension for vector search and BM25 for keyword search
- **Migration Tool**: `vector_migration_deprecated.py` was used for the one-time migration

### Advantages of PGVector

1. **AWS RDS Compatibility**: Native PostgreSQL extension, works with AWS RDS
2. **Single Database**: Unified storage for vectors, BM25, and application data
3. **Better Scalability**: PostgreSQL's proven scaling capabilities
4. **User Isolation**: Native support for multi-tenancy with user_id filtering
5. **Transactional Consistency**: ACID guarantees across all operations

## Do Not Use

These modules will generate `DeprecationWarning` if imported. They are kept for:
- Historical reference
- Understanding migration decisions
- Potential rollback scenarios (unlikely but possible)

## Current Implementation

Use these modules instead:
- `/home/user/collections-local/retrieval/pgvector_store.py` - Vector search with pgvector
- `/home/user/collections-local/retrieval/postgres_bm25.py` - BM25 keyword search
- `/home/user/collections-local/retrieval/hybrid_retriever.py` - Combined vector + BM25 search
