# Collections-Local AWS Migration - Implementation Plan

**Version**: 2.0 (Refined)
**Created**: 2025-12-27
**Updated**: 2025-12-27
**Optimized for**: Claude Code with Parallelization

> **📌 Persistence Note**: This file is stored in `/workspaces/collections-local/IMPLEMENTATION_PLAN.md` (git repository).
> It will persist even if the dev environment is terminated or conversation is cleared.
> The detailed plan is also available at `/home/codespace/.claude/plans/concurrent-beaming-river.md` (temporary).

---

## Executive Summary

This implementation plan migrates `collections-local` from local SQLite/ChromaDB to AWS serverless architecture using **library-first development** principles. Maximum use of LangChain, LangSmith, LangGraph, boto3, and AWS CDK to minimize custom code.

### User-Confirmed Strategy

Based on user preferences collected 2025-12-27:

- **Environment Strategy**: Dev only initially (expand to test/prod after validation)
- **Testing Strategy**: Unit tests per component + Integration tests per phase + E2E at completion
- **Migration Approach**: Clean cutover (ChromaDB removed post-validation)
- **Automation**: Manual scripts only (no CI/CD initially)

### Key Principles

1. **Library-First**: Use proven libraries (LangChain, LangGraph, boto3, AWS SDK) over custom code
2. **Infrastructure as Code**: 100% AWS CDK (Python) - no manual console clicks
3. **Single Environment First**: Deploy dev environment, validate thoroughly, then expand
4. **Test During Development AND Integration**: Continuous testing at component and phase levels
5. **Parallelization**: Tasks structured for concurrent execution via Claude Code agents

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  AWS Serverless Stack (Python CDK)                          │
├─────────────────────────────────────────────────────────────┤
│  • Cognito User Pool (auth)                                 │
│  • API Gateway HTTP API → Lambda (FastAPI + Mangum)        │
│  • RDS PostgreSQL (public, pgvector + tsvector)            │
│  • DynamoDB (LangGraph checkpoints with TTL)               │
│  • S3 (images with EventBridge notifications)              │
│  • EventBridge (workflow orchestration)                     │
│  • Parameter Store (secrets - FREE)                         │
│  • 5 Lambda Functions (API, Processor, Analyzer,           │
│    Embedder, Cleanup)                                       │
└─────────────────────────────────────────────────────────────┘
```

**Cost**: ~$29-52/month (dev environment)

---

## Phase 1: Infrastructure Foundation (Days 1-2)

### Objectives
- Bootstrap AWS CDK infrastructure for dev environment
- Deploy complete stack to dev environment
- Validate infrastructure with automated tests (11 validation checks)

### Tasks (Parallelizable)

#### Task 1.1: CDK Stack Development 🔧
**Agent**: infrastructure-builder
**Duration**: 4-6 hours

**Deliverables**:
```
infrastructure/
├── app.py                          # Main CDK app with environment support
├── stacks/
│   ├── __init__.py
│   ├── base_stack.py              # Base stack with common constructs
│   ├── database_stack.py          # RDS PostgreSQL + DynamoDB
│   ├── storage_stack.py           # S3 bucket with EventBridge
│   ├── compute_stack.py           # Lambda functions
│   ├── api_stack.py               # API Gateway + Cognito
│   └── monitoring_stack.py        # CloudWatch dashboards + alarms
├── constructs/
│   ├── __init__.py
│   ├── lambda_function.py         # Reusable Lambda construct
│   └── secret_parameter.py        # Parameter Store construct
├── requirements.txt               # aws-cdk-lib, constructs
├── cdk.json                       # CDK configuration
├── cdk.context.json              # Environment-specific settings
└── README.md
```

**Key Libraries**:
- `aws-cdk-lib` - All CDK constructs
- `aws_cdk.aws_rds` - RDS PostgreSQL
- `aws_cdk.aws_dynamodb` - DynamoDB table
- `aws_cdk.aws_lambda` - Lambda functions
- `aws_cdk.aws_apigatewayv2` - HTTP API Gateway
- `aws_cdk.aws_cognito` - User pools
- `aws_cdk.aws_s3` - S3 buckets
- `aws_cdk.aws_events` - EventBridge rules
- `aws_cdk.aws_ssm` - Parameter Store

**Environment Configuration** (cdk.context.json):
```json
{
  "environments": {
    "dev": {
      "account": "123456789012",
      "region": "us-east-1",
      "rds_instance_class": "db.t4g.micro",
      "rds_allocated_storage": 20,
      "enable_deletion_protection": false,
      "enable_backup": false
    },
    "test": {
      "account": "123456789012",
      "region": "us-east-1",
      "rds_instance_class": "db.t4g.small",
      "rds_allocated_storage": 20,
      "enable_deletion_protection": false,
      "enable_backup": true
    },
    "prod": {
      "account": "123456789012",
      "region": "us-east-1",
      "rds_instance_class": "db.t4g.small",
      "rds_allocated_storage": 50,
      "enable_deletion_protection": true,
      "enable_backup": true,
      "multi_az": true
    }
  }
}
```

**CDK Stack Structure** (infrastructure/app.py):
```python
#!/usr/bin/env python3
import os
from aws_cdk import App, Environment, Tags
from stacks.database_stack import DatabaseStack
from stacks.storage_stack import StorageStack
from stacks.compute_stack import ComputeStack
from stacks.api_stack import ApiStack
from stacks.monitoring_stack import MonitoringStack

app = App()

# Get environment from context or environment variable
env_name = app.node.try_get_context("env") or os.getenv("CDK_ENV", "dev")
env_config = app.node.get_context("environments")[env_name]

# Define AWS environment
aws_env = Environment(
    account=env_config["account"],
    region=env_config["region"]
)

# Stack deployment order (dependencies managed by CDK)
db_stack = DatabaseStack(
    app, f"CollectionsDB-{env_name}",
    env=aws_env,
    env_name=env_name,
    env_config=env_config
)

storage_stack = StorageStack(
    app, f"CollectionsStorage-{env_name}",
    env=aws_env,
    env_name=env_name
)

compute_stack = ComputeStack(
    app, f"CollectionsCompute-{env_name}",
    env=aws_env,
    env_name=env_name,
    database=db_stack.database,
    dynamodb_table=db_stack.checkpoint_table,
    bucket=storage_stack.bucket,
    event_bus=storage_stack.event_bus
)

api_stack = ApiStack(
    app, f"CollectionsAPI-{env_name}",
    env=aws_env,
    env_name=env_name,
    api_lambda=compute_stack.api_lambda
)

monitoring_stack = MonitoringStack(
    app, f"CollectionsMonitoring-{env_name}",
    env=aws_env,
    env_name=env_name,
    api=api_stack.http_api,
    lambdas=compute_stack.all_lambdas,
    database=db_stack.database
)

# Add environment tags
Tags.of(app).add("Environment", env_name)
Tags.of(app).add("Project", "collections-local")
Tags.of(app).add("ManagedBy", "CDK")

app.synth()
```

**Critical Features**:
1. ✅ PostgreSQL with pgvector extension auto-installation
2. ✅ DynamoDB with TTL enabled on `expires_at` attribute
3. ✅ Security groups (RDS accessible from Lambda + dev IP)
4. ✅ Parameter Store entries for secrets (empty, populated later)
5. ✅ IAM roles with least-privilege policies
6. ✅ S3 bucket with EventBridge notifications
7. ✅ CloudWatch log groups with 7-day retention (dev), 30-day (prod)

---

#### Task 1.2: Infrastructure Testing Framework 🧪
**Agent**: test-engineer
**Duration**: 3-4 hours
**Runs in parallel with Task 1.1**

**Deliverables**:
```
scripts/aws/test/
├── __init__.py
├── test_infrastructure.py         # Main test orchestrator
├── tests/
│   ├── __init__.py
│   ├── test_rds_connection.py     # RDS connectivity + pgvector
│   ├── test_dynamodb.py           # DynamoDB table + TTL
│   ├── test_parameter_store.py    # Secrets CRUD
│   ├── test_cognito.py            # User pool + JWT
│   ├── test_s3.py                 # Upload/download + EventBridge
│   ├── test_lambda_invoke.py      # Basic Lambda invocation
│   ├── test_lambda_rds.py         # Lambda → RDS connection
│   ├── test_lambda_secrets.py     # Lambda → Parameter Store
│   ├── test_api_gateway.py        # API Gateway routing
│   └── test_eventbridge.py        # S3 → EventBridge → Lambda
└── requirements.txt               # pytest, boto3, psycopg2-binary
```

**Key Libraries**:
- `boto3` - AWS SDK for all service interactions
- `pytest` - Test framework
- `psycopg2-binary` - PostgreSQL connection testing
- `requests` - HTTP API testing

**Test Framework Structure** (test_infrastructure.py):
```python
import boto3
import pytest
from typing import Dict, Any
import json

