# AWS Deployment Quick Start Guide

This guide shows you how to use the deployment automation to deploy the Collections application to AWS.

## Prerequisites Check

```bash
# Verify all required tools are installed
make check-deps
```

This will verify you have:
- AWS CLI
- AWS CDK CLI
- jq (JSON processor)
- PostgreSQL client (for database connections)

## Step 1: Configure AWS Credentials

```bash
# Configure your AWS credentials
aws configure

# Verify access
aws sts get-caller-identity
```

You should see your AWS account ID and user ARN.

## Step 2: Prepare Configuration

### Update CDK Context

Edit `infrastructure/cdk.context.json` and replace the placeholder account ID:

```json
{
  "environments": {
    "dev": {
      "account": "YOUR_AWS_ACCOUNT_ID",  # Replace this
      "region": "us-east-1"
    }
  }
}
```

### Create Environment Secrets

```bash
# Copy the template
cp .env.dev.example .env.dev

# Edit and add your actual API keys
nano .env.dev
```

Required secrets:
- `ANTHROPIC_API_KEY` - Your Anthropic API key
- `OPENAI_API_KEY` - Your OpenAI API key
- `VOYAGE_API_KEY` - Your VoyageAI API key
- `TAVILY_API_KEY` - Your Tavily API key
- `LANGCHAIN_API_KEY` - Your LangSmith API key
- `DATABASE_PASSWORD` - Generate a secure password (32+ chars)

**Generate a secure database password:**
```bash
openssl rand -base64 32
```

## Step 3: Bootstrap CDK (One-Time)

This creates the necessary CDK infrastructure in your AWS account.

```bash
make infra-bootstrap ENV=dev
```

This only needs to be done once per AWS account/region.

## Step 4: Upload Secrets

Upload your secrets to AWS Systems Manager Parameter Store:

```bash
make secrets-populate ENV=dev
```

Secrets are stored as SecureStrings and encrypted at rest (FREE).

## Step 5: Deploy Infrastructure

Deploy all CDK stacks to AWS:

```bash
make infra-deploy ENV=dev
```

This will:
1. Show a preview of changes (cdk diff)
2. Ask for confirmation
3. Deploy all stacks (RDS, DynamoDB, S3, Lambda, API Gateway, Cognito)
4. Extract outputs to `.aws-outputs-dev.json`

**Deployment time:** 10-15 minutes (RDS takes longest)

## Step 6: Verify Deployment

### Check Stack Status

```bash
make infra-status ENV=dev
```

All stacks should show `CREATE_COMPLETE` or `UPDATE_COMPLETE`.

### View Outputs

```bash
make infra-outputs ENV=dev
cat .aws-outputs-dev.json | jq
```

You should see:
- API Gateway URL
- RDS endpoint
- S3 bucket name
- Cognito User Pool ID
- DynamoDB table name

### Run Infrastructure Tests

```bash
make test-infra ENV=dev
```

This runs 11 validation tests to verify:
- RDS is accessible
- DynamoDB table exists
- S3 bucket is configured
- Lambda functions deployed
- API Gateway is live
- Cognito pool configured

## Step 7: Test the API

Get the API URL:

```bash
API_URL=$(jq -r '.[] | select(.OutputKey=="ApiUrl") | .OutputValue' .aws-outputs-dev.json)
echo $API_URL
```

Test the health endpoint:

```bash
curl $API_URL/health
```

## Common Operations

### Connect to Database

```bash
make db-connect ENV=dev
```

This opens an interactive PostgreSQL session.

### View Lambda Logs

```bash
# API Lambda logs
make lambda-logs FUNC=api ENV=dev

# Processor Lambda logs
make lambda-logs FUNC=processor ENV=dev
```

Press Ctrl+C to stop tailing logs.

### Redeploy After Code Changes

```bash
# Preview changes
make infra-diff ENV=dev

# Deploy changes
make infra-deploy ENV=dev
```

### Quick Update of API Lambda Only

If you only changed the API code (not infrastructure):

```bash
make lambda-deploy-api ENV=dev
```

This is faster than redeploying all stacks.

## Troubleshooting

### Deployment Failed

1. Check stack status:
   ```bash
   make infra-status ENV=dev
   ```

2. View CloudFormation events:
   ```bash
   aws cloudformation describe-stack-events --stack-name CollectionsStack-dev
   ```

3. Check Lambda logs:
   ```bash
   make lambda-logs FUNC=api ENV=dev
   ```

### Cannot Connect to Database

1. Verify RDS is running:
   ```bash
   make infra-status ENV=dev
   ```

2. Check security group allows your IP

3. Verify password in Parameter Store:
   ```bash
   aws ssm get-parameter --name /collections/dev/database-password --with-decryption
   ```

### Lambda Not Working

1. Check function logs:
   ```bash
   make lambda-logs FUNC=api ENV=dev
   ```

2. Verify environment variables are set in Lambda

3. Check IAM permissions

## Complete Workflow Example

Here's a complete workflow from scratch:

```bash
# 1. Check dependencies
make check-deps

# 2. Configure AWS
aws configure

# 3. Create secrets file
cp .env.dev.example .env.dev
nano .env.dev  # Add your keys

# 4. One-time setup
make infra-bootstrap ENV=dev

# 5. Upload secrets
make secrets-populate ENV=dev

# 6. Deploy infrastructure
make infra-deploy ENV=dev

# 7. Verify deployment
make infra-status ENV=dev
make test-infra ENV=dev

# 8. View outputs
make infra-outputs ENV=dev

# 9. Test API
API_URL=$(jq -r '.[] | select(.OutputKey=="ApiUrl") | .OutputValue' .aws-outputs-dev.json)
curl $API_URL/health

# 10. Connect to database
make db-connect ENV=dev
```

**Or use the shortcut for steps 4-6:**

```bash
make dev-setup
```

## Cleanup

To completely remove all infrastructure:

```bash
make infra-destroy ENV=dev
```

**WARNING:** This is DESTRUCTIVE and IRREVERSIBLE. All data will be permanently deleted.

## Next Steps

- **API Documentation**: See `api/README.md`
- **Testing**: See `testing/README.md`
- **Architecture**: See `AWS_MIGRATION_PLAN.md`
- **Full Implementation**: See `IMPLEMENTATION_PLAN.md`

## Getting Help

- **All available commands**: `make help`
- **Script documentation**: `scripts/aws/README.md`
- **Troubleshooting guide**: `scripts/aws/README.md#troubleshooting`

## Cost Estimate

Monthly cost for dev environment:
- RDS PostgreSQL (db.t4g.micro): $15-20
- Lambda: $5-15
- API Gateway: $1-2
- S3: $0.50
- DynamoDB: $1-5
- CloudWatch Logs: $1-2
- Parameter Store: FREE

**Total: ~$23-45/month**

To minimize costs:
- Destroy dev environment when not in use: `make infra-destroy ENV=dev`
- Use RDS instance scheduler for non-24/7 usage
- Enable S3 lifecycle policies for old images
