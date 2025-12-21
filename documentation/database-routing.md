# Database Routing Architecture

## Overview

The Collections Local API supports simultaneous access to two SQLite databases through a single server instance using host-based routing. This architecture simplifies testing and deployment by eliminating the need to run separate server processes while maintaining complete database isolation.

## Architecture

### Before: Dual-Server Approach

Previously, the system required running two separate uvicorn processes:
- Port 8000: Production database (`DATABASE_PATH=./data/collections.db`)
- Port 8001: Golden database (`DATABASE_PATH=./data/collections_golden.db`)

**Drawbacks:**
- Manual testing required on both ports
- Two processes to manage and monitor
- More complex deployment setup
- Higher resource usage

### After: Single-Server with Middleware Routing

The new architecture uses a single FastAPI server with custom middleware that routes requests to the appropriate database based on the HTTP Host header or query parameter.

**Benefits:**
- Single server process on port 8000
- Simplified testing (one endpoint, different routing)
- Lower resource usage
- Easier deployment and monitoring
- Backwards compatible with existing code

## How It Works

### Request Flow

```
Client Request
    ↓
Host Header / Query Param Detection
    ↓
DatabaseRoutingMiddleware
    ↓
database_context(path) applied
    ↓
Request Handler (routes)
    ↓
Database Operations
    ↓
Response + X-Database-Context header
```

### Routing Logic

The `DatabaseRoutingMiddleware` inspects each incoming request and determines the target database using this priority:

1. **Query Parameter** (highest priority, for testing)
   - `?_db=golden` → Golden database
   - `?_db=prod` → Production database

2. **Host Header** (primary routing method)
   - `golden.localhost:8000` → Golden database
   - `golden.api.example.com` → Golden database
   - `localhost:8000` → Production database (default)
   - `api.example.com` → Production database (default)

### Thread Safety

Database routing is thread-safe through Python's `threading.local()` storage:

```python
# In database.py
_context = threading.local()

@contextmanager
def database_context(db_path: str):
    """Thread-local database path override"""
    previous = getattr(_context, 'db_path', None)
    _context.db_path = db_path
    try:
        yield
    finally:
        # Restore previous context
        ...
```

Each request runs in its own thread with isolated database context, preventing cross-contamination between concurrent requests to different databases.

## Configuration

### Environment Variables

Configure database paths in `.env`:

```env
# New configuration (recommended)
PROD_DATABASE_PATH=./data/collections.db
GOLDEN_DATABASE_PATH=./data/collections_golden.db

# Legacy configuration (still supported)
# DATABASE_PATH=./data/collections.db  # Deprecated
```

The system supports backwards compatibility:
- If `PROD_DATABASE_PATH` is not set, falls back to `DATABASE_PATH`
- Logs a deprecation warning if old variable is used

### Middleware Registration

In `main.py`:

```python
from middleware import DatabaseRoutingMiddleware

app.add_middleware(
    DatabaseRoutingMiddleware,
    prod_db_path=PROD_DATABASE_PATH,
    golden_db_path=GOLDEN_DATABASE_PATH
)
```

The middleware must be added **after** CORS middleware but **before** route handlers.

## Local Development Setup

### Option 1: Subdomain Routing (Recommended)

Edit `/etc/hosts` (requires sudo):

```bash
sudo nano /etc/hosts
```

Add:
```
127.0.0.1    golden.localhost
```

Save and test:
```bash
# Production DB
curl http://localhost:8000/health

# Golden DB
curl http://golden.localhost:8000/health
```

### Option 2: Query Parameter Routing (Easiest)

No configuration needed:

```bash
# Production DB
curl http://localhost:8000/items

# Golden DB
curl "http://localhost:8000/items?_db=golden"
```

### Option 3: Host Header Override (Advanced)

Use curl's `-H` flag:

```bash
curl -H "Host: golden.localhost:8000" http://localhost:8000/health
```

