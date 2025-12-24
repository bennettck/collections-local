# Testing Suite for Collections Local

This directory contains the comprehensive test suite for the collections-local project, with special focus on agentic search functionality.

## Test Structure

### Unit Tests
- **`test_agentic_search.py`**: Unit tests for the agentic search orchestrator with mocked dependencies
  - Tests search strategy selection logic
  - Tests tool invocation and coordination
  - Tests reasoning generation
  - Tests error handling and fallbacks

### Integration Tests
- **`test_search_endpoint.py`**: Integration tests for the `/search` endpoint
  - Tests all search types (bm25-lc, vector-lc, hybrid-lc, agentic)
  - Tests database routing (prod vs golden)
  - Tests response format compliance
  - Tests error handling

## Running Tests

### Prerequisites
```bash
# Install pytest and dependencies
pip install pytest pytest-asyncio pytest-mock

# Ensure the project is set up
pip install -r requirements.txt
```

### Run All Tests
```bash
# From project root
pytest

# With verbose output
pytest -v

# With coverage (requires pytest-cov)
pytest --cov=. --cov-report=html
```

### Run Specific Test Files
```bash
# Unit tests only
pytest tests/test_agentic_search.py

# Integration tests only
pytest tests/test_search_endpoint.py
```

### Run Tests by Marker
```bash
# Run only unit tests
pytest -m unit

# Run only integration tests (may require running services)
pytest -m integration

# Run agentic-specific tests
pytest -m agentic
```

### Run Specific Tests
```bash
# Run a specific test class
pytest tests/test_agentic_search.py::TestAgenticSearchOrchestrator

# Run a specific test method
pytest tests/test_agentic_search.py::TestAgenticSearchOrchestrator::test_select_search_strategy_vector_for_long_query

# Run tests matching a pattern
pytest -k "agentic"
```

## Validation Scripts

In addition to pytest tests, there are validation scripts for quick smoke testing:

### Test Agentic Search
```bash
# Test against golden database (default)
./scripts/test_agentic_search.py

# Test against production database
./scripts/test_agentic_search.py --no-golden-subdomain

# Custom API endpoint
./scripts/test_agentic_search.py --base-url http://localhost:8000
```

### Test Hybrid Retriever
```bash
# Test hybrid search
./scripts/test_hybrid_retriever.py

# Custom options
./scripts/test_hybrid_retriever.py --base-url http://localhost:8000 --no-golden-subdomain
```

## Evaluation

For full retrieval quality evaluation:

```bash
# Evaluate all search types
python scripts/evaluate_retrieval.py --search-types all

# Evaluate specific search types
python scripts/evaluate_retrieval.py --search-types agentic,hybrid-lc,vector-lc

# Evaluate agentic only
python scripts/evaluate_retrieval.py --search-types agentic

# With verbose output
python scripts/evaluate_retrieval.py --search-types agentic --verbose
```

## Test Development Guidelines

### Writing Unit Tests
- Mock all external dependencies (database, API calls, LLM calls)
- Focus on testing business logic and edge cases
- Use fixtures for common test data
- Keep tests fast and isolated

### Writing Integration Tests
- Test full workflows end-to-end
- Use TestClient for FastAPI endpoint testing
- Mark tests that require running services with `@pytest.mark.integration`
- Clean up test data after tests complete

### Test Naming Conventions
- Test files: `test_<module_name>.py`
- Test classes: `Test<ClassName>`
- Test methods: `test_<what_is_being_tested>`

### Markers
Use pytest markers to categorize tests:
- `@pytest.mark.unit` - Fast, isolated unit tests
- `@pytest.mark.integration` - Tests requiring running services
- `@pytest.mark.slow` - Tests that take significant time
- `@pytest.mark.agentic` - Agentic search specific tests

## Continuous Integration

Tests are designed to run in CI environments:

```bash
# Quick test suite (unit tests only)
pytest -m "unit and not slow"

# Full test suite
pytest -m "not integration"

# Integration tests (requires services)
pytest -m integration
```

## Troubleshooting

### Import Errors
If you see import errors, ensure you're running tests from the project root:
```bash
cd /workspaces/collections-local
pytest
```

### Database Errors
Integration tests may require database initialization:
```bash
# Initialize databases
python -c "from database import init_db; init_db()"
```

### API Connection Errors
Validation scripts require the API to be running:
```bash
# Start the API
uvicorn main:app --port 8000
```

## Test Coverage

To generate coverage reports:

```bash
# Generate HTML coverage report
pytest --cov=. --cov-report=html

# View report
open htmlcov/index.html  # macOS
# or
xdg-open htmlcov/index.html  # Linux
```

## Future Enhancements

- Add performance benchmarking tests
- Add property-based testing with Hypothesis
- Add mutation testing with mutmut
- Add API contract testing
- Add load testing scenarios
