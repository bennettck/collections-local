#!/usr/bin/env python3
"""
Sync API keys from .env file to AWS Parameter Store.

This script reads API keys from the .env file and updates AWS Systems Manager
Parameter Store with the current infrastructure naming scheme.

Usage:
    python scripts/sync_api_keys_to_aws.py
    python scripts/sync_api_keys_to_aws.py --dry-run
"""

import os
import sys
import argparse
import boto3
from pathlib import Path
from dotenv import load_dotenv


# Parameter mappings (AWS Parameter Store path → .env variable name)
PARAMETER_MAPPINGS = {
    "/collections/anthropic-api-key": "ANTHROPIC_API_KEY",
    "/collections/voyage-api-key": "VOYAGE_API_KEY",
    "/collections/tavily-api-key": "TAVILY_API_KEY",
    "/collections/langsmith-api-key": "LANGSMITH_API_KEY",
}


def sync_parameters(dry_run: bool = False, region: str = "us-east-1"):
    """
    Sync API keys from .env to Parameter Store.

    Args:
        dry_run: If True, only print what would be updated without actually updating
        region: AWS region (default: us-east-1)
    """
    # Load .env file
    env_file = Path(".env")
    if not env_file.exists():
        print(f"❌ Error: {env_file} not found")
        print("Please create a .env file with your API keys")
        sys.exit(1)

    print(f"📖 Loading API keys from {env_file}")
    load_dotenv()

    # Initialize SSM client
    ssm = boto3.client('ssm', region_name=region)

    print(f"\n🚀 Syncing API keys to AWS Parameter Store")
    print(f"Region: {region}")
    print(f"{'=' * 70}")

    # Track statistics
    updated = 0
    skipped = 0
    errors = 0

    # Update each parameter
    for param_path, env_var_name in PARAMETER_MAPPINGS.items():
        # Get value from environment
        value = os.getenv(env_var_name)

        if not value or value in ["PLACEHOLDER", ""]:
            print(f"⏭️  Skipping {param_path} (not set in .env)")
            skipped += 1
            continue

        # Mask value for display (show first 10 chars)
        display_value = value[:10] + "..." if len(value) > 10 else "***"

        if dry_run:
            print(f"🔍 [DRY RUN] Would update: {param_path}")
            print(f"   Value: {display_value}")
            updated += 1
            continue

        try:
            # Update Parameter Store
            ssm.put_parameter(
                Name=param_path,
                Value=value,
                Type='SecureString',
                Overwrite=True,
                Description=f"{env_var_name} for Collections Local API"
            )

            print(f"✅ Updated: {param_path}")
            print(f"   Value: {display_value}")
            updated += 1

        except Exception as e:
            print(f"❌ Error updating {param_path}: {e}")
            errors += 1

    # Print summary
    print(f"\n{'=' * 70}")
    print(f"📊 Summary:")
    print(f"   ✅ Updated: {updated}")
    print(f"   ⏭️  Skipped: {skipped}")
    print(f"   ❌ Errors: {errors}")

    if dry_run:
        print(f"\n💡 This was a dry run. Run without --dry-run to actually update.")
    elif updated > 0:
        print(f"\n🎉 API keys synced successfully!")
        print(f"\nℹ️  Note: Lambda functions may need to be redeployed or restarted")
        print(f"   to pick up the new parameter values.")

    return updated, skipped, errors


def verify_parameters(region: str = "us-east-1"):
    """Verify that all parameters are set correctly."""
    ssm = boto3.client('ssm', region_name=region)

    print(f"\n🔍 Verifying Parameter Store values")
    print(f"{'=' * 70}")

    all_good = True

    for param_path, env_var_name in PARAMETER_MAPPINGS.items():
        try:
            response = ssm.get_parameter(Name=param_path, WithDecryption=True)
            value = response['Parameter']['Value']
            param_type = response['Parameter']['Type']

            if value == "PLACEHOLDER":
                print(f"⚠️  {param_path}: Still set to PLACEHOLDER")
                all_good = False
            else:
                # Mask the value
                display_value = value[:10] + "..." if len(value) > 10 else "***"
                print(f"✅ {param_path}: {display_value} (Type: {param_type})")

        except ssm.exceptions.ParameterNotFound:
            print(f"❌ {param_path}: NOT FOUND")
            all_good = False
        except Exception as e:
            print(f"⚠️  {param_path}: Error - {e}")
            all_good = False

    print(f"{'=' * 70}")

    if all_good:
        print("✅ All API keys are properly configured!")
    else:
        print("⚠️  Some API keys need attention")

    return all_good


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Sync API keys from .env to AWS Parameter Store"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be updated without actually updating"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify parameters after sync"
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region (default: us-east-1)"
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

    # Sync parameters
    updated, skipped, errors = sync_parameters(args.dry_run, args.region)

    # Verify if requested
    if args.verify:
        verify_parameters(args.region)

    # Exit with error code if there were errors
    sys.exit(1 if errors > 0 else 0)


if __name__ == "__main__":
    main()
