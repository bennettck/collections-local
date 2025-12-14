"""
Backfill original_filename for all existing golden dataset records.

This script reads each golden record, looks up the item_id in the database,
and adds the original_filename field to the golden record.
"""

import sys
from pathlib import Path

# Add parent directory to path so we can import from the project
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.golden_dataset import load_golden_dataset, save_golden_dataset
from database import get_item


def backfill_original_filenames():
    """Backfill original_filename for all golden records."""
    print("Loading golden dataset...")
    dataset = load_golden_dataset()

    golden_analyses = dataset.get('golden_analyses', [])
    total = len(golden_analyses)

    if total == 0:
        print("No golden records found. Nothing to backfill.")
        return

    print(f"Found {total} golden records to backfill")

    updated_count = 0
    missing_count = 0

    for i, entry in enumerate(golden_analyses, 1):
        item_id = entry.get('item_id')

        if not item_id:
            print(f"  [{i}/{total}] Warning: Entry has no item_id, skipping")
            continue

        # Check if already has original_filename
        if entry.get('original_filename'):
            print(f"  [{i}/{total}] Item {item_id[:8]}... already has original_filename: {entry['original_filename']}")
            continue

        # Look up item in database
        item = get_item(item_id)

        if not item:
            print(f"  [{i}/{total}] WARNING: Item {item_id} not found in database!")
            missing_count += 1
            continue

        original_filename = item.get('original_filename')

        if original_filename:
            entry['original_filename'] = original_filename
            updated_count += 1
            print(f"  [{i}/{total}] ✓ Updated {item_id[:8]}... -> {original_filename}")
        else:
            print(f"  [{i}/{total}] Warning: Item {item_id[:8]}... has no original_filename in database")
            missing_count += 1

    # Save updated dataset
    if updated_count > 0:
        print(f"\nSaving updated golden dataset...")
        save_golden_dataset(dataset)
        print(f"✓ Successfully backfilled {updated_count} records")
    else:
        print(f"\nNo records needed updating")

    if missing_count > 0:
        print(f"⚠ Warning: {missing_count} records could not be updated (item not found or no filename)")

    print("\nBackfill complete!")


if __name__ == "__main__":
    backfill_original_filenames()
