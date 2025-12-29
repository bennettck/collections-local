#!/usr/bin/env python3
"""
Debug script for search endpoint returning no results.

This script checks:
1. Whether the user has any items/analyses in the database
2. Whether embeddings exist in langchain_pg_embedding table for the user
3. Whether the deployed Lambda matches the latest code

Run this script with AWS credentials configured.
"""

import os
import sys
import json
import boto3
from datetime import datetime

# User info from JWT token
USER_ID = "94c844d8-10c1-70dd-80e3-4a88742efbb6"
USER_EMAIL = "testuser1@example.com"

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check_database_content():
    """Check if user has content in the database."""
    print("\n" + "="*60)
    print("1. CHECKING DATABASE CONTENT FOR USER")
    print("="*60)

    try:
        from database_orm.connection import init_connection, get_session
        from database_orm.models import Item, Analysis
        from sqlalchemy import select, func

        # Initialize connection
        init_connection()

        with get_session() as session:
            # Count items for user
            item_count = session.scalar(
                select(func.count(Item.id)).where(Item.user_id == USER_ID)
            )
            print(f"\nItems for user {USER_ID}: {item_count}")

            # Count analyses for user
            analysis_count = session.scalar(
                select(func.count(Analysis.id)).where(Analysis.user_id == USER_ID)
            )
            print(f"Analyses for user {USER_ID}: {analysis_count}")

            # Get sample items
            if item_count > 0:
                items = session.execute(
                    select(Item.id, Item.filename, Item.created_at)
                    .where(Item.user_id == USER_ID)
                    .limit(5)
                ).fetchall()
                print(f"\nSample items:")
                for item in items:
                    print(f"  - {item.id}: {item.filename} ({item.created_at})")
            else:
                print("\n❌ NO ITEMS FOUND FOR USER - This is the root cause!")
                print("   User needs to upload images before search will return results.")

    except Exception as e:
        print(f"\n❌ Database error: {e}")
        print("   Make sure DATABASE_URL or DB_SECRET_ARN is set")


def check_vector_embeddings():
    """Check if embeddings exist in langchain_pg_embedding table."""
    print("\n" + "="*60)
    print("2. CHECKING VECTOR EMBEDDINGS")
    print("="*60)

    try:
        from database_orm.connection import get_connection_string
        import psycopg2
        from psycopg2.extras import RealDictCursor

        conn_str = get_connection_string()

        with psycopg2.connect(conn_str) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # Check collection exists
                cursor.execute("""
                    SELECT name, uuid
                    FROM langchain_pg_collection
                    WHERE name LIKE 'collections_vectors%'
                """)
                collections = cursor.fetchall()
                print(f"\nCollections found:")
                for col in collections:
                    print(f"  - {col['name']} (uuid: {col['uuid'][:8]}...)")

                # Check embeddings for this user
                cursor.execute("""
                    SELECT COUNT(*) as count
                    FROM langchain_pg_embedding e
                    JOIN langchain_pg_collection c ON e.collection_id = c.uuid
                    WHERE c.name = 'collections_vectors_prod'
                      AND e.cmetadata->>'user_id' = %s
                """, (USER_ID,))
                result = cursor.fetchone()
                embedding_count = result['count']
                print(f"\nEmbeddings for user in collections_vectors_prod: {embedding_count}")

                if embedding_count == 0:
                    print("\n❌ NO EMBEDDINGS FOUND FOR USER")
                    print("   Possible causes:")
                    print("   1. User hasn't uploaded any images")
                    print("   2. Embedder Lambda didn't process uploads")
                    print("   3. Embeddings stored with wrong user_id")

                    # Check if there are ANY embeddings in the collection
                    cursor.execute("""
                        SELECT COUNT(*) as count
                        FROM langchain_pg_embedding e
                        JOIN langchain_pg_collection c ON e.collection_id = c.uuid
                        WHERE c.name = 'collections_vectors_prod'
                    """)
                    total = cursor.fetchone()['count']
                    print(f"\n   Total embeddings in collection: {total}")

                    # Sample some user_ids to see what's there
                    if total > 0:
                        cursor.execute("""
                            SELECT DISTINCT e.cmetadata->>'user_id' as user_id
                            FROM langchain_pg_embedding e
                            JOIN langchain_pg_collection c ON e.collection_id = c.uuid
                            WHERE c.name = 'collections_vectors_prod'
                            LIMIT 5
                        """)
                        users = cursor.fetchall()
                        print(f"   User IDs in collection:")
                        for u in users:
                            print(f"     - {u['user_id']}")
                else:
                    print(f"\n✅ Found {embedding_count} embeddings for user")

                    # Get sample metadata
                    cursor.execute("""
                        SELECT e.cmetadata
                        FROM langchain_pg_embedding e
                        JOIN langchain_pg_collection c ON e.collection_id = c.uuid
                        WHERE c.name = 'collections_vectors_prod'
                          AND e.cmetadata->>'user_id' = %s
                        LIMIT 3
                    """, (USER_ID,))
                    samples = cursor.fetchall()
                    print(f"\nSample embedding metadata:")
                    for s in samples:
                        meta = s['cmetadata']
                        print(f"  - item_id: {meta.get('item_id')}, category: {meta.get('category')}")

    except Exception as e:
        print(f"\n❌ Error checking embeddings: {e}")


