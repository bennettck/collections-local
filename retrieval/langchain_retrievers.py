"""
LangChain-based retrieval implementations for Collections Local API.

Provides BM25 and Vector retrievers that wrap existing database functions
while conforming to LangChain's BaseRetriever interface for evaluation.
"""

import logging
from typing import List, Optional

from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_classic.retrievers.ensemble import EnsembleRetriever
from langsmith import traceable

import database
import embeddings

logger = logging.getLogger(__name__)


class BM25LangChainRetriever(BaseRetriever):
    """LangChain retriever wrapping SQLite FTS5 BM25 search."""

    top_k: int = 10
    category_filter: Optional[str] = None
    min_relevance_score: float = -1.0

    @traceable(name="bm25_retrieval", run_type="retriever")
    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Optional[CallbackManagerForRetrieverRun] = None
    ) -> List[Document]:
        """Execute BM25 search and return as LangChain Documents."""
        try:
            # Call native database search (returns item_ids and scores)
            search_results = database.search_items(
                query=query,
                top_k=self.top_k,
                category_filter=self.category_filter,
                min_relevance_score=self.min_relevance_score
            )

            if not search_results:
                return []

            # Extract item IDs
            item_ids = [item_id for item_id, _ in search_results]

            # OPTIMIZED: Batch fetch all items with their analyses in a single query
            items_data = database.batch_get_items_with_analyses(item_ids)

            # Convert to Documents, preserving the search result order
            documents = []
            for item_id, bm25_score in search_results:
                item_data = items_data.get(item_id)
                if item_data and item_data.get('analysis'):
                    doc = self._create_document_from_data(
                        item_data=item_data,
                        score=bm25_score,
                        score_type="bm25"
                    )
                    if doc:
                        documents.append(doc)

            return documents

        except Exception as e:
            logger.error(f"BM25 retrieval failed: {e}")
            return []

    def _create_document_from_data(
        self,
        item_data: dict,
        score: float,
        score_type: str
    ) -> Optional[Document]:
        """Convert item data (from batch query) to LangChain Document."""
        try:
            analysis = item_data.get('analysis')
            if not analysis:
                logger.warning(f"No analysis for item: {item_data['id']}")
                return None

            # Extract raw_response data
            raw_response = analysis.get("raw_response", {})
            summary = raw_response.get("summary", "")

            # Construct metadata
            metadata = {
                "item_id": item_data['id'],
                "score": score,
                "score_type": score_type,
                "category": raw_response.get("category"),
                "headline": raw_response.get("headline"),
                "summary": summary,
                "image_url": f"/images/{item_data['filename']}",
                "filename": item_data["filename"],
                "raw_response": raw_response,
            }

            # Create Document
            return Document(
                page_content=summary,
                metadata=metadata
            )

        except Exception as e:
            logger.error(f"Failed to create document for {item_data.get('id')}: {e}")
            return None


class VectorLangChainRetriever(BaseRetriever):
    """LangChain retriever using vector store."""

    top_k: int = 10
    category_filter: Optional[str] = None
    min_similarity_score: float = 0.0
    vector_store: Optional[object] = None  # Vector store manager instance

    @traceable(name="vector_retrieval", run_type="retriever")
    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Optional[CallbackManagerForRetrieverRun] = None
    ) -> List[Document]:
        """Execute vector search and return as LangChain Documents."""
        try:
            if not self.vector_store:
                logger.error("Vector store not provided to VectorLangChainRetriever")
                return []

            # Build filter dict for category filtering
            filter_dict = None
            if self.category_filter:
                filter_dict = {"category": self.category_filter}

            # Use vector store's similarity_search_with_score for threshold filtering
            results = self.vector_store.vectorstore.similarity_search_with_score(
                query,
                k=self.top_k,
                filter=filter_dict
            )

            # Filter by similarity threshold and add scores to metadata
            documents = []
            for doc, distance in results:
                # Convert distance to similarity (cosine distance)
                similarity = 1.0 - distance

                if similarity >= self.min_similarity_score:
                    # Add similarity score to metadata
                    doc.metadata["score"] = similarity
                    doc.metadata["score_type"] = "similarity"
                    documents.append(doc)

            return documents

        except Exception as e:
            logger.error(f"Vector retrieval failed: {e}")
            return []

class HybridLangChainRetriever(BaseRetriever):
    """LangChain hybrid retriever combining BM25 and Vector search with RRF.

    Uses LangChain's official EnsembleRetriever for Reciprocal Rank Fusion.
    """

    # Configuration
    top_k: int = 10                          # Final results after fusion
    bm25_top_k: int = 20                     # Fetch 2x from each retriever
    vector_top_k: int = 20
    bm25_weight: float = 0.3                 # Reduced BM25 influence (optimized)
    vector_weight: float = 0.7               # Favor vector search (optimized)
    category_filter: Optional[str] = None
    min_relevance_score: float = -1.0        # For BM25
    min_similarity_score: float = 0.0        # For vector
    vector_store: Optional[object] = None    # Vector store manager instance
    rrf_c: int = 15                          # RRF constant (optimized for sensitivity)

    @traceable(name="hybrid_retrieval", run_type="retriever")
    def _get_relevant_documents(
        self, query: str, *, run_manager: Optional[CallbackManagerForRetrieverRun] = None
    ) -> List[Document]:
        """Execute hybrid search using EnsembleRetriever with RRF."""

        # Create BM25 retriever
        bm25_retriever = BM25LangChainRetriever(
            top_k=self.bm25_top_k,
            category_filter=self.category_filter,
            min_relevance_score=self.min_relevance_score
        )

        # Create vector retriever
        vector_retriever = VectorLangChainRetriever(
            top_k=self.vector_top_k,
            category_filter=self.category_filter,
            min_similarity_score=self.min_similarity_score,
            vector_store=self.vector_store
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
            # (EnsembleRetriever doesn't expose the score directly)
            if "rrf_score" not in doc.metadata:
                doc.metadata["rrf_score"] = 1.0 / (self.rrf_c + i)

        return documents
