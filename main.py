import os
import time
import uuid
import json
import logging
import aiofiles
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Request
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
    vector_search_items,
    get_search_status,
    create_embedding,
)
from llm import analyze_image, get_trace_id, get_resolved_provider_and_model
from embeddings import generate_embedding, generate_query_embedding, _create_embedding_document, DEFAULT_EMBEDDING_MODEL

# Load environment variables
load_dotenv()

# Setup logging
logger = logging.getLogger(__name__)

# Get settings - support both new and old env var names (backwards compatibility)
PROD_DATABASE_PATH = os.getenv("PROD_DATABASE_PATH") or os.getenv("DATABASE_PATH", "./data/collections.db")
GOLDEN_DATABASE_PATH = os.getenv("GOLDEN_DATABASE_PATH", "./data/collections_golden.db")
IMAGES_PATH = os.getenv("IMAGES_PATH", "./data/images")

# Log deprecation warning if old var is used
if os.getenv("DATABASE_PATH") and not os.getenv("PROD_DATABASE_PATH"):
    print("⚠️  WARNING: DATABASE_PATH is deprecated. Use PROD_DATABASE_PATH instead.")

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
    # Import database_context for scoped DB access
    from database import database_context

    # Initialize production database
    print("Initializing production database...")
    with database_context(PROD_DATABASE_PATH):
        init_db()

    # Initialize golden database
    print("Initializing golden database...")
    with database_context(GOLDEN_DATABASE_PATH):
        init_db()

    # Ensure images directory exists
    os.makedirs(IMAGES_PATH, exist_ok=True)

    # Initialize search index for production DB
    print("Checking production search index...")
    with database_context(PROD_DATABASE_PATH):
        status = get_search_status()
        if status['doc_count'] == 0 and status['total_items'] > 0:
            print(f"Building production search index ({status['total_items']} items)...")
            stats = rebuild_search_index()
            print(f"Production index built: {stats['num_documents']} documents")
        else:
            print(f"Production index ready: {status['doc_count']} documents")

    # Initialize search index for golden DB
    print("Checking golden search index...")
    with database_context(GOLDEN_DATABASE_PATH):
        status = get_search_status()
        if status['doc_count'] == 0 and status['total_items'] > 0:
            print(f"Building golden search index ({status['total_items']} items)...")
            stats = rebuild_search_index()
            print(f"Golden index built: {stats['num_documents']} documents")
        else:
            print(f"Golden index ready: {status['doc_count']} documents")

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

# Add database routing middleware
from middleware import DatabaseRoutingMiddleware

