"""
Image Processor Lambda Handler.

Triggered by S3 uploads, this Lambda:
1. Parses S3 event to get bucket/key
2. Downloads image using boto3
3. Creates thumbnail (max 800x800) using Pillow
4. Uploads thumbnail back to S3 with key pattern: {user_id}/thumbnails/{filename}
5. Publishes "ImageProcessed" event to EventBridge
"""

import os
import json
import logging
import tempfile
from typing import Dict, Any
from urllib.parse import unquote_plus
import boto3
from PIL import Image

# Setup logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3_client = boto3.client('s3')
events_client = boto3.client('events')

# Configuration from environment variables
BUCKET_NAME = os.environ.get('BUCKET_NAME', '')
EVENT_BUS_NAME = os.environ.get('EVENT_BUS_NAME', 'default')

# Image processing configuration
THUMBNAIL_MAX_SIZE = (800, 800)
THUMBNAIL_QUALITY = 85


def parse_s3_event(event: Dict[str, Any]) -> tuple[str, str]:
    """
    Parse S3 event to extract bucket and key.

    Args:
        event: Lambda event dictionary from S3

    Returns:
        Tuple of (bucket_name, object_key)

    Raises:
        ValueError: If event format is invalid
    """
    try:
        # S3 events have a 'Records' array
        record = event['Records'][0]
        bucket = record['s3']['bucket']['name']
        key = unquote_plus(record['s3']['object']['key'])

        logger.info(f"Parsed S3 event: bucket={bucket}, key={key}")
        return bucket, key

    except (KeyError, IndexError) as e:
        logger.error(f"Invalid S3 event format: {e}")
        raise ValueError(f"Invalid S3 event format: {e}")


def extract_user_id_from_key(key: str) -> str:
    """
    Extract user_id from S3 key.

    Expected format: {user_id}/{filename}

    Args:
        key: S3 object key

    Returns:
        user_id string

    Raises:
        ValueError: If key format is invalid
    """
    parts = key.split('/')
    if len(parts) < 2:
        raise ValueError(f"Invalid key format (expected user_id/filename): {key}")

    user_id = parts[0]
    logger.info(f"Extracted user_id: {user_id}")
    return user_id


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


def create_thumbnail(image_path: str) -> str:
    """
    Create thumbnail from image using Pillow.

    Maintains aspect ratio and uses THUMBNAIL_MAX_SIZE as maximum dimensions.

    Args:
        image_path: Path to original image

    Returns:
        Path to thumbnail file

    Raises:
        Exception: If image processing fails
    """
    logger.info(f"Creating thumbnail from {image_path}")

    # Open image
    with Image.open(image_path) as img:
        # Convert RGBA to RGB if needed (for JPEG)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background

        # Create thumbnail (maintains aspect ratio)
        img.thumbnail(THUMBNAIL_MAX_SIZE, Image.Resampling.LANCZOS)

        # Save to temporary file
        fd, thumbnail_path = tempfile.mkstemp(suffix='.jpg')
        os.close(fd)

        img.save(thumbnail_path, 'JPEG', quality=THUMBNAIL_QUALITY, optimize=True)

        logger.info(f"Thumbnail created: {thumbnail_path} (size: {img.size})")
        return thumbnail_path


def upload_thumbnail(bucket: str, thumbnail_path: str, user_id: str, filename: str) -> str:
    """
    Upload thumbnail to S3.

    Args:
        bucket: S3 bucket name
        thumbnail_path: Path to thumbnail file
        user_id: User identifier
        filename: Original filename

    Returns:
        S3 key of uploaded thumbnail
    """
    # Generate thumbnail key: {user_id}/thumbnails/{filename}
    base_filename = os.path.basename(filename)
    # Replace extension with .jpg
    base_filename = os.path.splitext(base_filename)[0] + '.jpg'
    thumbnail_key = f"{user_id}/thumbnails/{base_filename}"

    logger.info(f"Uploading thumbnail to s3://{bucket}/{thumbnail_key}")

    s3_client.upload_file(
        thumbnail_path,
        bucket,
        thumbnail_key,
        ExtraArgs={'ContentType': 'image/jpeg'}
    )

    return thumbnail_key


def publish_event(bucket: str, original_key: str, thumbnail_key: str, user_id: str, item_id: str):
    """
    Publish ImageProcessed event to EventBridge.

    Args:
        bucket: S3 bucket name
        original_key: Original image S3 key
        thumbnail_key: Thumbnail S3 key
        user_id: User identifier
        item_id: Item identifier (extracted from filename)
    """
    event_detail = {
        'item_id': item_id,
        'user_id': user_id,
        'bucket': bucket,
        'original_key': original_key,
        'thumbnail_key': thumbnail_key
    }

    logger.info(f"Publishing ImageProcessed event: {json.dumps(event_detail)}")

    events_client.put_events(
        Entries=[
            {
                'Source': 'collections.imageprocessor',
                'DetailType': 'ImageProcessed',
                'Detail': json.dumps(event_detail),
                'EventBusName': EVENT_BUS_NAME
            }
        ]
    )


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for image processing.

    Args:
        event: Lambda event (S3 event)
        context: Lambda context

    Returns:
        Response dictionary
    """
    try:
        logger.info(f"Received event: {json.dumps(event)}")

        # Parse S3 event
        bucket, original_key = parse_s3_event(event)

        # Skip thumbnail uploads (avoid infinite loop)
        if '/thumbnails/' in original_key:
            logger.info(f"Skipping thumbnail file: {original_key}")
            return {
                'statusCode': 200,
                'body': json.dumps({'message': 'Skipped thumbnail file'})
            }

        # Extract user_id from key
        user_id = extract_user_id_from_key(original_key)

        # Extract item_id from filename (assuming format: {user_id}/{item_id}.ext)
        filename = os.path.basename(original_key)
        item_id = os.path.splitext(filename)[0]

        # Download image
        image_path = download_image(bucket, original_key)

        try:
            # Create thumbnail
            thumbnail_path = create_thumbnail(image_path)

            try:
                # Upload thumbnail
                thumbnail_key = upload_thumbnail(bucket, thumbnail_path, user_id, filename)

                # Publish event
                publish_event(bucket, original_key, thumbnail_key, user_id, item_id)

                logger.info(f"Successfully processed image: {original_key}")

                return {
                    'statusCode': 200,
                    'body': json.dumps({
                        'message': 'Image processed successfully',
                        'original_key': original_key,
                        'thumbnail_key': thumbnail_key,
                        'item_id': item_id
                    })
                }

            finally:
                # Cleanup thumbnail
                if os.path.exists(thumbnail_path):
                    os.unlink(thumbnail_path)

        finally:
            # Cleanup original image
            if os.path.exists(image_path):
                os.unlink(image_path)

    except Exception as e:
        logger.error(f"Error processing image: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e)
            })
        }
