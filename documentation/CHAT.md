# Multi-Turn Agentic Chat

This document describes the multi-turn conversational chat feature that enables persistent, context-aware conversations with the image collection search system.

## Overview

The chat feature extends the single-turn agentic search to support multi-turn conversations where:
- Context from previous exchanges is maintained
- Follow-up queries like "show me more" or "filter those by X" work naturally
- Conversation state persists across requests within a session

## Architecture

### Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `ConversationManager` | `chat/conversation_manager.py` | SQLite persistence, session lifecycle |
| `AgenticChatOrchestrator` | `chat/agentic_chat.py` | Multi-turn agent with memory |
| Chat Config | `config/chat_config.py` | Configuration settings |
| Chat Models | `models.py` | Request/response schemas |

### Data Flow

```
Client                    API                     Agent                  Storage
  │                        │                        │                       │
  │  POST /chat            │                        │                       │
  │  {message, session_id} │                        │                       │
  ├───────────────────────►│                        │                       │
  │                        │  get_thread_config()   │                       │
  │                        ├───────────────────────►│                       │
  │                        │                        │  Load checkpoint      │
  │                        │                        ├──────────────────────►│
  │                        │                        │◄─────────────────────┤
  │                        │  chat(message)         │                       │
  │                        ├───────────────────────►│                       │
  │                        │                        │  LLM + Tools          │
  │                        │                        │◄─────────────────────►│
  │                        │                        │  Save checkpoint      │
  │                        │                        ├──────────────────────►│
  │                        │◄───────────────────────┤                       │
  │  ChatResponse          │                        │                       │
  │◄───────────────────────┤                        │                       │
```

## API Endpoints

### POST /chat

Send a message and get a response with conversation context.

**Request:**
```json
{
  "message": "Show me beach photos",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "top_k": 10,
  "category_filter": null,
  "min_similarity_score": 0.0
}
```

**Response:**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": {
    "role": "assistant",
    "content": "I found 5 beach photos in your collection...",
    "timestamp": "2024-01-15T10:30:00Z",
    "search_results": [...],
    "tools_used": [...]
  },
  "conversation_turn": 1,
  "search_results": [...],
  "agent_reasoning": ["Found 5 beach items matching query"],
  "tools_used": [{"tool": "search_collections", "input": {"query": "beach"}, "output": "..."}],
  "response_time_ms": 1250.5
}
```

### GET /chat/{session_id}/history

Get conversation history for a session.

**Response:**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "messages": [
    {"role": "user", "content": "Show me beach photos", "timestamp": "..."},
    {"role": "assistant", "content": "I found 5 beach photos...", "timestamp": "..."}
  ],
  "created_at": "2024-01-15T10:30:00Z",
  "last_activity": "2024-01-15T10:32:00Z",
  "message_count": 2
}
```

### DELETE /chat/{session_id}

Clear a chat session and its history.

**Response:**
```json
{
  "status": "deleted",
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### GET /chat/sessions

List active chat sessions (development/debug endpoint).

**Response:**
```json
{
  "sessions": [
    {
      "session_id": "550e8400-e29b-41d4-a716-446655440000",
      "created_at": "2024-01-15T10:30:00Z",
      "last_activity": "2024-01-15T10:35:00Z",
      "message_count": 5
    }
  ],
  "stats": {
    "total_sessions": 1,
    "total_messages": 5,
    "database_size_bytes": 12288,
    "ttl_hours": 4,
    "max_sessions": 100
  }
}
```

## Client Integration

### Session Management (JavaScript)

```javascript
// Get or create session ID
const getOrCreateSessionId = () => {
  let sessionId = sessionStorage.getItem('chat_session');
  if (!sessionId) {
    sessionId = crypto.randomUUID();
    sessionStorage.setItem('chat_session', sessionId);
  }
  return sessionId;
};

// Send chat message
const sendMessage = async (message) => {
  const response = await fetch('/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message: message,
      session_id: getOrCreateSessionId(),
      top_k: 10
    })
  });
  return response.json();
};

