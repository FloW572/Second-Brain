"""Application settings, loaded from environment / .env."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Telegram
    telegram_bot_token: str = ""
    allowed_telegram_user_ids: str = ""  # comma-separated user IDs

    # Anthropic
    anthropic_api_key: str = ""

    # Database
    database_url: str = "postgresql://secondbrain:secondbrain@localhost:5432/secondbrain"

    # Models
    embedding_model: str = "BAAI/bge-m3"
    router_model: str = "claude-haiku-4-5-20251001"
    extract_model: str = "claude-haiku-4-5-20251001"
    query_model: str = "claude-opus-4-8"

    # Speech-to-text (local, faster-whisper): tiny|base|small|medium|large-v3
    whisper_model: str = "small"
    whisper_language: str = "de"  # ISO code, or "auto" to detect

    # Locale
    timezone: str = "Europe/Vienna"

    # Proactive briefings: explicit on/off switches for the scheduled loops.
    # Turning these off does NOT disable the manual /digest and /review commands.
    digest_enabled: bool = False
    review_enabled: bool = False

    # Daily digest: local hour in 24h format (0-23) for the morning summary.
    # On/off is controlled by digest_enabled above, not by this value.
    digest_hour: int = 8

    # Weekly review: weekday (0=Mon .. 6=Sun) + local hour in 24h format (0-23).
    # On/off is controlled by review_enabled above, not by these values.
    review_weekday: int = 6
    review_hour: int = 18

    # Document storage: file bytes on disk (a volume); only metadata in the DB
    docs_dir: str = "/data/documents"

    # Observability: per-call token/cost/latency logging is always on; /stats shows the
    # live total since start. If > 0, log a one-time WARNING when cumulative Anthropic
    # spend since start crosses this many USD (0 = no warning). Not a hard cap.
    cost_warn_threshold_usd: float = 0.0

    @property
    def allowed_user_ids(self) -> set[int]:
        return {int(x.strip()) for x in self.allowed_telegram_user_ids.split(",") if x.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
