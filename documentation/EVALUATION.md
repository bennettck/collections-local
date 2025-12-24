# Retrieval Evaluation System

## Overview

The retrieval evaluation system measures search quality using a golden dataset of curated queries and standard Information Retrieval (IR) metrics. This enables systematic assessment of search performance, regression testing, and optimization tracking.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│              Golden Database (55 Items)                  │
│         data/collections_golden.db                       │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              Golden API Instance                         │
│         http://localhost:8001                            │
│         (runs alongside production on :8000)             │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│         Evaluation Dataset (50 Queries)                  │
│    data/eval/retrieval_evaluation_dataset.json          │
│    - single-item-precision queries (15)                 │
│    - multi-item-recall queries (15)                     │
│    - semantic queries (12)                              │
│    - edge-case-no-results (8)                           │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│         evaluate_retrieval.py Script                     │
│    - Runs all queries against API                       │
│    - Calculates Precision, Recall, MRR, NDCG            │
│    - Generates markdown + JSON reports                  │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│           Evaluation Reports                             │
│    data/eval/reports/eval_YYYYMMDD_HHMMSS_*.{md,json}   │
└─────────────────────────────────────────────────────────┘
```

## Components

### 1. Golden Database

A curated subset of 55 high-quality items from the production database used for evaluation.

**Setup**:
```bash
# Create golden database from production
python scripts/setup_golden_db.py

