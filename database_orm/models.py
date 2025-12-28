"""
SQLAlchemy ORM models for PostgreSQL database.

This module defines the database schema using SQLAlchemy ORM with:
- Items table with user_id for multi-tenancy
- Analyses table with JSONB for structured data and tsvector for full-text search
- Embeddings table with pgvector support for semantic search
- Proper relationships and foreign keys with CASCADE delete
- Indexes for performance optimization
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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator, JSON

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    # Fallback for environments without pgvector
    Vector = None


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


class VectorType(TypeDecorator):
    """
    Custom Vector type that works with both PostgreSQL (pgvector) and SQLite.

    Uses Vector for PostgreSQL and JSON array for other databases.
    """
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql' and Vector is not None:
            return dialect.type_descriptor(Vector(1024))
        else:
            # Store as JSON array for SQLite/testing
            return dialect.type_descriptor(JSON())


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
    embeddings: Mapped[list["Embedding"]] = relationship(
        "Embedding",
        back_populates="item",
        cascade="all, delete-orphan"
    )

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
    embeddings: Mapped[list["Embedding"]] = relationship(
        "Embedding",
        back_populates="analysis",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Analysis(id={self.id}, item_id={self.item_id}, version={self.version})>"


class Embedding(Base):
    """
    Embeddings table stores vector embeddings for semantic search.

    Uses pgvector extension for efficient similarity search with:
    - Vector(1024) for 1024-dimensional embeddings
    - IVFFlat index with cosine similarity
    - User association for multi-tenancy
    """
    __tablename__ = "embeddings"

    # Primary key
    id: Mapped[str] = mapped_column(String, primary_key=True)

    # Foreign keys
    item_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    analysis_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # User association for multi-tenancy (denormalized for faster queries)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # Vector embedding (1024 dimensions for Voyage AI embeddings)
    vector: Mapped[Optional[list[float]]] = mapped_column(
        VectorType,
        nullable=True
    )

    # Embedding metadata
    embedding_model: Mapped[str] = mapped_column(String, nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_source: Mapped[Optional[dict]] = mapped_column(JSONBType, nullable=True)

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    item: Mapped["Item"] = relationship("Item", back_populates="embeddings")
    analysis: Mapped["Analysis"] = relationship("Analysis", back_populates="embeddings")

    def __repr__(self) -> str:
        return f"<Embedding(id={self.id}, item_id={self.item_id}, model={self.embedding_model})>"


# Indexes for performance optimization

# Index for user_id on items (already created via index=True in column definition)
# Index for user_id on analyses (already created via index=True in column definition)
# Index for user_id on embeddings (already created via index=True in column definition)

# Index for item_id on analyses (already created via index=True in column definition)
# Index for category on analyses (already created via index=True in column definition)

# Composite index for item_id + version on analyses for efficient latest version queries
Index("idx_analyses_item_version", Analysis.item_id, Analysis.version.desc())

# GIN index for full-text search on search_vector
Index("idx_analyses_search_vector", Analysis.search_vector, postgresql_using="gin")

# IVFFlat index for vector similarity search with cosine distance
# Note: This will be created in the migration after data is populated
# Index("idx_embeddings_vector_cosine", Embedding.vector, postgresql_using="ivfflat", postgresql_with={"lists": 100}, postgresql_ops={"vector": "vector_cosine_ops"})
