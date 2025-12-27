#!/usr/bin/env python3
"""
Populate AWS Parameter Store with secrets from .env.dev file.

This script reads secrets from .env.dev and uploads them to AWS Systems Manager
Parameter Store under the /collections/{environment}/ namespace.

Usage:
    python scripts/aws/populate_parameters.py --env dev
    python scripts/aws/populate_parameters.py --env dev --dry-run
"""

import os
import sys
import argparse
import boto3
from pathlib import Path
from dotenv import dotenv_values


# Parameter Store paths and their corresponding .env variable names
PARAMETER_MAPPINGS = {
    # API Keys
    "/collections/{env}/anthropic/api_key": "ANTHROPIC_API_KEY",
    "/collections/{env}/openai/api_key": "OPENAI_API_KEY",
    "/collections/{env}/voyage/api_key": "VOYAGE_API_KEY",
    "/collections/{env}/tavily/api_key": "TAVILY_API_KEY",
    "/collections/{env}/langsmith/api_key": "LANGSMITH_API_KEY",

    # Database Configuration
    "/collections/{env}/database/username": "DATABASE_USERNAME",
    "/collections/{env}/database/password": "DATABASE_PASSWORD",
    "/collections/{env}/database/name": "DATABASE_NAME",

    # Application Configuration
    "/collections/{env}/voyage/embedding_model": "VOYAGE_EMBEDDING_MODEL",
    "/collections/{env}/voyage/embedding_dimensions": "VOYAGE_EMBEDDING_DIMENSIONS",
    "/collections/{env}/langsmith/project": "LANGCHAIN_PROJECT",
    "/collections/{env}/checkpoint/ttl_hours": "CHECKPOINT_TTL_HOURS",
}


def load_env_file(env: str) -> dict:
    """Load environment variables from .env.{env} file."""
    env_file = Path(f".env.{env}")

    if not env_file.exists():
        print(f"❌ Error: {env_file} not found")
        sys.exit(1)

    print(f"📖 Loading secrets from {env_file}")
    return dotenv_values(env_file)


def populate_parameters(env: str, dry_run: bool = False):
    """
    Populate Parameter Store with secrets.

    Args:
        env: Environment name (dev, test, prod)
        dry_run: If True, only print what would be uploaded without actually uploading
    """
    # Load environment variables
    env_vars = load_env_file(env)

    # Initialize SSM client
    ssm = boto3.client('ssm')

    print(f"\n🚀 Populating Parameter Store for environment: {env}")
    print(f"{'=' * 60}")

    # Track statistics
    uploaded = 0
    skipped = 0
    errors = 0

    # Upload each parameter
    for param_path_template, env_var_name in PARAMETER_MAPPINGS.items():
        # Format parameter path with environment
        param_path = param_path_template.format(env=env)

        # Get value from env file
        value = env_vars.get(env_var_name)

        if not value or value in ["WILL_BE_SET_BY_CDK", ""]:
            print(f"⏭️  Skipping {param_path} (not set in .env.{env})")
            skipped += 1
            continue

        if dry_run:
            # Mask sensitive values in output
            display_value = value[:10] + "..." if len(value) > 10 else "***"
            print(f"🔍 [DRY RUN] Would upload: {param_path} = {display_value}")
            uploaded += 1
            continue

        try:
            # Determine if this is a sensitive parameter
            is_sensitive = any(keyword in param_path.lower() for keyword in [
                'api_key', 'password', 'secret'
            ])

            # Upload to Parameter Store
            ssm.put_parameter(
                Name=param_path,
                Value=value,
                Type='SecureString' if is_sensitive else 'String',
                Overwrite=True,
                Description=f"Auto-uploaded from .env.{env} for {env_var_name}"
            )

            # Mask sensitive values in output
            display_value = value[:10] + "..." if is_sensitive else value
            print(f"✅ Uploaded: {param_path} = {display_value}")
            uploaded += 1

        except Exception as e:
            print(f"❌ Error uploading {param_path}: {e}")
            errors += 1

    # Print summary
    print(f"\n{'=' * 60}")
    print(f"📊 Summary:")
    print(f"   ✅ Uploaded: {uploaded}")
    print(f"   ⏭️  Skipped: {skipped}")
    print(f"   ❌ Errors: {errors}")

    if dry_run:
        print(f"\n💡 This was a dry run. Use --no-dry-run to actually upload.")
    else:
        print(f"\n🎉 Parameter Store population complete!")

    return uploaded, skipped, errors


def verify_parameters(env: str):
    """Verify that all parameters were uploaded successfully."""
    ssm = boto3.client('ssm')

    print(f"\n🔍 Verifying uploaded parameters for environment: {env}")
    print(f"{'=' * 60}")

    for param_path_template in PARAMETER_MAPPINGS.keys():
        param_path = param_path_template.format(env=env)

        try:
            response = ssm.get_parameter(Name=param_path, WithDecryption=False)
            param_type = response['Parameter']['Type']
            print(f"✅ Found: {param_path} (Type: {param_type})")
        except ssm.exceptions.ParameterNotFound:
            print(f"❌ Missing: {param_path}")
        except Exception as e:
            print(f"⚠️  Error checking {param_path}: {e}")

    print(f"{'=' * 60}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Populate AWS Parameter Store with secrets from .env file"
    )
    parser.add_argument(
        "--env",
        default="dev",
        choices=["dev", "test", "prod"],
        help="Environment to populate (default: dev)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be uploaded without actually uploading"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify parameters after upload"
    )

    args = parser.parse_args()

    # Check AWS credentials
    try:
        sts = boto3.client('sts')
        identity = sts.get_caller_identity()
        print(f"🔑 AWS Account: {identity['Account']}")
        print(f"👤 AWS User: {identity['Arn']}")
    except Exception as e:
        print(f"❌ Error: AWS credentials not configured or invalid: {e}")
        sys.exit(1)

    # Populate parameters
    uploaded, skipped, errors = populate_parameters(args.env, args.dry_run)

    # Verify if requested
    if args.verify and not args.dry_run:
        verify_parameters(args.env)

    # Exit with error code if there were errors
    sys.exit(1 if errors > 0 else 0)


if __name__ == "__main__":
    main()
