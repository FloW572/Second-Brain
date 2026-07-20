-- Second Brain — migration 002: time-of-day due dates + reminders.
-- Idempotent: safe to run repeatedly and on either the old (due_date DATE) or
-- the new schema. Fresh installs already get the final shape from 001_init.sql;
-- run this by hand against an existing database:
--   docker compose exec db psql -U secondbrain -d secondbrain -f \
--     /docker-entrypoint-initdb.d/002_add_reminders.sql

-- Track whether a due todo has already been reminded (NULL = not yet).
ALTER TABLE items ADD COLUMN IF NOT EXISTS reminded_at TIMESTAMPTZ;

-- Upgrade due_date (DATE) -> due_at (TIMESTAMPTZ) once, preserving existing values.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'items' AND column_name = 'due_date'
    ) THEN
        ALTER TABLE items
            ALTER COLUMN due_date TYPE TIMESTAMPTZ USING due_date::timestamptz;
        ALTER TABLE items RENAME COLUMN due_date TO due_at;
    END IF;
END $$;

-- Point the due-date index at the renamed column.
DROP INDEX IF EXISTS items_due_idx;
CREATE INDEX IF NOT EXISTS items_due_at_idx ON items (due_at);
