# Evaluation Scripts

## Create Golden Test Set

The `create_test_set.py` script helps you interactively build a golden test dataset for evaluating the retrieval system.

### Quick Start

```bash
python scripts/create_test_set.py
```

### How It Works

1. **Shows random items** from your collection with full details
2. **Helps you write queries** for each item with natural language
3. **Automatically records ground truth** (item IDs, categories, etc.)
4. **Saves to `data/eval/test_queries.json`**

### Interactive Example

```
🔍 Golden Test Set Builder

Options:
  1. Browse random items from all categories
  2. Browse items from a specific category

How many items to browse? [10]: 5

════════════════════════════════════════
ITEM 1
════════════════════════════════════════
Category: Food
Headline: Tofuya Ukai dining spot beneath Tokyo Tower
Summary: Beautiful restaurant beneath Tokyo Tower...

Create a query for this item?
(y)es, (n)o, (m)ulti-item, (q)uit [y]: y

Query: What restaurants are in Tokyo?
Query Type: 1 (location_search)
Reference answer (optional): Tofuya Ukai

✓ Created query q001
```

### Features

#### Query Creation Modes

- **Single-item** (`y`) - One query → one item
- **Multi-item** (`m`) - One query → multiple items (e.g., "all Tokyo restaurants")
- **Skip** (`n`) - Skip current item
- **Quit** (`q`) - Save and exit

#### Query Types

1. **location_search** - "restaurants in Tokyo"
2. **category_search** - "beauty products"
3. **specific_question** - "what perfume brands..."
4. **object_content** - "images with text"
5. **complex_multi_part** - "Japanese food and shopping"

### Output Format

Creates `data/eval/test_queries.json`:

```json
{
  "queries": [
    {
      "id": "q001",
      "query": "What restaurants are in Tokyo?",
      "type": "location_search",
      "ground_truth_items": ["item-id-1", "item-id-2"],
      "expected_category": "Food",
      "min_expected_results": 2,
      "reference_answer": "Tofuya Ukai"
    }
  ]
}
```

### Best Practices

✅ **Do:**
- Create 20-30 diverse queries
- Use natural language
- Include various query types
- Add reference answers for key queries

❌ **Don't:**
- Create only one query type
- Use overly specific/technical queries
- Skip categories you want to evaluate

### Keyboard Shortcuts

- `y` - Create query
- `n` - Skip item
- `m` - Multi-item query
- `q` - Quit
- `Ctrl+C` - Cancel current input

### Next Steps

After creating queries:

```bash
# Review the test set
cat data/eval/test_queries.json | python -m json.tool

# Run evaluation (see below)
python scripts/evaluate_retrieval.py
```

## Evaluate Retrieval Quality

The `evaluate_retrieval.py` script measures search quality using standard Information Retrieval metrics.

### Quick Start

```bash
# Standard run against golden database (uses subdomain routing)
python scripts/evaluate_retrieval.py

# Verbose output with detailed progress
python scripts/evaluate_retrieval.py --verbose
```

### Prerequisites

1. **Start the API server** on port 8000:
   ```bash
   uvicorn main:app --port 8000
   ```

   The evaluation script automatically uses golden.localhost subdomain routing to access the golden database.

2. **Ensure you have the evaluation dataset**:
   - `data/eval/retrieval_evaluation_dataset.json` (50 test queries)

### How It Works

1. **Validates API connection** - Finds running API server (tries 8000, 8001, 8080, 3000)
2. **Routes to golden database** - Uses golden.localhost subdomain routing (via Host header)
3. **Verifies item count** - Ensures you're testing against the golden DB (55 items)
4. **Runs all queries** - Executes 50 test queries against the search endpoint
5. **Calculates metrics** - Computes Precision@K, Recall@K, MRR, NDCG@K
6. **Generates reports** - Creates markdown and JSON reports with detailed results

### Metrics Calculated

For each K value (1, 3, 5, 10):

- **Precision@K** - Of the top K results, what fraction are relevant?
- **Recall@K** - Of all relevant items, what fraction appear in top K?
- **NDCG@K** - Normalized Discounted Cumulative Gain (accounts for ranking quality)
- **MRR** - Mean Reciprocal Rank (average of 1/rank of first relevant result)

### Command-Line Options

```bash
python scripts/evaluate_retrieval.py [OPTIONS]

Options:
  --port PORT                API port (default: 8000)
  --base-url URL            Full base URL (overrides port)
  --use-golden-subdomain    Use golden.localhost routing (default: True)
  --no-golden-subdomain     Disable golden routing (test against production)
  --dataset PATH            Evaluation dataset path
  --output-dir PATH         Report output directory (default: data/eval/reports)
  --top-k VALUES            K values for metrics (default: 1,3,5,10)
  --expected-items N        Expected DB items (default: 55)
  --skip-item-check         Skip item count validation
  --verbose                 Show detailed progress
```

### Examples

```bash
# Run against golden database (default)
python scripts/evaluate_retrieval.py

# Run against production database
python scripts/evaluate_retrieval.py --no-golden-subdomain --skip-item-check

# Custom K values
python scripts/evaluate_retrieval.py --top-k 1,5,10,20

# Remote server
python scripts/evaluate_retrieval.py --base-url http://192.168.1.100:8000

# Custom output location
python scripts/evaluate_retrieval.py --output-dir ./my_reports
```

### Output Reports

Creates two timestamped files in `data/eval/reports/`:

1. **`eval_YYYYMMDD_HHMMSS_report.md`** - Human-readable markdown report
   - Summary metrics table
   - Breakdown by query type
   - Detailed results for all 50 queries

2. **`eval_YYYYMMDD_HHMMSS_report.json`** - Machine-readable JSON
   - Full metric data
   - Individual query results
   - Timing statistics
   - Configuration details

### Sample Output

```
============================================================
Retrieval Evaluation Script
============================================================
✓ API endpoint: http://localhost:8000
✓ Item count validated: 55 items

Loaded dataset: 50 queries

Evaluating 50 queries...
  Progress: 50/50 (100%)
Completed in 8.43s

✓ Reports generated:
  - data/eval/reports/eval_20241214_153022_report.json
  - data/eval/reports/eval_20241214_153022_report.md

============================================================
Evaluation complete!
============================================================
```

### Safety Features

The script prevents accidental evaluation against production:

- **Golden subdomain routing** - Automatically routes to golden database by default
- **Item count validation** - Checks that DB has exactly 55 items (golden dataset size)
- **Port auto-discovery** - Tries common ports if default fails
- **Clear warnings** - Shows warning if item count doesn't match expected

Use `--no-golden-subdomain --skip-item-check` to run against production instead.
