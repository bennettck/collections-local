# Quick Start Guide - Collections Local (AWS)

Your Collections Local application has been successfully migrated to AWS! This guide will help you get started.

## What's Been Deployed

All 5 phases of the AWS migration are complete:
- Phase 1: AWS Infrastructure (RDS, DynamoDB, S3, Lambda, API Gateway, Cognito)
- Phase 2: Database migration (PostgreSQL with pgvector)
- Phase 3: LangGraph conversation system (DynamoDB checkpointer)
- Phase 4: Lambda functions and FastAPI API
- Phase 5: Testing and validation

## Quick Access

### API Endpoint
```
https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com
```

### Test Users
Three test users have been created for you:

| User | Email | Password |
|------|-------|----------|
| Test User 1 | testuser1@example.com | Collections2025! |
| Test User 2 | testuser2@example.com | Collections2025! |
| Demo User | demo@example.com | Collections2025! |

## Get Started in 30 Seconds

### Option 1: Use the Test Script (Recommended)

```bash
# Install dependencies
pip install boto3 requests

# Run the test script
python scripts/test_api_access.py

# Or test with a specific user
python scripts/test_api_access.py --user testuser2

# Or just get the JWT token
python scripts/test_api_access.py --token-only
```

The script will:
1. Authenticate with Cognito
2. Get your JWT tokens
3. Test the API endpoints
4. Save your tokens to `.api-tokens.json` for reuse

### Option 2: Manual Authentication

```bash
# Get JWT token using AWS CLI
aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id 1tce0ddbsbm254e9r9p4jar1em \
  --auth-parameters USERNAME=testuser1@example.com,PASSWORD=Collections2025! \
  --region us-east-1

# Extract the IdToken from the response and use it:
export ID_TOKEN="your-id-token-here"

# Test the API
curl -H "Authorization: Bearer $ID_TOKEN" \
  https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com/items
```

## Test the API

Once authenticated, you can test various endpoints:

```bash
# List all items
curl -H "Authorization: Bearer $ID_TOKEN" \
  https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com/items

# Get API documentation
curl -H "Authorization: Bearer $ID_TOKEN" \
  https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com/docs

# List chat sessions
curl -H "Authorization: Bearer $ID_TOKEN" \
  https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com/chat/sessions

# Health check
curl -H "Authorization: Bearer $ID_TOKEN" \
  https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com/
```

## Access the Database

If you need direct database access:

```bash
# Using psql
psql postgresql://postgres:d9zqRRf1pcgiHUAV6.HUvGdaWppqiH@collectionsdb-dev-postgresqlinstanced9ad3cf0-kxbb6jk93mam.cjc0i0sksmi3.us-east-1.rds.amazonaws.com:5432/collections

# List tables
\dt

# Check pgvector installation
SELECT * FROM pg_extension WHERE extname = 'vector';

# See user data
SELECT user_id, COUNT(*) FROM items GROUP BY user_id;
```

## View Lambda Logs

```bash
# API Lambda logs
aws logs tail /aws/lambda/CollectionsCompute-dev-APILambda7D19CDDA-EZseSXjbKwUR --follow

# Image processor logs
aws logs tail /aws/lambda/CollectionsCompute-dev-ImageProcessorLambda383C2A0-BOsNeo2gzYDr --follow

# Analyzer logs
aws logs tail /aws/lambda/CollectionsCompute-dev-AnalyzerLambdaDB803ECF-syOngKfh5PVu --follow
```

## Multi-Tenancy

Each user's data is completely isolated:
- Your `user_id` is extracted from your JWT token automatically
- All API requests filter data by your `user_id`
- You can only see and modify your own data
- Chat sessions are isolated per user

Try it:
1. Authenticate as `testuser1@example.com` and create some items
2. Authenticate as `testuser2@example.com` and try to list items
3. You'll see that testuser2 cannot see testuser1's items!

## Example Workflow

Here's a complete example of uploading an image and analyzing it:

```bash
# 1. Authenticate
python scripts/test_api_access.py --token-only

# 2. Load the token
export ID_TOKEN=$(cat .api-tokens.json | jq -r .IdToken)

# 3. Create an item
curl -X POST https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com/items \
  -H "Authorization: Bearer $ID_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My First Item",
    "description": "Testing the API",
    "category": "test"
  }'

# 4. Upload an image (if you have one)
# The API will automatically:
# - Store it in S3
# - Trigger image processing Lambda
# - Analyze it with LLM
# - Generate embeddings for search
# - Make it searchable

# 5. Search for items
curl -X POST https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com/search/text \
  -H "Authorization: Bearer $ID_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "test",
    "limit": 10
  }'

# 6. Have a conversation
curl -X POST https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com/chat \
  -H "Authorization: Bearer $ID_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What items do I have?",
    "session_id": "my-session-1"
  }'
```

## Important Files

- `CREDENTIALS.md` - Complete credentials and configuration details
- `.aws-outputs-dev.json` - AWS infrastructure outputs
- `scripts/test_api_access.py` - Automated API testing script
- `~/.claude/plans/concurrent-beaming-river.md` - Full migration plan

## Architecture

```
User Request
    ↓
API Gateway → API Lambda (FastAPI + Mangum)
                ↓
    ┌───────────┼───────────┐
    ↓           ↓           ↓
PostgreSQL  DynamoDB    S3 Bucket
(pgvector)  (sessions)  (images)
                            ↓
                    Event-Driven Lambdas
                    (Processor → Analyzer → Embedder)
```

## Features Available

- Full CRUD operations on items
- Image upload and storage
- AI-powered image analysis
- Vector similarity search
- Full-text search (BM25)
- Hybrid search
- Multi-turn conversations with LangGraph
- Session persistence in DynamoDB
- Automatic embedding generation
- User isolation and multi-tenancy

## Need Help?

1. Check the logs: `aws logs tail /aws/lambda/[FUNCTION_NAME] --follow`
2. Review credentials: `cat CREDENTIALS.md`
3. Test with script: `python scripts/test_api_access.py`
4. Check infrastructure: `cat .aws-outputs-dev.json`

## Security Reminders

- JWT tokens expire after 1 hour - use refresh tokens to get new ones
- All API calls require authentication
- Change the default passwords for production use
- Database credentials are in AWS Secrets Manager
- S3 images use pre-signed URLs for secure access

---

**Deployment Date**: 2025-12-27
**Environment**: Development (dev)
**Region**: us-east-1
**Status**: All phases complete ✅
