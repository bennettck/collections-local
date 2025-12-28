"""
PostgreSQL PGVector store for Collections Local API.

Uses LangChain's langchain-postgres library for vector storage with VoyageAI embeddings.
Replaces ChromaDB with PostgreSQL pgvector for AWS RDS compatibility.
"""

import logging
import json
import os
from typing import List, Optional, Dict, Any

from langchain_postgres import PGVector
from langchain_postgres.vectorstores import PGVector as PGVectorStore
from langchain_voyageai import VoyageAIEmbeddings
from langchain_core.documents import Document

from utils.document_builder import create_flat_document, create_langchain_document

logger = logging.getLogger(__name__)


class PGVectorStoreManager:
    """PostgreSQL PGVector store manager with VoyageAI embeddings.

    Features:
    - PostgreSQL pgvector integration via langchain-postgres
    - LangChain VoyageAIEmbeddings integration
    - Flat document representation (matching ChromaDB approach)
    - Metadata filtering support (user_id isolation)
    - Connection string from AWS Parameter Store
    - Cosine distance for similarity matching
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
        collection_name: str = "collections_vectors",
        embedding_model: str = "voyage-3.5-lite",
        use_parameter_store: bool = True,
        parameter_name: str = "/collections-local/rds/connection-string"
    ):
        """Initialize PGVector store.

        Args:
            connection_string: PostgreSQL connection string (if not using Parameter Store)
            collection_name: Name of the collection/table
            embedding_model: VoyageAI model name
            use_parameter_store: Whether to load connection string from Parameter Store
            parameter_name: AWS Parameter Store parameter name for connection string
        """
        self.collection_name = collection_name
        self.embedding_model = embedding_model

        # Get connection string
        if not connection_string:
            # Use shared connection management from database_orm.connection
            from database_orm.connection import get_connection_string
            connection_string = get_connection_string()

        self.connection_string = connection_string

        # Initialize VoyageAI embeddings
        voyage_api_key = os.getenv("VOYAGE_API_KEY")
        if not voyage_api_key:
            raise ValueError("VOYAGE_API_KEY environment variable not set")

        self.embeddings = VoyageAIEmbeddings(
            voyage_api_key=voyage_api_key,
            model=embedding_model
        )

        # Initialize PGVector store with cosine distance (matching ChromaDB)
        self.vectorstore = PGVector(
            embeddings=self.embeddings,
            collection_name=collection_name,
            connection=connection_string,
            distance_strategy="cosine",  # CRITICAL: Must match ChromaDB
            use_jsonb=True  # Store metadata as JSONB for efficient filtering
        )

        logger.info(
            f"Initialized PGVector store: {collection_name} "
            f"(model={embedding_model}, distance=cosine)"
        )

    def add_documents(
        self,
        documents: List[Document],
        ids: Optional[List[str]] = None
    ) -> List[str]:
        """Add documents to the vector store.

        Args:
            documents: List of LangChain Document objects
            ids: Optional list of IDs for the documents

        Returns:
            List of document IDs
        """
        try:
            # Use PGVector's add_documents method
            doc_ids = self.vectorstore.add_documents(documents, ids=ids)
            logger.info(f"Added {len(documents)} documents to PGVector store")
            return doc_ids
        except Exception as e:
            logger.error(f"Failed to add documents: {e}")
            raise

    def similarity_search(
        self,
        query: str,
        k: int = 10,
        filter: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """Execute similarity search.

        Args:
            query: Search query string
            k: Number of results to return
            filter: Optional metadata filter dict (e.g., {"user_id": "123", "category": "Food"})

        Returns:
            List of relevant Documents
        """
        try:
            return self.vectorstore.similarity_search(
                query,
                k=k,
                filter=filter
            )
        except Exception as e:
            logger.error(f"Similarity search failed: {e}")
            return []

    def similarity_search_with_score(
        self,
        query: str,
        k: int = 10,
        filter: Optional[Dict[str, Any]] = None
    ) -> List[tuple[Document, float]]:
        """Execute similarity search with scores.

        Args:
            query: Search query string
            k: Number of results to return
            filter: Optional metadata filter dict

        Returns:
            List of (Document, distance) tuples
            Note: Returns cosine distance (lower is better, range 0-2)
        """
        try:
            return self.vectorstore.similarity_search_with_score(
                query,
                k=k,
                filter=filter
            )
        except Exception as e:
            logger.error(f"Similarity search with score failed: {e}")
            return []

    def as_retriever(self, search_kwargs: Optional[dict] = None):
        """Get retriever interface for use in chains.

        Args:
            search_kwargs: Optional search parameters (e.g., {"k": 10, "filter": {...}})

        Returns:
            VectorStoreRetriever instance
        """
        return self.vectorstore.as_retriever(
            search_kwargs=search_kwargs or {"k": 10}
        )

    def delete_collection(self):
        """Delete the collection and recreate it.

        Useful for fresh index rebuilds.
        """
        try:
            # Drop the collection table
            self.vectorstore.drop_tables()
            logger.info(f"Deleted collection: {self.collection_name}")

            # Recreate collection
            self.vectorstore.create_tables_if_not_exists()
            logger.info(f"Recreated collection: {self.collection_name}")

        except Exception as e:
            logger.error(f"Failed to delete collection: {e}")
            raise

    def get_collection_stats(self) -> dict:
        """Get statistics about the collection.

        Returns:
            Dictionary with collection stats
        """
        try:
            # Query document count from PostgreSQL
            with self.vectorstore._make_session() as session:
                from sqlalchemy import text
                result = session.execute(
                    text(f"SELECT COUNT(*) FROM {self.collection_name}")
                )
                count = result.scalar()

            return {
                "collection_name": self.collection_name,
                "document_count": count,
                "embedding_model": self.embedding_model,
                "distance_strategy": "cosine"
            }
        except Exception as e:
            logger.error(f"Failed to get collection stats: {e}")
            return {
                "collection_name": self.collection_name,
                "error": str(e)
            }

    @staticmethod
    def create_flat_document(raw_response: dict, item_id: str, filename: str) -> Document:
        """Create flat document using shared document builder utility.

        This is a compatibility wrapper that maintains the original API while using
        the centralized document builder from utils.document_builder.

        Args:
            raw_response: Analysis data dictionary
            item_id: Item identifier
            filename: Image filename

        Returns:
            LangChain Document with flat content and metadata
        """
        # Create document using shared utility
        doc = create_langchain_document(
            raw_response=raw_response,
            item_id=item_id,
            filename=filename,
            category=raw_response.get("category")
        )

        # Add PGVector-specific metadata
        doc.metadata.update({
            "headline": raw_response.get("headline"),
            "summary": raw_response.get("summary"),
            "image_url": f"/images/{filename}",
            "raw_response": json.dumps(raw_response)  # Store as JSON string
        })

        return doc

    def build_index(self, batch_size: int = 128) -> int:
        """Build index from database analyses.

        Note: For PGVector with RDS PostgreSQL, items/analyses should be in PostgreSQL.
        This is a compatibility stub for the ChromaDB interface.
        Use manual migrations or populate via API endpoints instead.

        Args:
            batch_size: Number of documents to process at once (unused)

        Returns:
            Number of documents indexed (0 for stub)
        """
        logger.warning(
            "build_index() called on PGVectorStoreManager. "
            "For RDS deployment, populate vector store via API endpoints or migrations. "
            "Use scripts/migrate/chromadb_to_pgvector.py for migration from ChromaDB."
        )
        return 0
