"""Monitoring stack: CloudWatch dashboards and alarms."""

from aws_cdk import (
    Stack,
    Duration,
    aws_cloudwatch as cloudwatch,
    aws_lambda as lambda_,
    aws_apigatewayv2 as apigw,
    aws_rds as rds,
    aws_dynamodb as dynamodb,
    aws_sns as sns,
    aws_cloudwatch_actions as cw_actions,
)
from constructs import Construct
from typing import Dict, Any, List, Optional


class MonitoringStack(Stack):
    """
    Monitoring infrastructure stack.

    Components:
    - CloudWatch Dashboard with key metrics
    - CloudWatch Alarms for critical metrics
    - SNS topic for alarm notifications (optional)
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        env_name: str,
        env_config: Dict[str, Any] = None,
        http_api: apigw.HttpApi,
        lambdas: List[lambda_.Function],
        database: rds.DatabaseInstance,
        checkpoint_table: dynamodb.Table,
        create_alarms: bool = True,
        **kwargs
    ):
        """
        Initialize monitoring stack.

        Args:
            scope: CDK app
            construct_id: Stack ID
            env_name: Environment name (dev/test/prod)
            env_config: Environment-specific configuration
            http_api: API Gateway HTTP API
            lambdas: List of Lambda functions to monitor
            database: RDS database instance
            checkpoint_table: DynamoDB checkpoint table
            create_alarms: Whether to create CloudWatch alarms
            **kwargs: Additional stack properties
        """
        super().__init__(scope, construct_id, **kwargs)

        self.env_name = env_name
        self.env_config = env_config or {}
        self.http_api = http_api
        self.lambdas = lambdas
        self.database = database
        self.checkpoint_table = checkpoint_table

        # Create SNS topic for alarms (optional)
        if create_alarms:
            self._create_alarm_topic()

        # Create CloudWatch Dashboard
        self._create_dashboard()

        # Create CloudWatch Alarms
        if create_alarms:
            self._create_alarms()

    def _create_alarm_topic(self):
        """Create SNS topic for alarm notifications."""
        self.alarm_topic = sns.Topic(
            self,
            "AlarmTopic",
            topic_name=f"collections-{self.env_name}-alarms",
            display_name=f"Collections Alarms - {self.env_name}",
        )

    def _create_dashboard(self):
        """Create CloudWatch Dashboard with key metrics."""
        self.dashboard = cloudwatch.Dashboard(
            self,
            "Dashboard",
            dashboard_name=f"Collections-{self.env_name}",
        )

        # API Gateway Metrics
        api_widget = cloudwatch.GraphWidget(
            title="API Gateway Metrics",
            left=[
                cloudwatch.Metric(
                    namespace="AWS/ApiGateway",
                    metric_name="Count",
                    dimensions_map={"ApiId": self.http_api.http_api_id},
                    statistic="Sum",
                    label="Total Requests",
                ),
                cloudwatch.Metric(
                    namespace="AWS/ApiGateway",
                    metric_name="4XXError",
                    dimensions_map={"ApiId": self.http_api.http_api_id},
                    statistic="Sum",
                    label="4XX Errors",
                ),
                cloudwatch.Metric(
                    namespace="AWS/ApiGateway",
                    metric_name="5XXError",
                    dimensions_map={"ApiId": self.http_api.http_api_id},
                    statistic="Sum",
                    label="5XX Errors",
                ),
            ],
            right=[
                cloudwatch.Metric(
                    namespace="AWS/ApiGateway",
                    metric_name="Latency",
                    dimensions_map={"ApiId": self.http_api.http_api_id},
                    statistic="Average",
                    label="Avg Latency",
                )
            ],
        )

        # Lambda Metrics
        lambda_invocations = []
        lambda_errors = []
        lambda_durations = []

        for func in self.lambdas:
            lambda_invocations.append(
                cloudwatch.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Invocations",
                    dimensions_map={"FunctionName": func.function_name},
                    statistic="Sum",
                    label=f"{func.function_name}",
                )
            )
            lambda_errors.append(
                cloudwatch.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Errors",
                    dimensions_map={"FunctionName": func.function_name},
                    statistic="Sum",
                    label=f"{func.function_name}",
                )
            )
            lambda_durations.append(
                cloudwatch.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Duration",
                    dimensions_map={"FunctionName": func.function_name},
                    statistic="Average",
                    label=f"{func.function_name}",
                )
            )

        lambda_invocations_widget = cloudwatch.GraphWidget(
            title="Lambda Invocations",
            left=lambda_invocations,
        )

        lambda_errors_widget = cloudwatch.GraphWidget(
            title="Lambda Errors",
            left=lambda_errors,
        )

        lambda_duration_widget = cloudwatch.GraphWidget(
            title="Lambda Duration (ms)",
            left=lambda_durations,
        )

        # RDS Metrics
        rds_widget = cloudwatch.GraphWidget(
            title="RDS Metrics",
            left=[
                cloudwatch.Metric(
                    namespace="AWS/RDS",
                    metric_name="DatabaseConnections",
                    dimensions_map={"DBInstanceIdentifier": self.database.instance_identifier},
                    statistic="Average",
                    label="DB Connections",
                ),
                cloudwatch.Metric(
                    namespace="AWS/RDS",
                    metric_name="CPUUtilization",
                    dimensions_map={"DBInstanceIdentifier": self.database.instance_identifier},
                    statistic="Average",
                    label="CPU %",
                ),
            ],
            right=[
                cloudwatch.Metric(
                    namespace="AWS/RDS",
                    metric_name="FreeStorageSpace",
                    dimensions_map={"DBInstanceIdentifier": self.database.instance_identifier},
                    statistic="Average",
                    label="Free Storage",
                )
            ],
        )

        # DynamoDB Metrics
        dynamodb_widget = cloudwatch.GraphWidget(
            title="DynamoDB Metrics",
            left=[
                cloudwatch.Metric(
                    namespace="AWS/DynamoDB",
                    metric_name="ConsumedReadCapacityUnits",
                    dimensions_map={"TableName": self.checkpoint_table.table_name},
                    statistic="Sum",
                    label="Read Capacity",
                ),
                cloudwatch.Metric(
                    namespace="AWS/DynamoDB",
                    metric_name="ConsumedWriteCapacityUnits",
                    dimensions_map={"TableName": self.checkpoint_table.table_name},
                    statistic="Sum",
                    label="Write Capacity",
                ),
            ],
        )

        # Add widgets to dashboard
        self.dashboard.add_widgets(api_widget)
        self.dashboard.add_widgets(
            lambda_invocations_widget,
            lambda_errors_widget,
        )
        self.dashboard.add_widgets(lambda_duration_widget)
        self.dashboard.add_widgets(rds_widget, dynamodb_widget)

    def _create_alarms(self):
        """Create CloudWatch Alarms for critical metrics."""
        # API Gateway 5XX Error Alarm
        api_5xx_alarm = cloudwatch.Alarm(
            self,
            "API5XXErrorAlarm",
            alarm_name=f"collections-{self.env_name}-api-5xx-errors",
            metric=cloudwatch.Metric(
                namespace="AWS/ApiGateway",
                metric_name="5XXError",
                dimensions_map={"ApiId": self.http_api.http_api_id},
                statistic="Sum",
                period=Duration.minutes(5),
            ),
            threshold=10,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        # Lambda Error Alarm (for API Lambda)
        if len(self.lambdas) > 0:
            api_lambda = self.lambdas[0]  # Assuming first is API Lambda
            lambda_error_alarm = cloudwatch.Alarm(
                self,
                "APILambdaErrorAlarm",
                alarm_name=f"collections-{self.env_name}-api-lambda-errors",
                metric=api_lambda.metric_errors(
                    period=Duration.minutes(5),
                    statistic="Sum",
                ),
                threshold=5,
                evaluation_periods=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            )

        # RDS CPU Alarm
        rds_cpu_alarm = cloudwatch.Alarm(
            self,
            "RDSCPUAlarm",
            alarm_name=f"collections-{self.env_name}-rds-cpu",
            metric=cloudwatch.Metric(
                namespace="AWS/RDS",
                metric_name="CPUUtilization",
                dimensions_map={"DBInstanceIdentifier": self.database.instance_identifier},
                statistic="Average",
                period=Duration.minutes(5),
            ),
            threshold=80,
            evaluation_periods=2,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        # RDS Storage Alarm
        rds_storage_alarm = cloudwatch.Alarm(
            self,
            "RDSStorageAlarm",
            alarm_name=f"collections-{self.env_name}-rds-storage",
            metric=cloudwatch.Metric(
                namespace="AWS/RDS",
                metric_name="FreeStorageSpace",
                dimensions_map={"DBInstanceIdentifier": self.database.instance_identifier},
                statistic="Average",
                period=Duration.minutes(5),
            ),
            threshold=1000000000,  # 1GB in bytes
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        # Add alarm actions if SNS topic exists
        if hasattr(self, "alarm_topic"):
            alarms = [
                api_5xx_alarm,
                rds_cpu_alarm,
                rds_storage_alarm,
            ]
            if hasattr(self, "lambda_error_alarm"):
                alarms.append(lambda_error_alarm)

            for alarm in alarms:
                alarm.add_alarm_action(cw_actions.SnsAction(self.alarm_topic))
