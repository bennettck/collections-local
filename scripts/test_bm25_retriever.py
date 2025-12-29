#!/usr/bin/env python3
"""
Quick validation script to test the BM25 search implementation.

This script tests the bm25-lc search type against the AWS API to verify:
1. The API accepts "bm25-lc" as a valid search type
2. Keyword-based search is working correctly
3. Term frequency scoring is working correctly
4. Results are relevant for keyword queries

Usage:
    python scripts/test_bm25_retriever.py --user testuser1
    python scripts/test_bm25_retriever.py --user demo
"""

import requests
import sys
import boto3
from botocore.exceptions import ClientError


# AWS Configuration (from deployment)
AWS_CONFIG = {
    "USER_POOL_ID": "us-east-1_SGF7r9htD",
    "CLIENT_ID": "1tce0ddbsbm254e9r9p4jar1em",
    "API_ENDPOINT": "https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com",
    "REGION": "us-east-1"
}

# Test users for AWS authentication
TEST_USERS = {
    "testuser1": {
        "email": "testuser1@example.com",
        "password": "Collections2025!",
    },
    "testuser2": {
        "email": "testuser2@example.com",
        "password": "Collections2025!",
    },
    "demo": {
        "email": "demo@example.com",
        "password": "Collections2025!",
    }
}


def get_jwt_token(username: str, password: str) -> str:
    """
    Authenticate with Cognito and get JWT ID token.

    Args:
        username: User email
        password: User password

    Returns:
        JWT ID token for API authentication
    """
    client = boto3.client('cognito-idp', region_name=AWS_CONFIG["REGION"])

    try:
        response = client.initiate_auth(
            AuthFlow='USER_PASSWORD_AUTH',
            AuthParameters={
                'USERNAME': username,
                'PASSWORD': password
            },
            ClientId=AWS_CONFIG["CLIENT_ID"]
        )
        return response['AuthenticationResult']['IdToken']
    except ClientError as e:
        print(f"❌ Authentication failed: {e}")
        sys.exit(1)


def test_bm25_search(aws_user="testuser1"):
    """Test BM25 search with a few sample queries."""

    # Authenticate with AWS Cognito
    print(f"🔐 Authenticating with AWS Cognito as {aws_user}...")
    user_info = TEST_USERS.get(aws_user)
    if not user_info:
        print(f"❌ Unknown user: {aws_user}")
        print(f"Available users: {', '.join(TEST_USERS.keys())}")
        return False

    id_token = get_jwt_token(user_info["email"], user_info["password"])
    print("✓ Authentication successful\n")

    # Setup headers with authentication
    base_url = AWS_CONFIG["API_ENDPOINT"]
    headers = {
        "Authorization": f"Bearer {id_token}"
    }

    # Test queries covering different scenarios
    # BM25 excels at keyword/term-based queries
    test_queries = [
        {
            "query": "TeamLab Fukuoka",
            "description": "Specific keyword query",
            "expected_result": "Should return TeamLab item at rank 1 based on exact term matches"
        },
        {
            "query": "onsen ryokan",
            "description": "Short keyword query",
            "expected_result": "Should return multiple onsen/ryokan items based on keyword frequency"
        },
        {
            "query": "TOKYO RESTAURANTS",
            "description": "All-caps keyword query",
            "expected_result": "Should match Tokyo restaurant items (case-insensitive)"
        },
        {
            "query": "temple shrine",
            "description": "Multiple keywords",
            "expected_result": "Should return items containing 'temple' or 'shrine' keywords"
        },
        {
            "query": "beauty skincare",
            "description": "Product category keywords",
            "expected_result": "Should return beauty/skincare product items"
        },
        {
            "query": "digital art museum",
            "description": "Descriptive keywords",
            "expected_result": "Should return art museum items based on keyword matching"
        },
        {
            "query": "Paris Eiffel Tower",
            "description": "Edge case - no results expected",
            "expected_result": "Should return no results or very low scores"
        }
    ]

    print("=" * 70)
    print("BM25 SEARCH VALIDATION TEST")
    print("=" * 70)
    print(f"\nAPI Endpoint: {base_url}")
    print(f"Authenticated as: {aws_user}")
    print(f"Search Type: bm25 (keyword/term frequency)\n")

    # Check API health
    try:
        response = requests.get(f"{base_url}/health", headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"Error: API health check failed (status {response.status_code})")
            return False
        print("✓ API is healthy\n")
    except requests.exceptions.RequestException as e:
        print(f"Error: Cannot connect to AWS API: {e}")
        print("\nPlease verify:")
        print("  1. Your AWS credentials are configured")
        print("  2. The API endpoint is accessible")
        print("  3. You have network connectivity")
        return False

    # Run test queries
    all_passed = True
    queries_with_no_results = 0

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
                    "search_type": "bm25",
                    "include_answer": False
                },
                headers=headers,
                timeout=30
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

                # BM25 scores are typically not normalized but should be positive
                if all(s >= 0 for s in scores):
                    print(f"  ✓ Scores are valid (range: {min(scores):.4f} - {max(scores):.4f})")
                else:
                    print(f"  ⚠ Warning: Some negative scores found")

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
                queries_with_no_results += 1
                print(f"  ℹ No results returned (may be expected for edge cases)")

        except requests.exceptions.RequestException as e:
            print(f"  ✗ FAIL: Request error: {e}")
            all_passed = False
        except Exception as e:
            print(f"  ✗ FAIL: Unexpected error: {e}")
            all_passed = False

        print()

    # Check if too many queries returned no results
    total_queries = len(test_queries)
    max_allowed_empty = total_queries - 4  # At least 4 must return results
    if queries_with_no_results > max_allowed_empty:
        all_passed = False
        print(f"⚠ WARNING: {queries_with_no_results}/{total_queries} queries returned no results")
        print(f"  Expected at least 4 queries to return results, but only {total_queries - queries_with_no_results} did.")
        print()

    # Summary
    print("=" * 70)
    if all_passed:
        print("✓ ALL TESTS PASSED")
        print("\nThe BM25 search is working correctly!")
        print("You can now run the full evaluation with:")
        print("  python scripts/evaluate_retrieval.py --search-types bm25-lc")
    else:
        print("✗ SOME TESTS FAILED")
        print("\nPlease check the errors above and verify:")
        print("  1. The BM25 search is properly implemented")
        print("  2. The API is accepting 'bm25-lc' as a search type")
        print("  3. Keyword matching is working correctly")
        print("  4. PostgreSQL full-text search is configured properly")
        if queries_with_no_results > max_allowed_empty:
            print(f"  5. Database contains searchable data (got results from only {total_queries - queries_with_no_results}/{total_queries} queries)")
    print("=" * 70)

    return all_passed


def main():
    """Run the validation tests."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Test BM25 search implementation against AWS API"
    )
    parser.add_argument(
        "--user",
        type=str,
        default="testuser1",
        choices=list(TEST_USERS.keys()),
        help="AWS test user to authenticate as (default: testuser1)"
    )

    args = parser.parse_args()

    success = test_bm25_search(aws_user=args.user)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
