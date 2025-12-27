"""
Unit tests for Image Processor Lambda handler.
"""

import json
import os
import tempfile
from unittest.mock import Mock, patch, MagicMock
import pytest
from PIL import Image


# Import handler module
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from handler import (
    parse_s3_event,
    extract_user_id_from_key,
    create_thumbnail,
    handler
)


class TestParseS3Event:
    """Tests for parse_s3_event function."""

    def test_parse_valid_s3_event(self):
        """Test parsing valid S3 event."""
        event = {
            'Records': [
                {
                    's3': {
                        'bucket': {'name': 'test-bucket'},
                        'object': {'key': 'user123/image.jpg'}
                    }
                }
            ]
        }

        bucket, key = parse_s3_event(event)

        assert bucket == 'test-bucket'
        assert key == 'user123/image.jpg'

    def test_parse_url_encoded_key(self):
        """Test parsing S3 event with URL-encoded key."""
        event = {
            'Records': [
                {
                    's3': {
                        'bucket': {'name': 'test-bucket'},
                        'object': {'key': 'user123/my+image.jpg'}
                    }
                }
            ]
        }

        bucket, key = parse_s3_event(event)

        assert bucket == 'test-bucket'
        assert key == 'user123/my image.jpg'  # URL decoded

    def test_parse_invalid_event_missing_records(self):
        """Test parsing event with missing Records."""
        event = {}

        with pytest.raises(ValueError, match="Invalid S3 event format"):
            parse_s3_event(event)

    def test_parse_invalid_event_empty_records(self):
        """Test parsing event with empty Records."""
        event = {'Records': []}

        with pytest.raises(ValueError, match="Invalid S3 event format"):
            parse_s3_event(event)


class TestExtractUserIdFromKey:
    """Tests for extract_user_id_from_key function."""

    def test_extract_valid_user_id(self):
        """Test extracting user_id from valid key."""
        key = 'user123/image.jpg'
        user_id = extract_user_id_from_key(key)
        assert user_id == 'user123'

    def test_extract_user_id_with_subdirectories(self):
        """Test extracting user_id with subdirectories."""
        key = 'user456/uploads/2024/image.jpg'
        user_id = extract_user_id_from_key(key)
        assert user_id == 'user456'

    def test_extract_invalid_key_no_slash(self):
        """Test extracting from invalid key without slash."""
        key = 'image.jpg'

        with pytest.raises(ValueError, match="Invalid key format"):
            extract_user_id_from_key(key)


class TestCreateThumbnail:
    """Tests for create_thumbnail function."""

    def test_create_thumbnail_from_jpeg(self):
        """Test creating thumbnail from JPEG image."""
        # Create a test image
        test_image = Image.new('RGB', (1600, 1200), color='red')
        fd, image_path = tempfile.mkstemp(suffix='.jpg')
        os.close(fd)
        test_image.save(image_path, 'JPEG')

        try:
            # Create thumbnail
            thumbnail_path = create_thumbnail(image_path)

            try:
                # Verify thumbnail exists
                assert os.path.exists(thumbnail_path)

                # Verify thumbnail size (should be 800x600 maintaining aspect ratio)
                with Image.open(thumbnail_path) as thumb:
                    assert thumb.size[0] <= 800
                    assert thumb.size[1] <= 800
                    assert thumb.format == 'JPEG'

            finally:
                if os.path.exists(thumbnail_path):
                    os.unlink(thumbnail_path)

        finally:
            if os.path.exists(image_path):
                os.unlink(image_path)

    def test_create_thumbnail_from_png(self):
        """Test creating thumbnail from PNG image (with transparency)."""
        # Create a test image with transparency
        test_image = Image.new('RGBA', (1000, 1000), color=(255, 0, 0, 128))
        fd, image_path = tempfile.mkstemp(suffix='.png')
        os.close(fd)
        test_image.save(image_path, 'PNG')

        try:
            # Create thumbnail
            thumbnail_path = create_thumbnail(image_path)

            try:
                # Verify thumbnail exists and is JPEG (converted from RGBA)
                assert os.path.exists(thumbnail_path)

                with Image.open(thumbnail_path) as thumb:
                    assert thumb.size[0] <= 800
                    assert thumb.size[1] <= 800
                    assert thumb.format == 'JPEG'
                    assert thumb.mode == 'RGB'  # Converted from RGBA

            finally:
                if os.path.exists(thumbnail_path):
                    os.unlink(thumbnail_path)

        finally:
            if os.path.exists(image_path):
                os.unlink(image_path)

    def test_create_thumbnail_small_image(self):
        """Test creating thumbnail from image already smaller than max size."""
        # Create a small test image
        test_image = Image.new('RGB', (400, 300), color='blue')
        fd, image_path = tempfile.mkstemp(suffix='.jpg')
        os.close(fd)
        test_image.save(image_path, 'JPEG')

        try:
            # Create thumbnail
            thumbnail_path = create_thumbnail(image_path)

            try:
                # Verify thumbnail preserves original size (doesn't upscale)
                with Image.open(thumbnail_path) as thumb:
                    assert thumb.size == (400, 300)

            finally:
                if os.path.exists(thumbnail_path):
                    os.unlink(thumbnail_path)

        finally:
            if os.path.exists(image_path):
                os.unlink(image_path)


