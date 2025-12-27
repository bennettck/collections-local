#!/usr/bin/env python3
"""
CDK Application for Collections Local AWS Migration.

Deploys complete serverless infrastructure for collections-local application.

Usage:
    cdk synth --context env=dev
    cdk deploy --context env=dev --all
    cdk destroy --context env=dev --all

Environment: dev, test, or prod (default: dev)
"""

import os
from aws_cdk import App, Environment, Tags

from stacks.database_stack import DatabaseStack
from stacks.storage_stack import StorageStack
from stacks.compute_stack import ComputeStack
from stacks.api_stack import ApiStack
from stacks.monitoring_stack import MonitoringStack

# Initialize CDK app
app = App()

# Get environment from context or environment variable
env_name = app.node.try_get_context("env") or os.getenv("CDK_ENV", "dev")

# Get environment configuration
env_config = app.node.try_get_context("environments").get(env_name)

if not env_config:
    raise ValueError(
        f"Environment '{env_name}' not found in cdk.context.json. "
        "Available: dev, test, prod"
    )

# Update account ID if provided via environment variable
account_id = os.getenv("CDK_DEFAULT_ACCOUNT") or env_config["account"]
region = os.getenv("CDK_DEFAULT_REGION") or env_config["region"]

# Define AWS environment
aws_env = Environment(
    account=account_id,
    region=region,
)

print(f"Deploying to environment: {env_name}")
print(f"AWS Account: {account_id}")
print(f"AWS Region: {region}")

# ============================================================================
# Deploy Stacks in Dependency Order
# ============================================================================

# 1. Database Stack (RDS + DynamoDB)
db_stack = DatabaseStack(
    app,
    f"CollectionsDB-{env_name}",
    env=aws_env,
    env_name=env_name,
    env_config=env_config,
    description=f"Collections Database Stack - {env_name}",
)

# 2. Compute Stack (Lambda functions + S3 Storage)
# Note: S3 bucket is created within ComputeStack to avoid circular dependencies
compute_stack = ComputeStack(
    app,
    f"CollectionsCompute-{env_name}",
    env=aws_env,
    env_name=env_name,
    env_config=env_config,
    database=db_stack.database,
    checkpoint_table=db_stack.checkpoint_table,
    db_credentials=db_stack.db_credentials,
    description=f"Collections Compute Stack - {env_name}",
)

# 3. API Stack (API Gateway + Cognito)
api_stack = ApiStack(
    app,
    f"CollectionsAPI-{env_name}",
    env=aws_env,
    env_name=env_name,
    env_config=env_config,
    api_lambda=compute_stack.api_lambda,
    description=f"Collections API Stack - {env_name}",
)

# 4. Monitoring Stack (CloudWatch)
monitoring_stack = MonitoringStack(
    app,
    f"CollectionsMonitoring-{env_name}",
    env=aws_env,
    env_name=env_name,
    env_config=env_config,
    http_api=api_stack.http_api,
    lambdas=compute_stack.all_lambdas,
    database=db_stack.database,
    checkpoint_table=db_stack.checkpoint_table,
    create_alarms=env_name != "dev",  # No alarms in dev
    description=f"Collections Monitoring Stack - {env_name}",
)

# ============================================================================
# Add Common Tags
# ============================================================================

Tags.of(app).add("Environment", env_name)
Tags.of(app).add("Project", "collections-local")
Tags.of(app).add("ManagedBy", "CDK")
Tags.of(app).add("Repository", "https://github.com/bennettck/collections-local")

# ============================================================================
# Synthesize CloudFormation Templates
# ============================================================================

app.synth()
