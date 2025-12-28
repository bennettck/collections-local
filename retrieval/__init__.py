"""Retrieval system for Collections Local.

Provides PostgreSQL-based retrieval components:
- PGVector for semantic similarity search
- PostgreSQL BM25 for keyword search
- Hybrid retrieval with RRF
"""

from retrieval.pgvector_store import PGVectorStoreManager
from retrieval.postgres_bm25 import PostgresBM25Retriever
from retrieval.hybrid_retriever import PostgresHybridRetriever, VectorOnlyRetriever

# DEPRECATED for PostgreSQL deployments:
# - retrieval.langchain_retrievers (uses SQLite/ChromaDB)
# - ChromaDB support (removed, available in retrieval.archive for reference)
#
# For PostgreSQL deployments, use the exports above.
# For local SQLite development, langchain_retrievers.py is still available.

__all__ = [
    "PGVectorStoreManager",
    "PostgresBM25Retriever",
    "PostgresHybridRetriever",
    "VectorOnlyRetriever",
]
