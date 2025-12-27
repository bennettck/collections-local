#!/usr/bin/env python3
"""
Migration Validation Script

Validates data migration from SQLite/ChromaDB to PostgreSQL/pgvector.

Validation Checks:
1. Count validation: SQLite vs PostgreSQL
2. Count validation: ChromaDB vs pgvector
3. Sample query comparison (>=80% overlap in top results)
4. Check for NULL user_ids
5. Verify JSONB structure
6. Performance benchmark: search latency

Usage:
    python scripts/migrate/validate_migration.py \\
        --sqlite-db ./data/collections_golden.db \\
        --postgres-url postgresql://user:pass@host:5432/collections \\
        --chroma-path ./data/chroma_prod \\
        --chroma-collection collections_vectors_prod \\
        --pgvector-collection collections_vectors \\
        --user-id cognito-user-id \\
        --report-output validation_report.md
"""

import sys
import os
import json
import argparse
import logging
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Tuple
from datetime import datetime
import time

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
import chromadb
from dotenv import load_dotenv
from langchain_voyageai import VoyageAIEmbeddings
from langchain_postgres import PGVector

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ValidationReport:
    """Track validation results."""

    def __init__(self):
        self.checks = []
        self.start_time = datetime.now()
        self.end_time = None

    def add_check(self, name: str, passed: bool, details: str = ""):
        """Add a validation check result."""
        self.checks.append({
            'name': name,
            'passed': passed,
            'details': details
        })

    def passed_count(self) -> int:
        """Count passed checks."""
        return sum(1 for c in self.checks if c['passed'])

    def failed_count(self) -> int:
        """Count failed checks."""
        return sum(1 for c in self.checks if not c['passed'])

    def generate_markdown(self) -> str:
        """Generate markdown report."""
        self.end_time = datetime.now()
        duration = (self.end_time - self.start_time).total_seconds()

        md = f"""# Migration Validation Report

**Generated**: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}
**Duration**: {duration:.2f} seconds
**Total Checks**: {len(self.checks)}
**Passed**: {self.passed_count()}
**Failed**: {self.failed_count()}

## Summary

{'✓ All validation checks passed!' if self.failed_count() == 0 else '⚠ Some validation checks failed!'}

## Detailed Results

"""
        for i, check in enumerate(self.checks, 1):
            status = "✓ PASS" if check['passed'] else "✗ FAIL"
            md += f"### {i}. {check['name']}\n\n"
            md += f"**Status**: {status}\n\n"
            if check['details']:
                md += f"{check['details']}\n\n"

        md += f"""
## Conclusion

"""
        if self.failed_count() == 0:
            md += "Migration validation completed successfully. All data integrity checks passed.\n"
        else:
            md += f"Migration validation completed with {self.failed_count()} failed checks. Review the details above.\n"

        return md

    def __str__(self):
        """String representation."""
        return f"ValidationReport: {self.passed_count()}/{len(self.checks)} passed"


def validate_counts_postgres(
    sqlite_path: str,
    postgres_url: str,
    report: ValidationReport
):
    """Validate record counts between SQLite and PostgreSQL."""
    logger.info("Validating record counts (SQLite vs PostgreSQL)...")

    # Read SQLite counts
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_counts = {}

    cursor = sqlite_conn.execute("SELECT COUNT(*) FROM items")
    sqlite_counts['items'] = cursor.fetchone()[0]

    cursor = sqlite_conn.execute("SELECT COUNT(*) FROM analyses")
    sqlite_counts['analyses'] = cursor.fetchone()[0]

    cursor = sqlite_conn.execute("SELECT COUNT(*) FROM embeddings")
    sqlite_counts['embeddings'] = cursor.fetchone()[0]

    sqlite_conn.close()

    # Read PostgreSQL counts
    engine = create_engine(postgres_url)
    postgres_counts = {}

    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM items"))
        postgres_counts['items'] = result.scalar()

        result = conn.execute(text("SELECT COUNT(*) FROM analyses"))
        postgres_counts['analyses'] = result.scalar()

        result = conn.execute(text("SELECT COUNT(*) FROM embeddings"))
        postgres_counts['embeddings'] = result.scalar()

    # Compare counts
    details = f"""
**SQLite**:
- Items: {sqlite_counts['items']}
- Analyses: {sqlite_counts['analyses']}
- Embeddings: {sqlite_counts['embeddings']}

**PostgreSQL**:
- Items: {postgres_counts['items']}
- Analyses: {postgres_counts['analyses']}
- Embeddings: {postgres_counts['embeddings']}
"""

    all_match = (
        sqlite_counts['items'] == postgres_counts['items'] and
        sqlite_counts['analyses'] == postgres_counts['analyses'] and
        sqlite_counts['embeddings'] == postgres_counts['embeddings']
    )

    if all_match:
        logger.info("  ✓ Counts match!")
        report.add_check("SQLite → PostgreSQL Count Validation", True, details)
    else:
        logger.error("  ✗ Counts do not match!")
        report.add_check("SQLite → PostgreSQL Count Validation", False, details)


