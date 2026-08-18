"""Agentic query loop: Claude reasons over the second brain using the tools."""
import json
import logging

from app.query.tools import TOOLS, run_tool
from app.usage import create_message

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
    "- Biete oder verspreche NUR Aktionen an, die deine Tools tatsächlich ermöglichen "
    "(lesen/suchen, ändern, erledigt markieren, löschen, per Websuche mit Fakten ergänzen, "
    "Projekte anlegen/umbenennen/löschen). Erfinde keine Fähigkeiten, die es noch nicht gibt.\n"
    "- Ein Projekt umbenennen: IMMER `rename_project` nutzen (Einträge bleiben dran) — verschiebe "
    "NIE Einträge einzeln, um ein Projekt umzubenennen. Ein leeres Projekt entfernst du mit "
    "`delete_project`; ist es nicht leer, meldet das Tool das, dann sag mir Bescheid statt zu raten.\n"
    "- Jährlich wiederkehrende Daten (Geburtstag, Jahrestag) gehören NICHT als Todo angelegt, "
    "sondern mit `add_occasion` — dann erinnere ich jedes Jahr automatisch mit Vorlauf. "
    "`list_occasions` zeigt sie an, `delete_occasion` entfernt einen.\n"
    "- Fragt jemand nach Geschenk- oder Unternehmungsideen für eine Person, suche ZUERST mit "
    "`search` nach dem, was zu ihr gespeichert ist (Vorlieben, Marken, Interessen, alte Ideen), "
    "und leite die Vorschläge daraus ab — nenne dabei die id der Notiz. Erst wenn du nichts "
    "findest, sag das in einem Satz und gib allgemeine Vorschläge. Frage nicht erst um "
    "Erlaubnis nachzusehen, sondern sieh nach.\n"
    "- Wenn ich einen Eintrag 'um relevante Fakten ergänzen' o.ä. will, finde ihn zuerst mit "
    "`search` und rufe dann `enrich_item` mit seiner id auf; nenne mir danach kurz, welche "
    "Fakten hinzugefügt wurden. Bei Mehrdeutigkeit frage nach der richtigen id.\n"
    "- Bei Änderungen oder Löschungen: Wenn mehrere Einträge passen, frage nach, welcher "
    "gemeint ist (nenne die betroffenen ids), statt zu raten. Lösche nie ungefragt das Falsche.\n"
    "- Antworte auf Deutsch, knapp und konkret.\n"
    "- Formatiere für Telegram als REINEN Text — KEIN Markdown (kein **, kein #, keine "
    "-Aufzählungszeichen); das wird in Telegram nicht gerendert und sieht unschön aus.\n"
    "- Bei Listen: ein Eintrag pro Block, getrennt durch eine Leerzeile. "
    "Kopfzeile im Format 'EMOJI #id Titel' (Emoji je Typ: ✅ todo, 💡 idee, 📝 notiz, 🔗 referenz). "
    "Darunter — nur wenn vorhanden und nicht mit dem Titel redundant — eine eingerückte Detailzeile, "
    "kompakt mit ' · ' getrennt, z.B. '📅 2026-07-25 · Prio: hoch · 📁 Finanzen · 🏷️ steuer'. "
    "Lass leere Felder weg und wiederhole den Titel nicht im Detail."
)


async def answer(anthropic, pool, question: str, settings, history=None) -> str:
    messages = list(history or [])          # prior conversation turns, if any
    messages.append({"role": "user", "content": question})

    for _ in range(MAX_TURNS):
        resp = await create_message(
            anthropic,
            label="query",
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
                result = await run_tool(anthropic, pool, settings, block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })
        messages.append({"role": "user", "content": tool_results})

    return "⚠️ Ich konnte die Frage nicht in der erwarteten Schrittzahl beantworten."
