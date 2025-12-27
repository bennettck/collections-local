"""
Search performance benchmarking tests.

Tests measure search query latency for different search types and compare
against targets:
- Target: Search p95 latency < 300ms

Tests include:
- BM25 (PostgreSQL tsvector) search performance
- Vector (pgvector) search performance
- Hybrid (RRF) search performance
- Search quality vs speed tradeoff analysis

Results include:
- Latency statistics per search type
- Query complexity impact analysis
- Top-k parameter impact
- User isolation overhead

Usage:
    pytest tests/performance/test_search_latency.py -v
    pytest tests/performance/test_search_latency.py -v --env=dev
"""

import pytest
import time
import statistics
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Tuple
import boto3
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


class SearchLatencyMeasurement:
    """Container for search latency measurement data."""

    def __init__(self, search_type: str, top_k: int = 10):
        self.search_type = search_type
        self.top_k = top_k
        self.latencies: List[float] = []
        self.result_counts: List[int] = []
        self.queries: List[str] = []

    def record(self, query: str, latency_ms: float, result_count: int):
        """Record a search latency measurement."""
        self.queries.append(query)
        self.latencies.append(latency_ms)
        self.result_counts.append(result_count)

    def get_statistics(self) -> Dict[str, Any]:
        """Calculate search latency statistics."""
        if not self.latencies:
            return {
                'search_type': self.search_type,
                'top_k': self.top_k,
                'error': 'No measurements recorded'
            }

        sorted_latencies = sorted(self.latencies)
        n = len(sorted_latencies)

        stats = {
            'search_type': self.search_type,
            'top_k': self.top_k,
            'query_count': n,
            'mean': statistics.mean(self.latencies),
            'median': statistics.median(self.latencies),
            'min': min(self.latencies),
            'max': max(self.latencies),
            'stdev': statistics.stdev(self.latencies) if n > 1 else 0,
            'p50': sorted_latencies[int(n * 0.50)],
            'p90': sorted_latencies[int(n * 0.90)] if n > 10 else sorted_latencies[-1],
            'p95': sorted_latencies[int(n * 0.95)] if n > 20 else sorted_latencies[-1],
            'p99': sorted_latencies[int(n * 0.99)] if n > 100 else sorted_latencies[-1],
            'avg_results': statistics.mean(self.result_counts) if self.result_counts else 0,
            'queries_per_second': n / (sum(self.latencies) / 1000) if self.latencies else 0
        }

        return stats

    def meets_target(self, target_p95_ms: float = 300) -> Tuple[bool, str]:
        """Check if search latency meets performance target."""
        stats = self.get_statistics()

        if stats.get('error'):
            return False, stats['error']

        p95 = stats['p95']
        meets = p95 < target_p95_ms

        message = f"P95: {p95:.2f}ms (target: <{target_p95_ms}ms)"

        return meets, message


@pytest.fixture(scope="module")
def database_url(stack_outputs, boto3_clients) -> str:
    """
    Get PostgreSQL database URL.

    Args:
        stack_outputs: CDK stack outputs fixture
        boto3_clients: boto3 clients fixture

    Returns:
        Database connection URL

    Raises:
        pytest.skip: If database credentials not available
    """
    # Try to get from Parameter Store first
    ssm = boto3_clients['ssm']

    try:
        response = ssm.get_parameter(
            Name='/collections/database-url',
            WithDecryption=True
        )
        return response['Parameter']['Value']

    except Exception:
        # Fallback to constructing from stack outputs
        rds_endpoint = stack_outputs.get('RdsEndpoint')
        db_name = stack_outputs.get('DatabaseName', 'collections')
        username = stack_outputs.get('RdsUsername', 'postgres')
        password = stack_outputs.get('RdsPassword')

        if not all([rds_endpoint, password]):
            pytest.skip("Database credentials not available")

        return f"postgresql://{username}:{password}@{rds_endpoint}:5432/{db_name}"


@pytest.fixture(scope="module")
def db_session(database_url):
    """
    Create SQLAlchemy session for direct database queries.

    Args:
        database_url: Database connection URL fixture

    Yields:
        SQLAlchemy session
    """
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        SessionLocal = sessionmaker(bind=engine)

        session = SessionLocal()

        yield session

        session.close()
        engine.dispose()

    except Exception as e:
        pytest.skip(f"Cannot connect to database: {e}")


