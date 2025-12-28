# Archived Scripts

This directory contains deprecated scripts that have been replaced by newer implementations.

## Archived Scripts

- `regenerate_embeddings_deprecated.py` - ChromaDB embedding regeneration (no longer needed)
- `migrate_to_langchain_deprecated.py` - ChromaDB vector store builder (no longer needed)
- `build_chroma_index_deprecated.py` - ChromaDB index builder (no longer needed)

## Why Archived?

The project migrated from ChromaDB (local development) to PostgreSQL with pgvector
extension (AWS RDS compatible). These scripts are kept for reference only.

## Do Not Use

These scripts will generate `DeprecationWarning` if executed. They are kept for:
- Historical reference
- Understanding migration decisions
- Documentation purposes

## Current Scripts

Use these scripts instead:
- For vector index management, use PostgreSQL-based tools or the API endpoints
- PGVector indices are managed automatically by the retrieval system
