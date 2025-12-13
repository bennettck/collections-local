# Collections Local API Documentation

API documentation for the Collections App Local - a minimal local version that analyzes and categorizes screenshot images using AI.

## Overview

This API allows you to:
- Upload and manage image items
- Trigger AI-powered analysis on images
- Retrieve categorization, summaries, and extracted text

## Base URL

```
http://localhost:8000
```

## Authentication

No authentication required for local development.

---

## Health

### Health Check

Verify that the API server is running and healthy.

**Endpoint:** `GET /health`

**Response:**

```json
{
  "status": "healthy",
  "timestamp": "2025-11-30T12:00:00.000000"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Health status, always "healthy" if responding |
| `timestamp` | string | ISO 8601 timestamp of the response |

---

## Items

Endpoints for managing collection items (images).

### Upload Item

Upload an image file to create a new item in the collection.

**Endpoint:** `POST /items`

**Content-Type:** `multipart/form-data`

**Request:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | file | Yes | Image file (PNG, JPEG, WebP, or GIF) |

**Supported File Types:**

- `image/png`
- `image/jpeg`
- `image/webp`
- `image/gif`

**Example (curl):**

```bash
curl -X POST http://localhost:8000/items \
  -F "file=@screenshot.png"
```

**Response:** `200 OK`

```json
{
  "id": "uuid-string",
  "filename": "uuid-string.png",
  "original_filename": "screenshot.png",
  "file_size": 12345,
  "mime_type": "image/png",
  "created_at": "2025-11-30T12:00:00.000000",
  "updated_at": "2025-11-30T12:00:00.000000",
  "latest_analysis": null
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (UUID) for the item |
| `filename` | string | Stored filename (UUID-based) |
| `original_filename` | string | Original uploaded filename |
| `file_size` | integer | File size in bytes |
| `mime_type` | string | MIME type of the file |
| `created_at` | string | ISO 8601 creation timestamp |
| `updated_at` | string | ISO 8601 last update timestamp |
| `latest_analysis` | object/null | Latest analysis result (null if not analyzed) |

**Error Response:** `400 Bad Request`

```json
{
  "detail": "Invalid file type. Allowed types: image/png, image/jpeg, image/webp, image/gif"
}
```

---

### List Items

Retrieve a paginated list of all items in the collection.

**Endpoint:** `GET /items`

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `category` | string | - | Filter by analysis category |
| `limit` | integer | 50 | Maximum items to return (max 100) |
| `offset` | integer | 0 | Items to skip for pagination |

**Available Categories:**

- `receipt`
- `screenshot`
- `document`
- `note`
- `reference`
- `other`

**Example (curl):**

```bash
# List all items
curl http://localhost:8000/items

# Filter by category with pagination
curl "http://localhost:8000/items?category=screenshot&limit=10&offset=0"
```

**Response:** `200 OK`

```json
{
  "items": [
    {
      "id": "uuid-string",
      "filename": "uuid-string.png",
      "original_filename": "screenshot.png",
      "file_size": 12345,
      "mime_type": "image/png",
      "created_at": "2025-11-30T12:00:00.000000",
      "updated_at": "2025-11-30T12:00:00.000000",
      "latest_analysis": {
        "id": "analysis-uuid",
        "item_id": "uuid-string",
        "version": 1,
        "category": "Travel",
        "summary": "A TikTok screenshot about Togoshi Ginza...",
        "raw_response": { ... },
        "provider_used": "anthropic",
        "model_used": "claude-sonnet-4-5",
        "trace_id": null,
        "created_at": "2025-11-30T12:05:00.000000"
      }
    }
  ],
  "total": 1
}
```

| Field | Type | Description |
|-------|------|-------------|
| `items` | array | List of item objects |
| `total` | integer | Total count of items matching the filter |

---

### Get Item

Retrieve a single item by its ID, including the latest analysis if available.

**Endpoint:** `GET /items/{item_id}`

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `item_id` | string | UUID of the item |

**Example (curl):**

```bash
curl http://localhost:8000/items/uuid-string
```

**Response:** `200 OK`

```json
{
  "id": "uuid-string",
  "filename": "uuid-string.png",
  "original_filename": "screenshot.png",
  "file_size": 12345,
  "mime_type": "image/png",
  "created_at": "2025-11-30T12:00:00.000000",
  "updated_at": "2025-11-30T12:00:00.000000",
  "latest_analysis": {
    "id": "analysis-uuid",
    "item_id": "uuid-string",
    "version": 1,
    "category": "Travel",
    "summary": "A TikTok screenshot about Togoshi Ginza, a 1.3km local shopping street in Tokyo...",
    "raw_response": {
      "category": "Travel",
      "subcategories": ["Japan", "Shopping", "Local Culture"],
      "headline": "Togoshi Ginza: Tokyo's authentic 1.3km local shopping street",
      "summary": "A TikTok screenshot about Togoshi Ginza...",
      "media_metadata": {
        "original_poster": "recommend_ndre",
        "tagged_accounts": [],
        "location_tags": ["Tokyo"],
        "audio_source": "Apple Music - bloodline - Ariana Grande",
        "hashtags": ["#japan"]
      },
      "image_details": {
        "extracted_text": ["TOGOSHI GINZA", "With over 400 shops..."],
        "objects": ["Japanese street scene", "Traditional shop signs"],
        "themes": ["Authentic local experiences", "Japanese culture"],
        "emotions": ["Curiosity", "Cultural appreciation"],
        "vibes": ["Authentic", "Local", "Cultural immersion"],
        "likely_source": "TikTok",
        "key_interest": "Hidden local shopping district",
        "visual_hierarchy": ["TOGOSHI GINZA title text", "Descriptive paragraph"]
      }
    },
    "provider_used": "anthropic",
    "model_used": "claude-sonnet-4-5",
    "trace_id": null,
    "created_at": "2025-11-30T12:05:00.000000"
  }
}
```

**Error Response:** `404 Not Found`

```json
{
  "detail": "Item not found"
}
```

---

### Delete Item

Delete an item and all associated data including:
- The stored image file
- All analysis records

**Endpoint:** `DELETE /items/{item_id}`

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `item_id` | string | UUID of the item to delete |

**Example (curl):**

```bash
curl -X DELETE http://localhost:8000/items/uuid-string
```

**Response:** `200 OK`

```json
{
  "status": "deleted",
  "id": "uuid-string"
}
```

**Error Response:** `404 Not Found`

```json
{
  "detail": "Item not found"
}
```

---

## Analysis

Endpoints for AI-powered image analysis.

### Analyze Item

Trigger AI analysis on an uploaded image. The analysis uses AI vision capabilities (Anthropic Claude or OpenAI GPT-4o) to:
- Categorize the image
- Generate a summary
- Extract text content
- Assign relevant tags

**Endpoint:** `POST /items/{item_id}/analyze`

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `item_id` | string | UUID of the item to analyze |

**Request Body:**

```json
{
  "force_reanalyze": false,
  "provider": "anthropic",
  "model": "claude-sonnet-4-5"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `force_reanalyze` | boolean | `false` | If true, creates new analysis even if one exists |
| `provider` | string | `"anthropic"` | AI provider to use: `"anthropic"` or `"openai"` |
| `model` | string | *(provider default)* | Model to use. Defaults to `"claude-sonnet-4-5"` for Anthropic or `"gpt-4o"` for OpenAI |

**Provider Defaults:**

| Provider | Default Model |
|----------|---------------|
| `anthropic` | `claude-sonnet-4-5` |
| `openai` | `gpt-4o` |

**Example (curl):**

```bash
# Basic analysis (uses cached result if available, defaults to Anthropic)
curl -X POST http://localhost:8000/items/uuid-string/analyze

# Force reanalysis with default provider
curl -X POST http://localhost:8000/items/uuid-string/analyze \
  -H "Content-Type: application/json" \
  -d '{"force_reanalyze": true}'

# Use OpenAI instead of Anthropic
curl -X POST http://localhost:8000/items/uuid-string/analyze \
  -H "Content-Type: application/json" \
  -d '{"provider": "openai"}'

# Specify a different model
curl -X POST http://localhost:8000/items/uuid-string/analyze \
  -H "Content-Type: application/json" \
  -d '{"provider": "anthropic", "model": "claude-opus-4"}'
```

**Response:** `200 OK`

```json
{
  "id": "analysis-uuid",
  "item_id": "uuid-string",
  "version": 1,
  "category": "Travel",
  "summary": "A TikTok screenshot about Togoshi Ginza, a 1.3km local shopping street in Tokyo...",
  "raw_response": {
    "category": "Travel",
    "subcategories": ["Japan", "Shopping", "Local Culture"],
    "headline": "Togoshi Ginza: Tokyo's authentic 1.3km local shopping street",
    "summary": "A TikTok screenshot about Togoshi Ginza...",
    "media_metadata": {
      "original_poster": "recommend_ndre",
      "tagged_accounts": [],
      "location_tags": ["Tokyo"],
      "audio_source": "Apple Music - bloodline - Ariana Grande",
      "hashtags": ["#japan"]
    },
    "image_details": {
      "extracted_text": ["TOGOSHI GINZA", "With over 400 shops..."],
      "objects": ["Japanese street scene", "Traditional shop signs"],
      "themes": ["Authentic local experiences", "Japanese culture"],
      "emotions": ["Curiosity", "Cultural appreciation"],
      "vibes": ["Authentic", "Local", "Cultural immersion"],
      "likely_source": "TikTok",
      "key_interest": "Hidden local shopping district",
      "visual_hierarchy": ["TOGOSHI GINZA title text", "Descriptive paragraph"]
    }
  },
  "provider_used": "anthropic",
  "model_used": "claude-sonnet-4-5",
  "trace_id": null,
  "created_at": "2025-11-30T12:05:00.000000"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier for this analysis |
| `item_id` | string | ID of the analyzed item |
| `version` | integer | Analysis version number (increments with each reanalysis) |
| `category` | string | Primary category extracted from the analysis |
| `summary` | string | 2-3 sentence summary of the content |
| `raw_response` | object | Full LLM analysis response (see schema below) |
| `provider_used` | string | AI provider used (`"anthropic"` or `"openai"`) |
| `model_used` | string | AI model used for analysis |
| `trace_id` | string/null | Langfuse trace ID for debugging |
| `created_at` | string | ISO 8601 timestamp |

#### raw_response Schema

The `raw_response` object contains the complete analysis from the LLM:

| Field | Type | Description |
|-------|------|-------------|
| `category` | string | Primary category |
| `subcategories` | array | 2-3 specific subcategories |
| `headline` | string | 140 character headline |
| `summary` | string | 2-3 sentence summary |
| `media_metadata` | object | Social media metadata (poster, tags, location, audio, hashtags) |
| `image_details` | object | Detailed analysis (text, objects, themes, emotions, vibes, source, etc.) |

**Error Responses:**

`404 Not Found`
```json
{
  "detail": "Item not found"
}
```

`500 Internal Server Error`
```json
{
  "detail": "Analysis failed: <error message>"
}
```

**Prerequisites:**

Before using this endpoint, ensure:
1. Langfuse credentials are configured in `.env`
2. A prompt named `collections/image-analysis` exists in Langfuse

---

### Get Item Analyses

Retrieve all analysis versions for a specific item, ordered by version (newest first).

This is useful for:
- Viewing analysis history
- Comparing results across different models
- Tracking how categorization has changed

**Endpoint:** `GET /items/{item_id}/analyses`

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `item_id` | string | UUID of the item |

**Example (curl):**

```bash
curl http://localhost:8000/items/uuid-string/analyses
```

**Response:** `200 OK`

```json
[
  {
    "id": "analysis-uuid-2",
    "item_id": "uuid-string",
    "version": 2,
    "category": "Travel",
    "summary": "Updated analysis of a travel screenshot...",
    "raw_response": {
      "category": "Travel",
      "subcategories": ["Japan", "Shopping"],
      "headline": "...",
      "summary": "Updated analysis of a travel screenshot...",
      "media_metadata": { ... },
      "image_details": { ... }
    },
    "provider_used": "openai",
    "model_used": "gpt-4o",
    "trace_id": null,
    "created_at": "2025-11-30T14:00:00.000000"
  },
  {
    "id": "analysis-uuid-1",
    "item_id": "uuid-string",
    "version": 1,
    "category": "Travel",
    "summary": "Original analysis...",
    "raw_response": {
      "category": "Travel",
      "subcategories": ["Japan", "Local Culture"],
      "headline": "...",
      "summary": "Original analysis...",
      "media_metadata": { ... },
      "image_details": { ... }
    },
    "provider_used": "anthropic",
    "model_used": "claude-sonnet-4-5",
    "trace_id": null,
    "created_at": "2025-11-30T12:05:00.000000"
  }
]
```

**Error Response:** `404 Not Found`

```json
{
  "detail": "Item not found"
}
```

---

### Get Analysis

Retrieve a specific analysis by its ID.

**Endpoint:** `GET /analyses/{analysis_id}`

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `analysis_id` | string | UUID of the analysis |

**Example (curl):**

```bash
curl http://localhost:8000/analyses/analysis-uuid
```

**Response:** `200 OK`

```json
{
  "id": "analysis-uuid",
  "item_id": "uuid-string",
  "version": 1,
  "category": "Travel",
  "summary": "A TikTok screenshot about Togoshi Ginza...",
  "raw_response": {
    "category": "Travel",
    "subcategories": ["Japan", "Shopping", "Local Culture"],
    "headline": "Togoshi Ginza: Tokyo's authentic 1.3km local shopping street",
    "summary": "A TikTok screenshot about Togoshi Ginza...",
    "media_metadata": {
      "original_poster": "recommend_ndre",
      "tagged_accounts": [],
      "location_tags": ["Tokyo"],
      "audio_source": "Apple Music - bloodline - Ariana Grande",
      "hashtags": ["#japan"]
    },
    "image_details": {
      "extracted_text": ["TOGOSHI GINZA", "With over 400 shops..."],
      "objects": ["Japanese street scene", "Traditional shop signs"],
      "themes": ["Authentic local experiences", "Japanese culture"],
      "emotions": ["Curiosity", "Cultural appreciation"],
      "vibes": ["Authentic", "Local", "Cultural immersion"],
      "likely_source": "TikTok",
      "key_interest": "Hidden local shopping district",
      "visual_hierarchy": ["TOGOSHI GINZA title text", "Descriptive paragraph"]
    }
  },
  "provider_used": "anthropic",
  "model_used": "claude-sonnet-4-5",
  "trace_id": null,
  "created_at": "2025-11-30T12:05:00.000000"
}
```

**Error Response:** `404 Not Found`

```json
{
  "detail": "Analysis not found"
}
```

---

## Search & Retrieval

Natural language search and Q&A over your image collection using BM25 full-text search with AI-powered answer generation.

### Search Collection

Perform natural language search over your collection and optionally generate AI-powered answers to questions.

**Endpoint:** `POST /search`

**Request Body:**

```json
{
  "query": "Tokyo restaurants",
  "top_k": 10,
  "category_filter": null,
  "include_answer": true,
  "answer_model": null
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | string | *required* | Natural language search query (min 3 characters) |
| `top_k` | integer | `10` | Number of results to return (1-50) |
| `category_filter` | string | `null` | Filter results by category |
| `include_answer` | boolean | `true` | Generate LLM answer from search results |
| `answer_model` | string | `null` | Model for answer generation (defaults to `claude-sonnet-4-5`) |

**Example (curl):**

```bash
# Basic search with answer generation
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Tokyo restaurants", "top_k": 5}'

# Search without answer generation (faster)
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "beauty products perfume", "include_answer": false}'

# Search with category filter
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "food", "category_filter": "Food", "top_k": 10}'

