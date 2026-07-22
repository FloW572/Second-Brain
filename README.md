# Second Brain 🧠

Ein persönliches, selbst gehostetes „Second Brain": Todos, Ideen, Projekte und Notizen
werden per **Telegram** — als **Text oder Sprachnachricht** — vom Handy erfasst, in
**PostgreSQL + pgvector** gespeichert und von **Claude** ausgewertet, z.B.
*„Was sollte ich heute zuerst tun?"*. Fällige Todos meldet der Bot **proaktiv** als Erinnerung.

## Architektur

```
Handy ──Telegram──▶ Bot (Polling) ──▶ Backend (Python)      Browser ──▶ Web-Dashboard :8001
 Text · 🎙 Voice · Datei/Foto           ├─ Voice: faster-whisper (lokal) → Text
                                        ├─ Router (Claude Haiku): capture | query
                                        ├─ Capture: Claude strukturiert → Embedding (lokal) → DB
                                        ├─ Query: agentischer Claude-Loop (Opus) mit Tools
                                        │    └─ enrich_item → Anthropic-Websuche → Fakten
                                        └─ Loops: Erinnerungen · Tages-Digest · Wochen-Review
                                        │
                                        ▼
                              PostgreSQL 16 + pgvector
                              (projects · items[+embedding+fts] · documents) + Datei-Volume
```

- **Erfassen:** Text oder Sprachnachricht (Voice wird lokal transkribiert) → Claude extrahiert
  Typ/Titel/Fälligkeit (mit Uhrzeit)/Priorität/Projekt/Tags → lokales, multilinguales Embedding
  (bge-m3) → gespeichert.
- **Fragen & Handeln:** Claude nutzt Tools, liest bzw. verändert die echten Daten und antwortet
  begründet — statt zu raten; für Rückfragen merkt es sich den Gesprächskontext.
- **Anreichern:** „Ergänze Referenz X um relevante Fakten" → Claude recherchiert per **Websuche**
  die wichtigsten Fakten (z.B. Adresse/Telefon/Bewertung) und hängt sie an den Eintrag an.
- **Erinnern:** Ein Hintergrund-Loop prüft jede Minute fällige, offene Todos und schickt genau
  **eine** proaktive Telegram-Nachricht pro Todo.
- **Proaktiv:** täglicher **Digest** (Morgenüberblick) und wöchentliches **Review** (Rückblick +
  Fokus), automatisch zur eingestellten Zeit oder on-demand per `/digest` / `/review`.

## Funktionen

| Bereich | Was |
|---|---|
| **Erfassen** | Freitext **und Sprachnachrichten** → strukturierte Todos / Ideen / Notizen / Referenzen |
| **Suche** | hybrid: semantisch (pgvector) **+** deutscher Volltext, fusioniert mit RRF, mit Distanz-Schwelle |
| **Fragen** | agentischer Claude-Loop, begründete Antworten aus den echten Daten |
| **Gedächtnis** | kurzes Konversations-Gedächtnis pro Chat für Rückfragen; `/reset` startet neu |
| **Bearbeiten** | `update_item` (Titel/Inhalt/Typ/Fälligkeit/Priorität/Status/Projekt/Tags), `complete_item`, `delete_item` |
| **Projekte** | automatische Zuordnung beim Erfassen; `create_project`; Projekt-Ansicht im Dashboard |
| **Anreichern** | „Ergänze Eintrag X um relevante Fakten" → Claude recherchiert per **Websuche** die wichtigsten typgerechten Fakten (Hotel: Adresse/Telefon/Bewertung usw.) und hängt sie an den Inhalt an (für jeden Eintragstyp) |
| **Erinnerungen** | proaktive Benachrichtigung zu fälligen Todos (uhrzeitgenau, Zeitzone `TIMEZONE`) |
| **Digest & Review** | täglicher Morgenüberblick + wöchentlicher Rückblick, automatisch oder per `/digest` / `/review` |
| **Lern-Rückblick** | `/recently_learned` — fasst zusammen, was du zuletzt gelernt/festgehalten hast (neue Notizen/Ideen + erledigte Todos der letzten 7 Tage) |
| **Dokumente** | Dateien (xlsx/PDF/Bilder) je Projekt — per Telegram **und** Dashboard; mit freiem **Kommentar** je Datei (Bildunterschrift; `#Projekt` ordnet zu). Bytes im Volume, Metadaten in der DB |
| **Web-Dashboard** | FastAPI-Oberfläche zum Browsen, Suchen, Bearbeiten und Verwalten der Dokumente (Port 8001) |

