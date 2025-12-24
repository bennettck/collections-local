#!/usr/bin/env python3
"""Remove vec_items virtual table from databases.

This migration script removes the sqlite-vec vec_items table which is no longer
needed after migrating to Chroma for vector storage.

Usage:
    python scripts/migrate_remove_vec_items.py
"""

# Use pysqlite3 if available (for extension support)
try:
    import pysqlite3.dbapi2 as sqlite3
except ImportError:
    import sqlite3

import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


def remove_vec_items(db_path: str):
    """Remove vec_items virtual table."""
    print(f"Processing: {db_path}")

    if not os.path.exists(db_path):
        print(f"  ⚠️  Database not found: {db_path}")
        return False

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Load sqlite-vec extension (needed to drop virtual table)
        try:
            import sqlite_vec
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
        except ImportError:
            print(f"  ⚠️  sqlite-vec not available, cannot drop vec_items")
            return False

        # Check if table exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='vec_items'
        """)

        if cursor.fetchone():
            cursor.execute("DROP TABLE IF EXISTS vec_items")
            conn.commit()
            print(f"  ✓ Removed vec_items from {db_path}")
        else:
            print(f"  → vec_items doesn't exist in {db_path} (already migrated)")

        return True

    except Exception as e:
        print(f"  ✗ Error removing vec_items from {db_path}: {e}")
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    print("\n" + "="*70)
    print("MIGRATION: Remove sqlite-vec vec_items table")
    print("="*70)
    print()
    print("This migration removes the vec_items virtual table which is no longer")
    print("needed after migrating to Chroma for vector storage.")
    print()

    # Get database paths
    prod_db_path = os.getenv("PROD_DATABASE_PATH", "./data/collections.db")
    golden_db_path = os.getenv("GOLDEN_DATABASE_PATH", "./data/collections_golden.db")

    success = True

    # Migrate both databases
    print("Migrating PROD database:")
    if not remove_vec_items(prod_db_path):
        success = False
    print()

    print("Migrating GOLDEN database:")
    if not remove_vec_items(golden_db_path):
        success = False
    print()

    if success:
        print("="*70)
        print("✓ Migration complete!")
        print("="*70)
        print()
        print("The vec_items table has been removed from all databases.")
        print("Vector search now exclusively uses Chroma.")
        print()
    else:
        print("="*70)
        print("⚠️  Migration completed with warnings")
        print("="*70)
        print()
        print("Some databases could not be migrated. Check the output above.")
        print()
        sys.exit(1)
