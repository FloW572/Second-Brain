"""Proaktive Anstupser: Anlässe rechtzeitig melden und liegengebliebene Ideen auffrischen.

Zwei Loops, gebaut wie ``app.digest`` (eigener asyncio-Task, Minutentakt, lokale Zeit):

  - ``occasion_loop``  — meldet Geburtstage/Jahrestage ``lead_days`` im Voraus und liefert
                          gleich Geschenk-/Aktionsideen aus den gespeicherten Notizen zur
                          Person mit.
  - ``resurface_loop`` — holt einmal pro Woche eine Idee hoch, die seit Wochen unangetastet
                          herumliegt, und schlägt vor, mit wem sie zu welchem Anlass passt.

Beide nutzen den Query-Agenten (``answer``), erben also dessen Tools und Formatierung.
"""
import asyncio
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.digest import _broadcast, _should_send_daily, _should_send_weekly
from app.occasions import KIND_LABEL, due_occasions, mark_notified
from app.query.agent import answer

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 60


def occasion_question(occasion: dict) -> str:
    """Frage an den Agenten: Ideen für diesen Anlass aus den echten Notizen ziehen."""
    person = occasion["person"] or occasion["label"]
    kind = KIND_LABEL.get(occasion["kind"], "Anlass")
    left = occasion["days_until"]
    when = "heute" if left == 0 else ("morgen" if left == 1 else f"in {left} Tagen")
    return (
        f"{when} ({occasion['next_date']}) ist: {occasion['label']} ({kind}). "
        f"Ich brauche rechtzeitig konkrete Ideen, damit ich nicht wieder in letzter Minute suche.\n"
        f"Vorgehen: Suche mit `search` nach allem, was ich zu „{person}“ gespeichert habe — "
        f"Vorlieben, Wünsche, Marken, Interessen, gemeinsame Pläne, alte Ideen. Suche mehrfach mit "
        f"verschiedenen Formulierungen, wenn der erste Treffer dünn ist, und sieh mit "
        f"`list_todos` nach, ob dazu schon etwas offen ist.\n"
        f"Antworte dann mit 3 konkreten Vorschlägen (Geschenk oder gemeinsame Unternehmung), die "
        f"zu den GESPEICHERTEN Vorlieben passen — nicht zu meinen eigenen. Nenne bei jedem "
        f"Vorschlag in Klammern die id der Notiz, auf der er beruht. "
        f"Findest du nichts Gespeichertes, sag das ehrlich in einem Satz und gib stattdessen "
        f"2 allgemeine Vorschläge. Halte es kurz. Beginne direkt mit dem Inhalt, ohne Begrüßung."
    )


def resurface_question(idea: dict) -> str:
    """Frage an den Agenten: liegengebliebene Idee mit passenden Personen zusammenbringen."""
    detail = f"\nInhalt: {idea['content']}" if idea.get("content") else ""
    return (
        f"Diese Idee liegt seit {idea['age_days']} Tagen unangetastet in meinem Second Brain:\n"
        f"#{idea['id']} {idea['title']}{detail}\n\n"
        f"Hilf mir, sie nicht wieder untergehen zu lassen. Suche mit `search` nach Personen, "
        f"Notizen und Anlässen, deren gespeicherte Vorlieben in dieselbe Richtung gehen "
        f"(z.B. wer laut meinen Notizen Outdoor/Action/Ähnliches mag), und antworte kurz mit:\n"
        f"1) mit wem das laut meinen Notizen passen würde (mit id der Notiz),\n"
        f"2) einem konkreten nächsten kleinen Schritt (anfragen, Termin, Buchung),\n"
        f"3) einem guten Zeitfenster, falls sich aus meinen Daten eines ergibt.\n"
        f"Findest du keine passende Person, sag das in einem Satz. "
        f"Beginne direkt mit dem Inhalt, ohne Begrüßung."
    )


async def _dormant_ideas(pool, min_age_days: int, cooldown_days: int, limit: int) -> list[dict]:
    """Ideen, die lange niemand angefasst hat und die zuletzt nicht schon vorgeschlagen wurden."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, title, content,
                   EXTRACT(DAY FROM now() - updated_at)::int AS age_days
            FROM items
            WHERE type = 'idea'
              AND updated_at <= now() - make_interval(days => %(min_age)s)
              AND (nudged_at IS NULL OR nudged_at <= now() - make_interval(days => %(cooldown)s))
            ORDER BY nudged_at ASC NULLS FIRST, updated_at ASC
            LIMIT %(limit)s
            """,
            {"min_age": min_age_days, "cooldown": cooldown_days, "limit": limit},
        )
        rows = await cur.fetchall()
    return [{"id": r[0], "title": r[1], "content": r[2], "age_days": r[3]} for r in rows]


async def _mark_nudged(pool, item_id: int) -> None:
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("UPDATE items SET nudged_at = now() WHERE id = %s", (item_id,))
        await conn.commit()