# Use different model for answer
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Tokyo restaurants", "answer_model": "gpt-4o"}'
```

**Response:** `200 OK`

```json
{
  "query": "Tokyo restaurants",
  "results": [
    {
      "item_id": "8aed0ca7-6aed-4635-9cb2-ef47a2aba461",
      "rank": 1,
      "score": -4.640884826212837,
      "category": "Food",
      "headline": "Tofuya Ukai dining spot beneath Tokyo Tower in Minato City",
      "summary": "Tofuya Ukai (東京 芝 とうふ屋うかい) is presented as a beautiful restaurant...",
      "image_url": "/images/8aed0ca7-6aed-4635-9cb2-ef47a2aba461.jpg",
      "metadata": {
        "category": "Food",
        "subcategories": ["Restaurants", "Tokyo", "Japan"],
        "headline": "Tofuya Ukai dining spot beneath Tokyo Tower in Minato City",
        "summary": "Tofuya Ukai (東京 芝 とうふ屋うかい) is presented...",
        "media_metadata": { ... },
        "image_details": { ... }
      }
    }
  ],
  "total_results": 2,
  "answer": "Based on your collection, you have images of **Tofuya Ukai** (東京 芝 とうふ屋うかい), a stunning traditional Japanese restaurant located beneath Tokyo Tower in Minato City [Item 1, Item 2]. The restaurant is noted for its beautiful traditional architecture and landscaping, with dramatic views of the illuminated Tokyo Tower at night [Item 2].",
  "answer_confidence": 0.4185694423760841,
  "citations": ["1", "2"],
  "retrieval_time_ms": 1.71,
  "answer_time_ms": 4717.53
}
```

| Field | Type | Description |
|-------|------|-------------|
| `query` | string | The search query that was executed |
| `results` | array | List of search results ordered by relevance |
| `total_results` | integer | Total number of results returned |
| `answer` | string/null | AI-generated answer (null if `include_answer` is false) |
| `answer_confidence` | float/null | Confidence score 0-1 based on result relevance |
| `citations` | array/null | List of item numbers cited in the answer |
| `retrieval_time_ms` | float | Time taken for search in milliseconds |
| `answer_time_ms` | float/null | Time taken for answer generation in milliseconds |

#### SearchResult Object

| Field | Type | Description |
|-------|------|-------------|
| `item_id` | string | Unique identifier of the item |
| `rank` | integer | Rank position (1-based) |
| `score` | float | BM25 relevance score (lower/more negative = better match) |
| `category` | string/null | Primary category |
| `headline` | string/null | Item headline |
| `summary` | string/null | Item summary |
| `image_url` | string | URL to access the image file |
| `metadata` | object | Full raw_response analysis data |

**Search Features:**

- **BM25 Full-Text Search**: Fast keyword-based search using SQLite FTS5
- **All Fields Searchable**: Searches across categories, summaries, extracted text, locations, hashtags, and all metadata
- **Weighted Ranking**: Important fields (summary, headline) ranked higher than others
- **Natural Language Queries**: Ask questions like "Show me Tokyo restaurants" or "beauty products"
- **AI Answer Generation**: Optional LLM-powered answers with citations to specific items
- **Category Filtering**: Narrow results to specific categories

**Performance:**

- Retrieval: ~2-5ms for typical queries
- Answer generation: ~4-5 seconds (when enabled)

**Error Response:** `500 Internal Server Error`

```json
{
  "detail": "Search failed: <error message>"
}
```

---

### Rebuild Search Index

Rebuild the full-text search index from current database. Useful after bulk analysis updates or if search results seem stale.

**Endpoint:** `POST /index/rebuild`

**Example (curl):**

```bash
curl -X POST http://localhost:8000/index/rebuild
```

**Response:** `200 OK`

```json
{
  "status": "success",
  "num_documents": 130,
  "build_time_seconds": 0.08,
  "timestamp": "2025-12-13T00:22:30.219287"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Build status ("success") |
| `num_documents` | integer | Number of documents indexed |
| `build_time_seconds` | float | Time taken to rebuild in seconds |
| `timestamp` | string | ISO 8601 timestamp of rebuild |

**When to Rebuild:**

- After analyzing new items in bulk
- If search results seem outdated
- After changing analysis data
- Automatically runs on server startup if index is empty

**Error Response:** `500 Internal Server Error`

```json
{
  "detail": "Index rebuild failed: <error message>"
}
```

---

### Get Search Index Status

Get current status and statistics for the search index.

**Endpoint:** `GET /index/status`

**Example (curl):**

```bash
curl http://localhost:8000/index/status
```

**Response:** `200 OK`

```json
{
  "doc_count": 130,
  "total_items": 182,
  "is_loaded": true,
  "index_coverage": 0.7142857142857143
}
```

| Field | Type | Description |
|-------|------|-------------|
| `doc_count` | integer | Number of documents in search index |
| `total_items` | integer | Total number of items in database |
| `is_loaded` | boolean | Whether index is loaded and ready |
| `index_coverage` | float | Percentage of items indexed (0.0-1.0) |

**Understanding Index Coverage:**

- Coverage < 1.0 means some items haven't been analyzed yet
- Only items with analysis are included in search index
- Analyze remaining items to increase coverage

**Error Response:** `500 Internal Server Error`

```json
{
  "detail": "Failed to get index status: <error message>"
}
```

---

### Serve Image

Serve image files for display in search results and item details.

**Endpoint:** `GET /images/{filename}`

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `filename` | string | Image filename (UUID-based with extension) |

**Example (curl):**

```bash
curl http://localhost:8000/images/8aed0ca7-6aed-4635-9cb2-ef47a2aba461.jpg \
  --output image.jpg
```

**Response:** `200 OK`

Returns the image file with appropriate Content-Type header.

**Error Response:** `404 Not Found`

```json
{
  "detail": "Image not found"
}
```

---

## Golden Dataset

Endpoints for creating and managing curated "golden" analysis data for model evaluation. The Golden Dataset Creator is a web-based tool that helps curators review multiple AI analyses of the same image and select the most accurate values to create ground truth evaluation data.

### Golden Dataset UI

Serves the web-based golden dataset creation tool interface.

**Endpoint:** `GET /golden-dataset`

**Description:** Opens an interactive web interface for reviewing items with multiple analyses and curating golden reference data.

**Example (browser):**
```
http://localhost:8000/golden-dataset
```

**Response:** HTML page with the Golden Dataset Creator UI

**Features:**
- Side-by-side comparison of multiple analyses for the same item
- Automatic similarity scoring (Levenshtein for text, TF-IDF for summaries)
- Color-coded agreement indicators (green = high agreement, red = disagreement)
- Progress tracking and auto-save
- Keyboard shortcuts for efficient curation

For detailed usage instructions, see `documentation/GOLDEN_DATASET.md`.

---

### Get Items for Review

Retrieve items for golden dataset curation with their analyses.

**Endpoint:** `GET /golden-dataset/items`

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skip_reviewed` | boolean | `true` | Skip items that already have golden data |
| `limit` | integer | `1` | Number of items to return (max 100) |
| `offset` | integer | `0` | Offset for pagination |

**Example (curl):**

```bash
# Get next unreviewed item
curl "http://localhost:8000/golden-dataset/items?skip_reviewed=true&limit=1"

# Get all items including reviewed
curl "http://localhost:8000/golden-dataset/items?skip_reviewed=false&limit=10"
```

**Response:** `200 OK`

```json
{
  "items": [
    {
      "item_id": "abc-123-def",
      "filename": "abc-123-def.jpg",
      "has_golden": false,
      "analyses": [
        {
          "id": "analysis-1",
          "item_id": "abc-123-def",
          "version": 1,
          "category": "Beauty",
          "summary": "Analysis from Claude Sonnet 4.5...",
          "raw_response": { ... },
          "provider_used": "anthropic",
          "model_used": "claude-sonnet-4-5",
          "created_at": "2025-12-13T10:00:00.000000"
        },
        {
          "id": "analysis-2",
          "item_id": "abc-123-def",
          "version": 2,
          "category": "Beauty",
          "summary": "Analysis from GPT-4o...",
          "raw_response": { ... },
          "provider_used": "openai",
          "model_used": "gpt-4o",
          "created_at": "2025-12-13T11:00:00.000000"
        }
      ]
    }
  ],
  "total": 182,
  "reviewed_count": 25
}
```

| Field | Type | Description |
|-------|------|-------------|
| `items` | array | List of items with their analyses |
| `total` | integer | Total number of items in database |
| `reviewed_count` | integer | Number of items with golden data |

**Items Object:**

| Field | Type | Description |
|-------|------|-------------|
| `item_id` | string | Item UUID |
| `filename` | string | Image filename |
| `has_golden` | boolean | Whether this item has golden data |
| `analyses` | array | All analysis versions for this item |

---

### Compare Analyses

Calculate similarity scores between different analysis values to identify agreement.

**Endpoint:** `POST /golden-dataset/compare`

**Request Body:**

```json
{
  "field_type": "extracted_text",
  "values": [
    ["Text from analysis 1", "More text"],
    ["Text from analysis 2", "More text"],
    ["Slightly different text", "More text"]
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `field_type` | string | Type of field: `"extracted_text"`, `"headline"`, or `"summary"` |
| `values` | array | List of values to compare (strings or arrays of strings) |

**Similarity Methods:**

| Field Type | Method | Description |
|------------|--------|-------------|
| `extracted_text` | Levenshtein distance | Character-level comparison for OCR-like text |
| `headline`, `summary` | TF-IDF + Cosine similarity | Semantic comparison for generated text |

**Example (curl):**

```bash
# Compare extracted text from different analyses
curl -X POST http://localhost:8000/golden-dataset/compare \
  -H "Content-Type: application/json" \
  -d '{
    "field_type": "extracted_text",
    "values": [
      ["J-SCENT", "Tokyo perfume"],
      ["J-Scent", "Tokyo Perfume"],
      ["J-SCENT", "Tokyo perfume shop"]
    ]
  }'

# Compare headlines
curl -X POST http://localhost:8000/golden-dataset/compare \
  -H "Content-Type: application/json" \
  -d '{
    "field_type": "headline",
    "values": [
      "Tokyo perfume shop offers affordable fragrances",
      "Affordable perfume store in Tokyo",
      "Budget-friendly scents at Tokyo shop"
    ]
  }'
```

**Response:** `200 OK`

```json
{
  "method": "levenshtein",
  "similarity_matrix": [
    [1.0, 0.95, 0.87],
    [0.95, 1.0, 0.89],
    [0.87, 0.89, 1.0]
  ],
  "highest_agreement_index": 0,
  "average_similarity": 0.92
}
```

| Field | Type | Description |
|-------|------|-------------|
| `method` | string | Similarity method used (`"levenshtein"` or `"tfidf"`) |
| `similarity_matrix` | array | NxN matrix of pairwise similarity scores (0.0-1.0) |
| `highest_agreement_index` | integer | Index of value with highest average agreement |
| `average_similarity` | float | Mean similarity across all comparisons |

**Interpreting Scores:**

- **0.90-1.00** (🟢 Green): High agreement - models are very aligned
- **0.70-0.89** (🟡 Yellow): Moderate agreement - some variation
- **< 0.70** (🔴 Red): Low agreement - manual review needed

---

### Save Golden Entry

Save or update a curated golden dataset entry.

**Endpoint:** `POST /golden-dataset/save`

**Request Body:**

```json
{
  "item_id": "abc-123-def",
  "reviewed_at": "2025-12-13T12:00:00Z",
  "source_analyses_count": 3,
  "source_analysis_ids": ["analysis-1", "analysis-2", "analysis-3"],
  "category": "Beauty",
  "subcategories": ["Perfume", "Shopping"],
  "headline": "J-Scent perfume house in Tokyo",
  "summary": "Japanese perfume shop offering affordable fragrances...",
  "media_metadata": {
    "original_poster": "username",
    "tagged_accounts": [],
    "location_tags": ["Tokyo", "Japan"],
    "audio_source": "original sound",
    "hashtags": ["#beauty", "#perfume"]
  },
  "image_details": {
    "extracted_text": ["J-SCENT", "¥4,950"],
    "objects": ["perfume bottles", "tester bottles"],
    "themes": ["Japanese beauty", "affordable luxury"],
    "emotions": ["excited", "curious"],
    "vibes": ["luxurious", "intimate"],
    "visual_hierarchy": ["perfume bottles", "price tags"],
    "key_interest": "Affordable Japanese perfumes",
    "likely_source": "TikTok"
  }
}
```

**Field Requirements:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `item_id` | string | Yes | Item UUID |
| `reviewed_at` | string | No | ISO 8601 timestamp (auto-generated if omitted) |
| `source_analyses_count` | integer | Yes | Number of analyses reviewed |
| `source_analysis_ids` | array | Yes | IDs of analyses used for curation |
| `category` | string | Yes | Primary category |
| `subcategories` | array | No | List of subcategories |
| `headline` | string | Yes | Curated headline |
| `summary` | string | Yes | Curated summary |
| `media_metadata` | object | No | Social media metadata |
| `image_details` | object | No | Detailed image analysis |

**Example (curl):**

```bash
curl -X POST http://localhost:8000/golden-dataset/save \
  -H "Content-Type: application/json" \
  -d '{
    "item_id": "abc-123-def",
    "source_analyses_count": 2,
    "source_analysis_ids": ["analysis-1", "analysis-2"],
    "category": "Beauty",
    "subcategories": ["Perfume"],
    "headline": "Tokyo perfume shop",
    "summary": "A perfume shop in Tokyo...",
    "image_details": {
      "extracted_text": ["J-SCENT"],
      "objects": ["perfume bottles"]
    }
  }'
```

**Response:** `200 OK`

```json
{
  "status": "success",
  "item_id": "abc-123-def",
  "total_golden_count": 26
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Save status (always `"success"`) |
| `item_id` | string | ID of saved item |
| `total_golden_count` | integer | Total items with golden data |

**Output File:**

Golden entries are saved to `data/eval/golden_analyses.json` with version 1.0 schema.

**Error Response:** `500 Internal Server Error`

```json
{
  "detail": "Failed to save golden entry: <error message>"
}
```

---

### Get Golden Dataset Status

Get progress statistics for golden dataset curation.

**Endpoint:** `GET /golden-dataset/status`

**Example (curl):**

```bash
curl http://localhost:8000/golden-dataset/status
```

**Response:** `200 OK`

```json
{
  "total_items": 182,
  "reviewed_items": 26,
  "progress_percentage": 14.3
}
```

| Field | Type | Description |
|-------|------|-------------|
| `total_items` | integer | Total number of items in database |
| `reviewed_items` | integer | Number of items with golden data |
| `progress_percentage` | float | Percentage of items reviewed (0.0-100.0) |

**Error Response:** `500 Internal Server Error`

```json
{
  "detail": "Failed to get status: <error message>"
}
```

---

## Data Models

### Item

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (UUID) |
| `filename` | string | Stored filename |
| `original_filename` | string | Original uploaded filename |
| `file_size` | integer | File size in bytes |
| `mime_type` | string | MIME type |
| `created_at` | string | ISO 8601 timestamp |
| `updated_at` | string | ISO 8601 timestamp |
| `latest_analysis` | Analysis/null | Most recent analysis |

### Analysis

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (UUID) |
| `item_id` | string | Parent item ID |
| `version` | integer | Version number |
| `category` | string/null | Primary category (extracted from raw_response) |
| `summary` | string/null | Content summary (extracted from raw_response) |
| `raw_response` | object | Full LLM analysis response (see schema below) |
| `provider_used` | string/null | AI provider used (`"anthropic"` or `"openai"`) |
| `model_used` | string/null | AI model used |
| `trace_id` | string/null | Langfuse trace ID |
| `created_at` | string | ISO 8601 timestamp |

### raw_response Schema

The `raw_response` object contains the complete analysis from the LLM. The structure depends on the Langfuse prompt but typically includes:

| Field | Type | Description |
|-------|------|-------------|
| `category` | string | Primary category |
| `subcategories` | array[string] | 2-3 specific subcategories |
| `headline` | string | 140 character headline |
| `summary` | string | 2-3 sentence summary |
| `media_metadata` | object | Social media metadata (see below) |
| `image_details` | object | Detailed image analysis (see below) |

#### media_metadata

| Field | Type | Description |
|-------|------|-------------|
| `original_poster` | string | Username of original poster |
| `tagged_accounts` | array[string] | Tagged accounts |
| `location_tags` | array[string] | Location tags |
| `audio_source` | string | Audio/music source |
| `hashtags` | array[string] | Hashtags used |

#### image_details

| Field | Type | Description |
|-------|------|-------------|
| `extracted_text` | array[string] | Text extracted from image |
| `objects` | array[string] | Objects identified in image |
| `themes` | array[string] | Themes present in image |
| `emotions` | array[string] | Emotions conveyed |
| `vibes` | array[string] | Overall vibes/aesthetic |
| `likely_source` | string | Likely source platform |
| `key_interest` | string | Main point of interest |
| `visual_hierarchy` | array[string] | Visual elements in order of prominence |

### SearchRequest

Request model for search and Q&A endpoint.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | string | *required* | Natural language search query (min 3 characters) |
| `top_k` | integer | `10` | Number of results to return (1-50) |
| `category_filter` | string | `null` | Filter results by category |
| `include_answer` | boolean | `true` | Generate LLM answer from search results |
| `answer_model` | string | `null` | Model for answer generation (defaults to `claude-sonnet-4-5`) |

### SearchResult

Individual search result item.

| Field | Type | Description |
|-------|------|-------------|
| `item_id` | string | Unique identifier of the item |
| `rank` | integer | Rank position (1-based) |
| `score` | float | BM25 relevance score (lower/more negative = better match) |
| `category` | string/null | Primary category |
| `headline` | string/null | Item headline |
| `summary` | string/null | Item summary |
| `image_url` | string | URL to access the image file |
| `metadata` | object | Full raw_response analysis data |

### SearchResponse

Response model for search and Q&A endpoint.

| Field | Type | Description |
|-------|------|-------------|
| `query` | string | The search query that was executed |
| `results` | array[SearchResult] | List of search results ordered by relevance |
| `total_results` | integer | Total number of results returned |
| `answer` | string/null | AI-generated answer (null if `include_answer` is false) |
| `answer_confidence` | float/null | Confidence score 0-1 based on result relevance |
| `citations` | array[string]/null | List of item numbers cited in the answer |
| `retrieval_time_ms` | float | Time taken for search in milliseconds |
| `answer_time_ms` | float/null | Time taken for answer generation in milliseconds |

### GoldenAnalysisEntry

Curated golden dataset entry for model evaluation. Saved to `data/eval/golden_analyses.json`.

| Field | Type | Description |
|-------|------|-------------|
| `item_id` | string | Item UUID this golden data is for |
| `reviewed_at` | string | ISO 8601 timestamp of curation |
| `source_analyses_count` | integer | Number of analyses reviewed for curation |
| `source_analysis_ids` | array[string] | IDs of analyses used as sources |
| `category` | string | Curated primary category |
| `subcategories` | array[string] | Curated subcategories |
| `headline` | string | Curated headline (best/edited from analyses) |
| `summary` | string | Curated summary (best/edited from analyses) |
| `media_metadata` | object | Curated social media metadata (see below) |
| `image_details` | object | Curated image analysis details (see below) |

The `media_metadata` and `image_details` objects follow the same structure as the Analysis `raw_response` schema.

**File Structure:**

```json
{
  "metadata": {
    "version": "1.0",
    "created_at": "2025-12-13T00:00:00Z",
    "last_updated": "2025-12-13T12:00:00Z",
    "total_items": 50
  },
  "golden_analyses": [
    {
      "item_id": "...",
      "reviewed_at": "...",
      ...
    }
  ]
}
```

**Version:** 1.0

**Location:** `data/eval/golden_analyses.json`

### CompareRequest

Request model for comparing analysis values to calculate similarity.

| Field | Type | Description |
|-------|------|-------------|
| `item_id` | string | Item ID being compared |
| `field_type` | string | Field type: `"extracted_text"`, `"headline"`, or `"summary"` |
| `values` | array | List of values to compare (strings or arrays of strings) |

### CompareResponse

Response model for similarity comparison results.

| Field | Type | Description |
|-------|------|-------------|
| `similarity_matrix` | array[array[float]] | NxN matrix of pairwise similarity scores (0.0-1.0) |
| `highest_agreement` | object | Details about the value with highest average agreement |
| `method` | string | Similarity method used: `"levenshtein"` or `"tfidf"` |

### Categories

Categories are dynamic and determined by the LLM analysis. Common categories include:

| Category | Description |
|----------|-------------|
| `Travel` | Travel destinations, experiences |
| `Beauty` | Beauty, skincare, cosmetics |
| `Food` | Food, recipes, restaurants |
| `Fashion` | Clothing, style, accessories |
| `Technology` | Tech products, apps, software |
| `Entertainment` | Movies, music, shows |
| `Other` | Uncategorized content |

---

## Evaluation Tools

In addition to the API endpoints, this project includes command-line tools for creating evaluation datasets.

### Retrieval Test Set Creator

**Script:** `scripts/create_test_set.py`

An interactive CLI tool for creating test queries for evaluating search quality. This is separate from the Golden Dataset (which evaluates analysis quality).

**Purpose:**
- Create natural language queries for search evaluation
- Associate queries with ground truth items they should retrieve
- Build a test set for measuring retrieval metrics (precision, recall, etc.)

**Output File:** `data/eval/test_queries.json`

**Usage:**

```bash
python scripts/create_test_set.py
```

The script will:
1. Show you random items from your collection
2. Let you write natural language queries that should find those items
3. Automatically record the item IDs as ground truth
4. Save queries with metadata to test_queries.json

**Output Schema (version 1.0):**

```json
{
  "metadata": {
    "created_at": "2025-12-13T00:00:00Z",
    "total_queries": 25,
    "version": "1.0"
  },
  "queries": [
    {
      "id": "q001",
      "query": "Tokyo restaurants",
      "type": "location_search",
      "ground_truth_items": ["item-id-1", "item-id-2"],
      "expected_category": "Food",
      "min_expected_results": 2,
      "reference_answer": "Optional reference answer..."
    }
  ]
}
```

**Query Types:**
- `location_search`: Queries about specific locations
- `category_search`: Queries for categories/types of items
- `specific_question`: Question-style queries
- `object_content`: Queries about visual content
- `complex_multi_part`: Multi-faceted queries

**Comparison with Golden Dataset:**

| Feature | Retrieval Test Set | Golden Dataset |
|---------|-------------------|----------------|
| **Purpose** | Evaluate search quality | Evaluate analysis quality |
| **Input** | Natural language queries | Images with analyses |
| **Output** | Query → Item mappings | Item → Correct analysis |
| **Evaluation** | Retrieval metrics | Field accuracy |
| **Tool** | CLI script | Web UI |
| **File** | `test_queries.json` | `golden_analyses.json` |

For detailed information about the Golden Dataset Creator web tool, see `documentation/GOLDEN_DATASET.md`.
