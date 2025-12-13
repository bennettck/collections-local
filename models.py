from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from datetime import datetime
from typing import Optional, Literal, List, Any


class Settings(BaseSettings):
    """Application settings from environment variables."""
    anthropic_api_key: str
    openai_api_key: Optional[str] = None
    langfuse_secret_key: str
    langfuse_public_key: str
    langfuse_host: str = "https://cloud.langfuse.com"
    database_path: str = "./data/collections.db"
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
                    "top_k": 10,
                    "category_filter": None,
                    "include_answer": True,
                    "answer_model": None
                },
                {
                    "query": "beauty products",
                    "top_k": 5,
                    "category_filter": "Beauty",
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
    category: Optional[str] = None
    headline: Optional[str] = None
    summary: Optional[str] = None
    image_url: str
    metadata: dict = {}


class SearchResponse(BaseModel):
    """Response model for search and Q&A."""
    query: str
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


