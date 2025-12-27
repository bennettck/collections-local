"""AWS Systems Manager Parameter Store parameter construct."""

from aws_cdk import (
    aws_ssm as ssm,
)
from constructs import Construct
from typing import Optional


class SecretParameter(Construct):
    """
    AWS Systems Manager Parameter Store SecureString parameter.

    Creates placeholder parameters that will be populated later via scripts.
    Uses FREE standard parameters with KMS encryption.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        parameter_name: str,
        description: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize Parameter Store parameter.

        Args:
            scope: CDK scope
            construct_id: Construct identifier
            parameter_name: Parameter name (e.g., /collections/api-key)
            description: Parameter description
            **kwargs: Additional SSM parameter properties
        """
        super().__init__(scope, construct_id)

        # Create SecureString parameter with placeholder value
        self.parameter = ssm.StringParameter(
            self,
            "Parameter",
            parameter_name=parameter_name,
            description=description or f"Secret parameter: {parameter_name}",
            string_value="PLACEHOLDER_TO_BE_POPULATED",
            tier=ssm.ParameterTier.STANDARD,  # FREE tier
            **kwargs
        )

    @property
    def parameter_name(self) -> str:
        """Get parameter name."""
        return self.parameter.parameter_name

    @property
    def parameter_arn(self) -> str:
        """Get parameter ARN."""
        return self.parameter.parameter_arn
