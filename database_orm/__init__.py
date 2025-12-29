"""
Database package for PostgreSQL with SQLAlchemy ORM.

This package provides:
- SQLAlchemy models for Items and Analyses
- Connection management with Parameter Store integration
- Alembic migrations for schema management

EMBEDDING ARCHITECTURE:
- Embeddings are stored in the langchain_pg_embedding table (managed by langchain-postgres)
- NOT in an ORM model - this avoids data duplication and sync issues
- See retrieval/pgvector_store.py for embedding storage
- See retrieval/postgres_bm25.py for BM25 search on the same table
"""

from database_orm.models import Item, Analysis, Base
from database_orm.connection import get_session, get_engine, init_connection

__all__ = [
    "Item",
    "Analysis",
    "Base",
    "get_session",
    "get_engine",
    "init_connection",
]
