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
