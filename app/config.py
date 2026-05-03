from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Auth
    INGEST_API_KEY: Optional[str] = None

    # Patreon login
    PATREON_EMAIL: Optional[str] = None
    PATREON_PASSWORD: Optional[str] = None
    PATREON_SESSION: Optional[str] = None  # base64 JSON, optional seed for the in-memory session

    # Telegram (operator notifications)
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[str] = None

    # Patreon publishing knobs
    CREATOR_EDITOR_URL: str = "https://www.patreon.com/creator/posts/new"
    PATREON_DRY_RUN: bool = False
    PATREON_HEADLESS: bool = True
    PATREON_SLOWMO_MS: int = 0


settings = Settings()
