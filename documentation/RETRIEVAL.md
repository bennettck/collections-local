# Retrieval System Documentation

## Overview

This document describes the retrieval system for natural language Q&A over the Collections Local image collection. The system supports multiple search modes, all implemented using LangChain retrievers for consistency:

- **BM25 Full-Text Search (bm25-lc)**: Keyword-based retrieval using SQLite FTS5 with BM25 ranking
- **Vector Semantic Search (vector-lc)**: Embedding-based semantic retrieval using VoyageAI and sqlite-vec
- **Hybrid Search (hybrid-lc)**: Combines BM25 and vector search using Reciprocal Rank Fusion (RRF)

All retrievers use LangChain's retriever interface, providing a consistent API and enabling advanced features like hybrid search and ensemble retrieval. Users can search their collection using natural language queries and receive AI-generated answers with citations.

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────┐
│                     FastAPI Endpoint                     │
│                    POST /search                          │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              LangChain Retrievers Layer                  │
│    (BM25-LC, Vector-LC, Hybrid-LC with RRF)             │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│         Search Engines (SQLite FTS5 / sqlite-vec)        │
│           BM25 Ranking & Vector Similarity               │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              Search Results (Top-K Items)                │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│          LLM Answer Generator (Optional)                 │
│         Claude Sonnet 4.5 / GPT-4o                       │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│         Natural Language Answer + Citations             │
└─────────────────────────────────────────────────────────┘
```

### Key Technologies

- **LangChain**: Unified retriever interface for all search modes
- **SQLite FTS5**: Full-text search with built-in BM25 ranking
- **sqlite-vec**: Vector similarity search with VoyageAI embeddings
- **Reciprocal Rank Fusion (RRF)**: Hybrid search result merging
- **unicode61 Tokenizer**: Unicode-aware tokenization with diacritics removal
- **Claude Sonnet 4.5**: Default model for answer generation
- **FastAPI**: REST API endpoints

## Implementation Details

### 1. Search Index (`database.py`)

#### FTS5 Virtual Table

```sql
CREATE VIRTUAL TABLE items_fts USING fts5(
    item_id UNINDEXED,
    content,
    tokenize='unicode61 remove_diacritics 2'
);
```

**Key Features:**
- `item_id UNINDEXED`: Not searchable, used for joining
- `content`: Searchable weighted document
- `unicode61`: Unicode-aware tokenization
- `remove_diacritics 2`: Normalizes accented characters

#### Weighted Document Construction

The `_create_search_document()` function builds a composite document where fields are repeated by importance:

**Field Weights:**
- **3x**: `summary`
- **2x**: `headline`, `extracted_text`, `category`, `subcategories`, `key_interest`
- **1x**: `themes`, `objects`, `location_tags`, `emotions`, `vibes`, `hashtags`, minimal metadata fields

**Minimal Metadata Fields** (1x weight, combined):
- `original_poster`, `tagged_accounts`, `audio_source`, `likely_source`, `visual_hierarchy`

**Implementation:**
```python
# High priority: summary appears 3 times for 3x weight
parts.extend([summary] * 3)

# High priority: headline and extracted_text appear 2 times for 2x weight
parts.extend([headline, extracted_text] * 2)

# Medium-high priority: category, subcategories, key_interest appear 2 times for 2x weight
parts.extend([category, subcategories, key_interest])
parts.extend([category, subcategories, key_interest])

# Medium priority: themes, objects, location_tags, etc. appear 1 time for 1x weight
parts.extend([themes, objects, location_tags])

# Minimal priority fields are combined into a single string and added once
minimal_fields = f"{original_poster} {tagged_accounts} {audio_source} {likely_source} {visual_hierarchy}"
parts.append(minimal_fields)
```

This approach leverages BM25's term frequency component - fields appearing more often get higher relevance scores.

#### Query Preprocessing

Before executing the search, queries are preprocessed by the `_preprocess_query()` function:

**Preprocessing Steps:**
1. **Punctuation Removal**: Removes `?`, `!`, `.`, `,`, `;`, `:`, quotes, brackets
2. **Lowercasing**: Converts all text to lowercase for case-insensitive matching

**Example:**
```python
# Input query
"What restaurants are in Tokyo?"

# After preprocessing
"what restaurants are in tokyo"
```

**Benefits:**
- Case-insensitive search
- Cleaner query matching without punctuation noise
- Preserves all meaningful words including location prepositions (in, at, near)

#### Search Query

```sql
SELECT item_id, bm25(items_fts) as score
FROM items_fts
WHERE items_fts MATCH ?
ORDER BY score
LIMIT ?
```

**BM25 Score Interpretation:**
- Scores are negative (FTS5 convention)
- Lower (more negative) = better match
- Typical range: -1 to -10+
- Query is preprocessed to remove stopwords before matching

#### Relevance Score Filtering

The search system supports filtering out low-quality results using a `min_relevance_score` threshold. This is implemented in the `search_items()` function with two filtering checks:

**Implementation (`database.py`):**

```python
def search_items(query: str, top_k: int = 10, category_filter: Optional[str] = None,
                 min_relevance_score: float = -1.0) -> list[tuple[str, float]]:
    # ... execute search query ...

    results = [(row["item_id"], row["score"]) for row in rows]

    # Check 1: If no results or best match is weak, return empty list
    if not results or results[0][1] > min_relevance_score:
        return []

    # Check 2: Filter out weak tail results
    return [r for r in results if r[1] < min_relevance_score]
```

**Filtering Logic:**

1. **Early Return Check**: If the best (first) result has a score > `min_relevance_score`, all results are filtered out
   - This prevents returning results when even the best match is weak
   - Example: Best score is `-1.5`, threshold is `-5.0` → No results returned

2. **Tail Filtering**: Remove results from the tail that don't meet the threshold
   - Keeps only results with scores < `min_relevance_score` (more negative = stronger)
   - Example: Scores `[-5.99, -5.98, -1.5]` with threshold `-2.0` → Returns `[-5.99, -5.98]`

**Default Behavior:**

- Default threshold: `-1.0`
- Most real search results score more negatively than `-1.0`, so default effectively disables filtering
- This allows tuning based on evaluation results

**Usage Examples:**

```bash
# Default (no filtering) - most results pass
curl -X POST http://localhost:8000/search \
  -d '{"query": "perfume", "top_k": 10, "min_relevance_score": -1.0}'

# Strict filtering - only very strong matches
curl -X POST http://localhost:8000/search \
  -d '{"query": "perfume", "top_k": 10, "min_relevance_score": -5.0}'

# Moderate filtering - filter weak tail results
curl -X POST http://localhost:8000/search \
  -d '{"query": "perfume", "top_k": 10, "min_relevance_score": -2.0}'
