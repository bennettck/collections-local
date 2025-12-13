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

# Run evaluation (coming soon)
python scripts/run_evaluation.py
```
