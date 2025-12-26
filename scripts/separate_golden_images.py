#!/usr/bin/env python3
"""
Separate images into golden dataset and non-golden dataset groups.

Supports two matching modes:
1. SHA256 (default): Hashes entire file bytes including metadata
2. Visual (--visual): Uses perceptual hashing to compare only visual content,
   ignoring metadata like EXIF, download dates, etc.

Usage:
    python scripts/separate_golden_images.py --source /path/to/your/images
    python scripts/separate_golden_images.py --source /path/to/images --visual
    python scripts/separate_golden_images.py --source /path/to/images --output ./separated
    python scripts/separate_golden_images.py --source /path/to/images --dry-run
"""

import argparse
import hashlib
import shutil
from pathlib import Path
from typing import Dict, Tuple, Callable, Any

# Optional imports for visual hashing
try:
    from PIL import Image
    import imagehash
    VISUAL_HASH_AVAILABLE = True
except ImportError:
    VISUAL_HASH_AVAILABLE = False

# Image extensions to process
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic', '.heif'}

# Paths relative to project root
PROJECT_ROOT = Path(__file__).parent.parent
GOLDEN_IMAGES_DIR = PROJECT_ROOT / "data" / "eval" / "golden_dataset_images"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "eval" / "separated_images"


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA256 hash of file contents (includes metadata)."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def compute_visual_hash(file_path: Path) -> str:
    """
    Compute perceptual hash of image visual content only.

    Uses average hash (aHash) which is fast and ignores:
    - EXIF metadata
    - Download dates
    - File timestamps
    - Color profile differences

    Only compares the actual visual appearance of the image.
    """
    if not VISUAL_HASH_AVAILABLE:
        raise RuntimeError("Visual hashing requires 'Pillow' and 'imagehash' packages. "
                          "Install with: pip install Pillow imagehash")

    with Image.open(file_path) as img:
        # Use average hash - good balance of speed and accuracy
        # Hash size 16 gives 256 bits for better discrimination
        ahash = imagehash.average_hash(img, hash_size=16)
        return str(ahash)


def get_image_files(directory: Path) -> list[Path]:
    """Get all image files from a directory (non-recursive by default)."""
    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    image_files = []
    for file_path in directory.iterdir():
        if file_path.is_file() and file_path.suffix.lower() in IMAGE_EXTENSIONS:
            image_files.append(file_path)
    return sorted(image_files)


def get_image_files_recursive(directory: Path) -> list[Path]:
    """Get all image files from a directory recursively."""
    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    image_files = []
    for file_path in directory.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in IMAGE_EXTENSIONS:
            image_files.append(file_path)
    return sorted(image_files)


def build_golden_hash_set(
    golden_dir: Path,
    hash_func: Callable[[Path], str] = compute_file_hash
) -> Dict[str, Path]:
    """Build a set of hashes for all golden dataset images."""
    print(f"\n📂 Building hash index from golden dataset: {golden_dir}")

    golden_images = get_image_files(golden_dir)
    hash_to_path: Dict[str, Path] = {}

    for i, img_path in enumerate(golden_images, 1):
        try:
            file_hash = hash_func(img_path)
            hash_to_path[file_hash] = img_path
        except Exception as e:
            print(f"   ⚠️  Warning: Could not hash {img_path.name}: {e}")

        if i % 10 == 0:
            print(f"   Indexed {i}/{len(golden_images)} golden images...")

    print(f"   Found {len(hash_to_path)} images in golden dataset")
    return hash_to_path


def separate_images(
    source_dir: Path,
    golden_hashes: Dict[str, Path],
    output_dir: Path,
    hash_func: Callable[[Path], str] = compute_file_hash,
    recursive: bool = False,
    dry_run: bool = False,
    copy_mode: bool = True  # True = copy, False = move
) -> Tuple[list, list]:
    """
    Separate source images into golden and non-golden groups.

    Returns:
        Tuple of (golden_matches, non_golden_matches)
    """
    print(f"\n📂 Scanning source directory: {source_dir}")

    if recursive:
        source_images = get_image_files_recursive(source_dir)
    else:
        source_images = get_image_files(source_dir)

    print(f"   Found {len(source_images)} images to process")

    # Prepare output directories
    golden_output = output_dir / "in_golden_dataset"
    non_golden_output = output_dir / "not_in_golden_dataset"

    if not dry_run:
        golden_output.mkdir(parents=True, exist_ok=True)
        non_golden_output.mkdir(parents=True, exist_ok=True)

    golden_matches = []
    non_golden_matches = []

    print(f"\n🔍 Processing images...")
    for i, img_path in enumerate(source_images, 1):
        try:
            file_hash = hash_func(img_path)
        except Exception as e:
            print(f"   ⚠️  Warning: Could not hash {img_path.name}: {e}")
            non_golden_matches.append(img_path)
            continue

        if file_hash in golden_hashes:
            golden_matches.append((img_path, golden_hashes[file_hash]))
            dest_dir = golden_output
            status = "✓ GOLDEN"
        else:
            non_golden_matches.append(img_path)
            dest_dir = non_golden_output
            status = "✗ NOT IN GOLDEN"

        if not dry_run:
            dest_path = dest_dir / img_path.name
            # Handle duplicate filenames
            if dest_path.exists():
                stem = img_path.stem
                suffix = img_path.suffix
                counter = 1
                while dest_path.exists():
                    dest_path = dest_dir / f"{stem}_{counter}{suffix}"
                    counter += 1

            if copy_mode:
                shutil.copy2(img_path, dest_path)
            else:
                shutil.move(img_path, dest_path)

        # Progress indicator
        if i % 10 == 0 or i == len(source_images):
            print(f"   Processed {i}/{len(source_images)} images...")

    return golden_matches, non_golden_matches


