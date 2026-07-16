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

from app.bot.handlers import help_cmd, start, text_handler, voice_handler
from app.config import get_settings
from app.db import close_pool, init_pool
from app.ingest.embed import get_model

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
    logger.info("Lade Embedding-Modell %s (einmalig, kann dauern) ...", settings.embedding_model)
    await asyncio.to_thread(get_model, settings.embedding_model)
    logger.info("Second Brain ist bereit. 🧠")


async def _post_shutdown(app) -> None:
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
    app.add_handler(MessageHandler(filters.VOICE, voice_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    logger.info("Starte Polling ...")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
