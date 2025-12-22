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

import database
import embeddings

logger = logging.getLogger(__name__)


class BM25LangChainRetriever(BaseRetriever):
    """LangChain retriever wrapping SQLite FTS5 BM25 search."""

    top_k: int = 10
    category_filter: Optional[str] = None
    min_relevance_score: float = -1.0

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Optional[CallbackManagerForRetrieverRun] = None
    ) -> List[Document]:
        """Execute BM25 search and return as LangChain Documents."""
        try:
            # Call native database search
            search_results = database.search_items(
                query=query,
                top_k=self.top_k,
                category_filter=self.category_filter,
                min_relevance_score=self.min_relevance_score
            )

            # Convert to Documents
            documents = []
            for item_id, bm25_score in search_results:
                doc = self._create_document_from_item(
                    item_id=item_id,
                    score=bm25_score,
                    score_type="bm25"
                )
                if doc:
                    documents.append(doc)

            return documents

        except Exception as e:
            logger.error(f"BM25 retrieval failed: {e}")
            return []

    def _create_document_from_item(
        self,
        item_id: str,
        score: float,
        score_type: str
    ) -> Optional[Document]:
        """Convert item to LangChain Document."""
        try:
            # Fetch item and analysis
            item = database.get_item(item_id)
            if not item:
                logger.warning(f"Item not found: {item_id}")
                return None

            analysis = database.get_latest_analysis(item_id)
            if not analysis:
                logger.warning(f"No analysis for item: {item_id}")
                return None

            # Extract raw_response data
            raw_response = analysis.get("raw_response", {})
            summary = raw_response.get("summary", "")

            # Construct metadata
            metadata = {
                "item_id": item_id,
                "score": score,
                "score_type": score_type,
                "category": raw_response.get("category"),
                "headline": raw_response.get("headline"),
                "summary": summary,
                "image_url": f"/images/{item['filename']}",
                "filename": item["filename"],
                "raw_response": raw_response,
            }

            # Create Document
            return Document(
                page_content=summary,
                metadata=metadata
            )

        except Exception as e:
            logger.error(f"Failed to create document for {item_id}: {e}")
            return None


class VectorLangChainRetriever(BaseRetriever):
    """LangChain retriever wrapping sqlite-vec vector search."""

    top_k: int = 10
    category_filter: Optional[str] = None
    min_similarity_score: float = 0.0
    embedding_model: str = "voyage-3.5-lite"

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Optional[CallbackManagerForRetrieverRun] = None
    ) -> List[Document]:
        """Execute vector search and return as LangChain Documents."""
        try:
            # Generate query embedding
            query_embedding = embeddings.generate_query_embedding(
                query=query,
                model=self.embedding_model
            )

            # Call native database vector search
            search_results = database.vector_search_items(
                query_embedding=query_embedding,
                top_k=self.top_k,
                category_filter=self.category_filter,
                min_similarity_score=self.min_similarity_score
            )

            # Convert to Documents
            documents = []
            for item_id, similarity in search_results:
                doc = self._create_document_from_item(
                    item_id=item_id,
                    score=similarity,
                    score_type="similarity"
                )
                if doc:
                    documents.append(doc)

            return documents

        except Exception as e:
            logger.error(f"Vector retrieval failed: {e}")
            return []

    def _create_document_from_item(
        self,
        item_id: str,
        score: float,
        score_type: str
    ) -> Optional[Document]:
        """Convert item to LangChain Document."""
        try:
            # Fetch item and analysis
            item = database.get_item(item_id)
            if not item:
                logger.warning(f"Item not found: {item_id}")
                return None

            analysis = database.get_latest_analysis(item_id)
            if not analysis:
                logger.warning(f"No analysis for item: {item_id}")
                return None

            # Extract raw_response data
            raw_response = analysis.get("raw_response", {})
            summary = raw_response.get("summary", "")

            # Construct metadata
            metadata = {
                "item_id": item_id,
                "score": score,
                "score_type": score_type,
                "category": raw_response.get("category"),
                "headline": raw_response.get("headline"),
                "summary": summary,
                "image_url": f"/images/{item['filename']}",
                "filename": item["filename"],
                "raw_response": raw_response,
            }

            # Create Document
            return Document(
                page_content=summary,
                metadata=metadata
            )

        except Exception as e:
            logger.error(f"Failed to create document for {item_id}: {e}")
            return None

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
    embedding_model: str = "voyage-3.5-lite"
    rrf_c: int = 15                          # RRF constant (optimized for sensitivity)

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
            embedding_model=self.embedding_model
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
