"""Ingestion pipeline: free text -> structured fields -> embedding -> stored item."""
import logging

from app.documents import extract_project_hashtag
from app.duetime import parse_due
from app.ingest.embed import embed_text, to_vector_literal
from app.ingest.extract import extract_structure
from app.ingest.normalize import normalize_capture
from app.ingest.projects import resolve_project
from app.models import CaptureData

logger = logging.getLogger(__name__)

_TYPE_LABEL = {
    "todo": ("✅", "Todo"),
    "idea": ("💡", "Idee"),
    "note": ("📝", "Notiz"),
    "reference": ("🔗", "Referenz"),
}


def _confirmation(data: dict, project_name: str | None, due) -> str:
    emoji, label = _TYPE_LABEL.get(data["type"], ("📝", "Notiz"))
    lines = [f'{emoji} {label}: {data["title"]}']
    if project_name:
        lines.append(f"📁 Projekt: {project_name}")
    if due:
        lines.append(f"📅 Fällig: {due.strftime('%Y-%m-%d %H:%M')}")
    if data["priority"]:
        lines.append("❗ Priorität: " + {1: "hoch", 2: "mittel", 3: "niedrig"}[data["priority"]])
    if data["tags"]:
        lines.append("🏷️ " + ", ".join(data["tags"]))
    return "\n".join(lines)


async def _open_todo_candidates(pool, settings, query_text: str) -> list[dict]:
    """Open todos a capture message might actually be about, so the extractor can
    update one of them instead of creating a duplicate (e.g. 'X morgen 19 Uhr' when
    an open todo about X already exists)."""
    # Local import: app.search imports app.ingest.embed, which would otherwise cycle
    # back through this package's __init__ while it's still being loaded.
    from app.search import hybrid_search
    try:
        hits = await hybrid_search(pool, settings, query_text, types=["todo"], limit=5)
    except Exception:
        logger.exception("candidate search for duplicate detection failed")
        return []
    return [
        {"id": h["id"], "title": h["title"], "due_at": h["due_at"]}
        for h in hits if h["status"] != "done"
    ][:4]


async def _update_existing(pool, item_id: int, data: CaptureData, settings) -> str:
    """Apply a capture message as an update to an already-existing todo instead of
    inserting a duplicate."""
    from app.query.tools import _update_item  # local import: see _open_todo_candidates
    args: dict = {"id": item_id}
    if data.get("due_at"):
        args["due_at"] = data["due_at"]
    if data.get("priority"):
        args["priority"] = data["priority"]
    result = await _update_item(pool, settings, args)
    if not result.get("updated"):
        logger.warning("could not update existing item %s: %s", item_id, result.get("reason"))
        return f"⚠️ Konnte bestehendes Todo #{item_id} nicht aktualisieren."
    due = parse_due(data["due_at"], settings.timezone) if data.get("due_at") else None
    lines = [f"🔄 Aktualisiert: {result['title']}"]
    if due:
        lines.append(f"📅 Fällig: {due.strftime('%Y-%m-%d %H:%M')}")
    return "\n".join(lines)


async def capture(pool, anthropic, text: str, source: str, settings) -> str:
    """Extract, embed and store one captured message. Returns a confirmation string."""
    # A #Projektname typed in the message assigns the project deterministically (same
    # convention as file captions); it's stripped before extraction and overrides
    # whatever project Claude might otherwise guess.
    project_tag, body = extract_project_hashtag(text)
    query_text = body or text

    candidates = await _open_todo_candidates(pool, settings, query_text)
    raw = await extract_structure(anthropic, query_text, settings, candidates=candidates)
    existing_id = raw.get("existing_item_id")
    data: CaptureData = normalize_capture(raw, query_text)
    if project_tag:
        data["project_hint"] = project_tag

    if existing_id and existing_id in {c["id"] for c in candidates}:
        return await _update_existing(pool, existing_id, data, settings)

    emb_lit = to_vector_literal(
        await embed_text(f"{data['title']}\n{data['content'] or ''}", settings.embedding_model)
    )
    due = parse_due(data["due_at"], settings.timezone)

    async with pool.connection() as conn:
        project_id, project_name = await resolve_project(conn, data["project_hint"])
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO items
                    (type, title, content, project_id, status, priority,
                     due_at, tags, source, raw_input, embedding)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                RETURNING id
                """,
                (data["type"], data["title"], data["content"], project_id, data["status"],
                 data["priority"], due, data["tags"], source, text, emb_lit),
            )
            item_id = (await cur.fetchone())[0]
        await conn.commit()

    logger.info("Stored item id=%s type=%s", item_id, data["type"])
    return _confirmation(data, project_name, due)
