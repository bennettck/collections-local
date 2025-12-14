# Golden Dataset Tool Implementation - Context Document

**Purpose**: This document provides complete context for implementing the Golden Dataset Creation Tool. It can be used to resume work in a fresh codespace instance without losing any decisions or understanding.

---

## Original User Request

The user requested:

> I need a way to create a golden data set to evaluate llm performance and analysis performance. I'm thinking that a web tool would show me a large version on an image and a combination of analyses for the items. I could then edit, modify, select applicable items which would be written into the golden dataset for the item. The tool would show:
>
> 1) a large version on the image
> 2) analyze the extracted text across the available 'extracted_text' across the available analysis from various models, and based on the similarity of the text a score would be assigned to indicate confidence in the "correctness of the text. The web UI would show the highest-confidence, most correct version. I can manually evaluate the text and make edits as needed.
> 3) For the remainder of the objects in the raw_response.image_detail, since most objects are lists, all items would be displayed and I could check/select the correct items. I would also need a option to add items in case the correct items are not in the list
> 4) a similar mechanism would be available for raw_response object category, subcategories, and potentially media_metadata
> 5) for headline and summary objects, I want to be able to rank each from all available analysis.

---

## User Decisions & Clarifications

### Question 1: Storage Format
**Answer**: JSON file in `data/eval/golden_analyses.json` with same schema as analyses for easier downstream analysis

### Question 2: Item Scope
**Answer**: All items (regardless of analysis count)

### Question 3: Similarity Scoring Methods
**Answer**:
- String matching (Levenshtein distance) for `extracted_text` fields
- TF-IDF cosine similarity for `headline` and `summary` fields

### Question 4: Technology Stack
**Answer**: Simple HTML/CSS/JS served by FastAPI (no build step, easy to modify, runs locally)

### Question 5: Single Analysis Items Workflow
**Answer**: Allow review/editing (curator can still verify and edit the single analysis to create golden data)

### Question 6: Headline/Summary Ranking
**Answer**: Just select the best one (not full ranking) - simpler UI, faster workflow

---

## Codebase Context Summary

### Database Structure

**SQLite database with 2 main tables**:

1. **`items` table**: Stores uploaded images
   - id (TEXT, PRIMARY KEY, UUID)
   - filename (UUID-based)
   - original_filename
   - file_path (full path to stored image)
   - file_size, mime_type
   - created_at, updated_at

2. **`analyses` table**: Stores AI analysis results
   - id (TEXT, PRIMARY KEY, UUID)
   - item_id (FK to items, CASCADE delete)
   - version (INTEGER, starts at 1, increments)
   - category (TEXT, extracted from raw_response)
   - summary (TEXT, extracted from raw_response)
   - raw_response (TEXT, JSON-encoded complete LLM response)
   - provider_used ("anthropic" or "openai")
   - model_used (e.g., "claude-sonnet-4-5")
   - trace_id (Langfuse trace ID)
   - created_at

**Key Point**: Items can have multiple analyses (different models/providers), each with incrementing version number.

### raw_response Structure

The `raw_response` JSON contains:

```json
{
  "category": "string",
  "subcategories": ["string", "string"],
  "headline": "string",
  "summary": "string",
  "media_metadata": {
    "original_poster": "string",
    "tagged_accounts": ["string"],
    "location_tags": ["string"],
    "audio_source": "string",
    "hashtags": ["string"]
  },
  "image_details": {
    "extracted_text": ["string"],
    "objects": ["string"],
    "themes": ["string"],
    "emotions": ["string"],
    "vibes": ["string"],
    "likely_source": "string",
    "key_interest": "string",
    "visual_hierarchy": ["string"]
  }
}
```

### Existing Patterns in Codebase

**File Locations**:
- Main API: `/workspaces/collections-local/main.py` (FastAPI app)
- Database functions: `/workspaces/collections-local/database.py`
- Models: `/workspaces/collections-local/models.py` (Pydantic)
- Images stored: `/workspaces/collections-local/data/images/`
- Image serving: `GET /images/{filename}` endpoint exists

**Similar Tool**: `scripts/create_test_set.py`
- Creates retrieval test queries (different purpose)
- Saves to `data/eval/test_queries.json`
- Uses terminal UI with colored output
- Interactive browsing of items
- Shows pattern for:
  - Loading items from database
  - Displaying item details
  - Collecting user input
  - Saving to JSON in `data/eval/`

**Database Access Pattern**:
```python
from database import get_db, get_item, get_latest_analysis, get_item_analyses

# Get all analyses for an item
analyses = get_item_analyses(item_id)  # Returns list[dict], newest first

# Each analysis dict has raw_response already parsed from JSON
```

