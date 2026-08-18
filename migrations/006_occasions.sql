-- Second Brain — migration 006: wiederkehrende Anlässe + Ideen-Auffrischung.
-- Idempotent. Fresh installs already get this from 001_init.sql; run by hand
-- against an existing database:
--   docker compose exec -T db psql -U secondbrain -d secondbrain < migrations/006_occasions.sql

-- Wiederkehrende jährliche Anlässe (Geburtstag, Jahrestag, ...). Bewusst OHNE Jahr
-- im Fälligkeitsfeld: die nächste Wiederholung wird aus (month, day) berechnet.
CREATE TABLE IF NOT EXISTS occasions (
    id               SERIAL PRIMARY KEY,
    label            TEXT NOT NULL,                    -- "Luisa Geburtstag"
    person           TEXT,                             -- "Luisa" — verknüpft Notizen/Projekt
    kind             TEXT NOT NULL DEFAULT 'birthday', -- birthday | anniversary | custom
    month            SMALLINT NOT NULL CHECK (month BETWEEN 1 AND 12),
    day              SMALLINT NOT NULL CHECK (day BETWEEN 1 AND 31),
    lead_days        SMALLINT NOT NULL DEFAULT 14,     -- Vorlauf der Erinnerung
    project_id       INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    notes            TEXT,
    last_notified_on DATE,                             -- letzte Vorlauf-Erinnerung (NULL = nie)
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS occasions_date_idx    ON occasions (month, day);
CREATE INDEX IF NOT EXISTS occasions_person_idx  ON occasions (person);

DROP TRIGGER IF EXISTS trg_occasions_updated_at ON occasions;
CREATE TRIGGER trg_occasions_updated_at BEFORE UPDATE ON occasions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Wann eine liegengebliebene Idee zuletzt wieder vorgeschlagen wurde (NULL = noch nie),
-- damit dieselbe Idee nicht in Dauerschleife auftaucht.
ALTER TABLE items ADD COLUMN IF NOT EXISTS nudged_at TIMESTAMPTZ;
