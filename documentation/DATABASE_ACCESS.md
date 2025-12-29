# Database Access

This guide explains how to connect to the RDS PostgreSQL database securely from any location, including GitHub Codespaces.

## Overview

The database runs in a private VPC and is accessed through a bastion host using AWS SSM Session Manager. This approach:

- Requires no IP whitelisting (works from changing IPs like Codespaces)
- Uses IAM credentials for authentication
- Creates an encrypted tunnel
- Provides audit trail via CloudTrail

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

### Bastion Host Details

The bastion host is a minimal EC2 instance that acts as a secure jump point:

| Property | Value |
|----------|-------|
| Instance Type | t4g.nano (ARM64) |
| OS | Amazon Linux 2023 |
| Monthly Cost | ~$3 |
| Access Method | SSM Session Manager (no SSH) |
| Inbound Ports | None (SSM uses outbound HTTPS) |

### Security Model

1. **No public access**: The bastion has no inbound security group rules
2. **IAM authentication**: Access controlled via IAM policies, not SSH keys
3. **Encrypted tunnel**: SSM sessions are encrypted end-to-end
4. **Audit logging**: All sessions logged to CloudTrail
5. **IMDSv2 required**: Instance metadata service hardened

---

## Deployment

### Prerequisites

1. AWS CLI configured with credentials that have CDK deployment permissions
2. AWS CDK installed (`npm install -g aws-cdk`)
3. Python environment with project dependencies

### Deploy the Infrastructure

```bash
# Navigate to infrastructure directory
cd infrastructure

# Deploy all stacks (includes bastion host)
cdk deploy --all

# Or deploy just the database stack
cdk deploy collections-dev-database
```

### Verify Deployment

After deployment, verify the bastion host is running:

```bash
# Check CloudFormation outputs
aws cloudformation describe-stacks \
  --stack-name CollectionsDB-dev \
  --query "Stacks[0].Outputs" \
  --output table


# Verify bastion is online in SSM
aws ssm describe-instance-information \
  --filters "Key=ResourceType,Values=EC2Instance" \
  --query "InstanceInformationList[*].[InstanceId,PingStatus]" \
  --output table
```

Expected outputs:
- `BastionInstanceId`: The EC2 instance ID (e.g., `i-0abc123def456`)
- `RDSEndpoint`: The RDS hostname
- `DatabaseSecretArn`: The Secrets Manager ARN for credentials

---

## Post-Deployment Setup

### 1. Install Session Manager Plugin

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

### 2. Configure IAM Permissions

Ensure your IAM user/role has these permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ssm:StartSession",
        "ssm:TerminateSession",
        "ssm:ResumeSession",
        "ssm:DescribeSessions",
        "ssm:GetConnectionStatus"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "cloudformation:DescribeStacks"
      ],
      "Resource": "arn:aws:cloudformation:*:*:stack/collections-*/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:*:*:secret:collections-db-*"
    }
  ]
}
```

### 3. Get Database Password

Retrieve the auto-generated password from Secrets Manager:

```bash
  # Get the secret ARN (corrected stack name)
  SECRET_ARN=$(aws cloudformation describe-stacks \
    --stack-name CollectionsDB-dev \
    --query "Stacks[0].Outputs[?OutputKey=='DatabaseSecretArn'].OutputValue" \
    --output text)

  # Get the password
  aws secretsmanager get-secret-value \
    --secret-id "$SECRET_ARN" \
    --query 'SecretString' \
    --output text | jq -r '.password'
```

Save this password securely - you'll need it to connect.

---

## Connecting to the Database

### Using the Helper Script (Recommended)

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

### Connect via psql

Once the tunnel is running, open another terminal:

```bash
psql -h localhost -p 5432 -U postgres -d collections
```
access wrd: d9zqRRf1pcgiHUAV6.HUvGdaWppqiH
### Connect via Python

```python
import os
os.environ["DATABASE_URL"] = "postgresql://postgres:d9zqRRf1pcgiHUAV6.HUvGdaWppqiH@localhost:5432/collections"

from sqlalchemy import create_engine
engine = create_engine(os.environ["DATABASE_URL"])
```

---

## Troubleshooting

### "Session Manager plugin not installed"

Install the plugin as described in [Post-Deployment Setup](#1-install-session-manager-plugin).

### "Target is not connected"

The bastion instance may not be running or SSM agent not ready:

1. Check the instance is running:
   ```bash
   aws ec2 describe-instances \
     --instance-ids <bastion-id> \
     --query "Reservations[0].Instances[0].State.Name"
   ```

2. Check SSM agent status:
   ```bash
   aws ssm describe-instance-information \
     --filters "Key=InstanceIds,Values=<bastion-id>" \
     --query "InstanceInformationList[0].PingStatus"
   ```

   Should return `"Online"`. If not, the instance may need a few minutes after launch.

3. Start the instance if stopped:
   ```bash
   aws ec2 start-instances --instance-ids <bastion-id>
   ```

### "Access Denied"

Ensure your IAM user/role has the required permissions (see [Configure IAM Permissions](#2-configure-iam-permissions)).

### Connection times out

1. Verify the tunnel is still running (check the terminal where you started it)
2. Check RDS security group allows access from bastion security group
3. Verify RDS instance is running:
   ```bash
   aws rds describe-db-instances \
     --query "DBInstances[?DBInstanceIdentifier=='collections-dev'].DBInstanceStatus"
   ```

### "psql: could not connect to server: Connection refused"

The tunnel isn't running or is using a different port. Check:
1. The tunnel terminal shows "Waiting for connections..."
2. You're using the correct local port (default: 5432)

---

## Cost

The bastion host is a minimal `t4g.nano` instance:

| Component | Cost |
|-----------|------|
| EC2 t4g.nano | ~$3/month |
| SSM data transfer | Free (uses HTTPS outbound) |
| VPC | No additional cost (uses existing subnets) |

**Tip**: Stop the bastion when not in use to save costs:
```bash
# Stop
aws ec2 stop-instances --instance-ids <bastion-id>

# Start when needed
aws ec2 start-instances --instance-ids <bastion-id>
```
