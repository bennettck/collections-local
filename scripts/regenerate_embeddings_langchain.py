#!/usr/bin/env python3
"""
Regenerate embeddings using PGVectorStoreManager (langchain-postgres).

This script generates embeddings for all analyses and stores them in the
langchain_pg_embedding table (where search queries read from).

IMPORTANT: This replaces regenerate_embeddings_pgvector.py which incorrectly
wrote to the 'embeddings' ORM table instead of 'langchain_pg_embedding'.

Usage:
    # Regenerate for specific user
    python scripts/regenerate_embeddings_langchain.py --user-id 94c844d8-10c1-70dd-80e3-4a88742efbb6

    # Regenerate for all users
    python scripts/regenerate_embeddings_langchain.py --all-users

    # Custom batch size
    python scripts/regenerate_embeddings_langchain.py --user-id UUID --batch-size 50
"""

import argparse
import sys
import os
from typing import List, Dict, Any
from datetime import datetime, UTC

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database_orm.connection import init_connection, get_session, close_connection
from database_orm.models import Analysis, Item
from retrieval.pgvector_store import PGVectorStoreManager
from sqlalchemy import text, select

# Import VoyageAI
try:
    import voyageai
    VOYAGE_AVAILABLE = True
except ImportError:
    VOYAGE_AVAILABLE = False
    print("Warning: voyageai not installed. Install with: pip install voyageai")


def get_embedding_config():
    """Get embedding model configuration."""
    model_name = os.getenv("VOYAGE_EMBEDDING_MODEL", "voyage-3.5-lite")
    return model_name


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
            for field in ['headline', 'title', 'description', 'tags', 'key_points']:
                if field in analysis.raw_response:
                    value = analysis.raw_response[field]
                    if isinstance(value, list):
                        parts.append(f"{field}: {', '.join(str(v) for v in value)}")
                    else:
                        parts.append(f"{field}: {value}")

    return "\n".join(parts)


def regenerate_embeddings(
    user_id: str = None,
    all_users: bool = False,
    batch_size: int = 32,
    force: bool = False
):
    """
    Regenerate embeddings using PGVectorStoreManager.

    Args:
        user_id: Filter by specific user_id (optional)
        all_users: Process all users (default: False)
        batch_size: Number of embeddings to process per batch
        force: If True, regenerate all embeddings even if they exist
    """
    if not user_id and not all_users:
        print("Error: Must specify --user-id or --all-users")
        return {'total': 0, 'embedded': 0, 'skipped': 0, 'errors': 0}

    print("=" * 70)
    print("Regenerating Embeddings Using PGVectorStoreManager")
    print("=" * 70)
    print()

    # Get embedding model config
    model_name = get_embedding_config()
    print(f"Embedding Model: {model_name}")
    print(f"Batch Size: {batch_size}")
    if user_id:
        print(f"User Filter: {user_id}")
    elif all_users:
        print(f"Processing: ALL USERS")
    print()

    # Initialize PGVectorStoreManager (uses langchain_pg_embedding table)
    print("Initializing PGVectorStoreManager...")
    try:
        from config.langchain_config import get_vector_store_config

        vector_config = get_vector_store_config("prod")
        vector_store_manager = PGVectorStoreManager(
            collection_name=vector_config["collection_name"],
            embedding_model=model_name,
            use_parameter_store=False
        )
        print(f"✓ Connected to collection: {vector_config['collection_name']}")
        print()
    except Exception as e:
        print(f"✗ Failed to initialize PGVectorStoreManager: {e}")
        return {'total': 0, 'embedded': 0, 'skipped': 0, 'errors': 0}

    # Initialize database connection
    engine = init_connection()

    with get_session() as session:
        # Build query for analyses
        query = select(Analysis).join(Item, Analysis.item_id == Item.id)

        if user_id:
            query = query.where(Analysis.user_id == user_id)

        query = query.order_by(Analysis.created_at)

        analyses = session.execute(query).scalars().all()

        if not analyses:
            print("✓ No analyses found to process.")
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

            # Process each analysis in batch
            for analysis in batch:
                try:
                    # Get text for embedding
                    text_content = get_text_for_embedding(analysis)
                    if not text_content.strip():
                        print(f"  ⚠ Skipping analysis {analysis.id[:8]}... (no text content)")
                        stats['skipped'] += 1
                        continue

                    # Get item for filename
                    item = session.get(Item, analysis.item_id)
                    if not item:
                        print(f"  ⚠ Skipping analysis {analysis.id[:8]}... (no item found)")
                        stats['skipped'] += 1
                        continue

                    # Use PGVectorStoreManager.add_document()
                    # This writes to langchain_pg_embedding table (correct!)
                    doc_id = vector_store_manager.add_document(
                        item_id=analysis.item_id,
                        raw_response=analysis.raw_response or {},
                        filename=item.filename or item.file_path or f"item_{analysis.item_id[:8]}",
                        user_id=analysis.user_id
                    )

                    stats['embedded'] += 1

                except Exception as e:
                    print(f"  ✗ Error processing {analysis.id[:8]}...: {e}")
                    stats['errors'] += 1

            print(f"  ✓ Processed batch {batch_num}/{total_batches}")
            print()

        print()
        print("=" * 70)
        print("Embedding Generation Complete")
        print("=" * 70)
        print(f"Total analyses: {stats['total']}")
        print(f"Embeddings generated: {stats['embedded']}")
        print(f"Skipped: {stats['skipped']}")
        print(f"Errors: {stats['errors']}")
        print()

        # Verify embeddings were created
        try:
            with engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT COUNT(*) as count
                    FROM langchain_pg_embedding
                    WHERE cmetadata->>'user_id' = :user_id
                """), {"user_id": user_id if user_id else ""})
                count = result.scalar()
                print(f"✓ Verification: {count} embeddings in langchain_pg_embedding table")
        except Exception as e:
            print(f"⚠ Could not verify embeddings: {e}")

    close_connection()
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Regenerate embeddings using PGVectorStoreManager (langchain-postgres)"
    )
    parser.add_argument(
        "--user-id",
        help="Filter by specific user_id (UUID format)"
    )
    parser.add_argument(
        "--all-users",
        action="store_true",
        help="Process all users (WARNING: may take a long time)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Number of analyses per batch (default: 32)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate all embeddings even if they exist"
    )

    args = parser.parse_args()

    try:
        stats = regenerate_embeddings(
            user_id=args.user_id,
            all_users=args.all_users,
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
