"""
Analyzer Lambda Handler.

Triggered by "ImageProcessed" EventBridge events, this Lambda:
1. Parses EventBridge event to get image details
2. Downloads image from S3
3. Calls llm.analyze_image() with image path
4. Stores analysis in PostgreSQL using SQLAlchemy
5. Publishes "AnalysisComplete" event to EventBridge
"""

import os
import json
import logging
import tempfile
import uuid
import boto3

# Import llm module (copied from root)
import llm

# Import database modules
from database_orm.connection import init_connection, get_session
from database_orm.models import Analysis

# Setup logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3_client = boto3.client('s3')
events_client = boto3.client('events')
ssm_client = boto3.client('ssm')

# Configuration from environment variables
BUCKET_NAME = os.environ.get('BUCKET_NAME', '')
EVENT_BUS_NAME = os.environ.get('EVENT_BUS_NAME', 'default')
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
        # Get Anthropic API key
        anthropic_response = ssm_client.get_parameter(
            Name='/collections/ANTHROPIC_API_KEY',
            WithDecryption=True
        )
        os.environ['ANTHROPIC_API_KEY'] = anthropic_response['Parameter']['Value']

        # Get OpenAI API key (optional)
        try:
            openai_response = ssm_client.get_parameter(
                Name='/collections/OPENAI_API_KEY',
                WithDecryption=True
            )
            os.environ['OPENAI_API_KEY'] = openai_response['Parameter']['Value']
        except ssm_client.exceptions.ParameterNotFound:
            logger.warning("OpenAI API key not found in Parameter Store")

        # Get LangSmith API key (optional)
        try:
            langsmith_response = ssm_client.get_parameter(
                Name='/collections/LANGSMITH_API_KEY',
                WithDecryption=True
            )
            os.environ['LANGSMITH_API_KEY'] = langsmith_response['Parameter']['Value']
        except ssm_client.exceptions.ParameterNotFound:
            logger.warning("LangSmith API key not found in Parameter Store")

        logger.info("API keys retrieved from Parameter Store")

    except Exception as e:
        logger.error(f"Failed to get API keys: {e}")
        raise


def parse_eventbridge_event(event: dict) -> dict:
    """
    Parse EventBridge event to extract image processing details.

    Args:
        event: Lambda event dictionary from EventBridge

    Returns:
        Event detail dictionary

    Raises:
        ValueError: If event format is invalid
    """
    try:
        detail = event['detail']

        required_fields = ['item_id', 'user_id', 'bucket', 'original_key']
        for field in required_fields:
            if field not in detail:
                raise ValueError(f"Missing required field: {field}")

        logger.info(f"Parsed EventBridge event: item_id={detail['item_id']}, user_id={detail['user_id']}")
        return detail

    except KeyError as e:
        logger.error(f"Invalid EventBridge event format: {e}")
        raise ValueError(f"Invalid EventBridge event format: {e}")


def download_image(bucket: str, key: str) -> str:
    """
    Download image from S3 to temporary file.

    Args:
        bucket: S3 bucket name
        key: S3 object key

    Returns:
        Path to temporary file
    """
    # Create temporary file
    suffix = os.path.splitext(key)[1]  # Preserve file extension
    fd, temp_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)

    # Download from S3
    logger.info(f"Downloading s3://{bucket}/{key} to {temp_path}")
    s3_client.download_file(bucket, key, temp_path)

    return temp_path


def analyze_image_with_llm(image_path: str, item_id: str) -> tuple[dict, str]:
    """
    Analyze image using LLM.

    Args:
        image_path: Path to image file
        item_id: Item identifier (for metadata)

    Returns:
        Tuple of (analysis_result, trace_id)
    """
    logger.info(f"Analyzing image with LLM: {image_path}")

    # Call llm.analyze_image()
    metadata = {'item_id': item_id}
    result, trace_id = llm.analyze_image(
        image_path=image_path,
        metadata=metadata
    )

    logger.info(f"Analysis complete: category={result.get('category')}, trace_id={trace_id}")
    return result, trace_id


def store_analysis(
    item_id: str,
    user_id: str,
    result: dict,
    provider_used: str,
    model_used: str,
    trace_id: str
) -> str:
    """
    Store analysis in PostgreSQL.

    Args:
        item_id: Item identifier
        user_id: User identifier
        result: Analysis result dictionary
        provider_used: AI provider name
        model_used: Model name
        trace_id: Tracing identifier

    Returns:
        Analysis ID
    """
    logger.info(f"Storing analysis for item_id={item_id}")

    analysis_id = str(uuid.uuid4())

    with get_session() as session:
        # Get next version number
        from sqlalchemy import func, select
        stmt = (
            select(func.max(Analysis.version))
            .filter_by(item_id=item_id, user_id=user_id)
        )
        max_version = session.scalar(stmt) or 0
        version = max_version + 1

        # Create analysis record
        analysis = Analysis(
            id=analysis_id,
            item_id=item_id,
            user_id=user_id,
            version=version,
            category=result.get('category'),
            summary=result.get('summary'),
            raw_response=result,
            provider_used=provider_used,
            model_used=model_used,
            trace_id=trace_id
        )

        session.add(analysis)
        session.commit()

        logger.info(f"Analysis stored: analysis_id={analysis_id}, version={version}")

    return analysis_id


def publish_event(item_id: str, analysis_id: str, user_id: str):
    """
    Publish AnalysisComplete event to EventBridge.

    Args:
        item_id: Item identifier
        analysis_id: Analysis identifier
        user_id: User identifier
    """
    event_detail = {
        'item_id': item_id,
        'analysis_id': analysis_id,
        'user_id': user_id
    }

    logger.info(f"Publishing AnalysisComplete event: {json.dumps(event_detail)}")

    events_client.put_events(
        Entries=[
            {
                'Source': 'collections.analyzer',
                'DetailType': 'AnalysisComplete',
                'Detail': json.dumps(event_detail),
                'EventBusName': EVENT_BUS_NAME
            }
        ]
    )


def handler(event: dict, context) -> dict:
    """
    Lambda handler for image analysis.

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
        user_id = detail['user_id']
        bucket = detail['bucket']
        original_key = detail['original_key']

        # Download image
        image_path = download_image(bucket, original_key)

        try:
            # Analyze image with LLM
            result, trace_id = analyze_image_with_llm(image_path, item_id)

            # Determine provider and model used
            provider_used, model_used = llm.get_resolved_provider_and_model()

            # Store analysis in database
            analysis_id = store_analysis(
                item_id=item_id,
                user_id=user_id,
                result=result,
                provider_used=provider_used,
                model_used=model_used,
                trace_id=trace_id or ''
            )

            # Publish AnalysisComplete event
            publish_event(item_id, analysis_id, user_id)

            logger.info(f"Successfully analyzed image: item_id={item_id}, analysis_id={analysis_id}")

            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'Image analyzed successfully',
                    'item_id': item_id,
                    'analysis_id': analysis_id,
                    'category': result.get('category')
                })
            }

        finally:
            # Cleanup downloaded image
            if os.path.exists(image_path):
                os.unlink(image_path)

    except Exception as e:
        logger.error(f"Error analyzing image: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e)
            })
        }
