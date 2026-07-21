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
Handy ──Telegram──▶ Bot (Long-Polling)        Browser ──HTTP :8001──▶ Web-Dashboard (FastAPI)
 Text · 🎙 Voice · Datei/Foto  │                                        │
                               ▼                                        │
                      Backend (Python)  ◀────────────────────────────────┘
                      ├─ Voice: faster-whisper (lokal) → Text
                      ├─ Router (Claude Haiku): capture | query
                      ├─ Capture: Claude strukturiert → Embedding (lokal) → DB
                      ├─ Query: agentischer Claude-Loop (Opus) mit Tools über die DB
                      │    └─ enrich_item → Anthropic-Websuche → Fakten anhängen
                      └─ Hintergrund-Loops: Erinnerungen · Tages-Digest · Wochen-Review
                               │
                               ▼
                      PostgreSQL 16 + pgvector
                      (projects · items[+embedding+fts] · documents)  +  Datei-Volume
```

### Verarbeitungsfluss

1. **Eingang** — Telegram-Nachricht trifft im Bot ein (`app/bot/handlers.py`):
   Text, 🎙 Sprachnachricht oder Datei/Foto. Autorisierung über `ALLOWED_TELEGRAM_USER_IDS`
   (leer = alle gesperrt, deny by default). Während langlaufender Antworten hält der Bot die
   „tippt…"-Anzeige aktiv.
2. **Sprache → Text** — Sprachnachrichten werden lokal mit `faster-whisper` transkribiert
   (`app/transcribe.py`) und laufen danach durch dieselbe Pipeline wie Text.
3. **Routing** — `app/bot/router.py` klassifiziert mit Haiku via Tool-Call:
   `capture` (speichern) oder `query` (auswerten/handeln). Fallback bei Fehler: `capture`.
4. **Capture** — `app/ingest/` extrahiert Struktur (Claude), normalisiert, erzeugt
   ein lokales Embedding (bge-m3), ordnet ein Projekt zu und schreibt in die DB.
5. **Query** — `app/query/agent.py` fährt einen agentischen Loop (Opus) mit Tools und
   antwortet begründet — inkl. Lesen/Suchen, Ändern/Löschen, Erledigen und Faktenrecherche
   per Websuche (`enrich_item`). Ein Konversations-Gedächtnis (`app/memory.py`) hält den
   Kontext für Rückfragen.
6. **Dateien** — hochgeladene Dokumente/Fotos werden je Projekt abgelegt (`app/documents.py`):
   Bytes im Volume, Metadaten in der DB.
7. **Proaktiv** — Hintergrund-Loops verschicken fällige Erinnerungen (`app/reminders.py`),
   einen täglichen Digest und ein wöchentliches Review (`app/digest.py`).
8. **Web-Dashboard** — ein separater FastAPI-Dienst (`app/web/`) liest dieselbe DB und nutzt
   dieselben Aktions-Handler; browsen, suchen, bearbeiten, Dokumente verwalten im Browser.

### Komponenten

| Bereich   | Dateien                              | Aufgabe |
|-----------|--------------------------------------|---------|
| Einstieg  | `app/main.py`                        | Bot starten, Pool/Anthropic-Client/Embedding-Modell + Hintergrund-Loops initialisieren |
| Config    | `app/config.py`                      | Settings aus `.env` (Pydantic) |
| Bot       | `app/bot/handlers.py`, `router.py`   | Telegram-Handler (Text/Voice/Datei/Foto, Befehle), Intent-Routing, „tippt…"-Anzeige |
| Sprache   | `app/transcribe.py`                  | Lokale Transkription von Sprachnachrichten (`faster-whisper`) |
| Ingest    | `app/ingest/extract.py`, `normalize.py`, `embed.py`, `projects.py` | Struktur extrahieren, normalisieren, einbetten, Projekt zuordnen |
| Suche     | `app/search.py`                      | Hybride Suche (Vektor + Volltext) mit RRF-Fusion, Distanz-Schwelle |
| Query     | `app/query/agent.py`, `tools.py`     | Reasoning-Loop + Tools über die DB (inkl. `enrich_item` via Websuche) |
| Gedächtnis| `app/memory.py`                      | Kurzes Konversations-Gedächtnis pro Chat (in-memory, Inaktivitäts-Reset) |
| Zeit      | `app/duetime.py`                     | Fälligkeiten parsen (Datum → 09:00 lokal), Zeitzone `TIMEZONE` |
| Proaktiv  | `app/reminders.py`, `app/digest.py`  | Erinnerungs-Loop, täglicher Digest & wöchentliches Review |
| Dokumente | `app/documents.py`                   | Datei-Anhänge je Projekt (Bytes im Volume, Metadaten in DB) |
| Dashboard | `app/web/main.py`, `app/web/templates/` | FastAPI-Weboberfläche (browsen, suchen, bearbeiten, Dokumente) |
| Daten     | `migrations/001_init.sql`, `002_add_reminders.sql`, `003_documents.sql`, `app/db.py`, `app/models.py` | Schema + Migrationen, Connection-Pool, Typen |

### Datenfluss & Datenschutz

Self-hosted für die **Ablage**, aber nicht offline — das Reasoning läuft über die Anthropic-API.

- **Lokal (nie an Anthropic):** Audio von Sprachnachrichten, Embeddings, Dokument-/Foto-Inhalte,
  die Datenbank samt Suche, die `.env`.
- **An Anthropic (Text, TLS):** jede Nachricht (Router), der Erfassungstext (Extraktion), bei
  Fragen die Frage **plus die per Tools gelesenen Einträge** (Reasoning), Digest/Review (nur wenn
  aktiviert) sowie die Anreicherung (Eintrag + server-seitige Websuche ins öffentliche Web).

Standardmäßig kein Training auf API-Daten (kommerzielle Bedingungen). Tabellen und
Sicherheitshinweise (u.a. Dashboard ohne Auth, opt-in-Briefings, deny-by-default) im
[README](README.md), Abschnitt „Datenschutz".

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
- `due_at TIMESTAMPTZ`, `reminded_at TIMESTAMPTZ` (NULL = noch nicht erinnert), `tags[]`
- `source` — `telegram_text | telegram_voice`
- `raw_input` — Originalnachricht (Audit / Re-Processing)
- `embedding VECTOR(1024)` — **Dimension muss zu `EMBEDDING_MODEL` passen** (bge-m3 = 1024)
- `fts TSVECTOR` — generierte Spalte (deutsche Textsuche über `title` + `content`)

**`documents`** (Migration 003) — Datei-Anhänge je Projekt: `id`, `project_id` → `projects`
(FK, `ON DELETE CASCADE`), `filename`, `content_type`, `size_bytes`, `created_at`. Die
Datei-**Bytes** liegen im Volume `docdata` (`DOCS_DIR/<id>`), nur die **Metadaten** in der DB.

**Indizes:** HNSW auf `embedding` (Cosine), GIN auf `fts`, B-Tree auf `due_at`,
`project_id`, `(type, status)` sowie `documents(project_id)`. Trigger halten `updated_at` aktuell.

> **Migrationen:** `002_add_reminders.sql` hob `due_date DATE` → `due_at TIMESTAMPTZ` an und
> ergänzte `reminded_at`; `003_documents.sql` legte die `documents`-Tabelle an. Beide sind
> idempotent; Neuinstallationen erhalten die Endform bereits aus `001_init.sql`.

---

## 4. Modelle

| Rolle          | Modell (Default)              | Konfig-Variable   |
|----------------|-------------------------------|-------------------|
| Embedding      | `BAAI/bge-m3` (lokal, 1024-d) | `EMBEDDING_MODEL` |
| Sprache → Text | `faster-whisper` (lokal, CPU) | `WHISPER_MODEL`, `WHISPER_LANGUAGE` |
| Routing        | `claude-haiku-4-5-...`        | `ROUTER_MODEL`    |
| Extraktion     | `claude-haiku-4-5-...`        | `EXTRACT_MODEL`   |
| Reasoning      | `claude-opus-4-8`             | `QUERY_MODEL`     |

Embeddings **und** Spracherkennung laufen lokal (kostenlos, deutschtauglich). **Achtung:**
Wechsel von `EMBEDDING_MODEL` erfordert Anpassung der Vektordimension im Schema und ein
Neu-Einbetten aller Items.

**Websuche:** Die Faktenrecherche (`enrich_item`) nutzt das **Server-Tool `web_search`** der
Anthropic-API (kein separates Modell, läuft über `QUERY_MODEL`). Sie wird nur auf diesem
Pfad ausgelöst; normale Abfragen verursachen keine Suchkosten.

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

### ✅ Phase 3 — Proaktiv & Oberfläche (umgesetzt; Kalender zurückgestellt)

- [x] **Konversations-Gedächtnis** — der Query-Agent kennt die letzten Austausche pro Chat
      (`app/memory.py`, in-memory, begrenzt + Inaktivitäts-Reset), sodass Folgefragen
      (z.B. „und diese Woche?") den Kontext behalten; `/reset` startet neu.
- [x] **Täglicher Digest** — proaktive Morgen-Zusammenfassung/Priorisierung (`app/digest.py`,
      eigener Loop zur `DIGEST_HOUR`, einmal täglich); auch on-demand via `/digest`.
      Ein-/Ausschalten über `DIGEST_ENABLED` (opt-in, Default aus); die Uhrzeit ist reines
      24-Stunden-Format und steuert nur noch das *Wann*.
- [x] **Wöchentliches Review** — proaktiver Wochenrückblick + Fokus-Vorschlag (`app/digest.py`,
      eigener Loop zu `REVIEW_WEEKDAY`/`REVIEW_HOUR`); auch on-demand via `/review`.
      Ein-/Ausschalten über `REVIEW_ENABLED` (opt-in, Default aus); ungültige Zeitwerte sind
      eine Fehlkonfiguration (Warnung), kein stiller Aus-Schalter.
- [x] **Web-Dashboard** — FastAPI-Oberfläche (`app/web/`, eigener Compose-Service auf Port 8001):
      Items browsen/filtern, semantische Suche, bearbeiten/erledigen/löschen; Projekt-Ansicht;
      nutzt dieselben Tool-Handler wie der Bot
- [x] **Dokumente** — Dateien (xlsx/PDF/Bilder) pro Projekt ablegen, per Dashboard **und** per
      Telegram (Bildunterschrift = Projekt). Bytes im Volume, Metadaten in der DB
      (`app/documents.py`, Migration 003)
- [ ] **Kalender-Integration** (nice-to-have, zurückgestellt) — `.ics`-Export/Abo der Fälligkeiten
      für die Handy-Kalender-App. Bewusst zurückgestellt: die Erinnerungen decken den Kernbedarf
      (rechtzeitig informiert werden) bereits ab; der Kalender wäre nur die Anzeige.

### ✅ Phase 4 — Anreicherung & Recherche (umgesetzt)

- [x] **Fakten-Anreicherung** — „Ergänze Referenz X um relevante Fakten" (für **jeden**
      Eintragstyp): das `enrich_item`-Tool findet den Eintrag per `search` und recherchiert
      per **Anthropic-Websuche** (`web_search`, Server-Tool) die wichtigsten typgerechten
      Fakten (z.B. Hotel → Adresse/Telefon/Bewertung, Buch → Autor/Jahr) und hängt sie an den
      Inhalt an (re-embedded). Erneutes Ergänzen **ersetzt** den vorhandenen Fakten-Block
      (kein Stapeln); Such-Kommentare und Zitat-Markup werden herausgefiltert. Die Websuche ist
      auf diesen Pfad beschränkt, damit normale Abfragen kostenfrei bleiben; findet sie nichts
      Verlässliches, wird nichts erfunden.
- [x] **Responsive Telegram-Antworten** — die „tippt…"-Anzeige bleibt während langlaufender
      Antworten (v.a. Websuche, ~1–2 Min) durchgehend aktiv, statt nach ~5 s zu verschwinden.

> **Der Funktionsumfang bis hier gilt als v1.0.** Die Kernfunktionen (Erfassen, Suchen, Fragen,
> Bearbeiten, Erinnern, Digest/Review, Dokumente, Dashboard, Anreicherung) sind vollständig,
> dogfooded und dokumentiert. Ab jetzt: Fehlerbehebungen als Patch (1.0.x), neue Funktionen als
> Minor (1.x.0), Breaking Changes als Major (2.0.0).

### ✅ Seit v1.0 — umgesetzt

- [x] **Lern-Rückblick** — On-Demand-Befehl `/recently_learned` fasst zusammen, was ich zuletzt
      gelernt/festgehalten habe: neue Notizen/Ideen und erledigte Todos der letzten 7 Tage,
      plus 1-3 kurze Erkenntnisse. Basiert auf dem neuen Tool `list_recent` (Einträge nach
      Änderungszeit), das auch für normale Fragen („was habe ich diese Woche notiert?") nutzbar ist.

### 🔮 Phase 5 — Betrieb & Beobachtbarkeit (optional, nach v1.0)

Kein Blocker für v1.0 (Einzelnutzer-Betrieb; Logging genügt), aber sinnvoller Ausbau 

- [ ] **Beobachtbarkeit** — strukturierte Logs, einfache Metriken (Anzahl Anfragen, Latenz) und
      Token-/Kosten-Logging pro Anthropic-Aufruf; optional leichtes Tracing.
- [ ] **Dashboard-Absicherung** — Login bzw. Reverse-Proxy, falls das Dashboard über localhost
      hinaus erreichbar sein soll (aktuell bewusst ohne Auth, nur für lokal/vertrauenswürdiges Netz).
- [ ] **Kosten-/Budget-Grenzen** — optionales Limit/Warnschwelle für Anthropic-Ausgaben.

### 🔮 Phase 6 — Geplante Funktionen (nach v1.0)

- [ ] **Proaktive Vorschläge** — der Bot erkennt Muster in den Daten und schlägt von sich aus
      etwas vor, z.B. „Du hast 3 Ideen zum Thema RAG — soll ich sie zusammenfassen/bündeln?"
      (auf Basis von Häufung/Ähnlichkeit verwandter Einträge).
- [ ] **Erledigte Todos im Dashboard ausblenden** — Umschalter im Web, der `done`-Todos
      standardmäßig ausblendet und nur offene zeigt (bei Bedarf wieder einblendbar).
- [ ] **Wiederkehrende Todos (recurring)** — Todos mit Wiederholung (täglich/wöchentlich/
      monatlich); beim Erledigen wird automatisch die nächste Fälligkeit angelegt.

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
  (`tests/test_normalize.py`, `test_search.py`, `test_embed.py`, `test_duetime.py`,
  `test_memory.py`, `test_digest.py`).
- **Start:** `docker compose up -d --build`, danach Logs bis
  „Second Brain ist bereit. 🧠".
- **DB inspizieren:** siehe [README](README.md#datenbank-inspizieren).

---

*Ergänzungen zur Roadmap willkommen — dieses Dokument wächst mit dem Projekt.*
