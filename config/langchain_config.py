"""
Centralized LangChain configuration for Collections Local API.

This module provides default configuration values for:
- Embedding models and settings
- PGVector store settings
- BM25 retriever settings
- Document chunking parameters
"""

import os

# Default embedding model
DEFAULT_EMBEDDING_MODEL = "voyage-3.5-lite"

# LangChain configuration
LANGCHAIN_CONFIG = {
    # Embedding settings
    "embeddings": {
        "model": DEFAULT_EMBEDDING_MODEL,
        "batch_size": 128,
        "dimensions": 1024  # voyage-3.5-lite actual dimension
    },

    # Vector store settings (dual database support)
    "vector_store": {
        # Production database
        "collection_name_prod": "collections_vectors_prod",

        # Golden database
        "collection_name_golden": "collections_vectors_golden"
    },

    # BM25 retriever settings
    "bm25": {
        "k": 10,  # Default number of results
        "preload": True  # Build index on startup
    },

    # Document chunking settings
    "chunking": {
        "enabled": os.getenv("ENABLE_DOCUMENT_CHUNKING", "true").lower() == "true",
        "max_chunk_size": int(os.getenv("MAX_CHUNK_SIZE", "2000")),
        "chunk_overlap": int(os.getenv("CHUNK_OVERLAP", "200")),
        "use_json_splitter": os.getenv("USE_JSON_SPLITTER", "true").lower() == "true"
    }
}


def get_vector_store_config(database_type: str = "prod") -> dict:
    """Get vector store configuration for specific database.

    Args:
        database_type: Either "prod" or "golden"

    Returns:
        Dictionary with collection_name
    """
    if database_type == "golden":
        return {
            "collection_name": LANGCHAIN_CONFIG["vector_store"]["collection_name_golden"]
        }
    else:
        return {
            "collection_name": LANGCHAIN_CONFIG["vector_store"]["collection_name_prod"]
        }


def get_chunking_config() -> dict:
    """Get document chunking configuration.

    Returns:
        Dictionary with chunking settings
    """
    return LANGCHAIN_CONFIG["chunking"]


def get_embedding_config() -> dict:
    """Get embedding configuration.

    Returns:
        Dictionary with embedding settings
    """
    return LANGCHAIN_CONFIG["embeddings"]
