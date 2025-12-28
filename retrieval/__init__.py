"""Retrieval system for Collections Local.

Provides PostgreSQL-based retrieval components:
- PGVector for semantic similarity search
- PostgreSQL BM25 for keyword search
- Hybrid retrieval with RRF
"""

from retrieval.pgvector_store import PGVectorStoreManager
from retrieval.postgres_bm25 import PostgresBM25Retriever
from retrieval.hybrid_retriever import PostgresHybridRetriever, VectorOnlyRetriever

# DEPRECATED: ChromaDB support has been removed.
# Legacy code is available in retrieval.archive for reference only.

__all__ = [
    "PGVectorStoreManager",
    "PostgresBM25Retriever",
    "PostgresHybridRetriever",
    "VectorOnlyRetriever",
]
