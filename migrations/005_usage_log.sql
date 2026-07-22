-- Second Brain — migration 005: per-call Anthropic usage log (cost observability).
-- Idempotent. Fresh installs already get this from 001_init.sql; run by hand
-- against an existing database:
--   docker compose exec -T db psql -U secondbrain -d secondbrain < migrations/005_usage_log.sql

CREATE TABLE IF NOT EXISTS usage_log (
    id                     SERIAL PRIMARY KEY,
    label                  TEXT NOT NULL,              -- router | extract | query | research
    model                  TEXT NOT NULL,
    input_tokens           INTEGER NOT NULL DEFAULT 0, -- uncached prompt tokens
    cache_creation_tokens  INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens      INTEGER NOT NULL DEFAULT 0,
    output_tokens          INTEGER NOT NULL DEFAULT 0,
    web_searches           INTEGER NOT NULL DEFAULT 0,
    cost_usd               NUMERIC(12, 6) NOT NULL DEFAULT 0,  -- estimate; see app/usage.py
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS usage_log_created_idx ON usage_log (created_at);
