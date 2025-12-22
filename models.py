from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from datetime import datetime
from typing import Optional, Literal, List, Any


class Settings(BaseSettings):
    """Application settings from environment variables."""
    anthropic_api_key: str
    openai_api_key: Optional[str] = None
    langsmith_prompt_name: str = "collections-app-initial"
    prod_database_path: str = "./data/collections.db"
    golden_database_path: str = "./data/collections_golden.db"
    images_path: str = "./data/images"

    class Config:
        env_file = ".env"


class ItemCreate(BaseModel):
    """Request model for creating an item (file upload)."""
    pass  # File comes via form data


class AnalysisResponse(BaseModel):
    """Response model for an analysis."""
    id: str
    item_id: str
    version: int
    category: Optional[str] = None
    summary: Optional[str] = None
    raw_response: dict = {}
    provider_used: Optional[str] = None
    model_used: Optional[str] = None
    trace_id: Optional[str] = None
    created_at: datetime


class ItemResponse(BaseModel):
    """Response model for an item with optional latest analysis."""
    id: str
    filename: str
    original_filename: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    latest_analysis: Optional[AnalysisResponse] = None


class AnalysisRequest(BaseModel):
    """Optional parameters for analysis."""
    force_reanalyze: bool = False
    provider: Optional[Literal["anthropic", "openai"]] = None
    model: Optional[str] = None


class ItemListResponse(BaseModel):
    """Response model for listing items."""
    items: list[ItemResponse]
    total: int


class SearchRequest(BaseModel):
    """Request model for search and Q&A."""
    query: str = Field(
        ...,
        min_length=3,
        description="Natural language search query",
        examples=["What restaurants are in Tokyo?", "Show me beauty products", "perfume"]
    )
    search_type: Literal["bm25", "vector", "bm25-lc", "vector-lc", "hybrid", "hybrid-lc"] = Field(
        "bm25",
        description="Search type: 'bm25' for full-text search, 'vector' for semantic search, "
                    "'bm25-lc' for LangChain BM25 retriever, 'vector-lc' for LangChain vector retriever, "
                    "'hybrid' for native hybrid search with RRF, 'hybrid-lc' for LangChain hybrid with RRF"
    )
    top_k: int = Field(
        10,
        ge=1,
        le=50,
        description="Number of results to return"
    )
    category_filter: Optional[str] = Field(
        None,
        description="Filter by category (e.g., 'Food', 'Travel', 'Beauty'). Leave null for no filter.",
        examples=[None, "Food", "Travel"]
    )
    min_relevance_score: float = Field(
        -1.0,
        description="Minimum BM25 relevance score threshold. Results with scores > this value will be filtered out. Default -1.0 effectively disables filtering since most results score lower (more negative = better match).",
        examples=[-1.0, -5.0, -10.0]
    )
    min_similarity_score: float = Field(
        0.0,
        description="Minimum similarity score threshold for vector search (0-1 range). Results below this threshold will be filtered out."
    )
    include_answer: bool = Field(
        True,
        description="Generate LLM answer from results"
    )
    answer_model: Optional[str] = Field(
        None,
        description="Model to use for answer generation (defaults to claude-sonnet-4-5 if null)",
        examples=[None, "claude-sonnet-4-5", "gpt-4o"]
    )

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "query": "What restaurants are in Tokyo?",
                    "search_type": "bm25",
                    "top_k": 10,
                    "category_filter": None,
                    "min_relevance_score": -1.0,
                    "min_similarity_score": 0.0,
                    "include_answer": True,
                    "answer_model": None
                },
                {
                    "query": "Japanese beauty products and perfume",
                    "search_type": "vector",
                    "top_k": 5,
                    "category_filter": None,
                    "min_relevance_score": -1.0,
                    "min_similarity_score": 0.7,
                    "include_answer": True,
                    "answer_model": "claude-sonnet-4-5"
                },
                {
                    "query": "traditional architecture",
                    "search_type": "vector",
                    "top_k": 10,
                    "category_filter": "Travel",
                    "min_relevance_score": -1.0,
                    "min_similarity_score": 0.0,
                    "include_answer": False,
                    "answer_model": None
                }
            ]
        }


class SearchResult(BaseModel):
    """Single search result item."""
    item_id: str
    rank: int
    score: float
    score_type: Literal["bm25", "similarity", "hybrid_rrf"] = Field(
        "bm25",
        description="Type of score: 'bm25' for full-text search scores or 'similarity' for vector search scores"
    )
    category: Optional[str] = None
    headline: Optional[str] = None
    summary: Optional[str] = None
    image_url: str
    metadata: dict = {}


class SearchResponse(BaseModel):
    """Response model for search and Q&A."""
    query: str
    search_type: Literal["bm25", "vector", "bm25-lc", "vector-lc", "hybrid", "hybrid-lc"] = Field(
        description="Search method used: 'bm25' for keyword search, 'vector' for semantic search, "
                    "'bm25-lc' for LangChain BM25, 'vector-lc' for LangChain vector, "
                    "'hybrid' for native hybrid RRF, 'hybrid-lc' for LangChain hybrid RRF"
    )
    results: list[SearchResult]
    total_results: int
    answer: Optional[str] = None
    answer_confidence: Optional[float] = None
    citations: Optional[list[str]] = None
    retrieval_time_ms: float
    answer_time_ms: Optional[float] = None


class GoldenAnalysisEntry(BaseModel):
    """Model for a golden dataset entry."""
    item_id: str
    original_filename: Optional[str] = None
    reviewed_at: str  # ISO-8601 timestamp
    source_analyses_count: int
    source_analysis_ids: List[str]
    category: str
    subcategories: List[str]
    headline: str
    summary: str
    media_metadata: dict
    image_details: dict


class CompareRequest(BaseModel):
    """Request model for comparing analysis values."""
    item_id: str
    field_type: Literal["extracted_text", "headline", "summary"]
    values: List[Any]  # Can be List[str] or List[List[str]]


class CompareResponse(BaseModel):
    """Response model for similarity comparison."""
    similarity_matrix: List[List[float]]
    highest_agreement: dict
    method: Literal["levenshtein", "tfidf"]


