import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException

from .config import settings
from .publishers import PatreonPublisher, SessionUnavailableError
from .schemas import (
    PatreonDraftPayload,
    PatreonDraftResult,
    PatreonSessionPayload,
    SessionStatusOut,
)
from .session import state as session_state
from .utils import notify_telegram

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    session_state.seed_from_env()
    log.info("🚀 easy_travel_deal_publisher started")
    log.info("🔐 INGEST_API_KEY configured: %s", bool(settings.INGEST_API_KEY))
    log.info(
        "🎨 PATREON credentials configured: %s",
        bool(settings.PATREON_EMAIL and settings.PATREON_PASSWORD),
    )
    status = session_state.get_status()
    log.info(
        "🍪 Session at boot: present=%s count=%d needs_refresh=%s",
        status["cookies_present"], status["cookies_count"], status["needs_refresh"],
    )
    log.info(
        "📬 TELEGRAM configured: %s",
        bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID),
    )
    yield


app = FastAPI(title="easy_travel_deal_publisher", lifespan=lifespan)


def verify_api_key(x_api_key: Optional[str] = Header(None)) -> None:
    if settings.INGEST_API_KEY and x_api_key != settings.INGEST_API_KEY:
        log.warning("🔐 Rejected request — invalid API key")
        raise HTTPException(status_code=403, detail="invalid api key")


@app.get("/health")
def health() -> dict:
    status = session_state.get_status()
    return {
        "status": "ok",
        "cookies_present": status["cookies_present"],
        "cookies_count": status["cookies_count"],
        "needs_refresh": status["needs_refresh"],
        "patreon_credentials": bool(settings.PATREON_EMAIL and settings.PATREON_PASSWORD),
    }


@app.post("/session/patreon")
def set_patreon_session(
    payload: PatreonSessionPayload,
    _: None = Depends(verify_api_key),
) -> dict:
    """Receive a pre-captured cookie blob (e.g. from `setup_session.py`) and store it in memory."""
    log.info("🔐 Updating Patreon session — %d cookies received", len(payload.cookies))
    cookies = [c.model_dump(exclude_none=True) for c in payload.cookies]
    session_state.set_session(cookies, payload.email)
    notify_telegram("Cookies byly úspěšně nahrány ✅, služba je připravena k přípravě příspěvků 🚀")
    return {
        "status": "ok",
        "cookies_count": len(cookies),
        "email": payload.email or None,
    }


@app.get("/session/patreon/status", response_model=SessionStatusOut)
def get_patreon_session_status(_: None = Depends(verify_api_key)) -> SessionStatusOut:
    return SessionStatusOut(**session_state.get_status())


@app.post("/publish/patreon", response_model=PatreonDraftResult)
async def publish_patreon(
    payload: PatreonDraftPayload,
    _: None = Depends(verify_api_key),
) -> PatreonDraftResult:
    """Create a Patreon draft from `title` + `body`. Auto-logs in if no session is held."""
    log.info("📝 /publish/patreon — title='%s' destination=%s", payload.title, payload.destination or "n/a")

    if settings.PATREON_DRY_RUN:
        log.info("🧪 PATREON_DRY_RUN — skipping browser automation")
        return PatreonDraftResult(status="dry_run", draft_url=None, post_id=None)

    publisher = PatreonPublisher()
    try:
        result = await publisher.publish(
            title=payload.title,
            body_text=payload.body,
            destination=payload.destination,
        )
    except SessionUnavailableError as exc:
        log.error("❌ /publish/patreon — session unavailable: %s", exc)
        notify_telegram(
            "❌ Patreon session nelze obnovit — služba potřebuje nové cookies. "
            "Spusť `python -m app.session.setup_session --manual` a pošli je na POST /session/patreon."
        )
        raise HTTPException(status_code=401, detail={"error": "session_unavailable", "reason": str(exc)})
    except Exception as exc:
        log.exception("💥 /publish/patreon — publish failed")
        raise HTTPException(status_code=502, detail=f"patreon_error: {exc}")

    if not result.get("success"):
        log.warning("⚠️  /publish/patreon — publisher returned non-success: %s", result)
        raise HTTPException(status_code=502, detail="patreon_publish_failed")

    log.info("✅ /publish/patreon — draft_url=%s post_id=%s", result.get("draft_url"), result.get("post_id"))
    return PatreonDraftResult(
        status="ok",
        draft_url=result.get("draft_url") or result.get("url"),
        post_id=result.get("post_id"),
    )
