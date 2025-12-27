# DynamoDB Checkpointer for LangGraph

This module implements a DynamoDB-based checkpoint saver for LangGraph conversations, enabling serverless, multi-tenant conversation state persistence with automatic TTL expiration.

## Architecture

### Components

1. **DynamoDBSaver** (`dynamodb_saver.py`)
   - Extends `langgraph.checkpoint.base.BaseCheckpointSaver`
   - Implements all required checkpoint operations
   - Uses boto3 DynamoDB resource API
   - Supports msgpack serialization for efficient storage

2. **ConversationManager** (`../conversation_manager.py`)
   - High-level interface for managing conversations
   - Multi-tenant support via `{user_id}#{session_id}` thread IDs
   - Compatible with existing AgenticChatOrchestrator

## Features

### Multi-Tenancy
- Thread IDs follow format: `{user_id}#{session_id}`
- Ensures complete isolation between users
- Single DynamoDB table serves all users

### Automatic Expiration
- TTL set on `expires_at` attribute (default: 4 hours)
- DynamoDB automatically deletes expired checkpoints
- No manual cleanup required

### Complete BaseCheckpointSaver Implementation
- `put()` - Store checkpoints
- `get()` / `get_tuple()` - Retrieve checkpoints
- `list()` - List checkpoints for a thread
- `put_writes()` - Store intermediate writes
- `delete_thread()` - Delete all checkpoints for a thread

### Efficient Storage
- Binary checkpoint data stored as DynamoDB Binary type
- Metadata stored as DynamoDB Map with Decimal conversion
- Supports checkpoint versioning and parent references

## DynamoDB Table Schema

### Primary Key
- **Partition Key**: `thread_id` (String) - Format: `{user_id}#{session_id}`
- **Sort Key**: `sort_key` (String) - Format: `{checkpoint_ns}#{checkpoint_id}`

### Attributes
- `checkpoint_id` (String) - Unique checkpoint identifier
- `checkpoint_ns` (String) - Checkpoint namespace (usually empty)
- `checkpoint_data` (Binary) - Serialized checkpoint (msgpack)
- `metadata` (Map) - Checkpoint metadata
- `expires_at` (Number) - TTL timestamp (Unix epoch seconds)
- `created_at` (String) - ISO timestamp
- `parent_checkpoint_id` (String) - Optional parent reference
- `pending_writes` (List) - Optional intermediate writes

### TTL Configuration
- Enable TTL on the `expires_at` attribute
- DynamoDB automatically deletes items after expiration

## Usage

### Basic Usage

```python
from chat.checkpointers.dynamodb_saver import DynamoDBSaver

# Create checkpointer
checkpointer = DynamoDBSaver(
    table_name='langgraph-checkpoints',
    ttl_hours=4,
    region_name='us-east-1'
)

# Use with LangGraph agent
from langgraph.prebuilt import create_react_agent

agent = create_react_agent(
    model=llm,
    tools=tools,
    checkpointer=checkpointer
)

# Invoke with config
config = {
    "configurable": {
        "thread_id": "user123#session456"
    }
}

result = agent.invoke({"messages": [{"role": "user", "content": "Hello"}]}, config)
```

### With ConversationManager

```python
from chat.conversation_manager import ConversationManager

# Create manager
manager = ConversationManager(
    table_name='langgraph-checkpoints',
    ttl_hours=4,
    region_name='us-east-1',
    user_id='user123'
)

# Get checkpointer
checkpointer = manager.get_checkpointer()

# Get thread config (automatically formats thread_id)
config = manager.get_thread_config('session456')
# Returns: {"configurable": {"thread_id": "user123#session456"}}

# Use with agent
agent = create_react_agent(model=llm, tools=tools, checkpointer=checkpointer)
result = agent.invoke({"messages": [...]}, config)
```

### With AgenticChatOrchestrator

```python
from chat.agentic_chat import AgenticChatOrchestrator
from chat.conversation_manager import ConversationManager

# Create conversation manager
conversation_manager = ConversationManager(
    table_name='langgraph-checkpoints',
    user_id='user123'
)

# Create orchestrator (automatically uses DynamoDB checkpointer)
orchestrator = AgenticChatOrchestrator(
    chroma_manager=chroma_manager,
    conversation_manager=conversation_manager
)

# Chat with persistent state
response = orchestrator.chat(
    message="Hello",
    session_id="session456"
)
```

## Configuration

### Environment Variables

