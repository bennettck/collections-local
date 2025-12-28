"""
Hybrid retriever combining PostgreSQL BM25 and PGVector with RRF.

Uses LangChain's EnsembleRetriever for Reciprocal Rank Fusion (RRF).
Replaces ChromaDB-based hybrid retriever with PostgreSQL backend.
"""

import logging
from typing import List, Optional

from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain.retrievers.ensemble import EnsembleRetriever
from langsmith import traceable

from retrieval.postgres_bm25 import PostgresBM25Retriever
from retrieval.pgvector_store import PGVectorStoreManager

logger = logging.getLogger(__name__)


class PostgresHybridRetriever(BaseRetriever):
    """Hybrid retriever combining PostgreSQL BM25 and PGVector with RRF.

    Features:
    - PostgreSQL BM25 for keyword matching
    - PGVector for semantic similarity
    - Reciprocal Rank Fusion (RRF) for score combination
    - User isolation via metadata filtering
    - Category filtering support
    - Configurable weights and RRF constant
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
        """Execute hybrid search using EnsembleRetriever with RRF.

        Args:
            query: Search query string
            run_manager: Callback manager (optional)

        Returns:
            List of relevant Documents ranked by RRF
        """
        try:
            # Create BM25 retriever
            bm25_retriever = PostgresBM25Retriever(
                top_k=self.bm25_top_k,
                user_id=self.user_id,
                category_filter=self.category_filter,
                min_relevance_score=self.min_relevance_score,
                connection_string=self.connection_string,
                use_parameter_store=self.use_parameter_store,
                parameter_name=self.parameter_name
            )

            # Create vector retriever
            if not self.pgvector_manager:
                logger.error("PGVector manager not provided to PostgresHybridRetriever")
                return []

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

            # Wrap vector retriever to add scores and filter by similarity threshold
            vector_retriever = self._wrap_vector_retriever_with_scoring(
                vector_retriever,
                self.min_similarity_score
            )

            # Create ensemble retriever with RRF
            ensemble = EnsembleRetriever(
                retrievers=[bm25_retriever, vector_retriever],
                weights=[self.bm25_weight, self.vector_weight],
                c=self.rrf_c,  # RRF constant
                id_key="item_id"  # Use item_id for deduplication
            )

            # Execute retrieval with proper callback handling
            try:
                if run_manager:
                    documents = ensemble.invoke(
                        query,
                        config={"callbacks": run_manager.get_child()}
                    )
                else:
                    documents = ensemble.invoke(query)
            except Exception as e:
                logger.warning(f"Ensemble retrieval callback error, retrying without callbacks: {e}")
                # Fallback without callbacks if there's an issue
                documents = ensemble.invoke(query)

            # Limit to top_k results
            documents = documents[:self.top_k]

            # Mark as hybrid search in metadata and add RRF score
            for i, doc in enumerate(documents, start=1):
                doc.metadata["score_type"] = "hybrid_rrf"
                # Calculate approximate RRF score for this rank
                if "rrf_score" not in doc.metadata:
                    doc.metadata["rrf_score"] = 1.0 / (self.rrf_c + i)

            logger.info(f"Hybrid search returned {len(documents)} documents")
            return documents

        except Exception as e:
            logger.error(f"Hybrid retrieval failed: {e}")
            return []

    def _wrap_vector_retriever_with_scoring(
        self,
        base_retriever,
        min_similarity: float
    ) -> BaseRetriever:
        """Wrap vector retriever to add similarity scores and filter by threshold.

        Args:
            base_retriever: Base vector retriever
            min_similarity: Minimum similarity threshold

        Returns:
            Wrapped retriever with scoring
        """
        class ScoredVectorRetriever(BaseRetriever):
            """Wrapper to add scores to vector retriever results."""

            retriever: BaseRetriever
            min_similarity: float
            pgvector_manager: PGVectorStoreManager

            class Config:
                arbitrary_types_allowed = True

            def _get_relevant_documents(
                self,
                query: str,
                *,
                run_manager: Optional[CallbackManagerForRetrieverRun] = None
            ) -> List[Document]:
                """Get documents with similarity scores."""
                try:
                    # Use similarity_search_with_score directly from PGVector
                    filter_dict = self.retriever.search_kwargs.get("filter")
                    k = self.retriever.search_kwargs.get("k", 10)

                    results = self.pgvector_manager.similarity_search_with_score(
                        query,
                        k=k,
                        filter=filter_dict
                    )

                    # Filter by similarity and add scores
                    documents = []
                    for doc, distance in results:
                        # Convert distance to similarity (cosine distance: lower is better)
                        # For cosine distance in range [0, 2], similarity = 1 - (distance / 2)
                        similarity = 1.0 - (distance / 2.0)

                        if similarity >= self.min_similarity:
                            doc.metadata["score"] = similarity
                            doc.metadata["score_type"] = "similarity"
                            documents.append(doc)

                    return documents

                except Exception as e:
                    logger.error(f"Scored vector retrieval failed: {e}")
                    return []

        return ScoredVectorRetriever(
            retriever=base_retriever,
            min_similarity=min_similarity,
            pgvector_manager=self.pgvector_manager
        )


class VectorOnlyRetriever(BaseRetriever):
    """Vector-only retriever using PGVector.

    Convenience class for vector-only search without BM25.
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
        try:
            if not self.pgvector_manager:
                logger.error("PGVector manager not provided to VectorOnlyRetriever")
                return []

            # Build filter dict
            filter_dict = {}
            if self.user_id:
                filter_dict["user_id"] = self.user_id
            if self.category_filter:
                filter_dict["category"] = self.category_filter

            # Use similarity_search_with_score for threshold filtering
            results = self.pgvector_manager.similarity_search_with_score(
                query,
                k=self.top_k,
                filter=filter_dict if filter_dict else None
            )

            # Filter by similarity threshold and add scores to metadata
            documents = []
            for doc, distance in results:
                # Convert distance to similarity (cosine distance: lower is better)
                similarity = 1.0 - (distance / 2.0)

                if similarity >= self.min_similarity_score:
                    # Add similarity score to metadata
                    doc.metadata["score"] = similarity
                    doc.metadata["score_type"] = "similarity"
                    documents.append(doc)

            logger.info(f"Vector search returned {len(documents)} documents")
            return documents

        except Exception as e:
            logger.error(f"Vector retrieval failed: {e}")
            return []