# Start golden API on port 8001
./scripts/run_golden_api.sh
```

**Why 55 items?**
- Large enough for diverse query types
- Small enough for fast evaluation (8-10 seconds)
- Manually curated for quality and variety
- Covers all major categories and content types

See [DUAL_DATABASE.md](./DUAL_DATABASE.md) for complete dual-database documentation.

### 2. Evaluation Dataset

File: `data/eval/retrieval_evaluation_dataset.json`

**Basic Structure** (backward compatible):
```json
{
  "metadata": {
    "version": "1.0",
    "total_queries": 50,
    "query_types": {
      "single-item-precision": 15,
      "multi-item-recall": 15,
      "semantic": 12,
      "edge-case-no-results": 8
    }
  },
  "queries": [
    {
      "query_id": "q001",
      "query_text": "TeamLab digital art museum Fukuoka",
      "query_type": "single-item-precision",
      "expected_items": [
        {
          "item_id": "f5129142-8126-4f7b-8b72-72f4024d4078",
          "relevance": "high"
        }
      ],
      "expected_count": 1
    }
  ]
}
```

**Extended Structure** (per-search-type expectations):
```json
{
  "queries": [
    {
      "query_id": "q025",
      "query_text": "peaceful nature escapes",
      "query_type": "semantic",
      "expected_items_by_search_type": {
        "bm25-lc": [
          {
            "item_id": "f509d013-83c6-4e77-b71f-0afbd9999c09",
            "relevance": "high"
          }
        ],
        "vector-lc": [
          {
            "item_id": "f509d013-83c6-4e77-b71f-0afbd9999c09",
            "relevance": "high"
          },
          {
            "item_id": "8e59d5c3-71ef-4caf-bc16-c23c5b1cc3eb",
            "relevance": "medium"
          }
        ]
      }
    }
  ]
}
```

**Expected Items Resolution**:
- If `expected_items_by_search_type` exists for the current search type → use it
- Else if `expected_items` exists → use it (backward compatible)
- This allows different expected results for BM25 vs vector vs hybrid vs agentic search
- Supported search types: `bm25-lc`, `vector-lc`, `hybrid-lc`, `agentic`

**Query Types**:

1. **single-item-precision** (15 queries)
   - Tests ability to find a specific item
   - Example: "TeamLab digital art museum Fukuoka"
   - Success criteria: Target item in top result

2. **multi-item-recall** (15 queries)
   - Tests ability to find multiple relevant items
   - Example: "Japanese museums and attractions"
   - Success criteria: High recall of all relevant items

3. **semantic** (12 queries)
   - Tests semantic understanding beyond keyword matching
   - Example: "immersive art experiences"
   - Success criteria: Finds conceptually related items

4. **edge-case-no-results** (8 queries)
   - Tests handling of queries with no relevant results
   - Example: "restaurants in Paris" (golden DB has no Paris items)
   - Success criteria: Returns zero results (true negative)

**Relevance Levels**:
- `high` (score: 3) - Highly relevant, answers query directly
- `medium` (score: 2) - Somewhat relevant, related but not perfect match
- `low` (score: 1) - Marginally relevant

### 3. Evaluation Script

Location: `scripts/evaluate_retrieval.py`

**Core Features**:
- Automatic API endpoint discovery
- Item count validation (prevents running against wrong database)
- Comprehensive metric calculation
- Dual report generation (markdown + JSON)
- Edge case handling
- Query-type breakdown analysis

## Metrics Explained

### Precision@K

**Definition**: Of the top K results returned, what fraction are relevant?

**Formula**: `Precision@K = |relevant ∩ retrieved@K| / K`

**Example**:
- Query returns 5 results
- 3 are relevant, 2 are not
- Precision@5 = 3/5 = 0.60

**Interpretation**:
- 1.0 = Perfect precision, all results are relevant
- 0.0 = No relevant results found
- Higher is better

**Use case**: Measures result quality when you care about not showing irrelevant items.

### Recall@K

**Definition**: Of all relevant items that exist, what fraction appear in the top K results?

**Formula**: `Recall@K = |relevant ∩ retrieved@K| / |relevant|`

**Example**:
- 4 relevant items exist in database
- Query returns top 5 results
- 3 of the 4 relevant items appear in those 5 results
- Recall@5 = 3/4 = 0.75

**Interpretation**:
- 1.0 = Perfect recall, found all relevant items
- 0.0 = Found none of the relevant items
- Higher is better

**Use case**: Measures completeness when you want to find all relevant items.

### MRR (Mean Reciprocal Rank)

**Definition**: Average of the reciprocal rank of the first relevant result.

**Formula**: `MRR = (1/N) × Σ(1/rank_i)`

**Example**:
- Query 1: First relevant result at rank 1 → RR = 1/1 = 1.0
- Query 2: First relevant result at rank 3 → RR = 1/3 = 0.33
- Query 3: First relevant result at rank 2 → RR = 1/2 = 0.50
- MRR = (1.0 + 0.33 + 0.50) / 3 = 0.61

**Interpretation**:
- 1.0 = Perfect, first result always relevant
- 0.5 = First relevant result typically at rank 2
- 0.0 = No relevant results found
- Higher is better

**Use case**: Emphasizes getting the first relevant result as high as possible. Critical for user experience.

### NDCG@K (Normalized Discounted Cumulative Gain)

**Definition**: Measures ranking quality with graded relevance, discounting lower-ranked results.

**Formula**:
```
DCG@K = Σ(rel_i / log2(i+1)) for i=1 to K
IDCG@K = DCG of ideal ranking
NDCG@K = DCG@K / IDCG@K
```

**Example**:
- Results: [high, low, high, medium, none]
- Relevance scores: [3, 1, 3, 2, 0]
- DCG@5 = 3/log2(2) + 1/log2(3) + 3/log2(4) + 2/log2(5) + 0/log2(6)
- DCG@5 = 3.0 + 0.63 + 1.5 + 0.86 + 0 = 5.99
- Ideal: [high, high, medium, low, none] → IDCG@5 = 7.13
- NDCG@5 = 5.99 / 7.13 = 0.84

**Interpretation**:
- 1.0 = Perfect ranking (ideal order)
- 0.0 = No relevant results
- Higher is better
- Penalizes relevant items that appear too low in results

**Use case**: Best overall metric when you have graded relevance and care about result ordering.

## Usage

### Quick Start

```bash
# 1. Start golden API
./scripts/run_golden_api.sh

# 2. Run evaluation
python scripts/evaluate_retrieval.py

