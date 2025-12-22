"""
LangChain native retriever implementations for Collections Local API.

Uses TRUE LangChain components (not wrappers):
- BM25Retriever from langchain-community (uses rank-bm25 library)
- EnsembleRetriever for hybrid search with RRF

Supports dual database mode (prod and golden databases).
"""

import logging
import json
import sqlite3
from typing import List, Optional
from contextlib import contextmanager

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_classic.retrievers.ensemble import EnsembleRetriever

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


class LangChainNativeBM25Retriever:
    """TRUE LangChain BM25 retriever using rank-bm25 library.

    This is NOT a wrapper - it uses LangChain's BM25Retriever which
    uses the rank-bm25 library under the hood.

    Features:
    - In-memory BM25 using rank-bm25
    - Flat document representation (no field weighting)
    - Dual database support (prod/golden via database_path)
    - Rebuild on startup or manual refresh
    """

    def __init__(
        self,
        database_path: str,
        top_k: int = 10,
        category_filter: Optional[str] = None,
        preload: bool = True,
        k1: float = 1.2,
        b: float = 0.75,
        epsilon: float = 0.25
    ):
        """Initialize BM25 retriever.

        Args:
            database_path: Path to SQLite database (prod or golden)
            top_k: Number of results to return
            category_filter: Optional category filter
            preload: Build index immediately (default True)
            k1: BM25 term frequency saturation parameter (default 1.2, Elasticsearch recommended)
            b: BM25 document length normalization (default 0.75, range 0-1)
            epsilon: BM25 floor for IDF values (default 0.25)
        """
        self.database_path = database_path
        self.top_k = top_k
        self.category_filter = category_filter
        self.k1 = k1
        self.b = b
        self.epsilon = epsilon
        self.retriever = None

        if preload:
            self._build_index()

    def _build_index(self):
        """Build in-memory BM25 index from database."""
        logger.info(
            f"Building BM25 index from {self.database_path} "
            f"(k1={self.k1}, b={self.b}, epsilon={self.epsilon})"
        )
        documents = self._load_documents_from_db()

        if not documents:
            logger.warning("No documents loaded from database")
            return

        # Create BM25Retriever from documents with tuned parameters
        self.retriever = BM25Retriever.from_documents(
            documents,
            k=self.top_k,
            bm25_params={"k1": self.k1, "b": self.b, "epsilon": self.epsilon}
        )
        logger.info(
            f"BM25 index built with {len(documents)} documents "
            f"(k1={self.k1}, b={self.b}, epsilon={self.epsilon})"
        )

    def _load_documents_from_db(self) -> List[Document]:
        """Load all documents from database.

        Returns:
            List of LangChain Documents with metadata
        """
        documents = []

        with database_context(self.database_path) as conn:
            # Query for all items with latest analyses
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

            # Apply category filter if provided
            if self.category_filter:
                query += " AND json_extract(a.raw_response, '$.category') = ?"
                rows = conn.execute(query, (self.category_filter,)).fetchall()
            else:
                rows = conn.execute(query).fetchall()

            # Transform to Documents
            for row in rows:
                item_id = row["id"]
                filename = row["filename"]

                try:
                    raw_response = json.loads(row["raw_response"])
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON for item {item_id}")
                    continue

                # Create flat document (no field weighting)
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
                        "raw_response": raw_response,
                    }
                )
                documents.append(doc)

        return documents

    def _create_flat_document(self, raw_response: dict) -> str:
        """Create flat document from analysis data (no field weighting).

        This method concatenates all fields ONCE (no repetition).
        Modern embedding models handle field importance implicitly.

        Args:
            raw_response: Analysis data dictionary

        Returns:
            Concatenated string of all fields
        """
        parts = []

        # Extract all fields once (no weighting/repetition)
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

    def invoke(self, query: str) -> List[Document]:
        """Execute BM25 search.

        Args:
            query: Search query string

        Returns:
            List of relevant Documents
        """
        if not self.retriever:
            logger.error("Retriever not initialized - call _build_index first")
            return []

        try:
            return self.retriever.invoke(query)
        except Exception as e:
            logger.error(f"BM25 search failed: {e}")
            return []

    def get_relevant_documents(self, query: str) -> List[Document]:
        """Alias for invoke() to match BaseRetriever interface.

        Args:
            query: Search query string

        Returns:
            List of relevant Documents
        """
        return self.invoke(query)

    def rebuild(self):
        """Manually rebuild the index from database."""
        self._build_index()


