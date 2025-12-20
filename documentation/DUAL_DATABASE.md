# Dual-Database Environment

This guide explains how to run the Collections App with separate production and golden databases for evaluation purposes.

## Overview

The dual-database environment allows you to run two instances of the Collections App API simultaneously:

- **Production Database** (`data/collections.db`) - Your full collection with all items
- **Golden Database** (`data/collections_golden.db`) - Curated subset of 55 items for testing and evaluation
- **Shared Images** (`data/images/`) - Both databases reference the same image files

This setup is designed for:
- Running retrieval evaluation tests against a known golden dataset
- Testing search and retrieval quality without affecting production data
- Comparing API behavior between full and curated datasets

## Setup

### 1. Create Golden Database

Create the golden database from your production database and the golden dataset JSON:

```bash
python3 scripts/setup_golden_db.py
```

This will:
- Create `data/collections_golden.db` with the same schema as production
- Copy 55 items from `data/eval/golden_analyses.json`
- Copy their latest analyses from production
- Build the search index
- Validate the setup (item count, index status)

### Options

Force overwrite existing golden database:
```bash
python3 scripts/setup_golden_db.py --force
```

Use custom paths:
```bash
python3 scripts/setup_golden_db.py \
    --golden-db /path/to/golden.db \
    --production-db /path/to/production.db
```

### 2. Run API with Golden Database

Start the golden API on port 8001:

```bash
./scripts/run_golden_api.sh
```

The script will:
- Validate that the golden database exists
- Show the item count for verification
- Start uvicorn on port 8001 with the golden database

The API will be available at `http://localhost:8001`.

Production API can still run simultaneously on port 8000:
```bash
uvicorn main:app --port 8000
```

## Using Scripts with Custom Databases

All scripts now support the `--db-path` parameter to work with any database:

### Export golden database
```bash
python3 scripts/export_db.py --db-path ./data/collections_golden.db
```

### Import to golden database
```bash
python3 scripts/import_db.py --db-path ./data/collections_golden.db
```

### Backfill on golden database
```bash
python3 scripts/backfill_golden_filenames.py --db-path ./data/collections_golden.db
```

### Resume batch analysis on golden database
```bash
python3 testing/resume_batch_analyze.py --db-path ./data/collections_golden.db
```

## Environment Variables

### DATABASE_PATH

Specifies which database to use (default: `./data/collections.db`)

```bash
# Run API with golden database
DATABASE_PATH=./data/collections_golden.db uvicorn main:app --port 8001

# Run script with golden database
DATABASE_PATH=./data/collections_golden.db python3 scripts/export_db.py
```

**CLI Parameter Priority**: `--db-path` overrides `DATABASE_PATH` environment variable when both are specified.

### IMAGES_PATH

Path to images directory (default: `./data/images`)

Images are shared between both databases - the same item_id references the same image file.

### GOLDEN_DB_PATH

Used by `run_golden_api.sh` to specify golden database location:

```bash
GOLDEN_DB_PATH=/path/to/custom.db ./scripts/run_golden_api.sh
```

### GOLDEN_API_PORT

Port for golden API (default: 8001):

```bash
GOLDEN_API_PORT=9000 ./scripts/run_golden_api.sh
```

## Architecture

### Database Context Manager

The `database.py` module provides a thread-local context manager for temporarily overriding the database path:

```python
from database import database_context, get_item

# Default behavior - uses DATABASE_PATH env var
item = get_item(item_id)

# Override database for specific operations
with database_context('/path/to/other.db'):
    item = get_item(item_id)  # Uses other.db
```

This allows scripts to work with any database without modifying global state or affecting other threads.

### Benefits
- Thread-safe for concurrent operations
- Clean, scoped overrides
- No breaking changes to existing code
- Works with all database module functions

## Common Workflows

### Rebuild Golden Database

When you update the golden dataset JSON:

```bash
# 1. Update golden dataset JSON via UI or manually
# 2. Recreate golden database
python3 scripts/setup_golden_db.py --force
# 3. Restart golden API
./scripts/run_golden_api.sh
```

### Run Evaluation

Run retrieval evaluation against the golden database:

