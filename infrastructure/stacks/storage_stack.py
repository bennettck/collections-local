"""Storage stack: S3 bucket with EventBridge notifications."""

from aws_cdk import (
    Stack,
    RemovalPolicy,
    CfnOutput,
    aws_s3 as s3,
    aws_events as events,
)
from constructs import Construct
from typing import Dict, Any


class StorageStack(Stack):
    """
    Storage infrastructure stack.

    Components:
    - S3 bucket for image storage (with user-based isolation)
    - EventBridge notifications enabled
    - CORS configuration for web access
    - Lifecycle policies (prod only)
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        env_config: Dict[str, Any] = None,
        **kwargs
    ):
        """
        Initialize storage stack.

        Args:
            scope: CDK app
            construct_id: Stack ID
            env_name: Environment name (dev/test/prod)
            env_config: Environment-specific configuration
            **kwargs: Additional stack properties
        """
        super().__init__(scope, construct_id, **kwargs)

        self.env_name = env_name
        self.env_config = env_config or {}

        # Create S3 bucket
        self._create_s3_bucket()

        # Create EventBridge event bus
        self._create_event_bus()

        # Stack outputs
        self._create_outputs()

    def _create_s3_bucket(self):
        """Create S3 bucket for image storage."""
        # Bucket configuration varies by environment
        versioned = self.env_name == "prod"
        lifecycle_rules = [] if self.env_name == "dev" else [
            s3.LifecycleRule(
                id="DeleteOldThumbnails",
                enabled=True,
                expiration_days=90,
                prefix="*/thumbnails/",
            )
        ]

        self.bucket = s3.Bucket(
            self,
            "ImageBucket",
            bucket_name=f"collections-images-{self.env_name}-{self.account}",
            versioned=versioned,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN if self.env_name == "prod" else RemovalPolicy.DESTROY,
            auto_delete_objects=self.env_name == "dev",  # Auto-delete on stack deletion (dev only)
            lifecycle_rules=lifecycle_rules,
            event_bridge_enabled=True,  # Enable EventBridge notifications
            cors=[
                s3.CorsRule(
                    allowed_methods=[
                        s3.HttpMethods.GET,
                        s3.HttpMethods.PUT,
                        s3.HttpMethods.POST,
                        s3.HttpMethods.DELETE,
                    ],
                    allowed_origins=["*"],  # Configure based on frontend domain
                    allowed_headers=["*"],
                    max_age=3000,
                )
            ],
        )

    def _create_event_bus(self):
        """Create EventBridge event bus for workflow orchestration."""
        # Use default event bus for simplicity
        # Custom event bus can be added if needed
        self.event_bus = events.EventBus.from_event_bus_name(
            self,
            "DefaultEventBus",
            "default",
        )

    def _create_outputs(self):
        """Create CloudFormation outputs."""
        CfnOutput(
            self,
            "BucketName",
            value=self.bucket.bucket_name,
            description="S3 bucket name for images",
            export_name=f"collections-{self.env_name}-bucket-name",
        )

        CfnOutput(
            self,
            "BucketArn",
            value=self.bucket.bucket_arn,
            description="S3 bucket ARN",
            export_name=f"collections-{self.env_name}-bucket-arn",
        )

        CfnOutput(
            self,
            "EventBusName",
            value=self.event_bus.event_bus_name,
            description="EventBridge event bus name",
            export_name=f"collections-{self.env_name}-event-bus-name",
        )

        CfnOutput(
            self,
            "EventBusArn",
            value=self.event_bus.event_bus_arn,
            description="EventBridge event bus ARN",
            export_name=f"collections-{self.env_name}-event-bus-arn",
        )
