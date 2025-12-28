"""
Database module router for Collections Local.

Routes to appropriate backend based on environment:
- PostgreSQL (database_sqlalchemy) for production
- SQLite (database_sqlite_legacy) for local development
"""

import os
import warnings

# Determine backend
_use_postgres = bool(
    os.getenv("DB_SECRET_ARN") or
    os.getenv("DATABASE_URL", "").startswith("postgresql")
)

if _use_postgres:
    # Production: Use PostgreSQL via SQLAlchemy
    from database_sqlalchemy import *
else:
    # Local development: Use SQLite (deprecated)
    warnings.warn(
        "Using SQLite backend for local development. "
        "Set DATABASE_URL to a PostgreSQL URL for production behavior.",
        UserWarning
    )
    from database_sqlite_legacy import *
