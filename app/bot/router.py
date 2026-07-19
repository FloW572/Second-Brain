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
                "description": "capture = the user wants to STORE new information (a concrete "
                               "todo/idea/note/reference to keep). query = everything else: "
                               "questions/analysis about stored data, changes/actions on existing "
                               "items (edit, rename, reschedule, set priority/status, complete, "
                               "delete), AND conversation/meta directed at the assistant "
                               "(greeting, thanks, 'who are you', 'call yourself X').",
            }
        },
        "required": ["intent"],
    },
}

SYSTEM = (
    "Entscheide die Absicht der Nachricht:\n"
    "- capture = der Nutzer will NEUE Information ABLEGEN (ein konkretes Todo/Idee/Notiz/"
    "Referenz zum Merken).\n"
    "- query = alles andere: Fragen/Auswertungen zu gespeicherten Daten, Änderungen/Aktionen "
    "an bestehenden Einträgen (ändern, umbenennen, verschieben, Priorität/Status setzen, "
    "erledigt markieren, löschen) UND an den Assistenten gerichtete Konversation/Meta "
    "(Begrüßung, Dank, 'wer bist du?', 'nenne dich ab jetzt X').\n"
    "Beispiele capture: 'Idee: App für X', 'morgen 9 Uhr Rechnung zahlen', 'Notiz: WLAN-Passwort'.\n"
    "Beispiele query: 'Was soll ich heute tun?', 'Zeig mir offene Todos', "
    "'Setz Auto verkaufen auf hohe Priorität', 'lösche #7', 'Wer bist du?', "
    "'Nenne dich ab jetzt Husi', 'Danke!'.\n"
    "Nur wenn klar etwas ABGELEGT werden soll → capture. Sonst → query. Antworte nur über das Tool."
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