```

**When to Adjust Threshold:**

- **Lower (more negative)**: To filter aggressively and only return high-confidence results
- **Higher (less negative)**: To be more permissive and return more results
- **Monitor**: Use evaluation metrics to tune optimal threshold for your dataset

## Vector Search System

### Overview

The vector search system provides semantic retrieval capabilities using embedding-based similarity matching. Unlike BM25 keyword search, vector search can match conceptually similar items even when exact keywords don't match.

**Key Components:**
- **VoyageAI Embeddings**: State-of-the-art text embeddings for semantic similarity
- **sqlite-vec Extension**: Efficient in-database vector search with KNN
- **Cosine Similarity**: Standard distance metric for text embeddings
- **Batch Processing**: Optimized embedding generation (up to 128 documents per API call)

### Embedding Generation (`embeddings.py`)

#### VoyageAI Integration

The system uses VoyageAI's embedding models for high-quality semantic representations.

**Configuration:**
```python
# Default model (configurable via VOYAGE_EMBEDDING_MODEL env var)
DEFAULT_EMBEDDING_MODEL = "voyage-3.5-lite"

# Available models and dimensions
EMBEDDING_DIMENSIONS = {
    "voyage-3.5-lite": 512,    # Default, optimized for speed
    "voyage-3.5": 1024,        # Higher quality, more compute
    "voyage-3-lite": 512,
    "voyage-3": 1024,
    "voyage-large-2": 1536,
    "voyage-2": 1024
}
```

**Default Model:** `voyage-3.5-lite` (512 dimensions)
- Fast embedding generation
- Good balance of quality and performance
- Optimal for large collections

**Alternative Model:** `voyage-3.5` (1024 dimensions)
- Higher quality embeddings
- Better semantic understanding
- 2x storage and compute cost

#### Core Functions

**1. generate_embedding(text, model)**

Generate embedding for a single document.

```python
def generate_embedding(
    text: str,
    model: str = DEFAULT_EMBEDDING_MODEL
) -> list[float]:
    """
    Generate embedding for text using VoyageAI.

    Args:
        text: Input text to embed
        model: VoyageAI model name (default: voyage-3.5-lite)

    Returns:
        List of floats representing the embedding vector (512 or 1024 dims)
    """
    result = voyage_client.embed(
        texts=[text],
        model=model,
        input_type="document",  # Optimized for indexing
        truncation=True  # Auto-truncate if exceeds context length
    )
    return result.embeddings[0]
```

**Features:**
- Automatic retry on rate limits (429) and transient errors (5xx)
- Exponential backoff built into client (max_retries=3)
- Auto-truncation for long documents (up to 32K tokens)
- Empty text validation

**2. generate_query_embedding(query, model)**

Generate embedding for search queries.

```python
def generate_query_embedding(
    query: str,
    model: str = DEFAULT_EMBEDDING_MODEL
) -> list[float]:
    """
    Generate embedding for search query using VoyageAI.

    Uses input_type="query" for optimal search performance.
    """
    result = voyage_client.embed(
        texts=[query],
        model=model,
        input_type="query",  # Optimized for search
        truncation=True
    )
    return result.embeddings[0]
```

**Key Difference:**
- `input_type="query"` vs `input_type="document"`
- Optimizes embedding space for query-document matching
- Essential for best retrieval performance

**3. generate_embeddings_batch(texts, model, batch_size)**

Generate embeddings for multiple documents efficiently.

```python
def generate_embeddings_batch(
    texts: list[str],
    model: str = DEFAULT_EMBEDDING_MODEL,
    batch_size: int = 128
) -> list[list[float]]:
    """
    Generate embeddings for multiple texts in batches.

    VoyageAI supports up to 128 documents per request.
    Processes texts in batches to minimize API calls.

    Token limits (per batch):
    - voyage-3.5-lite: 1M tokens
    - voyage-3.5: 320K tokens
    - Max 32K tokens per individual text
    """
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        result = voyage_client.embed(
            texts=batch,
            model=model,
            input_type="document",
            truncation=True
        )
        all_embeddings.extend(result.embeddings)

    return all_embeddings
```

**Benefits:**
- **Minimize API Calls**: 128 documents in 1 request vs 128 requests
- **Faster Processing**: Parallel embedding generation on server
- **Rate Limit Friendly**: Fewer requests = less likely to hit limits
- **Cost Effective**: Lower API overhead

**Usage Example:**
```python
# Index 500 documents
documents = [_create_embedding_document(analysis) for analysis in analyses]
embeddings = generate_embeddings_batch(documents, batch_size=128)
# Result: 4 API calls instead of 500
```

#### Weighted Document Construction

The `_create_embedding_document()` function mirrors the BM25 weighting strategy for consistency between search modes.

```python
def _create_embedding_document(analysis_data: dict) -> str:
    """
    Create weighted text document for embedding generation.
    Mirrors BM25 weighting strategy for consistency.
    """
    parts = []

    # Extract fields from analysis JSON
    summary = analysis_data.get("summary", "")
    headline = analysis_data.get("headline", "")
    category = analysis_data.get("category", "")
    subcategories = " ".join(analysis_data.get("subcategories", []))

    image_details = analysis_data.get("image_details", {})
    extracted_text = " ".join(image_details.get("extracted_text", []))
    key_interest = image_details.get("key_interest", "")
    themes = " ".join(image_details.get("themes", []))
    objects = " ".join(image_details.get("objects", []))

    # High priority (3x): summary appears 3 times
    parts.extend([summary] * 3)

    # High priority (2x): headline, extracted_text appear 2 times
    parts.extend([headline, extracted_text] * 2)

    # Medium-high priority (1.5x): category, subcategories, key_interest
    parts.extend([category, subcategories, key_interest])
    parts.append(f"{category} {subcategories} {key_interest}")

    # Medium priority (1x): themes, objects, location_tags
    parts.extend([themes, objects, location_tags])

    # Lower priority (0.5x): emotions, vibes, hashtags
    parts.append(f"{emotions} {vibes} {hashtags}")

    # Combine and clean
    document = " ".join([p for p in parts if p and p.strip()])
    return document
```

**Field Weighting Strategy:**

| Field | Weight | Reason |
|-------|--------|--------|
| summary | 3x | Most comprehensive description |
| headline, extracted_text | 2x | Primary content indicators |
| category, subcategories, key_interest | 1.5x | Important classification |
| themes, objects, location_tags | 1x | Supporting metadata |
| emotions, vibes, hashtags | 0.5x | Contextual signals |

**Why Mirror BM25 Weights?**
- Consistent search behavior across modes
- Users get similar results from both search types
- Easy to switch between keyword and semantic search
- Simpler mental model for debugging

### Vector Database Architecture

#### Tables Schema

**1. embeddings Table (Metadata)**

Stores embedding metadata and references.

```sql
CREATE TABLE IF NOT EXISTS embeddings (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    analysis_id TEXT NOT NULL,
    embedding_model TEXT NOT NULL,          -- e.g., "voyage-3.5-lite"
    embedding_dimensions INTEGER NOT NULL,   -- e.g., 512 or 1024
    embedding_source TEXT NOT NULL,          -- JSON: field weights used
    created_at TEXT NOT NULL,
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
    FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
)
```

**2. vec_items Virtual Table (Vector Storage)**

sqlite-vec virtual table for efficient similarity search.

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS vec_items USING vec0(
    item_id TEXT PRIMARY KEY,
    embedding float[512] distance_metric=cosine,
    category TEXT
)
```

