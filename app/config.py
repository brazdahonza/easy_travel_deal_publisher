from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    DATABASE_URL: str = "sqlite:///./test.db"
    INGEST_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    PATREON_EMAIL: Optional[str] = None
    PATREON_PASSWORD: Optional[str] = None
    PATREON_SESSION: Optional[str] = None
    TWITTER_API_KEY: Optional[str] = None
    TWITTER_API_SECRET: Optional[str] = None
    TWITTER_ACCESS_TOKEN: Optional[str] = None
    TWITTER_ACCESS_SECRET: Optional[str] = None
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    NEARBY_COUNTRIES: Optional[str] = None
    CREATOR_EDITOR_URL: str = "https://www.patreon.com/creator/posts/new"


settings = Settings()