### Agent-Tools

| Tool | Zweck |
|---|---|
| `now` | aktuelles Datum/Uhrzeit (vor Fälligkeits-Logik) |
| `list_projects` | aktive Projekte inkl. Anzahl offener Todos |
| `list_todos` | Todos, gefiltert nach Status/Fälligkeit/Projekt/Priorität |
| `search` | hybride semantische + Volltextsuche über alle Einträge |
| `list_recent` | kürzlich hinzugekommene/geänderte Einträge (Zeitfenster in Tagen, optional Typ-Filter) |
| `complete_item` | Todo als erledigt markieren |
| `update_item` | Felder eines Eintrags ändern (partiell; re-embedded bei Textänderung) |
| `delete_item` | Eintrag endgültig löschen |
| `create_project` | neues (leeres) Projekt anlegen (keine Duplikate) |
| `enrich_item` | per **Websuche** die wichtigsten Fakten zu einem Eintrag recherchieren und anhängen |

## Setup

### 1. Voraussetzungen
- Docker + Docker Compose
- Ein **Telegram-Bot-Token** von [@BotFather](https://t.me/BotFather)
- Deine **Telegram-User-ID** (via [@userinfobot](https://t.me/userinfobot))
- Ein **Anthropic API Key**

### 2. Konfigurieren
```bash
cp .env.example .env
# .env ausfüllen: TELEGRAM_BOT_TOKEN, ALLOWED_TELEGRAM_USER_IDS, ANTHROPIC_API_KEY
```
> Ist `ALLOWED_TELEGRAM_USER_IDS` leer, sperrt der Bot **alle** aus (deny by default).

### 3. Starten
```bash
docker compose up -d --build
docker compose logs -f app        # warte auf "Second Brain ist bereit. 🧠"
```
> Beim ersten Start lädt das Embedding-Modell (~2 GB) herunter. Die erste Sprachnachricht lädt
> zusätzlich einmalig das Whisper-Modell (~0,5 GB). Beides wird im Volume `hf_cache` gecacht.

### 4. Benutzen
Schreib **oder sprich** deinem Bot in Telegram:
- `Idee: wiederkehrende Rechnungen automatisch erkennen` → als Idee gespeichert
- `morgen 9 Uhr KFZ-Versicherung kündigen, Projekt Finanzen, wichtig` → Todo mit Fälligkeit + Uhrzeit + Projekt
- 🎙️ Sprachnachricht → wird transkribiert und wie Text verarbeitet
- 📎 Datei/Foto mit Bildunterschrift → Unterschrift = **Kommentar** (Ort/Begebenheit); optionales `#Projektname` ordnet es einem Projekt zu
- `Was soll ich heute zuerst machen?` → priorisierte, begründete Antwort
- `Setz "KFZ-Versicherung kündigen" auf hohe Priorität` → bearbeitet den Eintrag
- `Ergänze Referenz Quellenhof Südtirol um relevante Fakten` → recherchiert per Websuche und hängt die Fakten an (dauert ~1–2 Min, „tippt…" bleibt sichtbar)
- `Lösche das Todo #7` → löscht den Eintrag

**Befehle:** `/start` · `/help` (Kurzanleitung), `/digest` (Tagesüberblick jetzt),
`/review` (Wochenrückblick jetzt), `/recently_learned` (was du zuletzt gelernt/festgehalten hast),
`/reset` (Gespräch/Gedächtnis zurücksetzen).

> **Proaktive Briefings abschalten:** Die automatischen Digests/Reviews lassen sich in der
> `.env` explizit ausschalten — `DIGEST_ENABLED=false` bzw. `REVIEW_ENABLED=false`. Dann
> verschickt der Bot **nichts** mehr von selbst; die Befehle `/digest` und `/review` bleiben
> für den manuellen Abruf trotzdem verfügbar. (Die Uhrzeiten `DIGEST_HOUR` / `REVIEW_*` steuern
> nur *wann* automatisch gesendet wird.)

## Web-Dashboard
Neben dem Bot läuft eine Browser-Oberfläche (eigener FastAPI-Dienst) unter
**[http://localhost:8001](http://localhost:8001)**:
- alle Einträge browsen und nach Typ filtern
- semantische Suche (dieselbe hybride Suche wie im Bot)
- Einträge **bearbeiten, erledigen, löschen** per Klick
- **Projekte** durchklicken und je Projekt **Dokumente** (xlsx/PDF/Bilder) hochladen & herunterladen
- **Kommentare** je Datei direkt im Web bearbeiten (und beim Hochladen gleich mitgeben)
- **Dateien**-Ansicht: alle Dokumente auf einen Blick; Projekt-Zuordnung per Dropdown ändern

Sie liest dieselbe Datenbank und nutzt dieselben Aktions-Handler wie der Bot — beide
Oberflächen bleiben also konsistent. (Host-Port 8001, falls 8000 belegt ist.)

**Dokumente** gehen auch **per Telegram**: schick dem Bot eine Datei oder ein Foto — die
**Bildunterschrift** ist ein freier **Kommentar** (z.B. Ort oder Begebenheit) und wird mit der
Datei gespeichert; ein optionales **`#Projektname`** darin ordnet sie einem Projekt zu (sonst
landet sie unter „Ohne Projekt" und lässt sich später im Dashboard zuordnen). Die Kommentare
werden im Dashboard angezeigt und lassen sich dort bearbeiten (und beim Hochladen im Web direkt
mitgeben). Dateien liegen im Volume `docdata`, nur die Metadaten in der DB.

## Datenbank inspizieren
```bash
docker compose exec db psql -U secondbrain -d secondbrain -c \
  "SELECT id, type, title, status, due_at FROM items ORDER BY id DESC LIMIT 20;"
```

## Migrationen
`migrations/001_init.sql` legt beim **ersten** Start eines leeren Daten-Volumes das Schema an
(der ganze Ordner ist als `docker-entrypoint-initdb.d` gemountet). Spätere Schemaänderungen
liegen als nummerierte, **idempotente** Dateien vor und werden bei einer bestehenden DB von Hand
angewandt, z.B.:
```bash
docker compose exec -T db psql -U secondbrain -d secondbrain < migrations/002_add_reminders.sql
docker compose exec -T db psql -U secondbrain -d secondbrain < migrations/003_documents.sql
docker compose exec -T db psql -U secondbrain -d secondbrain < migrations/004_document_notes.sql
```
`002` hebt `due_date` → `due_at` (mit Uhrzeit) an und ergänzt `reminded_at`; `003` legt die
`documents`-Tabelle an; `004` ergänzt die Kommentar-Spalte `note` an Dokumenten.

## Tests
```bash
pip install -r requirements.txt pytest
pytest
```
Die Unit-Tests decken reine Logik ab (Normalisierung, RRF-Fusion, Vektor-Literal, Zeit-Parsing);
sie brauchen weder DB noch API.

## Modell-Hinweise
- **Embeddings** laufen **lokal** (kostenlos, deutschtauglich). Wechselst du `EMBEDDING_MODEL`,
  muss die Vektor-Dimension in `migrations/001_init.sql` (`VECTOR(1024)`) passen und die Items
  müssen neu eingebettet werden.
- **Sprache-zu-Text** läuft **lokal** via `faster-whisper` (CPU). Größe über `WHISPER_MODEL`
  (`tiny`…`large-v3`), Sprache über `WHISPER_LANGUAGE` (`de` oder `auto`).
- **Claude** (Router/Extraktion = Haiku, Reasoning = Opus) wird über die Anthropic API genutzt;
  Nachrichtentexte werden dorthin gesendet.
- **Websuche:** Die Fakten-Anreicherung (`enrich_item`) nutzt das Server-Tool `web_search` der
  Anthropic-API. Es muss für den API-Key freigeschaltet sein und kostet pro Suche ein paar Cent —
  wird aber **nur** beim Anreichern ausgelöst, normale Abfragen bleiben suchfrei.

## Datenschutz — was verlässt den Rechner?
Selbst gehostet heißt hier: **Ablage, Suche, Embeddings und Spracherkennung laufen lokal** — das
Reasoning (Claude) nutzt aber die Anthropic-Cloud. Es ist also „self-hosted für die Ablage", nicht
„offline".

**Bleibt lokal (geht nie an Anthropic):**

| Daten | Wo |
|---|---|
| Audio von Sprachnachrichten | lokal transkribiert (faster-whisper); die Audiodatei verlässt den Rechner nie |
| Embeddings | lokal erzeugt (bge-m3) |
| Dokumente/Fotos | nur im Volume `docdata` + Metadaten in der DB; der Inhalt wird nie an Claude gesendet |
| Datenbank & Suche | Postgres + Vektor-/Volltextsuche laufen lokal |
| `.env` (API-Key, Bot-Token) | lokal, nicht im Image, nicht im Repo |

**Geht an Anthropic (Text, über HTTPS):**

| Wann | Was gesendet wird |
|---|---|
| jede Nachricht | voller Text bzw. Transkript → Router (Haiku) |
| beim Erfassen | zusätzlich der Text → Extraktion (Haiku) |
| bei Fragen | deine Frage **+ die per Tools gelesenen Einträge** (Titel/Inhalt/Fälligkeit/Projekt/Tags) → Reasoning (Opus) |
| Digest & Review | lesen Einträge und senden sie an Anthropic — **nur wenn aktiviert** (`DIGEST_ENABLED` / `REVIEW_ENABLED`) |
| Anreicherung | der Eintrag **+ eine Websuche** (läuft server-seitig bei Anthropic und fragt das öffentliche Web) |

Kurz: Sobald Claude antwortet, fließen die **abgefragten Notizinhalte** als Kontext zu Anthropic;
die Anreicherung geht zusätzlich ins öffentliche Web.

**Sicherheit & Hinweise:**
- Transport ist TLS-verschlüsselt. Nach Anthropics kommerziellen API-Bedingungen werden API-Daten
  standardmäßig **nicht zum Modelltraining** verwendet (begrenzte Aufbewahrung zur
  Missbrauchserkennung; Zero-Data-Retention auf Anfrage möglich) — Details in Anthropics aktueller
  Data-Policy.
- **Proaktive Briefings sind opt-in** (`DIGEST_ENABLED` / `REVIEW_ENABLED`, Default aus) — ohne dein
  Zutun geht dadurch nichts an Anthropic.
- **Das Web-Dashboard hat keine Authentifizierung** — nur für localhost/vertrauenswürdiges Netz
  gedacht; nicht offen ins Internet stellen (sonst Reverse-Proxy mit Login oder VPN davorschalten).
- Der Bot ist **deny-by-default** (nur deine Telegram-User-ID darf ihn nutzen).

## Roadmap
- **Phase 1 (fertig):** Erfassen, hybride Suche, agentische Abfragen, Docker.
- **Phase 2 (fertig):** Sprachnachrichten, Uhrzeiten (`TIMESTAMPTZ`), Erinnerungen,
  `update_item` / `delete_item`, `create_project`, robusteres Routing.
- **Phase 3 (fertig):** Konversations-Gedächtnis, täglicher Digest, wöchentliches Review,
  Web-Dashboard, Dokumente je Projekt; zurückgestellt: Kalender-Integration.
- **Phase 4 (fertig):** Fakten-Anreicherung per Websuche (`enrich_item`), durchgehende
  „tippt…"-Anzeige bei langen Antworten.
- **Release:** aktueller Stand als **v1.0.0** getaggt.
- **Seit v1.0:** Lern-Rückblick (`/recently_learned`).
- **Geplant (nach v1.0):** proaktive Vorschläge (z.B. „Du hast 3 Ideen zu RAG — zusammenfassen?"),
  erledigte Todos im Dashboard ausblenden, wiederkehrende Todos; optional:
  Beobachtbarkeit/Kosten-Logging und Dashboard-Login.

Siehe den vollständigen Plan in [PLAN.md](PLAN.md).
