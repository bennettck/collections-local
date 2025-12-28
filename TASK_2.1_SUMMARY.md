# Task 2.1: Update main.py Database Imports - Summary

## Approach Taken

**Wrapper Module Approach (Alternative/Simpler)** - Created a database API wrapper that routes between SQLite and PostgreSQL backends based on environment variables.

## Files Modified

### 1. Created `/home/user/collections-local/database/api.py`
- **Purpose**: Unified database API that routes to appropriate backend
- **Features**:
  - Detects backend based on `DB_SECRET_ARN` or `DATABASE_URL` environment variables
  - For PostgreSQL: Requires and passes `user_id` parameter
  - For SQLite: Accepts but ignores `user_id` parameter
  - Provides all database functions with optional `user_id` parameter
  - Includes helper function `use_postgres()` to check active backend

### 2. Renamed `/home/user/collections-local/database.py` → `/home/user/collections-local/database_sqlite.py`
- **Reason**: Resolved import conflict between `database.py` file and `database/` package
- **Impact**: This file is actually a router that imports from `database_sqlite_legacy.py`

### 3. Updated `/home/user/collections-local/main.py`
Major changes:
- **Imports**: Changed from `from database import` to `from database.api import`
- **Added**: `from typing import Optional` for type hints
- **Added**: `get_user_id_from_request(request: Request)` helper function
  - Extracts user_id from `request.state.user_id` (set by CognitoAuthMiddleware)
  - Falls back to `os.getenv("DEFAULT_USER_ID", "default")` for local development

- **Helper Functions**:
  - `_item_to_response()`: Added optional `user_id` parameter, passes to `get_latest_analysis()`

- **Updated Endpoints** (added Request parameter and user_id extraction):
  - `POST /items` - create_item_endpoint
  - `GET /items` - list_items_endpoint
  - `GET /items/{item_id}` - get_item_endpoint
  - `DELETE /items/{item_id}` - delete_item_endpoint
  - `POST /items/{item_id}/analyze` - analyze_item_endpoint
  - `GET /items/{item_id}/analyses` - get_item_analyses_endpoint
  - `GET /analyses/{analysis_id}` - get_analysis_endpoint
  - `POST /search` - search_collection (extracts user_id for result processing)
  - `POST /chat` - chat_endpoint (extracts user_id for result processing)
  - Golden dataset endpoints (use hardcoded `"default"` user_id)

- **Updated Direct Imports**:
  - Changed `from database import database_context` to `from database_sqlite import database_context`
  - Changed `from database import get_db` to `from database_sqlite import get_db`
  - Changed `from database import get_vector_index_status` to `from database_sqlite import get_vector_index_status`

### 4. Updated `/home/user/collections-local/middleware/database_routing.py`
- Changed `from database import database_context` to `from database_sqlite_legacy import database_context`

## User ID Flow

### In Production (PostgreSQL):
1. CognitoAuthMiddleware validates JWT and sets `request.state.user_id`
2. Endpoints call `get_user_id_from_request(request)` to extract user_id
3. Database API wrapper receives user_id and passes to PostgreSQL backend
4. PostgreSQL enforces multi-tenancy by filtering on user_id

### In Local Development (SQLite):
1. No auth middleware (or disabled)
2. `get_user_id_from_request()` returns fallback: `"default"`
3. Database API wrapper receives user_id but SQLite backend ignores it
4. SQLite operates without multi-tenancy (single-tenant mode)

## Verification

```bash
python -c "from main import app; print('OK')"
```

**Result**: ✅ OK (with one deprecation warning about `regex` vs `pattern` in FastAPI Query)

## Key Design Decisions

1. **Wrapper Pattern**: Chose wrapper module over inline import shim for cleaner separation of concerns
2. **Optional user_id**: Made user_id optional with None default to maintain compatibility with SQLite
3. **Graceful Degradation**: SQLite backend accepts but ignores user_id, allowing same code to work in both environments
4. **Minimal Changes**: Updated only critical endpoints and helper functions that directly call database functions
5. **Golden Dataset**: Hardcoded `"default"` user_id for golden dataset endpoints (single-tenant by design)

## Not Yet Implemented

Some functions in the PostgreSQL backend are marked as TODO in the wrapper:
- `create_embedding()` - Raises NotImplementedError for PostgreSQL
- `get_embedding()` - Raises NotImplementedError for PostgreSQL

These can be implemented when the corresponding functions are added to `database_sqlalchemy.py`.

## Environment Detection

The backend selection logic:
```python
_use_postgres = bool(
    os.getenv("DB_SECRET_ARN") or
    os.getenv("DATABASE_URL", "").startswith("postgresql")
)
```

- If `DB_SECRET_ARN` is set → PostgreSQL (AWS Lambda with Secrets Manager)
- If `DATABASE_URL` starts with "postgresql" → PostgreSQL
- Otherwise → SQLite (local development)

## Testing Recommendations

1. **Local Development**: Test with SQLite backend (no env vars set)
2. **PostgreSQL Mode**: Set `DATABASE_URL=postgresql://...` and verify user_id is enforced
3. **Auth Flow**: Verify JWT tokens properly set `request.state.user_id`
4. **Multi-tenancy**: Verify users can only access their own data in PostgreSQL mode

## Future Work

- Implement remaining PostgreSQL functions (embeddings)
- Add comprehensive integration tests for both backends
- Consider adding user_id validation/authorization layer
- Add metrics/logging for backend selection and user_id extraction
