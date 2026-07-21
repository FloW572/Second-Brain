"""Telegram message handlers."""
import asyncio
import logging
import os
import tempfile
from contextlib import asynccontextmanager

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from app.bot.router import classify
from app.digest import send_digest, send_review
from app.documents import store_document
from app.ingest import capture
from app.ingest.projects import resolve_project
from app.query.agent import answer
from app.transcribe import transcribe_file

logger = logging.getLogger(__name__)

WELCOME = (
    "👋 Hi! Ich bin dein Second Brain.\n\n"
    "Schick mir einfach Todos, Ideen oder Notizen — als Text oder 🎙️ Sprachnachricht — "
    "ich sortiere sie ein.\n"
    "Oder stell mir Fragen wie:\n"
    "• „Was soll ich heute zuerst machen?“\n"
    "• „Welche Ideen habe ich zum Thema X?“\n"
    "• „Zeig mir offene Todos für Projekt Y.“\n\n"
    "Ich behalte den Gesprächskontext für Rückfragen. /digest = Tagesüberblick, "
    "/review = Wochenrückblick, /reset = neues Gespräch."
)


@asynccontextmanager
async def _keep_typing(bot, chat_id):
    """Hold Telegram's 'typing…' indicator for the whole block — it otherwise expires
    after ~5s, so slow replies (e.g. web-search enrichment, ~1–2 min) would look dead."""
    stop = asyncio.Event()

    async def loop():
        while not stop.is_set():
            try:
                await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            except Exception:  # noqa: BLE001 - a failed keep-alive must not break the reply
                logger.debug("send_chat_action failed", exc_info=True)
            try:
                await asyncio.wait_for(stop.wait(), timeout=4.0)
            except asyncio.TimeoutError:
                pass

    task = asyncio.create_task(loop())
    try:
        yield
    finally:
        stop.set()
        await task


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


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.bot_data["settings"]
    if not _is_allowed(update.effective_user.id, settings):
        await update.message.reply_text("⛔ Nicht berechtigt.")
        return
    context.bot_data["memory"].clear(update.effective_chat.id)
    await update.message.reply_text("🧹 Gespräch zurückgesetzt — ich starte ohne vorherigen Kontext.")


async def digest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.bot_data["settings"]
    if not _is_allowed(update.effective_user.id, settings):
        await update.message.reply_text("⛔ Nicht berechtigt.")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    sent = await send_digest(context.bot, context.bot_data["pool"],
                             context.bot_data["anthropic"], settings)
    if not sent:
        await update.message.reply_text("⚠️ Konnte den Digest nicht erstellen.")


async def review_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.bot_data["settings"]
    if not _is_allowed(update.effective_user.id, settings):
        await update.message.reply_text("⛔ Nicht berechtigt.")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    sent = await send_review(context.bot, context.bot_data["pool"],
                             context.bot_data["anthropic"], settings)
    if not sent:
        await update.message.reply_text("⚠️ Konnte das Review nicht erstellen.")


async def _handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       text: str, source: str) -> None:
    """Route one piece of text through classify -> capture/query and reply."""
    settings = context.bot_data["settings"]
    anthropic = context.bot_data["anthropic"]
    pool = context.bot_data["pool"]
    memory = context.bot_data["memory"]
    chat_id = update.effective_chat.id
    try:
        async with _keep_typing(context.bot, chat_id):
            intent = await classify(anthropic, text, settings)
            if intent == "query":
                reply = await answer(anthropic, pool, text, settings, history=memory.get(chat_id))
                memory.add(chat_id, text, reply)      # remember this turn for follow-ups
            else:
                reply = await capture(pool, anthropic, text, source, settings)
    except Exception:
        logger.exception("Failed to handle message")
        reply = "⚠️ Da ist etwas schiefgelaufen. Schau bitte ins Log."
    await update.message.reply_text(reply)


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.bot_data["settings"]
    if not _is_allowed(update.effective_user.id, settings):
        await update.message.reply_text("⛔ Nicht berechtigt.")
        return
    await _handle_text(update, context, update.message.text, "telegram_text")


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.bot_data["settings"]
    if not _is_allowed(update.effective_user.id, settings):
        await update.message.reply_text("⛔ Nicht berechtigt.")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id,
                                        action=ChatAction.TYPING)
    tmp_path = None
    try:
        tg_file = await context.bot.get_file(update.message.voice.file_id)
        fd, tmp_path = tempfile.mkstemp(suffix=".oga")
        os.close(fd)
        await tg_file.download_to_drive(tmp_path)
        text = await transcribe_file(tmp_path, settings.whisper_model, settings.whisper_language)
    except Exception:
        logger.exception("transcription failed")
        await update.message.reply_text("⚠️ Konnte die Sprachnachricht nicht verarbeiten.")
        return
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    if not text.strip():
        await update.message.reply_text("🤔 Ich habe in der Sprachnachricht nichts verstanden.")
        return

    await update.message.reply_text(f"🎙️ Verstanden: „{text}“")
    await _handle_text(update, context, text, "telegram_voice")


async def _store_incoming_file(update, context, content: bytes,
                               filename: str, content_type: str | None) -> None:
    """Store an uploaded file; a caption (if any) names the project to attach it to."""
    settings = context.bot_data["settings"]
    pool = context.bot_data["pool"]
    caption = (update.message.caption or "").strip()
    project_name = None
    project_id = None
    if caption:
        async with pool.connection() as conn:
            project_id, project_name = await resolve_project(conn, caption)
    await store_document(pool, settings.docs_dir, project_id, filename, content_type, content)
    if project_name:
        await update.message.reply_text(
            f"📎 „{filename}“ gespeichert – Projekt: {project_name}."
        )
    else:
        await update.message.reply_text(
            f"📎 „{filename}“ gespeichert (ohne Projekt).\n"
            "Tipp: Projektnamen als Bildunterschrift mitschicken oder im Dashboard zuordnen."
        )


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.bot_data["settings"]
    if not _is_allowed(update.effective_user.id, settings):
        await update.message.reply_text("⛔ Nicht berechtigt.")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    doc = update.message.document
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        content = bytes(await tg_file.download_as_bytearray())
    except Exception:
        logger.exception("document download failed")
        await update.message.reply_text("⚠️ Konnte das Dokument nicht laden.")
        return
    filename = doc.file_name or f"dokument_{doc.file_unique_id}"
    await _store_incoming_file(update, context, content, filename, doc.mime_type)


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.bot_data["settings"]
    if not _is_allowed(update.effective_user.id, settings):
        await update.message.reply_text("⛔ Nicht berechtigt.")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    photo = update.message.photo[-1]  # largest resolution
    try:
        tg_file = await context.bot.get_file(photo.file_id)
        content = bytes(await tg_file.download_as_bytearray())
    except Exception:
        logger.exception("photo download failed")
        await update.message.reply_text("⚠️ Konnte das Bild nicht laden.")
        return
    await _store_incoming_file(update, context, content, f"foto_{photo.file_unique_id}.jpg", "image/jpeg")
