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

        # Set environment variable for database_orm.connection
        os.environ['DATABASE_URL'] = database_url

        # Initialize database connection
        from database_orm.connection import init_connection
        init_connection(database_url=database_url)
        _db_initialized = True
        logger.info("Database connection initialized")

    except Exception as e:
        logger.error(f"Failed to initialize database connection: {e}")
        raise


def get_api_keys():
    """
    Get API keys from Parameter Store.

    Returns:
        Dictionary with API keys
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

    from database_orm.connection import get_session
    from database_orm.models import Analysis, Item

    with get_session() as session:
        from sqlalchemy import select

        # Fetch analysis
        stmt = select(Analysis).filter_by(id=analysis_id, user_id=user_id)
        analysis = session.scalar(stmt)

        if not analysis:
            raise ValueError(f"Analysis not found: {analysis_id}")

        # Fetch associated item to get filename
        item_stmt = select(Item).filter_by(id=analysis.item_id, user_id=user_id)
        item = session.scalar(item_stmt)

        if not item:
            raise ValueError(f"Item not found: {analysis.item_id}")

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
            'created_at': analysis.created_at.isoformat() if analysis.created_at else None,
            'filename': item.filename  # Include filename for document creation
        }

        logger.info(f"Analysis fetched: category={analysis.category}, filename={item.filename}")
        return analysis_dict


def store_in_vector_store(
    item_id: str,
    user_id: str,
    raw_response: dict,
    filename: str
) -> str:
    """
    Store document with embedding in langchain-postgres vector store.

    This uses PGVectorStoreManager which handles:
    - VoyageAI embedding generation
    - PostgreSQL pgvector storage
    - Proper metadata for retrieval

    Args:
        item_id: Item identifier
        user_id: User identifier
        raw_response: Analysis result dictionary
        filename: Image filename

    Returns:
        Document ID
    """
    logger.info(f"Storing document in vector store: item_id={item_id}")

    from retrieval.pgvector_store import PGVectorStoreManager

    # Initialize vector store manager
    vector_mgr = PGVectorStoreManager()

    # Add document using the convenience method
    doc_id = vector_mgr.add_document(
        item_id=item_id,
        raw_response=raw_response,
        filename=filename,
        user_id=user_id
    )

    logger.info(f"Document stored in vector store: doc_id={doc_id}")
    return doc_id


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

        # Fetch analysis from database (includes filename)
        analysis_data = fetch_analysis(analysis_id, user_id)

        # Store in langchain-postgres vector store
        # This handles embedding generation and storage
        doc_id = store_in_vector_store(
            item_id=item_id,
            user_id=user_id,
            raw_response=analysis_data['raw_response'],
            filename=analysis_data['filename']
        )

        logger.info(f"Successfully processed embedding: item_id={item_id}, doc_id={doc_id}")

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Embedding generated and stored successfully',
                'item_id': item_id,
                'doc_id': doc_id
            })
        }

    except Exception as e:
        logger.error(f"Error generating embedding: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e)
            })
        }
