"""
Shared pytest fixtures for performance tests.

Provides reusable fixtures for:
- AWS resource configuration
- Performance measurement utilities
- Test data setup
- Report generation

Performance tests can be run with:
    pytest tests/performance/ -v
    pytest tests/performance/test_api_latency.py -v --env=dev
"""

import pytest
import boto3
import json
import os
from pathlib import Path
from typing import Dict, Any
from datetime import datetime


# Import shared fixtures from integration tests
# This allows us to reuse common setup
pytest_plugins = ['tests.integration.conftest']


@pytest.fixture(scope="session")
def performance_config() -> Dict[str, Any]:
    """
    Performance test configuration.

    Returns:
        Dictionary with performance test settings
    """
    return {
        'targets': {
            'api_p95_latency_ms': 500,
            'search_p95_latency_ms': 300,
            'cold_start_max_ms': 3000,
            'success_rate_percent': 95
        },
        'iterations': {
            'health_endpoint': 100,
            'authenticated_endpoint': 50,
            'search_query': 25,
            'cold_start': 5,
            'warm_start': 10
        },
        'warmup_requests': 1
    }


@pytest.fixture(scope="session")
def report_directory(project_root) -> Path:
    """
    Ensure reports directory exists.

    Args:
        project_root: Project root path fixture

    Returns:
        Path to reports directory
    """
    report_dir = project_root / 'reports'
    report_dir.mkdir(exist_ok=True)
    return report_dir


@pytest.fixture(scope="session")
def performance_start_time() -> datetime:
    """
    Record test session start time.

    Returns:
        Session start timestamp
    """
    return datetime.utcnow()


@pytest.fixture(scope="session", autouse=True)
def performance_test_banner(performance_config, env_name):
    """
    Display performance test banner at start.

    Args:
        performance_config: Performance config fixture
        env_name: Environment name fixture
    """
    print("\n" + "=" * 80)
    print("PERFORMANCE TEST SUITE")
    print("=" * 80)
    print(f"Environment: {env_name}")
    print(f"Timestamp: {datetime.utcnow().isoformat()}")
    print("\nPerformance Targets:")
    for target_name, target_value in performance_config['targets'].items():
        print(f"  - {target_name}: {target_value}")
    print("=" * 80 + "\n")


@pytest.fixture(scope="function")
def measure_time():
    """
    Utility fixture to measure execution time.

    Yields:
        Function that returns elapsed time in milliseconds
    """
    import time

    start_times = {}

    def start_timer(name: str = 'default'):
        """Start a named timer."""
        start_times[name] = time.perf_counter()

    def get_elapsed_ms(name: str = 'default') -> float:
        """Get elapsed time in milliseconds."""
        if name not in start_times:
            return 0
        return (time.perf_counter() - start_times[name]) * 1000

    class Timer:
        def start(self, name: str = 'default'):
            start_timer(name)

        def elapsed(self, name: str = 'default') -> float:
            return get_elapsed_ms(name)

    yield Timer()


@pytest.fixture(scope="function")
def performance_tracker():
    """
    Track performance measurements across tests.

    Yields:
        Performance tracker instance
    """
    class PerformanceTracker:
        def __init__(self):
            self.measurements = []

        def record(self, test_name: str, metric: str, value: float, metadata: Dict[str, Any] = None):
            """Record a performance measurement."""
            self.measurements.append({
                'test_name': test_name,
                'metric': metric,
                'value': value,
                'metadata': metadata or {},
                'timestamp': datetime.utcnow().isoformat()
            })

        def get_measurements(self, test_name: str = None, metric: str = None):
            """Get filtered measurements."""
            results = self.measurements

            if test_name:
                results = [m for m in results if m['test_name'] == test_name]

            if metric:
                results = [m for m in results if m['metric'] == metric]

            return results

        def export_json(self, filepath: Path):
            """Export measurements to JSON file."""
            with open(filepath, 'w') as f:
                json.dump(self.measurements, f, indent=2)

    yield PerformanceTracker()


@pytest.fixture(scope="session")
def lambda_arn_map(stack_outputs) -> Dict[str, str]:
    """
    Map Lambda function names to ARNs.

    Args:
        stack_outputs: CDK stack outputs fixture

    Returns:
        Dictionary mapping friendly names to Lambda ARNs
    """
    return {
        'api': stack_outputs.get('APILambdaArn'),
        'analyzer': stack_outputs.get('AnalyzerLambdaArn'),
        'embedder': stack_outputs.get('EmbedderLambdaArn'),
        'image_processor': stack_outputs.get('ImageProcessorLambdaArn'),
        'cleanup': stack_outputs.get('CleanupLambdaArn')
    }


