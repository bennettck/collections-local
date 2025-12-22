#!/usr/bin/env python3
"""
Full migration script to LangChain RAG pipeline.

This script:
1. Builds BM25 indexes (in-memory) for both prod and golden databases
2. Builds Chroma vector stores for both prod and golden databases
3. Tests both retrievers

Usage:
    python scripts/migrate_to_langchain.py [--batch-size 128] [--skip-test]
"""

import sys
import os
import argparse
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from retrieval.langchain_native_retrievers import LangChainNativeBM25Retriever
from retrieval.chroma_manager import ChromaVectorStoreManager
from config.langchain_config import get_chroma_config, DEFAULT_EMBEDDING_MODEL


def build_indexes_for_database(
    database_type: str,
    batch_size: int = 128,
    skip_test: bool = False
):
    """Build BM25 and Chroma indexes for a specific database.

    Args:
        database_type: Either "prod" or "golden"
        batch_size: Batch size for indexing
        skip_test: Skip test queries
    """
    print(f"\n{'='*60}")
    print(f"Building indexes for {database_type.upper()} database")
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

    # 1. Build BM25 index (in-memory)
    print("Step 1: Building BM25 index (in-memory)...")
    print("-" * 60)
    bm25_retriever = LangChainNativeBM25Retriever(
        database_path=database_path,
        top_k=10,
        preload=True
    )
    print("✓ BM25 index built successfully")
    print()

    # 2. Build Chroma vector store
    print("Step 2: Building Chroma vector store...")
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

    # 4. Test retrievers
    if not skip_test:
        print("Step 3: Testing retrievers...")
        print("-" * 60)

        test_query = "Tokyo restaurants"
        print(f"Test query: '{test_query}'")
        print()

        # Test BM25
        print("BM25 Results:")
        bm25_docs = bm25_retriever.invoke(test_query)
        for i, doc in enumerate(bm25_docs[:3], 1):
            print(f"  {i}. {doc.metadata.get('headline', 'No headline')}")
            print(f"     Category: {doc.metadata.get('category')}")
            print(f"     Item ID: {doc.metadata.get('item_id')}")
        print()

        # Test Chroma
        print("Chroma Results:")
        chroma_docs = chroma_manager.similarity_search(test_query, k=10)
        for i, doc in enumerate(chroma_docs[:3], 1):
            print(f"  {i}. {doc.metadata.get('headline', 'No headline')}")
            print(f"     Category: {doc.metadata.get('category')}")
            print(f"     Item ID: {doc.metadata.get('item_id')}")
        print()

        print("✓ Both retrievers working correctly")
        print()


def main():
    """Run full migration."""
    parser = argparse.ArgumentParser(
        description="Migrate to LangChain RAG pipeline (BM25 + Chroma)"
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
    print("LangChain RAG Pipeline Migration")
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
    print("Migration Complete!")
    print("="*60)
    print("\nNext steps:")
    print("  1. Update main.py to use new retrievers")
    print("  2. Test endpoints: /search with search_type='bm25-lc' and 'vector-lc'")
    print("  3. Compare results with old implementations")
    print()


if __name__ == "__main__":
    main()
