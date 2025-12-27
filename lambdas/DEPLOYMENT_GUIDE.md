# Lambda Deployment Guide

This guide explains how to deploy the event-driven Lambda functions to AWS.

## Prerequisites

1. AWS CDK installed and configured
2. AWS credentials configured
3. PostgreSQL database deployed (from Phase 3)
4. Required API keys available

## Step 1: Update CDK Compute Stack

Replace the inline placeholder code in `infrastructure/stacks/compute_stack.py` with references to the actual Lambda directories.

### Current Code (Placeholders)

The current implementation uses inline code:

```python
self.image_processor_lambda = lambda_.Function(
    self,
    "ImageProcessorLambda",
    runtime=lambda_.Runtime.PYTHON_3_12,
    handler="index.handler",
    code=lambda_.Code.from_inline("...placeholder...")
)
```

### Updated Code (Actual Implementations)

Update to reference the Lambda directories:

```python
import os

# Get path relative to infrastructure directory
lambda_base_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "lambdas")

# Image Processor Lambda
image_processor_path = os.path.join(lambda_base_path, "image_processor")
self.image_processor_lambda = lambda_.Function(
    self,
    "ImageProcessorLambda",
    runtime=lambda_.Runtime.PYTHON_3_12,
    handler="handler.handler",
    code=lambda_.Code.from_asset(image_processor_path),
    timeout=Duration.seconds(self.env_config["lambda_timeout_processor"]),
    memory_size=self.env_config["lambda_memory_processor"],
    environment=self.common_env,
    log_retention=self._get_log_retention(self.env_config["log_retention_days"]),
    description=f"Image processor Lambda - {self.env_name}",
)

# Analyzer Lambda
analyzer_path = os.path.join(lambda_base_path, "analyzer")
self.analyzer_lambda = lambda_.Function(
    self,
    "AnalyzerLambda",
    runtime=lambda_.Runtime.PYTHON_3_12,
    handler="handler.handler",
    code=lambda_.Code.from_asset(analyzer_path),
    timeout=Duration.seconds(self.env_config["lambda_timeout_analyzer"]),
    memory_size=self.env_config["lambda_memory_analyzer"],
    environment=self.common_env,
    log_retention=self._get_log_retention(self.env_config["log_retention_days"]),
    description=f"Image analyzer Lambda - {self.env_name}",
)

# Embedder Lambda
embedder_path = os.path.join(lambda_base_path, "embedder")
self.embedder_lambda = lambda_.Function(
    self,
    "EmbedderLambda",
    runtime=lambda_.Runtime.PYTHON_3_12,
    handler="handler.handler",
    code=lambda_.Code.from_asset(embedder_path),
    timeout=Duration.seconds(self.env_config["lambda_timeout_embedder"]),
    memory_size=self.env_config["lambda_memory_embedder"],
    environment=self.common_env,
    log_retention=self._get_log_retention(self.env_config["log_retention_days"]),
    description=f"Embedding generator Lambda - {self.env_name}",
)
```

## Step 2: Populate Parameter Store

Before deploying, populate AWS Systems Manager Parameter Store with required secrets.

### Required Parameters

```bash
# Database connection string
aws ssm put-parameter \
  --name "/collections/DATABASE_URL" \
  --value "postgresql://user:password@host:5432/collections" \
  --type "SecureString" \
  --overwrite

# Anthropic API key (for Analyzer)
aws ssm put-parameter \
  --name "/collections/ANTHROPIC_API_KEY" \
  --value "sk-ant-..." \
  --type "SecureString" \
  --overwrite

# OpenAI API key (optional, for Analyzer)
aws ssm put-parameter \
  --name "/collections/OPENAI_API_KEY" \
  --value "sk-..." \
  --type "SecureString" \
  --overwrite

# LangSmith API key (optional, for Analyzer tracing)
aws ssm put-parameter \
  --name "/collections/LANGSMITH_API_KEY" \
  --value "ls-..." \
  --type "SecureString" \
  --overwrite

# Voyage AI API key (for Embedder)
aws ssm put-parameter \
  --name "/collections/VOYAGE_API_KEY" \
  --value "pa-..." \
  --type "SecureString" \
  --overwrite
```

