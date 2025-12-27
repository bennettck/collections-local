"""
Embedder Lambda Handler.

Triggered by "AnalysisComplete" EventBridge events, this Lambda:
1. Parses EventBridge event to get analysis details
2. Fetches analysis from PostgreSQL
3. Calls embeddings.generate_embedding() with analysis data
4. Stores embedding in pgvector using langchain-postgres
5. NO EventBridge event needed (end of workflow)
"""

import os
import json
import logging
import uuid
import boto3

# Import embeddings module (copied from root)
import embeddings

# Import database modules
from database.connection import init_connection, get_session
from database.models import Analysis, Embedding

# Setup logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
ssm_client = boto3.client('ssm')

# Configuration from environment variables
DATABASE_HOST = os.environ.get('DATABASE_HOST', '')
DATABASE_PORT = os.environ.get('DATABASE_PORT', '5432')
DATABASE_NAME = os.environ.get('DATABASE_NAME', 'collections')

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


def generate_embedding_vector(analysis_data: dict) -> list[float]:
    """
    Generate embedding vector from analysis data.

    Args:
        analysis_data: Analysis dictionary with raw_response

    Returns:
        Embedding vector as list of floats
    """
    logger.info("Generating embedding from analysis data")

    # Use the same document creation logic as in embeddings.py
    raw_response = analysis_data.get('raw_response', {})

    # Create embedding document
    parts = []

    # Extract all fields once (same order as in embeddings.py)
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

    # Combine and clean
    document = " ".join([p for p in parts if p and p.strip()])

    if not document:
        raise ValueError("Empty document generated from analysis data")

    # Generate embedding using embeddings.py
    embedding_vector = embeddings.generate_embedding(document)

    logger.info(f"Embedding generated: dimensions={len(embedding_vector)}")
    return embedding_vector


def store_embedding(
    item_id: str,
    analysis_id: str,
    user_id: str,
    embedding_vector: list[float],
    model: str,
    source_fields: dict
) -> str:
    """
    Store embedding in PostgreSQL with pgvector.

    Args:
        item_id: Item identifier
        analysis_id: Analysis identifier
        user_id: User identifier
        embedding_vector: Vector embedding as list of floats
        model: Embedding model name
        source_fields: Dictionary of fields used for embedding

    Returns:
        Embedding ID
    """
    logger.info(f"Storing embedding for item_id={item_id}")

    embedding_id = str(uuid.uuid4())

    with get_session() as session:
        # Create embedding record
        embedding = Embedding(
            id=embedding_id,
            item_id=item_id,
            analysis_id=analysis_id,
            user_id=user_id,
            vector=embedding_vector,
            embedding_model=model,
            embedding_dimensions=len(embedding_vector),
            embedding_source=source_fields
        )

        session.add(embedding)
        session.commit()

        logger.info(f"Embedding stored: embedding_id={embedding_id}, dimensions={len(embedding_vector)}")

    return embedding_id


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

        # Generate embedding vector
        embedding_vector = generate_embedding_vector(analysis_data)

        # Get embedding model name from environment or use default
        model = os.environ.get('VOYAGE_EMBEDDING_MODEL', embeddings.DEFAULT_EMBEDDING_MODEL)

        # Store embedding in database
        source_fields = {
            'analysis_id': analysis_id,
            'category': analysis_data.get('category'),
            'summary': analysis_data.get('summary')
        }

        embedding_id = store_embedding(
            item_id=item_id,
            analysis_id=analysis_id,
            user_id=user_id,
            embedding_vector=embedding_vector,
            model=model,
            source_fields=source_fields
        )

        logger.info(f"Successfully generated embedding: item_id={item_id}, embedding_id={embedding_id}")

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Embedding generated successfully',
                'item_id': item_id,
                'embedding_id': embedding_id,
                'dimensions': len(embedding_vector)
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
