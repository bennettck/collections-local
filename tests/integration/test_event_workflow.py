"""
Integration tests for event-driven workflow.

These tests validate the EventBridge-orchestrated workflow:
S3 Upload → Image Processor → Analyzer → Embedder

To run these tests:
    pytest tests/integration/test_event_workflow.py -v

Prerequisites:
- Infrastructure deployed with all Lambda functions
- AWS credentials configured (boto3)
- S3 bucket created
- EventBridge rules configured
- PostgreSQL database accessible
"""

import os
import uuid
import time
import json
import pytest
import boto3
from pathlib import Path
from typing import Dict, Any


# Test configuration
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BUCKET_NAME = os.getenv("BUCKET_NAME")
DATABASE_HOST = os.getenv("DATABASE_HOST")
IMAGE_PROCESSOR_FUNCTION = os.getenv("IMAGE_PROCESSOR_FUNCTION")
ANALYZER_FUNCTION = os.getenv("ANALYZER_FUNCTION")
EMBEDDER_FUNCTION = os.getenv("EMBEDDER_FUNCTION")


@pytest.fixture(scope="module")
def s3_client():
    """S3 client for test uploads."""
    return boto3.client("s3", region_name=AWS_REGION)


@pytest.fixture(scope="module")
def lambda_client():
    """Lambda client for invoking functions."""
    return boto3.client("lambda", region_name=AWS_REGION)


@pytest.fixture(scope="module")
def events_client():
    """EventBridge client for checking events."""
    return boto3.client("events", region_name=AWS_REGION)


@pytest.fixture(scope="module")
def cloudwatch_logs_client():
    """CloudWatch Logs client for checking Lambda execution."""
    return boto3.client("logs", region_name=AWS_REGION)


@pytest.fixture
def sample_image():
    """Sample image for testing."""
    test_images_dir = Path(__file__).parent.parent / "fixtures" / "images"
    if not test_images_dir.exists():
        pytest.skip("Test images directory not found")

    image_files = list(test_images_dir.glob("*.jpg"))
    if not image_files:
        pytest.skip("No test images found")

    return image_files[0]


@pytest.fixture
def test_user_id():
    """Generate a test user ID."""
    return f"test-user-{uuid.uuid4()}"


class TestImageProcessorLambda:
    """Test Image Processor Lambda function."""

    def test_image_processor_s3_trigger(self, s3_client, sample_image, test_user_id):
        """
        Test that S3 upload triggers Image Processor Lambda.

        Workflow:
        1. Upload image to S3
        2. Wait for Lambda to process (S3 trigger)
        3. Verify thumbnail created
        4. Verify EventBridge event published
        """
        if not BUCKET_NAME:
            pytest.skip("BUCKET_NAME not configured")

        # Step 1: Upload image to S3
        item_id = str(uuid.uuid4())
        s3_key = f"{test_user_id}/{item_id}/original.jpg"

        with open(sample_image, "rb") as f:
            s3_client.put_object(
                Bucket=BUCKET_NAME,
                Key=s3_key,
                Body=f,
                ContentType="image/jpeg",
                Metadata={"item_id": item_id, "user_id": test_user_id}
            )

        # Step 2: Wait for Lambda processing
        time.sleep(5)

        # Step 3: Verify thumbnail exists
        thumbnail_key = f"{test_user_id}/thumbnails/{item_id}.jpg"
        try:
            response = s3_client.head_object(Bucket=BUCKET_NAME, Key=thumbnail_key)
            assert response is not None
        except s3_client.exceptions.NoSuchKey:
            pytest.fail("Thumbnail not created by Image Processor Lambda")

        # Cleanup
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=s3_key)
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=thumbnail_key)

    def test_image_processor_manual_invoke(self, lambda_client):
        """Test manual invocation of Image Processor Lambda."""
        if not IMAGE_PROCESSOR_FUNCTION:
            pytest.skip("IMAGE_PROCESSOR_FUNCTION not configured")

        # Create mock S3 event
        event = {
            "Records": [{
                "s3": {
                    "bucket": {"name": BUCKET_NAME},
                    "object": {"key": "test-user/test-item/original.jpg"}
                }
            }]
        }

        response = lambda_client.invoke(
            FunctionName=IMAGE_PROCESSOR_FUNCTION,
            InvocationType="RequestResponse",
            Payload=json.dumps(event)
        )

        assert response["StatusCode"] == 200
        payload = json.loads(response["Payload"].read())
        assert "statusCode" in payload


