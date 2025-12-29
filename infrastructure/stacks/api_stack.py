"""API stack: API Gateway + Cognito authentication."""

from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    aws_apigatewayv2 as apigw,
    aws_apigatewayv2_integrations as apigw_integrations,
    aws_apigatewayv2_authorizers as apigw_authorizers,
    aws_cognito as cognito,
    aws_lambda as lambda_,
)
from constructs import Construct
from typing import Dict, Any


class ApiStack(Stack):
    """
    API infrastructure stack.

    Components:
    - Cognito User Pool for authentication
    - Cognito User Pool Client
    - API Gateway HTTP API
    - Lambda integration
    - JWT authorizer
    - CORS configuration
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        env_config: Dict[str, Any] = None,
        api_lambda: lambda_.Function,
        **kwargs
    ):
        """
        Initialize API stack.

        Args:
            scope: CDK app
            construct_id: Stack ID
            env_name: Environment name (dev/test/prod)
            env_config: Environment-specific configuration
            api_lambda: API Lambda function
            **kwargs: Additional stack properties
        """
        super().__init__(scope, construct_id, **kwargs)

        self.env_name = env_name
        self.env_config = env_config or {}
        self.api_lambda = api_lambda

        # Create Cognito User Pool
        self._create_cognito_user_pool()

        # Create API Gateway
        self._create_api_gateway()

        # Stack outputs
        self._create_outputs()

    def _create_cognito_user_pool(self):
        """Create Cognito User Pool for user authentication."""
        # User Pool
        self.user_pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name=f"collections-{self.env_name}",
            self_sign_up_enabled=False,  # Admin creates users
            sign_in_aliases=cognito.SignInAliases(
                email=True,
                username=False,
            ),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(
                    required=True,
                    mutable=True,
                )
            ),
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=False,
            ),
            mfa=cognito.Mfa.OPTIONAL,  # Optional MFA
            mfa_second_factor=cognito.MfaSecondFactor(
                sms=False,
                otp=True,
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
        )

        # User Pool Client
        self.user_pool_client = self.user_pool.add_client(
            "UserPoolClient",
            user_pool_client_name=f"collections-{self.env_name}-client",
            auth_flows=cognito.AuthFlow(
                user_password=True,  # Enable USER_PASSWORD_AUTH
                user_srp=True,
                admin_user_password=True,
            ),
            generate_secret=False,  # No client secret for public clients
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(30),
            prevent_user_existence_errors=True,
        )

    def _create_api_gateway(self):
        """Create API Gateway HTTP API with Lambda integration."""
        # Lambda integration
        lambda_integration = apigw_integrations.HttpLambdaIntegration(
            "APILambdaIntegration",
            self.api_lambda,
            payload_format_version=apigw.PayloadFormatVersion.VERSION_2_0,
        )

        # HTTP API
        self.http_api = apigw.HttpApi(
            self,
            "HttpApi",
            api_name=f"collections-{self.env_name}",
            description=f"Collections API - {self.env_name}",
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=["*"],  # Configure based on frontend domain
                allow_methods=[
                    apigw.CorsHttpMethod.GET,
                    apigw.CorsHttpMethod.POST,
                    apigw.CorsHttpMethod.PUT,
                    apigw.CorsHttpMethod.DELETE,
                    apigw.CorsHttpMethod.OPTIONS,
                ],
                allow_headers=[
                    "Content-Type",
                    "Authorization",
                    "X-Amz-Date",
                    "X-Api-Key",
                    "X-Amz-Security-Token",
                ],
                max_age=Duration.hours(1),
            ),
            default_integration=lambda_integration,
        )

        # JWT Authorizer (Cognito)
        self.authorizer = apigw_authorizers.HttpJwtAuthorizer(
            "CognitoAuthorizer",
            f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool.user_pool_id}",
            jwt_audience=[self.user_pool_client.user_pool_client_id],
        )

        # Add catch-all route with authorization
        # Note: Health check endpoint should be public (handled in Lambda)
        self.http_api.add_routes(
            path="/{proxy+}",
            methods=[
                apigw.HttpMethod.ANY,
            ],
            integration=lambda_integration,
            authorizer=self.authorizer,
        )

        # Add public route for health checks
        self.http_api.add_routes(
            path="/health",
            methods=[apigw.HttpMethod.GET],
            integration=lambda_integration,
            # No authorizer for health endpoint
        )

        # Add public route for version info
        self.http_api.add_routes(
            path="/version",
            methods=[apigw.HttpMethod.GET],
            integration=lambda_integration,
            # No authorizer for version endpoint
        )

    def _create_outputs(self):
        """Create CloudFormation outputs."""
        CfnOutput(
            self,
            "UserPoolId",
            value=self.user_pool.user_pool_id,
            description="Cognito User Pool ID",
            export_name=f"collections-{self.env_name}-user-pool-id",
        )

        CfnOutput(
            self,
            "UserPoolArn",
            value=self.user_pool.user_pool_arn,
            description="Cognito User Pool ARN",
            export_name=f"collections-{self.env_name}-user-pool-arn",
        )

        CfnOutput(
            self,
            "UserPoolClientId",
            value=self.user_pool_client.user_pool_client_id,
            description="Cognito User Pool Client ID",
            export_name=f"collections-{self.env_name}-user-pool-client-id",
        )

        CfnOutput(
            self,
            "ApiEndpoint",
            value=self.http_api.url or "",
            description="API Gateway endpoint URL",
            export_name=f"collections-{self.env_name}-api-endpoint",
        )

        CfnOutput(
            self,
            "ApiId",
            value=self.http_api.http_api_id,
            description="API Gateway ID",
            export_name=f"collections-{self.env_name}-api-id",
        )

        CfnOutput(
            self,
            "Region",
            value=self.region,
            description="AWS Region",
            export_name=f"collections-{self.env_name}-region",
        )
