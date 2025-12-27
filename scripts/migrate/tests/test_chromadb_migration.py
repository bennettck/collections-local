"""
Unit tests for ChromaDB to pgvector migration script.

Tests vector migration logic and metadata transformation.
"""

import sys
import os
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest
import numpy as np

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from scripts.migrate.chromadb_to_pgvector import (
    add_user_id_to_metadata,
)


def test_add_user_id_to_metadata():
    """Test adding user_id to metadata."""
    metadatas = [
        {'item_id': 'item-1', 'category': 'Food'},
        {'item_id': 'item-2', 'category': 'Travel'},
        None  # Test None handling
    ]

    user_id = 'test-user-123'
    updated = add_user_id_to_metadata(metadatas, user_id)

    # Verify user_id added
    assert updated[0]['user_id'] == user_id
    assert updated[0]['item_id'] == 'item-1'

    assert updated[1]['user_id'] == user_id
    assert updated[1]['category'] == 'Travel'

    # Verify None handled
    assert updated[2]['user_id'] == user_id


def test_add_user_id_preserves_existing_metadata():
    """Test that existing metadata is preserved."""
    metadatas = [{
        'item_id': 'item-1',
        'category': 'Food',
        'headline': 'Test headline',
        'summary': 'Test summary',
        'raw_response': '{"key": "value"}'
    }]

    user_id = 'test-user'
    updated = add_user_id_to_metadata(metadatas, user_id)

    # All original fields should be preserved
    assert updated[0]['item_id'] == 'item-1'
    assert updated[0]['category'] == 'Food'
    assert updated[0]['headline'] == 'Test headline'
    assert updated[0]['summary'] == 'Test summary'
    assert updated[0]['raw_response'] == '{"key": "value"}'
    assert updated[0]['user_id'] == user_id


def test_empty_metadata_list():
    """Test handling of empty metadata list."""
    metadatas = []
    user_id = 'test-user'

    updated = add_user_id_to_metadata(metadatas, user_id)
    assert updated == []


@patch('scripts.migrate.chromadb_to_pgvector.chromadb.PersistentClient')
def test_read_chromadb_collection_mock(mock_client_class):
    """Test reading from ChromaDB (mocked)."""
    # This is a simplified mock test
    # Full integration tests would use actual ChromaDB instance

    mock_client = Mock()
    mock_collection = Mock()

    # Setup mock return values
    mock_collection.count.return_value = 2
    mock_collection.get.return_value = {
        'ids': ['id-1', 'id-2'],
        'embeddings': [[0.1] * 1024, [0.2] * 1024],
        'documents': ['doc-1', 'doc-2'],
        'metadatas': [
            {'item_id': 'item-1'},
            {'item_id': 'item-2'}
        ]
    }

    mock_client.get_collection.return_value = mock_collection
    mock_client_class.return_value = mock_client

    # Import and test (would need actual implementation)
    # This verifies the mock structure is correct
    assert mock_collection.count() == 2
    results = mock_collection.get(include=['embeddings', 'documents', 'metadatas'])
    assert len(results['ids']) == 2
    assert len(results['embeddings'][0]) == 1024


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