def validate_counts_vector(
    chroma_path: str,
    chroma_collection_name: str,
    postgres_url: str,
    pgvector_collection_name: str,
    report: ValidationReport
):
    """Validate vector counts between ChromaDB and pgvector."""
    logger.info("Validating vector counts (ChromaDB vs pgvector)...")

    # Read ChromaDB count
    try:
        client = chromadb.PersistentClient(path=chroma_path)
        collection = client.get_collection(name=chroma_collection_name)
        chroma_count = collection.count()
    except Exception as e:
        logger.error(f"Failed to read ChromaDB: {str(e)}")
        report.add_check("ChromaDB → pgvector Count Validation", False, f"Error: {str(e)}")
        return

    # Read pgvector count
    engine = create_engine(postgres_url)
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                f"SELECT COUNT(*) FROM langchain_pg_embedding e "
                f"JOIN langchain_pg_collection c ON e.collection_id = c.uuid "
                f"WHERE c.name = :collection_name"
            ), {'collection_name': pgvector_collection_name})
            pgvector_count = result.scalar()
    except Exception as e:
        logger.error(f"Failed to read pgvector: {str(e)}")
        report.add_check("ChromaDB → pgvector Count Validation", False, f"Error: {str(e)}")
        return

    details = f"""
**ChromaDB**: {chroma_count} vectors
**pgvector**: {pgvector_count} vectors
"""

    if chroma_count == pgvector_count:
        logger.info("  ✓ Vector counts match!")
        report.add_check("ChromaDB → pgvector Count Validation", True, details)
    else:
        logger.error("  ✗ Vector counts do not match!")
        report.add_check("ChromaDB → pgvector Count Validation", False, details)


def validate_sample_queries(
    chroma_path: str,
    chroma_collection_name: str,
    postgres_url: str,
    pgvector_collection_name: str,
    report: ValidationReport,
    similarity_threshold: float = 0.8
):
    """Validate search results with sample queries."""
    logger.info("Validating sample queries...")

    sample_queries = [
        "modern furniture",
        "outdoor activities",
        "food photography",
        "vintage items",
        "nature scenes"
    ]

    # Initialize ChromaDB
    client = chromadb.PersistentClient(path=chroma_path)
    chroma_collection = client.get_collection(name=chroma_collection_name)

    # Initialize pgvector
    voyage_api_key = os.getenv("VOYAGE_API_KEY")
    if not voyage_api_key:
        logger.error("VOYAGE_API_KEY not set")
        report.add_check("Sample Query Validation", False, "VOYAGE_API_KEY not set")
        return

    embedding_function = VoyageAIEmbeddings(
        voyage_api_key=voyage_api_key,
        model="voyage-3.5-lite"
    )

    pgvector_store = PGVector(
        embeddings=embedding_function,
        collection_name=pgvector_collection_name,
        connection=postgres_url,
        use_jsonb=True,
    )

    # Run queries
    results = []
    total_overlap = 0

    for query in sample_queries:
        # ChromaDB search
        chroma_results = chroma_collection.query(
            query_texts=[query],
            n_results=5,
            include=['metadatas']
        )
        chroma_ids = set(chroma_results['ids'][0]) if chroma_results['ids'] else set()

        # pgvector search
        pgvector_results = pgvector_store.similarity_search(query, k=5)
        pgvector_ids = set(doc.metadata.get('item_id', '') for doc in pgvector_results)

        # Calculate overlap
        overlap = len(chroma_ids & pgvector_ids)
        overlap_ratio = overlap / 5 if chroma_ids and pgvector_ids else 0

        results.append({
            'query': query,
            'overlap': overlap,
            'overlap_ratio': overlap_ratio,
            'chroma_ids': list(chroma_ids),
            'pgvector_ids': list(pgvector_ids)
        })

        total_overlap += overlap_ratio

    # Calculate average overlap
    avg_overlap = total_overlap / len(sample_queries) if sample_queries else 0

    # Generate details
    details = f"""
**Similarity Threshold**: {similarity_threshold:.1%}
**Average Overlap**: {avg_overlap:.1%}

"""
    for r in results:
        details += f"- **{r['query']}**: {r['overlap']}/5 overlap ({r['overlap_ratio']:.1%})\n"

    passed = avg_overlap >= similarity_threshold

    if passed:
        logger.info(f"  ✓ Average overlap {avg_overlap:.1%} >= threshold {similarity_threshold:.1%}")
        report.add_check("Sample Query Validation", True, details)
    else:
        logger.error(f"  ✗ Average overlap {avg_overlap:.1%} < threshold {similarity_threshold:.1%}")
        report.add_check("Sample Query Validation", False, details)


