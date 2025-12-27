#!/usr/bin/env python3
"""
ChromaDB to pgvector Migration Script

Migrates vector embeddings from ChromaDB to PostgreSQL pgvector using langchain-postgres.

This script:
1. Reads embeddings from existing ChromaDB collections (data/chroma_prod/)
2. Extracts vectors, documents, and metadata
3. Adds user_id to all metadata
4. Inserts into pgvector using batch operations
5. Validates migration with sample queries

Usage:
    python scripts/migrate/chromadb_to_pgvector.py \\
        --chroma-path ./data/chroma_prod \\
        --collection collections_vectors_prod \\
        --postgres-url postgresql://user:pass@host:5432/collections \\
        --user-id cognito-user-id \\
        --validate

    # With AWS Parameter Store:
    POSTGRES_URL=$(aws ssm get-parameter --name /collections/dev/database-url --query 'Parameter.Value' --output text)

    python scripts/migrate/chromadb_to_pgvector.py \\
        --chroma-path ./data/chroma_prod \\
        --collection collections_vectors_prod \\
        --postgres-url "$POSTGRES_URL" \\
        --user-id "$USER_ID" \\
        --validate
"""

import sys
import os
import json
import argparse
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import chromadb
from chromadb.api import Collection
import numpy as np
from dotenv import load_dotenv

# langchain imports
from langchain_voyageai import VoyageAIEmbeddings
from langchain_core.documents import Document
from langchain_postgres import PGVector
from sqlalchemy import create_engine

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class VectorMigrationStats:
    """Track vector migration statistics."""

    def __init__(self):
        self.vectors_migrated = 0
        self.batches_processed = 0
        self.errors = []
        self.start_time = None
        self.end_time = None
        self.chroma_count = 0
        self.pgvector_count = 0

    def __str__(self):
        duration = (self.end_time - self.start_time).total_seconds() if self.end_time and self.start_time else 0
        return f"""
Vector Migration Statistics:
  ChromaDB vectors: {self.chroma_count}
  Vectors migrated: {self.vectors_migrated}
  pgvector count: {self.pgvector_count}
  Batches processed: {self.batches_processed}
  Errors: {len(self.errors)}
  Duration: {duration:.2f} seconds
"""


def read_chromadb_collection(
    chroma_path: str,
    collection_name: str
) -> Tuple[Collection, List[str], List[List[float]], List[str], List[Dict[str, Any]]]:
    """
    Read all vectors from ChromaDB collection.

    Args:
        chroma_path: Path to ChromaDB persistent directory
        collection_name: Name of collection to read

    Returns:
        Tuple of (collection, ids, embeddings, documents, metadatas)
    """
    logger.info(f"Reading ChromaDB collection: {collection_name}")
    logger.info(f"  Path: {chroma_path}")

    # Initialize ChromaDB client
    client = chromadb.PersistentClient(path=chroma_path)

    # Get collection
    try:
        collection = client.get_collection(name=collection_name)
        logger.info(f"  Found collection: {collection_name}")
    except Exception as e:
        logger.error(f"Collection not found: {collection_name}")
        logger.error(f"Available collections: {[c.name for c in client.list_collections()]}")
        raise

    # Get count
    count = collection.count()
    logger.info(f"  Total vectors: {count}")

    if count == 0:
        logger.warning("Collection is empty!")
        return collection, [], [], [], []

    # Get all data (ChromaDB get() retrieves everything if no limit)
    results = collection.get(
        include=['embeddings', 'documents', 'metadatas']
    )

    ids = results['ids']
    embeddings = results['embeddings']
    documents = results['documents']
    metadatas = results['metadatas']

    logger.info(f"  Retrieved {len(ids)} vectors")
    logger.info(f"  Sample ID: {ids[0] if ids else 'N/A'}")
    logger.info(f"  Embedding dimensions: {len(embeddings[0]) if embeddings and embeddings[0] else 'N/A'}")

    return collection, ids, embeddings, documents, metadatas


def add_user_id_to_metadata(
    metadatas: List[Dict[str, Any]],
    user_id: str
) -> List[Dict[str, Any]]:
    """
    Add user_id to all metadata dictionaries.

    Args:
        metadatas: List of metadata dictionaries
        user_id: Cognito user ID to add

    Returns:
        Updated metadata list
    """
    logger.info(f"Adding user_id to {len(metadatas)} metadata records...")

    updated = []
    for metadata in metadatas:
        updated_metadata = metadata.copy() if metadata else {}
        updated_metadata['user_id'] = user_id
        updated.append(updated_metadata)

    return updated


def create_pgvector_table(postgres_url: str, collection_name: str, vector_dimensions: int):
    """
    Create pgvector table for embeddings.

    Args:
        postgres_url: PostgreSQL connection URL
        collection_name: Name for the pgvector collection
        vector_dimensions: Dimensionality of vectors
    """
    logger.info(f"Creating pgvector table: {collection_name}")

    engine = create_engine(postgres_url)

    with engine.connect() as conn:
        # Enable pgvector extension
        from sqlalchemy import text
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        conn.commit()

        # Drop existing table (for fresh migration)
        logger.warning(f"Dropping existing table: langchain_pg_embedding (if exists)...")
        conn.execute(text("DROP TABLE IF EXISTS langchain_pg_embedding CASCADE;"))
        conn.execute(text("DROP TABLE IF EXISTS langchain_pg_collection CASCADE;"))
        conn.commit()

    logger.info("pgvector extension enabled")