# 3. View results
cat data/eval/reports/eval_*_report.md
```

### Command-Line Options

```bash
python scripts/evaluate_retrieval.py [OPTIONS]

Required:
  (none - all have defaults)

Optional:
  --port PORT              API port (default: 8000)
  --base-url URL          Full base URL (overrides --port)
  --dataset PATH          Evaluation dataset JSON
                          (default: data/eval/retrieval_evaluation_dataset.json)
  --output-dir PATH       Report output directory
                          (default: data/eval/reports)
  --top-k VALUES          Comma-separated K values for metrics
                          (default: 1,3,5,10)
  --expected-items N      Expected item count in database
                          (default: 55 for golden DB)
  --skip-item-check       Skip item count validation
  --verbose               Print detailed progress

Multi-Search Type Options:
  --search-types TYPES    Comma-separated search types to evaluate:
                          'bm25-lc', 'vector-lc', 'hybrid-lc', 'agentic', or 'all' (default: all)
                          Note: 'agentic' can take 2-4s per query (optimized)
  --parallel              Run search types in parallel per query
                          for faster evaluation (default: enabled)
  --no-parallel           Disable parallel execution
                          (run search types sequentially)

Subdomain Routing Options:
  --use-golden-subdomain  Use golden.localhost subdomain routing to access
                          golden database (default: enabled)
  --no-golden-subdomain   Disable golden subdomain routing
                          (for testing against production DB)
```

### Common Workflows

#### 1. Standard Evaluation (All Search Types)

```bash
# Start API on port 8000
uvicorn main:app --port 8000

# Run evaluation for both BM25 and vector search (default)
python scripts/evaluate_retrieval.py --verbose

# This will:
# - Route to golden database via golden.localhost subdomain
# - Evaluate both BM25-LC and vector-LC search in parallel
# - Generate comparison reports
```

#### 2. Evaluate Single Search Type

```bash
# Evaluate BM25-LC only
python scripts/evaluate_retrieval.py --search-types bm25-lc

# Evaluate vector-LC search only
python scripts/evaluate_retrieval.py --search-types vector-lc

# Evaluate hybrid-LC search only
python scripts/evaluate_retrieval.py --search-types hybrid-lc

# Evaluate agentic search only (slower but intelligent)
python scripts/evaluate_retrieval.py --search-types agentic
```

#### 3. Sequential vs Parallel Execution

```bash
# Parallel execution (default, faster)
python scripts/evaluate_retrieval.py --search-types all --parallel

# Sequential execution (slower, but easier to debug)
python scripts/evaluate_retrieval.py --search-types all --no-parallel
```

#### 4. Evaluate Production Database

```bash
# Start production API
uvicorn main:app --port 8000

# Disable golden subdomain routing and skip item count check
python scripts/evaluate_retrieval.py \
  --no-golden-subdomain \
  --skip-item-check \
  --search-types all
```

⚠️ **Warning**: Production evaluation may show lower scores because:
- Production has many more items (more "distractor" items)
- Golden dataset is designed for the 55-item golden database

#### 5. Custom K Values

```bash
# Test with different K values
python scripts/evaluate_retrieval.py --top-k 1,5,10,20,50
```

#### 6. Remote Server Evaluation

```bash
# Evaluate remote API endpoint
python scripts/evaluate_retrieval.py --base-url http://192.168.1.100:8000
```

#### 7. Custom Output Location

```bash
# Save reports to custom directory
python scripts/evaluate_retrieval.py --output-dir ./my_evaluation_reports
```

## Output Reports

### Report Files

Each evaluation run generates two timestamped files:

1. **`eval_YYYYMMDD_HHMMSS_report.md`** - Human-readable markdown
2. **`eval_YYYYMMDD_HHMMSS_report.json`** - Machine-readable JSON

**Example**:
- `eval_20241214_153022_report.md`
- `eval_20241214_153022_report.json`

### Markdown Report Structure (Single Search Type)

```markdown
# Retrieval Evaluation Report

