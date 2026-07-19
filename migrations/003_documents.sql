-- Second Brain — migration 003: document attachments per project.
-- Idempotent. Fresh installs already get this from 001_init.sql; run by hand
-- against an existing database:
--   docker compose exec -T db psql -U secondbrain -d secondbrain < migrations/003_documents.sql

CREATE TABLE IF NOT EXISTS documents (
    id           SERIAL PRIMARY KEY,
    project_id   INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    filename     TEXT NOT NULL,
    content_type TEXT,
    size_bytes   BIGINT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS documents_project_idx ON documents (project_id);