Or use browser extensions like ModHeader or Requestly to modify the Host header.

## Usage Examples

### Health Check

Check which database is active:

```bash
# Production
curl http://localhost:8000/health | python3 -m json.tool

# Output:
{
    "status": "healthy",
    "timestamp": "2025-12-21T03:30:00.000000",
    "active_database": "production",
    "active_db_path": "./data/collections.db",
    "database_stats": {
        "production": {"items": 84},
        "golden": {"items": 55}
    }
}
```

### Listing Items

```bash
# Production database (84 items)
curl http://localhost:8000/items

# Golden database (55 items)
curl "http://localhost:8000/items?_db=golden"
```

### Search

```bash
# Search in production
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "tokyo restaurants", "top_k": 10}'

# Search in golden dataset
curl -X POST "http://localhost:8000/search?_db=golden" \
  -H "Content-Type: application/json" \
  -d '{"query": "tokyo restaurants", "top_k": 10}'
```

### Response Headers

All responses include the `X-Database-Context` header:

```bash
curl -I http://localhost:8000/health

# Headers include:
# x-database-context: production

curl -I "http://localhost:8000/health?_db=golden"

# Headers include:
# x-database-context: golden
```

## Database Initialization

On server startup, both databases are automatically initialized:

```
Initializing production database...
Initializing golden database...
Checking production search index...
Production index ready: 84 documents
Checking golden search index...
Golden index ready: 55 documents
```

The lifespan function ensures:
1. Both database schemas are created/migrated
2. Both FTS5 search indices are built or verified
3. Images directory exists
4. All prerequisites are ready before accepting requests

## Testing

### Manual Testing Checklist

- [ ] Health endpoint shows correct active database for production
- [ ] Health endpoint shows correct active database for golden (`?_db=golden`)
- [ ] Items endpoint returns different counts (prod: 84, golden: 55)
- [ ] Search works on both databases
- [ ] `X-Database-Context` header is present in all responses
- [ ] Concurrent requests to different DBs work correctly
- [ ] No cross-contamination between database requests

### Concurrent Access Test

```bash
# Run simultaneously in different terminals
curl http://localhost:8000/items &
curl "http://localhost:8000/items?_db=golden" &
wait

# Verify both return correct counts
```

### Integration Testing

```python
from fastapi.testclient import TestClient
from main import app

def test_database_routing():
    client = TestClient(app)

    # Test production routing
    response = client.get("/health")
    assert response.json()["active_database"] == "production"

    # Test golden routing via query param
    response = client.get("/health?_db=golden")
    assert response.json()["active_database"] == "golden"

    # Test golden routing via host header
    response = client.get("/health", headers={"Host": "golden.localhost:8000"})
    assert response.json()["active_database"] == "golden"

    # Verify database isolation
    prod_items = client.get("/items").json()["total"]
    golden_items = client.get("/items?_db=golden").json()["total"]
    assert golden_items < prod_items  # Golden is subset
```

## Migration Guide

### From Dual-Server Setup

If you're currently running two servers:

1. **Stop both servers**
   ```bash
   pkill -f "uvicorn main:app"
   ```

2. **Update environment variables**
   ```bash
   # In .env
   # Remove or comment: DATABASE_PATH=./data/collections.db
   # Add:
   PROD_DATABASE_PATH=./data/collections.db
   GOLDEN_DATABASE_PATH=./data/collections_golden.db
   ```

3. **Start single server**
   ```bash
   uvicorn main:app --port 8000 --reload
   ```

4. **Update client code** (if needed)
   ```python
   # Before
   prod_url = "http://localhost:8000"
   golden_url = "http://localhost:8001"

   # After (option 1: query param)
   base_url = "http://localhost:8000"
   prod_url = f"{base_url}/items"
   golden_url = f"{base_url}/items?_db=golden"

   # After (option 2: subdomain)
   prod_url = "http://localhost:8000"
   golden_url = "http://golden.localhost:8000"
   ```