def migrate_to_pgvector(
    postgres_url: str,
    collection_name: str,
    ids: List[str],
    embeddings: List[List[float]],
    documents: List[str],
    metadatas: List[Dict[str, Any]],
    batch_size: int = 100,
    stats: Optional[VectorMigrationStats] = None
) -> VectorMigrationStats:
    """
    Migrate vectors to pgvector using langchain-postgres.

    Args:
        postgres_url: PostgreSQL connection URL
        collection_name: Collection name for pgvector
        ids: List of vector IDs
        embeddings: List of embeddings (vectors)
        documents: List of document text
        metadatas: List of metadata dicts (with user_id)
        batch_size: Batch size for insertion
        stats: Optional VectorMigrationStats to update

    Returns:
        VectorMigrationStats with results
    """
    if stats is None:
        stats = VectorMigrationStats()

    logger.info(f"Starting migration to pgvector (batch_size={batch_size})...")
    logger.info(f"  Total vectors to migrate: {len(ids)}")

    # Get embedding model (needed for PGVector initialization)
    voyage_api_key = os.getenv("VOYAGE_API_KEY")
    if not voyage_api_key:
        raise ValueError("VOYAGE_API_KEY environment variable not set")

    embedding_function = VoyageAIEmbeddings(
        voyage_api_key=voyage_api_key,
        model="voyage-3.5-lite"  # Same model used in ChromaDB
    )

    # Initialize PGVector
    # Note: PGVector will create tables automatically if they don't exist
    logger.info("Initializing PGVector...")

    vectorstore = PGVector(
        embeddings=embedding_function,
        collection_name=collection_name,
        connection=postgres_url,
        use_jsonb=True,  # Use JSONB for metadata
    )

    # Migrate in batches
    logger.info("Migrating vectors in batches...")

    for i in range(0, len(ids), batch_size):
        batch_ids = ids[i:i + batch_size]
        batch_embeddings = embeddings[i:i + batch_size]
        batch_documents = documents[i:i + batch_size]
        batch_metadatas = metadatas[i:i + batch_size]

        # Create LangChain Documents
        docs = []
        for doc_id, embedding, document, metadata in zip(
            batch_ids, batch_embeddings, batch_documents, batch_metadatas
        ):
            # Store original item_id from metadata
            item_id = metadata.get('item_id', doc_id)

            doc = Document(
                page_content=document or "",
                metadata=metadata
            )
            docs.append(doc)

        # Add documents with embeddings
        # PGVector.add_documents will use the embedding_function to re-embed
        # But we want to use our existing embeddings, so we use add_embeddings
        try:
            # Use from_embeddings class method to add with existing embeddings
            vectorstore.add_embeddings(
                texts=[doc.page_content for doc in docs],
                embeddings=batch_embeddings,
                metadatas=[doc.metadata for doc in docs],
                ids=batch_ids
            )

            stats.vectors_migrated += len(batch_ids)
            stats.batches_processed += 1
            logger.info(f"  Migrated {stats.vectors_migrated}/{len(ids)} vectors")

        except Exception as e:
            logger.error(f"Error migrating batch {stats.batches_processed}: {str(e)}")
            stats.errors.append(f"Batch {stats.batches_processed}: {str(e)}")

    logger.info("Vector migration completed")
    return stats


def validate_migration(
    chroma_collection: Collection,
    pgvector_store: PGVector,
    sample_queries: List[str],
    top_k: int = 5,
    similarity_threshold: float = 0.8
) -> bool:
    """
    Validate migration by comparing search results.

    Args:
        chroma_collection: ChromaDB collection
        pgvector_store: PGVector store
        sample_queries: List of queries to test
        top_k: Number of results to compare
        similarity_threshold: Minimum overlap required (0.0-1.0)

    Returns:
        True if validation passes, False otherwise
    """
    logger.info("Validating migration with sample queries...")
    logger.info(f"  Similarity threshold: {similarity_threshold}")

    total_queries = len(sample_queries)
    passed_queries = 0

    for query in sample_queries:
        logger.info(f"  Query: '{query}'")

        # Search ChromaDB
        chroma_results = chroma_collection.query(
            query_texts=[query],
            n_results=top_k,
            include=['metadatas']
        )
        chroma_ids = set(chroma_results['ids'][0]) if chroma_results['ids'] else set()

        # Search pgvector
        pgvector_results = pgvector_store.similarity_search(query, k=top_k)
        pgvector_ids = set(doc.metadata.get('item_id', '') for doc in pgvector_results)

        # Calculate overlap
        overlap = len(chroma_ids & pgvector_ids)
        overlap_ratio = overlap / top_k if top_k > 0 else 0

        logger.info(f"    ChromaDB: {chroma_ids}")
        logger.info(f"    pgvector: {pgvector_ids}")
        logger.info(f"    Overlap: {overlap}/{top_k} ({overlap_ratio:.1%})")

        if overlap_ratio >= similarity_threshold:
            logger.info(f"    ✓ PASS (overlap >= {similarity_threshold:.1%})")
            passed_queries += 1
        else:
            logger.warning(f"    ✗ FAIL (overlap < {similarity_threshold:.1%})")

    # Overall validation
    pass_rate = passed_queries / total_queries if total_queries > 0 else 0
    logger.info(f"\nValidation Results: {passed_queries}/{total_queries} queries passed ({pass_rate:.1%})")

    if pass_rate >= similarity_threshold:
        logger.info("✓ Validation PASSED")
        return True
    else:
        logger.error("✗ Validation FAILED")
        return False