def validate_user_ids(postgres_url: str, user_id: str, report: ValidationReport):
    """Validate that all records have user_id set."""
    logger.info("Validating user_ids in PostgreSQL...")

    engine = create_engine(postgres_url)

    with engine.connect() as conn:
        # Check items
        result = conn.execute(text(
            "SELECT COUNT(*) FROM items WHERE user_id IS NULL OR user_id = ''"
        ))
        items_null = result.scalar()

        # Check analyses
        result = conn.execute(text(
            "SELECT COUNT(*) FROM analyses WHERE user_id IS NULL OR user_id = ''"
        ))
        analyses_null = result.scalar()

        # Check embeddings
        result = conn.execute(text(
            "SELECT COUNT(*) FROM embeddings WHERE user_id IS NULL OR user_id = ''"
        ))
        embeddings_null = result.scalar()

    details = f"""
**Expected user_id**: `{user_id}`

**NULL/Empty user_id counts**:
- Items: {items_null}
- Analyses: {analyses_null}
- Embeddings: {embeddings_null}
"""

    passed = items_null == 0 and analyses_null == 0 and embeddings_null == 0

    if passed:
        logger.info("  ✓ No NULL user_ids found")
        report.add_check("User ID Validation", True, details)
    else:
        logger.error("  ✗ Found NULL user_ids!")
        report.add_check("User ID Validation", False, details)


def validate_jsonb_structure(postgres_url: str, report: ValidationReport):
    """Validate JSONB structure in PostgreSQL."""
    logger.info("Validating JSONB structure...")

    engine = create_engine(postgres_url)

    with engine.connect() as conn:
        # Check analyses.raw_response JSONB
        result = conn.execute(text("""
            SELECT COUNT(*) FROM analyses
            WHERE raw_response IS NOT NULL
            AND jsonb_typeof(raw_response) = 'object'
        """))
        valid_analyses = result.scalar()

        result = conn.execute(text("SELECT COUNT(*) FROM analyses WHERE raw_response IS NOT NULL"))
        total_analyses = result.scalar()

        # Check embeddings.embedding_source JSONB
        result = conn.execute(text("""
            SELECT COUNT(*) FROM embeddings
            WHERE embedding_source IS NOT NULL
            AND jsonb_typeof(embedding_source) = 'object'
        """))
        valid_embeddings = result.scalar()

        result = conn.execute(text("SELECT COUNT(*) FROM embeddings WHERE embedding_source IS NOT NULL"))
        total_embeddings = result.scalar()

    details = f"""
**Analyses raw_response**:
- Valid JSONB: {valid_analyses}/{total_analyses}

**Embeddings embedding_source**:
- Valid JSONB: {valid_embeddings}/{total_embeddings}
"""

    passed = (valid_analyses == total_analyses) and (valid_embeddings == total_embeddings)

    if passed:
        logger.info("  ✓ All JSONB structures valid")
        report.add_check("JSONB Structure Validation", True, details)
    else:
        logger.error("  ✗ Invalid JSONB structures found")
        report.add_check("JSONB Structure Validation", False, details)