async def send_occasion_alerts(bot, pool, anthropic, settings, today: date | None = None) -> int:
    """Ein Durchlauf über fällige Anlässe. Gibt zurück, wie viele gemeldet wurden."""
    today = today or datetime.now(ZoneInfo(settings.timezone)).date()
    occasions = await due_occasions(pool, today)
    if not occasions:
        return 0
    recipients = settings.allowed_user_ids
    if not recipients:
        logger.warning("Anlass fällig, aber ALLOWED_TELEGRAM_USER_IDS ist leer.")
        return 0

    sent = 0
    for occasion in occasions:
        text = await answer(anthropic, pool, occasion_question(occasion), settings)
        left = occasion["days_until"]
        when = "Heute" if left == 0 else ("Morgen" if left == 1 else f"In {left} Tagen")
        header = (f'🎁 {when}: {occasion["label"]} '
                  f'({occasion["day"]:02d}.{occasion["month"]:02d}.)')
        if await _broadcast(bot, recipients, f"{header}\n\n{text}"):
            await mark_notified(pool, occasion["id"], today)
            sent += 1
            logger.info("Anlass-Erinnerung gesendet für occasion id=%s", occasion["id"])
    return sent


async def send_idea_resurface(bot, pool, anthropic, settings) -> int:
    """Eine liegengebliebene Idee hochholen. Gibt zurück, wie viele gesendet wurden (0 oder 1)."""
    recipients = settings.allowed_user_ids
    if not recipients:
        logger.warning("Ideen-Auffrischung fällig, aber ALLOWED_TELEGRAM_USER_IDS ist leer.")
        return 0
    ideas = await _dormant_ideas(pool, settings.resurface_min_age_days,
                                 settings.resurface_cooldown_days, limit=1)
    if not ideas:
        logger.info("Keine liegengebliebene Idee zum Auffrischen gefunden.")
        return 0

    idea = ideas[0]
    text = await answer(anthropic, pool, resurface_question(idea), settings)
    header = f'💡 Liegt seit {idea["age_days"]} Tagen herum: {idea["title"]}'
    if not await _broadcast(bot, recipients, f"{header}\n\n{text}"):
        return 0
    await _mark_nudged(pool, idea["id"])
    logger.info("Idee aufgefrischt: item id=%s", idea["id"])
    return 1


async def occasion_loop(bot, pool, anthropic, settings):
    if not settings.occasions_enabled:
        logger.info("Anlass-Erinnerungen deaktiviert (OCCASIONS_ENABLED=false); "
                    "/occasions bleibt nutzbar.")
        return
    if not 0 <= settings.occasion_hour <= 23:
        logger.warning("OCCASION_HOUR=%s ist ungültig (0-23) — Anlässe werden nicht gemeldet.",
                       settings.occasion_hour)
        return
    tz = ZoneInfo(settings.timezone)
    logger.info("Anlass-Loop gestartet (täglich um %02d:00 %s).",
                settings.occasion_hour, settings.timezone)
    last_run: date | None = None
    while True:
        try:
            now_local = datetime.now(tz)
            if _should_send_daily(now_local, last_run, settings.occasion_hour):
                await send_occasion_alerts(bot, pool, anthropic, settings, now_local.date())
                last_run = now_local.date()      # auch ohne fälligen Anlass: heute geprüft
        except asyncio.CancelledError:
            logger.info("Anlass-Loop gestoppt.")
            raise
        except Exception:
            logger.exception("Anlass-Durchlauf fehlgeschlagen")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def resurface_loop(bot, pool, anthropic, settings):
    if not settings.resurface_enabled:
        logger.info("Ideen-Auffrischung deaktiviert (RESURFACE_ENABLED=false); "
                    "/ideas bleibt nutzbar.")
        return
    if not (0 <= settings.resurface_hour <= 23 and 0 <= settings.resurface_weekday <= 6):
        logger.warning("RESURFACE_WEEKDAY=%s/RESURFACE_HOUR=%s ist ungültig "
                       "(Wochentag 0-6, Stunde 0-23) — Ideen werden nicht aufgefrischt.",
                       settings.resurface_weekday, settings.resurface_hour)
        return
    tz = ZoneInfo(settings.timezone)
    logger.info("Ideen-Loop gestartet (Wochentag %s um %02d:00 %s).",
                settings.resurface_weekday, settings.resurface_hour, settings.timezone)
    last_run: date | None = None
    while True:
        try:
            now_local = datetime.now(tz)
            if _should_send_weekly(now_local, last_run, settings.resurface_weekday,
                                   settings.resurface_hour):
                await send_idea_resurface(bot, pool, anthropic, settings)
                last_run = now_local.date()
        except asyncio.CancelledError:
            logger.info("Ideen-Loop gestoppt.")
            raise
        except Exception:
            logger.exception("Ideen-Durchlauf fehlgeschlagen")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
