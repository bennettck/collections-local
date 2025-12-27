# Benchmark Quick Start Guide

Get started with Phase 5 benchmarks in 5 minutes.

## Prerequisites

1. **AWS Infrastructure Deployed**
   ```bash
   make infra-deploy ENV=dev
   ```

2. **Python Dependencies**
   ```bash
   pip install -r scripts/benchmark/requirements.txt
   ```

3. **AWS Credentials Configured**
   ```bash
   aws configure
   # OR
   export AWS_ACCESS_KEY_ID=xxx
   export AWS_SECRET_ACCESS_KEY=xxx
   ```

## Run All Benchmarks

### Full Benchmark (10-15 minutes)
```bash
cd /workspaces/collections-local/scripts/benchmark
./run_all_benchmarks.sh dev
```

### Quick Benchmark (5-7 minutes)
```bash
./run_all_benchmarks.sh dev --quick
```

## View Results

### Check Report
```bash
# Find latest report
ls -lt /workspaces/collections-local/reports/phase5-benchmark-*.md | head -1

# View report
cat /workspaces/collections-local/reports/phase5-benchmark-dev-*.md

# Or open in editor
code /workspaces/collections-local/reports/phase5-benchmark-dev-*.md
```

### Check JSON Results
```bash
# Latest results in current directory
ls -lt benchmark_*.json

# View with jq
jq '.' benchmark_api_dev_*.json
```

## Individual Benchmarks

### API Only
```bash
python benchmark_api.py --env dev
```

### Search Only
```bash
python benchmark_search.py --env dev
```

### Cold Starts Only
```bash
python benchmark_cold_starts.py --env dev
```

## Common Scenarios

### Test Specific Endpoint
```bash
python benchmark_api.py --env dev --endpoint /health
```

### Test with Custom Queries
```bash
python benchmark_search.py --env dev --queries example_test_queries.json
```

### Reduce Cold Start Iterations (Faster)
```bash
python benchmark_cold_starts.py --env dev --iterations 3
```

### Generate Report from Existing Results
```bash
python generate_report.py --env dev \
  --api benchmark_api_dev_20240127_120000.json \
  --search benchmark_search_dev_20240127_120000.json \
  --cold-start benchmark_cold_starts_dev_20240127_120000.json
```

## Understanding Results

### Performance Targets

| Metric | Target | What It Means |
|--------|--------|---------------|
| API P95 Latency | < 500ms | 95% of API requests complete in under 500ms |
| Search P95 Latency | < 300ms | 95% of searches complete in under 300ms |
| API Cold Start | < 3s | Lambda initialization takes less than 3 seconds |

### Status Indicators

- ✅ **PASS** - Meets performance target
- ❌ **FAIL** - Exceeds performance target (needs optimization)
- **N/A** - Metric not available or not applicable

## Troubleshooting

### Configuration Not Found
```
Error: .aws-outputs-dev.json not found
```
**Fix:** Deploy infrastructure first
```bash
make infra-deploy ENV=dev
```

### Lambda Not Found
```
Error: Function not found
```
**Fix:** Check Lambda ARN in configuration
```bash
cat infrastructure/.aws-outputs-dev.json | grep Lambda
```

### Permission Denied
```
Error: Access denied
```
**Fix:** Check AWS credentials
```bash
aws sts get-caller-identity
```

## Next Steps

1. **Review Report** - Check recommendations section
2. **Address Issues** - Fix any failed targets
3. **Re-test** - Run benchmarks again after optimizations
4. **Compare** - Compare results across environments (dev vs prod)

## Cost

Approximate cost per full benchmark run:
- ~1,250 Lambda invocations
- ~$0.25 USD
- Minimal data transfer

## Support

See full documentation: `README.md`
