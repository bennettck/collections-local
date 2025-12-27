# Performance Testing Suite

Comprehensive performance benchmarking for the Collections AWS migration (Phase 5).

## Overview

This test suite measures and validates performance metrics for the deployed AWS infrastructure, including:

- **API Endpoint Latency**: Response times for all API endpoints
- **Lambda Cold Starts**: Initialization times for Lambda functions
- **Search Query Latency**: Performance of different search types (BM25, Vector, Hybrid)

## Performance Targets

| Metric | Target | Priority |
|--------|--------|----------|
| API P95 Latency | < 500ms | High |
| Search P95 Latency | < 300ms | High |
| Lambda Cold Start | < 3s | Medium |
| API Success Rate | > 95% | Critical |

## Test Structure

```
tests/performance/
├── __init__.py              # Package initialization
├── conftest.py              # Shared pytest fixtures
├── test_api_latency.py      # API endpoint performance tests
├── test_cold_starts.py      # Lambda cold start measurements
├── test_search_latency.py   # Search performance benchmarks
└── README.md                # This file
```

## Prerequisites

### Infrastructure Deployment

Tests require a deployed AWS environment:

```bash
# Deploy infrastructure (if not already deployed)
make infra-deploy ENV=dev

# Verify deployment
make infra-status ENV=dev
```

### Configuration Files

Tests load configuration from:
- `/workspaces/collections-local/infrastructure/.aws-outputs-dev.json` (CDK outputs)
- Environment variables (AWS credentials, region)

### Dependencies

```bash
# Install test dependencies
pip install pytest requests boto3 psycopg2-binary sqlalchemy
```

## Running Tests

### Run All Performance Tests

```bash
# All tests with default environment (dev)
pytest tests/performance/ -v

# Specify environment
pytest tests/performance/ -v --env=dev

# With detailed output
pytest tests/performance/ -v -s
```

### Run Specific Test Suites

```bash
# API latency tests only
pytest tests/performance/test_api_latency.py -v

# Lambda cold start tests only
pytest tests/performance/test_cold_starts.py -v

# Search latency tests only
pytest tests/performance/test_search_latency.py -v
```

### Run Specific Tests

```bash
# Single test
pytest tests/performance/test_api_latency.py::TestHealthEndpointLatency::test_health_endpoint_latency -v

# Test class
pytest tests/performance/test_api_latency.py::TestAuthenticatedEndpointLatency -v
```

### Filter Tests by Marker

```bash
# Run only slow tests
pytest tests/performance/ -v -m slow

# Skip slow tests
pytest tests/performance/ -v -m "not slow"

# Run tests requiring data
pytest tests/performance/ -v -m requires_data
```

## Test Descriptions

### test_api_latency.py

**Purpose**: Measure API endpoint response times and compare against targets.

**Tests**:
- `test_health_endpoint_latency`: Baseline latency measurement (no auth, no DB)
- `test_list_items_latency`: Authenticated endpoint with database query
- `test_search_endpoint_latency`: Search endpoints (BM25, Vector, Hybrid)
- `test_chat_endpoint_latency`: Chat endpoint with LLM integration

**Metrics**:
- Mean, median, min, max latencies
- Percentiles (p50, p90, p95, p99)
- Success rate
- Throughput (queries per second)

**Example**:
```bash
pytest tests/performance/test_api_latency.py -v -s

# Expected output:
# Health Endpoint Latency:
#   Mean: 45.23ms
#   Median: 42.18ms
#   P95: 67.89ms
#   Success Rate: 100.0%
```

### test_cold_starts.py

**Purpose**: Measure Lambda function initialization times.

**Methodology**:
1. Update Lambda environment variable to force new instance
2. Invoke Lambda and measure total duration
3. Compare cold vs warm invocations
4. Repeat for statistical significance

**Tests**:
- `test_api_lambda_cold_start`: API Lambda (most critical)
- `test_image_processor_cold_start`: S3 event handler
- `test_analyzer_lambda_cold_start`: LLM analysis handler
- `test_all_lambdas_cold_start_comparison`: Cross-function comparison

**Metrics**:
- Cold start mean, median, max
- Warm start comparison
- Cold start overhead
- Memory usage
- Billed duration

**Example**:
```bash
pytest tests/performance/test_cold_starts.py::TestAPILambdaColdStart -v -s

# Expected output:
# API Lambda Cold Start Statistics:
#   Cold Start Mean: 1834ms
#   Cold Start Max: 2156ms
#   Warm Start Mean: 123ms
#   Cold Start Overhead: 1711ms
```

### test_search_latency.py

**Purpose**: Benchmark search query performance for different search types.

**Tests**:
- `test_bm25_search_latency`: PostgreSQL tsvector full-text search
- `test_vector_search_latency`: pgvector cosine similarity
- `test_hybrid_search_latency`: RRF fusion (BM25 + Vector)
- `test_bm25_search_scalability`: Impact of top_k parameter
- `test_search_type_comparison`: Comparative analysis

**Metrics**:
- Search latency per query type
- Scalability with result set size
- Query complexity impact
- Queries per second

**Example**:
```bash
pytest tests/performance/test_search_latency.py -v -s

# Expected output:
# BM25 Search Statistics:
#   Mean: 87.45ms
#   P95: 142.33ms
#   Queries/sec: 11.4
#
# Vector Search Statistics:
#   Mean: 156.78ms
#   P95: 234.56ms
```

## Understanding Results

### Latency Metrics

