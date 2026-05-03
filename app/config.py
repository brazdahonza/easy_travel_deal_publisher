from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    DATABASE_URL: str = "sqlite:///./test.db"
    INGEST_API_KEY: Optional[str] = None
    PATREON_EMAIL: Optional[str] = None
    PATREON_PASSWORD: Optional[str] = None
    # Bootstrap value: copied into the DB session_store on first startup, then
    # ignored. Live cookies live in the patreon_sessions table.
    PATREON_SESSION: Optional[str] = None
    # TOTP base32 secret from authenticator-app 2FA setup. If set, codes are
    # generated automatically on every login — best for fully autonomous use.
    PATREON_TOTP_SECRET: Optional[str] = None
    # One-shot 2FA code (e.g. SMS/email OTP). Used once, then ignored.
    PATREON_2FA_CODE: Optional[str] = None
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[str] = None
    PATREON_DRY_RUN: bool = False
    PATREON_HEADLESS: bool = True
    PATREON_SLOWMO_MS: int = 0


settings = Settings()
