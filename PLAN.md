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
| Beobachtbarkeit | `app/usage.py`                  | Wrapper um Anthropic-Aufrufe: Tokens/Latenz/Kosten loggen + in `usage_log` persistieren, `/stats`, Warnschwelle |
| Dashboard | `app/web/main.py`, `app/web/templates/` | FastAPI-Weboberfläche (browsen, suchen, bearbeiten, Dokumente) |
| Evals     | `evals/` (`metrics.py`, `*_eval.py`, `run.py`, `datasets/`) | Qualitäts-Messung: Router/Extraktion/Retrieval/Antwort (LLM-Judge) |
| Daten     | `migrations/001_init.sql` … `005_usage_log.sql`, `app/db.py`, `app/models.py` | Schema + Migrationen, Connection-Pool, Typen |

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

**`documents`** (Migration 003, `note` seit 004) — Datei-Anhänge je Projekt: `id`, `project_id`
→ `projects` (FK, `ON DELETE CASCADE`), `filename`, `content_type`, `size_bytes`, `note`
(freier Kommentar), `created_at`. Die Datei-**Bytes** liegen im Volume `docdata` (`DOCS_DIR/<id>`),
nur die **Metadaten** in der DB.

**`usage_log`** (Migration 005) — eine Zeile je Anthropic-Aufruf für die Kosten-Beobachtbarkeit:
`id`, `label` (router/extract/query/research), `model`, Token-Zähler (`input_tokens`,
`cache_creation_tokens`, `cache_read_tokens`, `output_tokens`), `web_searches`, `cost_usd`
(**Schätzung**, siehe `app/usage.py`), `created_at`. `/stats` aggregiert daraus heute/diesen Monat.

**Indizes:** HNSW auf `embedding` (Cosine), GIN auf `fts`, B-Tree auf `due_at`,
`project_id`, `(type, status)` sowie `documents(project_id)`. Trigger halten `updated_at` aktuell.

> **Migrationen:** `002_add_reminders.sql` hob `due_date DATE` → `due_at TIMESTAMPTZ` an und
> ergänzte `reminded_at`; `003_documents.sql` legte die `documents`-Tabelle an;
> `004_document_notes.sql` ergänzte die Kommentar-Spalte `note`; `005_usage_log.sql` legte die
> `usage_log`-Tabelle an. Alle idempotent; Neuinstallationen erhalten die Endform bereits aus
> `001_init.sql`.

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
      Telegram. Bytes im Volume, Metadaten in der DB (`app/documents.py`, Migration 003)
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
- [x] **Datei-Kommentare** — die Telegram-Bildunterschrift ist jetzt ein freier Kommentar
      (z.B. Ort/Begebenheit) und wird mit der Datei gespeichert (`note`, Migration 004); ein
      optionales `#Projektname` darin ordnet die Datei einem Projekt zu. Im Dashboard werden
      Kommentare angezeigt, sind dort inline editierbar und lassen sich schon beim Hochladen angeben.
- [x] **Projekt-Verwaltung** — Projekte lassen sich **umbenennen** (`rename_project`) und **leere**
      Projekte **löschen** (`delete_project`; verweigert, solange noch Einträge oder Dateien dranhängen).
      Umbenennen ändert das Projekt in-place, sodass alle Einträge/Dateien verknüpft bleiben — nötig,
      weil zuvor nur Einträge einzeln verschiebbar waren und der Fuzzy-Namensabgleich ein Verschieben
      auf einen Teilnamen (z.B. „Bier Gut" → „Bier") still zum No-Op machte. Verfügbar im Bot **und**
      im Dashboard (Umbenennen-Feld bzw. Löschen-Button je Projektkarte; Löschen nur bei leeren Projekten).

### 🟡 Phase 5 — Betrieb & Beobachtbarkeit (teilweise umgesetzt; Umfang bewusst auf Einzelbetrieb zugeschnitten)

Kein Blocker für v1.0. Umgesetzt wurde, was im Einzelnutzer-Betrieb echten Nutzen bringt;
Multi-User-/Betriebs-Themen bleiben bewusst zurückgestellt.

- [x] **Beobachtbarkeit (Kosten/Nutzung)** — ein dünner Wrapper (`app/usage.py`) um alle
      Anthropic-Aufrufe (Router, Extraktion, Query, Recherche) loggt pro Aufruf Tokens, Latenz und
      **geschätzte Kosten** (Preise je Modell inkl. Cache-Tarifen) und zählt Fehler/Rate-Limits.
      Jeder Aufruf wird zusätzlich in die Tabelle `usage_log` **persistiert** (Migration 005), sodass
      `/stats` Summen **heute und diesen Monat** je Modell zeigt — auch über Neustarts hinweg.