- **Mean**: Average latency across all requests
- **Median (P50)**: Middle value (50% faster, 50% slower)
- **P95**: 95th percentile (95% of requests faster)
- **P99**: 99th percentile (99% of requests faster)

**Interpretation**:
- Mean shows overall performance
- Median shows typical user experience
- P95/P99 show worst-case scenarios

### Success Rate

Percentage of requests that returned 2xx status codes.

**Thresholds**:
- 100%: Ideal
- 95-99%: Acceptable (some errors expected)
- <95%: Investigation required

### Cold Start Impact

Cold starts occur when Lambda creates a new execution environment.

**Factors**:
- Deployment package size
- Memory allocation
- Runtime initialization
- VPC configuration (if applicable)

**Mitigation**:
- Provisioned concurrency
- Smaller package size
- Container image optimization

## Report Generation

Tests automatically generate markdown reports in `/workspaces/collections-local/reports/`:

```
reports/
├── api-latency-dev-20251227-123456.md
├── cold-starts-dev-20251227-123456.md
├── search-latency-dev-20251227-123456.md
└── performance-summary-dev-20251227-123456.md
```

### Report Contents

Each report includes:
- Test execution timestamp
- Environment information
- Performance statistics
- Target comparison (PASS/FAIL)
- Recommendations

### Viewing Reports

```bash
# List recent reports
ls -lt reports/performance-*.md | head -5

# View latest summary
cat reports/performance-summary-dev-*.md | tail -n 100
```

## Troubleshooting

### Tests Skipped

**Symptom**: Tests show as "SKIPPED" instead of running

**Causes**:
1. Infrastructure not deployed
2. Configuration files missing
3. AWS credentials not configured
4. Insufficient test data

**Solutions**:
```bash
# Verify infrastructure deployed
make infra-status ENV=dev

# Check CDK outputs exist
ls -la infrastructure/.aws-outputs-dev.json

# Verify AWS credentials
aws sts get-caller-identity

# Seed test data
make db-seed-golden ENV=dev
```

### High Latency

**Symptom**: Latencies exceed targets

**Investigations**:
1. Check cold start frequency (CloudWatch)
2. Review database query plans (PostgreSQL EXPLAIN)
3. Verify network latency (VPC configuration)
4. Check Lambda memory allocation

**Optimizations**:
```bash
# Increase Lambda memory
# Edit infrastructure/stacks/compute_stack.py
# memory_size=2048  # Increase from 1024

# Re-deploy
make infra-deploy ENV=dev

# Re-run tests
pytest tests/performance/test_api_latency.py -v
```

### Authentication Failures

**Symptom**: Tests fail with 401 errors

**Causes**:
1. Cognito not configured
2. Test user creation failed
3. JWT token expired

**Solutions**:
```bash
# Verify Cognito user pool exists
aws cognito-idp list-user-pools --max-results 10

# Check CDK outputs for Cognito IDs
cat infrastructure/.aws-outputs-dev.json | grep Cognito
```

### Database Connection Issues

**Symptom**: Cannot connect to PostgreSQL

**Causes**:
1. RDS security group not allowing access
2. Database credentials incorrect
3. Database not initialized

**Solutions**:
```bash
# Test RDS connection
make db-connect ENV=dev

# Run migrations
make db-migrate ENV=dev

# Verify Parameter Store secrets
aws ssm get-parameter --name /collections/database-url --with-decryption
```

## Best Practices

### Test Execution

1. **Warm Up**: Always include warm-up requests to prime caches
2. **Sample Size**: Use sufficient iterations for statistical significance
3. **Isolation**: Run tests against dedicated test environment
4. **Timing**: Avoid running during production hours
5. **Cleanup**: Tests should clean up resources (handled automatically)

### Performance Analysis

1. **Compare Trends**: Track performance over time
2. **Baseline**: Establish baseline before optimization
3. **A/B Testing**: Compare before/after changes
4. **Real Load**: Simulate realistic usage patterns

### Continuous Monitoring

```bash
# Run nightly performance tests
0 2 * * * cd /workspaces/collections-local && pytest tests/performance/ -v --env=dev

# Alert on failures
# Configure CloudWatch alarms based on test results
```

## Integration with CI/CD

### GitHub Actions Example

```yaml
name: Performance Tests

on:
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM
  workflow_dispatch:     # Manual trigger

jobs:
  performance:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Configure AWS
        uses: aws-actions/configure-aws-credentials@v2
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1

      - name: Install Dependencies
        run: pip install -r requirements.txt

      - name: Run Performance Tests
        run: pytest tests/performance/ -v --env=dev

      - name: Upload Reports
        uses: actions/upload-artifact@v3
        with:
          name: performance-reports
          path: reports/
```

## Contributing

When adding new performance tests:

1. Follow existing patterns in `conftest.py`
2. Use measurement classes for consistency
3. Document expected latencies
4. Include statistical analysis
5. Generate markdown reports
6. Update this README

## References

- [IMPLEMENTATION_PLAN.md](../../IMPLEMENTATION_PLAN.md) - Phase 5 requirements
- [Integration Tests](../integration/README.md) - Functional test patterns
- [AWS Lambda Performance](https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html)
- [PostgreSQL Performance](https://www.postgresql.org/docs/current/performance-tips.html)
- [pgvector Optimization](https://github.com/pgvector/pgvector#performance)

## Support

For issues or questions:
1. Check CloudWatch logs for errors
2. Review test output for details
3. Consult IMPLEMENTATION_PLAN.md
4. Open issue with full error logs