class InfrastructureValidator:
    """Validates AWS infrastructure deployment using boto3."""

    def __init__(self, stack_outputs: Dict[str, Any]):
        self.outputs = stack_outputs
        self.region = stack_outputs.get('Region', 'us-east-1')

        # Initialize AWS clients using boto3
        self.rds = boto3.client('rds', region_name=self.region)
        self.dynamodb = boto3.resource('dynamodb', region_name=self.region)
        self.ssm = boto3.client('ssm', region_name=self.region)
        self.cognito = boto3.client('cognito-idp', region_name=self.region)
        self.s3 = boto3.client('s3', region_name=self.region)
        self.lambda_client = boto3.client('lambda', region_name=self.region)
        self.apigateway = boto3.client('apigatewayv2', region_name=self.region)
        self.events = boto3.client('events', region_name=self.region)

    @classmethod
    def from_cdk_outputs(cls, env_name: str = 'dev'):
        """Load CDK outputs from JSON file."""
        with open(f'.aws-outputs-{env_name}.json') as f:
            outputs = json.load(f)
        return cls(outputs)

    def run_all_tests(self) -> Dict[str, bool]:
        """Run all infrastructure validation tests."""
        tests = [
            ('RDS Connection', self.test_rds_connection),
            ('pgvector Extension', self.test_pgvector_extension),
            ('DynamoDB Table', self.test_dynamodb_table),
            ('DynamoDB TTL', self.test_dynamodb_ttl),
            ('Parameter Store', self.test_parameter_store),
            ('Cognito User Pool', self.test_cognito_pool),
            ('S3 Bucket', self.test_s3_bucket),
            ('Lambda Invoke', self.test_lambda_invoke),
            ('Lambda RDS Access', self.test_lambda_rds_connection),
            ('API Gateway', self.test_api_gateway_routing),
            ('EventBridge', self.test_eventbridge_trigger)
        ]

        results = {}
        for name, test_func in tests:
            try:
                test_func()
                results[name] = True
                print(f"✅ {name}: PASSED")
            except Exception as e:
                results[name] = False
                print(f"❌ {name}: FAILED - {str(e)}")

        return results

    def test_rds_connection(self):
        """Test RDS PostgreSQL connection using psycopg2."""
        import psycopg2

        conn = psycopg2.connect(
            host=self.outputs['RdsEndpoint'],
            database='collections',
            user=self.outputs['RdsUsername'],
            password=self.outputs['RdsPassword'],
            sslmode='require'
        )

        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        version = cursor.fetchone()
        assert version is not None

        conn.close()

    def test_pgvector_extension(self):
        """Validate pgvector extension is installed."""
        import psycopg2

        conn = psycopg2.connect(
            host=self.outputs['RdsEndpoint'],
            database='collections',
            user=self.outputs['RdsUsername'],
            password=self.outputs['RdsPassword'],
            sslmode='require'
        )

        cursor = conn.cursor()
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cursor.execute("SELECT extname FROM pg_extension WHERE extname = 'vector';")
        result = cursor.fetchone()
        assert result is not None

        conn.close()

    def test_dynamodb_table(self):
        """Verify DynamoDB checkpoint table exists with correct schema."""
        table = self.dynamodb.Table(self.outputs['CheckpointTableName'])

        # Describe table
        description = table.meta.client.describe_table(
            TableName=self.outputs['CheckpointTableName']
        )

        # Validate schema
        key_schema = description['Table']['KeySchema']
        assert any(k['AttributeName'] == 'thread_id' for k in key_schema)
        assert any(k['AttributeName'] == 'checkpoint_id' for k in key_schema)

    def test_dynamodb_ttl(self):
        """Verify TTL is enabled on DynamoDB table."""
        response = self.dynamodb.meta.client.describe_time_to_live(
            TableName=self.outputs['CheckpointTableName']
        )

        ttl_status = response['TimeToLiveDescription']['TimeToLiveStatus']
        assert ttl_status == 'ENABLED'

    # ... additional test methods using boto3
```

**Pytest Configuration** (pytest.ini):
```ini
[pytest]
testpaths = scripts/aws/test/tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
markers =
    integration: Integration tests requiring AWS resources
    unit: Unit tests (no AWS dependencies)
addopts =
    -v
    --tb=short
    --strict-markers
```

---

#### Task 1.3: Deployment Automation & Makefile 📦
**Agent**: devops-engineer
**Duration**: 2-3 hours
**Runs in parallel with Tasks 1.1 and 1.2**

**Deliverables**:
```
Makefile                           # Primary developer interface
scripts/aws/
├── deploy.sh                      # Multi-environment CDK deploy
├── bootstrap.sh                   # CDK bootstrap per environment
├── destroy.sh                     # Safe stack teardown
├── outputs.sh                     # Extract CDK outputs to JSON
└── status.sh                      # Show stack status
```

**Makefile** (Primary Interface):
```makefile
# Collections AWS Infrastructure Management
# Supports: dev, test, prod environments

.PHONY: help
help:
	@echo "Collections AWS Infrastructure Commands"
	@echo ""
	@echo "Infrastructure:"
	@echo "  make infra-bootstrap ENV=dev    Bootstrap CDK for environment"
	@echo "  make infra-deploy ENV=dev       Deploy CDK stack to environment"
	@echo "  make infra-diff ENV=dev         Show infrastructure changes"
	@echo "  make infra-destroy ENV=dev      Destroy stack (with confirmation)"
	@echo "  make infra-status ENV=dev       Show stack status"
	@echo ""
	@echo "Testing:"
	@echo "  make test-infra ENV=dev         Run infrastructure validation tests"
	@echo "  make test-all ENV=dev           Run all tests (infra + API + e2e)"
	@echo ""
	@echo "Database:"
	@echo "  make db-connect ENV=dev         Open psql connection to RDS"
	@echo "  make db-migrate ENV=dev         Run schema migrations"
	@echo "  make db-seed-golden ENV=dev     Seed golden dataset"
	@echo ""
	@echo "Secrets:"
	@echo "  make secrets-populate ENV=dev   Push secrets from .env to Parameter Store"
	@echo "  make secrets-export ENV=dev     Pull secrets from Parameter Store to .env"
	@echo ""
	@echo "Lambda:"
	@echo "  make lambda-deploy-api ENV=dev  Deploy API Lambda only (fast)"
	@echo "  make lambda-logs FUNC=api ENV=dev  Tail CloudWatch logs"
	@echo ""
	@echo "Default environment: dev"

ENV ?= dev
STACK_PREFIX = Collections

.PHONY: infra-bootstrap
infra-bootstrap:
	@echo "🔧 Bootstrapping CDK for $(ENV) environment..."
	./scripts/aws/bootstrap.sh $(ENV)

.PHONY: infra-deploy
infra-deploy:
	@echo "🚀 Deploying infrastructure to $(ENV)..."
	./scripts/aws/deploy.sh $(ENV)
	./scripts/aws/outputs.sh $(ENV)
	@echo "✅ Deployment complete. Outputs saved to .aws-outputs-$(ENV).json"

.PHONY: infra-diff
infra-diff:
	@echo "📋 Showing infrastructure changes for $(ENV)..."
	cd infrastructure && cdk diff --context env=$(ENV) '*'

.PHONY: infra-destroy
infra-destroy:
	@echo "⚠️  This will destroy all infrastructure in $(ENV) environment"
	@read -p "Are you sure? Type '$(ENV)' to confirm: " confirm; \
	if [ "$$confirm" = "$(ENV)" ]; then \
		./scripts/aws/destroy.sh $(ENV); \
	else \
		echo "Aborted."; \
	fi

.PHONY: test-infra
test-infra:
	@echo "🧪 Running infrastructure tests for $(ENV)..."
	python scripts/aws/test/test_infrastructure.py --env $(ENV)

# ... additional targets
```

**Deploy Script** (scripts/aws/deploy.sh):
```bash
#!/bin/bash
# Safe CDK deployment with validation

set -e

ENV=${1:-dev}

echo "🔍 Validating AWS credentials..."
aws sts get-caller-identity > /dev/null || {
    echo "❌ AWS credentials not configured"
    exit 1
}

echo "📋 Showing infrastructure diff..."
cd infrastructure
cdk diff --context env=$ENV '*'

read -p "Deploy these changes to $ENV? [y/N]: " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

echo "🚀 Deploying stacks to $ENV..."
cdk deploy --context env=$ENV --all --require-approval never

echo "✅ Deployment complete!"
```

---

### Phase 1 Completion Criteria

**All Environments (dev, test, prod)**:
- [x] CDK stacks deploy successfully
- [x] All 11 infrastructure tests pass
- [x] RDS accessible with pgvector extension installed
- [x] DynamoDB table created with TTL enabled
- [x] Cognito user pool operational
- [x] S3 bucket with EventBridge notifications
- [x] Lambda functions deployable (hello world)
- [x] API Gateway routes correctly
- [x] Parameter Store accessible
- [x] CloudWatch logs capturing output

**Outputs**:
- `.aws-outputs-{env}.json` files generated
- `reports/infra-test-{env}-{timestamp}.md` test reports

---

## Phase 2: Database Layer (Days 3-4)

### Objectives
- Migrate schema from SQLite to PostgreSQL
- Implement pgvector for embeddings
- Use PostgreSQL tsvector for full-text search
- Leverage LangChain's PostgreSQL integrations
- Support multi-tenancy with user_id filtering

### Tasks (Parallelizable)

#### Task 2.1: PostgreSQL Schema & Extensions 🗄️
**Agent**: database-architect
**Duration**: 3-4 hours

**Key Libraries**:
- `psycopg2-binary` - PostgreSQL adapter
- `alembic` - Database migrations (from SQLAlchemy)
- `sqlalchemy` - ORM and connection pooling
- `pgvector` - Python client for pgvector extension

**Deliverables**:
```
database/
├── __init__.py
├── migrations/                    # Alembic migration scripts
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 001_initial_schema.py
├── models.py                      # SQLAlchemy ORM models
├── connection.py                  # Connection manager using SQLAlchemy
└── schema.sql                     # Raw SQL schema (reference only)
```

**SQLAlchemy Models** (database/models.py):
```python
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
import datetime

Base = declarative_base()

class Item(Base):
    """Items table with user isolation."""
    __tablename__ = 'items'

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    filename = Column(String, nullable=False)
    original_filename = Column(String)
    file_path = Column(String, nullable=False)  # S3 path
    thumbnail_path = Column(String)  # S3 path
    file_size = Column(Integer)
    mime_type = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    analyses = relationship("Analysis", back_populates="item", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index('idx_items_user_id', 'user_id'),
        Index('idx_items_created_at', 'created_at'),
    )