def benchmark_search_performance(
    postgres_url: str,
    pgvector_collection_name: str,
    report: ValidationReport
):
    """Benchmark search performance."""
    logger.info("Benchmarking search performance...")

    voyage_api_key = os.getenv("VOYAGE_API_KEY")
    if not voyage_api_key:
        logger.error("VOYAGE_API_KEY not set, skipping benchmark")
        report.add_check("Search Performance Benchmark", False, "VOYAGE_API_KEY not set")
        return

    embedding_function = VoyageAIEmbeddings(
        voyage_api_key=voyage_api_key,
        model="voyage-3.5-lite"
    )

    pgvector_store = PGVector(
        embeddings=embedding_function,
        collection_name=pgvector_collection_name,
        connection=postgres_url,
        use_jsonb=True,
    )

    # Run benchmark queries
    test_queries = [
        "modern furniture",
        "food photography",
        "nature scenes"
    ]

    latencies = []

    for query in test_queries:
        start = time.time()
        pgvector_store.similarity_search(query, k=10)
        latency = (time.time() - start) * 1000  # Convert to ms
        latencies.append(latency)

    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    max_latency = max(latencies) if latencies else 0
    min_latency = min(latencies) if latencies else 0

    details = f"""
**Queries tested**: {len(test_queries)}
**Average latency**: {avg_latency:.2f} ms
**Min latency**: {min_latency:.2f} ms
**Max latency**: {max_latency:.2f} ms

Individual query latencies:
"""
    for query, latency in zip(test_queries, latencies):
        details += f"- {query}: {latency:.2f} ms\n"

    # Consider passing if average latency < 1000ms (1 second)
    passed = avg_latency < 1000

    if passed:
        logger.info(f"  ✓ Average latency {avg_latency:.2f} ms < 1000 ms")
        report.add_check("Search Performance Benchmark", True, details)
    else:
        logger.warning(f"  ⚠ Average latency {avg_latency:.2f} ms >= 1000 ms")
        report.add_check("Search Performance Benchmark", False, details)


def main():
    """Main validation orchestrator."""
    parser = argparse.ArgumentParser(
        description="Validate data migration from SQLite/ChromaDB to PostgreSQL/pgvector"
    )
    parser.add_argument('--sqlite-db', required=True, help='SQLite database path')
    parser.add_argument('--postgres-url', required=True, help='PostgreSQL connection URL')
    parser.add_argument('--chroma-path', required=True, help='ChromaDB persistent directory')
    parser.add_argument('--chroma-collection', required=True, help='ChromaDB collection name')
    parser.add_argument('--pgvector-collection', default='collections_vectors', help='pgvector collection name')
    parser.add_argument('--user-id', required=True, help='Expected Cognito user ID')
    parser.add_argument('--report-output', default='validation_report.md', help='Output markdown report path')
    parser.add_argument('--similarity-threshold', type=float, default=0.8, help='Query similarity threshold')

    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("Migration Validation")
    logger.info("=" * 70)

    # Initialize report
    report = ValidationReport()

    try:
        # Run all validation checks
        validate_counts_postgres(args.sqlite_db, args.postgres_url, report)
        validate_counts_vector(
            args.chroma_path,
            args.chroma_collection,
            args.postgres_url,
            args.pgvector_collection,
            report
        )
        validate_sample_queries(
            args.chroma_path,
            args.chroma_collection,
            args.postgres_url,
            args.pgvector_collection,
            report,
            args.similarity_threshold
        )
        validate_user_ids(args.postgres_url, args.user_id, report)
        validate_jsonb_structure(args.postgres_url, report)
        benchmark_search_performance(args.postgres_url, args.pgvector_collection, report)

        # Generate markdown report
        markdown = report.generate_markdown()

        # Write report
        with open(args.report_output, 'w') as f:
            f.write(markdown)

        logger.info(f"\nReport written to: {args.report_output}")

        # Print summary
        logger.info("=" * 70)
        logger.info(f"Validation Summary: {report.passed_count()}/{len(report.checks)} checks passed")
        logger.info("=" * 70)

        if report.failed_count() == 0:
            logger.info("✓ All validation checks passed!")
            sys.exit(0)
        else:
            logger.error(f"✗ {report.failed_count()} validation checks failed!")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Validation failed: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
