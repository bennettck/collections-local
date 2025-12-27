#!/bin/bash
# Run all Phase 5 benchmarks and generate report
#
# Usage:
#   ./run_all_benchmarks.sh dev
#   ./run_all_benchmarks.sh prod --quick

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
ENV=${1:-dev}
QUICK_MODE=${2}  # --quick for reduced iterations

# Script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Benchmark parameters
API_CONCURRENCY="1 10 50 100"
API_REQUESTS=100
SEARCH_ITERATIONS=10
COLD_START_ITERATIONS=5

# Quick mode (fewer iterations)
if [ "$QUICK_MODE" = "--quick" ]; then
    echo -e "${YELLOW}Running in QUICK MODE (reduced iterations)${NC}"
    API_CONCURRENCY="1 10"
    API_REQUESTS=50
    SEARCH_ITERATIONS=5
    COLD_START_ITERATIONS=3
fi

# Output files
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
API_OUTPUT="benchmark_api_${ENV}_${TIMESTAMP}.json"
SEARCH_OUTPUT="benchmark_search_${ENV}_${TIMESTAMP}.json"
COLD_START_OUTPUT="benchmark_cold_starts_${ENV}_${TIMESTAMP}.json"
REPORT_OUTPUT="/workspaces/collections-local/reports/phase5-benchmark-${ENV}-${TIMESTAMP}.md"

# Ensure reports directory exists
mkdir -p /workspaces/collections-local/reports

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  Phase 5 Benchmark Suite${NC}"
echo -e "${BLUE}================================================${NC}"
echo -e "Environment:      ${GREEN}${ENV}${NC}"
echo -e "Timestamp:        ${TIMESTAMP}"
echo -e "Quick Mode:       $([ "$QUICK_MODE" = "--quick" ] && echo "${GREEN}Yes${NC}" || echo "${YELLOW}No${NC}")"
echo -e "${BLUE}================================================${NC}\n"

# Validate configuration
CONFIG_FILE="/workspaces/collections-local/infrastructure/.aws-outputs-${ENV}.json"
if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}ERROR: Configuration file not found: ${CONFIG_FILE}${NC}"
    echo "Run 'make infra-deploy ENV=${ENV}' first."
    exit 1
fi

echo -e "${GREEN}✓ Configuration validated${NC}\n"

# Step 1: API Benchmarks
echo -e "${BLUE}[1/4] Running API Endpoint Benchmarks${NC}"
echo "----------------------------------------------"
python3 "${SCRIPT_DIR}/benchmark_api.py" \
    --env "${ENV}" \
    --concurrency ${API_CONCURRENCY} \
    --requests ${API_REQUESTS} \
    --output "${API_OUTPUT}"

if [ $? -ne 0 ]; then
    echo -e "${RED}✗ API benchmark failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ API benchmark complete${NC}\n"

# Step 2: Search Benchmarks
echo -e "${BLUE}[2/4] Running Search Performance Benchmarks${NC}"
echo "----------------------------------------------"
python3 "${SCRIPT_DIR}/benchmark_search.py" \
    --env "${ENV}" \
    --output "${SEARCH_OUTPUT}"

if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Search benchmark failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Search benchmark complete${NC}\n"

# Step 3: Cold Start Benchmarks
echo -e "${BLUE}[3/4] Running Lambda Cold Start Benchmarks${NC}"
echo "----------------------------------------------"
echo -e "${YELLOW}Warning: This will temporarily update Lambda configurations${NC}"
echo -e "${YELLOW}         and may take several minutes...${NC}\n"

python3 "${SCRIPT_DIR}/benchmark_cold_starts.py" \
    --env "${ENV}" \
    --iterations ${COLD_START_ITERATIONS} \
    --output "${COLD_START_OUTPUT}"

if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Cold start benchmark failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Cold start benchmark complete${NC}\n"

# Step 4: Generate Report
echo -e "${BLUE}[4/4] Generating Comprehensive Report${NC}"
echo "----------------------------------------------"
python3 "${SCRIPT_DIR}/generate_report.py" \
    --env "${ENV}" \
    --api "${API_OUTPUT}" \
    --search "${SEARCH_OUTPUT}" \
    --cold-start "${COLD_START_OUTPUT}" \
    --output "${REPORT_OUTPUT}"

if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Report generation failed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Report generated${NC}\n"

# Summary
echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  Benchmark Complete!${NC}"
echo -e "${BLUE}================================================${NC}"
echo -e "Results:"
echo -e "  API:         ${API_OUTPUT}"
echo -e "  Search:      ${SEARCH_OUTPUT}"
echo -e "  Cold Start:  ${COLD_START_OUTPUT}"
echo -e ""
echo -e "Report:"
echo -e "  ${GREEN}${REPORT_OUTPUT}${NC}"
echo -e ""
echo -e "To view report:"
echo -e "  ${YELLOW}cat ${REPORT_OUTPUT}${NC}"
echo -e "  ${YELLOW}code ${REPORT_OUTPUT}${NC} (if using VS Code)"
echo -e "${BLUE}================================================${NC}"

# Optional: Display quick summary
if command -v jq &> /dev/null; then
    echo -e "\n${BLUE}Quick Summary:${NC}"

    # API P95
    if [ -f "${API_OUTPUT}" ]; then
        API_P95=$(jq -r '.summary.overall_metrics.p95_latency_ms // "N/A"' "${API_OUTPUT}")
        echo -e "  API P95 Latency:     ${API_P95}ms"
    fi

    # Search Winner
    if [ -f "${SEARCH_OUTPUT}" ]; then
        SEARCH_WINNER=$(jq -r '.summary.winner.fastest.method // "N/A"' "${SEARCH_OUTPUT}")
        SEARCH_P95=$(jq -r '.summary.winner.fastest.p95_latency_ms // "N/A"' "${SEARCH_OUTPUT}")
        echo -e "  Fastest Search:      ${SEARCH_WINNER} (${SEARCH_P95}ms)"
    fi

    # Cold Start
    if [ -f "${COLD_START_OUTPUT}" ]; then
        COLD_START=$(jq -r '.summary.target_compliance.api.mean_ms // "N/A"' "${COLD_START_OUTPUT}")
        MEETS_TARGET=$(jq -r '.summary.target_compliance.api.meets_target // "N/A"' "${COLD_START_OUTPUT}")
        STATUS=$([ "$MEETS_TARGET" = "true" ] && echo "${GREEN}✓${NC}" || echo "${RED}✗${NC}")
        echo -e "  API Cold Start:      ${COLD_START}ms ${STATUS}"
    fi
fi

exit 0
