"""
Database migration script to add vector search tables.

This script uses the database module's functions which handle
sqlite-vec extension loading properly.
"""

import sys
import os

# Add parent directory to path to import database module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import init_db, init_vector_table


def migrate():
    """Add vector search tables to the database."""
    # This will add the embeddings table and indexes if they don't exist
    print("Creating embeddings table...")
    init_db()

    # This will create the vec_items virtual table
    print("Creating vec_items virtual table...")
    init_vector_table(embedding_dimensions=512)

    print("Migration completed successfully")

if __name__ == "__main__":
    migrate()
