# Integration Tests

Integration tests for AWS migration phases. These tests use **real AWS resources** (not mocks) to validate the infrastructure and implementation.

## Prerequisites

1. **AWS Infrastructure Deployed**: Run `make infra-deploy` to deploy the CDK stack
2. **AWS Credentials Configured**: Ensure AWS credentials are set up in your environment
3. **Stack Outputs Available**: The `.aws-outputs-{env}.json` file must exist in the project root
4. **Dependencies Installed**: Run `pip install -r requirements.txt`

## Test Structure

```
tests/integration/
├── conftest.py                 # Shared pytest fixtures
├── test_chat_workflow.py       # Phase 3: LangGraph conversation tests
├── test_database.py            # Phase 2: Database layer tests (to be created)
├── test_api_endpoints.py       # Phase 4: API endpoint tests (to be created)
└── test_event_workflow.py      # Phase 4: Event-driven workflow tests (to be created)
```

## Running Tests

### Run All Integration Tests
```bash
pytest tests/integration/ -v
```

### Run Specific Test File
```bash
# Phase 3: Chat workflow tests
pytest tests/integration/test_chat_workflow.py -v

# Show detailed output
pytest tests/integration/test_chat_workflow.py -v -s
```

### Run Specific Test Class
```bash
pytest tests/integration/test_chat_workflow.py::TestMultiTurnConversation -v
```

### Run Specific Test Function
```bash
pytest tests/integration/test_chat_workflow.py::TestMultiTurnConversation::test_checkpoint_save_and_load -v
```

### Run with Custom Environment
```bash
# Use test environment instead of dev
CDK_ENV=test pytest tests/integration/test_chat_workflow.py -v

# Use specific AWS region
AWS_REGION=us-west-2 pytest tests/integration/test_chat_workflow.py -v
```

## Phase 3: Chat Workflow Tests

The `test_chat_workflow.py` file contains integration tests for the LangGraph conversation system with DynamoDB checkpointing.

### Test Coverage

**1. DynamoDB Checkpointer Interface** (`TestDynamoDBCheckpointerInterface`)
- Validates implementation of `BaseCheckpointSaver`
- Verifies required methods: `put()`, `get()`, `list()`, `put_writes()`

**2. Multi-Turn Conversation** (`TestMultiTurnConversation`)
- Checkpoint save and load cycle
- Conversation state accumulation over multiple turns
- Listing all checkpoints for a thread

**3. Session Isolation** (`TestSessionIsolation`)
- Different users have separate sessions
- User cannot access other user's sessions
- Thread ID format validation: `{user_id}#{session_id}`

**4. TTL Expiration** (`TestTTLExpiration`)
- Checkpoints have `expires_at` attribute
- TTL is set to future timestamp (~4 hours)
- TTL updates on session activity

**5. DynamoDB GSI Queries** (`TestGSIQueries`)
- Query all sessions for a user
- Query recent sessions ordered by timestamp

**6. End-to-End Workflow** (`TestE2EConversationWorkflow`)
- Full conversation lifecycle: create → update → list → delete
- Concurrent users with different sessions

**7. Error Handling** (`TestErrorHandling`)
- Get non-existent checkpoint returns None
- List non-existent thread returns empty list
- Invalid thread_id format handling

**8. Performance** (`TestPerformance`)
- Checkpoint write latency < 500ms
- Checkpoint read latency < 200ms

### Prerequisites for Chat Tests

**Before the DynamoDB checkpointer is implemented**:
- Tests will be skipped with message: "DynamoDBSaver not implemented yet"
- This is expected and allows tests to be created ahead of implementation

**After the DynamoDB checkpointer is implemented**:
1. The `chat/checkpointers/dynamodb_saver.py` module must exist
2. It must export `DynamoDBSaver` class
3. `DynamoDBSaver` must extend `langgraph.checkpoint.base.BaseCheckpointSaver`
4. DynamoDB table must be deployed with:
   - Primary key: `thread_id` (partition key) + `checkpoint_id` (sort key)
   - TTL attribute: `expires_at`
   - Optional GSI for user queries

### Manual Testing

Test DynamoDB connection manually:
```bash
pytest tests/integration/test_chat_workflow.py::manual_test_dynamodb_connection -v -s
```

This will:
- Load stack outputs
- Connect to DynamoDB table
- Check table status and TTL configuration
- Report success or failure

## Test Fixtures

Key fixtures provided by `conftest.py`:

### Session-Scoped Fixtures
- `aws_region`: AWS region from environment (default: us-east-1)
- `env_name`: Environment name (default: dev)
- `project_root`: Path to project root
- `stack_outputs`: CDK stack outputs loaded from JSON
- `boto3_clients`: All boto3 clients (DynamoDB, RDS, S3, etc.)
- `dynamodb_resource`: DynamoDB resource client
- `dynamodb_client`: DynamoDB client

### Function-Scoped Fixtures
- `checkpoint_table`: DynamoDB checkpoint table resource
- `rds_connection`: PostgreSQL connection (Phase 2)
- `s3_bucket`: S3 bucket name
- `cognito_user_pool`: Cognito User Pool ID
- `test_cognito_user`: Creates and cleans up test Cognito user
- `cleanup_dynamodb_items`: Tracks and deletes test items
- `cleanup_s3_objects`: Tracks and deletes test S3 objects
- `cleanup_ssm_parameters`: Tracks and deletes test SSM parameters

### Test-Specific Fixtures (in test_chat_workflow.py)
- `cleanup_checkpoints`: Cleanup function for DynamoDB checkpoints
- `test_users`: List of test user dictionaries for multi-tenancy testing
- `dynamodb_checkpointer`: DynamoDBSaver instance (requires implementation)

## Environment Variables

```bash
# AWS Configuration
export AWS_REGION=us-east-1
export CDK_ENV=dev

# AWS Credentials (if not using default profile)
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret
export AWS_SESSION_TOKEN=your_token  # If using temporary credentials
```

## Expected Test Results

### Before Implementation
```
tests/integration/test_chat_workflow.py::TestDynamoDBCheckpointerInterface SKIPPED
tests/integration/test_chat_workflow.py::TestMultiTurnConversation SKIPPED
...
```

All tests should be skipped with: "DynamoDBSaver not implemented yet"

### After Implementation
```
tests/integration/test_chat_workflow.py::TestDynamoDBCheckpointerInterface::test_checkpointer_implements_base_interface PASSED
tests/integration/test_chat_workflow.py::TestDynamoDBCheckpointerInterface::test_checkpointer_has_required_methods PASSED
tests/integration/test_chat_workflow.py::TestMultiTurnConversation::test_checkpoint_save_and_load PASSED
tests/integration/test_chat_workflow.py::TestMultiTurnConversation::test_conversation_state_accumulates PASSED
...

====== 25 passed in 15.32s ======
```

## Troubleshooting

### "CDK outputs not found"
- Run `make infra-deploy` to deploy infrastructure
- Verify `.aws-outputs-dev.json` exists in project root

### "CheckpointTableName not in outputs"
- DynamoDB table not created in CDK stack
- Check `infrastructure/stacks/database_stack.py`

### "Checkpoint table not accessible"
- AWS credentials not configured correctly
- Table doesn't exist in the specified region
- IAM permissions insufficient

### "DynamoDBSaver not implemented yet"
- Expected before Phase 3 Agent 1 completes
- Tests will pass once `chat/checkpointers/dynamodb_saver.py` is implemented

### Connection timeouts
- Check AWS region matches deployed infrastructure
- Verify network connectivity to AWS
- Ensure security groups allow access

## Success Criteria (Phase 3)

As per the implementation plan, Phase 3 is successful when:

- ✅ DynamoDB checkpointer implements full `BaseCheckpointSaver` interface
- ✅ Multi-turn conversations work
- ✅ Checkpoints persist across Lambda invocations
- ✅ TTL deletes expired sessions
- ✅ User isolation verified (can't access other user's sessions)
- ✅ No SQLite dependencies remaining in chat module
- ✅ All integration tests passing

## Next Steps

After Phase 3 implementation:

1. **Implement DynamoDB Checkpointer**: Create `chat/checkpointers/dynamodb_saver.py`
2. **Update Conversation Manager**: Modify `chat/conversation_manager.py` to use DynamoDB
3. **Update Agentic Chat**: Modify `chat/agentic_chat.py` to use new checkpointer
4. **Run Tests**: Execute `pytest tests/integration/test_chat_workflow.py -v`
5. **Validate Success Criteria**: Ensure all tests pass and requirements met
6. **Proceed to Phase 4**: API Lambda and event-driven workflow

## Related Documentation

- [AWS Migration Plan](/workspaces/collections-local/AWS_MIGRATION_PLAN.md)
- [Implementation Plan](/home/codespace/.claude/plans/concurrent-beaming-river.md)
- [Phase 1 Tests](/workspaces/collections-local/scripts/aws/test/)
- [Unit Tests](/workspaces/collections-local/tests/)
