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
from mangum import Mangum

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
    ChatRequest,
    ChatMessage,
    ChatResponse,
    ChatHistoryResponse,
    ChatSessionInfo,
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
    create_embedding,
    get_db,
    _create_search_document,
)

from llm import analyze_image, get_trace_id, get_resolved_provider_and_model
from embeddings import generate_embedding, _create_embedding_document, DEFAULT_EMBEDDING_MODEL, get_embedding_dimensions
from retrieval.pgvector_store import PGVectorStoreManager
from config.langchain_config import get_chroma_config, DEFAULT_EMBEDDING_MODEL as LANGCHAIN_EMBEDDING_MODEL
from config.retriever_config import get_voyage_config

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
    logger.warning("DATABASE_PATH is deprecated. Use PROD_DATABASE_PATH instead.")

# Allowed image MIME types
ALLOWED_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
}

# Global instances for Chroma vector stores (dual database support)
prod_chroma_manager = None
golden_chroma_manager = None

# Global conversation manager for multi-turn chat
conversation_manager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Skip SQLite initialization in Lambda (use PostgreSQL instead)
    is_lambda = bool(os.getenv("DB_SECRET_ARN") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))

    if not is_lambda:
        # Local development only: Initialize SQLite databases
        from database import database_context

        # Initialize production database
        with database_context(PROD_DATABASE_PATH):
            init_db()

        # Initialize golden database
        with database_context(GOLDEN_DATABASE_PATH):
            init_db()

        # Ensure images directory exists
        os.makedirs(IMAGES_PATH, exist_ok=True)

        # Initialize search index for production DB
        with database_context(PROD_DATABASE_PATH):
            status = get_search_status()
            if status['doc_count'] == 0 and status['total_items'] > 0:
                rebuild_search_index()

        # Initialize search index for golden DB
        with database_context(GOLDEN_DATABASE_PATH):
            status = get_search_status()
            if status['doc_count'] == 0 and status['total_items'] > 0:
                rebuild_search_index()

    # Initialize PGVector store for PRODUCTION database
    global prod_chroma_manager

    # Skip PGVector initialization in Lambda for now (lazy load on first use)
    if not is_lambda:
        try:
            prod_chroma_config = get_chroma_config("prod")
            prod_chroma_manager = PGVectorStoreManager(
                collection_name=prod_chroma_config["collection_name"],
                embedding_model=LANGCHAIN_EMBEDDING_MODEL,
                use_parameter_store=False,  # Use database connection from environment
                parameter_name=None
            )
        except Exception as e:
            logger.error(f"Failed to initialize PGVector (PROD): {e}")

        # Initialize PGVector store for GOLDEN database
        global golden_chroma_manager

        try:
            golden_chroma_config = get_chroma_config("golden")
            golden_chroma_manager = PGVectorStoreManager(
                collection_name=golden_chroma_config["collection_name"] + "_golden",
                embedding_model=LANGCHAIN_EMBEDDING_MODEL,
                use_parameter_store=False,  # Use database connection from environment
                parameter_name=None
            )
        except Exception as e:
            logger.error(f"Failed to initialize PGVector (GOLDEN): {e}")

    # Initialize conversation manager for multi-turn chat (local development only)
    global conversation_manager

    if not is_lambda:
        try:
            from chat.conversation_manager import ConversationManager
            from config.chat_config import CONVERSATION_DB_PATH, CLEANUP_ON_STARTUP, CONVERSATION_TTL_HOURS

            conversation_manager = ConversationManager(db_path=CONVERSATION_DB_PATH)

            # Cleanup expired sessions on startup
            if CLEANUP_ON_STARTUP:
                conversation_manager.cleanup_expired_sessions(ttl_hours=CONVERSATION_TTL_HOURS)
        except Exception as e:
            logger.error(f"Failed to initialize conversation manager: {e}")

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

# Mount static files (only if directory exists - not needed in Lambda)
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


# Helper function for database routing
def get_current_chroma_manager(request: Request) -> PGVectorStoreManager:
    """Get the appropriate Chroma manager based on request context."""
    host = request.headers.get("host", "")
    if "golden" in host:
        return golden_chroma_manager
    return prod_chroma_manager


