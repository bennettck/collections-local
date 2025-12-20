#!/usr/bin/env python3
"""
Resume batch image analysis from where it left off.
Checks the database for missing analyses and only runs those.

Usage:
    python resume_batch_analyze.py [--db-path PATH]

The script will:
1. Check all uploaded items in the database
2. Identify which provider/model combinations are missing for each item
3. Only analyze items missing specific analyses
"""

import sys
import os
import time
import sqlite3
import argparse
import httpx
from pathlib import Path

API_BASE = "http://localhost:8000"

# Model configurations to test
MODEL_CONFIGS = [
    {"name": "anthropic-default", "provider": "anthropic", "model": None},
    {"name": "openai-default", "provider": "openai", "model": None},
    {"name": "anthropic-opus", "provider": "anthropic", "model": "claude-opus-4-5"},
    {"name": "openai-gpt5", "provider": "openai", "model": "gpt-5-2025-08-07"},
]


def get_db_connection(db_path: str):
    """Create database connection.

    Args:
        db_path: Path to database file
    """
    return sqlite3.connect(db_path)


def get_all_items(db_path: str):
    """Get all items from database.

    Args:
        db_path: Path to database file
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, original_filename FROM items ORDER BY original_filename")
    items = [{"id": row[0], "filename": row[1]} for row in cursor.fetchall()]
    conn.close()
    return items


def get_existing_analyses(db_path: str):
    """Get all existing analyses grouped by item_id and provider/model.

    Args:
        db_path: Path to database file
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT item_id, provider_used, model_used
        FROM analyses
    """)

    analyses = {}
    for row in cursor.fetchall():
        item_id, provider, model = row
        if item_id not in analyses:
            analyses[item_id] = []
        analyses[item_id].append({
            "provider": provider,
            "model": model
        })

    conn.close()
    return analyses


def needs_analysis(item_id, existing_analyses, config):
    """Check if an item needs analysis for a specific config."""
    if item_id not in existing_analyses:
        return True

    # Determine the expected model name
    expected_model = config["model"]
    if expected_model is None:
        # For default models, check what the API actually uses
        # Anthropic default is claude-sonnet-4-5, OpenAI default is gpt-4o
        if config["provider"] == "anthropic":
            expected_model = "claude-sonnet-4-5"
        elif config["provider"] == "openai":
            expected_model = "gpt-4o"

    # Check if this provider/model combo exists
    for analysis in existing_analyses[item_id]:
        if (analysis["provider"] == config["provider"] and
            analysis["model"] == expected_model):
            return False

    return True


def analyze_image(client: httpx.Client, item_id: str, provider: str = None, model: str = None) -> dict:
    """Analyze an image with specified provider/model."""
    payload = {"force_reanalyze": True}
    if provider:
        payload["provider"] = provider
    if model:
        payload["model"] = model

    response = client.post(
        f"{API_BASE}/items/{item_id}/analyze",
        json=payload,
        timeout=240.0  # 4 minutes for reasoning models like GPT-5
    )
    response.raise_for_status()
    return response.json()


def main():
    parser = argparse.ArgumentParser(
        description="Resume batch image analysis from where it left off"
    )
    parser.add_argument(
        '--db-path',
        default=os.getenv("DATABASE_PATH", "./data/collections.db"),
        help='Path to database file (default: $DATABASE_PATH or ./data/collections.db)'
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Resume Batch Analysis Script")
    print("=" * 60)
    print(f"Database: {args.db_path}")

    # Check API health
    print("\nChecking API health...")
    with httpx.Client() as client:
        try:
            health = client.get(f"{API_BASE}/health")
            health.raise_for_status()
            print(f"API is healthy: {health.json()}")
        except Exception as e:
            print(f"API health check failed: {e}")
            print("Make sure the API is running: uvicorn main:app")
            sys.exit(1)

    # Get all items and existing analyses
    print("\nLoading data from database...")
    items = get_all_items(args.db_path)
    existing_analyses = get_existing_analyses(args.db_path)

    print(f"Found {len(items)} total items in database")
    print(f"Found {sum(len(a) for a in existing_analyses.values())} existing analyses")

    # Calculate what needs to be done
    print("\n" + "=" * 60)
    print("Analysis Status:")
    print("=" * 60)

    work_plan = {}
    for config in MODEL_CONFIGS:
        needed = []
        for item in items:
            if needs_analysis(item["id"], existing_analyses, config):
                needed.append(item)

        work_plan[config["name"]] = needed
        status = f"{len(items) - len(needed)}/{len(items)} complete"
        print(f"{config['name']:20s}: {status:15s} ({len(needed)} remaining)")

    total_work = sum(len(tasks) for tasks in work_plan.values())
    if total_work == 0:
        print("\n" + "=" * 60)
        print("All analyses are complete! Nothing to do.")
        print("=" * 60)
        return

    print(f"\nTotal analyses needed: {total_work}")
    print("\nStarting analysis in 3 seconds...")
    time.sleep(3)

    # Process each configuration
    with httpx.Client() as client:
        for config in MODEL_CONFIGS:
            needed = work_plan[config["name"]]

            if not needed:
                print(f"\n{config['name']}: Already complete, skipping")
                continue

            print("\n" + "=" * 60)
            print(f"Analyzing with {config['name']}")
            print(f"  Provider: {config['provider']}, Model: {config['model'] or 'default'}")
            print(f"  Items to process: {len(needed)}")
            print("=" * 60)

            successful = 0
            failed = 0

            for i, item in enumerate(needed, 1):
                try:
                    print(f"[{i}/{len(needed)}] Analyzing {item['filename']}...", end=" ", flush=True)
                    start = time.time()
                    analysis = analyze_image(
                        client,
                        item["id"],
                        provider=config["provider"],
                        model=config["model"]
                    )
                    elapsed = time.time() - start
                    category = analysis.get("category", "unknown")
                    print(f"OK ({elapsed:.1f}s) - Category: {category}")
                    successful += 1
                except httpx.HTTPStatusError as e:
                    print(f"FAILED: HTTP {e.response.status_code}")
                    failed += 1
                except Exception as e:
                    print(f"FAILED: {e}")
                    failed += 1

            print(f"\n{config['name']}: {successful} successful, {failed} failed")

    print("\n" + "=" * 60)
    print("COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
