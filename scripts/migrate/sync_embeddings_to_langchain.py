#!/usr/bin/env python3
"""
Sync embeddings from ORM table to langchain-postgres vector store.

This script copies existing embeddings from the SQLAlchemy ORM 'embeddings' table
to the langchain-postgres vector store tables so that retrievers can find them.

The issue being fixed:
- Embedder Lambda stores embeddings in the ORM 'embeddings' table
- Retrievers query from langchain-postgres 'langchain_pg_embedding' table
- This script syncs data between the two

Usage:
    python scripts/migrate/sync_embeddings_to_langchain.py [--dry-run] [--user-id USER_ID]
"""

import os
import sys
import logging
import argparse
from typing import Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import select
from langchain_core.documents import Document

from database_orm.connection import init_connection, get_session
from database_orm.models import Embedding, Analysis, Item
from retrieval.pgvector_store import PGVectorStoreManager
from utils.document_builder import create_langchain_document

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def sync_embeddings_to_langchain(
    dry_run: bool = False,
    user_id: Optional[str] = None,
    batch_size: int = 100
) -> dict:
    """
    Sync embeddings from ORM table to langchain-postgres vector store.

    Args:
        dry_run: If True, only report what would be done without making changes
        user_id: Optional user_id filter to sync only specific user's embeddings
        batch_size: Number of embeddings to process per batch

    Returns:
        Dictionary with sync statistics
    """
    # Initialize database connection
    connection_string = os.getenv("DATABASE_URL")
    if not connection_string:
        from database_orm.connection import get_connection_string
        connection_string = get_connection_string()

    init_connection(database_url=connection_string)

    # Initialize PGVectorStoreManager
    voyage_api_key = os.getenv("VOYAGE_API_KEY")
    if not voyage_api_key:
        raise ValueError("VOYAGE_API_KEY environment variable required")

    pgvector_manager = PGVectorStoreManager(
        connection_string=connection_string,
        collection_name="collections_vectors"
    )

    stats = {
        "total_embeddings": 0,
        "synced": 0,
        "skipped": 0,
        "errors": 0,
        "dry_run": dry_run
    }

    with get_session() as session:
        # Build query for embeddings with their analyses
        stmt = select(Embedding, Analysis, Item).join(
            Analysis, Embedding.analysis_id == Analysis.id
        ).join(
            Item, Embedding.item_id == Item.id
        )

        if user_id:
            stmt = stmt.filter(Embedding.user_id == user_id)
            logger.info(f"Filtering by user_id: {user_id}")

        results = session.execute(stmt).all()
        stats["total_embeddings"] = len(results)

        logger.info(f"Found {len(results)} embeddings to sync")

        if dry_run:
            logger.info("[DRY RUN] Would sync the following embeddings:")
            for embedding, analysis, item in results[:10]:  # Show first 10
                logger.info(f"  - item_id={embedding.item_id}, user_id={embedding.user_id}, category={analysis.category}")
            if len(results) > 10:
                logger.info(f"  ... and {len(results) - 10} more")
            return stats

        # Process in batches
        documents = []
        ids = []

        for i, (embedding, analysis, item) in enumerate(results):
            try:
                # Get raw_response from analysis
                raw_response = analysis.raw_response or {}

                # Create LangChain document with proper metadata
                doc = create_langchain_document(
                    raw_response=raw_response,
                    item_id=embedding.item_id,
                    filename=item.filename,
                    category=analysis.category
                )

                # Add user_id to metadata for filtering
                doc.metadata["user_id"] = embedding.user_id
                doc.metadata["analysis_id"] = embedding.analysis_id
                doc.metadata["embedding_id"] = embedding.id
                doc.metadata["headline"] = raw_response.get("headline", "")
                doc.metadata["summary"] = raw_response.get("summary", "")

                documents.append(doc)
                ids.append(embedding.item_id)  # Use item_id as document ID

                # Process batch
                if len(documents) >= batch_size:
                    logger.info(f"Processing batch of {len(documents)} documents...")
                    pgvector_manager.add_documents(documents, ids=ids)
                    stats["synced"] += len(documents)
                    documents = []
                    ids = []

            except Exception as e:
                logger.error(f"Error syncing embedding {embedding.id}: {e}")
                stats["errors"] += 1

        # Process remaining documents
        if documents:
            logger.info(f"Processing final batch of {len(documents)} documents...")
            pgvector_manager.add_documents(documents, ids=ids)
            stats["synced"] += len(documents)

    logger.info(f"Sync complete: {stats}")
    return stats


def main():
    parser = argparse.ArgumentParser(description="Sync embeddings to langchain-postgres")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    parser.add_argument("--user-id", type=str, help="Only sync embeddings for specific user")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size for processing")

    args = parser.parse_args()

    stats = sync_embeddings_to_langchain(
        dry_run=args.dry_run,
        user_id=args.user_id,
        batch_size=args.batch_size
    )

    print(f"\nSync Statistics:")
    print(f"  Total embeddings: {stats['total_embeddings']}")
    print(f"  Synced: {stats['synced']}")
    print(f"  Errors: {stats['errors']}")
    if stats['dry_run']:
        print("  (DRY RUN - no changes made)")


if __name__ == "__main__":
    main()
