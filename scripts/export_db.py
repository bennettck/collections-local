#!/usr/bin/env python3
"""
Export database to JSON format for version control.
This script exports both the database content and creates a manifest of images.
"""
import sqlite3
import json
import os
import hashlib
from pathlib import Path
from datetime import datetime, timezone

# Paths
DB_PATH = os.getenv("DATABASE_PATH", "./data/collections.db")
IMAGES_PATH = os.getenv("IMAGES_PATH", "./data/images")
EXPORT_DIR = "./data/exports"


def calculate_file_hash(filepath):
    """Calculate SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def export_database():
    """Export database tables to JSON."""
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    # Create export directory
    os.makedirs(EXPORT_DIR, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    export_data = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "database_path": DB_PATH,
        "tables": {}
    }

    # Export items table
    cursor = conn.execute("SELECT * FROM items ORDER BY created_at")
    items = [dict(row) for row in cursor.fetchall()]
    export_data["tables"]["items"] = items
    print(f"Exported {len(items)} items")

    # Export analyses table
    cursor = conn.execute("SELECT * FROM analyses ORDER BY created_at")
    analyses = [dict(row) for row in cursor.fetchall()]
    export_data["tables"]["analyses"] = analyses
    print(f"Exported {len(analyses)} analyses")

    conn.close()

    # Write to JSON file
    export_file = os.path.join(EXPORT_DIR, "database.json")
    with open(export_file, "w") as f:
        json.dump(export_data, f, indent=2)

    print(f"Database exported to {export_file}")
    return export_file


def export_images_manifest():
    """Create a manifest of all images with metadata."""
    if not os.path.exists(IMAGES_PATH):
        print(f"Images directory not found at {IMAGES_PATH}")
        return

    os.makedirs(EXPORT_DIR, exist_ok=True)

    manifest = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "images_path": IMAGES_PATH,
        "images": []
    }

    images_dir = Path(IMAGES_PATH)
    for img_file in sorted(images_dir.glob("*")):
        if img_file.is_file():
            stat = img_file.stat()
            manifest["images"].append({
                "filename": img_file.name,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "sha256": calculate_file_hash(img_file)
            })

    print(f"Found {len(manifest['images'])} images")

    # Write manifest
    manifest_file = os.path.join(EXPORT_DIR, "images_manifest.json")
    with open(manifest_file, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Images manifest exported to {manifest_file}")
    return manifest_file


if __name__ == "__main__":
    print("Starting database and images export...")
    print("=" * 50)
    export_database()
    print()
    export_images_manifest()
    print("=" * 50)
    print("Export complete!")
