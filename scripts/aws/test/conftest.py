"""
Pytest fixtures for AWS infrastructure testing.

Provides reusable test fixtures for:
- AWS credentials
- Stack outputs
- boto3 clients
- Cleanup handlers
"""

import pytest
import boto3
import json
import os
from pathlib import Path
from typing import Dict, Any


@pytest.fixture(scope="session")
def aws_region() -> str:
    """
    Get AWS region from environment or default.

    Returns:
        AWS region name
    """
    return os.getenv('AWS_REGION', 'us-east-1')


@pytest.fixture(scope="session")
def env_name() -> str:
    """
    Get environment name from environment or default.

    Returns:
        Environment name (dev, test, prod)
    """
    return os.getenv('CDK_ENV', 'dev')


@pytest.fixture(scope="session")
def stack_outputs(env_name) -> Dict[str, Any]:
    """
    Load CDK stack outputs from JSON file.

    Args:
        env_name: Environment name fixture

    Returns:
        Dictionary of stack outputs

    Raises:
        FileNotFoundError: If outputs file doesn't exist
    """
    # Look for outputs file in project root (3 levels up from scripts/aws/test)
    project_root = Path(__file__).parent.parent.parent.parent
    outputs_file = project_root / f'.aws-outputs-{env_name}.json'

    if not outputs_file.exists():
        pytest.skip(f"CDK outputs not found: {outputs_file}")

    with open(outputs_file) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def boto3_clients(aws_region) -> Dict[str, Any]:
    """
    Initialize all boto3 clients.

    Args:
        aws_region: AWS region fixture

    Returns:
        Dictionary of boto3 client instances
    """
    return {
        'rds': boto3.client('rds', region_name=aws_region),
        'dynamodb': boto3.resource('dynamodb', region_name=aws_region),
        'dynamodb_client': boto3.client('dynamodb', region_name=aws_region),
        'ssm': boto3.client('ssm', region_name=aws_region),
        'cognito': boto3.client('cognito-idp', region_name=aws_region),
        's3': boto3.client('s3', region_name=aws_region),
        'lambda': boto3.client('lambda', region_name=aws_region),
        'apigateway': boto3.client('apigatewayv2', region_name=aws_region),
        'events': boto3.client('events', region_name=aws_region),
        'logs': boto3.client('logs', region_name=aws_region),
    }


@pytest.fixture(scope="function")
def rds_connection(stack_outputs):
    """
    Provide PostgreSQL database connection.

    Yields:
        psycopg2 connection object

    Cleanup:
        Closes connection after test
    """
    import psycopg2

    rds_endpoint = stack_outputs.get('RdsEndpoint')
    db_name = stack_outputs.get('DatabaseName', 'collections')
    username = stack_outputs.get('RdsUsername', 'postgres')
    password = stack_outputs.get('RdsPassword')

    if not all([rds_endpoint, password]):
        pytest.skip("Database credentials not available")

    conn = psycopg2.connect(
        host=rds_endpoint,
        database=db_name,
        user=username,
        password=password,
        sslmode='require'
    )

    yield conn

    conn.close()


@pytest.fixture(scope="function")
def dynamodb_table(stack_outputs, boto3_clients):
    """
    Provide DynamoDB table resource.

    Yields:
        boto3 Table resource
    """
    table_name = stack_outputs.get('CheckpointTableName')

    if not table_name:
        pytest.skip("CheckpointTableName not in outputs")

    dynamodb = boto3_clients['dynamodb']
    table = dynamodb.Table(table_name)

    yield table


@pytest.fixture(scope="function")
def s3_bucket(stack_outputs):
    """
    Provide S3 bucket name.

    Returns:
        Bucket name string
    """
    bucket_name = stack_outputs.get('BucketName')

    if not bucket_name:
        pytest.skip("BucketName not in outputs")

    return bucket_name


@pytest.fixture(scope="function")
def cognito_user_pool(stack_outputs):
    """
    Provide Cognito User Pool ID.

    Returns:
        User Pool ID string
    """
    user_pool_id = stack_outputs.get('CognitoUserPoolId')

    if not user_pool_id:
        pytest.skip("CognitoUserPoolId not in outputs")

    return user_pool_id


@pytest.fixture(scope="function")
def test_user(cognito_user_pool, boto3_clients):
    """
    Create and cleanup test Cognito user.

    Yields:
        Dictionary with user credentials and attributes

    Cleanup:
        Deletes user after test
    """
    import time

    cognito = boto3_clients['cognito']
    timestamp = int(time.time())
    username = f'test-user-{timestamp}'
    email = f'{username}@example.com'

    # Create user
    response = cognito.admin_create_user(
        UserPoolId=cognito_user_pool,
        Username=username,
        UserAttributes=[
            {'Name': 'email', 'Value': email},
            {'Name': 'email_verified', 'Value': 'true'}
        ],
        MessageAction='SUPPRESS'
    )

    # Extract user_id (sub claim)
    user_id = None
    for attr in response['User']['Attributes']:
        if attr['Name'] == 'sub':
            user_id = attr['Value']
            break

    user_info = {
        'username': username,
        'email': email,
        'user_id': user_id,
        'user_pool_id': cognito_user_pool
    }

    yield user_info

    # Cleanup
    try:
        cognito.admin_delete_user(
            UserPoolId=cognito_user_pool,
            Username=username
        )
    except Exception:
        pass  # User may already be deleted


@pytest.fixture(scope="function")
def cleanup_s3_objects(s3_bucket, boto3_clients):
    """
    Track and cleanup S3 objects created during tests.

    Yields:
        Function to register S3 keys for cleanup

    Cleanup:
        Deletes all registered objects
    """
    s3 = boto3_clients['s3']
    keys_to_delete = []

    def register(key: str):
        """Register S3 key for cleanup."""
        keys_to_delete.append(key)

    yield register

    # Cleanup
    for key in keys_to_delete:
        try:
            s3.delete_object(Bucket=s3_bucket, Key=key)
        except Exception:
            pass  # Object may not exist


@pytest.fixture(scope="function")
def cleanup_ssm_parameters(boto3_clients):
    """
    Track and cleanup SSM parameters created during tests.

    Yields:
        Function to register parameter names for cleanup

    Cleanup:
        Deletes all registered parameters
    """
    ssm = boto3_clients['ssm']
    parameters_to_delete = []

    def register(name: str):
        """Register parameter name for cleanup."""
        parameters_to_delete.append(name)

    yield register

    # Cleanup
    for name in parameters_to_delete:
        try:
            ssm.delete_parameter(Name=name)
        except Exception:
            pass  # Parameter may not exist


@pytest.fixture(scope="function")
def cleanup_dynamodb_items(dynamodb_table):
    """
    Track and cleanup DynamoDB items created during tests.

    Yields:
        Function to register items for cleanup

    Cleanup:
        Deletes all registered items
    """
    items_to_delete = []

    def register(thread_id: str, checkpoint_id: str):
        """Register DynamoDB item for cleanup."""
        items_to_delete.append({'thread_id': thread_id, 'checkpoint_id': checkpoint_id})

    yield register

    # Cleanup
    with dynamodb_table.batch_writer() as batch:
        for item in items_to_delete:
            try:
                batch.delete_item(Key=item)
            except Exception:
                pass  # Item may not exist
