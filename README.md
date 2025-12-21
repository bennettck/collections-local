# collections-local

A local API server for managing and analyzing image collections with dual database support for production and golden dataset evaluation.

## Database Routing

The API supports two databases accessed via host-based routing:

- **Production DB** (full collection): `http://localhost:8000`
- **Golden DB** (evaluation subset): `http://golden.localhost:8000`

### Local Setup

Add to `/etc/hosts`:
```
127.0.0.1    golden.localhost
```

### Testing with Query Parameters

For quick testing without DNS configuration:
```bash
# Production database
curl http://localhost:8000/health

# Golden database
curl http://localhost:8000/health?_db=golden
```

### Verifying Active Database

Check the `X-Database-Context` response header or `active_database` field in `/health` response:

```bash
# Check response headers
curl -I http://localhost:8000/health

# Check health endpoint
curl http://localhost:8000/health | python3 -m json.tool
```

## Running the Server

```bash
uvicorn main:app --port 8000 --reload
```

The server will automatically initialize both databases on startup.

## Environment Variables

Configure in `.env`:
```env
PROD_DATABASE_PATH=./data/collections.db
GOLDEN_DATABASE_PATH=./data/collections_golden.db
IMAGES_PATH=./data/images
```

See `.env.example` for full configuration options.