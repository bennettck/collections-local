#!/usr/bin/env python3
"""
Benchmark Lambda Cold Starts

Measures Lambda function initialization time by:
- Forcing cold starts (updating environment variables)
- Tracking initialization duration
- Comparing against performance targets

Target: < 3s for API Lambda cold start

Usage:
    python benchmark_cold_starts.py --env dev
    python benchmark_cold_starts.py --env dev --function api
    python benchmark_cold_starts.py --env dev --iterations 10
"""

import argparse
import json
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

import boto3


class ColdStartBenchmark:
    """Benchmark Lambda function cold starts."""

    def __init__(self, env: str = "dev"):
        """
        Initialize cold start benchmarker.

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
        self.cloudwatch_client = boto3.client(
            'logs',
            region_name=self.config.get('region', 'us-east-1')
        )

        self.results = {
            'environment': env,
            'timestamp': datetime.utcnow().isoformat(),
            'functions': {},
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

        # Parse outputs into function names
        config = {
            'region': 'us-east-1',
            'functions': {}
        }

        for output in outputs:
            key = output.get('OutputKey', '')
            value = output.get('OutputValue', '')

            if 'LambdaName' in key or 'Lambda' in key and 'Name' in key:
                # Extract function type from key
                if 'API' in key:
                    config['functions']['api'] = value
                elif 'ImageProcessor' in key:
                    config['functions']['processor'] = value
                elif 'Analyzer' in key:
                    config['functions']['analyzer'] = value
                elif 'Embedder' in key:
                    config['functions']['embedder'] = value
                elif 'Cleanup' in key:
                    config['functions']['cleanup'] = value

        return config

    def force_cold_start(self, function_name: str) -> bool:
        """
        Force a cold start by updating environment variable.

        Args:
            function_name: Lambda function name

        Returns:
            True if successful
        """
        try:
            # Get current configuration
            response = self.lambda_client.get_function_configuration(
                FunctionName=function_name
            )

            current_env = response.get('Environment', {}).get('Variables', {})

            # Add/update a benign environment variable to force redeployment
            current_env['COLD_START_TRIGGER'] = str(int(time.time()))

            # Update function configuration
            self.lambda_client.update_function_configuration(
                FunctionName=function_name,
                Environment={'Variables': current_env}
            )

            # Wait for update to complete
            print(f"  Waiting for update to complete...", end='', flush=True)
            waiter = self.lambda_client.get_waiter('function_updated')
            waiter.wait(FunctionName=function_name)
            print(" Done")

            return True

        except Exception as e:
            print(f"  Error forcing cold start: {e}")
            return False

    def measure_cold_start(self, function_name: str,
                          payload: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Measure cold start time for a Lambda function.

        Args:
            function_name: Lambda function name
            payload: Optional invocation payload

        Returns:
            Cold start metrics
        """
        if payload is None:
            payload = {'test': True}

        # Invoke function
        start_time = time.time()

        try:
            response = self.lambda_client.invoke(
                FunctionName=function_name,
                InvocationType='RequestResponse',
                Payload=json.dumps(payload)
            )

            total_duration = (time.time() - start_time) * 1000  # ms

            # Parse response to check for errors
            response_payload = json.loads(response['Payload'].read())
            success = response.get('StatusCode') == 200

            # Extract duration from Lambda response
            # Lambda includes billed duration in response
            billed_duration_ms = None
            if 'FunctionError' not in response:
                # Try to get init duration from CloudWatch logs
                init_duration = self._get_init_duration_from_logs(function_name)
            else:
                init_duration = None

            return {
                'success': success,
                'total_duration_ms': total_duration,
                'init_duration_ms': init_duration,
                'error': response.get('FunctionError')
            }

        except Exception as e:
            total_duration = (time.time() - start_time) * 1000
            return {
                'success': False,
                'total_duration_ms': total_duration,
                'init_duration_ms': None,
                'error': str(e)
            }

    def _get_init_duration_from_logs(self, function_name: str,
                                     max_wait_seconds: int = 10) -> float:
        """
        Extract init duration from CloudWatch logs.

        Args:
            function_name: Lambda function name
            max_wait_seconds: Maximum time to wait for logs

        Returns:
            Init duration in milliseconds, or None if not found
        """
        log_group = f"/aws/lambda/{function_name}"
        start_time = time.time()

        # Wait for logs to appear
        while time.time() - start_time < max_wait_seconds:
            try:
                # Get most recent log stream
                streams = self.cloudwatch_client.describe_log_streams(
                    logGroupName=log_group,
                    orderBy='LastEventTime',
                    descending=True,
                    limit=1
                )

                if not streams.get('logStreams'):
                    time.sleep(0.5)
                    continue

                log_stream = streams['logStreams'][0]['logStreamName']

                # Get log events
                events = self.cloudwatch_client.get_log_events(
                    logGroupName=log_group,
                    logStreamName=log_stream,
                    limit=10,
                    startFromHead=False
                )

                # Search for REPORT line with Init Duration
                for event in events.get('events', []):
                    message = event.get('message', '')
                    if 'REPORT' in message and 'Init Duration' in message:
                        # Parse: "Init Duration: 1234.56 ms"
                        parts = message.split('Init Duration:')
                        if len(parts) > 1:
                            duration_str = parts[1].split('ms')[0].strip()
                            try:
                                return float(duration_str)
                            except ValueError:
                                pass

                time.sleep(0.5)

            except Exception as e:
                print(f"    Warning: Could not get logs: {e}")
                return None

        return None

    def benchmark_function(self, function_type: str,
                          iterations: int = 5) -> Dict[str, Any]:
        """
        Benchmark cold starts for a specific function.

        Args:
            function_type: Function type (api, processor, analyzer, embedder, cleanup)
            iterations: Number of cold start measurements

        Returns:
            Benchmark results
        """
        function_name = self.config['functions'].get(function_type)

        if not function_name:
            raise ValueError(f"Function type '{function_type}' not found in config")

        print(f"\n{'='*60}")
        print(f"Benchmarking: {function_type.upper()} Lambda")
        print(f"{'='*60}")
        print(f"Function: {function_name}")
        print(f"Iterations: {iterations}")

        # Define appropriate payload for function type
        payloads = {
            'api': {
                'httpMethod': 'GET',
                'path': '/health',
                'headers': {}
            },
            'processor': {
                'Records': [{
                    's3': {
                        'bucket': {'name': 'test-bucket'},
                        'object': {'key': 'test/image.jpg'}
                    }
                }]
            },
            'analyzer': {
                'detail': {
                    'user_id': 'test-user',
                    'item_id': 'test-item',
                    'image_path': 's3://test/image.jpg'
                }
            },
            'embedder': {
                'detail': {
                    'user_id': 'test-user',
                    'item_id': 'test-item',
                    'analysis_id': 'test-analysis'
                }
            },
            'cleanup': {}
        }

        payload = payloads.get(function_type, {})

        cold_starts = []
        total_durations = []
        init_durations = []

        for i in range(iterations):
            print(f"\nIteration {i + 1}/{iterations}")

            # Force cold start
            print("  Forcing cold start...", end='', flush=True)
            if self.force_cold_start(function_name):
                print(" Done")

                # Wait a bit for instances to terminate
                time.sleep(2)

                # Measure cold start
                print("  Measuring cold start...", end='', flush=True)
                result = self.measure_cold_start(function_name, payload)
                print(" Done")

                cold_starts.append(result)
                total_durations.append(result['total_duration_ms'])

                if result['init_duration_ms']:
                    init_durations.append(result['init_duration_ms'])

                print(f"  Total: {result['total_duration_ms']:.2f}ms", end='')
                if result['init_duration_ms']:
                    print(f", Init: {result['init_duration_ms']:.2f}ms")
                else:
                    print()

                if not result['success']:
                    print(f"  ⚠️  Error: {result.get('error')}")

            else:
                print(" Failed")

        # Calculate statistics
        stats = {
            'function_type': function_type,
            'function_name': function_name,
            'iterations': iterations,
            'successful_measurements': len([cs for cs in cold_starts if cs['success']]),
            'total_duration': {
                'min_ms': min(total_durations) if total_durations else 0,
                'max_ms': max(total_durations) if total_durations else 0,
                'mean_ms': statistics.mean(total_durations) if total_durations else 0,
                'median_ms': statistics.median(total_durations) if total_durations else 0,
                'stddev_ms': statistics.stdev(total_durations) if len(total_durations) > 1 else 0
            },
            'measurements': cold_starts
        }

        if init_durations:
            stats['init_duration'] = {
                'min_ms': min(init_durations),
                'max_ms': max(init_durations),
                'mean_ms': statistics.mean(init_durations),
                'median_ms': statistics.median(init_durations),
                'stddev_ms': statistics.stdev(init_durations) if len(init_durations) > 1 else 0
            }

        # Check against target (< 3s for API Lambda)
        target_ms = 3000  # 3 seconds
        if function_type == 'api' and total_durations:
            mean_duration = statistics.mean(total_durations)
            stats['meets_target'] = mean_duration < target_ms
            stats['target_ms'] = target_ms

            print(f"\n{'='*60}")
            print(f"Target: < {target_ms}ms")
            print(f"Actual: {mean_duration:.2f}ms")
            print(f"Status: {'✅ PASS' if stats['meets_target'] else '❌ FAIL'}")
            print(f"{'='*60}")

        return stats

    def benchmark_all_functions(self, iterations: int = 5) -> Dict[str, Any]:
        """
        Benchmark all Lambda functions.

        Args:
            iterations: Number of iterations per function

        Returns:
            Complete benchmark results
        """
        for function_type in self.config['functions'].keys():
            try:
                result = self.benchmark_function(function_type, iterations)
                self.results['functions'][function_type] = result
            except Exception as e:
                print(f"\n❌ Error benchmarking {function_type}: {e}")
                self.results['functions'][function_type] = {
                    'error': str(e)
                }

        # Generate summary
        self._generate_summary()

        return self.results

    def _generate_summary(self):
        """Generate overall summary."""
        summary = {
            'functions_tested': len(self.results['functions']),
            'target_compliance': {},
            'fastest_init': None,
            'slowest_init': None
        }

        # Check target compliance for API Lambda
        if 'api' in self.results['functions']:
            api_result = self.results['functions']['api']
            if 'meets_target' in api_result:
                summary['target_compliance']['api'] = {
                    'meets_target': api_result['meets_target'],
                    'mean_ms': api_result['total_duration']['mean_ms'],
                    'target_ms': api_result['target_ms']
                }

        # Find fastest/slowest init times
        init_times = {}
        for func_type, data in self.results['functions'].items():
            if 'init_duration' in data:
                init_times[func_type] = data['init_duration']['mean_ms']

        if init_times:
            fastest = min(init_times, key=init_times.get)
            slowest = max(init_times, key=init_times.get)

            summary['fastest_init'] = {
                'function': fastest,
                'mean_ms': init_times[fastest]
            }
            summary['slowest_init'] = {
                'function': slowest,
                'mean_ms': init_times[slowest]
            }

        self.results['summary'] = summary

    def save_results(self, output_path: Path = None):
        """Save benchmark results to JSON file."""
        if output_path is None:
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            output_path = Path(f"./benchmark_cold_starts_{self.env}_{timestamp}.json")

        with open(output_path, 'w') as f:
            json.dump(self.results, f, indent=2)

        print(f"\n✅ Results saved to: {output_path}")
        return output_path


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Benchmark Lambda cold starts')
    parser.add_argument('--env', default='dev', help='Environment (dev/test/prod)')
    parser.add_argument('--function', help='Specific function to test')
    parser.add_argument('--iterations', type=int, default=5,
                       help='Number of iterations')
    parser.add_argument('--output', help='Output file path')

    args = parser.parse_args()

    # Create benchmarker
    benchmark = ColdStartBenchmark(env=args.env)

    # Run benchmarks
    if args.function:
        result = benchmark.benchmark_function(args.function, args.iterations)
        benchmark.results['functions'][args.function] = result
        benchmark._generate_summary()
    else:
        benchmark.benchmark_all_functions(args.iterations)

    # Save results
    output_path = Path(args.output) if args.output else None
    benchmark.save_results(output_path)

    # Print summary
    print("\n" + "="*60)
    print("COLD START SUMMARY")
    print("="*60)

    summary = benchmark.results.get('summary', {})

    if 'target_compliance' in summary and 'api' in summary['target_compliance']:
        api_target = summary['target_compliance']['api']
        print(f"\nAPI Lambda Target Compliance:")
        print(f"  Target: < {api_target['target_ms']}ms")
        print(f"  Actual: {api_target['mean_ms']:.2f}ms")
        print(f"  Status: {'✅ PASS' if api_target['meets_target'] else '❌ FAIL'}")

    if 'fastest_init' in summary and summary['fastest_init']:
        fastest = summary['fastest_init']
        print(f"\nFastest Init: {fastest['function']} ({fastest['mean_ms']:.2f}ms)")

    if 'slowest_init' in summary and summary['slowest_init']:
        slowest = summary['slowest_init']
        print(f"Slowest Init: {slowest['function']} ({slowest['mean_ms']:.2f}ms)")


if __name__ == '__main__':
    main()