**Key Features:**
- `vec0`: sqlite-vec extension virtual table
- `float[512]`: Vector dimensions (matches embedding model)
- `distance_metric=cosine`: Cosine distance for text similarity
- `category TEXT`: Metadata column for filtering (no JOIN needed)

**Why Two Tables?**

| Table | Purpose | Storage |
|-------|---------|---------|
| `embeddings` | Metadata, versioning, lineage | Regular SQLite table |
| `vec_items` | Fast vector search, KNN | Virtual table (sqlite-vec) |

**Benefits:**
- `embeddings`: Track which model, when generated, what fields used
- `vec_items`: Optimized vector operations, metadata filtering
- Separation allows metadata updates without re-indexing vectors

#### Distance Metric: Cosine Similarity

**Cosine Distance Formula:**
```
distance = 1 - cosine_similarity
```

**Score Interpretation:**
- `distance = 0.0` → Perfect match (cosine_similarity = 1.0)
- `distance = 1.0` → Orthogonal vectors (cosine_similarity = 0.0)
- `distance = 2.0` → Opposite vectors (cosine_similarity = -1.0)

**Converted to Similarity Score (in API):**
```python
similarity = 1.0 - distance
```

**Final Score Range (0-1):**
- `1.0` = Perfect semantic match
- `0.5` = Somewhat related
- `0.0` = Unrelated or opposite

**Why Cosine for Text?**
- Angle-based similarity (ignores magnitude)
- Standard for text embeddings
- Handles variable document lengths
- Normalized embeddings make it equivalent to dot product

### Vector Search Implementation

#### Function: vector_search_items()

Search items using vector similarity with optional metadata filtering.

**Implementation (`database.py`):**

```python
def vector_search_items(
    query_embedding: list[float],
    top_k: int = 10,
    category_filter: Optional[str] = None,
    min_similarity_score: float = 0.0
) -> list[tuple[str, float]]:
    """
    Search items using vector similarity.

    Uses sqlite-vec's KNN search with metadata filtering for optimal performance.
    Returns list of (item_id, similarity_score) tuples.

    Note: sqlite-vec with cosine distance returns distance values where:
    - distance = 1 - cosine_similarity
    - Lower distance = higher similarity
    - We convert to similarity score (0-1) where 1 is most similar

    Args:
        query_embedding: Query vector (must match table dimensions)
        top_k: Number of results to return
        category_filter: Optional category to filter by (uses metadata column)
        min_similarity_score: Minimum similarity threshold (0-1)

    Returns:
        List of (item_id, similarity_score) tuples sorted by similarity (descending)
    """
    with get_db() as conn:
        # Serialize query embedding for sqlite-vec
        serialized_query = sqlite_vec.serialize_float32(query_embedding)

        # Build query with metadata filtering (no JOIN needed)
        if category_filter:
            query = """
                SELECT
                    item_id,
                    distance
                FROM vec_items
                WHERE embedding MATCH ?
                  AND k = ?
                  AND category = ?
            """
            rows = conn.execute(query, (serialized_query, top_k, category_filter)).fetchall()
        else:
            query = """
                SELECT
                    item_id,
                    distance
                FROM vec_items
                WHERE embedding MATCH ?
                  AND k = ?
            """
            rows = conn.execute(query, (serialized_query, top_k)).fetchall()

        # Convert distance to similarity and filter by threshold
        # For cosine distance: similarity = 1 - distance
        results = []
        for row in rows:
            item_id = row["item_id"]
            distance = row["distance"]
            similarity = 1.0 - distance

            if similarity >= min_similarity_score:
                results.append((item_id, similarity))

    return results
```

#### Key Features

**1. KNN Search via MATCH Operator**

```sql
WHERE embedding MATCH ? AND k = ?
```

- `MATCH`: Triggers KNN search in sqlite-vec
- `k`: Number of nearest neighbors to return
- Fast approximate nearest neighbor search

**2. Metadata Filtering (No JOIN)**

```sql
WHERE embedding MATCH ? AND k = ? AND category = ?
```

- Filter by category directly in vec_items table
- No JOIN with items table needed
- Faster than post-filtering

**3. Score Conversion**

```python
similarity = 1.0 - distance
```

- Converts distance (lower=better) to similarity (higher=better)
- Intuitive 0-1 range matching user expectations
- Consistent with other similarity metrics

**4. Threshold Filtering**

```python
if similarity >= min_similarity_score:
    results.append((item_id, similarity))
```

- Filter out low-quality matches
- Configurable per-query
- Default: 0.0 (no filtering)

#### Performance Characteristics

**Typical Query Times:**
- Simple query: 10-50ms
- With category filter: 15-60ms
- Complex query: 20-100ms

**Factors Affecting Speed:**
- Vector dimensions (512 vs 1024)
- Database size (scales logarithmically with KNN)
- top_k parameter (more neighbors = slower)
- Category filter (slight overhead)

**Comparison to BM25:**
- BM25: 1-10ms (faster for keyword match)
- Vector: 10-100ms (slower but semantic understanding)
- Trade-off: Speed vs semantic quality

**Memory Usage:**
- 512 dims: ~2KB per vector
- 1024 dims: ~4KB per vector
- 10,000 items with 512 dims: ~20MB

### BM25 vs Vector Search Comparison

#### When to Use Each Search Type

| Use Case | Recommended Search | Reason |
|----------|-------------------|--------|
| Exact keyword match (e.g., "Tokyo") | **BM25** | Faster, exact term matching |
| Concept search (e.g., "Japanese capital") | **Vector** | Semantic understanding |
| Multi-word phrases | **BM25** | Better term co-occurrence |
| Synonym matching | **Vector** | Embeddings capture synonyms |
| Ambiguous queries | **Vector** | Context-aware matching |
| Category + keyword | **BM25** | Faster with category filter |
| Exploratory search | **Vector** | Discovers related content |
| Precise product lookup | **BM25** | Exact name/SKU matching |

#### Score Comparison

**BM25 Scores:**
- **Range**: Negative values (FTS5 convention)
- **Better**: More negative (e.g., -8.5 > -2.3)
- **Typical**: -1 to -10+
- **Interpretation**: Keyword relevance based on term frequency and IDF

**Vector Scores:**
- **Range**: 0.0 to 1.0 (similarity)
- **Better**: Higher values (e.g., 0.85 > 0.42)
- **Typical**: 0.3 to 0.9 for good matches
- **Interpretation**: Semantic similarity based on embedding distance

#### Score Interpretation Guide

**Vector Similarity Ranges:**