app.add_middleware(
    DatabaseRoutingMiddleware,
    prod_db_path=PROD_DATABASE_PATH,
    golden_db_path=GOLDEN_DATABASE_PATH
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
async def health_check(request: Request):
    """Health check endpoint with database context info."""
    from database import database_context

    # Get active database from request state (set by middleware)
    active_db = getattr(request.state, "active_database", "unknown")
    db_path = getattr(request.state, "db_path", "unknown")

    # Get item counts from both databases
    with database_context(PROD_DATABASE_PATH):
        prod_count = count_items()

    with database_context(GOLDEN_DATABASE_PATH):
        golden_count = count_items()

    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "active_database": active_db,
        "active_db_path": db_path,
        "database_stats": {
            "production": {"items": prod_count},
            "golden": {"items": golden_count}
        }
    }


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

    # Prepare metadata for tracing
    metadata = {
        "item_id": item_id,
        "filename": item.get("filename"),
        "original_filename": item.get("original_filename"),
        "provider": provider_used,
        "model": model_used,
    }

    # Call LLM with resolved provider and model
    try:
        result, trace_id = analyze_image(
            file_path,
            provider=provider_used,
            model=model_used,
            metadata=metadata
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

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

    # Generate and store embedding (non-blocking)
    try:
        # Create embedding document
        embedding_doc = _create_embedding_document(result)

        # Generate embedding
        embedding = generate_embedding(embedding_doc)

        # Store embedding with category metadata
        category = result.get("category")
        source_fields = {
            "weighting_strategy": "bm25_mirror",
            "fields": ["summary", "headline", "extracted_text", "category", "themes", "objects"]
        }

        create_embedding(
            item_id=item_id,
            analysis_id=analysis_id,
            embedding=embedding,
            model=DEFAULT_EMBEDDING_MODEL,
            source_fields=source_fields,
            category=category
        )
    except Exception as e:
        # Log error but don't fail the analysis
        logger.warning(f"Failed to generate embedding for {item_id}: {e}")

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

    Supports both BM25 full-text search and vector semantic search.
    """
    retrieval_start = time.time()

    # Route to appropriate search method
    if request.search_type == "bm25-lc":
        # LangChain BM25 retrieval
        from retrieval.langchain_retrievers import BM25LangChainRetriever

        retriever = BM25LangChainRetriever(
            top_k=request.top_k,
            category_filter=request.category_filter,
            min_relevance_score=request.min_relevance_score
        )

        documents = retriever.invoke(request.query)

        # Convert Documents to search_results format: List[(item_id, score)]
        search_results = [
            (doc.metadata["item_id"], doc.metadata["score"])
            for doc in documents
        ]
        score_type = "bm25"

    elif request.search_type == "vector-lc":
        # LangChain Vector retrieval
        from retrieval.langchain_retrievers import VectorLangChainRetriever

        retriever = VectorLangChainRetriever(
            top_k=request.top_k,
            category_filter=request.category_filter,
            min_similarity_score=request.min_similarity_score,
            embedding_model=DEFAULT_EMBEDDING_MODEL
        )

        documents = retriever.invoke(request.query)

        # Convert Documents to search_results format: List[(item_id, score)]
        search_results = [
            (doc.metadata["item_id"], doc.metadata["score"])
            for doc in documents
        ]
        score_type = "similarity"

    elif request.search_type == "hybrid-lc":
        # LangChain Hybrid retrieval (BM25 + Vector with RRF)
        from retrieval.langchain_retrievers import HybridLangChainRetriever

        retriever = HybridLangChainRetriever(
            top_k=request.top_k,
            bm25_top_k=request.top_k * 2,        # Fetch 2x for better fusion
            vector_top_k=request.top_k * 2,
            bm25_weight=0.3,                     # Reduced BM25 influence
            vector_weight=0.7,                   # Favor vector search
            rrf_c=15,                            # Lower c = more rank sensitivity
            category_filter=request.category_filter,
            min_relevance_score=request.min_relevance_score,
            min_similarity_score=request.min_similarity_score,
            embedding_model=DEFAULT_EMBEDDING_MODEL
        )

        documents = retriever.invoke(request.query)

        # Convert Documents to search_results format
        search_results = [
            (doc.metadata["item_id"], doc.metadata.get("rrf_score", doc.metadata.get("score", 0)))
            for doc in documents
        ]
        score_type = "hybrid_rrf"

    elif request.search_type == "vector":
        # Vector search
        # Generate query embedding
        query_embedding = generate_query_embedding(request.query)

        # Search using vector similarity
        search_results = vector_search_items(
            query_embedding=query_embedding,
            top_k=request.top_k,
            category_filter=request.category_filter,
            min_similarity_score=request.min_similarity_score
        )

        score_type = "similarity"

    else:  # BM25 (default)
        # Existing BM25 search
        search_results = search_items(
            query=request.query,
            top_k=request.top_k,
            category_filter=request.category_filter,
            min_relevance_score=request.min_relevance_score
        )

        score_type = "bm25"

    retrieval_time = (time.time() - retrieval_start) * 1000

    # Build SearchResult objects (same for both search types)
    results = []
    for rank, (item_id, score) in enumerate(search_results, start=1):
        item = get_item(item_id)
        if not item:
            continue

        analysis = get_latest_analysis(item_id)
        if not analysis:
            continue

        # raw_response is already a dict from the database
        analysis_data = analysis.get("raw_response", {})

        results.append(SearchResult(
            item_id=item_id,
            rank=rank,
            score=score,
            score_type=score_type,
            category=analysis_data.get("category"),
            headline=analysis_data.get("headline"),
            summary=analysis_data.get("summary"),
            image_url=f"/images/{item['filename']}",
            metadata=analysis_data
        ))

    # Generate answer (same for both search types)
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
        search_type=request.search_type,
        results=results,
        total_results=len(results),
        answer=answer,
        answer_confidence=confidence,
        citations=citations,
        retrieval_time_ms=retrieval_time,
        answer_time_ms=answer_time
    )


@app.get("/search/config")
async def get_search_config():
    """
    Get current search configuration for all search types.

    Returns the actual parameters being used for each search method,
    including field weighting, RRF parameters, embedding models, etc.
    """
    config = {
        "bm25": {
            "algorithm": "SQLite FTS5 BM25",
            "implementation": "Native",
            "field_weighting": {
                "summary": "3x",
                "headline": "2x",
                "extracted_text": "2x",
                "category": "1.5x",
                "subcategories": "1.5x",
                "key_interest": "1.5x",
                "themes": "1x",
                "objects": "1x",
                "location_tags": "1x",
                "emotions": "0.5x",
                "vibes": "0.5x",
                "hashtags": "0.5x"
            }
        },
        "vector": {
            "algorithm": "Cosine similarity",
            "implementation": "Native sqlite-vec",
            "embedding_model": DEFAULT_EMBEDDING_MODEL,
            "dimensions": 512 if "lite" in DEFAULT_EMBEDDING_MODEL else 1024,
            "field_weighting": {
                "summary": "3x",
                "headline": "2x",
                "extracted_text": "2x",
                "category": "1.5x",
                "subcategories": "1.5x",
                "key_interest": "1.5x",
                "themes": "1x",
                "objects": "1x",
                "location_tags": "1x",
                "emotions": "0.5x",
                "vibes": "0.5x",
                "hashtags": "0.5x"
            }
        },
        "bm25-lc": {
            "algorithm": "SQLite FTS5 BM25",
            "implementation": "LangChain wrapper",
            "field_weighting": {
                "summary": "3x",
                "headline": "2x",
                "extracted_text": "2x",
                "category": "1.5x",
                "subcategories": "1.5x",
                "key_interest": "1.5x",
                "themes": "1x",
                "objects": "1x",
                "location_tags": "1x",
                "emotions": "0.5x",
                "vibes": "0.5x",
                "hashtags": "0.5x"
            }
        },
        "vector-lc": {
            "algorithm": "Cosine similarity",
            "implementation": "LangChain wrapper",
            "embedding_model": DEFAULT_EMBEDDING_MODEL,
            "dimensions": 512 if "lite" in DEFAULT_EMBEDDING_MODEL else 1024,
            "field_weighting": {
                "summary": "3x",
                "headline": "2x",
                "extracted_text": "2x",
                "category": "1.5x",
                "subcategories": "1.5x",
                "key_interest": "1.5x",
                "themes": "1x",
                "objects": "1x",
                "location_tags": "1x",
                "emotions": "0.5x",
                "vibes": "0.5x",
                "hashtags": "0.5x"
            }
        },
        "hybrid-lc": {
            "algorithm": "RRF Ensemble (BM25 + Vector)",
            "implementation": "LangChain EnsembleRetriever",
            "rrf_constant_c": 15,
            "weights": {
                "bm25": 0.3,
                "vector": 0.7
            },
            "fetch_multiplier": "2x top_k from each retriever",
            "embedding_model": DEFAULT_EMBEDDING_MODEL,
            "deduplication": "by item_id",
            "field_weighting": "Inherits from BM25 and Vector (see above)"
        }
    }

    return config


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


# Vector Index Management Endpoints
@app.post("/vector-index/rebuild")
async def rebuild_vector_index_endpoint():
    """Rebuild vector search index."""
    from database import rebuild_vector_index
    result = rebuild_vector_index()
    return result


@app.get("/vector-index/status")
async def vector_index_status():
    """Get vector index statistics."""
    from database import get_vector_index_status
    return get_vector_index_status()


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
