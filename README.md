# Second Brain 🧠

Ein persönliches, selbst gehostetes „Second Brain": Todos, Ideen, Projekte und Notizen
werden per **Telegram** — als **Text oder Sprachnachricht** — vom Handy erfasst, in
**PostgreSQL + pgvector** gespeichert und von **Claude** ausgewertet, z.B.
*„Was sollte ich heute zuerst tun?"*. Fällige Todos meldet der Bot **proaktiv** als Erinnerung.

## Architektur

```
Handy ──Telegram──▶ Bot (Polling) ──▶ Backend (Python)
 Text │ 🎙️ Voice                       ├─ Voice: faster-whisper (lokal) → Text
                                        ├─ Router (Claude Haiku): capture | query?
                                        ├─ Capture: Claude strukturiert → Embedding (lokal) → DB
                                        ├─ Query: agentischer Claude-Loop (Opus) mit Tools über die DB
                                        └─ Reminder-Loop (asyncio): fällige Todos → Push
                                        │
                                        ▼
                              PostgreSQL 16 + pgvector
                              (projects, items + embedding + fts)
```

- **Erfassen:** Text oder Sprachnachricht (Voice wird lokal transkribiert) → Claude extrahiert
  Typ/Titel/Fälligkeit (mit Uhrzeit)/Priorität/Projekt/Tags → lokales, multilinguales Embedding
  (bge-m3) → gespeichert.
- **Fragen & Handeln:** Claude nutzt Tools, liest bzw. verändert die echten Daten und antwortet
  begründet — statt zu raten.
- **Erinnern:** Ein Hintergrund-Loop prüft jede Minute fällige, offene Todos und schickt genau
  **eine** proaktive Telegram-Nachricht pro Todo.

## Funktionen

| Bereich | Was |
|---|---|
| **Erfassen** | Freitext **und Sprachnachrichten** → strukturierte Todos / Ideen / Notizen / Referenzen |
| **Suche** | hybrid: semantisch (pgvector) **+** deutscher Volltext, fusioniert mit RRF |
| **Fragen** | agentischer Claude-Loop, begründete Antworten aus den echten Daten |
| **Bearbeiten** | `update_item` (Titel/Inhalt/Typ/Fälligkeit/Priorität/Status/Projekt/Tags), `complete_item`, `delete_item` |
| **Erinnerungen** | proaktive Benachrichtigung zu fälligen Todos (uhrzeitgenau, Zeitzone `TIMEZONE`) |

### Agent-Tools

| Tool | Zweck |
|---|---|
| `now` | aktuelles Datum/Uhrzeit (vor Fälligkeits-Logik) |
| `list_projects` | aktive Projekte inkl. Anzahl offener Todos |
| `list_todos` | Todos, gefiltert nach Status/Fälligkeit/Projekt/Priorität |
| `search` | hybride semantische + Volltextsuche über alle Einträge |
| `complete_item` | Todo als erledigt markieren |
| `update_item` | Felder eines Eintrags ändern (partiell; re-embedded bei Textänderung) |
| `delete_item` | Eintrag endgültig löschen |

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
- `Was soll ich heute zuerst machen?` → priorisierte, begründete Antwort
- `Setz "KFZ-Versicherung kündigen" auf hohe Priorität` → bearbeitet den Eintrag
- `Lösche das Todo #7` → löscht den Eintrag

## Web-Dashboard
Neben dem Bot läuft eine Browser-Oberfläche (eigener FastAPI-Dienst) unter
**[http://localhost:8001](http://localhost:8001)**:
- alle Einträge browsen und nach Typ filtern
- semantische Suche (dieselbe hybride Suche wie im Bot)
- Einträge **bearbeiten, erledigen, löschen** per Klick
- **Projekte** durchklicken und je Projekt **Dokumente** (xlsx/PDF/Bilder) hochladen & herunterladen
- **Dateien**-Ansicht: alle Dokumente auf einen Blick; Projekt-Zuordnung per Dropdown ändern

Sie liest dieselbe Datenbank und nutzt dieselben Aktions-Handler wie der Bot — beide
Oberflächen bleiben also konsistent. (Host-Port 8001, falls 8000 belegt ist.)

**Dokumente** gehen auch **per Telegram**: schick dem Bot eine Datei oder ein Foto — die
**Bildunterschrift** bestimmt das Projekt (ohne Bildunterschrift landet es unter „Ohne Projekt"
und lässt sich später im Dashboard zuordnen). Dateien liegen im Volume `docdata`, nur die
Metadaten in der DB.

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
```

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

## Roadmap
- **Phase 1 (fertig):** Erfassen, hybride Suche, agentische Abfragen, Docker.
- **Phase 2 (fertig):** Sprachnachrichten, Uhrzeiten (`TIMESTAMPTZ`), Erinnerungen,
  `update_item` / `delete_item`, robusteres Routing.
- **Phase 3 (läuft):** Konversations-Gedächtnis ✓, täglicher Digest ✓, wöchentliches Review ✓,
  Web-Dashboard ✓; offen: Kalender-Integration.

Siehe den vollständigen Plan in [PLAN.md](PLAN.md).
