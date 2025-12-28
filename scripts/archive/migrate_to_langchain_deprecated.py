#!/usr/bin/env python3
"""
DEPRECATED: Migration script to build Chroma vector stores.

This script has been replaced by PostgreSQL-based vector storage.
ChromaDB is no longer used in this project.

Kept for reference only. Do not use in new code.
---

Migration script to build Chroma vector stores.

This script:
1. Builds Chroma vector stores for both prod and golden databases
2. Tests vector retrieval

Note: BM25 search uses SQLite FTS5 directly (no separate indexing required)

Usage:
    python scripts/migrate_to_langchain.py [--batch-size 128] [--skip-test]
"""

import warnings
warnings.warn(
    "migrate_to_langchain.py is deprecated. ChromaDB has been replaced by PGVector.",
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


def build_indexes_for_database(
    database_type: str,
    batch_size: int = 128,
    skip_test: bool = False
):
    """Build Chroma vector store for a specific database.

    Args:
        database_type: Either "prod" or "golden"
        batch_size: Batch size for indexing
        skip_test: Skip test queries
    """
    print(f"\n{'='*60}")
    print(f"Building Chroma index for {database_type.upper()} database")
    print(f"{'='*60}\n")

    # Get database path
    if database_type == "golden":
        database_path = os.getenv(
            "GOLDEN_DATABASE_PATH",
            "./data/collections_golden.db"
        )
    else:
        database_path = os.getenv(
            "PROD_DATABASE_PATH",
            "./data/collections.db"
        )

    print(f"Database path: {database_path}")
    print()

    # Build Chroma vector store
    print("Building Chroma vector store...")
    print("-" * 60)

    chroma_config = get_chroma_config(database_type)
    chroma_manager = ChromaVectorStoreManager(
        database_path=database_path,
        persist_directory=chroma_config["persist_directory"],
        collection_name=chroma_config["collection_name"],
        embedding_model=DEFAULT_EMBEDDING_MODEL
    )

    # Delete existing collection for fresh start
    print("Deleting existing collection...")
    chroma_manager.delete_collection()

    print(f"Building index with batch_size={batch_size}...")
    num_docs = chroma_manager.build_index(batch_size=batch_size)
    print(f"✓ Chroma index built with {num_docs} documents")
    print()

    # 3. Show stats
    print("Collection Stats:")
    print("-" * 60)
    stats = chroma_manager.get_collection_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    print()

    # 4. Test retriever
    if not skip_test:
        print("Testing retriever...")
        print("-" * 60)

        test_query = "Tokyo restaurants"
        print(f"Test query: '{test_query}'")
        print()

        # Test Chroma
        print("Chroma Results:")
        chroma_docs = chroma_manager.similarity_search(test_query, k=10)
        for i, doc in enumerate(chroma_docs[:3], 1):
            print(f"  {i}. {doc.metadata.get('headline', 'No headline')}")
            print(f"     Category: {doc.metadata.get('category')}")
            print(f"     Item ID: {doc.metadata.get('item_id')}")
        print()

        print("✓ Chroma retriever working correctly")
        print()


def main():
    """Build Chroma vector stores."""
    parser = argparse.ArgumentParser(
        description="Build Chroma vector stores for collections databases"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=128,
        help="Batch size for indexing"
    )
    parser.add_argument(
        "--skip-test",
        action="store_true",
        help="Skip test queries"
    )
    parser.add_argument(
        "--database",
        choices=["prod", "golden", "both"],
        default="both",
        help="Which database(s) to migrate"
    )

    args = parser.parse_args()

    print("\n" + "="*60)
    print("Chroma Vector Store Build")
    print("="*60)

    # Build indexes based on database choice
    if args.database in ["prod", "both"]:
        build_indexes_for_database(
            database_type="prod",
            batch_size=args.batch_size,
            skip_test=args.skip_test
        )

    if args.database in ["golden", "both"]:
        build_indexes_for_database(
            database_type="golden",
            batch_size=args.batch_size,
            skip_test=args.skip_test
        )

    print("\n" + "="*60)
    print("Build Complete!")
    print("="*60)
    print("\nNext steps:")
    print("  1. Test endpoints: /search with search_type='vector-lc' and 'hybrid-lc'")
    print("  2. BM25 search uses SQLite FTS5 (no separate indexing needed)")
    print("  3. Hybrid search combines BM25 + Chroma with RRF")
    print()


if __name__ == "__main__":
    main()
