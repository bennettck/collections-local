# Database Package

PostgreSQL database layer for the Collections application with SQLAlchemy ORM, pgvector support, and Alembic migrations.

## Overview

This package provides a complete PostgreSQL database layer to replace the original SQLite implementation. It includes:

- **SQLAlchemy ORM Models**: Type-safe models with relationships
- **Multi-tenancy Support**: All tables include `user_id` for data isolation
- **Vector Search**: pgvector integration for semantic search (1024-dimensional embeddings)
- **Full-Text Search**: PostgreSQL tsvector with automatic triggers
- **Connection Management**: Parameter Store integration for secure credential storage
- **Database Migrations**: Alembic-based schema versioning

## Package Structure

```
database/
├── __init__.py                 # Package exports
├── models.py                   # SQLAlchemy ORM models
├── connection.py              # Connection manager with Parameter Store
├── migrations/
│   ├── alembic.ini            # Alembic configuration
│   ├── env.py                 # Migration environment
│   ├── script.py.mako         # Migration template
│   └── versions/
│       └── 001_initial_schema.py  # Initial schema migration
└── tests/
    ├── test_models.py         # Model unit tests
    └── test_connection.py     # Connection manager tests
```

## Models

### Item

Stores uploaded files with metadata.

**Fields:**
- `id` (String, PK): Unique identifier
- `user_id` (String, indexed): User owner
- `filename` (String): Stored filename
- `original_filename` (String, nullable): Original uploaded name
- `file_path` (String): Path to stored file
- `file_size` (BigInteger, nullable): Size in bytes
- `mime_type` (String, nullable): MIME type
- `created_at` (DateTime TZ): Creation timestamp
- `updated_at` (DateTime TZ): Last update timestamp

**Relationships:**
- `analyses`: One-to-many with Analysis (cascade delete)
- `embeddings`: One-to-many with Embedding (cascade delete)

### Analysis

Stores AI-generated analysis results with versioning.

**Fields:**
- `id` (String, PK): Unique identifier
- `item_id` (String, FK, indexed): Reference to Item
- `user_id` (String, indexed): User owner
- `version` (Integer): Analysis version number
- `category` (String, nullable, indexed): Item category
- `summary` (String, nullable): Brief summary
- `raw_response` (JSONB, nullable): Full analysis data
- `provider_used` (String, nullable): AI provider name
- `model_used` (String, nullable): Model name
- `trace_id` (String, nullable): Tracing identifier
- `search_vector` (TSVECTOR, nullable): Full-text search vector (auto-populated)
- `created_at` (DateTime TZ): Creation timestamp

**Relationships:**
- `item`: Many-to-one with Item
- `embeddings`: One-to-many with Embedding (cascade delete)

**Indexes:**
- `ix_analyses_item_id`: Item lookup
- `ix_analyses_user_id`: User filtering
- `ix_analyses_category`: Category filtering
- `idx_analyses_item_version`: Latest version queries (composite: item_id, version DESC)
- `idx_analyses_search_vector`: Full-text search (GIN index)

**Triggers:**
- `analyses_search_vector_trigger`: Automatically populates `search_vector` from `raw_response` JSONB fields

### Embedding

Stores vector embeddings for semantic search.

**Fields:**
- `id` (String, PK): Unique identifier
- `item_id` (String, FK, indexed): Reference to Item
- `analysis_id` (String, FK, indexed): Reference to Analysis
- `user_id` (String, indexed): User owner
- `vector` (Vector(1024), nullable): pgvector embedding
- `embedding_model` (String): Model used for embedding
- `embedding_dimensions` (Integer): Vector dimensions
- `embedding_source` (JSONB, nullable): Source field metadata
- `created_at` (DateTime TZ): Creation timestamp

**Relationships:**
- `item`: Many-to-one with Item
- `analysis`: Many-to-one with Analysis

**Indexes:**
- `ix_embeddings_item_id`: Item lookup
- `ix_embeddings_analysis_id`: Analysis lookup
- `ix_embeddings_user_id`: User filtering
- IVFFlat index for vector similarity search (created after data population)