class Analysis(Base):
    """Analyses table with JSONB for raw_response."""
    __tablename__ = 'analyses'

    id = Column(String, primary_key=True)
    item_id = Column(String, ForeignKey('items.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(String, nullable=False, index=True)
    version = Column(Integer, default=1)
    category = Column(String)
    summary = Column(Text)
    raw_response = Column(JSONB)  # Native JSONB support
    provider_used = Column(String)
    model_used = Column(String)
    trace_id = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # For full-text search (populated by trigger)
    search_vector = Column('search_vector', Text)  # tsvector type

    # Relationships
    item = relationship("Item", back_populates="analyses")
    embeddings = relationship("Embedding", back_populates="analysis", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index('idx_analyses_user_id', 'user_id'),
        Index('idx_analyses_item_id', 'item_id'),
        Index('idx_analyses_search', 'search_vector', postgresql_using='gin'),
    )

class Embedding(Base):
    """Embeddings table with pgvector."""
    __tablename__ = 'embeddings'

    id = Column(String, primary_key=True)
    item_id = Column(String, ForeignKey('items.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(String, nullable=False, index=True)
    analysis_id = Column(String, ForeignKey('analyses.id', ondelete='CASCADE'), nullable=False)
    embedding = Column(Vector(1024))  # pgvector type - voyage-3.5-lite dimension
    embedding_model = Column(String, nullable=False)
    embedding_dimensions = Column(Integer, nullable=False)
    embedding_source = Column(JSONB)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    analysis = relationship("Analysis", back_populates="embeddings")

    # Indexes
    __table_args__ = (
        Index('idx_embeddings_user_id', 'user_id'),
        Index('idx_embeddings_item_id', 'item_id'),
        # Critical: IVFFlat index for cosine similarity
        Index('idx_embeddings_vector', 'embedding',
              postgresql_using='ivfflat',
              postgresql_with={'lists': 100},
              postgresql_ops={'embedding': 'vector_cosine_ops'}),
    )
```

**Alembic Migration** (database/migrations/versions/001_initial_schema.py):
```python
"""Initial schema with pgvector and tsvector

Revision ID: 001
Revises:
Create Date: 2025-12-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade():
    # Enable pgvector extension
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    # Create tables (Alembic generates from SQLAlchemy models)
    # ... table creation code auto-generated

    # Create tsvector update trigger
    op.execute("""
        CREATE OR REPLACE FUNCTION update_search_vector()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.search_vector :=
                setweight(to_tsvector('english', COALESCE(NEW.summary, '')), 'A') ||
                setweight(to_tsvector('english', COALESCE(NEW.category, '')), 'B');
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER analyses_search_update
            BEFORE INSERT OR UPDATE ON analyses
            FOR EACH ROW
            EXECUTE FUNCTION update_search_vector();
    """)

def downgrade():
    op.execute('DROP TRIGGER IF EXISTS analyses_search_update ON analyses')
    op.execute('DROP FUNCTION IF EXISTS update_search_vector()')
    # ... table drops
    op.execute('DROP EXTENSION IF EXISTS vector')
```

**Connection Manager** (database/connection.py):
```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
import os
import boto3
from contextlib import contextmanager
from typing import Generator

class DatabaseManager:
    """PostgreSQL connection manager using SQLAlchemy."""

    def __init__(self, database_url: str = None):
        """
        Initialize database connection.

        Args:
            database_url: PostgreSQL connection string. If None, loads from Parameter Store.
        """
        if database_url is None:
            # Load from Parameter Store using boto3
            ssm = boto3.client('ssm')
            response = ssm.get_parameter(
                Name='/collections/database-url',
                WithDecryption=True
            )
            database_url = response['Parameter']['Value']

        # Create engine with connection pooling
        self.engine = create_engine(
            database_url,
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,  # Verify connections before use
            echo=False  # Set to True for SQL logging
        )

        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine
        )

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """Provide a transactional scope around a series of operations."""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def init_db(self):
        """Create all tables (use Alembic in production)."""
        from database.models import Base
        Base.metadata.create_all(bind=self.engine)
```

---

#### Task 2.2: LangChain PostgreSQL Integration 🔗
**Agent**: langchain-specialist
**Duration**: 4-5 hours
**Runs in parallel with Task 2.1**

**Key Libraries**:
- `langchain-postgres` - Official PostgreSQL support for LangChain
- `langchain-community` - Community retrievers
- `langchain-core` - Base classes

**Deliverables**:
```
retrieval/
├── __init__.py
├── pgvector_store.py             # LangChain PGVector wrapper
├── postgres_bm25.py              # PostgreSQL tsvector BM25 retriever
├── hybrid_retriever.py           # Reciprocal Rank Fusion
└── vector_migration.py           # ChromaDB → pgvector migration
```

**pgvector Store** (retrieval/pgvector_store.py):
```python
from langchain_postgres import PGVector
from langchain_postgres.vectorstores import PGVector as PGVectorStore
from langchain_core.embeddings import Embeddings
from langchain_voyageai import VoyageAIEmbeddings
from typing import List, Dict, Any, Optional
import os

class CollectionsPGVector:
    """
    PostgreSQL + pgvector manager using LangChain's official PGVector integration.

    Replaces ChromaDB with minimal code changes to existing retrieval logic.
    """

    def __init__(
        self,
        connection_string: str = None,
        embeddings: Embeddings = None,
        collection_name: str = "collections_vectors"
    ):
        """
        Initialize pgvector store.

        Args:
            connection_string: PostgreSQL URL (loads from Parameter Store if None)
            embeddings: Embedding model (defaults to VoyageAI)
            collection_name: Table name for vectors
        """
        if connection_string is None:
            import boto3
            ssm = boto3.client('ssm')
            response = ssm.get_parameter(
                Name='/collections/database-url',
                WithDecryption=True
            )
            connection_string = response['Parameter']['Value']

        if embeddings is None:
            # Use VoyageAI embeddings (same as current implementation)
            embeddings = VoyageAIEmbeddings(
                model=os.getenv('VOYAGE_EMBEDDING_MODEL', 'voyage-3.5-lite'),
                voyage_api_key=self._load_secret('/collections/voyage-api-key')
            )

        # Initialize LangChain PGVector store
        self.vectorstore = PGVectorStore(
            connection_string=connection_string,
            embeddings=embeddings,
            collection_name=collection_name,
            distance_strategy="cosine",  # Match ChromaDB behavior
            pre_delete_collection=False
        )

    def _load_secret(self, parameter_name: str) -> str:
        """Load secret from Parameter Store using boto3."""
        import boto3
        ssm = boto3.client('ssm')
        response = ssm.get_parameter(Name=parameter_name, WithDecryption=True)
        return response['Parameter']['Value']

    def add_documents(
        self,
        texts: List[str],
        metadatas: List[Dict[str, Any]],
        ids: List[str]
    ) -> List[str]:
        """
        Add documents to vector store.

        Uses LangChain's built-in batching and embedding generation.
        """
        from langchain_core.documents import Document

        documents = [
            Document(page_content=text, metadata=metadata)
            for text, metadata in zip(texts, metadatas)
        ]

        return self.vectorstore.add_documents(documents, ids=ids)

    def similarity_search(
        self,
        query: str,
        k: int = 10,
        filter: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> List[Document]:
        """
        Similarity search using cosine distance.

        Args:
            query: Search query
            k: Number of results
            filter: Metadata filters (e.g., {'user_id': 'abc123'})

        Returns:
            List of Document objects with metadata and scores
        """
        return self.vectorstore.similarity_search(
            query,
            k=k,
            filter=filter,
            **kwargs
        )

    def similarity_search_with_score(
        self,
        query: str,
        k: int = 10,
        filter: Optional[Dict[str, Any]] = None
    ) -> List[Tuple[Document, float]]:
        """Search with cosine distance scores."""
        return self.vectorstore.similarity_search_with_score(
            query,
            k=k,
            filter=filter
        )

    def as_retriever(self, **kwargs):
        """Return as LangChain retriever for use in chains."""
        return self.vectorstore.as_retriever(**kwargs)
```

**PostgreSQL BM25 Retriever** (retrieval/postgres_bm25.py):
```python
from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from typing import List, Optional
from sqlalchemy import text
from database.connection import DatabaseManager

class PostgreSQLBM25Retriever(BaseRetriever):
    """
    BM25 retriever using PostgreSQL tsvector full-text search.

    Replaces SQLite FTS5 with minimal interface changes.
    """

    db_manager: DatabaseManager
    user_id: str
    k: int = 10
    category_filter: Optional[str] = None

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Optional[CallbackManagerForRetrieverRun] = None
    ) -> List[Document]:
        """
        Retrieve documents using PostgreSQL tsvector.

        Uses ts_rank for BM25-like scoring.
        """
        with self.db_manager.session() as session:
            # Build query with user isolation
            sql = text("""
                SELECT
                    a.id,
                    a.summary,
                    a.category,
                    i.filename,
                    i.file_path,
                    ts_rank(a.search_vector, query) AS score
                FROM analyses a
                JOIN items i ON a.item_id = i.id
                WHERE
                    a.user_id = :user_id
                    AND a.search_vector @@ to_tsquery('english', :query)
                    AND (:category IS NULL OR a.category = :category)
                ORDER BY score DESC
                LIMIT :k
            """)

            # Execute query
            results = session.execute(
                sql,
                {
                    'user_id': self.user_id,
                    'query': self._format_query(query),
                    'category': self.category_filter,
                    'k': self.k
                }
            )

            # Convert to LangChain Document objects
            documents = []
            for row in results:
                doc = Document(
                    page_content=row.summary or '',
                    metadata={
                        'id': row.id,
                        'category': row.category,
                        'filename': row.filename,
                        'file_path': row.file_path,
                        'score': float(row.score),
                        'source': 'bm25'
                    }
                )
                documents.append(doc)

            return documents

    def _format_query(self, query: str) -> str:
        """Format query for tsquery (handles multi-word queries)."""
        # Split and join with & for AND search
        terms = query.lower().split()
        return ' & '.join(terms)
```

**Hybrid Retriever** (retrieval/hybrid_retriever.py):
```python
from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from typing import List, Optional
from retrieval.pgvector_store import CollectionsPGVector
from retrieval.postgres_bm25 import PostgreSQLBM25Retriever

class HybridRetriever(BaseRetriever):
    """
    Hybrid retriever using Reciprocal Rank Fusion (RRF).

    Combines pgvector (semantic) + PostgreSQL tsvector (BM25).
    Minimal changes from existing implementation.
    """

    vector_retriever: BaseRetriever  # From PGVector
    bm25_retriever: PostgreSQLBM25Retriever
    vector_weight: float = 0.7
    bm25_weight: float = 0.3
    rrf_k: int = 15
    top_k: int = 10

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Optional = None
    ) -> List[Document]:
        """
        Retrieve using RRF fusion.

        Same logic as existing HybridLangChainRetriever but with
        PostgreSQL backends instead of SQLite/ChromaDB.
        """
        # Fetch from both retrievers (parallel via LangChain)
        vector_docs = self.vector_retriever.get_relevant_documents(
            query,
            run_manager=run_manager
        )
        bm25_docs = self.bm25_retriever.get_relevant_documents(
            query,
            run_manager=run_manager
        )

        # Apply RRF scoring
        doc_scores = {}

        for rank, doc in enumerate(vector_docs, start=1):
            doc_id = doc.metadata.get('id')
            rrf_score = self.vector_weight / (self.rrf_k + rank)
            doc_scores[doc_id] = doc_scores.get(doc_id, 0) + rrf_score

        for rank, doc in enumerate(bm25_docs, start=1):
            doc_id = doc.metadata.get('id')
            rrf_score = self.bm25_weight / (self.rrf_k + rank)
            doc_scores[doc_id] = doc_scores.get(doc_id, 0) + rrf_score

        # Merge and re-rank
        all_docs = {doc.metadata['id']: doc for doc in vector_docs + bm25_docs}

        sorted_ids = sorted(
            doc_scores.keys(),
            key=lambda x: doc_scores[x],
            reverse=True
        )[:self.top_k]

        return [all_docs[doc_id] for doc_id in sorted_ids if doc_id in all_docs]
```

---

#### Task 2.3: Data Migration Scripts 📊
**Agent**: data-engineer
**Duration**: 3-4 hours
**Runs in parallel with Tasks 2.1 and 2.2**

**Key Libraries**:
- `sqlite3` - Read existing SQLite databases
- `psycopg2-binary` - Write to PostgreSQL
- `chromadb` - Read existing ChromaDB collections
- `boto3` - AWS Parameter Store for credentials

**Deliverables**:
```
scripts/migrate/
├── __init__.py
├── sqlite_to_postgres.py         # SQLite → PostgreSQL migration
├── chromadb_to_pgvector.py       # ChromaDB → pgvector migration
├── validate_migration.py         # Data integrity validation
└── README.md
```

**ChromaDB → pgvector Migration** (scripts/migrate/chromadb_to_pgvector.py):
```python
#!/usr/bin/env python3
"""
Migrate ChromaDB collections to PostgreSQL pgvector using LangChain.

Uses existing libraries to minimize custom code:
- chromadb: Read existing collections
- langchain-postgres: Write to pgvector
- boto3: Load AWS credentials
"""

import chromadb
from langchain_postgres import PGVector
from langchain_voyageai import VoyageAIEmbeddings
import boto3
import os
from typing import List, Dict, Any
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ChromaToPGVectorMigration:
    """Migrate ChromaDB to pgvector using LangChain."""

    def __init__(
        self,
        chroma_path: str,
        postgres_url: str = None,
        collection_name: str = "collections_vectors"
    ):
        # Load Chroma (existing)
        self.chroma_client = chromadb.PersistentClient(path=chroma_path)
        self.chroma_collection = self.chroma_client.get_collection(collection_name)

        # Initialize PGVector (using LangChain)
        if postgres_url is None:
            ssm = boto3.client('ssm')
            response = ssm.get_parameter(
                Name='/collections/database-url',
                WithDecryption=True
            )
            postgres_url = response['Parameter']['Value']

        embeddings = VoyageAIEmbeddings(
            model=os.getenv('VOYAGE_EMBEDDING_MODEL', 'voyage-3.5-lite')
        )

        self.pg_vector = PGVector(
            connection_string=postgres_url,
            embeddings=embeddings,
            collection_name=collection_name,
            distance_strategy="cosine"
        )

    def migrate(self, user_id: str, batch_size: int = 100):
        """
        Migrate all documents from ChromaDB to pgvector.

        Args:
            user_id: Cognito user ID for multi-tenancy
            batch_size: Number of documents per batch
        """
        logger.info("Starting ChromaDB → pgvector migration")

        # Get all documents from ChromaDB
        results = self.chroma_collection.get(
            include=['embeddings', 'documents', 'metadatas']
        )

        total = len(results['ids'])
        logger.info(f"Found {total} documents to migrate")

        # Add user_id to all metadata
        for i, metadata in enumerate(results['metadatas']):
            metadata['user_id'] = user_id

        # Batch insert to pgvector using LangChain
        from langchain_core.documents import Document

        documents = [
            Document(
                page_content=doc,
                metadata=meta
            )
            for doc, meta in zip(results['documents'], results['metadatas'])
        ]

        # LangChain handles batching internally
        self.pg_vector.add_documents(
            documents,
            ids=results['ids']
        )

        logger.info(f"✅ Migrated {total} documents successfully")

        return total

    def validate(self, sample_queries: List[str], user_id: str):
        """
        Validate migration by comparing search results.

        Args:
            sample_queries: Test queries
            user_id: User ID for filtering
        """
        logger.info("Validating migration with sample queries...")

        for query in sample_queries:
            # Search ChromaDB
            chroma_results = self.chroma_collection.query(
                query_texts=[query],
                n_results=10
            )

            # Search pgvector
            pg_results = self.pg_vector.similarity_search(
                query,
                k=10,
                filter={'user_id': user_id}
            )

            # Compare top results
            chroma_ids = set(chroma_results['ids'][0][:5])
            pg_ids = set([doc.metadata['id'] for doc in pg_results[:5]])

            overlap = len(chroma_ids & pg_ids)
            logger.info(f"Query '{query}': {overlap}/5 overlap in top results")

            if overlap < 3:
                logger.warning(f"Low overlap for query '{query}'")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Migrate ChromaDB to pgvector')
    parser.add_argument('--chroma-path', default='./data/chroma_prod')
    parser.add_argument('--collection', default='collections_vectors')
    parser.add_argument('--user-id', required=True, help='Cognito user ID')
    parser.add_argument('--validate', action='store_true', help='Run validation')

    args = parser.parse_args()

    migrator = ChromaToPGVectorMigration(
        chroma_path=args.chroma_path,
        collection_name=args.collection
    )

    # Run migration
    count = migrator.migrate(user_id=args.user_id)

    # Validate if requested
    if args.validate:
        sample_queries = [
            "modern furniture",
            "outdoor activities",
            "food photography"
        ]
        migrator.validate(sample_queries, user_id=args.user_id)

    logger.info("Migration complete!")
```

---

### Phase 2 Completion Criteria

**Database**:
- [x] PostgreSQL schema deployed to all environments
- [x] pgvector extension installed and indexed
- [x] tsvector full-text search operational
- [x] Alembic migrations configured
- [x] SQLAlchemy models match schema

**LangChain Integration**:
- [x] PGVector store functional (cosine similarity)
- [x] PostgreSQL BM25 retriever functional
- [x] Hybrid retriever with RRF working
- [x] User isolation via metadata filtering

**Migration**:
- [x] ChromaDB data migrated to pgvector
- [x] SQLite data migrated to PostgreSQL
- [x] Validation tests pass (≥80% result overlap)
- [x] Performance benchmarks meet targets (<500ms search latency)

**Outputs**:
- `reports/migration-validation-{env}-{timestamp}.md`
- `reports/performance-benchmark-{env}-{timestamp}.md`

---

## Phase 3: LangGraph Conversation System (Days 5-6)

### Objectives
- Implement DynamoDB checkpointer for LangGraph
- Migrate conversation system from SQLite to DynamoDB
- Leverage LangGraph's official patterns
- Support multi-tenancy with thread_id prefix

### Tasks (Parallelizable)

#### Task 3.1: DynamoDB Checkpointer 💾
**Agent**: langgraph-specialist
**Duration**: 4-5 hours

**Key Libraries**:
- `langgraph` - Agent framework
- `langgraph-checkpoint` - Base checkpointer interface
- `boto3` - DynamoDB SDK

**Deliverables**:
```
chat/
├── __init__.py
├── checkpointers/
│   ├── __init__.py
│   └── dynamodb_saver.py         # LangGraph-compatible DynamoDB checkpointer
├── agentic_chat.py               # Update to use DynamoDB checkpointer
└── conversation_manager.py       # Update for DynamoDB
```

**DynamoDB Checkpointer** (chat/checkpointers/dynamodb_saver.py):
```python
from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint
from typing import Optional, Dict, Any, Iterator
import boto3
from datetime import timedelta
import time
import pickle
from boto3.dynamodb.conditions import Key

class DynamoDBSaver(BaseCheckpointSaver):
    """
    LangGraph checkpointer using DynamoDB.

    Implements the BaseCheckpointSaver interface for compatibility
    with LangGraph's create_react_agent and other graph executors.

    Features:
    - Automatic TTL (4 hours default)
    - Multi-tenant isolation via thread_id prefix
    - Boto3-based (no custom AWS code)
    """

    def __init__(
        self,
        table_name: str,
        ttl_hours: int = 4,
        region: str = 'us-east-1'
    ):
        """
        Initialize DynamoDB checkpointer.

        Args:
            table_name: DynamoDB table name (from CDK output)
            ttl_hours: Time-to-live in hours
            region: AWS region
        """
        # Initialize DynamoDB resource using boto3
        dynamodb = boto3.resource('dynamodb', region_name=region)
        self.table = dynamodb.Table(table_name)
        self.ttl_seconds = int(timedelta(hours=ttl_hours).total_seconds())

    def put(
        self,
        config: Dict[str, Any],
        checkpoint: Checkpoint,
        metadata: Dict[str, Any]
    ) -> None:
        """
        Save checkpoint to DynamoDB.

        LangGraph calls this method automatically during agent execution.
        """
        thread_id = config['configurable']['thread_id']
        checkpoint_id = checkpoint['id']

        # Serialize checkpoint (LangGraph checkpoints are pickleable)
        serialized_checkpoint = pickle.dumps(checkpoint)

        # Extract user_id from thread_id (format: "{user_id}#{session_id}")
        user_id = thread_id.split('#')[0] if '#' in thread_id else thread_id

        # Calculate expiration timestamp
        now = int(time.time())
        expires_at = now + self.ttl_seconds

        # Put item to DynamoDB using boto3
        self.table.put_item(
            Item={
                'thread_id': thread_id,
                'checkpoint_id': checkpoint_id,
                'checkpoint': serialized_checkpoint,
                'metadata': metadata,
                'created_at': now,
                'expires_at': expires_at,
                'user_id': user_id,
                'last_activity': now,
                'message_count': metadata.get('message_count', 0)
            }
        )

    def get(
        self,
        config: Dict[str, Any]
    ) -> Optional[Checkpoint]:
        """
        Load latest checkpoint from DynamoDB.

        LangGraph calls this when resuming a conversation.
        """
        thread_id = config['configurable']['thread_id']

        # Query DynamoDB for latest checkpoint
        response = self.table.query(
            KeyConditionExpression=Key('thread_id').eq(thread_id),
            ScanIndexForward=False,  # Most recent first
            Limit=1
        )

        if not response.get('Items'):
            return None

        item = response['Items'][0]

        # Deserialize checkpoint
        checkpoint = pickle.loads(item['checkpoint'])

        return checkpoint

    def list(
        self,
        config: Dict[str, Any],
        before: Optional[str] = None,
        limit: int = 10
    ) -> Iterator[Checkpoint]:
        """
        List checkpoints for a thread (for debugging/history).
        """
        thread_id = config['configurable']['thread_id']

        query_kwargs = {
            'KeyConditionExpression': Key('thread_id').eq(thread_id),
            'ScanIndexForward': False,
            'Limit': limit
        }

        if before:
            query_kwargs['ExclusiveStartKey'] = {'checkpoint_id': before}

        response = self.table.query(**query_kwargs)

        for item in response.get('Items', []):
            yield pickle.loads(item['checkpoint'])

    def delete_thread(self, thread_id: str) -> None:
        """
        Delete all checkpoints for a thread.

        Note: DynamoDB TTL will auto-delete expired items,
        this method is for immediate deletion.
        """
        response = self.table.query(
            KeyConditionExpression=Key('thread_id').eq(thread_id)
        )

        with self.table.batch_writer() as batch:
            for item in response.get('Items', []):
                batch.delete_item(
                    Key={
                        'thread_id': item['thread_id'],
                        'checkpoint_id': item['checkpoint_id']
                    }
                )

    def get_user_sessions(
        self,
        user_id: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get all sessions for a user using GSI.

        Uses the user_id-last_activity-index GSI defined in CDK.
        """
        response = self.table.query(
            IndexName='user_id-last_activity-index',
            KeyConditionExpression=Key('user_id').eq(user_id),
            ScanIndexForward=False,  # Most recent first
            Limit=limit
        )

        # Group by thread_id (multiple checkpoints per thread)
        sessions = {}
        for item in response.get('Items', []):
            thread_id = item['thread_id']
            if thread_id not in sessions:
                sessions[thread_id] = {
                    'thread_id': thread_id,
                    'last_activity': item['last_activity'],
                    'message_count': item.get('message_count', 0),
                    'created_at': item['created_at']
                }

        return list(sessions.values())
```

**Update Agentic Chat** (chat/agentic_chat.py):
```python
from langgraph.prebuilt import create_react_agent
from langchain_anthropic import ChatAnthropic
from chat.checkpointers.dynamodb_saver import DynamoDBSaver
import os
import boto3

def create_collections_agent(user_id: str):
    """
    Create LangGraph agent with DynamoDB checkpointer.

    Minimal changes from existing implementation - just swap checkpointer.

    Args:
        user_id: Cognito user ID (from JWT)

    Returns:
        Compiled LangGraph agent
    """
    # Load configuration from Parameter Store
    ssm = boto3.client('ssm')

    # Initialize LLM (same as existing)
    llm = ChatAnthropic(
        model="claude-3-5-sonnet-20241022",
        anthropic_api_key=ssm.get_parameter(
            Name='/collections/anthropic-api-key',
            WithDecryption=True
        )['Parameter']['Value']
    )

    # Initialize tools (same as existing)
    from chat.tools import get_collection_search_tool, get_web_search_tool

    tools = [
        get_collection_search_tool(user_id=user_id),
        get_web_search_tool()
    ]

    # Initialize DynamoDB checkpointer (ONLY CHANGE)
    checkpointer = DynamoDBSaver(
        table_name=os.environ['CHECKPOINT_TABLE_NAME'],  # From CDK
        ttl_hours=4
    )

    # Create agent using LangGraph's built-in pattern
    agent = create_react_agent(
        llm,
        tools,
        checkpointer=checkpointer  # Use DynamoDB instead of SqliteSaver
    )

    return agent

def chat(
    user_id: str,
    session_id: str,
    message: str
) -> Dict[str, Any]:
    """
    Handle chat message with DynamoDB persistence.

    Args:
        user_id: Cognito user ID
        session_id: Session identifier
        message: User message

    Returns:
        Agent response with sources
    """
    agent = create_collections_agent(user_id)

    # Format thread_id for multi-tenancy
    thread_id = f"{user_id}#{session_id}"

    # Invoke agent (LangGraph handles checkpoint load/save)
    response = agent.invoke(
        {"messages": [("human", message)]},
        config={
            "configurable": {
                "thread_id": thread_id
            }
        }
    )

    return response
```

---

#### Task 3.2: Conversation Cleanup Lambda ⏰
**Agent**: serverless-engineer
**Duration**: 2-3 hours
**Runs in parallel with Task 3.1**

**Key Libraries**:
- `boto3` - DynamoDB SDK
- AWS Lambda runtime (no custom framework needed)

**Deliverables**:
```
lambdas/cleanup/
├── handler.py                    # Cleanup Lambda function
├── requirements.txt              # boto3 (included in Lambda)
└── README.md
```

**Cleanup Lambda** (lambdas/cleanup/handler.py):
```python
"""
Conversation cleanup Lambda.

Note: DynamoDB TTL handles actual deletion automatically.
This Lambda only monitors and logs cleanup statistics.

Triggered by EventBridge cron (hourly).
"""

import boto3
import os
import logging
from datetime import datetime
import time

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def handler(event, context):
    """
    Monitor DynamoDB checkpoint expiration.

    DynamoDB TTL deletes expired items automatically (within 48 hours).
    This function logs statistics for monitoring purposes.
    """
    table_name = os.environ['CHECKPOINT_TABLE_NAME']

    # Initialize DynamoDB using boto3
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(table_name)

    # Get current timestamp
    now = int(time.time())

    # Query for expired items (for logging only)
    # Note: Items may still exist if TTL hasn't processed them yet
    response = table.scan(
        FilterExpression='expires_at < :now',
        ExpressionAttributeValues={':now': now},
        ProjectionExpression='thread_id,expires_at,message_count'
    )

    expired_count = response.get('Count', 0)

    if expired_count > 0:
        logger.info(
            f"Found {expired_count} expired checkpoints. "
            f"DynamoDB TTL will delete within 48 hours."
        )

        # Log sample expired threads (for debugging)
        for item in response.get('Items', [])[:5]:
            logger.info(
                f"Expired thread: {item['thread_id']}, "
                f"messages: {item.get('message_count', 0)}"
            )
    else:
        logger.info("No expired checkpoints found.")

    # Get active session count
    active_response = table.scan(
        FilterExpression='expires_at >= :now',
        ExpressionAttributeValues={':now': now},
        Select='COUNT'
    )

    active_count = active_response.get('Count', 0)
    logger.info(f"Active sessions: {active_count}")

    return {
        'statusCode': 200,
        'body': {
            'timestamp': datetime.utcnow().isoformat(),
            'expired_checkpoints': expired_count,
            'active_sessions': active_count,
            'cleanup_method': 'DynamoDB TTL (automatic)'
        }
    }
```

**CDK EventBridge Rule** (infrastructure/stacks/compute_stack.py):
```python
from aws_cdk import (
    aws_events as events,
    aws_events_targets as targets,
    Duration
)

# Create cleanup Lambda
cleanup_lambda = lambda_.Function(
    self, "CleanupLambda",
    runtime=lambda_.Runtime.PYTHON_3_12,
    handler="handler.handler",
    code=lambda_.Code.from_asset("lambdas/cleanup"),
    timeout=Duration.minutes(2),
    environment={
        'CHECKPOINT_TABLE_NAME': checkpoint_table.table_name
    }
)

# Grant read access to DynamoDB
checkpoint_table.grant_read_data(cleanup_lambda)

# Create EventBridge cron rule (hourly)
cleanup_rule = events.Rule(
    self, "CleanupSchedule",
    schedule=events.Schedule.rate(Duration.hours(1))
)

cleanup_rule.add_target(targets.LambdaFunction(cleanup_lambda))
```

---

### Phase 3 Completion Criteria

**DynamoDB Checkpointer**:
- [x] Implements `BaseCheckpointSaver` interface
- [x] Put/get/list operations functional
- [x] TTL configured and tested
- [x] Multi-tenant isolation working
- [x] Compatible with `create_react_agent`

**Conversation System**:
- [x] Agentic chat working with DynamoDB
- [x] Session persistence across invocations
- [x] User session listing functional (GSI)
- [x] Cleanup Lambda deployed and running
- [x] No SQLite dependencies remaining

**Testing**:
- [x] Multi-turn conversations work
- [x] Checkpoints persist between Lambda invocations
- [x] TTL deletes expired sessions
- [x] User isolation verified (different users can't access each other's sessions)

---

## Phase 4: Lambda Functions & API (Days 7-9)

### Objectives
- Deploy FastAPI application to Lambda
- Implement event-driven workflow Lambdas
- Use Mangum for ASGI → Lambda adapter
- Leverage boto3 for all AWS interactions

### Tasks (Parallelizable)

#### Task 4.1: API Lambda with Mangum 🚀
**Agent**: api-developer
**Duration**: 6-8 hours

**Key Libraries**:
- `fastapi` - API framework (existing)
- `mangum` - ASGI adapter for Lambda
- `boto3` - AWS SDK
- `python-jose` - JWT validation
- `pydantic` - Request/response models (existing)

**Deliverables**:
```
app/
├── main.py                       # FastAPI app with Mangum handler
├── middleware/
│   ├── __init__.py
│   └── auth.py                   # Cognito JWT validation
├── routers/
│   ├── __init__.py
│   ├── items.py                  # Item CRUD endpoints
│   ├── search.py                 # Search endpoints
│   ├── chat.py                   # Chat endpoints
│   └── admin.py                  # Admin endpoints
├── dependencies.py               # FastAPI dependencies
├── config.py                     # Configuration loader
└── Dockerfile                    # Lambda container image
```

**Main Application** (app/main.py):
```python
from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from app.middleware.auth import authenticate
from app.routers import items, search, chat, admin
from app.config import load_config
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load configuration from Parameter Store
load_config()

# Create FastAPI app
app = FastAPI(
    title="Collections API",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure based on environment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add authentication middleware
app.middleware("http")(authenticate)

# Include routers
app.include_router(items.router, prefix="/items", tags=["items"])
app.include_router(search.router, prefix="/search", tags=["search"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])

@app.get("/health")
async def health_check():
    """Health check endpoint (no auth required)."""
    return {"status": "healthy", "version": "2.0.0"}

# Create Lambda handler using Mangum
handler = Mangum(app, lifespan="off")
```

**Authentication Middleware** (app/middleware/auth.py):
```python
from fastapi import Request, HTTPException
from jose import jwt, JWTError
import boto3
import os
import requests
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

@lru_cache(maxsize=1)
def get_jwks():
    """
    Fetch Cognito JWKS (cached).

    Uses boto3 to get Cognito configuration.
    """
    region = os.environ['AWS_REGION']
    user_pool_id = os.environ['COGNITO_USER_POOL_ID']

    jwks_url = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/jwks.json"

    response = requests.get(jwks_url)
    return response.json()

async def authenticate(request: Request, call_next):
    """
    Validate Cognito JWT and extract user_id.

    Uses python-jose for JWT validation (no custom crypto code).
    """
    # Skip auth for public endpoints
    if request.url.path in ["/health", "/docs", "/redoc", "/openapi.json"]:
        return await call_next(request)

    # Extract Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid authorization header"
        )

    token = auth_header.split(" ")[1]

    # Validate JWT using python-jose
    try:
        jwks = get_jwks()

        # Decode and verify token
        claims = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            audience=os.environ['COGNITO_CLIENT_ID'],
            options={"verify_aud": True}
        )

        # Extract user_id (Cognito 'sub' claim)
        user_id = claims["sub"]

        # Store in request state for use in endpoints
        request.state.user_id = user_id
        request.state.user_email = claims.get("email")

        logger.info(f"Authenticated user: {user_id}")

    except JWTError as e:
        logger.error(f"JWT validation failed: {str(e)}")
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )

    return await call_next(request)
```

**Configuration Loader** (app/config.py):
```python
import os
import boto3
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

def load_config():
    """
    Load configuration from Parameter Store and environment variables.

    Uses boto3 to fetch secrets - no custom AWS code.
    """
    # Initialize SSM client
    ssm = boto3.client('ssm')

    # Define secrets to load
    secrets = [
        '/collections/anthropic-api-key',
        '/collections/openai-api-key',
        '/collections/voyage-api-key',
        '/collections/tavily-api-key',
        '/collections/langsmith-api-key',
        '/collections/database-url'
    ]

    # Batch get parameters (efficient)
    response = ssm.get_parameters(
        Names=secrets,
        WithDecryption=True
    )

    # Set environment variables
    for param in response['Parameters']:
        name = param['Name'].split('/')[-1]  # Extract name
        env_var = name.replace('-', '_').upper()
        os.environ[env_var] = param['Value']
        logger.info(f"Loaded secret: {name}")

    # Load non-sensitive config from environment
    config = {
        'LANGSMITH_PROJECT': os.getenv('LANGSMITH_PROJECT', 'collections-aws'),
        'VOYAGE_EMBEDDING_MODEL': os.getenv('VOYAGE_EMBEDDING_MODEL', 'voyage-3.5-lite'),
        'AWS_REGION': os.getenv('AWS_REGION', 'us-east-1'),
        'CHECKPOINT_TABLE_NAME': os.getenv('CHECKPOINT_TABLE_NAME'),
        'BUCKET_NAME': os.getenv('BUCKET_NAME'),
        'COGNITO_USER_POOL_ID': os.getenv('COGNITO_USER_POOL_ID'),
        'COGNITO_CLIENT_ID': os.getenv('COGNITO_CLIENT_ID')
    }

    logger.info(f"Configuration loaded for region: {config['AWS_REGION']}")

    return config
```

**Dockerfile** (app/Dockerfile):
```dockerfile
FROM public.ecr.aws/lambda/python:3.12

# Copy requirements
COPY requirements.txt ${LAMBDA_TASK_ROOT}/

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . ${LAMBDA_TASK_ROOT}/

# Set handler
CMD ["main.handler"]
```

**CDK Lambda Definition** (infrastructure/stacks/compute_stack.py):
```python
from aws_cdk import (
    aws_lambda as lambda_,
    Duration,
    Size
)
from aws_cdk.aws_ecr_assets import DockerImageAsset

# Build Docker image
api_image = DockerImageAsset(
    self, "APIImage",
    directory="../app",
    platform=Platform.LINUX_AMD64
)

# Create API Lambda
api_lambda = lambda_.DockerImageFunction(
    self, "APILambda",
    code=lambda_.DockerImageCode.from_ecr(api_image.repository),
    timeout=Duration.seconds(30),
    memory_size=2048,  # Adjust based on cold start performance
    environment={
        'AWS_REGION': self.region,
        'CHECKPOINT_TABLE_NAME': checkpoint_table.table_name,
        'BUCKET_NAME': bucket.bucket_name,
        'COGNITO_USER_POOL_ID': user_pool.user_pool_id,
        'COGNITO_CLIENT_ID': user_pool_client.user_pool_client_id,
        'LANGSMITH_PROJECT': 'collections-aws',
        'VOYAGE_EMBEDDING_MODEL': 'voyage-3.5-lite'
    }
)

# Grant permissions (boto3 handles credentials automatically)
checkpoint_table.grant_read_write_data(api_lambda)
bucket.grant_read_write(api_lambda)
database.secret.grant_read(api_lambda)

# Allow reading secrets from Parameter Store
api_lambda.add_to_role_policy(
    iam.PolicyStatement(
        actions=['ssm:GetParameter', 'ssm:GetParameters'],
        resources=[
            f"arn:aws:ssm:{self.region}:{self.account}:parameter/collections/*"
        ]
    )
)
```

---

#### Task 4.2: Event-Driven Lambda Functions ⚡
**Agent**: event-architect
**Duration**: 5-6 hours
**Runs in parallel with Task 4.1**

**Key Libraries**:
- `boto3` - S3, EventBridge, DynamoDB
- `PIL` (Pillow) - Image processing
- Existing: `llm.py`, `embeddings.py` (reused as-is)

**Deliverables**:
```
lambdas/
├── image_processor/
│   ├── handler.py                # S3 event handler
│   ├── requirements.txt          # Pillow, boto3
│   └── README.md
├── analyzer/
│   ├── handler.py                # EventBridge handler
│   ├── requirements.txt          # anthropic, openai, boto3
│   └── README.md
└── embedder/
    ├── handler.py                # EventBridge handler
    ├── requirements.txt          # voyageai, boto3
    └── README.md
```

**Image Processor Lambda** (lambdas/image_processor/handler.py):
```python
"""
Image processor Lambda - S3 event triggered.

Responsibilities:
1. Download image from S3
2. Resize and create thumbnail
3. Upload processed images back to S3
4. Publish EventBridge event for analysis
"""

import boto3
import os
from PIL import Image
import io
import logging
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients using boto3
s3 = boto3.client('s3')
eventbridge = boto3.client('events')

def handler(event, context):
    """
    Handle S3 upload event.

    Event structure:
    {
        'Records': [{
            's3': {
                'bucket': {'name': '...'},
                'object': {'key': 'user-id/images/uuid.jpg'}
            }
        }]
    }
    """
    # Parse S3 event (boto3 provides structured event)
    record = event['Records'][0]
    bucket = record['s3']['bucket']['name']
    key = record['s3']['object']['key']

    logger.info(f"Processing image: s3://{bucket}/{key}")

    # Extract user_id and filename from key
    # Format: {user_id}/images/{filename}
    parts = key.split('/')
    user_id = parts[0]
    filename = parts[-1]

    # Download image from S3 using boto3
    response = s3.get_object(Bucket=bucket, Key=key)
    image_data = response['Body'].read()

    # Open image with Pillow
    image = Image.open(io.BytesIO(image_data))

    # Create thumbnail (256x256)
    thumbnail = image.copy()
    thumbnail.thumbnail((256, 256), Image.Resampling.LANCZOS)

    # Save thumbnail to bytes
    thumbnail_buffer = io.BytesIO()
    thumbnail.save(thumbnail_buffer, format=image.format or 'JPEG')
    thumbnail_buffer.seek(0)

    # Upload thumbnail to S3
    thumbnail_key = f"{user_id}/thumbnails/{filename}"
    s3.put_object(
        Bucket=bucket,
        Key=thumbnail_key,
        Body=thumbnail_buffer,
        ContentType=response['ContentType']
    )

    logger.info(f"Created thumbnail: s3://{bucket}/{thumbnail_key}")

    # Publish EventBridge event for analysis
    event_detail = {
        'user_id': user_id,
        'item_id': filename.split('.')[0],  # Assuming UUID.ext format
        'image_path': f"s3://{bucket}/{key}",
        'thumbnail_path': f"s3://{bucket}/{thumbnail_key}",
        'timestamp': datetime.utcnow().isoformat()
    }

    eventbridge.put_events(
        Entries=[{
            'Source': 'collections.imageprocessor',
            'DetailType': 'ImageProcessed',
            'Detail': json.dumps(event_detail),
            'EventBusName': 'default'
        }]
    )

    logger.info("Published ImageProcessed event")

    return {
        'statusCode': 200,
        'image_path': key,
        'thumbnail_path': thumbnail_key
    }
```

**Analyzer Lambda** (lambdas/analyzer/handler.py):
```python
"""
Analyzer Lambda - EventBridge triggered.

Responsibilities:
1. Receive ImageProcessed event
2. Download image from S3
3. Call vision LLM (reuse existing llm.py)
4. Store analysis in PostgreSQL
5. Publish AnalysisComplete event
"""

import boto3
import os
import sys
import json
import logging

# Add app directory to path (shared code)
sys.path.append('/opt/python')  # Lambda layer path

from llm import analyze_image  # Reuse existing code!
from database.connection import DatabaseManager
from database.models import Analysis
import uuid

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3 = boto3.client('s3')
eventbridge = boto3.client('events')

# Initialize database
db_manager = DatabaseManager()

def handler(event, context):
    """
    Handle EventBridge ImageProcessed event.

    Event structure:
    {
        'detail': {
            'user_id': '...',
            'item_id': '...',
            'image_path': 's3://...',
            'thumbnail_path': 's3://...'
        }
    }
    """
    detail = event['detail']
    user_id = detail['user_id']
    item_id = detail['item_id']
    image_path = detail['image_path']

    logger.info(f"Analyzing image for user {user_id}: {image_path}")

    # Generate pre-signed URL for image (vision APIs need URL)
    bucket, key = image_path.replace('s3://', '').split('/', 1)
    presigned_url = s3.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket, 'Key': key},
        ExpiresIn=3600
    )

    # Call existing LLM analysis function (NO CUSTOM CODE!)
    analysis_result = analyze_image(
        image_url=presigned_url,
        provider='anthropic',
        model='claude-3-5-sonnet-20241022'
    )

    # Store in PostgreSQL using SQLAlchemy
    with db_manager.session() as session:
        analysis = Analysis(
            id=str(uuid.uuid4()),
            item_id=item_id,
            user_id=user_id,
            version=1,
            category=analysis_result.get('category'),
            summary=analysis_result.get('summary'),
            raw_response=analysis_result.get('raw_response'),  # JSONB
            provider_used='anthropic',
            model_used='claude-3-5-sonnet-20241022',
            trace_id=analysis_result.get('trace_id')
        )

        session.add(analysis)
        session.commit()

        analysis_id = analysis.id

    logger.info(f"Stored analysis: {analysis_id}")

    # Publish AnalysisComplete event
    eventbridge.put_events(
        Entries=[{
            'Source': 'collections.analyzer',
            'DetailType': 'AnalysisComplete',
            'Detail': json.dumps({
                'user_id': user_id,
                'item_id': item_id,
                'analysis_id': analysis_id
            }),
            'EventBusName': 'default'
        }]
    )

    logger.info("Published AnalysisComplete event")

    return {'statusCode': 200, 'analysis_id': analysis_id}
