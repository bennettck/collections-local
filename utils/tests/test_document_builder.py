"""
Unit tests for document_builder module.
"""

import pytest
from langchain_core.documents import Document
from utils.document_builder import create_flat_document, create_langchain_document


class TestCreateFlatDocument:
    """Tests for create_flat_document function."""

    def test_create_flat_document_with_complete_data(self):
        """Test creating a flat document with all fields populated."""
        raw_response = {
            "summary": "A beautiful sunset over the ocean",
            "headline": "Stunning Ocean Sunset",
            "category": "Nature",
            "subcategories": ["Landscape", "Beach"],
            "image_details": {
                "extracted_text": ["Ocean View", "Beach"],
                "key_interest": "Sunset colors",
                "themes": ["Nature", "Peace"],
                "objects": ["Sun", "Ocean", "Sky"],
                "emotions": ["Calm", "Peaceful"],
                "vibes": ["Relaxing", "Serene"]
            },
            "media_metadata": {
                "location_tags": ["California", "Pacific Coast"],
                "hashtags": ["#sunset", "#nature"]
            }
        }

        result = create_flat_document(raw_response)

        # Verify all fields are present in the result
        assert "A beautiful sunset over the ocean" in result
        assert "Stunning Ocean Sunset" in result
        assert "Nature" in result
        assert "Landscape Beach" in result
        assert "Ocean View Beach" in result
        assert "Sunset colors" in result
        assert "Nature Peace" in result
        assert "Sun Ocean Sky" in result
        assert "Calm Peaceful" in result
        assert "Relaxing Serene" in result
        assert "California Pacific Coast" in result
        assert "#sunset #nature" in result

    def test_create_flat_document_with_extracted_text_as_string(self):
        """Test handling of extracted_text as a string instead of list."""
        raw_response = {
            "summary": "Test summary",
            "image_details": {
                "extracted_text": "Single text string"
            }
        }

        result = create_flat_document(raw_response)

        assert "Test summary" in result
        assert "Single text string" in result

    def test_create_flat_document_with_missing_fields(self):
        """Test handling of missing fields - should handle gracefully."""
        raw_response = {
            "summary": "Minimal data",
            # Most fields missing
        }

        result = create_flat_document(raw_response)

        # Should still work and include the summary
        assert "Minimal data" in result
        # Should not crash on missing fields

    def test_create_flat_document_with_partial_image_details(self):
        """Test handling when image_details has some fields missing."""
        raw_response = {
            "summary": "Test",
            "image_details": {
                "key_interest": "Main focus",
                # Other fields missing
            }
        }

        result = create_flat_document(raw_response)

        assert "Test" in result
        assert "Main focus" in result

    def test_create_flat_document_with_empty_lists(self):
        """Test handling of empty list fields."""
        raw_response = {
            "summary": "Test",
            "subcategories": [],
            "image_details": {
                "themes": [],
                "objects": [],
                "emotions": [],
                "vibes": []
            },
            "media_metadata": {
                "location_tags": [],
                "hashtags": []
            }
        }

        result = create_flat_document(raw_response)

        # Should still work with empty lists
        assert "Test" in result

    def test_create_flat_document_with_none_raw_response(self):
        """Test that None raw_response raises ValueError."""
        with pytest.raises(ValueError, match="raw_response cannot be None or empty"):
            create_flat_document(None)

    def test_create_flat_document_with_empty_dict(self):
        """Test that empty dict raw_response raises ValueError."""
        with pytest.raises(ValueError, match="raw_response cannot be None or empty"):
            create_flat_document({})

    def test_create_flat_document_strips_whitespace(self):
        """Test that empty strings and whitespace are properly cleaned."""
        raw_response = {
            "summary": "Test summary",
            "headline": "",
            "category": "   ",
            "subcategories": ["Valid", ""],
            "image_details": {
                "key_interest": "Focus",
                "themes": []
            }
        }

        result = create_flat_document(raw_response)

        # Should include non-empty fields
        assert "Test summary" in result
        assert "Focus" in result
        # Should not have multiple spaces from empty fields
        assert "  " not in result


class TestCreateLangchainDocument:
    """Tests for create_langchain_document function."""

    def test_create_langchain_document_with_required_fields_only(self):
        """Test creating a LangChain document with only required fields."""
        raw_response = {
            "summary": "Test summary",
            "headline": "Test headline"
        }

        doc = create_langchain_document(
            raw_response=raw_response,
            item_id="item123",
            filename="test.jpg"
        )

        assert isinstance(doc, Document)
        assert "Test summary" in doc.page_content
        assert "Test headline" in doc.page_content
        assert doc.metadata["item_id"] == "item123"
        assert doc.metadata["filename"] == "test.jpg"

    def test_create_langchain_document_with_all_fields(self):
        """Test creating a LangChain document with all fields."""
        raw_response = {
            "summary": "Complete test",
            "headline": "Test headline",
            "category": "TestCategory"
        }

        doc = create_langchain_document(
            raw_response=raw_response,
            item_id="item456",
            filename="test2.jpg",
            user_id="user789",
            category="TestCategory"
        )

        assert isinstance(doc, Document)
        assert doc.metadata["item_id"] == "item456"
        assert doc.metadata["filename"] == "test2.jpg"
        assert doc.metadata["user_id"] == "user789"
        assert doc.metadata["category"] == "TestCategory"

    def test_create_langchain_document_with_extra_metadata(self):
        """Test creating a LangChain document with extra metadata."""
        raw_response = {
            "summary": "Test with extra metadata"
        }

        doc = create_langchain_document(
            raw_response=raw_response,
            item_id="item999",
            filename="test3.jpg",
            source="upload",
            timestamp="2024-01-01T00:00:00Z"
        )

        assert isinstance(doc, Document)
        assert doc.metadata["item_id"] == "item999"
        assert doc.metadata["filename"] == "test3.jpg"
        assert doc.metadata["source"] == "upload"
        assert doc.metadata["timestamp"] == "2024-01-01T00:00:00Z"

    def test_create_langchain_document_without_optional_fields(self):
        """Test that optional user_id and category are not included when None."""
        raw_response = {
            "summary": "Test without optional"
        }

        doc = create_langchain_document(
            raw_response=raw_response,
            item_id="item111",
            filename="test4.jpg"
        )

        assert "user_id" not in doc.metadata
        assert "category" not in doc.metadata

    def test_create_langchain_document_propagates_value_error(self):
        """Test that ValueError from create_flat_document is propagated."""
        with pytest.raises(ValueError):
            create_langchain_document(
                raw_response=None,
                item_id="item123",
                filename="test.jpg"
            )

    def test_create_langchain_document_page_content_matches_flat_document(self):
        """Test that page_content matches output of create_flat_document."""
        raw_response = {
            "summary": "Consistency test",
            "headline": "Same output",
            "category": "Test"
        }

        flat_doc = create_flat_document(raw_response)
        langchain_doc = create_langchain_document(
            raw_response=raw_response,
            item_id="item222",
            filename="test5.jpg"
        )

        assert langchain_doc.page_content == flat_doc
