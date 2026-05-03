"""In-memory Patreon session state.

The session blob (cookies + email + timestamps) lives only in process memory.
It is seeded at startup from the optional `PATREON_SESSION` env var, can be
overwritten by `POST /session/patreon`, and is refreshed automatically by the
publisher after every successful draft creation or auto-login.
"""
import base64
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from ..config import settings

log = logging.getLogger(__name__)

_session: Optional[dict] = None
_needs_refresh: bool = False
_last_error: Optional[str] = None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_session() -> Optional[dict]:
    """Return the in-memory session dict (with `cookies`, `email`, `stored_at`) or None."""
    return _session


def set_session(cookies: list, email: Optional[str] = None) -> dict:
    """Replace the in-memory session and clear the needs-refresh flag."""
    global _session, _needs_refresh, _last_error
    _session = {
        "cookies": list(cookies or []),
        "email": email or "",
        "stored_at": _utcnow_iso(),
    }
    _needs_refresh = False
    _last_error = None
    log.info("🔐 Session stored in memory — %d cookies, email=%s", len(_session["cookies"]), email or "n/a")
    return _session


def mark_expired(reason: str = "session_expired") -> None:
    """Flag the in-memory session as needing renewal (without clearing it)."""
    global _needs_refresh, _last_error
    _needs_refresh = True
    _last_error = reason
    log.warning("⚠️  Session marked as needing refresh — reason=%s", reason)


def clear_session() -> None:
    """Drop the in-memory session entirely (used by tests)."""
    global _session, _needs_refresh, _last_error
    _session = None
    _needs_refresh = False
    _last_error = None


def get_status() -> dict:
    """Return a JSON-serializable snapshot for the status endpoint."""
    cookies = (_session or {}).get("cookies", []) if _session else []
    return {
        "cookies_present": _session is not None and len(cookies) > 0,
        "cookies_count": len(cookies),
        "email": (_session or {}).get("email") or None,
        "stored_at": (_session or {}).get("stored_at"),
        "needs_refresh": _needs_refresh,
        "last_error": _last_error,
    }


def seed_from_env() -> None:
    """Decode `settings.PATREON_SESSION` (base64 JSON) into the in-memory store."""
    raw = settings.PATREON_SESSION
    if not raw:
        log.info("🔐 PATREON_SESSION not set — starting with empty session (auto-login on first publish)")
        return
    try:
        decoded = base64.b64decode(raw)
        data = json.loads(decoded)
        cookies = data.get("cookies", [])
        email = data.get("email")
        set_session(cookies, email)
        log.info("🔐 Seeded session from PATREON_SESSION env var — %d cookies", len(cookies))
    except Exception:
        log.exception("❌ Failed to decode PATREON_SESSION env var — ignoring")
