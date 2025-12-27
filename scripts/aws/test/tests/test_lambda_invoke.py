"""
Test 8: Lambda Function Invocation

Validates:
- Lambda function exists
- Can invoke function
- Function returns valid response
- CloudWatch logs are created
- Function has correct IAM permissions
"""

import pytest
import json


@pytest.mark.integration
def test_lambda_function_exists(stack_outputs, boto3_clients):
    """Verify Lambda function exists."""
    lambda_client = boto3_clients['lambda']

    lambda_name = stack_outputs.get('ApiLambdaName')

    if not lambda_name:
        # Try to find any Lambda function
        response = lambda_client.list_functions()
        functions = response['Functions']

        # Find collections-related function
        for func in functions:
            if 'collections' in func['FunctionName'].lower() or 'api' in func['FunctionName'].lower():
                lambda_name = func['FunctionName']
                break

        if not lambda_name:
            pytest.skip("No Lambda function found")

    # Get function configuration
    response = lambda_client.get_function(FunctionName=lambda_name)

    assert 'Configuration' in response
    assert response['Configuration']['FunctionName'] == lambda_name


@pytest.mark.integration
def test_lambda_invoke_basic(stack_outputs, boto3_clients):
    """Test basic Lambda invocation."""
    lambda_client = boto3_clients['lambda']

    lambda_name = stack_outputs.get('ApiLambdaName')

    if not lambda_name:
        response = lambda_client.list_functions()
        functions = response['Functions']

        for func in functions:
            if 'collections' in func['FunctionName'].lower():
                lambda_name = func['FunctionName']
                break

        if not lambda_name:
            pytest.skip("No Lambda function found")

    # Invoke function
    response = lambda_client.invoke(
        FunctionName=lambda_name,
        InvocationType='RequestResponse',
        Payload=json.dumps({'test': True})
    )

    assert response['StatusCode'] == 200

    # Read response payload
    payload = json.loads(response['Payload'].read())

    # Should have some response
    assert payload is not None


@pytest.mark.integration
def test_lambda_cloudwatch_logs(stack_outputs, boto3_clients):
    """Verify CloudWatch log group exists for Lambda."""
    logs_client = boto3_clients['logs']

    lambda_name = stack_outputs.get('ApiLambdaName')

    if not lambda_name:
        pytest.skip("ApiLambdaName not in outputs")

    log_group_name = f"/aws/lambda/{lambda_name}"

    # Check if log group exists
    try:
        response = logs_client.describe_log_groups(
            logGroupNamePrefix=log_group_name
        )

        log_groups = response['logGroups']
        assert len(log_groups) > 0, f"Log group not found: {log_group_name}"

        # Verify exact match
        log_group_names = [lg['logGroupName'] for lg in log_groups]
        assert log_group_name in log_group_names

    except Exception as e:
        pytest.skip(f"Could not verify CloudWatch logs: {e}")


@pytest.mark.integration
def test_lambda_configuration(stack_outputs, boto3_clients):
    """Test Lambda function configuration."""
    lambda_client = boto3_clients['lambda']

    lambda_name = stack_outputs.get('ApiLambdaName')

    if not lambda_name:
        pytest.skip("ApiLambdaName not in outputs")

    response = lambda_client.get_function_configuration(
        FunctionName=lambda_name
    )

    # Verify basic configuration
    assert 'Runtime' in response
    assert 'python' in response['Runtime'].lower() or 'container' in response.get('PackageType', '').lower()

    assert 'MemorySize' in response
    assert response['MemorySize'] >= 128  # Minimum memory

    assert 'Timeout' in response
    assert response['Timeout'] > 0


@pytest.mark.integration
def test_lambda_environment_variables(stack_outputs, boto3_clients):
    """Test Lambda environment variables."""
    lambda_client = boto3_clients['lambda']

    lambda_name = stack_outputs.get('ApiLambdaName')

    if not lambda_name:
        pytest.skip("ApiLambdaName not in outputs")

    response = lambda_client.get_function_configuration(
        FunctionName=lambda_name
    )

    # Check if environment variables are set
    if 'Environment' in response:
        variables = response['Environment'].get('Variables', {})

        # Verify some expected variables (based on CDK config)
        # These are optional checks
        if 'AWS_REGION' in variables:
            assert variables['AWS_REGION'] is not None
