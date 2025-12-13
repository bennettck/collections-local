# Collections App Local v0 - Implementation Spec

## Overview

Build a minimal local version of the Collections App that analyzes and categorizes screenshot images using AI. This serves as a development/testing environment that mirrors the production AWS architecture patterns.

## Tech Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| API | FastAPI + Uvicorn | REST API server |
| Database | SQLite + sqlite3 | Item metadata storage |
| File Storage | Local filesystem | Image storage |
| LLM | Anthropic SDK (direct) | Image analysis |
| Observability | Langfuse | Prompt management + tracing |
| Validation | Pydantic | Request/response models |

## Project Structure

```
collections-local/
├── .env.example            # Environment template
├── .env                    # Local env vars (gitignored)
├── requirements.txt        # Dependencies
├── main.py                 # FastAPI app + routes
├── models.py               # Pydantic models + DB schema
├── llm.py                  # Langfuse + Anthropic integration
├── database.py             # SQLite connection + CRUD
├── data/
│   ├── .gitkeep
│   └── images/             # Uploaded images stored here
│       └── .gitkeep
└── tests/
    └── test_api.py         # Basic API tests
```

## Environment Variables

```bash
# .env.example
ANTHROPIC_API_KEY=sk-ant-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com  # or self-hosted URL
DATABASE_PATH=./data/collections.db
IMAGES_PATH=./data/images
```

## Dependencies

```
# requirements.txt
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
python-multipart>=0.0.6
python-dotenv>=1.0.0
pydantic>=2.5.0
pydantic-settings>=2.1.0
anthropic>=0.40.0
langfuse>=2.0.0
aiofiles>=23.2.0
```

## Data Models

### Database Schema (SQLite)

```sql
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    original_filename TEXT,
    file_path TEXT NOT NULL,
    file_size INTEGER,
    mime_type TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analyses (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    category TEXT,
    subcategory TEXT,
    summary TEXT,
    extracted_text TEXT,
    tags TEXT,  -- JSON array stored as text
    confidence REAL,
    model_used TEXT,
    trace_id TEXT,  -- Langfuse trace ID
    created_at TEXT NOT NULL,
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_analyses_item_id ON analyses(item_id);
CREATE INDEX IF NOT EXISTS idx_items_category ON analyses(category);
```

### Pydantic Models (models.py)

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class ItemCreate(BaseModel):
    """Request model for creating an item (file upload)"""
    pass  # File comes via form data

class ItemResponse(BaseModel):
    id: str
    filename: str
    original_filename: Optional[str]
    file_size: Optional[int]
    mime_type: Optional[str]
    created_at: datetime
    updated_at: datetime
    latest_analysis: Optional["AnalysisResponse"] = None

class AnalysisResponse(BaseModel):
    id: str
    item_id: str
    version: int
    category: Optional[str]
    subcategory: Optional[str]
    summary: Optional[str]
    extracted_text: Optional[str]
    tags: list[str] = []
    confidence: Optional[float]
    model_used: Optional[str]
    trace_id: Optional[str]
    created_at: datetime

class AnalysisRequest(BaseModel):
    """Optional parameters for analysis"""
    force_reanalyze: bool = False
    model: str = "claude-sonnet-4-20250514"

class ItemListResponse(BaseModel):
    items: list[ItemResponse]
    total: int
    
class AnalysisResult(BaseModel):
    """Structured output from LLM analysis"""
    category: str = Field(description="Primary category: receipt, screenshot, document, note, reference, other")
    subcategory: Optional[str] = Field(description="More specific subcategory")
    summary: str = Field(description="2-3 sentence summary of the content")
    extracted_text: Optional[str] = Field(description="Key text extracted from the image")
    tags: list[str] = Field(description="Relevant tags for searchability", default_factory=list)
    confidence: float = Field(description="Confidence score 0-1", ge=0, le=1)
```

## API Endpoints

### Items

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/items` | Upload image, create item |
| GET | `/items` | List all items (with optional filters) |
| GET | `/items/{item_id}` | Get single item with latest analysis |
| DELETE | `/items/{item_id}` | Delete item and associated files/analyses |

### Analysis

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/items/{item_id}/analyze` | Trigger AI analysis |
| GET | `/items/{item_id}/analyses` | Get all analysis versions for item |
| GET | `/analyses/{analysis_id}` | Get specific analysis |

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |

## API Implementation (main.py)

```python
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uuid
from datetime import datetime

