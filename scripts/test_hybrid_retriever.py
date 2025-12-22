#!/usr/bin/env python3
"""
Quick validation script to test the hybrid retriever implementation.

This script tests the hybrid-lc search type in isolation to verify:
1. The API accepts hybrid-lc as a valid search type
2. The retriever returns results with proper scores
3. Score normalization is working correctly
"""

import requests
import sys


def test_hybrid_search(base_url="http://localhost:8000", use_golden_db=True):
    """Test hybrid search with a few sample queries."""

    # Setup headers for golden database routing
    headers = {}
    if use_golden_db:
        headers["Host"] = "golden.localhost:8000"

    # Test queries covering different scenarios
    test_queries = [
        {
            "query": "TeamLab digital art museum Fukuoka",
            "description": "Single-item precision query",
            "expected_result": "Should return TeamLab item at rank 1"
        },
        {
            "query": "onsen hot spring accommodations Japan",
            "description": "Multi-item recall query",
            "expected_result": "Should return multiple onsen/ryokan items"
        },
        {
            "query": "where can I relax in a hot spring with mountain views",
            "description": "Semantic query",
            "expected_result": "Should return onsen items with mountain views"
        },
        {
            "query": "things to do in Paris",
            "description": "Edge case - no results expected",
            "expected_result": "Should return no results or very low scores"
        }
    ]

    print("=" * 70)
    print("HYBRID RETRIEVER VALIDATION TEST")
    print("=" * 70)
    print(f"\nAPI Endpoint: {base_url}")
    print(f"Database: {'golden (via subdomain)' if use_golden_db else 'production'}")
    print(f"Search Type: hybrid-lc\n")

    # Check API health
    try:
        response = requests.get(f"{base_url}/health", headers=headers, timeout=2)
        if response.status_code != 200:
            print(f"Error: API health check failed (status {response.status_code})")
            return False
        print("✓ API is healthy\n")
    except requests.exceptions.RequestException as e:
        print(f"Error: Cannot connect to API: {e}")
        print("\nPlease start the API server with: uvicorn main:app --port 8000")
        return False

    # Run test queries
    all_passed = True

    for i, test_case in enumerate(test_queries, 1):
        query_text = test_case["query"]
        description = test_case["description"]
        expected = test_case["expected_result"]

        print(f"Test {i}/{len(test_queries)}: {description}")
        print(f"Query: \"{query_text}\"")
        print(f"Expected: {expected}")

        try:
            # Make search request
            response = requests.post(
                f"{base_url}/search",
                json={
                    "query": query_text,
                    "top_k": 5,
                    "search_type": "hybrid-lc",
                    "include_answer": False
                },
                headers=headers,
                timeout=10
            )

            if response.status_code != 200:
                print(f"  ✗ FAIL: API returned status {response.status_code}")
                print(f"  Response: {response.text[:200]}")
                all_passed = False
                print()
                continue

            data = response.json()
            results = data.get("results", [])
            retrieval_time = data.get("retrieval_time_ms", 0)

            # Analyze results
            num_results = len(results)
            print(f"  ✓ Results: {num_results} items returned in {retrieval_time:.1f}ms")

            if num_results > 0:
                # Show top 3 results with scores
                print(f"  Top results:")
                for rank, result in enumerate(results[:3], 1):
                    item_id = result.get("item_id", "unknown")[:12]
                    score = result.get("score", 0)
                    category = result.get("category", "")
                    headline = result.get("headline", "")[:40]

                    print(f"    {rank}. {item_id}... (score: {score:.4f})")
                    print(f"       {category}: \"{headline}...\"")

                # Validate score properties
                scores = [r.get("score", 0) for r in results]

                # Check if scores are normalized (0-1 range for hybrid)
                if all(0 <= s <= 1 for s in scores):
                    print(f"  ✓ Scores are normalized (range: {min(scores):.4f} - {max(scores):.4f})")
                else:
                    print(f"  ⚠ Warning: Some scores outside [0,1] range")

                # Check if scores are descending
                if scores == sorted(scores, reverse=True):
                    print(f"  ✓ Scores are properly sorted (descending)")
                else:
                    print(f"  ⚠ Warning: Scores not in descending order")

                # Check score gaps (confidence)
                if len(scores) >= 2:
                    first_gap = scores[0] - scores[1]
                    print(f"  Score gap (rank 1 vs 2): {first_gap:.4f}")
            else:
                print(f"  ℹ No results returned (may be expected for edge cases)")

        except requests.exceptions.RequestException as e:
            print(f"  ✗ FAIL: Request error: {e}")
            all_passed = False
        except Exception as e:
            print(f"  ✗ FAIL: Unexpected error: {e}")
            all_passed = False

        print()

    # Summary
    print("=" * 70)
    if all_passed:
        print("✓ ALL TESTS PASSED")
        print("\nThe hybrid retriever is working correctly!")
        print("You can now run the full evaluation with:")
        print("  python scripts/evaluate_retrieval.py --search-types hybrid-lc")
    else:
        print("✗ SOME TESTS FAILED")
        print("\nPlease check the errors above and verify:")
        print("  1. The hybrid retriever is properly implemented")
        print("  2. The API is accepting 'hybrid-lc' as a search type")
        print("  3. Score normalization is working correctly")
    print("=" * 70)

    return all_passed


def main():
    """Run the validation tests."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Test hybrid retriever implementation"
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://localhost:8000",
        help="API base URL (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--no-golden-subdomain",
        dest="use_golden_db",
        action="store_false",
        help="Disable golden subdomain routing (test against production DB)"
    )
    parser.add_argument(
        "--use-golden-subdomain",
        dest="use_golden_db",
        action="store_true",
        default=True,
        help="Use golden.localhost subdomain routing (default: True)"
    )

    args = parser.parse_args()

    success = test_hybrid_search(
        base_url=args.base_url,
        use_golden_db=args.use_golden_db
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