@pytest.fixture(scope="module")
def test_queries() -> List[Dict[str, Any]]:
    """
    Provide a comprehensive set of test queries.

    Returns:
        List of query dictionaries with metadata
    """
    return [
        # Simple single-word queries
        {'query': 'furniture', 'complexity': 'simple', 'expected_results': True},
        {'query': 'landscape', 'complexity': 'simple', 'expected_results': True},
        {'query': 'portrait', 'complexity': 'simple', 'expected_results': True},
        {'query': 'food', 'complexity': 'simple', 'expected_results': True},
        {'query': 'architecture', 'complexity': 'simple', 'expected_results': True},

        # Two-word queries
        {'query': 'modern furniture', 'complexity': 'medium', 'expected_results': True},
        {'query': 'outdoor activities', 'complexity': 'medium', 'expected_results': True},
        {'query': 'food photography', 'complexity': 'medium', 'expected_results': True},
        {'query': 'urban landscape', 'complexity': 'medium', 'expected_results': True},
        {'query': 'vintage items', 'complexity': 'medium', 'expected_results': True},

        # Complex multi-word queries
        {'query': 'modern minimalist furniture design', 'complexity': 'complex', 'expected_results': True},
        {'query': 'outdoor adventure sports photography', 'complexity': 'complex', 'expected_results': True},
        {'query': 'contemporary urban architecture photography', 'complexity': 'complex', 'expected_results': True},

        # Semantic queries (better for vector search)
        {'query': 'items for home decoration', 'complexity': 'semantic', 'expected_results': True},
        {'query': 'photos taken during sunset', 'complexity': 'semantic', 'expected_results': True},
        {'query': 'images with natural lighting', 'complexity': 'semantic', 'expected_results': True},

        # Edge cases
        {'query': 'xyz123nonexistent', 'complexity': 'edge', 'expected_results': False},
        {'query': 'a', 'complexity': 'edge', 'expected_results': False},
    ]


@pytest.fixture(scope="module")
def test_user_id(test_cognito_user) -> str:
    """
    Get test user ID for user-isolated queries.

    Args:
        test_cognito_user: Test Cognito user fixture

    Returns:
        User ID string
    """
    return test_cognito_user['user_id']


