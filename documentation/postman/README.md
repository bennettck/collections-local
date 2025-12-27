# Postman Collections for Collections API

This directory contains Postman collections and environments for testing the Collections API.

## Available Collections

### Local Development
- **Collection**: `collections-local.postman_collection.json`
- **Environment**: `collections-local.postman_environment.json`
- **Base URL**: `http://localhost:8000`
- **Authentication**: None required
- **Use Case**: Local testing and development

### AWS Deployment
- **Collection**: `collections-aws.postman_collection.json`
- **Environment**: `collections-aws.postman_environment.json`
- **Base URL**: `https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com`
- **Authentication**: AWS Cognito JWT tokens required
- **Use Case**: Testing AWS-deployed API

## Quick Start

### For Local Development

1. Import `collections-local.postman_collection.json`
2. Import `collections-local.postman_environment.json`
3. Select the "Collections Local" environment
4. Start your local API server: `uvicorn main:app --reload`
5. Test with the Health Check endpoint

### For AWS Deployment

1. Import `collections-aws.postman_collection.json`
2. Import `collections-aws.postman_environment.json`
3. Select the "Collections AWS (Dev)" environment
4. Get a JWT token using the AWS CLI:
   ```bash
   aws cognito-idp initiate-auth \
     --auth-flow USER_PASSWORD_AUTH \
     --client-id 1tce0ddbsbm254e9r9p4jar1em \
     --auth-parameters USERNAME=testuser1@example.com,PASSWORD=Collections2025! \
     --region us-east-1
   ```
5. Copy the `IdToken` from the response
6. Set it as the `id_token` variable in your Postman environment
7. Test with the Health Check endpoint

## Test Credentials (AWS Only)

| Email | Password |
|-------|----------|
| testuser1@example.com | Collections2025! |
| testuser2@example.com | Collections2025! |
| demo@example.com | Collections2025! |

## Key Differences

| Feature | Local | AWS |
|---------|-------|-----|
| Authentication | None | Cognito JWT required |
| Multi-tenancy | No | Yes (user_id isolation) |
| Database | SQLite + ChromaDB | PostgreSQL + pgvector + DynamoDB |
| Storage | Local filesystem | S3 with pre-signed URLs |
| Processing | Synchronous | Event-driven (Lambda) |
| Database Routing | Supports production/golden | Not applicable |
| Golden Dataset Tool | Available | Not available |

## Environment Variables

### Local Environment
- `base_url`: http://localhost:8000
- `golden_base_url`: http://golden.localhost:8000
- `item_id`: (auto-populated by tests)
- `analysis_id`: (auto-populated by tests)

### AWS Environment
- `base_url`: https://ttuvnh7u33.execute-api.us-east-1.amazonaws.com
- `cognito_user_pool_id`: us-east-1_SGF7r9htD
- `cognito_client_id`: 1tce0ddbsbm254e9r9p4jar1em
- `cognito_region`: us-east-1
- `id_token`: (set after authentication)
- `access_token`: (set after authentication)
- `refresh_token`: (set after authentication)
- `item_id`: (auto-populated by tests)
- `analysis_id`: (auto-populated by tests)
- `session_id`: (for chat endpoints)
- `filename`: (for image endpoints)

## Authentication Flow (AWS)

1. **Get Token**: Use AWS CLI to authenticate with Cognito
   ```bash
   aws cognito-idp initiate-auth \
     --auth-flow USER_PASSWORD_AUTH \
     --client-id <CLIENT_ID> \
     --auth-parameters USERNAME=<EMAIL>,PASSWORD=<PASSWORD> \
     --region us-east-1
   ```

2. **Set Token**: Copy the `IdToken` and set it as `id_token` in your environment

3. **Use Token**: The collection automatically adds it to the `Authorization: Bearer` header

4. **Refresh Token**: When the token expires (after 1 hour), use the `RefreshToken` to get a new one

## Collection Features

### Local Collection
- Health check (production and golden databases)
- Database routing examples
- Items CRUD operations
- Analysis endpoints
- Search (BM25, Vector, Hybrid, Agentic)
- Index management
- Golden dataset curation
- Keepalive endpoint

### AWS Collection
- Health check
- Items CRUD operations (multi-tenant)
- Analysis endpoints (event-driven)
- Search (BM25, Vector, Hybrid, Agentic) - user-scoped
- Chat endpoints (LangGraph with DynamoDB)
- Image access (S3 pre-signed URLs)
- Authentication helper

## Tips

### Auto-Save Variables
Both collections include test scripts that automatically save:
- `item_id` after uploading an item
- `analysis_id` after analyzing an item

This makes it easy to chain requests together.

### Token Management (AWS)
- Tokens expire after 1 hour
- Set `id_token` as a **secret** variable in your environment
- Clear the token when switching users
- Use the Python script for easier token management:
  ```bash
  python scripts/test_api_access.py --token-only
  cat .api-tokens.json | jq -r .IdToken
  ```

### Testing Workflows

**Local Development:**
1. Upload Item → Analyze Item → Search Collection → View Results

**AWS Deployment:**
1. Get JWT Token → Upload Item → Wait for Event Processing → Search Collection → View Results

## Troubleshooting

### Local Issues
- **Connection Refused**: Make sure the API server is running on port 8000
- **Database Not Found**: Check that `./data/collections.db` exists
- **Golden DB Issues**: Verify `/etc/hosts` entry for `golden.localhost`

### AWS Issues
- **401 Unauthorized**: Token expired or invalid - get a new token
- **403 Forbidden**: User doesn't have permission - check user_id
- **404 Not Found**: Item belongs to another user or doesn't exist
- **429 Too Many Requests**: Rate limit exceeded - wait 60 seconds

## Further Documentation

- **API Documentation (Local)**: [../API.md](../API.md)
- **API Documentation (AWS)**: [../API_AWS.md](../API_AWS.md)
- **Credentials & Setup**: [../../CREDENTIALS.md](../../CREDENTIALS.md)
- **Quick Start Guide**: [../../QUICKSTART.md](../../QUICKSTART.md)
- **Deployment Summary**: [../../AWS_DEPLOYMENT_SUMMARY.md](../../AWS_DEPLOYMENT_SUMMARY.md)
