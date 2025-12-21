#!/usr/bin/env python3
import json
import os
import shutil
from pathlib import Path

# Paths
GOLDEN_JSON = "/workspaces/collections-local/data/eval/golden_analyses.json"
IMAGES_DIR = "/workspaces/collections-local/data/images"
OUTPUT_DIR = "/workspaces/collections-local/golden_dataset_images"

# Create output directory
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Load golden analyses
with open(GOLDEN_JSON, 'r') as f:
    data = json.load(f)

# Process each golden analysis item
copied_count = 0
missing_count = 0
missing_items = []

for item in data['golden_analyses']:
    item_id = item['item_id']
    original_filename = item['original_filename']

    # Try common image extensions (the stored files use .jpg even if original was .jpeg)
    possible_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']

    source_path = None
    for ext in possible_extensions:
        potential_source = os.path.join(IMAGES_DIR, f"{item_id}{ext}")
        if os.path.exists(potential_source):
            source_path = potential_source
            break

    if source_path:
        # Create new filename: original_filename (without extension) + item_id + extension
        original_name_no_ext = Path(original_filename).stem
        file_ext = Path(source_path).suffix
        new_filename = f"{original_name_no_ext}_{item_id}{file_ext}"
        dest_path = os.path.join(OUTPUT_DIR, new_filename)

        # Copy the file
        shutil.copy2(source_path, dest_path)
        copied_count += 1
        print(f"✓ Copied: {new_filename}")
    else:
        missing_count += 1
        missing_items.append(f"{original_filename} (ID: {item_id})")
        print(f"✗ Missing: {original_filename} (ID: {item_id})")

print(f"\n{'='*60}")
print(f"Summary:")
print(f"  Total items in golden dataset: {len(data['golden_analyses'])}")
print(f"  Successfully copied: {copied_count}")
print(f"  Missing images: {missing_count}")
print(f"  Output directory: {OUTPUT_DIR}")

if missing_items:
    print(f"\nMissing items:")
    for item in missing_items:
        print(f"  - {item}")