## Connection Management

The connection manager provides automatic configuration from multiple sources:

### Configuration Priority

1. `DATABASE_URL` environment variable (direct connection string)
2. AWS Systems Manager Parameter Store (via `PARAMETER_STORE_DB_URL` env var)
3. SQLite fallback for local development

### Usage

```python
from database.connection import init_connection, get_session, health_check

# Initialize connection (call once at startup)
init_connection()

# Use sessions
with get_session() as session:
    item = session.query(Item).filter_by(id=item_id).first()
    # Automatically commits on success, rolls back on error

# Check health
status = health_check()
print(status)  # {'healthy': True, 'database': 'postgresql', ...}
```

### Parameter Store Integration

Store your database URL in AWS Systems Manager Parameter Store:

```bash
aws ssm put-parameter \
  --name "/collections/database/url" \
  --type "SecureString" \
  --value "postgresql://user:pass@host:5432/db"
```

Then set the environment variable:

```bash
export PARAMETER_STORE_DB_URL="/collections/database/url"
```

## Migrations

Alembic manages database schema versions.

### Running Migrations

```bash
# Navigate to database/migrations directory
cd database/migrations

# Upgrade to latest version
alembic upgrade head

# Downgrade one version
alembic downgrade -1

# Show current version
alembic current

# Show migration history
alembic history
```

### Creating New Migrations

```bash
# Auto-generate migration from model changes
alembic revision --autogenerate -m "Description of changes"

# Create empty migration
alembic revision -m "Description"
```

### Initial Migration (001_initial_schema.py)

The initial migration creates:
- pgvector extension
- All tables (items, analyses, embeddings)
- Indexes for performance
- Full-text search trigger and function

## Database Operations (database_sqlalchemy.py)

A new `database_sqlalchemy.py` module provides SQLAlchemy-based operations with the same API as the original `database.py`, but with `user_id` added to all functions.

### Key Differences from Original database.py

1. **All functions require `user_id` parameter** for multi-tenancy
2. Uses SQLAlchemy sessions instead of sqlite3 connections
3. JSONB support for structured data
4. pgvector support for embeddings
5. PostgreSQL full-text search via tsvector

### Example Usage

```python
from database_sqlalchemy import (
    init_db,
    create_item,
    get_item,
    create_analysis,
    search_items,
    create_embedding,
)

# Initialize
init_db()

# Create item (note: user_id required)
item = create_item(
    item_id="item-123",
    filename="photo.jpg",
    original_filename="vacation.jpg",
    file_path="/data/photo.jpg",
    file_size=1024000,
    mime_type="image/jpeg",
    user_id="user-456"  # NEW: Required for multi-tenancy
)

# Get item (user_id for security)
item = get_item("item-123", user_id="user-456")

# Create analysis
analysis = create_analysis(
    analysis_id="analysis-789",
    item_id="item-123",
    user_id="user-456",
    result={
        "category": "photo",
        "summary": "Beach vacation",
        "tags": ["beach", "sunset"]
    },
    provider_used="anthropic",
    model_used="claude-3"
)

# Search (PostgreSQL full-text search)
results = search_items(
    query="beach sunset",
    user_id="user-456",
    top_k=10
)

# Create embedding
embedding_id = create_embedding(
    item_id="item-123",
    analysis_id="analysis-789",
    user_id="user-456",
    embedding=[0.1] * 1024,  # 1024-dimensional vector
    model="voyage-2",
    source_fields={"summary": True, "tags": True}
)
```

## Testing

The package includes comprehensive unit tests for both models and connection management.

### Running Tests

```bash
# Run all database tests
pytest database/tests/ -v

# Run only model tests
pytest database/tests/test_models.py -v

# Run only connection tests
pytest database/tests/test_connection.py -v
```

### Test Coverage

- **Models (test_models.py)**: 12 tests
  - Item creation, timestamps, required fields, relationships
  - Analysis creation, JSONB fields, versioning, cascade delete
  - Embedding creation, vector dimensions, cascade delete, relationships

