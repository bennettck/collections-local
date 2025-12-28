#!/usr/bin/env python3
"""
DEPRECATED: Regenerate embeddings using Chroma vector store.

This script has been replaced by PostgreSQL-based vector storage.
ChromaDB is no longer used in this project.

Use scripts/regenerate_pgvector.py instead (if available).

Kept for reference only. Do not use in new code.
---

Regenerate embeddings using Chroma vector store.

This script rebuilds Chroma indexes for prod and/or golden databases.
All embeddings are generated in real-time during analysis, but this script
can be used to rebuild the Chroma index from existing SQLite data.

Usage:
    python scripts/regenerate_embeddings.py [--database prod|golden|both]
"""

import warnings
warnings.warn(
    "regenerate_embeddings.py is deprecated. ChromaDB has been replaced by PGVector.",
    DeprecationWarning,
    stacklevel=2
)

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from retrieval.chroma_manager import ChromaVectorStoreManager
from config.langchain_config import get_chroma_config, DEFAULT_EMBEDDING_MODEL
from dotenv import load_dotenv

load_dotenv()


def regenerate_for_database(database_type: str, database_path: str):
    """Rebuild Chroma index for a specific database."""
    print(f"\n{'='*70}")
    print(f"Rebuilding Chroma index for {database_type.upper()} database")
    print(f"{'='*70}\n")

    chroma_config = get_chroma_config(database_type)
    chroma_manager = ChromaVectorStoreManager(
        database_path=database_path,
        persist_directory=chroma_config["persist_directory"],
        collection_name=chroma_config["collection_name"],
        embedding_model=DEFAULT_EMBEDDING_MODEL
    )

    # Delete and rebuild collection
    print("Deleting existing Chroma collection...")
    chroma_manager.delete_collection()

    print("Building new Chroma index...")
    num_docs = chroma_manager.build_index(batch_size=128)

    print(f"✓ Rebuilt Chroma index with {num_docs} documents")

    # Show statistics
    print("\nStatistics:")
    print("-" * 70)
    stats = chroma_manager.get_collection_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rebuild Chroma vector indexes")
    parser.add_argument(
        "--database",
        choices=["prod", "golden", "both"],
        default="both",
        help="Which database to rebuild (default: both)"
    )
    args = parser.parse_args()

    # Get database paths
    prod_db_path = os.getenv("PROD_DATABASE_PATH", "./data/collections.db")
    golden_db_path = os.getenv("GOLDEN_DATABASE_PATH", "./data/collections_golden.db")

    if args.database in ["prod", "both"]:
        regenerate_for_database("prod", prod_db_path)

    if args.database in ["golden", "both"]:
        regenerate_for_database("golden", golden_db_path)

    print("\n✓ All Chroma indexes rebuilt successfully!")