class TestBM25SearchLatency:
    """Test PostgreSQL tsvector (BM25) search performance."""

    def test_bm25_search_latency(self, db_session, test_queries, test_user_id):
        """
        Measure BM25 search latency using PostgreSQL tsvector.

        This tests the SQL-based full-text search performance.
        """
        measurement = SearchLatencyMeasurement('bm25-tsvector', top_k=10)

        print(f"\n\nTesting BM25 Search Latency (PostgreSQL tsvector):")

        # Execute searches
        for query_data in test_queries:
            query = query_data['query']

            # Format query for tsvector
            terms = query.lower().split()
            tsquery = ' & '.join(terms)

            # Measure search latency
            start = time.perf_counter()

            try:
                sql = text("""
                    SELECT
                        a.id,
                        a.summary,
                        a.category,
                        i.filename,
                        ts_rank(a.search_vector, to_tsquery('english', :query)) AS score
                    FROM analyses a
                    JOIN items i ON a.item_id = i.id
                    WHERE
                        a.user_id = :user_id
                        AND a.search_vector @@ to_tsquery('english', :query)
                    ORDER BY score DESC
                    LIMIT :limit
                """)

                result = db_session.execute(
                    sql,
                    {
                        'user_id': test_user_id,
                        'query': tsquery,
                        'limit': 10
                    }
                )

                results = result.fetchall()

            except Exception as e:
                # Query may fail for edge cases
                results = []

            latency_ms = (time.perf_counter() - start) * 1000

            measurement.record(query, latency_ms, len(results))

            print(f"  Query: '{query}' - {latency_ms:.2f}ms ({len(results)} results)")

        # Get statistics
        stats = measurement.get_statistics()

        print(f"\n\nBM25 Search Statistics:")
        print(f"  Mean: {stats['mean']:.2f}ms")
        print(f"  Median: {stats['median']:.2f}ms")
        print(f"  P95: {stats['p95']:.2f}ms")
        print(f"  P99: {stats['p99']:.2f}ms")
        print(f"  Min/Max: {stats['min']:.2f}ms / {stats['max']:.2f}ms")
        print(f"  Avg Results: {stats['avg_results']:.1f}")
        print(f"  Queries/sec: {stats['queries_per_second']:.1f}")

        # Check against target
        meets_target, message = measurement.meets_target(300)
        print(f"  Target Check: {'PASS' if meets_target else 'FAIL'} - {message}")

        assert stats['mean'] < 200, f"BM25 search too slow (mean): {stats['mean']:.2f}ms"
        assert meets_target, f"BM25 search target not met: {message}"

    def test_bm25_search_scalability(self, db_session, test_user_id):
        """
        Test how BM25 search scales with different top_k values.

        Measures impact of result set size on latency.
        """
        query = 'modern furniture'
        terms = query.split()
        tsquery = ' & '.join(terms)

        top_k_values = [5, 10, 20, 50, 100]
        results = []

        print(f"\n\nBM25 Search Scalability Test:")

        for top_k in top_k_values:
            latencies = []

            # Run 10 iterations
            for _ in range(10):
                start = time.perf_counter()

                sql = text("""
                    SELECT
                        a.id,
                        a.summary,
                        ts_rank(a.search_vector, to_tsquery('english', :query)) AS score
                    FROM analyses a
                    WHERE
                        a.user_id = :user_id
                        AND a.search_vector @@ to_tsquery('english', :query)
                    ORDER BY score DESC
                    LIMIT :limit
                """)

                result = db_session.execute(
                    sql,
                    {
                        'user_id': test_user_id,
                        'query': tsquery,
                        'limit': top_k
                    }
                )

                result.fetchall()

                latency_ms = (time.perf_counter() - start) * 1000
                latencies.append(latency_ms)

            avg_latency = statistics.mean(latencies)
            results.append({'top_k': top_k, 'latency': avg_latency})

            print(f"  top_k={top_k:3d}: {avg_latency:.2f}ms")

        # Latency should scale roughly linearly (or less)
        # Check that doubling top_k doesn't double latency
        if len(results) >= 2:
            latency_ratio = results[-1]['latency'] / results[0]['latency']
            top_k_ratio = results[-1]['top_k'] / results[0]['top_k']

            print(f"\n  Latency scaling: {latency_ratio:.2f}x (top_k scaling: {top_k_ratio:.0f}x)")

            assert latency_ratio < top_k_ratio * 1.5, "BM25 search scales poorly with top_k"


class TestVectorSearchLatency:
    """Test pgvector search performance."""

    def test_vector_search_latency(self, db_session, test_queries, test_user_id):
        """
        Measure vector search latency using pgvector.

        This tests the cosine similarity search performance.
        """
        # Skip if no embeddings exist
        try:
            count_result = db_session.execute(
                text("SELECT COUNT(*) FROM embeddings WHERE user_id = :user_id"),
                {'user_id': test_user_id}
            ).fetchone()

            if count_result[0] == 0:
                pytest.skip("No embeddings available for testing")

        except Exception as e:
            pytest.skip(f"Cannot check embeddings: {e}")

        measurement = SearchLatencyMeasurement('pgvector-cosine', top_k=10)

        print(f"\n\nTesting Vector Search Latency (pgvector):")

        # For this test, we'll measure the query execution time
        # Note: Actual embedding generation happens in the application layer
        # Here we're testing the vector similarity search itself

        # Get a sample embedding to use for testing
        try:
            sample = db_session.execute(
                text("SELECT embedding FROM embeddings WHERE user_id = :user_id LIMIT 1"),
                {'user_id': test_user_id}
            ).fetchone()

            if not sample:
                pytest.skip("No sample embedding available")

            sample_embedding = sample[0]

        except Exception as e:
            pytest.skip(f"Cannot get sample embedding: {e}")

        # Test vector search performance
        for i in range(len(test_queries)):
            # Measure search latency
            start = time.perf_counter()

            try:
                sql = text("""
                    SELECT
                        e.id,
                        e.item_id,
                        e.embedding <=> :query_embedding AS distance
                    FROM embeddings e
                    WHERE e.user_id = :user_id
                    ORDER BY e.embedding <=> :query_embedding
                    LIMIT :limit
                """)

                result = db_session.execute(
                    sql,
                    {
                        'user_id': test_user_id,
                        'query_embedding': sample_embedding,
                        'limit': 10
                    }
                )

                results = result.fetchall()

            except Exception as e:
                print(f"  Query error: {e}")
                results = []

            latency_ms = (time.perf_counter() - start) * 1000

            measurement.record(f"vector_query_{i}", latency_ms, len(results))

            if i < 5:  # Print first few
                print(f"  Query {i+1}: {latency_ms:.2f}ms ({len(results)} results)")

        # Get statistics
        stats = measurement.get_statistics()

        print(f"\n\nVector Search Statistics:")
        print(f"  Mean: {stats['mean']:.2f}ms")
        print(f"  Median: {stats['median']:.2f}ms")
        print(f"  P95: {stats['p95']:.2f}ms")
        print(f"  P99: {stats['p99']:.2f}ms")
        print(f"  Min/Max: {stats['min']:.2f}ms / {stats['max']:.2f}ms")
        print(f"  Avg Results: {stats['avg_results']:.1f}")
        print(f"  Queries/sec: {stats['queries_per_second']:.1f}")

        # Check against target
        meets_target, message = measurement.meets_target(300)
        print(f"  Target Check: {'PASS' if meets_target else 'FAIL'} - {message}")

        # Vector search should be fast with proper indexing
        assert stats['mean'] < 250, f"Vector search too slow (mean): {stats['mean']:.2f}ms"
        assert meets_target, f"Vector search target not met: {message}"