### Verify Parameters

```bash
# List all collections parameters
aws ssm describe-parameters \
  --parameter-filters "Key=Name,Values=/collections"

# Get parameter value (decrypted)
aws ssm get-parameter \
  --name "/collections/ANTHROPIC_API_KEY" \
  --with-decryption
```

## Step 3: Deploy Infrastructure

Deploy the compute stack with the Lambda functions:

```bash
# Navigate to infrastructure directory
cd infrastructure

# Install CDK dependencies
npm install

# Bootstrap CDK (if not already done)
cdk bootstrap

# Synthesize CloudFormation template
cdk synth CollectionsComputeStack-dev

# Deploy to dev environment
cdk deploy CollectionsComputeStack-dev

# For production
cdk deploy CollectionsComputeStack-prod
```

### Deploy Options

```bash
# Deploy without confirmation prompts
cdk deploy CollectionsComputeStack-dev --require-approval never

# Deploy with specific profile
cdk deploy CollectionsComputeStack-dev --profile my-aws-profile

# Deploy all stacks
cdk deploy --all
```

## Step 4: Verify Deployment

### Check Lambda Functions

```bash
# List Lambda functions
aws lambda list-functions --query "Functions[?starts_with(FunctionName, 'collections')].FunctionName"

# Get specific Lambda details
aws lambda get-function --function-name collections-dev-ImageProcessorLambda

# Check Lambda logs
aws logs tail /aws/lambda/collections-dev-ImageProcessorLambda --follow
```

### Check EventBridge Rules

```bash
# List EventBridge rules
aws events list-rules --name-prefix collections

# Get rule details
aws events describe-rule --name collections-dev-ImageProcessedRule
```

### Check S3 Bucket Notifications

```bash
# Get bucket notification configuration
aws s3api get-bucket-notification-configuration \
  --bucket collections-images-dev-123456789
```

## Step 5: Test End-to-End

### Upload Test Image

```bash
# Upload a test image to S3
aws s3 cp test-image.jpg s3://collections-images-dev-123456789/user123/test-image.jpg

# Monitor CloudWatch Logs for all Lambdas in real-time
aws logs tail /aws/lambda/collections-dev-ImageProcessorLambda --follow &
aws logs tail /aws/lambda/collections-dev-AnalyzerLambda --follow &
aws logs tail /aws/lambda/collections-dev-EmbedderLambda --follow &
```

### Expected Flow

1. **Image Processor** logs show:
   - S3 event received
   - Image downloaded
   - Thumbnail created
   - EventBridge event published

2. **Analyzer** logs show (30-60 seconds later):
   - EventBridge event received
   - Image downloaded
   - LLM analysis complete
   - Analysis stored in PostgreSQL
   - EventBridge event published

3. **Embedder** logs show (few seconds after analyzer):
   - EventBridge event received
   - Analysis fetched from database
   - Embedding generated
   - Embedding stored in pgvector

### Verify Database

Connect to PostgreSQL and verify data:

```sql
-- Check items
SELECT * FROM items WHERE id = 'test-image';

-- Check analyses
SELECT id, item_id, category, summary
FROM analyses
WHERE item_id = 'test-image';

-- Check embeddings
SELECT id, item_id, embedding_model, embedding_dimensions
FROM embeddings
WHERE item_id = 'test-image';
```

## Troubleshooting

### Lambda Not Triggered

**Check S3 Event Notification**:
```bash
aws s3api get-bucket-notification-configuration \
  --bucket collections-images-dev-123456789
```

**Check Lambda Permissions**:
```bash
aws lambda get-policy --function-name collections-dev-ImageProcessorLambda
```

### Lambda Fails with Timeout

**Check Lambda Configuration**:
```bash
aws lambda get-function-configuration \
  --function-name collections-dev-AnalyzerLambda
```

**Increase Timeout** (if needed):
```bash
aws lambda update-function-configuration \
  --function-name collections-dev-AnalyzerLambda \
  --timeout 600
```

### Parameter Store Access Denied

**Check Lambda IAM Role**:
```bash
aws iam get-role-policy \
  --role-name collections-dev-AnalyzerLambdaRole \
  --policy-name ParameterStorePolicy
```

