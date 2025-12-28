"""
DEPRECATED: Migration helper to migrate from ChromaDB to PostgreSQL PGVector.

This module was used for the one-time migration from ChromaDB to PGVector.
The migration has been completed and this module is no longer needed.

Kept for reference only. Do not use in new code.
"""

import warnings
warnings.warn(
    "vector_migration is deprecated. Migration to PGVector is complete.",
    DeprecationWarning,
    stacklevel=2
)

"""
Migration helper to migrate from ChromaDB to PostgreSQL PGVector.

Reads data from existing ChromaDB collections and imports into PostgreSQL.
"""

import logging
import json
from typing import List, Optional, Dict, Any
from pathlib import Path

try:
    from langchain_chroma import Chroma
    import chromadb
except ImportError:
    # langchain_chroma/chromadb not available - ChromaDB support disabled
    Chroma = None
    chromadb = None
from langchain_voyageai import VoyageAIEmbeddings
from langchain_core.documents import Document

from retrieval.pgvector_store import PGVectorStoreManager
from retrieval.postgres_bm25 import PostgresBM25Retriever

logger = logging.getLogger(__name__)


class VectorMigrationHelper:
    """Helper class to migrate from ChromaDB to PostgreSQL PGVector."""

    def __init__(
        self,
        chroma_persist_directory: str = "./data/chroma_prod",
        chroma_collection_name: str = "collections_vectors",
        pgvector_connection_string: Optional[str] = None,
        pgvector_collection_name: str = "collections_vectors",
        postgres_bm25_table_name: str = "collections_documents",
        embedding_model: str = "voyage-3.5-lite",
        use_parameter_store: bool = True,
        parameter_name: str = "/collections-local/rds/connection-string",
        batch_size: int = 100,
        default_user_id: Optional[str] = None
    ):
        """Initialize migration helper.

        Args:
            chroma_persist_directory: ChromaDB persistence directory
            chroma_collection_name: ChromaDB collection name
            pgvector_connection_string: PostgreSQL connection string
            pgvector_collection_name: PGVector collection name
            postgres_bm25_table_name: PostgreSQL BM25 table name
            embedding_model: VoyageAI model name
            use_parameter_store: Whether to use AWS Parameter Store
            parameter_name: Parameter Store parameter name
            batch_size: Batch size for migration
            default_user_id: Default user_id to add to all documents (for user isolation)
        """
        self.chroma_persist_directory = chroma_persist_directory
        self.chroma_collection_name = chroma_collection_name
        self.batch_size = batch_size
        self.default_user_id = default_user_id

        # Initialize ChromaDB client (source)
        logger.info(f"Connecting to ChromaDB at {chroma_persist_directory}")
        self.chroma_client = chromadb.PersistentClient(path=chroma_persist_directory)

        # Initialize VoyageAI embeddings
        import os
        voyage_api_key = os.getenv("VOYAGE_API_KEY")
        if not voyage_api_key:
            raise ValueError("VOYAGE_API_KEY environment variable not set")

        self.embeddings = VoyageAIEmbeddings(
            voyage_api_key=voyage_api_key,
            model=embedding_model
        )

        # Initialize source ChromaDB collection
        self.chroma_collection = Chroma(
            client=self.chroma_client,
            collection_name=chroma_collection_name,
            embedding_function=self.embeddings
        )

        # Initialize PGVector target
        logger.info("Initializing PGVector target")
        self.pgvector_manager = PGVectorStoreManager(
            connection_string=pgvector_connection_string,
            collection_name=pgvector_collection_name,
            embedding_model=embedding_model,
            use_parameter_store=use_parameter_store,
            parameter_name=parameter_name
        )

        # Initialize PostgreSQL BM25 target
        logger.info("Initializing PostgreSQL BM25 target")
        self.postgres_bm25 = PostgresBM25Retriever(
            connection_string=pgvector_connection_string,
            use_parameter_store=use_parameter_store,
            parameter_name=parameter_name,
            table_name=postgres_bm25_table_name
        )

        # Create BM25 table if it doesn't exist
        self.postgres_bm25.create_table_if_not_exists()

    def migrate_all_documents(self) -> Dict[str, Any]:
        """Migrate all documents from ChromaDB to PostgreSQL.

        Returns:
            Dictionary with migration statistics
        """
        logger.info("Starting migration from ChromaDB to PostgreSQL")

        try:
            # Get all documents from ChromaDB
            collection = self.chroma_client.get_collection(name=self.chroma_collection_name)

            # Get all data from collection
            results = collection.get(
                include=["documents", "metadatas", "embeddings"]
            )

            total_docs = len(results["ids"])
            logger.info(f"Found {total_docs} documents in ChromaDB")

            if total_docs == 0:
                return {
                    "status": "success",
                    "total_documents": 0,
                    "migrated_to_pgvector": 0,
                    "migrated_to_bm25": 0,
                    "errors": []
                }

            # Process documents in batches
            migrated_pgvector = 0
            migrated_bm25 = 0
            errors = []

            for i in range(0, total_docs, self.batch_size):
                batch_end = min(i + self.batch_size, total_docs)
                logger.info(f"Processing batch {i//self.batch_size + 1}: documents {i+1}-{batch_end}")

                # Extract batch
                batch_ids = results["ids"][i:batch_end]
                batch_documents = results["documents"][i:batch_end]
                batch_metadatas = results["metadatas"][i:batch_end]
                batch_embeddings = results["embeddings"][i:batch_end]

                # Create LangChain Documents
                documents = []
                for doc_id, content, metadata, embedding in zip(
                    batch_ids, batch_documents, batch_metadatas, batch_embeddings
                ):
                    # Add user_id to metadata if provided
                    if self.default_user_id and "user_id" not in metadata:
                        metadata["user_id"] = self.default_user_id

                    doc = Document(
                        page_content=content,
                        metadata=metadata
                    )
                    documents.append(doc)

                try:
                    # Migrate to PGVector
                    self.pgvector_manager.add_documents(documents, ids=batch_ids)
                    migrated_pgvector += len(documents)
                    logger.info(f"Migrated {len(documents)} documents to PGVector")

                    # Migrate to PostgreSQL BM25
                    for doc_id, doc in zip(batch_ids, documents):
                        item_id = doc.metadata.get("item_id", doc_id)
                        self.postgres_bm25.add_document(
                            item_id=item_id,
                            content=doc.page_content,
                            metadata=doc.metadata
                        )
                        migrated_bm25 += 1

                    logger.info(f"Migrated {len(documents)} documents to PostgreSQL BM25")

                except Exception as e:
                    error_msg = f"Failed to migrate batch {i//self.batch_size + 1}: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)

            # Get final statistics
            pgvector_stats = self.pgvector_manager.get_collection_stats()
            bm25_stats = self.postgres_bm25.get_table_stats()

            migration_stats = {
                "status": "success" if not errors else "partial",
                "total_documents": total_docs,
                "migrated_to_pgvector": migrated_pgvector,
                "migrated_to_bm25": migrated_bm25,
                "pgvector_final_count": pgvector_stats.get("document_count", 0),
                "bm25_final_count": bm25_stats.get("document_count", 0),
                "errors": errors
            }

            logger.info(f"Migration completed: {migration_stats}")
            return migration_stats

        except Exception as e:
            logger.error(f"Migration failed: {e}")
            return {
                "status": "failed",
                "error": str(e)
            }

    def validate_migration(self, test_queries: List[str], top_k: int = 5) -> Dict[str, Any]:
        """Validate migration by comparing search results.

        Args:
            test_queries: List of test queries to validate
            top_k: Number of results to compare

        Returns:
            Dictionary with validation statistics
        """
        logger.info(f"Validating migration with {len(test_queries)} test queries")

        validation_results = []

        for query in test_queries:
            try:
                # Search ChromaDB
                chroma_results = self.chroma_collection.similarity_search(query, k=top_k)
                chroma_ids = [doc.metadata.get("item_id") for doc in chroma_results]

                # Search PGVector
                pgvector_results = self.pgvector_manager.similarity_search(query, k=top_k)
                pgvector_ids = [doc.metadata.get("item_id") for doc in pgvector_results]

                # Calculate overlap
                overlap = len(set(chroma_ids) & set(pgvector_ids))
                overlap_percentage = (overlap / top_k) * 100 if top_k > 0 else 0

                validation_results.append({
                    "query": query,
                    "chroma_ids": chroma_ids,
                    "pgvector_ids": pgvector_ids,
                    "overlap": overlap,
                    "overlap_percentage": overlap_percentage
                })

                logger.info(
                    f"Query: '{query}' - Overlap: {overlap}/{top_k} ({overlap_percentage:.1f}%)"
                )

            except Exception as e:
                logger.error(f"Validation failed for query '{query}': {e}")
                validation_results.append({
                    "query": query,
                    "error": str(e)
                })

        # Calculate average overlap
        valid_results = [r for r in validation_results if "error" not in r]
        avg_overlap = sum(r["overlap_percentage"] for r in valid_results) / len(valid_results) if valid_results else 0

        return {
            "total_queries": len(test_queries),
            "successful_queries": len(valid_results),
            "failed_queries": len(test_queries) - len(valid_results),
            "average_overlap_percentage": avg_overlap,
            "detailed_results": validation_results
        }

    def get_migration_stats(self) -> Dict[str, Any]:
        """Get current migration statistics.

        Returns:
            Dictionary with current stats
        """
        try:
            # ChromaDB stats
            chroma_collection = self.chroma_client.get_collection(
                name=self.chroma_collection_name
            )
            chroma_count = chroma_collection.count()

            # PGVector stats
            pgvector_stats = self.pgvector_manager.get_collection_stats()

            # PostgreSQL BM25 stats
            bm25_stats = self.postgres_bm25.get_table_stats()

            return {
                "chroma_document_count": chroma_count,
                "pgvector_document_count": pgvector_stats.get("document_count", 0),
                "bm25_document_count": bm25_stats.get("document_count", 0),
                "chroma_collection": self.chroma_collection_name,
                "pgvector_collection": pgvector_stats.get("collection_name"),
                "bm25_table": bm25_stats.get("table_name")
            }

        except Exception as e:
            logger.error(f"Failed to get migration stats: {e}")
            return {"error": str(e)}


