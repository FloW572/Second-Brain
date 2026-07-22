-- Second Brain — migration 004: free-text note/comment on documents.
-- Idempotent. Fresh installs already get this from 001_init.sql; run by hand
-- against an existing database:
--   docker compose exec -T db psql -U secondbrain -d secondbrain < migrations/004_document_notes.sql

ALTER TABLE documents ADD COLUMN IF NOT EXISTS note TEXT;
