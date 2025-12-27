#!/usr/bin/env python3
"""
Benchmark API Endpoints

Tests all major API endpoints with varying load levels to measure:
- Response times (mean, median, p95, p99)
- Throughput (requests/second)
- Error rates
- Concurrent request handling

Usage:
    python benchmark_api.py --env dev
    python benchmark_api.py --env dev --concurrency 100
    python benchmark_api.py --env dev --endpoint /health
"""

import argparse
import asyncio
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


class APIBenchmark:
    """Benchmark API endpoints using direct Lambda invocation and HTTP requests."""

    def __init__(self, env: str = "dev"):
        """
        Initialize API benchmarker.

        Args:
            env: Environment name (dev, test, prod)
        """
        self.env = env
        self.config = self._load_config()

        # Initialize AWS clients
        self.lambda_client = boto3.client('lambda', region_name=self.config.get('region', 'us-east-1'))
        self.apigateway_client = boto3.client('apigatewayv2', region_name=self.config.get('region', 'us-east-1'))

        # Extract configuration
        self.api_lambda_arn = self.config.get('api_lambda_arn')
        self.api_lambda_name = self.config.get('api_lambda_name')
        self.api_url = self.config.get('api_url', '')

        self.results = {
            'environment': env,
            'timestamp': datetime.utcnow().isoformat(),
            'endpoints': {},
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

        # Parse outputs into usable config
        config = {
            'region': 'us-east-1'  # Default, should be in outputs
        }

        for output in outputs:
            key = output.get('OutputKey', '')
            value = output.get('OutputValue', '')

            if 'APILambdaArn' in key:
                config['api_lambda_arn'] = value
            elif 'APILambdaName' in key:
                config['api_lambda_name'] = value
            elif 'ApiUrl' in key or 'APIUrl' in key:
                config['api_url'] = value

        return config

    def _invoke_lambda_sync(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Invoke Lambda function synchronously.

        Args:
            payload: Lambda event payload

        Returns:
            Response with timing information
        """
        start = time.time()

        try:
            response = self.lambda_client.invoke(
                FunctionName=self.api_lambda_name,
                InvocationType='RequestResponse',
                Payload=json.dumps(payload)
            )

            duration = (time.time() - start) * 1000  # Convert to ms

            # Parse response
            response_payload = json.loads(response['Payload'].read())
            status_code = response.get('StatusCode', 0)

            return {
                'success': status_code == 200,
                'duration_ms': duration,
                'status_code': status_code,
                'response': response_payload,
                'error': None
            }

        except Exception as e:
            duration = (time.time() - start) * 1000
            return {
                'success': False,
                'duration_ms': duration,
                'status_code': 500,
                'response': None,
                'error': str(e)
            }

    def _make_http_request(self, endpoint: str, method: str = 'GET',
                          body: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Make HTTP request to API Gateway.

        Args:
            endpoint: API endpoint path
            method: HTTP method
            body: Request body for POST/PUT

        Returns:
            Response with timing information
        """
        url = f"{self.api_url}{endpoint}"
        start = time.time()

        try:
            if method == 'GET':
                response = requests.get(url, timeout=30)
            elif method == 'POST':
                response = requests.post(url, json=body, timeout=30)
            else:
                raise ValueError(f"Unsupported method: {method}")

            duration = (time.time() - start) * 1000

            return {
                'success': response.status_code == 200,
                'duration_ms': duration,
                'status_code': response.status_code,
                'response': response.json() if response.ok else None,
                'error': None if response.ok else response.text
            }

        except Exception as e:
            duration = (time.time() - start) * 1000
            return {
                'success': False,
                'duration_ms': duration,
                'status_code': 500,
                'response': None,
                'error': str(e)
            }

    def benchmark_endpoint(self, endpoint: str, method: str = 'GET',
                          payload: Optional[Dict] = None,
                          concurrency_levels: List[int] = [1, 10, 50, 100],
                          requests_per_level: int = 100) -> Dict[str, Any]:
        """
        Benchmark a single endpoint at different concurrency levels.

        Args:
            endpoint: API endpoint path
            method: HTTP method
            payload: Request payload
            concurrency_levels: List of concurrent request counts
            requests_per_level: Number of requests per concurrency level

        Returns:
            Benchmark results
        """
        print(f"\n{'='*60}")
        print(f"Benchmarking: {method} {endpoint}")
        print(f"{'='*60}")

        endpoint_results = {
            'endpoint': endpoint,
            'method': method,
            'concurrency_tests': []
        }

        for concurrency in concurrency_levels:
            print(f"\nConcurrency: {concurrency} requests")
            print(f"Total requests: {requests_per_level}")

            # Run concurrent requests
            start_time = time.time()

            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = []
                for _ in range(requests_per_level):
                    if self.api_url:
                        future = executor.submit(
                            self._make_http_request,
                            endpoint, method, payload
                        )
                    else:
                        # Fallback to direct Lambda invocation
                        lambda_payload = {
                            'httpMethod': method,
                            'path': endpoint,
                            'body': json.dumps(payload) if payload else None
                        }
                        future = executor.submit(
                            self._invoke_lambda_sync,
                            lambda_payload
                        )
                    futures.append(future)

                # Collect results
                responses = [f.result() for f in futures]

            total_time = time.time() - start_time

            # Analyze results
            durations = [r['duration_ms'] for r in responses]
            successes = [r for r in responses if r['success']]
            failures = [r for r in responses if not r['success']]

            # Calculate statistics
            if durations:
                stats = {
                    'concurrency': concurrency,
                    'total_requests': requests_per_level,
                    'successful_requests': len(successes),
                    'failed_requests': len(failures),
                    'success_rate': len(successes) / requests_per_level * 100,
                    'total_time_seconds': total_time,
                    'requests_per_second': requests_per_level / total_time,
                    'latency': {
                        'min_ms': min(durations),
                        'max_ms': max(durations),
                        'mean_ms': statistics.mean(durations),
                        'median_ms': statistics.median(durations),
                        'p95_ms': self._percentile(durations, 95),
                        'p99_ms': self._percentile(durations, 99),
                        'stddev_ms': statistics.stdev(durations) if len(durations) > 1 else 0
                    }
                }

                # Print summary
                print(f"  Success rate: {stats['success_rate']:.1f}%")
                print(f"  Throughput: {stats['requests_per_second']:.2f} req/s")
                print(f"  Latency:")
                print(f"    Mean:   {stats['latency']['mean_ms']:.2f}ms")
                print(f"    Median: {stats['latency']['median_ms']:.2f}ms")
                print(f"    P95:    {stats['latency']['p95_ms']:.2f}ms")
                print(f"    P99:    {stats['latency']['p99_ms']:.2f}ms")

                # Add error details if any
                if failures:
                    error_samples = [f['error'] for f in failures[:3]]  # First 3 errors
                    stats['error_samples'] = error_samples

                endpoint_results['concurrency_tests'].append(stats)

        return endpoint_results

    def _percentile(self, data: List[float], percentile: int) -> float:
        """Calculate percentile of data."""
        if not data:
            return 0
        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile / 100)
        return sorted_data[min(index, len(sorted_data) - 1)]

    def benchmark_all_endpoints(self) -> Dict[str, Any]:
        """Benchmark all major API endpoints."""

        # Define endpoints to test
        endpoints = [
            {'path': '/health', 'method': 'GET', 'concurrency': [1, 10, 50, 100]},
            {'path': '/items', 'method': 'GET', 'concurrency': [1, 10, 50]},
            {'path': '/search', 'method': 'POST', 'concurrency': [1, 10, 25],
             'payload': {'query': 'test search', 'k': 10}},
            # Add more endpoints as needed
        ]

        for endpoint_config in endpoints:
            result = self.benchmark_endpoint(
                endpoint=endpoint_config['path'],
                method=endpoint_config['method'],
                payload=endpoint_config.get('payload'),
                concurrency_levels=endpoint_config['concurrency'],
                requests_per_level=50  # Adjust based on cost constraints
            )

            self.results['endpoints'][endpoint_config['path']] = result

        # Generate summary
        self._generate_summary()

        return self.results

    def _generate_summary(self):
        """Generate overall benchmark summary."""
        summary = {
            'total_endpoints_tested': len(self.results['endpoints']),
            'overall_metrics': {}
        }

        all_latencies = []
        all_success_rates = []

        for endpoint_name, endpoint_data in self.results['endpoints'].items():
            for test in endpoint_data.get('concurrency_tests', []):
                # Collect P95 latencies
                if 'latency' in test:
                    all_latencies.append(test['latency']['p95_ms'])

                # Collect success rates
                all_success_rates.append(test.get('success_rate', 0))

        if all_latencies:
            summary['overall_metrics']['p95_latency_ms'] = statistics.mean(all_latencies)

        if all_success_rates:
            summary['overall_metrics']['average_success_rate'] = statistics.mean(all_success_rates)

        self.results['summary'] = summary

    def save_results(self, output_path: Optional[Path] = None):
        """Save benchmark results to JSON file."""
        if output_path is None:
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            output_path = Path(f"./benchmark_api_{self.env}_{timestamp}.json")

        with open(output_path, 'w') as f:
            json.dump(self.results, f, indent=2)

        print(f"\n✅ Results saved to: {output_path}")
        return output_path


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Benchmark API endpoints')
    parser.add_argument('--env', default='dev', help='Environment (dev/test/prod)')
    parser.add_argument('--endpoint', help='Specific endpoint to test')
    parser.add_argument('--concurrency', type=int, nargs='+',
                       default=[1, 10, 50, 100],
                       help='Concurrency levels to test')
    parser.add_argument('--requests', type=int, default=100,
                       help='Requests per concurrency level')
    parser.add_argument('--output', help='Output file path')

    args = parser.parse_args()

    # Create benchmarker
    benchmark = APIBenchmark(env=args.env)

    # Run benchmarks
    if args.endpoint:
        # Single endpoint
        result = benchmark.benchmark_endpoint(
            endpoint=args.endpoint,
            concurrency_levels=args.concurrency,
            requests_per_level=args.requests
        )
        benchmark.results['endpoints'][args.endpoint] = result
        benchmark._generate_summary()
    else:
        # All endpoints
        benchmark.benchmark_all_endpoints()

    # Save results
    output_path = Path(args.output) if args.output else None
    benchmark.save_results(output_path)

    # Print summary
    print("\n" + "="*60)
    print("BENCHMARK SUMMARY")
    print("="*60)
    summary = benchmark.results['summary']
    if 'overall_metrics' in summary:
        metrics = summary['overall_metrics']
        if 'p95_latency_ms' in metrics:
            print(f"Overall P95 Latency: {metrics['p95_latency_ms']:.2f}ms")
        if 'average_success_rate' in metrics:
            print(f"Average Success Rate: {metrics['average_success_rate']:.1f}%")


if __name__ == '__main__':
    main()
