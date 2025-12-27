"""Unit tests for ComputeStack."""

import aws_cdk as cdk
from aws_cdk import assertions, aws_rds as rds, aws_dynamodb as dynamodb, aws_s3 as s3, aws_events as events

from stacks.compute_stack import ComputeStack


def create_test_compute_stack(app):
    """Helper to create ComputeStack with mock dependencies."""
    # Create mock database
    db_stack = cdk.Stack(app, "MockDBStack")
    mock_database = rds.DatabaseInstance(
        db_stack,
        "MockDB",
        engine=rds.DatabaseInstanceEngine.postgres(version=rds.PostgresEngineVersion.VER_16),
        instance_type=cdk.aws_ec2.InstanceType("db.t4g.micro"),
        vpc=cdk.aws_ec2.Vpc(db_stack, "VPC"),
    )

    # Create mock DynamoDB table
    mock_table = dynamodb.Table(
        db_stack,
        "MockTable",
        partition_key=dynamodb.Attribute(name="id", type=dynamodb.AttributeType.STRING),
    )

    # Create mock S3 bucket
    mock_bucket = s3.Bucket(db_stack, "MockBucket")

    # Create mock event bus
    mock_event_bus = events.EventBus.from_event_bus_name(db_stack, "MockBus", "default")

    # Create ComputeStack
    stack = ComputeStack(
        app,
        "TestComputeStack",
        env_name="dev",
        env_config={
            "lambda_timeout_api": 30,
            "lambda_timeout_processor": 60,
            "lambda_timeout_analyzer": 120,
            "lambda_timeout_embedder": 60,
            "lambda_timeout_cleanup": 120,
            "lambda_memory_api": 2048,
            "lambda_memory_processor": 1024,
            "lambda_memory_analyzer": 1536,
            "lambda_memory_embedder": 1024,
            "lambda_memory_cleanup": 512,
            "log_retention_days": 7,
        },
        database=mock_database,
        checkpoint_table=mock_table,
        bucket=mock_bucket,
        event_bus=mock_event_bus,
        db_credentials=mock_database.secret,
    )

    return stack


def test_compute_stack_creates_five_lambda_functions():
    """Test that all 5 Lambda functions are created."""
    app = cdk.App()
    stack = create_test_compute_stack(app)

    template = assertions.Template.from_stack(stack)

    # Assert 5 Lambda functions exist
    template.resource_count_is("AWS::Lambda::Function", 5)


def test_compute_stack_creates_eventbridge_rules():
    """Test that EventBridge rules are created."""
    app = cdk.App()
    stack = create_test_compute_stack(app)

    template = assertions.Template.from_stack(stack)

    # Assert EventBridge rules exist (3 rules: ImageProcessed, AnalysisComplete, Cleanup schedule)
    template.resource_count_is("AWS::Events::Rule", 3)


def test_api_lambda_has_correct_memory():
    """Test that API Lambda has correct memory configuration."""
    app = cdk.App()
    stack = create_test_compute_stack(app)

    template = assertions.Template.from_stack(stack)

    # Assert at least one Lambda has 2048 MB memory (API Lambda)
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "MemorySize": 2048,
        },
    )


def test_compute_stack_outputs():
    """Test that stack creates required outputs."""
    app = cdk.App()
    stack = create_test_compute_stack(app)

    template = assertions.Template.from_stack(stack)

    # Assert outputs exist
    template.has_output("APILambdaArn", {})
    template.has_output("ImageProcessorLambdaArn", {})
    template.has_output("AnalyzerLambdaArn", {})
    template.has_output("EmbedderLambdaArn", {})
    template.has_output("CleanupLambdaArn", {})
