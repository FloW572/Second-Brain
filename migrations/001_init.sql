-- Second Brain — initial schema (PostgreSQL + pgvector)
-- Runs automatically via /docker-entrypoint-initdb.d on the FIRST init of an
-- empty data volume. To re-apply on an existing DB, run this file with psql.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS projects (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    status      TEXT NOT NULL DEFAULT 'active',   -- active | on_hold | done | archived
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS items (
    id          SERIAL PRIMARY KEY,
    type        TEXT NOT NULL DEFAULT 'note',      -- todo | idea | note | reference
    title       TEXT NOT NULL,
    content     TEXT,
    project_id  INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    status      TEXT,                              -- todo: open|doing|done ; else NULL
    priority    SMALLINT,                          -- 1 (high) .. 3 (low)
    due_at      TIMESTAMPTZ,                        -- due date (+ optional time)
    reminded_at TIMESTAMPTZ,                        -- when a reminder was sent (NULL = not yet)
    tags        TEXT[] NOT NULL DEFAULT '{}',
    source      TEXT,                              -- telegram_text | telegram_voice
    raw_input   TEXT,                              -- original message (audit / re-processing)
    embedding   VECTOR(1024),                      -- dim MUST match EMBEDDING_MODEL (bge-m3 = 1024)
    fts         TSVECTOR GENERATED ALWAYS AS (
                    to_tsvector('german', coalesce(title, '') || ' ' || coalesce(content, ''))
                ) STORED,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS items_embedding_idx   ON items USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS items_fts_idx         ON items USING gin (fts);
CREATE INDEX IF NOT EXISTS items_due_at_idx      ON items (due_at);
CREATE INDEX IF NOT EXISTS items_project_idx     ON items (project_id);
CREATE INDEX IF NOT EXISTS items_type_status_idx ON items (type, status);

-- Files (xlsx / pdf / images) attached to a project. Bytes live on disk (a volume);
-- this table holds only metadata. The file on disk is named after the row id.
CREATE TABLE IF NOT EXISTS documents (
    id           SERIAL PRIMARY KEY,
    project_id   INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    filename     TEXT NOT NULL,
    content_type TEXT,
    size_bytes   BIGINT,
    note         TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS documents_project_idx ON documents (project_id);

-- Per-call Anthropic usage log for cost observability (see app/usage.py). The dollar
-- figure is an estimate from a local price table; the token counts are Anthropic's own.
CREATE TABLE IF NOT EXISTS usage_log (
    id                     SERIAL PRIMARY KEY,
    label                  TEXT NOT NULL,              -- router | extract | query | research
    model                  TEXT NOT NULL,
    input_tokens           INTEGER NOT NULL DEFAULT 0, -- uncached prompt tokens
    cache_creation_tokens  INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens      INTEGER NOT NULL DEFAULT 0,
    output_tokens          INTEGER NOT NULL DEFAULT 0,
    web_searches           INTEGER NOT NULL DEFAULT 0,
    cost_usd               NUMERIC(12, 6) NOT NULL DEFAULT 0,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS usage_log_created_idx ON usage_log (created_at);

-- Keep updated_at fresh on UPDATE.
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_items_updated_at ON items;
CREATE TRIGGER trg_items_updated_at BEFORE UPDATE ON items
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_projects_updated_at ON projects;
CREATE TRIGGER trg_projects_updated_at BEFORE UPDATE ON projects
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