def main():
    """Main migration orchestrator."""
    parser = argparse.ArgumentParser(
        description="Migrate ChromaDB vectors to PostgreSQL pgvector"
    )
    parser.add_argument(
        '--chroma-path',
        required=True,
        help='Path to ChromaDB persistent directory'
    )
    parser.add_argument(
        '--collection',
        required=True,
        help='ChromaDB collection name'
    )
    parser.add_argument(
        '--postgres-url',
        required=True,
        help='PostgreSQL connection URL'
    )
    parser.add_argument(
        '--user-id',
        required=True,
        help='Cognito user ID to add to metadata'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='Batch size for vector insertion'
    )
    parser.add_argument(
        '--validate',
        action='store_true',
        help='Run validation queries after migration'
    )
    parser.add_argument(
        '--pgvector-collection-name',
        default='collections_vectors',
        help='pgvector collection name (default: collections_vectors)'
    )

    args = parser.parse_args()

    # Initialize stats
    stats = VectorMigrationStats()
    stats.start_time = datetime.now()

    try:
        logger.info("=" * 70)
        logger.info("ChromaDB to pgvector Migration")
        logger.info("=" * 70)
        logger.info(f"ChromaDB path: {args.chroma_path}")
        logger.info(f"Collection: {args.collection}")
        logger.info(f"PostgreSQL: {args.postgres_url.split('@')[1] if '@' in args.postgres_url else args.postgres_url}")
        logger.info(f"User ID: {args.user_id}")
        logger.info(f"pgvector collection: {args.pgvector_collection_name}")
        logger.info("=" * 70)

        # Read ChromaDB
        collection, ids, embeddings, documents, metadatas = read_chromadb_collection(
            args.chroma_path,
            args.collection
        )

        stats.chroma_count = len(ids)

        if stats.chroma_count == 0:
            logger.warning("No vectors to migrate!")
            sys.exit(0)

        # Add user_id to metadata
        metadatas = add_user_id_to_metadata(metadatas, args.user_id)

        # Create pgvector table
        vector_dimensions = len(embeddings[0]) if embeddings and embeddings[0] else 1024
        create_pgvector_table(args.postgres_url, args.pgvector_collection_name, vector_dimensions)

        # Migrate to pgvector
        stats = migrate_to_pgvector(
            postgres_url=args.postgres_url,
            collection_name=args.pgvector_collection_name,
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
            batch_size=args.batch_size,
            stats=stats
        )

        # Validate migration
        validation_passed = True
        if args.validate:
            logger.info("\nRunning validation queries...")

            # Sample queries for validation
            sample_queries = [
                "modern furniture",
                "outdoor activities",
                "food photography",
                "vintage items",
                "nature scenes"
            ]

            # Reinitialize pgvector for querying
            voyage_api_key = os.getenv("VOYAGE_API_KEY")
            embedding_function = VoyageAIEmbeddings(
                voyage_api_key=voyage_api_key,
                model="voyage-3.5-lite"
            )

            pgvector_store = PGVector(
                embeddings=embedding_function,
                collection_name=args.pgvector_collection_name,
                connection=args.postgres_url,
                use_jsonb=True,
            )

            # Get pgvector count for stats
            from sqlalchemy import create_engine, text
            engine = create_engine(args.postgres_url)
            with engine.connect() as conn:
                result = conn.execute(text(
                    "SELECT COUNT(*) FROM langchain_pg_embedding"
                ))
                stats.pgvector_count = result.scalar()

            validation_passed = validate_migration(
                collection,
                pgvector_store,
                sample_queries,
                top_k=5,
                similarity_threshold=0.8
            )

        stats.end_time = datetime.now()

        # Print summary
        logger.info("=" * 70)
        logger.info(stats)
        logger.info("=" * 70)

        if validation_passed:
            logger.info("✓ Migration completed successfully!")
            sys.exit(0)
        else:
            logger.error("✗ Migration validation failed!")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Migration failed: {str(e)}", exc_info=True)
        stats.errors.append(str(e))
        stats.end_time = datetime.now()
        logger.error(stats)
        sys.exit(1)


if __name__ == '__main__':
    main()
