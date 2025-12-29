"""
Hybrid retriever combining PostgreSQL BM25 and PGVector with RRF.

ARCHITECTURE:
- Both BM25 and Vector search use the langchain_pg_embedding table
- This ensures data consistency and eliminates sync issues
- BM25 uses PostgreSQL full-text search (tsvector/tsquery) on the document column
- Vector uses PGVector cosine similarity on the embedding column
- RRF (Reciprocal Rank Fusion) combines results with configurable weights

ERROR HANDLING:
- If BM25 fails, falls back to vector-only search
- If Vector fails, falls back to BM25-only search
- All errors are logged with full tracebacks for debugging
- Never silently returns empty results without logging why
"""

import logging
import traceback
from typing import List, Optional

from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langsmith import traceable
from collections import defaultdict

from retrieval.postgres_bm25 import PostgresBM25Retriever
from retrieval.pgvector_store import PGVectorStoreManager

logger = logging.getLogger(__name__)


def _log(msg: str, level: str = "INFO"):
    """Log with both print (for Lambda CloudWatch) and logger."""
    print(f"[HYBRID:{level}] {msg}")
    if level == "ERROR":
        logger.error(msg)
    elif level == "WARNING":
        logger.warning(msg)
    else:
        logger.info(msg)


class PostgresHybridRetriever(BaseRetriever):
    """Hybrid retriever combining PostgreSQL BM25 and PGVector with RRF.

    IMPORTANT: Both retrievers query the same langchain_pg_embedding table.
    This ensures data consistency between keyword and semantic search.

    Features:
    - PostgreSQL BM25 for keyword matching (full-text search on document column)
    - PGVector for semantic similarity (cosine on embedding column)
    - Reciprocal Rank Fusion (RRF) for score combination
    - User isolation via metadata filtering
    - Category filtering support
    - Configurable weights and RRF constant
    - Graceful fallback if one retriever fails
    """

    # Configuration
    top_k: int = 10  # Final results after fusion
    bm25_top_k: int = 20  # Fetch 2x from each retriever
    vector_top_k: int = 20
    bm25_weight: float = 0.3  # 30% weight for BM25
    vector_weight: float = 0.7  # 70% weight for vector search
    rrf_c: int = 15  # RRF constant (optimized for sensitivity)

    # Filtering
    user_id: Optional[str] = None
    category_filter: Optional[str] = None
    min_relevance_score: float = 0.0  # For BM25
    min_similarity_score: float = 0.0  # For vector

    # Backend instances
    pgvector_manager: Optional[PGVectorStoreManager] = None
    connection_string: Optional[str] = None
    use_parameter_store: bool = True
    parameter_name: str = "/collections-local/rds/connection-string"

    class Config:
        """Pydantic config."""
        arbitrary_types_allowed = True

    @traceable(name="hybrid_retrieval", run_type="retriever")
    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Optional[CallbackManagerForRetrieverRun] = None
    ) -> List[Document]:
        """Execute hybrid search using BM25 + Vector with RRF fusion.

        Args:
            query: Search query string
            run_manager: Callback manager (optional)

        Returns:
            List of relevant Documents ranked by RRF

        Note:
            If one retriever fails, gracefully falls back to the other.
            Only raises if both retrievers fail.
        """
        _log(f"Starting hybrid search: query='{query[:50]}...', user_id={self.user_id}")

        bm25_docs = []
        vector_docs = []
        bm25_error = None
        vector_error = None

        # Execute BM25 retrieval
        try:
            _log(f"Executing BM25 search (top_k={self.bm25_top_k})")
            bm25_retriever = PostgresBM25Retriever(
                top_k=self.bm25_top_k,
                user_id=self.user_id,
                category_filter=self.category_filter,
                min_relevance_score=self.min_relevance_score,
                connection_string=self.connection_string,
                use_parameter_store=self.use_parameter_store,
                parameter_name=self.parameter_name
            )
            bm25_docs = bm25_retriever._get_relevant_documents(query)
            _log(f"BM25 returned {len(bm25_docs)} documents")
        except Exception as e:
            bm25_error = e
            _log(f"BM25 search failed: {e}", "WARNING")
            _log(f"BM25 traceback: {traceback.format_exc()}", "WARNING")

        # Execute vector retrieval
        try:
            if not self.pgvector_manager:
                raise ValueError("PGVector manager not provided to PostgresHybridRetriever")

            _log(f"Executing vector search (top_k={self.vector_top_k})")

            # Build filter dict for PGVector
            filter_dict = {}
            if self.user_id:
                filter_dict["user_id"] = self.user_id
            if self.category_filter:
                filter_dict["category"] = self.category_filter

            # Get vector retriever with filters
            vector_retriever = self.pgvector_manager.as_retriever(
                search_kwargs={
                    "k": self.vector_top_k,
                    "filter": filter_dict if filter_dict else None
                }
            )

            vector_docs = vector_retriever._get_relevant_documents(query)
            _log(f"Vector returned {len(vector_docs)} documents")
        except Exception as e:
            vector_error = e
            _log(f"Vector search failed: {e}", "WARNING")
            _log(f"Vector traceback: {traceback.format_exc()}", "WARNING")

        # Check if both failed
        if bm25_error and vector_error:
            _log("Both BM25 and Vector search failed!", "ERROR")
            _log(f"BM25 error: {bm25_error}", "ERROR")
            _log(f"Vector error: {vector_error}", "ERROR")
            # Return empty but log the failures
            return []

        # Handle fallback scenarios
        if bm25_error:
            _log("Falling back to vector-only search (BM25 failed)", "WARNING")
            documents = vector_docs[:self.top_k]
            for doc in documents:
                doc.metadata["score_type"] = "vector_fallback"
            return documents

        if vector_error:
            _log("Falling back to BM25-only search (Vector failed)", "WARNING")
            documents = bm25_docs[:self.top_k]
            for doc in documents:
                doc.metadata["score_type"] = "bm25_fallback"
            return documents

        # Normal case: both succeeded, perform RRF fusion
        _log(f"Performing RRF fusion: {len(bm25_docs)} BM25 + {len(vector_docs)} vector")
        documents = self._manual_rrf_fusion(
            bm25_docs=bm25_docs,
            vector_docs=vector_docs,
            bm25_weight=self.bm25_weight,
            vector_weight=self.vector_weight,
            c=self.rrf_c
        )

        # Limit to top_k results
        documents = documents[:self.top_k]

        # Mark as hybrid search in metadata and add RRF score
        for i, doc in enumerate(documents, start=1):
            doc.metadata["score_type"] = "hybrid_rrf"
            if "rrf_score" not in doc.metadata:
                doc.metadata["rrf_score"] = 1.0 / (self.rrf_c + i)

        _log(f"Hybrid search complete: returning {len(documents)} documents")
        return documents

    def _manual_rrf_fusion(
        self,
        bm25_docs: List[Document],
        vector_docs: List[Document],
        bm25_weight: float,
        vector_weight: float,
        c: int
    ) -> List[Document]:
        """
        Perform Reciprocal Rank Fusion (RRF) on two document lists.

        RRF Score = sum(weight * 1/(c + rank)) for each retriever

        Args:
            bm25_docs: Documents from BM25 retriever (ranked)
            vector_docs: Documents from vector retriever (ranked)
            bm25_weight: Weight for BM25 scores (default 0.3)
            vector_weight: Weight for vector scores (default 0.7)
            c: RRF constant (lower = more sensitive to rank differences)

        Returns:
            Fused and re-ranked documents
        """
        # Build score mapping: item_id -> weighted RRF score
        rrf_scores = defaultdict(float)
        doc_map = {}  # item_id -> Document

        # Process BM25 results (rank starts at 1)
        for rank, doc in enumerate(bm25_docs, start=1):
            item_id = doc.metadata.get("item_id")
            if not item_id:
                _log(f"BM25 doc missing item_id, skipping", "WARNING")
                continue

            rrf_score = bm25_weight * (1.0 / (c + rank))
            rrf_scores[item_id] += rrf_score

            # Store doc (prefer first occurrence)
            if item_id not in doc_map:
                doc_map[item_id] = doc

        # Process vector results
        for rank, doc in enumerate(vector_docs, start=1):
            item_id = doc.metadata.get("item_id")
            if not item_id:
                _log(f"Vector doc missing item_id, skipping", "WARNING")
                continue

            rrf_score = vector_weight * (1.0 / (c + rank))
            rrf_scores[item_id] += rrf_score

            # Store doc if not already stored
            if item_id not in doc_map:
                doc_map[item_id] = doc

        # Sort by RRF score (descending)
        sorted_items = sorted(
            rrf_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )

        # Build final document list
        fused_docs = []
        for item_id, rrf_score in sorted_items:
            doc = doc_map[item_id]
            # Add RRF score to metadata
            doc.metadata["rrf_score"] = rrf_score
            doc.metadata["score"] = rrf_score  # Use as primary score
            doc.metadata["score_type"] = "hybrid_rrf"
            fused_docs.append(doc)

        _log(f"RRF fusion: {len(bm25_docs)} BM25 + {len(vector_docs)} vector -> {len(fused_docs)} unique")
        return fused_docs