class TestHandler:
    """Tests for Lambda handler function."""

    @patch('handler.s3_client')
    @patch('handler.events_client')
    def test_handler_success(self, mock_events, mock_s3):
        """Test successful image processing."""
        # Setup mock S3 download
        def mock_download(bucket, key, path):
            # Create a test image at the path
            img = Image.new('RGB', (1000, 1000), color='green')
            img.save(path, 'JPEG')

        mock_s3.download_file = Mock(side_effect=mock_download)
        mock_s3.upload_file = Mock()
        mock_events.put_events = Mock(return_value={})

        # Create S3 event
        event = {
            'Records': [
                {
                    's3': {
                        'bucket': {'name': 'test-bucket'},
                        'object': {'key': 'user123/item456.jpg'}
                    }
                }
            ]
        }

        # Call handler
        response = handler(event, None)

        # Verify response
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['item_id'] == 'item456'
        assert 'thumbnail_key' in body

        # Verify S3 upload was called
        mock_s3.upload_file.assert_called_once()

        # Verify EventBridge publish was called
        mock_events.put_events.assert_called_once()
        call_args = mock_events.put_events.call_args
        entries = call_args[1]['Entries']
        assert len(entries) == 1
        assert entries[0]['Source'] == 'collections.imageprocessor'
        assert entries[0]['DetailType'] == 'ImageProcessed'

        event_detail = json.loads(entries[0]['Detail'])
        assert event_detail['item_id'] == 'item456'
        assert event_detail['user_id'] == 'user123'

    @patch('handler.s3_client')
    @patch('handler.events_client')
    def test_handler_skips_thumbnails(self, mock_events, mock_s3):
        """Test handler skips thumbnail files to avoid infinite loop."""
        event = {
            'Records': [
                {
                    's3': {
                        'bucket': {'name': 'test-bucket'},
                        'object': {'key': 'user123/thumbnails/item456.jpg'}
                    }
                }
            ]
        }

        # Call handler
        response = handler(event, None)

        # Verify response
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['message'] == 'Skipped thumbnail file'

        # Verify S3 download was NOT called
        mock_s3.download_file.assert_not_called()

        # Verify EventBridge publish was NOT called
        mock_events.put_events.assert_not_called()

    @patch('handler.s3_client')
    @patch('handler.events_client')
    def test_handler_error_handling(self, mock_events, mock_s3):
        """Test handler error handling."""
        # Setup mock S3 to raise error
        mock_s3.download_file = Mock(side_effect=Exception('S3 error'))

        # Create S3 event
        event = {
            'Records': [
                {
                    's3': {
                        'bucket': {'name': 'test-bucket'},
                        'object': {'key': 'user123/item456.jpg'}
                    }
                }
            ]
        }

        # Call handler
        response = handler(event, None)

        # Verify error response
        assert response['statusCode'] == 500
        body = json.loads(response['body'])
        assert 'error' in body

        # Verify EventBridge publish was NOT called
        mock_events.put_events.assert_not_called()

    def test_handler_invalid_event(self):
        """Test handler with invalid event format."""
        event = {'invalid': 'event'}

        # Call handler
        response = handler(event, None)

        # Verify error response
        assert response['statusCode'] == 500
        body = json.loads(response['body'])
        assert 'error' in body
