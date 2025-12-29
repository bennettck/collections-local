"""
PostgreSQL BM25 retriever for Collections Local API.

Uses PostgreSQL full-text search (tsvector/tsquery) with ts_rank for BM25-like scoring.
Queries the langchain_pg_embedding table directly - the single source of truth for search.

ARCHITECTURE NOTE:
- All search (vector, BM25, hybrid) uses the langchain_pg_embedding table
- This avoids data duplication and sync issues
- The 'document' column contains the text content for BM25 search
- The 'cmetadata' column contains user_id, category, and other filters
"""

import logging
from typing import List, Optional, Dict, Any
import psycopg2
from psycopg2.extras import RealDictCursor

from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langsmith import traceable

logger = logging.getLogger(__name__)


class PostgresBM25Retriever(BaseRetriever):
    """LangChain retriever using PostgreSQL full-text search for BM25-like scoring.

    IMPORTANT: Queries the langchain_pg_embedding table directly.
    This is the same table used by PGVector for semantic search, ensuring
    data consistency between BM25 and vector search.

    Features:
    - PostgreSQL tsvector for full-text indexing
    - ts_rank for BM25-style scoring
    - User ID filtering (user isolation via cmetadata)
    - Category filtering (via cmetadata)
    - Collection filtering (via langchain_pg_collection join)
    - Returns LangChain Document objects
    """

    # Configuration
    top_k: int = 10
    user_id: Optional[str] = None
    category_filter: Optional[str] = None
    min_relevance_score: float = 0.0
    connection_string: Optional[str] = None
    use_parameter_store: bool = True
    parameter_name: str = "/collections-local/rds/connection-string"

    # Collection name must match the one used by PGVectorStoreManager
    collection_name: str = "collections_vectors_prod"

    class Config:
        """Pydantic config."""
        arbitrary_types_allowed = True

    def __init__(self, **kwargs):
        """Initialize PostgreSQL BM25 retriever."""
        super().__init__(**kwargs)

        # Load connection string if not provided
        if not self.connection_string:
            from database_orm.connection import get_connection_string
            self.connection_string = get_connection_string()

        # Get collection name from config if not explicitly set
        if self.collection_name == "collections_vectors_prod":
            try:
                from config.langchain_config import get_vector_store_config
                vector_config = get_vector_store_config("prod")
                self.collection_name = vector_config["collection_name"]
            except ImportError:
                pass  # Use default

    @traceable(name="postgres_bm25_retrieval", run_type="retriever")
    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Optional[CallbackManagerForRetrieverRun] = None
    ) -> List[Document]:
        """Execute BM25 search using PostgreSQL full-text search on langchain_pg_embedding.

        Args:
            query: Search query string
            run_manager: Callback manager (optional)

        Returns:
            List of relevant Documents
        """
        # Use print for Lambda visibility
        print(f"[BM25] Starting search: query='{query}', user_id={self.user_id}, collection={self.collection_name}")

        try:
            # Format query for tsquery (handle multi-word queries)
            formatted_query = self._format_query_for_tsquery(query)

            if not formatted_query:
                print("[BM25] Empty query after formatting, returning empty results")
                return []

            # Build SQL query that joins with collection table and searches document content
            # The langchain_pg_embedding table has: id, collection_id, embedding, document, cmetadata
            # The langchain_pg_collection table has: uuid, name, cmetadata
            sql = """
                SELECT
                    e.id,
                    e.document,
                    e.cmetadata,
                    ts_rank(to_tsvector('english', e.document), to_tsquery('english', %s)) as score
                FROM langchain_pg_embedding e
                JOIN langchain_pg_collection c ON e.collection_id = c.uuid
                WHERE c.name = %s
                  AND to_tsvector('english', e.document) @@ to_tsquery('english', %s)
            """

            params = [formatted_query, self.collection_name, formatted_query]

            # Add user_id filter if specified
            if self.user_id:
                sql += " AND e.cmetadata->>'user_id' = %s"
                params.append(self.user_id)

            # Add category filter if specified
            if self.category_filter:
                sql += " AND e.cmetadata->>'category' = %s"
                params.append(self.category_filter)

            # Order by score and limit
            sql += " ORDER BY score DESC LIMIT %s"
            params.append(self.top_k)

            print(f"[BM25] Executing query with params: collection={self.collection_name}, user_id={self.user_id}")

            # Execute query
            with psycopg2.connect(self.connection_string) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(sql, params)
                    rows = cursor.fetchall()

            print(f"[BM25] Raw query returned {len(rows)} rows")

            # Convert to Documents
            documents = []
            for row in rows:
                score = float(row['score']) if row['score'] else 0.0

                # Filter by minimum relevance score
                if score < self.min_relevance_score:
                    continue

                # Get metadata from cmetadata column
                metadata = row['cmetadata'] or {}
                if isinstance(metadata, str):
                    import json
                    metadata = json.loads(metadata)

                # Add score to metadata
                metadata['score'] = score
                metadata['score_type'] = 'bm25'

                # Create Document
                doc = Document(
                    page_content=row['document'] or '',
                    metadata=metadata
                )
                documents.append(doc)

            print(f"[BM25] Returning {len(documents)} documents after score filter")
            logger.info(f"PostgreSQL BM25 search returned {len(documents)} documents")
            return documents

        except psycopg2.errors.UndefinedTable as e:
            # Table doesn't exist - this is expected if no embeddings have been created yet
            print(f"[BM25] Table not found (no embeddings yet): {e}")
            logger.warning(f"BM25 table not found - no embeddings exist yet: {e}")
            return []

        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            print(f"[BM25] ERROR: {e}")
            print(f"[BM25] TRACEBACK: {error_trace}")
            logger.error(f"PostgreSQL BM25 search failed: {e}")
            # Re-raise to allow caller to handle or log
            # Don't silently return empty results
            raise

    def _format_query_for_tsquery(self, query: str) -> str:
        """Format query string for PostgreSQL tsquery.

        Handles multi-word queries by converting to OR-based tsquery format.
        Using OR allows matching documents that contain any of the query terms,
        which is more forgiving for natural language queries.

        Args:
            query: Raw query string

        Returns:
            Formatted tsquery string (e.g., "word1 | word2 | word3")
        """
        if not query:
            return ""

        # Split query into words
        words = query.strip().split()

        # Escape special characters and filter empty words
        formatted_words = []
        for word in words:
            # Remove special characters that could break tsquery
            # Keep alphanumeric and hyphens
            clean_word = ''.join(c for c in word if c.isalnum() or c == '-')
            if clean_word and len(clean_word) > 1:  # Skip single-char words
                formatted_words.append(clean_word)

        if not formatted_words:
            return ""

        # Join with OR operator for more inclusive matching
        # BM25 scoring will rank documents with more matches higher
        return ' | '.join(formatted_words)

    def get_table_stats(self) -> Dict[str, Any]:
        """Get statistics about the BM25-searchable documents.

        Returns:
            Dictionary with table stats
        """
        try:
            sql = """
                SELECT COUNT(*) as count
                FROM langchain_pg_embedding e
                JOIN langchain_pg_collection c ON e.collection_id = c.uuid
                WHERE c.name = %s
            """
            params = [self.collection_name]

            if self.user_id:
                sql = sql.replace("WHERE c.name = %s", "WHERE c.name = %s AND e.cmetadata->>'user_id' = %s")
                params.append(self.user_id)

            with psycopg2.connect(self.connection_string) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(sql, params)
                    result = cursor.fetchone()
                    count = result['count'] if result else 0

            return {
                "collection_name": self.collection_name,
                "document_count": count,
                "user_id": self.user_id,
                "category_filter": self.category_filter,
                "source_table": "langchain_pg_embedding"
            }

        except Exception as e:
            logger.error(f"Failed to get table stats: {e}")
            return {
                "collection_name": self.collection_name,
                "error": str(e)
            }
