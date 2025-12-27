"""
Shared pytest fixtures for integration tests.

Provides reusable test fixtures for:
- AWS credentials and configuration
- DynamoDB resources
- Cognito test users
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
def project_root() -> Path:
    """
    Get project root directory.

    Returns:
        Path to project root
    """
    # Integration tests are in tests/integration/
    return Path(__file__).parent.parent.parent


@pytest.fixture(scope="session")
def stack_outputs(env_name, project_root) -> Dict[str, Any]:
    """
    Load CDK stack outputs from JSON file.

    Args:
        env_name: Environment name fixture
        project_root: Project root path fixture

    Returns:
        Dictionary of stack outputs (OutputKey -> OutputValue)

    Raises:
        pytest.skip: If outputs file doesn't exist (infrastructure not deployed)
    """
    outputs_file = project_root / f'.aws-outputs-{env_name}.json'

    if not outputs_file.exists():
        pytest.skip(
            f"CDK outputs not found: {outputs_file}. "
            f"Deploy infrastructure first with: make infra-deploy"
        )

    with open(outputs_file) as f:
        raw_outputs = json.load(f)

    # Convert from list of {OutputKey, OutputValue} to dict
    if isinstance(raw_outputs, list):
        return {item['OutputKey']: item['OutputValue'] for item in raw_outputs}

    # Already a dict (alternative format)
    return raw_outputs


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


@pytest.fixture(scope="session")
def dynamodb_resource(aws_region):
    """
    Initialize DynamoDB resource.

    Args:
        aws_region: AWS region fixture

    Returns:
        boto3 DynamoDB resource
    """
    return boto3.resource('dynamodb', region_name=aws_region)


@pytest.fixture(scope="session")
def dynamodb_client(aws_region):
    """
    Initialize DynamoDB client.

    Args:
        aws_region: AWS region fixture

    Returns:
        boto3 DynamoDB client
    """
    return boto3.client('dynamodb', region_name=aws_region)


@pytest.fixture(scope="function")
def rds_connection(stack_outputs):
    """
    Provide PostgreSQL database connection.

    Args:
        stack_outputs: CDK stack outputs fixture

    Yields:
        psycopg2 connection object

    Cleanup:
        Closes connection after test
    """
    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 not installed")

    rds_endpoint = stack_outputs.get('RdsEndpoint')
    db_name = stack_outputs.get('DatabaseName', 'collections')
    username = stack_outputs.get('RdsUsername', 'postgres')
    password = stack_outputs.get('RdsPassword')

    if not all([rds_endpoint, password]):
        pytest.skip("Database credentials not available in stack outputs")

    try:
        conn = psycopg2.connect(
            host=rds_endpoint,
            database=db_name,
            user=username,
            password=password,
            sslmode='require',
            connect_timeout=10
        )

        yield conn

        conn.close()
    except Exception as e:
        pytest.skip(f"Cannot connect to RDS: {e}")


@pytest.fixture(scope="function")
def checkpoint_table(stack_outputs, dynamodb_resource):
    """
    Provide DynamoDB checkpoint table resource.

    Args:
        stack_outputs: CDK stack outputs fixture
        dynamodb_resource: DynamoDB resource fixture

    Yields:
        boto3 Table resource for checkpoint storage

    Raises:
        pytest.skip: If table not available
    """
    table_name = stack_outputs.get('CheckpointTableName')

    if not table_name:
        pytest.skip("CheckpointTableName not in stack outputs")

    table = dynamodb_resource.Table(table_name)

    # Verify table exists and is accessible
    try:
        table.load()
    except Exception as e:
        pytest.skip(f"Checkpoint table not accessible: {e}")

    yield table


@pytest.fixture(scope="function")
def s3_bucket(stack_outputs):
    """
    Provide S3 bucket name.

    Args:
        stack_outputs: CDK stack outputs fixture

    Returns:
        Bucket name string

    Raises:
        pytest.skip: If bucket not available
    """
    bucket_name = stack_outputs.get('BucketName')

    if not bucket_name:
        pytest.skip("BucketName not in stack outputs")

    return bucket_name


@pytest.fixture(scope="function")
def cognito_user_pool(stack_outputs):
    """
    Provide Cognito User Pool ID.

    Args:
        stack_outputs: CDK stack outputs fixture

    Returns:
        User Pool ID string

    Raises:
        pytest.skip: If user pool not available
    """
    user_pool_id = stack_outputs.get('CognitoUserPoolId')

    if not user_pool_id:
        pytest.skip("CognitoUserPoolId not in stack outputs")

    return user_pool_id


@pytest.fixture(scope="function")
def test_cognito_user(cognito_user_pool, boto3_clients):
    """
    Create and cleanup test Cognito user.

    Args:
        cognito_user_pool: Cognito User Pool ID fixture
        boto3_clients: boto3 clients fixture

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

    try:
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

    except Exception as e:
        pytest.skip(f"Cannot create test Cognito user: {e}")

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

    Args:
        s3_bucket: S3 bucket name fixture
        boto3_clients: boto3 clients fixture

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

    Args:
        boto3_clients: boto3 clients fixture

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
def cleanup_dynamodb_items(checkpoint_table):
    """
    Track and cleanup DynamoDB items created during tests.

    Args:
        checkpoint_table: DynamoDB table fixture

    Yields:
        Function to register items for cleanup

    Cleanup:
        Deletes all registered items
    """
    items_to_delete = []

    def register(thread_id: str, checkpoint_id: str = None):
        """Register DynamoDB item for cleanup."""
        items_to_delete.append({'thread_id': thread_id, 'checkpoint_id': checkpoint_id})

    yield register

    # Cleanup all registered items
    for item in items_to_delete:
        try:
            if item['checkpoint_id']:
                # Delete specific checkpoint
                checkpoint_table.delete_item(
                    Key={
                        'thread_id': item['thread_id'],
                        'checkpoint_id': item['checkpoint_id']
                    }
                )
            else:
                # Delete all checkpoints for thread_id
                response = checkpoint_table.query(
                    KeyConditionExpression='thread_id = :tid',
                    ExpressionAttributeValues={':tid': item['thread_id']}
                )

                with checkpoint_table.batch_writer() as batch:
                    for checkpoint in response.get('Items', []):
                        batch.delete_item(
                            Key={
                                'thread_id': checkpoint['thread_id'],
                                'checkpoint_id': checkpoint.get('checkpoint_id', checkpoint.get('id'))
                            }
                        )
        except Exception:
            pass  # Item may not exist