| Score Range | Quality | Example Query-Item Match |
|-------------|---------|--------------------------|
| **0.9 - 1.0** | Excellent | "Tokyo restaurants" → "Dining spots in Tokyo" |
| **0.7 - 0.9** | Very Good | "Japanese food" → "Sushi and ramen in Tokyo" |
| **0.5 - 0.7** | Good | "Asian cuisine" → "Tokyo restaurant" |
| **0.3 - 0.5** | Fair | "Food photography" → "Tokyo restaurant" |
| **0.0 - 0.3** | Poor | "Beauty products" → "Tokyo restaurant" |

**BM25 Score Ranges:**

| Score Range | Quality | Example Query-Item Match |
|-------------|---------|--------------------------|
| **-8 to -10+** | Excellent | "Tokyo restaurant" → "Tokyo restaurant dining" |
| **-5 to -8** | Very Good | "Tokyo" → "Tokyo restaurant" |
| **-3 to -5** | Good | "restaurant" → "Tokyo restaurant" |
| **-1 to -3** | Fair | "food" → "Tokyo restaurant" |
| **0 to -1** | Poor | "image" → "Tokyo restaurant" |

#### Use Case Examples

**Example 1: Exact Product Search**

```bash
# Query: "Chanel No. 5 perfume"

# BM25: BETTER (exact keyword matching)
# Scores: [-9.2, -8.5, -7.1]
# Finds items with exact "Chanel No. 5" mentions

# Vector: GOOD (semantic understanding)
# Scores: [0.88, 0.82, 0.75]
# Finds similar perfumes, might include related items
```

**Recommendation:** Use BM25 for exact product lookups

**Example 2: Conceptual Search**

```bash
# Query: "places to eat in Japan's capital"

# BM25: POOR (no keyword "Tokyo")
# Scores: [-2.1, -1.8]
# Might miss relevant items without "capital" keyword

# Vector: EXCELLENT (understands "Japan's capital" = "Tokyo")
# Scores: [0.85, 0.79, 0.72]
# Finds Tokyo restaurants through semantic understanding
```

**Recommendation:** Use Vector for conceptual/synonym queries

**Example 3: Category + Keyword**

```bash
# Query: "lipstick" + category_filter: "Beauty"

# BM25: FASTER (10ms with category filter)
# Scores: [-6.2, -5.8, -5.1]

# Vector: SLOWER (50ms with category filter)
# Scores: [0.82, 0.78, 0.71]
```

**Recommendation:** Use BM25 when category filtering is primary

### 2. Answer Generation (`retrieval/answer_generator.py`)

#### Prompt Template

```python
You are answering questions about a personal image collection.

User Question: {query}

Retrieved Items from Collection:
{formatted_results}

Provide a natural, conversational answer to the user's question based on the retrieved items above.

Guidelines:
- Be specific and cite details from the results
- Reference items using [Item X] notation when mentioning specific items
- If multiple items are relevant, summarize the key themes or patterns
- If the results don't fully answer the question, acknowledge the limitations
- Keep responses concise but informative (2-4 sentences for simple queries, more for complex)
- Focus on answering the specific question asked
```

#### Result Formatting

Each search result is formatted with relevance score for the LLM:

```
Item 1 (Relevance Score: 4.64):
Category: Food
Title: Tofuya Ukai dining spot beneath Tokyo Tower
Description: Beautiful traditional Japanese restaurant...
---
```

#### Citation Extraction

The system automatically extracts citations from the answer:

```python
pattern = r'\[Item (\d+)\]'
matches = re.findall(pattern, answer)
```

Citations link back to specific search results for transparency.

#### Confidence Score

The `answer_confidence` value (0.0-1.0) indicates how well the retrieved results match the query, based on BM25 relevance scores.

**Calculation Process:**

```python
# Step 1: Get absolute values of BM25 scores
# BM25 scores are negative; more negative = better match
# Example scores: [-4.64, -3.73]
avg_score = sum(abs(r['score']) for r in results) / len(results)
# Example: (4.64 + 3.73) / 2 = 4.185

# Step 2: Normalize to 0-1 range (divide by typical max of 10)
confidence = min(1.0, avg_score / 10.0) if avg_score > 0 else 0.5
# Example: 4.185 / 10.0 = 0.42 (42% confidence)
```

**Confidence Interpretation:**

| Confidence Range | Meaning | Typical BM25 Scores | Query Match Quality |
|-----------------|---------|---------------------|---------------------|
| **0.8 - 1.0** | Very High | -8 to -10+ | Exact keyword matches, highly relevant results |
| **0.5 - 0.8** | High | -5 to -8 | Strong matches, good topic alignment |
| **0.3 - 0.5** | Medium | -3 to -5 | Decent matches, partial relevance |
| **0.1 - 0.3** | Low | -1 to -3 | Weak matches, tangential results |
| **0.0 - 0.1** | Very Low | 0 to -1 | Poor matches, irrelevant results |

**Example from Real Query:**

```bash
curl -X POST http://localhost:8000/search \
  -d '{"query": "Tokyo restaurants"}'
```

Results:
- Item 1: score = `-4.64` (good match)
- Item 2: score = `-3.73` (good match)

Calculation:
```
avg_score = (4.64 + 3.73) / 2 = 4.185
confidence = 4.185 / 10.0 = 0.42 (42%)
```

**Use Cases:**

- **High Confidence (>0.7)**: Results are highly relevant; LLM answer likely accurate
- **Medium Confidence (0.3-0.7)**: Results partially relevant; answer may have caveats
- **Low Confidence (<0.3)**: Poor matches; LLM should acknowledge limitations

**What Affects Confidence:**

✅ **Increases Confidence:**
- Exact keyword matches in high-weight fields (summary, headline, category)
- Multiple query terms matching after preprocessing
- Terms appearing frequently in documents
- Specific, descriptive queries (e.g., "Tokyo restaurants")

❌ **Decreases Confidence:**
- Vague or generic queries (e.g., "photo", "image")
- Missing key terms or very short queries
- Only matching low-weight metadata fields
- Queries with very common words that appear in many documents
- Single-term queries

### 3. API Endpoints (`main.py`)

#### POST /search

Search the collection using BM25 or vector search.

**Request:**
```json
{
  "query": "Tokyo restaurants",
  "search_type": "bm25-lc",
  "top_k": 10,
  "category_filter": null,
  "min_relevance_score": -1.0,
  "min_similarity_score": 0.0,
  "include_answer": true,
  "answer_model": null
}
```

**Request Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | required | Natural language search query |
| `search_type` | string | `"bm25-lc"` | Search type: `"bm25-lc"`, `"vector-lc"`, or `"hybrid-lc"` |
| `top_k` | integer | `10` | Number of results to return (1-50) |
| `category_filter` | string | `null` | Filter by category (e.g., "Food", "Beauty") |
| `min_relevance_score` | float | `-1.0` | BM25 minimum score threshold (more negative = stricter) |
| `min_similarity_score` | float | `0.0` | Vector minimum similarity threshold (0-1, higher = stricter) |
| `include_answer` | boolean | `true` | Generate AI answer from results |
| `answer_model` | string | `null` | LLM model for answer (default: Claude Sonnet 4.5) |

