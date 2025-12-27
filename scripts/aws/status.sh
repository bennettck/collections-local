#!/bin/bash
# Show status of all CDK stacks
# Usage: ./scripts/aws/status.sh <dev|test|prod>
#
# This script:
# - Queries CloudFormation for all stacks in the environment
# - Displays stack name and status in a table
# - Shows last updated time
# - Highlights failed or in-progress deployments

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

echo -e "${BLUE}📊 Stack status for ${ENV} environment${NC}"
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

# Query CloudFormation for stacks
echo -e "${BLUE}Region: ${REGION}${NC}"
echo ""

# Get detailed stack information
STACK_INFO=$(aws cloudformation describe-stacks \
    --region "$REGION" \
    --query "Stacks[?contains(StackName, 'Collections') && contains(StackName, '-${ENV}')].[StackName, StackStatus, LastUpdatedTime]" \
    --output json 2>/dev/null || echo "[]")

# Check if any stacks found
STACK_COUNT=$(echo "$STACK_INFO" | jq '. | length')

if [ "$STACK_COUNT" -eq 0 ]; then
    echo -e "${YELLOW}⚠️  No stacks found for environment: ${ENV}${NC}"
    echo ""
    echo "Have you deployed the infrastructure yet?"
    echo "Run: make infra-deploy ENV=${ENV}"
    exit 0
fi

echo -e "${GREEN}✓ Found ${STACK_COUNT} stack(s)${NC}"
echo ""

# Print table header
printf "%-50s %-25s %-25s\n" "STACK NAME" "STATUS" "LAST UPDATED"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Parse and print each stack
echo "$STACK_INFO" | jq -r '.[] | @tsv' | while IFS=$'\t' read -r name status updated; do
    # Color-code status
    case $status in
        *COMPLETE)
            if [[ $status == *ROLLBACK* ]] || [[ $status == DELETE_COMPLETE ]]; then
                STATUS_COLOR="${RED}"
            else
                STATUS_COLOR="${GREEN}"
            fi
            ;;
        *IN_PROGRESS)
            STATUS_COLOR="${YELLOW}"
            ;;
        *FAILED)
            STATUS_COLOR="${RED}"
            ;;
        *)
            STATUS_COLOR="${NC}"
            ;;
    esac

    # Format timestamp (remove timezone for brevity)
    FORMATTED_TIME=$(echo "$updated" | cut -d'T' -f1,2 | tr 'T' ' ')

    printf "%-50s ${STATUS_COLOR}%-25s${NC} %-25s\n" "$name" "$status" "$FORMATTED_TIME"
done

echo ""

# Check for any problematic states
FAILED_STACKS=$(echo "$STACK_INFO" | jq -r '.[] | select(.[1] | contains("FAILED") or contains("ROLLBACK")) | .[0]')

if [ -n "$FAILED_STACKS" ]; then
    echo -e "${RED}⚠️  Failed or rolled back stacks detected:${NC}"
    echo "$FAILED_STACKS" | while read -r stack; do
        echo -e "${RED}  - $stack${NC}"
    done
    echo ""
    echo "To view error details:"
    echo "  aws cloudformation describe-stack-events --stack-name <STACK_NAME> --region $REGION"
    echo ""
fi

# Check for in-progress operations
IN_PROGRESS_STACKS=$(echo "$STACK_INFO" | jq -r '.[] | select(.[1] | contains("IN_PROGRESS")) | .[0]')

if [ -n "$IN_PROGRESS_STACKS" ]; then
    echo -e "${YELLOW}⏳ Operations in progress:${NC}"
    echo "$IN_PROGRESS_STACKS" | while read -r stack; do
        echo -e "${YELLOW}  - $stack${NC}"
    done
    echo ""
    echo "Monitor progress:"
    echo "  watch -n 5 'make infra-status ENV=$ENV'"
    echo ""
fi

# Show quick actions
echo "Quick actions:"
echo "  View outputs:     make infra-outputs ENV=$ENV"
echo "  View stack diff:  make infra-diff ENV=$ENV"
echo "  Redeploy:         make infra-deploy ENV=$ENV"
echo "  Destroy:          make infra-destroy ENV=$ENV"
