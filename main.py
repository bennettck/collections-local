import os
import uuid
import aiofiles
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from dotenv import load_dotenv

from models import (
    ItemResponse,
    ItemListResponse,
    AnalysisRequest,
    AnalysisResponse,
    Settings,
)
from database import (
    init_db,
    create_item,
    get_item,
    list_items,
    count_items,
    delete_item,
    create_analysis,
    get_analysis,
    get_latest_analysis,
    get_item_analyses,
)
from llm import analyze_image, get_trace_id, get_resolved_provider_and_model

# Load environment variables
load_dotenv()

# Get settings
IMAGES_PATH = os.getenv("IMAGES_PATH", "./data/images")

# Allowed image MIME types
ALLOWED_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup: initialize database
    init_db()
    # Ensure images directory exists
    os.makedirs(IMAGES_PATH, exist_ok=True)
    yield
    # Shutdown: cleanup if needed


app = FastAPI(
    title="Collections App Local",
    version="0.1.0",
    lifespan=lifespan
)

# CORS for local frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _parse_datetime(dt_str: str) -> datetime:
    """Parse ISO datetime string to datetime object."""
    return datetime.fromisoformat(dt_str)


def _item_to_response(item: dict, include_analysis: bool = True) -> ItemResponse:
    """Convert database item dict to ItemResponse."""
    latest_analysis = None
    if include_analysis:
        analysis_data = get_latest_analysis(item["id"])
        if analysis_data:
            latest_analysis = AnalysisResponse(
                id=analysis_data["id"],
                item_id=analysis_data["item_id"],
                version=analysis_data["version"],
                category=analysis_data.get("category"),
                summary=analysis_data.get("summary"),
                raw_response=analysis_data.get("raw_response", {}),
                provider_used=analysis_data.get("provider_used"),
                model_used=analysis_data.get("model_used"),
                trace_id=analysis_data.get("trace_id"),
                created_at=_parse_datetime(analysis_data["created_at"]),
            )

    return ItemResponse(
        id=item["id"],
        filename=item["filename"],
        original_filename=item.get("original_filename"),
        file_size=item.get("file_size"),
        mime_type=item.get("mime_type"),
        created_at=_parse_datetime(item["created_at"]),
        updated_at=_parse_datetime(item["updated_at"]),
        latest_analysis=latest_analysis,
    )


def _analysis_to_response(analysis: dict) -> AnalysisResponse:
    """Convert database analysis dict to AnalysisResponse."""
    return AnalysisResponse(
        id=analysis["id"],
        item_id=analysis["item_id"],
        version=analysis["version"],
        category=analysis.get("category"),
        summary=analysis.get("summary"),
        raw_response=analysis.get("raw_response", {}),
        provider_used=analysis.get("provider_used"),
        model_used=analysis.get("model_used"),
        trace_id=analysis.get("trace_id"),
        created_at=_parse_datetime(analysis["created_at"]),
    )


# Health Check
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


# Item Endpoints
@app.post("/items", response_model=ItemResponse)
async def create_item_endpoint(file: UploadFile = File(...)):
    """Upload an image and create a new item."""
    # Validate file type
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed types: {', '.join(ALLOWED_MIME_TYPES)}"
        )

    # Generate UUID
    item_id = str(uuid.uuid4())

    # Determine file extension from content type
    ext_map = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    extension = ext_map.get(file.content_type, ".png")
    filename = f"{item_id}{extension}"
    file_path = os.path.join(IMAGES_PATH, filename)

    # Save file to disk
    content = await file.read()
    file_size = len(content)

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    # Create DB record
    item = create_item(
        item_id=item_id,
        filename=filename,
        original_filename=file.filename,
        file_path=file_path,
        file_size=file_size,
        mime_type=file.content_type,
    )

    return _item_to_response(item, include_analysis=False)


@app.get("/items", response_model=ItemListResponse)
async def list_items_endpoint(
    category: str | None = Query(None),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0)
):
    """List all items with optional filtering."""
    items = list_items(category=category, limit=limit, offset=offset)
    total = count_items(category=category)

    return ItemListResponse(
        items=[_item_to_response(item) for item in items],
        total=total,
    )


@app.get("/items/{item_id}", response_model=ItemResponse)
async def get_item_endpoint(item_id: str):
    """Get a single item with its latest analysis."""
    item = get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    return _item_to_response(item)


@app.delete("/items/{item_id}")
async def delete_item_endpoint(item_id: str):
    """Delete an item and its associated files and analyses."""
    item = get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Delete file from disk
    file_path = item.get("file_path")
    if file_path and os.path.exists(file_path):
        os.remove(file_path)

    # Delete from database (cascades to analyses)
    delete_item(item_id)

    return {"status": "deleted", "id": item_id}


# Analysis Endpoints
@app.post("/items/{item_id}/analyze", response_model=AnalysisResponse)
async def analyze_item_endpoint(
    item_id: str,
    request: AnalysisRequest = AnalysisRequest()
):
    """Trigger AI analysis on an item."""
    # Get item from DB
    item = get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Check if analysis exists (unless force_reanalyze)
    if not request.force_reanalyze:
        existing = get_latest_analysis(item_id)
        if existing:
            return _analysis_to_response(existing)

    # Get file path
    file_path = item.get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Image file not found")

    # Resolve provider and model
    provider_used, model_used = get_resolved_provider_and_model(
        provider=request.provider,
        model=request.model
    )

    # Call LLM
    try:
        result = analyze_image(file_path, provider=request.provider, model=request.model)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

    # Get trace ID from Langfuse
    trace_id = get_trace_id()

    # Store analysis result
    analysis_id = str(uuid.uuid4())
    analysis = create_analysis(
        analysis_id=analysis_id,
        item_id=item_id,
        result=result,
        provider_used=provider_used,
        model_used=model_used,
        trace_id=trace_id,
    )

    return _analysis_to_response(analysis)


@app.get("/items/{item_id}/analyses", response_model=list[AnalysisResponse])
async def get_item_analyses_endpoint(item_id: str):
    """Get all analysis versions for an item."""
    # Verify item exists
    item = get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    analyses = get_item_analyses(item_id)
    return [_analysis_to_response(a) for a in analyses]


@app.get("/analyses/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis_endpoint(analysis_id: str):
    """Get a specific analysis."""
    analysis = get_analysis(analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    return _analysis_to_response(analysis)
