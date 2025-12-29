"""
SQLAlchemy ORM models for PostgreSQL database.

This module defines the database schema using SQLAlchemy ORM with:
- Items table with user_id for multi-tenancy
- Analyses table with JSONB for structured data and tsvector for full-text search
- Proper relationships and foreign keys with CASCADE delete
- Indexes for performance optimization

EMBEDDING ARCHITECTURE:
- Embeddings are stored in the langchain_pg_embedding table (managed by langchain-postgres)
- This table is the SINGLE SOURCE OF TRUTH for all search (BM25, vector, hybrid)
- Do NOT use a separate ORM Embedding model - it creates sync issues
- See retrieval/pgvector_store.py for embedding storage
- See retrieval/postgres_bm25.py for BM25 search on the same table
"""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Column,
    String,
    Integer,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator, JSON

# NOTE: pgvector is not imported here because embeddings are stored in
# the langchain_pg_embedding table (managed by langchain-postgres library)
# See retrieval/pgvector_store.py for vector storage


class JSONBType(TypeDecorator):
    """
    Custom JSONB type that works with both PostgreSQL and SQLite.

    Uses JSONB for PostgreSQL and JSON for other databases.
    """
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(JSONB())
        else:
            return dialect.type_descriptor(JSON())


# NOTE: VectorType was removed because embeddings are now stored in
# the langchain_pg_embedding table (managed by langchain-postgres library)
# See retrieval/pgvector_store.py for embedding storage


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class Item(Base):
    """
    Items table stores uploaded files with metadata.

    Each item belongs to a user and can have multiple analyses and embeddings.
    """
    __tablename__ = "items"

    # Primary key
    id: Mapped[str] = mapped_column(String, primary_key=True)

    # User association for multi-tenancy
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # File metadata
    filename: Mapped[str] = mapped_column(String, nullable=False)
    original_filename: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    analyses: Mapped[list["Analysis"]] = relationship(
        "Analysis",
        back_populates="item",
        cascade="all, delete-orphan"
    )
    # NOTE: Embeddings are stored in langchain_pg_embedding table (not ORM)
    # See retrieval/pgvector_store.py for embedding management

    def __repr__(self) -> str:
        return f"<Item(id={self.id}, user_id={self.user_id}, filename={self.filename})>"


class Analysis(Base):
    """
    Analyses table stores AI-generated analysis results.

    Each analysis is versioned and includes:
    - Structured data in JSONB format (raw_response)
    - Full-text search support via tsvector column
    - Tracing information for debugging
    """
    __tablename__ = "analyses"

    # Primary key
    id: Mapped[str] = mapped_column(String, primary_key=True)

    # Foreign key to items
    item_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # User association for multi-tenancy (denormalized for faster queries)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # Versioning
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Analysis data
    category: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    summary: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    raw_response: Mapped[Optional[dict]] = mapped_column(JSONBType, nullable=True)

    # Provider information
    provider_used: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    model_used: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    trace_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Full-text search column (populated by trigger in PostgreSQL, unused in SQLite)
    search_vector = Column(Text, nullable=True)  # Will be TSVECTOR in PostgreSQL via migration

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    item: Mapped["Item"] = relationship("Item", back_populates="analyses")
    # NOTE: Embeddings are stored in langchain_pg_embedding table (not ORM)
    # See retrieval/pgvector_store.py for embedding management

    def __repr__(self) -> str:
        return f"<Analysis(id={self.id}, item_id={self.item_id}, version={self.version})>"


# EMBEDDING ARCHITECTURE NOTE:
# ----------------------------
# Embeddings are NOT stored in an ORM model. They are stored in the
# langchain_pg_embedding table which is managed by the langchain-postgres library.
#
# This table is the SINGLE SOURCE OF TRUTH for all search functionality:
# - Vector search: Uses PGVector cosine similarity on the 'embedding' column
# - BM25 search: Uses PostgreSQL full-text search on the 'document' column
# - Hybrid search: Combines both using RRF (Reciprocal Rank Fusion)
#
# Key table: langchain_pg_embedding
# Key columns:
#   - id: UUID primary key
#   - collection_id: Links to langchain_pg_collection
#   - embedding: vector(1024) for VoyageAI embeddings
#   - document: TEXT content for BM25 search
#   - cmetadata: JSONB with user_id, item_id, category, etc.
#
# See:
# - retrieval/pgvector_store.py: PGVectorStoreManager for embedding storage
# - retrieval/postgres_bm25.py: PostgresBM25Retriever for BM25 search
# - retrieval/hybrid_retriever.py: PostgresHybridRetriever for combined search


# Indexes for performance optimization

# Index for user_id on items (already created via index=True in column definition)
# Index for user_id on analyses (already created via index=True in column definition)

# Index for item_id on analyses (already created via index=True in column definition)
# Index for category on analyses (already created via index=True in column definition)

# Composite index for item_id + version on analyses for efficient latest version queries
Index("idx_analyses_item_version", Analysis.item_id, Analysis.version.desc())

# GIN index for full-text search on search_vector
Index("idx_analyses_search_vector", Analysis.search_vector, postgresql_using="gin")

# NOTE: Vector search indexes are managed by langchain-postgres in the
# langchain_pg_embedding table. See retrieval/pgvector_store.py for details.
