"""
PostgreSQL PGVector store for Collections Local API.

Uses LangChain's langchain-postgres library for vector storage with VoyageAI embeddings.
Replaces ChromaDB with PostgreSQL pgvector for AWS RDS compatibility.
"""

import logging
import json
import os
from typing import List, Optional, Dict, Any
import boto3

from langchain_postgres import PGVector
from langchain_postgres.vectorstores import PGVector as PGVectorStore
from langchain_voyageai import VoyageAIEmbeddings
from langchain_core.documents import Document

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
        if use_parameter_store and not connection_string:
            connection_string = self._load_connection_string_from_parameter_store(parameter_name)
        elif not connection_string:
            # Fallback to environment variable
            connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
            if not connection_string:
                raise ValueError(
                    "No connection string provided. Set POSTGRES_CONNECTION_STRING "
                    "environment variable or enable use_parameter_store"
                )

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

    def _load_connection_string_from_parameter_store(self, parameter_name: str) -> str:
        """Load PostgreSQL connection string from AWS Systems Manager Parameter Store.

        Args:
            parameter_name: Parameter Store parameter name

        Returns:
            Connection string

        Raises:
            Exception: If parameter cannot be retrieved
        """
        try:
            ssm = boto3.client('ssm')
            response = ssm.get_parameter(
                Name=parameter_name,
                WithDecryption=True
            )
            connection_string = response['Parameter']['Value']
            logger.info(f"Loaded connection string from Parameter Store: {parameter_name}")
            return connection_string
        except Exception as e:
            logger.error(f"Failed to load connection string from Parameter Store: {e}")
            raise

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
        """Create flat document (no field weighting) - matches ChromaDB approach.

        Args:
            raw_response: Analysis data dictionary
            item_id: Item identifier
            filename: Image filename

        Returns:
            LangChain Document with flat content and metadata
        """
        parts = []

        # Extract all fields once (same order as ChromaDB)
        parts.append(raw_response.get("summary", ""))
        parts.append(raw_response.get("headline", ""))
        parts.append(raw_response.get("category", ""))
        parts.append(" ".join(raw_response.get("subcategories", [])))

        # Image details
        image_details = raw_response.get("image_details", {})
        if isinstance(image_details.get("extracted_text"), list):
            parts.append(" ".join(image_details.get("extracted_text", [])))
        else:
            parts.append(image_details.get("extracted_text", ""))

        parts.append(image_details.get("key_interest", ""))
        parts.append(" ".join(image_details.get("themes", [])))
        parts.append(" ".join(image_details.get("objects", [])))
        parts.append(" ".join(image_details.get("emotions", [])))
        parts.append(" ".join(image_details.get("vibes", [])))

        # Media metadata
        media_metadata = raw_response.get("media_metadata", {})
        parts.append(" ".join(media_metadata.get("location_tags", [])))
        parts.append(" ".join(media_metadata.get("hashtags", [])))

        # Join all parts, filtering out empty strings
        content = " ".join([p for p in parts if p and p.strip()])

        # Create Document with metadata
        # Note: user_id should be added by caller if needed
        return Document(
            page_content=content,
            metadata={
                "item_id": item_id,
                "category": raw_response.get("category"),
                "headline": raw_response.get("headline"),
                "summary": raw_response.get("summary"),
                "image_url": f"/images/{filename}",
                "filename": filename,
                "raw_response": json.dumps(raw_response)  # Store as JSON string
            }
        )
