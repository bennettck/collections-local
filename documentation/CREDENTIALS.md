# Collections Local - User Credentials & Access Guide

## AWS Migration Completion Status
All phases of the AWS migration plan have been completed successfully. The system is now running on AWS serverless infrastructure.

---

## API Access

### API Endpoint
```
https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com/
```

### Region
```
us-east-1 (US East - N. Virginia)
```

---

## User Authentication (Cognito)

### User Pool Configuration
- **User Pool ID**: `us-east-1_SGF7r9htD`
- **User Pool Name**: `collections-dev`
- **App Client ID**: `1tce0ddbsbm254e9r9p4jar1em`
- **App Client Name**: `collections-dev-client`

### Setup Test Users
To configure test users with permanent passwords, run:
```bash
make cognito-setup ENV=dev
```

To list all users in the pool:
```bash
make cognito-list ENV=dev
```

To preview changes without making them:
```bash
make cognito-setup-dry-run ENV=dev
```

### Test User Accounts

**Important**: After deploying infrastructure, run `make cognito-setup ENV=dev` to configure user passwords.

#### User 1
- **Email/Username**: `testuser1@example.com`
- **Password**: `Collections2025!`
- **User ID (sub)**: `94c844d8-10c1-70dd-80e3-4a88742efbb6`

#### User 2
- **Email/Username**: `testuser2@example.com`
- **Password**: `Collections2025!`
- **User ID (sub)**: `7478e4c8-f0b1-70d3-6396-5754bc95ca9e`

#### Demo User
- **Email/Username**: `demo@example.com`
- **Password**: `Collections2025!`
- **User ID (sub)**: `84e84488-a071-70bc-8ed0-d048d2fb193c`

---

## Database Access (RDS PostgreSQL)

### Connection Details
- **Host**: `collectionsdb-dev-postgresqlinstanced9ad3cf0-kxbb6jk93mam.cjc0i0sksmi3.us-east-1.rds.amazonaws.com`
- **Port**: `5432`
- **Database Name**: `collections`
- **Username**: `postgres`
- **Password**: `d9zqRRf1pcgiHUAV6.HUvGdaWppqiH`

### Extensions Enabled
- `pgvector` - for vector similarity search
- `pg_trgm` - for text search optimizations

### Connection String
```
postgresql://postgres:d9zqRRf1pcgiHUAV6.HUvGdaWppqiH@collectionsdb-dev-postgresqlinstanced9ad3cf0-kxbb6jk93mam.cjc0i0sksmi3.us-east-1.rds.amazonaws.com:5432/collections
```

### Quick Connect
```bash
psql -h collectionsdb-dev-postgresqlinstanced9ad3cf0-kxbb6jk93mam.cjc0i0sksmi3.us-east-1.rds.amazonaws.com \
     -p 5432 \
     -U postgres \
     -d collections
```

---

## DynamoDB

### Checkpoint Table
- **Table Name**: `collections-checkpoints-dev`
- **Purpose**: LangGraph conversation state persistence
- **TTL**: 4 hours (automatic cleanup)
- **Access Pattern**: User sessions isolated by `user_id#session_id`

---

## S3 Storage

### Images Bucket
- **Bucket Name**: `collections-images-dev-443370675683`
- **Region**: `us-east-1`
- **Purpose**: Image storage and processing
- **Access**: Pre-signed URLs for secure access

---

## Lambda Functions

### API Lambda
- **Function Name**: `CollectionsCompute-dev-APILambda7D19CDDA-EZseSXjbKwUR`
- **ARN**: `arn:aws:lambda:us-east-1:443370675683:function:CollectionsCompute-dev-APILambda7D19CDDA-EZseSXjbKwUR`
- **Purpose**: FastAPI application with Mangum adapter

### Image Processor Lambda
- **Function Name**: `CollectionsCompute-dev-ImageProcessorLambda383C2A0-BOsNeo2gzYDr`
- **ARN**: `arn:aws:lambda:us-east-1:443370675683:function:CollectionsCompute-dev-ImageProcessorLambda383C2A0-BOsNeo2gzYDr`
- **Purpose**: S3 event-driven image resizing

### Analyzer Lambda
- **Function Name**: `CollectionsCompute-dev-AnalyzerLambdaDB803ECF-syOngKfh5PVu`
- **ARN**: `arn:aws:lambda:us-east-1:443370675683:function:CollectionsCompute-dev-AnalyzerLambdaDB803ECF-syOngKfh5PVu`
- **Purpose**: LLM-powered image analysis

### Embedder Lambda
- **Function Name**: `CollectionsCompute-dev-EmbedderLambdaA8002AC3-ryyxeoVQAqeY`
- **ARN**: `arn:aws:lambda:us-east-1:443370675683:function:CollectionsCompute-dev-EmbedderLambdaA8002AC3-ryyxeoVQAqeY`
- **Purpose**: Generate embeddings for vector search

