#!/usr/bin/env python3
"""
Quick check script - run this with AWS credentials configured.

Usage:
  export AWS_PROFILE=your-profile  # or configure credentials
  python claude-temp/check_user_content.py
"""

import boto3
import psycopg2
from psycopg2.extras import RealDictCursor

USER_ID = "94c844d8-10c1-70dd-80e3-4a88742efbb6"

# Get DATABASE_URL from Parameter Store
ssm = boto3.client('ssm', region_name='us-east-1')
response = ssm.get_parameter(Name='/collections/DATABASE_URL', WithDecryption=True)
db_url = response['Parameter']['Value']

print(f"Checking content for user: {USER_ID}\n")

with psycopg2.connect(db_url) as conn:
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        # 1. Items
        cursor.execute("SELECT COUNT(*) FROM items WHERE user_id = %s", (USER_ID,))
        items = cursor.fetchone()['count']
        print(f"1. Items: {items}")

        # 2. Analyses
        cursor.execute("SELECT COUNT(*) FROM analyses WHERE user_id = %s", (USER_ID,))
        analyses = cursor.fetchone()['count']
        print(f"2. Analyses: {analyses}")

        # 3. Embeddings
        cursor.execute("""
            SELECT COUNT(*) FROM langchain_pg_embedding e
            JOIN langchain_pg_collection c ON e.collection_id = c.uuid
            WHERE c.name = 'collections_vectors_prod' AND e.cmetadata->>'user_id' = %s
        """, (USER_ID,))
        embeddings = cursor.fetchone()['count']
        print(f"3. Embeddings: {embeddings}")

        # 4. All users with embeddings
        cursor.execute("""
            SELECT e.cmetadata->>'user_id' as uid, COUNT(*) as cnt
            FROM langchain_pg_embedding e
            JOIN langchain_pg_collection c ON e.collection_id = c.uuid
            WHERE c.name = 'collections_vectors_prod'
            GROUP BY uid
        """)
        print(f"\n4. All users with embeddings:")
        for row in cursor.fetchall():
            marker = " <-- TARGET USER" if row['uid'] == USER_ID else ""
            print(f"   {row['uid']}: {row['cnt']}{marker}")

        # Diagnosis
        print("\n" + "="*50)
        if items == 0:
            print("❌ USER HAS NO ITEMS - upload images first!")
        elif analyses == 0:
            print("❌ USER HAS ITEMS BUT NO ANALYSES - check analyzer Lambda")
        elif embeddings == 0:
            print("❌ USER HAS ANALYSES BUT NO EMBEDDINGS - check embedder Lambda")
        else:
            print("✅ User has content - search should work!")