from models import ItemResponse, ItemListResponse, AnalysisRequest, AnalysisResponse
from database import init_db, get_db
from llm import analyze_image

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize database
    init_db()
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

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.post("/items", response_model=ItemResponse)
async def create_item(file: UploadFile = File(...)):
    """Upload an image and create a new item."""
    # 1. Validate file type
    # 2. Generate UUID
    # 3. Save file to disk
    # 4. Create DB record
    # 5. Return item
    pass

@app.get("/items", response_model=ItemListResponse)
async def list_items(
    category: str | None = Query(None),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0)
):
    """List all items with optional filtering."""
    pass

@app.get("/items/{item_id}", response_model=ItemResponse)
async def get_item(item_id: str):
    """Get a single item with its latest analysis."""
    pass

@app.delete("/items/{item_id}")
async def delete_item(item_id: str):
    """Delete an item and its associated files and analyses."""
    pass

@app.post("/items/{item_id}/analyze", response_model=AnalysisResponse)
async def analyze_item(item_id: str, request: AnalysisRequest = AnalysisRequest()):
    """Trigger AI analysis on an item."""
    # 1. Get item from DB
    # 2. Load image from disk
    # 3. Call LLM via Langfuse
    # 4. Store analysis result
    # 5. Return analysis
    pass

@app.get("/items/{item_id}/analyses", response_model=list[AnalysisResponse])
async def get_item_analyses(item_id: str):
    """Get all analysis versions for an item."""
    pass
```

## Langfuse Integration (llm.py)

### Setup

```python
import os
import base64
from anthropic import Anthropic
from langfuse import Langfuse
from langfuse.decorators import observe, langfuse_context
from models import AnalysisResult

# Initialize clients
langfuse = Langfuse()
anthropic = Anthropic()

def get_prompt(name: str) -> str:
    """Fetch prompt from Langfuse by name."""
    prompt = langfuse.get_prompt(name)
    return prompt.compile()
```

### Langfuse Prompts to Create

Create these prompts in your Langfuse dashboard:

**Prompt: `collections-categorize`**
```
You are analyzing a screenshot or image from a user's collection. Your task is to categorize and extract useful information.

Analyze the image and provide:
1. A primary category (one of: receipt, screenshot, document, note, reference, other)
2. A subcategory if applicable
3. A 2-3 sentence summary of the content
4. Key text extracted from the image (if text is present)
5. Relevant tags for searchability
6. Your confidence score (0-1)

Respond with valid JSON matching this schema:
{
  "category": "string",
  "subcategory": "string or null",
  "summary": "string",
  "extracted_text": "string or null", 
  "tags": ["string"],
  "confidence": number
}
```

### Analysis Function

```python
@observe(name="analyze_image")
async def analyze_image(image_path: str, model: str = "claude-sonnet-4-20250514") -> AnalysisResult:
    """
    Analyze an image using Claude vision via Langfuse tracing.
    
    Args:
        image_path: Path to the image file
        model: Anthropic model to use
        
    Returns:
        AnalysisResult with category, summary, tags, etc.
    """
    # Load and encode image
    with open(image_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")
    
    # Determine media type
    media_type = "image/png"  # Detect from file extension
    if image_path.lower().endswith(".jpg") or image_path.lower().endswith(".jpeg"):
        media_type = "image/jpeg"
    elif image_path.lower().endswith(".webp"):
        media_type = "image/webp"
    elif image_path.lower().endswith(".gif"):
        media_type = "image/gif"
    
    # Get prompt from Langfuse
    system_prompt = get_prompt("collections-categorize")
    
    # Call Anthropic
    response = anthropic.messages.create(
        model=model,
        max_tokens=1024,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Analyze this image and categorize it for my collection."
                    }
                ],
            }
        ],
    )
    
    # Update Langfuse trace with model info
    langfuse_context.update_current_observation(
        model=model,
        usage={
            "input": response.usage.input_tokens,
            "output": response.usage.output_tokens
        }
    )
    
    # Parse response
    import json
    result_text = response.content[0].text
    result_data = json.loads(result_text)
    
    return AnalysisResult(**result_data)
```

## Database Functions (database.py)

```python
import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Optional
import json

DATABASE_PATH = os.getenv("DATABASE_PATH", "./data/collections.db")

def init_db():
    """Initialize database with schema."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS items (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                original_filename TEXT,
                file_path TEXT NOT NULL,
                file_size INTEGER,
                mime_type TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                category TEXT,
                subcategory TEXT,
                summary TEXT,
                extracted_text TEXT,
                tags TEXT,
                confidence REAL,
                model_used TEXT,
                trace_id TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_analyses_item_id ON analyses(item_id);
        """)