def check_lambda_deployment():
    """Check if Lambda is deployed with latest code."""
    print("\n" + "="*60)
    print("3. CHECKING LAMBDA DEPLOYMENT")
    print("="*60)

    try:
        lambda_client = boto3.client('lambda', region_name='us-east-1')

        # Check API Lambda
        functions_to_check = [
            'collections-api-function',
            'collections-embedder-function',
            'CollectionsApiStack-ApiFunction'  # Alternative name
        ]

        for func_name in functions_to_check:
            try:
                response = lambda_client.get_function(FunctionName=func_name)
                config = response['Configuration']
                print(f"\n{func_name}:")
                print(f"  Last Modified: {config['LastModified']}")
                print(f"  Runtime: {config.get('Runtime', 'N/A')}")
                print(f"  Memory: {config.get('MemorySize', 'N/A')} MB")

                # Check if it's recent (within last 24 hours)
                modified = datetime.fromisoformat(config['LastModified'].replace('Z', '+00:00'))
                if (datetime.now(modified.tzinfo) - modified).total_seconds() > 86400:
                    print(f"  ⚠️ Lambda was last modified more than 24 hours ago")
                    print(f"     Consider redeploying: cd infrastructure && cdk deploy --all")
            except lambda_client.exceptions.ResourceNotFoundException:
                continue
            except Exception as e:
                print(f"\n  Error checking {func_name}: {e}")

    except Exception as e:
        print(f"\n❌ Error checking Lambda: {e}")
        print("   Make sure AWS credentials are configured")


def check_cloudwatch_logs():
    """Check recent CloudWatch logs for errors."""
    print("\n" + "="*60)
    print("4. CHECKING CLOUDWATCH LOGS FOR ERRORS")
    print("="*60)

    try:
        logs_client = boto3.client('logs', region_name='us-east-1')

        log_groups = [
            '/aws/lambda/collections-api-function',
            '/aws/lambda/collections-embedder-function'
        ]

        for log_group in log_groups:
            try:
                # Get recent log events
                response = logs_client.filter_log_events(
                    logGroupName=log_group,
                    filterPattern='ERROR',
                    limit=5
                )

                events = response.get('events', [])
                if events:
                    print(f"\n{log_group}:")
                    print(f"  Found {len(events)} recent ERROR events:")
                    for event in events[:3]:
                        msg = event['message'][:200] + '...' if len(event['message']) > 200 else event['message']
                        print(f"    - {msg}")
                else:
                    print(f"\n{log_group}: No recent errors ✅")

            except logs_client.exceptions.ResourceNotFoundException:
                print(f"\n{log_group}: Log group not found")
            except Exception as e:
                print(f"\n{log_group}: Error: {e}")

    except Exception as e:
        print(f"\n❌ Error checking logs: {e}")


def main():
    print("="*60)
    print("DEBUG: Search Endpoint Returning No Results")
    print("="*60)
    print(f"\nUser ID: {USER_ID}")
    print(f"Email: {USER_EMAIL}")

    # Check database content
    check_database_content()

    # Check vector embeddings
    check_vector_embeddings()

    # Check Lambda deployment
    check_lambda_deployment()

    # Check CloudWatch logs
    check_cloudwatch_logs()

    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print("""
Most likely causes of empty search results:

1. USER HAS NO CONTENT
   - User needs to upload images via POST /items/upload
   - After upload, images need to go through the processing pipeline:
     Image Upload -> Analyzer Lambda -> Embedder Lambda

2. EMBEDDINGS NOT STORED
   - Check if Embedder Lambda was triggered after upload
   - Check CloudWatch logs for embedding errors
   - Verify embeddings exist in langchain_pg_embedding table

3. LAMBDA NOT DEPLOYED
   - If Lambda was modified locally but not deployed, run:
     cd infrastructure && cdk deploy --all

4. COLLECTION NAME MISMATCH
   - Verify embedder uses "collections_vectors_prod" collection
   - This was fixed in commit 57a570f

To test the search with a fresh token:
  python scripts/test_api_access.py --user testuser1
""")


if __name__ == '__main__':
    main()