def _parse_datetime(dt_value) -> datetime:
    """Parse datetime value (string from SQLite or datetime from PostgreSQL)."""
    if isinstance(dt_value, datetime):
        # Already a datetime object (PostgreSQL)
        return dt_value
    # String that needs parsing (SQLite)
    return datetime.fromisoformat(dt_value)


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
    # Get active database from request state (set by middleware)
    active_db = getattr(request.state, "active_database", "unknown")
    db_path = getattr(request.state, "db_path", "unknown")

    # Try to get item counts from databases (may fail in Lambda environment)
    database_stats = None
    try:
        from database import database_context
        with database_context(PROD_DATABASE_PATH):
            prod_count = count_items()
        with database_context(GOLDEN_DATABASE_PATH):
            golden_count = count_items()
        database_stats = {
            "production": {"items": prod_count},
            "golden": {"items": golden_count}
        }
    except Exception as e:
        # Database access not available (e.g., in Lambda) - skip stats
        logger.debug(f"Database stats unavailable: {e}")

    response = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "active_database": active_db,
        "active_db_path": db_path,
    }

    if database_stats:
        response["database_stats"] = database_stats

    return response


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

        # Real-time FTS5 index sync
        try:
            search_doc = _create_search_document(result)
            with get_db() as conn:
                # Delete existing entry if present (for re-analysis)
                conn.execute("DELETE FROM items_fts WHERE item_id = ?", (item_id,))
                # Insert new entry
                conn.execute(
                    "INSERT INTO items_fts(item_id, content) VALUES (?, ?)",
                    (item_id, search_doc)
                )
            logger.info(f"Successfully synced FTS5 index for {item_id}")
        except Exception as fts_error:
            # Log but don't fail analysis if FTS5 sync fails
            logger.error(f"Failed to sync FTS5 index for {item_id}: {fts_error}")

        # Real-time Chroma sync
        try:
            chroma_mgr = get_current_chroma_manager(request)
            item = get_item(item_id)
            if item:
                chroma_mgr.add_document(
                    item_id=item_id,
                    raw_response=result,
                    filename=item["filename"]
                )
                logger.info(f"Successfully synced Chroma vector store for {item_id}")
            else:
                logger.error(f"Cannot sync to Chroma: item {item_id} not found")
        except Exception as chroma_error:
            # Log but don't fail analysis if Chroma sync fails
            logger.error(f"Failed to sync to Chroma for {item_id}: {chroma_error}", exc_info=True)

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
async def search_collection(search_request: SearchRequest, request: Request):
    """
    Natural language search and Q&A over the collection.

    Supports BM25 full-text search, vector semantic search, and hybrid search with RRF fusion.
    All retrievers use LangChain for consistent observability and evaluation.
    """
    retrieval_start = time.time()

    # Route to appropriate search method
    if search_request.search_type == "agentic":
        # Agentic search with LangChain agent
        from retrieval.agentic_search import AgenticSearchOrchestrator

        chroma_mgr = get_current_chroma_manager(request)

        # Create orchestrator
        orchestrator = AgenticSearchOrchestrator(
            chroma_manager=chroma_mgr,
            top_k=search_request.top_k,
            category_filter=search_request.category_filter,
            min_relevance_score=search_request.min_relevance_score,
            min_similarity_score=search_request.min_similarity_score
        )

        # Execute agentic search
        agentic_result = orchestrator.search(search_request.query)

        # Extract documents and metadata
        documents = agentic_result["documents"]
        agent_reasoning = agentic_result["reasoning"]
        tools_used = agentic_result["tools_used"]
        agent_answer = agentic_result["final_answer"]

        # Convert Documents to search_results format
        search_results = [
            (doc.metadata["item_id"], doc.metadata.get("rrf_score", doc.metadata.get("score", 0)))
            for doc in documents
        ]
        score_type = "hybrid_rrf"

    elif search_request.search_type == "hybrid-lc":
        # Hybrid retrieval with RRF (LangChain BM25 + Chroma Vector)
        from retrieval.langchain_retrievers import HybridLangChainRetriever

        chroma_mgr = get_current_chroma_manager(request)

        retriever = HybridLangChainRetriever(
            top_k=search_request.top_k,
            bm25_top_k=search_request.top_k * 2,        # Fetch 2x for better fusion
            vector_top_k=search_request.top_k * 2,
            bm25_weight=0.3,                     # Reduced BM25 influence
            vector_weight=0.7,                   # Favor vector search
            rrf_c=15,                            # Lower c = more rank sensitivity
            category_filter=search_request.category_filter,
            min_relevance_score=search_request.min_relevance_score,
            min_similarity_score=search_request.min_similarity_score,
            chroma_manager=chroma_mgr
        )

        documents = retriever.invoke(search_request.query)

        # Convert Documents to search_results format
        search_results = [
            (doc.metadata["item_id"], doc.metadata.get("rrf_score", doc.metadata.get("score", 0)))
            for doc in documents
        ]
        score_type = "hybrid_rrf"

    elif search_request.search_type == "vector-lc":
        # LangChain Vector retrieval
        from retrieval.langchain_retrievers import VectorLangChainRetriever

        chroma_mgr = get_current_chroma_manager(request)

        retriever = VectorLangChainRetriever(
            top_k=search_request.top_k,
            category_filter=search_request.category_filter,
            min_similarity_score=search_request.min_similarity_score,
            chroma_manager=chroma_mgr
        )

        documents = retriever.invoke(search_request.query)

        # Convert Documents to search_results format
        search_results = [
            (doc.metadata["item_id"], doc.metadata["score"])
            for doc in documents
        ]
        score_type = "similarity"

    elif search_request.search_type == "bm25-lc":
        # LangChain BM25 retrieval
        from retrieval.langchain_retrievers import BM25LangChainRetriever

        retriever = BM25LangChainRetriever(
            top_k=search_request.top_k,
            category_filter=search_request.category_filter,
            min_relevance_score=search_request.min_relevance_score
        )

        documents = retriever.invoke(search_request.query)

        # Convert Documents to search_results format
        search_results = [
            (doc.metadata["item_id"], doc.metadata["score"])
            for doc in documents
        ]
        score_type = "bm25"

    else:
        # This should never happen due to Pydantic validation
        raise ValueError(f"Invalid search_type: {search_request.search_type}")

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
    reasoning = None
    tools = None

    # For agentic search, use agent's answer and metadata
    if search_request.search_type == "agentic":
        answer = agent_answer
        reasoning = agent_reasoning
        tools = tools_used
        # Set answer_time to 0 since it's included in retrieval_time
        answer_time = 0
        # Calculate simple confidence based on number of results
        confidence = min(1.0, len(results) / 5.0) if results else 0.0

    elif search_request.include_answer and results:
        answer_start = time.time()

        from retrieval.answer_generator import generate_answer
        answer_data = generate_answer(
            query=search_request.query,
            results=[r.model_dump() for r in results],
            model=search_request.answer_model
        )

        answer = answer_data["answer"]
        citations = answer_data["citations"]
        confidence = answer_data["confidence"]
        answer_time = (time.time() - answer_start) * 1000

    return SearchResponse(
        query=search_request.query,
        search_type=search_request.search_type,
        results=results,
        total_results=len(results),
        answer=answer,
        answer_confidence=confidence,
        citations=citations,
        retrieval_time_ms=retrieval_time,
        answer_time_ms=answer_time,
        agent_reasoning=reasoning,
        tools_used=tools
    )