class VectorOnlyRetriever(BaseRetriever):
    """Vector-only retriever using PGVector.

    Convenience class for vector-only search without BM25.
    Uses the langchain_pg_embedding table directly via PGVectorStoreManager.
    """

    top_k: int = 10
    user_id: Optional[str] = None
    category_filter: Optional[str] = None
    min_similarity_score: float = 0.0
    pgvector_manager: Optional[PGVectorStoreManager] = None

    class Config:
        """Pydantic config."""
        arbitrary_types_allowed = True

    @traceable(name="vector_retrieval", run_type="retriever")
    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Optional[CallbackManagerForRetrieverRun] = None
    ) -> List[Document]:
        """Execute vector search using PGVector.

        Args:
            query: Search query string
            run_manager: Callback manager (optional)

        Returns:
            List of relevant Documents
        """
        _log(f"Starting vector-only search: query='{query[:50]}...', user_id={self.user_id}")

        try:
            if not self.pgvector_manager:
                _log("PGVector manager not provided to VectorOnlyRetriever", "ERROR")
                raise ValueError("PGVector manager not provided to VectorOnlyRetriever")

            # Build filter dict
            filter_dict = {}
            if self.user_id:
                filter_dict["user_id"] = self.user_id
            if self.category_filter:
                filter_dict["category"] = self.category_filter

            _log(f"Vector search params: filter={filter_dict}, top_k={self.top_k}")

            # Use similarity_search_with_score for threshold filtering
            results = self.pgvector_manager.similarity_search_with_score(
                query,
                k=self.top_k,
                filter=filter_dict if filter_dict else None
            )

            _log(f"Vector search raw results: {len(results)} documents from PGVector")

            # Filter by similarity threshold and add scores to metadata
            documents = []
            for doc, distance in results:
                # Convert distance to similarity (cosine distance: lower is better)
                # For cosine distance in range [0, 2], similarity = 1 - (distance / 2)
                similarity = 1.0 - (distance / 2.0)

                if similarity >= self.min_similarity_score:
                    # Add similarity score to metadata
                    doc.metadata["score"] = similarity
                    doc.metadata["score_type"] = "similarity"
                    documents.append(doc)

            _log(f"Vector search complete: {len(documents)} documents (threshold={self.min_similarity_score})")
            return documents

        except Exception as e:
            _log(f"Vector retrieval failed: {e}", "ERROR")
            _log(f"Traceback: {traceback.format_exc()}", "ERROR")
            # Re-raise so caller knows there was an error
            raise
