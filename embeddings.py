import os
import logging
from typing import Optional
import voyageai

# Load environment variables (skip in Lambda - use environment variables directly)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv not available (Lambda environment) - use system environment variables
    pass

logger = logging.getLogger(__name__)

# Lazy-initialized VoyageAI client
_voyage_client = None

def _get_voyage_client():
    """Get or create VoyageAI client (lazy initialization)."""
    global _voyage_client
    if _voyage_client is None:
        api_key = os.getenv("VOYAGE_API_KEY")
        if not api_key:
            raise ValueError("VOYAGE_API_KEY environment variable not set")
        _voyage_client = voyageai.Client(
            api_key=api_key,
            max_retries=3  # Built-in exponential backoff for 429 and 5xx errors
        )
    return _voyage_client

# Model configuration
DEFAULT_EMBEDDING_MODEL = os.getenv("VOYAGE_EMBEDDING_MODEL", "voyage-3.5-lite")
EMBEDDING_DIMENSIONS = {
    "voyage-3.5-lite": 1024,  # Actual dimension returned by API (confirmed via testing)
    "voyage-3.5": 1024,
    "voyage-3-lite": 512,
    "voyage-3": 1024,
    "voyage-large-2": 1536,
    "voyage-2": 1024
}

def get_embedding_dimensions(model: str) -> int:
    """Get embedding dimensions for a VoyageAI model."""
    return EMBEDDING_DIMENSIONS.get(model, 1024)  # Default to 1024


def generate_embedding(
    text: str,
    model: str = DEFAULT_EMBEDDING_MODEL
) -> list[float]:
    """
    Generate embedding for text using VoyageAI.

    The client automatically retries on rate limits (429) and transient errors (5xx)
    with exponential backoff (configured via max_retries parameter on client).

    Args:
        text: Input text to embed
        model: VoyageAI model name (default: from VOYAGE_EMBEDDING_MODEL env var)

    Returns:
        List of floats representing the embedding vector

    Raises:
        ValueError: If text is empty
        voyageai.error.RateLimitError: If rate limit exceeded after all retries
        voyageai.error.InvalidRequestError: If request is invalid (4xx errors)
        Exception: For other unexpected errors
    """
    if not text or not text.strip():
        raise ValueError("Cannot embed empty text")

    try:
        result = _get_voyage_client().embed(
            texts=[text],
            model=model,
            input_type="document",  # Use "document" for indexing
            truncation=True  # Auto-truncate if exceeds context length
        )
        return result.embeddings[0]

    except Exception as e:
        logger.error(f"Failed to generate embedding: {e}")
        raise


def generate_query_embedding(
    query: str,
    model: str = DEFAULT_EMBEDDING_MODEL
) -> list[float]:
    """
    Generate embedding for search query using VoyageAI.

    Uses input_type="query" for optimal search performance.
    The client automatically retries on rate limits and transient errors.

    Args:
        query: Query text to embed
        model: VoyageAI model name (default: from VOYAGE_EMBEDDING_MODEL env var)

    Returns:
        List of floats representing the embedding vector

    Raises:
        ValueError: If query is empty
        Exception: For API errors after retries
    """
    if not query or not query.strip():
        raise ValueError("Cannot embed empty query")

    try:
        result = _get_voyage_client().embed(
            texts=[query],
            model=model,
            input_type="query",  # Use "query" for searching
            truncation=True
        )
        return result.embeddings[0]

    except Exception as e:
        logger.error(f"Failed to generate query embedding: {e}")
        raise


def generate_embeddings_batch(
    texts: list[str],
    model: str = DEFAULT_EMBEDDING_MODEL,
    batch_size: int = 128
) -> list[list[float]]:
    """
    Generate embeddings for multiple texts in batches.

    VoyageAI supports up to 128 documents per request. This function
    processes texts in batches to minimize API calls and avoid rate limits.

    Token limits (per batch):
    - voyage-3.5-lite: 1M tokens
    - voyage-3.5: 320K tokens
    - Max 32K tokens per individual text

    Args:
        texts: List of texts to embed
        model: VoyageAI model name (default: from VOYAGE_EMBEDDING_MODEL env var)
        batch_size: Number of texts per API request (max 128, default 128)

    Returns:
        List of embedding vectors (one per input text)

    Raises:
        ValueError: If texts is empty or batch_size invalid
        Exception: For API errors after retries
    """
    if not texts:
        raise ValueError("Cannot embed empty text list")

    if batch_size < 1 or batch_size > 128:
        raise ValueError("batch_size must be between 1 and 128")

    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]

        try:
            result = _get_voyage_client().embed(
                texts=batch,
                model=model,
                input_type="document",
                truncation=True
            )
            all_embeddings.extend(result.embeddings)

            logger.info(f"Generated embeddings for batch {i//batch_size + 1} "
                       f"({len(batch)} texts, {result.total_tokens} tokens)")

        except Exception as e:
            logger.error(f"Failed to generate embeddings for batch starting at index {i}: {e}")
            raise

    return all_embeddings


def _create_embedding_document(analysis_data: dict) -> str:
    """
    Create flat embedding document from analysis data (no field weighting).

    This method concatenates all fields ONCE (no repetition).
    Modern embedding models handle field importance implicitly.
    """
    parts = []

    # Extract all fields once (same order as search document)
    parts.append(analysis_data.get("summary", ""))
    parts.append(analysis_data.get("headline", ""))
    parts.append(analysis_data.get("category", ""))
    parts.append(" ".join(analysis_data.get("subcategories", [])))

    # Image details
    image_details = analysis_data.get("image_details", {})
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
    media_metadata = analysis_data.get("media_metadata", {})
    parts.append(" ".join(media_metadata.get("location_tags", [])))
    parts.append(" ".join(media_metadata.get("hashtags", [])))

    # Combine and clean
    document = " ".join([p for p in parts if p and p.strip()])
    return document
