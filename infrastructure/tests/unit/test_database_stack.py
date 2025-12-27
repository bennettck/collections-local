"""Unit tests for DatabaseStack."""

import aws_cdk as cdk
from aws_cdk import assertions

from stacks.database_stack import DatabaseStack


def test_database_stack_creates_rds_instance():
    """Test that RDS PostgreSQL instance is created."""
    app = cdk.App()

    # Create stack
    stack = DatabaseStack(
        app,
        "TestDatabaseStack",
        env_name="dev",
        env_config={
            "rds_instance_class": "db.t4g.micro",
            "rds_allocated_storage": 20,
            "enable_deletion_protection": False,
            "enable_backup": False,
        },
    )

    # Prepare template for assertions
    template = assertions.Template.from_stack(stack)

    # Assert RDS instance exists
    template.resource_count_is("AWS::RDS::DBInstance", 1)

    # Assert database properties
    template.has_resource_properties(
        "AWS::RDS::DBInstance",
        {
            "Engine": "postgres",
            "DBInstanceClass": "db.t4g.micro",
            "AllocatedStorage": "20",
            "PubliclyAccessible": True,
        },
    )


def test_database_stack_creates_dynamodb_table():
    """Test that DynamoDB checkpoint table is created."""
    app = cdk.App()

    stack = DatabaseStack(
        app,
        "TestDatabaseStack",
        env_name="dev",
        env_config={
            "rds_instance_class": "db.t4g.micro",
            "rds_allocated_storage": 20,
            "enable_deletion_protection": False,
            "enable_backup": False,
        },
    )

    template = assertions.Template.from_stack(stack)

    # Assert DynamoDB table exists
    template.resource_count_is("AWS::DynamoDB::Table", 1)

    # Assert table properties
    template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "BillingMode": "PAY_PER_REQUEST",
            "TimeToLiveSpecification": {
                "AttributeName": "expires_at",
                "Enabled": True,
            },
            "KeySchema": assertions.Match.array_with([
                {"AttributeName": "thread_id", "KeyType": "HASH"},
                {"AttributeName": "checkpoint_id", "KeyType": "RANGE"},
            ]),
        },
    )


def test_database_stack_creates_parameter_store_entries():
    """Test that Parameter Store parameters are created."""
    app = cdk.App()

    stack = DatabaseStack(
        app,
        "TestDatabaseStack",
        env_name="dev",
        env_config={
            "rds_instance_class": "db.t4g.micro",
            "rds_allocated_storage": 20,
            "enable_deletion_protection": False,
            "enable_backup": False,
        },
    )

    template = assertions.Template.from_stack(stack)

    # Assert at least 6 SSM parameters (1 for DB URL + 5 for API keys)
    template.resource_count_is("AWS::SSM::Parameter", 6)


def test_database_stack_creates_security_group():
    """Test that RDS security group is created."""
    app = cdk.App()

    stack = DatabaseStack(
        app,
        "TestDatabaseStack",
        env_name="dev",
        env_config={
            "rds_instance_class": "db.t4g.micro",
            "rds_allocated_storage": 20,
            "enable_deletion_protection": False,
            "enable_backup": False,
        },
    )

    template = assertions.Template.from_stack(stack)

    # Assert security group exists
    template.resource_count_is("AWS::EC2::SecurityGroup", 1)


def test_database_stack_outputs():
    """Test that stack creates required outputs."""
    app = cdk.App()

    stack = DatabaseStack(
        app,
        "TestDatabaseStack",
        env_name="dev",
        env_config={
            "rds_instance_class": "db.t4g.micro",
            "rds_allocated_storage": 20,
            "enable_deletion_protection": False,
            "enable_backup": False,
        },
    )

    template = assertions.Template.from_stack(stack)

    # Assert outputs exist
    template.has_output("RDSEndpoint", {})
    template.has_output("RDSPort", {})
    template.has_output("DatabaseName", {})
    template.has_output("CheckpointTableName", {})
