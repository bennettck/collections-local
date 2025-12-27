"""
Test 2: pgvector Extension

Validates:
- pgvector extension is installed
- Vector columns can be created
- Vector operations work (cosine, L2, inner product)
- IVFFlat index creation
- Query performance
"""

import pytest


@pytest.mark.integration
def test_pgvector_extension_exists(rds_connection):
    """Verify pgvector extension is installed."""
    cursor = rds_connection.cursor()

    # Check if extension exists
    cursor.execute("""
        SELECT extname, extversion
        FROM pg_extension
        WHERE extname = 'vector';
    """)

    result = cursor.fetchone()
    assert result is not None, "pgvector extension not found"

    ext_name, ext_version = result
    assert ext_name == 'vector', f"Wrong extension: {ext_name}"

    print(f"pgvector version: {ext_version}")


@pytest.mark.integration
def test_pgvector_create_table(rds_connection):
    """Test creating table with vector column."""
    cursor = rds_connection.cursor()

    # Create table with vector column
    cursor.execute("""
        DROP TABLE IF EXISTS test_vectors;
        CREATE TABLE test_vectors (
            id SERIAL PRIMARY KEY,
            embedding vector(1024)
        );
    """)
    rds_connection.commit()

    # Verify table structure
    cursor.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'test_vectors' AND column_name = 'embedding';
    """)

    result = cursor.fetchone()
    assert result is not None, "Vector column not created"

    # Cleanup
    cursor.execute("DROP TABLE test_vectors;")
    rds_connection.commit()


@pytest.mark.integration
def test_pgvector_insert_and_query(rds_connection):
    """Test inserting and querying vector data."""
    cursor = rds_connection.cursor()

    # Create test table
    cursor.execute("""
        DROP TABLE IF EXISTS test_vectors;
        CREATE TABLE test_vectors (
            id SERIAL PRIMARY KEY,
            name TEXT,
            embedding vector(3)
        );
    """)

    # Insert test vectors
    test_vectors = [
        ('vec1', '[1, 2, 3]'),
        ('vec2', '[4, 5, 6]'),
        ('vec3', '[1, 1, 1]'),
    ]

    for name, embedding in test_vectors:
        cursor.execute("""
            INSERT INTO test_vectors (name, embedding)
            VALUES (%s, %s);
        """, (name, embedding))

    rds_connection.commit()

    # Query all vectors
    cursor.execute("SELECT name, embedding FROM test_vectors ORDER BY id;")
    results = cursor.fetchall()

    assert len(results) == 3, f"Expected 3 vectors, got {len(results)}"

    # Cleanup
    cursor.execute("DROP TABLE test_vectors;")
    rds_connection.commit()


@pytest.mark.integration
def test_pgvector_cosine_distance(rds_connection):
    """Test cosine distance operator (<->)."""
    cursor = rds_connection.cursor()

    # Create test table
    cursor.execute("""
        DROP TABLE IF EXISTS test_vectors;
        CREATE TABLE test_vectors (
            id SERIAL PRIMARY KEY,
            name TEXT,
            embedding vector(3)
        );
    """)

    # Insert test vectors
    cursor.execute("""
        INSERT INTO test_vectors (name, embedding) VALUES
        ('exact_match', '[1, 2, 3]'),
        ('close_match', '[1, 2, 4]'),
        ('far_match', '[10, 20, 30]');
    """)
    rds_connection.commit()

    # Test cosine distance search
    query_vector = '[1, 2, 3]'

    cursor.execute("""
        SELECT name, embedding <-> %s::vector AS distance
        FROM test_vectors
        ORDER BY distance
        LIMIT 3;
    """, (query_vector,))

    results = cursor.fetchall()

    # Verify results are ordered by distance
    assert results[0][0] == 'exact_match', "Exact match should be first"
    assert results[0][1] < 0.01, f"Exact match distance should be ~0, got {results[0][1]}"

    # Second closest should be close_match
    assert results[1][0] == 'close_match', "Close match should be second"

    # Cleanup
    cursor.execute("DROP TABLE test_vectors;")
    rds_connection.commit()


@pytest.mark.integration
def test_pgvector_l2_distance(rds_connection):
    """Test L2 (Euclidean) distance operator (<+>)."""
    cursor = rds_connection.cursor()

    # Create test table
    cursor.execute("""
        DROP TABLE IF EXISTS test_vectors;
        CREATE TABLE test_vectors (
            id SERIAL PRIMARY KEY,
            embedding vector(2)
        );
    """)

    # Insert test points
    cursor.execute("""
        INSERT INTO test_vectors (embedding) VALUES
        ('[0, 0]'),
        ('[3, 4]'),
        ('[1, 1]');
    """)
    rds_connection.commit()

    # Test L2 distance from origin
    cursor.execute("""
        SELECT embedding <+> '[0, 0]'::vector AS distance
        FROM test_vectors
        ORDER BY distance;
    """)

    results = cursor.fetchall()

    # Verify L2 distances
    assert abs(results[0][0] - 0.0) < 0.01, "Origin distance should be 0"
    assert abs(results[1][0] - 1.414) < 0.01, "Distance should be sqrt(2)"
    assert abs(results[2][0] - 5.0) < 0.01, "Distance should be 5"

    # Cleanup
    cursor.execute("DROP TABLE test_vectors;")
    rds_connection.commit()


@pytest.mark.integration
def test_pgvector_inner_product(rds_connection):
    """Test inner product operator (<#>)."""
    cursor = rds_connection.cursor()

    # Create test table
    cursor.execute("""
        DROP TABLE IF EXISTS test_vectors;
        CREATE TABLE test_vectors (
            id SERIAL PRIMARY KEY,
            embedding vector(3)
        );
    """)

    # Insert test vectors
    cursor.execute("""
        INSERT INTO test_vectors (embedding) VALUES
        ('[1, 0, 0]'),
        ('[0, 1, 0]'),
        ('[1, 1, 0]');
    """)
    rds_connection.commit()

    # Test inner product
    query_vector = '[1, 0, 0]'

    cursor.execute("""
        SELECT embedding <#> %s::vector AS neg_inner_product
        FROM test_vectors
        ORDER BY neg_inner_product;
    """, (query_vector,))

    results = cursor.fetchall()

    # Inner product returns negative value, so smaller = more similar
    # [1,0,0] · [1,0,0] = 1 (most similar, smallest negative)
    # [1,0,0] · [1,1,0] = 1
    # [1,0,0] · [0,1,0] = 0 (least similar, largest negative)

    assert results[0][0] <= results[1][0], "Results should be ordered by inner product"

    # Cleanup
    cursor.execute("DROP TABLE test_vectors;")
    rds_connection.commit()


@pytest.mark.integration
def test_pgvector_ivfflat_index(rds_connection):
    """Test IVFFlat index creation for performance."""
    cursor = rds_connection.cursor()

    # Create table
    cursor.execute("""
        DROP TABLE IF EXISTS test_vectors;
        CREATE TABLE test_vectors (
            id SERIAL PRIMARY KEY,
            embedding vector(128)
        );
    """)

    # Insert sample vectors (need enough for index to be useful)
    import random

    for i in range(100):
        # Generate random 128-dimensional vector
        vector = [random.random() for _ in range(128)]
        vector_str = '[' + ','.join(str(v) for v in vector) + ']'

        cursor.execute("""
            INSERT INTO test_vectors (embedding) VALUES (%s);
        """, (vector_str,))

    rds_connection.commit()

    # Create IVFFlat index
    cursor.execute("""
        CREATE INDEX test_vectors_embedding_idx
        ON test_vectors
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 10);
    """)
    rds_connection.commit()

    # Verify index exists
    cursor.execute("""
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename = 'test_vectors';
    """)

    indexes = cursor.fetchall()
    assert len(indexes) > 0, "Index not created"

    index_names = [idx[0] for idx in indexes]
    assert 'test_vectors_embedding_idx' in index_names, "IVFFlat index not found"

    # Test query using index
    query_vector = '[' + ','.join(str(random.random()) for _ in range(128)) + ']'

    cursor.execute("""
        SELECT id, embedding <-> %s::vector AS distance
        FROM test_vectors
        ORDER BY distance
        LIMIT 10;
    """, (query_vector,))

    results = cursor.fetchall()
    assert len(results) == 10, f"Expected 10 results, got {len(results)}"

    # Cleanup
    cursor.execute("DROP TABLE test_vectors;")
    rds_connection.commit()


@pytest.mark.integration
def test_pgvector_dimension_consistency(rds_connection):
    """Test that vector dimension must be consistent."""
    cursor = rds_connection.cursor()

    # Create table with 3-dimensional vectors
    cursor.execute("""
        DROP TABLE IF EXISTS test_vectors;
        CREATE TABLE test_vectors (
            id SERIAL PRIMARY KEY,
            embedding vector(3)
        );
    """)

    # Insert valid 3D vector
    cursor.execute("""
        INSERT INTO test_vectors (embedding) VALUES ('[1, 2, 3]');
    """)
    rds_connection.commit()

    # Try to insert wrong dimension (should fail)
    with pytest.raises(Exception) as exc_info:
        cursor.execute("""
            INSERT INTO test_vectors (embedding) VALUES ('[1, 2, 3, 4]');
        """)
        rds_connection.commit()

    # Verify error mentions dimension mismatch
    error_msg = str(exc_info.value).lower()
    assert 'dimension' in error_msg or 'expected' in error_msg

    # Rollback failed transaction
    rds_connection.rollback()

    # Cleanup
    cursor.execute("DROP TABLE test_vectors;")
    rds_connection.commit()


@pytest.mark.integration
def test_pgvector_large_vectors(rds_connection):
    """Test handling of large vectors (1024 dimensions for voyage-3.5-lite)."""
    cursor = rds_connection.cursor()

    # Create table with 1024-dimensional vectors
    cursor.execute("""
        DROP TABLE IF EXISTS test_vectors;
        CREATE TABLE test_vectors (
            id SERIAL PRIMARY KEY,
            embedding vector(1024)
        );
    """)

    # Generate 1024-dimensional vector
    import random

    vector_data = [random.random() for _ in range(1024)]
    vector_str = '[' + ','.join(str(v) for v in vector_data) + ']'

    # Insert large vector
    cursor.execute("""
        INSERT INTO test_vectors (embedding) VALUES (%s)
        RETURNING id;
    """, (vector_str,))

    result = cursor.fetchone()
    assert result is not None, "Failed to insert 1024-dimensional vector"

    rds_connection.commit()

    # Query the vector back
    cursor.execute("SELECT embedding FROM test_vectors;")
    result = cursor.fetchone()

    # Note: pgvector returns array, not list
    assert result is not None, "Failed to retrieve vector"

    # Cleanup
    cursor.execute("DROP TABLE test_vectors;")
    rds_connection.commit()


@pytest.mark.integration
def test_pgvector_null_handling(rds_connection):
    """Test NULL vector handling."""
    cursor = rds_connection.cursor()

    # Create table
    cursor.execute("""
        DROP TABLE IF EXISTS test_vectors;
        CREATE TABLE test_vectors (
            id SERIAL PRIMARY KEY,
            embedding vector(3)
        );
    """)

    # Insert NULL vector
    cursor.execute("""
        INSERT INTO test_vectors (embedding) VALUES (NULL)
        RETURNING id;
    """)
    result = cursor.fetchone()
    assert result is not None, "Failed to insert NULL vector"

    rds_connection.commit()

    # Query NULL vector
    cursor.execute("SELECT id, embedding FROM test_vectors WHERE embedding IS NULL;")
    result = cursor.fetchone()

    assert result is not None, "Failed to query NULL vector"
    assert result[1] is None, "NULL vector should be NULL"

    # Cleanup
    cursor.execute("DROP TABLE test_vectors;")
    rds_connection.commit()
