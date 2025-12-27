"""
Test 5: Parameter Store Operations

Validates:
- Can create parameters
- Can read parameters (with decryption)
- Can update parameters
- Can delete parameters
- SecureString encryption works
"""

import pytest


@pytest.mark.integration
def test_parameter_store_create(boto3_clients, cleanup_ssm_parameters):
    """Test creating parameter."""
    ssm = boto3_clients['ssm']
    param_name = '/collections/test-param-create'
    param_value = 'test-value-123'

    cleanup_ssm_parameters(param_name)

    # Create parameter
    ssm.put_parameter(
        Name=param_name,
        Value=param_value,
        Type='SecureString',
        Description='Test parameter for validation'
    )

    # Verify created
    response = ssm.get_parameter(
        Name=param_name,
        WithDecryption=True
    )

    assert response['Parameter']['Name'] == param_name
    assert response['Parameter']['Value'] == param_value
    assert response['Parameter']['Type'] == 'SecureString'


@pytest.mark.integration
def test_parameter_store_read(boto3_clients, cleanup_ssm_parameters):
    """Test reading parameter."""
    ssm = boto3_clients['ssm']
    param_name = '/collections/test-param-read'
    param_value = 'secret-value-456'

    cleanup_ssm_parameters(param_name)

    # Create parameter
    ssm.put_parameter(
        Name=param_name,
        Value=param_value,
        Type='SecureString'
    )

    # Read with decryption
    response = ssm.get_parameter(
        Name=param_name,
        WithDecryption=True
    )

    assert response['Parameter']['Value'] == param_value

    # Read without decryption (should get encrypted value)
    response_encrypted = ssm.get_parameter(
        Name=param_name,
        WithDecryption=False
    )

    # Encrypted value should be different
    assert response_encrypted['Parameter']['Value'] != param_value


@pytest.mark.integration
def test_parameter_store_update(boto3_clients, cleanup_ssm_parameters):
    """Test updating existing parameter."""
    ssm = boto3_clients['ssm']
    param_name = '/collections/test-param-update'
    original_value = 'original-value'
    updated_value = 'updated-value'

    cleanup_ssm_parameters(param_name)

    # Create parameter
    ssm.put_parameter(
        Name=param_name,
        Value=original_value,
        Type='SecureString'
    )

    # Update parameter
    ssm.put_parameter(
        Name=param_name,
        Value=updated_value,
        Type='SecureString',
        Overwrite=True
    )

    # Verify updated
    response = ssm.get_parameter(
        Name=param_name,
        WithDecryption=True
    )

    assert response['Parameter']['Value'] == updated_value


@pytest.mark.integration
def test_parameter_store_delete(boto3_clients):
    """Test deleting parameter."""
    ssm = boto3_clients['ssm']
    param_name = '/collections/test-param-delete'
    param_value = 'value-to-delete'

    # Create parameter
    ssm.put_parameter(
        Name=param_name,
        Value=param_value,
        Type='SecureString'
    )

    # Verify exists
    response = ssm.get_parameter(Name=param_name)
    assert response['Parameter']['Name'] == param_name

    # Delete parameter
    ssm.delete_parameter(Name=param_name)

    # Verify deleted
    with pytest.raises(ssm.exceptions.ParameterNotFound):
        ssm.get_parameter(Name=param_name)


@pytest.mark.integration
def test_parameter_store_secure_string(boto3_clients, cleanup_ssm_parameters):
    """Test SecureString encryption."""
    ssm = boto3_clients['ssm']
    param_name = '/collections/test-param-secure'
    param_value = 'very-secret-value'

    cleanup_ssm_parameters(param_name)

    # Create SecureString parameter
    ssm.put_parameter(
        Name=param_name,
        Value=param_value,
        Type='SecureString'
    )

    # Get parameter metadata
    response = ssm.describe_parameters(
        Filters=[
            {'Key': 'Name', 'Values': [param_name]}
        ]
    )

    params = response['Parameters']
    assert len(params) == 1

    param = params[0]
    assert param['Type'] == 'SecureString'