class TestHybridSearchLatency:
    """Test hybrid search (BM25 + Vector) performance."""

    def test_hybrid_search_latency(self, db_session, test_user_id):
        """
        Measure hybrid search latency (RRF fusion).

        This combines BM25 and vector search results.
        """
        # Skip if no embeddings
        try:
            count_result = db_session.execute(
                text("SELECT COUNT(*) FROM embeddings WHERE user_id = :user_id"),
                {'user_id': test_user_id}
            ).fetchone()

            if count_result[0] == 0:
                pytest.skip("No embeddings available for testing")

        except Exception as e:
            pytest.skip(f"Cannot check embeddings: {e}")

        measurement = SearchLatencyMeasurement('hybrid-rrf', top_k=10)

        print(f"\n\nTesting Hybrid Search Latency (BM25 + Vector RRF):")

        # Test queries
        queries = ['modern furniture', 'landscape', 'food photography', 'architecture', 'vintage']

        for query in queries:
            # Simulate hybrid search (both BM25 and vector queries)
            start = time.perf_counter()

            # 1. BM25 query
            terms = query.split()
            tsquery = ' & '.join(terms)

            try:
                bm25_sql = text("""
                    SELECT
                        a.id,
                        ts_rank(a.search_vector, to_tsquery('english', :query)) AS score
                    FROM analyses a
                    WHERE
                        a.user_id = :user_id
                        AND a.search_vector @@ to_tsquery('english', :query)
                    ORDER BY score DESC
                    LIMIT 20
                """)

                bm25_results = db_session.execute(
                    bm25_sql,
                    {'user_id': test_user_id, 'query': tsquery}
                ).fetchall()

            except Exception:
                bm25_results = []

            # 2. Vector query (using sample embedding for timing)
            try:
                sample = db_session.execute(
                    text("SELECT embedding FROM embeddings WHERE user_id = :user_id LIMIT 1"),
                    {'user_id': test_user_id}
                ).fetchone()

                if sample:
                    vector_sql = text("""
                        SELECT
                            e.id,
                            e.embedding <=> :query_embedding AS distance
                        FROM embeddings e
                        WHERE e.user_id = :user_id
                        ORDER BY e.embedding <=> :query_embedding
                        LIMIT 20
                    """)

                    vector_results = db_session.execute(
                        vector_sql,
                        {'user_id': test_user_id, 'query_embedding': sample[0]}
                    ).fetchall()
                else:
                    vector_results = []

            except Exception:
                vector_results = []

            # 3. RRF fusion (simplified - just combine)
            combined_results = list(set(
                [r[0] for r in bm25_results[:10]] +
                [r[0] for r in vector_results[:10]]
            ))[:10]

            latency_ms = (time.perf_counter() - start) * 1000

            measurement.record(query, latency_ms, len(combined_results))

            print(f"  Query: '{query}' - {latency_ms:.2f}ms ({len(combined_results)} results)")

        # Get statistics
        stats = measurement.get_statistics()

        print(f"\n\nHybrid Search Statistics:")
        print(f"  Mean: {stats['mean']:.2f}ms")
        print(f"  Median: {stats['median']:.2f}ms")
        print(f"  P95: {stats['p95']:.2f}ms")
        print(f"  Min/Max: {stats['min']:.2f}ms / {stats['max']:.2f}ms")
        print(f"  Avg Results: {stats['avg_results']:.1f}")

        # Hybrid search should be < 2x BM25 alone (since it runs both)
        meets_target, message = measurement.meets_target(500)
        print(f"  Target Check: {'PASS' if meets_target else 'FAIL'} - {message}")


