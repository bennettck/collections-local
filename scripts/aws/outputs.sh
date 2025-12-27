#!/bin/bash
# Extract CDK outputs to JSON file
# Usage: ./scripts/aws/outputs.sh <dev|test|prod>
#
# This script:
# - Queries CloudFormation for all stack outputs
# - Filters stacks by environment name
# - Exports outputs to .aws-outputs-{ENV}.json
#
# Output file contains all CDK stack outputs including:
# - API Gateway URL
# - RDS endpoint
# - S3 bucket name
# - Cognito User Pool ID
# - DynamoDB table name
# - Lambda function names

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

echo -e "${BLUE}📤 Extracting CDK outputs for ${ENV} environment...${NC}"

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

command -v jq >/dev/null 2>&1 || {
    echo -e "${RED}❌ jq not found. Install with: sudo apt-get install jq${NC}"
    exit 1
}

# Validate AWS credentials
aws sts get-caller-identity > /dev/null || {
    echo -e "${RED}❌ AWS credentials not configured${NC}"
    echo "Run: aws configure"
    exit 1
}

# Output file
OUTPUT_FILE=".aws-outputs-${ENV}.json"

# Get region from cdk.context.json if it exists
if [ -f "infrastructure/cdk.context.json" ]; then
    REGION=$(jq -r ".environments.$ENV.region" infrastructure/cdk.context.json 2>/dev/null || echo "us-east-1")
else
    REGION="us-east-1"
fi

# Query CloudFormation for all stacks matching the environment
# Stack naming convention: Collections*-{ENV}
echo -e "${BLUE}🔍 Querying CloudFormation stacks...${NC}"

# Get all stacks that match our naming pattern
STACKS=$(aws cloudformation describe-stacks \
    --region "$REGION" \
    --query "Stacks[?contains(StackName, 'Collections') && contains(StackName, '-${ENV}')].StackName" \
    --output text 2>/dev/null || echo "")

if [ -z "$STACKS" ]; then
    echo -e "${YELLOW}⚠️  No stacks found for environment: ${ENV}${NC}"
    echo "Have you deployed the infrastructure yet?"
    echo "Run: make infra-deploy ENV=${ENV}"
    exit 1
fi

echo -e "${GREEN}✓ Found stacks:${NC}"
for stack in $STACKS; do
    echo "  - $stack"
done
echo ""

# Extract all outputs from all stacks
echo -e "${BLUE}📋 Extracting outputs...${NC}"

aws cloudformation describe-stacks \
    --region "$REGION" \
    --query "Stacks[?contains(StackName, 'Collections') && contains(StackName, '-${ENV}')].Outputs[]" \
    --output json > "$OUTPUT_FILE"

# Check if we got any outputs
OUTPUTS_COUNT=$(jq '. | length' "$OUTPUT_FILE")

if [ "$OUTPUTS_COUNT" -eq 0 ]; then
    echo -e "${YELLOW}⚠️  No outputs found in stacks${NC}"
    echo "The stacks may not have exported any outputs yet."
else
    echo -e "${GREEN}✓ Extracted ${OUTPUTS_COUNT} outputs${NC}"
fi

# Pretty print the outputs
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Stack Outputs for ${ENV}:${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [ "$OUTPUTS_COUNT" -gt 0 ]; then
    jq -r '.[] | "\(.OutputKey): \(.OutputValue)"' "$OUTPUT_FILE" | while read -r line; do
        echo "  $line"
    done
else
    echo "  (No outputs available)"
fi

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo -e "${GREEN}✅ Outputs saved to: ${OUTPUT_FILE}${NC}"
echo ""
echo "Usage:"
echo "  # View all outputs:"
echo "  cat ${OUTPUT_FILE} | jq"
echo ""
echo "  # Get specific output (example):"
echo "  jq -r '.[] | select(.OutputKey==\"ApiUrl\") | .OutputValue' ${OUTPUT_FILE}"
