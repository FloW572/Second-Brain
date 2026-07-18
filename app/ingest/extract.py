"""Turn a free-text message into structured fields using Claude (forced tool call)."""
import logging
from datetime import date

logger = logging.getLogger(__name__)

STRUCTURE_TOOL = {
    "name": "structure_item",
    "description": "Extract structured fields from a captured note/todo/idea.",
    "input_schema": {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": ["todo", "idea", "note", "reference"],
                "description": "todo = actionable task; idea = idea/thought; "
                               "note = general note; reference = link/resource to keep.",
            },
            "title": {"type": "string", "description": "Short, concise title (max ~10 words)."},
            "content": {"type": ["string", "null"], "description": "Fuller detail, or null."},
            "project_hint": {
                "type": ["string", "null"],
                "description": "Name of a project this belongs to, if mentioned; else null.",
            },
            "due_date": {
                "type": ["string", "null"],
                "description": "Due date as ISO YYYY-MM-DD, resolved from relative terms "
                               "(e.g. 'morgen') against today; null if none.",
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


async def extract_structure(anthropic, text: str, settings, today: str | None = None) -> dict:
    today = today or date.today().isoformat()
    system = (
        f"Heute ist {today}. Du extrahierst aus einer kurzen Notiz strukturierte Felder "
        f"für ein persönliches Second-Brain-System. Löse relative Datumsangaben "
        f"('morgen', 'nächste Woche', 'Freitag') gegen das heutige Datum auf. "
        f"Halte den Titel kurz und prägnant. Antworte ausschließlich über das Tool."
    )
    try:
        resp = await anthropic.messages.create(
            model=settings.extract_model,
            max_tokens=600,
            system=system,
            tools=[STRUCTURE_TOOL],
            tool_choice={"type": "tool", "name": "structure_item"},
            messages=[{"role": "user", "content": text}],
        )
        for block in resp.content:
            if block.type == "tool_use" and block.name == "structure_item":
                return dict(block.input)
    except Exception:
        logger.exception("extract_structure failed; falling back to plain note")
    return {"type": "note", "title": text[:80], "content": text}
