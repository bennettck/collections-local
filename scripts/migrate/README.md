# Data Migration Scripts

This directory contains scripts for migrating data from local SQLite/ChromaDB to AWS PostgreSQL/pgvector.

## Overview

The migration process consists of three main scripts orchestrated by a single runner:

1. **SQLite → PostgreSQL Migration** (`sqlite_to_postgres.py`)
   - Migrates items, analyses, and embeddings metadata
   - Transforms schema for multi-tenancy (adds user_id)
   - Converts TEXT → JSONB for structured data

2. **ChromaDB → pgvector Migration** (`chromadb_to_pgvector.py`)
   - Migrates vector embeddings
   - Uses langchain-postgres for efficient batch insertion
   - Validates migration with sample queries

3. **Validation** (`validate_migration.py`)
   - Comprehensive validation checks
   - Generates detailed markdown report
   - Verifies data integrity and search functionality

4. **Orchestrator** (`run_migration.py`)
   - Manages complete migration workflow
   - Handles Cognito user creation
   - Supports dry-run mode

## Quick Start

### Prerequisites

1. AWS infrastructure deployed (Phase 1 complete)
2. Environment variables configured
3. Required Python packages installed:
   ```bash
   pip install -r requirements.txt
   ```

### Complete Migration (Recommended)

Use the orchestrator script for end-to-end migration:

```bash
# Migrate golden dataset to dev environment
python scripts/migrate/run_migration.py \
    --env dev \
    --dataset golden

# Dry run (validation only, no migration)
python scripts/migrate/run_migration.py \
    --env dev \
    --dataset golden \
    --dry-run

# Migrate full dataset to production
python scripts/migrate/run_migration.py \
    --env prod \
    --dataset full \
    --aws-profile production
```

The orchestrator will:
1. Get PostgreSQL URL from AWS Parameter Store
2. Get/create Cognito test user
3. Run SQLite migration
4. Run ChromaDB migration
5. Run validation checks
6. Generate migration report

### Manual Migration (Advanced)

For more control, run scripts individually:

#### Step 1: Get AWS Resources

```bash
# Get PostgreSQL URL from Parameter Store
POSTGRES_URL=$(aws ssm get-parameter \
    --name /collections/dev/database-url \
    --with-decryption \
    --query 'Parameter.Value' \
    --output text)

# Get Cognito User Pool ID from CDK outputs
USER_POOL_ID=$(jq -r '.[] | select(.OutputKey=="UserPoolId") | .OutputValue' \
    .aws-outputs-dev.json)

# Create test user and get user_id
aws cognito-idp admin-create-user \
    --user-pool-id "$USER_POOL_ID" \
    --username migration-test-golden \
    --user-attributes Name=email,Value=test@example.com

# Get user_id (sub claim)
USER_ID=$(aws cognito-idp admin-get-user \
    --user-pool-id "$USER_POOL_ID" \
    --username migration-test-golden \
    --query 'UserAttributes[?Name==`sub`].Value' \
    --output text)
```

#### Step 2: Run SQLite Migration

```bash
python scripts/migrate/sqlite_to_postgres.py \
    --sqlite-db ./data/collections_golden.db \
    --postgres-url "$POSTGRES_URL" \
    --user-id "$USER_ID" \
    --dataset golden \
    --batch-size 100
```

#### Step 3: Run ChromaDB Migration

```bash
python scripts/migrate/chromadb_to_pgvector.py \
    --chroma-path ./data/chroma_golden \
    --collection collections_vectors_golden \
    --postgres-url "$POSTGRES_URL" \
    --user-id "$USER_ID" \
    --batch-size 100 \
    --validate
```

#### Step 4: Run Validation

```bash
python scripts/migrate/validate_migration.py \
    --sqlite-db ./data/collections_golden.db \
    --postgres-url "$POSTGRES_URL" \
    --chroma-path ./data/chroma_golden \
    --chroma-collection collections_vectors_golden \
    --pgvector-collection collections_vectors \
    --user-id "$USER_ID" \
    --report-output validation_report.md
```

## Script Details

### sqlite_to_postgres.py

**Purpose**: Migrate relational data from SQLite to PostgreSQL with schema transformations.

**Schema Transformations**:
- Add `user_id` column (TEXT NOT NULL)
- Convert `raw_response` TEXT → JSONB
- Convert `embedding_source` TEXT → JSONB
- Convert `created_at`/`updated_at` TEXT → TIMESTAMP

**Options**:
```
--sqlite-db PATH          SQLite database file path
--postgres-url URL        PostgreSQL connection URL
--user-id ID              Cognito user ID (sub claim)
--dataset golden|full     Dataset type (for logging)
--batch-size N            Batch size for bulk inserts (default: 100)
--skip-schema-creation    Skip creating tables (use existing schema)
```

**Validation**:
- Compares record counts (items, analyses, embeddings)
- Reports any mismatches

### chromadb_to_pgvector.py

**Purpose**: Migrate vector embeddings from ChromaDB to PostgreSQL pgvector.

