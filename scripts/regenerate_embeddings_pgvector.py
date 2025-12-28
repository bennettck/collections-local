#!/usr/bin/env python3
"""
Regenerate embeddings for AWS RDS PostgreSQL with pgvector.

This script generates embeddings for all analyses in the database that don't
have embeddings yet, using VoyageAI and storing them in pgvector format.

Usage:
    # Use DATABASE_URL from environment or Parameter Store
    python scripts/regenerate_embeddings_pgvector.py

    # Specify a custom database URL
    python scripts/regenerate_embeddings_pgvector.py --database-url "postgresql://..."

    # Filter by user_id
    python scripts/regenerate_embeddings_pgvector.py --user-id testuser1@example.com

    # Batch size control
    python scripts/regenerate_embeddings_pgvector.py --batch-size 50
"""

import argparse
import sys
import os
import uuid
from typing import List, Dict, Any
import json
from datetime import datetime, UTC

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database_orm.connection import init_connection, get_session, close_connection
from database_orm.models import Analysis, Embedding
from sqlalchemy import text, select
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import VoyageAI
try:
    import voyageai
    VOYAGE_AVAILABLE = True
except ImportError:
    VOYAGE_AVAILABLE = False
    print("Warning: voyageai not installed. Install with: pip install voyageai")


def get_embedding_model():
    """Get VoyageAI embedding model configuration."""
    model_name = os.getenv("VOYAGE_EMBEDDING_MODEL", "voyage-3.5-lite")
    dimensions = int(os.getenv("VOYAGE_EMBEDDING_DIMENSIONS", "1024"))

    # Override for voyage-3.5-lite which has 1024 dimensions
    if model_name == "voyage-3.5-lite":
        dimensions = 1024
    elif model_name == "voyage-3-lite":
        dimensions = 512

    return model_name, dimensions


def generate_embeddings_batch(texts: List[str], model_name: str) -> List[List[float]]:
    """Generate embeddings for a batch of texts using VoyageAI."""
    if not VOYAGE_AVAILABLE:
        raise ImportError("voyageai package not installed")

    api_key = os.getenv("VOYAGE_API_KEY")
    if not api_key:
        raise ValueError("VOYAGE_API_KEY not set in environment")

    client = voyageai.Client(api_key=api_key)

    # Generate embeddings
    result = client.embed(
        texts=texts,
        model=model_name,
        input_type="document"  # For storing/indexing
    )

    return result.embeddings


def get_text_for_embedding(analysis: Analysis) -> str:
    """Extract text from analysis for embedding generation."""
    parts = []

    # Add category
    if analysis.category:
        parts.append(f"Category: {analysis.category}")

    # Add summary
    if analysis.summary:
        parts.append(f"Summary: {analysis.summary}")

    # Extract key fields from raw_response if available
    if analysis.raw_response:
        if isinstance(analysis.raw_response, dict):
            # Extract specific fields that are useful for search
            for field in ['title', 'description', 'tags', 'key_points']:
                if field in analysis.raw_response:
                    value = analysis.raw_response[field]
                    if isinstance(value, list):
                        parts.append(f"{field}: {', '.join(str(v) for v in value)}")
                    else:
                        parts.append(f"{field}: {value}")

    return "\n".join(parts)


