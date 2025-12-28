"""
Retriever Configuration for Collections Local API.

This module provides optimized configuration parameters for LangChain retrievers
based on evaluation results and best practices.
"""

# BM25 Configuration
# ------------------
# Based on Elasticsearch best practices and evaluation testing
# Source: https://www.elastic.co/blog/practical-bm25-part-3-considerations-for-picking-b-and-k1-in-elasticsearch

BM25_CONFIG = {
    # k1: Controls term frequency saturation
    # - Higher values (e.g., 2.0) make BM25 more sensitive to repeated keywords
    # - Lower values (e.g., 1.2) apply stronger saturation (Elasticsearch default)
    # - Default in rank-bm25: 1.5
    # - Recommended: 1.2 (Elasticsearch best practice)
    "k1": 1.2,

    # b: Controls document length normalization
    # - Range: 0.0 to 1.0
    # - b=1.0: Full document length normalization
    # - b=0.0: No length normalization
    # - Default: 0.75 (good for most corpora)
    # - Recommended: 0.75
    "b": 0.75,

    # epsilon: Floor for IDF values
    # - Prevents zero IDF for very common terms
    # - Default: 0.25
    # - Recommended: 0.25
    "epsilon": 0.25,
}

# Alternative BM25 configurations for experimentation
BM25_CONFIGS = {
    "default": BM25_CONFIG,

    "high_saturation": {
        "k1": 1.0,  # Stronger saturation, less sensitive to term repetition
        "b": 0.75,
        "epsilon": 0.25,
    },

    "low_saturation": {
        "k1": 2.0,  # Weaker saturation, more sensitive to term repetition
        "b": 0.75,
        "epsilon": 0.25,
    },

    "no_length_norm": {
        "k1": 1.2,
        "b": 0.0,  # Ignore document length
        "epsilon": 0.25,
    },

    "full_length_norm": {
        "k1": 1.2,
        "b": 1.0,  # Full document length normalization
        "epsilon": 0.25,
    },
}


# VoyageAI Embeddings Configuration
# ----------------------------------
# Based on VoyageAI API documentation
# Source: https://docs.voyageai.com/reference

VOYAGE_CONFIG = {
    # input_type: Optimizes embeddings for specific use cases
    # - "document": Use when embedding documents for indexing
    # - "query": Use when embedding search queries
    # - None/null: Generic embeddings (default)
    #
    # IMPORTANT: For optimal retrieval quality, use different input_type
    # for documents (during indexing) vs queries (during search)
    "document_input_type": "document",
    "query_input_type": "query",

    # Model selection
    "model": "voyage-3.5-lite",  # Fast, cost-effective
    # Alternatives:
    # - "voyage-3-large": Highest quality, slower
    # - "voyage-3.5": Balanced quality/speed
    # - "voyage-code-3": Optimized for code
}


# PGVector Configuration
# ----------------------
# Based on pgvector documentation and LangChain best practices

PGVECTOR_CONFIG = {
    # Distance metric for similarity search
    # - "cosine": Cosine similarity - used by VoyageAI normalized embeddings
    # - "l2": L2 (Euclidean) distance
    # - "ip": Inner product
    "distance_metric": "cosine",

    # Collection naming
    "collection_name_prod": "collections_vectors_prod",
    "collection_name_golden": "collections_vectors_golden",
}


# Hybrid Search Configuration
# ---------------------------
# Configuration for ensemble retriever combining BM25 and vector search

HYBRID_CONFIG = {
    # Retriever weights (must sum to 1.0)
    "bm25_weight": 0.3,
    "vector_weight": 0.7,

    # Top-k for each retriever before fusion
    "bm25_top_k": 20,
    "vector_top_k": 20,

    # Final top-k after fusion
    "final_top_k": 10,

    # RRF (Reciprocal Rank Fusion) constant
    # - Lower values (e.g., 10) = more sensitive to rank differences
    # - Higher values (e.g., 60) = less sensitive to rank differences
    # - Default: 60 (LangChain default)
    # - Recommended: 15 (based on testing)
    "rrf_c": 15,
}


def get_bm25_config(config_name: str = "default") -> dict:
    """Get BM25 configuration by name.

    Args:
        config_name: Name of configuration ("default", "high_saturation", etc.)

    Returns:
        Dictionary with k1, b, epsilon parameters
    """
    if config_name not in BM25_CONFIGS:
        raise ValueError(
            f"Unknown BM25 config: {config_name}. "
            f"Available: {list(BM25_CONFIGS.keys())}"
        )
    return BM25_CONFIGS[config_name].copy()


def get_voyage_config() -> dict:
    """Get VoyageAI embeddings configuration.

    Returns:
        Dictionary with model and input_type parameters
    """
    return VOYAGE_CONFIG.copy()


def get_hybrid_config() -> dict:
    """Get hybrid search configuration.

    Returns:
        Dictionary with weights, top-k, and RRF parameters
    """
    return HYBRID_CONFIG.copy()


def get_pgvector_config() -> dict:
    """Get PGVector configuration.

    Returns:
        Dictionary with distance metric and collection settings
    """
    return PGVECTOR_CONFIG.copy()