- [x] **Kosten-Warnschwelle** — `COST_WARN_THRESHOLD_USD` (Default 0 = aus): bei Überschreiten der
      geschätzten Ausgaben seit Start wird **einmalig** eine Log-Warnung ausgegeben. Bewusst **keine
      harte Sperre** — die würde einen aus dem eigenen Bot aussperren.
- [ ] **Dashboard-Absicherung** (zurückgestellt) — Login/Reverse-Proxy nur relevant, falls das
      Dashboard über localhost hinaus erreichbar sein soll. Im Einzelbetrieb auf vertrauenswürdigem
      Netz nicht nötig (der Bot ist ohnehin deny-by-default); wird erst bei Bedarf umgesetzt.
- [ ] **Metrik-Backend/Tracing** (zurückgestellt) — Prometheus o.ä. oder verteiltes Tracing wären
      für einen Ein-Personen-Bot überdimensioniert; die Log-Zeilen + `usage_log` + `/stats` decken den
      Bedarf. Leicht nachrüstbar, falls später gewünscht.

### ✅ Phase 6 — Evaluation-Harness (umgesetzt)

Getrennt von den Unit-Tests (deterministische Logik) misst ein **Eval-Harness** (`evals/`) die
**Qualität der modellabhängigen Schritte** auf kleinen gelabelten Datensätzen und gibt eine
Scorecard aus (`python -m evals.run <name>|all`, am besten im App-Container). Gedacht zum
Beobachten einer Kennzahl über die Zeit — etwa um Prompt-Regressionen zu erkennen.

- [x] **Router-Eval** — capture-vs-query-Klassifikation, misst Accuracy (Haiku).
- [x] **Extraktions-Eval** — prüft die strukturierten Felder (Typ, Fälligkeit ja/nein, Priorität,
      Projekt) gegen gelabelte Fälle; Accuracy je Feld (Haiku).
- [x] **Retrieval-/RAG-Eval** — seedet ein bekanntes Korpus, misst `hybrid_search` mit
      **hit@3 / recall@5 / MRR**. Nutzt nur das lokale Embedding-Modell → **keine API-Kosten**.
- [x] **Antwort-Eval (LLM-as-Judge)** — End-to-End-Antwort des Query-Agenten, von einem
      Richter-Modell gegen eine Rubrik bewertet; Bestanden-Quote (Opus).
- [x] Reine Metriken (`evals/metrics.py`: accuracy, hit@k, recall@k, MRR) sind unit-getestet.

**Letzte Messung** (im Container, gegen die mitgelieferten Datensätze): Router **100 %** (24/24) ·
Extraktion **Ø 97,5 %** (Typ 90 %, Fälligkeit/Priorität/Projekt je 100 %) · Retrieval
**hit@3 100 % / recall@5 93,8 % / MRR 0,938** · Antwort (LLM-Judge) **100 %** (4/4).

Hinweis: `retrieval`/`answer` seeden in die echte `items`-Tabelle (Marker `source='eval'`,
danach gelöscht); für saubere Zahlen gegen eine kleine/leere DB laufen lassen.

> **Versionssprung → v1.1.0.** Der Stand bis hier ist als **v1.1.0** getaggt und gepusht (Minor
> über v1.0.0, keine Breaking Changes). Dazu gehört alles seit dem v1.0-Marker: die
> „Seit v1.0"-Funktionen (Lern-Rückblick, Datei-Kommentare, Projekt-Verwaltung), die Kosten-/
> Nutzungs-Observability aus Phase 5 und der Eval-Harness (Phase 6). Ab Phase 7 folgt Geplantes,
> das noch nicht released ist.

### ✅ Seit v1.1 — umgesetzt

- [x] **`#Projektname` beim Text-Erfassen** — ein `#Projekt` (auch mit Leerzeichen: `# Finanzen`)
      in einer Nachricht ordnet den Eintrag deterministisch einem Projekt zu (dieselbe Konvention
      wie bei Datei-Bildunterschriften), statt es Claude raten zu lassen. Der Tag wird vor der
      Extraktion entfernt und überschreibt Claudes Vermutung; er muss eigenständig sein
      (Zeilenanfang oder nach Leerzeichen), damit URL-Fragmente (`…/p#abschnitt`) oder `C#` nicht
      als Projekt missverstanden werden. Gemeinsame Logik (`extract_project_hashtag`) für Captions
      und Text.