**Response:**
```json
{
  "query": "Tokyo restaurants",
  "search_type": "bm25-lc",
  "results": [...],
  "total_results": 2,
  "answer": "Based on your collection...",
  "answer_confidence": 0.42,
  "citations": ["1", "2"],
  "retrieval_time_ms": 1.71,
  "answer_time_ms": 4717.53
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `query` | string | Original query |
| `search_type` | string | Search type used (`"bm25-lc"`, `"vector-lc"`, or `"hybrid-lc"`) |
| `results` | array | Search results with metadata |
| `total_results` | integer | Number of results returned |
| `answer` | string | AI-generated answer (if `include_answer=true`) |
| `answer_confidence` | float | Confidence score (0-1) |
| `citations` | array | Cited item IDs from answer |
| `retrieval_time_ms` | float | Search execution time |
| `answer_time_ms` | float | LLM answer generation time |

#### POST /index/rebuild

Rebuilds the FTS5 index from current database analyses.

**Process:**
1. Deletes existing FTS data
2. Queries all items with latest analysis
3. Builds weighted document for each item
4. Inserts into `items_fts` table

**Returns:**
```json
{
  "status": "success",
  "num_documents": 130,
  "build_time_seconds": 0.08,
  "timestamp": "2025-12-13T00:22:30.219287"
}
```

#### GET /index/status

Returns index health metrics:

```json
{
  "doc_count": 130,
  "total_items": 182,
  "is_loaded": true,
  "index_coverage": 0.71
}
```

**Index Coverage** = `doc_count / total_items`
- Items without analysis aren't indexed
- Coverage < 1.0 indicates unanalyzed items

#### POST /vector-index/rebuild

Rebuild the vector search index by generating embeddings for all analyzed items.

**Process:**
1. Finds items with analyses but no embeddings
2. Creates weighted documents (mirrors BM25 strategy)
3. Generates embeddings in batches (up to 128 per API call)
4. Stores embeddings in `embeddings` and `vec_items` tables

**Request:**
```bash
curl -X POST http://localhost:8000/vector-index/rebuild
```

**Returns:**
```json
{
  "embedded_count": 125,
  "skipped_count": 5,
  "total_processed": 130
}
```

**Response Fields:**

| Field | Description |
|-------|-------------|
| `embedded_count` | Number of items successfully embedded |
| `skipped_count` | Number of items skipped (empty documents, errors) |
| `total_processed` | Total items processed |

**Notes:**
- Uses `voyage-3.5-lite` model by default (512 dimensions)
- Batch processing minimizes API calls (128 docs/request)
- Built-in retry logic for rate limits and transient errors
- Only embeds items without existing embeddings (incremental)

**Performance:**
- 100 items: ~30-60 seconds (depends on batch size, API latency)
- 500 items: ~2-4 minutes
- 1000 items: ~4-8 minutes

#### GET /vector-index/status

Get statistics about the vector search index.

**Request:**
```bash
curl http://localhost:8000/vector-index/status
```

**Returns:**
```json
{
  "total_analyzed_items": 130,
  "total_embeddings": 125,
  "total_vectors": 125,
  "coverage": 96.15
}
```

**Response Fields:**

| Field | Description |
|-------|-------------|
| `total_analyzed_items` | Number of items with analyses |
| `total_embeddings` | Number of embedding records in `embeddings` table |
| `total_vectors` | Number of vectors in `vec_items` table |
| `coverage` | Percentage of analyzed items with embeddings |

**Coverage Calculation:**
```
coverage = (total_embeddings / total_analyzed_items) * 100
```

**Interpreting Coverage:**
- **100%**: All analyzed items are indexed for vector search
- **<100%**: Some items need embeddings (run `/vector-index/rebuild`)
- **0%**: No embeddings generated yet (must rebuild index)

## Performance Characteristics

### Retrieval Speed

**Typical Query Times:**
- Simple query: 1-5ms
- With category filter: 2-8ms
- Complex multi-term query: 3-10ms

**Factors Affecting Speed:**
- Query complexity (number of terms)
- Result set size (top_k parameter)
- Database size (scales logarithmically)
- Category filter (adds JOIN)

### Answer Generation Speed

**Typical Times:**
- Claude Sonnet 4.5: 4-6 seconds
- GPT-4o: 3-5 seconds
- OpenAI Reasoning models (o1, o3): 8-15 seconds (longer due to extended reasoning)
- Depends on: result set size, answer length, API latency, model type

**Token Limits:**
- Standard models (Claude, GPT-4o): 1024 max tokens
- OpenAI Reasoning models: 4000 max completion tokens (includes reasoning trace)

### Index Build Performance

**Benchmark (130 documents):**
- Build time: ~80ms
- Per-document: ~0.6ms

**Scales linearly** with document count.

## Query Examples

### Simple Keyword Search

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Tokyo", "search_type": "bm25-lc", "top_k": 5, "include_answer": false}'
```

**Matches:**
- Items with "Tokyo" in any field
- Weighted by field importance
- Fast (no LLM call)

### Natural Language Question

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "What restaurants are in my collection?", "search_type": "bm25-lc", "include_answer": true}'
```

**Query Processing:**
- Input: "What restaurants are in my collection?"
- Preprocessed: "restaurants collection" (stopwords removed)
- Searches for items with these terms

**Returns:**
- Relevant restaurant items
- AI-generated answer summarizing results
- Citations to specific items

### Category-Filtered Search

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "perfume", "search_type": "bm25-lc", "category_filter": "Beauty", "top_k": 10}'
```

**Benefits:**
- Narrows results to specific category
- Improves precision for ambiguous terms
- Slightly slower (JOIN operation)

### Multi-Term Query

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Japanese food Tokyo shopping", "search_type": "bm25-lc", "top_k": 10}'
```

**Behavior:**
- BM25 ranks by relevance across all terms
- Items matching more terms rank higher
- Term proximity doesn't affect ranking (bag-of-words)

### Relevance Score Filtering

```bash
# Default behavior - no filtering
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "perfume", "search_type": "bm25-lc", "top_k": 10, "min_relevance_score": -1.0}'

# Strict filtering - only very strong matches (scores < -5.0)
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "perfume", "search_type": "bm25-lc", "top_k": 10, "min_relevance_score": -5.0}'

# Moderate filtering - filter weak tail results (scores < -2.0)
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "perfume", "search_type": "bm25-lc", "top_k": 10, "min_relevance_score": -2.0}'
```

**Use Cases:**
- **Precision over Recall**: Use strict thresholds to only return high-confidence results
- **Quality Control**: Filter out tangentially related items
- **Tuning**: Adjust based on evaluation metrics to find optimal threshold

### Vector Search Examples

#### Simple Semantic Search

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Japanese capital", "search_type": "vector-lc", "top_k": 5}'
```

