"""Entry point: start the Telegram bot (long-polling)."""
import asyncio
import logging

from anthropic import AsyncAnthropic
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.bot.handlers import (
    digest_cmd,
    help_cmd,
    reset_cmd,
    review_cmd,
    start,
    text_handler,
    voice_handler,
)
from app.config import get_settings
from app.db import close_pool, init_pool
from app.digest import digest_loop, review_loop
from app.ingest.embed import get_model
from app.memory import ConversationMemory
from app.reminders import reminder_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("secondbrain")


async def _post_init(app) -> None:
    settings = get_settings()
    app.bot_data["settings"] = settings
    app.bot_data["pool"] = await init_pool(settings.database_url)
    app.bot_data["anthropic"] = AsyncAnthropic(api_key=settings.anthropic_api_key)
    app.bot_data["memory"] = ConversationMemory()
    logger.info("Lade Embedding-Modell %s (einmalig, kann dauern) ...", settings.embedding_model)
    await asyncio.to_thread(get_model, settings.embedding_model)
    app.bot_data["reminder_task"] = asyncio.create_task(
        reminder_loop(app.bot, app.bot_data["pool"], settings)
    )
    app.bot_data["digest_task"] = asyncio.create_task(
        digest_loop(app.bot, app.bot_data["pool"], app.bot_data["anthropic"], settings)
    )
    app.bot_data["review_task"] = asyncio.create_task(
        review_loop(app.bot, app.bot_data["pool"], app.bot_data["anthropic"], settings)
    )
    logger.info("Second Brain ist bereit. 🧠")


async def _post_shutdown(app) -> None:
    for key in ("reminder_task", "digest_task", "review_task"):
        task = app.bot_data.get(key)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    await close_pool()


def main() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN fehlt — bitte in .env setzen.")
    if not settings.anthropic_api_key:
        raise SystemExit("ANTHROPIC_API_KEY fehlt — bitte in .env setzen.")

    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("digest", digest_cmd))
    app.add_handler(CommandHandler("review", review_cmd))
    app.add_handler(MessageHandler(filters.VOICE, voice_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    logger.info("Starte Polling ...")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
