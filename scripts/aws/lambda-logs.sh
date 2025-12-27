#!/bin/bash
# Tail Lambda CloudWatch logs
# Usage: ./scripts/aws/lambda-logs.sh <function-name> <dev|test|prod>
#
# This script:
# - Tails CloudWatch logs for a Lambda function
# - Follows new log entries in real-time
# - Supports multiple Lambda functions (api, processor, analyzer, embedder, cleanup)
#
# Examples:
#   ./scripts/aws/lambda-logs.sh api dev
#   ./scripts/aws/lambda-logs.sh processor dev

set -e  # Exit on any error
set -u  # Exit on undefined variables

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Parse arguments
FUNC=${1:-}
ENV=${2:-dev}

# Show usage if function not specified
if [ -z "$FUNC" ]; then
    echo -e "${RED}❌ Function name required${NC}"
    echo ""
    echo "Usage: $0 <function-name> <environment>"
    echo ""
    echo "Available functions:"
    echo "  api        - API Lambda (FastAPI)"
    echo "  processor  - Image Processor Lambda"
    echo "  analyzer   - Image Analyzer Lambda"
    echo "  embedder   - Embedding Generator Lambda"
    echo "  cleanup    - Session Cleanup Lambda"
    echo ""
    echo "Example:"
    echo "  $0 api dev"
    echo "  make lambda-logs FUNC=api ENV=dev"
    exit 1
fi

echo -e "${BLUE}📋 Tailing CloudWatch logs for ${FUNC} in ${ENV} environment...${NC}"
echo ""

# Validate environment argument
if [[ ! "$ENV" =~ ^(dev|test|prod)$ ]]; then
    echo -e "${RED}❌ Invalid environment: ${ENV}${NC}"
    echo "Valid environments: dev, test, prod"
    exit 1
fi

# Validate function name
VALID_FUNCTIONS=("api" "processor" "analyzer" "embedder" "cleanup")
if [[ ! " ${VALID_FUNCTIONS[@]} " =~ " ${FUNC} " ]]; then
    echo -e "${YELLOW}⚠️  Warning: Unknown function name: ${FUNC}${NC}"
    echo "Expected one of: ${VALID_FUNCTIONS[*]}"
    echo "Continuing anyway..."
    echo ""
fi

# Check for required tools
command -v aws >/dev/null 2>&1 || {
    echo -e "${RED}❌ AWS CLI not found. Install from https://aws.amazon.com/cli/${NC}"
    exit 1
}

# Validate AWS credentials
aws sts get-caller-identity > /dev/null || {
    echo -e "${RED}❌ AWS credentials not configured${NC}"
    echo "Run: aws configure"
    exit 1
}

# Get region from cdk.context.json if it exists
if [ -f "infrastructure/cdk.context.json" ]; then
    REGION=$(jq -r ".environments.$ENV.region" infrastructure/cdk.context.json 2>/dev/null || echo "us-east-1")
else
    REGION="us-east-1"
fi

# Construct log group name
# Common naming patterns:
# /aws/lambda/collections-{func}-{env}
# /aws/lambda/{stack-name}-{func}-{env}
LOG_GROUP="/aws/lambda/collections-${FUNC}-${ENV}"

echo -e "${BLUE}Region: ${REGION}${NC}"
echo -e "${BLUE}Log Group: ${LOG_GROUP}${NC}"
echo ""

# Check if log group exists
LOG_GROUP_EXISTS=$(aws logs describe-log-groups \
    --region "$REGION" \
    --log-group-name-prefix "$LOG_GROUP" \
    --query "logGroups[?logGroupName=='${LOG_GROUP}'].logGroupName" \
    --output text 2>/dev/null || echo "")

if [ -z "$LOG_GROUP_EXISTS" ]; then
    echo -e "${YELLOW}⚠️  Log group not found: ${LOG_GROUP}${NC}"
    echo ""
    echo "Searching for similar log groups..."

    # Search for any log groups matching the pattern
    SIMILAR_GROUPS=$(aws logs describe-log-groups \
        --region "$REGION" \
        --log-group-name-prefix "/aws/lambda/collections-" \
        --query "logGroups[?contains(logGroupName, '${ENV}')].logGroupName" \
        --output text 2>/dev/null || echo "")

    if [ -n "$SIMILAR_GROUPS" ]; then
        echo -e "${BLUE}Found these log groups for ${ENV}:${NC}"
        echo "$SIMILAR_GROUPS" | tr '\t' '\n' | while read -r group; do
            echo "  - $group"
        done
        echo ""

        # Try to find a matching group
        MATCHED_GROUP=$(echo "$SIMILAR_GROUPS" | tr '\t' '\n' | grep -i "$FUNC" | head -n 1 || echo "")

        if [ -n "$MATCHED_GROUP" ]; then
            echo -e "${GREEN}Using similar log group: ${MATCHED_GROUP}${NC}"
            LOG_GROUP="$MATCHED_GROUP"
        else
            echo -e "${RED}❌ No matching log group found for function: ${FUNC}${NC}"
            exit 1
        fi
    else
        echo -e "${RED}❌ No log groups found for environment: ${ENV}${NC}"
        echo ""
        echo "Possible reasons:"
        echo "  1. Lambda function not deployed yet"
        echo "  2. Function hasn't been invoked (no logs generated)"
        echo "  3. Different naming convention used"
        echo ""
        echo "Deploy the stack:"
        echo "  make infra-deploy ENV=${ENV}"
        exit 1
    fi
fi

echo ""
echo -e "${GREEN}✓ Log group found${NC}"
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Following logs (press Ctrl+C to stop)...${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Tail logs with follow
# --follow: Keep the connection open and wait for new logs
# --format short: Compact format (timestamp + message)
# --since 1h: Show logs from the last hour
aws logs tail "$LOG_GROUP" \
    --region "$REGION" \
    --follow \
    --format short \
    --since 1h

# If user cancels (Ctrl+C), show a clean exit message
echo ""
echo -e "${GREEN}✓ Stopped tailing logs${NC}"
