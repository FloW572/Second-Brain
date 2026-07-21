# Projektplan — Second Brain 🧠

Dieses Dokument beschreibt Vision, Architektur, den aktuellen Umsetzungsstand
und die geplanten Ausbaustufen. Es ist die Referenz, auf die das [README](README.md)
verweist.

---

## 1. Vision & Ziel

Ein **persönliches, selbst gehostetes „Second Brain"**: Todos, Ideen, Projekte und
Notizen werden unterwegs per **Telegram** vom Handy erfasst, dauerhaft in
**PostgreSQL + pgvector** gespeichert und von **Claude** ausgewertet.

Leitfragen, die das System beantworten soll:

- *„Was sollte ich heute zuerst tun?"*
- *„Welche Ideen habe ich zum Thema X?"*
- *„Zeig mir offene Todos für Projekt Y."*

**Designprinzipien**

- **Reibungslos erfassen:** Freitext genügt — die Struktur (Typ, Titel, Fälligkeit,
  Priorität, Tags, Projekt) leitet Claude selbst ab.
- **Datenhoheit:** Alles läuft self-hosted; Embeddings werden **lokal** erzeugt.
- **Begründete Antworten:** Der Query-Agent liest die echten Daten über Tools,
  statt zu halluzinieren.
- **Günstig im Betrieb:** Billiges Modell (Haiku) fürs Routing/Extrahieren,
  starkes Modell (Opus) nur fürs Reasoning.

---

## 2. Architektur

```
Handy ──Telegram──▶ Bot (Long-Polling) ──▶ Backend (Python)
                                            ├─ Router (Claude Haiku): capture | query
                                            ├─ Capture: Claude strukturiert → Embedding (lokal) → DB
                                            └─ Query: agentischer Claude-Loop (Opus) mit Tools über die DB
                                            │
                                            ▼
                                  PostgreSQL 16 + pgvector
                                  (projects, items + embedding + fts)
```

### Verarbeitungsfluss

1. **Eingang** — Telegram-Nachricht trifft im Bot ein (`app/bot/handlers.py`).
   Autorisierung über `ALLOWED_TELEGRAM_USER_IDS`.
2. **Routing** — `app/bot/router.py` klassifiziert mit Haiku via Tool-Call:
   `capture` (speichern) oder `query` (auswerten). Fallback bei Fehler: `capture`.
3. **Capture** — `app/ingest/` extrahiert Struktur (Claude), normalisiert, erzeugt
   ein lokales Embedding (bge-m3) und schreibt in die DB.
4. **Query** — `app/query/agent.py` fährt einen agentischen Loop (Opus) mit Tools
   und antwortet begründet.

### Komponenten

| Bereich   | Dateien                              | Aufgabe |
|-----------|--------------------------------------|---------|
| Einstieg  | `app/main.py`                        | Bot starten, Pool/Anthropic-Client/Embedding-Modell initialisieren |
| Config    | `app/config.py`                      | Settings aus `.env` (Pydantic) |
| Bot       | `app/bot/handlers.py`, `router.py`   | Telegram-Handler, Intent-Routing |
| Ingest    | `app/ingest/extract.py`, `normalize.py`, `embed.py`, `projects.py` | Struktur extrahieren, normalisieren, einbetten, Projekt zuordnen |
| Suche     | `app/search.py`                      | Hybride Suche (Vektor + Volltext) mit RRF-Fusion |
| Query     | `app/query/agent.py`, `tools.py`     | Reasoning-Loop + Tools über die DB |
| Daten     | `migrations/001_init.sql`, `app/db.py`, `app/models.py` | Schema, Connection-Pool, Typen |

---

## 3. Datenmodell

Definiert in [`migrations/001_init.sql`](migrations/001_init.sql).

**`projects`** — `id`, `name`, `description`, `status` (`active | on_hold | done | archived`),
`created_at`, `updated_at`.

**`items`** — die zentrale Tabelle:

- `type` — `todo | idea | note | reference`
- `title`, `content`
- `project_id` → `projects` (FK, `ON DELETE SET NULL`)
- `status` — bei Todos `open | doing | done`, sonst `NULL`
- `priority` — `1` (hoch) … `3` (niedrig)
- `due_date`, `tags[]`
- `source` — `telegram_text | telegram_voice`
- `raw_input` — Originalnachricht (Audit / Re-Processing)
- `embedding VECTOR(1024)` — **Dimension muss zu `EMBEDDING_MODEL` passen** (bge-m3 = 1024)
- `fts TSVECTOR` — generierte Spalte (deutsche Textsuche über `title` + `content`)

**Indizes:** HNSW auf `embedding` (Cosine), GIN auf `fts`, B-Tree auf `due_date`,
`project_id`, `(type, status)`. Trigger halten `updated_at` aktuell.

---

## 4. Modelle

| Rolle        | Modell (Default)              | Konfig-Variable   |
|--------------|-------------------------------|-------------------|
| Embedding    | `BAAI/bge-m3` (lokal, 1024-d) | `EMBEDDING_MODEL` |
| Routing      | `claude-haiku-4-5-...`        | `ROUTER_MODEL`    |
| Extraktion   | `claude-haiku-4-5-...`        | `EXTRACT_MODEL`   |
| Reasoning    | `claude-opus-4-8`             | `QUERY_MODEL`     |

Embeddings laufen lokal (kostenlos, deutschtauglich). **Achtung:** Wechsel von
`EMBEDDING_MODEL` erfordert Anpassung der Vektordimension im Schema und ein
Neu-Einbetten aller Items.

---

