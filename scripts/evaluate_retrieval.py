#!/usr/bin/env python3
"""
Retrieval Evaluation Script for Collections App API

Evaluates search/retrieval quality using a golden dataset and calculates
standard Information Retrieval metrics (Precision@K, Recall@K, MRR, NDCG@K).
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests


class RetrievalEvaluator:
    """Evaluates retrieval quality for the Collections App search API."""

    RELEVANCE_SCORES = {"high": 3, "medium": 2, "low": 1}
    DEFAULT_PORTS = [8000, 8001, 8080, 3000]

    def __init__(self, args):
        self.args = args
        self.base_url = None
        self.top_k_values = [int(k) for k in args.top_k.split(",")]
        self.max_k = max(self.top_k_values)
        self.verbose = args.verbose
        self.dataset = None
        self.results = []
        # Use golden subdomain routing by default
        self.use_golden_subdomain = getattr(args, 'use_golden_subdomain', True)

    def log(self, message: str, force: bool = False):
        """Print message if verbose mode is enabled or force is True."""
        if self.verbose or force:
            print(message)

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

    def search(self, query_text: str) -> Dict:
        """Call the search API."""
        try:
            headers = self._get_request_headers()
            response = requests.post(
                f"{self.base_url}/search",
                json={"query": query_text, "top_k": self.max_k, "include_answer": False},
                headers=headers,
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
        """Evaluate a single query."""
        query_id = query["query_id"]
        query_text = query["query_text"]
        query_type = query["query_type"]
        expected_items = query["expected_items"]

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

        # Handle edge cases (no results expected)
        if expected_count == 0:
            status = "true_negative" if len(retrieved_ids) == 0 else "false_positive"
            return {
                "query_id": query_id,
                "query_text": query_text,
                "query_type": query_type,
                "expected_items": expected_ids,
                "expected_relevance": {},
                "retrieved_items": retrieved_ids,
                "retrieved_scores": retrieved_scores,
                "retrieval_time_ms": retrieval_time_ms,
                "status": status,
                "metrics": {},
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

        return {
            "query_id": query_id,
            "query_text": query_text,
            "query_type": query_type,
            "expected_items": expected_ids,
            "expected_relevance": {item["item_id"]: item["relevance"] for item in expected_items},
            "retrieved_items": retrieved_ids,
            "retrieved_scores": retrieved_scores,
            "retrieval_time_ms": retrieval_time_ms,
            "metrics": metrics,
            "first_relevant_rank": first_relevant_rank,
            "status": status,
        }

    def run_evaluation(self):
        """Run evaluation on all queries."""
        queries = self.dataset["queries"]
        total = len(queries)

        print(f"\nEvaluating {total} queries...")
        start_time = time.time()

        for i, query in enumerate(queries, start=1):
            result = self.evaluate_query(query)
            self.results.append(result)

            if self.verbose:
                status_symbol = {"pass": "✓", "partial": "~", "fail": "✗", "error": "⚠", "true_negative": "✓", "false_positive": "✗"}
                symbol = status_symbol.get(result["status"], "?")
                print(f"  [{i}/{total}] {symbol} {result['query_id']}: {result['query_text'][:50]}")
            else:
                # Progress indicator
                if i % 5 == 0 or i == total:
                    print(f"  Progress: {i}/{total} ({100*i//total}%)", end="\r")

        if not self.verbose:
            print()  # New line after progress

        elapsed = time.time() - start_time
        print(f"Completed in {elapsed:.2f}s")

        return elapsed

    def aggregate_metrics(self) -> Dict:
        """Aggregate metrics across all queries."""
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
        """Aggregate metrics by query type."""
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
        """Calculate timing statistics."""
        retrieval_times = [r["retrieval_time_ms"] for r in self.results if r["retrieval_time_ms"] > 0]

        if not retrieval_times:
            return {"avg_retrieval_time_ms": 0, "min_retrieval_time_ms": 0, "max_retrieval_time_ms": 0}

        return {
            "avg_retrieval_time_ms": sum(retrieval_times) / len(retrieval_times),
            "min_retrieval_time_ms": min(retrieval_times),
            "max_retrieval_time_ms": max(retrieval_times),
        }

    def generate_reports(self, run_id: str, total_time: float, actual_item_count: int, item_count_valid: bool):
        """Generate markdown and JSON reports."""
        output_dir = Path(self.args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        summary = self.aggregate_metrics()
        by_query_type = self.aggregate_by_query_type()
        timing_stats = self.calculate_timing_stats()

        # Generate JSON report
        json_report = {
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config": {
                "api_base_url": self.base_url,
                "dataset_path": self.args.dataset,
                "top_k_values": self.top_k_values,
                "dataset_version": self.dataset["metadata"].get("version", "unknown"),
                "total_queries": len(self.results),
                "target_item_count": self.args.expected_items,
                "actual_item_count": actual_item_count,
            },
            "summary": summary,
            "by_query_type": by_query_type,
            "query_results": self.results,
            "timing": {
                "total_evaluation_time_s": total_time,
                **timing_stats,
            },
        }

        json_path = output_dir / f"{run_id}_report.json"
        with open(json_path, "w") as f:
            json.dump(json_report, f, indent=2)

        # Generate Markdown report
        md_report = self._generate_markdown_report(
            run_id, summary, by_query_type, actual_item_count, item_count_valid
        )

        md_path = output_dir / f"{run_id}_report.md"
        with open(md_path, "w") as f:
            f.write(md_report)

        print(f"\n✓ Reports generated:")
        print(f"  - {json_path}")
        print(f"  - {md_path}")

    def _generate_markdown_report(
        self, run_id: str, summary: Dict, by_query_type: Dict, actual_item_count: int, item_count_valid: bool
    ) -> str:
        """Generate markdown report content."""
        lines = [
            "# Retrieval Evaluation Report",
            "",
            f"**Run ID**: {run_id}",
            f"**Timestamp**: {datetime.now(timezone.utc).isoformat()}",
            f"**API Endpoint**: {self.base_url}",
            f"**Dataset**: {Path(self.args.dataset).name} ({len(self.results)} queries)",
            f"**Target Items**: {self.args.expected_items} | **Actual Items**: {actual_item_count} {'✓' if item_count_valid else '✗'}",
            "",
            "## Summary Metrics",
            "",
            "| Metric | " + " | ".join(f"@{k}" for k in self.top_k_values) + " |",
            "|--------|" + "|".join("-----" for _ in self.top_k_values) + "|",
        ]

        # Precision row
        lines.append(
            "| Precision | "
            + " | ".join(f"{summary['precision'].get(f'@{k}', 0):.3f}" for k in self.top_k_values)
            + " |"
        )

        # Recall row
        lines.append(
            "| Recall | "
            + " | ".join(f"{summary['recall'].get(f'@{k}', 0):.3f}" for k in self.top_k_values)
            + " |"
        )

        # NDCG row
        lines.append(
            "| NDCG | " + " | ".join(f"{summary['ndcg'].get(f'@{k}', 0):.3f}" for k in self.top_k_values) + " |"
        )

        lines.extend(
            [
                "",
                f"**MRR**: {summary['mrr']:.3f}",
                "",
            ]
        )

        # Edge cases
        if summary["edge_cases"]["total"] > 0:
            ec = summary["edge_cases"]
            lines.extend(
                [
                    "### Edge Cases (No Results Expected)",
                    f"- True Negatives: {ec['true_negatives']}/{ec['total']} ({ec['tn_rate']*100:.1f}%)",
                    f"- False Positives: {ec['false_positives']}/{ec['total']} ({ec['fp_rate']*100:.1f}%)",
                    "",
                ]
            )

        # By query type
        if by_query_type:
            lines.extend(
                [
                    "### By Query Type",
                    "",
                    "| Type | Count | P@5 | R@5 | MRR |",
                    "|------|-------|-----|-----|-----|",
                ]
            )

            for qtype, metrics in sorted(by_query_type.items()):
                p5 = metrics["precision"].get("@5", 0)
                r5 = metrics["recall"].get("@5", 0)
                mrr = metrics["mrr"]
                lines.append(f"| {qtype} | {metrics['count']} | {p5:.2f} | {r5:.2f} | {mrr:.2f} |")

            lines.append("")

        # Detailed results
        lines.extend(
            [
                "## Detailed Results",
                "",
            ]
        )

        for result in self.results:
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

            if result.get("retrieved_items"):
                retrieved_str = ", ".join(f"{item_id[:8]}..." for item_id in result["retrieved_items"][:3])
                if len(result["retrieved_items"]) > 3:
                    retrieved_str += f" (+{len(result['retrieved_items'])-3} more)"
                lines.append(f"- **Retrieved@{self.max_k}**: {retrieved_str}")
                if result.get("first_relevant_rank"):
                    lines.append(f"- **First relevant at rank**: {result['first_relevant_rank']}")
            else:
                lines.append(f"- **Retrieved**: 0 results")

            if result.get("metrics"):
                m = result["metrics"]
                p5 = m["precision"].get("@5", 0)
                r5 = m["recall"].get("@5", 0)
                rr = m.get("reciprocal_rank", 0)
                lines.append(f"- **P@5**: {p5:.2f} | **R@5**: {r5:.2f} | **RR**: {rr:.2f}")

            lines.append(f"- **Status**: {status}")

            if result.get("error"):
                lines.append(f"- **Error**: {result['error']}")

            lines.append("")

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

        # Validate item count
        actual_item_count, item_count_valid = self.validate_item_count()
        if item_count_valid:
            print(f"✓ Item count validated: {actual_item_count} items")
        else:
            print(f"⚠ Item count mismatch (proceeding anyway)")

        # Load dataset
        self.load_dataset()

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

    args = parser.parse_args()

    evaluator = RetrievalEvaluator(args)
    evaluator.run()


if __name__ == "__main__":
    main()