### Cleanup Lambda
- **Function Name**: `CollectionsCompute-dev-CleanupLambda82DB42D3-GaGyiZb9eBZf`
- **ARN**: `arn:aws:lambda:us-east-1:443370675683:function:CollectionsCompute-dev-CleanupLambda82DB42D3-GaGyiZb9eBZf`
- **Purpose**: Monitor expired sessions

---

## How to Authenticate & Use the API

### Step 1: Get JWT Token

Use AWS Cognito to authenticate and get an access token:

```bash
# Using AWS CLI
aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id 1tce0ddbsbm254e9r9p4jar1em \
  --auth-parameters USERNAME=testuser1@example.com,PASSWORD=Collections2025! \
  --region us-east-1
```

This will return a JSON response containing:
- `IdToken` - Use this for API authentication
- `AccessToken` - For accessing AWS resources
- `RefreshToken` - To refresh the session

### Step 2: Make API Requests

Include the JWT token in the Authorization header:

```bash
# Example: List all items
curl -X GET "https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com/items" \
  -H "Authorization: Bearer YOUR_ID_TOKEN_HERE"

# Example: Create a new item
curl -X POST "https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com/items" \
  -H "Authorization: Bearer YOUR_ID_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{"name": "My Item", "description": "Test item"}'
```

### Step 3: Multi-Tenancy

All API requests are automatically isolated by user:
- Your `user_id` is extracted from the JWT token's `sub` claim
- All database queries are filtered by `user_id`
- You can only access your own data
- Each user has a separate namespace in the system

---

## Available API Endpoints

Base URL: `https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com`

### Items
- `GET /items` - List all items
- `POST /items` - Create new item
- `GET /items/{id}` - Get item details
- `PUT /items/{id}` - Update item
- `DELETE /items/{id}` - Delete item

### Search
- `POST /search/text` - Full-text search (BM25)
- `POST /search/vector` - Vector similarity search
- `POST /search/hybrid` - Hybrid search (BM25 + Vector)
- `POST /search/agentic` - AI-powered conversational search

### Chat
- `POST /chat` - Multi-turn conversation
- `GET /chat/sessions` - List user sessions
- `DELETE /chat/sessions/{id}` - Delete session

### Images
- `POST /images` - Upload image
- `GET /images/{id}` - Get pre-signed URL for image

### Analysis
- `POST /analyze` - Trigger manual analysis
- `GET /analyses/{item_id}` - Get analysis results

---

## Environment & Secrets

All secrets are stored in AWS Systems Manager Parameter Store:
- API keys (Anthropic, Voyage AI, Tavily)
- Database credentials
- Service configurations

Access via AWS CLI:
```bash
aws ssm get-parameter --name /collections/dev/ANTHROPIC_API_KEY --with-decryption
```

---

## Monitoring & Logs

### CloudWatch Logs
View Lambda logs:
```bash
# API Lambda logs
aws logs tail /aws/lambda/CollectionsCompute-dev-APILambda7D19CDDA-EZseSXjbKwUR --follow

# Image Processor logs
aws logs tail /aws/lambda/CollectionsCompute-dev-ImageProcessorLambda383C2A0-BOsNeo2gzYDr --follow
```

### Using Makefile (if configured)
```bash
make lambda-logs FUNC=api
make lambda-logs FUNC=analyzer
make lambda-logs FUNC=embedder
```

---

## Testing Credentials

### Quick Test Script

Save this as `test-api.sh`:

```bash
#!/bin/bash

# Get JWT token
TOKEN_RESPONSE=$(aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id 1tce0ddbsbm254e9r9p4jar1em \
  --auth-parameters USERNAME=testuser1@example.com,PASSWORD=Collections2025! \
  --region us-east-1)

ID_TOKEN=$(echo $TOKEN_RESPONSE | jq -r '.AuthenticationResult.IdToken')

# Test API
curl -X GET "https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com/items" \
  -H "Authorization: Bearer $ID_TOKEN"
```

Make it executable and run:
```bash
chmod +x test-api.sh
./test-api.sh
```

---

## Security Notes

1. **Change Default Passwords**: These are test credentials. For production, use strong, unique passwords.
2. **JWT Expiration**: ID tokens expire after 1 hour. Use the refresh token to get new tokens.
3. **HTTPS Only**: All API endpoints use HTTPS encryption.
4. **User Isolation**: Multi-tenancy ensures data isolation between users.
5. **Database Credentials**: Stored in AWS Secrets Manager, rotated automatically.
6. **S3 Security**: Pre-signed URLs with expiration for secure image access.

---

## Support & Documentation

- **Migration Plan**: `~/.claude/plans/concurrent-beaming-river.md`
- **AWS Outputs**: `.aws-outputs-dev.json`
- **Project Documentation**: `./documentation/`

---

**Last Updated**: 2025-12-27
**Environment**: Development (dev)
**AWS Account**: 443370675683
**Region**: us-east-1