- `DYNAMODB_CHECKPOINT_TABLE` - Table name (default: "langgraph-checkpoints")
- `AWS_REGION` - AWS region (default: boto3 default)
- `CONVERSATION_TTL_HOURS` - Hours until expiration (default: 4)

### AWS Permissions Required

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:Query",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:BatchWriteItem"
      ],
      "Resource": "arn:aws:dynamodb:*:*:table/langgraph-checkpoints"
    }
  ]
}
```

## Testing

### Unit Tests

```bash
# Run DynamoDBSaver tests (uses moto for mocking)
pytest retrieval/tests/test_dynamodb_saver.py -v

# Run ConversationManager tests
pytest retrieval/tests/test_conversation_manager_dynamodb.py -v

# Run all tests
pytest retrieval/tests/test_dynamodb_saver.py retrieval/tests/test_conversation_manager_dynamodb.py -v
```

### Test Coverage

- ✅ Initialization and configuration
- ✅ TTL calculation
- ✅ Thread ID formatting and extraction
- ✅ Checkpoint storage and retrieval
- ✅ Checkpoint listing with filters
- ✅ Parent checkpoint references
- ✅ Intermediate writes (put_writes)
- ✅ Thread deletion
- ✅ Serialization/deserialization (msgpack, Decimal conversion)
- ✅ Multi-tenancy (user isolation)
- ✅ ConversationManager integration

## Migration from SQLite

### Key Differences

| Feature | SQLite (Old) | DynamoDB (New) |
|---------|-------------|----------------|
| Storage | Local file | AWS DynamoDB |
| Multi-tenancy | None | Built-in via thread_id |
| TTL | Manual cleanup | Automatic (DynamoDB TTL) |
| Session tracking | Separate table | Embedded in checkpoints |
| Scaling | Single instance | Serverless, auto-scaling |
| Cost | Free | Pay per request |

### Migration Steps

1. Update initialization to use DynamoDB:
   ```python
   # OLD
   manager = ConversationManager(db_path="./data/conversations.db")

   # NEW
   manager = ConversationManager(
       table_name='langgraph-checkpoints',
       user_id='user123'
   )
   ```

2. No changes needed to AgenticChatOrchestrator - it uses the ConversationManager interface

3. Deploy DynamoDB table with CDK or manually:
   ```python
   # See infrastructure/stacks/database_stack.py for CDK example
   ```

## Performance Considerations

### Optimization Tips

1. **Use consistent checkpoint_ns** - Empty string is recommended for most use cases
2. **Limit checkpoint history** - Delete old sessions periodically
3. **Enable DynamoDB auto-scaling** - For production workloads
4. **Use on-demand billing** - For variable/unpredictable traffic
5. **Monitor CloudWatch metrics** - Track request latency and throttling

### Expected Performance

- **Checkpoint write**: <50ms (p95)
- **Checkpoint read**: <20ms (p95)
- **Thread deletion**: <100ms for 10 checkpoints
- **TTL cleanup**: Automatic within 48 hours of expiration

## Troubleshooting

### Common Issues

1. **"thread_id must be provided in config"**
   - Ensure `configurable.thread_id` is set in config
   - Use `ConversationManager.get_thread_config()` to get properly formatted config

2. **"ResourceNotFoundException: Requested resource not found"**
   - DynamoDB table doesn't exist
   - Check table name and AWS region

3. **"AccessDeniedException"**
   - Missing IAM permissions
   - Add required DynamoDB permissions to Lambda/EC2 role

4. **Checkpoints not expiring**
   - TTL not enabled on table
   - Enable TTL on `expires_at` attribute in DynamoDB console

5. **User isolation not working**
   - Verify thread_id format: `{user_id}#{session_id}`
   - Check ConversationManager is initialized with correct user_id

## Best Practices

1. **Always use ConversationManager** - Don't instantiate DynamoDBSaver directly
2. **Set user_id from JWT claims** - Extract from Cognito tokens
3. **Use UUIDs for session_id** - Ensure uniqueness
4. **Enable CloudWatch alarms** - Monitor throttling and errors
5. **Test with moto** - Mock DynamoDB for unit tests
6. **Use consistent TTL** - 4 hours recommended for conversations

## References

- [LangGraph Checkpointing Documentation](https://langchain-ai.github.io/langgraph/concepts/persistence/)
- [DynamoDB TTL Documentation](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/TTL.html)
- [AWS Migration Implementation Plan](/home/codespace/.claude/plans/concurrent-beaming-river.md)