**API Endpoint Pattern**:
```python
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

@app.get("/endpoint", response_class=HTMLResponse)
async def serve_ui():
    # Serve HTML template
    pass

@app.post("/endpoint")
async def process(request: RequestModel):
    # Process and return response
    pass
```

### Current Database Statistics
- Total items: 182
- Items with analyses: ~130
- Items with multiple analyses: Good candidates for comparison
- Max analyses per item: 7

---

## Technical Requirements

### New Dependencies
Add to `requirements.txt`:
```
scikit-learn>=1.3.0  # For TF-IDF vectorization
```

Optional (can implement pure Python fallback):
```
python-Levenshtein>=0.21.0  # Faster Levenshtein calculation
```

### Directory Structure to Create
```
utils/                          # NEW package
├── __init__.py
├── similarity.py               # Levenshtein + TF-IDF algorithms
└── golden_dataset.py          # JSON I/O operations

static/                         # NEW directory
├── css/
│   └── golden_dataset.css
└── js/
    └── golden_dataset.js

templates/                      # NEW directory
└── golden_dataset.html

data/eval/
└── golden_analyses.json       # Generated by tool (gitignore)
```

### Files to Modify
1. `main.py` - Add 5 new endpoints
2. `models.py` - Add 3 new Pydantic models
3. `requirements.txt` - Add scikit-learn

---

## Implementation Overview

### Core Components

**1. Similarity Algorithms** (`utils/similarity.py`)
- `levenshtein_similarity(str1, str2) -> float` - Normalize 0-1
- `compare_text_arrays(arrays: List[List[str]]) -> dict` - Compare extracted_text
- `tfidf_similarity(texts: List[str]) -> dict` - Compare headlines/summaries
- Return format: `{similarity_matrix: [...], highest_agreement: {...}, method: "..."}`

**2. Golden Dataset I/O** (`utils/golden_dataset.py`)
- `load_golden_dataset() -> dict` - Load or return empty structure
- `save_golden_dataset(dataset: dict) -> None` - Atomic write (temp + rename)
- `get_golden_entry(item_id: str) -> Optional[dict]`
- `has_golden_entry(item_id: str) -> bool`
- `update_golden_entry(item_id: str, entry: dict) -> None`

**3. API Endpoints** (`main.py`)
- `GET /golden-dataset` - Serve HTML UI
- `GET /golden-dataset/items?skip_reviewed=true&limit=1&offset=0` - Load items
- `POST /golden-dataset/compare` - Calculate similarities
- `POST /golden-dataset/save` - Save golden entry
- `GET /golden-dataset/status` - Progress stats

**4. Frontend** (HTML/CSS/JS)
- Single-page application
- Sections for each field type
- Color-coded similarity badges (green/yellow/red)
- Auto-save every 30 seconds
- Keyboard shortcuts (Ctrl+N/P/S)

### Golden Dataset Schema

```json
{
  "metadata": {
    "version": "1.0",
    "last_updated": "ISO-8601",
    "total_items": 25
  },
  "golden_analyses": [
    {
      "item_id": "uuid",
      "reviewed_at": "ISO-8601",
      "source_analyses_count": 3,
      "source_analysis_ids": ["id1", "id2"],

      "category": "Beauty",
      "subcategories": ["Perfume", "Shopping"],
      "headline": "...",
      "summary": "...",
      "media_metadata": {...},
      "image_details": {
        "extracted_text": [...],
        "objects": [...],
        "themes": [...],
        "emotions": [...],
        "vibes": [...],
        "visual_hierarchy": [...],
        "key_interest": "...",
        "likely_source": "..."
      }
    }
  ]
}
```

**CRITICAL**: Schema matches `raw_response` structure exactly for easier downstream comparison.

---

## Implementation Sequence

Follow this order to minimize dependencies:

### Step 1: Similarity Utilities
Create `utils/similarity.py` first - no dependencies on other new code.

**Levenshtein Implementation**:
```python
def levenshtein_distance(s1: str, s2: str) -> int:
    # Dynamic programming implementation
    # Create matrix (len(s1)+1) x (len(s2)+1)
    # Return bottom-right cell

def levenshtein_similarity(s1: str, s2: str) -> float:
    # Normalize: 1 - (distance / max(len(s1), len(s2)))
    # Returns 0.0-1.0 (1.0 = identical)

def compare_text_arrays(arrays: List[List[str]]) -> dict:
    # Flatten each array to string: " ".join(arr)
    # Pairwise Levenshtein comparison
    # Return matrix + highest agreement index
```