**Behavior:**
- Generates query embedding for "Japanese capital"
- Finds semantically similar items
- Matches "Tokyo" items even without keyword "capital"
- Returns similarity scores (0-1 range)

**When to use:**
- Conceptual queries without exact keywords
- Synonym matching ("car" → "automobile")
- Paraphrased searches

#### Vector Search with Category Filter

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "cosmetics", "search_type": "vector-lc", "category_filter": "Beauty", "top_k": 10}'
```

**Benefits:**
- Combines semantic search with category precision
- Finds beauty items semantically related to "cosmetics"
- Faster than post-filtering results

#### Vector Search with Similarity Threshold

```bash
# Only return high-quality semantic matches
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "perfume", "search_type": "vector-lc", "min_similarity_score": 0.7, "top_k": 10}'
```

**Filtering:**
- `min_similarity_score`: 0.0-1.0 (higher = stricter)
- 0.7 threshold: Only returns very similar items
- Useful for high-precision requirements

**Comparison with BM25 threshold:**
```bash
# BM25 threshold (more negative = stricter)
curl -X POST http://localhost:8000/search \
  -d '{"query": "perfume", "search_type": "bm25-lc", "min_relevance_score": -5.0}'

# Vector threshold (higher = stricter)
curl -X POST http://localhost:8000/search \
  -d '{"query": "perfume", "search_type": "vector-lc", "min_similarity_score": 0.7}'
```

#### Exploratory Search

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "outdoor activities", "search_type": "vector-lc", "top_k": 20}'
```

**Use case:**
- Discover related content
- Broad conceptual queries
- Finding items you didn't know you had
- Higher top_k for exploration (10-20)

**Example results:**
- Hiking photos
- Beach scenes
- Sports activities
- Nature photography
- Adventure travel

#### Comparing BM25 vs Vector Search

```bash
# BM25 search
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "ramen noodles", "search_type": "bm25-lc", "include_answer": false}'

# Vector search (same query)
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "ramen noodles", "search_type": "vector-lc", "include_answer": false}'
```

**Expected differences:**
- **BM25**: Exact matches for "ramen" or "noodles" keywords
- **Vector**: May include related items (soup, Japanese food, dining)
- **BM25 scores**: Negative values (e.g., -6.2, -5.1)
- **Vector scores**: 0-1 range (e.g., 0.82, 0.76)

**When BM25 wins:**
- Query: "Chanel No. 5"
- BM25 finds exact product mentions
- Vector may return similar perfumes

**When Vector wins:**
- Query: "France's most famous perfume"
- Vector understands concept → finds Chanel
- BM25 misses without keyword match

## Limitations

### Current Limitations

**BM25-Specific Limitations** (Use Vector Search to Address)

1. **No Semantic Understanding (BM25 only)**
   - BM25 is keyword-based only
   - Doesn't understand synonyms or paraphrases
   - Example: "Tokyo" won't match "Japan's capital" in BM25
   - **Solution**: Use `search_type="vector-lc"` for semantic queries

2. **No Stopword Filtering (BM25)**
   - All words preserved in BM25 queries (including "a", "the", "in", etc.)
   - May match common words that don't add search value
   - BM25 naturally downweights frequently occurring terms
   - **Solution**: Use specific, descriptive terms or switch to vector search

3. **Bag-of-Words (BM25)**
   - No phrase matching capability
   - Word order doesn't matter
   - "Tokyo restaurants" ≈ "restaurants Tokyo"
   - Can't distinguish "New York" from "New" and "York" separately
   - **Solution**: Vector embeddings capture some phrase semantics

**Vector Search Limitations**

4. **Slower Than BM25**
   - Vector search: 10-100ms typical
   - BM25 search: 1-10ms typical
   - Trade-off: Speed vs semantic understanding
   - **Solution**: Use BM25 for simple keyword queries

5. **Requires Embedding Generation**
   - Must call `/vector-index/rebuild` before first use
   - New analyses need re-indexing
   - API costs for embedding generation
   - **Solution**: Batch processing minimizes API calls (128 docs/request)

6. **Less Precise for Exact Matches**
   - Vector search may return semantically similar but wrong items
   - Example: "Chanel No. 5" might match other perfumes
   - Better for concepts than exact product names
   - **Solution**: Use BM25 for exact keyword/product lookups

**System-Wide Limitations**

7. **Index Staleness**
   - Neither BM25 nor vector indexes auto-update after new analyses
   - Must manually rebuild indexes
   - **Workaround**: Call `/index/rebuild` and `/vector-index/rebuild` after bulk analysis

8. **No Multi-Modal Search**
   - Text-only search for all modes
   - Can't search by image similarity or visual features
   - Would require vision embeddings (CLIP, etc.)
   - **Future**: Could add image vector search

### Addressing Limitations

**Available Now:**
- **Semantic Search**: Use `search_type="vector-lc"` for conceptual queries
- **Keyword Search**: Use `search_type="bm25-lc"` for exact matches
- **Hybrid Search**: Use `search_type="hybrid-lc"` to combine BM25 and vector search using Reciprocal Rank Fusion (RRF)
- **LangChain Integration**: All retrievers use LangChain for consistent interface and advanced features

**Future Enhancements:**

1. **Enhanced Hybrid Search**
   - Re-rank with cross-encoder for even better results
   - Automatic search type selection based on query
   - Configurable fusion weights and strategies

2. **Smarter Query Preprocessing**
   - Optional stopword removal for very long queries
   - Query expansion with synonyms
   - LLM-based query reformulation
   - Phrase detection and boosting

3. **Automatic Index Updates**
   - Database triggers on analysis insert/update
   - Background index refresh daemon
   - Real-time updates without manual rebuild
   - Incremental embedding generation

4. **Phrase Matching Improvements**
   - Support for quoted phrase queries
   - FTS5 NEAR operator for proximity search
   - Better handling of multi-word entities
   - Phrase-aware vector embeddings

5. **Multi-Modal Search**
   - Image similarity search using vision embeddings
   - Combine text + image queries
   - Visual feature filtering
   - Cross-modal retrieval (text query → image results)

6. **Conversational Search**
   - Multi-turn Q&A with context retention
   - Clarifying questions when results are ambiguous
   - Follow-up query support
   - Session-based query refinement

## Testing

### Manual Testing

**BM25 Search Testing:**

```bash
# 1. Check BM25 index status
curl http://localhost:8000/index/status

# 2. Rebuild BM25 index if needed
curl -X POST http://localhost:8000/index/rebuild

# 3. Test BM25 search without answer
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "search_type": "bm25-lc", "include_answer": false}'

# 4. Test BM25 search with answer
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "search_type": "bm25-lc", "include_answer": true}'
```

**Vector Search Testing:**

