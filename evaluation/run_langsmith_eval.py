"""Run LangSmith evaluations on datasets."""

import logging
from typing import Dict, Optional, Any
import requests

from langsmith import Client, evaluate
from langsmith.schemas import Example, Run

from evaluation.langsmith_evaluators import (
    category_accuracy_evaluator,
    subcategory_overlap_evaluator,
    semantic_similarity_evaluator,
    retrieval_precision_evaluator,
    retrieval_recall_evaluator
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API base URL
API_BASE_URL = "http://localhost:8000"


def analysis_target_function(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Target function for analysis evaluation.
    Calls the /items/{id}/analyze endpoint.

    Args:
        inputs: Dict with item_id

    Returns:
        Analysis results
    """
    item_id = inputs.get("item_id")

    try:
        response = requests.post(
            f"{API_BASE_URL}/items/{item_id}/analyze",
            json={"force_reanalyze": True},
            timeout=30
        )
        response.raise_for_status()

        result = response.json()

        return {
            "category": result.get("category"),
            "subcategories": result.get("subcategories", []),
            "headline": result.get("headline"),
            "summary": result.get("summary"),
            "image_details": result.get("image_details", {}),
            "media_metadata": result.get("media_metadata", {})
        }
    except Exception as e:
        logger.error(f"Error analyzing item {item_id}: {e}")
        return {
            "category": None,
            "subcategories": [],
            "headline": None,
            "summary": None,
            "error": str(e)
        }


def retrieval_target_function(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Target function for retrieval evaluation.
    Calls the /search endpoint.

    Args:
        inputs: Dict with query and search_type

    Returns:
        Search results
    """
    query = inputs.get("query")
    search_type = inputs.get("search_type", "bm25")

    try:
        response = requests.post(
            f"{API_BASE_URL}/search",
            json={
                "query": query,
                "search_type": search_type,
                "top_k": 10,
                "include_answer": True
            },
            timeout=30
        )
        response.raise_for_status()

        result = response.json()

        return {
            "results": result.get("results", []),
            "answer": result.get("answer"),
            "citations": result.get("citations", []),
            "total_results": result.get("total_results", 0)
        }
    except Exception as e:
        logger.error(f"Error searching for '{query}': {e}")
        return {
            "results": [],
            "answer": None,
            "citations": [],
            "error": str(e)
        }


def run_analysis_evaluation(
    dataset_name: str = "golden-analyses",
    experiment_name: Optional[str] = None,
    max_concurrency: int = 1
) -> Dict[str, Any]:
    """
    Run evaluation on image analysis quality.

    Args:
        dataset_name: Name of dataset in LangSmith
        experiment_name: Optional name for this experiment
        max_concurrency: Number of concurrent evaluations

    Returns:
        Evaluation results summary
    """
    logger.info(f"Running analysis evaluation on dataset '{dataset_name}'")

    # Run evaluation
    results = evaluate(
        analysis_target_function,
        data=dataset_name,
        evaluators=[
            category_accuracy_evaluator,
            subcategory_overlap_evaluator,
            semantic_similarity_evaluator
        ],
        experiment_prefix=experiment_name or "analysis-eval",
        max_concurrency=max_concurrency
    )

    logger.info("✓ Analysis evaluation complete")
    logger.info(f"  View results at: https://smith.langchain.com/")

    return {"status": "complete", "results": results}


def run_retrieval_evaluation(
    dataset_name: str = "retrieval-queries",
    search_type: str = "bm25",
    experiment_name: Optional[str] = None,
    max_concurrency: int = 1
) -> Dict[str, Any]:
    """
    Run evaluation on retrieval quality.

    Args:
        dataset_name: Name of dataset in LangSmith
        search_type: Type of search (bm25 or vector)
        experiment_name: Optional name for this experiment
        max_concurrency: Number of concurrent evaluations

    Returns:
        Evaluation results summary
    """
    logger.info(f"Running retrieval evaluation on dataset '{dataset_name}' with {search_type} search")

    # Run evaluation
    results = evaluate(
        retrieval_target_function,
        data=dataset_name,
        evaluators=[
            retrieval_precision_evaluator,
            retrieval_recall_evaluator
        ],
        experiment_prefix=experiment_name or f"retrieval-eval-{search_type}",
        max_concurrency=max_concurrency
    )

    logger.info("✓ Retrieval evaluation complete")
    logger.info(f"  View results at: https://smith.langchain.com/")

    return {"status": "complete", "results": results}


def compare_search_types(dataset_name: str = "retrieval-queries") -> Dict[str, Any]:
    """
    Compare BM25 vs vector search performance.

    Args:
        dataset_name: Name of dataset in LangSmith

    Returns:
        Comparison results
    """
    logger.info("Comparing BM25 vs vector search")

    # Run BM25 evaluation
    logger.info("Evaluating BM25 search...")
    bm25_results = run_retrieval_evaluation(
        dataset_name=dataset_name,
        search_type="bm25",
        experiment_name="compare-bm25"
    )

    # Run vector evaluation
    logger.info("Evaluating vector search...")
    vector_results = run_retrieval_evaluation(
        dataset_name=dataset_name,
        search_type="vector",
        experiment_name="compare-vector"
    )

    logger.info("✓ Search comparison complete")

    return {
        "bm25": bm25_results,
        "vector": vector_results
    }


if __name__ == "__main__":
    """Run evaluations as standalone script."""
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="Run LangSmith evaluations")
    parser.add_argument(
        "--type",
        choices=["analysis", "retrieval", "compare"],
        default="analysis",
        help="Type of evaluation to run"
    )
    parser.add_argument(
        "--dataset",
        help="Dataset name (defaults based on type)"
    )
    parser.add_argument(
        "--search-type",
        choices=["bm25", "vector"],
        default="bm25",
        help="Search type for retrieval evaluation"
    )

    args = parser.parse_args()

    try:
        logger.info("=" * 60)
        logger.info("LangSmith Evaluation")
        logger.info("=" * 60)

        if args.type == "analysis":
            dataset = args.dataset or "golden-analyses"
            run_analysis_evaluation(dataset_name=dataset)
        elif args.type == "retrieval":
            dataset = args.dataset or "retrieval-queries"
            run_retrieval_evaluation(dataset_name=dataset, search_type=args.search_type)
        elif args.type == "compare":
            dataset = args.dataset or "retrieval-queries"
            compare_search_types(dataset_name=dataset)

        logger.info("=" * 60)
        logger.info("✓ Evaluation complete!")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"❌ Evaluation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