@app.get("/search/config")
async def get_search_config():
    """
    Get current search configuration for all search types.

    Returns the actual parameters being used for each search method,
    including content fields, RRF parameters, embedding models, etc.

    IMPORTANT: This endpoint queries the actual runtime configuration from
    the data stores, not hardcoded values. This ensures evaluation reports
    accurately reflect what distance metrics and parameters are actually in use.
    """
    config = {
        "bm25": {
            "algorithm": "SQLite FTS5 BM25",
            "implementation": "Native",
            "content_field": "Unified content field (no field weighting)",
            "tokenizer": "unicode61 with diacritics removal"
        },
        "vector": {
            "algorithm": "Cosine similarity",  # Defined in database.py:497
            "implementation": "Native sqlite-vec",
            "embedding_model": DEFAULT_EMBEDDING_MODEL,
            "dimensions": get_embedding_dimensions(DEFAULT_EMBEDDING_MODEL),
            "content_field": "Unified content field (no field weighting)",
            "distance_metric": "cosine"  # sqlite-vec configuration
        },
        "hybrid": {
            "algorithm": "RRF Ensemble (Native BM25 + Native Vector)",
            "implementation": "Native implementations with LangChain EnsembleRetriever",
            "rrf_constant_c": 15,
            "weights": {
                "bm25": 0.3,
                "vector": 0.7
            },
            "fetch_multiplier": "2x top_k from each retriever",
            "embedding_model": DEFAULT_EMBEDDING_MODEL,
            "deduplication": "by item_id",
            "content_field": "Unified content field (no field weighting)",
            "components": {
                "bm25": "SQLite FTS5 (native, wrapper-based)",
                "vector": "sqlite-vec (native, wrapper-based, cosine)"
            }
        }
    }

    return config