**Verify Parameter Exists**:
```bash
aws ssm get-parameter --name /collections/ANTHROPIC_API_KEY
```

### Database Connection Failed

**Check Security Group**:
- Ensure Lambda has network access to RDS
- Verify RDS security group allows inbound from Lambda security group

**Check DATABASE_URL**:
```bash
# Get parameter value
aws ssm get-parameter \
  --name /collections/DATABASE_URL \
  --with-decryption \
  --query "Parameter.Value"
```

### EventBridge Not Triggering

**Check EventBridge Rules**:
```bash
# Verify rule is enabled
aws events describe-rule --name collections-dev-ImageProcessedRule

# Check rule targets
aws events list-targets-by-rule --rule collections-dev-ImageProcessedRule
```

**Test EventBridge Manually**:
```bash
aws events put-events --entries '[
  {
    "Source": "collections.imageprocessor",
    "DetailType": "ImageProcessed",
    "Detail": "{\"item_id\":\"test\",\"user_id\":\"user123\",\"bucket\":\"test\",\"original_key\":\"test.jpg\"}"
  }
]'
```

## Monitoring

### CloudWatch Dashboards

Create a dashboard to monitor Lambda metrics:

```bash
aws cloudwatch put-dashboard --dashboard-name collections-lambdas --dashboard-body file://dashboard.json
```

**dashboard.json**:
```json
{
  "widgets": [
    {
      "type": "metric",
      "properties": {
        "metrics": [
          ["AWS/Lambda", "Invocations", {"stat": "Sum"}],
          [".", "Errors", {"stat": "Sum"}],
          [".", "Duration", {"stat": "Average"}]
        ],
        "period": 300,
        "region": "us-east-1",
        "title": "Lambda Metrics"
      }
    }
  ]
}
```

### CloudWatch Alarms

Set up alarms for critical metrics:

```bash
# Alarm for errors
aws cloudwatch put-metric-alarm \
  --alarm-name collections-analyzer-errors \
  --alarm-description "Alert when Analyzer Lambda has errors" \
  --metric-name Errors \
  --namespace AWS/Lambda \
  --statistic Sum \
  --period 300 \
  --threshold 5 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 1
```

## Cost Optimization

### Lambda Memory Optimization

Test different memory configurations to find optimal cost/performance:

```bash
# Update memory (also affects CPU)
aws lambda update-function-configuration \
  --function-name collections-dev-AnalyzerLambda \
  --memory-size 2048
```

### S3 Lifecycle Rules

Automatically delete old thumbnails:

```bash
aws s3api put-bucket-lifecycle-configuration \
  --bucket collections-images-dev-123456789 \
  --lifecycle-configuration file://lifecycle.json
```

### Reserved Concurrency

Limit concurrent executions to control costs:

```bash
aws lambda put-function-concurrency \
  --function-name collections-dev-ImageProcessorLambda \
  --reserved-concurrent-executions 10
```

## Rollback

If deployment fails or issues occur:

```bash
# Rollback to previous stack version
cdk deploy CollectionsComputeStack-dev --rollback

# Or destroy and redeploy
cdk destroy CollectionsComputeStack-dev
cdk deploy CollectionsComputeStack-dev
```

## Next Steps

After successful deployment:

1. **Set up monitoring**: CloudWatch dashboards and alarms
2. **Configure DLQs**: Dead letter queues for failed events
3. **Enable X-Ray tracing**: Distributed tracing across Lambdas
4. **Implement CI/CD**: Automate Lambda deployments
5. **Load testing**: Test at scale with concurrent uploads
6. **Optimize costs**: Right-size Lambda memory and timeout
7. **Security audit**: Review IAM permissions and network access

## Additional Resources

- [AWS Lambda Documentation](https://docs.aws.amazon.com/lambda/)
- [AWS CDK Documentation](https://docs.aws.amazon.com/cdk/)
- [EventBridge Documentation](https://docs.aws.amazon.com/eventbridge/)
- [Parameter Store Documentation](https://docs.aws.amazon.com/systems-manager/latest/userguide/systems-manager-parameter-store.html)