def regenerate_embeddings(
    database_url: str = None,
    user_id: str = None,
    batch_size: int = 32,
    force: bool = False
):
    """
    Regenerate embeddings for analyses.

    Args:
        database_url: Database URL (uses env/Parameter Store if not provided)
        user_id: Filter by specific user_id (optional)
        batch_size: Number of embeddings to generate per API call
        force: If True, regenerate all embeddings even if they exist
    """
    print("=" * 70)
    print("Regenerating Embeddings for AWS RDS PostgreSQL (pgvector)")
    print("=" * 70)
    print()

    # Get embedding model config
    model_name, expected_dimensions = get_embedding_model()
    print(f"Embedding Model: {model_name}")
    print(f"Expected Dimensions: {expected_dimensions}")
    print(f"Batch Size: {batch_size}")
    if user_id:
        print(f"User Filter: {user_id}")
    print()

    # Initialize database connection
    engine = init_connection(database_url=database_url)

    with get_session() as session:
        # Build query for analyses without embeddings
        query = select(Analysis)

        if not force:
            # Only get analyses that don't have embeddings
            query = query.outerjoin(
                Embedding,
                Analysis.id == Embedding.analysis_id
            ).where(Embedding.id.is_(None))

        if user_id:
            query = query.where(Analysis.user_id == user_id)

        query = query.order_by(Analysis.created_at)

        analyses = session.execute(query).scalars().all()

        if not analyses:
            print("✓ No analyses need embeddings. All done!")
            close_connection()
            return {
                'total': 0,
                'embedded': 0,
                'skipped': 0,
                'errors': 0
            }

        print(f"Found {len(analyses)} analyses to process")
        print()

        stats = {
            'total': len(analyses),
            'embedded': 0,
            'skipped': 0,
            'errors': 0
        }

        # Process in batches
        for i in range(0, len(analyses), batch_size):
            batch = analyses[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(analyses) + batch_size - 1) // batch_size

            print(f"Processing batch {batch_num}/{total_batches} ({len(batch)} analyses)...")

            # Prepare texts for embedding
            texts = []
            analysis_data = []

            for analysis in batch:
                text = get_text_for_embedding(analysis)
                if text.strip():
                    texts.append(text)
                    analysis_data.append(analysis)
                else:
                    print(f"  ⚠ Skipping analysis {analysis.id[:8]}... (no text content)")
                    stats['skipped'] += 1

            if not texts:
                continue

            try:
                # Generate embeddings
                embeddings = generate_embeddings_batch(texts, model_name)

                # Verify dimensions
                if embeddings and len(embeddings[0]) != expected_dimensions:
                    print(f"  ⚠ Warning: Got {len(embeddings[0])} dimensions, expected {expected_dimensions}")

                # Store embeddings
                for analysis, embedding_vector in zip(analysis_data, embeddings):
                    try:
                        # Create embedding source metadata
                        embedding_source = {
                            'fields': ['category', 'summary', 'raw_response'],
                            'generated_at': datetime.now(UTC).isoformat()
                        }

                        # Create embedding record
                        embedding = Embedding(
                            id=str(uuid.uuid4()),
                            item_id=analysis.item_id,
                            analysis_id=analysis.id,
                            user_id=analysis.user_id,
                            vector=embedding_vector,
                            embedding_model=model_name,
                            embedding_dimensions=len(embedding_vector),
                            embedding_source=embedding_source
                        )

                        session.add(embedding)
                        stats['embedded'] += 1

                    except Exception as e:
                        print(f"  ✗ Error storing embedding for {analysis.id[:8]}...: {e}")
                        stats['errors'] += 1

                # Commit batch
                session.commit()
                print(f"  ✓ Generated {len(embeddings)} embeddings")

            except Exception as e:
                print(f"  ✗ Error generating embeddings for batch: {e}")
                stats['errors'] += len(texts)
                session.rollback()

        print()
        print("=" * 70)
        print("Embedding Generation Complete")
        print("=" * 70)
        print(f"Total analyses: {stats['total']}")
        print(f"Embeddings generated: {stats['embedded']}")
        print(f"Skipped: {stats['skipped']}")
        print(f"Errors: {stats['errors']}")
        print()

        # Create vector index if we generated embeddings
        if stats['embedded'] > 0:
            print("Creating pgvector index for similarity search...")
            try:
                session.execute(text("""
                    CREATE INDEX IF NOT EXISTS embeddings_vector_idx
                    ON embeddings
                    USING ivfflat (vector vector_cosine_ops)
                    WITH (lists = 100)
                """))
                session.commit()
                print("✓ Vector index created successfully")
            except Exception as e:
                print(f"⚠ Could not create vector index: {e}")
                print("  (Index may already exist or need more data)")

    close_connection()
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Regenerate embeddings for AWS RDS PostgreSQL with pgvector"
    )
    parser.add_argument(
        "--database-url",
        help="Database URL (uses env/Parameter Store if not provided)"
    )
    parser.add_argument(
        "--user-id",
        help="Filter by specific user_id"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Number of embeddings per API call (default: 32)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate all embeddings even if they exist"
    )

    args = parser.parse_args()

    try:
        stats = regenerate_embeddings(
            database_url=args.database_url,
            user_id=args.user_id,
            batch_size=args.batch_size,
            force=args.force
        )

        # Exit with error code if there were errors
        if stats['errors'] > 0:
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
