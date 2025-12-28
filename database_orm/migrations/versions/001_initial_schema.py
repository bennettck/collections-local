"""Initial schema with pgvector support

Revision ID: 001
Revises:
Create Date: 2025-12-27

This migration creates the initial database schema with:
- pgvector extension for vector embeddings
- items, analyses, and embeddings tables
- Full-text search support with tsvector
- Proper indexes for performance
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create initial schema with pgvector extension and all tables.
    """
    # Enable pgvector extension (PostgreSQL only)
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    # Create items table
    op.create_table(
        'items',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('original_filename', sa.String(), nullable=True),
        sa.Column('file_path', sa.String(), nullable=False),
        sa.Column('file_size', sa.BigInteger(), nullable=True),
        sa.Column('mime_type', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_items_user_id', 'items', ['user_id'])

    # Create analyses table
    op.create_table(
        'analyses',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('item_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('summary', sa.String(), nullable=True),
        sa.Column('raw_response', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('provider_used', sa.String(), nullable=True),
        sa.Column('model_used', sa.String(), nullable=True),
        sa.Column('trace_id', sa.String(), nullable=True),
        sa.Column('search_vector', postgresql.TSVECTOR(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['item_id'], ['items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_analyses_item_id', 'analyses', ['item_id'])
    op.create_index('ix_analyses_user_id', 'analyses', ['user_id'])
    op.create_index('ix_analyses_category', 'analyses', ['category'])
    op.create_index('idx_analyses_item_version', 'analyses', ['item_id', sa.text('version DESC')])
    op.create_index('idx_analyses_search_vector', 'analyses', ['search_vector'], postgresql_using='gin')

    # Create embeddings table with pgvector
    op.create_table(
        'embeddings',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('item_id', sa.String(), nullable=False),
        sa.Column('analysis_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('vector', postgresql.ARRAY(sa.Float(), dimensions=1024), nullable=True),  # Will be converted to vector type
        sa.Column('embedding_model', sa.String(), nullable=False),
        sa.Column('embedding_dimensions', sa.Integer(), nullable=False),
        sa.Column('embedding_source', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['item_id'], ['items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_embeddings_item_id', 'embeddings', ['item_id'])
    op.create_index('ix_embeddings_analysis_id', 'embeddings', ['analysis_id'])
    op.create_index('ix_embeddings_user_id', 'embeddings', ['user_id'])

    # Convert vector column to proper pgvector type
    op.execute('ALTER TABLE embeddings ALTER COLUMN vector TYPE vector(1024) USING vector::vector(1024)')

    # Create tsvector update function for full-text search
    op.execute("""
        CREATE OR REPLACE FUNCTION analyses_search_vector_update() RETURNS trigger AS $$
        DECLARE
            search_text TEXT;
            image_details JSONB;
            media_metadata JSONB;
        BEGIN
            -- Extract fields from raw_response JSONB
            search_text := '';

            -- Add summary
            IF NEW.raw_response->>'summary' IS NOT NULL THEN
                search_text := search_text || ' ' || NEW.raw_response->>'summary';
            END IF;

            -- Add headline
            IF NEW.raw_response->>'headline' IS NOT NULL THEN
                search_text := search_text || ' ' || NEW.raw_response->>'headline';
            END IF;

            -- Add category
            IF NEW.raw_response->>'category' IS NOT NULL THEN
                search_text := search_text || ' ' || NEW.raw_response->>'category';
            END IF;

            -- Add subcategories (array)
            IF NEW.raw_response->'subcategories' IS NOT NULL THEN
                search_text := search_text || ' ' || array_to_string(
                    ARRAY(SELECT jsonb_array_elements_text(NEW.raw_response->'subcategories')),
                    ' '
                );
            END IF;

            -- Extract image_details
            image_details := NEW.raw_response->'image_details';
            IF image_details IS NOT NULL THEN
                -- Add extracted_text (can be string or array)
                IF jsonb_typeof(image_details->'extracted_text') = 'array' THEN
                    search_text := search_text || ' ' || array_to_string(
                        ARRAY(SELECT jsonb_array_elements_text(image_details->'extracted_text')),
                        ' '
                    );
                ELSIF image_details->>'extracted_text' IS NOT NULL THEN
                    search_text := search_text || ' ' || image_details->>'extracted_text';
                END IF;

                -- Add other image_details fields
                IF image_details->>'key_interest' IS NOT NULL THEN
                    search_text := search_text || ' ' || image_details->>'key_interest';
                END IF;

                IF image_details->'themes' IS NOT NULL THEN
                    search_text := search_text || ' ' || array_to_string(
                        ARRAY(SELECT jsonb_array_elements_text(image_details->'themes')),
                        ' '
                    );
                END IF;

                IF image_details->'objects' IS NOT NULL THEN
                    search_text := search_text || ' ' || array_to_string(
                        ARRAY(SELECT jsonb_array_elements_text(image_details->'objects')),
                        ' '
                    );
                END IF;

                IF image_details->'emotions' IS NOT NULL THEN
                    search_text := search_text || ' ' || array_to_string(
                        ARRAY(SELECT jsonb_array_elements_text(image_details->'emotions')),
                        ' '
                    );
                END IF;

                IF image_details->'vibes' IS NOT NULL THEN
                    search_text := search_text || ' ' || array_to_string(
                        ARRAY(SELECT jsonb_array_elements_text(image_details->'vibes')),
                        ' '
                    );
                END IF;
            END IF;

            -- Extract media_metadata
            media_metadata := NEW.raw_response->'media_metadata';
            IF media_metadata IS NOT NULL THEN
                IF media_metadata->'location_tags' IS NOT NULL THEN
                    search_text := search_text || ' ' || array_to_string(
                        ARRAY(SELECT jsonb_array_elements_text(media_metadata->'location_tags')),
                        ' '
                    );
                END IF;

                IF media_metadata->'hashtags' IS NOT NULL THEN
                    search_text := search_text || ' ' || array_to_string(
                        ARRAY(SELECT jsonb_array_elements_text(media_metadata->'hashtags')),
                        ' '
                    );
                END IF;
            END IF;

            -- Update search_vector using PostgreSQL's to_tsvector
            NEW.search_vector := to_tsvector('english', search_text);

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Create trigger to automatically update search_vector
    op.execute("""
        CREATE TRIGGER analyses_search_vector_trigger
        BEFORE INSERT OR UPDATE OF raw_response ON analyses
        FOR EACH ROW
        EXECUTE FUNCTION analyses_search_vector_update();
    """)


def downgrade() -> None:
    """
    Drop all tables and extensions.
    """
    # Drop trigger and function
    op.execute('DROP TRIGGER IF EXISTS analyses_search_vector_trigger ON analyses')
    op.execute('DROP FUNCTION IF EXISTS analyses_search_vector_update()')

    # Drop tables (in reverse order due to foreign keys)
    op.drop_table('embeddings')
    op.drop_table('analyses')
    op.drop_table('items')

    # Drop pgvector extension
    op.execute('DROP EXTENSION IF EXISTS vector')
