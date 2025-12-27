# Collections Local - AWS Infrastructure

AWS CDK infrastructure for the Collections Local application migration to serverless architecture.

## Architecture Overview

This infrastructure deploys a complete serverless stack on AWS:

- **Database**: RDS PostgreSQL 16 (with pgvector) + DynamoDB (LangGraph checkpoints)
- **Storage**: S3 bucket with EventBridge notifications
- **Compute**: 5 Lambda functions (API, Image Processor, Analyzer, Embedder, Cleanup)
- **API**: API Gateway HTTP API with Cognito authentication
- **Monitoring**: CloudWatch dashboards and alarms

## Prerequisites

1. **AWS Account**: Access to an AWS account with admin permissions
2. **AWS CLI**: Installed and configured
   ```bash
   aws configure
   ```

3. **AWS CDK**: Install CDK CLI
   ```bash
   npm install -g aws-cdk
   ```

4. **Python 3.12+**: For CDK application
   ```bash
   python3 --version
   ```

## Setup

### 1. Install Dependencies

```bash
cd infrastructure
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment

Update `cdk.context.json` with your AWS account ID:

```json
{
  "environments": {
    "dev": {
      "account": "YOUR_ACCOUNT_ID",
      ...
    }
  }
}
```

Or set via environment variables:

```bash
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export CDK_DEFAULT_REGION=us-east-1
```

### 3. Bootstrap CDK

Bootstrap your AWS account for CDK (one-time per account/region):

```bash
cdk bootstrap aws://$CDK_DEFAULT_ACCOUNT/us-east-1
```

## Deployment

### Deploy to Dev Environment

```bash
# Show what will be deployed
cdk synth --context env=dev

# Preview infrastructure changes
cdk diff --context env=dev --all

# Deploy all stacks
cdk deploy --context env=dev --all
```

### Deploy Individual Stacks

```bash
# Deploy only database stack
cdk deploy --context env=dev CollectionsDB-dev

# Deploy only storage stack
cdk deploy --context env=dev CollectionsStorage-dev
```

### Deploy to Other Environments

```bash
# Test environment
cdk deploy --context env=test --all

# Production environment
cdk deploy --context env=prod --all
```

## Post-Deployment Steps

### 1. Install pgvector Extension

Connect to RDS and install pgvector:

```bash
# Get RDS endpoint from CDK outputs
RDS_ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name CollectionsDB-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`RDSEndpoint`].OutputValue' \
  --output text)

# Get database password from Secrets Manager
DB_PASSWORD=$(aws secretsmanager get-secret-value \
  --secret-id collections-db-dev \
  --query SecretString \
  --output text | jq -r .password)

# Connect and install extension
psql -h $RDS_ENDPOINT -U postgres -d collections <<EOF
CREATE EXTENSION IF NOT EXISTS vector;
\dx
EOF
```

### 2. Populate Parameter Store Secrets

Update placeholder parameters with actual API keys:

```bash
# Anthropic API Key
aws ssm put-parameter \
  --name /collections/anthropic-api-key \
  --value "YOUR_ANTHROPIC_KEY" \
  --type SecureString \
  --overwrite

# OpenAI API Key
aws ssm put-parameter \
  --name /collections/openai-api-key \
  --value "YOUR_OPENAI_KEY" \
  --type SecureString \
  --overwrite

# Voyage AI API Key
aws ssm put-parameter \
  --name /collections/voyage-api-key \
  --value "YOUR_VOYAGE_KEY" \
  --type SecureString \
  --overwrite

# Tavily API Key
aws ssm put-parameter \
  --name /collections/tavily-api-key \
  --value "YOUR_TAVILY_KEY" \
  --type SecureString \
  --overwrite

# LangSmith API Key
aws ssm put-parameter \
  --name /collections/langsmith-api-key \
  --value "YOUR_LANGSMITH_KEY" \
  --type SecureString \
  --overwrite
```

### 3. Create Test User in Cognito

```bash
USER_POOL_ID=$(aws cloudformation describe-stacks \
  --stack-name CollectionsAPI-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' \
  --output text)

aws cognito-idp admin-create-user \
  --user-pool-id $USER_POOL_ID \
  --username testuser@example.com \
  --user-attributes Name=email,Value=testuser@example.com Name=email_verified,Value=true \
  --temporary-password TempPassword123!
```

## Stack Outputs

After deployment, retrieve stack outputs:

```bash
# Get API endpoint
aws cloudformation describe-stacks \
  --stack-name CollectionsAPI-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' \
  --output text

# Get all outputs as JSON
aws cloudformation describe-stacks \
  --stack-name CollectionsDB-dev \
  --query 'Stacks[0].Outputs' \
  --output json > .aws-outputs-dev.json
```

## Testing

### Health Check

```bash
API_URL=$(aws cloudformation describe-stacks \
  --stack-name CollectionsAPI-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' \
  --output text)

curl $API_URL/health
```

### Unit Tests

Run CDK unit tests:

```bash
cd infrastructure
pytest tests/unit/
```

## Cleanup

### Destroy Infrastructure

**Warning**: This will delete all resources. Data will be lost unless you have backups.

```bash
# Destroy all stacks in dev environment
cdk destroy --context env=dev --all

# Force destroy without confirmation
cdk destroy --context env=dev --all --force
```

## Costs

Estimated monthly costs for each environment:

- **Dev**: $20-30/month (db.t4g.micro, no backups, no multi-AZ)
- **Test**: $30-45/month (db.t4g.small, backups enabled)
- **Prod**: $65-98/month (db.t4g.small, multi-AZ, backups, alarms)

## Directory Structure

```
infrastructure/
├── app.py                          # Main CDK app
├── cdk.json                        # CDK configuration
├── cdk.context.json               # Environment settings
├── requirements.txt                # Python dependencies
├── README.md                       # This file
├── stacks/
│   ├── __init__.py
│   ├── database_stack.py          # RDS + DynamoDB
│   ├── storage_stack.py           # S3 + EventBridge
│   ├── compute_stack.py           # Lambda functions
│   ├── api_stack.py               # API Gateway + Cognito
│   └── monitoring_stack.py        # CloudWatch
├── constructs/
│   ├── __init__.py
│   ├── lambda_function.py         # Reusable Lambda construct
│   └── secret_parameter.py        # Parameter Store construct
└── tests/
    └── unit/                       # CDK unit tests
```

## Troubleshooting

### CDK Bootstrap Issues

If you encounter bootstrap errors:

```bash
cdk bootstrap aws://ACCOUNT_ID/REGION --force
```

### RDS Connection Issues

Check security group rules:

```bash
aws ec2 describe-security-groups \
  --filters Name=group-name,Values=CollectionsDB-dev* \
  --query 'SecurityGroups[0].IpPermissions'
```

### Lambda Function Logs

View Lambda logs:

```bash
aws logs tail /aws/lambda/CollectionsCompute-dev-APILambda --follow
```

## Support

For issues or questions:
- GitHub Issues: https://github.com/bennettck/collections-local/issues
- Documentation: See `/workspaces/collections-local/IMPLEMENTATION_PLAN.md`

## License

See main project LICENSE file.
