"""DB-backed Patreon session store. Single-row semantics: latest blob wins."""
import base64
import json
import logging
from typing import Optional

log = logging.getLogger(__name__)


def _decode(blob: str) -> Optional[dict]:
    try:
        return json.loads(base64.b64decode(blob))
    except Exception:
        log.exception("❌ Failed to decode session blob")
        return None


def _encode(cookies: list, email: Optional[str]) -> str:
    from datetime import datetime
    payload = {
        "cookies": cookies,
        "email": email or "",
        "timestamp": datetime.utcnow().isoformat(),
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()


def load() -> Optional[dict]:
    """Return the latest stored session as a {cookies,email,timestamp} dict, or None."""
    from .database import SessionLocal
    from .models import PatreonSession

    if SessionLocal is None:
        return None

    db = SessionLocal()
    try:
        row = db.query(PatreonSession).order_by(PatreonSession.id.desc()).first()
        if row is None:
            return None
        decoded = _decode(row.cookies_b64)
        if decoded:
            log.info(
                "🔐 Patreon session loaded from DB — %d cookies, stored at %s",
                len(decoded.get("cookies", [])), decoded.get("timestamp", "?"),
            )
        return decoded
    finally:
        db.close()


def save(cookies: list, email: Optional[str] = None) -> None:
    """Upsert a session row. Always writes a new row tagged with updated_at."""
    from .database import SessionLocal
    from .models import PatreonSession

    if SessionLocal is None:
        log.warning("⚠️  DB unavailable — cannot persist Patreon session")
        return

    db = SessionLocal()
    try:
        encoded = _encode(cookies, email)
        row = db.query(PatreonSession).order_by(PatreonSession.id.desc()).first()
        if row is None:
            row = PatreonSession(cookies_b64=encoded, email=email or None)
            db.add(row)
        else:
            row.cookies_b64 = encoded
            if email:
                row.email = email
        db.commit()
        log.info("🔐 Patreon session persisted — %d cookies", len(cookies))
    except Exception:
        log.exception("❌ Failed to persist Patreon session")
        db.rollback()
    finally:
        db.close()


def bootstrap_from_env_if_empty() -> None:
    """First-run only: copy PATREON_SESSION env into DB if no row exists yet."""
    from .config import settings
    from .database import SessionLocal
    from .models import PatreonSession

    if SessionLocal is None or not settings.PATREON_SESSION:
        return

    db = SessionLocal()
    try:
        if db.query(PatreonSession).first() is not None:
            return
        decoded = _decode(settings.PATREON_SESSION)
        if not decoded:
            return
        row = PatreonSession(
            cookies_b64=settings.PATREON_SESSION,
            email=decoded.get("email") or None,
        )
        db.add(row)
        db.commit()
        log.info("🔐 Bootstrapped Patreon session from PATREON_SESSION env")
    except Exception:
        log.exception("❌ Failed to bootstrap session from env")
        db.rollback()
    finally:
        db.close()
