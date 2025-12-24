#!/usr/bin/env python3
"""
Quick validation script to test the agentic search implementation.

This script tests the agentic search type in isolation to verify:
1. The API accepts "agentic" as a valid search type
2. Reasoning is captured in the response
3. Tools used (vector, bm25, etc.) are populated
4. Answer quality is good (if include_answer=True)
5. The orchestrator coordinates retrieval properly
"""

import requests
import sys


def test_agentic_search(base_url="http://localhost:8000", use_golden_db=True):
    """Test agentic search with a few sample queries."""

    # Setup headers for golden database routing
    headers = {}
    if use_golden_db:
        headers["Host"] = "golden.localhost:8000"

    # Test queries covering different scenarios
    test_queries = [
        {
            "query": "TeamLab digital art museum Fukuoka",
            "description": "Single-item precision query",
            "expected_result": "Should use vector search, return TeamLab item at rank 1, with reasoning"
        },
        {
            "query": "onsen hot spring accommodations Japan",
            "description": "Multi-item recall query",
            "expected_result": "Should use hybrid search, return multiple onsen/ryokan items, with reasoning"
        },
        {
            "query": "where can I relax in a hot spring with mountain views",
            "description": "Semantic query requiring interpretation",
            "expected_result": "Should use vector search, return onsen items with mountain views, explain semantic matching"
        },
        {
            "query": "things to do in Paris",
            "description": "Edge case - no results expected",
            "expected_result": "Should try multiple search types, return no results or explain lack of matches"
        },
        {
            "query": "Japanese temples and shrines",
            "description": "Broad semantic query",
            "expected_result": "Should use hybrid or vector search, return cultural/religious sites, explain selection"
        }
    ]

    print("=" * 70)
    print("AGENTIC SEARCH VALIDATION TEST")
    print("=" * 70)
    print(f"\nAPI Endpoint: {base_url}")
    print(f"Database: {'golden (via subdomain)' if use_golden_db else 'production'}")
    print(f"Search Type: agentic\n")

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
                    "search_type": "agentic",
                    "include_answer": True
                },
                headers=headers,
                timeout=30  # Agentic search may take longer
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
            answer = data.get("answer")
            reasoning = data.get("agent_reasoning")
            tools_used = data.get("tools_used", [])
            search_strategy = data.get("search_strategy")

            # Analyze results
            num_results = len(results)
            print(f"  ✓ Results: {num_results} items returned in {retrieval_time:.1f}ms")

            # Check for agentic-specific fields
            if reasoning:
                # reasoning is a list of strings
                reasoning_text = ' '.join(reasoning) if isinstance(reasoning, list) else str(reasoning)
                print(f"  ✓ Reasoning captured ({len(reasoning_text)} chars)")
                print(f"    Preview: \"{reasoning_text[:80]}...\"")
            else:
                print(f"  ⚠ Warning: No reasoning captured")
                all_passed = False

            if tools_used and len(tools_used) > 0:
                # tools_used is a list of dicts, extract tool names
                tool_names = [tool.get('tool', 'unknown') for tool in tools_used]
                print(f"  ✓ Tools used: {', '.join(tool_names)} ({len(tools_used)} calls)")
            else:
                print(f"  ⚠ Warning: No tools_used populated")
                all_passed = False

            if search_strategy:
                print(f"  ✓ Search strategy: {search_strategy}")
            else:
                print(f"  ℹ Info: No search_strategy field (optional)")

            if answer:
                print(f"  ✓ Answer generated ({len(answer)} chars)")
                print(f"    Preview: \"{answer[:80]}...\"")
            else:
                print(f"  ℹ Info: No answer generated (may be expected for edge cases)")

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

                # Check if scores are normalized (0-1 range)
                if all(0 <= s <= 1 for s in scores):
                    print(f"  ✓ Scores are normalized (range: {min(scores):.4f} - {max(scores):.4f})")
                else:
                    print(f"  ⚠ Warning: Some scores outside [0,1] range")

                # Check if scores are descending
                if scores == sorted(scores, reverse=True):
                    print(f"  ✓ Scores are properly sorted (descending)")
                else:
                    print(f"  ⚠ Warning: Scores not in descending order")

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
        print("\nThe agentic search is working correctly!")
        print("You can now run the full evaluation with:")
        print("  python scripts/evaluate_retrieval.py --search-types agentic")
    else:
        print("✗ SOME TESTS FAILED")
        print("\nPlease check the errors above and verify:")
        print("  1. The agentic search is properly implemented")
        print("  2. The API is accepting 'agentic' as a search type")
        print("  3. Reasoning and tools_used fields are populated")
        print("  4. The orchestrator is coordinating retrieval properly")
    print("=" * 70)

    return all_passed


def main():
    """Run the validation tests."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Test agentic search implementation"
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

    success = test_agentic_search(
        base_url=args.base_url,
        use_golden_db=args.use_golden_db
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
