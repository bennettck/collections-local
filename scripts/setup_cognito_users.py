#!/usr/bin/env python3
"""
Setup Cognito Test Users

Creates and configures test users in the Cognito User Pool with permanent passwords.
This script ensures that users created with admin_create_user have their passwords
properly set so they can authenticate via USER_PASSWORD_AUTH.

Usage:
    python scripts/setup_cognito_users.py
    python scripts/setup_cognito_users.py --env dev
    python scripts/setup_cognito_users.py --user-pool-id us-east-1_XXXXXXXXX
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

import boto3
from botocore.exceptions import ClientError


# Test users configuration
TEST_USERS = [
    {
        "email": "testuser1@example.com",
        "password": "Collections2025!",
        "attributes": {
            "email_verified": "true",
            "name": "Test User 1"
        }
    },
    {
        "email": "testuser2@example.com",
        "password": "Collections2025!",
        "attributes": {
            "email_verified": "true",
            "name": "Test User 2"
        }
    },
    {
        "email": "demo@example.com",
        "password": "Collections2025!",
        "attributes": {
            "email_verified": "true",
            "name": "Demo User"
        }
    }
]


def load_stack_outputs(env: str) -> Dict:
    """
    Load CDK stack outputs from JSON file.

    Args:
        env: Environment name (dev, test, prod)

    Returns:
        Dictionary of stack outputs (OutputKey -> OutputValue)
    """
    project_root = Path(__file__).parent.parent
    outputs_file = project_root / f'.aws-outputs-{env}.json'

    if not outputs_file.exists():
        print(f"Error: CDK outputs not found: {outputs_file}")
        print("Run 'make infra-outputs' first to generate outputs file")
        sys.exit(1)

    with open(outputs_file) as f:
        outputs_list = json.load(f)

    # Convert list of output dicts to simple key-value dict
    if isinstance(outputs_list, list):
        return {item['OutputKey']: item['OutputValue'] for item in outputs_list}

    # If it's already a dict, return as-is
    return outputs_list


def get_user_pool_id(args) -> str:
    """Get User Pool ID from args or stack outputs."""
    if args.user_pool_id:
        return args.user_pool_id

    outputs = load_stack_outputs(args.env)

    # Try both possible key names
    user_pool_id = outputs.get('UserPoolId') or outputs.get('CognitoUserPoolId')

    if not user_pool_id:
        print("Error: UserPoolId not found in stack outputs")
        print(f"Available keys: {list(outputs.keys())}")
        sys.exit(1)

    return user_pool_id


def user_exists(cognito, user_pool_id: str, username: str) -> bool:
    """
    Check if user exists in the pool.

    Args:
        cognito: Boto3 Cognito client
        user_pool_id: User Pool ID
        username: Username/email to check

    Returns:
        True if user exists, False otherwise
    """
    try:
        cognito.admin_get_user(
            UserPoolId=user_pool_id,
            Username=username
        )
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'UserNotFoundException':
            return False
        raise


def create_or_update_user(
    cognito,
    user_pool_id: str,
    user_config: Dict,
    dry_run: bool = False
) -> Dict:
    """
    Create or update a Cognito user with permanent password.

    Args:
        cognito: Boto3 Cognito client
        user_pool_id: User Pool ID
        user_config: User configuration dict
        dry_run: If True, only show what would be done

    Returns:
        Dictionary with user details
    """
    email = user_config['email']
    password = user_config['password']
    attributes = user_config.get('attributes', {})

    # Build user attributes list
    user_attributes = [
        {'Name': 'email', 'Value': email}
    ]

    for key, value in attributes.items():
        user_attributes.append({'Name': key, 'Value': value})

    exists = user_exists(cognito, user_pool_id, email)

    if dry_run:
        if exists:
            print(f"  [DRY RUN] Would update password for: {email}")
        else:
            print(f"  [DRY RUN] Would create user: {email}")
        return {'email': email, 'action': 'dry_run'}

    # Create user if doesn't exist
    if not exists:
        print(f"  Creating user: {email}")
        try:
            response = cognito.admin_create_user(
                UserPoolId=user_pool_id,
                Username=email,
                UserAttributes=user_attributes,
                MessageAction='SUPPRESS'  # Don't send welcome email
            )

            # Extract user_id (sub claim)
            user_id = None
            for attr in response['User']['Attributes']:
                if attr['Name'] == 'sub':
                    user_id = attr['Value']
                    break

            print(f"    ✓ Created with user_id: {user_id}")
        except ClientError as e:
            print(f"    ✗ Error creating user: {e}")
            return {'email': email, 'action': 'error', 'error': str(e)}
    else:
        print(f"  User exists: {email}")

        # Get current user details
        response = cognito.admin_get_user(
            UserPoolId=user_pool_id,
            Username=email
        )

        user_id = None
        for attr in response['UserAttributes']:
            if attr['Name'] == 'sub':
                user_id = attr['Value']
                break

    # Set permanent password
    print(f"  Setting permanent password...")
    try:
        cognito.admin_set_user_password(
            UserPoolId=user_pool_id,
            Username=email,
            Password=password,
            Permanent=True
        )
        print(f"    ✓ Password set successfully")

        return {
            'email': email,
            'user_id': user_id,
            'action': 'created' if not exists else 'updated'
        }
    except ClientError as e:
        print(f"    ✗ Error setting password: {e}")
        return {'email': email, 'action': 'error', 'error': str(e)}


def list_users(cognito, user_pool_id: str) -> List[Dict]:
    """
    List all users in the pool.

    Args:
        cognito: Boto3 Cognito client
        user_pool_id: User Pool ID

    Returns:
        List of user dictionaries
    """
    users = []
    paginator = cognito.get_paginator('list_users')

    for page in paginator.paginate(UserPoolId=user_pool_id):
        for user in page['Users']:
            user_dict = {
                'username': user['Username'],
                'status': user['UserStatus'],
                'enabled': user['Enabled'],
                'created': user['UserCreateDate'].isoformat(),
            }

            # Extract attributes
            for attr in user.get('Attributes', []):
                if attr['Name'] in ['email', 'sub', 'email_verified']:
                    user_dict[attr['Name']] = attr['Value']

            users.append(user_dict)

    return users


def main():
    parser = argparse.ArgumentParser(
        description='Setup Cognito test users with permanent passwords'
    )
    parser.add_argument(
        '--env',
        default='dev',
        choices=['dev', 'test', 'prod'],
        help='Environment name (default: dev)'
    )
    parser.add_argument(
        '--user-pool-id',
        help='Cognito User Pool ID (overrides env lookup)'
    )
    parser.add_argument(
        '--region',
        default='us-east-1',
        help='AWS region (default: us-east-1)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List all users in the pool and exit'
    )

    args = parser.parse_args()

    # Get User Pool ID
    user_pool_id = get_user_pool_id(args)

    # Initialize Cognito client
    cognito = boto3.client('cognito-idp', region_name=args.region)

    print("=" * 80)
    print("Cognito User Setup")
    print("=" * 80)
    print(f"Environment:   {args.env}")
    print(f"User Pool ID:  {user_pool_id}")
    print(f"Region:        {args.region}")
    print(f"Mode:          {'DRY RUN' if args.dry_run else 'EXECUTE'}")
    print("=" * 80)
    print()

    # List mode
    if args.list:
        print("Current users in pool:")
        print("-" * 80)
        users = list_users(cognito, user_pool_id)

        for user in users:
            print(f"  Email:    {user.get('email', 'N/A')}")
            print(f"  User ID:  {user.get('sub', 'N/A')}")
            print(f"  Status:   {user['status']}")
            print(f"  Enabled:  {user['enabled']}")
            print(f"  Created:  {user['created']}")
            print()

        print(f"Total users: {len(users)}")
        return

    # Setup users
    print(f"Setting up {len(TEST_USERS)} test users...")
    print()

    results = []
    for user_config in TEST_USERS:
        result = create_or_update_user(
            cognito,
            user_pool_id,
            user_config,
            dry_run=args.dry_run
        )
        results.append(result)
        print()

    # Summary
    print("=" * 80)
    print("Summary")
    print("=" * 80)

    created = sum(1 for r in results if r.get('action') == 'created')
    updated = sum(1 for r in results if r.get('action') == 'updated')
    errors = sum(1 for r in results if r.get('action') == 'error')

    print(f"Created:  {created}")
    print(f"Updated:  {updated}")
    print(f"Errors:   {errors}")
    print()

    if not args.dry_run and errors == 0:
        print("✓ All test users configured successfully!")
        print()
        print("Test credentials:")
        for user_config in TEST_USERS:
            print(f"  Email:    {user_config['email']}")
            print(f"  Password: {user_config['password']}")
            print()

    if errors > 0:
        print("✗ Some users failed to configure. Check errors above.")
        sys.exit(1)


if __name__ == '__main__':
    main()
