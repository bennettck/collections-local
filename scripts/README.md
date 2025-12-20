# Database Export/Import Scripts

These scripts allow you to version control your SQLite database and images using git.

## How It Works

The system automatically exports your database to JSON before each commit:

1. **Pre-commit hook** (`../.git/hooks/pre-commit`) runs automatically before each commit
2. **export_db.py** exports the database to `data/exports/database.json` and creates an image manifest
3. Both exports and images are added to the commit automatically

## Files Created

- `data/exports/database.json` - All database tables in JSON format
- `data/exports/images_manifest.json` - Metadata for all images (filename, size, hash)
- `data/images/*.jpg` - Actual image files (tracked in git)

## Manual Export

To manually export the database (without committing):

```bash
python3 scripts/export_db.py
```

## Restore from Export

To restore the database from a JSON export:

```bash
python3 scripts/import_db.py
```

This will:
- Clear the existing database
- Import all items and analyses from `data/exports/database.json`
- Verify images against the manifest

## Version Control Strategy

- ✅ **Tracked in git**: JSON exports, images, image manifest
- ❌ **NOT tracked**: Binary `.db` files (excluded via `.gitignore`)

This allows you to:
- View data changes in git diffs (human-readable JSON)
- Roll back to any previous state
- Track image changes with SHA256 hashes
- Restore your entire collection from any commit

## Restoring to a Previous Version

```bash
# Checkout a previous commit's exports
git checkout <commit-hash> data/exports/

# Restore the database from that export
python3 scripts/import_db.py

# Checkout the images from that commit
git checkout <commit-hash> data/images/
```

---

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
# Standard run against golden instance (must be running on port 8001)
python scripts/evaluate_retrieval.py

# Verbose output with detailed progress
python scripts/evaluate_retrieval.py --verbose
```

### Prerequisites

1. **Start the golden API** on port 8001:
   ```bash
   ./scripts/run_golden_api.sh
   ```

2. **Ensure you have the evaluation dataset**:
   - `data/eval/retrieval_evaluation_dataset.json` (50 test queries)

### How It Works

1. **Validates API connection** - Finds running API server (tries 8001, 8000, 8080, 3000)
2. **Verifies item count** - Ensures you're testing against the golden DB (55 items)
3. **Runs all queries** - Executes 50 test queries against the search endpoint
4. **Calculates metrics** - Computes Precision@K, Recall@K, MRR, NDCG@K
5. **Generates reports** - Creates markdown and JSON reports with detailed results

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
  --port PORT              API port (default: 8001)
  --base-url URL          Full base URL (overrides port)
  --dataset PATH          Evaluation dataset path
  --output-dir PATH       Report output directory (default: data/eval/reports)
  --top-k VALUES          K values for metrics (default: 1,3,5,10)
  --expected-items N      Expected DB items (default: 55)
  --skip-item-check       Skip item count validation
  --verbose               Show detailed progress
```

### Examples

```bash
# Run against production (skip item count check)
python scripts/evaluate_retrieval.py --port 8000 --skip-item-check

# Custom K values
python scripts/evaluate_retrieval.py --top-k 1,5,10,20

# Remote server
python scripts/evaluate_retrieval.py --base-url http://192.168.1.100:8001

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
✓ API endpoint: http://localhost:8001
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

- **Item count validation** - Checks that DB has exactly 55 items (golden dataset size)
- **Port auto-discovery** - Tries common ports if default fails
- **Clear warnings** - Shows warning if item count doesn't match expected

Use `--skip-item-check` to run against production anyway.

---

# Golden Database Setup

The golden database is a curated subset of your collection (55 items) used for evaluation and testing.

## Setup Golden Database

Create the golden database from your production database:

```bash
python3 scripts/setup_golden_db.py
```

This will:
- Create `data/collections_golden.db`
- Copy 55 items from `data/eval/golden_analyses.json`
- Build the search index
- Validate the setup

Force overwrite existing golden database:
```bash
python3 scripts/setup_golden_db.py --force
```

## Run Golden API

Start the API server with the golden database on port 8001:

```bash
./scripts/run_golden_api.sh
```

The golden API will run on `http://localhost:8001` while production runs on `http://localhost:8000`.

## Database Parameter

All scripts now support `--db-path` to work with any database:

```bash
# Export golden database
python3 scripts/export_db.py --db-path ./data/collections_golden.db

# Import to golden database
python3 scripts/import_db.py --db-path ./data/collections_golden.db

# Backfill golden database
python3 scripts/backfill_golden_filenames.py --db-path ./data/collections_golden.db

# Resume batch analysis on golden database
python3 testing/resume_batch_analyze.py --db-path ./data/collections_golden.db
```

**Default behavior**: Without `--db-path`, scripts use `$DATABASE_PATH` environment variable or `./data/collections.db`.

## Environment Variables

- `DATABASE_PATH` - Database file path (default: `./data/collections.db`)
- `IMAGES_PATH` - Images directory (default: `./data/images`)
- `GOLDEN_DB_PATH` - Golden database path for `run_golden_api.sh`
- `GOLDEN_API_PORT` - Golden API port (default: `8001`)

## Documentation

For complete dual-database documentation, see [DUAL_DATABASE.md](../documentation/DUAL_DATABASE.md).
