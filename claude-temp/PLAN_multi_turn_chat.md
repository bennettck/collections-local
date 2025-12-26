# Implementation Plan: Multi-Turn Agentic Chat

## Overview

Add multi-turn conversational capabilities to the existing agentic search system using LangGraph with SQLite checkpointing.

### Decisions Made

| Decision | Choice |
|----------|--------|
| Persistence | SQLite (WAL mode) - `conversations.db` |
| Scope | Per-browser-tab sessions |
| Expiration | 4-hour TTL with cleanup on startup |
| Thread ID format | `session_{client_uuid}` |
| Context window | 5-10 turns, no summarization needed |
| Future-proofing | Thread ID structure supports user prefix later |

---

## Implementation Steps

### Step 1: Create Conversation Manager Module

**New file:** `chat/conversation_manager.py`

**Purpose:** Manage SQLite checkpointing, session lifecycle, and cleanup.

**Key components:**
```python
from langgraph.checkpoint.sqlite import SqliteSaver
from datetime import datetime, timedelta

class ConversationManager:
    def __init__(self, db_path: str = "./data/conversations.db")
    def get_checkpointer(self) -> SqliteSaver
    def get_thread_config(self, session_id: str) -> dict
    def cleanup_expired_sessions(self, ttl_hours: int = 4) -> int
    def get_session_history(self, session_id: str) -> list
    def delete_session(self, session_id: str) -> bool
```

**Configuration:**
```python
CONVERSATION_CONFIG = {
    "db_path": "./data/conversations.db",
    "ttl_hours": 4,
    "max_sessions": 100,
    "cleanup_on_startup": True,
}
```

---

### Step 2: Create Multi-Turn Chat Agent

**New file:** `chat/agentic_chat.py`

**Purpose:** Extend `AgenticSearchOrchestrator` to support multi-turn conversation with memory.

**Key changes from single-turn:**
1. Use `SqliteSaver` checkpointer with `create_react_agent`
2. Thread-based state management
3. Conversation-aware system prompt
4. Return conversation context in responses

**Key components:**
```python
class AgenticChatOrchestrator:
    def __init__(
        self,
        chroma_manager,
        conversation_manager: ConversationManager,
        top_k: int = 10,
        ...
    )

    def chat(
        self,
        message: str,
        session_id: str,
    ) -> ChatResponse

    def get_history(self, session_id: str) -> list[Message]

    def clear_session(self, session_id: str) -> bool
```

**Updated system prompt (conversation-aware):**
```python
CHAT_SYSTEM_MESSAGE = """You are a helpful assistant for searching and discussing a personal image collection.

You have access to the conversation history and can reference previous exchanges.
When the user says things like "show me more", "what about...", or "filter those by...",
use the conversation context to understand their intent.

Available tools:
- search_collections: Search the image collection

Guidelines:
- Reference previous results when relevant
- Ask clarifying questions if the user's intent is unclear
- Provide concise, helpful responses
- Remember context from earlier in the conversation
"""
```

---

### Step 3: Create Chat Data Models

**Modified file:** `models.py`

**New models to add:**

```python
class ChatRequest(BaseModel):
    """Request model for chat endpoint."""
    message: str = Field(..., min_length=1, description="User message")
    session_id: str = Field(..., description="Client-generated session UUID")
    top_k: int = Field(10, ge=1, le=50)
    category_filter: Optional[str] = None
    min_similarity_score: float = Field(0.0, ge=0.0, le=1.0)

class ChatMessage(BaseModel):
    """A single message in the conversation."""
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime
    search_results: Optional[List[SearchResult]] = None
    tools_used: Optional[List[Dict[str, Any]]] = None

class ChatResponse(BaseModel):
    """Response model for chat endpoint."""
    session_id: str
    message: ChatMessage
    conversation_length: int
    search_results: Optional[List[SearchResult]] = None
    agent_reasoning: Optional[List[str]] = None
    tools_used: Optional[List[Dict[str, Any]]] = None
    response_time_ms: float

class ChatHistoryResponse(BaseModel):
    """Response model for chat history."""
    session_id: str
    messages: List[ChatMessage]
    created_at: datetime
    last_activity: datetime
```

---

### Step 4: Create Chat Configuration

**New file:** `config/chat_config.py`

```python
"""Configuration for multi-turn agentic chat."""

# Conversation persistence
CONVERSATION_DB_PATH = "./data/conversations.db"
CONVERSATION_TTL_HOURS = 4
MAX_CONVERSATIONS = 100
CLEANUP_ON_STARTUP = True

# Agent configuration (inherits from agent_config but can override)
CHAT_MODEL = "claude-sonnet-4-5"
CHAT_TEMPERATURE = 0.1  # Slightly higher for more natural conversation
CHAT_MAX_TOKENS = 2048
CHAT_MAX_ITERATIONS = 3

# System message for conversational context
CHAT_SYSTEM_MESSAGE = """..."""  # Full message as above
```

---

### Step 5: Add Chat API Endpoints

