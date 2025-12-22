#!/usr/bin/env python3
"""
Retrieval Evaluation Script for Collections App API

Evaluates search/retrieval quality using a golden dataset and calculates
standard Information Retrieval metrics (Precision@K, Recall@K, MRR, NDCG@K).

Supports evaluating multiple search types (BM25, vector) with side-by-side
comparison reports.
"""

import argparse
import concurrent.futures
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests


def get_expected_items(query: dict, search_type: str) -> List[Dict]:
    """
    Get expected items for a search type with backward compatibility.

    Resolution order:
    1. expected_items_by_search_type[search_type] (new format)
    2. expected_items (old format, backward compatible)

    Args:
        query: Query dict from dataset
        search_type: Search type (e.g., "bm25", "vector")

    Returns:
        List of expected items with item_id and relevance

    Raises:
        ValueError: If query has no expected items defined
    """
    # New format: per-search-type expectations
    if "expected_items_by_search_type" in query:
        search_type_items = query["expected_items_by_search_type"]
        if search_type in search_type_items:
            return search_type_items[search_type]

    # Backward compatible: shared expectations
    if "expected_items" in query:
        return query["expected_items"]

    # Invalid query
    raise ValueError(f"Query {query.get('query_id', 'unknown')} missing expected items")


class SearchTypeEvaluator:
    """Evaluates retrieval quality for a single search type."""

    RELEVANCE_SCORES = {"high": 3, "medium": 2, "low": 1}

    def __init__(self, search_type: str, base_url: str, headers: dict,
                 top_k_values: list, verbose: bool):
        """
        Initialize evaluator for a specific search type.

        Args:
            search_type: Search type to evaluate (e.g., "bm25", "vector")
            base_url: Base URL for API
            headers: Request headers (for golden subdomain routing)
            top_k_values: List of K values for metrics (e.g., [1, 3, 5, 10])
            verbose: Whether to print detailed progress
        """
        self.search_type = search_type
        self.base_url = base_url
        self.headers = headers
        self.top_k_values = top_k_values
        self.max_k = max(top_k_values)
        self.verbose = verbose
        self.results = []

    def log(self, message: str, force: bool = False):
        """Print message if verbose mode is enabled or force is True."""
        if self.verbose or force:
            print(message)

    def search(self, query_text: str) -> Dict:
        """Call the search API with this search type."""
        try:
            response = requests.post(
                f"{self.base_url}/search",
                json={
                    "query": query_text,
                    "top_k": self.max_k,
                    "search_type": self.search_type,  # Specify search type
                    "include_answer": False
                },
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": str(e), "results": [], "total_results": 0, "retrieval_time_ms": 0}

    def calculate_precision_recall(
        self, retrieved_ids: List[str], expected_ids: List[str], k: int
    ) -> Tuple[float, float]:
        """Calculate Precision@K and Recall@K."""
        retrieved_at_k = set(retrieved_ids[:k])
        expected_set = set(expected_ids)

        if k == 0:
            precision = 0.0
        else:
            precision = len(retrieved_at_k & expected_set) / k

        if len(expected_set) == 0:
            recall = 0.0
        else:
            recall = len(retrieved_at_k & expected_set) / len(expected_set)

        return precision, recall

    def calculate_reciprocal_rank(
        self, retrieved_ids: List[str], expected_ids: List[str]
    ) -> Tuple[float, Optional[int]]:
        """Calculate reciprocal rank and return first relevant rank."""
        expected_set = set(expected_ids)
        for rank, item_id in enumerate(retrieved_ids, start=1):
            if item_id in expected_set:
                return 1.0 / rank, rank
        return 0.0, None

    def calculate_dcg(self, retrieved_ids: List[str], relevance_map: Dict[str, int], k: int) -> float:
        """Calculate Discounted Cumulative Gain at K."""
        dcg = 0.0
        for i, item_id in enumerate(retrieved_ids[:k], start=1):
            rel = relevance_map.get(item_id, 0)
            dcg += rel / (i + 1).bit_length()  # log2(i+1) using bit_length for efficiency
        return dcg

    def calculate_ndcg(
        self, retrieved_ids: List[str], relevance_map: Dict[str, int], k: int
    ) -> float:
        """Calculate Normalized Discounted Cumulative Gain at K."""
        dcg = self.calculate_dcg(retrieved_ids, relevance_map, k)

        # Calculate ideal DCG
        ideal_relevances = sorted(relevance_map.values(), reverse=True)
        ideal_dcg = sum(rel / (i + 1).bit_length() for i, rel in enumerate(ideal_relevances[:k], start=1))

        if ideal_dcg == 0:
            return 0.0
        return dcg / ideal_dcg

    def evaluate_query(self, query: Dict) -> Dict:
        """Evaluate a single query for this search type."""
        query_id = query["query_id"]
        query_text = query["query_text"]
        query_type = query["query_type"]

        # Get expected items for this search type (with backward compatibility)
        expected_items = get_expected_items(query, self.search_type)

        # Handle expected_count: can be a single value or inferred from expected_items
        # Some queries use expected_count_range instead
        if "expected_count" in query:
            expected_count = query["expected_count"]
        elif "expected_count_range" in query:
            # For range queries, we just check if items exist (not count)
            expected_count = len(expected_items) if expected_items else 0
        else:
            # Infer from expected_items
            expected_count = len(expected_items)

        # Build expected items list and relevance map
        expected_ids = [item["item_id"] for item in expected_items]
        relevance_map = {
            item["item_id"]: self.RELEVANCE_SCORES.get(item["relevance"], 0)
            for item in expected_items
        }

        # Call search API
        search_result = self.search(query_text)

        if "error" in search_result:
            return {
                "query_id": query_id,
                "query_text": query_text,
                "query_type": query_type,
                "search_type": self.search_type,
                "expected_items": expected_ids,
                "expected_relevance": {k: v for k, v in zip(expected_ids, [item["relevance"] for item in expected_items])},
                "retrieved_items": [],
                "retrieved_scores": [],
                "retrieval_time_ms": 0,
                "error": search_result["error"],
                "status": "error",
                "metrics": {},
            }

        retrieved_ids = [r["item_id"] for r in search_result.get("results", [])]
        retrieved_scores = [r["score"] for r in search_result.get("results", [])]
        retrieval_time_ms = search_result.get("retrieval_time_ms", 0)

        # Capture metadata from search results
        retrieved_metadata = [
            {
                "item_id": r["item_id"],
                "category": r.get("category"),
                "headline": r.get("headline"),
                "score": r["score"]
            }
            for r in search_result.get("results", [])
        ]

        # Handle edge cases (no results expected)
        if expected_count == 0:
            status = "true_negative" if len(retrieved_ids) == 0 else "false_positive"

            # Add diagnostic fields for edge cases too
            score_stats = {}
            if retrieved_scores:
                sorted_scores = sorted(retrieved_scores)
                score_stats = {
                    "min": min(retrieved_scores),
                    "max": max(retrieved_scores),
                    "median": sorted_scores[len(sorted_scores)//2],
                    "range": max(retrieved_scores) - min(retrieved_scores),
                }

            return {
                "query_id": query_id,
                "query_text": query_text,
                "query_type": query_type,
                "search_type": self.search_type,
                "expected_items": expected_ids,
                "expected_relevance": {},
                "retrieved_items": retrieved_ids,
                "retrieved_scores": retrieved_scores,
                "retrieval_time_ms": retrieval_time_ms,
                "status": status,
                "metrics": {},
                # Enhanced diagnostic fields for edge cases
                "retrieved_metadata": retrieved_metadata,
                "score_stats": score_stats,
            }

        # Calculate metrics
        metrics = {"precision": {}, "recall": {}, "ndcg": {}}

        for k in self.top_k_values:
            precision, recall = self.calculate_precision_recall(retrieved_ids, expected_ids, k)
            ndcg = self.calculate_ndcg(retrieved_ids, relevance_map, k)
            metrics["precision"][f"@{k}"] = precision
            metrics["recall"][f"@{k}"] = recall
            metrics["ndcg"][f"@{k}"] = ndcg

        rr, first_relevant_rank = self.calculate_reciprocal_rank(retrieved_ids, expected_ids)
        metrics["reciprocal_rank"] = rr

        # Determine status
        status = "pass" if first_relevant_rank == 1 else "partial" if first_relevant_rank else "fail"

        # Calculate score analysis
        score_gaps = []
        if len(retrieved_scores) >= 2:
            score_gaps = [retrieved_scores[i] - retrieved_scores[i+1] for i in range(len(retrieved_scores)-1)]

        expected_item_scores = {}
        for item_id in expected_ids:
            if item_id in retrieved_ids:
                idx = retrieved_ids.index(item_id)
                expected_item_scores[item_id] = retrieved_scores[idx]
            else:
                expected_item_scores[item_id] = None

        # Calculate relevance alignment
        relevance_alignment = []
        for item in expected_items:
            item_id = item["item_id"]
            expected_rel = item["relevance"]
            actual_rank = retrieved_ids.index(item_id) + 1 if item_id in retrieved_ids else None
            actual_score = retrieved_scores[actual_rank-1] if actual_rank else None

            relevance_alignment.append({
                "item_id": item_id,
                "expected_relevance": expected_rel,
                "actual_rank": actual_rank,
                "actual_score": actual_score
            })

        # Calculate score statistics
        score_stats = {}
        if retrieved_scores:
            sorted_scores = sorted(retrieved_scores)
            score_stats = {
                "min": min(retrieved_scores),
                "max": max(retrieved_scores),
                "median": sorted_scores[len(sorted_scores)//2],
                "range": max(retrieved_scores) - min(retrieved_scores),
            }

        return {
            "query_id": query_id,
            "query_text": query_text,
            "query_type": query_type,
            "search_type": self.search_type,
            "expected_items": expected_ids,
            "expected_relevance": {item["item_id"]: item["relevance"] for item in expected_items},
            "retrieved_items": retrieved_ids,
            "retrieved_scores": retrieved_scores,
            "retrieval_time_ms": retrieval_time_ms,
            "metrics": metrics,
            "first_relevant_rank": first_relevant_rank,
            "status": status,
            # Enhanced diagnostic fields
            "score_gaps": score_gaps,
            "expected_item_scores": expected_item_scores,
            "relevance_alignment": relevance_alignment,
            "retrieved_metadata": retrieved_metadata,
            "score_stats": score_stats,
        }

    def aggregate_metrics(self) -> Dict:
        """Aggregate metrics across all queries for this search type."""
        # Separate edge cases from regular queries
        regular_results = [r for r in self.results if r.get("metrics") and r["status"] not in ["true_negative", "false_positive"]]
        edge_cases = [r for r in self.results if r["status"] in ["true_negative", "false_positive"]]

        # Aggregate regular metrics
        summary = {"precision": {}, "recall": {}, "ndcg": {}, "mrr": 0.0}

        if regular_results:
            for k in self.top_k_values:
                key = f"@{k}"
                summary["precision"][key] = sum(r["metrics"]["precision"][key] for r in regular_results) / len(regular_results)
                summary["recall"][key] = sum(r["metrics"]["recall"][key] for r in regular_results) / len(regular_results)
                summary["ndcg"][key] = sum(r["metrics"]["ndcg"][key] for r in regular_results) / len(regular_results)

            summary["mrr"] = sum(r["metrics"]["reciprocal_rank"] for r in regular_results) / len(regular_results)

        # Edge cases
        summary["edge_cases"] = {
            "total": len(edge_cases),
            "true_negatives": len([r for r in edge_cases if r["status"] == "true_negative"]),
            "false_positives": len([r for r in edge_cases if r["status"] == "false_positive"]),
        }
        if edge_cases:
            summary["edge_cases"]["tn_rate"] = summary["edge_cases"]["true_negatives"] / len(edge_cases)
            summary["edge_cases"]["fp_rate"] = summary["edge_cases"]["false_positives"] / len(edge_cases)
        else:
            summary["edge_cases"]["tn_rate"] = 0.0
            summary["edge_cases"]["fp_rate"] = 0.0

        return summary

    def aggregate_by_query_type(self) -> Dict:
        """Aggregate metrics by query type for this search type."""
        by_type = {}

        # Group results by query type (excluding edge cases)
        for result in self.results:
            if result["status"] in ["true_negative", "false_positive"]:
                continue
            if not result.get("metrics"):
                continue

            qtype = result["query_type"]
            if qtype not in by_type:
                by_type[qtype] = []
            by_type[qtype].append(result)

        # Aggregate each type
        aggregated = {}
        for qtype, results in by_type.items():
            agg = {"count": len(results), "precision": {}, "recall": {}, "ndcg": {}, "mrr": 0.0}

            for k in self.top_k_values:
                key = f"@{k}"
                agg["precision"][key] = sum(r["metrics"]["precision"][key] for r in results) / len(results)
                agg["recall"][key] = sum(r["metrics"]["recall"][key] for r in results) / len(results)
                agg["ndcg"][key] = sum(r["metrics"]["ndcg"][key] for r in results) / len(results)

            agg["mrr"] = sum(r["metrics"]["reciprocal_rank"] for r in results) / len(results)
            aggregated[qtype] = agg

        return aggregated

    def calculate_timing_stats(self) -> Dict:
        """Calculate timing statistics for this search type."""
        retrieval_times = [r["retrieval_time_ms"] for r in self.results if r["retrieval_time_ms"] > 0]

        if not retrieval_times:
            return {"avg_retrieval_time_ms": 0, "min_retrieval_time_ms": 0, "max_retrieval_time_ms": 0}

        return {
            "avg_retrieval_time_ms": sum(retrieval_times) / len(retrieval_times),
            "min_retrieval_time_ms": min(retrieval_times),
            "max_retrieval_time_ms": max(retrieval_times),
        }

    def identify_timing_outliers(self, threshold_multiplier: float = 2.0) -> List[str]:
        """Identify queries with retrieval times significantly above average."""
        timing_stats = self.calculate_timing_stats()
        avg_time = timing_stats.get("avg_retrieval_time_ms", 0)
        if avg_time == 0:
            return []

        outliers = []
        for result in self.results:
            if result["retrieval_time_ms"] > avg_time * threshold_multiplier:
                outliers.append(result["query_id"])

        return outliers

    def format_score_with_context(self, score: float, search_type: str) -> str:
        """Format score with appropriate context based on search type."""
        if search_type == "vector":
            # Similarity scores are 0-1
            return f"{score:.3f}"
        else:  # BM25
            # BM25 scores are typically negative
            return f"{score:.2f}"

    def get_score_confidence_label(self, score_gaps: List[float]) -> str:
        """Determine confidence level based on score gaps."""
        if not score_gaps or len(score_gaps) < 1:
            return "Unknown"

        first_gap = abs(score_gaps[0])

        # Thresholds depend on search type (heuristic)
        if self.search_type == "vector":
            # For similarity scores (0-1 range)
            if first_gap > 0.1:
                return "High"
            elif first_gap > 0.05:
                return "Medium"
            else:
                return "Low"
        else:  # BM25
            # For BM25 scores (typically negative, larger magnitude = better)
            if first_gap > 5.0:
                return "High"
            elif first_gap > 2.0:
                return "Medium"
            else:
                return "Low"


class MultiSearchRetrievalEvaluator:
    """Coordinates evaluation across multiple search types."""

    DEFAULT_PORTS = [8000, 8001, 8080, 3000]
    VALID_SEARCH_TYPES = ["bm25", "vector", "bm25-lc", "vector-lc", "hybrid", "hybrid-lc"]

    def __init__(self, args):
        self.args = args
        self.base_url = None
        self.verbose = args.verbose
        self.dataset = None
        self.use_golden_subdomain = getattr(args, 'use_golden_subdomain', True)

        # Parse and validate search types
        self.search_types = self._parse_search_types(args.search_types)

        # Evaluators for each search type
        self.evaluators: Dict[str, SearchTypeEvaluator] = {}

        # Search configuration (fetched from API)
        self.search_config = {}

    def log(self, message: str, force: bool = False):
        """Print message if verbose mode is enabled or force is True."""
        if self.verbose or force:
            print(message)

    def _parse_search_types(self, search_types_arg: str) -> List[str]:
        """Parse and validate --search-types argument."""
        if search_types_arg == "all":
            return self.VALID_SEARCH_TYPES.copy()

        # Split by comma and strip whitespace
        types = [s.strip() for s in search_types_arg.split(",")]

        # Validate
        invalid = [t for t in types if t not in self.VALID_SEARCH_TYPES]
        if invalid:
            print(f"Error: Invalid search type(s): {', '.join(invalid)}")
            print(f"Valid types: {', '.join(self.VALID_SEARCH_TYPES)}")
            sys.exit(1)

        return types

    def _initialize_evaluators(self):
        """Create SearchTypeEvaluator for each search type."""
        headers = self._get_request_headers()
        top_k_values = [int(k) for k in self.args.top_k.split(",")]

        for search_type in self.search_types:
            self.evaluators[search_type] = SearchTypeEvaluator(
                search_type=search_type,
                base_url=self.base_url,
                headers=headers,
                top_k_values=top_k_values,
                verbose=self.verbose
            )

    def find_api_endpoint(self) -> str:
        """Find and validate the API endpoint."""
        if self.args.base_url:
            # User provided a full base URL
            if self._check_health(self.args.base_url):
                return self.args.base_url
            print(f"Error: Cannot connect to {self.args.base_url}")
            sys.exit(1)

        # Try the specified port first
        specified_url = f"http://localhost:{self.args.port}"
        if self._check_health(specified_url):
            return specified_url

        # Try common ports
        print(f"Warning: Cannot connect to {specified_url}")
        print("Trying common ports...")
        for port in self.DEFAULT_PORTS:
            if port == self.args.port:
                continue  # Already tried
            url = f"http://localhost:{port}"
            if self._check_health(url):
                print(f"Found API at {url}")
                return url

        print("\nError: Could not find a running API server.")
        print("Tried ports:", [self.args.port] + self.DEFAULT_PORTS)
        print("\nPlease start the API server with:")
        print("  uvicorn main:app --port 8000")
        print("\nThe script will automatically route to the golden database via subdomain.")
        sys.exit(1)

    def _check_health(self, base_url: str) -> bool:
        """Check if the API health endpoint responds."""
        try:
            headers = self._get_request_headers()
            response = requests.get(f"{base_url}/health", headers=headers, timeout=2)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def _get_request_headers(self) -> dict:
        """Get headers for API requests, including golden subdomain routing."""
        headers = {}
        if self.use_golden_subdomain and not self.args.base_url:
            # Extract port from base_url if available
            if self.base_url:
                # Parse port from base_url (e.g., "http://localhost:8000")
                import re
                port_match = re.search(r':(\d+)', self.base_url)
                port = port_match.group(1) if port_match else "8000"
            else:
                port = str(self.args.port)
            headers["Host"] = f"golden.localhost:{port}"
        return headers

    def validate_item_count(self) -> Tuple[int, bool]:
        """Validate that the database has the expected number of items."""
        try:
            headers = self._get_request_headers()
            response = requests.get(f"{self.base_url}/items", params={"limit": 1}, headers=headers, timeout=5)
            response.raise_for_status()
            data = response.json()
            actual_count = data.get("total", 0)
            expected_count = self.args.expected_items

            if actual_count != expected_count:
                print(f"\n⚠️  WARNING: Item count mismatch!")
                print(f"   Expected: {expected_count} items (golden database)")
                print(f"   Actual:   {actual_count} items")
                if not self.args.skip_item_check:
                    print("\nThis suggests you may be running against the wrong database.")
                    print("Use --skip-item-check to proceed anyway, or specify --expected-items")
                    sys.exit(1)
                else:
                    print("   Continuing anyway (--skip-item-check enabled)")
                    return actual_count, False

            return actual_count, True
        except requests.exceptions.RequestException as e:
            print(f"Error: Could not validate item count: {e}")
            sys.exit(1)

    def load_dataset(self):
        """Load the evaluation dataset."""
        dataset_path = Path(self.args.dataset)
        if not dataset_path.exists():
            print(f"Error: Dataset file not found: {dataset_path}")
            sys.exit(1)

        with open(dataset_path) as f:
            self.dataset = json.load(f)

        self.log(f"Loaded dataset: {len(self.dataset['queries'])} queries", force=True)

    def fetch_search_config(self):
        """Fetch runtime search configuration from the API."""
        try:
            headers = self._get_request_headers()
            url = f"{self.base_url}/search/config"
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            self.search_config = response.json()
            self.log(f"✓ Fetched search configuration for {len(self.search_config)} search type(s)", force=True)
        except requests.exceptions.RequestException as e:
            self.log(f"⚠ Warning: Could not fetch search configuration: {e}", force=True)
            self.log(f"  Continuing without runtime configuration details", force=True)
            self.search_config = {}

    def run_evaluation(self):
        """Run evaluation on all queries across all search types."""
        queries = self.dataset["queries"]
        total = len(queries)

        print(f"\nEvaluating {total} queries across {len(self.search_types)} search type(s)...")
        print(f"Search types: {', '.join(self.search_types)}")
        print(f"Parallel execution: {'enabled' if self.args.parallel else 'disabled'}")
        start_time = time.time()

        for i, query in enumerate(queries, start=1):
            if self.args.parallel and len(self.search_types) > 1:
                self._evaluate_query_parallel(query, i, total)
            else:
                self._evaluate_query_sequential(query, i, total)

        if not self.verbose:
            print()  # New line after progress

        elapsed = time.time() - start_time
        print(f"Completed in {elapsed:.2f}s")

        return elapsed

    def _evaluate_query_sequential(self, query: Dict, i: int, total: int):
        """Evaluate query sequentially across all search types."""
        for search_type in self.search_types:
            evaluator = self.evaluators[search_type]
            result = evaluator.evaluate_query(query)
            evaluator.results.append(result)

            if self.verbose:
                symbol = self._get_status_symbol(result["status"])
                print(f"  [{i}/{total}] {symbol} {search_type:6s} {result['query_id']}: {result['query_text'][:40]}")

        # Progress indicator for non-verbose mode
        if not self.verbose and (i % 5 == 0 or i == total):
            print(f"  Progress: {i}/{total} ({100*i//total}%)", end="\r")

    def _evaluate_query_parallel(self, query: Dict, i: int, total: int):
        """Evaluate query in parallel across all search types."""
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.search_types)) as executor:
            futures = {
                executor.submit(evaluator.evaluate_query, query): search_type
                for search_type, evaluator in self.evaluators.items()
            }

            for future in concurrent.futures.as_completed(futures):
                search_type = futures[future]
                evaluator = self.evaluators[search_type]
                result = future.result()
                evaluator.results.append(result)

                if self.verbose:
                    symbol = self._get_status_symbol(result["status"])
                    print(f"  [{i}/{total}] {symbol} {search_type:6s} {result['query_id']}: {result['query_text'][:40]}")

        # Progress indicator for non-verbose mode
        if not self.verbose and (i % 5 == 0 or i == total):
            print(f"  Progress: {i}/{total} ({100*i//total}%)", end="\r")

    def _get_status_symbol(self, status: str) -> str:
        """Get status symbol for a query result."""
        status_symbols = {
            "pass": "✓",
            "partial": "~",
            "fail": "✗",
            "error": "⚠",
            "true_negative": "✓",
            "false_positive": "✗"
        }
        return status_symbols.get(status, "?")

    def calculate_comparison_metrics(self) -> Dict:
        """Calculate comparison metrics across search types."""
        if len(self.search_types) == 1:
            return {}  # No comparison for single search type

        comparison = {
            "metric_differences": self._calculate_metric_deltas(),
            "agreement": self._calculate_agreement_metrics(),
            "performance": self._calculate_performance_comparison()
        }
        return comparison

    def _calculate_metric_deltas(self) -> Dict:
        """Calculate absolute and percentage differences in metrics."""
        if len(self.search_types) != 2:
            return {}  # Only support pairwise comparison for now

        type1, type2 = self.search_types
        summary1 = self.evaluators[type1].aggregate_metrics()
        summary2 = self.evaluators[type2].aggregate_metrics()

        deltas = {}

        # Compare precision, recall, ndcg at each k
        for metric_name in ["precision", "recall", "ndcg"]:
            for k_key in summary1[metric_name].keys():
                val1 = summary1[metric_name][k_key]
                val2 = summary2[metric_name][k_key]
                diff = val2 - val1
                pct = (diff / val1 * 100) if val1 != 0 else 0

                deltas[f"{metric_name}{k_key}"] = {
                    type1: val1,
                    type2: val2,
                    "difference": diff,
                    "percent_change": pct,
                    "winner": type2 if val2 > val1 else type1 if val1 > val2 else "tie"
                }

        # Compare MRR
        mrr1 = summary1["mrr"]
        mrr2 = summary2["mrr"]
        mrr_diff = mrr2 - mrr1
        mrr_pct = (mrr_diff / mrr1 * 100) if mrr1 != 0 else 0

        deltas["mrr"] = {
            type1: mrr1,
            type2: mrr2,
            "difference": mrr_diff,
            "percent_change": mrr_pct,
            "winner": type2 if mrr2 > mrr1 else type1 if mrr1 > mrr2 else "tie"
        }

        return deltas

    def _calculate_agreement_metrics(self) -> Dict:
        """Calculate rank agreement and top-K overlap."""
        if len(self.search_types) != 2:
            return {}

        type1, type2 = self.search_types
        results1 = self.evaluators[type1].results
        results2 = self.evaluators[type2].results

        rank1_agreements = 0
        top3_overlaps = []
        top5_overlaps = []
        total_comparable = 0

        for r1, r2 in zip(results1, results2):
            # Skip edge cases and errors
            if r1["status"] in ["true_negative", "false_positive", "error"]:
                continue
            if r2["status"] in ["true_negative", "false_positive", "error"]:
                continue
            if not r1.get("retrieved_items") or not r2.get("retrieved_items"):
                continue

            total_comparable += 1

            # Rank-1 agreement
            if r1["retrieved_items"][0] == r2["retrieved_items"][0]:
                rank1_agreements += 1

            # Top-3 overlap (Jaccard similarity)
            top3_1 = set(r1["retrieved_items"][:3])
            top3_2 = set(r2["retrieved_items"][:3])
            if top3_1 or top3_2:
                jaccard3 = len(top3_1 & top3_2) / len(top3_1 | top3_2)
                top3_overlaps.append(jaccard3)

            # Top-5 overlap
            top5_1 = set(r1["retrieved_items"][:5])
            top5_2 = set(r2["retrieved_items"][:5])
            if top5_1 or top5_2:
                jaccard5 = len(top5_1 & top5_2) / len(top5_1 | top5_2)
                top5_overlaps.append(jaccard5)

        return {
            "rank_1_agreement": rank1_agreements / total_comparable if total_comparable > 0 else 0,
            "top_3_overlap": sum(top3_overlaps) / len(top3_overlaps) if top3_overlaps else 0,
            "top_5_overlap": sum(top5_overlaps) / len(top5_overlaps) if top5_overlaps else 0,
            "comparable_queries": total_comparable
        }

    def _calculate_performance_comparison(self) -> Dict:
        """Compare retrieval times across search types."""
        performance = {}

        for search_type, evaluator in self.evaluators.items():
            timing = evaluator.calculate_timing_stats()
            performance[search_type] = timing

        return performance

    def _generate_per_query_comparison(self) -> List[Dict]:
        """Generate per-query comparison data across search types."""
        if len(self.search_types) != 2:
            return []

        type1, type2 = self.search_types
        results1 = self.evaluators[type1].results
        results2 = self.evaluators[type2].results

        comparisons = []
        for r1, r2 in zip(results1, results2):
            # Skip edge cases and errors
            if r1["status"] in ["true_negative", "false_positive", "error"]:
                continue
            if r2["status"] in ["true_negative", "false_positive", "error"]:
                continue
            if not r1.get("metrics") or not r2.get("metrics"):
                continue

            # Determine winner based on MRR
            mrr1 = r1["metrics"].get("reciprocal_rank", 0)
            mrr2 = r2["metrics"].get("reciprocal_rank", 0)
            if mrr2 > mrr1:
                winner = type2
            elif mrr1 > mrr2:
                winner = type1
            else:
                winner = "tie"

            # Rank-1 comparison
            rank1_match = None
            if r1.get("retrieved_items") and r2.get("retrieved_items"):
                rank1_match = r1["retrieved_items"][0] == r2["retrieved_items"][0]

            comparisons.append({
                "query_id": r1["query_id"],
                "query_text": r1["query_text"],
                "query_type": r1["query_type"],
                "winner": winner,
                "mrr_diff": mrr2 - mrr1,
                "rank1_agreement": rank1_match,
                f"{type1}_first_rank": r1.get("first_relevant_rank"),
                f"{type2}_first_rank": r2.get("first_relevant_rank"),
                f"{type1}_mrr": mrr1,
                f"{type2}_mrr": mrr2,
            })

        return comparisons

    def generate_reports(self, run_id: str, total_time: float, actual_item_count: int, item_count_valid: bool):
        """Generate markdown and JSON reports."""
        output_dir = Path(self.args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Generate reports based on number of search types
        if len(self.search_types) == 1:
            self._generate_single_search_reports(run_id, total_time, actual_item_count, item_count_valid, output_dir)
        else:
            self._generate_multi_search_reports(run_id, total_time, actual_item_count, item_count_valid, output_dir)

    def _generate_single_search_reports(self, run_id: str, total_time: float,
                                       actual_item_count: int, item_count_valid: bool, output_dir: Path):
        """Generate reports for single search type evaluation (backward compatible)."""
        search_type = self.search_types[0]
        evaluator = self.evaluators[search_type]

        summary = evaluator.aggregate_metrics()
        by_query_type = evaluator.aggregate_by_query_type()
        timing_stats = evaluator.calculate_timing_stats()

        # Generate JSON report (original format)
        json_report = {
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config": {
                "api_base_url": self.base_url,
                "dataset_path": self.args.dataset,
                "search_type": search_type,
                "top_k_values": evaluator.top_k_values,
                "dataset_version": self.dataset["metadata"].get("version", "unknown"),
                "total_queries": len(evaluator.results),
                "target_item_count": self.args.expected_items,
                "actual_item_count": actual_item_count,
            },
            "summary": summary,
            "by_query_type": by_query_type,
            "query_results": evaluator.results,
            "timing": {
                "total_evaluation_time_s": total_time,
                **timing_stats,
            },
        }

        json_path = output_dir / f"{run_id}_report.json"
        with open(json_path, "w") as f:
            json.dump(json_report, f, indent=2)

        # Generate Markdown report
        md_report = self._generate_single_markdown_report(
            run_id, search_type, summary, by_query_type, actual_item_count, item_count_valid, evaluator
        )

        md_path = output_dir / f"{run_id}_report.md"
        with open(md_path, "w") as f:
            f.write(md_report)

        print(f"\n✓ Reports generated:")
        print(f"  - {json_path}")
        print(f"  - {md_path}")

    def _generate_multi_search_reports(self, run_id: str, total_time: float,
                                      actual_item_count: int, item_count_valid: bool, output_dir: Path):
        """Generate comparison reports for multiple search types."""
        # Collect data from all evaluators
        results_by_search_type = {}
        for search_type, evaluator in self.evaluators.items():
            results_by_search_type[search_type] = {
                "summary": evaluator.aggregate_metrics(),
                "by_query_type": evaluator.aggregate_by_query_type(),
                "query_results": evaluator.results,
                "timing": {
                    "total_evaluation_time_s": total_time,
                    **evaluator.calculate_timing_stats(),
                }
            }

        # Calculate comparison metrics
        comparison = self.calculate_comparison_metrics()

        # Add per-query comparison data
        per_query_comparisons = self._generate_per_query_comparison()
        if per_query_comparisons:
            comparison["per_query_comparisons"] = per_query_comparisons

        # Generate JSON report
        json_report = {
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config": {
                "api_base_url": self.base_url,
                "dataset_path": self.args.dataset,
                "search_types_evaluated": self.search_types,
                "parallel_execution": self.args.parallel,
                "top_k_values": list(self.evaluators.values())[0].top_k_values,
                "dataset_version": self.dataset["metadata"].get("version", "unknown"),
                "total_queries": len(list(self.evaluators.values())[0].results),
                "target_item_count": self.args.expected_items,
                "actual_item_count": actual_item_count,
            },
            "search_configuration": self.search_config,  # Runtime configuration
            "results_by_search_type": results_by_search_type,
            "comparison": comparison,
        }

        json_path = output_dir / f"{run_id}_report.json"
        with open(json_path, "w") as f:
            json.dump(json_report, f, indent=2)

        # Generate Markdown report
        md_report = self._generate_multi_markdown_report(
            run_id, results_by_search_type, comparison, actual_item_count, item_count_valid
        )

        md_path = output_dir / f"{run_id}_report.md"
        with open(md_path, "w") as f:
            f.write(md_report)

        print(f"\n✓ Reports generated:")
        print(f"  - {json_path}")
        print(f"  - {md_path}")

    def _generate_single_markdown_report(
        self, run_id: str, search_type: str, summary: Dict, by_query_type: Dict,
        actual_item_count: int, item_count_valid: bool, evaluator: SearchTypeEvaluator
    ) -> str:
        """Generate markdown report for single search type (backward compatible format)."""
        lines = [
            "# Retrieval Evaluation Report",
            "",
            f"**Run ID**: {run_id}",
            f"**Timestamp**: {datetime.now(timezone.utc).isoformat()}",
            f"**API Endpoint**: {self.base_url}",
            f"**Search Type**: {search_type}",
            f"**Dataset**: {Path(self.args.dataset).name} ({len(evaluator.results)} queries)",
            f"**Target Items**: {self.args.expected_items} | **Actual Items**: {actual_item_count} {'✓' if item_count_valid else '✗'}",
            "",
            "## Summary Metrics",
            "",
            "| Metric | " + " | ".join(f"@{k}" for k in evaluator.top_k_values) + " |",
            "|--------|" + "|".join("-----" for _ in evaluator.top_k_values) + "|",
        ]

        # Precision row
        lines.append(
            "| Precision | "
            + " | ".join(f"{summary['precision'].get(f'@{k}', 0):.3f}" for k in evaluator.top_k_values)
            + " |"
        )

        # Recall row
        lines.append(
            "| Recall | "
            + " | ".join(f"{summary['recall'].get(f'@{k}', 0):.3f}" for k in evaluator.top_k_values)
            + " |"
        )

        # NDCG row
        lines.append(
            "| NDCG | " + " | ".join(f"{summary['ndcg'].get(f'@{k}', 0):.3f}" for k in evaluator.top_k_values) + " |"
        )

        lines.extend([
            "",
            f"**MRR**: {summary['mrr']:.3f}",
            "",
        ])

        # Edge cases
        if summary["edge_cases"]["total"] > 0:
            ec = summary["edge_cases"]
            lines.extend([
                "### Edge Cases (No Results Expected)",
                f"- True Negatives: {ec['true_negatives']}/{ec['total']} ({ec['tn_rate']*100:.1f}%)",
                f"- False Positives: {ec['false_positives']}/{ec['total']} ({ec['fp_rate']*100:.1f}%)",
                "",
            ])

        # By query type
        if by_query_type:
            lines.extend([
                "### By Query Type",
                "",
                "| Type | Count | P@5 | R@5 | MRR |",
                "|------|-------|-----|-----|-----|",
            ])

            for qtype, metrics in sorted(by_query_type.items()):
                p5 = metrics["precision"].get("@5", 0)
                r5 = metrics["recall"].get("@5", 0)
                mrr = metrics["mrr"]
                lines.append(f"| {qtype} | {metrics['count']} | {p5:.2f} | {r5:.2f} | {mrr:.2f} |")

            lines.append("")

        # Detailed results
        lines.extend([
            "## Detailed Results",
            "",
        ])

        for result in evaluator.results:
            status_symbols = {
                "pass": "✓ PASS",
                "partial": "~ PARTIAL",
                "fail": "✗ FAIL",
                "error": "⚠ ERROR",
                "true_negative": "✓ TRUE NEGATIVE",
                "false_positive": "✗ FALSE POSITIVE",
            }
            status = status_symbols.get(result["status"], "? UNKNOWN")

            lines.append(f"### Query: {result['query_id']} - \"{result['query_text']}\"")
            lines.append(f"- **Type**: {result['query_type']}")

            if result.get("expected_items"):
                expected_str = ", ".join(
                    f"{item_id[:8]}... ({result.get('expected_relevance', {}).get(item_id, 'unknown')})"
                    for item_id in result["expected_items"][:3]
                )
                if len(result["expected_items"]) > 3:
                    expected_str += f" (+{len(result['expected_items'])-3} more)"
                lines.append(f"- **Expected**: {expected_str}")
            else:
                lines.append("- **Expected**: (none)")

            # Enhanced: Show retrieved items with scores and metadata
            if result.get("retrieved_items"):
                lines.append("- **Retrieved Top-3 with Scores**:")
                retrieved_metadata = result.get("retrieved_metadata", [])
                retrieved_scores = result.get("retrieved_scores", [])
                score_gaps = result.get("score_gaps", [])
                expected_item_scores = result.get("expected_item_scores", {})

                for i, item_id in enumerate(result["retrieved_items"][:3]):
                    # Build score display
                    score = retrieved_scores[i] if i < len(retrieved_scores) else None
                    score_str = evaluator.format_score_with_context(score, result["search_type"]) if score is not None else "N/A"

                    # Check if this is an expected item
                    is_expected = item_id in result.get("expected_items", [])
                    expected_marker = ""
                    if is_expected:
                        relevance = result.get("expected_relevance", {}).get(item_id, "")
                        expected_marker = f" [Expected: {relevance}] ✓"

                    # Get score gap
                    gap_str = ""
                    if i < len(score_gaps):
                        gap = score_gaps[i]
                        gap_str = f" [gap: {evaluator.format_score_with_context(gap, result['search_type'])}]"

                    # Get metadata if available
                    metadata_str = ""
                    if i < len(retrieved_metadata):
                        meta = retrieved_metadata[i]
                        category = meta.get("category", "")
                        headline = meta.get("headline", "")
                        if category or headline:
                            metadata_str = f" - {category}"
                            if headline:
                                truncated_headline = headline[:40] + "..." if len(headline) > 40 else headline
                                metadata_str += f": \"{truncated_headline}\""

                    lines.append(f"  - {i+1}. {item_id[:8]}... (score: {score_str}){expected_marker}{gap_str}{metadata_str}")

                if len(result["retrieved_items"]) > 3:
                    lines.append(f"  - ... (+{len(result['retrieved_items'])-3} more)")

                # Show score confidence if available
                if score_gaps:
                    confidence = evaluator.get_score_confidence_label(score_gaps)
                    lines.append(f"- **Score Confidence**: {confidence}")

                # Show relevance alignment for expected items not in top 3
                relevance_alignment = result.get("relevance_alignment", [])
                if relevance_alignment:
                    missing_expected = [
                        align for align in relevance_alignment
                        if align["actual_rank"] is None or align["actual_rank"] > 3
                    ]
                    if missing_expected:
                        lines.append("- **Expected Items Not in Top-3**:")
                        for align in missing_expected[:2]:  # Show up to 2
                            item_id = align["item_id"]
                            rel = align["expected_relevance"]
                            rank = align["actual_rank"]
                            rank_str = f"Rank {rank}" if rank else "Not retrieved"
                            score = align["actual_score"]
                            score_str = evaluator.format_score_with_context(score, result["search_type"]) if score is not None else "N/A"
                            lines.append(f"  - {item_id[:8]}... ({rel}) → {rank_str}, score: {score_str}")

                if result.get("first_relevant_rank"):
                    lines.append(f"- **First Relevant at Rank**: {result['first_relevant_rank']}")
            else:
                lines.append(f"- **Retrieved**: 0 results")

            # Show metrics
            if result.get("metrics"):
                m = result["metrics"]
                p5 = m["precision"].get("@5", 0)
                r5 = m["recall"].get("@5", 0)
                rr = m.get("reciprocal_rank", 0)
                lines.append(f"- **Metrics**: P@5: {p5:.2f} | R@5: {r5:.2f} | RR: {rr:.2f}")

            # Show retrieval time with outlier detection
            retrieval_time = result.get("retrieval_time_ms", 0)
            if retrieval_time > 0:
                timing_stats = evaluator.calculate_timing_stats()
                avg_time = timing_stats.get("avg_retrieval_time_ms", 0)
                outlier_marker = ""
                if avg_time > 0 and retrieval_time > avg_time * 2:
                    ratio = retrieval_time / avg_time
                    outlier_marker = f" ⚠ (outlier - {ratio:.1f}x average)"
                lines.append(f"- **Retrieval Time**: {retrieval_time:.1f}ms{outlier_marker}")

            # Enhanced false positive analysis for edge cases
            if result["status"] == "false_positive":
                score_stats = result.get("score_stats", {})
                if score_stats:
                    lines.append("- **False Positive Analysis**:")
                    top_scores = result.get("retrieved_scores", [])[:3]
                    score_strs = [evaluator.format_score_with_context(s, result["search_type"]) for s in top_scores]
                    lines.append(f"  - Top scores: {', '.join(score_strs)}")

                    # Category breakdown
                    categories = {}
                    for meta in result.get("retrieved_metadata", []):
                        cat = meta.get("category", "Unknown")
                        categories[cat] = categories.get(cat, 0) + 1
                    if categories:
                        cat_str = ", ".join(f"{cat} ({count})" for cat, count in sorted(categories.items()))
                        lines.append(f"  - Categories: {cat_str}")

            lines.append(f"- **Status**: {status}")

            if result.get("error"):
                lines.append(f"- **Error**: {result['error']}")

            lines.append("")

        return "\n".join(lines)

    def _generate_detailed_query_results(self, results_by_search_type: Dict) -> List[str]:
        """Generate detailed per-query comparison across search types."""
        lines = [
            "## Detailed Query Results",
            "",
            "Per-query breakdown comparing all search types. Shows top-3 results, metrics, and status for each search method.",
            "",
        ]

        # Get all queries from first search type
        first_search_type = self.search_types[0]
        all_queries = results_by_search_type[first_search_type]["query_results"]

        for query_result in all_queries:
            query_id = query_result["query_id"]
            query_text = query_result["query_text"]
            query_type = query_result["query_type"]

            lines.extend([
                f"### Query: {query_id} - \"{query_text}\"",
                f"- **Type**: {query_type}",
            ])

            # Show expected items (from first search type as reference)
            expected_items = query_result.get("expected_items", [])
            if expected_items:
                expected_relevance = query_result.get("expected_relevance", {})
                expected_str = ", ".join([
                    f"{item_id[:8]}... ({expected_relevance.get(item_id, 'unknown')})"
                    for item_id in expected_items[:3]
                ])
                if len(expected_items) > 3:
                    expected_str += f" (+{len(expected_items) - 3} more)"
                lines.append(f"- **Expected**: {expected_str}")

            lines.append("")

            # Show results for each search type
            for search_type in self.search_types:
                # Find corresponding query result for this search type
                st_results = results_by_search_type[search_type]["query_results"]
                st_query = next((r for r in st_results if r["query_id"] == query_id), None)

                if not st_query:
                    continue

                status = st_query.get("status", "unknown")
                status_symbol = self._get_status_symbol(status)

                lines.append(f"**{search_type}** {status_symbol}:")

                # Show error if present
                if "error" in st_query:
                    lines.append(f"  - Error: {st_query['error']}")
                    lines.append("")
                    continue

                # Top-3 results
                retrieved_metadata = st_query.get("retrieved_metadata", [])
                expected_set = set(expected_items)

                if retrieved_metadata:
                    lines.append("  - Top-3 Results:")
                    for i, item in enumerate(retrieved_metadata[:3], 1):
                        item_id = item["item_id"]
                        score = item["score"]
                        category = item.get("category", "Unknown")
                        headline = item.get("headline", "No headline")[:40]

                        # Check if expected
                        is_expected = "✓" if item_id in expected_set else ""
                        relevance = query_result.get("expected_relevance", {}).get(item_id, "")
                        expected_str = f" [Expected: {relevance}]" if is_expected else ""

                        lines.append(f"    {i}. {item_id[:8]}... (score: {score:.2f}) {is_expected}{expected_str} - {category}: \"{headline}...\"")

                    if len(retrieved_metadata) > 3:
                        lines.append(f"    ... (+{len(retrieved_metadata) - 3} more)")
                else:
                    lines.append("  - No results retrieved")

                # Metrics
                metrics = st_query.get("metrics", {})
                p5 = metrics.get("precision", {}).get("@5", 0)
                r5 = metrics.get("recall", {}).get("@5", 0)
                rr = metrics.get("reciprocal_rank", 0)
                lines.append(f"  - Metrics: P@5: {p5:.2f} | R@5: {r5:.2f} | RR: {rr:.2f}")

                # Retrieval time
                time_ms = st_query.get("retrieval_time_ms", 0)
                lines.append(f"  - Time: {time_ms:.1f}ms")
                lines.append("")

            lines.append("")  # Extra spacing between queries

        return lines

    def _format_config_table(self) -> List[str]:
        """Format search configuration as a markdown table (Option 2 format)."""
        if not self.search_config:
            return []

        lines = [
            "## Search Configuration",
            "",
            "Runtime configuration captured at evaluation time:",
            "",
        ]

        # Create table for each configured search type
        for search_type in self.search_types:
            config = self.search_config.get(search_type, {})
            if not config:
                continue

            lines.extend([
                f"### {search_type}",
                "",
                "| Parameter | Value |",
                "|-----------|-------|",
            ])

            # Algorithm and implementation
            if "algorithm" in config:
                lines.append(f"| **Algorithm** | {config['algorithm']} |")
            if "implementation" in config:
                lines.append(f"| **Implementation** | {config['implementation']} |")
            if "embedding_model" in config:
                lines.append(f"| **Embedding Model** | {config['embedding_model']} |")

            # RRF-specific parameters
            if "rrf_constant_c" in config:
                lines.append(f"| **RRF Constant (c)** | {config['rrf_constant_c']} |")
            if "weights" in config:
                weights = config["weights"]
                if isinstance(weights, dict):
                    weight_str = ", ".join([f"{k}={v}" for k, v in weights.items()])
                    lines.append(f"| **Weights** | {weight_str} |")
            if "fetch_multiplier" in config:
                lines.append(f"| **Fetch Strategy** | {config['fetch_multiplier']} |")
            if "deduplication" in config:
                lines.append(f"| **Deduplication** | {config['deduplication']} |")

            # Content field / field weighting
            if "content_field" in config:
                lines.append(f"| **Content Field** | {config['content_field']} |")
            elif "field_weighting" in config:
                field_weights = config["field_weighting"]
                if isinstance(field_weights, dict):
                    lines.append(f"| **Field Weighting** | |")
                    for field, weight in field_weights.items():
                        lines.append(f"| &nbsp;&nbsp;&nbsp;• {field} | {weight} |")
                elif isinstance(field_weights, str):
                    lines.append(f"| **Field Weighting** | {field_weights} |")

            # Tokenizer (for BM25 methods)
            if "tokenizer" in config:
                lines.append(f"| **Tokenizer** | {config['tokenizer']} |")

            lines.extend(["", ""])

        lines.extend(["---", ""])
        return lines

    def _generate_multi_markdown_report(
        self, run_id: str, results_by_search_type: Dict, comparison: Dict,
        actual_item_count: int, item_count_valid: bool
    ) -> str:
        """Generate comparison markdown report for multiple search types."""
        evaluator = list(self.evaluators.values())[0]  # Get any evaluator for top_k_values

        lines = [
            "# Retrieval Evaluation Report (Multi-Search Comparison)",
            "",
            f"**Run ID**: {run_id}",
            f"**Timestamp**: {datetime.now(timezone.utc).isoformat()}",
            f"**API Endpoint**: {self.base_url}",
            f"**Dataset**: {Path(self.args.dataset).name} ({len(evaluator.results)} queries)",
            f"**Search Types**: {', '.join(self.search_types)}",
            f"**Parallel Execution**: {'Yes' if self.args.parallel else 'No'}",
            f"**Target Items**: {self.args.expected_items} | **Actual Items**: {actual_item_count} {'✓' if item_count_valid else '✗'}",
            "",
            "---",
            "",
        ]

        # Add search configuration section if available
        config_lines = self._format_config_table()
        if config_lines:
            lines.extend(config_lines)

        # Performance comparison
        if "performance" in comparison and comparison["performance"]:
            lines.extend([
                "## Performance Comparison",
                "",
                "| Search Type | Avg Time (ms) | Min (ms) | Max (ms) |",
                "|-------------|---------------|----------|----------|",
            ])

            for search_type in self.search_types:
                perf = comparison["performance"].get(search_type, {})
                avg = perf.get("avg_retrieval_time_ms", 0)
                min_t = perf.get("min_retrieval_time_ms", 0)
                max_t = perf.get("max_retrieval_time_ms", 0)
                lines.append(f"| **{search_type}** | {avg:.1f} | {min_t:.1f} | {max_t:.1f} |")

            lines.extend(["", "---", ""])

        # Summary metrics comparison
        lines.extend([
            "## Summary Metrics Comparison",
            "",
        ])

        # Create comparison tables for precision, recall, NDCG
        for metric_name in ["Precision", "Recall", "NDCG"]:
            lines.extend([
                f"### {metric_name}",
                "",
                "| Metric | " + " | ".join(f"**{st}**" for st in self.search_types) + " | Δ (abs) | Δ (%) | Winner |",
                "|--------|" + "|".join("------" for _ in self.search_types) + "|---------|-------|--------|",
            ])

            for k in evaluator.top_k_values:
                metric_key = f"{metric_name.lower()}@{k}"
                row_parts = [f"**@{k}**"]

                # Get values for each search type
                values = []
                for search_type in self.search_types:
                    summary = results_by_search_type[search_type]["summary"]
                    val = summary[metric_name.lower()].get(f"@{k}", 0)
                    values.append(val)
                    row_parts.append(f"{val:.3f}")

                # Calculate comparison metrics
                if len(self.search_types) == 2 and metric_key in comparison.get("metric_differences", {}):
                    # Use pre-calculated pairwise comparison
                    delta_info = comparison["metric_differences"][metric_key]
                    diff = delta_info.get("difference", 0)
                    pct = delta_info.get("percent_change", 0)
                    winner = delta_info.get("winner", "-")
                    row_parts.extend([
                        f"{diff:+.3f}",
                        f"{pct:+.1f}%",
                        winner.upper()
                    ])
                elif len(self.search_types) > 2:
                    # Calculate on-the-fly for multi-search
                    max_val = max(values)
                    min_val = min(values)
                    winner_idx = values.index(max_val)
                    winner = self.search_types[winner_idx]

                    # Delta: max - min
                    diff = max_val - min_val
                    pct = (diff / min_val * 100) if min_val > 0 else 0

                    row_parts.extend([
                        f"{diff:+.3f}",
                        f"{pct:+.1f}%",
                        winner.upper()
                    ])
                else:
                    row_parts.extend(["-", "-", "-"])

                lines.append("| " + " | ".join(row_parts) + " |")

            lines.extend(["", ""])

        # MRR comparison
        lines.extend([
            "### Mean Reciprocal Rank (MRR)",
            "",
            "| Search Type | MRR | Δ vs best | Winner |",
            "|-------------|-----|-----------|--------|",
        ])

        # Collect all MRR values
        mrr_values = []
        for search_type in self.search_types:
            summary = results_by_search_type[search_type]["summary"]
            mrr_values.append(summary["mrr"])

        # Find best MRR
        best_mrr = max(mrr_values)
        winner_idx = mrr_values.index(best_mrr)
        winner_search_type = self.search_types[winner_idx]

        # Generate rows
        for idx, search_type in enumerate(self.search_types):
            summary = results_by_search_type[search_type]["summary"]
            mrr = summary["mrr"]

            # Calculate delta from best
            if len(self.search_types) >= 2:
                delta = mrr - best_mrr
                delta_str = f"{delta:+.3f}" if delta != 0 else "-"
            else:
                delta_str = "-"

            # Mark winner
            winner_mark = "✓" if search_type == winner_search_type else ""

            lines.append(f"| **{search_type}** | {mrr:.3f} | {delta_str} | {winner_mark} |")

        lines.extend(["", "---", ""])

        # Agreement analysis
        if "agreement" in comparison and comparison["agreement"]:
            agreement = comparison["agreement"]
            lines.extend([
                "## Agreement Analysis",
                "",
                f"### Rank-1 Agreement",
                f"- **{agreement.get('rank_1_agreement', 0)*100:.1f}%** of queries return the same top result",
                f"- Based on {agreement.get('comparable_queries', 0)} comparable queries",
                "",
                f"### Top-K Overlap (Jaccard Similarity)",
                f"- **Top-3 Average**: {agreement.get('top_3_overlap', 0):.2f} ({agreement.get('top_3_overlap', 0)*100:.0f}% overlap in top 3 results)",
                f"- **Top-5 Average**: {agreement.get('top_5_overlap', 0):.2f} ({agreement.get('top_5_overlap', 0)*100:.0f}% overlap in top 5 results)",
                "",
                "---",
                "",
            ])

        # Per-query comparison (new section)
        per_query_comparisons = self._generate_per_query_comparison()
        if per_query_comparisons and len(self.search_types) == 2:
            type1, type2 = self.search_types

            # Calculate summary statistics
            vector_wins = sum(1 for c in per_query_comparisons if c["winner"] == type2 and type2 == "vector")
            bm25_wins = sum(1 for c in per_query_comparisons if c["winner"] == type1 and type1 == "bm25")
            ties = sum(1 for c in per_query_comparisons if c["winner"] == "tie")
            rank1_same = sum(1 for c in per_query_comparisons if c["rank1_agreement"])
            total = len(per_query_comparisons)

            lines.extend([
                "## Per-Query Search Type Comparison",
                "",
                "### Agreement Summary",
                f"- Queries with same rank-1: {rank1_same}/{total} ({100*rank1_same/total:.1f}%)",
                f"- Queries where {type2} won: {vector_wins if type2 == 'vector' else 0}/{total} ({100*(vector_wins if type2 == 'vector' else 0)/total:.1f}%)",
                f"- Queries where {type1} won: {bm25_wins if type1 == 'bm25' else 0}/{total} ({100*(bm25_wins if type1 == 'bm25' else 0)/total:.1f}%)",
                f"- Ties: {ties}/{total} ({100*ties/total:.1f}%)",
                "",
            ])

            # Show queries where vector significantly outperformed
            significant_vector_wins = [
                c for c in per_query_comparisons
                if c["winner"] == "vector" and c["mrr_diff"] > 0.2
            ]
            if significant_vector_wins:
                lines.extend([
                    f"### Queries Where Vector Significantly Outperformed (MRR Δ > 0.2)",
                    "",
                    f"| Query ID | Type | {type1.upper()} Rank | {type2.upper()} Rank | Δ MRR | Query Text |",
                    "|----------|------|----------|----------|-------|------------|",
                ])
                for c in significant_vector_wins[:10]:  # Show top 10
                    q_text = c["query_text"][:40] + "..." if len(c["query_text"]) > 40 else c["query_text"]
                    r1 = c.get(f"{type1}_first_rank", "-") or "-"
                    r2 = c.get(f"{type2}_first_rank", "-") or "-"
                    lines.append(f"| {c['query_id']} | {c['query_type']} | {r1} | {r2} | {c['mrr_diff']:+.2f} | {q_text} |")
                lines.extend(["", ""])

            # Show queries where BM25 outperformed
            bm25_wins_list = [
                c for c in per_query_comparisons
                if c["winner"] == "bm25" and c["mrr_diff"] < -0.1
            ]
            if bm25_wins_list:
                lines.extend([
                    f"### Queries Where BM25 Outperformed Vector (MRR Δ < -0.1)",
                    "",
                    f"| Query ID | Type | {type1.upper()} Rank | {type2.upper()} Rank | Δ MRR | Query Text |",
                    "|----------|------|----------|----------|-------|------------|",
                ])
                for c in bm25_wins_list[:10]:  # Show top 10
                    q_text = c["query_text"][:40] + "..." if len(c["query_text"]) > 40 else c["query_text"]
                    r1 = c.get(f"{type1}_first_rank", "-") or "-"
                    r2 = c.get(f"{type2}_first_rank", "-") or "-"
                    lines.append(f"| {c['query_id']} | {c['query_type']} | {r1} | {r2} | {c['mrr_diff']:+.2f} | {q_text} |")
                lines.extend(["", ""])

            lines.extend(["---", ""])

        # By query type comparison
        lines.extend([
            "## By Query Type Comparison",
            "",
        ])

        # Collect all query types
        all_query_types = set()
        for search_type in self.search_types:
            all_query_types.update(results_by_search_type[search_type]["by_query_type"].keys())

        for qtype in sorted(all_query_types):
            lines.extend([
                f"### {qtype}",
                "",
                "| Metric | " + " | ".join(f"**{st}**" for st in self.search_types) + " | Winner |",
                "|--------|" + "|".join("------" for _ in self.search_types) + "|--------|",
            ])

            for metric_name, metric_key in [("P@5", "precision"), ("R@5", "recall"), ("MRR", "mrr")]:
                row = [metric_name]
                values = []

                for search_type in self.search_types:
                    by_type = results_by_search_type[search_type]["by_query_type"]
                    if qtype in by_type:
                        if metric_key == "mrr":
                            val = by_type[qtype].get(metric_key, 0)
                        else:
                            val = by_type[qtype].get(metric_key, {}).get("@5", 0)
                        values.append(val)
                        row.append(f"{val:.2f}")
                    else:
                        values.append(0)
                        row.append("-")

                # Determine winner
                if values:
                    max_val = max(values)
                    winner_idx = values.index(max_val)
                    winner = self.search_types[winner_idx].upper() if max_val > 0 else "-"
                    row.append(winner)
                else:
                    row.append("-")

                lines.append("| " + " | ".join(row) + " |")

            lines.extend(["", ""])

        # Detailed query results (if not skipped)
        if not self.args.skip_details:
            detailed_lines = self._generate_detailed_query_results(results_by_search_type)
            if detailed_lines:
                lines.extend(["---", ""])
                lines.extend(detailed_lines)

        return "\n".join(lines)

    def run(self):
        """Main execution flow."""
        print("=" * 60)
        print("Retrieval Evaluation Script")
        print("=" * 60)

        # Find and validate API
        self.base_url = self.find_api_endpoint()

        # Show which database is being used
        if self.use_golden_subdomain and not self.args.base_url:
            print(f"✓ API endpoint: {self.base_url}")
            print(f"✓ Database routing: golden (via Host: golden.localhost subdomain)")
        else:
            print(f"✓ API endpoint: {self.base_url}")
            print(f"✓ Database routing: production (default)")

        # Initialize evaluators for each search type
        self._initialize_evaluators()

        # Validate item count
        actual_item_count, item_count_valid = self.validate_item_count()
        if item_count_valid:
            print(f"✓ Item count validated: {actual_item_count} items")
        else:
            print(f"⚠ Item count mismatch (proceeding anyway)")

        # Load dataset
        self.load_dataset()

        # Fetch search configuration
        self.fetch_search_config()

        # Run evaluation
        total_time = self.run_evaluation()

        # Generate reports
        run_id = f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.generate_reports(run_id, total_time, actual_item_count, item_count_valid)

        print("\n" + "=" * 60)
        print("Evaluation complete!")
        print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate retrieval quality for Collections App search API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--port", type=int, default=8000, help="API port (default: 8000)"
    )
    parser.add_argument("--base-url", type=str, help="Full base URL (overrides port if provided)")
    parser.add_argument(
        "--use-golden-subdomain",
        action="store_true",
        default=True,
        help="Use golden.localhost subdomain routing to access golden database (default: True)"
    )
    parser.add_argument(
        "--no-golden-subdomain",
        dest="use_golden_subdomain",
        action="store_false",
        help="Disable golden subdomain routing (for testing against production DB)"
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="data/eval/retrieval_evaluation_dataset.json",
        help="Path to evaluation dataset JSON",
    )
    parser.add_argument(
        "--output-dir", type=str, default="data/eval/reports", help="Directory for output reports"
    )
    parser.add_argument(
        "--top-k",
        type=str,
        default="1,3,5,10",
        help="Comma-separated K values for metrics (default: 1,3,5,10)",
    )
    parser.add_argument(
        "--expected-items",
        type=int,
        default=55,
        help="Expected item count in target database (default: 55 for golden DB)",
    )
    parser.add_argument(
        "--skip-item-check", action="store_true", help="Skip the item count validation"
    )
    parser.add_argument("--verbose", action="store_true", help="Print detailed progress")

    # Multi-search type support
    parser.add_argument(
        "--search-types",
        type=str,
        default="all",
        help="Comma-separated search types to evaluate: 'bm25', 'vector', 'bm25-lc', 'vector-lc', 'hybrid', 'hybrid-lc', or 'all' (default: all)"
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        default=True,
        help="Run search types in parallel per query for faster evaluation (default: True)"
    )
    parser.add_argument(
        "--no-parallel",
        dest="parallel",
        action="store_false",
        help="Disable parallel execution (run search types sequentially)"
    )
    parser.add_argument(
        "--skip-details",
        action="store_true",
        default=False,
        help="Skip detailed per-query results in reports (default: include details)"
    )

    args = parser.parse_args()

    evaluator = MultiSearchRetrievalEvaluator(args)
    evaluator.run()


if __name__ == "__main__":
    main()
