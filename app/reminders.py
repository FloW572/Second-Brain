"""Background loop that sends proactive Telegram reminders for due todos.

A lightweight asyncio task (no extra dependency) started from the bot's
post_init hook. Every CHECK_INTERVAL_SECONDS it looks for todos whose due time
has arrived and that have not been reminded yet, notifies the allowed users and
marks them as reminded so each fires only once.
"""
import asyncio
import logging
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 60


async def _due_todos(pool):
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, title, due_at
            FROM items
            WHERE type = 'todo' AND status <> 'done'
              AND due_at IS NOT NULL AND due_at <= now()
              AND reminded_at IS NULL
            ORDER BY due_at
            """
        )
        return await cur.fetchall()


async def _mark_reminded(pool, item_id):
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute("UPDATE items SET reminded_at = now() WHERE id = %s", (item_id,))
        await conn.commit()


async def check_once(bot, pool, settings):
    """One reminder sweep. Returns the number of reminders sent."""
    todos = await _due_todos(pool)
    if not todos:
        return 0
    tz = ZoneInfo(settings.timezone)
    recipients = settings.allowed_user_ids
    if not recipients:
        logger.warning("Fällige Todos, aber ALLOWED_TELEGRAM_USER_IDS ist leer — kein Empfänger.")
        return 0

    sent_count = 0
    for item_id, title, due_at in todos:
        when = due_at.astimezone(tz).strftime("%d.%m. %H:%M")
        text = f"⏰ Erinnerung: {title}\n   fällig {when} · #{item_id}"
        delivered = False
        for uid in recipients:
            try:
                await bot.send_message(chat_id=uid, text=text)
                delivered = True
            except Exception:
                logger.exception("Erinnerung an %s fehlgeschlagen", uid)
        if delivered:
            await _mark_reminded(pool, item_id)
            sent_count += 1
            logger.info("Erinnerung gesendet für item id=%s", item_id)
    return sent_count


async def reminder_loop(bot, pool, settings):
    logger.info("Reminder-Loop gestartet (Intervall %ss).", CHECK_INTERVAL_SECONDS)
    while True:
        try:
            await check_once(bot, pool, settings)
        except asyncio.CancelledError:
            logger.info("Reminder-Loop gestoppt.")
            raise
        except Exception:
            logger.exception("Reminder-Durchlauf fehlgeschlagen")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
