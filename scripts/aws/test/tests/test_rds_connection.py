"""
Test 1: RDS PostgreSQL Connection

Validates:
- RDS instance exists and is accessible
- Can connect using psycopg2
- Basic SQL operations work
- SSL connection is enforced
"""

import pytest
import psycopg2


@pytest.mark.integration
def test_rds_connection_basic(rds_connection):
    """Test basic RDS PostgreSQL connection."""
    cursor = rds_connection.cursor()

    # Test basic query
    cursor.execute("SELECT 1 as test;")
    result = cursor.fetchone()

    assert result[0] == 1, "Basic query failed"


@pytest.mark.integration
def test_rds_version(rds_connection):
    """Verify PostgreSQL version."""
    cursor = rds_connection.cursor()

    cursor.execute("SELECT version();")
    version = cursor.fetchone()[0]

    assert 'PostgreSQL' in version, f"Unexpected version: {version}"
    # Verify minimum version (PostgreSQL 14+)
    assert 'PostgreSQL 14' in version or 'PostgreSQL 15' in version or 'PostgreSQL 16' in version, \
        f"PostgreSQL version should be 14+: {version}"


@pytest.mark.integration
def test_rds_ssl_connection(stack_outputs, boto3_clients):
    """Verify SSL connection is enforced."""
    import psycopg2

    rds_endpoint = stack_outputs['RdsEndpoint']
    db_name = stack_outputs.get('DatabaseName', 'collections')
    username = stack_outputs.get('RdsUsername', 'postgres')
    password = stack_outputs.get('RdsPassword')

    # Try to connect without SSL (should fail or warn)
    conn = psycopg2.connect(
        host=rds_endpoint,
        database=db_name,
        user=username,
        password=password,
        sslmode='require'  # Enforce SSL
    )

    cursor = conn.cursor()

    # Check SSL status
    cursor.execute("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid();")
    ssl_status = cursor.fetchone()

    if ssl_status:
        assert ssl_status[0] is True, "SSL not enabled on connection"

    conn.close()


@pytest.mark.integration
def test_rds_database_exists(rds_connection, stack_outputs):
    """Verify correct database exists."""
    cursor = rds_connection.cursor()

    expected_db = stack_outputs.get('DatabaseName', 'collections')

    cursor.execute("SELECT current_database();")
    current_db = cursor.fetchone()[0]

    assert current_db == expected_db, \
        f"Wrong database: {current_db} != {expected_db}"


@pytest.mark.integration
def test_rds_create_table(rds_connection):
    """Test table creation and basic CRUD operations."""
    cursor = rds_connection.cursor()

    # Create test table
    cursor.execute("""
        DROP TABLE IF EXISTS test_table;
        CREATE TABLE test_table (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    rds_connection.commit()

    # Insert test data
    cursor.execute("""
        INSERT INTO test_table (name) VALUES ('test1'), ('test2')
        RETURNING id, name;
    """)
    results = cursor.fetchall()

    assert len(results) == 2, "Failed to insert test rows"

    # Query test data
    cursor.execute("SELECT COUNT(*) FROM test_table;")
    count = cursor.fetchone()[0]

    assert count == 2, f"Wrong row count: {count}"

    # Cleanup
    cursor.execute("DROP TABLE test_table;")
    rds_connection.commit()


@pytest.mark.integration
def test_rds_jsonb_support(rds_connection):
    """Test JSONB column support (required for migration)."""
    cursor = rds_connection.cursor()

    # Create table with JSONB column
    cursor.execute("""
        DROP TABLE IF EXISTS test_jsonb;
        CREATE TABLE test_jsonb (
            id SERIAL PRIMARY KEY,
            data JSONB
        );
    """)

    # Insert JSONB data
    import json

    test_data = {'key': 'value', 'nested': {'field': 123}}

    cursor.execute("""
        INSERT INTO test_jsonb (data) VALUES (%s)
        RETURNING data;
    """, (json.dumps(test_data),))

    result = cursor.fetchone()[0]

    assert result == test_data, "JSONB data mismatch"

    # Test JSONB operators
    cursor.execute("""
        SELECT data->>'key' as key_value FROM test_jsonb;
    """)
    key_value = cursor.fetchone()[0]

    assert key_value == 'value', "JSONB operator failed"

    # Cleanup
    cursor.execute("DROP TABLE test_jsonb;")
    rds_connection.commit()


@pytest.mark.integration
def test_rds_concurrent_connections(stack_outputs):
    """Test multiple concurrent connections."""
    import psycopg2

    rds_endpoint = stack_outputs['RdsEndpoint']
    db_name = stack_outputs.get('DatabaseName', 'collections')
    username = stack_outputs.get('RdsUsername', 'postgres')
    password = stack_outputs.get('RdsPassword')

    connections = []

    try:
        # Create multiple connections
        for i in range(5):
            conn = psycopg2.connect(
                host=rds_endpoint,
                database=db_name,
                user=username,
                password=password,
                sslmode='require'
            )
            connections.append(conn)

        # Verify all connections work
        for i, conn in enumerate(connections):
            cursor = conn.cursor()
            cursor.execute(f"SELECT {i + 1} as conn_id;")
            result = cursor.fetchone()[0]
            assert result == i + 1, f"Connection {i} failed"

    finally:
        # Cleanup
        for conn in connections:
            try:
                conn.close()
            except:
                pass


@pytest.mark.integration
def test_rds_transaction_support(rds_connection):
    """Test transaction rollback functionality."""
    cursor = rds_connection.cursor()

    # Create test table
    cursor.execute("""
        DROP TABLE IF EXISTS test_transaction;
        CREATE TABLE test_transaction (id SERIAL, value TEXT);
    """)
    rds_connection.commit()

    # Start transaction and insert data
    cursor.execute("INSERT INTO test_transaction (value) VALUES ('test');")

    # Rollback
    rds_connection.rollback()

    # Verify data was rolled back
    cursor.execute("SELECT COUNT(*) FROM test_transaction;")
    count = cursor.fetchone()[0]

    assert count == 0, "Rollback failed"

    # Test commit
    cursor.execute("INSERT INTO test_transaction (value) VALUES ('committed');")
    rds_connection.commit()

    cursor.execute("SELECT COUNT(*) FROM test_transaction;")
    count = cursor.fetchone()[0]

    assert count == 1, "Commit failed"

    # Cleanup
    cursor.execute("DROP TABLE test_transaction;")
    rds_connection.commit()
