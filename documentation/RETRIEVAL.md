# BM25 Retrieval System Documentation

## Overview

This document describes the BM25-based retrieval system for natural language Q&A over the Collections Local image collection. The system enables users to search their collection using natural language queries and receive AI-generated answers with citations.

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
│              SQLite FTS5 Search Engine                   │
│           (Built-in BM25 Ranking)                        │
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

- **SQLite FTS5**: Full-text search with built-in BM25 ranking
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
2. **Stopword Removal**: Filters common words that don't add search value
3. **Tokenization**: Splits on whitespace and converts to lowercase
4. **Length Filtering**: Removes tokens shorter than 2 characters

**Stopwords Removed:**
```
a, an, and, are, as, at, be, by, for, from, has, he, in, is, it, its,
of, on, that, the, to, was, will, with, what, where, when, who, how
```

**Example:**
```python
# Input query
"What restaurants are in Tokyo?"

# After preprocessing
"restaurants tokyo"
```

**Benefits:**
- Improves precision by removing noise words
- Reduces irrelevant matches on common terms
- Faster search with fewer terms

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
- Queries with mostly stopwords (automatically filtered, may result in overly broad search)
- Single-term queries after preprocessing

### 3. API Endpoints (`main.py`)

#### POST /search

**Request:**
```json
{
  "query": "Tokyo restaurants",
  "top_k": 10,
  "category_filter": null,
  "include_answer": true,
  "answer_model": null
}
```

**Response:**
```json
{
  "query": "Tokyo restaurants",
  "results": [...],
  "total_results": 2,
  "answer": "Based on your collection...",
  "answer_confidence": 0.42,
  "citations": ["1", "2"],
  "retrieval_time_ms": 1.71,
  "answer_time_ms": 4717.53
}
```

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
  -d '{"query": "Tokyo", "top_k": 5, "include_answer": false}'
```

**Matches:**
- Items with "Tokyo" in any field
- Weighted by field importance
- Fast (no LLM call)

### Natural Language Question

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "What restaurants are in my collection?", "include_answer": true}'
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
  -d '{"query": "perfume", "category_filter": "Beauty", "top_k": 10}'
```

**Benefits:**
- Narrows results to specific category
- Improves precision for ambiguous terms
- Slightly slower (JOIN operation)

### Multi-Term Query

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Japanese food Tokyo shopping", "top_k": 10}'
```

**Behavior:**
- BM25 ranks by relevance across all terms
- Items matching more terms rank higher
- Term proximity doesn't affect ranking (bag-of-words)

## Limitations

### Current Limitations

1. **No Semantic Understanding**
   - Keyword-based only (BM25)
   - Doesn't understand synonyms (unless manually added)
   - Can't handle paraphrases
   - Example: "Tokyo" won't match "Japan's capital"

2. **Stopword Filtering Side Effects**
   - Removes common question words automatically
   - May affect very short queries
   - Example: "What is in the photo?" → "photo" (single term)
   - Workaround: Use more specific query terms

3. **No Query Expansion**
   - Searches exact preprocessed terms only
   - Manual synonym support not implemented
   - Would require additional query processing layer

4. **Bag-of-Words**
   - No phrase matching capability
   - Word order doesn't matter
   - "Tokyo restaurants" ≈ "restaurants Tokyo"
   - Can't distinguish "New York" from "New" and "York" separately

5. **Index Staleness**
   - Doesn't auto-update after new analyses
   - Must manually rebuild or restart server
   - Workaround: Call `/index/rebuild` after bulk analysis

6. **No Multi-Modal Search**
   - Text-only search
   - Can't search by image similarity or visual features
   - Would require vision embeddings

### Addressing Limitations

**Future Enhancements:**

1. **Hybrid Search** (BM25 + Embeddings)
   - Combine keyword and semantic search
   - Re-rank with cross-encoder
   - Best of both worlds - precision + recall

2. **Smarter Query Preprocessing**
   - Context-aware stopword removal
   - Preserve important question phrases
   - Query expansion with synonyms
   - LLM-based query reformulation

3. **Automatic Index Updates**
   - Database triggers on analysis insert/update
   - Background index refresh daemon
   - Real-time updates without manual rebuild

4. **Phrase Matching**
   - Support for quoted phrase queries
   - FTS5 NEAR operator for proximity search
   - Better handling of multi-word entities

5. **Conversational Search**
   - Multi-turn Q&A with context retention
   - Clarifying questions when results are ambiguous
   - Follow-up query support

## Testing

### Manual Testing

```bash
# 1. Check index status
curl http://localhost:8000/index/status

# 2. Rebuild if needed
curl -X POST http://localhost:8000/index/rebuild

# 3. Test search without answer
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "include_answer": false}'

# 4. Test search with answer
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "include_answer": true}'
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
3. All query terms were stopwords - query became empty after preprocessing
4. No analyzed items - analyze images first
5. Typo in query - check spelling

**Solutions:**
```bash
# Check index
curl http://localhost:8000/index/status

# Rebuild index
curl -X POST http://localhost:8000/index/rebuild

# Try simpler query
curl -X POST http://localhost:8000/search \
  -d '{"query": "tokyo", "include_answer": false}'

# Avoid stopword-only queries
# Bad: "What is this?"  (preprocesses to empty)
# Good: "screenshot content" (meaningful terms)
```

**Query Preprocessing Note:**
Remember that common words are automatically removed. If your query is:
- "What is in the photo?" → preprocesses to "photo"
- "Show me the items" → preprocesses to "show items"
- Use specific nouns and descriptive terms for best results

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

## Configuration

### Environment Variables

Required for answer generation:
- `ANTHROPIC_API_KEY` - For Claude models
- `OPENAI_API_KEY` - For GPT models (optional)

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

**Current settings:**
- Tokenizer: `unicode61 remove_diacritics 2`
- BM25 parameters: Default (k1=1.2, b=0.75)
- No stemming

**To enable Porter stemming:**
```sql
-- Modify in database.py
tokenize='porter unicode61'
```

## Development

### File Structure

```
/workspaces/collections-local/
├── database.py                 # FTS5 table & search functions
├── models.py                   # SearchRequest/Response models
├── main.py                     # API endpoints
├── retrieval/
│   ├── __init__.py
│   └── answer_generator.py     # LLM answer generation
├── evaluation/                  # Planned
│   ├── __init__.py
│   ├── metrics.py              # Evaluation metrics
│   └── evaluator.py            # Test runner
└── data/
    └── eval/                   # Planned
        └── test_queries.json   # Test query set
```

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
