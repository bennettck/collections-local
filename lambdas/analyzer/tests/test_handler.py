"""
Unit tests for Analyzer Lambda handler.
"""

import json
import os
from unittest.mock import Mock, patch, MagicMock
import pytest


# Import handler module
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from handler import (
    parse_eventbridge_event,
    handler
)


class TestParseEventBridgeEvent:
    """Tests for parse_eventbridge_event function."""

    def test_parse_valid_event(self):
        """Test parsing valid EventBridge event."""
        event = {
            'detail': {
                'item_id': 'item123',
                'user_id': 'user456',
                'bucket': 'test-bucket',
                'original_key': 'user456/item123.jpg',
                'thumbnail_key': 'user456/thumbnails/item123.jpg'
            }
        }

        detail = parse_eventbridge_event(event)

        assert detail['item_id'] == 'item123'
        assert detail['user_id'] == 'user456'
        assert detail['bucket'] == 'test-bucket'
        assert detail['original_key'] == 'user456/item123.jpg'

    def test_parse_event_missing_detail(self):
        """Test parsing event with missing detail."""
        event = {}

        with pytest.raises(ValueError, match="Invalid EventBridge event format"):
            parse_eventbridge_event(event)

    def test_parse_event_missing_required_field(self):
        """Test parsing event with missing required field."""
        event = {
            'detail': {
                'item_id': 'item123',
                # Missing user_id, bucket, original_key
            }
        }

        with pytest.raises(ValueError, match="Missing required field"):
            parse_eventbridge_event(event)


class TestHandler:
    """Tests for Lambda handler function."""

    @patch('handler.ensure_db_connection')
    @patch('handler.get_api_keys')
    @patch('handler.s3_client')
    @patch('handler.events_client')
    @patch('handler.llm.analyze_image')
    @patch('handler.llm.get_resolved_provider_and_model')
    @patch('handler.get_session')
    def test_handler_success(
        self,
        mock_get_session,
        mock_get_provider,
        mock_analyze,
        mock_events,
        mock_s3,
        mock_get_keys,
        mock_ensure_db
    ):
        """Test successful image analysis."""
        # Setup mocks
        mock_ensure_db.return_value = None
        mock_get_keys.return_value = None

        # Mock S3 download
        def mock_download(bucket, key, path):
            # Create a dummy file
            with open(path, 'wb') as f:
                f.write(b'fake image data')

        mock_s3.download_file = Mock(side_effect=mock_download)

        # Mock LLM analysis
        mock_analyze.return_value = (
            {
                'category': 'Travel',
                'summary': 'A beautiful landscape',
                'headline': 'Mountain View'
            },
            'trace-123'
        )

        # Mock provider resolution
        mock_get_provider.return_value = ('anthropic', 'claude-sonnet-4-5')

        # Mock database session
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_session.scalar = Mock(return_value=0)  # First version
        mock_get_session.return_value = mock_session

        # Mock EventBridge
        mock_events.put_events = Mock(return_value={})

        # Create EventBridge event
        event = {
            'detail': {
                'item_id': 'item123',
                'user_id': 'user456',
                'bucket': 'test-bucket',
                'original_key': 'user456/item123.jpg',
                'thumbnail_key': 'user456/thumbnails/item123.jpg'
            }
        }

        # Call handler
        response = handler(event, None)

        # Verify response
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['item_id'] == 'item123'
        assert 'analysis_id' in body
        assert body['category'] == 'Travel'

        # Verify S3 download was called
        mock_s3.download_file.assert_called_once()

        # Verify LLM analysis was called
        mock_analyze.assert_called_once()

        # Verify database operations
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

        # Verify EventBridge publish was called
        mock_events.put_events.assert_called_once()
        call_args = mock_events.put_events.call_args
        entries = call_args[1]['Entries']
        assert len(entries) == 1
        assert entries[0]['Source'] == 'collections.analyzer'
        assert entries[0]['DetailType'] == 'AnalysisComplete'

        event_detail = json.loads(entries[0]['Detail'])
        assert event_detail['item_id'] == 'item123'
        assert event_detail['user_id'] == 'user456'

    @patch('handler.ensure_db_connection')
    @patch('handler.get_api_keys')
    def test_handler_invalid_event(self, mock_get_keys, mock_ensure_db):
        """Test handler with invalid event format."""
        mock_ensure_db.return_value = None
        mock_get_keys.return_value = None

        event = {'invalid': 'event'}

        # Call handler
        response = handler(event, None)

        # Verify error response
        assert response['statusCode'] == 500
        body = json.loads(response['body'])
        assert 'error' in body

    @patch('handler.ensure_db_connection')
    @patch('handler.get_api_keys')
    @patch('handler.s3_client')
    def test_handler_s3_download_error(self, mock_s3, mock_get_keys, mock_ensure_db):
        """Test handler with S3 download error."""
        mock_ensure_db.return_value = None
        mock_get_keys.return_value = None

        # Mock S3 to raise error
        mock_s3.download_file = Mock(side_effect=Exception('S3 error'))

        # Create valid event
        event = {
            'detail': {
                'item_id': 'item123',
                'user_id': 'user456',
                'bucket': 'test-bucket',
                'original_key': 'user456/item123.jpg'
            }
        }

        # Call handler
        response = handler(event, None)

        # Verify error response
        assert response['statusCode'] == 500
        body = json.loads(response['body'])
        assert 'error' in body

    @patch('handler.ensure_db_connection')
    @patch('handler.get_api_keys')
    @patch('handler.s3_client')
    @patch('handler.llm.analyze_image')
    def test_handler_llm_error(self, mock_analyze, mock_s3, mock_get_keys, mock_ensure_db):
        """Test handler with LLM analysis error."""
        mock_ensure_db.return_value = None
        mock_get_keys.return_value = None

        # Mock S3 download
        def mock_download(bucket, key, path):
            with open(path, 'wb') as f:
                f.write(b'fake image data')

        mock_s3.download_file = Mock(side_effect=mock_download)

        # Mock LLM to raise error
        mock_analyze.side_effect = Exception('LLM error')

        # Create valid event
        event = {
            'detail': {
                'item_id': 'item123',
                'user_id': 'user456',
                'bucket': 'test-bucket',
                'original_key': 'user456/item123.jpg'
            }
        }

        # Call handler
        response = handler(event, None)

        # Verify error response
        assert response['statusCode'] == 500
        body = json.loads(response['body'])
        assert 'error' in body
