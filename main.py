import os
import time
import uuid
import aiofiles
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from dotenv import load_dotenv

from models import (
    ItemResponse,
    ItemListResponse,
    AnalysisRequest,
    AnalysisResponse,
    Settings,
    SearchRequest,
    SearchResult,
    SearchResponse,
    GoldenAnalysisEntry,
    CompareRequest,
    CompareResponse,
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
    rebuild_search_index,
    search_items,
    get_search_status,
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

    # Initialize search index if empty
    status = get_search_status()
    if status['doc_count'] == 0 and status['total_items'] > 0:
        print(f"Building search index for {status['total_items']} items...")
        stats = rebuild_search_index()
        print(f"Search index built: {stats['num_documents']} documents indexed")
    else:
        print(f"Search index ready: {status['doc_count']} documents")

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

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


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


# Search Endpoints
@app.post("/search", response_model=SearchResponse)
async def search_collection(request: SearchRequest):
    """
    Natural language search and Q&A over the collection.

    Retrieves relevant items using BM25 full-text search and optionally
    generates an AI-powered answer to the user's question.
    """
    start_time = time.time()

    # Retrieve top-k items using FTS5 BM25
    try:
        search_results = search_items(
            query=request.query,
            top_k=request.top_k,
            category_filter=request.category_filter
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

    retrieval_time = (time.time() - start_time) * 1000

    # Convert to SearchResult objects
    results = []
    for rank, (item_id, score) in enumerate(search_results, 1):
        item = get_item(item_id)
        if not item:
            continue

        analysis = get_latest_analysis(item_id)
        raw_response = analysis.get("raw_response", {}) if analysis else {}

        results.append(SearchResult(
            item_id=item_id,
            rank=rank,
            score=score,
            category=analysis.get("category") if analysis else None,
            headline=raw_response.get("headline"),
            summary=analysis.get("summary") if analysis else None,
            image_url=f"/images/{item['filename']}",
            metadata=raw_response
        ))

    # Optionally generate answer using LLM
    answer = None
    answer_time = None
    citations = None
    confidence = None

    if request.include_answer and results:
        answer_start = time.time()

        from retrieval.answer_generator import generate_answer
        answer_data = generate_answer(
            query=request.query,
            results=[r.model_dump() for r in results],
            model=request.answer_model
        )

        answer = answer_data["answer"]
        citations = answer_data["citations"]
        confidence = answer_data["confidence"]
        answer_time = (time.time() - answer_start) * 1000

    return SearchResponse(
        query=request.query,
        results=results,
        total_results=len(results),
        answer=answer,
        answer_confidence=confidence,
        citations=citations,
        retrieval_time_ms=retrieval_time,
        answer_time_ms=answer_time
    )


# Index Management Endpoints
@app.post("/index/rebuild")
async def rebuild_index():
    """
    Rebuild the FTS5 search index from current database.

    Useful after bulk analysis updates or if search results seem stale.
    """
    start_time = time.time()

    try:
        stats = rebuild_search_index()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Index rebuild failed: {str(e)}")

    build_time = time.time() - start_time

    return {
        "status": "success",
        "num_documents": stats["num_documents"],
        "build_time_seconds": round(build_time, 2),
        "timestamp": stats["timestamp"]
    }


@app.get("/index/status")
async def get_index_status_endpoint():
    """Get current search index status and statistics."""
    try:
        status = get_search_status()
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get index status: {str(e)}")


# Image Serving
from fastapi.responses import FileResponse, HTMLResponse

@app.get("/images/{filename}")
async def serve_image(filename: str):
    """Serve image files for search results and item display."""
    file_path = os.path.join(IMAGES_PATH, filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(file_path)


# Golden Dataset Tool Endpoints
from utils.similarity import compare_text_arrays, tfidf_similarity
from utils.golden_dataset import (
    load_golden_dataset,
    update_golden_entry,
    has_golden_entry,
    get_golden_entry,
)


@app.get("/golden-dataset", response_class=HTMLResponse)
async def serve_golden_dataset_ui():
    """Serve the golden dataset creation tool UI."""
    html_path = Path("templates/golden_dataset.html")

    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Golden dataset UI not found")

    with open(html_path, 'r', encoding='utf-8') as f:
        return HTMLResponse(content=f.read())


@app.get("/golden-dataset/items")
async def get_items_for_review(
    review_mode: str = Query("unreviewed", regex="^(unreviewed|all|reviewed)$"),
    limit: int = Query(1, le=100),
    offset: int = Query(0, ge=0)
):
    """
    Get items for golden dataset review.

    Args:
        review_mode: Filter mode - "unreviewed" (default), "all", or "reviewed"
        limit: Number of items to return
        offset: Offset for pagination

    Returns:
        Dict with items list, total count, and reviewed count
    """
    from database import get_db

    with get_db() as conn:
        # Get items with pagination
        cursor = conn.cursor()

        # Get all item IDs and golden data
        golden_data = load_golden_dataset()
        reviewed_ids = {entry["item_id"] for entry in golden_data.get("golden_analyses", [])}

        all_items_rows = cursor.execute(
            "SELECT id FROM items ORDER BY created_at"
        ).fetchall()

        # Filter based on review_mode
        if review_mode == "unreviewed":
            # Show only items without golden data
            filtered_item_ids = [
                row['id'] for row in all_items_rows
                if row['id'] not in reviewed_ids
            ]
        elif review_mode == "reviewed":
            # Show only items with golden data
            filtered_item_ids = [
                row['id'] for row in all_items_rows
                if row['id'] in reviewed_ids
            ]
        else:  # review_mode == "all"
            # Show all items
            filtered_item_ids = [row['id'] for row in all_items_rows]

        # Apply pagination
        paginated_ids = filtered_item_ids[offset:offset + limit]

        # Build response for each item
        items = []
        for item_id in paginated_ids:
            item = get_item(item_id)
            if not item:
                continue

            analyses = get_item_analyses(item_id)

            items.append({
                "item_id": item_id,
                "filename": item['filename'],
                "original_filename": item.get('original_filename'),
                "analyses": analyses,
                "has_golden": has_golden_entry(item_id)
            })

        # Count totals
        total_count = cursor.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        golden_data = load_golden_dataset()
        reviewed_count = len(golden_data.get('golden_analyses', []))

        return {
            "items": items,
            "total": total_count,
            "reviewed_count": reviewed_count
        }


@app.post("/golden-dataset/compare", response_model=CompareResponse)
async def compare_analyses(request: CompareRequest):
    """
    Calculate similarity between analysis values.

    Uses Levenshtein distance for extracted_text and TF-IDF cosine similarity
    for headlines and summaries.

    Args:
        request: CompareRequest with field_type and values

    Returns:
        CompareResponse with similarity matrix and highest agreement
    """
    if request.field_type == "extracted_text":
        result = compare_text_arrays(request.values)
        result['method'] = 'levenshtein'
    else:  # headline or summary
        result = tfidf_similarity(request.values)
        result['method'] = 'tfidf'

    return CompareResponse(**result)


@app.post("/golden-dataset/save")
async def save_golden_entry(entry: GoldenAnalysisEntry):
    """
    Save or update a golden dataset entry.

    Args:
        entry: GoldenAnalysisEntry with curated values

    Returns:
        Dict with status and updated count
    """
    try:
        # Fetch item to get original_filename
        item = get_item(entry.item_id)
        if not item:
            raise HTTPException(status_code=404, detail=f"Item {entry.item_id} not found")

        # Convert entry to dict and inject original_filename from database
        entry_dict = entry.model_dump()
        entry_dict['original_filename'] = item.get('original_filename')

        update_golden_entry(entry.item_id, entry_dict)
        golden_data = load_golden_dataset()

        return {
            "status": "success",
            "item_id": entry.item_id,
            "total_golden_count": len(golden_data.get('golden_analyses', []))
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save golden entry: {str(e)}")


@app.get("/golden-dataset/status")
async def get_golden_status():
    """
    Get golden dataset progress statistics.

    Returns:
        Dict with total items, reviewed items, and progress percentage
    """
    from database import get_db

    try:
        with get_db() as conn:
            total_items = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]

        golden_data = load_golden_dataset()
        reviewed_count = len(golden_data.get('golden_analyses', []))

        return {
            "total_items": total_items,
            "reviewed_items": reviewed_count,
            "progress_percentage": round((reviewed_count / total_items * 100), 1) if total_items > 0 else 0
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")


@app.post("/keepalive")
async def keepalive():
    """
    Keepalive endpoint to prevent GitHub Codespace timeout.
    Writes a timestamp to a temporary file to generate filesystem activity.

    Returns:
        Dict with status and current timestamp
    """
    try:
        # Write to a temporary keepalive file to generate FS activity
        keepalive_file = Path(".keepalive")
        keepalive_file.write_text(str(time.time()))

        return {"status": "alive", "timestamp": time.time()}
    except Exception as e:
        # Don't fail if keepalive fails, just log it
        print(f"Keepalive error: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/golden-dataset/entry/{item_id}")
async def get_golden_entry_endpoint(item_id: str):
    """
    Get existing golden entry for an item.

    Args:
        item_id: Item UUID to fetch golden entry for

    Returns:
        Dict with entry (or None if not found)
    """
    entry = get_golden_entry(item_id)
    return {"entry": entry}