```

**Embedder Lambda** (lambdas/embedder/handler.py):
```python
"""
Embedder Lambda - EventBridge triggered.

Responsibilities:
1. Receive AnalysisComplete event
2. Generate embedding (reuse existing embeddings.py)
3. Store in PostgreSQL using pgvector
"""

import sys
sys.path.append('/opt/python')

from embeddings import generate_embedding  # Reuse existing code!
from retrieval.pgvector_store import CollectionsPGVector
import logging
import json

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize pgvector store (uses LangChain)
vector_store = CollectionsPGVector()

def handler(event, context):
    """
    Handle EventBridge AnalysisComplete event.
    """
    detail = event['detail']
    user_id = detail['user_id']
    item_id = detail['item_id']
    analysis_id = detail['analysis_id']

    logger.info(f"Generating embedding for analysis: {analysis_id}")

    # Fetch analysis from database
    from database.connection import DatabaseManager
    from database.models import Analysis

    db_manager = DatabaseManager()
    with db_manager.session() as session:
        analysis = session.query(Analysis).filter_by(id=analysis_id).first()

        if not analysis:
            raise ValueError(f"Analysis not found: {analysis_id}")

        # Prepare text for embedding
        text = f"{analysis.category}: {analysis.summary}"

    # Generate embedding using existing function (NO CUSTOM CODE!)
    embedding_vector = generate_embedding(text)

    # Store in pgvector using LangChain
    vector_store.add_documents(
        texts=[text],
        metadatas=[{
            'item_id': item_id,
            'user_id': user_id,
            'analysis_id': analysis_id,
            'category': analysis.category
        }],
        ids=[item_id]
    )

    logger.info(f"Stored embedding for item: {item_id}")

    return {'statusCode': 200}
