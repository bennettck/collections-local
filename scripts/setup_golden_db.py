#!/usr/bin/env python3
"""
Setup golden database for evaluation.

This script:
1. Creates data/collections_golden.db with the same schema
2. Copies items from golden_analyses.json from production DB
3. Copies their latest analyses
4. Rebuilds search index
5. Validates the setup
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import (
    init_db, database_context, get_item, get_latest_analysis,
    create_item, create_analysis, rebuild_search_index, count_items
)
from utils.golden_dataset import load_golden_dataset


def setup_golden_database(
    golden_db_path: str,
    production_db_path: str,
    force: bool = False
):
    """Setup golden database from production and golden dataset.

    Args:
        golden_db_path: Path to golden database to create
        production_db_path: Path to production database to copy from
        force: If True, overwrite existing golden database

    Returns:
        True if setup successful, False otherwise
    """

    # Step 1: Check if golden DB exists
    if os.path.exists(golden_db_path):
        if not force:
            print(f"ERROR: Golden database already exists at {golden_db_path}")
            print("Use --force to overwrite")
            return False
        print(f"WARNING: Overwriting existing golden database")
        os.remove(golden_db_path)

    # Step 2: Create golden DB with schema
    print(f"Creating golden database at {golden_db_path}...")
    with database_context(golden_db_path):
        init_db()
    print("✓ Schema created")

    # Step 3: Load golden dataset
    print("\nLoading golden dataset...")
    golden_data = load_golden_dataset()
    golden_items = golden_data.get('golden_analyses', [])
    print(f"Found {len(golden_items)} items in golden dataset")

    if len(golden_items) == 0:
        print("ERROR: No items in golden dataset")
        return False

    # Step 4: Copy items and analyses from production
    print("\nCopying items from production database...")
    copied_count = 0
    missing_count = 0
    missing_items = []

    for golden_entry in golden_items:
        item_id = golden_entry['item_id']

        # Get item from production DB
        with database_context(production_db_path):
            item = get_item(item_id)
            analysis = get_latest_analysis(item_id)

        if not item:
            missing_count += 1
            missing_items.append(item_id)
            print(f"  ✗ Item {item_id[:8]}... not found in production DB")
            continue

        if not analysis:
            print(f"  ⚠ Item {item_id[:8]}... has no analysis, skipping")
            missing_count += 1
            continue

        # Copy to golden DB
        with database_context(golden_db_path):
            create_item(
                item_id=item['id'],
                filename=item['filename'],
                original_filename=item.get('original_filename'),
                file_path=item['file_path'],
                file_size=item.get('file_size'),
                mime_type=item.get('mime_type')
            )

            create_analysis(
                analysis_id=analysis['id'],
                item_id=analysis['item_id'],
                result=analysis['raw_response'],
                provider_used=analysis.get('provider_used'),
                model_used=analysis.get('model_used'),
                trace_id=analysis.get('trace_id')
            )

        copied_count += 1
        original_fn = item.get('original_filename', item_id[:8])
        print(f"  ✓ Copied {original_fn}")

    # Step 5: Rebuild search index
    print("\nRebuilding search index for golden database...")
    with database_context(golden_db_path):
        stats = rebuild_search_index()
    print(f"✓ Indexed {stats['num_documents']} documents")

    # Step 6: Validation
    print("\n" + "="*60)
    print("VALIDATION")
    print("="*60)

    with database_context(golden_db_path):
        total_items = count_items()

    print(f"Items in golden dataset:     {len(golden_items)}")
    print(f"Items copied successfully:   {copied_count}")
    print(f"Items missing/skipped:       {missing_count}")
    print(f"Items in golden database:    {total_items}")
    print(f"Search index documents:      {stats['num_documents']}")

    if missing_items:
        print(f"\nMissing items from production DB:")
        for item_id in missing_items[:10]:
            print(f"  - {item_id}")
        if len(missing_items) > 10:
            print(f"  ... and {len(missing_items) - 10} more")

    # Success criteria
    success = (total_items == copied_count == stats['num_documents'])

    if success:
        print("\n✓ Golden database setup complete!")
    else:
        print("\n⚠ Setup completed with warnings")

    return success


def main():
    parser = argparse.ArgumentParser(
        description="Setup golden database for evaluation"
    )
    parser.add_argument(
        '--golden-db',
        default='./data/collections_golden.db',
        help='Path for golden database (default: ./data/collections_golden.db)'
    )
    parser.add_argument(
        '--production-db',
        default=os.getenv("DATABASE_PATH", "./data/collections.db"),
        help='Path to production database (default: $DATABASE_PATH or ./data/collections.db)'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force overwrite if golden database exists'
    )

    args = parser.parse_args()

    print("="*60)
    print("Golden Database Setup")
    print("="*60)
    print(f"Production DB: {args.production_db}")
    print(f"Golden DB:     {args.golden_db}")
    print(f"Force:         {args.force}")
    print("="*60)
    print()

    success = setup_golden_database(
        golden_db_path=args.golden_db,
        production_db_path=args.production_db,
        force=args.force
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
