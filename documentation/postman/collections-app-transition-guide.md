# Collections App AWS Migration Guide

## Executive Summary

This document outlines the architecture and migration strategy for the Collections App, transitioning from a monolithic deployment to a serverless AWS architecture. The primary directives are:

1. **Libraries First** - Minimize custom code; leverage proven libraries
2. **AWS Best Practices** - Use native AWS services and patterns

### Table of Contents

1. [Technology Stack](#technology-stack) - Libraries and services used
2. [Target Architecture](#target-architecture) - Core design principles
3. [Folder Structure](#folder-structure) - Project organization
4. [Infrastructure Components](#infrastructure-components) - CDK stacks (Database, Compute, API, Monitoring)
5. [Data Architecture](#data-architecture) - PostgreSQL schema and models
6. [Search Implementation](#search-implementation) - Vector, BM25, hybrid, and agentic search
7. [Library Usage Summary](#library-usage-summary) - What to use vs. build custom
8. [Secrets Management](#secrets-management) - SSM and Secrets Manager patterns
9. [Deployment](#deployment) - Prerequisites and deployment order
10. [New Repository Setup](#new-repository-setup) - Fresh start migration approach
11. [Migration Checklist](#migration-checklist) - Phase-by-phase tasks
12. [Cost Optimization](#cost-optimization) - Free tier and cost management
13. [Observability](#observability) - LangSmith and CloudWatch
14. [AWS Lambda Powertools](#aws-lambda-powertools-required) - Required utilities reference
15. [Security](#security) - Network, data, and authentication
16. [Makefile & Scripts Updates](#makefile--scripts-updates) - Build tooling changes
17. [Troubleshooting](#troubleshooting) - Common issues and debugging
18. [Future Enhancements](#future-enhancements) - Roadmap items

### About Code Examples

Code examples in this document follow a hybrid approach:

| Section | Type | Usage |
|---------|------|-------|
| **CDK Infrastructure** | Prescriptive | Copy-paste ready; use as-is |
| **SSM Parameter Paths** | Prescriptive | Follow exact naming conventions |
| **Powertools Setup** | Prescriptive | Standard boilerplate; use as-is |
| **API Route Handlers** | Illustrative | Patterns to adapt to your business logic |
| **Search Implementations** | Illustrative | Reference for existing code migration |
| **SQLAlchemy Models** | Illustrative | Schema reference; adapt field names |

**Prescriptive** = Copy directly into your codebase
**Illustrative** = Understand the pattern, adapt to your implementation

---

## Technology Stack

### Libraries & Services

| Component | Current Implementation | Library |
|-----------|----------------------|---------|
| **API Framework** | Powertools Event Handler | `aws-lambda-powertools` |
| **Database ORM** | SQLAlchemy 2.0 | `sqlalchemy` |
| **Database** | PostgreSQL 16 with pgvector | AWS RDS |
| **Vector Store** | langchain-postgres (PGVector) | `langchain-postgres` |
| **Embeddings** | VoyageAI | `langchain-voyageai`, `voyageai` |
| **LLM Operations** | LangChain + LangSmith | `langchain-anthropic`, `langchain-openai` |
| **Agent Framework** | LangGraph | `langgraph` |
| **Checkpointing** | langgraph-checkpoint-postgres | `langgraph-checkpoint-postgres` |
| **Infrastructure** | AWS CDK (Python) | `aws-cdk-lib` |
| **Secrets** | AWS Secrets Manager + SSM Parameter Store | `boto3` |
| **Image Processing** | Pillow | `pillow` |
| **Observability (LLM)** | LangSmith | `langsmith` |
| **Observability (AWS)** | Lambda Powertools | `aws-lambda-powertools` |

### Current Architecture Strengths

1. **Single Source of Truth**: `langchain_pg_embedding` table serves both BM25 and vector search
2. **Multi-tenancy**: User isolation via `user_id` in metadata filtering
3. **Hybrid Search**: RRF fusion combining PostgreSQL full-text search + pgvector
4. **Event-Driven**: EventBridge for async workflows (S3 → Process → Analyze → Embed)
5. **Serverless-Ready**: Docker-based Lambda functions with Powertools Event Handler

---

## Target Architecture

### Core Principles

1. **AWS CDK for Infrastructure** - Use CDK (Python) for all infrastructure-as-code:
   - Complex multi-stack dependencies (VPC, RDS, Lambda, API Gateway)
   - Programmatic constructs over YAML configuration
   - Type-safe infrastructure definitions
   - *Note: SAM is not used; CDK provides better support for complex architectures*

2. **Libraries First** - Use library solutions wherever possible:
   - Vector Search: `langchain-postgres` PGVector
   - Agent Checkpointing: `langgraph-checkpoint-postgres`
   - Embeddings: `langchain-voyageai`
   - Observability: `aws-lambda-powertools`

3. **AWS Native Services**:
   - Lambda for compute (Docker images for complex dependencies)
   - RDS PostgreSQL for all data (items, analyses, vectors, checkpoints)
   - S3 for image storage
   - EventBridge for workflow orchestration
   - Secrets Manager for credentials
   - API Gateway HTTP API for REST endpoints
   - Cognito for authentication

4. **Single Database Strategy**:
   - PostgreSQL with pgvector handles ALL data
   - No DynamoDB
   - Checkpointing via `langgraph-checkpoint-postgres`

---

## Folder Structure

```
collections-app/
├── api/                          # API Lambda code
│   ├── handler.py               # Powertools Event Handler (routes)
│   ├── services/                # Business logic services
│   │   ├── item_service.py
│   │   ├── search_service.py
│   │   ├── chat_service.py
│   │   └── upload_service.py
│   └── Dockerfile               # API Lambda Docker image
│
├── chat/                         # Multi-turn conversation
│   ├── agentic_chat.py          # AgenticChatOrchestrator (LangGraph)
│   ├── conversation_manager.py   # PostgreSQL checkpointing wrapper
│   └── checkpointers/
│       └── postgres_saver.py    # langgraph-checkpoint-postgres wrapper
│
├── config/                       # Configuration modules
│   ├── agent_config.py          # Agent model/behavior settings
│   ├── chat_config.py           # Chat/conversation settings
│   ├── langchain_config.py      # Embedding/vector store config
│   └── retriever_config.py      # BM25/hybrid search parameters
│
├── database_orm/                 # SQLAlchemy models
│   ├── models.py                # Item, Analysis (NO Embedding model)
│   ├── connection.py            # Connection manager with Secrets Manager
│   └── migrations/              # Alembic migrations
│
├── retrieval/                    # Search implementations
│   ├── pgvector_store.py        # PGVectorStoreManager (langchain-postgres)
│   ├── postgres_bm25.py         # PostgresBM25Retriever (tsvector/tsquery)
│   ├── hybrid_retriever.py      # RRF fusion (BM25 + Vector)
│   ├── agentic_search.py        # AgenticSearchOrchestrator
│   └── answer_generator.py      # LLM answer generation
│
├── infrastructure/               # AWS CDK
│   ├── app.py                   # CDK app entry point
│   ├── cdk.context.json         # Environment configurations
│   ├── stacks/
│   │   ├── database_stack.py    # RDS PostgreSQL + pgvector
│   │   ├── compute_stack.py     # Lambda functions + S3
│   │   ├── api_stack.py         # API Gateway + Cognito
│   │   └── monitoring_stack.py  # CloudWatch dashboards/alarms
│   └── cdk_constructs/
│       ├── lambda_function.py   # Reusable Lambda construct
│       └── secret_parameter.py  # SSM parameter construct
│
├── lambdas/                      # Lambda function code
│   ├── image_processor/         # S3 trigger → thumbnail → EventBridge
│   ├── analyzer/                # EventBridge → LLM analysis → DB
│   ├── embedder/                # EventBridge → VoyageAI → pgvector
│   └── cleanup/                 # Scheduled cleanup monitoring
│
├── utils/                        # Shared utilities
│   ├── powertools.py            # Logger, Tracer, Metrics instances
│   ├── config.py                # SSM parameter retrieval (Powertools)
│   ├── document_builder.py      # Unified document creation
│   └── similarity.py            # Comparison utilities
│
├── llm.py                        # Image analysis (LangChain)
├── embeddings.py                 # VoyageAI embeddings
└── database_sqlalchemy.py        # Database operations wrapper
```

---

## Infrastructure Components

### Database Stack (database_stack.py)

**Creates**:
- VPC with public subnets (simplified for cost)
- RDS PostgreSQL 16 with pgvector extension
- Bastion host for SSM-based database access
- Secrets Manager for database credentials
- SSM Parameter Store for API keys

**Key Configuration**:
```python
# Database instance
instance_type = "db.t4g.micro"  # Free tier eligible
storage = 20  # GB, gp3
multi_az = False  # Cost optimization
backup_retention = 7  # Days

# pgvector enabled via parameter group
# Extension created manually: CREATE EXTENSION IF NOT EXISTS vector;
```

**Exports**: 
- `RDSEndpoint`, `RDSPort`, `DatabaseSecretArn`
- `BastionInstanceId` (for SSM port forwarding)

---

### Compute Stack (compute_stack.py)

**Lambda Functions**:

| Function | Trigger | Runtime | Memory | Timeout |
|----------|---------|---------|--------|---------|
| API | API Gateway | Docker (Python 3.12) | 1024MB | 30s |
| ImageProcessor | S3 ObjectCreated | Python 3.12 | 512MB | 60s |
| Analyzer | EventBridge | Python 3.12 | 1024MB | 120s |
| Embedder | EventBridge | Docker (Python 3.12) | 512MB | 60s |
| Cleanup | EventBridge Schedule | Python 3.12 | 256MB | 60s |

#### Docker vs Lambda Layers: Current State & Recommendations

**Current Implementation**: API and Embedder use Docker; others use standard Python runtime.

| Factor | Docker Lambda | Standard + Layers |
|--------|---------------|-------------------|
| Cold start | **Slower** (2-5s+) | Faster (~500ms) |
| Deployment size limit | 10GB | 250MB unzipped (50MB zipped/layer) |
| Build complexity | Dockerfile required | pip install |
| Local testing | Easier (identical env) | May differ from Lambda |
| ECR costs | Container storage fees | No extra storage |
| Provisioned concurrency | Higher cost to mitigate cold starts | Less critical |

**Why Docker is currently used**:
- Convenience during development (complex dependency tree)
- Assumed dependencies exceed 250MB layer limit

**Potential Optimization**:
The dependencies (`langchain-postgres`, `psycopg2-binary`, `voyageai`) may fit within Lambda layers if selectively packaged. Docker was likely chosen for convenience rather than necessity.

**Recommendation** (AWS best practices):
1. **Audit actual dependency sizes** - many packages include unnecessary extras
2. **Try Lambda layers first** - faster cold starts, lower cost
3. **Use Docker only if** layer limits are exceeded or native builds fail
4. **If Docker is required** - consider Provisioned Concurrency for latency-sensitive endpoints

```bash
# Check unzipped size of dependencies
pip install --target ./package langchain-postgres psycopg2-binary voyageai
du -sh ./package
# If < 250MB, layers are viable
```

**EventBridge Events**:
```
S3 Upload → ImageProcessor → "ImageProcessed" event
                                    ↓
                              Analyzer → "AnalysisComplete" event
                                              ↓
                                        Embedder (stores in pgvector)
```

**S3 Bucket (Image Storage)**:

```python
# infrastructure/stacks/compute_stack.py

from aws_cdk import (
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    RemovalPolicy,
    Duration,
)

# Image storage bucket
self.images_bucket = s3.Bucket(
    self,
    "ImagesBucket",
    bucket_name=f"collections-images-{env}",
    
    # Security
    block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
    encryption=s3.BucketEncryption.S3_MANAGED,
    enforce_ssl=True,
    
    # EventBridge integration (required for Lambda triggers)
    event_bridge_enabled=True,
    
    # CORS for direct browser uploads
    cors=[
        s3.CorsRule(
            allowed_methods=[s3.HttpMethods.PUT, s3.HttpMethods.POST, s3.HttpMethods.GET],
            allowed_origins=["https://your-app-domain.com"],  # Configure per environment
            allowed_headers=["*"],
            max_age=3000,
        )
    ],
    
    # Lifecycle rules
    lifecycle_rules=[
        # Transition thumbnails to Infrequent Access after 90 days
        s3.LifecycleRule(
            id="ThumbnailsToIA",
            prefix="thumbnails/",
            transitions=[
                s3.Transition(
                    storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                    transition_after=Duration.days(90),
                )
            ],
        ),
        # Delete failed/incomplete multipart uploads
        s3.LifecycleRule(
            id="CleanupIncompleteUploads",
            abort_incomplete_multipart_upload_after=Duration.days(1),
        ),
    ],
    
    # Retain bucket on stack deletion (protect user data)
    removal_policy=RemovalPolicy.RETAIN,
    auto_delete_objects=False,
)
```

**Bucket Structure**:
```
collections-images-{env}/
├── originals/
│   └── {user_id}/{item_id}.{ext}     # Full-size uploads
├── thumbnails/
│   └── {user_id}/{item_id}_thumb.webp # Generated thumbnails
└── temp/
    └── {upload_id}/                   # Multipart upload staging
```

**Key Configuration Notes**:

| Setting | Value | Rationale |
|---------|-------|-----------|
| `event_bridge_enabled` | `True` | Required for S3 → EventBridge → Lambda flow |
| `block_public_access` | `BLOCK_ALL` | No public access; presigned URLs for downloads |
| `encryption` | `S3_MANAGED` | Encryption at rest |
| `removal_policy` | `RETAIN` | Prevent accidental data loss on stack deletion |

**Presigned URLs for Upload/Download**:
```python
# api/routes/uploads.py

import boto3
from botocore.config import Config

s3_client = boto3.client('s3', config=Config(signature_version='s3v4'))

def generate_upload_url(user_id: str, filename: str) -> str:
    """Generate presigned URL for direct browser upload."""
    key = f"originals/{user_id}/{uuid4()}_{filename}"
    return s3_client.generate_presigned_url(
        'put_object',
        Params={
            'Bucket': os.environ['IMAGES_BUCKET'],
            'Key': key,
            'ContentType': 'image/*',
        },
        ExpiresIn=300,  # 5 minutes
    )

def generate_download_url(key: str) -> str:
    """Generate presigned URL for image download."""
    return s3_client.generate_presigned_url(
        'get_object',
        Params={
            'Bucket': os.environ['IMAGES_BUCKET'],
            'Key': key,
        },
        ExpiresIn=3600,  # 1 hour
    )
```

**Lambda Trigger Configuration**:
```python
# S3 → EventBridge → Lambda (preferred over direct S3 notifications)
# EventBridge provides: filtering, retry, multiple targets, archive/replay

from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets

# Rule: S3 object created in originals/
s3_upload_rule = events.Rule(
    self,
    "S3UploadRule",
    event_pattern=events.EventPattern(
        source=["aws.s3"],
        detail_type=["Object Created"],
        detail={
            "bucket": {"name": [self.images_bucket.bucket_name]},
            "object": {"key": [{"prefix": "originals/"}]},
        },
    ),
)
s3_upload_rule.add_target(targets.LambdaFunction(image_processor_lambda))

---

### API Stack (api_stack.py)

**Creates**:
- Cognito User Pool (email-based authentication)
- Cognito User Pool Client (USER_PASSWORD_AUTH flow)
- API Gateway HTTP API
- JWT Authorizer (Cognito)
- CORS configuration

#### Cognito User Pool Configuration

```python
# infrastructure/stacks/api_stack.py

from aws_cdk import (
    aws_cognito as cognito,
    aws_apigatewayv2 as apigw,
    aws_apigatewayv2_authorizers as authorizers,
    aws_apigatewayv2_integrations as integrations,
    Duration,
)

class ApiStack(Stack):
    def __init__(self, scope, id, compute_stack, env_name, **kwargs):
        super().__init__(scope, id, **kwargs)
        
        # Cognito User Pool
        self.user_pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name=f"collections-users-{env_name}",
            
            # Sign-in options
            sign_in_aliases=cognito.SignInAliases(
                email=True,
                username=False,
            ),
            
            # Password policy
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=False,
            ),
            
            # Self-service sign-up
            self_sign_up_enabled=True,
            
            # Email verification
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            
            # Account recovery
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            
            # MFA (optional, enable for production)
            mfa=cognito.Mfa.OPTIONAL,
            mfa_second_factor=cognito.MfaSecondFactor(
                sms=False,
                otp=True,
            ),
        )
        
        # User Pool Client (for web/mobile app)
        self.user_pool_client = self.user_pool.add_client(
            "WebClient",
            user_pool_client_name=f"collections-web-{env_name}",
            
            # Auth flows
            auth_flows=cognito.AuthFlow(
                user_password=True,      # USER_PASSWORD_AUTH
                user_srp=True,           # USER_SRP_AUTH (more secure)
            ),
            
            # Token validity
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(30),
            
            # Prevent client secret (for public clients like web apps)
            generate_secret=False,
        )
```

#### API Gateway HTTP API Configuration

```python
        # HTTP API (cheaper than REST API, lower latency)
        self.http_api = apigw.HttpApi(
            self,
            "HttpApi",
            api_name=f"collections-api-{env_name}",
            
            # CORS configuration
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=self._get_allowed_origins(env_name),
                allow_methods=[
                    apigw.CorsHttpMethod.GET,
                    apigw.CorsHttpMethod.POST,
                    apigw.CorsHttpMethod.PUT,
                    apigw.CorsHttpMethod.DELETE,
                    apigw.CorsHttpMethod.OPTIONS,
                ],
                allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
                allow_credentials=True,
                max_age=Duration.hours(1),
            ),
        )
        
        # JWT Authorizer (validates Cognito tokens)
        jwt_authorizer = authorizers.HttpJwtAuthorizer(
            "JwtAuthorizer",
            jwt_issuer=f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool.user_pool_id}",
            jwt_audience=[self.user_pool_client.user_pool_client_id],
            authorizer_name=f"cognito-jwt-{env_name}",
        )
        
        # Lambda integration
        api_integration = integrations.HttpLambdaIntegration(
            "ApiIntegration",
            handler=compute_stack.api_lambda,
        )
```

#### Route Configuration

```python
        # ============================================
        # PUBLIC ROUTES (no authentication required)
        # ============================================
        
        self.http_api.add_routes(
            path="/health",
            methods=[apigw.HttpMethod.GET],
            integration=api_integration,
            # No authorizer = public
        )
        
        self.http_api.add_routes(
            path="/version",
            methods=[apigw.HttpMethod.GET],
            integration=api_integration,
        )
        
        # ============================================
        # PROTECTED ROUTES (JWT required)
        # ============================================
        
        # Items CRUD
        self.http_api.add_routes(
            path="/items",
            methods=[apigw.HttpMethod.GET, apigw.HttpMethod.POST],
            integration=api_integration,
            authorizer=jwt_authorizer,
        )
        
        self.http_api.add_routes(
            path="/items/{item_id}",
            methods=[apigw.HttpMethod.GET, apigw.HttpMethod.PUT, apigw.HttpMethod.DELETE],
            integration=api_integration,
            authorizer=jwt_authorizer,
        )
        
        # Search endpoints
        self.http_api.add_routes(
            path="/search",
            methods=[apigw.HttpMethod.POST],
            integration=api_integration,
            authorizer=jwt_authorizer,
        )
        
        self.http_api.add_routes(
            path="/search/hybrid",
            methods=[apigw.HttpMethod.POST],
            integration=api_integration,
            authorizer=jwt_authorizer,
        )
        
        self.http_api.add_routes(
            path="/search/agentic",
            methods=[apigw.HttpMethod.POST],
            integration=api_integration,
            authorizer=jwt_authorizer,
        )
        
        # Chat endpoints
        self.http_api.add_routes(
            path="/chat",
            methods=[apigw.HttpMethod.POST],
            integration=api_integration,
            authorizer=jwt_authorizer,
        )
        
        self.http_api.add_routes(
            path="/chat/sessions",
            methods=[apigw.HttpMethod.GET],
            integration=api_integration,
            authorizer=jwt_authorizer,
        )
        
        self.http_api.add_routes(
            path="/chat/sessions/{session_id}",
            methods=[apigw.HttpMethod.GET, apigw.HttpMethod.DELETE],
            integration=api_integration,
            authorizer=jwt_authorizer,
        )
        
        # Upload (presigned URL generation)
        self.http_api.add_routes(
            path="/uploads/presigned",
            methods=[apigw.HttpMethod.POST],
            integration=api_integration,
            authorizer=jwt_authorizer,
        )
        
        # ============================================
        # ALTERNATIVE: Catch-all proxy route
        # ============================================
        # If using Powertools internal routing exclusively:
        #
        # self.http_api.add_routes(
        #     path="/{proxy+}",
        #     methods=[apigw.HttpMethod.ANY],
        #     integration=api_integration,
        #     authorizer=jwt_authorizer,
        # )
        #
        # Note: Catch-all means ALL routes require auth.
        # Public routes (/health, /version) must be added BEFORE proxy.
        
    def _get_allowed_origins(self, env_name: str) -> list[str]:
        """CORS origins per environment."""
        if env_name == "prod":
            return ["https://collections.yourdomain.com"]
        elif env_name == "staging":
            return ["https://staging.collections.yourdomain.com"]
        else:
            return ["http://localhost:3000", "http://localhost:5173"]  # Local dev
```

#### API Route Summary

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | ✗ | Health check |
| GET | `/version` | ✗ | API version |
| GET | `/items` | ✓ | List user's items |
| POST | `/items` | ✓ | Create item (metadata only) |
| GET | `/items/{item_id}` | ✓ | Get item details |
| PUT | `/items/{item_id}` | ✓ | Update item |
| DELETE | `/items/{item_id}` | ✓ | Delete item |
| POST | `/search` | ✓ | Hybrid search (default) |
| POST | `/search/hybrid` | ✓ | Explicit hybrid search |
| POST | `/search/agentic` | ✓ | Agentic search with LLM |
| POST | `/chat` | ✓ | Send chat message |
| GET | `/chat/sessions` | ✓ | List chat sessions |
| GET | `/chat/sessions/{session_id}` | ✓ | Get session history |
| DELETE | `/chat/sessions/{session_id}` | ✓ | Delete session |
| POST | `/uploads/presigned` | ✓ | Get presigned S3 upload URL |

#### Stack Outputs & SSM Parameters

```python
        # ============================================
        # Store configuration in SSM for Lambda access
        # (Powertools retrieves these at runtime)
        # ============================================
        
        ssm.StringParameter(
            self,
            "UserPoolIdParam",
            parameter_name=f"/collections/{env_name}/cognito/user-pool-id",
            string_value=self.user_pool.user_pool_id,
        )
        
        ssm.StringParameter(
            self,
            "ClientIdParam",
            parameter_name=f"/collections/{env_name}/cognito/client-id",
            string_value=self.user_pool_client.user_pool_client_id,
        )
        
        ssm.StringParameter(
            self,
            "CognitoRegionParam",
            parameter_name=f"/collections/{env_name}/cognito/region",
            string_value=self.region,
        )
        
        ssm.StringParameter(
            self,
            "ApiEndpointParam",
            parameter_name=f"/collections/{env_name}/api/endpoint",
            string_value=self.http_api.url,
        )
        
        # ============================================
        # CloudFormation Outputs (for CLI/scripts)
        # ============================================
        
        CfnOutput(self, "ApiEndpoint", value=self.http_api.url)
        CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        CfnOutput(self, "UserPoolClientId", value=self.user_pool_client.user_pool_client_id)
        CfnOutput(self, "CognitoRegion", value=self.region)
```

**Frontend Configuration**:

Option A: Static config (from CDK outputs):
```javascript
// frontend/src/config.js
export const config = {
  apiEndpoint: "https://abc123.execute-api.us-west-2.amazonaws.com",
  cognito: {
    userPoolId: "us-west-2_xxxxx",
    clientId: "xxxxxxxxxxxxxxxxxxxxxxxxxx",
    region: "us-west-2",
  },
};
```

Option B: Dynamic config (fetch from SSM via API):
```javascript
// frontend/src/config.js
export async function getConfig() {
  const response = await fetch(`${API_ENDPOINT}/config`);
  return response.json();
}

// Add public /config endpoint that returns SSM values
// (No auth required, returns non-sensitive config only)
```

**Lambda Access to Config** (via Powertools):
```python
# See "SSM Parameter Store" section for get_cognito_config() implementation
from utils.config import get_cognito_config, get_api_keys

config = get_cognito_config()  # Cached via @lru_cache
api_keys = get_api_keys()      # Cached via @lru_cache
```

**Public Endpoints** (no auth):
- `GET /health`
- `GET /version`

**Protected Endpoints** (JWT required):
- All other routes (see table above)

---

### User Identity: JWT `sub` Claim → `user_id`

**Critical**: The `user_id` used throughout the application comes from the Cognito JWT `sub` claim. This is the **only trusted source** of user identity.

#### Extracting User ID from JWT (Powertools Event Handler)

```python
# api/handler.py

from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, Response
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger()
tracer = Tracer()
metrics = Metrics()
app = APIGatewayHttpResolver()


def get_user_id() -> str:
    """Extract user_id from JWT claims (already validated by API Gateway)."""
    claims = app.current_event.request_context.authorizer.jwt_claim
    return claims["sub"]


# Public route (no auth)
@app.get("/health")
def health():
    return {"status": "healthy"}


# Protected route pattern
@app.get("/items")
@tracer.capture_method
def list_items():
    user_id = get_user_id()  # Always extract from JWT
    logger.info("Listing items", extra={"user_id": user_id})
    
    items = item_service.list_by_user(user_id)
    return {"items": items}


@app.post("/search")
@tracer.capture_method
def search():
    user_id = get_user_id()
    body = app.current_event.json_body
    
    results = search_service.search(
        query=body.get("query"),
        user_id=user_id,  # Always scope to user
    )
    return {"results": results}


# Lambda entry point
@logger.inject_lambda_context(log_event=True)
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event, context):
    return app.resolve(event, context)
```

#### User Identity Flow

```
Browser → API Gateway → JWT Authorizer (validates signature)
                              ↓
                        Lambda (Powertools Event Handler)
                              ↓
                        app.current_event.request_context.authorizer.jwt_claim
                              ↓
                        Extract 'sub' claim → user_id
                              ↓
                        Route handler uses get_user_id()
```

#### Where `user_id` Is Applied

| Table/Storage | Column/Field | Source |
|---------------|--------------|--------|
| `items` | `user_id` | JWT `sub` at creation |
| `analyses` | `user_id` | Copied from parent `item.user_id` |
| `langchain_pg_embedding` | `cmetadata->>'user_id'` | Copied from `item.user_id` during embedding |
| `checkpoints` | `thread_id` prefix | Format: `{user_id}#{session_id}` |
| S3 | Object key prefix | `originals/{user_id}/...` |

#### Security Rules

1. **Never trust user-provided `user_id`** - Always extract from JWT via `get_user_id()`
2. **All queries must filter by `user_id`** - No cross-tenant data access
3. **S3 keys include `user_id`** - Prevents path traversal attacks
4. **Denormalize `user_id`** - Store in `analyses` table for fast filtering without joins

---

### Monitoring Stack (monitoring_stack.py)

**CloudWatch Dashboard**:
- API Gateway: requests, errors, latency
- Lambda: invocations, errors, duration (all functions)
- RDS: connections, CPU, storage

**Alarms** (test/prod only):
- API 5XX errors > 10 in 5 minutes
- Lambda errors > 5 in 5 minutes
- RDS CPU > 80% for 10 minutes
- RDS storage < 1GB

---

## Data Architecture

### Single Source of Truth: `langchain_pg_embedding`

**Critical Design Decision**: All search operations use the same table.

```sql
-- Table managed by langchain-postgres
CREATE TABLE langchain_pg_embedding (
    id UUID PRIMARY KEY,
    collection_id UUID REFERENCES langchain_pg_collection(uuid),
    embedding vector(1024),  -- VoyageAI voyage-3.5-lite
    document TEXT,           -- Full-text content for BM25
    cmetadata JSONB          -- user_id, item_id, category, headline, etc.
);

-- Indexes
CREATE INDEX ON langchain_pg_embedding USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX ON langchain_pg_embedding USING gin (to_tsvector('english', document));
CREATE INDEX ON langchain_pg_embedding ((cmetadata->>'user_id'));
```

**Why This Matters**:
- BM25 and Vector search always return consistent results
- No sync issues between separate keyword/vector stores
- Single write path (Embedder Lambda)
- Simplified backup/restore

### SQLAlchemy Models (NO Embedding Model)

```python
# database_orm/models.py

class Item(Base):
    """Uploaded files with metadata."""
    __tablename__ = "items"
    id: str  # UUID
    user_id: str  # From JWT 'sub' claim - NEVER from request body
    filename: str
    file_path: str
    # ... timestamps, file metadata

class Analysis(Base):
    """AI-generated analysis results."""
    __tablename__ = "analyses"
    id: str  # UUID
    item_id: str  # FK to items
    user_id: str  # Denormalized from item.user_id for fast queries
    version: int  # Versioning support
    category: str
    summary: str
    raw_response: JSONB  # Full analysis data
    search_vector: TSVECTOR  # Auto-populated via trigger
    # ... provider info, timestamps

# NOTE: No Embedding model - embeddings stored in langchain_pg_embedding
# NOTE: user_id in analyses is denormalized from items.user_id, not from JWT directly
```

**User ID Propagation**:
```
JWT 'sub' claim
    ↓
Item created with user_id
    ↓
Analysis created with user_id (copied from item)
    ↓
Embedding stored with cmetadata.user_id (copied from item)
```

### Checkpoint Storage (PostgreSQL via langgraph-checkpoint-postgres)

```python
# chat/checkpointers/postgres_saver.py

from langgraph.checkpoint.postgres import PostgresSaver

class PostgresCheckpointerSaver:
    """Wrapper for langgraph-checkpoint-postgres."""
    
    def _get_saver(self):
        with Connection.connect(conn_string, autocommit=True) as conn:
            saver = PostgresSaver(conn)
            saver.setup()  # Creates tables automatically
            yield saver
```

**Tables Created** (by langgraph-checkpoint-postgres):
- `checkpoints` - Agent state snapshots
- `checkpoint_writes` - Intermediate writes
- `checkpoint_blobs` - Binary checkpoint data

**Thread ID Format**: `{user_id}#{session_id}` for multi-tenant isolation

---

## Search Implementation

### Retriever Summary

| Retriever | Library | Implementation | Notes |
|-----------|---------|----------------|-------|
| **Vector** | `langchain-postgres` | PGVector wrapper | Full library usage ✓ |
| **BM25** | None (custom) | Raw psycopg2 + SQL | No LangChain wrapper exists for PostgreSQL FTS |
| **Hybrid** | Custom RRF | Combines BM25 + Vector | Manual fusion, extends `BaseRetriever` |
| **Agentic** | `langgraph` | ReAct agent | Uses hybrid retriever as tool |

---

### Vector Search (PGVectorStoreManager)

**Library**: `langchain-postgres`

Uses the official LangChain PGVector integration for semantic similarity search.

```python
# retrieval/pgvector_store.py

from langchain_postgres import PGVector
from langchain_voyageai import VoyageAIEmbeddings

class PGVectorStoreManager:
    """PostgreSQL PGVector store with VoyageAI embeddings."""
    
    def __init__(self, collection_name, embedding_model, connection_string):
        self.embeddings = VoyageAIEmbeddings(
            voyage_api_key=os.getenv("VOYAGE_API_KEY"),
            model=embedding_model  # voyage-3.5-lite
        )
        
        self.vectorstore = PGVector(
            embeddings=self.embeddings,
            collection_name=collection_name,
            connection=connection_string,
            distance_strategy="cosine",
            use_jsonb=True
        )
    
    def similarity_search(self, query, k=10, filter=None):
        return self.vectorstore.similarity_search(query, k=k, filter=filter)
    
    def as_retriever(self, search_kwargs=None):
        return self.vectorstore.as_retriever(search_kwargs=search_kwargs)
```

---

### BM25 Search (PostgreSQL Native - Custom Implementation)

**Library**: None - Custom implementation using `psycopg2`

> **Note**: There is no LangChain wrapper for PostgreSQL native full-text search (`tsvector/tsquery`). This custom implementation uses raw SQL but extends `BaseRetriever` for LangChain compatibility. This is an acceptable exception to the "libraries first" principle since no suitable library exists.

> **REQUIRED MIGRATION**: Currently uses `psycopg2`, but `langchain-postgres` and `langgraph-checkpoint-postgres` both use `psycopg` (v3). Migrate to `psycopg` to eliminate redundant driver dependency and reduce package size.

```python
# retrieval/postgres_bm25.py

# CURRENT (to be migrated):
import psycopg2
from psycopg2.extras import RealDictCursor

# TARGET:
from psycopg import Connection
from psycopg.rows import dict_row

class PostgresBM25Retriever(BaseRetriever):
    """Custom PostgreSQL full-text search on langchain_pg_embedding.
    
    Uses psycopg (v3) for direct database access since LangChain does not
    provide a wrapper for PostgreSQL tsvector/tsquery full-text search.
    Extends BaseRetriever for compatibility with LangChain chains.
    """
    
    def _get_relevant_documents(self, query):
        formatted_query = self._format_query_for_tsquery(query)
        
        sql = """
            SELECT e.id, e.document, e.cmetadata,
                   ts_rank(to_tsvector('english', e.document), 
                          to_tsquery('english', %s)) as score
            FROM langchain_pg_embedding e
            JOIN langchain_pg_collection c ON e.collection_id = c.uuid
            WHERE c.name = %s
              AND to_tsvector('english', e.document) @@ to_tsquery('english', %s)
              AND e.cmetadata->>'user_id' = %s
            ORDER BY score DESC
            LIMIT %s
        """
        
        # TARGET: Use psycopg v3 (matches langchain-postgres driver)
        with Connection.connect(self.connection_string) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
        
        # Convert rows to LangChain Documents
        return [Document(page_content=row['document'], 
                        metadata=row['cmetadata']) for row in rows]
    
    def _format_query_for_tsquery(self, query):
        """Convert natural language to tsquery format (word1 | word2 | ...)."""
        words = [w for w in query.split() if len(w) > 1]
        return ' | '.join(words)  # OR-based matching
```

---

### Hybrid Search (PostgresHybridRetriever)

**Library**: Custom RRF implementation, extends `BaseRetriever`

Combines BM25 and Vector results using Reciprocal Rank Fusion (RRF).

```python
# retrieval/hybrid_retriever.py

from langchain_core.retrievers import BaseRetriever
from collections import defaultdict

class PostgresHybridRetriever(BaseRetriever):
    """RRF fusion of PostgreSQL BM25 + PGVector.
    
    Custom implementation since LangChain's EnsembleRetriever doesn't
    provide the error handling and fallback behavior needed.
    """
    
    # Optimized weights based on evaluation
    bm25_weight: float = 0.3   # Keyword matching
    vector_weight: float = 0.7  # Semantic similarity
    rrf_c: int = 15            # Lower = more rank sensitive
    
    pgvector_manager: PGVectorStoreManager  # Library-based
    
    def _get_relevant_documents(self, query):
        bm25_docs, bm25_error = [], None
        vector_docs, vector_error = [], None
        
        # Execute BM25 (custom psycopg2)
        try:
            bm25_retriever = PostgresBM25Retriever(...)
            bm25_docs = bm25_retriever._get_relevant_documents(query)
        except Exception as e:
            bm25_error = e
        
        # Execute Vector (langchain-postgres)
        try:
            vector_docs = self.pgvector_manager.similarity_search(query)
        except Exception as e:
            vector_error = e
        
        # Graceful fallback
        if bm25_error and vector_error:
            return []  # Both failed
        if bm25_error:
            return vector_docs  # Vector-only
        if vector_error:
            return bm25_docs    # BM25-only
            
        # RRF fusion
        return self._manual_rrf_fusion(bm25_docs, vector_docs)
    
    def _manual_rrf_fusion(self, bm25_docs, vector_docs):
        """Reciprocal Rank Fusion: score = sum(weight / (c + rank))"""
        rrf_scores = defaultdict(float)
        doc_map = {}
        
        for rank, doc in enumerate(bm25_docs, start=1):
            item_id = doc.metadata.get("item_id")
            rrf_scores[item_id] += self.bm25_weight / (self.rrf_c + rank)
            doc_map[item_id] = doc
            
        for rank, doc in enumerate(vector_docs, start=1):
            item_id = doc.metadata.get("item_id")
            rrf_scores[item_id] += self.vector_weight / (self.rrf_c + rank)
            if item_id not in doc_map:
                doc_map[item_id] = doc
        
        # Sort by RRF score and return
        sorted_items = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        return [doc_map[item_id] for item_id, _ in sorted_items]
```

---

### Agentic Search (AgenticSearchOrchestrator)

**Library**: `langgraph` (ReAct agent)

Uses LangGraph's `create_react_agent` with hybrid retriever as a tool.

```python
# retrieval/agentic_search.py

from langchain_anthropic import ChatAnthropic
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

class AgenticSearchOrchestrator:
    """LangGraph ReAct agent with search tool."""
    
    def __init__(self, vector_store, user_id):
        self.llm = ChatAnthropic(model="claude-sonnet-4-5")
        
        # Reuse single retriever instance (optimization)
        self.retriever = PostgresHybridRetriever(
            pgvector_manager=vector_store,
            user_id=user_id
        )
        
        self.agent = create_react_agent(
            model=self.llm,
            tools=[self._create_search_tool()],
            prompt=AGENT_SYSTEM_MESSAGE
        )
    
    def _create_search_tool(self):
        @tool
        def search_collections(query: str) -> str:
            """Search the collection using hybrid search."""
            documents = self.retriever.invoke(query)
            return self._format_results(documents)
        return search_collections
    
    def search(self, query):
        # Eager first search optimization
        initial_docs = self.retriever.invoke(query)
        enhanced_query = f"Found {len(initial_docs)} results: ..."
        
        return self.agent.invoke({"messages": [HumanMessage(enhanced_query)]})
```

---

### Multi-Turn Chat (AgenticChatOrchestrator)

**Library**: `langgraph` + `langgraph-checkpoint-postgres`

Extends agentic search with conversation memory via PostgreSQL checkpointing.

```python
# chat/agentic_chat.py

from langgraph.prebuilt import create_react_agent
from chat.conversation_manager import ConversationManager

class AgenticChatOrchestrator:
    """Multi-turn agentic chat with PostgreSQL checkpointing."""
    
    def __init__(self, vector_store, conversation_manager, user_id):
        self.conversation_manager = conversation_manager
        self.retriever = PostgresHybridRetriever(...)
        
        # Agent with checkpointer for conversation memory
        self.agent = create_react_agent(
            model=ChatAnthropic(model="claude-sonnet-4-5"),
            tools=[self.search_tool, self.tavily_tool],
            checkpointer=conversation_manager.get_checkpointer()
        )
    
    def chat(self, message, session_id):
        config = self.conversation_manager.get_thread_config(session_id)
        # Thread ID format: {user_id}#{session_id}
        
        return self.agent.stream(
            {"messages": [HumanMessage(message)]}, 
            config=config
        )
```

---

## Library Usage Summary

### Use Libraries For:

| Capability | Library | Status |
|------------|---------|--------|
| Vector Search | `langchain-postgres` (PGVector) | ✓ Full library usage |
| Embeddings | `langchain-voyageai` | ✓ Full library usage |
| LLM Calls | `langchain-anthropic`, `langchain-openai` | ✓ Full library usage |
| Prompt Management | `langsmith` (Hub) | ✓ Prompts fetched from LangSmith Hub |
| Agent Framework | `langgraph` | ✓ Full library usage |
| Checkpointing | `langgraph-checkpoint-postgres` | ✓ Full library usage |
| LLM Observability | `langsmith` (@traceable) | ✓ Full library usage |
| AWS Observability | `aws-lambda-powertools` | ✓ Logging, Tracing, Metrics |
| Parameters/Secrets | `aws-lambda-powertools` | ✓ Replaces boto3 SSM/Secrets calls |
| Idempotency | `aws-lambda-powertools` | ✓ Prevents duplicate processing |
| Event Parsing | `aws-lambda-powertools` | ✓ Type-safe S3/EventBridge events |
| ORM | `sqlalchemy` | ✓ Full library usage |
| Validation | `pydantic` | ✓ Full library usage |
| API Framework | `aws-lambda-powertools` (Event Handler) | ✓ Full library usage |
| Auth | Cognito JWT via API Gateway Authorizer | ✓ No custom code needed |

### Custom Implementations (No Suitable Library):

| Capability | Implementation | Rationale | Status |
|------------|----------------|-----------|--------|
| BM25 Search | `psycopg` + raw SQL | No LangChain wrapper for PostgreSQL FTS | ⚠️ Migrate from `psycopg2` to `psycopg` (v3) |
| RRF Fusion | Manual scoring algorithm | LangChain's `EnsembleRetriever` lacks needed error handling | ✓ |
| Document Builder | `utils/document_builder.py` | Application-specific field extraction | ✓ |

> **REQUIRED**: Migrate `PostgresBM25Retriever` from `psycopg2` to `psycopg` (v3). This eliminates a redundant driver dependency since `langchain-postgres` and `langgraph-checkpoint-postgres` already require `psycopg` (v3). Reduces package size and simplifies dependency management.

### Write Custom Code Only For:

1. **Business Logic Composition**
   - Search result formatting
   - Answer generation prompts
   - Event handling orchestration

2. **Model Definitions**
   - SQLAlchemy models (`Item`, `Analysis`)
   - Pydantic schemas (`SearchRequest`, `ChatResponse`)

3. **Configuration**
   - Environment-specific settings
   - Model/retriever parameters

4. **AWS Integration Wrappers**
   - Secrets Manager helper
   - EventBridge event publishing

5. **Database Access Where No Library Exists**
   - PostgreSQL full-text search (BM25)

---

## Secrets Management

### AWS Secrets Manager (Database Credentials)

```python
# utils/aws_secrets.py

def get_database_url(use_ssl: bool = True) -> str:
    """Get DATABASE_URL from Secrets Manager."""
    secret_arn = os.getenv("DB_SECRET_ARN")
    client = boto3.client("secretsmanager")
    secret = client.get_secret_value(SecretId=secret_arn)
    credentials = json.loads(secret["SecretString"])
    
    return (
        f"postgresql://{credentials['username']}:{credentials['password']}"
        f"@{credentials['host']}:{credentials['port']}/{credentials['dbname']}"
        f"{'?sslmode=require' if use_ssl else ''}"
    )
```

### SSM Parameter Store (API Keys & Configuration)

```python
# infrastructure/stacks/database_stack.py

# Created as standard (FREE) parameters
"/collections/{env}/anthropic-api-key"
"/collections/{env}/voyage-api-key"
"/collections/{env}/langsmith-api-key"
"/collections/{env}/tavily-api-key"

# Cognito configuration (created by ApiStack, consumed by Lambdas)
"/collections/{env}/cognito/user-pool-id"
"/collections/{env}/cognito/client-id"
"/collections/{env}/cognito/region"

# Lambda accesses via CfnDynamicReference (resolved at deploy time)
anthropic_key = CfnDynamicReference(
    CfnDynamicReferenceService.SSM,
    "/collections/anthropic-api-key"
).to_string()
```

**Storing Cognito Outputs in SSM** (in ApiStack):

```python
# infrastructure/stacks/api_stack.py

from aws_cdk import aws_ssm as ssm

# After creating User Pool, store config in SSM for Lambda access
ssm.StringParameter(
    self,
    "UserPoolIdParam",
    parameter_name=f"/collections/{env_name}/cognito/user-pool-id",
    string_value=self.user_pool.user_pool_id,
)

ssm.StringParameter(
    self,
    "ClientIdParam",
    parameter_name=f"/collections/{env_name}/cognito/client-id",
    string_value=self.user_pool_client.user_pool_client_id,
)

ssm.StringParameter(
    self,
    "CognitoRegionParam",
    parameter_name=f"/collections/{env_name}/cognito/region",
    string_value=self.region,
)
```

**Retrieving Config via Powertools** (in Lambda):

```python
# utils/config.py

from aws_lambda_powertools.utilities import parameters
from functools import lru_cache

@lru_cache
def get_cognito_config() -> dict:
    """Get Cognito configuration from SSM with caching."""
    env = os.environ.get("ENV", "dev")
    
    return {
        "user_pool_id": parameters.get_parameter(
            f"/collections/{env}/cognito/user-pool-id"
        ),
        "client_id": parameters.get_parameter(
            f"/collections/{env}/cognito/client-id"
        ),
        "region": parameters.get_parameter(
            f"/collections/{env}/cognito/region"
        ),
    }

@lru_cache
def get_api_keys() -> dict:
    """Get API keys from SSM with caching."""
    env = os.environ.get("ENV", "dev")
    
    return {
        "anthropic": parameters.get_parameter(
            f"/collections/{env}/anthropic-api-key", decrypt=True
        ),
        "voyage": parameters.get_parameter(
            f"/collections/{env}/voyage-api-key", decrypt=True
        ),
        "langsmith": parameters.get_parameter(
            f"/collections/{env}/langsmith-api-key", decrypt=True
        ),
        "tavily": parameters.get_parameter(
            f"/collections/{env}/tavily-api-key", decrypt=True
        ),
    }
```

**Benefits**:
- Single source of truth for configuration
- No hardcoded values in Lambda environment variables
- Powertools caching reduces SSM API calls
- Environment-aware (`/collections/dev/...`, `/collections/prod/...`)

---

## Deployment

### Prerequisites

1. **AWS CLI configured** with appropriate credentials
2. **CDK bootstrapped**: `cdk bootstrap aws://ACCOUNT/REGION`
3. **API keys populated** in SSM Parameter Store

### Deployment Order

```bash
# 1. Deploy all stacks
cd infrastructure
cdk deploy --all --context env=dev

# 2. Enable pgvector extension (manual step)
# Connect via SSM port forwarding:
aws ssm start-session \
    --target i-BASTION_ID \
    --document-name AWS-StartPortForwardingSessionToRemoteHost \
    --parameters '{"host":["RDS_ENDPOINT"],"portNumber":["5432"],"localPortNumber":["5432"]}'

# Then via psql:
psql -h localhost -U postgres -d collections
CREATE EXTENSION IF NOT EXISTS vector;

# 3. Run Alembic migrations
alembic upgrade head

# 4. Populate SSM parameters
aws ssm put-parameter --name "/collections/anthropic-api-key" \
    --value "sk-ant-..." --type "String" --overwrite
# Repeat for other API keys
```

### Stack Dependencies

```
DatabaseStack
     ↓
ComputeStack (depends on DB credentials, creates S3)
     ↓
ApiStack (depends on API Lambda)
     ↓
MonitoringStack (depends on all resources)
```

---

## New Repository Setup

### Why a New Repository?

Starting fresh in a new repository is recommended for this migration:

| Factor | New Repo | Migrate In-Place |
|--------|----------|------------------|
| **Clean history** | Fresh git history focused on new architecture | Cluttered with old FastAPI commits |
| **No legacy baggage** | Start with correct structure from day one | Risk of leaving dead code, old patterns |
| **Parallel development** | Keep old app running while building new | Must maintain backward compatibility |
| **Library-first enforcement** | No temptation to copy old custom code | Easy to accidentally keep old patterns |
| **Testing** | Compare outputs between old and new | Harder to A/B test |
| **Rollback** | Old repo still works if migration fails | Rollback requires git gymnastics |

### Repository Strategy

```
collections-app/          ← Current repo (keep running during migration)
collections-app-v2/       ← New repo (clean implementation)
```

### New Repository Structure

```
collections-app-v2/
├── infrastructure/                # CDK stacks (prescriptive)
│   ├── app.py
│   ├── cdk.json
│   ├── cdk.context.json
│   ├── requirements.txt
│   └── stacks/
│       ├── database_stack.py
│       ├── compute_stack.py
│       ├── api_stack.py
│       └── monitoring_stack.py
│
├── lambdas/                       # Lambda function code
│   ├── api/                       # API Lambda (Powertools Event Handler)
│   │   ├── handler.py             # Routes and entry point
│   │   ├── services/              # Business logic
│   │   │   ├── item_service.py
│   │   │   ├── search_service.py
│   │   │   ├── chat_service.py
│   │   │   └── upload_service.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── analyzer/                  # Image analysis Lambda
│   │   ├── handler.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── embedder/                  # Embedding generation Lambda
│   │   ├── handler.py
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   ├── image_processor/           # S3 trigger Lambda
│   │   ├── handler.py
│   │   └── requirements.txt
│   │
│   └── cleanup/                   # Scheduled cleanup Lambda
│       ├── handler.py
│       └── requirements.txt
│
├── shared/                        # Shared code (Lambda layer or copied)
│   ├── utils/
│   │   ├── powertools.py          # Logger, Tracer, Metrics instances
│   │   └── config.py              # SSM parameter retrieval
│   ├── retrieval/
│   │   ├── pgvector_store.py      # langchain-postgres wrapper
│   │   ├── postgres_bm25.py       # Custom BM25 (psycopg v3)
│   │   └── hybrid_retriever.py    # RRF fusion
│   ├── database/
│   │   ├── models.py              # SQLAlchemy models
│   │   └── connection.py          # Connection management
│   └── chat/
│       ├── agentic_chat.py        # LangGraph agent
│       └── conversation_manager.py
│
├── scripts/                       # AWS-only scripts (no localhost)
│   ├── aws/
│   │   ├── bootstrap.sh
│   │   ├── deploy.sh
│   │   ├── destroy.sh
│   │   ├── status.sh
│   │   ├── outputs.sh
│   │   ├── db-connect.sh
│   │   └── lambda-logs.sh
│   ├── setup_cognito_users.py
│   └── sync_api_keys_to_aws.py
│
├── tests/                         # AWS API tests only
│   ├── test_api_access.py
│   ├── test_bm25_retriever.py
│   ├── test_vector_retriever.py
│   └── test_infrastructure.py
│
├── Makefile                       # AWS deployment commands
├── README.md
├── .gitignore
└── .env.example                   # Template for API keys
```

### What to Bring from Old Repo

**Copy and use as-is:**
- `infrastructure/` CDK stacks (update for Powertools/new structure)
- `scripts/aws/` deployment scripts
- `Makefile` (remove localhost commands)
- Evaluation datasets / golden test data

**Copy and refactor:**
- SQLAlchemy models → `shared/database/models.py`
- Search logic → `shared/retrieval/` (update psycopg2 → psycopg)
- LangGraph agent → `shared/chat/`

**Rewrite from scratch:**
- API routes → `lambdas/api/handler.py` (Powertools Event Handler)
- Utilities → `shared/utils/` (Powertools-based)
- Tests → `tests/` (AWS API only, no localhost)

**Do NOT bring:**
- FastAPI application code (`main.py`, routes, middleware)
- `requirements.txt` (rebuild with correct dependencies)
- Local development scripts (uvicorn, localhost tests)
- Old utility functions (replace with Powertools)

### Initial Setup Commands

```bash
# 1. Create new repository
mkdir collections-app-v2
cd collections-app-v2
git init

# 2. Create directory structure
mkdir -p infrastructure/stacks
mkdir -p lambdas/{api/services,analyzer,embedder,image_processor,cleanup}
mkdir -p shared/{utils,retrieval,database,chat}
mkdir -p scripts/aws
mkdir -p tests

# 3. Copy CDK infrastructure from old repo
cp -r ../collections-app/infrastructure/*.py infrastructure/
cp -r ../collections-app/infrastructure/stacks/*.py infrastructure/stacks/
cp ../collections-app/infrastructure/cdk.context.json infrastructure/

# 4. Copy deployment scripts
cp -r ../collections-app/scripts/aws/*.sh scripts/aws/
cp ../collections-app/scripts/setup_cognito_users.py scripts/
cp ../collections-app/scripts/sync_api_keys_to_aws.py scripts/
cp ../collections-app/Makefile .

# 5. Create Powertools shared utilities (new)
cat > shared/utils/powertools.py << 'EOF'
from aws_lambda_powertools import Logger, Tracer, Metrics

logger = Logger(service="collections-app")
tracer = Tracer(service="collections-app")
metrics = Metrics(namespace="CollectionsApp", service="collections-app")
EOF

# 6. Create .gitignore
cat > .gitignore << 'EOF'
# Python
__pycache__/
*.py[cod]
.venv/
venv/

# CDK
cdk.out/
.cdk.staging/

# Environment
.env
.env.*
!.env.example

# AWS
.aws-outputs-*.json
.api-tokens.json

# IDE
.idea/
.vscode/
EOF

# 7. Initial commit
git add .
git commit -m "Initial structure for Collections App v2 (Powertools migration)"
```

### Dependencies (New requirements.txt)

```text
# lambdas/api/requirements.txt

# AWS
aws-lambda-powertools[all]
boto3

# Database
sqlalchemy>=2.0
psycopg[binary]  # Note: psycopg v3, not psycopg2

# LangChain ecosystem
langchain-core
langchain-postgres
langchain-anthropic
langchain-openai
langchain-voyageai
langgraph
langgraph-checkpoint-postgres

# Utilities
pydantic>=2.0
```

### Migration Workflow

```
1. Set up new repo structure (above)
           ↓
2. Copy/refactor CDK infrastructure
           ↓
3. Implement shared utilities (Powertools)
           ↓
4. Implement API Lambda (Powertools Event Handler)
           ↓
5. Deploy to dev environment
           ↓
6. Run AWS API tests against new deployment
           ↓
7. Compare results with old app
           ↓
8. Migrate remaining Lambdas (analyzer, embedder, etc.)
           ↓
9. Full end-to-end testing
           ↓
10. Production cutover
```

---

## Migration Checklist

### Phase 1: Code Cleanup (Required)
- [ ] **Remove FastAPI** - Replace with Powertools Event Handler:
  - [ ] Remove `fastapi`, `mangum`, `python-jose`, `uvicorn` from dependencies
  - [ ] Convert route handlers to `@app.get/post/etc` decorators
  - [ ] Replace `Depends(get_current_user_id)` with `get_user_id()` helper
  - [ ] Remove middleware classes
  - [ ] Update `main.py` to use `APIGatewayHttpResolver`
- [ ] Migrate `PostgresBM25Retriever` from `psycopg2` to `psycopg` (v3)
- [ ] Remove `psycopg2-binary` from dependencies
- [ ] Audit Docker Lambda dependencies - migrate to layers if under 250MB
- [ ] Integrate AWS Lambda Powertools (see "AWS Lambda Powertools" section):
  - [ ] Install `aws-lambda-powertools[all]` in all Lambdas
  - [ ] Create shared `utils/powertools.py`
  - [ ] Replace `print()` with structured logging
  - [ ] Replace boto3 secrets/SSM calls with Powertools parameters
  - [ ] Add handler decorators (@logger, @tracer, @metrics)
  - [ ] Enable X-Ray tracing in CDK
  - [ ] Add idempotency for Embedder Lambda
  - [ ] Create DynamoDB idempotency table
- [ ] Update Makefile and scripts (see "Makefile & Scripts Updates" section):
  - [ ] Remove local development commands (`make dev`, `make run`, uvicorn references)
  - [ ] Remove localhost test scripts
  - [ ] Update documentation references from FastAPI to Powertools

### Phase 2: Infrastructure (Complete)
- [x] VPC with public subnets
- [x] RDS PostgreSQL 16 with pgvector
- [x] Bastion host for SSM access
- [x] Secrets Manager for DB credentials
- [x] SSM Parameter Store for API keys
- [x] S3 bucket with EventBridge
- [x] Lambda functions (Docker-based)
- [x] API Gateway HTTP API
- [x] Cognito User Pool
- [x] CloudWatch monitoring

### Phase 3: Data Validation
- [ ] Verify items/analyses in RDS PostgreSQL
- [ ] Confirm embeddings in `langchain_pg_embedding` table
- [ ] Validate search functionality (BM25, vector, hybrid)
- [ ] Test multi-tenancy isolation

### Phase 4: API Migration
- [ ] Deploy API Lambda
- [ ] Configure Cognito clients
- [ ] Update frontend to use new endpoints
- [ ] Enable authentication

### Phase 5: Workflow Migration
- [ ] Test S3 upload → EventBridge flow
- [ ] Validate analyzer Lambda
- [ ] Validate embedder Lambda
- [ ] End-to-end upload test

### Phase 6: Cleanup
- [ ] Remove local development workarounds
- [ ] Update documentation
- [ ] Production deployment

---

## Cost Optimization

### Free Tier Usage
- RDS: `db.t4g.micro` (750 hours/month free)
- Lambda: 1M requests/month free
- S3: 5GB storage free
- API Gateway: 1M requests/month free
- Secrets Manager: First secret free for 30 days

### Cost Considerations
- **Bastion Host**: ~$3/month (`t4g.nano`)
- **RDS Storage**: $0.115/GB-month (gp3)
- **Data Transfer**: Minimize cross-AZ traffic
- **ECR Storage**: Docker images incur storage costs (~$0.10/GB-month)
- **Lambda Cold Starts**: Docker images have longer cold starts, may require Provisioned Concurrency

### Recommendations

1. **Evaluate Lambda Layers vs Docker**
   - Audit dependency sizes before defaulting to Docker
   - Layers have faster cold starts and no ECR costs
   - Docker adds build complexity and container storage fees

2. **Use Provisioned Concurrency sparingly**
   - Only for API Lambda if cold starts are problematic
   - Consider layers first to reduce cold start impact

3. **RDS Proxy** - Add for connection pooling at scale

4. **S3 Intelligent-Tiering** - For infrequently accessed images

5. **Set up AWS Budgets alerts** - Catch unexpected costs early

---

## Observability

### LangSmith Integration

**Prompt Management**: Analysis prompts are fetched from LangSmith Hub at runtime.

```python
# llm.py

from langsmith import Client as LangSmithClient

def get_prompt(name: str) -> str:
    """Fetch prompt from LangSmith Hub with fallback."""
    prompt_name = os.getenv("LANGSMITH_PROMPT_NAME", "collections-app-initial")
    
    try:
        client = LangSmithClient()
        prompt_template = client.pull_prompt(prompt_name)
        return prompt_template.template
    except Exception as e:
        logger.warning(f"Failed to fetch prompt from LangSmith Hub: {e}")
        return FALLBACK_PROMPT  # Embedded fallback
```

**Benefits**:
- Prompts can be updated without code deployment
- Version history maintained in LangSmith
- A/B testing of prompt variations
- Fallback to embedded prompt if LangSmith unavailable

**Tracing**: All LLM operations are traced via `@traceable` decorator:

```python
from langsmith import traceable

@traceable(name="analyze_image", run_type="chain")
def analyze_image(image_path, provider, model, metadata):
    # LangChain operations automatically traced
    llm = ChatAnthropic(model=model)
    response = llm.invoke(messages)
    return result, trace_id
```

### CloudWatch Metrics

**Built-in Metrics**:
- Lambda duration, errors, throttles
- API Gateway latency, 4XX/5XX errors
- RDS connections, CPU, storage

---

## AWS Lambda Powertools (Required)

**Library**: `aws-lambda-powertools[all]`

Lambda Powertools is **required** for all Lambda functions to reduce custom code, improve observability, and follow AWS best practices.

> **Note**: This section provides comprehensive reference documentation for Powertools features. Refer to specific subsections as needed during implementation.

### Core Utilities

#### Logger (Structured Logging)

Replaces custom logging with structured JSON logs that integrate with CloudWatch Logs Insights.

```python
# utils/powertools.py

from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.metrics import MetricUnit

# Shared instances across all Lambdas
logger = Logger(service="collections-app")
tracer = Tracer(service="collections-app")
metrics = Metrics(namespace="CollectionsApp", service="collections-app")
```

```python
# lambdas/embedder/handler.py

from utils.powertools import logger, tracer, metrics

@logger.inject_lambda_context(log_event=True)
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event, context):
    # Structured logging with correlation
    logger.info("Processing embedding request", extra={
        "item_id": item_id,
        "user_id": user_id,
    })
    
    # Automatic exception logging
    try:
        result = process_embedding(item_id)
    except Exception as e:
        logger.exception("Embedding failed")
        raise
    
    return result
```

**Benefits over `print()`**:
- JSON structured logs (queryable in CloudWatch Logs Insights)
- Automatic correlation IDs across Lambda invocations
- Log levels (DEBUG, INFO, WARNING, ERROR)
- Automatic Lambda context injection (request_id, function_name)

#### Tracer (X-Ray Integration)

Distributed tracing across Lambda functions and AWS services.

```python
from utils.powertools import tracer

@tracer.capture_method
def analyze_image(item_id: str, user_id: str) -> Analysis:
    """Traced method - appears in X-Ray service map."""
    
    # Add custom annotations (indexed, searchable)
    tracer.put_annotation(key="item_id", value=item_id)
    tracer.put_annotation(key="user_id", value=user_id)
    
    # Add metadata (not indexed, for debugging)
    tracer.put_metadata(key="model", value="claude-sonnet-4-20250514")
    
    result = call_llm(...)
    return result
```

**Trace Flow**:
```
API Gateway → API Lambda → RDS
                    ↓
              EventBridge
                    ↓
             Analyzer Lambda → Anthropic API
                    ↓
              EventBridge
                    ↓
             Embedder Lambda → VoyageAI API → RDS
```

#### Metrics (Custom CloudWatch Metrics)

Emit custom metrics without CloudWatch API calls.

```python
from utils.powertools import metrics
from aws_lambda_powertools.metrics import MetricUnit

@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event, context):
    # Search metrics
    metrics.add_metric(name="SearchLatency", unit=MetricUnit.Milliseconds, value=latency_ms)
    metrics.add_metric(name="SearchResultCount", unit=MetricUnit.Count, value=len(results))
    
    # Add dimensions for filtering
    metrics.add_dimension(name="SearchType", value="hybrid")
    metrics.add_dimension(name="Environment", value=os.environ.get("ENV", "dev"))
    
    return results
```

**Custom Metrics to Emit**:

| Metric | Unit | Dimensions | Purpose |
|--------|------|------------|---------|
| `SearchLatency` | Milliseconds | SearchType (bm25/vector/hybrid/agentic) | Performance tracking |
| `SearchResultCount` | Count | SearchType | Quality monitoring |
| `EmbeddingLatency` | Milliseconds | Model | VoyageAI performance |
| `AgentIterations` | Count | - | Agent efficiency |
| `LLMTokensUsed` | Count | Provider, Model | Cost tracking |

### Parameters & Secrets (SSM/Secrets Manager)

Replace direct boto3 calls with Powertools utilities.

```python
# BEFORE (custom code)
import boto3
client = boto3.client("secretsmanager")
secret = client.get_secret_value(SecretId=arn)
credentials = json.loads(secret["SecretString"])

# AFTER (Powertools)
from aws_lambda_powertools.utilities import parameters

# SSM Parameter Store
api_key = parameters.get_parameter("/collections/anthropic-api-key", decrypt=True)

# Secrets Manager
db_credentials = parameters.get_secret("collections/db-credentials", transform="json")

# With caching (default 5 seconds, configurable)
api_key = parameters.get_parameter(
    "/collections/anthropic-api-key",
    decrypt=True,
    max_age=300  # Cache for 5 minutes
)
```

**Benefits**:
- Built-in caching (reduces API calls and latency)
- Automatic JSON/binary transformation
- Consistent error handling

### Event Parsing (EventBridge/S3/API Gateway)

Type-safe event parsing for Lambda triggers.

```python
# lambdas/image_processor/handler.py

from aws_lambda_powertools.utilities.data_classes import (
    S3Event,
    event_source
)

@event_source(data_class=S3Event)
def handler(event: S3Event, context):
    for record in event.records:
        bucket = record.s3.bucket.name
        key = record.s3.object.key
        
        logger.info("Processing S3 object", extra={
            "bucket": bucket,
            "key": key,
            "size": record.s3.object.size,
        })
        
        process_image(bucket, key)
```

```python
# lambdas/analyzer/handler.py

from aws_lambda_powertools.utilities.data_classes import EventBridgeEvent

@event_source(data_class=EventBridgeEvent)
def handler(event: EventBridgeEvent, context):
    detail = event.detail
    item_id = detail["item_id"]
    user_id = detail["user_id"]
    
    analyze_item(item_id, user_id)
```

### Validation (Pydantic Integration)

Powertools integrates with Pydantic for request/event validation, reducing manual validation code.

```python
# lambdas/api/validation.py

from pydantic import BaseModel, Field
from typing import Optional
from aws_lambda_powertools.utilities.validation import validate

class SearchRequest(BaseModel):
    """Validated search request."""
    query: str = Field(..., min_length=1, max_length=500)
    search_type: str = Field(default="hybrid", pattern="^(bm25|vector|hybrid|agentic)$")
    limit: int = Field(default=10, ge=1, le=100)


class ItemCreate(BaseModel):
    """Validated item creation request."""
    filename: str = Field(..., min_length=1, max_length=255)
    content_type: str = Field(..., pattern="^image/(jpeg|png|webp|gif)$")
    metadata: Optional[dict] = None
```

```python
# With Powertools Event Handler
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver
from aws_lambda_powertools.event_handler.openapi.params import Body

app = APIGatewayHttpResolver()

@app.post("/search")
def search(request: SearchRequest = Body()):
    """Search with automatic Pydantic validation."""
    # request is already validated
    user_id = get_user_id_from_event(app.current_event)
    
    results = search_service.search(
        query=request.query,
        search_type=request.search_type,
        limit=request.limit,
        user_id=user_id
    )
    return {"results": results}
```

```python
# For non-API Lambda (EventBridge), use validator decorator
from aws_lambda_powertools.utilities.validation import validator
from aws_lambda_powertools.utilities.validation.exceptions import SchemaValidationError

EMBEDDING_EVENT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["detail"],
    "properties": {
        "detail": {
            "type": "object",
            "required": ["item_id", "user_id"],
            "properties": {
                "item_id": {"type": "string", "format": "uuid"},
                "user_id": {"type": "string", "minLength": 1}
            }
        }
    }
}

@validator(inbound_schema=EMBEDDING_EVENT_SCHEMA)
def handler(event, context):
    """Event is validated before handler executes."""
    item_id = event["detail"]["item_id"]
    user_id = event["detail"]["user_id"]
    
    process_embedding(item_id, user_id)
```

**Benefits over manual validation**:
- Declarative schemas (Pydantic or JSON Schema)
- Automatic 400 responses with error details
- Consistent validation across all endpoints
- OpenAPI schema generation
```

### Idempotency (Prevent Duplicate Processing)

Critical for EventBridge-triggered Lambdas where retries can occur.

```python
from aws_lambda_powertools.utilities.idempotency import (
    idempotent,
    DynamoDBPersistenceLayer,
    IdempotencyConfig
)

# Configure persistence (requires DynamoDB table)
persistence = DynamoDBPersistenceLayer(table_name="IdempotencyTable")
config = IdempotencyConfig(expires_after_seconds=3600)  # 1 hour

@idempotent(config=config, persistence_store=persistence)
def process_embedding(item_id: str, user_id: str) -> dict:
    """Idempotent embedding - safe to retry."""
    # This will only execute once per unique (item_id, user_id) within expiry
    embedding = generate_embedding(item_id)
    store_embedding(embedding, user_id)
    return {"status": "complete", "item_id": item_id}
```

**DynamoDB Table for Idempotency** (add to CDK):
```python
# infrastructure/stacks/compute_stack.py

from aws_cdk import aws_dynamodb as dynamodb

self.idempotency_table = dynamodb.Table(
    self,
    "IdempotencyTable",
    table_name=f"collections-idempotency-{env}",
    partition_key=dynamodb.Attribute(
        name="id",
        type=dynamodb.AttributeType.STRING
    ),
    time_to_live_attribute="expiration",
    billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
    removal_policy=RemovalPolicy.DESTROY,  # OK for idempotency data
)
```

### Batch Processing (SQS/EventBridge)

Handle partial failures in batch operations.

```python
from aws_lambda_powertools.utilities.batch import (
    BatchProcessor,
    EventType,
    process_partial_response
)

processor = BatchProcessor(event_type=EventType.SQS)

@tracer.capture_method
def process_record(record: dict):
    """Process single record - failures won't fail entire batch."""
    item_id = record["body"]["item_id"]
    generate_embedding(item_id)

def handler(event, context):
    return process_partial_response(
        event=event,
        record_handler=process_record,
        processor=processor,
        context=context
    )
```

### Lambda Handler Pattern

Standard pattern for all Lambda functions:

```python
# lambdas/{function}/handler.py

from utils.powertools import logger, tracer, metrics
from aws_lambda_powertools.utilities import parameters
from aws_lambda_powertools.utilities.typing import LambdaContext

@logger.inject_lambda_context(log_event=True)
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext) -> dict:
    """
    Standard Lambda handler with Powertools instrumentation.
    
    - Structured logging with correlation IDs
    - X-Ray tracing with annotations
    - Custom metrics with dimensions
    - Cold start tracking
    """
    
    # Get secrets/parameters with caching
    db_url = parameters.get_secret("collections/db-credentials", transform="json")
    
    # Business logic with tracing
    result = process_event(event)
    
    # Emit custom metrics
    metrics.add_metric(name="ProcessedEvents", unit=MetricUnit.Count, value=1)
    
    return result
```

### CDK Integration

Enable Powertools features in Lambda construct:

```python
# infrastructure/stacks/compute_stack.py

from aws_cdk import aws_lambda as lambda_

api_lambda = lambda_.DockerImageFunction(
    self,
    "ApiLambda",
    code=lambda_.DockerImageCode.from_image_asset("./lambdas/api"),
    environment={
        # Powertools configuration
        "POWERTOOLS_SERVICE_NAME": "collections-app",
        "POWERTOOLS_METRICS_NAMESPACE": "CollectionsApp",
        "LOG_LEVEL": "INFO",
        
        # Enable X-Ray
        "AWS_XRAY_SDK_ENABLED": "true",
        
        # Other env vars...
    },
    tracing=lambda_.Tracing.ACTIVE,  # Enable X-Ray tracing
)

# Grant Powertools access to parameters/secrets
ssm_policy = iam.PolicyStatement(
    actions=["ssm:GetParameter", "ssm:GetParameters"],
    resources=[f"arn:aws:ssm:{region}:{account}:parameter/collections/*"]
)
api_lambda.add_to_role_policy(ssm_policy)
```

---

## Security

### Network Security
- RDS in VPC (public for dev, private subnets for prod)
- Security groups: Lambda SG → RDS SG on port 5432
- Bastion access via SSM (no SSH keys)

### Data Security
- Secrets Manager for database credentials
- SSM Parameter Store for API keys
- User isolation via `user_id` metadata filtering
- CORS restricted in production

### Authentication
- Cognito JWT validation in API Gateway (JWT Authorizer)
- `get_user_id()` extracts `sub` claim from `request_context.authorizer.jwt_claim`
- Public endpoints explicitly configured (no authorizer)

---

## Makefile & Scripts Updates

### Makefile Commands - No Changes Required

The existing Makefile commands remain valid after the FastAPI → Powertools transition:

| Command Category | Status | Notes |
|------------------|--------|-------|
| `infra-*` | ✓ No change | CDK infrastructure unchanged |
| `db-*` | ✓ No change | Database commands unchanged |
| `secrets-*` | ✓ No change | SSM parameter commands unchanged |
| `cognito-*` | ✓ No change | Cognito user setup unchanged |
| `lambda-*` | ✓ No change | Lambda deploy/logs unchanged |
| `test-infra` | ✓ No change | Infrastructure tests unchanged |
| `dev-setup` | ✓ No change | Full setup workflow unchanged |

### Scripts to Update

#### 1. `scripts/aws/destroy.sh` - Text update

```bash
# Line ~72: Update Lambda description
# BEFORE:
echo "     - API Lambda (FastAPI application)"

# AFTER:
echo "     - API Lambda (Powertools Event Handler)"
```

#### 2. `scripts/aws/README.md` - Documentation updates

Update all references from "FastAPI application" to "Powertools Event Handler":

```markdown
# BEFORE:
- `api` - API Lambda (FastAPI)

# AFTER:
- `api` - API Lambda (Powertools Event Handler)
```

### Scripts to Remove (Local Testing)

These scripts rely on `localhost:8000` which is no longer available without uvicorn:

| Script | Action | Reason |
|--------|--------|--------|
| `scripts/test_hybrid_retriever.py` | **Remove** or update to use AWS API | Uses `localhost:8000` |
| `scripts/test_agentic_search.py` | **Remove** or update to use AWS API | Uses `localhost:8000` |
| `scripts/run_tests.sh` | **Update** | Remove `validate` mode that requires local API |

### Scripts That Work (AWS API Testing)

These scripts authenticate with Cognito and test against the deployed AWS API - no changes needed:

| Script | Status |
|--------|--------|
| `scripts/test_api_access.py` | ✓ Works - uses AWS API |
| `scripts/test_bm25_retriever.py` | ✓ Works - uses AWS API |
| `scripts/test_vector_retriever.py` | ✓ Works - uses AWS API |
| `scripts/setup_cognito_users.py` | ✓ Works - Cognito setup |
| `scripts/sync_api_keys_to_aws.py` | ✓ Works - SSM parameters |
| `scripts/aws/populate_parameters.py` | ✓ Works - SSM parameters |

### Updated `run_tests.sh`

Remove the `validate` mode that requires a local API server:

```bash
# scripts/run_tests.sh

# REMOVE this section:
validate)
    print_status "Running validation scripts..."

    # Check if API is running
    if ! curl -s http://localhost:8000/health > /dev/null 2>&1; then
        print_error "API is not running at http://localhost:8000"
        print_warning "Start it with: uvicorn main:app --port 8000"  # ← No longer valid
        exit 1
    fi
    # ...
    ;;

# REPLACE with AWS API testing:
validate)
    print_status "Running validation against AWS API..."
    python scripts/test_api_access.py --user testuser1
    python scripts/test_bm25_retriever.py --user testuser1
    python scripts/test_vector_retriever.py --user testuser1
    print_success "All AWS API validation tests passed!"
    ;;
```

### Testing Strategy Without Local Server

| Test Type | Before (FastAPI) | After (Powertools) |
|-----------|------------------|-------------------|
| Unit tests | `pytest` | `pytest` (unchanged) |
| Integration tests | `localhost:8000` | AWS API via Cognito auth |
| Manual testing | `uvicorn main:app` | `make lambda-logs` + AWS Console |
| Debugging | Local debugger | CloudWatch Logs + X-Ray |

### Makefile Help Text Update

Update the help text to reflect the new testing approach:

```makefile
# BEFORE:
.PHONY: help
help:
	@echo "  make test-all ENV=dev           - Run all tests (infra + API + e2e)"

# AFTER:
.PHONY: help
help:
	@echo "  make test-all ENV=dev           - Run all tests (infra + AWS API)"
```

---

## Troubleshooting

### Common Issues

**1. "langchain_pg_embedding table not found"**
- Cause: No embeddings created yet
- Solution: Upload an image and trigger the embedding workflow

**2. "pgvector extension not found"**
- Cause: Extension not enabled
- Solution: `CREATE EXTENSION IF NOT EXISTS vector;`

**3. Lambda cold start timeout**
- Cause: Docker image initialization
- Solution: Use provisioned concurrency or pre-warm

**4. "User isolation not working"**
- Cause: Missing `user_id` in metadata
- Solution: Verify embedder passes `user_id` to `add_document()`

**5. Hybrid search returns empty**
- Cause: Both BM25 and vector failed silently
- Solution: Check CloudWatch logs for `[HYBRID:ERROR]` messages

### Debugging Commands

```bash
# Check Lambda logs
aws logs tail /aws/lambda/collections-dev-api --follow

# Test database connection via bastion
aws ssm start-session --target i-BASTION_ID ...

# Query embeddings directly
psql -c "SELECT COUNT(*) FROM langchain_pg_embedding;"

# Check EventBridge rules
aws events list-rules --name-prefix collections
```

---

## Future Enhancements

### Short Term
- [ ] Implement RDS Proxy for connection pooling
- [ ] Add CloudWatch Logs Insights queries for common debugging patterns

### Medium Term
- [ ] Multi-region deployment
- [ ] Read replicas for search scaling
- [ ] CDN for image serving (CloudFront)

### Long Term
- [ ] Migrate to Aurora Serverless v2
- [ ] Implement RAG with conversation context
- [ ] Add image similarity search (CLIP embeddings)
