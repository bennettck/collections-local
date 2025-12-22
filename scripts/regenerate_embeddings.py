#!/usr/bin/env python3
"""
Regenerate ALL embeddings with new flat document approach (no field weighting).

This script:
1. Deletes existing embeddings from sqlite-vec (vector search)
2. Regenerates embeddings using the new flat document approach
3. Rebuilds Chroma indexes (vector-lc) with same approach

This ensures consistency across all vector search methods.

Usage:
    python scripts/regenerate_embeddings.py [--database prod|golden|both]
"""

import sys
import os
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_db, rebuild_vector_index, database_context, init_vector_table
from retrieval.chroma_manager import ChromaVectorStoreManager
from config.langchain_config import get_chroma_config, DEFAULT_EMBEDDING_MODEL
from dotenv import load_dotenv

load_dotenv()


def delete_all_embeddings(database_path: str) -> int:
    """Delete all existing embeddings from the database.

    Args:
        database_path: Path to the database

    Returns:
        Number of embeddings deleted
    """
    with database_context(database_path):
        with get_db() as conn:
            cursor = conn.cursor()

            # Count existing embeddings
            count = cursor.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]

            # Drop and recreate vec_items virtual table (more reliable than DELETE)
            cursor.execute("DROP TABLE IF EXISTS vec_items")

            # Delete from embeddings (metadata table)
            cursor.execute("DELETE FROM embeddings")
            conn.commit()

    # Recreate the vec_items table
    # Note: Using 1024 dimensions because voyage-3.5-lite actually returns 1024-dim embeddings
    with database_context(database_path):
        init_vector_table(embedding_dimensions=1024)

    return count


def regenerate_for_database(database_type: str, database_path: str):
    """Regenerate embeddings for a specific database.

    Args:
        database_type: Either "prod" or "golden"
        database_path: Path to the database file
    """
    print(f"\n{'='*70}")
    print(f"Regenerating embeddings for {database_type.upper()} database")
    print(f"{'='*70}\n")
    print(f"Database path: {database_path}")
    print()

    # Step 1: Delete existing embeddings
    print("Step 1: Deleting existing embeddings from sqlite-vec...")
    print("-" * 70)
    deleted_count = delete_all_embeddings(database_path)
    print(f"✓ Deleted {deleted_count} existing embeddings")
    print()

    # Step 2: Regenerate embeddings for sqlite-vec (vector search)
    print("Step 2: Regenerating embeddings for sqlite-vec (vector search)...")
    print("-" * 70)
    with database_context(database_path):
        result = rebuild_vector_index(
            embedding_model=DEFAULT_EMBEDDING_MODEL,  # voyage-3.5-lite (512 dims)
            batch_size=128
        )
    print(f"✓ Generated {result['embedded_count']} new embeddings")
    print(f"  (Skipped {result['skipped_count']}, Total processed: {result['total_processed']})")
    print()

    # Step 3: Rebuild Chroma index (vector-lc)
    print("Step 3: Rebuilding Chroma index (vector-lc)...")
    print("-" * 70)

    chroma_config = get_chroma_config(database_type)
    chroma_manager = ChromaVectorStoreManager(
        database_path=database_path,
        persist_directory=chroma_config["persist_directory"],
        collection_name=chroma_config["collection_name"],
        embedding_model=DEFAULT_EMBEDDING_MODEL
    )

    # Delete and rebuild Chroma
    print("  Deleting existing Chroma collection...")
    chroma_manager.delete_collection()

    print(f"  Building new Chroma index...")
    num_docs = chroma_manager.build_index(batch_size=128)
    print(f"✓ Chroma index built with {num_docs} documents")
    print()

    # Step 4: Show statistics
    print("Statistics:")
    print("-" * 70)
    stats = chroma_manager.get_collection_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    print()

    print(f"✓ {database_type.upper()} database: All embeddings regenerated successfully!")
    print()


def main():
    """Main execution."""
    parser = argparse.ArgumentParser(
        description="Regenerate ALL embeddings with new flat document approach"
    )
    parser.add_argument(
        "--database",
        choices=["prod", "golden", "both"],
        default="both",
        help="Which database(s) to regenerate (default: both)"
    )

    args = parser.parse_args()

    # Get database paths
    prod_db_path = os.getenv("PROD_DATABASE_PATH", "./data/collections.db")
    golden_db_path = os.getenv("GOLDEN_DATABASE_PATH", "./data/collections_golden.db")

    print("\n" + "="*70)
    print("EMBEDDING REGENERATION - Flat Document Approach (No Field Weighting)")
    print("="*70)
    print()
    print("This will:")
    print("  1. Delete ALL existing embeddings from sqlite-vec")
    print("  2. Regenerate embeddings using flat documents (no field weighting)")
    print("  3. Rebuild Chroma indexes with same approach")
    print()
    print("This ensures ALL vector search methods use the same unweighted data.")
    print()

    # Regenerate based on database choice
    if args.database in ["prod", "both"]:
        regenerate_for_database("prod", prod_db_path)

    if args.database in ["golden", "both"]:
        regenerate_for_database("golden", golden_db_path)

    print("\n" + "="*70)
    print("REGENERATION COMPLETE!")
    print("="*70)
    print()
    print("All vector search methods now use the same unweighted data:")
    print("  - vector (sqlite-vec): ✓ Fresh embeddings (no field weighting)")
    print("  - vector-lc (Chroma):  ✓ Fresh embeddings (no field weighting)")
    print()
    print("Next steps:")
    print("  1. Test search quality: python scripts/evaluate_retrieval.py")
    print("  2. Compare with previous results")
    print()


if __name__ == "__main__":
    main()
