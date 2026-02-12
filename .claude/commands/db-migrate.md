---
description: Create database migrations for PostgreSQL (Alembic) and Neo4j schema changes
---

# Database Migration

Create and manage database migrations for QPrisma's PostgreSQL and Neo4j databases.

## Usage
```
/db-migrate [--db postgres|neo4j] [--action create|upgrade|downgrade|status]
```

## Instructions

When creating a database migration, follow these steps:

### PostgreSQL (Alembic)

1. Create migration with: `cd backend && alembic revision --autogenerate -m "<description>"`
2. Review the generated file in `backend/alembic/versions/`
3. Ensure both `upgrade()` and `downgrade()` are implemented
4. Always add indexes for foreign keys and frequently-queried columns
5. Use `datetime.now(UTC)` for timestamps (never `datetime.utcnow()`)
6. Run with: `alembic upgrade head`

**QPrisma table conventions:**
```python
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade() -> None:
    op.create_table(
        'processing_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('media_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('media.id'), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, default='pending'),
        sa.Column('config', postgresql.JSONB, nullable=True),
        sa.Column('progress', sa.Integer, default=0),
        sa.Column('error', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index('ix_processing_jobs_status', 'processing_jobs', ['status'])
    op.create_index('ix_processing_jobs_media_id', 'processing_jobs', ['media_id'])

def downgrade() -> None:
    op.drop_index('ix_processing_jobs_media_id')
    op.drop_index('ix_processing_jobs_status')
    op.drop_table('processing_jobs')
```

### Neo4j (Script-based)

Create migration scripts at `backend/migrations/neo4j/NNN_description.py` following this pattern:

```python
"""Neo4j Migration: Description"""
from neo4j import GraphDatabase

MIGRATION_ID = "NNN_description"

def upgrade(driver):
    with driver.session() as session:
        # Constraints (unique IDs for all node types)
        session.run("""
            CREATE CONSTRAINT video_id IF NOT EXISTS
            FOR (v:Video) REQUIRE v.id IS UNIQUE
        """)
        # Indexes for query performance
        session.run("""
            CREATE INDEX frame_timestamp IF NOT EXISTS
            FOR (f:Frame) ON (f.media_id, f.timestamp)
        """)
        # Vector indexes (1536 dims for text-embedding-3-large)
        session.run("""
            CALL db.index.vector.createNodeIndex(
                'frame_embeddings', 'Frame', 'embedding', 1536, 'cosine'
            )
        """)
        # Full-text indexes
        session.run("""
            CREATE FULLTEXT INDEX frame_description_fulltext IF NOT EXISTS
            FOR (f:Frame) ON EACH [f.description]
        """)
        # Record migration
        session.run("MERGE (m:Migration {id: $id}) SET m.applied_at = datetime()", id=MIGRATION_ID)

def downgrade(driver):
    with driver.session() as session:
        session.run("DROP INDEX frame_timestamp IF EXISTS")
        session.run("DROP CONSTRAINT video_id IF EXISTS")
        session.run("MATCH (m:Migration {id: $id}) DELETE m", id=MIGRATION_ID)

def is_applied(driver) -> bool:
    with driver.session() as session:
        result = session.run("MATCH (m:Migration {id: $id}) RETURN m", id=MIGRATION_ID)
        return result.single() is not None
```

Run with: `python -m migrations.neo4j.runner upgrade`

## Checklist
- [ ] Migration file created with descriptive name
- [ ] `upgrade()` and `downgrade()` both implemented
- [ ] Indexes added for foreign keys and queried columns
- [ ] Migration tested locally (upgrade + downgrade)
- [ ] Data migration included if needed