@contextmanager
def get_db():
    """Get database connection with row factory."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def create_item(item_id: str, filename: str, original_filename: str, 
                file_path: str, file_size: int, mime_type: str) -> dict:
    """Create a new item in the database."""
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO items (id, filename, original_filename, file_path, 
               file_size, mime_type, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (item_id, filename, original_filename, file_path, file_size, mime_type, now, now)
        )
    return get_item(item_id)

def get_item(item_id: str) -> Optional[dict]:
    """Get an item by ID."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return dict(row) if row else None

def list_items(category: str = None, limit: int = 50, offset: int = 0) -> list[dict]:
    """List items with optional category filter."""
    with get_db() as conn:
        if category:
            # Join with analyses to filter by category
            rows = conn.execute("""
                SELECT DISTINCT i.* FROM items i
                LEFT JOIN analyses a ON i.id = a.item_id
                WHERE a.category = ?
                ORDER BY i.created_at DESC
                LIMIT ? OFFSET ?
            """, (category, limit, offset)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM items ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset)
            ).fetchall()
        return [dict(row) for row in rows]

def delete_item(item_id: str) -> bool:
    """Delete an item (cascades to analyses)."""
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        return cursor.rowcount > 0

def create_analysis(analysis_id: str, item_id: str, result: dict, 
                    model_used: str, trace_id: str = None) -> dict:
    """Create a new analysis for an item."""
    # Get next version number
    with get_db() as conn:
        row = conn.execute(
            "SELECT MAX(version) as max_ver FROM analyses WHERE item_id = ?",
            (item_id,)
        ).fetchone()
        version = (row["max_ver"] or 0) + 1
        
        now = datetime.utcnow().isoformat()
        tags_json = json.dumps(result.get("tags", []))
        
        conn.execute(
            """INSERT INTO analyses (id, item_id, version, category, subcategory,
               summary, extracted_text, tags, confidence, model_used, trace_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (analysis_id, item_id, version, result.get("category"), 
             result.get("subcategory"), result.get("summary"),
             result.get("extracted_text"), tags_json, result.get("confidence"),
             model_used, trace_id, now)
        )
    return get_analysis(analysis_id)

def get_analysis(analysis_id: str) -> Optional[dict]:
    """Get an analysis by ID."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
        if row:
            result = dict(row)
            result["tags"] = json.loads(result["tags"]) if result["tags"] else []
            return result
        return None

def get_latest_analysis(item_id: str) -> Optional[dict]:
    """Get the latest analysis for an item."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM analyses WHERE item_id = ? ORDER BY version DESC LIMIT 1",
            (item_id,)
        ).fetchone()
        if row:
            result = dict(row)
            result["tags"] = json.loads(result["tags"]) if result["tags"] else []
            return result
        return None

def get_item_analyses(item_id: str) -> list[dict]:
    """Get all analyses for an item."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM analyses WHERE item_id = ? ORDER BY version DESC",
            (item_id,)
        ).fetchall()
        results = []
        for row in rows:
            result = dict(row)
            result["tags"] = json.loads(result["tags"]) if result["tags"] else []
            results.append(result)
        return results
```

## Running the App

```bash
# Install dependencies
pip install -r requirements.txt

# Copy env file and fill in keys
cp .env.example .env

# Create data directories
mkdir -p data/images

# Run the server
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Then in Codespaces, make port 8000 public to access externally.

## Testing

```bash
# Health check
curl http://localhost:8000/health

# Upload an image
curl -X POST http://localhost:8000/items \
  -F "file=@screenshot.png"

# List items
curl http://localhost:8000/items

# Trigger analysis
curl -X POST http://localhost:8000/items/{item_id}/analyze

# Get item with analysis
curl http://localhost:8000/items/{item_id}
```

## Implementation Order

1. **Setup** - Create project structure, requirements.txt, .env
2. **Database** - Implement database.py with init and CRUD
3. **Models** - Define Pydantic models in models.py
4. **API basics** - FastAPI app with health check and item CRUD (no analysis yet)
5. **Langfuse setup** - Create prompt in Langfuse dashboard
6. **LLM integration** - Implement llm.py with analyze_image
7. **Analysis endpoints** - Wire up analysis routes
8. **Test** - Manual testing with curl/Postman

## Notes

- This mirrors the AWS production architecture patterns (repository pattern, service layer separation)
- SQLite can be swapped for DynamoDB by implementing the same interface
- Local file storage can be swapped for S3
- Langfuse provides the same prompt management and tracing as production
- No authentication in v0 - add later if needed for multi-user