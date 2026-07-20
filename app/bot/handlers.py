"""Telegram message handlers."""
import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from app.bot.router import classify
from app.ingest import capture
from app.query.agent import answer

logger = logging.getLogger(__name__)

WELCOME = (
    "👋 Hi! Ich bin dein Second Brain.\n\n"
    "Schick mir einfach Todos, Ideen oder Notizen — ich sortiere sie ein.\n"
    "Oder stell mir Fragen wie:\n"
    "• „Was soll ich heute zuerst machen?“\n"
    "• „Welche Ideen habe ich zum Thema X?“\n"
    "• „Zeig mir offene Todos für Projekt Y.“"
)


def _is_allowed(user_id: int, settings) -> bool:
    allowed = settings.allowed_user_ids
    if not allowed:
        logger.error(
            "ALLOWED_TELEGRAM_USER_IDS ist leer — Zugriff fuer ALLE gesperrt (deny by default). "
            "Trage deine Telegram-User-ID in die .env ein."
        )
        return False
    return user_id in allowed


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME)


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.bot_data["settings"]
    if not _is_allowed(update.effective_user.id, settings):
        await update.message.reply_text("⛔ Nicht berechtigt.")
        return

    anthropic = context.bot_data["anthropic"]
    pool = context.bot_data["pool"]
    text = update.message.text

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id,
                                            action=ChatAction.TYPING)
        intent = await classify(anthropic, text, settings)
        if intent == "query":
            reply = await answer(anthropic, pool, text, settings)
        else:
            reply = await capture(pool, anthropic, text, "telegram_text", settings)
    except Exception:
        logger.exception("Failed to handle message")
        reply = "⚠️ Da ist etwas schiefgelaufen. Schau bitte ins Log."

    await update.message.reply_text(reply)


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.bot_data["settings"]
    if not _is_allowed(update.effective_user.id, settings):
        await update.message.reply_text("⛔ Nicht berechtigt.")
        return
    await update.message.reply_text(
        "🎙️ Sprachnachrichten folgen in Phase 2 (Transkription via faster-whisper). "
        "Bitte aktuell als Text senden."
    )
