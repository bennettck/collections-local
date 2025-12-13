"""
Golden dataset I/O operations.

Handles reading and writing the golden dataset JSON file with atomic writes
to prevent corruption.
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime


GOLDEN_PATH = Path("data/eval/golden_analyses.json")


def _get_empty_structure() -> Dict[str, Any]:
    """
    Create empty golden dataset structure with metadata.

    Returns:
        Dict with metadata and empty golden_analyses list
    """
    now = datetime.utcnow().isoformat() + "Z"
    return {
        "metadata": {
            "version": "1.0",
            "created_at": now,
            "last_updated": now,
            "total_items": 0
        },
        "golden_analyses": []
    }


def load_golden_dataset() -> Dict[str, Any]:
    """
    Load golden dataset from file or return empty structure.

    Returns:
        Golden dataset dictionary
    """
    if not GOLDEN_PATH.exists():
        return _get_empty_structure()

    try:
        with open(GOLDEN_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        # If file is corrupted, return empty structure
        return _get_empty_structure()


def save_golden_dataset(dataset: Dict[str, Any]) -> None:
    """
    Save golden dataset to file with atomic write.

    Uses temporary file + rename to prevent corruption.

    Args:
        dataset: Golden dataset dictionary to save
    """
    # Ensure directory exists
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Update metadata
    dataset["metadata"]["last_updated"] = datetime.utcnow().isoformat() + "Z"
    dataset["metadata"]["total_items"] = len(dataset.get("golden_analyses", []))

    # Atomic write: temp file + rename
    temp_path = GOLDEN_PATH.with_suffix('.tmp')
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(dataset, f, indent=2, ensure_ascii=False)

        # Atomic rename
        temp_path.replace(GOLDEN_PATH)
    except Exception as e:
        # Clean up temp file on error
        if temp_path.exists():
            temp_path.unlink()
        raise e


def get_golden_entry(item_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve golden dataset entry for a specific item.

    Args:
        item_id: Item UUID to look up

    Returns:
        Golden analysis entry dict or None if not found
    """
    dataset = load_golden_dataset()

    for entry in dataset.get("golden_analyses", []):
        if entry.get("item_id") == item_id:
            return entry

    return None


def has_golden_entry(item_id: str) -> bool:
    """
    Check if an item has a golden dataset entry.

    Args:
        item_id: Item UUID to check

    Returns:
        True if entry exists, False otherwise
    """
    return get_golden_entry(item_id) is not None


def update_golden_entry(item_id: str, entry: Dict[str, Any]) -> None:
    """
    Update or create golden dataset entry for an item.

    Args:
        item_id: Item UUID
        entry: Golden analysis entry dictionary
    """
    dataset = load_golden_dataset()

    # Ensure item_id is in the entry
    entry["item_id"] = item_id

    # Find and update existing entry, or append new one
    updated = False
    for i, existing_entry in enumerate(dataset.get("golden_analyses", [])):
        if existing_entry.get("item_id") == item_id:
            dataset["golden_analyses"][i] = entry
            updated = True
            break

    if not updated:
        # Add new entry
        if "golden_analyses" not in dataset:
            dataset["golden_analyses"] = []
        dataset["golden_analyses"].append(entry)

    save_golden_dataset(dataset)


def delete_golden_entry(item_id: str) -> bool:
    """
    Delete golden dataset entry for an item.

    Args:
        item_id: Item UUID to delete

    Returns:
        True if entry was deleted, False if not found
    """
    dataset = load_golden_dataset()

    original_count = len(dataset.get("golden_analyses", []))

    dataset["golden_analyses"] = [
        entry for entry in dataset.get("golden_analyses", [])
        if entry.get("item_id") != item_id
    ]

    new_count = len(dataset["golden_analyses"])

    if new_count < original_count:
        save_golden_dataset(dataset)
        return True

    return False
