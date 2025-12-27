"""
PostgreSQL BM25 retriever for Collections Local API.

Uses PostgreSQL full-text search (tsvector/tsquery) with ts_rank for BM25-like scoring.
Replaces SQLite FTS5 with PostgreSQL for AWS RDS compatibility.
"""

import logging
import json
import os
from typing import List, Optional, Dict, Any
import boto3
import psycopg2
from psycopg2.extras import RealDictCursor

from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langsmith import traceable

logger = logging.getLogger(__name__)


class PostgresBM25Retriever(BaseRetriever):
    """LangChain retriever using PostgreSQL full-text search for BM25-like scoring.

    Features:
    - PostgreSQL tsvector for full-text indexing
    - ts_rank for BM25-style scoring
    - User ID filtering (user isolation)
    - Category filtering
    - Returns LangChain Document objects
    - Connection string from AWS Parameter Store
    """

    # Configuration
    top_k: int = 10
    user_id: Optional[str] = None
    category_filter: Optional[str] = None
    min_relevance_score: float = 0.0
    connection_string: Optional[str] = None
    use_parameter_store: bool = True
    parameter_name: str = "/collections-local/rds/connection-string"
    table_name: str = "collections_documents"

    class Config:
        """Pydantic config."""
        arbitrary_types_allowed = True

    def __init__(self, **kwargs):
        """Initialize PostgreSQL BM25 retriever."""
        super().__init__(**kwargs)

        # Load connection string if not provided
        if not self.connection_string:
            if self.use_parameter_store:
                self.connection_string = self._load_connection_string_from_parameter_store(
                    self.parameter_name
                )
            else:
                self.connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
                if not self.connection_string:
                    raise ValueError(
                        "No connection string provided. Set POSTGRES_CONNECTION_STRING "
                        "environment variable or enable use_parameter_store"
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

    @traceable(name="postgres_bm25_retrieval", run_type="retriever")
    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Optional[CallbackManagerForRetrieverRun] = None
    ) -> List[Document]:
        """Execute BM25 search using PostgreSQL full-text search.

        Args:
            query: Search query string
            run_manager: Callback manager (optional)

        Returns:
            List of relevant Documents
        """
        try:
            # Format query for tsquery (handle multi-word queries)
            formatted_query = self._format_query_for_tsquery(query)

            # Build WHERE clause for filters
            where_clauses = []
            params = [formatted_query]

            if self.user_id:
                where_clauses.append("metadata->>'user_id' = %s")
                params.append(self.user_id)

            if self.category_filter:
                where_clauses.append("metadata->>'category' = %s")
                params.append(self.category_filter)

            where_clause = ""
            if where_clauses:
                where_clause = "AND " + " AND ".join(where_clauses)

            # Execute search query
            sql = f"""
                SELECT
                    item_id,
                    content,
                    metadata,
                    ts_rank(search_vector, to_tsquery('english', %s)) as score
                FROM {self.table_name}
                WHERE search_vector @@ to_tsquery('english', %s)
                {where_clause}
                ORDER BY score DESC
                LIMIT %s
            """

            # Add query parameter twice (for ranking and matching)
            final_params = [formatted_query, *params, self.top_k]

            # Execute query
            with psycopg2.connect(self.connection_string) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(sql, final_params)
                    rows = cursor.fetchall()

            # Convert to Documents
            documents = []
            for row in rows:
                score = float(row['score'])

                # Filter by minimum relevance score
                if score < self.min_relevance_score:
                    continue

                # Parse metadata JSON
                metadata = row['metadata']
                if isinstance(metadata, str):
                    metadata = json.loads(metadata)

                # Add score to metadata
                metadata['score'] = score
                metadata['score_type'] = 'bm25'

                # Create Document
                doc = Document(
                    page_content=row['content'],
                    metadata=metadata
                )
                documents.append(doc)

            logger.info(f"PostgreSQL BM25 search returned {len(documents)} documents")
            return documents

        except Exception as e:
            logger.error(f"PostgreSQL BM25 search failed: {e}")
            return []

    def _format_query_for_tsquery(self, query: str) -> str:
        """Format query string for PostgreSQL tsquery.

        Handles multi-word queries by converting to AND-based tsquery format.

        Args:
            query: Raw query string

        Returns:
            Formatted tsquery string (e.g., "word1 & word2 & word3")
        """
        # Split query into words
        words = query.strip().split()

        # Escape special characters and join with AND operator
        formatted_words = []
        for word in words:
            # Remove special characters that could break tsquery
            clean_word = ''.join(c for c in word if c.isalnum() or c == '-')
            if clean_word:
                formatted_words.append(clean_word)

        # Join with AND operator
        return ' & '.join(formatted_words) if formatted_words else query

    def add_document(
        self,
        item_id: str,
        content: str,
        metadata: Dict[str, Any]
    ) -> bool:
        """Add or update a document in the PostgreSQL BM25 index.

        Args:
            item_id: Item identifier
            content: Document content
            metadata: Document metadata

        Returns:
            True if successful, False otherwise
        """
        try:
            # Ensure user_id is in metadata if set
            if self.user_id and 'user_id' not in metadata:
                metadata['user_id'] = self.user_id

            sql = f"""
                INSERT INTO {self.table_name} (item_id, content, metadata, search_vector)
                VALUES (%s, %s, %s, to_tsvector('english', %s))
                ON CONFLICT (item_id)
                DO UPDATE SET
                    content = EXCLUDED.content,
                    metadata = EXCLUDED.metadata,
                    search_vector = EXCLUDED.search_vector
            """

            with psycopg2.connect(self.connection_string) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        sql,
                        (item_id, content, json.dumps(metadata), content)
                    )
                conn.commit()

            logger.info(f"Added document to PostgreSQL BM25 index: {item_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to add document to PostgreSQL BM25 index: {item_id}, error: {e}")
            return False

    def create_table_if_not_exists(self) -> bool:
        """Create the BM25 index table if it doesn't exist.

        Returns:
            True if successful, False otherwise
        """
        try:
            sql = f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    item_id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    metadata JSONB NOT NULL,
                    search_vector tsvector,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_search_vector
                ON {self.table_name} USING GIN(search_vector);

                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_user_id
                ON {self.table_name} USING GIN((metadata->'user_id'));

                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_category
                ON {self.table_name} USING GIN((metadata->'category'));
            """

            with psycopg2.connect(self.connection_string) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql)
                conn.commit()

            logger.info(f"Created PostgreSQL BM25 table: {self.table_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to create PostgreSQL BM25 table: {e}")
            return False

    def get_table_stats(self) -> Dict[str, Any]:
        """Get statistics about the BM25 table.

        Returns:
            Dictionary with table stats
        """
        try:
            sql = f"SELECT COUNT(*) as count FROM {self.table_name}"

            with psycopg2.connect(self.connection_string) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(sql)
                    result = cursor.fetchone()
                    count = result['count']

            return {
                "table_name": self.table_name,
                "document_count": count,
                "user_id": self.user_id,
                "category_filter": self.category_filter
            }

        except Exception as e:
            logger.error(f"Failed to get table stats: {e}")
            return {
                "table_name": self.table_name,
                "error": str(e)
            }
