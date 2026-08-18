-- Second Brain — migration 007: Marker-Spalten frischen updated_at nicht mehr auf.
-- Idempotent (CREATE OR REPLACE). Fresh installs already get this from 001_init.sql;
-- run by hand against an existing database:
--   docker compose exec -T db psql -U secondbrain -d secondbrain < migrations/007_marker_columns_keep_updated_at.sql
--
-- Hintergrund: reminded_at ("Erinnerung verschickt") und nudged_at ("Idee wieder
-- vorgeschlagen") halten fest, dass etwas ZUGESTELLT wurde — sie ändern den Eintrag
-- inhaltlich nicht. Der bisherige Trigger setzte updated_at trotzdem auf now(), womit
-- jedes erinnerte Todo und jede aufgefrischte Idee als "gerade bearbeitet" galt: sie
-- tauchten fälschlich in list_recent / /recently_learned und oben im Dashboard auf, und
-- die Altersangabe der Ideen-Auffrischung zählte ab der letzten Erinnerung statt ab der
-- letzten echten Änderung.

-- 'fts' muss mit ausgeblendet werden: die Spalte ist GENERATED, und in einem
-- BEFORE-Trigger ist NEW.fts noch nicht berechnet (NULL). Ohne den Ausschluss
-- unterscheiden sich NEW und OLD immer und der Vergleich wäre wirkungslos.
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    -- Nur auffrischen, wenn sich abseits der Marker-Spalten wirklich etwas geändert hat.
    IF (to_jsonb(NEW) - 'nudged_at' - 'reminded_at' - 'updated_at' - 'fts')
       IS DISTINCT FROM
       (to_jsonb(OLD) - 'nudged_at' - 'reminded_at' - 'updated_at' - 'fts') THEN
        NEW.updated_at = now();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
