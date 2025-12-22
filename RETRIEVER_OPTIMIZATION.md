# Retriever Optimization Guide

## Summary of Changes

Based on evaluation results showing LangChain retrievers underperforming compared to native implementations, I've implemented the following optimizations:

### 1. BM25 Parameter Tuning ✅

**Problem**: BM25-LC showed -5.08% MRR degradation using default parameters (k1=1.5, b=0.75).

**Solution**: Added tunable BM25 parameters based on Elasticsearch best practices:
- `k1=1.2` (down from 1.5): Stronger term frequency saturation
- `b=0.75`: Document length normalization (unchanged)
- `epsilon=0.25`: IDF floor (unchanged)

**Files Modified**:
- `retrieval/langchain_native_retrievers.py`: Added k1, b, epsilon parameters to `LangChainNativeBM25Retriever`
- `main.py`: Updated initialization to use optimized parameters

### 2. Chroma Distance Metric Fix 🚨 **CRITICAL**

**Problem**: Chroma was using **L2 distance** (default) while native vector uses **cosine similarity**!

**Impact**: Different distance metrics produce **completely different rankings**, making performance comparisons invalid.

**Solution**: Configured Chroma to use cosine similarity via `collection_metadata`:
```python
collection_metadata={"hnsw:space": "cosine"}  # Match native vector implementation
```

**Files Modified**:
- `retrieval/chroma_manager.py`: Added `collection_metadata` parameter with cosine distance
- `main.py`: Updated initialization logs to show distance metric
- `config/retriever_config.py`: Documented critical importance of cosine for fair comparison

**Why This Matters**:
- Native vector (sqlite-vec): `distance_metric=cosine` (line 497 in database.py)
- Chroma default: L2 distance (NOT cosine!)
- **This mismatch likely caused most of the -2.25% MRR degradation**

### 3. VoyageAI input_type Limitation ⚠️

**Investigation**: VoyageAI's `input_type` parameter would optimize embeddings for documents vs queries.

**Finding**: LangChain's `VoyageAIEmbeddings` wrapper **does not support `input_type` parameter**.

**Alternative**: To use `input_type` optimization, must use direct VoyageAI SDK (see `embeddings.py`).

**Status**: Not implemented in this optimization pass (requires more extensive refactoring)

### 3. Configuration Module ✅

**Created**: `config/retriever_config.py`

Provides:
- Centralized parameter configuration
- Multiple BM25 configurations for experimentation
- Documentation on parameter tuning
- Helper functions for config access

## Expected Impact

Based on the evaluation report analysis:

### BM25-LC Improvements
**Current Performance** (with default k1=1.5):
- MRR: 0.8558 (-5.08% vs native)
- Severely degraded on multi-item recall (-23.29%) and semantic queries (-16.07%)

**Expected Improvement** (with k1=1.2):
- Reduced term frequency sensitivity should help with:
  - Better saturation on repeated terms
  - Closer alignment to Elasticsearch-tuned systems
  - Potential 1-3% MRR improvement

### Vector-LC Improvements 🚨 **CRITICAL FIX**
**Current Performance** (with WRONG distance metric):
- MRR: 0.9571 (-2.25% vs native)
- Degraded on semantic queries (-8.31%)
- **Using L2 distance instead of cosine similarity!**

**Expected Improvement** (with cosine similarity matching native):
- **This mismatch likely caused MOST of the degradation**
- Using same distance metric as native implementation
- **Potential 3-5% MRR improvement** (possibly complete recovery)
- Much better semantic query performance

### Combined Impact
- **Realistic expectation**: 3-6% MRR improvement for LangChain retrievers
- **Best case**: Vector-LC may match native performance (both use cosine + VoyageAI)
- **BM25-LC**: Moderate improvement from k1 tuning (2-3%)
- **Maintained**: 87.85% speed advantage for BM25-LC

## Testing Instructions

### 1. **Delete and Rebuild Chroma Collections (CRITICAL)** 🚨

**WARNING**: Chroma's distance metric **cannot be changed** on existing collections!

You **MUST delete** the old collections and rebuild with cosine similarity:

```bash
# Delete existing Chroma collections (DESTRUCTIVE - backups recommended)
rm -rf data/chroma_prod/
rm -rf data/chroma_golden/

# Regenerate with cosine similarity for PRODUCTION database
python scripts/regenerate_embeddings.py --database prod

# Regenerate with cosine similarity for GOLDEN database (for evaluation)
python scripts/regenerate_embeddings.py --database golden
```

**Why this is required**:
- Old collections use L2 distance (Chroma default)
- New collections will use cosine similarity (matching native)
- Distance metric is set at collection creation and cannot be changed
- **This is the most critical fix** - wrong distance metric invalidates comparisons

**Note**: BM25 index rebuilds automatically on server restart (in-memory).

### 2. Restart the Server

```bash
# Kill existing server
pkill -f uvicorn

# Start with new configurations
python main.py
```

You should see log output showing the optimized parameters:
```
✓ LangChain BM25 retriever (PROD) initialized (k1=1.2, b=0.75)
✓ Chroma vector store (PROD) initialized (distance=cosine)
```

