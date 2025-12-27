#!/usr/bin/env python3
"""
SQLite to PostgreSQL Migration Script

Migrates data from SQLite (collections.db) to AWS RDS PostgreSQL with schema transformations
for multi-tenancy support.

Schema Transformations:
- Add user_id column to all tables (from Cognito test user)
- Convert TEXT → JSONB for raw_response and embedding_source
- Preserve all existing data
- Use SQLAlchemy bulk operations for efficient insertion

Usage:
    python scripts/migrate/sqlite_to_postgres.py \\
        --sqlite-db ./data/collections_golden.db \\
        --postgres-url postgresql://user:pass@host:5432/collections \\
        --user-id cognito-user-id \\
        --dataset golden

    # Get postgres URL from AWS Parameter Store:
    POSTGRES_URL=$(aws ssm get-parameter --name /collections/dev/database-url --query 'Parameter.Value' --output text)

    # Get user ID from Cognito:
    USER_ID=$(aws cognito-idp list-users --user-pool-id <pool-id> --query 'Users[0].Username' --output text)

    python scripts/migrate/sqlite_to_postgres.py \\
        --sqlite-db ./data/collections_golden.db \\
        --postgres-url "$POSTGRES_URL" \\
        --user-id "$USER_ID" \\
        --dataset golden
"""

import sys
import os
import json
import argparse
import logging
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text, MetaData, Table, Column, String, Integer, DateTime, Text, JSON, ForeignKey
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

Base = declarative_base()


class MigrationStats:
    """Track migration statistics."""

    def __init__(self):
        self.items_migrated = 0
        self.analyses_migrated = 0
        self.embeddings_migrated = 0
        self.errors = []
        self.start_time = None
        self.end_time = None

    def __str__(self):
        duration = (self.end_time - self.start_time).total_seconds() if self.end_time and self.start_time else 0
        return f"""
Migration Statistics:
  Items migrated: {self.items_migrated}
  Analyses migrated: {self.analyses_migrated}
  Embeddings migrated: {self.embeddings_migrated}
  Errors: {len(self.errors)}
  Duration: {duration:.2f} seconds
"""


def create_postgres_schema(engine, user_id: str):
    """
    Create PostgreSQL tables with multi-tenancy support.

    Schema differences from SQLite:
    - user_id column added to all tables
    - raw_response: TEXT → JSONB
    - embedding_source: TEXT → JSONB
    - created_at/updated_at: TEXT → TIMESTAMP
    """
    logger.info("Creating PostgreSQL schema...")

    with engine.connect() as conn:
        # Enable pgvector extension (idempotent)
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        conn.commit()

        # Drop existing tables if they exist (for fresh migration)
        # NOTE: In production, you might want to add a --force flag for this
        logger.warning("Dropping existing tables (if any)...")
        conn.execute(text("DROP TABLE IF EXISTS embeddings CASCADE;"))
        conn.execute(text("DROP TABLE IF EXISTS analyses CASCADE;"))
        conn.execute(text("DROP TABLE IF EXISTS items CASCADE;"))
        conn.commit()

        # Create items table
        conn.execute(text("""
            CREATE TABLE items (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                original_filename TEXT,
                file_path TEXT NOT NULL,
                file_size INTEGER,
                mime_type TEXT,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            );
        """))

        # Create index on user_id for multi-tenancy queries
        conn.execute(text("CREATE INDEX idx_items_user_id ON items(user_id);"))

        # Create analyses table
        conn.execute(text("""
            CREATE TABLE analyses (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                category TEXT,
                summary TEXT,
                raw_response JSONB,
                provider_used TEXT,
                model_used TEXT,
                trace_id TEXT,
                created_at TIMESTAMP NOT NULL,
                FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE
            );
        """))

        # Create indices
        conn.execute(text("CREATE INDEX idx_analyses_user_id ON analyses(user_id);"))
        conn.execute(text("CREATE INDEX idx_analyses_item_id ON analyses(item_id);"))
        conn.execute(text("CREATE INDEX idx_analyses_category ON analyses(category);"))

        # Create embeddings table
        conn.execute(text("""
            CREATE TABLE embeddings (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                analysis_id TEXT NOT NULL,
                embedding_model TEXT NOT NULL,
                embedding_dimensions INTEGER NOT NULL,
                embedding_source JSONB NOT NULL,
                created_at TIMESTAMP NOT NULL,
                FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
                FOREIGN KEY (analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
            );
        """))

        # Create indices
        conn.execute(text("CREATE INDEX idx_embeddings_user_id ON embeddings(user_id);"))
        conn.execute(text("CREATE INDEX idx_embeddings_item_id ON embeddings(item_id);"))
        conn.execute(text("CREATE INDEX idx_embeddings_analysis_id ON embeddings(analysis_id);"))

        conn.commit()

    logger.info("PostgreSQL schema created successfully")


