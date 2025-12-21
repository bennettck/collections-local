"""Upload and manage datasets in LangSmith for evaluation."""

import json
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

from langsmith import Client
from langsmith.schemas import Example

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_analysis_dataset(
    dataset_name: str = "golden-analyses",
    golden_data_path: str = "./data/eval/golden_analyses.json"
) -> str:
    """
    Create or update LangSmith dataset from golden analyses.

    Args:
        dataset_name: Name for the dataset in LangSmith
        golden_data_path: Path to golden_analyses.json

    Returns:
        Dataset ID/name
    """
    logger.info(f"Loading golden dataset from {golden_data_path}")

    # Load golden dataset
    with open(golden_data_path, 'r') as f:
        golden_data = json.load(f)

    # Initialize LangSmith client
    client = Client()

    # Check if dataset exists
    try:
        dataset = client.read_dataset(dataset_name=dataset_name)
        logger.info(f"Dataset '{dataset_name}' already exists with {len(list(client.list_examples(dataset_id=dataset.id)))} examples")
        # Delete existing to recreate (for simplicity)
        client.delete_dataset(dataset_id=dataset.id)
        logger.info(f"Deleted existing dataset")
    except Exception:
        logger.info(f"Creating new dataset '{dataset_name}'")

    # Create dataset
    dataset = client.create_dataset(
        dataset_name=dataset_name,
        description="Golden dataset of curated image analyses for evaluation"
    )

    # Convert to LangSmith Examples
    examples = []
    for item_id, data in golden_data.items():
        example = Example(
            inputs={
                "item_id": item_id,
                "original_filename": data.get("original_filename")
            },
            outputs={
                "category": data.get("category"),
                "subcategories": data.get("subcategories", []),
                "headline": data.get("headline"),
                "summary": data.get("summary"),
                "image_details": data.get("image_details", {}),
                "media_metadata": data.get("media_metadata", {})
            },
            metadata={
                "reviewed_at": data.get("reviewed_at"),
                "source_analyses_count": data.get("source_analyses_count", 0),
                "source_analysis_ids": data.get("source_analysis_ids", [])
            }
        )
        examples.append(example)

    # Upload examples in batches
    logger.info(f"Uploading {len(examples)} examples to LangSmith...")
    client.create_examples(
        inputs=[ex.inputs for ex in examples],
        outputs=[ex.outputs for ex in examples],
        metadata=[ex.metadata for ex in examples],
        dataset_id=dataset.id
    )

    logger.info(f"✓ Successfully created dataset '{dataset_name}' with {len(examples)} examples")
    logger.info(f"  Dataset ID: {dataset.id}")
    logger.info(f"  View at: https://smith.langchain.com/datasets/{dataset.id}")

    return dataset.name


def create_retrieval_dataset(
    dataset_name: str = "retrieval-queries",
    retrieval_data_path: str = "./data/eval/retrieval_evaluation_dataset.json"
) -> str:
    """
    Create or update LangSmith dataset from retrieval evaluation queries.

    Args:
        dataset_name: Name for the dataset in LangSmith
        retrieval_data_path: Path to retrieval_evaluation_dataset.json

    Returns:
        Dataset ID/name
    """
    logger.info(f"Loading retrieval dataset from {retrieval_data_path}")

    # Load retrieval dataset
    with open(retrieval_data_path, 'r') as f:
        retrieval_data = json.load(f)

    # Initialize LangSmith client
    client = Client()

    # Check if dataset exists
    try:
        dataset = client.read_dataset(dataset_name=dataset_name)
        logger.info(f"Dataset '{dataset_name}' already exists")
        # Delete existing to recreate
        client.delete_dataset(dataset_id=dataset.id)
        logger.info(f"Deleted existing dataset")
    except Exception:
        logger.info(f"Creating new dataset '{dataset_name}'")

    # Create dataset
    dataset = client.create_dataset(
        dataset_name=dataset_name,
        description="Retrieval evaluation queries with expected results"
    )

    # Convert to LangSmith Examples
    examples = []
    for query_data in retrieval_data:
        example = Example(
            inputs={
                "query": query_data.get("query"),
                "search_type": "bm25"  # Default, can be overridden
            },
            outputs={
                "expected_items": query_data.get("expected_items", []),
                "expected_relevance": query_data.get("expected_relevance", {})
            },
            metadata={
                "query_type": query_data.get("query_type"),
                "expected_count": len(query_data.get("expected_items", []))
            }
        )
        examples.append(example)

    # Upload examples
    logger.info(f"Uploading {len(examples)} examples to LangSmith...")
    client.create_examples(
        inputs=[ex.inputs for ex in examples],
        outputs=[ex.outputs for ex in examples],
        metadata=[ex.metadata for ex in examples],
        dataset_id=dataset.id
    )

    logger.info(f"✓ Successfully created dataset '{dataset_name}' with {len(examples)} examples")
    logger.info(f"  Dataset ID: {dataset.id}")
    logger.info(f"  View at: https://smith.langchain.com/datasets/{dataset.id}")

    return dataset.name


if __name__ == "__main__":
    """Run dataset upload as standalone script."""
    import sys

    try:
        # Create both datasets
        logger.info("=" * 60)
        logger.info("Creating LangSmith Datasets")
        logger.info("=" * 60)

        # Upload golden analyses
        analysis_dataset = create_analysis_dataset()

        print()

        # Upload retrieval queries
        retrieval_dataset = create_retrieval_dataset()

        print()
        logger.info("=" * 60)
        logger.info("✓ All datasets created successfully!")
        logger.info("=" * 60)
        logger.info(f"View datasets at: https://smith.langchain.com/datasets")

    except FileNotFoundError as e:
        logger.error(f"❌ Dataset file not found: {e}")
        logger.error("Make sure you're running from the project root directory")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Error creating datasets: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
