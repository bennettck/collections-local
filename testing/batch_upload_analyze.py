#!/usr/bin/env python3
"""
Batch upload and analyze images using the Collections API.
Uploads all images from a folder and analyzes with multiple model configurations.

Usage:
    python batch_upload_analyze.py <images_directory>

Example:
    python batch_upload_analyze.py ./images/split_1
    python batch_upload_analyze.py /workspaces/collections-local/testing/images/split_2
"""

import argparse
import sys
import time
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


def get_image_files(images_dir: Path):
    """Get all image files from the specified directory."""
    extensions = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    files = []
    for f in images_dir.iterdir():
        if f.is_file() and f.suffix.lower() in extensions:
            files.append(f)
    return sorted(files)


def upload_image(client: httpx.Client, image_path: Path) -> dict:
    """Upload an image to the API."""
    with open(image_path, "rb") as f:
        files = {"file": (image_path.name, f, "image/jpeg")}
        response = client.post(f"{API_BASE}/items", files=files, timeout=30.0)
        response.raise_for_status()
        return response.json()


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
        timeout=120.0  # LLM calls can take a while
    )
    response.raise_for_status()
    return response.json()


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Batch upload and analyze images using the Collections API"
    )
    parser.add_argument(
        "images_dir",
        type=Path,
        help="Path to directory containing images to process"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    images_dir = args.images_dir.resolve()

    print("=" * 60)
    print("Batch Upload and Analysis Script")
    print("=" * 60)

    # Validate directory exists
    if not images_dir.exists():
        print(f"Error: Directory does not exist: {images_dir}")
        sys.exit(1)
    if not images_dir.is_dir():
        print(f"Error: Path is not a directory: {images_dir}")
        sys.exit(1)

    # Get image files
    image_files = get_image_files(images_dir)
    print(f"\nFound {len(image_files)} images in {images_dir}")

    if not image_files:
        print("No images found!")
        sys.exit(1)

    # Check API health
    with httpx.Client() as client:
        try:
            health = client.get(f"{API_BASE}/health")
            health.raise_for_status()
            print(f"API is healthy: {health.json()}")
        except Exception as e:
            print(f"API health check failed: {e}")
            sys.exit(1)

    # Upload all images first
    print("\n" + "=" * 60)
    print("PHASE 1: Uploading Images")
    print("=" * 60)

    uploaded_items = []
    with httpx.Client() as client:
        for i, image_path in enumerate(image_files, 1):
            try:
                print(f"[{i}/{len(image_files)}] Uploading {image_path.name}...", end=" ")
                item = upload_image(client, image_path)
                uploaded_items.append(item)
                print(f"OK - ID: {item['id'][:8]}...")
            except Exception as e:
                print(f"FAILED: {e}")

    print(f"\nUploaded {len(uploaded_items)} images successfully")

    # Analyze with each model configuration
    for config in MODEL_CONFIGS:
        print("\n" + "=" * 60)
        print(f"PHASE 2: Analyzing with {config['name']}")
        print(f"  Provider: {config['provider']}, Model: {config['model'] or 'default'}")
        print("=" * 60)

        successful = 0
        failed = 0

        with httpx.Client() as client:
            for i, item in enumerate(uploaded_items, 1):
                try:
                    print(f"[{i}/{len(uploaded_items)}] Analyzing {item['original_filename']}...", end=" ", flush=True)
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
                    print(f"FAILED: HTTP {e.response.status_code} - {e.response.text[:100]}")
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
