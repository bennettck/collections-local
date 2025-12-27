#!/bin/bash
# Deploy CDK stacks to environment
# Usage: ./scripts/aws/deploy.sh <dev|test|prod>
#
# This script:
# - Validates AWS credentials and environment
# - Shows infrastructure diff before deployment
# - Prompts for confirmation
# - Deploys all CDK stacks to the specified environment
#
# Requirements:
# - AWS CLI configured with valid credentials
# - AWS CDK CLI installed
# - CDK already bootstrapped (run bootstrap.sh first)

set -e  # Exit on any error
set -u  # Exit on undefined variables

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Default to dev if no environment specified
ENV=${1:-dev}

echo -e "${BLUE}🚀 Deploying to ${ENV} environment...${NC}"
echo ""

# Validate environment argument
if [[ ! "$ENV" =~ ^(dev|test|prod)$ ]]; then
    echo -e "${RED}❌ Invalid environment: ${ENV}${NC}"
    echo "Valid environments: dev, test, prod"
    exit 1
fi

# Check for required tools
command -v aws >/dev/null 2>&1 || {
    echo -e "${RED}❌ AWS CLI not found. Install from https://aws.amazon.com/cli/${NC}"
    exit 1
}

command -v cdk >/dev/null 2>&1 || {
    echo -e "${RED}❌ AWS CDK CLI not found. Install with: npm install -g aws-cdk${NC}"
    exit 1
}

# Validate AWS credentials
echo -e "${BLUE}🔍 Validating AWS credentials...${NC}"
aws sts get-caller-identity > /dev/null || {
    echo -e "${RED}❌ AWS credentials not configured${NC}"
    echo "Run: aws configure"
    exit 1
}

AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
AWS_USER=$(aws sts get-caller-identity --query Arn --output text)

echo -e "${GREEN}✓ Authenticated as: ${AWS_USER}${NC}"
echo -e "${GREEN}✓ Account ID: ${AWS_ACCOUNT}${NC}"
echo ""

# Check if infrastructure directory exists
if [ ! -d "infrastructure" ]; then
    echo -e "${RED}❌ infrastructure/ directory not found${NC}"
    echo "Please create the CDK infrastructure first (see IMPLEMENTATION_PLAN.md)"
    exit 1
fi

# Check if CDK app exists
if [ ! -f "infrastructure/app.py" ]; then
    echo -e "${RED}❌ infrastructure/app.py not found${NC}"
    echo "Please create the CDK application first"
    exit 1
fi

# Show infrastructure diff
echo -e "${BLUE}📋 Showing infrastructure diff...${NC}"
echo ""

cd infrastructure

# Run cdk diff (non-blocking - may show no changes)
cdk diff --context env="$ENV" '*' || true

echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Production safety check
if [ "$ENV" = "prod" ]; then
    echo -e "${RED}⚠️  WARNING: You are about to deploy to PRODUCTION${NC}"
    echo ""
    read -p "Type 'PRODUCTION' to confirm: " confirm
    if [ "$confirm" != "PRODUCTION" ]; then
        echo "Deployment cancelled."
        exit 0
    fi
else
    # Standard confirmation for dev/test
    read -p "Deploy these changes to ${ENV}? [y/N]: " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Deployment cancelled."
        exit 0
    fi
fi

echo ""
echo -e "${BLUE}🚀 Deploying all stacks to ${ENV}...${NC}"
echo ""

# Deploy all stacks
# --all: Deploy all stacks
# --require-approval never: Don't prompt for security changes (already confirmed above)
# --context env: Pass environment to CDK app
# --progress events: Show CloudFormation events as they happen
cdk deploy \
    --context env="$ENV" \
    --all \
    --require-approval never \
    --progress events

echo ""
echo -e "${GREEN}✅ Deployment complete!${NC}"
echo ""

# Extract outputs
echo -e "${BLUE}📤 Extracting stack outputs...${NC}"

cd ..
bash ./scripts/aws/outputs.sh "$ENV"

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ Deployment successful for ${ENV} environment${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Next steps:"
echo "  - View stack status: make infra-status ENV=${ENV}"
echo "  - Run infrastructure tests: make test-infra ENV=${ENV}"
echo "  - View stack outputs: cat .aws-outputs-${ENV}.json"
echo "  - Connect to database: make db-connect ENV=${ENV}"
echo "  - View Lambda logs: make lambda-logs FUNC=api ENV=${ENV}"
