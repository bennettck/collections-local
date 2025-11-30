from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from datetime import datetime
from typing import Optional


class Settings(BaseSettings):
    """Application settings from environment variables."""
    anthropic_api_key: str
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
    model: str = "claude-sonnet-4-20250514"


class ItemListResponse(BaseModel):
    """Response model for listing items."""
    items: list[ItemResponse]
    total: int


