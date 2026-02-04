# Database Migration

Manage database migrations for PostgreSQL and Neo4j schema changes.

## Usage
```
/db-migrate [--db postgres|neo4j] [--action create|upgrade|downgrade|status]
```

## PostgreSQL Migrations (Alembic)

### Setup Alembic
```bash
cd backend

# Install if not present
pip install alembic

# Initialize (first time only)
alembic init alembic

# Configure alembic.ini
# sqlalchemy.url = postgresql://qprisma:qprisma123@localhost:5432/qprisma
```

### Create Migration
```bash
# Auto-generate from model changes
alembic revision --autogenerate -m "Add processing_jobs table"

# Or create empty migration
alembic revision -m "Add custom index"
```

### Migration File Template
```python
"""Add processing_jobs table

Revision ID: abc123
Revises: previous_rev
Create Date: 2026-02-04 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'abc123'
down_revision = 'previous_rev'
branch_labels = None
depends_on = None


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

    # Add indexes
    op.create_index('ix_processing_jobs_status', 'processing_jobs', ['status'])
    op.create_index('ix_processing_jobs_media_id', 'processing_jobs', ['media_id'])


def downgrade() -> None:
    op.drop_index('ix_processing_jobs_media_id')
    op.drop_index('ix_processing_jobs_status')
    op.drop_table('processing_jobs')
```

### Run Migrations
```bash
# Upgrade to latest
alembic upgrade head

# Upgrade one revision
alembic upgrade +1

# Downgrade one revision
alembic downgrade -1

# Downgrade to specific revision
alembic downgrade abc123

# Check current revision
alembic current

# Show migration history
alembic history
```

### Common Migration Operations
```python
# Add column
def upgrade():
    op.add_column('media', sa.Column('duration', sa.Float, nullable=True))

def downgrade():
    op.drop_column('media', 'duration')

# Rename column
def upgrade():
    op.alter_column('media', 'name', new_column_name='title')

def downgrade():
    op.alter_column('media', 'title', new_column_name='name')

# Add index
def upgrade():
    op.create_index('ix_frames_timestamp', 'frames', ['media_id', 'timestamp'])

def downgrade():
    op.drop_index('ix_frames_timestamp')

# Add foreign key
def upgrade():
    op.create_foreign_key(
        'fk_frames_media',
        'frames', 'media',
        ['media_id'], ['id'],
        ondelete='CASCADE'
    )

def downgrade():
    op.drop_constraint('fk_frames_media', 'frames', type_='foreignkey')

# Modify column type
def upgrade():
    op.alter_column(
        'media',
        'description',
        type_=sa.Text,
        existing_type=sa.String(500)
    )

def downgrade():
    op.alter_column(
        'media',
        'description',
        type_=sa.String(500),
        existing_type=sa.Text
    )
```

## Neo4j Migrations

Neo4j doesn't have built-in migrations, so use a script-based approach.

### Migration Script Template
```python
# backend/migrations/neo4j/001_initial_schema.py
"""
Neo4j Migration: Initial Schema
Created: 2026-02-04
"""

from neo4j import GraphDatabase

MIGRATION_ID = "001_initial_schema"


def upgrade(driver):
    """Apply migration."""
    with driver.session() as session:
        # Create constraints
        session.run("""
            CREATE CONSTRAINT video_id IF NOT EXISTS
            FOR (v:Video) REQUIRE v.id IS UNIQUE
        """)

        session.run("""
            CREATE CONSTRAINT frame_id IF NOT EXISTS
            FOR (f:Frame) REQUIRE f.id IS UNIQUE
        """)

        session.run("""
            CREATE CONSTRAINT entity_id IF NOT EXISTS
            FOR (e:Entity) REQUIRE e.id IS UNIQUE
        """)

        # Create indexes
        session.run("""
            CREATE INDEX frame_timestamp IF NOT EXISTS
            FOR (f:Frame) ON (f.media_id, f.timestamp)
        """)

        # Create vector index
        session.run("""
            CALL db.index.vector.createNodeIndex(
                'frame_embeddings',
                'Frame',
                'embedding',
                1536,
                'cosine'
            )
        """)

        # Record migration
        session.run("""
            MERGE (m:Migration {id: $id})
            SET m.applied_at = datetime()
        """, id=MIGRATION_ID)

        print(f"Applied migration: {MIGRATION_ID}")


def downgrade(driver):
    """Rollback migration."""
    with driver.session() as session:
        session.run("DROP INDEX frame_timestamp IF EXISTS")
        session.run("DROP CONSTRAINT video_id IF EXISTS")
        session.run("DROP CONSTRAINT frame_id IF EXISTS")
        session.run("DROP CONSTRAINT entity_id IF EXISTS")

        session.run("""
            MATCH (m:Migration {id: $id}) DELETE m
        """, id=MIGRATION_ID)

        print(f"Rolled back migration: {MIGRATION_ID}")


def is_applied(driver) -> bool:
    """Check if migration is already applied."""
    with driver.session() as session:
        result = session.run("""
            MATCH (m:Migration {id: $id}) RETURN m
        """, id=MIGRATION_ID)
        return result.single() is not None
```

