"""Evaluate end-to-end query → search → answer pipeline (trajectory evaluation)."""

import logging
import time
from typing import List, Dict, Any
import requests

from langsmith import Client, evaluate
from evaluation.langsmith_evaluators import trajectory_evaluator

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API base URL
API_BASE_URL = "http://localhost:8000"


def trajectory_target_function(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Target function for trajectory evaluation.
    Calls search endpoint with answer generation and measures full pipeline.

    Args:
        inputs: Dict with query, search_type, etc.

    Returns:
        Complete pipeline results with timing
    """
    query = inputs.get("query")
    search_type = inputs.get("search_type", "bm25")
    answer_model = inputs.get("answer_model")

    start_time = time.time()

    try:
        response = requests.post(
            f"{API_BASE_URL}/search",
            json={
                "query": query,
                "search_type": search_type,
                "top_k": 10,
                "include_answer": True,
                "answer_model": answer_model
            },
            timeout=60
        )
        response.raise_for_status()

        result = response.json()
        total_time = time.time() - start_time

        return {
            "results": result.get("results", []),
            "answer": result.get("answer"),
            "citations": result.get("citations", []),
            "total_results": result.get("total_results", 0),
            "retrieval_time_ms": result.get("retrieval_time_ms", 0),
            "answer_time_ms": result.get("answer_time_ms", 0),
            "total_time_ms": total_time * 1000
        }
    except Exception as e:
        logger.error(f"Error in trajectory for '{query}': {e}")
        return {
            "results": [],
            "answer": None,
            "citations": [],
            "error": str(e),
            "total_time_ms": (time.time() - start_time) * 1000
        }


def run_trajectory_evaluation(
    queries: List[str] = None,
    dataset_name: str = None,
    search_type: str = "bm25",
    answer_model: str = "claude-sonnet-4-5",
    top_k: int = 5
) -> Dict[str, Any]:
    """
    Run end-to-end trajectory evaluation.

    Args:
        queries: List of queries to test (if not using dataset)
        dataset_name: Name of LangSmith dataset to use
        search_type: Search type (bm25 or vector)
        answer_model: Model to use for answer generation
        top_k: Number of results to retrieve

    Returns:
        Evaluation results
    """
    logger.info(f"Running trajectory evaluation")
    logger.info(f"  Search type: {search_type}")
    logger.info(f"  Answer model: {answer_model}")

    if dataset_name:
        # Use existing LangSmith dataset
        logger.info(f"  Using dataset: {dataset_name}")

        results = evaluate(
            trajectory_target_function,
            data=dataset_name,
            evaluators=[trajectory_evaluator],
            experiment_prefix=f"trajectory-{search_type}",
            max_concurrency=1  # Sequential to avoid overloading API
        )

        logger.info("✓ Trajectory evaluation complete")
        logger.info(f"  View results at: https://smith.langchain.com/")

        return {"status": "complete", "results": results}

    elif queries:
        # Use provided queries
        logger.info(f"  Testing {len(queries)} queries")

        results = []
        for i, query in enumerate(queries, 1):
            logger.info(f"  [{i}/{len(queries)}] Testing: {query}")

            result = trajectory_target_function({
                "query": query,
                "search_type": search_type,
                "answer_model": answer_model
            })

            results.append({
                "query": query,
                "result": result,
                "success": "error" not in result
            })

            # Brief pause between requests
            time.sleep(0.5)

        # Calculate summary statistics
        successful = sum(1 for r in results if r["success"])
        avg_time = sum(r["result"].get("total_time_ms", 0) for r in results) / len(results)
        avg_results = sum(r["result"].get("total_results", 0) for r in results) / len(results)

        logger.info("=" * 60)
        logger.info("Trajectory Evaluation Summary")
        logger.info("=" * 60)
        logger.info(f"  Total queries: {len(queries)}")
        logger.info(f"  Successful: {successful}/{len(queries)}")
        logger.info(f"  Avg time: {avg_time:.0f}ms")
        logger.info(f"  Avg results: {avg_results:.1f}")

        return {
            "total": len(queries),
            "successful": successful,
            "avg_time_ms": avg_time,
            "avg_results": avg_results,
            "details": results
        }

    else:
        raise ValueError("Must provide either queries or dataset_name")


if __name__ == "__main__":
    """Run trajectory evaluation as standalone script."""
    import sys

    # Test queries
    test_queries = [
        "show me restaurants in tokyo",
        "japanese beauty products",
        "traditional architecture photos",
        "nature and landscapes",
        "food and dining experiences"
    ]

    try:
        logger.info("=" * 60)
        logger.info("Trajectory Evaluation - End-to-End Pipeline Test")
        logger.info("=" * 60)

        # Run with test queries
        results = run_trajectory_evaluation(
            queries=test_queries,
            search_type="bm25",
            answer_model="claude-sonnet-4-5"
        )

        logger.info("=" * 60)
        logger.info("✓ Trajectory evaluation complete!")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"❌ Trajectory evaluation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