**Run ID**: eval_20241214_153022
**Timestamp**: 2024-12-14T15:30:22Z
**API Endpoint**: http://localhost:8000
**Search Type**: bm25-lc
**Dataset**: retrieval_evaluation_dataset.json (50 queries)
**Target Items**: 55 | **Actual Items**: 55 ✓

## Summary Metrics

| Metric    | @1   | @3   | @5   | @10  |
|-----------|------|------|------|------|
| Precision | 0.85 | 0.72 | 0.65 | 0.52 |
| Recall    | 0.45 | 0.68 | 0.82 | 0.94 |
| NDCG      | 0.78 | 0.81 | 0.83 | 0.85 |

**MRR**: 0.876

### Edge Cases (No Results Expected)
- True Negatives: 7/8 (87.5%)
- False Positives: 1/8 (12.5%)

### By Query Type

| Type                   | Count | P@5  | R@5  | MRR  |
|------------------------|-------|------|------|------|
| single-item-precision  | 15    | 0.92 | 0.92 | 0.95 |
| multi-item-recall      | 15    | 0.58 | 0.76 | 0.82 |
| semantic               | 12    | 0.55 | 0.71 | 0.78 |

## Detailed Results

### Query: q001 - "TeamLab digital art museum Fukuoka"
- **Type**: single-item-precision
- **Expected**: f5129142-... (high)
- **Retrieved@10**: f5129142-... (+2 more)
- **First relevant at rank**: 1
- **P@5**: 1.0 | **R@5**: 1.0 | **RR**: 1.0
- **Status**: ✓ PASS

[... all 50 queries ...]
```

### Markdown Report Structure (Multi-Search Comparison)

When evaluating multiple search types, the report includes side-by-side comparisons:

```markdown
# Retrieval Evaluation Report (Multi-Search Comparison)

**Run ID**: eval_20251221_064325
**Timestamp**: 2025-12-21T06:43:25Z
**API Endpoint**: http://localhost:8000
**Dataset**: retrieval_evaluation_dataset.json (50 queries)
**Search Types**: bm25-lc, vector-lc
**Parallel Execution**: Yes
**Target Items**: 55 | **Actual Items**: 55 ✓

---

## Performance Comparison

| Search Type    | Avg Time (ms) | Min (ms) | Max (ms) |
|----------------|---------------|----------|----------|
| **bm25-lc**    | 1.0           | 0.7      | 3.1      |
| **vector-lc**  | 103.6         | 80.5     | 406.4    |

---

## Summary Metrics Comparison

### Precision

| Metric | **bm25-lc** | **vector-lc** | Δ (abs) | Δ (%)  | Winner     |
|--------|-------------|---------------|---------|--------|------------|
| **@1** | 0.881       | 0.976         | +0.095  | +10.8% | VECTOR-LC  |
| **@5** | 0.376       | 0.414         | +0.038  | +10.1% | VECTOR-LC  |

### Recall

| Metric | **bm25-lc** | **vector-lc** | Δ (abs) | Δ (%)  | Winner     |
|--------|-------------|---------------|---------|--------|------------|
| **@1** | 0.546       | 0.578         | +0.033  | +6.0%  | VECTOR-LC  |
| **@5** | 0.846       | 0.901         | +0.055  | +6.4%  | VECTOR-LC  |

### NDCG

| Metric | **bm25-lc** | **vector-lc** | Δ (abs) | Δ (%)  | Winner     |
|--------|-------------|---------------|---------|--------|------------|
| **@1** | 0.865       | 0.976         | +0.111  | +12.8% | VECTOR-LC  |
| **@5** | 0.836       | 0.910         | +0.074  | +8.9%  | VECTOR-LC  |

### Mean Reciprocal Rank (MRR)

| Search Type    | MRR   | Δ vs first | Winner     |
|----------------|-------|------------|------------|
| **bm25-lc**    | 0.902 | -          |            |
| **vector-lc**  | 0.976 | +0.075     | VECTOR-LC  |

---

## Agreement Analysis

### Rank-1 Agreement
- **61.9%** of queries return the same top result
- Based on 42 comparable queries

