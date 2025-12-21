# LangSmith Integration

## Overview

The Collections Local API uses **LangSmith** (by LangChain) for observability, prompt management, and evaluation. LangSmith provides:

- **Tracing**: All image analysis and answer generation operations are traced
- **Prompt Management**: System prompts fetched from LangSmith Hub
- **Evaluation Framework**: Quality metrics and regression testing
- **Debugging**: Full trace visibility for troubleshooting

---

## Configuration

### Required Environment Variables

Add these to your `.env` file:

```bash
# LangSmith Configuration
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_YOUR_API_KEY_HERE
LANGCHAIN_PROJECT=collections-local
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_PROMPT_NAME=collections-app-initial
```

### Getting Your API Key

1. Sign up at [LangSmith](https://smith.langchain.com/)
2. Navigate to Settings → API Keys
3. Create a new API key
4. Copy the key (starts with `lsv2_pt_`)

---

## Tracing

### Automatic Tracing

All analysis operations automatically create traces in LangSmith:

- **Image Analysis** (`/items/{id}/analyze`): Full vision analysis trace
- **Answer Generation** (`/search` with `include_answer=true`): RAG pipeline trace

### Accessing Traces

**Dashboard URL:** https://smith.langchain.com/projects/collections-local

Each analysis response includes a `trace_id`:

```json
{
  "id": "analysis-uuid",
  "trace_id": "019b4294-297b-78e3-9f34-a188a2d932a4",
  "category": "Beauty",
  ...
}
```

Use this ID to locate the trace in the LangSmith dashboard for debugging.

### Trace Contents

Each trace includes:

- **Input**: Image path, provider, model, metadata
- **Prompt**: System prompt used for analysis
- **LLM Call**: Provider (Anthropic/OpenAI), model, tokens used
- **Output**: Full analysis response
- **Metadata**: Item ID, filename, provider, model
- **Timing**: Total duration, LLM latency

---

## Prompt Management

### LangSmith Hub Integration

The system prompt is fetched from **LangSmith Hub** at runtime:

```python
# Configured via environment variable
LANGSMITH_PROMPT_NAME=collections-app-initial

# Fetched automatically on each analysis
client = LangSmithClient()
prompt = client.pull_prompt('collections-app-initial')
```

### Prompt Structure

The current prompt (`collections-app-initial`) is a sophisticated multi-section prompt that:

1. **Categorizes content** with single-word primary category + subcategories
2. **Identifies platform source** (TikTok, Instagram, X, Facebook, etc.)
3. **Extracts social media metadata**:
   - Original poster username/handle
   - Tagged accounts (@mentions)
   - Location tags (📍 geo-tags)
   - Audio/music attribution
   - Hashtags (#tags)
4. **Analyzes visual elements**:
   - Extracted text (ordered by prominence)
   - Visual hierarchy (top 5 elements by visual weight)
   - Key interest point (what caught attention)
   - Objects, themes, emotions, vibes
5. **Generates user-focused output**:
   - Headline (max 140 chars)
   - Summary (fact-focused, no narrative)

### Updating the Prompt

**Option 1: Via LangSmith UI** (Recommended)

1. Visit https://smith.langchain.com/hub
2. Navigate to your `collections-app-initial` prompt
3. Click "Edit" or create new commit
4. Modify prompt instructions
5. Save - changes take effect immediately (no code deploy needed!)

**Option 2: Change Prompt Name**

```bash
# In .env
LANGSMITH_PROMPT_NAME=my-new-prompt-name
```

Restart the server to use the new prompt.

### Fallback Behavior

If LangSmith Hub is unavailable, the system automatically falls back to an embedded prompt to ensure zero downtime. You'll see a warning in logs:

```
WARNING: Failed to fetch prompt from LangSmith Hub: <error>. Using fallback prompt.
```

The fallback prompt provides basic analysis but lacks the sophisticated social media metadata extraction.

---

## Enhanced Analysis Response

### New Fields from LangSmith Prompt

Compared to the basic fallback, the LangSmith prompt adds:

**1. Media Metadata** (Social Platform Info)
```json
{
  "media_metadata": {
    "original_poster": "username",
    "tagged_accounts": ["@mention1", "@mention2"],
    "location_tags": ["Tokyo", "Shibuya"],
    "audio_source": "Song Name - Artist",
    "hashtags": ["#travel", "#japan"]
  }
}
```

**2. Enhanced Image Details**
```json
{
  "image_details": {
    "extracted_text": ["Text 1", "Text 2"],  // Array, ordered by prominence
    "likely_source": "TikTok",              // Platform detection
    "key_interest": "Primary attention point",
    "visual_hierarchy": [                    // Top 5 by visual weight
      "Main title",
      "Product image",
      "Price",
      "CTA button",
      "Brand logo"
    ],
    "objects": [...],
    "themes": [...],
    "emotions": [...],
    "vibes": [...]
  }
}
```

### Example Response

```json
{
  "id": "analysis-uuid",
  "item_id": "item-uuid",
  "category": "Beauty",
  "summary": "J-Scent Japanese perfume house features affordable fragrances at ¥4,950...",
  "raw_response": {
    "category": "Beauty",
    "subcategories": ["Perfume", "Shopping", "Japanese Beauty"],
    "headline": "J-Scent Japanese Perfume House Discovery",
    "summary": "J-Scent Japanese perfume house features affordable fragrances...",
    "media_metadata": {
      "original_poster": "ceri is a perfume junkie",
      "tagged_accounts": [],
      "location_tags": ["JAPAN", "J-Scent"],
      "audio_source": "Harpy Hare - Yaelokre",
      "hashtags": []
    },
    "image_details": {
      "extracted_text": [
        "J-SCENT",
        "finally had the chance to try this famous Japanese perfume house...",
        "*picked up Wood Flake, Hisui & Sumo Wrestler ❤️*"
      ],
      "likely_source": "TikTok",
      "key_interest": "Affordable Japanese perfumes at ¥4,950 with three specific scents",
      "visual_hierarchy": [
        "J-SCENT brand name",
        "Tester bottle with label held in hand",
        "Price point ¥4,950",
        "Three perfume names purchased",
        "Store display with multiple products"
      ],
      "objects": ["perfume bottles", "tester bottles", "retail display"],
      "themes": ["beauty shopping", "fragrance discovery"],
      "emotions": ["excitement", "enthusiasm"],
      "vibes": ["enthusiastic", "affordable luxury"]
    }
  },
  "provider_used": "anthropic",
  "model_used": "claude-sonnet-4-5",
  "trace_id": "019b4294-297b-78e3-9f34-a188a2d932a4",
  "created_at": "2024-12-21T20:00:00.000000"
}
```

---

## Evaluation Framework

### Available Evaluators

The system includes 6 custom evaluators for quality assessment:

1. **Category Accuracy** - Exact match on category (0 or 1)
2. **Subcategory Overlap** - Jaccard similarity (0-1)
3. **Semantic Similarity** - LLM-as-judge for summaries (0-1)
4. **Retrieval Precision@K** - Search precision
5. **Retrieval Recall@K** - Search recall
6. **Trajectory Score** - End-to-end pipeline quality

### Running Evaluations

```bash
# Upload golden dataset to LangSmith
python evaluation/langsmith_dataset.py

# Run analysis evaluation
python evaluation/run_langsmith_eval.py --type analysis

# Run retrieval evaluation
python evaluation/run_langsmith_eval.py --type retrieval --search-type bm25

# Compare search types
python evaluation/run_langsmith_eval.py --type compare

# Run end-to-end trajectory evaluation
python evaluation/trajectory_eval.py
```

### Viewing Results

Results are available in the LangSmith dashboard:
- **Experiments**: https://smith.langchain.com/experiments
- **Datasets**: https://smith.langchain.com/datasets

---

## Troubleshooting

### Issue: Trace ID Returns Null

**Symptoms:** `trace_id` field is `null` in analysis response

**Solutions:**
1. Verify `LANGCHAIN_TRACING_V2=true` in `.env`
2. Check `LANGCHAIN_API_KEY` is valid
3. Restart server to reload environment variables
4. Check LangSmith dashboard for traces (they may exist even if ID capture fails)

### Issue: Prompt Not Loading from Hub

**Symptoms:** Log shows "Failed to fetch prompt from LangSmith Hub" and using fallback

**Solutions:**
1. Verify `LANGCHAIN_API_KEY` is set correctly
2. Check prompt name: `LANGSMITH_PROMPT_NAME=collections-app-initial`
3. Ensure prompt exists in your LangSmith workspace
4. Test manually:
   ```python
   from langsmith import Client
   client = Client()
   prompt = client.pull_prompt('collections-app-initial')
   print(prompt.template[:100])
   ```

### Issue: Missing New Analysis Fields

**Symptoms:** Response lacks `media_metadata`, `likely_source`, or `visual_hierarchy`

**Possible Causes:**
1. Using fallback prompt instead of LangSmith prompt
2. Old analysis created before migration
3. LLM not following prompt structure

**Solutions:**
1. Check logs for prompt loading success
2. Force reanalysis: `POST /items/{id}/analyze` with `{"force_reanalyze": true}`
3. Verify LangSmith prompt is correct in dashboard

---

## Migration from Langfuse

If you previously used Langfuse, the migration is complete. Key changes:

| Aspect | Langfuse (Old) | LangSmith (New) |
|--------|----------------|-----------------|
| Tracing | `@observe` decorator | `@traceable` decorator |
| Prompts | `langfuse.get_prompt()` | `client.pull_prompt()` |
| Trace ID | `langfuse.trace_id` | `get_current_run_tree().id` |
| Dashboard | cloud.langfuse.com | smith.langchain.com |
| SDK | `langfuse` | `langsmith` |

**Environment variables removed:**
- `LANGFUSE_SECRET_KEY`
- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_HOST`

**Environment variables added:**
- `LANGCHAIN_TRACING_V2`
- `LANGCHAIN_API_KEY`
- `LANGCHAIN_PROJECT`
- `LANGSMITH_PROMPT_NAME`

---

## Resources

### Documentation
- **LangSmith Docs**: https://docs.smith.langchain.com/
- **LangChain Docs**: https://python.langchain.com/docs/
- **Evaluation Guide**: https://docs.smith.langchain.com/evaluation

### Dashboards
- **Project**: https://smith.langchain.com/projects/collections-local
- **Hub**: https://smith.langchain.com/hub
- **Datasets**: https://smith.langchain.com/datasets

### Support
- **LangChain Discord**: https://discord.gg/langchain
- **GitHub Issues**: https://github.com/langchain-ai/langsmith-sdk/issues

---

## Summary

LangSmith integration provides:
- ✅ Full observability for all AI operations
- ✅ Centralized prompt management
- ✅ Quality evaluation framework
- ✅ Enhanced analysis with social media metadata
- ✅ Zero-downtime fallback for reliability

All analysis operations are automatically traced, and the sophisticated LangSmith prompt provides richer analysis compared to the basic fallback.