**TF-IDF Implementation**:
```python
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

def tfidf_similarity(texts: List[str]) -> dict:
    # Edge case: if len(texts) == 1, return identity
    # Create TfidfVectorizer
    # Fit and transform texts
    # Calculate pairwise cosine_similarity
    # Find text with highest average similarity (centroid)
    # Return matrix + highest agreement
```

### Step 2: Golden Dataset I/O
Create `utils/golden_dataset.py` - only depends on JSON/pathlib.

```python
import json
from pathlib import Path
from typing import Optional
from datetime import datetime

GOLDEN_PATH = Path("data/eval/golden_analyses.json")

def _get_empty_structure() -> dict:
    return {
        "metadata": {
            "version": "1.0",
            "created_at": datetime.utcnow().isoformat(),
            "last_updated": datetime.utcnow().isoformat(),
            "total_items": 0
        },
        "golden_analyses": []
    }

def load_golden_dataset() -> dict:
    if not GOLDEN_PATH.exists():
        return _get_empty_structure()
    with open(GOLDEN_PATH) as f:
        return json.load(f)

def save_golden_dataset(dataset: dict) -> None:
    # Ensure directory exists
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write: temp file + rename
    temp_path = GOLDEN_PATH.with_suffix('.tmp')
    with open(temp_path, 'w') as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)
    temp_path.replace(GOLDEN_PATH)

# ... other functions follow similar patterns
```

### Step 3: Pydantic Models
Add to `models.py`:

```python
from typing import List, Any, Literal, Optional
from pydantic import BaseModel

class GoldenAnalysisEntry(BaseModel):
    item_id: str
    reviewed_at: str  # ISO-8601
    source_analyses_count: int
    source_analysis_ids: List[str]
    category: str
    subcategories: List[str]
    headline: str
    summary: str
    media_metadata: dict
    image_details: dict

class CompareRequest(BaseModel):
    item_id: str
    field_type: Literal["extracted_text", "headline", "summary"]
    values: List[Any]  # Can be List[str] or List[List[str]]

class CompareResponse(BaseModel):
    similarity_matrix: List[List[float]]
    highest_agreement: dict
    method: Literal["levenshtein", "tfidf"]
```

### Step 4: API Endpoints
Add to `main.py`:

```python
from fastapi.responses import HTMLResponse
from pathlib import Path
from utils.similarity import compare_text_arrays, tfidf_similarity
from utils.golden_dataset import (
    load_golden_dataset, update_golden_entry, has_golden_entry
)

@app.get("/golden-dataset", response_class=HTMLResponse)
async def serve_golden_dataset_ui():
    html_path = Path("templates/golden_dataset.html")
    with open(html_path) as f:
        return HTMLResponse(content=f.read())

@app.get("/golden-dataset/items")
async def get_items_for_review(
    skip_reviewed: bool = True,
    limit: int = 1,
    offset: int = 0
):
    with get_db() as conn:
        # Get all item IDs
        rows = conn.execute(
            "SELECT id FROM items ORDER BY created_at LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()

        items = []
        for row in rows:
            item_id = row['id']

            # Skip if reviewed and flag is set
            if skip_reviewed and has_golden_entry(item_id):
                continue

            # Get item details
            item = get_item(item_id)
            analyses = get_item_analyses(item_id)

            items.append({
                "item_id": item_id,
                "filename": item['filename'],
                "analyses": analyses,
                "has_golden": has_golden_entry(item_id)
            })

        # Count total and reviewed
        total_count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        golden_data = load_golden_dataset()
        reviewed_count = len(golden_data['golden_analyses'])

        return {
            "items": items,
            "total": total_count,
            "reviewed_count": reviewed_count
        }

@app.post("/golden-dataset/compare")
async def compare_analyses(request: CompareRequest) -> CompareResponse:
    if request.field_type == "extracted_text":
        result = compare_text_arrays(request.values)
        result['method'] = 'levenshtein'
    else:  # headline or summary
        result = tfidf_similarity(request.values)
        result['method'] = 'tfidf'

    return CompareResponse(**result)

@app.post("/golden-dataset/save")
async def save_golden_entry(entry: GoldenAnalysisEntry):
    update_golden_entry(entry.item_id, entry.dict())
    golden_data = load_golden_dataset()
    return {
        "status": "success",
        "item_id": entry.item_id,
        "total_golden_count": len(golden_data['golden_analyses'])
    }

@app.get("/golden-dataset/status")
async def get_golden_status():
    with get_db() as conn:
        total_items = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]

    golden_data = load_golden_dataset()
    reviewed_count = len(golden_data['golden_analyses'])

    return {
        "total_items": total_items,
        "reviewed_items": reviewed_count,
        "progress_percentage": round((reviewed_count / total_items * 100), 1) if total_items > 0 else 0
    }
```

