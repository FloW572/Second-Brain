"""Proactive scheduled briefings sent to the allowed users.

Both reuse the query agent (``answer``) with a fixed prompt, so they inherit its
tool access and formatting, and each runs in its own lightweight asyncio loop:

  - daily digest  — a short morning summary / prioritisation (``DIGEST_HOUR``)
  - weekly review — a look back + focus for the coming week
                    (``REVIEW_WEEKDAY`` / ``REVIEW_HOUR``)

A per-process 'last sent date' keeps each to once per occurrence. Both are also
available on demand via /digest and /review.
"""
import asyncio
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.query.agent import answer

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 60

DIGEST_QUESTION = (
    "Erstelle meinen Tagesüberblick für heute. Berücksichtige überfällige sowie heute und "
    "diese Woche fällige Todos und hilf mir zu priorisieren, womit ich anfangen soll. "
    "Halte es kurz, konkret und motivierend. Wenn nichts ansteht, sag das freundlich. "
    "Beginne direkt mit dem Inhalt, ohne eigene Begrüßung (die Begrüßung steht schon davor)."
)

REVIEW_QUESTION = (
    "Erstelle mein wöchentliches Review. Fasse kurz zusammen, was noch offen oder überfällig "
    "ist, und welche Ideen und Notizen ich mir wieder ansehen sollte. Gib einen knappen "
    "Rückblick und schlage einen Fokus für die kommende Woche vor. Halte es kompakt und "
    "motivierend. Beginne direkt mit dem Inhalt, ohne eigene Begrüßung."
)


async def _broadcast(bot, recipients, message: str) -> int:
    """Send one message to every recipient; return how many got it."""
    sent = 0
    for uid in recipients:
        try:
            await bot.send_message(chat_id=uid, text=message)
            sent += 1
        except Exception:
            logger.exception("Nachricht an %s fehlgeschlagen", uid)
    return sent


async def send_digest(bot, pool, anthropic, settings) -> int:
    recipients = settings.allowed_user_ids
    if not recipients:
        logger.warning("Digest fällig, aber ALLOWED_TELEGRAM_USER_IDS ist leer.")
        return 0
    text = await answer(anthropic, pool, DIGEST_QUESTION, settings)
    return await _broadcast(bot, recipients, f"☀️ Guten Morgen! Dein Tagesüberblick:\n\n{text}")


async def send_review(bot, pool, anthropic, settings) -> int:
    recipients = settings.allowed_user_ids
    if not recipients:
        logger.warning("Review fällig, aber ALLOWED_TELEGRAM_USER_IDS ist leer.")
        return 0
    text = await answer(anthropic, pool, REVIEW_QUESTION, settings)
    return await _broadcast(bot, recipients, f"🗓️ Dein Wochenrückblick:\n\n{text}")


def _should_send_daily(now_local: datetime, last_sent: date | None, hour: int) -> bool:
    return now_local.hour == hour and last_sent != now_local.date()


def _should_send_weekly(now_local: datetime, last_sent: date | None,
                        weekday: int, hour: int) -> bool:
    return (now_local.weekday() == weekday and now_local.hour == hour
            and last_sent != now_local.date())


async def digest_loop(bot, pool, anthropic, settings):
    if not settings.digest_enabled:
        logger.info("Täglicher Digest deaktiviert (DIGEST_ENABLED=false); /digest bleibt nutzbar.")
        return
    if not (0 <= settings.digest_hour <= 23):
        logger.warning("DIGEST_HOUR=%s ist ungültig (0-23, 24-Stunden-Format erwartet) — "
                       "Digest wird nicht gesendet. Zum Abschalten DIGEST_ENABLED=false setzen.",
                       settings.digest_hour)
        return
    tz = ZoneInfo(settings.timezone)
    logger.info("Digest-Loop gestartet (täglich um %02d:00 %s).",
                settings.digest_hour, settings.timezone)
    last_sent: date | None = None
    while True:
        try:
            now_local = datetime.now(tz)
            if _should_send_daily(now_local, last_sent, settings.digest_hour):
                if await send_digest(bot, pool, anthropic, settings):
                    last_sent = now_local.date()
                    logger.info("Digest gesendet.")
        except asyncio.CancelledError:
            logger.info("Digest-Loop gestoppt.")
            raise
        except Exception:
            logger.exception("Digest-Durchlauf fehlgeschlagen")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def review_loop(bot, pool, anthropic, settings):
    if not settings.review_enabled:
        logger.info("Wöchentliches Review deaktiviert (REVIEW_ENABLED=false); /review bleibt nutzbar.")
        return
    if not (0 <= settings.review_hour <= 23 and 0 <= settings.review_weekday <= 6):
        logger.warning("REVIEW_WEEKDAY=%s/REVIEW_HOUR=%s ist ungültig (Wochentag 0-6, Stunde 0-23) — "
                       "Review wird nicht gesendet. Zum Abschalten REVIEW_ENABLED=false setzen.",
                       settings.review_weekday, settings.review_hour)
        return
    tz = ZoneInfo(settings.timezone)
    logger.info("Review-Loop gestartet (Wochentag %s um %02d:00 %s).",
                settings.review_weekday, settings.review_hour, settings.timezone)
    last_sent: date | None = None
    while True:
        try:
            now_local = datetime.now(tz)
            if _should_send_weekly(now_local, last_sent, settings.review_weekday, settings.review_hour):
                if await send_review(bot, pool, anthropic, settings):
                    last_sent = now_local.date()
                    logger.info("Review gesendet.")
        except asyncio.CancelledError:
            logger.info("Review-Loop gestoppt.")
            raise
        except Exception:
            logger.exception("Review-Durchlauf fehlgeschlagen")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
