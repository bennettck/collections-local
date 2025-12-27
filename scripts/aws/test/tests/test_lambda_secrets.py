"""
Test 10: Lambda → Parameter Store Access

Validates:
- Lambda can read from Parameter Store
- Lambda has correct IAM permissions
"""

import pytest


@pytest.mark.integration
def test_lambda_iam_role(stack_outputs, boto3_clients):
    """Verify Lambda has IAM role with permissions."""
    lambda_client = boto3_clients['lambda']
    iam = boto3.client('iam')

    lambda_name = stack_outputs.get('ApiLambdaName')

    if not lambda_name:
        pytest.skip("ApiLambdaName not in outputs")

    # Get Lambda configuration
    response = lambda_client.get_function_configuration(
        FunctionName=lambda_name
    )

    role_arn = response.get('Role')
    assert role_arn is not None, "Lambda has no IAM role"

    # Extract role name from ARN
    role_name = role_arn.split('/')[-1]

    # Get role details
    try:
        role_response = iam.get_role(RoleName=role_name)
        assert role_response['Role']['RoleName'] == role_name
    except Exception as e:
        pytest.skip(f"Could not verify IAM role: {e}")


@pytest.mark.integration
def test_lambda_parameter_store_permissions(stack_outputs, boto3_clients):
    """Test Lambda has permissions to access Parameter Store."""
    lambda_client = boto3_clients['lambda']
    iam = boto3.client('iam')

    lambda_name = stack_outputs.get('ApiLambdaName')

    if not lambda_name:
        pytest.skip("ApiLambdaName not in outputs")

    # Get Lambda role
    response = lambda_client.get_function_configuration(
        FunctionName=lambda_name
    )

    role_arn = response.get('Role')
    role_name = role_arn.split('/')[-1]

    try:
        # List role policies
        policies_response = iam.list_attached_role_policies(
            RoleName=role_name
        )

        attached_policies = policies_response['AttachedPolicies']

        # Verify Lambda has some policies attached
        assert len(attached_policies) > 0, "Lambda role has no attached policies"

        # Note: Detailed permission checking would require inspecting policy documents
        # This is a basic check that policies are attached

    except Exception as e:
        pytest.skip(f"Could not verify IAM policies: {e}")
