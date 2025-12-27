#!/bin/bash
# Destroy CDK stacks (with safety confirmation)
# Usage: ./scripts/aws/destroy.sh <dev|test|prod>
#
# This script:
# - Shows all resources that will be destroyed
# - Requires explicit confirmation (type environment name)
# - Extra confirmation for production
# - Destroys all CDK stacks in the environment
#
# WARNING: This is DESTRUCTIVE and IRREVERSIBLE
# All data in RDS, DynamoDB, and S3 will be PERMANENTLY DELETED

set -e  # Exit on any error
set -u  # Exit on undefined variables

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Default to dev if no environment specified
ENV=${1:-dev}

echo -e "${RED}${BOLD}⚠️  DESTRUCTIVE OPERATION WARNING ⚠️${NC}"
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
aws sts get-caller-identity > /dev/null || {
    echo -e "${RED}❌ AWS credentials not configured${NC}"
    echo "Run: aws configure"
    exit 1
}

AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
AWS_USER=$(aws sts get-caller-identity --query Arn --output text)

echo -e "Account: ${BOLD}${AWS_ACCOUNT}${NC}"
echo -e "User: ${BOLD}${AWS_USER}${NC}"
echo ""

# Check if infrastructure directory exists
if [ ! -d "infrastructure" ]; then
    echo -e "${RED}❌ infrastructure/ directory not found${NC}"
    exit 1
fi

# Show what will be destroyed
echo -e "${RED}${BOLD}This will destroy ALL infrastructure in the ${ENV} environment:${NC}"
echo ""
echo -e "${RED}  🗄️  RDS PostgreSQL Database${NC}"
echo "     - All collections data will be PERMANENTLY DELETED"
echo "     - All user data will be PERMANENTLY DELETED"
echo "     - All metadata and vectors will be LOST"
echo ""
echo -e "${RED}  📦 DynamoDB Table${NC}"
echo "     - All conversation checkpoints will be DELETED"
echo "     - All chat history will be LOST"
echo ""
echo -e "${RED}  🪣 S3 Bucket${NC}"
echo "     - All uploaded images will be PERMANENTLY DELETED"
echo "     - All processed data will be LOST"
echo ""
echo -e "${RED}  ⚡ Lambda Functions${NC}"
echo "     - API Lambda (FastAPI application)"
echo "     - Image Processor Lambda"
echo "     - Image Analyzer Lambda"
echo "     - Embedding Generator Lambda"
echo "     - Session Cleanup Lambda"
echo ""
echo -e "${RED}  🌐 API Gateway${NC}"
echo "     - HTTP API endpoint will be deleted"
echo ""
echo -e "${RED}  🔐 Cognito User Pool${NC}"
echo "     - All user accounts will be DELETED"
echo "     - Users will need to re-register"
echo ""
echo -e "${RED}  📊 CloudWatch Resources${NC}"
echo "     - Log groups will be deleted"
echo "     - Metrics and alarms will be removed"
echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# First confirmation: Type environment name
echo -e "${YELLOW}To confirm destruction, type the environment name: ${BOLD}${ENV}${NC}"
read -p "> " confirm

if [ "$confirm" != "$ENV" ]; then
    echo ""
    echo -e "${GREEN}✓ Destruction cancelled.${NC}"
    exit 0
fi

echo ""

# Production extra safety
if [ "$ENV" = "prod" ]; then
    echo -e "${RED}${BOLD}⚠️  PRODUCTION ENVIRONMENT DESTRUCTION ⚠️${NC}"
    echo ""
    echo "You are about to destroy the PRODUCTION environment."
    echo "This will affect REAL USERS and REAL DATA."
    echo ""
    echo -e "${YELLOW}Type 'DELETE PRODUCTION' to confirm:${NC}"
    read -p "> " prod_confirm

    if [ "$prod_confirm" != "DELETE PRODUCTION" ]; then
        echo ""
        echo -e "${GREEN}✓ Destruction cancelled.${NC}"
        exit 0
    fi
    echo ""
fi

# Final countdown confirmation
echo -e "${RED}${BOLD}FINAL WARNING:${NC}"
echo "All data will be permanently deleted in 5 seconds..."
echo "Press Ctrl+C NOW to cancel!"
echo ""

for i in 5 4 3 2 1; do
    echo -e "${RED}${BOLD}$i...${NC}"
    sleep 1
done

echo ""
echo -e "${RED}🗑️  Destroying stacks in ${ENV} environment...${NC}"
echo ""

# Change to infrastructure directory
cd infrastructure

# Destroy all stacks
# --force: Don't ask for confirmation (we already confirmed above)
# --context env: Pass environment to CDK app
cdk destroy \
    --context env="$ENV" \
    --all \
    --force

cd ..

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ Infrastructure destroyed successfully${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "What was deleted:"
echo "  ✓ All CDK stacks for ${ENV} environment"
echo "  ✓ All AWS resources (RDS, DynamoDB, S3, Lambda, etc.)"
echo "  ✓ All data (this cannot be recovered)"
echo ""

# Clean up local outputs file
if [ -f ".aws-outputs-${ENV}.json" ]; then
    rm -f ".aws-outputs-${ENV}.json"
    echo "  ✓ Removed local outputs file: .aws-outputs-${ENV}.json"
fi

echo ""
echo "To redeploy:"
echo "  make infra-deploy ENV=${ENV}"