**Process**:
1. Read all vectors from ChromaDB collection
2. Add `user_id` to metadata
3. Batch insert to pgvector using langchain-postgres
4. Optionally validate with sample queries

**Options**:
```
--chroma-path PATH              ChromaDB persistent directory
--collection NAME               ChromaDB collection name
--postgres-url URL              PostgreSQL connection URL
--user-id ID                    Cognito user ID
--batch-size N                  Batch size (default: 100)
--validate                      Run validation queries
--pgvector-collection-name NAME pgvector collection name
```

**Sample Validation Queries**:
- "modern furniture"
- "outdoor activities"
- "food photography"
- "vintage items"
- "nature scenes"

### validate_migration.py

**Purpose**: Comprehensive validation of migrated data.

**Validation Checks**:

1. **SQLite → PostgreSQL Count Validation**
   - Compares record counts for items, analyses, embeddings
   - Pass: All counts match

2. **ChromaDB → pgvector Count Validation**
   - Compares vector counts
   - Pass: Vector counts match

3. **Sample Query Validation**
   - Runs 5 sample queries on both systems
   - Compares top-5 results for each query
   - Pass: Average overlap ≥ 80%

4. **User ID Validation**
   - Checks for NULL/empty user_ids
   - Pass: No NULL user_ids found

5. **JSONB Structure Validation**
   - Verifies raw_response and embedding_source are valid JSONB
   - Pass: All JSONB structures valid

6. **Search Performance Benchmark**
   - Measures search latency on pgvector
   - Pass: Average latency < 1000ms

**Options**:
```
--sqlite-db PATH              SQLite database path
--postgres-url URL            PostgreSQL connection URL
--chroma-path PATH            ChromaDB directory
--chroma-collection NAME      ChromaDB collection name
--pgvector-collection NAME    pgvector collection name
--user-id ID                  Expected user ID
--report-output PATH          Markdown report output path
--similarity-threshold FLOAT  Query similarity threshold (default: 0.8)
```

**Output**:
- Markdown validation report with pass/fail for each check
- Detailed metrics and statistics
- Performance benchmarks

### run_migration.py

**Purpose**: Orchestrate complete migration workflow.

**Workflow**:
1. Load AWS configuration (Parameter Store, CDK outputs)
2. Get or create Cognito test user
3. Run SQLite → PostgreSQL migration
4. Run ChromaDB → pgvector migration
5. Run validation checks
6. Generate summary report

**Options**:
```
--env dev|test|prod     AWS environment
--dataset golden|full   Dataset to migrate
--aws-profile NAME      AWS profile name
--dry-run               Validation only (no migration)
--user-id ID            Use existing user ID (skip Cognito)
--skip-cognito          Skip Cognito user creation
```

**Dry Run Mode**:
```bash
# Validate without migrating
python scripts/migrate/run_migration.py --env dev --dataset golden --dry-run
```

**Using Existing User**:
```bash
# Skip Cognito user creation
python scripts/migrate/run_migration.py \
    --env dev \
    --dataset golden \
    --user-id existing-cognito-user-id \
    --skip-cognito
```

## Migration Workflow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     run_migration.py                            │
│                   (Migration Orchestrator)                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
      ┌───────────────────────────────────────────────┐
      │  1. Get PostgreSQL URL (Parameter Store)      │
      └───────────────────────────────────────────────┘
                              │
                              ▼
      ┌───────────────────────────────────────────────┐
      │  2. Get/Create Cognito Test User              │
      │     (Extract user_id/sub claim)               │
      └───────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              │                               │
              ▼                               ▼
┌──────────────────────────┐    ┌──────────────────────────┐
│ sqlite_to_postgres.py    │    │ chromadb_to_pgvector.py  │
│                          │    │                          │
│ • Read SQLite data       │    │ • Read ChromaDB vectors  │
│ • Transform schema       │    │ • Add user_id metadata   │
│ • Add user_id            │    │ • Batch insert pgvector  │
│ • Bulk insert PostgreSQL │    │ • Validate with queries  │
└──────────────────────────┘    └──────────────────────────┘
              │                               │
              └───────────────┬───────────────┘
                              ▼
              ┌───────────────────────────────┐
              │  validate_migration.py        │
              │                               │
              │  • Count validation           │
              │  • Query comparison           │
              │  • User ID checks             │
              │  • JSONB validation           │
              │  • Performance benchmark      │
              └───────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │  Generate Reports             │
              │  • Validation report (MD)     │
              │  • Migration summary (MD)     │
              └───────────────────────────────┘
