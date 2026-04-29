import logging
from .config import settings
import httpx

log = logging.getLogger(__name__)


def notify_telegram(message: str) -> None:
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        log.debug("Telegram token or chat_id not set, skipping notify")
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        httpx.post(url, json={"chat_id": chat_id, "text": message}, timeout=5)
    except Exception:
        log.exception("Failed to send telegram message")
