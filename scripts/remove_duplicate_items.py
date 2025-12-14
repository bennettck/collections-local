"""
Remove duplicate items from the database based on original_filename.

Duplicate handling logic:
- For items with the same original_filename:
  - Keep all items that have golden records
  - If multiple items have golden records, keep only the most recently reviewed one
  - If no items have golden records, keep the oldest item (first by created_at)
  - Delete all other duplicates
"""

import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import get_db, delete_item
from utils.golden_dataset import load_golden_dataset


def parse_datetime(dt_str):
    """Parse ISO datetime string."""
    if dt_str.endswith('Z'):
        dt_str = dt_str[:-1]
    return datetime.fromisoformat(dt_str)


def remove_duplicates():
    """Remove duplicate items from database."""
    print("Loading golden dataset...")
    golden_data = load_golden_dataset()

    # Create mapping of item_id -> reviewed_at timestamp
    golden_records = {}
    for entry in golden_data.get('golden_analyses', []):
        item_id = entry.get('item_id')
        reviewed_at = entry.get('reviewed_at')
        if item_id and reviewed_at:
            golden_records[item_id] = parse_datetime(reviewed_at)

    print(f"Found {len(golden_records)} items with golden records\n")

    # Get all items from database
    print("Querying database for all items...")
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, original_filename, created_at
            FROM items
            ORDER BY original_filename, created_at
        """).fetchall()

    items = [dict(row) for row in rows]
    print(f"Found {len(items)} total items in database\n")

    # Group items by original_filename
    filename_groups = defaultdict(list)
    for item in items:
        filename = item['original_filename']
        if filename:  # Only consider items with a filename
            filename_groups[filename].append(item)

    # Find duplicates (groups with more than 1 item)
    duplicate_groups = {
        filename: items_list
        for filename, items_list in filename_groups.items()
        if len(items_list) > 1
    }

    if not duplicate_groups:
        print("No duplicate items found. Database is clean!")
        return

    print(f"Found {len(duplicate_groups)} filenames with duplicates:\n")

    total_to_delete = 0
    deletion_plan = []

    for filename, duplicate_items in duplicate_groups.items():
        print(f"Filename: {filename} ({len(duplicate_items)} copies)")

        # Find items with golden records in this group
        items_with_golden = [
            item for item in duplicate_items
            if item['id'] in golden_records
        ]

        # Determine which item to keep
        if items_with_golden:
            # Keep the most recently reviewed golden record
            items_with_golden.sort(
                key=lambda x: golden_records[x['id']],
                reverse=True
            )
            keep_item = items_with_golden[0]
            print(f"  ✓ Keeping item {keep_item['id'][:8]}... (has golden record from {golden_records[keep_item['id']].isoformat()})")
        else:
            # No golden records, keep the oldest item
            duplicate_items.sort(key=lambda x: x['created_at'])
            keep_item = duplicate_items[0]
            print(f"  ✓ Keeping item {keep_item['id'][:8]}... (oldest, created {keep_item['created_at']})")

        # Mark all others for deletion
        to_delete = [item for item in duplicate_items if item['id'] != keep_item['id']]

        for item in to_delete:
            has_golden = item['id'] in golden_records
            golden_note = f" [HAS GOLDEN RECORD from {golden_records[item['id']].isoformat()}]" if has_golden else ""
            print(f"  ✗ Will delete {item['id'][:8]}... (created {item['created_at']}){golden_note}")
            deletion_plan.append(item)

        total_to_delete += len(to_delete)
        print()

    print(f"Summary: Will delete {total_to_delete} duplicate items")

    if total_to_delete == 0:
        print("Nothing to delete!")
        return

    # Confirm deletion
    print("\n" + "="*60)
    response = input(f"Delete {total_to_delete} duplicate items? (yes/no): ").strip().lower()

    if response != 'yes':
        print("Cancelled. No items were deleted.")
        return

    # Perform deletions
    print("\nDeleting items...")
    deleted_count = 0

    for item in deletion_plan:
        try:
            delete_item(item['id'])
            deleted_count += 1
            print(f"  ✓ Deleted {item['id'][:8]}...")
        except Exception as e:
            print(f"  ✗ Failed to delete {item['id'][:8]}...: {e}")

    print(f"\n✓ Successfully deleted {deleted_count} duplicate items")
    print(f"Database cleanup complete!")


if __name__ == "__main__":
    remove_duplicates()
