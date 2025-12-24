"""
Chroma vector store management for Collections Local API.

Provides persistent vector storage using Chroma with VoyageAI embeddings.
AWS-portable (file-based persistence can migrate to S3 or Chroma Cloud).
"""

import logging
import json
import sqlite3
import os
from typing import List, Optional, Dict, Any
from contextlib import contextmanager

from langchain_chroma import Chroma
from langchain_voyageai import VoyageAIEmbeddings
from langchain_core.documents import Document

logger = logging.getLogger(__name__)


@contextmanager
def database_context(database_path: str):
    """Context manager for database connections."""
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


class ChromaVectorStoreManager:
    """Chroma vector store manager with VoyageAI embeddings.

    Features:
    - Persistent Chroma vector store (file-based)
    - LangChain VoyageAIEmbeddings integration
    - Flat document representation (no field weighting)
    - Metadata filtering support
    - Dual database support (prod/golden via database_path)
    - AWS-portable (can use S3-backed storage later)
    """

    def __init__(
        self,
        database_path: str,
        persist_directory: str = "./data/chroma",
        collection_name: str = "collections_vectors",
        embedding_model: str = "voyage-3.5-lite"
    ):
        """Initialize Chroma vector store.

        Args:
            database_path: Path to SQLite database (prod or golden)
            persist_directory: Directory for Chroma persistence
            collection_name: Name of Chroma collection
            embedding_model: VoyageAI model name
        """
        self.database_path = database_path
        self.persist_directory = persist_directory
        self.collection_name = collection_name
        self.embedding_model = embedding_model

        # Initialize VoyageAI embeddings (LangChain class)
        voyage_api_key = os.getenv("VOYAGE_API_KEY")
        if not voyage_api_key:
            raise ValueError("VOYAGE_API_KEY environment variable not set")

        # Create embeddings
        # Note: LangChain's VoyageAIEmbeddings doesn't support input_type parameter
        # For input_type optimization, use the direct VoyageAI SDK (see embeddings.py)
        self.embeddings = VoyageAIEmbeddings(
            voyage_api_key=voyage_api_key,
            model=embedding_model
        )

        # Initialize Chroma with cosine similarity (matching native vector implementation)
        # IMPORTANT: Native vector search uses cosine similarity, so Chroma must use the same metric
        # Default is L2 distance, which produces different rankings

        # Create ChromaDB client directly to ensure cosine similarity
        import chromadb
        self.chroma_client = chromadb.PersistentClient(path=persist_directory)

        # Get or create collection with cosine similarity
        try:
            # Try to get existing collection
            collection = self.chroma_client.get_collection(
                name=collection_name
            )
            logger.info(f"Loaded existing Chroma collection: {collection_name}")
        except Exception:
            # Create new collection with cosine similarity
            collection = self.chroma_client.create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"}  # CRITICAL: Set cosine similarity
            )
            logger.info(f"Created new Chroma collection with cosine similarity: {collection_name}")

        # Initialize LangChain wrapper with our pre-configured client
        self.vectorstore = Chroma(
            client=self.chroma_client,
            collection_name=collection_name,
            embedding_function=self.embeddings
        )

        logger.info(
            f"Initialized Chroma vector store: {collection_name} "
            f"at {persist_directory} (model={embedding_model}, distance=cosine)"
        )

    def build_index(self, batch_size: int = 128) -> int:
        """Build index from database analyses.

        Args:
            batch_size: Number of documents to process at once

        Returns:
            Number of documents indexed
        """
        logger.info(f"Building Chroma index from {self.database_path}")

        # Load all items from specific database
        with database_context(self.database_path) as conn:
            query = """
                SELECT i.id, i.filename, a.raw_response
                FROM items i
                JOIN analyses a ON i.id = a.item_id
                WHERE a.id = (
                    SELECT id FROM analyses
                    WHERE item_id = i.id
                    ORDER BY version DESC
                    LIMIT 1
                )
            """
            rows = conn.execute(query).fetchall()

        # Transform to Documents with FLAT content (no weighting)
        documents = []
        for row in rows:
            item_id = row["id"]
            filename = row["filename"]

            try:
                raw_response = json.loads(row["raw_response"])
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON for item {item_id}")
                continue

            # Create flat document (same as BM25)
            content = self._create_flat_document(raw_response)

            # Create Document with metadata
            doc = Document(
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
            documents.append(doc)

        # Add to Chroma in batches
        total_docs = len(documents)
        for i in range(0, total_docs, batch_size):
            batch = documents[i:i + batch_size]
            self.vectorstore.add_documents(batch)
            logger.info(f"Indexed {min(i + batch_size, total_docs)}/{total_docs} documents")

        logger.info(f"Chroma index built with {total_docs} documents")
        return total_docs

    def add_document(
        self,
        item_id: str,
        raw_response: dict,
        filename: str
    ) -> bool:
        """Add or update a single document in Chroma.

        Args:
            item_id: Item identifier
            raw_response: Analysis data dictionary
            filename: Image filename

        Returns:
            True if successful, False otherwise
        """
        try:
            # Create flat document (same as batch indexing)
            content = self._create_flat_document(raw_response)

            # Create Document with metadata
            doc = Document(
                page_content=content,
                metadata={
                    "item_id": item_id,
                    "category": raw_response.get("category"),
                    "headline": raw_response.get("headline"),
                    "summary": raw_response.get("summary"),
                    "image_url": f"/images/{filename}",
                    "filename": filename,
                    "raw_response": json.dumps(raw_response)
                }
            )

            # Add to Chroma (uses upsert internally)
            self.vectorstore.add_documents([doc], ids=[item_id])
            logger.info(f"Added document to Chroma: {item_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to add document to Chroma: {item_id}, error: {e}")
            return False

    def _create_flat_document(self, raw_response: dict) -> str:
        """Create flat document (no field weighting) - matches BM25 approach.

        Args:
            raw_response: Analysis data dictionary

        Returns:
            Concatenated string of all fields
        """
        parts = []

        # Extract all fields once (same order as BM25)
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
        return " ".join([p for p in parts if p and p.strip()])

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
            filter: Optional metadata filter dict (e.g., {"category": "Food"})

        Returns:
            List of relevant Documents
        """
        try:
            return self.vectorstore.similarity_search(query, k=k, filter=filter)
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
            Note: Chroma returns cosine distance (1 - cosine_similarity), lower is better
        """
        try:
            return self.vectorstore.similarity_search_with_score(
                query, k=k, filter=filter
            )
        except Exception as e:
            logger.error(f"Similarity search with score failed: {e}")
            return []

    def as_retriever(self, search_kwargs: Optional[dict] = None):
        """Get retriever interface for use in chains.

        Args:
            search_kwargs: Optional search parameters (e.g., {"k": 10})

        Returns:
            VectorStoreRetriever instance
        """
        return self.vectorstore.as_retriever(
            search_kwargs=search_kwargs or {"k": 10}
        )

    def delete_collection(self):
        """Delete the collection and reinitialize.

        Useful for fresh index rebuilds.
        """
        try:
            # Delete via chromadb client
            self.chroma_client.delete_collection(name=self.collection_name)
            logger.info(f"Deleted collection: {self.collection_name}")

            # Recreate collection with cosine similarity
            collection = self.chroma_client.create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"}  # CRITICAL: Set cosine similarity
            )
            logger.info(f"Recreated collection with cosine similarity: {self.collection_name}")

            # Reinitialize LangChain wrapper
            self.vectorstore = Chroma(
                client=self.chroma_client,
                collection_name=self.collection_name,
                embedding_function=self.embeddings
            )
            logger.info(f"Reinitialized vectorstore wrapper")

        except Exception as e:
            logger.error(f"Failed to delete collection: {e}")
            raise

    def get_collection_stats(self) -> dict:
        """Get statistics about the collection.

        Returns:
            Dictionary with collection stats
        """
        try:
            collection = self.vectorstore._collection
            count = collection.count()

            return {
                "collection_name": self.collection_name,
                "document_count": count,
                "persist_directory": self.persist_directory,
                "embedding_model": self.embedding_model
            }
        except Exception as e:
            logger.error(f"Failed to get collection stats: {e}")
            return {
                "collection_name": self.collection_name,
                "error": str(e)
            }

    def get_distance_metric(self) -> str:
        """Get the actual distance metric used by the Chroma collection.

        Returns:
            Distance metric name (e.g., "cosine", "l2", "ip")
        """
        try:
            # Get collection directly from chromadb client
            collection = self.chroma_client.get_collection(name=self.collection_name)

            # Get metadata from collection
            if hasattr(collection, 'metadata') and collection.metadata:
                metadata = collection.metadata
                # Check for hnsw:space in metadata
                if 'hnsw:space' in metadata:
                    return metadata['hnsw:space']

            # If no metadata found, collection is using default L2
            logger.warning(
                f"Collection {self.collection_name} has no hnsw:space in metadata. "
                f"Defaulting to L2. Please rebuild collection with cosine similarity."
            )
            return "l2"  # Chroma's default when no configuration is set

        except Exception as e:
            logger.error(f"Failed to get distance metric: {e}", exc_info=True)
            return "unknown"
