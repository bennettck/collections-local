"""Database stack: RDS PostgreSQL + DynamoDB for LangGraph checkpoints."""

from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    aws_rds as rds,
    aws_ec2 as ec2,
    aws_dynamodb as dynamodb,
    aws_secretsmanager as secretsmanager,
    aws_ssm as ssm,
)
from constructs import Construct
from typing import Dict, Any


class DatabaseStack(Stack):
    """
    Database infrastructure stack.

    Components:
    - RDS PostgreSQL 16 with pgvector extension (public access for dev)
    - DynamoDB table for LangGraph conversation checkpoints
    - Security groups and network configuration
    - Parameter Store entries for database credentials
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        env_config: Dict[str, Any],
        **kwargs
    ):
        """
        Initialize database stack.

        Args:
            scope: CDK app
            construct_id: Stack ID
            env_name: Environment name (dev/test/prod)
            env_config: Environment-specific configuration
            **kwargs: Additional stack properties
        """
        super().__init__(scope, construct_id, **kwargs)

        self.env_name = env_name
        self.env_config = env_config

        # Create PostgreSQL database
        self._create_rds_database()

        # Create DynamoDB table for checkpoints
        self._create_dynamodb_table()

        # Create Parameter Store entries
        self._create_parameter_store_entries()

        # Stack outputs
        self._create_outputs()

    def _create_rds_database(self):
        """Create RDS PostgreSQL instance with pgvector extension."""
        # Create VPC for the infrastructure
        # Note: RDS requires at least 2 AZs even for single-AZ databases
        self.vpc = ec2.Vpc(
            self,
            "VPC",
            max_azs=2,  # Always use 2 AZs (RDS requirement)
            nat_gateways=0,  # No NAT gateways to save costs (use public subnets)
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                )
            ],
        )

        # Database credentials
        self.db_credentials = rds.DatabaseSecret(
            self,
            "DBCredentials",
            username="postgres",
            secret_name=f"collections-db-{self.env_name}",
        )

        # Security group for RDS (public access)
        self.db_security_group = ec2.SecurityGroup(
            self,
            "DBSecurityGroup",
            vpc=self.vpc,
            description=f"Security group for Collections RDS - {self.env_name}",
            allow_all_outbound=True,
        )

        # Allow PostgreSQL access from anywhere (dev only - restrict in prod)
        if self.env_name == "dev":
            self.db_security_group.add_ingress_rule(
                ec2.Peer.any_ipv4(),
                ec2.Port.tcp(5432),
                "Allow PostgreSQL from anywhere (DEV ONLY)",
            )
        else:
            # In test/prod, only allow from specific IPs (configure via context)
            # For now, allow from anywhere but should be restricted
            self.db_security_group.add_ingress_rule(
                ec2.Peer.any_ipv4(),
                ec2.Port.tcp(5432),
                "PostgreSQL access - RESTRICT IN PRODUCTION",
            )

        # RDS PostgreSQL instance
        self.database = rds.DatabaseInstance(
            self,
            "PostgreSQLInstance",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_16
            ),
            instance_type=ec2.InstanceType(self.env_config["rds_instance_class"]),
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            credentials=rds.Credentials.from_secret(self.db_credentials),
            database_name="collections",
            allocated_storage=self.env_config["rds_allocated_storage"],
            max_allocated_storage=self.env_config.get("rds_max_allocated_storage", 100),
            storage_type=rds.StorageType.GP3,
            security_groups=[self.db_security_group],
            publicly_accessible=True,  # Public for simplified architecture
            deletion_protection=self.env_config["enable_deletion_protection"],
            backup_retention=Duration.days(self.env_config.get("backup_retention_days", 0)),
            multi_az=self.env_config.get("multi_az", False),
            removal_policy=RemovalPolicy.SNAPSHOT if self.env_name == "prod" else RemovalPolicy.DESTROY,
            parameter_group=rds.ParameterGroup(
                self,
                "DBParameterGroup",
                engine=rds.DatabaseInstanceEngine.postgres(
                    version=rds.PostgresEngineVersion.VER_16
                ),
                parameters={
                    # Optimize for pgvector workloads
                    # Note: pgvector doesn't need shared_preload_libraries
                    "max_connections": "100",
                    "work_mem": "16384",  # 16MB in KB
                },
            ),
        )

        # Custom resource to install pgvector extension
        # Note: This requires a Lambda-backed custom resource
        # For now, document manual installation step
        # TODO: Add Lambda custom resource for: CREATE EXTENSION IF NOT EXISTS vector;

    def _create_dynamodb_table(self):
        """Create DynamoDB table for LangGraph conversation checkpoints."""
        self.checkpoint_table = dynamodb.Table(
            self,
            "CheckpointTable",
            table_name=f"collections-checkpoints-{self.env_name}",
            partition_key=dynamodb.Attribute(
                name="thread_id",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="checkpoint_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,  # On-demand pricing
            time_to_live_attribute="expires_at",  # TTL for automatic cleanup
            point_in_time_recovery=self.env_name == "prod",  # PITR for prod only
            removal_policy=RemovalPolicy.RETAIN if self.env_name == "prod" else RemovalPolicy.DESTROY,
        )

        # Global Secondary Index for querying user sessions
        self.checkpoint_table.add_global_secondary_index(
            index_name="user_id-last_activity-index",
            partition_key=dynamodb.Attribute(
                name="user_id",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="last_activity",
                type=dynamodb.AttributeType.NUMBER,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

    def _create_parameter_store_entries(self):
        """Create Parameter Store entries for secrets."""
        # Database URL parameter
        database_url = (
            f"postgresql://{self.db_credentials.secret_value_from_json('username').unsafe_unwrap()}:"
            f"{self.db_credentials.secret_value_from_json('password').unsafe_unwrap()}@"
            f"{self.database.db_instance_endpoint_address}:{self.database.db_instance_endpoint_port}/"
            f"collections?sslmode=require"
        )

        self.database_url_parameter = ssm.StringParameter(
            self,
            "DatabaseURLParameter",
            parameter_name="/collections/database-url",
            string_value=database_url,
            description="PostgreSQL connection URL",
            tier=ssm.ParameterTier.STANDARD,
        )

        # Placeholder parameters for API keys (will be populated manually)
        self.api_key_parameters = {
            "anthropic": ssm.StringParameter(
                self,
                "AnthropicAPIKeyParam",
                parameter_name="/collections/anthropic-api-key",
                string_value="PLACEHOLDER",
                description="Anthropic API Key",
                tier=ssm.ParameterTier.STANDARD,
            ),
            "openai": ssm.StringParameter(
                self,
                "OpenAIAPIKeyParam",
                parameter_name="/collections/openai-api-key",
                string_value="PLACEHOLDER",
                description="OpenAI API Key",
                tier=ssm.ParameterTier.STANDARD,
            ),
            "voyage": ssm.StringParameter(
                self,
                "VoyageAPIKeyParam",
                parameter_name="/collections/voyage-api-key",
                string_value="PLACEHOLDER",
                description="Voyage AI API Key",
                tier=ssm.ParameterTier.STANDARD,
            ),
            "tavily": ssm.StringParameter(
                self,
                "TavilyAPIKeyParam",
                parameter_name="/collections/tavily-api-key",
                string_value="PLACEHOLDER",
                description="Tavily API Key",
                tier=ssm.ParameterTier.STANDARD,
            ),
            "langsmith": ssm.StringParameter(
                self,
                "LangSmithAPIKeyParam",
                parameter_name="/collections/langsmith-api-key",
                string_value="PLACEHOLDER",
                description="LangSmith API Key",
                tier=ssm.ParameterTier.STANDARD,
            ),
        }

    def _create_outputs(self):
        """Create CloudFormation outputs."""
        CfnOutput(
            self,
            "RDSEndpoint",
            value=self.database.db_instance_endpoint_address,
            description="RDS PostgreSQL endpoint",
            export_name=f"collections-{self.env_name}-rds-endpoint",
        )

        CfnOutput(
            self,
            "RDSPort",
            value=str(self.database.db_instance_endpoint_port),
            description="RDS PostgreSQL port",
            export_name=f"collections-{self.env_name}-rds-port",
        )

        CfnOutput(
            self,
            "DatabaseName",
            value="collections",
            description="Database name",
            export_name=f"collections-{self.env_name}-db-name",
        )

        CfnOutput(
            self,
            "DatabaseSecretArn",
            value=self.db_credentials.secret_arn,
            description="Database credentials secret ARN",
            export_name=f"collections-{self.env_name}-db-secret-arn",
        )

        CfnOutput(
            self,
            "CheckpointTableName",
            value=self.checkpoint_table.table_name,
            description="DynamoDB checkpoint table name",
            export_name=f"collections-{self.env_name}-checkpoint-table",
        )

        CfnOutput(
            self,
            "CheckpointTableArn",
            value=self.checkpoint_table.table_arn,
            description="DynamoDB checkpoint table ARN",
            export_name=f"collections-{self.env_name}-checkpoint-table-arn",
        )
