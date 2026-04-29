import logging
from .config import settings
import httpx

log = logging.getLogger(__name__)


def notify_telegram(message: str) -> None:
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        log.debug("Telegram token not set, skipping notify")
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        httpx.post(url, json={"chat_id": "@yourchannel", "text": message}, timeout=5)
    except Exception:
        log.exception("Failed to send telegram message")