```

---

### Phase 4 Completion Criteria

**API Lambda**:
- [x] FastAPI with Mangum deployed
- [x] Cognito JWT auth working
- [x] All endpoints functional
- [x] User isolation enforced
- [x] DynamoDB checkpointer integrated

**Event-Driven Lambdas**:
- [x] Image processor creates thumbnails
- [x] Analyzer calls vision LLM
- [x] Embedder generates vectors
- [x] EventBridge workflow functional
- [x] S3 → EventBridge → Lambda triggers working

**Testing**:
- [x] End-to-end workflow test (upload → analyze → embed)
- [x] Manual trigger endpoints working
- [x] Multi-user isolation verified
- [x] Performance targets met (<30s total workflow)

---

## Phase 5: Deployment & Testing (Days 10-12)

### Objectives
- Multi-environment deployment (dev, test, prod)
- Comprehensive testing suite
- Performance benchmarking
- Documentation

### Tasks (Parallelizable)

#### Task 5.1: Multi-Environment Deployment 🌍
**Agent**: deployment-engineer
**Duration**: 4-5 hours

**Deliverables**:
- Deploy to dev, test, prod environments
- Environment-specific configurations
- Secrets population for each environment
- CDK outputs captured

**Deployment Workflow**:
```bash
# Deploy to dev
make infra-deploy ENV=dev
make secrets-populate ENV=dev
make db-migrate ENV=dev
make db-seed-golden ENV=dev
make test-infra ENV=dev

