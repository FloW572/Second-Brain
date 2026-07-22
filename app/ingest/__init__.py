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


async def capture(pool, anthropic, text: str, source: str, settings) -> str:
    """Extract, embed and store one captured message. Returns a confirmation string."""
    # A #Projektname typed in the message assigns the project deterministically (same
    # convention as file captions); it's stripped before extraction and overrides
    # whatever project Claude might otherwise guess.
    project_tag, body = extract_project_hashtag(text)
    raw = await extract_structure(anthropic, body or text, settings)
    data: CaptureData = normalize_capture(raw, body or text)
    if project_tag:
        data["project_hint"] = project_tag

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
