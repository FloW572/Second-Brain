"""Proactive daily digest: a short morning summary/prioritisation, once per day.

Reuses the query agent (``answer``) with a fixed digest prompt, so it gets the
same tool access and formatting for free. A lightweight asyncio loop fires it
during the configured local hour; a per-process 'last sent date' keeps it to
once daily. Also callable on demand via the /digest command.
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


def _should_send(now_local: datetime, last_sent: date | None, digest_hour: int) -> bool:
    """True during the digest hour if we haven't already sent today."""
    return now_local.hour == digest_hour and last_sent != now_local.date()


async def send_digest(bot, pool, anthropic, settings) -> int:
    """Build the digest via the agent and send it to the allowed users."""
    recipients = settings.allowed_user_ids
    if not recipients:
        logger.warning("Digest fällig, aber ALLOWED_TELEGRAM_USER_IDS ist leer.")
        return 0
    text = await answer(anthropic, pool, DIGEST_QUESTION, settings)
    message = f"☀️ Guten Morgen! Dein Tagesüberblick:\n\n{text}"
    sent = 0
    for uid in recipients:
        try:
            await bot.send_message(chat_id=uid, text=message)
            sent += 1
        except Exception:
            logger.exception("Digest an %s fehlgeschlagen", uid)
    return sent


async def digest_loop(bot, pool, anthropic, settings):
    if not (0 <= settings.digest_hour <= 23):
        logger.info("Täglicher Digest deaktiviert (DIGEST_HOUR=%s).", settings.digest_hour)
        return
    tz = ZoneInfo(settings.timezone)
    logger.info("Digest-Loop gestartet (täglich um %02d:00 %s).",
                settings.digest_hour, settings.timezone)
    last_sent: date | None = None
    while True:
        try:
            now_local = datetime.now(tz)
            if _should_send(now_local, last_sent, settings.digest_hour):
                if await send_digest(bot, pool, anthropic, settings):
                    last_sent = now_local.date()
                    logger.info("Digest gesendet.")
        except asyncio.CancelledError:
            logger.info("Digest-Loop gestoppt.")
            raise
        except Exception:
            logger.exception("Digest-Durchlauf fehlgeschlagen")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