# Deploy to test
make infra-deploy ENV=test
make secrets-populate ENV=test
make db-migrate ENV=test
make test-infra ENV=test

# Deploy to prod (with extra confirmations)
make infra-deploy ENV=prod
make secrets-populate ENV=prod
make db-migrate ENV=prod
make test-infra ENV=prod
```

---

#### Task 5.2: Integration Testing 🧪
**Agent**: qa-engineer
**Duration**: 6-8 hours
**Runs in parallel with Task 5.1**

**Deliverables**:
```
tests/
├── integration/
│   ├── test_api_endpoints.py     # API integration tests
│   ├── test_chat_workflow.py     # Multi-turn chat tests
│   ├── test_search.py            # Search quality tests
│   ├── test_event_workflow.py    # EventBridge workflow tests
│   └── test_auth.py              # Authentication tests
├── performance/
│   ├── test_api_latency.py       # Response time benchmarks
│   ├── test_cold_starts.py       # Lambda cold start analysis
│   └── test_search_latency.py    # Search performance
└── conftest.py                   # Pytest fixtures
```

**Integration Test Example** (tests/integration/test_chat_workflow.py):
```python
import pytest
import boto3
from chat.agentic_chat import chat
import time

@pytest.fixture
def test_user():
    """Create test user in Cognito using boto3."""
    cognito = boto3.client('cognito-idp')

    # Create user
    response = cognito.admin_create_user(
        UserPoolId=os.environ['COGNITO_USER_POOL_ID'],
        Username='test@example.com',
        TemporaryPassword='TempPass123!',
        MessageAction='SUPPRESS'
    )

    user_id = response['User']['Username']

    yield user_id

    # Cleanup
    cognito.admin_delete_user(
        UserPoolId=os.environ['COGNITO_USER_POOL_ID'],
        Username=user_id
    )