def read_sqlite_data(sqlite_path: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Read all data from SQLite database.

    Returns:
        Dictionary with 'items', 'analyses', 'embeddings' keys containing lists of records
    """
    logger.info(f"Reading data from SQLite: {sqlite_path}")

    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row

    data = {
        'items': [],
        'analyses': [],
        'embeddings': []
    }

    # Read items
    cursor = conn.execute("SELECT * FROM items")
    data['items'] = [dict(row) for row in cursor.fetchall()]
    logger.info(f"  Read {len(data['items'])} items")

    # Read analyses
    cursor = conn.execute("SELECT * FROM analyses")
    data['analyses'] = [dict(row) for row in cursor.fetchall()]
    logger.info(f"  Read {len(data['analyses'])} analyses")

    # Read embeddings
    cursor = conn.execute("SELECT * FROM embeddings")
    data['embeddings'] = [dict(row) for row in cursor.fetchall()]
    logger.info(f"  Read {len(data['embeddings'])} embeddings")

    conn.close()

    return data


def transform_data(data: Dict[str, List[Dict]], user_id: str) -> Dict[str, List[Dict]]:
    """
    Transform SQLite data for PostgreSQL schema.

    Transformations:
    - Add user_id to all records
    - Parse JSON strings to dict for raw_response and embedding_source
    - Convert ISO datetime strings to datetime objects
    """
    logger.info("Transforming data for PostgreSQL schema...")

    transformed = {
        'items': [],
        'analyses': [],
        'embeddings': []
    }

    # Transform items
    for item in data['items']:
        transformed_item = item.copy()
        transformed_item['user_id'] = user_id
        # Convert datetime strings
        transformed_item['created_at'] = datetime.fromisoformat(item['created_at'].replace('Z', '+00:00'))
        transformed_item['updated_at'] = datetime.fromisoformat(item['updated_at'].replace('Z', '+00:00'))
        transformed['items'].append(transformed_item)

    # Transform analyses
    for analysis in data['analyses']:
        transformed_analysis = analysis.copy()
        transformed_analysis['user_id'] = user_id

        # Parse raw_response JSON
        if analysis['raw_response']:
            try:
                transformed_analysis['raw_response'] = json.loads(analysis['raw_response'])
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON in raw_response for analysis {analysis['id']}")
                transformed_analysis['raw_response'] = {}
        else:
            transformed_analysis['raw_response'] = {}

        # Convert datetime
        transformed_analysis['created_at'] = datetime.fromisoformat(analysis['created_at'].replace('Z', '+00:00'))
        transformed['analyses'].append(transformed_analysis)

    # Transform embeddings
    for embedding in data['embeddings']:
        transformed_embedding = embedding.copy()
        transformed_embedding['user_id'] = user_id

        # Parse embedding_source JSON
        if embedding['embedding_source']:
            try:
                transformed_embedding['embedding_source'] = json.loads(embedding['embedding_source'])
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON in embedding_source for embedding {embedding['id']}")
                transformed_embedding['embedding_source'] = {}
        else:
            transformed_embedding['embedding_source'] = {}

        # Convert datetime
        transformed_embedding['created_at'] = datetime.fromisoformat(embedding['created_at'].replace('Z', '+00:00'))
        transformed['embeddings'].append(transformed_embedding)

    logger.info(f"  Transformed {len(transformed['items'])} items")
    logger.info(f"  Transformed {len(transformed['analyses'])} analyses")
    logger.info(f"  Transformed {len(transformed['embeddings'])} embeddings")

    return transformed


def bulk_insert_data(
    engine,
    data: Dict[str, List[Dict]],
    batch_size: int = 100,
    stats: Optional[MigrationStats] = None
) -> MigrationStats:
    """
    Bulk insert data into PostgreSQL using SQLAlchemy.

    Args:
        engine: SQLAlchemy engine
        data: Transformed data dictionary
        batch_size: Number of records to insert per batch
        stats: Optional MigrationStats object to update

    Returns:
        MigrationStats object with migration results
    """
    if stats is None:
        stats = MigrationStats()

    logger.info(f"Starting bulk insert (batch_size={batch_size})...")

    with engine.connect() as conn:
        # Insert items
        logger.info("Inserting items...")
        items = data['items']
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]

            # Use parameterized queries to avoid SQL injection and syntax issues
            for item in batch:
                conn.execute(
                    text("""
                        INSERT INTO items (id, user_id, filename, original_filename, file_path,
                                         file_size, mime_type, created_at, updated_at)
                        VALUES (:id, :user_id, :filename, :original_filename, :file_path,
                                :file_size, :mime_type, :created_at, :updated_at)
                    """),
                    {
                        'id': item['id'],
                        'user_id': item['user_id'],
                        'filename': item['filename'],
                        'original_filename': item.get('original_filename'),
                        'file_path': item['file_path'],
                        'file_size': item.get('file_size'),
                        'mime_type': item.get('mime_type'),
                        'created_at': item['created_at'],
                        'updated_at': item['updated_at']
                    }
                )

            stats.items_migrated += len(batch)
            logger.info(f"  Inserted {stats.items_migrated}/{len(items)} items")

        conn.commit()

        # Insert analyses
        logger.info("Inserting analyses...")
        analyses = data['analyses']
        for i in range(0, len(analyses), batch_size):
            batch = analyses[i:i + batch_size]

            for analysis in batch:
                # Use parameterized query for JSONB
                conn.execute(
                    text("""
                        INSERT INTO analyses (id, user_id, item_id, version, category, summary,
                                            raw_response, provider_used, model_used, trace_id, created_at)
                        VALUES (:id, :user_id, :item_id, :version, :category, :summary,
                                :raw_response, :provider_used, :model_used, :trace_id, :created_at)
                    """),
                    {
                        'id': analysis['id'],
                        'user_id': analysis['user_id'],
                        'item_id': analysis['item_id'],
                        'version': analysis['version'],
                        'category': analysis.get('category'),
                        'summary': analysis.get('summary'),
                        'raw_response': json.dumps(analysis['raw_response']),
                        'provider_used': analysis.get('provider_used'),
                        'model_used': analysis.get('model_used'),
                        'trace_id': analysis.get('trace_id'),
                        'created_at': analysis['created_at']
                    }
                )

            conn.commit()
            stats.analyses_migrated += len(batch)
            logger.info(f"  Inserted {stats.analyses_migrated}/{len(analyses)} analyses")

        # Insert embeddings
        logger.info("Inserting embeddings...")
        embeddings = data['embeddings']
        for i in range(0, len(embeddings), batch_size):
            batch = embeddings[i:i + batch_size]

            for embedding in batch:
                # Use parameterized query for JSONB
                conn.execute(
                    text("""
                        INSERT INTO embeddings (id, user_id, item_id, analysis_id, embedding_model,
                                              embedding_dimensions, embedding_source, created_at)
                        VALUES (:id, :user_id, :item_id, :analysis_id, :embedding_model,
                                :embedding_dimensions, :embedding_source, :created_at)
                    """),
                    {
                        'id': embedding['id'],
                        'user_id': embedding['user_id'],
                        'item_id': embedding['item_id'],
                        'analysis_id': embedding['analysis_id'],
                        'embedding_model': embedding['embedding_model'],
                        'embedding_dimensions': embedding['embedding_dimensions'],
                        'embedding_source': json.dumps(embedding['embedding_source']),
                        'created_at': embedding['created_at']
                    }
                )

            conn.commit()
            stats.embeddings_migrated += len(batch)
            logger.info(f"  Inserted {stats.embeddings_migrated}/{len(embeddings)} embeddings")

    logger.info("Bulk insert completed successfully")
    return stats


def validate_counts(engine, expected_counts: Dict[str, int]) -> bool:
    """
    Validate that PostgreSQL has the expected number of records.

    Args:
        engine: SQLAlchemy engine
        expected_counts: Dictionary with expected counts for each table

    Returns:
        True if counts match, False otherwise
    """
    logger.info("Validating record counts...")

    with engine.connect() as conn:
        # Check items
        result = conn.execute(text("SELECT COUNT(*) FROM items"))
        items_count = result.scalar()

        # Check analyses
        result = conn.execute(text("SELECT COUNT(*) FROM analyses"))
        analyses_count = result.scalar()

        # Check embeddings
        result = conn.execute(text("SELECT COUNT(*) FROM embeddings"))
        embeddings_count = result.scalar()

    logger.info(f"  Items: {items_count} (expected: {expected_counts['items']})")
    logger.info(f"  Analyses: {analyses_count} (expected: {expected_counts['analyses']})")
    logger.info(f"  Embeddings: {embeddings_count} (expected: {expected_counts['embeddings']})")

    if (items_count == expected_counts['items'] and
        analyses_count == expected_counts['analyses'] and
        embeddings_count == expected_counts['embeddings']):
        logger.info("✓ Counts match!")
        return True
    else:
        logger.error("✗ Counts do not match!")
        return False


def main():
    """Main migration orchestrator."""
    parser = argparse.ArgumentParser(
        description="Migrate SQLite data to PostgreSQL with multi-tenancy support"
    )
    parser.add_argument(
        '--sqlite-db',
        required=True,
        help='Path to SQLite database file'
    )
    parser.add_argument(
        '--postgres-url',
        required=True,
        help='PostgreSQL connection URL (postgresql://user:pass@host:port/dbname)'
    )
    parser.add_argument(
        '--user-id',
        required=True,
        help='Cognito user ID (sub claim) to associate with all records'
    )
    parser.add_argument(
        '--dataset',
        choices=['golden', 'full'],
        default='full',
        help='Dataset type (for logging/tracking)'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='Batch size for bulk inserts'
    )
    parser.add_argument(
        '--skip-schema-creation',
        action='store_true',
        help='Skip schema creation (tables already exist)'
    )

    args = parser.parse_args()

    # Initialize stats
    stats = MigrationStats()
    stats.start_time = datetime.now()

    try:
        # Verify SQLite database exists
        if not os.path.exists(args.sqlite_db):
            logger.error(f"SQLite database not found: {args.sqlite_db}")
            sys.exit(1)

        logger.info("=" * 70)
        logger.info("SQLite to PostgreSQL Migration")
        logger.info("=" * 70)
        logger.info(f"SQLite DB: {args.sqlite_db}")
        logger.info(f"PostgreSQL: {args.postgres_url.split('@')[1] if '@' in args.postgres_url else args.postgres_url}")
        logger.info(f"User ID: {args.user_id}")
        logger.info(f"Dataset: {args.dataset}")
        logger.info("=" * 70)

        # Create PostgreSQL engine
        engine = create_engine(args.postgres_url, echo=False)

        # Create schema
        if not args.skip_schema_creation:
            create_postgres_schema(engine, args.user_id)
        else:
            logger.info("Skipping schema creation (--skip-schema-creation)")

        # Read SQLite data
        sqlite_data = read_sqlite_data(args.sqlite_db)

        # Transform data
        transformed_data = transform_data(sqlite_data, args.user_id)

        # Bulk insert
        stats = bulk_insert_data(engine, transformed_data, args.batch_size, stats)

        # Validate counts
        expected_counts = {
            'items': len(sqlite_data['items']),
            'analyses': len(sqlite_data['analyses']),
            'embeddings': len(sqlite_data['embeddings'])
        }

        validation_passed = validate_counts(engine, expected_counts)

        stats.end_time = datetime.now()

        # Print summary
        logger.info("=" * 70)
        logger.info(stats)
        logger.info("=" * 70)

        if validation_passed:
            logger.info("✓ Migration completed successfully!")
            sys.exit(0)
        else:
            logger.error("✗ Migration validation failed!")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Migration failed: {str(e)}", exc_info=True)
        stats.errors.append(str(e))
        stats.end_time = datetime.now()
        logger.error(stats)
        sys.exit(1)


if __name__ == '__main__':
    main()
