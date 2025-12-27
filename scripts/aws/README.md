# AWS Deployment Scripts

Comprehensive automation scripts for managing AWS infrastructure using AWS CDK.

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Available Scripts](#available-scripts)
- [Makefile Commands](#makefile-commands)
- [Workflow Examples](#workflow-examples)
- [Troubleshooting](#troubleshooting)
- [Security Best Practices](#security-best-practices)

## Overview

This directory contains deployment automation scripts that provide a seamless developer experience for AWS infrastructure management. All scripts use:

- **AWS CDK** for infrastructure as code
- **AWS CLI** for resource management
- **Parameter Store** for secrets management (FREE tier)
- **CloudFormation** for stack orchestration

**Architecture**: The scripts manage deployment of a serverless stack including:
- RDS PostgreSQL (with pgvector)
- DynamoDB (for LangGraph checkpoints)
- S3 (for image storage)
- Lambda Functions (API, Processor, Analyzer, Embedder, Cleanup)
- API Gateway (HTTP API)
- Cognito (user authentication)

## Prerequisites

### Required Tools

1. **AWS CLI** (v2.x)
   ```bash
   # Install
   curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
   unzip awscliv2.zip
   sudo ./aws/install

   # Configure
   aws configure
   ```

2. **AWS CDK CLI** (v2.x)
   ```bash
   npm install -g aws-cdk

   # Verify
   cdk --version
   ```

3. **jq** (JSON processor)
   ```bash
   # Ubuntu/Debian
   sudo apt-get install jq

   # macOS
   brew install jq
   ```

4. **PostgreSQL Client** (for database connections)
   ```bash
   # Ubuntu/Debian
   sudo apt-get install postgresql-client

   # macOS
   brew install postgresql
   ```

### AWS Configuration

1. **Configure AWS Credentials**
   ```bash
   aws configure
   # Enter: Access Key ID, Secret Access Key, Region, Output format
   ```

2. **Verify Access**
   ```bash
   aws sts get-caller-identity
   ```

3. **Update CDK Context**
   Edit `infrastructure/cdk.context.json` and replace placeholder account ID:
   ```json
   {
     "environments": {
       "dev": {
         "account": "YOUR_AWS_ACCOUNT_ID",
         "region": "us-east-1"
       }
     }
   }
   ```

## Quick Start

### First-Time Setup (Dev Environment)

```bash
# 1. Check dependencies
make check-deps

# 2. Create secrets file
cp .env.dev.example .env.dev
# Edit .env.dev and add your actual API keys

# 3. Bootstrap CDK (one-time per AWS account/region)
make infra-bootstrap ENV=dev

# 4. Upload secrets to Parameter Store
make secrets-populate ENV=dev

# 5. Deploy infrastructure
make infra-deploy ENV=dev

# 6. View outputs
make infra-outputs ENV=dev

# 7. Run infrastructure tests
make test-infra ENV=dev
```

**Or use the shortcut:**
```bash
make dev-setup
```

### Daily Development Workflow

```bash
# Check stack status
make infra-status ENV=dev

# Make infrastructure changes in CDK code
# ...

# Preview changes
make infra-diff ENV=dev

# Deploy changes
make infra-deploy ENV=dev

# View Lambda logs
make lambda-logs FUNC=api ENV=dev

# Connect to database
make db-connect ENV=dev
```

## Available Scripts

### Core Deployment Scripts

#### `bootstrap.sh`
Bootstrap CDK for an AWS account/region (one-time setup).

```bash
./scripts/aws/bootstrap.sh <dev|test|prod>
make infra-bootstrap ENV=dev
```

**What it does:**
- Validates AWS credentials
- Reads configuration from `cdk.context.json`
- Creates CDK bootstrap stack (CDKToolkit)
- Sets up S3 bucket for CDK assets
- Creates IAM roles for CloudFormation

**When to run:**
- First time deploying to a new AWS account/region
- After upgrading CDK CLI to a new major version

---

#### `deploy.sh`
Deploy all CDK stacks to an environment.

```bash
./scripts/aws/deploy.sh <dev|test|prod>
make infra-deploy ENV=dev
```

**What it does:**
- Validates credentials and environment
- Shows infrastructure diff (preview changes)
- Prompts for confirmation
- Deploys all stacks via CDK
- Extracts stack outputs to JSON

**Safety features:**
- Preview changes before deployment
- Extra confirmation for production
- Automatic outputs extraction

---

#### `destroy.sh`
Destroy all infrastructure (DESTRUCTIVE).

```bash
./scripts/aws/destroy.sh <dev|test|prod>
make infra-destroy ENV=dev
```

**What it does:**
- Shows detailed list of resources to be deleted
- Requires typing environment name to confirm
- Extra confirmation for production
- Countdown before deletion
- Destroys all CDK stacks

**⚠️ WARNING:** This is IRREVERSIBLE. All data will be PERMANENTLY DELETED:
- RDS database (all collections data)
- DynamoDB table (all conversation history)
- S3 bucket (all images)
- Cognito users (all user accounts)

---

#### `outputs.sh`
Extract CDK stack outputs to JSON file.

```bash
./scripts/aws/outputs.sh <dev|test|prod>
make infra-outputs ENV=dev
```

**What it does:**
- Queries CloudFormation for all stack outputs
- Saves to `.aws-outputs-{ENV}.json`
- Pretty-prints output values

**Output file contains:**
- API Gateway URL
- RDS endpoint
- S3 bucket name
- Cognito User Pool ID
- DynamoDB table name
- Lambda function ARNs

**Usage:**
```bash
# View all outputs
cat .aws-outputs-dev.json | jq

# Get specific output
jq -r '.[] | select(.OutputKey=="ApiUrl") | .OutputValue' .aws-outputs-dev.json
```

---

#### `status.sh`
Show status of all CDK stacks.

```bash
./scripts/aws/status.sh <dev|test|prod>
make infra-status ENV=dev
```

**What it does:**
- Lists all stacks for the environment
- Shows stack status and last updated time
- Highlights failed or in-progress deployments
- Provides quick action commands

**Stack statuses:**
- `CREATE_COMPLETE` - Stack created successfully (green)
- `UPDATE_COMPLETE` - Stack updated successfully (green)
- `*_IN_PROGRESS` - Operation in progress (yellow)
- `*_FAILED` - Operation failed (red)
- `ROLLBACK_COMPLETE` - Deployment failed and rolled back (red)

---

### Secrets Management

#### `secrets/populate.sh`
Upload secrets from `.env.{ENV}` to Parameter Store.

```bash
./scripts/aws/secrets/populate.sh <dev|test|prod>
make secrets-populate ENV=dev
```

**What it does:**
- Reads `.env.{ENV}` file
- Converts `KEY_NAME` to `/collections/{env}/key-name`
- Uploads as SecureString to Parameter Store
- Skips placeholders (values starting with `your-`, `sk-`, etc.)
- Shows upload statistics

**Parameter naming:**
```
OPENAI_API_KEY       → /collections/dev/openai-api-key
DATABASE_PASSWORD    → /collections/dev/database-password
TAVILY_API_KEY       → /collections/dev/tavily-api-key
```

**Cost:** FREE (Parameter Store Standard is free up to 10,000 parameters)

---

### Database Tools

#### `db-connect.sh`
Open interactive PostgreSQL connection to RDS.

```bash
./scripts/aws/db-connect.sh <dev|test|prod>
make db-connect ENV=dev
```

**What it does:**
- Reads RDS endpoint from stack outputs
- Retrieves password from Parameter Store
- Opens `psql` interactive shell

**Useful psql commands:**
```sql
\dt                    -- List all tables
\d table_name          -- Describe table schema
\l                     -- List all databases
\q                     -- Quit
SELECT version();      -- Show PostgreSQL version

-- Query examples
SELECT COUNT(*) FROM collections;
SELECT * FROM collections LIMIT 10;
```

---

### Lambda Tools

#### `lambda-logs.sh`
Tail CloudWatch logs for Lambda functions.

```bash
./scripts/aws/lambda-logs.sh <function-name> <dev|test|prod>
make lambda-logs FUNC=api ENV=dev
```

**Available functions:**
- `api` - API Lambda (FastAPI application)
- `processor` - Image Processor Lambda
- `analyzer` - Image Analyzer Lambda
- `embedder` - Embedding Generator Lambda
- `cleanup` - Session Cleanup Lambda

**What it does:**
- Finds CloudWatch log group for Lambda
- Tails logs in real-time (follows new entries)
- Shows logs from last 1 hour
- Press Ctrl+C to stop

**Example:**
```bash
# Tail API logs
make lambda-logs FUNC=api ENV=dev

# Tail processor logs
make lambda-logs FUNC=processor ENV=dev
```

---

## Makefile Commands

### Infrastructure Commands

| Command | Description | Example |
|---------|-------------|---------|
| `make infra-bootstrap ENV=dev` | Bootstrap CDK | First-time setup |
| `make infra-deploy ENV=dev` | Deploy stacks | Deploy changes |
| `make infra-diff ENV=dev` | Show changes | Preview before deploy |
| `make infra-destroy ENV=dev` | Destroy stacks | Delete everything |
| `make infra-status ENV=dev` | Show stack status | Check deployment |
| `make infra-outputs ENV=dev` | Extract outputs | Get endpoint URLs |

### Testing Commands

| Command | Description | Example |
|---------|-------------|---------|
| `make test-infra ENV=dev` | Infrastructure tests | 11 validation checks |
| `make test-all ENV=dev` | All tests | Infra + API + E2E |

### Database Commands

| Command | Description | Example |
|---------|-------------|---------|
| `make db-connect ENV=dev` | Connect to RDS | Open psql shell |
| `make db-migrate ENV=dev` | Run migrations | (Future) |
| `make db-seed-golden ENV=dev` | Seed golden data | (Future) |

### Secrets Commands

| Command | Description | Example |
|---------|-------------|---------|
| `make secrets-populate ENV=dev` | Upload secrets | From .env to AWS |
| `make secrets-export ENV=dev` | Download secrets | From AWS to .env (Future) |

### Lambda Commands

| Command | Description | Example |
|---------|-------------|---------|
| `make lambda-deploy-api ENV=dev` | Deploy API Lambda | Fast update |
| `make lambda-logs FUNC=api ENV=dev` | Tail Lambda logs | Real-time logs |

### Utility Commands

| Command | Description |
|---------|-------------|
| `make check-deps` | Verify dependencies installed |
| `make clean` | Clean temporary files |
| `make help` | Show all commands |

### Development Shortcuts

| Command | Description |
|---------|-------------|
| `make dev-setup` | Complete dev setup (bootstrap + deploy) |
| `make dev-reset` | Reset dev environment (destroy + redeploy) |

---

## Workflow Examples

### Example 1: First Deployment

```bash
# 1. Verify prerequisites
make check-deps

# 2. Create and configure secrets
cp .env.dev.example .env.dev
nano .env.dev  # Add your API keys

# 3. Bootstrap CDK (one-time)
make infra-bootstrap ENV=dev

# 4. Upload secrets
make secrets-populate ENV=dev

# 5. Deploy infrastructure
make infra-deploy ENV=dev

# 6. Verify deployment
make infra-status ENV=dev
make infra-outputs ENV=dev

# 7. Test infrastructure
make test-infra ENV=dev

# 8. Connect to database
make db-connect ENV=dev
```

### Example 2: Update Existing Infrastructure

```bash
# 1. Check current status
make infra-status ENV=dev

# 2. Preview changes
make infra-diff ENV=dev

# 3. Deploy changes
make infra-deploy ENV=dev

# 4. Monitor Lambda logs
make lambda-logs FUNC=api ENV=dev
```

### Example 3: Debugging

```bash
# 1. Check stack status
make infra-status ENV=dev

# 2. View outputs
make infra-outputs ENV=dev
cat .aws-outputs-dev.json | jq

# 3. Check Lambda logs
make lambda-logs FUNC=api ENV=dev

# 4. Connect to database
make db-connect ENV=dev

# 5. Query database
\dt
SELECT * FROM collections LIMIT 10;
```

### Example 4: Deploy to Production

```bash
# 1. Test in dev first
make test-all ENV=dev

# 2. Update context for prod
nano infrastructure/cdk.context.json

# 3. Bootstrap prod (if first time)
make infra-bootstrap ENV=prod

# 4. Prepare prod secrets
cp .env.dev.example .env.prod
nano .env.prod  # Use production API keys

# 5. Upload prod secrets
make secrets-populate ENV=prod

# 6. Preview prod changes
make infra-diff ENV=prod

# 7. Deploy to prod (requires "PRODUCTION" confirmation)
make infra-deploy ENV=prod

# 8. Validate prod deployment
make test-infra ENV=prod
```

---

## Troubleshooting

### Issue: CDK Bootstrap Fails

**Error:** `CDKToolkit stack already exists`

**Solution:**
```bash
# Bootstrap will update existing stack
make infra-bootstrap ENV=dev
# Answer 'y' when prompted to update
```

---

### Issue: Deploy Fails with "No Changes"

**Error:** Stack shows no changes but deployment needed

**Solution:**
```bash
# Force redeploy by destroying first
make infra-destroy ENV=dev
make infra-deploy ENV=dev
```

---

### Issue: Cannot Connect to Database

**Error:** Connection refused or timeout

**Possible causes:**
1. RDS security group not allowing your IP
2. Database password not in Parameter Store
3. Database not fully created yet

**Solution:**
```bash
# 1. Verify stack is complete
make infra-status ENV=dev

# 2. Check outputs for endpoint
make infra-outputs ENV=dev

# 3. Verify password exists
aws ssm get-parameter --name /collections/dev/database-password --with-decryption

# 4. Update security group in CDK code to allow your IP
```

---

### Issue: Lambda Logs Not Found

**Error:** Log group not found

**Possible causes:**
1. Lambda not deployed yet
2. Lambda never invoked (no logs generated)
3. Different naming convention

**Solution:**
```bash
# 1. List all Lambda log groups
aws logs describe-log-groups --log-group-name-prefix /aws/lambda/collections

# 2. Check Lambda function name
make infra-outputs ENV=dev | grep Lambda

# 3. Redeploy if needed
make infra-deploy ENV=dev
```

---

### Issue: Secrets Not Uploading

**Error:** Skipped placeholder values

**Solution:**
```bash
# 1. Check .env.dev file
cat .env.dev

# 2. Ensure values don't start with 'your-', 'sk-', 'REPLACE_'
nano .env.dev

# 3. Re-upload
make secrets-populate ENV=dev
```

---

### Issue: Stack Stuck in UPDATE_IN_PROGRESS

**Cause:** CloudFormation operation timed out or waiting for resource

**Solution:**
```bash
# 1. Check stack events
aws cloudformation describe-stack-events --stack-name CollectionsStack-dev

# 2. Wait for timeout (usually 60 minutes)
watch -n 30 'make infra-status ENV=dev'

# 3. If truly stuck, cancel update
aws cloudformation cancel-update-stack --stack-name CollectionsStack-dev

# 4. Roll back
make infra-destroy ENV=dev
make infra-deploy ENV=dev
```

---

## Security Best Practices

### 1. Secrets Management

✅ **DO:**
- Use Parameter Store for all secrets
- Use different API keys for dev/test/prod
- Rotate API keys regularly
- Generate strong database passwords (32+ characters)

❌ **DON'T:**
- Commit `.env.dev`, `.env.test`, `.env.prod` to git
- Share API keys across environments
- Use simple passwords
- Hard-code secrets in CDK code

```bash
# Generate secure password
openssl rand -base64 32
```

### 2. AWS Credentials

✅ **DO:**
- Use IAM roles when possible (EC2, ECS, Lambda)
- Use temporary credentials (AWS SSO, STS)
- Enable MFA on AWS account
- Use least privilege IAM policies

❌ **DON'T:**
- Use root account credentials
- Share AWS access keys
- Commit AWS credentials to git
- Use overly permissive IAM policies

### 3. Infrastructure Security

✅ **DO:**
- Enable deletion protection for production RDS
- Enable automated backups for production
- Use security groups to restrict access
- Enable CloudWatch logging
- Use HTTPS for all endpoints

❌ **DON'T:**
- Expose RDS publicly without security groups
- Disable backups in production
- Use default passwords
- Skip CloudWatch logs

### 4. Deployment Safety

✅ **DO:**
- Always preview changes with `make infra-diff`
- Test in dev before deploying to prod
- Use version control for infrastructure code
- Document all manual changes

❌ **DON'T:**
- Deploy to prod without testing
- Make manual changes in AWS Console
- Skip confirmations
- Delete production data without backups

---

## Additional Resources

### AWS Documentation
- [AWS CDK Developer Guide](https://docs.aws.amazon.com/cdk/latest/guide/home.html)
- [AWS CLI Command Reference](https://docs.aws.amazon.com/cli/latest/reference/)
- [Parameter Store User Guide](https://docs.aws.amazon.com/systems-manager/latest/userguide/systems-manager-parameter-store.html)

### Project Documentation
- [AWS Migration Plan](../../AWS_MIGRATION_PLAN.md)
- [Implementation Plan](../../IMPLEMENTATION_PLAN.md)
- [Project README](../../README.md)

### Support
- Report issues: [GitHub Issues](https://github.com/bennettck/collections-local/issues)
- CDK infrastructure: See `infrastructure/README.md`
- Testing: See `testing/infrastructure/README.md`

---

## Script Maintenance

All scripts follow these principles:

1. **Idempotent**: Can be run multiple times safely
2. **Error Handling**: Exit on errors (`set -e`)
3. **Validation**: Check prerequisites before execution
4. **Safety**: Confirm destructive operations
5. **Feedback**: Clear status messages with colors
6. **Documentation**: Comprehensive help and error messages

**Contributing:**
When adding new scripts, follow the existing patterns and update this README.

---

**Last Updated:** 2025-12-27
**Version:** 1.0
