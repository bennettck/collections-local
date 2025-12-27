# Phase 5 Benchmark Suite

Comprehensive benchmarking tools for testing AWS Lambda deployment performance, search quality, and cold start times.

## Overview

This benchmark suite provides automated testing for:

1. **API Endpoint Performance** - Latency, throughput, and concurrent request handling
2. **Search Quality & Speed** - Comparing hybrid, BM25, and vector search methods
3. **Lambda Cold Starts** - Measuring initialization times for all Lambda functions

## Requirements

### Python Dependencies

```bash
pip install boto3 requests
```

### AWS Configuration

Benchmarks require:
- AWS credentials configured (`aws configure`)
- Deployed infrastructure for target environment
- AWS outputs file: `/workspaces/collections-local/infrastructure/.aws-outputs-{env}.json`

## Quick Start

### Run All Benchmarks

```bash
# Run all benchmarks for dev environment
./run_all_benchmarks.sh dev

# Or manually:
python benchmark_api.py --env dev
python benchmark_search.py --env dev
python benchmark_cold_starts.py --env dev
python generate_report.py --env dev
```

### Run Individual Benchmarks

```bash
# API endpoints
python benchmark_api.py --env dev

# Search performance
python benchmark_search.py --env dev

# Lambda cold starts
python benchmark_cold_starts.py --env dev

# Generate report from existing results
python generate_report.py --env dev
```

## Scripts

### 1. benchmark_api.py

Tests API endpoint performance with varying concurrency levels.

**Usage:**
```bash
# Test all endpoints
python benchmark_api.py --env dev

# Test specific endpoint
python benchmark_api.py --env dev --endpoint /health

# Custom concurrency levels
python benchmark_api.py --env dev --concurrency 1 10 50 100

# Custom request count
python benchmark_api.py --env dev --requests 200
```

**Metrics:**
- Response time (mean, median, P95, P99)
- Throughput (requests/second)
- Success rate
- Error rates

**Default Concurrency Levels:**
- 1 (baseline)
- 10 (light load)
- 50 (moderate load)
- 100 (heavy load)

### 2. benchmark_search.py

Compares search methods for quality and performance.

**Usage:**
```bash
# Test all search methods
python benchmark_search.py --env dev

# Test specific method
python benchmark_search.py --env dev --method hybrid

# Custom queries from file
python benchmark_search.py --env dev --queries test_queries.json

# With ground truth for quality metrics
python benchmark_search.py --env dev --ground-truth ground_truth.json

# Custom k value
python benchmark_search.py --env dev --k 20
```

**Metrics:**
- Latency (mean, median, P95, P99)
- Precision@k
- Recall@k
- Mean Reciprocal Rank (MRR)

**Search Methods:**
- `hybrid` - Combined BM25 + vector search (Reciprocal Rank Fusion)
- `bm25` - PostgreSQL tsvector full-text search
- `vector` - pgvector cosine similarity search

**Query File Format (JSON):**
```json
{
  "queries": [
    "modern furniture",
    "outdoor activities",
    "food photography"
  ]
}
```

**Ground Truth Format (JSON):**
```json
{
  "modern furniture": ["item-id-1", "item-id-2", "item-id-3"],
  "outdoor activities": ["item-id-4", "item-id-5"]
}
```

### 3. benchmark_cold_starts.py

Measures Lambda function initialization times.

**Usage:**
```bash
# Test all functions
python benchmark_cold_starts.py --env dev

# Test specific function
python benchmark_cold_starts.py --env dev --function api

# Custom iteration count
python benchmark_cold_starts.py --env dev --iterations 10
```

**Functions:**
- `api` - API Gateway Lambda (FastAPI + Mangum)
- `processor` - Image processor Lambda
- `analyzer` - Image analysis Lambda
- `embedder` - Embedding generation Lambda
- `cleanup` - Conversation cleanup Lambda

**Metrics:**
- Total cold start time
- Initialization duration (from CloudWatch logs)
- Target compliance (API Lambda < 3s)

**How It Works:**
1. Forces cold start by updating environment variable
2. Waits for Lambda instances to terminate
3. Invokes function and measures total time
4. Extracts init duration from CloudWatch logs
5. Repeats for statistical significance

### 4. generate_report.py

Generates comprehensive markdown report from benchmark results.

**Usage:**
```bash
# Auto-discover latest results
python generate_report.py --env dev

# Specify result files
python generate_report.py --env dev \
  --api api_results.json \
  --search search_results.json \
  --cold-start cold_start_results.json

# Custom output path
python generate_report.py --env dev --output custom_report.md
```

**Report Sections:**
1. Executive Summary - Key metrics overview
2. API Endpoint Benchmarks - Detailed API performance
3. Search Performance - Method comparison
4. Lambda Cold Start Analysis - Initialization times
5. Performance Targets - Comparison against targets
6. Recommendations - Actionable optimization suggestions

**Default Output:**
`/workspaces/collections-local/reports/phase5-benchmark-{env}-{timestamp}.md`

## Performance Targets

Based on IMPLEMENTATION_PLAN.md Phase 5 requirements:

