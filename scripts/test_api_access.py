#!/usr/bin/env python3
"""
Test API Access Script
Authenticates with Cognito and tests the Collections API
"""

import json
import sys
import argparse
import boto3
import requests
from botocore.exceptions import ClientError


# Configuration from AWS deployment
USER_POOL_ID = "us-east-1_SGF7r9htD"
CLIENT_ID = "1tce0ddbsbm254e9r9p4jar1em"
API_ENDPOINT = "https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com"
REGION = "us-east-1"

# Test users
TEST_USERS = {
    "testuser1": {
        "email": "testuser1@example.com",
        "password": "Collections2025!",
        "user_id": "94c844d8-10c1-70dd-80e3-4a88742efbb6"
    },
    "testuser2": {
        "email": "testuser2@example.com",
        "password": "Collections2025!",
        "user_id": "7478e4c8-f0b1-70d3-6396-5754bc95ca9e"
    },
    "demo": {
        "email": "demo@example.com",
        "password": "Collections2025!",
        "user_id": "84e84488-a071-70bc-8ed0-d048d2fb193c"
    }
}


def get_jwt_token(username: str, password: str) -> dict:
    """
    Authenticate with Cognito and get JWT tokens

    Args:
        username: User email
        password: User password

    Returns:
        dict: Authentication result with tokens
    """
    client = boto3.client('cognito-idp', region_name=REGION)

    try:
        response = client.initiate_auth(
            AuthFlow='USER_PASSWORD_AUTH',
            AuthParameters={
                'USERNAME': username,
                'PASSWORD': password
            },
            ClientId=CLIENT_ID
        )

        return response['AuthenticationResult']
    except ClientError as e:
        print(f"Error authenticating: {e}")
        sys.exit(1)


def test_api_endpoint(id_token: str, endpoint: str, method: str = 'GET', data: dict = None):
    """
    Test an API endpoint with authentication

    Args:
        id_token: JWT ID token
        endpoint: API endpoint path (e.g., '/items')
        method: HTTP method (GET, POST, PUT, DELETE)
        data: Optional request body for POST/PUT

    Returns:
        Response object
    """
    url = f"{API_ENDPOINT}{endpoint}"
    headers = {
        'Authorization': f'Bearer {id_token}',
        'Content-Type': 'application/json'
    }

    try:
        if method == 'GET':
            response = requests.get(url, headers=headers)
        elif method == 'POST':
            response = requests.post(url, headers=headers, json=data)
        elif method == 'PUT':
            response = requests.put(url, headers=headers, json=data)
        elif method == 'DELETE':
            response = requests.delete(url, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        return response
    except requests.exceptions.RequestException as e:
        print(f"Error making API request: {e}")
        sys.exit(1)


def print_token_info(tokens: dict):
    """Print token information"""
    print("\n" + "="*80)
    print("AUTHENTICATION SUCCESSFUL")
    print("="*80)
    print(f"\nID Token (use for API calls):")
    print(f"{tokens['IdToken'][:50]}...{tokens['IdToken'][-50:]}")
    print(f"\nAccess Token:")
    print(f"{tokens['AccessToken'][:50]}...{tokens['AccessToken'][-50:]}")
    print(f"\nToken Type: {tokens['TokenType']}")
    print(f"Expires In: {tokens['ExpiresIn']} seconds")
    print("="*80 + "\n")


def run_basic_tests(id_token: str):
    """Run basic API tests"""
    print("\n" + "="*80)
    print("RUNNING API TESTS")
    print("="*80 + "\n")

    # Test 1: List items
    print("Test 1: GET /items")
    response = test_api_endpoint(id_token, '/items')
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text[:200]}")
    print()

    # Test 2: Health check or root endpoint
    print("Test 2: GET /")
    response = test_api_endpoint(id_token, '/')
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text[:200]}")
    print()

    # Test 3: Try chat sessions (if available)
    print("Test 3: GET /chat/sessions")
    response = test_api_endpoint(id_token, '/chat/sessions')
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text[:200]}")
    print()

    print("="*80 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description='Test Collections API access with Cognito authentication'
    )
    parser.add_argument(
        '--user',
        choices=list(TEST_USERS.keys()),
        default='testuser1',
        help='Test user to authenticate as'
    )
    parser.add_argument(
        '--custom-email',
        help='Custom email to authenticate with'
    )
    parser.add_argument(
        '--custom-password',
        help='Custom password (required with --custom-email)'
    )
    parser.add_argument(
        '--token-only',
        action='store_true',
        help='Only get and display the JWT token, skip API tests'
    )
    parser.add_argument(
        '--test-endpoint',
        help='Test a specific endpoint (e.g., /items, /chat/sessions)'
    )

    args = parser.parse_args()

    # Determine credentials
    if args.custom_email:
        if not args.custom_password:
            print("Error: --custom-password is required when using --custom-email")
            sys.exit(1)
        username = args.custom_email
        password = args.custom_password
    else:
        user_info = TEST_USERS[args.user]
        username = user_info['email']
        password = user_info['password']

    print(f"\nAuthenticating as: {username}")

    # Get JWT token
    tokens = get_jwt_token(username, password)
    id_token = tokens['IdToken']

    # Print token info
    print_token_info(tokens)

    # Save tokens to file for convenience
    with open('.api-tokens.json', 'w') as f:
        json.dump(tokens, f, indent=2)
    print(f"Tokens saved to: .api-tokens.json\n")

    if args.token_only:
        print("Token-only mode. Use the ID token above for API requests.")
        return

    # Run tests
    if args.test_endpoint:
        print(f"Testing endpoint: {args.test_endpoint}")
        response = test_api_endpoint(id_token, args.test_endpoint)
        print(f"Status: {response.status_code}")
        print(f"Headers: {dict(response.headers)}")
        print(f"Body: {response.text}")
    else:
        run_basic_tests(id_token)

    print("\nAPI testing complete!")
    print("Your JWT token is valid for 1 hour.")
    print("To make manual API calls, use:")
    print(f'  curl -H "Authorization: Bearer $(cat .api-tokens.json | jq -r .IdToken)" {API_ENDPOINT}/items')


if __name__ == '__main__':
    main()
