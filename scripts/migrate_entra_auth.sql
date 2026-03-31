-- ==========================================================================
-- QPrisma: Migrate from JWT auth to Microsoft Entra ID
-- ==========================================================================
--
-- This migration:
--   1. Adds the `entra_oid` column (nullable, unique, indexed)
--   2. Drops the `hashed_password` column
--
-- Run against your PostgreSQL database BEFORE deploying the new code.
--
-- Usage:
--   psql -h <host> -U <user> -d qprisma -f scripts/migrate_entra_auth.sql
--
-- Rollback script is included at the bottom (commented out).
-- ==========================================================================

BEGIN;

-- Step 1: Add entra_oid column (Entra ID Object ID)
-- This stores the Microsoft Entra ID `oid` claim for each user.
-- Nullable initially — existing users get linked on first Entra login.
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS entra_oid VARCHAR(128);

-- Step 2: Create unique index on entra_oid (for fast lookups)
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_entra_oid
    ON users (entra_oid)
    WHERE entra_oid IS NOT NULL;

-- Step 3: Drop hashed_password column (no longer needed)
-- All authentication is now handled by Microsoft Entra ID.
ALTER TABLE users
    DROP COLUMN IF EXISTS hashed_password;

COMMIT;

-- Verify the migration
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'users'
ORDER BY ordinal_position;

-- ==========================================================================
-- ROLLBACK (uncomment and run if you need to revert)
-- ==========================================================================
-- BEGIN;
--
-- ALTER TABLE users
--     ADD COLUMN IF NOT EXISTS hashed_password VARCHAR(255) NOT NULL DEFAULT '';
--
-- DROP INDEX IF EXISTS ix_users_entra_oid;
--
-- ALTER TABLE users
--     DROP COLUMN IF EXISTS entra_oid;
--
-- COMMIT;
