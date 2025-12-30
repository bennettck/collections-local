from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from datetime import datetime
from typing import Optional, Literal, List, Any, Dict


class Settings(BaseSettings):
    """Application settings from environment variables."""
    anthropic_api_key: str
    openai_api_key: Optional[str] = None
    langsmith_prompt_name: str = "collections-app-initial"
    images_path: str = "./data/images"

    class Config:
        env_file = ".env"


class ItemCreate(BaseModel):
    """Request model for creating an item (file upload)."""
    pass  # File comes via form data


class AnalysisResponse(BaseModel):
    """Response model for an analysis."""
    id: str
    version: int
    # Fields extracted from raw_response for convenience
    headline: Optional[str] = None
    category: Optional[str] = None
    subcategories: Optional[List[str]] = None
    summary: Optional[str] = None
    # Full raw LLM response for additional details
    raw_response: dict = {}
    # Tracking metadata
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
    image_url: Optional[str] = None
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
    search_type: Literal["bm25", "vector", "hybrid", "agentic"] = Field(
        "hybrid",
        description="Search type: 'bm25' for PostgreSQL BM25 full-text search, "
                    "'vector' for PGVector semantic search, "
                    "'hybrid' for hybrid search with RRF (Recommended), "
                    "'agentic' for AI agent-driven iterative search with reasoning"
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
                    "search_type": "hybrid",
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
    search_type: Literal["bm25", "vector", "hybrid", "agentic"] = Field(
        description="Search method used: 'bm25' for keyword search, 'vector' for semantic search, "
                    "'hybrid' for hybrid RRF, 'agentic' for AI agent-driven iterative search"
    )
    results: list[SearchResult]
    total_results: int
    answer: Optional[str] = None
    answer_confidence: Optional[float] = None
    citations: Optional[list[str]] = None
    retrieval_time_ms: float
    answer_time_ms: Optional[float] = None
    # Agentic search specific fields
    agent_reasoning: Optional[List[str]] = Field(
        None,
        description="Agent's reasoning steps (only for agentic search)"
    )
    tools_used: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Tools invoked by agent with inputs/outputs (only for agentic search)"
    )


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


# Chat Models for Multi-Turn Agentic Chat

class ChatRequest(BaseModel):
    """Request model for chat endpoint."""
    message: str = Field(
        ...,
        min_length=1,
        description="User message"
    )
    session_id: str = Field(
        ...,
        min_length=1,
        description="Client-generated session UUID for conversation continuity"
    )
    top_k: int = Field(
        10,
        ge=1,
        le=50,
        description="Number of search results to return"
    )
    category_filter: Optional[str] = Field(
        None,
        description="Filter search results by category"
    )
    min_similarity_score: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score for vector search"
    )


class ChatMessage(BaseModel):
    """A single message in the conversation."""
    role: Literal["user", "assistant"]
    content: str
    timestamp: datetime
    search_results: Optional[List[SearchResult]] = None
    tools_used: Optional[List[Dict[str, Any]]] = None


class ChatResponse(BaseModel):
    """Response model for chat endpoint."""
    session_id: str
    message: ChatMessage
    conversation_turn: int = Field(
        description="Current turn number in the conversation"
    )
    search_results: Optional[List[SearchResult]] = None
    agent_reasoning: Optional[List[str]] = None
    tools_used: Optional[List[Dict[str, Any]]] = None
    response_time_ms: float


class ChatHistoryResponse(BaseModel):
    """Response model for chat history."""
    session_id: str
    messages: List[ChatMessage]
    created_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    message_count: int


class ChatSessionInfo(BaseModel):
    """Info about a chat session."""
    session_id: str
    created_at: datetime
    last_activity: datetime
    message_count: int


