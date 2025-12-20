#!/bin/bash
# Run Collections App API with golden database on port 8001

set -e

GOLDEN_DB_PATH="${GOLDEN_DB_PATH:-./data/collections_golden.db}"
IMAGES_PATH="${IMAGES_PATH:-./data/images}"
PORT="${GOLDEN_API_PORT:-8001}"

echo "=================================================="
echo "Starting Collections App API (Golden Database)"
echo "=================================================="
echo "Golden DB: $GOLDEN_DB_PATH"
echo "Images:    $IMAGES_PATH"
echo "Port:      $PORT"
echo "=================================================="

# Validation: Check if golden database exists
if [ ! -f "$GOLDEN_DB_PATH" ]; then
    echo ""
    echo "ERROR: Golden database not found at $GOLDEN_DB_PATH"
    echo ""
    echo "Please run the setup script first:"
    echo "  python3 scripts/setup_golden_db.py"
    echo ""
    exit 1
fi

# Validation: Check if images directory exists
if [ ! -d "$IMAGES_PATH" ]; then
    echo ""
    echo "ERROR: Images directory not found at $IMAGES_PATH"
    echo ""
    exit 1
fi

# Count items in golden DB for info
ITEM_COUNT=$(sqlite3 "$GOLDEN_DB_PATH" "SELECT COUNT(*) FROM items;" 2>/dev/null || echo "unknown")
echo ""
echo "Golden database contains $ITEM_COUNT items"
echo ""
echo "Starting uvicorn..."
echo "API will be available at: http://localhost:$PORT"
echo "Press Ctrl+C to stop"
echo ""

# Export environment variables and run uvicorn
export DATABASE_PATH="$GOLDEN_DB_PATH"
export IMAGES_PATH="$IMAGES_PATH"

uvicorn main:app --host 0.0.0.0 --port "$PORT" --reload