class TrueLangChainHybridRetriever:
    """TRUE LangChain hybrid retriever using rank-bm25 + Chroma with RRF.

    This combines:
    - LangChainNativeBM25Retriever (rank-bm25 library)
    - ChromaVectorStoreManager (Chroma vector store)
    - EnsembleRetriever (LangChain's RRF implementation)

    This is the REAL LangChain migration, not wrappers around native implementations.
    """

    def __init__(
        self,
        bm25_retriever,  # LangChainNativeBM25Retriever instance
        chroma_manager,  # ChromaVectorStoreManager instance
        top_k: int = 10,
        bm25_top_k: int = 20,
        vector_top_k: int = 20,
        bm25_weight: float = 0.3,
        vector_weight: float = 0.7,
        rrf_c: int = 15,
        category_filter: Optional[str] = None,
        min_similarity_score: float = 0.0
    ):
        """Initialize TRUE LangChain hybrid retriever.

        Args:
            bm25_retriever: LangChainNativeBM25Retriever instance
            chroma_manager: ChromaVectorStoreManager instance
            top_k: Final number of results to return
            bm25_top_k: Number of results to fetch from BM25
            vector_top_k: Number of results to fetch from vector
            bm25_weight: Weight for BM25 results in ensemble
            vector_weight: Weight for vector results in ensemble
            rrf_c: RRF constant (lower = more rank sensitive)
            category_filter: Optional category filter
            min_similarity_score: Minimum similarity for vector results
        """
        self.bm25_retriever = bm25_retriever
        self.chroma_manager = chroma_manager
        self.top_k = top_k
        self.bm25_top_k = bm25_top_k
        self.vector_top_k = vector_top_k
        self.bm25_weight = bm25_weight
        self.vector_weight = vector_weight
        self.rrf_c = rrf_c
        self.category_filter = category_filter
        self.min_similarity_score = min_similarity_score

    def invoke(self, query: str) -> List[Document]:
        """Execute hybrid search using EnsembleRetriever with RRF.

        Args:
            query: Search query string

        Returns:
            List of relevant Documents with RRF scores
        """
        try:
            # Create ensemble retriever with the TRUE LangChain components
            # Note: We need to wrap chroma_manager to make it compatible
            ensemble = EnsembleRetriever(
                retrievers=[
                    self.bm25_retriever.retriever,  # TRUE rank-bm25
                    self.chroma_manager.as_retriever(
                        search_kwargs={
                            "k": self.vector_top_k,
                            "filter": {"category": self.category_filter} if self.category_filter else None
                        }
                    )  # TRUE Chroma
                ],
                weights=[self.bm25_weight, self.vector_weight],
                c=self.rrf_c,
                id_key="item_id"
            )

            # Execute retrieval
            documents = ensemble.invoke(query)

            # Limit to top_k
            documents = documents[:self.top_k]

            # Add RRF scores to metadata
            for i, doc in enumerate(documents, start=1):
                doc.metadata["score_type"] = "hybrid_rrf"
                if "rrf_score" not in doc.metadata:
                    doc.metadata["rrf_score"] = 1.0 / (self.rrf_c + i)

            return documents

        except Exception as e:
            logger.error(f"TRUE LangChain hybrid retrieval failed: {e}")
            return []

    def get_relevant_documents(self, query: str) -> List[Document]:
        """Alias for invoke() to match BaseRetriever interface.

        Args:
            query: Search query string

        Returns:
            List of relevant Documents
        """
        return self.invoke(query)