| Metric | Target | Critical |
|--------|--------|----------|
| API P95 Latency | < 500ms | Yes |
| Search P95 Latency | < 300ms | Yes |
| API Cold Start | < 3s | Yes |
| Workflow Completion | < 30s | No (not in this suite) |

## Output Files

### JSON Results

All benchmark scripts output JSON files with detailed results:

```
benchmark_api_{env}_{timestamp}.json
benchmark_search_{env}_{timestamp}.json
benchmark_cold_starts_{env}_{timestamp}.json
```

### Markdown Report

Generated report includes:
- Performance tables
- Target compliance
- Recommendations
- Detailed metrics

## Integration with Makefile

Add to project Makefile:

```makefile
.PHONY: benchmark-api
benchmark-api:
	@echo "🔬 Benchmarking API endpoints..."
	python scripts/benchmark/benchmark_api.py --env $(ENV)

.PHONY: benchmark-search
benchmark-search:
	@echo "🔍 Benchmarking search performance..."
	python scripts/benchmark/benchmark_search.py --env $(ENV)

.PHONY: benchmark-cold-starts
benchmark-cold-starts:
	@echo "❄️  Benchmarking Lambda cold starts..."
	python scripts/benchmark/benchmark_cold_starts.py --env $(ENV)

.PHONY: benchmark-all
benchmark-all: benchmark-api benchmark-search benchmark-cold-starts
	@echo "📊 Generating benchmark report..."
	python scripts/benchmark/generate_report.py --env $(ENV)

.PHONY: benchmark-report
benchmark-report:
	@echo "📊 Generating benchmark report..."
	python scripts/benchmark/generate_report.py --env $(ENV)
```

Usage:
```bash
make benchmark-all ENV=dev
make benchmark-report ENV=dev
```

## Cost Considerations

**Estimated Costs per Full Benchmark Run:**
- API benchmark (100 requests × 4 concurrency levels × 3 endpoints): ~1,200 Lambda invocations
- Search benchmark (10 queries × 3 methods): ~30 invocations
- Cold start benchmark (5 iterations × 5 functions): ~25 invocations
- **Total:** ~1,250 invocations ≈ $0.25 + data transfer

**Recommendations:**
- Run full benchmarks sparingly (weekly/monthly)
- Use lower iteration counts for frequent testing
- Clean up CloudWatch logs after benchmarks

## Troubleshooting

### Configuration Not Found

```
FileNotFoundError: Configuration file not found: .aws-outputs-dev.json
```

**Solution:** Deploy infrastructure first:
```bash
make infra-deploy ENV=dev
```

### Lambda Invocation Errors

```
Error: Function not found
```

**Solution:** Check function names in AWS outputs:
```bash
cat infrastructure/.aws-outputs-dev.json | jq '.[] | select(.OutputKey | contains("Lambda"))'
```

### CloudWatch Logs Not Found

```
Warning: Could not get logs
```

**Solution:** Logs may take time to appear. The benchmark will still measure total duration.

### Cold Start Measurement Incomplete

```
Init Duration: N/A
```

**Solution:** This is normal - not all Lambda invocations report init duration. The total duration is still accurate.

## Advanced Usage

### Parallel Benchmarking

Run benchmarks in parallel for faster results:

```bash
# Terminal 1
python benchmark_api.py --env dev &

# Terminal 2
python benchmark_search.py --env dev &

# Terminal 3
python benchmark_cold_starts.py --env dev &

# Wait for all to complete
wait

# Generate combined report
python generate_report.py --env dev
```

### Custom Test Queries

Create `custom_queries.json`:
```json
{
  "queries": [
    "your custom query 1",
    "your custom query 2"
  ]
}
```

Run with custom queries:
```bash
python benchmark_search.py --env dev --queries custom_queries.json
```

### Comparative Analysis

Compare multiple environments:

```bash
# Benchmark dev
python benchmark_api.py --env dev --output results_dev.json

# Benchmark prod
python benchmark_api.py --env prod --output results_prod.json

# Compare manually or create custom script
```

## Library Usage

Following the project's **library-first** philosophy:

### AWS Interactions
- **boto3** - All AWS SDK operations (Lambda, CloudWatch, etc.)
- Standard AWS service clients (no custom wrappers)

### HTTP Requests
- **requests** - HTTP client for API Gateway testing
- Built-in libraries for JSON parsing

### Statistics
- **statistics** module - Mean, median, percentile calculations
- No external statistical libraries required

### Concurrency
- **concurrent.futures.ThreadPoolExecutor** - Thread-based concurrency
- Standard library threading

## Next Steps

After running benchmarks:

1. **Review Report** - Check `/workspaces/collections-local/reports/phase5-benchmark-*.md`
2. **Address Failures** - Focus on metrics that don't meet targets
3. **Optimize** - Use recommendations section as guide
4. **Re-test** - Verify improvements with follow-up benchmarks
5. **Document** - Update project documentation with benchmark results

## References

- IMPLEMENTATION_PLAN.md - Performance targets and requirements
- AWS Lambda Pricing: https://aws.amazon.com/lambda/pricing/
- boto3 Documentation: https://boto3.amazonaws.com/v1/documentation/api/latest/index.html