```bash
# 1. Check vector index status
curl http://localhost:8000/vector-index/status

# 2. Rebuild vector index if needed (generates embeddings)
curl -X POST http://localhost:8000/vector-index/rebuild

# 3. Test vector search without answer
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "search_type": "vector-lc", "include_answer": false}'

# 4. Test vector search with answer
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "search_type": "vector-lc", "include_answer": true}'

# 5. Test semantic query (should find conceptually similar items)
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Japanese capital", "search_type": "vector-lc", "top_k": 5}'
```

**Hybrid Search Testing:**

```bash
# Test hybrid search combining BM25 and vector
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Japanese capital", "search_type": "hybrid-lc", "top_k": 5}'
```

**Compare All Search Types:**

```bash
# Run same query with all search types
QUERY="ramen noodles"

# BM25 results
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"$QUERY\", \"search_type\": \"bm25-lc\", \"include_answer\": false}" \
  | jq '.results[] | {rank, score, headline}'

# Vector results
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"$QUERY\", \"search_type\": \"vector-lc\", \"include_answer\": false}" \
  | jq '.results[] | {rank, score, headline}'

# Hybrid results
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"$QUERY\", \"search_type\": \"hybrid-lc\", \"include_answer\": false}" \
  | jq '.results[] | {rank, score, headline}'
```

### Evaluation Framework

**Planned (not yet implemented):**

1. **Test Query Set** (`data/eval/test_queries.json`)
   - 30-50 queries with ground truth
   - Covering various query types
   - Manual curation

2. **Retrieval Metrics** (`evaluation/metrics.py`)
   - Precision@K, Recall@K
   - Mean Reciprocal Rank (MRR)
   - Normalized DCG (NDCG)

3. **Answer Quality Metrics**
   - LLM-as-judge evaluation
   - ROUGE scores vs ground truth
   - Citation accuracy

4. **Coverage Metrics**
   - % queries returning results
   - Average results per query
   - Zero-result analysis

## Troubleshooting

### Search Returns No Results

**Possible causes:**
1. Index not built - check `/index/status`
2. Query too specific - try broader terms
3. No analyzed items - analyze images first
4. Typo in query - check spelling
5. Query terms don't match indexed content
6. `min_relevance_score` threshold too strict - results filtered out

**Solutions:**
```bash
# Check index
curl http://localhost:8000/index/status

# Rebuild index
curl -X POST http://localhost:8000/index/rebuild

# Try simpler query
curl -X POST http://localhost:8000/search \
  -d '{"query": "tokyo", "search_type": "bm25-lc", "include_answer": false}'

# Disable relevance filtering to see all results
curl -X POST http://localhost:8000/search \
  -d '{"query": "tokyo", "search_type": "bm25-lc", "min_relevance_score": 0.0, "include_answer": false}'

# Use specific, descriptive terms
# Good: "tokyo restaurants"
# Good: "digital art fukuoka"
# Good: "perfume shopping japan"
```

**Query Preprocessing Note:**
Queries are lowercased and punctuation is removed. All words are preserved for matching.
- "What restaurants are in Tokyo?" → "what restaurants are in tokyo"
- Use specific nouns and descriptive terms for best results

### Too Few Results Returned

**Possible cause:**
`min_relevance_score` threshold filtering out valid results

**Diagnosis:**
```bash
# Check what scores results are getting
curl -X POST http://localhost:8000/search \
  -d '{"query": "your query", "min_relevance_score": 0.0, "include_answer": false}' \
  | jq '.results[] | {rank, score}'
```

**Solutions:**
- **Relax threshold**: Increase `min_relevance_score` to be less strict (e.g., from `-5.0` to `-2.0`)
- **Disable filtering**: Set to `0.0` to see all results
- **Review scores**: Examine actual BM25 scores to determine appropriate threshold

**Example:**
```bash
# Too strict - filters out good results
curl -X POST http://localhost:8000/search \
  -d '{"query": "perfume", "search_type": "bm25-lc", "min_relevance_score": -10.0}'  # Returns 0

# More permissive - allows decent matches
curl -X POST http://localhost:8000/search \
  -d '{"query": "perfume", "search_type": "bm25-lc", "min_relevance_score": -2.0}'   # Returns 3
```

### Low Relevance Scores

**Possible causes:**
1. Mismatch between query and content
2. Important terms not in high-weight fields
3. Need query expansion

**Solutions:**
- Try different query terms
- Check what fields contain relevant info
- Consider adding synonyms (future)

### Slow Answer Generation

**Expected behavior:**
- Answer generation takes 4-6 seconds
- This is normal for LLM API calls

**If slower than 10 seconds:**
- Check API key configuration
- Verify network connection
- Try different model (e.g., GPT-4o)

### Index Coverage Low

**Check analysis coverage:**
```bash
curl http://localhost:8000/index/status
```

**If `index_coverage < 1.0`:**
- Some items haven't been analyzed
- Analyze remaining items
- Index will auto-update on next rebuild

### Vector Search Returns No Results

**Possible causes:**
1. Vector index not built - check `/vector-index/status`
2. No embeddings generated yet
3. `VOYAGE_API_KEY` not configured
4. `min_similarity_score` threshold too strict
5. Query embedding generation failed

**Solutions:**
```bash
# 1. Check vector index status
curl http://localhost:8000/vector-index/status

# 2. Rebuild vector index (generates embeddings)
curl -X POST http://localhost:8000/vector-index/rebuild

# 3. Test with simple query
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "search_type": "vector-lc", "include_answer": false}'

# 4. Disable similarity filtering
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "search_type": "vector-lc", "min_similarity_score": 0.0}'

# 5. Check environment variables
echo $VOYAGE_API_KEY  # Should not be empty
```

**Common errors:**
- `"VOYAGE_API_KEY environment variable not set"` → Add API key to `.env`
- `coverage: 0` in `/vector-index/status` → Run `/vector-index/rebuild`
- Empty results with BM25 working → Vector index needs building

### Vector Search Slower Than Expected

**Expected performance:**
- Vector search: 10-100ms (typical 20-50ms)
- BM25 search: 1-10ms (faster)

**If consistently > 100ms:**

**Possible causes:**
1. Large database (>10,000 items)
2. High `top_k` parameter (>50)
3. 1024-dimensional embeddings (slower than 512)
4. Category filter with many items

**Solutions:**
```bash
# Use lower top_k for faster results
curl -X POST http://localhost:8000/search \
  -d '{"query": "test", "search_type": "vector-lc", "top_k": 5}'

# Consider switching to voyage-3.5-lite (512 dims)
export VOYAGE_EMBEDDING_MODEL=voyage-3.5-lite
```

**Performance tuning:**
- Reduce `top_k` from 10 to 5 (faster)
- Use category filter to narrow search space
- Use BM25 for simple keyword queries
- Monitor retrieval_time_ms in API responses

### Vector Search Results Not Semantic Enough

**Symptoms:**
- Results similar to BM25 (keyword-based)
- Missing conceptually related items
- Synonyms not matched

**Possible causes:**
1. Query too short (single word)
2. Items have sparse metadata
3. Embedding model mismatch

**Solutions:**

