#!/bin/bash
# Populate Parameter Store from .env file
# Usage: ./scripts/aws/secrets/populate.sh <dev|test|prod>
#
# This script:
# - Reads secrets from .env.{ENV} file
# - Uploads each secret to AWS Systems Manager Parameter Store
# - Uses SecureString type for encryption
# - Overwrites existing parameters
#
# Parameter naming convention: /collections/{env}/{key-name}
# Example: OPENAI_API_KEY -> /collections/dev/openai-api-key

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

echo -e "${BLUE}🔐 Populating Parameter Store for ${ENV} environment...${NC}"
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
echo -e "${BLUE}🔍 Validating AWS credentials...${NC}"
aws sts get-caller-identity > /dev/null || {
    echo -e "${RED}❌ AWS credentials not configured${NC}"
    echo "Run: aws configure"
    exit 1
}

echo -e "${GREEN}✓ AWS credentials valid${NC}"
echo ""

# Check if .env file exists
ENV_FILE=".env.${ENV}"

if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}❌ File ${ENV_FILE} not found${NC}"
    echo ""
    echo "Create the file with your secrets:"
    echo "  cp .env.dev.example ${ENV_FILE}"
    echo "  # Edit ${ENV_FILE} and add your actual secrets"
    exit 1
fi

# Get region from cdk.context.json if it exists
if [ -f "infrastructure/cdk.context.json" ]; then
    REGION=$(jq -r ".environments.$ENV.region" infrastructure/cdk.context.json 2>/dev/null || echo "us-east-1")
else
    REGION="us-east-1"
fi

echo -e "${BLUE}Region: ${REGION}${NC}"
echo -e "${BLUE}Source: ${ENV_FILE}${NC}"
echo ""

# Warning for production
if [ "$ENV" = "prod" ]; then
    echo -e "${YELLOW}⚠️  WARNING: Uploading secrets to PRODUCTION${NC}"
    echo ""
    read -p "Continue? [y/N]: " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
    echo ""
fi

# Counter for uploaded secrets
COUNT=0
SKIPPED=0

# Read .env file and push to Parameter Store
while IFS= read -r line || [ -n "$line" ]; do
    # Skip comments
    if [[ $line =~ ^#.*$ ]]; then
        continue
    fi

    # Skip empty lines
    if [[ -z "$line" ]]; then
        continue
    fi

    # Parse KEY=VALUE
    if [[ $line =~ ^([^=]+)=(.*)$ ]]; then
        key="${BASH_REMATCH[1]}"
        value="${BASH_REMATCH[2]}"

        # Trim whitespace
        key=$(echo "$key" | xargs)
        value=$(echo "$value" | xargs)

        # Skip if key or value is empty
        if [[ -z "$key" ]] || [[ -z "$value" ]]; then
            continue
        fi

        # Convert KEY_NAME to /collections/env/key-name
        param_name=$(echo "$key" | tr '[:upper:]' '[:lower:]' | tr '_' '-')
        param_name="/collections/${ENV}/${param_name}"

        # Remove quotes from value if present
        value=$(echo "$value" | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")

        # Check if value is a placeholder
        if [[ "$value" == "your-"* ]] || [[ "$value" == "sk-"* ]] || [[ "$value" == "REPLACE_"* ]]; then
            echo -e "${YELLOW}⚠️  Skipping placeholder: ${param_name}${NC}"
            ((SKIPPED++))
            continue
        fi

        # Upload to Parameter Store
        echo -e "${BLUE}  → ${param_name}${NC}"

        aws ssm put-parameter \
            --region "$REGION" \
            --name "$param_name" \
            --value "$value" \
            --type "SecureString" \
            --overwrite \
            --no-cli-pager > /dev/null

        ((COUNT++))
    fi
done < "$ENV_FILE"

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ Secrets uploaded successfully${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Statistics:"
echo "  ✓ Uploaded: $COUNT parameter(s)"
if [ $SKIPPED -gt 0 ]; then
    echo "  ⚠ Skipped: $SKIPPED placeholder(s)"
fi
echo ""

if [ $COUNT -eq 0 ]; then
    echo -e "${YELLOW}⚠️  No secrets were uploaded${NC}"
    echo "Make sure your ${ENV_FILE} contains actual values (not placeholders)"
    exit 1
fi

echo "View parameters in AWS Console:"
echo "  https://console.aws.amazon.com/systems-manager/parameters?region=${REGION}"
echo ""
echo "List all parameters:"
echo "  aws ssm get-parameters-by-path --path /collections/${ENV} --region ${REGION}"
echo ""
echo "Get a specific parameter:"
echo "  aws ssm get-parameter --name /collections/${ENV}/openai-api-key --with-decryption --region ${REGION}"
