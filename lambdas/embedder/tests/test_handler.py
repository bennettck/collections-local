"""
Unit tests for Embedder Lambda handler.
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
    generate_embedding_vector,
    handler
)


class TestParseEventBridgeEvent:
    """Tests for parse_eventbridge_event function."""

    def test_parse_valid_event(self):
        """Test parsing valid EventBridge event."""
        event = {
            'detail': {
                'item_id': 'item123',
                'analysis_id': 'analysis456',
                'user_id': 'user789'
            }
        }

        detail = parse_eventbridge_event(event)

        assert detail['item_id'] == 'item123'
        assert detail['analysis_id'] == 'analysis456'
        assert detail['user_id'] == 'user789'

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
                # Missing analysis_id and user_id
            }
        }

        with pytest.raises(ValueError, match="Missing required field"):
            parse_eventbridge_event(event)


class TestGenerateEmbeddingVector:
    """Tests for generate_embedding_vector function."""

    @patch('handler.embeddings.generate_embedding')
    def test_generate_embedding_success(self, mock_generate):
        """Test successful embedding generation."""
        # Mock embedding generation
        mock_generate.return_value = [0.1] * 1024

        # Create analysis data
        analysis_data = {
            'raw_response': {
                'summary': 'A beautiful landscape',
                'headline': 'Mountain View',
                'category': 'Travel',
                'subcategories': ['Nature', 'Outdoors'],
                'image_details': {
                    'extracted_text': 'Welcome',
                    'themes': ['adventure', 'nature'],
                    'objects': ['mountain', 'sky'],
                    'emotions': ['peaceful', 'serene'],
                    'vibes': ['calm']
                }
            }
        }

        # Generate embedding
        embedding = generate_embedding_vector(analysis_data)

        # Verify
        assert len(embedding) == 1024
        mock_generate.assert_called_once()

    @patch('handler.embeddings.generate_embedding')
    def test_generate_embedding_empty_document(self, mock_generate):
        """Test embedding generation with empty document."""
        # Create analysis data with no content
        analysis_data = {
            'raw_response': {}
        }

        # Should raise ValueError
        with pytest.raises(ValueError, match="Empty document"):
            generate_embedding_vector(analysis_data)

    @patch('handler.embeddings.generate_embedding')
    def test_generate_embedding_with_list_extracted_text(self, mock_generate):
        """Test embedding generation with extracted_text as list."""
        mock_generate.return_value = [0.1] * 1024

        # Create analysis data with extracted_text as list
        analysis_data = {
            'raw_response': {
                'summary': 'Test',
                'image_details': {
                    'extracted_text': ['Hello', 'World']
                }
            }
        }

        # Generate embedding
        embedding = generate_embedding_vector(analysis_data)

        # Verify
        assert len(embedding) == 1024

        # Verify the generated document contains joined text
        call_args = mock_generate.call_args
        document = call_args[0][0]
        assert 'Hello World' in document


class TestHandler:
    """Tests for Lambda handler function."""

    @patch('handler.ensure_db_connection')
    @patch('handler.get_api_keys')
    @patch('handler.get_session')
    @patch('handler.embeddings.generate_embedding')
    def test_handler_success(
        self,
        mock_generate,
        mock_get_session,
        mock_get_keys,
        mock_ensure_db
    ):
        """Test successful embedding generation."""
        # Setup mocks
        mock_ensure_db.return_value = None
        mock_get_keys.return_value = None

        # Mock database session and analysis fetch
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)

        # Mock Analysis object
        mock_analysis = MagicMock()
        mock_analysis.id = 'analysis456'
        mock_analysis.item_id = 'item123'
        mock_analysis.user_id = 'user789'
        mock_analysis.version = 1
        mock_analysis.category = 'Travel'
        mock_analysis.summary = 'A beautiful landscape'
        mock_analysis.raw_response = {
            'summary': 'A beautiful landscape',
            'headline': 'Mountain View',
            'category': 'Travel'
        }
        mock_analysis.provider_used = 'anthropic'
        mock_analysis.model_used = 'claude-sonnet-4-5'
        mock_analysis.trace_id = 'trace-123'
        mock_analysis.created_at = None

        mock_session.scalar = Mock(return_value=mock_analysis)
        mock_get_session.return_value = mock_session

        # Mock embedding generation
        mock_generate.return_value = [0.1] * 1024

        # Create EventBridge event
        event = {
            'detail': {
                'item_id': 'item123',
                'analysis_id': 'analysis456',
                'user_id': 'user789'
            }
        }

        # Call handler
        response = handler(event, None)

        # Verify response
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['item_id'] == 'item123'
        assert 'embedding_id' in body
        assert body['dimensions'] == 1024

        # Verify embedding generation was called
        mock_generate.assert_called_once()

        # Verify database operations
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

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
    @patch('handler.get_session')
    def test_handler_analysis_not_found(self, mock_get_session, mock_get_keys, mock_ensure_db):
        """Test handler when analysis is not found."""
        mock_ensure_db.return_value = None
        mock_get_keys.return_value = None

        # Mock database session to return None (analysis not found)
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)
        mock_session.scalar = Mock(return_value=None)
        mock_get_session.return_value = mock_session

        # Create valid event
        event = {
            'detail': {
                'item_id': 'item123',
                'analysis_id': 'analysis456',
                'user_id': 'user789'
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
    @patch('handler.get_session')
    @patch('handler.embeddings.generate_embedding')
    def test_handler_embedding_generation_error(
        self,
        mock_generate,
        mock_get_session,
        mock_get_keys,
        mock_ensure_db
    ):
        """Test handler with embedding generation error."""
        mock_ensure_db.return_value = None
        mock_get_keys.return_value = None

        # Mock database session and analysis fetch
        mock_session = MagicMock()
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=False)

        # Mock Analysis object
        mock_analysis = MagicMock()
        mock_analysis.id = 'analysis456'
        mock_analysis.item_id = 'item123'
        mock_analysis.user_id = 'user789'
        mock_analysis.version = 1
        mock_analysis.category = 'Travel'
        mock_analysis.summary = 'A beautiful landscape'
        mock_analysis.raw_response = {
            'summary': 'A beautiful landscape',
            'category': 'Travel'
        }
        mock_analysis.provider_used = 'anthropic'
        mock_analysis.model_used = 'claude-sonnet-4-5'
        mock_analysis.trace_id = 'trace-123'
        mock_analysis.created_at = None

        mock_session.scalar = Mock(return_value=mock_analysis)
        mock_get_session.return_value = mock_session

        # Mock embedding generation to raise error
        mock_generate.side_effect = Exception('Embedding API error')

        # Create valid event
        event = {
            'detail': {
                'item_id': 'item123',
                'analysis_id': 'analysis456',
                'user_id': 'user789'
            }
        }

        # Call handler
        response = handler(event, None)

        # Verify error response
        assert response['statusCode'] == 500
        body = json.loads(response['body'])
        assert 'error' in body
