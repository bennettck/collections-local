#!/bin/bash
# Bootstrap CDK for a specific environment
# Usage: ./scripts/aws/bootstrap.sh <dev|test|prod>
#
# This script:
# - Validates AWS credentials
# - Reads environment configuration from cdk.context.json
# - Bootstraps CDK for the specified AWS account and region
#
# Requirements:
# - AWS CLI configured with valid credentials
# - AWS CDK CLI installed (npm install -g aws-cdk)
# - jq installed (for JSON parsing)

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

echo -e "${BLUE}🔧 Bootstrapping CDK for ${ENV} environment...${NC}"

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

command -v jq >/dev/null 2>&1 || {
    echo -e "${RED}❌ jq not found. Install with: sudo apt-get install jq${NC}"
    exit 1
}

# Validate AWS credentials
echo -e "${BLUE}🔍 Validating AWS credentials...${NC}"
aws sts get-caller-identity > /dev/null || {
    echo -e "${RED}❌ AWS credentials not configured${NC}"
    echo "Run: aws configure"
    exit 1
}

# Get AWS account and identity
AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
AWS_USER=$(aws sts get-caller-identity --query Arn --output text)

echo -e "${GREEN}✓ Authenticated as: ${AWS_USER}${NC}"
echo -e "${GREEN}✓ Account ID: ${AWS_ACCOUNT}${NC}"

# Check if infrastructure directory exists
if [ ! -d "infrastructure" ]; then
    echo -e "${RED}❌ infrastructure/ directory not found${NC}"
    echo "Please create the CDK infrastructure first (see IMPLEMENTATION_PLAN.md)"
    exit 1
fi

# Check if cdk.context.json exists
if [ ! -f "infrastructure/cdk.context.json" ]; then
    echo -e "${RED}❌ infrastructure/cdk.context.json not found${NC}"
    echo "Please create the CDK context configuration first"
    exit 1
fi

# Read environment configuration from cdk.context.json
echo -e "${BLUE}📋 Reading environment configuration...${NC}"

CONTEXT_FILE="infrastructure/cdk.context.json"

# Check if environment exists in context file
if ! jq -e ".environments.$ENV" "$CONTEXT_FILE" > /dev/null 2>&1; then
    echo -e "${RED}❌ Environment '$ENV' not found in $CONTEXT_FILE${NC}"
    echo "Available environments:"
    jq -r '.environments | keys[]' "$CONTEXT_FILE"
    exit 1
fi

# Extract account and region
ACCOUNT=$(jq -r ".environments.$ENV.account" "$CONTEXT_FILE")
REGION=$(jq -r ".environments.$ENV.region" "$CONTEXT_FILE")

# Validate configuration
if [ "$ACCOUNT" = "null" ] || [ -z "$ACCOUNT" ]; then
    echo -e "${RED}❌ Account ID not found in configuration${NC}"
    exit 1
fi

if [ "$ACCOUNT" = "PLACEHOLDER" ] || [ "$ACCOUNT" = "123456789012" ]; then
    echo -e "${RED}❌ Please update the account ID in $CONTEXT_FILE${NC}"
    echo "Replace 'PLACEHOLDER' or '123456789012' with your actual AWS account ID: $AWS_ACCOUNT"
    exit 1
fi

if [ "$REGION" = "null" ] || [ -z "$REGION" ]; then
    echo -e "${RED}❌ Region not found in configuration${NC}"
    exit 1
fi

# Verify account ID matches
if [ "$ACCOUNT" != "$AWS_ACCOUNT" ]; then
    echo -e "${YELLOW}⚠️  Warning: Account ID mismatch${NC}"
    echo "  Configured: $ACCOUNT"
    echo "  Current:    $AWS_ACCOUNT"
    read -p "Continue anyway? [y/N]: " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
fi

echo -e "${GREEN}✓ Account: ${ACCOUNT}${NC}"
echo -e "${GREEN}✓ Region: ${REGION}${NC}"

# Check if already bootstrapped
echo -e "${BLUE}🔍 Checking if CDK is already bootstrapped...${NC}"

BOOTSTRAP_STACK="CDKToolkit"
STACK_STATUS=$(aws cloudformation describe-stacks \
    --stack-name "$BOOTSTRAP_STACK" \
    --region "$REGION" \
    --query "Stacks[0].StackStatus" \
    --output text 2>/dev/null || echo "NOT_FOUND")

if [ "$STACK_STATUS" != "NOT_FOUND" ] && [ "$STACK_STATUS" != "DELETE_COMPLETE" ]; then
    echo -e "${YELLOW}⚠️  CDK already bootstrapped in ${REGION}${NC}"
    echo "Stack status: $STACK_STATUS"
    read -p "Bootstrap again (this will update)? [y/N]: " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${GREEN}✓ Using existing CDK bootstrap${NC}"
        exit 0
    fi
fi

# Bootstrap CDK
echo -e "${BLUE}🚀 Bootstrapping CDK in aws://${ACCOUNT}/${REGION}...${NC}"

cd infrastructure

cdk bootstrap "aws://${ACCOUNT}/${REGION}" \
    --cloudformation-execution-policies arn:aws:iam::aws:policy/AdministratorAccess \
    --verbose

cd ..

echo -e "${GREEN}✅ CDK bootstrapped successfully for ${ENV} environment${NC}"
echo ""
echo "Next steps:"
echo "  1. Populate secrets: make secrets-populate ENV=${ENV}"
echo "  2. Deploy stack: make infra-deploy ENV=${ENV}"