### Step 5: Frontend (HTML/CSS/JS)

**HTML**: Create sections for each field type with consistent patterns:
- Category: Radio buttons
- Subcategories: Checkboxes
- Extracted text: Radio + manual textarea
- Headline: Radio + manual input
- Summary: Radio + manual textarea
- Image details (objects/themes/etc): Checkboxes + add button
- Metadata: Checkboxes + inputs

**CSS**:
- Color-coded similarity badges
- Card-based sections
- Responsive layout

**JavaScript**:
- `GoldenDatasetApp` class
- Load items on init
- Display current item
- Calculate similarities via API
- Collect selections
- Save via API
- Auto-save timer
- Navigation

---

## Key Implementation Notes

### Similarity Score Color Coding
```javascript
function getSimilarityClass(score) {
    if (score >= 0.9) return 'similarity-high';      // Green
    if (score >= 0.7) return 'similarity-medium';    // Yellow
    return 'similarity-low';                          // Red
}
```

### Merging List Fields
For fields like `objects`, `themes`, `emotions`:
```javascript
function mergeListFields(analyses, fieldPath) {
    const allItems = new Set();
    analyses.forEach(analysis => {
        const items = getNestedField(analysis.raw_response, fieldPath) || [];
        items.forEach(item => allItems.add(item));
    });
    return Array.from(allItems);
}

// Example: mergeListFields(analyses, 'image_details.objects')
```

### Auto-Save Implementation
```javascript
// In GoldenDatasetApp
setupAutoSave() {
    this.autoSaveInterval = setInterval(() => {
        console.log('Auto-saving...');
        this.saveEntry(false);  // Save without navigating
    }, 30000);  // 30 seconds
}
```

### Edge Case: Single Analysis
```javascript
async populateExtractedText(analyses) {
    if (analyses.length === 1) {
        // No comparison possible, show single option without similarity
        const container = document.getElementById('text-options');
        container.innerHTML = `
            <div class="analysis-option">
                <input type="radio" name="text-choice" value="0" checked>
                <strong>Analysis v1</strong> (${analyses[0].provider_used})
                <div>${analyses[0].raw_response.image_details?.extracted_text?.join(', ') || 'N/A'}</div>
            </div>
        `;
        return;
    }

    // Multiple analyses: calculate similarities as normal
    // ...
}
```

---

## Testing Strategy

### Unit Tests (Optional but Recommended)
```python
# tests/test_similarity.py
def test_levenshtein_identical():
    assert levenshtein_similarity("hello", "hello") == 1.0

def test_levenshtein_completely_different():
    result = levenshtein_similarity("abc", "xyz")
    assert 0.0 <= result <= 0.3

def test_tfidf_single_text():
    result = tfidf_similarity(["hello world"])
    assert result['similarity_matrix'] == [[1.0]]
```

### Manual Testing Checklist
1. ✅ Item with 1 analysis displays (no similarity scores)
2. ✅ Item with 3+ analyses shows all versions
3. ✅ Similarity scores are reasonable (0-1 range)
4. ✅ Color coding works (green/yellow/red)
5. ✅ Selecting radio buttons works
6. ✅ Manual edit overrides selections
7. ✅ Checkboxes for lists work
8. ✅ Save persists to JSON
9. ✅ Auto-save triggers every 30s
10. ✅ Navigation loads next/previous items
11. ✅ Progress indicator updates
12. ✅ JSON schema matches analysis structure

### Test Items
- Item with 1 analysis: Test single-analysis workflow
- Item with 7 analyses: Test performance with many analyses
- Item with empty fields: Test graceful handling of missing data

---

## Resuming Implementation

When resuming in a fresh codespace:

1. Read this context document first
2. Read the implementation plan at `~/.claude/plans/serene-frolicking-flame.md`
3. Read the human documentation at `documentation/GOLDEN_DATASET.md`
4. Follow the implementation sequence (Steps 1-5 above)
5. Test thoroughly before marking complete

**No need to re-explore or re-ask questions** - all decisions have been documented here.

---

## References

- Implementation Plan: `/home/codespace/.claude/plans/serene-frolicking-flame.md`
- Human Documentation: `/workspaces/collections-local/documentation/GOLDEN_DATASET.md`
- Existing Test Set Script: `/workspaces/collections-local/scripts/create_test_set.py`
- Database Functions: `/workspaces/collections-local/database.py`
- API Main File: `/workspaces/collections-local/main.py`
- Models: `/workspaces/collections-local/models.py`
