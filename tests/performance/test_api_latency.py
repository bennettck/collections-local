"""
API endpoint latency performance tests.

Tests measure response times for all API endpoints and compare against targets:
- Target: API p95 latency < 500ms

Results include:
- Mean, median, min, max latencies
- Percentile distributions (p50, p90, p95, p99)
- Success/error rates
- Comparison against performance targets

Usage:
    pytest tests/performance/test_api_latency.py -v
    pytest tests/performance/test_api_latency.py -v --env=dev
"""

import pytest
import requests
import time
import statistics
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Any
import boto3


class LatencyMeasurement:
    """Container for latency measurement data."""

    def __init__(self, endpoint: str, method: str = "GET"):
        self.endpoint = endpoint
        self.method = method
        self.latencies: List[float] = []
        self.status_codes: List[int] = []
        self.errors: List[str] = []

    def record(self, latency_ms: float, status_code: int, error: str = None):
        """Record a latency measurement."""
        self.latencies.append(latency_ms)
        self.status_codes.append(status_code)
        if error:
            self.errors.append(error)

    def get_statistics(self) -> Dict[str, Any]:
        """Calculate latency statistics."""
        if not self.latencies:
            return {
                'endpoint': self.endpoint,
                'method': self.method,
                'count': 0,
                'error': 'No measurements recorded'
            }

        sorted_latencies = sorted(self.latencies)
        n = len(sorted_latencies)

        stats = {
            'endpoint': self.endpoint,
            'method': self.method,
            'count': n,
            'mean': statistics.mean(self.latencies),
            'median': statistics.median(self.latencies),
            'min': min(self.latencies),
            'max': max(self.latencies),
            'stdev': statistics.stdev(self.latencies) if n > 1 else 0,
            'p50': sorted_latencies[int(n * 0.50)],
            'p90': sorted_latencies[int(n * 0.90)] if n > 10 else sorted_latencies[-1],
            'p95': sorted_latencies[int(n * 0.95)] if n > 20 else sorted_latencies[-1],
            'p99': sorted_latencies[int(n * 0.99)] if n > 100 else sorted_latencies[-1],
            'success_rate': sum(1 for sc in self.status_codes if 200 <= sc < 300) / n * 100,
            'error_count': len(self.errors),
            'unique_status_codes': list(set(self.status_codes))
        }

        return stats

    def meets_target(self, target_p95_ms: float = 500) -> Tuple[bool, str]:
        """Check if latency meets performance target."""
        stats = self.get_statistics()

        if stats.get('error'):
            return False, stats['error']

        p95 = stats['p95']
        meets = p95 < target_p95_ms

        message = f"P95: {p95:.2f}ms (target: <{target_p95_ms}ms)"

        return meets, message


@pytest.fixture(scope="module")
def api_base_url(stack_outputs) -> str:
    """
    Get API base URL from stack outputs or environment.

    Args:
        stack_outputs: CDK stack outputs fixture

    Returns:
        API base URL string

    Raises:
        pytest.skip: If API URL not available
    """
    # Try to get from stack outputs first
    api_url = stack_outputs.get('ApiUrl') or stack_outputs.get('APIUrl')

    # Fallback to environment variable
    if not api_url:
        api_url = os.getenv('API_BASE_URL')

    if not api_url:
        pytest.skip("API URL not available. Set API_BASE_URL or deploy infrastructure")

    # Remove trailing slash
    return api_url.rstrip('/')


@pytest.fixture(scope="module")
def auth_headers(stack_outputs, boto3_clients) -> Dict[str, str]:
    """
    Get authenticated headers for API requests.

    This creates a test user in Cognito and gets a valid JWT token.

    Args:
        stack_outputs: CDK stack outputs fixture
        boto3_clients: boto3 clients fixture

    Returns:
        Dictionary with Authorization header

    Raises:
        pytest.skip: If authentication not available
    """
    user_pool_id = stack_outputs.get('CognitoUserPoolId')
    client_id = stack_outputs.get('CognitoClientId')

    if not all([user_pool_id, client_id]):
        pytest.skip("Cognito credentials not available in stack outputs")

    cognito = boto3_clients['cognito']

    # Create temporary test user
    timestamp = int(time.time())
    username = f'perf-test-{timestamp}'
    temp_password = f'TempPass{timestamp}!'

    try:
        # Create user
        response = cognito.admin_create_user(
            UserPoolId=user_pool_id,
            Username=username,
            TemporaryPassword=temp_password,
            MessageAction='SUPPRESS',
            UserAttributes=[
                {'Name': 'email', 'Value': f'{username}@example.com'},
                {'Name': 'email_verified', 'Value': 'true'}
            ]
        )

        # Set permanent password
        permanent_password = f'PermPass{timestamp}!'
        cognito.admin_set_user_password(
            UserPoolId=user_pool_id,
            Username=username,
            Password=permanent_password,
            Permanent=True
        )

        # Authenticate to get token
        auth_response = cognito.admin_initiate_auth(
            UserPoolId=user_pool_id,
            ClientId=client_id,
            AuthFlow='ADMIN_NO_SRP_AUTH',
            AuthParameters={
                'USERNAME': username,
                'PASSWORD': permanent_password
            }
        )

        token = auth_response['AuthenticationResult']['IdToken']

        yield {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }

        # Cleanup: Delete test user
        cognito.admin_delete_user(
            UserPoolId=user_pool_id,
            Username=username
        )

    except Exception as e:
        pytest.skip(f"Cannot authenticate test user: {e}")


