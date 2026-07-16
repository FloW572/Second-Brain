"""Cheap intent routing: is a message something to store, or a question to answer?"""
import logging

logger = logging.getLogger(__name__)

ROUTE_TOOL = {
    "name": "route",
    "description": "Classify the user's message intent.",
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": ["capture", "query"],
                "description": "capture = new information to store (todo/idea/note). "
                               "query = a question / request to reason over stored data.",
            }
        },
        "required": ["intent"],
    },
}

SYSTEM = (
    "Entscheide, ob die Nachricht NEUE Information zum Speichern ist (capture) oder eine "
    "FRAGE bzw. Bitte um Auswertung der gespeicherten Daten (query). "
    "Beispiele capture: 'Idee: App für X', 'morgen Rechnung zahlen'. "
    "Beispiele query: 'Was soll ich heute tun?', 'Welche Ideen habe ich zu X?', "
    "'Zeig mir offene Todos'. Antworte nur über das Tool."
)


async def classify(anthropic, text: str, settings) -> str:
    try:
        resp = await anthropic.messages.create(
            model=settings.router_model,
            max_tokens=100,
            system=SYSTEM,
            tools=[ROUTE_TOOL],
            tool_choice={"type": "tool", "name": "route"},
            messages=[{"role": "user", "content": text}],
        )
        for block in resp.content:
            if block.type == "tool_use" and block.name == "route":
                return block.input.get("intent", "capture")
    except Exception:
        logger.exception("router failed; defaulting to capture")
    return "capture"
