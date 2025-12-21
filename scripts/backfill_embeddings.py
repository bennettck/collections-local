#!/usr/bin/env python3
"""
Backfill embeddings for existing analyzed items.

Generates embeddings for all items that have been analyzed but don't yet have
embeddings stored. Uses batch processing to minimize API calls and avoid rate limits.

Usage:
    python scripts/backfill_embeddings.py
"""

import sys
import os

# Add parent directory to path to import database module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import rebuild_vector_index


if __name__ == "__main__":
    result = rebuild_vector_index()
    print(f"Generated {result['embedded_count']} embeddings")
    print(f"Skipped {result['skipped_count']} existing embeddings")
