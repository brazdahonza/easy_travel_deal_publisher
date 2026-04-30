import logging
from .config import settings
import httpx

log = logging.getLogger(__name__)


def notify_telegram(message: str) -> None:
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        log.debug("📬 Telegram not configured — skipping notification")
        return
    log.info("📬 Sending Telegram notification — %d chars", len(message))
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = httpx.post(url, json={"chat_id": chat_id, "text": message}, timeout=5)
        if resp.status_code == 200:
            log.info("✅ Telegram notification sent")
        else:
            log.warning("⚠️  Telegram returned status %d — %s", resp.status_code, resp.text[:100])
    except Exception:
        log.exception("❌ Failed to send Telegram notification")