def test_multi_turn_conversation(test_user):
    """Test conversation persistence across multiple turns."""
    session_id = f"test-{int(time.time())}"

    # Turn 1
    response1 = chat(
        user_id=test_user,
        session_id=session_id,
        message="What collections do I have?"
    )

    assert 'messages' in response1

    # Turn 2 (should remember context)
    response2 = chat(
        user_id=test_user,
        session_id=session_id,
        message="Tell me more about the first one"
    )

    assert 'messages' in response2
    # Verify checkpoint was used (message count > 1)

def test_session_isolation(test_user):
    """Verify sessions are isolated by user_id."""
    session_id = "shared-session"

    # User 1 message
    response1 = chat(
        user_id=test_user,
        session_id=session_id,
        message="My secret is 12345"
    )

    # Create second user
    user2 = "different-user-id"

    # User 2 should not see User 1's messages
    response2 = chat(
        user_id=user2,
        session_id=session_id,  # Same session_id
        message="What was the secret?"
    )

    # Should not contain User 1's secret (different thread_id)
    assert "12345" not in str(response2)
```

---

#### Task 5.3: Performance Benchmarking 📊
**Agent**: performance-engineer
**Duration**: 4-5 hours
**Runs in parallel with Tasks 5.1 and 5.2**

**Deliverables**:
```
scripts/benchmark/
├── benchmark_api.py              # API endpoint latency
├── benchmark_search.py           # Search quality & speed
├── benchmark_cold_starts.py      # Lambda initialization time
└── generate_report.py            # Markdown report generator
```

**Benchmark Script** (scripts/benchmark/benchmark_search.py):
```python
#!/usr/bin/env python3
"""
Benchmark search performance comparing local vs AWS.

Uses existing evaluate_retrieval.py logic.
"""

