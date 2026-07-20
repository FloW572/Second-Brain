"""Local speech-to-text via faster-whisper.

The model is loaded lazily (and cached) on first use so it does not slow down
startup or cost anything if voice messages are never sent. Runs on CPU with
int8 quantisation. Audio (Telegram OGG/Opus) is decoded by faster-whisper's
bundled PyAV — no separate ffmpeg install required.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

_model = None
_model_name: str | None = None


def get_model(name: str):
    """Load (and cache) the WhisperModel. Blocking — call in a thread."""
    global _model, _model_name
    from faster_whisper import WhisperModel  # lazy import (heavy)

    if _model is None or _model_name != name:
        logger.info("Lade Whisper-Modell %s (einmalig, kann dauern) ...", name)
        _model = WhisperModel(name, device="cpu", compute_type="int8")
        _model_name = name
    return _model


async def transcribe_file(path: str, name: str, language: str | None = "de") -> str:
    """Transcribe an audio file to text. ``language=None`` auto-detects."""
    lang = language or None
    if lang == "auto":
        lang = None

    def _run() -> str:
        model = get_model(name)
        segments, _info = model.transcribe(path, language=lang)
        return " ".join(seg.text.strip() for seg in segments).strip()

    return await asyncio.to_thread(_run)