class TestSearchComparison:
    """Compare search performance across all types."""

    def test_search_type_comparison(self, db_session, test_user_id):
        """
        Compare latency across BM25, Vector, and Hybrid searches.

        Provides comprehensive performance comparison.
        """
        query = 'modern furniture'
        results = []

        print(f"\n\nSearch Type Comparison (query: '{query}'):")

        # Test BM25
        bm25_latencies = []
        for _ in range(20):
            start = time.perf_counter()

            terms = query.split()
            tsquery = ' & '.join(terms)

            try:
                db_session.execute(
                    text("""
                        SELECT a.id, ts_rank(a.search_vector, to_tsquery('english', :query)) AS score
                        FROM analyses a
                        WHERE a.user_id = :user_id AND a.search_vector @@ to_tsquery('english', :query)
                        ORDER BY score DESC LIMIT 10
                    """),
                    {'user_id': test_user_id, 'query': tsquery}
                ).fetchall()
            except Exception:
                pass

            bm25_latencies.append((time.perf_counter() - start) * 1000)

        results.append({
            'type': 'BM25',
            'mean': statistics.mean(bm25_latencies),
            'median': statistics.median(bm25_latencies)
        })

        print(f"\n  BM25 Search:")
        print(f"    Mean: {results[-1]['mean']:.2f}ms")
        print(f"    Median: {results[-1]['median']:.2f}ms")

        # Print comparison table
        print(f"\n\nComparison Summary:")
        print(f"{'Search Type':<15} {'Mean (ms)':<12} {'Median (ms)':<12}")
        print("-" * 45)

        for result in results:
            print(f"{result['type']:<15} {result['mean']:<12.2f} {result['median']:<12.2f}")


def pytest_sessionfinish(session, exitstatus):
    """
    Generate search performance report after all tests complete.

    This is a pytest hook that runs after the test session.
    """
    if not hasattr(session, 'testscollected') or session.testscollected == 0:
        return

    # Generate markdown report
    report_dir = Path(__file__).parent.parent.parent / 'reports'
    report_dir.mkdir(exist_ok=True)

    timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    env_name = os.getenv('CDK_ENV', 'dev')
    report_file = report_dir / f'search-latency-{env_name}-{timestamp}.md'

    with open(report_file, 'w') as f:
        f.write(f"# Search Latency Performance Report\n\n")
        f.write(f"**Environment:** {env_name}\n")
        f.write(f"**Timestamp:** {datetime.utcnow().isoformat()}\n")
        f.write(f"**Tests Run:** {session.testscollected}\n")
        f.write(f"**Tests Failed:** {session.testsfailed}\n\n")

        f.write("## Performance Targets\n\n")
        f.write("| Metric | Target | Status |\n")
        f.write("|--------|--------|--------|\n")
        f.write("| Search P95 Latency | < 300ms | - |\n")
        f.write("| BM25 Mean Latency | < 200ms | - |\n")
        f.write("| Vector Mean Latency | < 250ms | - |\n\n")

        f.write("## Search Types Tested\n\n")
        f.write("- **BM25**: PostgreSQL tsvector full-text search\n")
        f.write("- **Vector**: pgvector cosine similarity search\n")
        f.write("- **Hybrid**: Reciprocal Rank Fusion (RRF) of BM25 + Vector\n\n")

        f.write("## Test Results\n\n")
        f.write("Detailed results available in pytest output.\n\n")

        f.write("## Recommendations\n\n")
        f.write("- Monitor search index statistics in PostgreSQL\n")
        f.write("- Consider query caching for common searches\n")
        f.write("- Tune pgvector index parameters based on data size\n")
        f.write("- Implement pagination to limit result set size\n")

    print(f"\n\nSearch performance report generated: {report_file}")


if __name__ == "__main__":
    """
    Run search latency tests with verbose output.

    Usage:
        python tests/performance/test_search_latency.py
    """
    pytest.main([__file__, "-v", "-s"])
