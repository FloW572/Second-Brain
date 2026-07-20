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
                "description": "capture = new information to store (todo/idea/note/reference). "
                               "query = anything about ALREADY-stored data: questions, analysis, "
                               "OR changes/actions on existing items (edit, rename, reschedule, "
                               "set priority/status, complete, delete).",
            }
        },
        "required": ["intent"],
    },
}

SYSTEM = (
    "Entscheide die Absicht der Nachricht:\n"
    "- capture = NEUE Information zum Speichern (ein neues Todo/Idee/Notiz/Referenz).\n"
    "- query = alles, was sich auf BEREITS gespeicherte Daten bezieht: Fragen, Auswertungen "
    "ODER Änderungen/Aktionen an bestehenden Einträgen (ändern, umbenennen, verschieben, "
    "Priorität/Status setzen, erledigt markieren, löschen).\n"
    "Beispiele capture: 'Idee: App für X', 'morgen Rechnung zahlen', 'Notiz: WLAN-Passwort'.\n"
    "Beispiele query: 'Was soll ich heute tun?', 'Welche Ideen habe ich zu X?', 'Zeig mir offene Todos', "
    "'Setz Auto verkaufen auf hohe Priorität', 'verschiebe X auf morgen', 'markiere X als erledigt', "
    "'lösche das doppelte Auto verkaufen'.\n"
    "Im Zweifel, ob es eine Änderung an Bestehendem ist: query. Antworte nur über das Tool."
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
