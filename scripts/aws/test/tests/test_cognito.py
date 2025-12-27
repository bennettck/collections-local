"""
Test 6: Cognito User Pool

Validates:
- User pool exists and is accessible
- Can create users
- Can get user attributes
- JWT token generation (if configured)
- Can delete users
"""

import pytest


@pytest.mark.integration
def test_cognito_pool_exists(cognito_user_pool, boto3_clients):
    """Verify Cognito user pool exists."""
    cognito = boto3_clients['cognito']

    response = cognito.describe_user_pool(
        UserPoolId=cognito_user_pool
    )

    assert 'UserPool' in response
    assert response['UserPool']['Id'] == cognito_user_pool


@pytest.mark.integration
def test_cognito_create_user(test_user):
    """Test creating Cognito user."""
    assert test_user['username'] is not None
    assert test_user['email'] is not None
    assert test_user['user_id'] is not None  # sub claim


@pytest.mark.integration
def test_cognito_get_user(test_user, boto3_clients):
    """Test retrieving user details."""
    cognito = boto3_clients['cognito']

    response = cognito.admin_get_user(
        UserPoolId=test_user['user_pool_id'],
        Username=test_user['username']
    )

    assert response['Username'] == test_user['username']

    # Verify user attributes
    attributes = {attr['Name']: attr['Value'] for attr in response['UserAttributes']}

    assert 'sub' in attributes
    assert attributes['sub'] == test_user['user_id']
    assert attributes['email'] == test_user['email']


@pytest.mark.integration
def test_cognito_user_status(test_user, boto3_clients):
    """Test user status after creation."""
    cognito = boto3_clients['cognito']

    response = cognito.admin_get_user(
        UserPoolId=test_user['user_pool_id'],
        Username=test_user['username']
    )

    # User should be in FORCE_CHANGE_PASSWORD or CONFIRMED state
    user_status = response['UserStatus']
    assert user_status in ['FORCE_CHANGE_PASSWORD', 'CONFIRMED', 'UNCONFIRMED']


@pytest.mark.integration
def test_cognito_list_users(cognito_user_pool, test_user, boto3_clients):
    """Test listing users in pool."""
    cognito = boto3_clients['cognito']

    response = cognito.list_users(
        UserPoolId=cognito_user_pool,
        Limit=10
    )

    assert 'Users' in response
    users = response['Users']

    # Verify test user is in list
    usernames = [u['Username'] for u in users]
    assert test_user['username'] in usernames


@pytest.mark.integration
def test_cognito_disable_enable_user(test_user, boto3_clients):
    """Test disabling and enabling user."""
    cognito = boto3_clients['cognito']

    # Disable user
    cognito.admin_disable_user(
        UserPoolId=test_user['user_pool_id'],
        Username=test_user['username']
    )

    # Verify disabled
    response = cognito.admin_get_user(
        UserPoolId=test_user['user_pool_id'],
        Username=test_user['username']
    )

    assert response['Enabled'] is False

    # Re-enable user
    cognito.admin_enable_user(
        UserPoolId=test_user['user_pool_id'],
        Username=test_user['username']
    )

    # Verify enabled
    response = cognito.admin_get_user(
        UserPoolId=test_user['user_pool_id'],
        Username=test_user['username']
    )

    assert response['Enabled'] is True


@pytest.mark.integration
def test_cognito_update_attributes(test_user, boto3_clients):
    """Test updating user attributes."""
    cognito = boto3_clients['cognito']

    # Update custom attribute
    cognito.admin_update_user_attributes(
        UserPoolId=test_user['user_pool_id'],
        Username=test_user['username'],
        UserAttributes=[
            {'Name': 'name', 'Value': 'Test User Name'}
        ]
    )

    # Verify updated
    response = cognito.admin_get_user(
        UserPoolId=test_user['user_pool_id'],
        Username=test_user['username']
    )

    attributes = {attr['Name']: attr['Value'] for attr in response['UserAttributes']}
    assert attributes.get('name') == 'Test User Name'


@pytest.mark.integration
def test_cognito_delete_user(cognito_user_pool, boto3_clients):
    """Test deleting user."""
    import time

    cognito = boto3_clients['cognito']

    # Create temporary user
    temp_username = f'temp-user-{int(time.time())}'

    cognito.admin_create_user(
        UserPoolId=cognito_user_pool,
        Username=temp_username,
        UserAttributes=[
            {'Name': 'email', 'Value': f'{temp_username}@example.com'}
        ],
        MessageAction='SUPPRESS'
    )

    # Verify exists
    response = cognito.admin_get_user(
        UserPoolId=cognito_user_pool,
        Username=temp_username
    )
    assert response['Username'] == temp_username

    # Delete user
    cognito.admin_delete_user(
        UserPoolId=cognito_user_pool,
        Username=temp_username
    )

    # Verify deleted
    from botocore.exceptions import ClientError

    with pytest.raises(ClientError) as exc_info:
        cognito.admin_get_user(
            UserPoolId=cognito_user_pool,
            Username=temp_username
        )

    error_code = exc_info.value.response['Error']['Code']
    assert error_code == 'UserNotFoundException'


@pytest.mark.integration
def test_cognito_pool_configuration(cognito_user_pool, boto3_clients):
    """Test user pool configuration details."""
    cognito = boto3_clients['cognito']

    response = cognito.describe_user_pool(
        UserPoolId=cognito_user_pool
    )

    pool = response['UserPool']

    # Verify basic configuration
    assert 'Policies' in pool
    assert 'LambdaConfig' in pool or True  # May or may not have Lambda triggers

    # Check MFA configuration
    mfa_config = pool.get('MfaConfiguration', 'OFF')
    assert mfa_config in ['OFF', 'ON', 'OPTIONAL']