def main():
    """Main function for running migration as a script."""
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Migrate ChromaDB to PostgreSQL PGVector")
    parser.add_argument(
        "--chroma-dir",
        default="./data/chroma_prod",
        help="ChromaDB persistence directory"
    )
    parser.add_argument(
        "--chroma-collection",
        default="collections_vectors",
        help="ChromaDB collection name"
    )
    parser.add_argument(
        "--pgvector-collection",
        default="collections_vectors",
        help="PGVector collection name"
    )
    parser.add_argument(
        "--bm25-table",
        default="collections_documents",
        help="PostgreSQL BM25 table name"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Batch size for migration"
    )
    parser.add_argument(
        "--user-id",
        help="Default user_id to add to all documents"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run validation after migration"
    )
    parser.add_argument(
        "--test-queries",
        nargs="+",
        default=["food", "art", "nature"],
        help="Test queries for validation"
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Create migration helper
    helper = VectorMigrationHelper(
        chroma_persist_directory=args.chroma_dir,
        chroma_collection_name=args.chroma_collection,
        pgvector_collection_name=args.pgvector_collection,
        postgres_bm25_table_name=args.bm25_table,
        batch_size=args.batch_size,
        default_user_id=args.user_id
    )

    # Run migration
    logger.info("=" * 80)
    logger.info("Starting ChromaDB to PostgreSQL migration")
    logger.info("=" * 80)

    stats = helper.migrate_all_documents()

    logger.info("=" * 80)
    logger.info("Migration Statistics:")
    logger.info(json.dumps(stats, indent=2))
    logger.info("=" * 80)

    # Run validation if requested
    if args.validate:
        logger.info("=" * 80)
        logger.info("Running validation")
        logger.info("=" * 80)

        validation = helper.validate_migration(args.test_queries)

        logger.info("=" * 80)
        logger.info("Validation Results:")
        logger.info(json.dumps(validation, indent=2))
        logger.info("=" * 80)


if __name__ == "__main__":
    main()