class TestHealthEndpointLatency:
    """Test health endpoint latency (baseline for comparison)."""

    def test_health_endpoint_latency(self, api_base_url):
        """
        Measure latency of health endpoint.

        This is the simplest endpoint and provides a baseline for comparison.
        Should be very fast since it doesn't require auth or database access.
        """
        measurement = LatencyMeasurement('/health', 'GET')

        # Warm up (1 request)
        requests.get(f"{api_base_url}/health")

        # Measure latency (100 requests)
        for _ in range(100):
            start = time.perf_counter()
            response = requests.get(f"{api_base_url}/health")
            latency_ms = (time.perf_counter() - start) * 1000

            measurement.record(latency_ms, response.status_code)

        # Get statistics
        stats = measurement.get_statistics()

        # Print results
        print(f"\n\nHealth Endpoint Latency:")
        print(f"  Mean: {stats['mean']:.2f}ms")
        print(f"  Median: {stats['median']:.2f}ms")
        print(f"  P95: {stats['p95']:.2f}ms")
        print(f"  Min/Max: {stats['min']:.2f}ms / {stats['max']:.2f}ms")
        print(f"  Success Rate: {stats['success_rate']:.1f}%")

        # Health should be very fast (< 100ms p95)
        assert stats['p95'] < 100, f"Health endpoint too slow: {stats['p95']:.2f}ms"
        assert stats['success_rate'] == 100, "Health endpoint failed"


class TestAuthenticatedEndpointLatency:
    """Test latency of authenticated endpoints."""

    def test_list_items_latency(self, api_base_url, auth_headers):
        """
        Measure latency of GET /items endpoint.

        Tests pagination endpoint with authentication.
        """
        measurement = LatencyMeasurement('/items', 'GET')

        # Warm up
        requests.get(f"{api_base_url}/items?limit=10", headers=auth_headers)

        # Measure latency (50 requests)
        for _ in range(50):
            start = time.perf_counter()
            response = requests.get(
                f"{api_base_url}/items?limit=10&offset=0",
                headers=auth_headers
            )
            latency_ms = (time.perf_counter() - start) * 1000

            measurement.record(latency_ms, response.status_code)

        # Get statistics
        stats = measurement.get_statistics()

        # Print results
        print(f"\n\nList Items Endpoint Latency:")
        print(f"  Mean: {stats['mean']:.2f}ms")
        print(f"  Median: {stats['median']:.2f}ms")
        print(f"  P95: {stats['p95']:.2f}ms")
        print(f"  Min/Max: {stats['min']:.2f}ms / {stats['max']:.2f}ms")
        print(f"  Success Rate: {stats['success_rate']:.1f}%")

        # Check against target
        meets_target, message = measurement.meets_target(500)
        print(f"  Target Check: {'PASS' if meets_target else 'FAIL'} - {message}")

        assert stats['success_rate'] > 95, f"Too many failures: {stats['success_rate']:.1f}%"
        assert meets_target, f"Latency target not met: {message}"

    def test_search_endpoint_latency(self, api_base_url, auth_headers):
        """
        Measure latency of POST /search endpoint.

        Tests different search types with varying queries.
        """
        search_types = ['bm25-lc', 'vector-lc', 'hybrid-lc']
        queries = [
            'modern furniture',
            'outdoor activities',
            'food photography',
            'landscape',
            'portrait'
        ]

        for search_type in search_types:
            measurement = LatencyMeasurement(f'/search (type={search_type})', 'POST')

            # Warm up
            requests.post(
                f"{api_base_url}/search",
                headers=auth_headers,
                json={'query': queries[0], 'search_type': search_type, 'top_k': 10}
            )

            # Measure latency (25 requests per query)
            for query in queries:
                for _ in range(5):
                    start = time.perf_counter()
                    response = requests.post(
                        f"{api_base_url}/search",
                        headers=auth_headers,
                        json={'query': query, 'search_type': search_type, 'top_k': 10}
                    )
                    latency_ms = (time.perf_counter() - start) * 1000

                    measurement.record(latency_ms, response.status_code)

            # Get statistics
            stats = measurement.get_statistics()

            # Print results
            print(f"\n\nSearch Endpoint Latency ({search_type}):")
            print(f"  Mean: {stats['mean']:.2f}ms")
            print(f"  Median: {stats['median']:.2f}ms")
            print(f"  P95: {stats['p95']:.2f}ms")
            print(f"  Min/Max: {stats['min']:.2f}ms / {stats['max']:.2f}ms")
            print(f"  Success Rate: {stats['success_rate']:.1f}%")

            # Check against target
            meets_target, message = measurement.meets_target(500)
            print(f"  Target Check: {'PASS' if meets_target else 'FAIL'} - {message}")

            assert stats['success_rate'] > 90, f"Too many failures: {stats['success_rate']:.1f}%"


