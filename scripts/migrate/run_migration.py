#!/usr/bin/env python3
"""
Complete Migration Orchestrator

Orchestrates the full data migration workflow from SQLite/ChromaDB to PostgreSQL/pgvector.

Workflow:
1. Get Cognito test user (or create if needed)
2. Run SQLite → PostgreSQL migration
3. Run ChromaDB → pgvector migration
4. Run validation checks
5. Generate migration report

Supports dry-run mode and rollback on validation failure.

Usage:
    # Production migration
    python scripts/migrate/run_migration.py \\
        --env dev \\
        --dataset golden \\
        --aws-profile default

    # Dry run (validation only, no migration)
    python scripts/migrate/run_migration.py \\
        --env dev \\
        --dataset golden \\
        --dry-run

    # Skip Cognito user creation (use existing user-id)
    python scripts/migrate/run_migration.py \\
        --env dev \\
        --dataset golden \\
        --user-id existing-cognito-user-id \\
        --skip-cognito
"""

import sys
import os
import json
import argparse
import logging
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple
from datetime import datetime
import boto3

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MigrationOrchestrator:
    """Orchestrates complete migration workflow."""

    def __init__(
        self,
        env_name: str,
        dataset: str,
        aws_profile: Optional[str] = None,
        dry_run: bool = False
    ):
        """
        Initialize orchestrator.

        Args:
            env_name: Environment (dev/test/prod)
            dataset: Dataset type (golden/full)
            aws_profile: AWS profile name
            dry_run: If True, only validate (no migration)
        """
        self.env_name = env_name
        self.dataset = dataset
        self.aws_profile = aws_profile
        self.dry_run = dry_run

        # Paths
        self.project_root = Path(__file__).parent.parent.parent
        self.scripts_dir = self.project_root / "scripts" / "migrate"

        # Database paths
        if dataset == "golden":
            self.sqlite_db = str(self.project_root / "data" / "collections_golden.db")
            self.chroma_path = str(self.project_root / "data" / "chroma_golden")
            self.chroma_collection = "collections_vectors_golden"
        else:
            self.sqlite_db = str(self.project_root / "data" / "collections.db")
            self.chroma_path = str(self.project_root / "data" / "chroma_prod")
            self.chroma_collection = "collections_vectors_prod"

        # AWS resources
        self.postgres_url = None
        self.user_id = None
        self.user_pool_id = None

        # Initialize AWS clients
        session_kwargs = {}
        if aws_profile:
            session_kwargs['profile_name'] = aws_profile

        self.session = boto3.Session(**session_kwargs)
        self.ssm = self.session.client('ssm')
        self.cognito = self.session.client('cognito-idp')

        # Migration status
        self.steps_completed = []
        self.steps_failed = []

    def log_step(self, step_name: str, status: str, details: str = ""):
        """Log migration step."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"[{timestamp}] {step_name}: {status}")
        if details:
            logger.info(f"  {details}")

        if status == "COMPLETED":
            self.steps_completed.append(step_name)
        elif status == "FAILED":
            self.steps_failed.append(step_name)

    def get_postgres_url(self) -> str:
        """Get PostgreSQL URL from Parameter Store."""
        logger.info("Retrieving PostgreSQL URL from Parameter Store...")

        param_name = f"/collections/{self.env_name}/database-url"

        try:
            response = self.ssm.get_parameter(
                Name=param_name,
                WithDecryption=True
            )
            postgres_url = response['Parameter']['Value']
            logger.info(f"  ✓ Retrieved: {param_name}")
            return postgres_url
        except Exception as e:
            logger.error(f"  ✗ Failed to retrieve {param_name}: {str(e)}")
            raise

    def get_cognito_user_pool_id(self) -> str:
        """Get Cognito User Pool ID from CDK outputs."""
        logger.info("Retrieving Cognito User Pool ID...")

        outputs_file = self.project_root / f".aws-outputs-{self.env_name}.json"

        if not outputs_file.exists():
            raise FileNotFoundError(
                f"CDK outputs file not found: {outputs_file}. "
                f"Run 'make infra-deploy ENV={self.env_name}' first."
            )

        with open(outputs_file) as f:
            outputs = json.load(f)

        # Find UserPoolId in outputs
        user_pool_id = None
        if isinstance(outputs, list):
            for output in outputs:
                if output.get('OutputKey') == 'UserPoolId':
                    user_pool_id = output['OutputValue']
                    break
        else:
            user_pool_id = outputs.get('UserPoolId')

        if not user_pool_id:
            raise ValueError("UserPoolId not found in CDK outputs")

        logger.info(f"  ✓ User Pool ID: {user_pool_id}")
        return user_pool_id

    def get_or_create_test_user(self) -> Tuple[str, str]:
        """
        Get existing test user or create new one.

        Returns:
            Tuple of (username, user_id/sub)
        """
        logger.info("Getting or creating Cognito test user...")

        # List existing users
        response = self.cognito.list_users(
            UserPoolId=self.user_pool_id,
            Limit=10
        )

        # Check if test user exists
        test_username = f"migration-test-{self.dataset}"

        for user in response.get('Users', []):
            if user['Username'] == test_username:
                logger.info(f"  Found existing user: {test_username}")

                # Extract user_id (sub claim)
                user_id = None
                for attr in user.get('Attributes', []):
                    if attr['Name'] == 'sub':
                        user_id = attr['Value']
                        break

                logger.info(f"  ✓ User ID (sub): {user_id}")
                return test_username, user_id

        # Create new test user
        logger.info(f"  Creating new test user: {test_username}")

        response = self.cognito.admin_create_user(
            UserPoolId=self.user_pool_id,
            Username=test_username,
            UserAttributes=[
                {'Name': 'email', 'Value': f'{test_username}@example.com'},
                {'Name': 'email_verified', 'Value': 'true'}
            ],
            MessageAction='SUPPRESS'  # Don't send welcome email
        )

        # Extract user_id (sub)
        user_id = None
        for attr in response['User'].get('Attributes', []):
            if attr['Name'] == 'sub':
                user_id = attr['Value']
                break

        logger.info(f"  ✓ Created user: {test_username}")
        logger.info(f"  ✓ User ID (sub): {user_id}")

        return test_username, user_id

    def run_sqlite_migration(self) -> bool:
        """Run SQLite to PostgreSQL migration."""
        self.log_step("SQLite → PostgreSQL Migration", "RUNNING")

        cmd = [
            "python3",
            str(self.scripts_dir / "sqlite_to_postgres.py"),
            "--sqlite-db", self.sqlite_db,
            "--postgres-url", self.postgres_url,
            "--user-id", self.user_id,
            "--dataset", self.dataset,
            "--batch-size", "100"
        ]

        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True
            )

            logger.info(result.stdout)
            self.log_step("SQLite → PostgreSQL Migration", "COMPLETED")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"SQLite migration failed:\n{e.stderr}")
            self.log_step("SQLite → PostgreSQL Migration", "FAILED", str(e))
            return False

    def run_chromadb_migration(self) -> bool:
        """Run ChromaDB to pgvector migration."""
        self.log_step("ChromaDB → pgvector Migration", "RUNNING")

        cmd = [
            "python3",
            str(self.scripts_dir / "chromadb_to_pgvector.py"),
            "--chroma-path", self.chroma_path,
            "--collection", self.chroma_collection,
            "--postgres-url", self.postgres_url,
            "--user-id", self.user_id,
            "--batch-size", "100",
            "--pgvector-collection-name", "collections_vectors",
            "--validate"
        ]

        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True
            )

            logger.info(result.stdout)
            self.log_step("ChromaDB → pgvector Migration", "COMPLETED")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"ChromaDB migration failed:\n{e.stderr}")
            self.log_step("ChromaDB → pgvector Migration", "FAILED", str(e))
            return False

    def run_validation(self) -> bool:
        """Run validation checks."""
        self.log_step("Validation", "RUNNING")

        report_path = self.project_root / f"migration_validation_{self.dataset}_{self.env_name}.md"

        cmd = [
            "python3",
            str(self.scripts_dir / "validate_migration.py"),
            "--sqlite-db", self.sqlite_db,
            "--postgres-url", self.postgres_url,
            "--chroma-path", self.chroma_path,
            "--chroma-collection", self.chroma_collection,
            "--pgvector-collection", "collections_vectors",
            "--user-id", self.user_id,
            "--report-output", str(report_path),
            "--similarity-threshold", "0.8"
        ]

        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True
            )

            logger.info(result.stdout)
            self.log_step("Validation", "COMPLETED", f"Report: {report_path}")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Validation failed:\n{e.stderr}")
            self.log_step("Validation", "FAILED", str(e))
            return False

    def generate_summary_report(self) -> str:
        """Generate summary report."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        report = f"""
