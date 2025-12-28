"""
Unit tests for SQLAlchemy ORM models.

Tests model creation, relationships, and constraints.
"""

import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from database_orm.models import Base, Item, Analysis, Embedding


@pytest.fixture
def engine():
    """Create in-memory SQLite engine for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def session(engine):
    """Create database session for testing."""
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestItemModel:
    """Test Item ORM model."""

    def test_create_item(self, session):
        """Test creating an item."""
        item = Item(
            id="test-item-1",
            user_id="user-123",
            filename="test.jpg",
            original_filename="original.jpg",
            file_path="/data/test.jpg",
            file_size=1024,
            mime_type="image/jpeg"
        )
        session.add(item)
        session.commit()

        # Verify item was created
        retrieved = session.query(Item).filter_by(id="test-item-1").first()
        assert retrieved is not None
        assert retrieved.user_id == "user-123"
        assert retrieved.filename == "test.jpg"
        assert retrieved.file_size == 1024

    def test_item_timestamps(self, session):
        """Test item timestamp auto-generation."""
        item = Item(
            id="test-item-2",
            user_id="user-123",
            filename="test2.jpg",
            file_path="/data/test2.jpg"
        )
        session.add(item)
        session.commit()

        # Timestamps should be auto-generated
        assert item.created_at is not None
        assert item.updated_at is not None
        assert isinstance(item.created_at, datetime)

    def test_item_required_fields(self, session):
        """Test that required fields are enforced."""
        item = Item(
            id="test-item-3",
            # Missing user_id (required)
            filename="test3.jpg",
            file_path="/data/test3.jpg"
        )
        session.add(item)

        with pytest.raises(IntegrityError):
            session.commit()

    def test_item_relationships(self, session):
        """Test item relationships with analyses and embeddings."""
        item = Item(
            id="test-item-4",
            user_id="user-123",
            filename="test4.jpg",
            file_path="/data/test4.jpg"
        )
        session.add(item)
        session.commit()

        # Add analysis
        analysis = Analysis(
            id="analysis-1",
            item_id="test-item-4",
            user_id="user-123",
            version=1,
            category="photo",
            raw_response={"summary": "Test"}
        )
        session.add(analysis)
        session.commit()

        # Verify relationship
        assert len(item.analyses) == 1
        assert item.analyses[0].id == "analysis-1"


class TestAnalysisModel:
    """Test Analysis ORM model."""

    def test_create_analysis(self, session):
        """Test creating an analysis."""
        # Create item first
        item = Item(
            id="test-item-5",
            user_id="user-123",
            filename="test5.jpg",
            file_path="/data/test5.jpg"
        )
        session.add(item)
        session.commit()

        # Create analysis
        analysis = Analysis(
            id="analysis-2",
            item_id="test-item-5",
            user_id="user-123",
            version=1,
            category="photo",
            summary="A beautiful photo",
            raw_response={
                "category": "photo",
                "summary": "A beautiful photo",
                "tags": ["nature", "landscape"]
            },
            provider_used="anthropic",
            model_used="claude-3"
        )
        session.add(analysis)
        session.commit()

        # Verify analysis was created
        retrieved = session.query(Analysis).filter_by(id="analysis-2").first()
        assert retrieved is not None
        assert retrieved.category == "photo"
        assert retrieved.raw_response["tags"] == ["nature", "landscape"]

    def test_analysis_jsonb_field(self, session):
        """Test JSONB field for raw_response (SQLite doesn't support JSONB, so we test dict)."""
        item = Item(
            id="test-item-6",
            user_id="user-123",
            filename="test6.jpg",
            file_path="/data/test6.jpg"
        )
        session.add(item)

        analysis = Analysis(
            id="analysis-3",
            item_id="test-item-6",
            user_id="user-123",
            version=1,
            raw_response={
                "nested": {
                    "data": "value",
                    "array": [1, 2, 3]
                }
            }
        )
        session.add(analysis)
        session.commit()

        # Verify nested structure preserved
        retrieved = session.query(Analysis).filter_by(id="analysis-3").first()
        assert retrieved.raw_response["nested"]["data"] == "value"
        assert retrieved.raw_response["nested"]["array"] == [1, 2, 3]

    def test_analysis_versioning(self, session):
        """Test analysis version tracking."""
        item = Item(
            id="test-item-7",
            user_id="user-123",
            filename="test7.jpg",
            file_path="/data/test7.jpg"
        )
        session.add(item)

        # Create multiple versions
        for version in [1, 2, 3]:
            analysis = Analysis(
                id=f"analysis-v{version}",
                item_id="test-item-7",
                user_id="user-123",
                version=version,
                category="photo",
                raw_response={"version": version}
            )
            session.add(analysis)

        session.commit()

        # Verify all versions exist
        analyses = session.query(Analysis).filter_by(item_id="test-item-7").all()
        assert len(analyses) == 3
        assert {a.version for a in analyses} == {1, 2, 3}

    def test_analysis_cascade_delete(self, session):
        """Test cascade delete from item to analysis."""
        item = Item(
            id="test-item-8",
            user_id="user-123",
            filename="test8.jpg",
            file_path="/data/test8.jpg"
        )
        session.add(item)

        analysis = Analysis(
            id="analysis-4",
            item_id="test-item-8",
            user_id="user-123",
            version=1,
            raw_response={}
        )
        session.add(analysis)
        session.commit()

        # Delete item (should cascade to analysis)
        session.delete(item)
        session.commit()

        # Verify analysis was also deleted
        retrieved = session.query(Analysis).filter_by(id="analysis-4").first()
        assert retrieved is None


class TestEmbeddingModel:
    """Test Embedding ORM model."""

    def test_create_embedding(self, session):
        """Test creating an embedding."""
        # Create item and analysis first
        item = Item(
            id="test-item-9",
            user_id="user-123",
            filename="test9.jpg",
            file_path="/data/test9.jpg"
        )
        session.add(item)

        analysis = Analysis(
            id="analysis-5",
            item_id="test-item-9",
            user_id="user-123",
            version=1,
            raw_response={}
        )
        session.add(analysis)
        session.commit()

        # Create embedding
        embedding = Embedding(
            id="embedding-1",
            item_id="test-item-9",
            analysis_id="analysis-5",
            user_id="user-123",
            vector=[0.1] * 1024,  # 1024-dimensional vector
            embedding_model="voyage-2",
            embedding_dimensions=1024,
            embedding_source={"fields": ["summary", "category"]}
        )
        session.add(embedding)
        session.commit()

        # Verify embedding was created
        retrieved = session.query(Embedding).filter_by(id="embedding-1").first()
        assert retrieved is not None
        assert retrieved.embedding_model == "voyage-2"
        assert retrieved.embedding_dimensions == 1024
        assert len(retrieved.vector) == 1024

    def test_embedding_vector_dimensions(self, session):
        """Test vector dimension validation."""
        item = Item(
            id="test-item-10",
            user_id="user-123",
            filename="test10.jpg",
            file_path="/data/test10.jpg"
        )
        session.add(item)

        analysis = Analysis(
            id="analysis-6",
            item_id="test-item-10",
            user_id="user-123",
            version=1,
            raw_response={}
        )
        session.add(analysis)
        session.commit()

        # Create embedding with different dimensions
        embedding = Embedding(
            id="embedding-2",
            item_id="test-item-10",
            analysis_id="analysis-6",
            user_id="user-123",
            vector=[0.1] * 512,  # Different size
            embedding_model="test-model",
            embedding_dimensions=512
        )
        session.add(embedding)
        session.commit()

        # Verify dimensions stored correctly
        retrieved = session.query(Embedding).filter_by(id="embedding-2").first()
        assert retrieved.embedding_dimensions == 512
        assert len(retrieved.vector) == 512

    def test_embedding_cascade_delete(self, session):
        """Test cascade delete from item to embedding."""
        item = Item(
            id="test-item-11",
            user_id="user-123",
            filename="test11.jpg",
            file_path="/data/test11.jpg"
        )
        session.add(item)

        analysis = Analysis(
            id="analysis-7",
            item_id="test-item-11",
            user_id="user-123",
            version=1,
            raw_response={}
        )
        session.add(analysis)

        embedding = Embedding(
            id="embedding-3",
            item_id="test-item-11",
            analysis_id="analysis-7",
            user_id="user-123",
            vector=[0.1] * 1024,
            embedding_model="test",
            embedding_dimensions=1024
        )
        session.add(embedding)
        session.commit()

        # Delete item (should cascade to analysis and embedding)
        session.delete(item)
        session.commit()

        # Verify embedding was also deleted
        retrieved = session.query(Embedding).filter_by(id="embedding-3").first()
        assert retrieved is None

    def test_embedding_relationships(self, session):
        """Test embedding relationships."""
        item = Item(
            id="test-item-12",
            user_id="user-123",
            filename="test12.jpg",
            file_path="/data/test12.jpg"
        )
        session.add(item)

        analysis = Analysis(
            id="analysis-8",
            item_id="test-item-12",
            user_id="user-123",
            version=1,
            raw_response={}
        )
        session.add(analysis)

        embedding = Embedding(
            id="embedding-4",
            item_id="test-item-12",
            analysis_id="analysis-8",
            user_id="user-123",
            vector=[0.1] * 1024,
            embedding_model="test",
            embedding_dimensions=1024
        )
        session.add(embedding)
        session.commit()

        # Verify relationships
        assert embedding.item.id == "test-item-12"
        assert embedding.analysis.id == "analysis-8"
        assert item.embeddings[0].id == "embedding-4"
        assert analysis.embeddings[0].id == "embedding-4"