// Example multi-turn conversation
await sendMessage("Show me beach photos");
// Response: "I found 5 beach photos..."

await sendMessage("Show me more like the first one");
// Response: "Here are similar beach scenes..."

await sendMessage("Filter those by sunset");
// Response: "I found 2 beach sunset photos..."
```

### Session Lifecycle

| Event | Session Behavior |
|-------|-----------------|
| New tab/window | New session created |
| Tab refresh | Same session (sessionStorage persists) |
| Tab close | Session orphaned (cleanup on TTL) |
| 4 hours inactivity | Session expired and cleaned up |
| Server restart | Expired sessions cleaned on startup |

## Configuration

Environment variables and defaults:

| Variable | Default | Description |
|----------|---------|-------------|
| `CONVERSATION_DB_PATH` | `./data/conversations.db` | SQLite database path |
| `CONVERSATION_TTL_HOURS` | `4` | Session expiration time |
| `MAX_CONVERSATIONS` | `100` | Maximum concurrent sessions |
| `CLEANUP_ON_STARTUP` | `true` | Clean expired sessions on start |
| `CHAT_MODEL` | `claude-sonnet-4-5` | LLM model for chat |
| `CHAT_TEMPERATURE` | `0.1` | LLM temperature |
| `CHAT_MAX_TOKENS` | `2048` | Max response tokens |
| `CHAT_MAX_ITERATIONS` | `3` | Max tool call iterations |

## Conversation Examples

### Basic Search
```
User: "Show me food photos"
Assistant: "I found 12 food items in your collection, including restaurants,
           street food, and home cooking. Would you like me to filter by a
           specific type?"
```

### Follow-up Query
```
User: "Just the restaurants"
Assistant: "Here are 5 restaurant photos from your collection..."
```

### Contextual Refinement
```
User: "Any in Tokyo?"
Assistant: "I found 3 Tokyo restaurant photos from your collection..."
```

### Show More
```
User: "Show me more like these"
Assistant: "Here are similar Japanese dining photos..."
```

## Persistence Details

### SQLite Schema

The conversation manager creates two types of tables:

1. **Session Tracking** (custom):
```sql
CREATE TABLE chat_sessions (
    session_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    last_activity TEXT NOT NULL,
    message_count INTEGER DEFAULT 0
);
```

2. **Checkpoints** (LangGraph managed):
```sql
-- Created automatically by SqliteSaver
CREATE TABLE checkpoints (...);
CREATE TABLE checkpoint_writes (...);
CREATE TABLE checkpoint_blobs (...);
```

### Cleanup Behavior

- **On Startup**: Sessions older than `CONVERSATION_TTL_HOURS` are removed
- **Max Sessions**: If count exceeds `MAX_CONVERSATIONS`, oldest sessions are removed
- **Manual**: Use `DELETE /chat/{session_id}` to clear specific sessions

## LangSmith Tracing

All chat operations are traced with:
- `@traceable(name="chat", run_type="chain")` decorator
- Session ID in trace metadata
- Full conversation context captured
- Tool calls and outputs logged

View traces in LangSmith under the "chat" operation name.

## Testing

Run chat tests:
```bash
pytest tests/test_chat.py -v
```

Test categories:
- `TestConversationManager`: Session lifecycle, cleanup, persistence
- `TestAgenticChatOrchestrator`: Chat execution, context handling
- `TestChatModels`: Request/response validation
- `TestChatConfiguration`: Config defaults

## Comparison with Single-Turn Search

| Feature | `/search` (agentic) | `/chat` |
|---------|--------------------:|--------:|
| Memory | None | SQLite checkpoint |
| Follow-ups | Not supported | Full context |
| Session ID | Not required | Required |
| Use case | One-off queries | Conversations |

## Future Enhancements

1. **User Authentication**: Add user prefix to thread IDs for per-user conversations
2. **Conversation Summarization**: Handle long conversations exceeding context limits
3. **Redis Backend**: Scale to multiple API servers with shared state
4. **Streaming Responses**: Stream agent responses for better UX
