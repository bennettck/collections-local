"""
Test 7: S3 Bucket Operations

Validates:
- Bucket exists and is accessible
- Can upload files
- Can download files
- Can list files
- Can delete files
- EventBridge notifications configured (optional)
"""

import pytest
import io


@pytest.mark.integration
def test_s3_bucket_exists(s3_bucket, boto3_clients):
    """Verify S3 bucket exists and is accessible."""
    s3 = boto3_clients['s3']

    # Head bucket (will raise error if doesn't exist)
    response = s3.head_bucket(Bucket=s3_bucket)

    assert response['ResponseMetadata']['HTTPStatusCode'] == 200


@pytest.mark.integration
def test_s3_upload_file(s3_bucket, boto3_clients, cleanup_s3_objects):
    """Test uploading file to S3."""
    s3 = boto3_clients['s3']

    key = 'test/upload-test.txt'
    content = b'Test content for upload'

    cleanup_s3_objects(key)

    # Upload file
    s3.put_object(
        Bucket=s3_bucket,
        Key=key,
        Body=content,
        ContentType='text/plain'
    )

    # Verify uploaded
    response = s3.head_object(Bucket=s3_bucket, Key=key)

    assert response['ContentLength'] == len(content)
    assert response['ContentType'] == 'text/plain'


@pytest.mark.integration
def test_s3_download_file(s3_bucket, boto3_clients, cleanup_s3_objects):
    """Test downloading file from S3."""
    s3 = boto3_clients['s3']

    key = 'test/download-test.txt'
    content = b'Test content for download'

    cleanup_s3_objects(key)

    # Upload first
    s3.put_object(
        Bucket=s3_bucket,
        Key=key,
        Body=content
    )

    # Download
    response = s3.get_object(Bucket=s3_bucket, Key=key)
    downloaded_content = response['Body'].read()

    assert downloaded_content == content


@pytest.mark.integration
def test_s3_list_objects(s3_bucket, boto3_clients, cleanup_s3_objects):
    """Test listing objects in S3 bucket."""
    s3 = boto3_clients['s3']

    # Upload multiple files
    prefix = 'test/list/'
    keys = [f'{prefix}file{i}.txt' for i in range(3)]

    for key in keys:
        cleanup_s3_objects(key)
        s3.put_object(
            Bucket=s3_bucket,
            Key=key,
            Body=b'test content'
        )

    # List objects with prefix
    response = s3.list_objects_v2(
        Bucket=s3_bucket,
        Prefix=prefix
    )

    assert 'Contents' in response
    objects = response['Contents']

    assert len(objects) >= 3

    # Verify all keys are present
    object_keys = [obj['Key'] for obj in objects]
    for key in keys:
        assert key in object_keys


@pytest.mark.integration
def test_s3_delete_object(s3_bucket, boto3_clients):
    """Test deleting object from S3."""
    s3 = boto3_clients['s3']

    key = 'test/delete-test.txt'

    # Upload file
    s3.put_object(
        Bucket=s3_bucket,
        Key=key,
        Body=b'content to delete'
    )

    # Verify exists
    response = s3.head_object(Bucket=s3_bucket, Key=key)
    assert response['ResponseMetadata']['HTTPStatusCode'] == 200

    # Delete
    s3.delete_object(Bucket=s3_bucket, Key=key)

    # Verify deleted
    from botocore.exceptions import ClientError

    with pytest.raises(ClientError) as exc_info:
        s3.head_object(Bucket=s3_bucket, Key=key)

    error_code = exc_info.value.response['Error']['Code']
    assert error_code == '404'


@pytest.mark.integration
def test_s3_metadata(s3_bucket, boto3_clients, cleanup_s3_objects):
    """Test object metadata."""
    s3 = boto3_clients['s3']

    key = 'test/metadata-test.txt'
    metadata = {
        'user-id': 'test-user-123',
        'category': 'test'
    }

    cleanup_s3_objects(key)

    # Upload with metadata
    s3.put_object(
        Bucket=s3_bucket,
        Key=key,
        Body=b'content',
        Metadata=metadata
    )

    # Get metadata
    response = s3.head_object(Bucket=s3_bucket, Key=key)

    assert 'Metadata' in response
    assert response['Metadata'] == metadata


@pytest.mark.integration
def test_s3_presigned_url(s3_bucket, boto3_clients, cleanup_s3_objects):
    """Test generating pre-signed URL."""
    s3 = boto3_clients['s3']

    key = 'test/presigned-test.txt'
    content = b'content for presigned URL'

    cleanup_s3_objects(key)

    # Upload file
    s3.put_object(
        Bucket=s3_bucket,
        Key=key,
        Body=content
    )

    # Generate presigned URL
    url = s3.generate_presigned_url(
        'get_object',
        Params={'Bucket': s3_bucket, 'Key': key},
        ExpiresIn=3600
    )

    assert url is not None
    assert s3_bucket in url
    assert key in url

    # Verify URL works
    import requests

    response = requests.get(url)
    assert response.status_code == 200
    assert response.content == content


@pytest.mark.integration
def test_s3_multipart_upload(s3_bucket, boto3_clients, cleanup_s3_objects):
    """Test multipart upload (for large files)."""
    s3 = boto3_clients['s3']

    key = 'test/multipart-test.txt'

    cleanup_s3_objects(key)

    # Initiate multipart upload
    response = s3.create_multipart_upload(
        Bucket=s3_bucket,
        Key=key
    )

    upload_id = response['UploadId']

    try:
        # Upload parts
        part1 = b'a' * 5 * 1024 * 1024  # 5MB
        part2 = b'b' * 5 * 1024 * 1024  # 5MB

        parts = []

        for i, part_data in enumerate([part1, part2], 1):
            response = s3.upload_part(
                Bucket=s3_bucket,
                Key=key,
                PartNumber=i,
                UploadId=upload_id,
                Body=part_data
            )

            parts.append({
                'PartNumber': i,
                'ETag': response['ETag']
            })

        # Complete multipart upload
        s3.complete_multipart_upload(
            Bucket=s3_bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={'Parts': parts}
        )

        # Verify file exists
        response = s3.head_object(Bucket=s3_bucket, Key=key)
        assert response['ContentLength'] == len(part1) + len(part2)

    except Exception:
        # Abort upload on error
        s3.abort_multipart_upload(
            Bucket=s3_bucket,
            Key=key,
            UploadId=upload_id
        )
        raise


@pytest.mark.integration
def test_s3_eventbridge_configuration(s3_bucket, boto3_clients):
    """Test EventBridge notifications configuration."""
    s3 = boto3_clients['s3']

    try:
        response = s3.get_bucket_notification_configuration(
            Bucket=s3_bucket
        )

        # Check if EventBridge is enabled
        if 'EventBridgeConfiguration' in response:
            # EventBridge notifications are configured
            assert response['EventBridgeConfiguration'] is not None
        else:
            # May not be configured yet
            pytest.skip("EventBridge notifications not configured")

    except Exception as e:
        pytest.skip(f"Could not check EventBridge config: {e}")