- **Connection (test_connection.py)**: 19 tests
  - Database URL retrieval (env, Parameter Store, fallback)
  - Connection initialization and pooling
  - Session management (commit, rollback)
  - Health checks
  - Connection cleanup

All tests use SQLite for speed and portability. The models use custom type decorators that adapt PostgreSQL-specific types (JSONB, Vector) to work with SQLite during testing.

## Migration from SQLite to PostgreSQL

To migrate from the original SQLite database to PostgreSQL:

1. **Set up PostgreSQL database** (via RDS or local instance)
2. **Configure DATABASE_URL** environment variable or Parameter Store
3. **Run migrations**: `alembic upgrade head`
4. **Update application code** to use `database_sqlalchemy.py` instead of `database.py`
5. **Add `user_id` parameter** to all database function calls
6. **Migrate data** (if needed) using custom migration script

### Breaking Changes

- All database functions now require `user_id` parameter
- `search_items()` uses PostgreSQL full-text search (different scoring than BM25)
- `raw_response` field is now JSONB (no need for JSON serialization)
- Embedding vectors stored directly in pgvector format

## Performance Considerations

### Connection Pooling

PostgreSQL connections use:
- Pool size: 10
- Max overflow: 20
- Pool recycle: 3600s (1 hour)
- Pre-ping: Enabled (validates connections before use)

### Indexes

The schema includes indexes for:
- User filtering (`user_id` on all tables)
- Item lookup (`item_id` on analyses, embeddings)
- Category filtering (`category` on analyses)
- Version queries (composite `item_id`, `version DESC`)
- Full-text search (GIN index on `search_vector`)
- Vector search (IVFFlat with cosine similarity - create after data population)

### Vector Index Creation

The IVFFlat index for vector similarity search should be created AFTER populating embeddings:

```sql
-- Create IVFFlat index (adjust lists parameter based on data size)
CREATE INDEX idx_embeddings_vector_cosine
ON embeddings
USING ivfflat (vector vector_cosine_ops)
WITH (lists = 100);
```

Recommended `lists` values:
- < 1K rows: 10-50
- 1K-10K rows: 50-100
- 10K-100K rows: 100-500
- > 100K rows: sqrt(row_count)

## Security

- Database credentials stored in AWS Parameter Store (encrypted)
- User isolation via `user_id` filtering
- SQL injection protection via SQLAlchemy ORM
- Foreign key constraints enforce referential integrity
- Cascade deletes prevent orphaned records

## Dependencies

- `sqlalchemy>=2.0.0`: ORM and query builder
- `alembic>=1.13.0`: Database migrations
- `psycopg2-binary>=2.9.0`: PostgreSQL driver
- `pgvector>=0.3.0`: Vector similarity search
- `boto3>=1.34.0`: AWS SDK (Parameter Store)

## Environment Variables

- `DATABASE_URL`: Direct PostgreSQL connection string (optional)
- `PARAMETER_STORE_DB_URL`: Parameter Store path (optional)
- `DATABASE_PATH`: SQLite fallback path (default: `./data/collections.db`)

## Troubleshooting

### Connection Issues

```python
from database.connection import health_check

status = health_check()
if not status["healthy"]:
    print(f"Error: {status.get('error')}")
```

### Migration Issues

```bash
# Check current version
alembic current

# View pending migrations
alembic heads

# Downgrade and retry
alembic downgrade -1
alembic upgrade head
```

### Parameter Store Access

Ensure AWS credentials are configured:

```bash
aws configure
# Or use IAM role (ECS, EC2, Lambda)
```

## Future Enhancements

- [ ] Vector search query functions with similarity scoring
- [ ] Migration script for SQLite → PostgreSQL data transfer
- [ ] Read replicas support for scaling
- [ ] Connection string encryption at rest
- [ ] Async SQLAlchemy support for FastAPI
- [ ] Automatic vector index maintenance
- [ ] Multi-region replication support
