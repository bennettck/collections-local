"""
Embedder Lambda Handler.

Triggered by "AnalysisComplete" EventBridge events, this Lambda:
1. Parses EventBridge event to get analysis details
2. Fetches analysis from PostgreSQL
3. Stores document with embedding in langchain-postgres vector store
4. NO EventBridge event needed (end of workflow)

Uses LangChain's langchain-postgres for vector storage with VoyageAI embeddings.
This is the single source of truth for embeddings (no ORM table).
"""

import os
import json
import logging
import boto3

# Import database modules
from database_orm.connection import init_connection, get_session, get_connection_string
from database_orm.models import Analysis, Item

# Import LangChain modules for vector store
from utils.document_builder import create_langchain_document
from retrieval.pgvector_store import PGVectorStoreManager

# Setup logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
ssm_client = boto3.client('ssm')

# Database connection (initialized on cold start)
_db_initialized = False


def ensure_db_connection():
    """
    Ensure database connection is initialized.

    Retrieves DATABASE_URL from Parameter Store and initializes connection.
    """
    global _db_initialized

    if _db_initialized:
        return

    try:
        # Get DATABASE_URL from Parameter Store
        parameter_name = '/collections/DATABASE_URL'
        response = ssm_client.get_parameter(
            Name=parameter_name,
            WithDecryption=True
        )
        database_url = response['Parameter']['Value']

        # Initialize database connection
        init_connection(database_url=database_url)
        _db_initialized = True
        logger.info("Database connection initialized")

    except Exception as e:
        logger.error(f"Failed to initialize database connection: {e}")
        raise


def get_api_keys():
    """
    Get API keys from Parameter Store.
    """
    try:
        # Get Voyage API key for embeddings
        voyage_response = ssm_client.get_parameter(
            Name='/collections/VOYAGE_API_KEY',
            WithDecryption=True
        )
        os.environ['VOYAGE_API_KEY'] = voyage_response['Parameter']['Value']

        logger.info("API keys retrieved from Parameter Store")

    except Exception as e:
        logger.error(f"Failed to get API keys: {e}")
        raise


def parse_eventbridge_event(event: dict) -> dict:
    """
    Parse EventBridge event to extract analysis details.

    Args:
        event: Lambda event dictionary from EventBridge

    Returns:
        Event detail dictionary

    Raises:
        ValueError: If event format is invalid
    """
    try:
        detail = event['detail']

        required_fields = ['item_id', 'analysis_id', 'user_id']
        for field in required_fields:
            if field not in detail:
                raise ValueError(f"Missing required field: {field}")

        logger.info(f"Parsed EventBridge event: item_id={detail['item_id']}, analysis_id={detail['analysis_id']}")
        return detail

    except KeyError as e:
        logger.error(f"Invalid EventBridge event format: {e}")
        raise ValueError(f"Invalid EventBridge event format: {e}")


def fetch_analysis(analysis_id: str, user_id: str) -> dict:
    """
    Fetch analysis from PostgreSQL.

    Args:
        analysis_id: Analysis identifier
        user_id: User identifier (for security)

    Returns:
        Analysis dictionary

    Raises:
        ValueError: If analysis not found
    """
    logger.info(f"Fetching analysis: analysis_id={analysis_id}")

    with get_session() as session:
        from sqlalchemy import select

        stmt = select(Analysis).filter_by(id=analysis_id, user_id=user_id)
        analysis = session.scalar(stmt)

        if not analysis:
            raise ValueError(f"Analysis not found: {analysis_id}")

        # Convert to dictionary
        analysis_dict = {
            'id': analysis.id,
            'item_id': analysis.item_id,
            'user_id': analysis.user_id,
            'version': analysis.version,
            'category': analysis.category,
            'summary': analysis.summary,
            'raw_response': analysis.raw_response or {},
            'provider_used': analysis.provider_used,
            'model_used': analysis.model_used,
            'trace_id': analysis.trace_id,
            'created_at': analysis.created_at.isoformat() if analysis.created_at else None
        }

        logger.info(f"Analysis fetched: category={analysis.category}")
        return analysis_dict


def fetch_item_filename(item_id: str, user_id: str) -> str:
    """
    Fetch item filename from database.

    Args:
        item_id: Item identifier
        user_id: User identifier

    Returns:
        Filename string
    """
    with get_session() as session:
        from sqlalchemy import select

        stmt = select(Item).filter_by(id=item_id, user_id=user_id)
        item = session.scalar(stmt)

        if not item:
            raise ValueError(f"Item not found: {item_id}")

        return item.filename


def store_in_langchain_vectorstore(
    item_id: str,
    analysis_id: str,
    user_id: str,
    analysis_data: dict,
    filename: str
) -> None:
    """
    Store document in langchain-postgres vector store.

    This is the single source of truth for embeddings. The langchain-postgres
    library handles embedding generation via VoyageAI and storage in PostgreSQL
    with pgvector extension.

    Args:
        item_id: Item identifier
        analysis_id: Analysis identifier
        user_id: User identifier
        analysis_data: Analysis dictionary with raw_response
        filename: Image filename
    """
    logger.info(f"Storing in langchain-postgres vector store: item_id={item_id}")

    # Get connection string
    connection_string = get_connection_string()

    # Initialize PGVectorStoreManager
    pgvector_manager = PGVectorStoreManager(
        connection_string=connection_string,
        collection_name="collections_vectors"
    )

    # Get raw_response
    raw_response = analysis_data.get('raw_response', {})

    # Create LangChain document with proper metadata
    doc = create_langchain_document(
        raw_response=raw_response,
        item_id=item_id,
        filename=filename,
        category=analysis_data.get('category')
    )

    # Add additional metadata for filtering
    doc.metadata["user_id"] = user_id
    doc.metadata["analysis_id"] = analysis_id
    doc.metadata["headline"] = raw_response.get("headline", "")
    doc.metadata["summary"] = raw_response.get("summary", "")

    # Add document to vector store (generates embedding via VoyageAI internally)
    pgvector_manager.add_documents([doc], ids=[item_id])

    logger.info(f"Document stored in langchain-postgres: item_id={item_id}")


def handler(event: dict, context) -> dict:
    """
    Lambda handler for embedding generation.

    Args:
        event: Lambda event (EventBridge event)
        context: Lambda context

    Returns:
        Response dictionary
    """
    try:
        logger.info(f"Received event: {json.dumps(event)}")

        # Initialize database connection
        ensure_db_connection()

        # Get API keys from Parameter Store
        get_api_keys()

        # Parse EventBridge event
        detail = parse_eventbridge_event(event)

        item_id = detail['item_id']
        analysis_id = detail['analysis_id']
        user_id = detail['user_id']

        # Fetch analysis from database
        analysis_data = fetch_analysis(analysis_id, user_id)

        # Fetch item filename
        filename = fetch_item_filename(item_id, user_id)

        # Store in langchain-postgres vector store (single source of truth)
        store_in_langchain_vectorstore(
            item_id=item_id,
            analysis_id=analysis_id,
            user_id=user_id,
            analysis_data=analysis_data,
            filename=filename
        )

        logger.info(f"Successfully stored embedding: item_id={item_id}")

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Embedding stored successfully',
                'item_id': item_id,
                'analysis_id': analysis_id
            })
        }

    except Exception as e:
        logger.error(f"Error storing embedding: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e)
            })
        }
