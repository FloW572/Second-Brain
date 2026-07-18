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

    # Locale
    timezone: str = "Europe/Vienna"

    @property
    def allowed_user_ids(self) -> set[int]:
        return {int(x.strip()) for x in self.allowed_telegram_user_ids.split(",") if x.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