### Migration Runner
```python
# backend/migrations/neo4j/runner.py
"""Neo4j migration runner."""

import os
import importlib
from pathlib import Path
from neo4j import GraphDatabase


def get_driver():
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD"))
    )


def get_migrations():
    """Get all migration modules sorted by name."""
    migrations_dir = Path(__file__).parent
    migration_files = sorted(migrations_dir.glob("[0-9]*.py"))

    migrations = []
    for f in migration_files:
        if f.name != "runner.py":
            module_name = f.stem
            module = importlib.import_module(f".{module_name}", package="migrations.neo4j")
            migrations.append(module)

    return migrations


def upgrade():
    """Run all pending migrations."""
    driver = get_driver()

    for migration in get_migrations():
        if not migration.is_applied(driver):
            migration.upgrade(driver)

    driver.close()


def downgrade(steps: int = 1):
    """Rollback migrations."""
    driver = get_driver()

    applied = [m for m in get_migrations() if m.is_applied(driver)]
    for migration in reversed(applied[:steps]):
        migration.downgrade(driver)

    driver.close()


def status():
    """Show migration status."""
    driver = get_driver()

    print("\nNeo4j Migration Status:")
    print("-" * 50)

    for migration in get_migrations():
        applied = migration.is_applied(driver)
        status = "✓ Applied" if applied else "○ Pending"
        print(f"  {status}: {migration.MIGRATION_ID}")

    driver.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        status()
    elif sys.argv[1] == "upgrade":
        upgrade()
    elif sys.argv[1] == "downgrade":
        steps = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        downgrade(steps)
    elif sys.argv[1] == "status":
        status()
```

### Run Neo4j Migrations
```bash
# Check status
python -m migrations.neo4j.runner status

# Upgrade all
python -m migrations.neo4j.runner upgrade

# Downgrade one step
python -m migrations.neo4j.runner downgrade 1
```

## Common Neo4j Schema Changes

### Add New Node Type
```python
def upgrade(driver):
    with driver.session() as session:
        # Create constraint
        session.run("""
            CREATE CONSTRAINT activity_id IF NOT EXISTS
            FOR (a:Activity) REQUIRE a.id IS UNIQUE
        """)

        # Create index for queries
        session.run("""
            CREATE INDEX activity_video IF NOT EXISTS
            FOR (a:Activity) ON (a.media_id)
        """)
```

### Add New Relationship
```python
def upgrade(driver):
    with driver.session() as session:
        # Add relationship type (relationships don't need explicit creation)
        # But we can create index on relationship properties

        session.run("""
            CREATE INDEX appears_with_confidence IF NOT EXISTS
            FOR ()-[r:APPEARS_WITH]-() ON (r.confidence)
        """)
```

### Add Vector Index
```python
def upgrade(driver):
    with driver.session() as session:
        # Check if index exists first
        result = session.run("""
            SHOW INDEXES WHERE name = 'entity_embeddings'
        """)
        if result.single() is None:
            session.run("""
                CALL db.index.vector.createNodeIndex(
                    'entity_embeddings',
                    'Entity',
                    'embedding',
                    1536,
                    'cosine'
                )
            """)
```

### Add Full-Text Index
```python
def upgrade(driver):
    with driver.session() as session:
        session.run("""
            CREATE FULLTEXT INDEX frame_description_fulltext IF NOT EXISTS
            FOR (f:Frame) ON EACH [f.description]
        """)
```

## CI/CD Integration

### GitHub Actions Migration Job
```yaml
name: Database Migrations

on:
  push:
    paths:
      - 'backend/alembic/**'
      - 'backend/migrations/**'

jobs:
  migrate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run PostgreSQL migrations
        run: |
          cd backend
          alembic upgrade head

      - name: Run Neo4j migrations
        run: |
          cd backend
          python -m migrations.neo4j.runner upgrade
```

## Checklist
- [ ] Migration file created with descriptive name
- [ ] upgrade() function implemented
- [ ] downgrade() function implemented
- [ ] Migration tested locally
- [ ] Indexes added for new columns/properties
- [ ] Foreign keys/constraints defined
- [ ] Data migration included if needed
- [ ] Rollback tested
