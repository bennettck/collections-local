#!/bin/bash
# Connect to RDS PostgreSQL database
# Usage: ./scripts/aws/db-connect.sh <dev|test|prod>
#
# This script:
# - Reads RDS endpoint from stack outputs
# - Retrieves database password from Parameter Store
# - Opens a psql connection to the database
#
# Requirements:
# - psql (PostgreSQL client) installed
# - Stack deployed and outputs available
# - Database password in Parameter Store

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

echo -e "${BLUE}🔌 Connecting to RDS database in ${ENV} environment...${NC}"
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

command -v psql >/dev/null 2>&1 || {
    echo -e "${RED}❌ psql not found. Install PostgreSQL client:${NC}"
    echo "  Ubuntu/Debian: sudo apt-get install postgresql-client"
    echo "  macOS: brew install postgresql"
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

# Get region from cdk.context.json if it exists
if [ -f "infrastructure/cdk.context.json" ]; then
    REGION=$(jq -r ".environments.$ENV.region" infrastructure/cdk.context.json 2>/dev/null || echo "us-east-1")
else
    REGION="us-east-1"
fi

# Check if outputs file exists
OUTPUTS_FILE=".aws-outputs-${ENV}.json"

if [ ! -f "$OUTPUTS_FILE" ]; then
    echo -e "${YELLOW}⚠️  Outputs file not found: ${OUTPUTS_FILE}${NC}"
    echo "Extracting outputs..."
    bash ./scripts/aws/outputs.sh "$ENV"
    echo ""
fi

# Read database connection details from outputs
echo -e "${BLUE}📋 Reading database connection details...${NC}"

# Try different possible output key names
ENDPOINT=$(jq -r '.[] | select(.OutputKey=="RdsEndpoint" or .OutputKey=="DatabaseEndpoint" or .OutputKey=="DbEndpoint") | .OutputValue' "$OUTPUTS_FILE" 2>/dev/null || echo "")
DB_NAME=$(jq -r '.[] | select(.OutputKey=="DatabaseName" or .OutputKey=="DbName") | .OutputValue' "$OUTPUTS_FILE" 2>/dev/null || echo "collections")
DB_USER=$(jq -r '.[] | select(.OutputKey=="DatabaseUser" or .OutputKey=="DbUser") | .OutputValue' "$OUTPUTS_FILE" 2>/dev/null || echo "collections_admin")

if [ -z "$ENDPOINT" ] || [ "$ENDPOINT" = "null" ]; then
    echo -e "${RED}❌ Database endpoint not found in outputs${NC}"
    echo ""
    echo "Expected output keys: RdsEndpoint, DatabaseEndpoint, or DbEndpoint"
    echo ""
    echo "Available outputs:"
    jq -r '.[] | .OutputKey' "$OUTPUTS_FILE"
    exit 1
fi

echo -e "${GREEN}✓ Endpoint: ${ENDPOINT}${NC}"
echo -e "${GREEN}✓ Database: ${DB_NAME}${NC}"
echo -e "${GREEN}✓ User: ${DB_USER}${NC}"
echo ""

# Get password from Parameter Store
echo -e "${BLUE}🔐 Retrieving password from Parameter Store...${NC}"

# Try different possible parameter names
PARAM_NAMES=(
    "/collections/${ENV}/database-password"
    "/collections/${ENV}/db-password"
    "/collections/${ENV}/rds-password"
)

PASSWORD=""
for param_name in "${PARAM_NAMES[@]}"; do
    PASSWORD=$(aws ssm get-parameter \
        --region "$REGION" \
        --name "$param_name" \
        --with-decryption \
        --query 'Parameter.Value' \
        --output text 2>/dev/null || echo "")

    if [ -n "$PASSWORD" ]; then
        echo -e "${GREEN}✓ Password retrieved from: ${param_name}${NC}"
        break
    fi
done

if [ -z "$PASSWORD" ]; then
    echo -e "${RED}❌ Database password not found in Parameter Store${NC}"
    echo ""
    echo "Tried these parameter names:"
    for param_name in "${PARAM_NAMES[@]}"; do
        echo "  - $param_name"
    done
    echo ""
    echo "Upload password to Parameter Store:"
    echo "  aws ssm put-parameter --name /collections/${ENV}/database-password \\"
    echo "    --value 'YOUR_PASSWORD' --type SecureString --region ${REGION}"
    exit 1
fi

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✓ Connected to PostgreSQL${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Useful commands:"
echo "  \\dt              - List all tables"
echo "  \\d table_name    - Describe a table"
echo "  \\q               - Quit"
echo "  SELECT version(); - Show PostgreSQL version"
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Connect to database
# PGPASSWORD environment variable is used to avoid password prompt
PGPASSWORD="$PASSWORD" psql \
    -h "$ENDPOINT" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    -p 5432