# Chat Endpoints (Multi-Turn Agentic Chat)

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(chat_request: ChatRequest, request: Request):
    """
    Multi-turn conversational search and Q&A.

    Send messages with a session_id to maintain conversation context.
    The agent remembers previous exchanges and can handle follow-up questions
    like "show me more", "filter those by category", etc.

    The session_id should be a client-generated UUID that persists for the
    duration of the conversation (e.g., stored in sessionStorage).
    """
    if conversation_manager is None:
        raise HTTPException(
            status_code=503,
            detail="Conversation manager not initialized"
        )

    from chat.agentic_chat import AgenticChatOrchestrator
    from datetime import datetime

    chroma_mgr = get_current_chroma_manager(request)

    # Create orchestrator with conversation manager
    orchestrator = AgenticChatOrchestrator(
        chroma_manager=chroma_mgr,
        conversation_manager=conversation_manager,
        top_k=chat_request.top_k,
        category_filter=chat_request.category_filter,
        min_similarity_score=chat_request.min_similarity_score
    )

    # Execute chat
    result = orchestrator.chat(
        message=chat_request.message,
        session_id=chat_request.session_id
    )

    # Convert documents to SearchResult format
    search_results = None
    if result["documents"]:
        search_results = []
        for rank, doc in enumerate(result["documents"], start=1):
            metadata = doc.metadata
            item = get_item(metadata.get("item_id"))
            if item:
                search_results.append(SearchResult(
                    item_id=metadata.get("item_id"),
                    rank=rank,
                    score=metadata.get("rrf_score", metadata.get("score", 0)),
                    score_type="hybrid_rrf",
                    category=metadata.get("category"),
                    headline=metadata.get("headline"),
                    summary=metadata.get("summary"),
                    image_url=f"/images/{item['filename']}",
                    metadata=metadata
                ))

    # Build response
    return ChatResponse(
        session_id=result["session_id"],
        message=ChatMessage(
            role="assistant",
            content=result["response"],
            timestamp=datetime.utcnow(),
            search_results=search_results,
            tools_used=result["tools_used"]
        ),
        conversation_turn=result["conversation_turn"],
        search_results=search_results,
        agent_reasoning=result["reasoning"],
        tools_used=result["tools_used"],
        response_time_ms=result["response_time_ms"]
    )


