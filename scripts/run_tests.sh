#!/bin/bash
# Test runner script for collections-local project
#
# Usage:
#   ./scripts/run_tests.sh              # Run all tests
#   ./scripts/run_tests.sh unit         # Run unit tests only
#   ./scripts/run_tests.sh integration  # Run integration tests only
#   ./scripts/run_tests.sh agentic      # Run agentic-specific tests
#   ./scripts/run_tests.sh validate     # Run validation scripts

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}==>${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Change to project root
cd "$(dirname "$0")/.."

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    print_error "pytest is not installed"
    echo "Install it with: pip install pytest pytest-asyncio pytest-mock"
    exit 1
fi

# Determine test mode
MODE=${1:-all}

case $MODE in
    all)
        print_status "Running all tests..."
        pytest -v
        ;;

    unit)
        print_status "Running unit tests only..."
        pytest -v -m "unit or not integration"
        ;;

    integration)
        print_status "Running integration tests..."
        print_warning "Integration tests require the API to be running"
        pytest -v -m integration
        ;;

    agentic)
        print_status "Running agentic-specific tests..."
        pytest -v -m agentic tests/test_agentic_search.py
        ;;

    validate)
        print_status "Running validation scripts..."

        # Check if API is running
        if ! curl -s http://localhost:8000/health > /dev/null 2>&1; then
            print_error "API is not running at http://localhost:8000"
            print_warning "Start it with: uvicorn main:app --port 8000"
            exit 1
        fi

        print_status "Testing hybrid retriever..."
        ./scripts/test_hybrid_retriever.py

        print_status "Testing agentic search..."
        ./scripts/test_agentic_search.py

        print_success "All validation tests passed!"
        ;;

    coverage)
        print_status "Running tests with coverage..."
        if ! command -v pytest-cov &> /dev/null; then
            print_error "pytest-cov is not installed"
            echo "Install it with: pip install pytest-cov"
            exit 1
        fi
        pytest --cov=. --cov-report=html --cov-report=term
        print_success "Coverage report generated in htmlcov/"
        ;;

    quick)
        print_status "Running quick test suite (unit tests, no slow tests)..."
        pytest -v -m "not integration and not slow"
        ;;

    *)
        print_error "Unknown test mode: $MODE"
        echo ""
        echo "Usage: $0 [MODE]"
        echo ""
        echo "Modes:"
        echo "  all          Run all tests (default)"
        echo "  unit         Run unit tests only"
        echo "  integration  Run integration tests"
        echo "  agentic      Run agentic-specific tests"
        echo "  validate     Run validation scripts (requires API)"
        echo "  coverage     Run tests with coverage report"
        echo "  quick        Run quick test suite (unit, no slow)"
        exit 1
        ;;
esac

# Exit with success
print_success "Tests completed successfully!"
exit 0