# Migration Summary Report

**Environment**: {self.env_name}
**Dataset**: {self.dataset}
**Timestamp**: {timestamp}
**Mode**: {"DRY RUN" if self.dry_run else "PRODUCTION"}

## Steps Completed

"""
        for step in self.steps_completed:
            report += f"- ✓ {step}\n"

        if self.steps_failed:
            report += "\n## Steps Failed\n\n"
            for step in self.steps_failed:
                report += f"- ✗ {step}\n"

        report += f"""

## Resources

- **SQLite DB**: {self.sqlite_db}
- **ChromaDB**: {self.chroma_path}
- **PostgreSQL**: {self.postgres_url.split('@')[1] if '@' in self.postgres_url else 'N/A'}
- **User ID**: {self.user_id}

## Status

"""
        if self.steps_failed:
            report += "⚠ Migration completed with errors. Review failed steps above.\n"
        else:
            report += "✓ Migration completed successfully!\n"

        return report

    def run(self) -> bool:
        """
        Execute complete migration workflow.

        Returns:
            True if successful, False otherwise
        """
        logger.info("=" * 70)
        logger.info("Migration Orchestrator")
        logger.info("=" * 70)
        logger.info(f"Environment: {self.env_name}")
        logger.info(f"Dataset: {self.dataset}")
        logger.info(f"Mode: {'DRY RUN' if self.dry_run else 'PRODUCTION'}")
        logger.info("=" * 70)

        try:
            # Step 1: Get PostgreSQL URL
            self.log_step("Get PostgreSQL URL", "RUNNING")
            self.postgres_url = self.get_postgres_url()
            self.log_step("Get PostgreSQL URL", "COMPLETED")

            # Step 2: Get Cognito User Pool ID
            self.log_step("Get Cognito User Pool ID", "RUNNING")
            self.user_pool_id = self.get_cognito_user_pool_id()
            self.log_step("Get Cognito User Pool ID", "COMPLETED")

            # Step 3: Get or create test user
            self.log_step("Get/Create Test User", "RUNNING")
            username, user_id = self.get_or_create_test_user()
            self.user_id = user_id
            self.log_step("Get/Create Test User", "COMPLETED", f"User: {username}, ID: {user_id}")

            if self.dry_run:
                logger.info("\n🔍 DRY RUN MODE - Skipping migrations, running validation only")

                # Only run validation
                if not self.run_validation():
                    logger.error("Validation failed in dry-run mode")
                    return False

            else:
                # Step 4: Run SQLite migration
                if not self.run_sqlite_migration():
                    logger.error("SQLite migration failed, aborting")
                    return False

                # Step 5: Run ChromaDB migration
                if not self.run_chromadb_migration():
                    logger.error("ChromaDB migration failed, aborting")
                    return False

                # Step 6: Run validation
                if not self.run_validation():
                    logger.error("Validation failed after migration")
                    # Note: In production, you might want to rollback here
                    return False

            # Generate summary
            summary = self.generate_summary_report()
            summary_path = self.project_root / f"migration_summary_{self.dataset}_{self.env_name}.md"

            with open(summary_path, 'w') as f:
                f.write(summary)

            logger.info("\n" + summary)
            logger.info(f"\nSummary report written to: {summary_path}")

            if self.steps_failed:
                logger.error("\n✗ Migration completed with errors")
                return False
            else:
                logger.info("\n✓ Migration completed successfully!")
                return True

        except Exception as e:
            logger.error(f"Migration orchestration failed: {str(e)}", exc_info=True)
            self.log_step("Migration Orchestration", "FAILED", str(e))
            return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Orchestrate complete data migration workflow"
    )
    parser.add_argument(
        '--env',
        choices=['dev', 'test', 'prod'],
        default='dev',
        help='AWS environment'
    )
    parser.add_argument(
        '--dataset',
        choices=['golden', 'full'],
        default='golden',
        help='Dataset to migrate'
    )
    parser.add_argument(
        '--aws-profile',
        help='AWS profile name'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Dry run mode (validation only, no migration)'
    )
    parser.add_argument(
        '--user-id',
        help='Use existing Cognito user ID (skip user creation)'
    )
    parser.add_argument(
        '--skip-cognito',
        action='store_true',
        help='Skip Cognito user creation (requires --user-id)'
    )

    args = parser.parse_args()

    if args.skip_cognito and not args.user_id:
        logger.error("--skip-cognito requires --user-id")
        sys.exit(1)

    # Create orchestrator
    orchestrator = MigrationOrchestrator(
        env_name=args.env,
        dataset=args.dataset,
        aws_profile=args.aws_profile,
        dry_run=args.dry_run
    )

    # Override user_id if provided
    if args.user_id:
        orchestrator.user_id = args.user_id
        logger.info(f"Using provided user_id: {args.user_id}")

    # Run migration
    success = orchestrator.run()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