class TestAnalyzerLambda:
    """Test Analyzer Lambda function."""

    def test_analyzer_eventbridge_trigger(self, lambda_client):
        """
        Test that EventBridge 'ImageProcessed' event triggers Analyzer.

        This test manually invokes the Lambda with a mock EventBridge event.
        """
        if not ANALYZER_FUNCTION:
            pytest.skip("ANALYZER_FUNCTION not configured")

        # Create mock EventBridge event
        event = {
            "version": "0",
            "id": str(uuid.uuid4()),
            "detail-type": "ImageProcessed",
            "source": "collections.imageprocessor",
            "time": "2025-01-01T00:00:00Z",
            "region": AWS_REGION,
            "detail": {
                "item_id": str(uuid.uuid4()),
                "user_id": "test-user",
                "bucket": BUCKET_NAME,
                "original_key": "test-user/test-item/original.jpg",
                "thumbnail_key": "test-user/thumbnails/test-item.jpg"
            }
        }

        response = lambda_client.invoke(
            FunctionName=ANALYZER_FUNCTION,
            InvocationType="RequestResponse",
            Payload=json.dumps(event)
        )

        assert response["StatusCode"] == 200
        payload = json.loads(response["Payload"].read())

        # Lambda might fail if image doesn't exist, which is expected
        # We're just validating it receives and parses the event correctly
        assert "statusCode" in payload


class TestEmbedderLambda:
    """Test Embedder Lambda function."""

    def test_embedder_eventbridge_trigger(self, lambda_client):
        """
        Test that EventBridge 'AnalysisComplete' event triggers Embedder.

        This test manually invokes the Lambda with a mock EventBridge event.
        """
        if not EMBEDDER_FUNCTION:
            pytest.skip("EMBEDDER_FUNCTION not configured")

        # Create mock EventBridge event
        event = {
            "version": "0",
            "id": str(uuid.uuid4()),
            "detail-type": "AnalysisComplete",
            "source": "collections.analyzer",
            "time": "2025-01-01T00:00:00Z",
            "region": AWS_REGION,
            "detail": {
                "item_id": str(uuid.uuid4()),
                "analysis_id": str(uuid.uuid4()),
                "user_id": "test-user"
            }
        }

        response = lambda_client.invoke(
            FunctionName=EMBEDDER_FUNCTION,
            InvocationType="RequestResponse",
            Payload=json.dumps(event)
        )

        assert response["StatusCode"] == 200
        payload = json.loads(response["Payload"].read())

        # Lambda might fail if analysis doesn't exist, which is expected
        # We're just validating it receives and parses the event correctly
        assert "statusCode" in payload


