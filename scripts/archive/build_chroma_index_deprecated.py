#!/usr/bin/env python3
"""
DEPRECATED: Build Chroma vector index from database analyses.

This script has been replaced by PostgreSQL-based vector storage.
ChromaDB is no longer used in this project.

Kept for reference only. Do not use in new code.
---

Build Chroma vector index from database analyses.

This script builds a Chroma vector store from the SQLite database.
Supports both production and golden databases.

Usage:
    python scripts/build_chroma_index.py [--database prod|golden] [--batch-size 128]
"""

import warnings
warnings.warn(
    "build_chroma_index.py is deprecated. ChromaDB has been replaced by PGVector.",
    DeprecationWarning,
    stacklevel=2
)

import sys
import os
import argparse
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from retrieval.chroma_manager import ChromaVectorStoreManager
from config.langchain_config import get_chroma_config, DEFAULT_EMBEDDING_MODEL


def main():
    """Build Chroma index."""
    parser = argparse.ArgumentParser(
        description="Build Chroma vector index from database"
    )
    parser.add_argument(
        "--database",
        choices=["prod", "golden"],
        default="prod",
        help="Database to index (prod or golden)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=128,
        help="Batch size for indexing"
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Delete existing collection before building"
    )

    args = parser.parse_args()

    # Get database path
    if args.database == "golden":
        database_path = os.getenv(
            "GOLDEN_DATABASE_PATH",
            "./data/collections_golden.db"
        )
    else:
        database_path = os.getenv(
            "PROD_DATABASE_PATH",
            "./data/collections.db"
        )

    # Get Chroma configuration
    chroma_config = get_chroma_config(args.database)

    print(f"Building Chroma index for {args.database} database")
    print(f"Database path: {database_path}")
    print(f"Persist directory: {chroma_config['persist_directory']}")
    print(f"Collection name: {chroma_config['collection_name']}")
    print(f"Batch size: {args.batch_size}")
    print()

    # Initialize Chroma manager
    chroma = ChromaVectorStoreManager(
        database_path=database_path,
        persist_directory=chroma_config["persist_directory"],
        collection_name=chroma_config["collection_name"],
        embedding_model=DEFAULT_EMBEDDING_MODEL
    )

    # Delete existing collection if rebuild requested
    if args.rebuild:
        print("Deleting existing collection...")
        chroma.delete_collection()
        print()

    # Build index
    print("Building index...")
    num_docs = chroma.build_index(batch_size=args.batch_size)

    print()
    print(f"✓ Successfully indexed {num_docs} documents")

    # Show stats
    stats = chroma.get_collection_stats()
    print("\nCollection Stats:")
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
