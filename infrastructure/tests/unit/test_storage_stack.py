"""Unit tests for StorageStack."""

import aws_cdk as cdk
from aws_cdk import assertions

from stacks.storage_stack import StorageStack


def test_storage_stack_creates_s3_bucket():
    """Test that S3 bucket is created with correct properties."""
    app = cdk.App()

    stack = StorageStack(
        app,
        "TestStorageStack",
        env_name="dev",
        env_config={},
    )

    template = assertions.Template.from_stack(stack)

    # Assert S3 bucket exists
    template.resource_count_is("AWS::S3::Bucket", 1)

    # Assert EventBridge is enabled
    template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "NotificationConfiguration": {
                "EventBridgeConfiguration": {"EventBridgeEnabled": True}
            },
        },
    )


def test_storage_stack_enables_cors():
    """Test that CORS is configured on S3 bucket."""
    app = cdk.App()

    stack = StorageStack(
        app,
        "TestStorageStack",
        env_name="dev",
        env_config={},
    )

    template = assertions.Template.from_stack(stack)

    # Assert CORS configuration
    template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "CorsConfiguration": {
                "CorsRules": assertions.Match.array_with([
                    assertions.Match.object_like({
                        "AllowedMethods": assertions.Match.array_with(["GET", "PUT", "POST", "DELETE"]),
                    })
                ])
            }
        },
    )


def test_storage_stack_outputs():
    """Test that stack creates required outputs."""
    app = cdk.App()

    stack = StorageStack(
        app,
        "TestStorageStack",
        env_name="dev",
        env_config={},
    )

    template = assertions.Template.from_stack(stack)

    # Assert outputs exist
    template.has_output("BucketName", {})
    template.has_output("BucketArn", {})