### Top-K Overlap (Jaccard Similarity)
- **Top-3 Average**: 0.50 (50% overlap in top 3 results)
- **Top-5 Average**: 0.44 (44% overlap in top 5 results)

---

## By Query Type Comparison

### multi-item-recall

| Metric | **bm25-lc** | **vector-lc** | Winner     |
|--------|-------------|---------------|------------|
| P@5    | 0.59        | 0.63          | VECTOR-LC  |
| R@5    | 0.86        | 0.91          | VECTOR-LC  |
| MRR    | 0.90        | 1.00          | VECTOR-LC  |

### semantic

| Metric | **bm25-lc** | **vector-lc** | Winner     |
|--------|-------------|---------------|------------|
| P@5    | 0.33        | 0.45          | VECTOR-LC  |
| R@5    | 0.64        | 0.74          | VECTOR-LC  |
| MRR    | 0.78        | 0.81          | VECTOR-LC  |

[... other query types ...]
```

### JSON Report Structure

```json
{
  "run_id": "eval_20241214_153022",
  "timestamp": "2024-12-14T15:30:22Z",
  "config": {
    "api_base_url": "http://localhost:8001",
    "dataset_path": "data/eval/retrieval_evaluation_dataset.json",
    "top_k_values": [1, 3, 5, 10],
    "dataset_version": "1.0",
    "total_queries": 50,
    "target_item_count": 55,
    "actual_item_count": 55
  },
  "summary": {
    "precision": {"@1": 0.85, "@3": 0.72, "@5": 0.65, "@10": 0.52},
    "recall": {"@1": 0.45, "@3": 0.68, "@5": 0.82, "@10": 0.94},
    "ndcg": {"@1": 0.78, "@3": 0.81, "@5": 0.83, "@10": 0.85},
    "mrr": 0.876,
    "edge_cases": {
      "total": 8,
      "true_negatives": 7,
      "false_positives": 1,
      "tn_rate": 0.875,
      "fp_rate": 0.125
    }
  },
  "by_query_type": {
    "single-item-precision": {
      "count": 15,
      "precision": {"@1": 0.92, "@3": 0.85, "@5": 0.82, "@10": 0.68},
      "recall": {"@1": 0.92, "@3": 0.95, "@5": 0.98, "@10": 1.0},
      "ndcg": {"@1": 0.92, "@3": 0.93, "@5": 0.94, "@10": 0.95},
      "mrr": 0.95
    }
  },
  "query_results": [
    {
      "query_id": "q001",
      "query_text": "TeamLab digital art museum Fukuoka",
      "query_type": "single-item-precision",
      "expected_items": ["f5129142-8126-4f7b-8b72-72f4024d4078"],
      "expected_relevance": {"f5129142-8126-4f7b-8b72-72f4024d4078": "high"},
      "retrieved_items": ["f5129142-...", "abc123-...", "..."],
      "retrieved_scores": [-4.53, -3.21, -2.87],
      "retrieval_time_ms": 1.45,
      "metrics": {
        "precision": {"@1": 1.0, "@3": 0.33, "@5": 0.2, "@10": 0.1},
        "recall": {"@1": 1.0, "@3": 1.0, "@5": 1.0, "@10": 1.0},
        "reciprocal_rank": 1.0,
        "ndcg": {"@1": 1.0, "@3": 1.0, "@5": 1.0, "@10": 1.0}
      },
      "first_relevant_rank": 1,
      "status": "pass"
    }
  ],
  "timing": {
    "total_evaluation_time_s": 8.43,
    "avg_retrieval_time_ms": 1.82,
    "min_retrieval_time_ms": 0.62,
    "max_retrieval_time_ms": 3.45
  }
}
```

## Interpreting Results

### What Good Scores Look Like

For the **golden database** (55 items) with well-tuned search:

| Metric | Target | Good | Needs Work |
|--------|--------|------|------------|
| MRR | >0.85 | 0.75-0.85 | <0.75 |
| P@5 | >0.70 | 0.60-0.70 | <0.60 |
| R@5 | >0.80 | 0.70-0.80 | <0.70 |
| NDCG@5 | >0.80 | 0.70-0.80 | <0.70 |

### By Query Type Expectations

| Query Type | Expected Performance |
|------------|---------------------|
| single-item-precision | Very high (MRR > 0.90, P@1 > 0.85) |
| multi-item-recall | Moderate precision, high recall (P@5 ~0.60, R@10 > 0.85) |
| semantic | Lower scores acceptable (P@5 ~0.55, semantic matching is hard) |
| edge-case-no-results | High true negative rate (>80%) |

### Common Issues

**Low MRR (< 0.70)**
- First relevant result appearing too low in rankings
- **Solutions**:
  - Improve query understanding
  - Boost headline/category fields
  - Add query expansion

**Low Recall (< 0.70 @ K=10)**
- Missing relevant items entirely
- **Solutions**:
  - Check tokenization (unicode61)
  - Add synonyms or stemming
  - Increase K or adjust BM25 parameters

**High False Positive Rate (> 20%)**
- Returning results when none should be returned
- **Solutions**:
  - Set minimum score threshold
  - Improve query classification
  - Better handling of out-of-scope queries

## Safety Features

### Item Count Validation

The script validates you're testing against the golden database:

```
✓ Item count validated: 55 items
```

If the count doesn't match:
```
⚠️  WARNING: Item count mismatch!
   Expected: 55 items (golden database)
   Actual:   247 items

