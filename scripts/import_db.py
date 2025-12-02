#!/usr/bin/env python3
"""
Import database from JSON export.
This script restores the database from the exported JSON files.
"""
import sqlite3
import json
import os
from datetime import datetime

# Paths
DB_PATH = os.getenv("DATABASE_PATH", "./data/collections.db")
EXPORT_DIR = "./data/exports"


def import_database():
    """Import database from JSON export."""
    export_file = os.path.join(EXPORT_DIR, "database.json")

    if not os.path.exists(export_file):
        print(f"Export file not found at {export_file}")
        return False

    # Load export data
    with open(export_file, "r") as f:
        export_data = json.load(f)

    print(f"Importing data from export created at: {export_data['exported_at']}")

    # Ensure database directory exists
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    # Create connection
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")  # Temporarily disable for import

    try:
        # Clear existing data
        conn.execute("DELETE FROM analyses")
        conn.execute("DELETE FROM items")
        print("Cleared existing data")

        # Import items
        items = export_data["tables"]["items"]
        for item in items:
            conn.execute(
                """INSERT INTO items (id, filename, original_filename, file_path,
                   file_size, mime_type, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item["id"], item["filename"], item.get("original_filename"),
                    item["file_path"], item.get("file_size"), item.get("mime_type"),
                    item["created_at"], item["updated_at"]
                )
            )
        print(f"Imported {len(items)} items")

        # Import analyses
        analyses = export_data["tables"]["analyses"]
        for analysis in analyses:
            conn.execute(
                """INSERT INTO analyses (id, item_id, version, category, summary,
                   raw_response, provider_used, model_used, trace_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    analysis["id"], analysis["item_id"], analysis["version"],
                    analysis.get("category"), analysis.get("summary"),
                    analysis.get("raw_response"), analysis.get("provider_used"),
                    analysis.get("model_used"), analysis.get("trace_id"),
                    analysis["created_at"]
                )
            )
        print(f"Imported {len(analyses)} analyses")

        conn.commit()
        print(f"\nSuccessfully restored database to {DB_PATH}")
        return True

    except Exception as e:
        conn.rollback()
        print(f"Error during import: {e}")
        return False

    finally:
        conn.execute("PRAGMA foreign_keys = ON")  # Re-enable foreign keys
        conn.close()


def verify_images():
    """Verify images against manifest."""
    manifest_file = os.path.join(EXPORT_DIR, "images_manifest.json")

    if not os.path.exists(manifest_file):
        print(f"Images manifest not found at {manifest_file}")
        return

    with open(manifest_file, "r") as f:
        manifest = json.load(f)

    print(f"\nImage manifest from: {manifest['exported_at']}")
    print(f"Expected {len(manifest['images'])} images in {manifest['images_path']}")

    # Check which images exist
    images_path = manifest['images_path']
    existing = 0
    missing = []

    for img in manifest['images']:
        img_path = os.path.join(images_path, img['filename'])
        if os.path.exists(img_path):
            existing += 1
        else:
            missing.append(img['filename'])

    print(f"Found {existing}/{len(manifest['images'])} images")

    if missing:
        print(f"\nWarning: {len(missing)} images are missing:")
        for filename in missing[:10]:  # Show first 10
            print(f"  - {filename}")
        if len(missing) > 10:
            print(f"  ... and {len(missing) - 10} more")


if __name__ == "__main__":
    print("Starting database import...")
    print("=" * 50)

    if import_database():
        verify_images()

    print("=" * 50)
    print("Import complete!")