```bash
# Start golden API
./scripts/run_golden_api.sh

# In another terminal, run evaluation
python3 testing/run_evaluation.py --api-url http://localhost:8001
```

### Compare Databases

Export and compare both databases:

```bash
# Export production
python3 scripts/export_db.py --db-path ./data/collections.db

# Export golden
python3 scripts/export_db.py --db-path ./data/collections_golden.db

# Compare exports
diff data/exports/database.json data/exports/database_golden.json
```

### Verify Item Counts

Check that both APIs are running correctly:

```bash
# Production count (should be > 55)
curl http://localhost:8000/items | jq '.total'

# Golden count (should be exactly 55)
curl http://localhost:8001/items | jq '.total'
```

### Test Search on Golden Database

```bash
curl -X POST http://localhost:8001/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Tokyo restaurants", "top_k": 5}'
```

## Troubleshooting

### Golden database not found

**Error**: `Golden database not found at ./data/collections_golden.db`

**Solution**: Run the setup script:
```bash
python3 scripts/setup_golden_db.py
```

### Images missing

**Symptom**: API returns 404 when accessing images

**Solution**: Check that images exist in `data/images/` with the correct item_id filenames:
```bash
ls -la data/images/ | head
```

Images are shared between databases, so if they exist for production, they should work for golden too.

### Search index out of sync

**Symptom**: Search returns unexpected results or no results

**Solution**: Rebuild the search index:

```python
from database import database_context, rebuild_search_index

with database_context('./data/collections_golden.db'):
    stats = rebuild_search_index()
    print(f"Indexed {stats['num_documents']} documents")
```

Or recreate the golden database:
```bash
python3 scripts/setup_golden_db.py --force
```

### Port already in use

**Error**: `Address already in use` when starting uvicorn

**Solution**: Kill existing process or use a different port:

```bash
# Kill process on port 8001
lsof -ti:8001 | xargs kill -9

# Or use different port
GOLDEN_API_PORT=9000 ./scripts/run_golden_api.sh
```

### Item count mismatch

**Symptom**: Golden database has fewer than 55 items after setup

**Cause**: Some items from golden dataset are missing in production DB or have no analyses

**Solution**: Check the setup script output for warnings about missing items. You may need to:
- Run analyses on missing items in production
- Update the golden dataset to remove items that no longer exist

### Both APIs accessing same database

**Symptom**: Changes in one API affect the other

**Cause**: Both APIs are pointing to the same database file

**Solution**: Verify environment variables:

```bash
# Check production API
ps aux | grep uvicorn

# Ensure run_golden_api.sh sets DATABASE_PATH correctly
cat scripts/run_golden_api.sh | grep DATABASE_PATH
```

## Best Practices

1. **Keep golden dataset small** - 55 items is ideal for quick evaluation tests
2. **Rebuild golden DB after curating** - Always recreate after updating golden dataset JSON
3. **Don't modify golden DB directly** - Always regenerate from golden dataset source
4. **Share images** - No need to duplicate image files, both DBs reference the same location
5. **Document expected results** - Track expected search results for regression testing

## Technical Details

### Database Schema

Both databases use identical schema:

- `items` table - Core item metadata
- `analyses` table - LLM analysis results with versioning
- `items_fts` table - FTS5 full-text search index

### Search Index

- Uses SQLite FTS5 with BM25 ranking
- Weighted fields (summary 3x, headline 2x, etc.)
- Rebuilt separately for each database
- Index coverage should be 100% (all items have analyses)

### File Organization

```
/workspaces/collections-local/
├── data/
│   ├── collections.db              # Production database
│   ├── collections_golden.db       # Golden database
│   ├── images/                     # Shared images
│   └── eval/
│       └── golden_analyses.json    # Golden dataset source
├── scripts/
│   ├── setup_golden_db.py          # Golden DB setup script
│   └── run_golden_api.sh           # Golden API launcher
└── documentation/
    └── DUAL_DATABASE.md            # This file
```

## See Also

- [scripts/README.md](../scripts/README.md) - Script usage documentation
- [RETRIEVAL.md](RETRIEVAL.md) - Retrieval system documentation
- Golden dataset curation UI: http://localhost:8000/golden-dataset