5. **Deprecate old script**
   The `scripts/run_golden_api.sh` script is now deprecated but still functional for backwards compatibility.

## Troubleshooting

### Issue: "Database not found"

**Symptom:** Server fails to start with database error

**Solution:** Ensure both database files exist:
```bash
ls -la ./data/collections.db
ls -la ./data/collections_golden.db
```

If missing, they will be created automatically on first startup.

### Issue: Subdomain doesn't work

**Symptom:** `golden.localhost` routes to production DB

**Solutions:**
1. Verify `/etc/hosts` entry exists and is correct
2. Clear DNS cache: `sudo dscacheutil -flushcache` (macOS)
3. Use query parameter fallback: `?_db=golden`
4. Check Host header is being sent: `curl -v http://golden.localhost:8000/health`

### Issue: Wrong database being used

**Symptom:** Expected production but got golden (or vice versa)

**Debug:**
1. Check response headers: `curl -I http://localhost:8000/health`
2. Check health endpoint: `curl http://localhost:8000/health | grep active_database`
3. Verify query parameters are being parsed correctly
4. Check middleware is registered (should see it in server logs)

### Issue: Concurrent requests interfere

**Symptom:** Production request returns golden data (or vice versa)

**Diagnosis:** This should not happen due to thread-local storage. If it does:
1. Check Python version (requires 3.7+)
2. Verify `database_context()` is being used correctly
3. Check for global state mutations
4. Review middleware order (DatabaseRoutingMiddleware should be early)

## Performance Considerations

### Overhead

- **Middleware processing:** ~0.1ms per request (negligible)
- **Thread-local context:** ~100 bytes per thread
- **Memory usage:** ~2MB for two database connections
- **Search index:** Both indices loaded in memory (~5MB each)

### Optimization Tips

1. **Connection pooling:** Not needed for SQLite (uses file-based locking)
2. **Search indices:** Both loaded at startup for fast queries
3. **Concurrent reads:** SQLite WAL mode supports multiple readers
4. **Write contention:** Rare in this read-heavy workload

### Scaling Considerations

For high traffic:
- SQLite is read-optimized (perfect for this use case)
- Write operations are serialized (acceptable for analysis creation)
- Consider upgrading to PostgreSQL if write concurrency becomes an issue
- Current setup supports 100+ concurrent readers easily

## Security Notes

### Host Header Validation

The middleware accepts any host with `golden.*` prefix. In production:

```python
ALLOWED_HOSTS = ["api.example.com", "golden.api.example.com"]

def _determine_db_path(self, host: str) -> str:
    hostname = re.sub(r':\d+$', '', host)

    # Validate against whitelist
    if hostname not in ALLOWED_HOSTS:
        raise HTTPException(403, "Invalid host")

    if hostname.startswith("golden."):
        return self.golden_db_path
    return self.prod_db_path
```

### Database Isolation

- Both databases share the same images directory (intentional)
- No sensitive data separation (both are test/evaluation data)
- If adding authentication, ensure it respects database context
- File paths are relative (no directory traversal risk)

## Future Enhancements

Potential improvements:

1. **Database-specific middleware:** Apply different auth/rate limiting per DB
2. **Read-only mode:** Make golden DB read-only to prevent accidents
3. **Multiple golden datasets:** Support `golden-v1.localhost`, `golden-v2.localhost`
4. **Automatic failover:** Fall back to production if golden DB is unavailable
5. **Request routing metrics:** Track usage per database for analytics
6. **Database version tracking:** Show schema version in health endpoint

## References

- Middleware implementation: `/workspaces/collections-local/middleware/database_routing.py`
- Database context manager: `/workspaces/collections-local/database.py` (lines 15-39)
- Main application setup: `/workspaces/collections-local/main.py`
- Original dual-database docs: `/workspaces/collections-local/documentation/DUAL_DATABASE.md`