@pytest.mark.integration
def test_parameter_store_batch_get(boto3_clients, cleanup_ssm_parameters):
    """Test getting multiple parameters at once."""
    ssm = boto3_clients['ssm']

    param_names = [
        '/collections/test-batch-1',
        '/collections/test-batch-2',
        '/collections/test-batch-3'
    ]

    # Create parameters
    for i, name in enumerate(param_names):
        cleanup_ssm_parameters(name)

        ssm.put_parameter(
            Name=name,
            Value=f'value-{i}',
            Type='String'  # Use String for batch test
        )

    # Get multiple parameters
    response = ssm.get_parameters(
        Names=param_names,
        WithDecryption=True
    )

    params = response['Parameters']
    assert len(params) == 3

    # Verify all parameters are present
    retrieved_names = {p['Name'] for p in params}
    assert set(param_names) == retrieved_names


@pytest.mark.integration
def test_parameter_store_string_list(boto3_clients, cleanup_ssm_parameters):
    """Test StringList parameter type."""
    ssm = boto3_clients['ssm']
    param_name = '/collections/test-string-list'
    param_value = 'value1,value2,value3'

    cleanup_ssm_parameters(param_name)

    # Create StringList parameter
    ssm.put_parameter(
        Name=param_name,
        Value=param_value,
        Type='StringList'
    )

    # Get parameter
    response = ssm.get_parameter(Name=param_name)

    assert response['Parameter']['Type'] == 'StringList'
    assert response['Parameter']['Value'] == param_value


@pytest.mark.integration
def test_parameter_store_description(boto3_clients, cleanup_ssm_parameters):
    """Test parameter description field."""
    ssm = boto3_clients['ssm']
    param_name = '/collections/test-description'
    param_value = 'test-value'
    description = 'This is a test parameter for infrastructure validation'

    cleanup_ssm_parameters(param_name)

    # Create parameter with description
    ssm.put_parameter(
        Name=param_name,
        Value=param_value,
        Type='String',
        Description=description
    )

    # Get parameter metadata
    response = ssm.describe_parameters(
        Filters=[
            {'Key': 'Name', 'Values': [param_name]}
        ]
    )

    params = response['Parameters']
    assert len(params) == 1
    assert params[0]['Description'] == description


@pytest.mark.integration
def test_parameter_store_overwrite_without_flag(boto3_clients, cleanup_ssm_parameters):
    """Test that overwrite fails without Overwrite=True."""
    from botocore.exceptions import ClientError

    ssm = boto3_clients['ssm']
    param_name = '/collections/test-overwrite'
    original_value = 'original'
    new_value = 'new'

    cleanup_ssm_parameters(param_name)

    # Create parameter
    ssm.put_parameter(
        Name=param_name,
        Value=original_value,
        Type='String'
    )

    # Try to overwrite without flag (should fail)
    with pytest.raises(ClientError) as exc_info:
        ssm.put_parameter(
            Name=param_name,
            Value=new_value,
            Type='String',
            Overwrite=False
        )

    error_code = exc_info.value.response['Error']['Code']
    assert error_code == 'ParameterAlreadyExists'


@pytest.mark.integration
def test_parameter_store_list_by_path(boto3_clients, cleanup_ssm_parameters):
    """Test listing parameters by path."""
    ssm = boto3_clients['ssm']

    base_path = '/collections/test-list'
    param_names = [
        f'{base_path}/param1',
        f'{base_path}/param2',
        f'{base_path}/param3'
    ]

    # Create parameters
    for name in param_names:
        cleanup_ssm_parameters(name)

        ssm.put_parameter(
            Name=name,
            Value='test-value',
            Type='String'
        )

    # List parameters by path
    response = ssm.get_parameters_by_path(
        Path=base_path,
        Recursive=True
    )

    params = response['Parameters']
    assert len(params) >= 3

    retrieved_names = {p['Name'] for p in params}
    assert set(param_names).issubset(retrieved_names)