```

## Data Schema Comparison

### SQLite (Before)

```sql
CREATE TABLE items (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE analyses (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    raw_response TEXT,  -- JSON as text
    created_at TEXT NOT NULL
);

CREATE TABLE embeddings (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    embedding_source TEXT,  -- JSON as text
    created_at TEXT NOT NULL
);
```

### PostgreSQL (After)

```sql
CREATE TABLE items (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,  -- NEW: Multi-tenancy
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,  -- CHANGED: TEXT → TIMESTAMP
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE analyses (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,  -- NEW: Multi-tenancy
    item_id TEXT NOT NULL,
    raw_response JSONB,  -- CHANGED: TEXT → JSONB
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE embeddings (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,  -- NEW: Multi-tenancy
    item_id TEXT NOT NULL,
    embedding_source JSONB,  -- CHANGED: TEXT → JSONB
    created_at TIMESTAMP NOT NULL
);

-- pgvector (managed by langchain-postgres)
CREATE TABLE langchain_pg_embedding (
    id UUID PRIMARY KEY,
    collection_id UUID NOT NULL,
    embedding VECTOR(1024),  -- NEW: Vector storage
    document TEXT,
    cmetadata JSONB  -- Includes user_id
);
```

## Error Handling

### Migration Failures

If migration fails midway:

1. **Check Logs**:
   ```bash
   # Review stdout/stderr from migration scripts
   ```

2. **Rollback** (if needed):
   ```bash
   # Drop PostgreSQL tables
   psql "$POSTGRES_URL" -c "DROP TABLE embeddings CASCADE;"
   psql "$POSTGRES_URL" -c "DROP TABLE analyses CASCADE;"
   psql "$POSTGRES_URL" -c "DROP TABLE items CASCADE;"
   psql "$POSTGRES_URL" -c "DROP TABLE langchain_pg_embedding CASCADE;"
   psql "$POSTGRES_URL" -c "DROP TABLE langchain_pg_collection CASCADE;"
   ```

3. **Retry**:
   ```bash
   # Re-run migration with fresh schema
   python scripts/migrate/run_migration.py --env dev --dataset golden
   ```

### Validation Failures

If validation fails:

1. **Review Validation Report**:
   ```bash
   cat validation_report.md
   ```

2. **Check Specific Failures**:
   - Count mismatches: Investigate missing/extra records
   - Query overlap < 80%: Check embedding quality
   - NULL user_ids: Verify migration script logic
   - JSONB errors: Check data transformation

3. **Re-validate**:
   ```bash
   # Run validation standalone
   python scripts/migrate/validate_migration.py \
       --sqlite-db ./data/collections_golden.db \
       --postgres-url "$POSTGRES_URL" \
       --chroma-path ./data/chroma_golden \
       --chroma-collection collections_vectors_golden \
       --pgvector-collection collections_vectors \
       --user-id "$USER_ID" \
       --report-output validation_retry.md
   ```

## Testing

Unit tests are provided for each migration script:

```bash
# Run all migration tests
pytest scripts/migrate/tests/

# Run specific tests
pytest scripts/migrate/tests/test_sqlite_migration.py -v
pytest scripts/migrate/tests/test_chromadb_migration.py -v
pytest scripts/migrate/tests/test_validation.py -v
```

## Performance Considerations

### Batch Sizing

- **Small datasets (<1000 records)**: 100 records/batch
- **Medium datasets (1000-10000)**: 500 records/batch
- **Large datasets (>10000)**: 1000 records/batch

Adjust with `--batch-size` parameter.

### Network Latency

If migrating over slow network:
- Use smaller batch sizes
- Run validation separately after migration
- Consider using AWS EC2 instance in same region as RDS

### pgvector Performance

For large vector collections:
- pgvector uses HNSW/IVFFlat indexing
- Initial inserts may be slower (index building)
- Query performance improves after indexing

## Troubleshooting

### Common Issues

**Issue**: `VOYAGE_API_KEY not set`
**Solution**: Export environment variable:
```bash
export VOYAGE_API_KEY=your-api-key
```

**Issue**: `Collection not found in ChromaDB`
**Solution**: Verify collection name and path:
```bash
python -c "import chromadb; client = chromadb.PersistentClient(path='./data/chroma_prod'); print([c.name for c in client.list_collections()])"
```

**Issue**: `PostgreSQL connection failed`
**Solution**: Verify RDS is accessible and security groups allow connection:
```bash
# Test connection
psql "$POSTGRES_URL" -c "SELECT version();"
```

**Issue**: `Validation query overlap < 80%`
**Solution**: This may indicate:
- Different embedding models (verify voyage-3.5-lite is used)
- Distance metric mismatch (both should use cosine)
- Data corruption during migration

## Next Steps

After successful migration:

1. **Test AWS API**:
   ```bash
   # Test search endpoint with pgvector
   curl -X POST "$API_URL/search" \
       -H "Content-Type: application/json" \
       -d '{"query": "modern furniture", "search_type": "vector-lc", "top_k": 5}'
   ```

2. **Monitor Performance**:
   - Check CloudWatch metrics for RDS
   - Monitor Lambda execution times
   - Review search latency

3. **Migrate Full Dataset**:
   ```bash
   # After validating golden dataset, migrate full dataset
   python scripts/migrate/run_migration.py --env prod --dataset full
   ```

## Support

For issues or questions:
- Review validation reports in project root
- Check AWS CloudWatch logs
- See `IMPLEMENTATION_PLAN.md` for architecture details
