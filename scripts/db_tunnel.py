#!/usr/bin/env python3
"""
Database tunnel script using AWS SSM Session Manager.

This script creates a secure tunnel to the RDS database through the bastion host,
allowing database access from anywhere (including GitHub Codespaces) without
IP whitelisting.

Usage:
    python scripts/db_tunnel.py                    # Start tunnel (default: dev)
    python scripts/db_tunnel.py --env prod         # Start tunnel for prod
    python scripts/db_tunnel.py --local-port 5433  # Use custom local port

Requirements:
    - AWS CLI configured with appropriate credentials
    - AWS Session Manager plugin installed
    - IAM permissions for ssm:StartSession

Install Session Manager plugin (Linux/Codespaces):
    curl "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb" -o session-manager-plugin.deb
    sudo dpkg -i session-manager-plugin.deb
"""

import argparse
import json
import subprocess
import sys

import boto3
from botocore.exceptions import ClientError


def get_stack_outputs(env_name: str) -> dict:
    """Get CloudFormation stack outputs for the database stack."""
    cf_client = boto3.client("cloudformation")
    stack_name = f"CollectionsDB-{env_name}"

    try:
        response = cf_client.describe_stacks(StackName=stack_name)
        outputs = {}
        for output in response["Stacks"][0].get("Outputs", []):
            outputs[output["OutputKey"]] = output["OutputValue"]
        return outputs
    except ClientError as e:
        print(f"Error: Could not find stack '{stack_name}': {e}")
        sys.exit(1)


def check_ssm_plugin() -> bool:
    """Check if the AWS Session Manager plugin is installed."""
    try:
        subprocess.run(
            ["session-manager-plugin", "--version"],
            capture_output=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def start_tunnel(
    bastion_id: str, rds_endpoint: str, rds_port: str, local_port: int
) -> None:
    """Start the SSM port forwarding session."""
    print(f"Starting tunnel to {rds_endpoint}:{rds_port}")
    print(f"Local port: {local_port}")
    print(f"Bastion instance: {bastion_id}")
    print()
    print("=" * 60)
    print("Connection ready! Use these credentials in another terminal:")
    print("=" * 60)
    print(f"  Host:     localhost")
    print(f"  Port:     {local_port}")
    print(f"  Database: collections")
    print()
    print("Example:")
    print(f"  psql -h localhost -p {local_port} -U postgres -d collections")
    print()
    print("Or set DATABASE_URL:")
    print(f"  export DATABASE_URL='postgresql://postgres:<password>@localhost:{local_port}/collections'")
    print()
    print("Press Ctrl+C to close the tunnel.")
    print("=" * 60)

    parameters = {
        "host": [rds_endpoint],
        "portNumber": [rds_port],
        "localPortNumber": [str(local_port)],
    }

    try:
        subprocess.run(
            [
                "aws",
                "ssm",
                "start-session",
                "--target",
                bastion_id,
                "--document-name",
                "AWS-StartPortForwardingSessionToRemoteHost",
                "--parameters",
                json.dumps(parameters),
            ],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"Error: SSM session failed: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nTunnel closed.")


def main():
    parser = argparse.ArgumentParser(
        description="Create a secure tunnel to the RDS database via SSM"
    )
    parser.add_argument(
        "--env",
        choices=["dev", "test", "prod"],
        default="dev",
        help="Environment to connect to (default: dev)",
    )
    parser.add_argument(
        "--local-port",
        type=int,
        default=5432,
        help="Local port to forward (default: 5432)",
    )
    args = parser.parse_args()

    # Check for SSM plugin
    if not check_ssm_plugin():
        print("Error: AWS Session Manager plugin not installed.")
        print()
        print("Install it with:")
        print('  curl "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb" -o session-manager-plugin.deb')
        print("  sudo dpkg -i session-manager-plugin.deb")
        sys.exit(1)

    # Get stack outputs
    print(f"Fetching stack outputs for '{args.env}' environment...")
    outputs = get_stack_outputs(args.env)

    bastion_id = outputs.get("BastionInstanceId")
    rds_endpoint = outputs.get("RDSEndpoint")
    rds_port = outputs.get("RDSPort", "5432")

    if not bastion_id:
        print("Error: BastionInstanceId not found in stack outputs.")
        print("Make sure the database stack is deployed with the bastion host.")
        sys.exit(1)

    if not rds_endpoint:
        print("Error: RDSEndpoint not found in stack outputs.")
        sys.exit(1)

    # Start tunnel
    start_tunnel(bastion_id, rds_endpoint, rds_port, args.local_port)


if __name__ == "__main__":
    main()
