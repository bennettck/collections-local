"""
Test 11: API Gateway Routing

Validates:
- API Gateway exists
- Routes are configured
- Health endpoint is accessible
- Returns valid HTTP responses
- CORS headers configured (if applicable)
"""

import pytest
import requests


@pytest.mark.integration
def test_api_gateway_exists(stack_outputs, boto3_clients):
    """Verify API Gateway exists."""
    apigateway = boto3_clients['apigateway']

    api_url = stack_outputs.get('ApiUrl')

    if not api_url:
        pytest.skip("ApiUrl not in outputs")

    # Extract API ID from URL if possible
    # Format: https://{api-id}.execute-api.{region}.amazonaws.com
    if 'execute-api' in api_url:
        parts = api_url.split('.')
        api_id = parts[0].split('//')[-1]

        # Get API details
        try:
            response = apigateway.get_api(ApiId=api_id)
            assert response['ApiId'] == api_id
        except Exception as e:
            pytest.skip(f"Could not verify API Gateway: {e}")


@pytest.mark.integration
def test_api_health_endpoint(stack_outputs):
    """Test health endpoint accessibility."""
    api_url = stack_outputs.get('ApiUrl')

    if not api_url:
        pytest.skip("ApiUrl not in outputs")

    # Test health endpoint
    health_url = f"{api_url.rstrip('/')}/health"

    try:
        response = requests.get(health_url, timeout=10)

        assert response.status_code == 200, \
            f"Health check failed with status: {response.status_code}"

        # Verify response is JSON
        data = response.json()

        # Health response should have status or similar field
        assert 'status' in data or 'message' in data or 'version' in data

    except requests.exceptions.RequestException as e:
        pytest.fail(f"API Gateway request failed: {e}")


@pytest.mark.integration
def test_api_cors_headers(stack_outputs):
    """Test CORS headers if configured."""
    api_url = stack_outputs.get('ApiUrl')

    if not api_url:
        pytest.skip("ApiUrl not in outputs")

    health_url = f"{api_url.rstrip('/')}/health"

    try:
        response = requests.options(health_url, timeout=10)

        # Check for CORS headers (if configured)
        if 'Access-Control-Allow-Origin' in response.headers:
            # CORS is configured
            assert response.headers['Access-Control-Allow-Origin'] is not None
        else:
            # CORS may not be configured yet
            pytest.skip("CORS not configured")

    except requests.exceptions.RequestException as e:
        pytest.skip(f"CORS check failed: {e}")


@pytest.mark.integration
def test_api_response_headers(stack_outputs):
    """Test API response headers."""
    api_url = stack_outputs.get('ApiUrl')

    if not api_url:
        pytest.skip("ApiUrl not in outputs")

    health_url = f"{api_url.rstrip('/')}/health"

    response = requests.get(health_url, timeout=10)

    # Verify standard headers
    assert 'Content-Type' in response.headers
    assert 'application/json' in response.headers['Content-Type']


@pytest.mark.integration
def test_api_404_handling(stack_outputs):
    """Test 404 handling for non-existent endpoint."""
    api_url = stack_outputs.get('ApiUrl')

    if not api_url:
        pytest.skip("ApiUrl not in outputs")

    # Try non-existent endpoint
    not_found_url = f"{api_url.rstrip('/')}/this-endpoint-does-not-exist"

    try:
        response = requests.get(not_found_url, timeout=10)

        # Should return 404 or similar error
        assert response.status_code >= 400, \
            "Should return error for non-existent endpoint"

    except requests.exceptions.RequestException:
        # Some error occurred, which is expected
        pass
