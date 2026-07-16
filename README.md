# Second Brain 🧠

Ein persönliches, selbst gehostetes "Second Brain": Todos, Ideen, Projekte und Notizen
werden per **Telegram** vom Handy erfasst, in **PostgreSQL + pgvector** gespeichert und von
**Claude** ausgewertet — z.B. *„Was sollte ich heute zuerst tun?“*

## Architektur

```
Handy ──Telegram──▶ Bot (Polling) ──▶ Backend (Python)
                                        ├─ Router (Claude Haiku): capture | query?
                                        ├─ Capture: Claude strukturiert → Embedding (lokal) → DB
                                        └─ Query: agentischer Claude-Loop (Opus) mit Tools über die DB
                                        │
                                        ▼
                              PostgreSQL 16 + pgvector
                              (projects, items + embedding + fts)
```

- **Erfassen:** Freitext → Claude extrahiert Typ/Titel/Fälligkeit/Priorität/Tags → lokales
  multilinguales Embedding (bge-m3) → gespeichert.
- **Fragen:** Claude nutzt Tools (`now`, `list_projects`, `list_todos`, `search`, `complete_item`),
  liest die echten Daten und antwortet begründet.

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

### 3. Starten
```bash
docker compose up -d --build
docker compose logs -f app        # warte auf "Second Brain ist bereit. 🧠"
```
> Beim ersten Start lädt das Embedding-Modell (~2 GB) herunter und wird im Volume `hf_cache`
> zwischengespeichert.

### 4. Benutzen
Schreib deinem Bot in Telegram:
- `Idee: wiederkehrende Rechnungen automatisch erkennen` → wird als Idee gespeichert
- `morgen die KFZ-Versicherung kündigen, Projekt Finanzen, wichtig` → Todo mit Fälligkeit/Projekt
- `Was soll ich heute zuerst machen?` → priorisierte, begründete Antwort

## Datenbank inspizieren
```bash
docker compose exec db psql -U secondbrain -d secondbrain -c \
  "SELECT id, type, title, status, due_date FROM items ORDER BY id DESC LIMIT 20;"
```

## Tests
```bash
pip install -r requirements.txt pytest
pytest
```
Die Unit-Tests decken reine Logik ab (Normalisierung, RRF-Fusion, Vektor-Literal);
sie brauchen weder DB noch API.

## Modell-Hinweise
- **Embeddings** laufen **lokal** (kostenlos, deutschtauglich). Wechselst du `EMBEDDING_MODEL`,
  muss die Vektor-Dimension in `migrations/001_init.sql` (`VECTOR(1024)`) passen und die Items
  müssen neu eingebettet werden.
- **Claude** (Router/Extraktion = Haiku, Reasoning = Opus) wird über die Anthropic API genutzt;
  Nachrichtentexte werden dorthin gesendet.

## Roadmap
- **Phase 2:** Sprachnachrichten (faster-whisper), Erinnerungen, `update_item`.
- **Phase 3:** täglicher Digest, wöchentliches Review, Web-Dashboard, Kalender.

Siehe den vollständigen Plan in [PLAN.md](PLAN.md).