### 3. Run Evaluation

```bash
# Evaluate on golden dataset
python scripts/evaluate_retrieval.py --database golden --output data/eval/reports
```

### 4. Compare Results

Compare the new evaluation report with the baseline:
- **Baseline**: `data/eval/reports/eval_20251222_192358_report.json`
- **New**: `data/eval/reports/eval_<timestamp>_report.json`

**Metrics to watch**:
- **MRR** (Mean Reciprocal Rank): Primary quality metric
- **Precision@5**: Top 5 accuracy
- **Recall@5**: Coverage in top 5
- **Query latency**: Should remain fast for BM25-LC

**Key comparisons**:
```bash
# Generate comparison report
python scripts/evaluate_retrieval.py --compare \
  --baseline data/eval/reports/eval_20251222_192358_report.json \
  --current data/eval/reports/eval_<new_timestamp>_report.json
```

## Parameter Tuning Guide

### When to Adjust BM25 Parameters

Located in `config/retriever_config.py`:

#### k1 (Term Frequency Saturation)
- **Current**: 1.2 (Elasticsearch recommended)
- **Increase to 1.5-2.0 if**: Important terms appear multiple times in relevant documents
- **Decrease to 0.8-1.0 if**: Term repetition creates noise

#### b (Length Normalization)
- **Current**: 0.75 (standard)
- **Increase to 1.0 if**: Long documents dilute relevance
- **Decrease to 0.5 if**: Longer documents are inherently more relevant

### Experimentation Configurations

The config module provides pre-configured alternatives:

```python
from config.retriever_config import get_bm25_config

# Try different configurations
configs = ["default", "high_saturation", "low_saturation", "no_length_norm"]

for config_name in configs:
    config = get_bm25_config(config_name)
    retriever = LangChainNativeBM25Retriever(
        database_path=path,
        k1=config["k1"],
        b=config["b"],
        epsilon=config["epsilon"]
    )
    # Run evaluation...
```

## Future Enhancements

### 1. Query-Time input_type Optimization

**Current**: Using `input_type="document"` for both indexing and querying

**Optimal**:
- Index time: `input_type="document"`
- Query time: `input_type="query"`

**Implementation**:
Requires modifying the query path to use a separate embedding instance:

```python
# Create query-optimized embeddings
query_embeddings = VoyageAIEmbeddings(
    voyage_api_key=api_key,
    model=model,
    input_type="query"
)

# Use for searches
results = vectorstore.similarity_search(
    query,
    embedding=query_embeddings.embed_query(query)
)
```

### 2. Chroma Distance Metric Optimization

**Current**: L2 (Euclidean) distance

**Potential**: Cosine similarity may perform better for normalized embeddings

**Warning**: Changing distance metric requires complete index rebuild

### 3. Hybrid Search Weight Tuning

**Current** (from `config/retriever_config.py`):
- BM25 weight: 0.3
- Vector weight: 0.7

**Tuning**: Adjust based on query type distribution in your workload

## Monitoring and Metrics

### Key Performance Indicators

Track these metrics in production:

1. **Search Quality**:
   - Click-through rate on search results
   - Position of clicked results
   - Search refinement frequency

2. **Performance**:
   - BM25-LC latency (target: <5ms)
   - Vector-LC latency (target: <150ms)
   - Hybrid-LC latency (target: <200ms)

3. **System**:
   - Memory usage (BM25 is in-memory)
   - Chroma disk usage
   - Embedding generation time

### A/B Testing Recommendations

When rolling out to production:

1. **Gradual rollout**: 10% → 25% → 50% → 100%
2. **Monitor**: User engagement metrics
3. **Compare**: Old vs new retriever performance
4. **Rollback plan**: Keep native retrievers available

## References

- [Elasticsearch BM25 Parameter Guide](https://www.elastic.co/blog/practical-bm25-part-3-considerations-for-picking-b-and-k1-in-elasticsearch)
- [VoyageAI API Documentation](https://docs.voyageai.com/reference)
- [LangChain BM25Retriever](https://python.langchain.com/docs/integrations/retrievers/bm25/)
- [rank-bm25 Library](https://github.com/dorianbrown/rank_bm25)

## Troubleshooting

### BM25 index not rebuilding

**Symptom**: Old parameters still showing in logs

**Solution**:
```bash
# Force rebuild via API
curl -X POST http://localhost:8000/api/rebuild-bm25-langchain?database=prod
```

### Chroma embeddings not updating

**Symptom**: Old input_type behavior persists

**Solution**:
```bash
# Delete and rebuild Chroma index
python scripts/regenerate_embeddings.py --database prod --force-rebuild
```

### Performance degradation

**Symptom**: Searches slower than before

**Check**:
1. BM25 in-memory index loaded
2. Chroma collection exists and is populated
3. No errors in server logs

## Questions?

For issues or questions:
1. Check server logs for initialization errors
2. Verify config values in `config/retriever_config.py`
3. Run evaluation to quantify changes
4. Compare against baseline metrics