This suggests you may be running against the wrong database.
Use --skip-item-check to proceed anyway, or specify --expected-items
```

**Why this matters**: Running evaluation against production will produce skewed results because:
- Production has more items (more distractors)
- Different data distribution
- Queries designed specifically for golden DB items

### API Auto-Discovery

If the default port doesn't work, the script tries common ports:

```
Warning: Cannot connect to http://localhost:8001
Trying common ports...
Found API at http://localhost:8000
```

Ports tried: 8001 (golden), 8000 (production), 8080, 3000

### Error Handling

- **API unavailable**: Clear error message with setup instructions
- **Dataset missing**: Helpful error with expected path
- **Individual query failures**: Logged as "error" status, doesn't stop evaluation
- **Invalid metrics**: Handled gracefully (division by zero, empty sets)

## Regression Testing

### Baseline Establishment

1. **Create baseline**:
   ```bash
   # Run evaluation and note scores
   python scripts/evaluate_retrieval.py --verbose

   # Save baseline report
   cp data/eval/reports/eval_*_report.json baselines/baseline_v1.0.json
   ```

2. **Set thresholds**:
   ```python
   BASELINE_THRESHOLDS = {
       "mrr": 0.85,
       "precision@5": 0.65,
       "recall@5": 0.82,
       "ndcg@5": 0.83
   }
   ```

### Continuous Testing

Add to CI/CD pipeline:

```bash
#!/bin/bash
# ci/run_evaluation.sh

# Start golden API
DB_PATH=data/collections_golden.db uvicorn app.main:app --port 8001 &
API_PID=$!
sleep 3

# Run evaluation
python scripts/evaluate_retrieval.py --output-dir ./ci/reports

# Compare against baseline
python scripts/compare_evaluations.py \
  --baseline baselines/baseline_v1.0.json \
  --current ci/reports/eval_*_report.json \
  --fail-on-regression

# Cleanup
kill $API_PID
```

## Advanced Usage

### Comparing Multiple Runs

```bash
# Run before changes
python scripts/evaluate_retrieval.py --output-dir reports/before

# Make search improvements
# (edit BM25 parameters, change tokenization, etc.)

# Run after changes
python scripts/evaluate_retrieval.py --output-dir reports/after

# Compare JSON reports manually or with jq
jq '.summary' reports/before/eval_*_report.json
jq '.summary' reports/after/eval_*_report.json
```

### Testing Different Search Configurations

```python
# Test different BM25 k1 parameters
for k1 in [1.2, 1.5, 2.0]:
    # Update database.py with new k1 value
    # Rebuild search index
    # Run evaluation
    # Compare results
