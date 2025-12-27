# Quick Start Guide - Collections Local AWS Infrastructure

Get the AWS infrastructure deployed in 5 steps.

## Prerequisites

- AWS Account with admin access
- AWS CLI configured (`aws configure`)
- Node.js 18+ (for CDK CLI)
- Python 3.12+

## Step 1: Update Account ID

Edit `cdk.context.json` and replace `PLACEHOLDER_ACCOUNT_ID` with your AWS account ID:

```bash
# Get your AWS account ID
aws sts get-caller-identity --query Account --output text

# Update cdk.context.json
# Change "account": "PLACEHOLDER_ACCOUNT_ID" to your actual account ID
```

Or set via environment variables:

```bash
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export CDK_DEFAULT_REGION=us-east-1
```

## Step 2: Install Dependencies

```bash
cd infrastructure

# Install CDK CLI globally (if not already installed)
npm install -g aws-cdk

# Install Python dependencies
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Step 3: Bootstrap CDK

One-time setup per AWS account/region:

```bash
cdk bootstrap aws://YOUR_ACCOUNT_ID/us-east-1
```

## Step 4: Deploy Infrastructure

```bash
# Preview what will be deployed
cdk synth --context env=dev

# Show infrastructure changes
cdk diff --context env=dev --all

# Deploy all stacks
cdk deploy --context env=dev --all
```

This will deploy 4 CloudFormation stacks:
1. CollectionsDB-dev (RDS + DynamoDB)
2. CollectionsCompute-dev (Lambdas + S3 + EventBridge)
3. CollectionsAPI-dev (API Gateway + Cognito)
4. CollectionsMonitoring-dev (CloudWatch)

Deployment takes ~15-20 minutes (RDS instance creation is the slowest).

## Step 5: Post-Deployment Setup

### 5.1 Install pgvector Extension

```bash
# Get RDS endpoint and password
RDS_ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name CollectionsDB-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`RDSEndpoint`].OutputValue' \
  --output text)

DB_SECRET=$(aws cloudformation describe-stacks \
  --stack-name CollectionsDB-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`DatabaseSecretArn`].OutputValue' \
  --output text)

DB_PASSWORD=$(aws secretsmanager get-secret-value \
  --secret-id $DB_SECRET \
  --query SecretString \
  --output text | jq -r .password)

# Connect and install pgvector
psql -h $RDS_ENDPOINT -U postgres -d collections <<EOF
CREATE EXTENSION IF NOT EXISTS vector;
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
EOF
```

### 5.2 Populate API Keys

```bash
# Update placeholder parameters with your actual API keys
aws ssm put-parameter \
  --name /collections/anthropic-api-key \
  --value "YOUR_ANTHROPIC_KEY" \
  --type SecureString \
  --overwrite

aws ssm put-parameter \
  --name /collections/voyage-api-key \
  --value "YOUR_VOYAGE_KEY" \
  --type SecureString \
  --overwrite

# Repeat for other keys: openai, tavily, langsmith
```

### 5.3 Create Test User

```bash
USER_POOL_ID=$(aws cloudformation describe-stacks \
  --stack-name CollectionsAPI-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' \
  --output text)

aws cognito-idp admin-create-user \
  --user-pool-id $USER_POOL_ID \
  --username testuser@example.com \
  --user-attributes \
    Name=email,Value=testuser@example.com \
    Name=email_verified,Value=true \
  --temporary-password TempPassword123!
```

### 5.4 Test Health Endpoint

```bash
API_URL=$(aws cloudformation describe-stacks \
  --stack-name CollectionsAPI-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' \
  --output text)

curl $API_URL/health
# Expected: {"status":"healthy","version":"2.0.0"}
```

## Costs

Expected monthly cost for dev environment: **$20-30**

Breakdown:
- RDS PostgreSQL (db.t4g.micro): $15-20
- Lambda invocations: $2-5
- API Gateway: $0.50
- DynamoDB: $1-2
- S3: $0.50
- CloudWatch: $1

## Clean Up

To destroy all infrastructure:

```bash
# WARNING: This deletes all data!
cdk destroy --context env=dev --all
```

## Troubleshooting

### CDK Bootstrap Errors

```bash
cdk bootstrap aws://ACCOUNT_ID/REGION --force
```

### RDS Connection Timeout

Check security group allows your IP:
```bash
aws ec2 authorize-security-group-ingress \
  --group-id sg-XXXXX \
  --protocol tcp \
  --port 5432 \
  --cidr YOUR_IP/32
```

### Lambda Function Logs

```bash
# View recent logs
aws logs tail /aws/lambda/CollectionsCompute-dev-APILambda --follow
```

## Next Steps

1. Replace placeholder Lambda functions with actual code
2. Run database migrations (Alembic)
3. Deploy FastAPI application to API Lambda
4. Test end-to-end workflow (upload → analyze → embed)
5. Set up CI/CD pipeline

## Support

- **Documentation**: See `README.md` and `DEPLOYMENT_SUMMARY.md`
- **Issues**: https://github.com/bennettck/collections-local/issues
- **Implementation Plan**: `/workspaces/collections-local/IMPLEMENTATION_PLAN.md`

---

**Quick Reference**

| Command | Description |
|---------|-------------|
| `cdk synth --context env=dev` | Generate CloudFormation templates |
| `cdk diff --context env=dev --all` | Show infrastructure changes |
| `cdk deploy --context env=dev --all` | Deploy all stacks |
| `cdk destroy --context env=dev --all` | Delete all infrastructure |
| `pytest tests/unit/` | Run unit tests |

