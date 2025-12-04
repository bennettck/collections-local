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