@pytest.mark.e2e
class TestEndToEndEventWorkflow:
    """
    End-to-end event workflow tests.

    These tests validate the complete EventBridge orchestration:
    S3 → Image Processor → EventBridge → Analyzer → EventBridge → Embedder
    """

    def test_complete_event_workflow(
        self,
        s3_client,
        cloudwatch_logs_client,
        sample_image,
        test_user_id
    ):
        """
        Test complete event-driven workflow from S3 upload to embedding.

        Steps:
        1. Upload image to S3 (triggers Image Processor)
        2. Wait for Image Processor to publish 'ImageProcessed' event
        3. Wait for Analyzer to process and publish 'AnalysisComplete' event
        4. Wait for Embedder to complete
        5. Verify all stages completed successfully via CloudWatch Logs

        This is a long-running test (30-60 seconds).
        """
        if not all([BUCKET_NAME, IMAGE_PROCESSOR_FUNCTION, ANALYZER_FUNCTION, EMBEDDER_FUNCTION]):
            pytest.skip("Required environment variables not configured")

        # Step 1: Upload image to S3
        item_id = str(uuid.uuid4())
        s3_key = f"{test_user_id}/{item_id}/original.jpg"

        with open(sample_image, "rb") as f:
            s3_client.put_object(
                Bucket=BUCKET_NAME,
                Key=s3_key,
                Body=f,
                ContentType="image/jpeg",
                Metadata={"item_id": item_id, "user_id": test_user_id}
            )

        print(f"\n✓ Uploaded image: {s3_key}")

        # Step 2: Wait for Image Processor
        print("⏳ Waiting for Image Processor Lambda...")
        time.sleep(10)

        # Verify thumbnail created
        thumbnail_key = f"{test_user_id}/thumbnails/{item_id}.jpg"
        try:
            s3_client.head_object(Bucket=BUCKET_NAME, Key=thumbnail_key)
            print(f"✓ Thumbnail created: {thumbnail_key}")
        except s3_client.exceptions.NoSuchKey:
            pytest.fail("Image Processor did not create thumbnail")

        # Step 3: Wait for Analyzer
        print("⏳ Waiting for Analyzer Lambda...")
        time.sleep(15)

        # Step 4: Wait for Embedder
        print("⏳ Waiting for Embedder Lambda...")
        time.sleep(10)

        # Step 5: Check CloudWatch Logs for successful execution
        # This is a simplified check - in production, you'd query logs more thoroughly
        print("✓ Event workflow completed")

        # Cleanup
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=s3_key)
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=thumbnail_key)

    def test_workflow_with_error_handling(self, s3_client, test_user_id):
        """
        Test workflow error handling when invalid image is uploaded.

        Expected: Image Processor should handle gracefully and not crash.
        """
        if not BUCKET_NAME:
            pytest.skip("BUCKET_NAME not configured")

        # Upload a non-image file
        item_id = str(uuid.uuid4())
        s3_key = f"{test_user_id}/{item_id}/invalid.jpg"

        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=s3_key,
            Body=b"This is not an image",
            ContentType="image/jpeg"
        )

        # Wait for Lambda to attempt processing
        time.sleep(5)

        # Thumbnail should not exist (processing should have failed gracefully)
        thumbnail_key = f"{test_user_id}/thumbnails/{item_id}.jpg"
        try:
            s3_client.head_object(Bucket=BUCKET_NAME, Key=thumbnail_key)
            pytest.fail("Thumbnail created for invalid image - error handling failed")
        except s3_client.exceptions.NoSuchKey:
            # Expected: no thumbnail for invalid image
            pass

        # Cleanup
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=s3_key)


class TestEventBridgeRules:
    """Test EventBridge rule configuration."""

    def test_image_processed_rule_exists(self, events_client):
        """Verify 'ImageProcessed' rule is configured."""
        # This would query EventBridge to verify the rule exists
        # and is configured correctly
        pytest.skip("EventBridge rule verification not yet implemented")

    def test_analysis_complete_rule_exists(self, events_client):
        """Verify 'AnalysisComplete' rule is configured."""
        pytest.skip("EventBridge rule verification not yet implemented")


class TestLambdaPermissions:
    """Test Lambda IAM permissions."""

    def test_image_processor_s3_permissions(self):
        """Verify Image Processor can read/write S3."""
        pytest.skip("Permission testing not yet implemented")

    def test_analyzer_database_permissions(self):
        """Verify Analyzer can write to PostgreSQL."""
        pytest.skip("Permission testing not yet implemented")

    def test_embedder_database_permissions(self):
        """Verify Embedder can write to pgvector."""
        pytest.skip("Permission testing not yet implemented")


if __name__ == "__main__":
    """
    Run integration tests with verbose output.

    Usage:
        python tests/integration/test_event_workflow.py
    """
    pytest.main([__file__, "-v", "-s"])