class TestChatEndpointLatency:
    """Test chat endpoint latency."""

    def test_chat_endpoint_latency(self, api_base_url, auth_headers):
        """
        Measure latency of POST /chat endpoint.

        Note: This includes LLM response time, so higher latency is expected.
        """
        measurement = LatencyMeasurement('/chat', 'POST')

        session_id = f'perf-test-{int(time.time())}'

        # Warm up
        requests.post(
            f"{api_base_url}/chat",
            headers=auth_headers,
            json={'message': 'Hello', 'session_id': f'{session_id}-warmup'}
        )

        # Measure latency (10 requests - fewer due to LLM cost)
        messages = [
            'What items do I have?',
            'Show me recent photos',
            'Tell me about my collections',
            'What categories are available?',
            'Thank you'
        ]

        for i, message in enumerate(messages):
            for turn in range(2):
                start = time.perf_counter()
                response = requests.post(
                    f"{api_base_url}/chat",
                    headers=auth_headers,
                    json={'message': message, 'session_id': f'{session_id}-{i}'}
                )
                latency_ms = (time.perf_counter() - start) * 1000

                measurement.record(latency_ms, response.status_code)

        # Get statistics
        stats = measurement.get_statistics()

        # Print results
        print(f"\n\nChat Endpoint Latency:")
        print(f"  Mean: {stats['mean']:.2f}ms")
        print(f"  Median: {stats['median']:.2f}ms")
        print(f"  P95: {stats['p95']:.2f}ms")
        print(f"  Min/Max: {stats['min']:.2f}ms / {stats['max']:.2f}ms")
        print(f"  Success Rate: {stats['success_rate']:.1f}%")

        # Chat has higher latency due to LLM (allow up to 10s p95)
        assert stats['p95'] < 10000, f"Chat endpoint too slow: {stats['p95']:.2f}ms"
        assert stats['success_rate'] > 80, f"Too many failures: {stats['success_rate']:.1f}%"


@pytest.fixture(scope="module")
def performance_report_data():
    """Collect performance data for final report."""
    data = {
        'test_run': {
            'timestamp': datetime.utcnow().isoformat(),
            'environment': os.getenv('CDK_ENV', 'dev')
        },
        'endpoints': []
    }

    yield data


def pytest_sessionfinish(session, exitstatus):
    """
    Generate performance report after all tests complete.

    This is a pytest hook that runs after the test session.
    """
    # Only generate report if tests ran (not if skipped)
    if not hasattr(session, 'testscollected') or session.testscollected == 0:
        return

    # Generate markdown report
    report_dir = Path(__file__).parent.parent.parent / 'reports'
    report_dir.mkdir(exist_ok=True)

    timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    env_name = os.getenv('CDK_ENV', 'dev')
    report_file = report_dir / f'api-latency-{env_name}-{timestamp}.md'

    # Collect results from pytest items
    results = []
    for item in session.items:
        if hasattr(item, 'latency_stats'):
            results.append(item.latency_stats)

    # Write report
    with open(report_file, 'w') as f:
        f.write(f"# API Latency Performance Report\n\n")
        f.write(f"**Environment:** {env_name}\n")
        f.write(f"**Timestamp:** {datetime.utcnow().isoformat()}\n")
        f.write(f"**Tests Run:** {session.testscollected}\n")
        f.write(f"**Tests Failed:** {session.testsfailed}\n\n")

        f.write("## Performance Targets\n\n")
        f.write("| Metric | Target | Status |\n")
        f.write("|--------|--------|--------|\n")
        f.write("| API P95 Latency | < 500ms | - |\n")
        f.write("| Success Rate | > 95% | - |\n\n")

        f.write("## Test Results\n\n")
        f.write("Detailed results available in pytest output.\n")

    print(f"\n\nPerformance report generated: {report_file}")


if __name__ == "__main__":
    """
    Run API latency tests with verbose output.

    Usage:
        python tests/performance/test_api_latency.py
    """
    pytest.main([__file__, "-v", "-s"])