@pytest.fixture(scope="session")
def sample_search_queries() -> list:
    """
    Provide sample search queries for testing.

    Returns:
        List of search query strings
    """
    return [
        'modern furniture',
        'landscape photography',
        'food',
        'architecture',
        'vintage items',
        'outdoor activities',
        'portrait',
        'urban design',
        'minimalist',
        'colorful'
    ]


def pytest_configure(config):
    """
    Pytest configuration hook.

    Registers custom markers for performance tests.
    """
    config.addinivalue_line(
        "markers", "performance: mark test as a performance benchmark"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running (>30s)"
    )
    config.addinivalue_line(
        "markers", "requires_data: mark test as requiring existing data"
    )


def pytest_collection_modifyitems(config, items):
    """
    Pytest collection hook.

    Automatically marks all tests in performance/ as performance tests.
    """
    for item in items:
        if "performance" in str(item.fspath):
            item.add_marker(pytest.mark.performance)


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    Pytest hook to capture test results for reporting.

    This allows us to collect performance data from tests.
    """
    outcome = yield
    report = outcome.get_result()

    # Store test duration
    if report.when == "call":
        item.test_duration = report.duration


def pytest_sessionfinish(session, exitstatus):
    """
    Pytest hook called after all tests complete.

    Generates summary performance report.
    """
    if not hasattr(session, 'testscollected') or session.testscollected == 0:
        return

    # Generate summary report
    report_dir = Path(__file__).parent.parent.parent / 'reports'
    report_dir.mkdir(exist_ok=True)

    timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    env_name = os.getenv('CDK_ENV', 'dev')
    summary_file = report_dir / f'performance-summary-{env_name}-{timestamp}.md'

    # Collect test results
    passed = session.testscollected - session.testsfailed
    success_rate = (passed / session.testscollected * 100) if session.testscollected > 0 else 0

    # Write summary report
    with open(summary_file, 'w') as f:
        f.write("# Performance Test Summary\n\n")
        f.write(f"**Environment:** {env_name}\n")
        f.write(f"**Timestamp:** {datetime.utcnow().isoformat()}\n")
        f.write(f"**Duration:** {getattr(session, 'duration', 0):.2f}s\n\n")

        f.write("## Test Results\n\n")
        f.write(f"- Total Tests: {session.testscollected}\n")
        f.write(f"- Passed: {passed}\n")
        f.write(f"- Failed: {session.testsfailed}\n")
        f.write(f"- Success Rate: {success_rate:.1f}%\n\n")

        f.write("## Performance Targets\n\n")
        f.write("| Metric | Target | Status |\n")
        f.write("|--------|--------|--------|\n")
        f.write("| API P95 Latency | < 500ms | See detailed reports |\n")
        f.write("| Search P95 Latency | < 300ms | See detailed reports |\n")
        f.write("| Cold Start Max | < 3s | See detailed reports |\n")
        f.write("| Success Rate | > 95% | See detailed reports |\n\n")

        f.write("## Detailed Reports\n\n")
        f.write(f"- API Latency: `api-latency-{env_name}-*.md`\n")
        f.write(f"- Cold Starts: `cold-starts-{env_name}-*.md`\n")
        f.write(f"- Search Latency: `search-latency-{env_name}-*.md`\n\n")

        f.write("## Next Steps\n\n")
        if session.testsfailed > 0:
            f.write("- Review failed tests and investigate performance issues\n")
            f.write("- Consider optimization strategies for failing metrics\n")
        else:
            f.write("- All performance tests passed\n")
            f.write("- Continue monitoring in production environment\n")

        f.write("\n## Test Execution\n\n")
        f.write("```bash\n")
        f.write(f"# Run all performance tests\n")
        f.write(f"pytest tests/performance/ -v --env={env_name}\n\n")
        f.write(f"# Run specific test suite\n")
        f.write(f"pytest tests/performance/test_api_latency.py -v\n")
        f.write(f"pytest tests/performance/test_cold_starts.py -v\n")
        f.write(f"pytest tests/performance/test_search_latency.py -v\n")
        f.write("```\n")

    print(f"\n\n{'=' * 80}")
    print(f"Performance summary report generated: {summary_file}")
    print(f"{'=' * 80}\n")
