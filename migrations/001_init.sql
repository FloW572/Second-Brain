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
    due_date    DATE,
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
CREATE INDEX IF NOT EXISTS items_due_idx         ON items (due_date);
CREATE INDEX IF NOT EXISTS items_project_idx     ON items (project_id);
CREATE INDEX IF NOT EXISTS items_type_status_idx ON items (type, status);

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