- [x] **Dashboard-Redesign** — die Weboberfläche bekam ein modernes App-Layout: feste
      **Sidebar-Navigation**, **Karten-Raster** mit farbigem Typ-Akzent je Eintrag, automatischer
      **Hell-/Dunkelmodus** (CSS-Variablen + `prefers-color-scheme`), dezente Glassmorphism-Panels
      und ein ambienter Aurora-Hintergrund. Rein CSS, dependency-frei; Templates und
      Funktionalität unverändert.

> **Versionssprung → v1.2.0.** Der Stand bis hier ist als **v1.2.0** getaggt und gepusht (Minor
> über v1.1.0, keine Breaking Changes). Dazu gehören die „Seit v1.1"-Funktionen: die
> `#Projektname`-Erfassung im Text und das Dashboard-Redesign. Ab Phase 7 folgt Geplantes,
> das noch nicht released ist.

### 🔮 Phase 7 — Geplante Funktionen (nach v1.2)

- [ ] **Proaktive Vorschläge** — der Bot erkennt Muster in den Daten und schlägt von sich aus
      etwas vor, z.B. „Du hast 3 Ideen zum Thema RAG — soll ich sie zusammenfassen/bündeln?"
      (auf Basis von Häufung/Ähnlichkeit verwandter Einträge).
- [ ] **Erledigte Todos im Dashboard ausblenden** — Umschalter im Web, der `done`-Todos
      standardmäßig ausblendet und nur offene zeigt (bei Bedarf wieder einblendbar).
- [ ] **Wiederkehrende Todos (recurring)** — Todos mit Wiederholung (täglich/wöchentlich/
      monatlich); beim Erledigen wird automatisch die nächste Fälligkeit angelegt.
- [ ] **Relevanz-Aging (Memory-Decay)** — alte, selten/nie abgefragte Einträge im RAG-Ranking
      leiser stellen: ein zeit- und zugriffsbasierter Gewichtungsfaktor auf den Suchscore, damit
      frische/relevante Notizen vorne landen und veraltete Karteileichen nach hinten rutschen
      (angelehnt an Memory-Decay-Ansätze, z.B. Ebbinghaus). Erfordert das Mitschreiben von
      Zugriffs-/Trefferzeitpunkten je Eintrag.
- [ ] **Health-/Doctor-Check** — Betriebs-Selbstdiagnose: ein `/healthz`-Endpoint am Dashboard
      (Maschinen-Ampel + Compose-Healthcheck) und ein `/doctor`-Telegram-Befehl mit 🟢/🔴-Report
      über DB, Embedding-Modell, Anthropic-Erreichbarkeit (+ Fehler-/Rate-Limit-Zähler),
      **Leben der Hintergrund-Loops** (Reminder/Digest/Review — fängt still ausgefallene
      Erinnerungen ab), Reminder-Frische und Plattenplatz. Optional ein „Canary", der proaktiv
      nur bei 🟢→🔴 meldet.

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
- **Kosten/Rate-Limits:** Kosten werden pro Aufruf geschätzt, geloggt und in `usage_log`
  persistiert (`/stats`); es gibt eine optionale Warnschwelle, aber **kein Caching** der
  Anthropic-Antworten und **keine harte Budget-Grenze**.
- **Beobachtbarkeit:** strukturierte Logs + Kosten-/Nutzungs-Persistenz + `/stats`; **kein
  Metrik-Backend/Tracing** (für Einzelbetrieb bewusst weggelassen).

---

## 7. Tests & Betrieb

- **Tests:** `pytest` — deckt reine Logik ohne DB/API ab
  (`tests/test_normalize.py`, `test_search.py`, `test_embed.py`, `test_duetime.py`,
  `test_memory.py`, `test_digest.py`, `test_caption.py`); `test_project_tools.py` testet
  die Projekt-Tools (umbenennen/löschen) gegen eine kleine In-Memory-Fake-DB;
  `test_usage.py` Kostenschätzung/Tracker, `test_eval_metrics.py` die Eval-Metriken.
- **Evals:** `python -m evals.run all` misst die Modell-Qualität (Router/Extraktion/Retrieval/
  Antwort) — braucht DB + API, daher im Container. Siehe `evals/README.md`.
- **Start:** `docker compose up -d --build`, danach Logs bis
  „Second Brain ist bereit. 🧠".
- **DB inspizieren:** siehe [README](README.md#datenbank-inspizieren).

---

*Ergänzungen zur Roadmap willkommen — dieses Dokument wächst mit dem Projekt.*
