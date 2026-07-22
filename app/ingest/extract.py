"""Turn a free-text message into structured fields using Claude (forced tool call)."""
import logging
from datetime import datetime
from typing import cast
from zoneinfo import ZoneInfo

from app.models import ITEM_TYPES, CaptureData
from app.usage import create_message

logger = logging.getLogger(__name__)

STRUCTURE_TOOL = {
    "name": "structure_item",
    "description": "Extract structured fields from a captured note/todo/idea.",
    "input_schema": {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": list(ITEM_TYPES),
                "description": "todo = actionable task; idea = idea/thought; "
                               "note = general note; reference = link/resource to keep.",
            },
            "title": {"type": "string", "description": "Short, concise title (max ~10 words)."},
            "content": {"type": ["string", "null"], "description": "Fuller detail, or null."},
            "project_hint": {
                "type": ["string", "null"],
                "description": "Name of a project this belongs to, if mentioned; else null.",
            },
            "due_at": {
                "type": ["string", "null"],
                "description": "Due date/time as ISO — 'YYYY-MM-DD' if only a day is meant, or "
                               "'YYYY-MM-DDTHH:MM' if a time is mentioned. Resolve relative terms "
                               "('morgen', 'nächste Woche', 'Freitag', 'heute 19 Uhr') against the "
                               "current date/time given in the system prompt; null if none.",
            },
            "priority": {
                "type": ["integer", "null"],
                "description": "1 = high, 2 = medium, 3 = low; null if unclear.",
            },
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["type", "title"],
    },
}


async def extract_structure(anthropic, text: str, settings, now: str | None = None) -> CaptureData:
    now = now or datetime.now(ZoneInfo(settings.timezone)).isoformat(timespec="minutes")
    system = (
        f"Aktuelle Zeit: {now} (Zeitzone {settings.timezone}). Du extrahierst aus einer kurzen "
        f"Notiz strukturierte Felder für ein persönliches Second-Brain-System. Löse relative "
        f"Datums- und Zeitangaben ('morgen', 'nächste Woche', 'Freitag', 'heute 19 Uhr') gegen "
        f"die aktuelle Zeit auf. Halte den Titel kurz und prägnant. Antworte ausschließlich über das Tool."
    )
    try:
        resp = await create_message(
            anthropic,
            label="extract",
            model=settings.extract_model,
            max_tokens=600,
            system=system,
            tools=[STRUCTURE_TOOL],
            tool_choice={"type": "tool", "name": "structure_item"},
            messages=[{"role": "user", "content": text}],
        )
        for block in resp.content:
            if block.type == "tool_use" and block.name == "structure_item":
                return cast(CaptureData, dict(block.input))
    except Exception:
        logger.exception("extract_structure failed; falling back to plain note")
    return {"type": "note", "title": text[:80], "content": text}