## 5. Phasen

### ✅ Phase 1 — MVP (umgesetzt)

- [x] Telegram-Bot (Long-Polling) mit Autorisierung über User-ID-Whitelist
- [x] Intent-Routing (capture/query) via Haiku
- [x] Capture-Pipeline: Extraktion → Normalisierung → lokales Embedding → DB
- [x] Automatische Projektzuordnung (`app/ingest/projects.py`)
- [x] Hybride Suche (semantisch + Volltext) mit RRF-Fusion
- [x] Query-Agent (Opus) mit Tools: `now`, `list_projects`, `list_todos`,
      `search`, `complete_item`
- [x] Schema mit pgvector, HNSW-/GIN-Indizes, `updated_at`-Trigger
- [x] Docker-Compose-Setup (App + Postgres/pgvector)
- [x] Unit-Tests für reine Logik (Normalisierung, RRF-Fusion, Vektor-Literal)

### ✅ Phase 2 — Komfort & Editieren (umgesetzt)

- [x] **Sprachnachrichten** — lokale Transkription via `faster-whisper`
      (`app/transcribe.py`); Transkript läuft durch dieselbe Pipeline wie Text
- [x] **`update_item`-Tool** — Titel/Inhalt/Typ/Fälligkeit/Priorität/Status/Projekt/Tags ändern
      (partielles Update, Typ-Wechsel hält Status konsistent, re-embedded bei Text-Änderung)
- [x] **Uhrzeiten** — `due_date DATE` → `due_at TIMESTAMPTZ` (Migration 002), Zeit-Parsing
      in `app/duetime.py` (nur Datum → 09:00 lokal)
- [x] **Erinnerungen** — asyncio-Hintergrund-Loop (`app/reminders.py`) benachrichtigt
      proaktiv über fällige, offene Todos; feuert dank `reminded_at` genau einmal
- [x] **`delete_item`-Tool** — Eintrag per id endgültig löschen (fragt bei Mehrdeutigkeit nach)
- [x] **Router erkennt Änderungen/Aktionen** an Bestehendem als `query` (kein Duplikat-Bug mehr)
- [x] **Agent bleibt ehrlich** — bietet nur Aktionen an, die die Tools wirklich können
- [x] **`create_project`-Tool** — Projekt explizit anlegen (optional mit Beschreibung; legt
      keine Duplikate an)
- [x] **`reschedule`** — bereits durch `update_item` (`due_at`) abgedeckt; setzt `reminded_at` zurück

### 🔮 Phase 3 — Proaktiv & Oberfläche

- [x] **Konversations-Gedächtnis** — der Query-Agent kennt die letzten Austausche pro Chat
      (`app/memory.py`, in-memory, begrenzt + Inaktivitäts-Reset), sodass Folgefragen
      (z.B. „und diese Woche?") den Kontext behalten; `/reset` startet neu.
- [x] **Täglicher Digest** — proaktive Morgen-Zusammenfassung/Priorisierung (`app/digest.py`,
      eigener Loop zur `DIGEST_HOUR`, einmal täglich); auch on-demand via `/digest`
- [x] **Wöchentliches Review** — proaktiver Wochenrückblick + Fokus-Vorschlag (`app/digest.py`,
      eigener Loop zu `REVIEW_WEEKDAY`/`REVIEW_HOUR`); auch on-demand via `/review`
- [x] **Web-Dashboard** — FastAPI-Oberfläche (`app/web/`, eigener Compose-Service auf Port 8001):
      Items browsen/filtern, semantische Suche, bearbeiten/erledigen/löschen; nutzt dieselben
      Tool-Handler wie der Bot
- [ ] **Kalender-Integration** (nice-to-have, zurückgestellt) — `.ics`-Export/Abo der Fälligkeiten
      für die Handy-Kalender-App. Bewusst zurückgestellt: die Erinnerungen decken den Kernbedarf
      (rechtzeitig informiert werden) bereits ab; der Kalender wäre nur die Anzeige.

> Später denkbar (eigene Phase): **Langzeit-Personalisierung** — dauerhafte Fakten über
> den Nutzer lernen und in den Kontext einspeisen (analog zu Claudes „Memory").

---

## 6. Offene Punkte / Bekannte Grenzen

- **Migrationen:** Nummerierte, idempotente SQL-Dateien in `migrations/` werden beim
  ersten Init automatisch in Reihenfolge ausgeführt. Ein volles Framework mit
  Versions-Tracking (Alembic/Flyway) fehlt aber — auf eine bestehende DB wendet man
  neue Migrationen von Hand an.
- **Mehrbenutzer:** Aktuell auf eine kleine Whitelist ausgelegt; keine Trennung
  der Daten pro Nutzer. Zwei parallele Instanzen sind nicht möglich (ein Poller pro
  Bot-Token; der Reminder-Loop ist auf eine Instanz ausgelegt).
- **Kosten/Rate-Limits:** Kein Caching der Anthropic-Antworten; keine
  Budget-Grenzen implementiert.
- **Beobachtbarkeit:** Nur Logging, keine Metriken/Tracing.

---

## 7. Tests & Betrieb

- **Tests:** `pytest` — deckt reine Logik ohne DB/API ab
  (`tests/test_normalize.py`, `test_search.py`, `test_embed.py`).
- **Start:** `docker compose up -d --build`, danach Logs bis
  „Second Brain ist bereit. 🧠".
- **DB inspizieren:** siehe [README](README.md#datenbank-inspizieren).

---

*Ergänzungen zur Roadmap willkommen — dieses Dokument wächst mit dem Projekt.*