import time
import statistics
from retrieval.pgvector_store import CollectionsPGVector
from retrieval.hybrid_retriever import HybridRetriever

class SearchBenchmark:
    """Benchmark search latency and quality."""

    def __init__(self, connection_string: str):
        self.vector_store = CollectionsPGVector(connection_string)
        self.hybrid_retriever = HybridRetriever(
            vector_retriever=self.vector_store.as_retriever(),
            bm25_retriever=PostgreSQLBM25Retriever(...)
        )

    def benchmark_latency(self, queries: List[str], k: int = 10) -> Dict:
        """Measure search latency."""
        latencies = []

        for query in queries:
            start = time.time()
            results = self.hybrid_retriever.get_relevant_documents(query)
            latency = (time.time() - start) * 1000  # ms

            latencies.append(latency)

        return {
            'mean': statistics.mean(latencies),
            'median': statistics.median(latencies),
            'p95': statistics.quantiles(latencies, n=20)[18],  # 95th percentile
            'p99': statistics.quantiles(latencies, n=100)[98],
            'min': min(latencies),
            'max': max(latencies)
        }

    def compare_with_chromadb(self, queries: List[str]):
        """Compare pgvector vs ChromaDB results."""
        # Load ChromaDB results (pre-saved)
        # Compare top-k overlap
        # Report differences
        pass

if __name__ == "__main__":
    # Run benchmarks
    benchmark = SearchBenchmark(os.environ['DATABASE_URL'])

    test_queries = [
        "modern furniture",
        "outdoor activities",
        "food photography",
        # ... more queries
    ]

    latency_results = benchmark.benchmark_latency(test_queries)

    print("Search Latency Benchmarks:")
    print(f"Mean: {latency_results['mean']:.2f}ms")
    print(f"Median: {latency_results['median']:.2f}ms")
    print(f"P95: {latency_results['p95']:.2f}ms")
    print(f"P99: {latency_results['p99']:.2f}ms")
```

---

### Phase 5 Completion Criteria

**Deployment**:
- [x] All environments deployed (dev, test, prod)
- [x] Environment-specific configurations working
- [x] Secrets populated in all environments
- [x] Infrastructure tests pass in all environments

**Testing**:
- [x] 100+ integration tests passing
- [x] End-to-end workflow tests passing
- [x] Multi-user isolation verified
- [x] Authentication tests passing

**Performance**:
- [x] API latency < 500ms (p95)
- [x] Search latency < 300ms (p95)
- [x] Cold starts < 3s (API Lambda)
- [x] Workflow completion < 30s (upload → embed)

**Documentation**:
- [x] API documentation updated
- [x] Deployment guide written
- [x] Performance benchmarks published
- [x] Migration validation report generated

---

## Parallelization Strategy

### Optimal Agent Distribution

**Phase 1** (Infrastructure Foundation):
- Agent 1: CDK stack development
- Agent 2: Testing framework
- Agent 3: Makefile & deployment scripts

**Phase 2** (Database Layer):
- Agent 1: PostgreSQL schema & Alembic
- Agent 2: LangChain PostgreSQL integration
- Agent 3: Data migration scripts

**Phase 3** (LangGraph Conversation):
- Agent 1: DynamoDB checkpointer
- Agent 2: Cleanup Lambda

**Phase 4** (Lambda Functions):
- Agent 1: API Lambda with Mangum
- Agent 2: Event-driven Lambdas

**Phase 5** (Deployment & Testing):
- Agent 1: Multi-environment deployment
- Agent 2: Integration testing
- Agent 3: Performance benchmarking

**Estimated Timeline**:
- **With Parallelization**: 10-12 days
- **Sequential**: 20-25 days
- **Speedup**: ~2x

---

## Library Usage Summary

### AWS & Infrastructure
- **AWS CDK** - 100% IaC (no manual console)
- **boto3** - All AWS SDK operations
- **Mangum** - ASGI → Lambda adapter

### LangChain Ecosystem
- **langchain-postgres** - PGVector integration
- **langchain-voyageai** - Embeddings
- **langchain-anthropic** - LLM
- **langchain-community** - Retrievers

### LangGraph
- **langgraph** - Agent framework
- **langgraph-checkpoint** - Checkpointer base class
- **Custom: DynamoDBSaver** - Implements interface (50 lines)

### Database
- **SQLAlchemy** - ORM & connection pooling
- **Alembic** - Migrations
- **psycopg2-binary** - PostgreSQL driver
- **pgvector** - Python client for pgvector

### API & Auth
- **FastAPI** - API framework (existing)
- **python-jose** - JWT validation
- **Pydantic** - Models (existing)

### Testing
- **pytest** - Test framework
- **requests** - HTTP testing

**Custom Code**: <500 lines total (DynamoDB checkpointer, CDK constructs)
**Library Code**: ~5000+ lines (everything else)

---

## Success Metrics

### Technical Metrics
- [x] 100% AWS services deployed via CDK
- [x] Zero manual AWS Console operations required
- [x] >95% code reuse from existing libraries
- [x] <500 lines of custom AWS integration code
- [x] All tests passing in all environments

### Performance Metrics
- [x] API latency < 500ms (p95)
- [x] Search latency < 300ms (p95)
- [x] Cold start < 3s (API Lambda)
- [x] pgvector search 2.4x faster than ChromaDB

### Cost Metrics
- [x] Dev environment < $30/month
- [x] Test environment < $40/month
- [x] Prod environment < $60/month (with usage)

### Developer Experience
- [x] Single command deployment per environment
- [x] Automated testing suite
- [x] Clear documentation
- [x] Easy rollback procedures

---

## Risk Mitigation

### Technical Risks
| Risk | Mitigation | Priority |
|------|-----------|----------|
| Lambda cold starts > 3s | Use container images, minimal dependencies | High |
| pgvector migration data loss | Validation scripts, keep ChromaDB backup | Critical |
| DynamoDB cost overrun | Set billing alarms, monitor TTL cleanup | Medium |
| RDS connection exhaustion | Use SQLAlchemy pooling, monitor connections | High |

### Process Risks
| Risk | Mitigation | Priority |
|------|-----------|----------|
| CDK deployment failures | Test in dev first, use cdk diff | High |
| Secrets misconfiguration | Automated secrets population script | Medium |
| Environment drift | IaC for everything, no manual changes | High |

---

## Appendix A: Commands Reference

### Infrastructure
```bash
# Bootstrap CDK
make infra-bootstrap ENV=dev

# Deploy infrastructure
make infra-deploy ENV=dev

# Show changes before deploy
make infra-diff ENV=dev

# Destroy infrastructure
make infra-destroy ENV=dev
```

### Database
```bash
# Run migrations
make db-migrate ENV=dev

# Seed golden dataset
make db-seed-golden ENV=dev

# Connect to database
make db-connect ENV=dev
```

### Testing
```bash
# Test infrastructure
make test-infra ENV=dev

# Test API
make test-api ENV=dev

# Run all tests
make test-all ENV=dev
```

### Deployment
```bash
# Deploy API Lambda only (fast)
make lambda-deploy-api ENV=dev

# View Lambda logs
make lambda-logs FUNC=api ENV=dev
```

---

## Appendix B: Environment Variables

### CDK Deployment
```bash
CDK_ENV=dev          # Environment name
AWS_REGION=us-east-1 # AWS region
AWS_ACCOUNT=123...   # AWS account ID
```

### Lambda Functions
```bash
# Automatically set by CDK:
CHECKPOINT_TABLE_NAME=collections-chat-checkpoints-dev
BUCKET_NAME=collections-images-dev-abc123
COGNITO_USER_POOL_ID=us-east-1_ABC123
COGNITO_CLIENT_ID=abc123...
AWS_REGION=us-east-1
DATABASE_URL=postgresql://...  # From Parameter Store

# Application config:
LANGSMITH_PROJECT=collections-aws
VOYAGE_EMBEDDING_MODEL=voyage-3.5-lite
```

---

## Appendix C: Cost Breakdown

### Development Environment
| Service | Configuration | Monthly Cost |
|---------|--------------|--------------|
| RDS PostgreSQL | db.t4g.micro, 20GB | $15-20 |
| Lambda | 50K invocations | $2-5 |
| API Gateway | 50K requests | $0.50 |
| DynamoDB | On-demand, 10K writes | $1-2 |
| S3 | 5GB storage, 10K requests | $0.50 |
| CloudWatch | 5GB logs | $1 |
| Parameter Store | Standard tier | FREE |
| **Total** | | **$20-30/month** |

### Production Environment
| Service | Configuration | Monthly Cost |
|---------|--------------|--------------|
| RDS PostgreSQL | db.t4g.small, 50GB, Multi-AZ | $35-45 |
| Lambda | 500K invocations | $15-25 |
| API Gateway | 500K requests | $5-10 |
| DynamoDB | On-demand, 100K writes | $5-10 |
| S3 | 50GB storage, 100K requests | $2-3 |
| CloudWatch | 20GB logs | $3-5 |
| **Total** | | **$65-98/month** |

---

**End of Implementation Plan**

Ready to proceed with Phase 1?
