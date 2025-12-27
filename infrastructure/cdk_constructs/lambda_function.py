"""Reusable Lambda function construct with best practices."""

from aws_cdk import (
    Duration,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_iam as iam,
)
from constructs import Construct
from typing import Dict, List, Optional


class LambdaFunction(Construct):
    """
    Reusable Lambda function construct with standard configurations.

    Features:
    - CloudWatch log group with configurable retention
    - Standard IAM permissions
    - Environment variables
    - Timeout and memory configuration
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        runtime: lambda_.Runtime = lambda_.Runtime.PYTHON_3_12,
        handler: str,
        code: lambda_.Code,
        timeout: Duration,
        memory_size: int,
        environment: Optional[Dict[str, str]] = None,
        log_retention: logs.RetentionDays = logs.RetentionDays.ONE_WEEK,
        description: Optional[str] = None,
        layers: Optional[List[lambda_.ILayerVersion]] = None,
        **kwargs
    ):
        """
        Initialize Lambda function construct.

        Args:
            scope: CDK scope
            construct_id: Construct identifier
            runtime: Lambda runtime
            handler: Function handler
            code: Lambda code
            timeout: Function timeout
            memory_size: Memory allocation in MB
            environment: Environment variables
            log_retention: CloudWatch log retention
            description: Function description
            layers: Lambda layers
            **kwargs: Additional Lambda function properties
        """
        super().__init__(scope, construct_id)

        # Create Lambda function
        self.function = lambda_.Function(
            self,
            "Function",
            runtime=runtime,
            handler=handler,
            code=code,
            timeout=timeout,
            memory_size=memory_size,
            environment=environment or {},
            description=description,
            layers=layers,
            log_retention=log_retention,
            **kwargs
        )

        # Grant Lambda basic execution permissions
        self.function.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=["*"],
            )
        )

    def grant_parameter_store_read(self, parameter_prefix: str):
        """Grant permission to read Parameter Store parameters."""
        self.function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter", "ssm:GetParameters"],
                resources=[
                    f"arn:aws:ssm:{self.function.env.region}:{self.function.env.account}:parameter{parameter_prefix}*"
                ],
            )
        )

    def grant_secrets_manager_read(self, secret_arns: List[str]):
        """Grant permission to read Secrets Manager secrets."""
        self.function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=secret_arns,
            )
        )
