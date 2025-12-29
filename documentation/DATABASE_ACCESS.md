# Database Access

This guide explains how to connect to the RDS PostgreSQL database securely from any location, including GitHub Codespaces.

## Overview

The database runs in a private VPC and is accessed through a bastion host using AWS SSM Session Manager. This approach:

- Requires no IP whitelisting (works from changing IPs like Codespaces)
- Uses IAM credentials for authentication
- Creates an encrypted tunnel
- Provides audit trail via CloudTrail

## Prerequisites

1. **AWS CLI** configured with appropriate credentials
2. **AWS Session Manager Plugin** installed
3. **IAM permissions** for `ssm:StartSession`

### Install Session Manager Plugin

**Linux / GitHub Codespaces:**
```bash
curl "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb" -o session-manager-plugin.deb
sudo dpkg -i session-manager-plugin.deb
rm session-manager-plugin.deb
```

**macOS:**
```bash
brew install --cask session-manager-plugin
```

**Windows:**
Download from [AWS Session Manager Plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)

## Quick Start

### Using the Helper Script

The easiest way to connect:

```bash
# Connect to dev environment
python scripts/db_tunnel.py

# Connect to prod environment
python scripts/db_tunnel.py --env prod

# Use a custom local port
python scripts/db_tunnel.py --local-port 5433
```

The script will:
1. Fetch the bastion and RDS details from CloudFormation
2. Start the SSM tunnel
3. Print connection instructions

### Manual Connection

If you prefer to connect manually:

```bash
# Get the bastion instance ID and RDS endpoint from CloudFormation outputs
BASTION_ID=$(aws cloudformation describe-stacks \
  --stack-name collections-dev-database \
  --query "Stacks[0].Outputs[?OutputKey=='BastionInstanceId'].OutputValue" \
  --output text)

RDS_ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name collections-dev-database \
  --query "Stacks[0].Outputs[?OutputKey=='RDSEndpoint'].OutputValue" \
  --output text)

# Start the tunnel
aws ssm start-session \
  --target $BASTION_ID \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "{\"host\":[\"$RDS_ENDPOINT\"],\"portNumber\":[\"5432\"],\"localPortNumber\":[\"5432\"]}"
```

## Connecting to the Database

Once the tunnel is running, connect in another terminal:

### Using psql
```bash
psql -h localhost -p 5432 -U postgres -d collections
```

### Using Python
```python
import os
os.environ["DATABASE_URL"] = "postgresql://postgres:<password>@localhost:5432/collections"

from sqlalchemy import create_engine
engine = create_engine(os.environ["DATABASE_URL"])
```

### Getting the Password

The database password is stored in AWS Secrets Manager:

```bash
# Get the secret ARN
SECRET_ARN=$(aws cloudformation describe-stacks \
  --stack-name collections-dev-database \
  --query "Stacks[0].Outputs[?OutputKey=='DatabaseSecretArn'].OutputValue" \
  --output text)

# Get the password
aws secretsmanager get-secret-value \
  --secret-id $SECRET_ARN \
  --query 'SecretString' \
  --output text | jq -r '.password'
```

## Troubleshooting

### "Session Manager plugin not installed"

Install the plugin as described in [Prerequisites](#install-session-manager-plugin).

### "Target is not connected"

The bastion instance may not be running. Check in the EC2 console that:
1. The instance is in "running" state
2. The SSM agent is reporting as "Online" in Systems Manager > Fleet Manager

### "Access Denied"

Ensure your IAM user/role has the following permissions:
- `ssm:StartSession`
- `ssm:TerminateSession`
- `ec2:DescribeInstances`

### Connection times out

1. Check that the RDS security group allows access from the bastion security group
2. Verify the RDS instance is running
3. Check that port 5432 is correct

## Architecture

```
┌─────────────────────┐
│  GitHub Codespace   │
│  or Local Machine   │
└──────────┬──────────┘
           │ SSM Session (encrypted)
           │ IAM Auth
           ▼
┌─────────────────────┐
│   Bastion Host      │
│   (t4g.nano)        │
│   SSM Agent         │
└──────────┬──────────┘
           │ VPC Internal
           │ Port 5432
           ▼
┌─────────────────────┐
│   RDS PostgreSQL    │
│   with pgvector     │
└─────────────────────┘
```

## Cost

The bastion host is a minimal `t4g.nano` instance:
- ~$3/month for the instance
- No data transfer costs for SSM (uses HTTPS outbound)
- No additional VPC costs (uses existing public subnets)