@app.get("/chat/{session_id}/history", response_model=ChatHistoryResponse)
async def get_chat_history(session_id: str, request: Request):
    """
    Get conversation history for a session.

    Returns all messages exchanged in this conversation session.
    """
    if conversation_manager is None:
        raise HTTPException(
            status_code=503,
            detail="Conversation manager not initialized"
        )

    from chat.agentic_chat import AgenticChatOrchestrator
    from datetime import datetime

    chroma_mgr = get_current_chroma_manager(request)

    orchestrator = AgenticChatOrchestrator(
        chroma_manager=chroma_mgr,
        conversation_manager=conversation_manager
    )

    # Get session info
    session_info = conversation_manager.get_session_info(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get conversation history
    history = orchestrator.get_conversation_history(session_id)

    messages = [
        ChatMessage(
            role=msg["role"],
            content=msg["content"],
            timestamp=datetime.fromisoformat(msg["timestamp"]) if msg.get("timestamp") else datetime.utcnow()
        )
        for msg in history
    ]

    return ChatHistoryResponse(
        session_id=session_id,
        messages=messages,
        created_at=datetime.fromisoformat(session_info["created_at"]) if session_info.get("created_at") else None,
        last_activity=datetime.fromisoformat(session_info["last_activity"]) if session_info.get("last_activity") else None,
        message_count=session_info.get("message_count", 0)
    )


@app.delete("/chat/{session_id}")
async def clear_chat_session(session_id: str):
    """
    Clear a chat session and its history.

    This permanently deletes the conversation state for this session.
    """
    if conversation_manager is None:
        raise HTTPException(
            status_code=503,
            detail="Conversation manager not initialized"
        )

    deleted = conversation_manager.delete_session(session_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"status": "deleted", "session_id": session_id}


@app.get("/chat/sessions")
async def list_chat_sessions(limit: int = Query(50, le=100)):
    """
    List active chat sessions (dev/debug endpoint).

    Returns session metadata for debugging and monitoring.
    """
    if conversation_manager is None:
        raise HTTPException(
            status_code=503,
            detail="Conversation manager not initialized"
        )

    sessions = conversation_manager.list_sessions(limit=limit)
    stats = conversation_manager.get_stats()

    return {
        "sessions": [
            ChatSessionInfo(
                session_id=s["session_id"],
                created_at=datetime.fromisoformat(s["created_at"]),
                last_activity=datetime.fromisoformat(s["last_activity"]),
                message_count=s["message_count"]
            ).model_dump()
            for s in sessions
        ],
        "stats": stats
    }


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
@app.get("/vector-index/status")
async def vector_index_status():
    """Get vector index statistics."""
    from database import get_vector_index_status
    return get_vector_index_status()


# LangChain Index Management Endpoints

@app.post("/langchain-index/rebuild-chroma")
async def rebuild_chroma_index(database: str = Query("prod", description="Database type: prod or golden")):
    """Rebuild PGVector index for specified database."""
    global prod_chroma_manager, golden_chroma_manager

    try:
        if database == "golden":
            chroma_config = get_chroma_config("golden")
            golden_chroma_manager = PGVectorStoreManager(
                collection_name=chroma_config["collection_name"] + "_golden",
                embedding_model=LANGCHAIN_EMBEDDING_MODEL,
                use_parameter_store=True,
                parameter_name="/collections-local/rds/connection-string"
            )
            golden_chroma_manager.delete_collection()
            num_docs = golden_chroma_manager.build_index(batch_size=128)
            return {
                "status": "success",
                "database": "golden",
                "num_documents": num_docs,
                "message": "PGVector index rebuilt successfully"
            }
        else:
            chroma_config = get_chroma_config("prod")
            prod_chroma_manager = PGVectorStoreManager(
                collection_name=chroma_config["collection_name"],
                embedding_model=LANGCHAIN_EMBEDDING_MODEL,
                use_parameter_store=True,
                parameter_name="/collections-local/rds/connection-string"
            )
            prod_chroma_manager.delete_collection()
            num_docs = prod_chroma_manager.build_index(batch_size=128)
            return {
                "status": "success",
                "database": "prod",
                "num_documents": num_docs,
                "message": "PGVector index rebuilt successfully"
            }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to rebuild PGVector index: {str(e)}"
        )


@app.get("/langchain-index/status")
async def langchain_index_status():
    """Get status of LangChain indexes for both databases."""
    return {
        "prod": {
            "chroma": {
                "status": "loaded" if prod_chroma_manager else "not_loaded",
                "stats": prod_chroma_manager.get_collection_stats() if prod_chroma_manager else None
            }
        },
        "golden": {
            "chroma": {
                "status": "loaded" if golden_chroma_manager else "not_loaded",
                "stats": golden_chroma_manager.get_collection_stats() if golden_chroma_manager else None
            }
        }
    }


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
        logger.error(f"Keepalive error: {e}")
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


# ============================================================================
# AWS Lambda Handler (Mangum Adapter)
# ============================================================================

# Optional Cognito authentication middleware
# Only enabled when COGNITO_USER_POOL_ID is set (AWS environment)
cognito_user_pool_id = os.getenv("COGNITO_USER_POOL_ID")
cognito_enabled = cognito_user_pool_id and cognito_user_pool_id != "WILL_BE_SET_BY_CDK"

if cognito_enabled:
    from app.middleware.auth import CognitoAuthMiddleware

    # Get Cognito configuration
    cognito_region = os.getenv("COGNITO_REGION", os.getenv("AWS_REGION", "us-east-1"))
    cognito_client_id = os.getenv("COGNITO_CLIENT_ID")

    # Add Cognito auth middleware
    app.add_middleware(
        CognitoAuthMiddleware,
        user_pool_id=cognito_user_pool_id,
        region=cognito_region,
        client_id=cognito_client_id,
        enabled=True,
    )
    logger.info(f"Cognito authentication enabled for User Pool: {cognito_user_pool_id}")
else:
    logger.info("Cognito authentication disabled (local development mode)")

# Mangum handler for AWS Lambda
# This wraps the FastAPI app to handle Lambda events
handler = Mangum(app, lifespan="off")  # Use "off" to avoid lifespan issues in Lambda