```bash
# Use longer, more descriptive queries
# Bad:  "food"
# Good: "Japanese cuisine and dining experiences"

curl -X POST http://localhost:8000/search \
  -d '{"query": "Japanese cuisine and dining experiences", "search_type": "vector-lc"}'

# Compare with BM25 to verify semantic difference
curl -X POST http://localhost:8000/search \
  -d '{"query": "Japanese capital", "search_type": "bm25-lc"}' | jq '.total_results'
# Should return fewer results

curl -X POST http://localhost:8000/search \
  -d '{"query": "Japanese capital", "search_type": "vector-lc"}' | jq '.total_results'
# Should find "Tokyo" items even without keyword
```

**Best practices:**
- Use 3+ word queries for better semantic matching
- Include context in queries ("perfume from France" vs "perfume")
- Test both search types to understand differences
- Verify embeddings were generated (`/vector-index/status`)

### Embedding Generation Fails

**Error messages:**
- `"Failed to generate embedding"` in logs
- `"Rate limit exceeded"` from VoyageAI API
- `"Invalid request error"`

**Solutions:**

```bash
# Rate limit errors - wait and retry
# VoyageAI has built-in exponential backoff (3 retries)
# If still failing, reduce batch size:

# Check current batch size (default 128)
# Modify in database.py rebuild_vector_index() if needed

# Invalid request errors - check API key
curl -X POST http://localhost:8000/vector-index/rebuild
# Look for error details in server logs

# Verify API key is valid
echo $VOYAGE_API_KEY  # Should start with "pa-"
```

**Common issues:**
- **Rate limits**: VoyageAI free tier has limits, wait or upgrade
- **Empty documents**: Some items skipped if analysis is empty
- **Token limits**: Very long documents auto-truncated (32K token max)
- **Network errors**: Temporary, automatic retry handles most cases

## Configuration

### Environment Variables

**Required for answer generation:**
- `ANTHROPIC_API_KEY` - For Claude models
- `OPENAI_API_KEY` - For GPT models (optional)

**Required for vector search:**
- `VOYAGE_API_KEY` - For VoyageAI embedding generation
- `VOYAGE_EMBEDDING_MODEL` - Optional, defaults to `voyage-3.5-lite`

**Example `.env` file:**
```bash
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-proj-...
VOYAGE_API_KEY=pa-...
VOYAGE_EMBEDDING_MODEL=voyage-3.5-lite  # Optional, 512 dims
```

### Model Selection

**Default:** Claude Sonnet 4.5

**Change model:**
```bash
curl -X POST http://localhost:8000/search \
  -d '{"query": "test", "answer_model": "gpt-4o"}'
```

**Supported models:**
- Claude: `claude-sonnet-4-5`, `claude-opus-4`
- OpenAI: `gpt-4o`, `gpt-4o-mini`
- OpenAI Reasoning: `gpt-5`, `o1`, `o1-mini`, `o1-preview`, `o3`, `o3-mini`

**Note on Reasoning Models:**
OpenAI's reasoning models (gpt-5, o1, o3 series) use extended token limits:
- Standard models: 1024 max_tokens
- Reasoning models: 4000 max_completion_tokens (allows for internal reasoning + output)

### Index Configuration

**BM25 Index Settings (`items_fts` table):**
- Tokenizer: `unicode61 remove_diacritics 2`
- BM25 parameters: Default (k1=1.2, b=0.75)
- No stemming
- Field weights: Implemented via document repetition (see weighted document construction)

**To enable Porter stemming:**
```sql
-- Modify in database.py
tokenize='porter unicode61'
```

**Vector Index Settings (`vec_items` table):**
- **Model**: `voyage-3.5-lite` (default)
- **Dimensions**: 512 (voyage-3.5-lite) or 1024 (voyage-3.5)
- **Distance Metric**: Cosine distance
- **Batch Size**: 128 documents per API call
- **Metadata**: Category field for filtering

**To change embedding model:**
```bash
# Set environment variable
export VOYAGE_EMBEDDING_MODEL=voyage-3.5  # 1024 dimensions

# Rebuild index with new model
curl -X POST http://localhost:8000/vector-index/rebuild
```

**Note:** Changing embedding model requires:
1. Updating `VOYAGE_EMBEDDING_MODEL` environment variable
2. Dropping and recreating `vec_items` table with new dimensions
3. Rebuilding entire vector index (all embeddings regenerated)

## Development

### File Structure

```
/workspaces/collections-local/
├── database.py                 # FTS5 & vector tables, search functions
├── embeddings.py               # VoyageAI embedding generation
├── models.py                   # SearchRequest/Response models
├── main.py                     # API endpoints
├── retrieval/
│   ├── __init__.py
│   ├── langchain_retrievers.py # LangChain retriever implementations
│   └── answer_generator.py     # LLM answer generation
├── scripts/
│   ├── backfill_embeddings.py  # Generate embeddings for existing items
│   ├── migrate_add_vector_tables.py  # Database migration for vector tables
│   └── evaluate_retrieval.py   # Retrieval evaluation script
├── evaluation/                  # Planned
│   ├── __init__.py
│   ├── metrics.py              # Evaluation metrics
│   └── evaluator.py            # Test runner
└── data/
    └── eval/                   # Evaluation data
        └── test_queries.json   # Test query set
```

**Key Files:**

| File | Purpose | Lines |
|------|---------|-------|
| `database.py` | BM25 FTS5 tables, vector tables, search functions | ~800 |
| `embeddings.py` | VoyageAI client, embedding generation, batch processing | 219 |
| `main.py` | FastAPI endpoints for search, index management | ~600 |
| `models.py` | Pydantic models for API requests/responses | ~150 |
| `retrieval/langchain_retrievers.py` | LangChain BM25, vector, and hybrid retrievers | ~300 |
| `retrieval/answer_generator.py` | LLM answer generation, citation extraction | ~100 |

### Adding New Features

**1. Query Expansion:**

Create `retrieval/query_processor.py`:
```python
def expand_query(query: str) -> str:
    synonyms = {
        "restaurant": ["restaurant", "dining", "cafe"],
        "tokyo": ["tokyo", "japan", "japanese"]
    }
    # Expand query with synonyms
    return expanded_query
```

**2. Custom Scoring:**

Modify BM25 parameters in database init:
```sql
-- Not directly supported by FTS5
-- Would need custom ranking function
```

**3. Faceted Search:**

Add aggregation endpoint:
```python
@app.get("/search/facets")
def get_search_facets(query: str):
    # Return category distribution of results
    return {"facets": {...}}
```

## References

- [SQLite FTS5 Documentation](https://www.sqlite.org/fts5.html)
- [BM25 Algorithm](https://en.wikipedia.org/wiki/Okapi_BM25)
- [Claude API Documentation](https://docs.anthropic.com/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)

## Support

For issues or questions:
1. Check this documentation
2. Review API docs at http://localhost:8000/docs
3. Check server logs for errors
4. Test with `/index/status` endpoint
