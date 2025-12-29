# Archived Scripts

This directory contains utility scripts that are no longer needed for normal operations.

## Kept Scripts

- `backfill_golden_filenames.py` - Backfill filenames for golden dataset
- `copy_golden_images.py` - Copy golden dataset images
- `remove_duplicate_items.py` - Remove duplicate items from database

## Removed (Deprecated)

The following scripts were removed because they wrote to incorrect tables:

- `regenerate_embeddings_deprecated.py` - Wrote to wrong table (removed)
- `migrate_to_langchain_deprecated.py` - ChromaDB migration (removed)
- `build_chroma_index_deprecated.py` - ChromaDB index builder (removed)

The following retrieval modules were removed:

- `retrieval/archive/` - Entire directory removed (contained deprecated ChromaDB and migration code)

## Architecture

Embeddings are now stored in the `langchain_pg_embedding` table:

- **Storage**: `retrieval/pgvector_store.py` (PGVectorStoreManager.add_document)
- **Vector Search**: `retrieval/pgvector_store.py` (PGVectorStoreManager.similarity_search_with_score)
- **BM25 Search**: `retrieval/postgres_bm25.py` (PostgresBM25Retriever)
- **Hybrid Search**: `retrieval/hybrid_retriever.py` (PostgresHybridRetriever)

## Current Embedding Script

Use `scripts/regenerate_embeddings_langchain.py` to regenerate embeddings:

```bash
# Regenerate for specific user
python scripts/regenerate_embeddings_langchain.py --user-id <UUID>

# Regenerate for all users
python scripts/regenerate_embeddings_langchain.py --all-users
```

This script correctly writes to the `langchain_pg_embedding` table.
