"""
Centralized document builder for embedding and search document creation.

This module provides a single source of truth for creating text documents
from analysis data, used for both embedding generation and search indexing.
"""

from typing import Dict, Any, Optional
from langchain_core.documents import Document


def create_flat_document(raw_response: Dict[str, Any]) -> str:
    """
    Create a flat text document from analysis raw_response data.

    Concatenates all relevant fields for embedding generation.
    Modern embedding models handle field importance implicitly,
    so no field weighting or repetition is needed.

    Args:
        raw_response: The raw_response dict from an analysis containing:
            - summary, headline, category, subcategories
            - image_details (extracted_text, key_interest, themes, objects, emotions, vibes)
            - media_metadata (location_tags, hashtags)

    Returns:
        Concatenated text document suitable for embedding

    Raises:
        ValueError: If raw_response is None or empty
    """
    if not raw_response:
        raise ValueError("raw_response cannot be None or empty")

    parts = []

    # Helper function to join list items, filtering out empty strings
    def join_list(items):
        return " ".join([item for item in items if item and item.strip()])

    # Extract all fields once (same order as in canonical implementation)
    parts.append(raw_response.get("summary", ""))
    parts.append(raw_response.get("headline", ""))
    parts.append(raw_response.get("category", ""))
    parts.append(join_list(raw_response.get("subcategories", [])))

    # Image details
    image_details = raw_response.get("image_details", {})
    if isinstance(image_details.get("extracted_text"), list):
        parts.append(join_list(image_details.get("extracted_text", [])))
    else:
        parts.append(image_details.get("extracted_text", ""))

    parts.append(image_details.get("key_interest", ""))
    parts.append(join_list(image_details.get("themes", [])))
    parts.append(join_list(image_details.get("objects", [])))
    parts.append(join_list(image_details.get("emotions", [])))
    parts.append(join_list(image_details.get("vibes", [])))

    # Media metadata
    media_metadata = raw_response.get("media_metadata", {})
    parts.append(join_list(media_metadata.get("location_tags", [])))
    parts.append(join_list(media_metadata.get("hashtags", [])))

    # Combine and clean
    document = " ".join([p for p in parts if p and p.strip()])
    return document


def create_langchain_document(
    raw_response: Dict[str, Any],
    item_id: str,
    filename: str,
    user_id: Optional[str] = None,
    category: Optional[str] = None,
    **extra_metadata
) -> Document:
    """
    Create a LangChain Document from analysis data.

    Args:
        raw_response: The raw_response dict from an analysis
        item_id: Unique identifier for the item
        filename: Original filename
        user_id: User ID for multi-tenancy (optional)
        category: Category from analysis (optional)
        **extra_metadata: Additional metadata to include

    Returns:
        LangChain Document with page_content and metadata
    """
    # Create the flat document text
    page_content = create_flat_document(raw_response)

    # Build metadata
    metadata = {
        "item_id": item_id,
        "filename": filename,
    }

    # Add optional fields if provided
    if user_id is not None:
        metadata["user_id"] = user_id

    if category is not None:
        metadata["category"] = category

    # Add any extra metadata
    metadata.update(extra_metadata)

    return Document(
        page_content=page_content,
        metadata=metadata
    )
