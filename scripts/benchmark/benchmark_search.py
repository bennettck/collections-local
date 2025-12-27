#!/usr/bin/env python3
"""
Benchmark Search Performance

Compares search quality and speed across different retrieval methods:
- Hybrid search (BM25 + vector)
- BM25 only
- Vector search only

Metrics:
- Latency (mean, median, p95, p99)
- Quality (precision@k, recall@k, NDCG)
- Throughput

Usage:
    python benchmark_search.py --env dev
    python benchmark_search.py --env dev --queries test_queries.json
    python benchmark_search.py --env dev --method hybrid
"""

import argparse
import json
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

import boto3


class SearchBenchmark:
    """Benchmark search performance and quality."""

    def __init__(self, env: str = "dev"):
        """
        Initialize search benchmarker.

        Args:
            env: Environment name (dev, test, prod)
        """
        self.env = env
        self.config = self._load_config()

        # Initialize AWS clients
        self.lambda_client = boto3.client(
            'lambda',
            region_name=self.config.get('region', 'us-east-1')
        )

        # Extract Lambda ARN for search/API
        self.api_lambda_name = self.config.get('api_lambda_name')

        self.results = {
            'environment': env,
            'timestamp': datetime.utcnow().isoformat(),
            'search_methods': {},
            'summary': {}
        }

    def _load_config(self) -> Dict[str, Any]:
        """Load AWS outputs from configuration file."""
        config_path = Path(f"/workspaces/collections-local/infrastructure/.aws-outputs-{self.env}.json")

        if not config_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {config_path}\n"
                f"Run 'make infra-deploy ENV={self.env}' first."
            )

        with open(config_path) as f:
            outputs = json.load(f)

        # Parse outputs
        config = {'region': 'us-east-1'}

        for output in outputs:
            key = output.get('OutputKey', '')
            value = output.get('OutputValue', '')

            if 'APILambdaName' in key:
                config['api_lambda_name'] = value

        return config

    def _invoke_search(self, query: str, method: str = 'hybrid',
                      k: int = 10, user_id: str = 'benchmark-user') -> Dict[str, Any]:
        """
        Invoke search via Lambda.

        Args:
            query: Search query
            method: Search method (hybrid, bm25, vector)
            k: Number of results
            user_id: User ID for filtering

        Returns:
            Search response with timing
        """
        # Construct Lambda payload for search endpoint
        payload = {
            'httpMethod': 'POST',
            'path': '/search',
            'body': json.dumps({
                'query': query,
                'method': method,
                'k': k,
                'user_id': user_id
            }),
            'headers': {
                'Content-Type': 'application/json'
            }
        }

        start = time.time()

        try:
            response = self.lambda_client.invoke(
                FunctionName=self.api_lambda_name,
                InvocationType='RequestResponse',
                Payload=json.dumps(payload)
            )

            duration = (time.time() - start) * 1000  # ms

            # Parse response
            response_payload = json.loads(response['Payload'].read())

            # Extract search results from response body
            body = json.loads(response_payload.get('body', '{}'))

            return {
                'success': response_payload.get('statusCode') == 200,
                'duration_ms': duration,
                'results': body.get('results', []),
                'total_results': body.get('total', 0),
                'error': None
            }

        except Exception as e:
            duration = (time.time() - start) * 1000
            return {
                'success': False,
                'duration_ms': duration,
                'results': [],
                'total_results': 0,
                'error': str(e)
            }

    def benchmark_search_method(self, method: str, queries: List[str],
                                k: int = 10,
                                ground_truth: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
        """
        Benchmark a specific search method.

        Args:
            method: Search method (hybrid, bm25, vector)
            queries: List of test queries
            k: Number of results to retrieve
            ground_truth: Optional ground truth for quality metrics

        Returns:
            Benchmark results
        """
        print(f"\n{'='*60}")
        print(f"Benchmarking: {method.upper()} Search")
        print(f"{'='*60}")
        print(f"Queries: {len(queries)}")
        print(f"k: {k}")

        latencies = []
        successes = []
        all_results = []

        for i, query in enumerate(queries, 1):
            print(f"\rProcessing query {i}/{len(queries)}...", end='', flush=True)

            result = self._invoke_search(query, method=method, k=k)

            latencies.append(result['duration_ms'])
            successes.append(result['success'])
            all_results.append({
                'query': query,
                'results': result['results'],
                'duration_ms': result['duration_ms'],
                'success': result['success'],
                'error': result.get('error')
            })

        print()  # New line after progress

        # Calculate latency statistics
        latency_stats = {
            'min_ms': min(latencies) if latencies else 0,
            'max_ms': max(latencies) if latencies else 0,
            'mean_ms': statistics.mean(latencies) if latencies else 0,
            'median_ms': statistics.median(latencies) if latencies else 0,
            'p95_ms': self._percentile(latencies, 95),
            'p99_ms': self._percentile(latencies, 99),
            'stddev_ms': statistics.stdev(latencies) if len(latencies) > 1 else 0
        }

        # Calculate success rate
        success_rate = sum(successes) / len(successes) * 100 if successes else 0

        # Print results
        print(f"\nLatency:")
        print(f"  Mean:   {latency_stats['mean_ms']:.2f}ms")
        print(f"  Median: {latency_stats['median_ms']:.2f}ms")
        print(f"  P95:    {latency_stats['p95_ms']:.2f}ms")
        print(f"  P99:    {latency_stats['p99_ms']:.2f}ms")
        print(f"\nSuccess Rate: {success_rate:.1f}%")

        results = {
            'method': method,
            'queries_count': len(queries),
            'k': k,
            'latency': latency_stats,
            'success_rate': success_rate,
            'query_results': all_results
        }

        # Add quality metrics if ground truth provided
        if ground_truth:
            quality_metrics = self._calculate_quality_metrics(
                all_results, ground_truth, k
            )
            results['quality'] = quality_metrics

            print(f"\nQuality Metrics:")
            print(f"  Precision@{k}: {quality_metrics['precision_at_k']:.3f}")
            print(f"  Recall@{k}:    {quality_metrics['recall_at_k']:.3f}")
            print(f"  MRR:           {quality_metrics['mrr']:.3f}")

        return results

    def _percentile(self, data: List[float], percentile: int) -> float:
        """Calculate percentile of data."""
        if not data:
            return 0
        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile / 100)
        return sorted_data[min(index, len(sorted_data) - 1)]

    def _calculate_quality_metrics(self, results: List[Dict],
                                   ground_truth: Dict[str, List[str]],
                                   k: int) -> Dict[str, float]:
        """
        Calculate search quality metrics.

        Args:
            results: Search results for each query
            ground_truth: Dict mapping query to relevant document IDs
            k: Number of results

        Returns:
            Quality metrics
        """
        precisions = []
        recalls = []
        reciprocal_ranks = []

        for result in results:
            query = result['query']
            retrieved_ids = [r.get('id') for r in result['results'][:k]]
            relevant_ids = ground_truth.get(query, [])

            if not relevant_ids:
                continue

            # Calculate metrics
            relevant_retrieved = set(retrieved_ids) & set(relevant_ids)

            # Precision@k
            precision = len(relevant_retrieved) / k if k > 0 else 0
            precisions.append(precision)

            # Recall@k
            recall = len(relevant_retrieved) / len(relevant_ids) if relevant_ids else 0
            recalls.append(recall)

            # Mean Reciprocal Rank (MRR)
            for i, doc_id in enumerate(retrieved_ids, 1):
                if doc_id in relevant_ids:
                    reciprocal_ranks.append(1.0 / i)
                    break
            else:
                reciprocal_ranks.append(0.0)

        return {
            'precision_at_k': statistics.mean(precisions) if precisions else 0,
            'recall_at_k': statistics.mean(recalls) if recalls else 0,
            'mrr': statistics.mean(reciprocal_ranks) if reciprocal_ranks else 0
        }

    def benchmark_all_methods(self, queries: List[str],
                              methods: List[str] = ['hybrid', 'bm25', 'vector'],
                              k: int = 10,
                              ground_truth: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Benchmark all search methods.

        Args:
            queries: List of test queries
            methods: List of search methods to test
            k: Number of results
            ground_truth: Optional ground truth for quality

        Returns:
            Complete benchmark results
        """
        for method in methods:
            result = self.benchmark_search_method(
                method=method,
                queries=queries,
                k=k,
                ground_truth=ground_truth
            )
            self.results['search_methods'][method] = result

        # Generate comparative summary
        self._generate_summary()

        return self.results

    def _generate_summary(self):
        """Generate comparative summary across methods."""
        summary = {
            'comparison': {},
            'winner': {}
        }

        # Compare latencies
        latencies = {}
        quality_scores = {}

        for method, data in self.results['search_methods'].items():
            latencies[method] = data['latency']['p95_ms']

            if 'quality' in data:
                quality_scores[method] = data['quality']['precision_at_k']

        # Find fastest method
        if latencies:
            fastest_method = min(latencies, key=latencies.get)
            summary['winner']['fastest'] = {
                'method': fastest_method,
                'p95_latency_ms': latencies[fastest_method]
            }

        # Find best quality method
        if quality_scores:
            best_method = max(quality_scores, key=quality_scores.get)
            summary['winner']['best_quality'] = {
                'method': best_method,
                'precision_at_k': quality_scores[best_method]
            }

        summary['comparison']['latencies'] = latencies
        summary['comparison']['quality_scores'] = quality_scores

        self.results['summary'] = summary

    def load_test_queries(self, queries_file: Optional[Path] = None) -> List[str]:
        """
        Load test queries from file or use defaults.

        Args:
            queries_file: Optional path to queries JSON file

        Returns:
            List of queries
        """
        if queries_file and queries_file.exists():
            with open(queries_file) as f:
                data = json.load(f)
                return data.get('queries', [])

        # Default test queries
        return [
            "modern furniture",
            "outdoor activities",
            "food photography",
            "nature landscape",
            "urban architecture",
            "vintage items",
            "technology gadgets",
            "art and design",
            "travel destinations",
            "sports equipment"
        ]

    def save_results(self, output_path: Optional[Path] = None):
        """Save benchmark results to JSON file."""
        if output_path is None:
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            output_path = Path(f"./benchmark_search_{self.env}_{timestamp}.json")

        with open(output_path, 'w') as f:
            json.dump(self.results, f, indent=2)

        print(f"\n✅ Results saved to: {output_path}")
        return output_path


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Benchmark search performance')
    parser.add_argument('--env', default='dev', help='Environment (dev/test/prod)')
    parser.add_argument('--queries', help='Path to queries JSON file')
    parser.add_argument('--method', help='Specific method to test (hybrid/bm25/vector)')
    parser.add_argument('--k', type=int, default=10, help='Number of results')
    parser.add_argument('--ground-truth', help='Path to ground truth JSON file')
    parser.add_argument('--output', help='Output file path')

    args = parser.parse_args()

    # Create benchmarker
    benchmark = SearchBenchmark(env=args.env)

    # Load queries
    queries_file = Path(args.queries) if args.queries else None
    queries = benchmark.load_test_queries(queries_file)

    print(f"Loaded {len(queries)} test queries")

    # Load ground truth if provided
    ground_truth = None
    if args.ground_truth:
        with open(args.ground_truth) as f:
            ground_truth = json.load(f)
        print(f"Loaded ground truth for {len(ground_truth)} queries")

    # Run benchmarks
    if args.method:
        # Single method
        result = benchmark.benchmark_search_method(
            method=args.method,
            queries=queries,
            k=args.k,
            ground_truth=ground_truth
        )
        benchmark.results['search_methods'][args.method] = result
        benchmark._generate_summary()
    else:
        # All methods
        benchmark.benchmark_all_methods(
            queries=queries,
            k=args.k,
            ground_truth=ground_truth
        )

    # Save results
    output_path = Path(args.output) if args.output else None
    benchmark.save_results(output_path)

    # Print summary
    print("\n" + "="*60)
    print("BENCHMARK SUMMARY")
    print("="*60)

    summary = benchmark.results.get('summary', {})
    if 'winner' in summary:
        if 'fastest' in summary['winner']:
            fastest = summary['winner']['fastest']
            print(f"Fastest Method: {fastest['method']} ({fastest['p95_latency_ms']:.2f}ms)")

        if 'best_quality' in summary['winner']:
            best = summary['winner']['best_quality']
            print(f"Best Quality: {best['method']} (P@k={best['precision_at_k']:.3f})")


if __name__ == '__main__':
    main()
