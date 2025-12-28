"""Compute stack: Lambda functions for API and event-driven workflows."""

from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_iam as iam,
    aws_events as events,
    aws_events_targets as targets,
    aws_s3 as s3,
    aws_dynamodb as dynamodb,
    aws_rds as rds,
    aws_secretsmanager as secretsmanager,
    aws_s3_notifications as s3n,
    aws_ecr as ecr,
)
from constructs import Construct
from typing import Dict, Any, List


class ComputeStack(Stack):
    """
    Compute infrastructure stack.

    Components:
    - 5 Lambda functions:
      1. API Lambda (FastAPI via Mangum) - placeholder hello world
      2. Image Processor Lambda (S3 trigger) - placeholder hello world
      3. Analyzer Lambda (EventBridge trigger) - placeholder hello world
      4. Embedder Lambda (EventBridge trigger) - placeholder hello world
      5. Cleanup Lambda (EventBridge cron) - placeholder hello world
    - EventBridge rules for workflow orchestration
    - IAM roles with least-privilege permissions
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        env_config: Dict[str, Any],
        database: rds.DatabaseInstance,
        checkpoint_table: dynamodb.Table,
        db_credentials: secretsmanager.ISecret,
        **kwargs
    ):
        """
        Initialize compute stack.

        Args:
            scope: CDK app
            construct_id: Stack ID
            env_name: Environment name (dev/test/prod)
            env_config: Environment-specific configuration
            database: RDS database instance
            checkpoint_table: DynamoDB table for checkpoints
            db_credentials: Database credentials secret
            **kwargs: Additional stack properties
        """
        super().__init__(scope, construct_id, **kwargs)

        self.env_name = env_name
        self.env_config = env_config
        self.database = database
        self.checkpoint_table = checkpoint_table
        self.db_credentials = db_credentials

        # Create S3 bucket and EventBridge bus internally (before common_env)
        self._create_storage_resources()

        # Common environment variables for all Lambdas
        # Note: AWS_REGION is automatically set by Lambda runtime
        self.common_env = {
            "ENVIRONMENT": env_name,
            "CHECKPOINT_TABLE_NAME": checkpoint_table.table_name,
            "BUCKET_NAME": self.bucket.bucket_name,
            # Database credentials via Secrets Manager (secure approach)
            "DB_SECRET_ARN": db_credentials.secret_arn,
            # Legacy environment variables (for backwards compatibility during migration)
            "DATABASE_HOST": database.db_instance_endpoint_address,
            "DATABASE_PORT": str(database.db_instance_endpoint_port),
            "DATABASE_NAME": "collections",
        }

        # Create Lambda functions
        self._create_api_lambda()
        self._create_image_processor_lambda()
        self._create_analyzer_lambda()
        self._create_embedder_lambda()
        self._create_cleanup_lambda()

        # Create EventBridge rules
        self._create_eventbridge_rules()

        # Create S3 event notifications
        self._create_s3_notifications()

        # Stack outputs
        self._create_outputs()

        # Collect all Lambdas for monitoring stack
        self.all_lambdas = [
            self.api_lambda,
            self.image_processor_lambda,
            self.analyzer_lambda,
            self.embedder_lambda,
            self.cleanup_lambda,
        ]

    def _get_log_retention(self, days: int) -> logs.RetentionDays:
        """Convert integer days to RetentionDays enum."""
        retention_map = {
            1: logs.RetentionDays.ONE_DAY,
            3: logs.RetentionDays.THREE_DAYS,
            5: logs.RetentionDays.FIVE_DAYS,
            7: logs.RetentionDays.ONE_WEEK,
            14: logs.RetentionDays.TWO_WEEKS,
            30: logs.RetentionDays.ONE_MONTH,
            60: logs.RetentionDays.TWO_MONTHS,
            90: logs.RetentionDays.THREE_MONTHS,
            120: logs.RetentionDays.FOUR_MONTHS,
            150: logs.RetentionDays.FIVE_MONTHS,
            180: logs.RetentionDays.SIX_MONTHS,
        }
        return retention_map.get(days, logs.RetentionDays.ONE_WEEK)

    def _create_storage_resources(self):
        """Create S3 bucket and EventBridge bus (to avoid circular dependencies)."""
        from aws_cdk import RemovalPolicy

        # S3 bucket for image storage
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
            auto_delete_objects=self.env_name == "dev",
            lifecycle_rules=lifecycle_rules,
            event_bridge_enabled=True,
            cors=[
                s3.CorsRule(
                    allowed_methods=[
                        s3.HttpMethods.GET,
                        s3.HttpMethods.PUT,
                        s3.HttpMethods.POST,
                        s3.HttpMethods.DELETE,
                    ],
                    allowed_origins=["*"],
                    allowed_headers=["*"],
                    max_age=3000,
                )
            ],
        )

        # EventBridge event bus (use default)
        self.event_bus = events.EventBus.from_event_bus_name(
            self,
            "DefaultEventBus",
            "default",
        )

    def _create_api_lambda(self):
        """Create API Lambda function (FastAPI + Mangum) using Docker image."""
        # Get ECR repository
        api_repo = ecr.Repository.from_repository_name(
            self,
            "APIRepository",
            f"collections-api-{self.env_name}"
        )

        self.api_lambda = lambda_.DockerImageFunction(
            self,
            "APILambda",
            code=lambda_.DockerImageCode.from_ecr(
                repository=api_repo,
                tag_or_digest="latest"
            ),
            timeout=Duration.seconds(self.env_config["lambda_timeout_api"]),
            memory_size=self.env_config["lambda_memory_api"],
            environment=self.common_env,
            log_retention=self._get_log_retention(self.env_config["log_retention_days"]),
            description=f"Collections API Lambda - {self.env_name}",
        )

        # Grant permissions
        self.checkpoint_table.grant_read_write_data(self.api_lambda)
        self.bucket.grant_read_write(self.api_lambda)
        self.db_credentials.grant_read(self.api_lambda)

        # Grant Parameter Store access
        self.api_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter", "ssm:GetParameters"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/collections/*"
                ],
            )
        )

    def _create_image_processor_lambda(self):
        """Create Image Processor Lambda (S3 trigger)."""
        import os
        # Get path to image_processor Lambda directory
        lambda_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "..",
            "lambdas",
            "image_processor"
        )

        self.image_processor_lambda = lambda_.Function(
            self,
            "ImageProcessorLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(lambda_path),
            timeout=Duration.seconds(self.env_config["lambda_timeout_processor"]),
            memory_size=self.env_config["lambda_memory_processor"],
            environment=self.common_env,
            log_retention=self._get_log_retention(self.env_config["log_retention_days"]),
            description=f"Image processor Lambda - {self.env_name}",
        )

        # Grant permissions
        self.bucket.grant_read_write(self.image_processor_lambda)

        # Grant EventBridge publish permissions
        self.image_processor_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["events:PutEvents"],
                resources=[self.event_bus.event_bus_arn],
            )
        )

    def _create_analyzer_lambda(self):
        """Create Analyzer Lambda (EventBridge trigger)."""
        import os
        # Get path to analyzer Lambda directory
        lambda_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "..",
            "lambdas",
            "analyzer"
        )

        self.analyzer_lambda = lambda_.Function(
            self,
            "AnalyzerLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(lambda_path),
            timeout=Duration.seconds(self.env_config["lambda_timeout_analyzer"]),
            memory_size=self.env_config["lambda_memory_analyzer"],
            environment=self.common_env,
            log_retention=self._get_log_retention(self.env_config["log_retention_days"]),
            description=f"Image analyzer Lambda - {self.env_name}",
        )

        # Grant permissions
        self.bucket.grant_read(self.analyzer_lambda)
        self.db_credentials.grant_read(self.analyzer_lambda)

        # Grant Parameter Store access for API keys
        self.analyzer_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter", "ssm:GetParameters"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/collections/*"
                ],
            )
        )

        # Grant EventBridge publish permissions
        self.analyzer_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["events:PutEvents"],
                resources=[self.event_bus.event_bus_arn],
            )
        )

    def _create_embedder_lambda(self):
        """Create Embedder Lambda (EventBridge trigger) using Docker image."""
        # Get ECR repository
        embedder_repo = ecr.Repository.from_repository_name(
            self,
            "EmbedderRepository",
            f"collections-embedder-{self.env_name}"
        )

        self.embedder_lambda = lambda_.DockerImageFunction(
            self,
            "EmbedderLambda",
            code=lambda_.DockerImageCode.from_ecr(
                repository=embedder_repo,
                tag_or_digest="latest"
            ),
            timeout=Duration.seconds(self.env_config["lambda_timeout_embedder"]),
            memory_size=self.env_config["lambda_memory_embedder"],
            environment=self.common_env,
            log_retention=self._get_log_retention(self.env_config["log_retention_days"]),
            description=f"Embedding generator Lambda - {self.env_name}",
        )

        # Grant permissions
        self.db_credentials.grant_read(self.embedder_lambda)

        # Grant Parameter Store access for API keys
        self.embedder_lambda.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter", "ssm:GetParameters"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/collections/*"
                ],
            )
        )

    def _create_cleanup_lambda(self):
        """
        Create Cleanup Lambda (EventBridge cron trigger).

        This Lambda monitors DynamoDB TTL-based cleanup of expired sessions.
        Actual deletion is handled automatically by DynamoDB's TTL feature.
        """
        import os
        # Get path relative to infrastructure directory
        lambda_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "lambdas", "cleanup")

        self.cleanup_lambda = lambda_.Function(
            self,
            "CleanupLambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(lambda_path),
            timeout=Duration.seconds(self.env_config["lambda_timeout_cleanup"]),
            memory_size=self.env_config["lambda_memory_cleanup"],
            environment=self.common_env,
            log_retention=self._get_log_retention(self.env_config["log_retention_days"]),
            description=f"Conversation cleanup monitoring Lambda - {self.env_name}",
        )

        # Grant read-only access to DynamoDB for monitoring
        self.checkpoint_table.grant_read_data(self.cleanup_lambda)

    def _create_eventbridge_rules(self):
        """Create EventBridge rules for workflow orchestration."""
        # Rule 1: ImageProcessed → Analyzer Lambda
        self.image_processed_rule = events.Rule(
            self,
            "ImageProcessedRule",
            event_bus=self.event_bus,
            event_pattern=events.EventPattern(
                source=["collections.imageprocessor"],
                detail_type=["ImageProcessed"],
            ),
            description="Trigger analyzer when image is processed",
        )
        self.image_processed_rule.add_target(targets.LambdaFunction(self.analyzer_lambda))

        # Rule 2: AnalysisComplete → Embedder Lambda
        self.analysis_complete_rule = events.Rule(
            self,
            "AnalysisCompleteRule",
            event_bus=self.event_bus,
            event_pattern=events.EventPattern(
                source=["collections.analyzer"],
                detail_type=["AnalysisComplete"],
            ),
            description="Trigger embedder when analysis is complete",
        )
        self.analysis_complete_rule.add_target(targets.LambdaFunction(self.embedder_lambda))

        # Rule 3: Hourly cleanup schedule
        self.cleanup_schedule_rule = events.Rule(
            self,
            "CleanupScheduleRule",
            schedule=events.Schedule.rate(Duration.hours(1)),
            description="Hourly cleanup monitoring",
        )
        self.cleanup_schedule_rule.add_target(targets.LambdaFunction(self.cleanup_lambda))

    def _create_s3_notifications(self):
        """
        Create S3 event notifications to trigger Image Processor Lambda.

        Note: S3 notifications are configured here instead of in StorageStack
        to avoid circular dependencies.
        """
        # S3 → Lambda notification for new image uploads
        self.bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(self.image_processor_lambda),
            s3.NotificationKeyFilter(
                prefix="",  # All prefixes
                suffix=".jpg",  # Only JPG files (extend to other formats as needed)
            ),
        )

        self.bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(self.image_processor_lambda),
            s3.NotificationKeyFilter(
                prefix="",
                suffix=".png",
            ),
        )

        self.bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(self.image_processor_lambda),
            s3.NotificationKeyFilter(
                prefix="",
                suffix=".jpeg",
            ),
        )

    def _create_outputs(self):
        """Create CloudFormation outputs."""
        CfnOutput(
            self,
            "APILambdaArn",
            value=self.api_lambda.function_arn,
            description="API Lambda function ARN",
            export_name=f"collections-{self.env_name}-api-lambda-arn",
        )

        CfnOutput(
            self,
            "APILambdaName",
            value=self.api_lambda.function_name,
            description="API Lambda function name",
            export_name=f"collections-{self.env_name}-api-lambda-name",
        )

        CfnOutput(
            self,
            "ImageProcessorLambdaArn",
            value=self.image_processor_lambda.function_arn,
            description="Image processor Lambda ARN",
            export_name=f"collections-{self.env_name}-processor-lambda-arn",
        )

        CfnOutput(
            self,
            "AnalyzerLambdaArn",
            value=self.analyzer_lambda.function_arn,
            description="Analyzer Lambda ARN",
            export_name=f"collections-{self.env_name}-analyzer-lambda-arn",
        )

        CfnOutput(
            self,
            "EmbedderLambdaArn",
            value=self.embedder_lambda.function_arn,
            description="Embedder Lambda ARN",
            export_name=f"collections-{self.env_name}-embedder-lambda-arn",
        )

        CfnOutput(
            self,
            "CleanupLambdaArn",
            value=self.cleanup_lambda.function_arn,
            description="Cleanup Lambda ARN",
            export_name=f"collections-{self.env_name}-cleanup-lambda-arn",
        )

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