**Modified file:** `main.py`

**New endpoints:**

```python
# Chat Endpoints

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(chat_request: ChatRequest, request: Request):
    """
    Multi-turn conversational search and Q&A.

    Send messages with a session_id to maintain conversation context.
    The agent remembers previous exchanges and can handle follow-up questions.
    """
    ...

@app.get("/chat/{session_id}/history", response_model=ChatHistoryResponse)
async def get_chat_history(session_id: str):
    """Get conversation history for a session."""
    ...

@app.delete("/chat/{session_id}")
async def clear_chat_session(session_id: str):
    """Clear a chat session and its history."""
    ...

@app.get("/chat/sessions")
async def list_active_sessions():
    """List active chat sessions (dev/debug endpoint)."""
    ...
```

---

### Step 6: Initialize Conversation Manager on Startup

**Modified file:** `main.py` (lifespan function)

```python
# Add to lifespan():
from chat.conversation_manager import ConversationManager

# Global conversation manager
conversation_manager = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global conversation_manager

    # ... existing initialization ...

    # Initialize conversation manager
    print("Initializing conversation manager...")
    conversation_manager = ConversationManager(
        db_path=CONVERSATION_DB_PATH
    )

    # Cleanup expired sessions on startup
    if CLEANUP_ON_STARTUP:
        expired = conversation_manager.cleanup_expired_sessions(
            ttl_hours=CONVERSATION_TTL_HOURS
        )
        print(f"Cleaned up {expired} expired conversations")

    yield

    # Shutdown cleanup if needed
```

---

### Step 7: Add LangSmith Tracing

**Integration points:**

1. `@traceable(name="chat", run_type="chain")` on `AgenticChatOrchestrator.chat()`
2. Include `session_id` in trace metadata
3. Link conversation turns via parent run ID

```python
@traceable(name="chat", run_type="chain")
def chat(self, message: str, session_id: str) -> ChatResponse:
    # LangSmith will automatically capture:
    # - Input message
    # - Conversation context (via checkpointer state)
    # - Tool calls and outputs
    # - Final response
    ...
```

---

### Step 8: Update Documentation

**New file:** `documentation/CHAT.md`

Document:
- Chat endpoint usage
- Session management
- Client-side session handling
- Conversation flow examples
- Configuration options

---

### Step 9: Create Tests

**New file:** `tests/test_chat.py`

Test cases:
1. Single message (new session)
2. Multi-turn conversation (context preservation)
3. Follow-up queries ("show me more", "filter those")
4. Session expiration
5. Session cleanup
6. Concurrent sessions
7. Invalid session handling

---

## File Structure After Implementation

```
collections-local/
├── chat/
│   ├── __init__.py
│   ├── conversation_manager.py    # NEW: Session & checkpoint management
│   └── agentic_chat.py            # NEW: Multi-turn chat orchestrator
├── config/
│   ├── agent_config.py            # Existing
│   ├── chat_config.py             # NEW: Chat-specific config
│   └── ...
├── retrieval/
│   ├── agentic_search.py          # Existing (unchanged)
│   └── ...
├── models.py                       # MODIFIED: Add chat models
├── main.py                         # MODIFIED: Add chat endpoints
├── data/
│   ├── collections.db             # Existing
│   ├── collections_golden.db      # Existing
│   └── conversations.db           # NEW: Chat state persistence
└── documentation/
    ├── CHAT.md                    # NEW: Chat documentation
    └── ...
```

---

## Implementation Order

1. **config/chat_config.py** - Configuration first
2. **chat/conversation_manager.py** - Core persistence layer
3. **models.py** - Add chat data models
4. **chat/agentic_chat.py** - Chat orchestrator
5. **main.py** - Add endpoints and startup init
6. **tests/test_chat.py** - Test coverage
7. **documentation/CHAT.md** - Documentation

---

## Key LangChain/LangGraph Methods Used

| Method | Purpose |
|--------|---------|
| `SqliteSaver.from_conn_string()` | Create SQLite checkpointer |
| `create_react_agent(checkpointer=...)` | Attach persistence to agent |
| `graph.invoke(input, config={"configurable": {"thread_id": ...}})` | Resume conversation |
| `checkpointer.list(config)` | List checkpoints for a thread |
| `checkpointer.get(config)` | Get specific checkpoint |

---

## Client Integration Example

```javascript
// Client-side session management
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
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| SQLite locking with multiple workers | Use WAL mode, single writer pattern |
| Unbounded conversation growth | 4-hour TTL + startup cleanup |
| Context window overflow | 5-10 turn limit, could add summarization later |
| Orphaned sessions | Aggressive cleanup on startup |

---

## Success Criteria

- [ ] New session creates persistent conversation
- [ ] Follow-up queries reference previous context
- [ ] "show me more" / "filter those" work correctly
- [ ] Sessions expire after 4 hours inactivity
- [ ] Cleanup removes expired sessions on startup
- [ ] LangSmith traces show full conversation flow
- [ ] Tests pass for multi-turn scenarios