```

### Custom Evaluation Dataset

Create your own evaluation dataset:

```json
{
  "metadata": {
    "version": "2.0",
    "total_queries": 25,
    "query_types": {"custom": 25}
  },
  "queries": [
    {
      "query_id": "custom_001",
      "query_text": "your query here",
      "query_type": "custom",
      "expected_items": [
        {"item_id": "uuid-here", "relevance": "high"}
      ],
      "expected_count": 1
    }
  ]
}
```

Run with custom dataset:
```bash
python scripts/evaluate_retrieval.py --dataset my_custom_dataset.json
```

## Limitations

### Current Limitations

1. **Binary relevance in practice**: Though the system supports graded relevance (high/medium/low), most queries use only "high"

2. **Fixed K values**: Must rerun entire evaluation to test different K values (though you can specify multiple)

3. **No partial matching**: An item is either in expected_items or not; no notion of "partially relevant"

4. **Static dataset**: Dataset doesn't evolve automatically as collection grows

5. **No query difficulty scoring**: All queries weighted equally regardless of difficulty

### Future Enhancements

- [ ] Comparative evaluation (A/B test two search configurations)
- [ ] Per-query difficulty scoring
- [ ] Automated dataset expansion
- [ ] Real-time monitoring dashboard
- [ ] Integration with observability platforms (Langfuse, LangSmith)
- [ ] Query performance prediction
- [ ] Automatic threshold tuning

## Troubleshooting

### API Connection Issues

**Problem**: `Error: Could not find a running API server`

**Solutions**:
```bash
# Check if API is running
curl http://localhost:8001/health

# Start golden API
./scripts/run_golden_api.sh

# Check port
lsof -i :8001
```

### Item Count Mismatch

**Problem**: `WARNING: Item count mismatch!`

**Cause**: Running against wrong database

**Solutions**:
```bash
# Verify golden DB exists and has 55 items
sqlite3 data/collections_golden.db "SELECT COUNT(*) FROM items"

# Recreate golden DB if needed
python scripts/setup_golden_db.py --force

# Or skip check if intentional
python scripts/evaluate_retrieval.py --skip-item-check
```

### Low Scores on First Run

**Problem**: All metrics < 0.50

**Cause**: Search index not built or corrupted

**Solutions**:
```bash
# Rebuild search index
python scripts/setup_golden_db.py --force

# Verify FTS table exists
sqlite3 data/collections_golden.db "SELECT COUNT(*) FROM items_fts"
```

### Missing Dataset File

**Problem**: `Error: Dataset file not found`

**Solution**:
```bash
# Check if file exists
ls -l data/eval/retrieval_evaluation_dataset.json

# If missing, might need to create from golden analyses
# (Contact maintainer for dataset file)
```

## Related Documentation

- [RETRIEVAL.md](./RETRIEVAL.md) - BM25 search implementation details
- [DUAL_DATABASE.md](./DUAL_DATABASE.md) - Golden database setup and management
- [GOLDEN_DATASET.md](./GOLDEN_DATASET.md) - Golden dataset creation tool
- [API.md](./API.md) - API endpoints and usage

## References

### Information Retrieval Metrics

- Manning, C. D., Raghavan, P., & Schütze, H. (2008). *Introduction to Information Retrieval*. Cambridge University Press.
- Järvelin, K., & Kekäläinen, J. (2002). Cumulated gain-based evaluation of IR techniques. *ACM TOIS*, 20(4), 422-446.

### BM25 Algorithm

- Robertson, S., & Zaragoza, H. (2009). The Probabilistic Relevance Framework: BM25 and Beyond. *Foundations and Trends in Information Retrieval*, 3(4), 333-389.

### Evaluation Best Practices

- Sanderson, M. (2010). Test Collection Based Evaluation of Information Retrieval Systems. *Foundations and Trends in Information Retrieval*, 4(4), 247-375.