def print_summary(
    golden_matches: list,
    non_golden_matches: list,
    output_dir: Path,
    dry_run: bool
):
    """Print a summary of the separation results."""
    total = len(golden_matches) + len(non_golden_matches)

    print("\n" + "=" * 60)
    print("📊 SEPARATION SUMMARY")
    print("=" * 60)

    print(f"\n📈 Statistics:")
    print(f"   Total images processed: {total}")
    print(f"   In golden dataset:      {len(golden_matches)} ({100*len(golden_matches)/total:.1f}%)" if total > 0 else "   In golden dataset:      0")
    print(f"   Not in golden dataset:  {len(non_golden_matches)} ({100*len(non_golden_matches)/total:.1f}%)" if total > 0 else "   Not in golden dataset:  0")

    if golden_matches:
        print(f"\n✓ Images IN golden dataset ({len(golden_matches)}):")
        for src_path, golden_path in golden_matches[:10]:
            print(f"   {src_path.name}")
            print(f"      → matches: {golden_path.name}")
        if len(golden_matches) > 10:
            print(f"   ... and {len(golden_matches) - 10} more")

    if non_golden_matches:
        print(f"\n✗ Images NOT in golden dataset ({len(non_golden_matches)}):")
        for img_path in non_golden_matches[:10]:
            print(f"   {img_path.name}")
        if len(non_golden_matches) > 10:
            print(f"   ... and {len(non_golden_matches) - 10} more")

    if dry_run:
        print(f"\n⚠️  DRY RUN - No files were copied/moved")
        print(f"   Run without --dry-run to actually separate files")
    else:
        print(f"\n📁 Output directories:")
        print(f"   Golden:     {output_dir / 'in_golden_dataset'}")
        print(f"   Non-golden: {output_dir / 'not_in_golden_dataset'}")


def main():
    parser = argparse.ArgumentParser(
        description="Separate images into golden dataset and non-golden dataset groups",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run to see what would happen
  python scripts/separate_golden_images.py --source ./my_images --dry-run

  # Use visual hashing (ignores metadata, compares pixels only)
  python scripts/separate_golden_images.py --source ./my_images --visual --dry-run

  # Actually separate images (copies them)
  python scripts/separate_golden_images.py --source ./my_images

  # Move instead of copy
  python scripts/separate_golden_images.py --source ./my_images --move

  # Custom output directory
  python scripts/separate_golden_images.py --source ./my_images --output ./sorted

  # Process subdirectories too
  python scripts/separate_golden_images.py --source ./my_images --recursive
        """
    )

    parser.add_argument(
        "--source", "-s",
        type=Path,
        required=True,
        help="Source directory containing images to separate"
    )

    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for separated images (default: {DEFAULT_OUTPUT_DIR})"
    )

    parser.add_argument(
        "--golden-dir", "-g",
        type=Path,
        default=GOLDEN_IMAGES_DIR,
        help=f"Golden dataset images directory (default: {GOLDEN_IMAGES_DIR})"
    )

    parser.add_argument(
        "--recursive", "-r",
        action="store_true",
        help="Recursively search source directory for images"
    )

    parser.add_argument(
        "--move", "-m",
        action="store_true",
        help="Move files instead of copying them"
    )

    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Show what would be done without actually copying/moving files"
    )

    parser.add_argument(
        "--visual", "-v",
        action="store_true",
        help="Use visual/perceptual hashing (ignores metadata, compares only pixel content). "
             "Requires: pip install Pillow imagehash"
    )

    args = parser.parse_args()

    # Validate paths
    if not args.source.exists():
        print(f"❌ Error: Source directory not found: {args.source}")
        return 1

    if not args.golden_dir.exists():
        print(f"❌ Error: Golden dataset directory not found: {args.golden_dir}")
        return 1

    # Select hash function
    if args.visual:
        if not VISUAL_HASH_AVAILABLE:
            print("❌ Error: Visual hashing requires 'Pillow' and 'imagehash' packages.")
            print("   Install with: pip install Pillow imagehash")
            return 1
        hash_func = compute_visual_hash
        hash_mode = "VISUAL (perceptual hash - ignores metadata)"
    else:
        hash_func = compute_file_hash
        hash_mode = "SHA256 (includes metadata)"

    print("🖼️  Image Separator: Golden Dataset vs Non-Golden")
    print("=" * 60)
    print(f"   Hash mode: {hash_mode}")

    # Build golden hash index
    golden_hashes = build_golden_hash_set(args.golden_dir, hash_func=hash_func)

    if not golden_hashes:
        print("❌ Error: No images found in golden dataset directory")
        return 1

    # Separate images
    golden_matches, non_golden_matches = separate_images(
        source_dir=args.source,
        golden_hashes=golden_hashes,
        output_dir=args.output,
        hash_func=hash_func,
        recursive=args.recursive,
        dry_run=args.dry_run,
        copy_mode=not args.move
    )

    # Print summary
    print_summary(golden_matches, non_golden_matches, args.output, args.dry_run)

    return 0


if __name__ == "__main__":
    exit(main())
