"""Agentic query loop: Claude reasons over the second brain using the tools."""
import json
import logging

from app.query.tools import TOOLS, run_tool

logger = logging.getLogger(__name__)

MAX_TURNS = 6

SYSTEM = (
    "Du bist mein persönliches 'Second Brain'-Assistenzsystem. Auf Basis meiner "
    "gespeicherten Todos, Ideen, Projekte und Notizen beantwortest du Fragen und hilfst "
    "mir zu priorisieren.\n\n"
    "Regeln:\n"
    "- Nutze IMMER die Tools, um die tatsächlich gespeicherten Daten zu lesen — rate nie.\n"
    "- Rufe zuerst `now` auf, wenn Fälligkeiten oder 'heute'/'diese Woche' eine Rolle spielen.\n"
    "- Wenn ich frage, was ich tun soll, wäge Fälligkeit, Priorität und Projektkontext ab "
    "und begründe deine Empfehlung kurz.\n"
    "- Antworte auf Deutsch, knapp und konkret. Nutze kurze Listen statt langer Absätze."
)


async def answer(anthropic, pool, question: str, settings) -> str:
    messages = [{"role": "user", "content": question}]

    for _ in range(MAX_TURNS):
        resp = await anthropic.messages.create(
            model=settings.query_model,
            max_tokens=1500,
            system=SYSTEM,
            tools=TOOLS,
            messages=messages,
        )

        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text").strip() \
                or "(keine Antwort)"

        messages.append({"role": "assistant", "content": resp.content})
        tool_results = []
        for block in resp.content:
            if block.type == "tool_use":
                result = await run_tool(pool, settings, block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })
        messages.append({"role": "user", "content": tool_results})

    return "⚠️ Ich konnte die Frage nicht in der erwarteten Schrittzahl beantworten."
