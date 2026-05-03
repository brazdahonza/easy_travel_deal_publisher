import logging
import os
from typing import Any, List, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from sqlalchemy import func

# Surface app-level INFO/DEBUG logs through uvicorn's stdout. Without this the
# root logger defaults to WARNING and every log.info() in publishers/main is dropped.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from .config import settings
from .database import get_db
from .models import IngestLog, PatreonSession, PublishedDeal
from .publishers import (
    CloudflareChallengeError,
    PatreonPublisher,
    SessionExpiredError,
)
from .schemas import DeleteResult, IngestPayload, StatsOut
from .utils import notify_telegram
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

app = FastAPI(title="easy_travel_deal_publisher")


@app.on_event("startup")
def create_tables():
    from .database import Base, ENGINE
    from . import models  # noqa: F401 — registers table metadata
    if ENGINE is not None:
        Base.metadata.create_all(bind=ENGINE)
        log.info("💾 Database tables ready")
    else:
        log.warning("⚠️  Database engine not available — skipping table creation")
    # Bootstrap session from env on first run, then env is ignored.
    try:
        from . import session_store
        session_store.bootstrap_from_env_if_empty()
    except Exception:
        log.exception("⚠️  Session bootstrap failed")
    log.info("🚀 easy_travel_deal_publisher started")
    log.info("🔐 INGEST_API_KEY configured: %s", bool(settings.INGEST_API_KEY))
    log.info("🎨 PATREON credentials configured: %s", bool(settings.PATREON_EMAIL and settings.PATREON_PASSWORD))
    log.info("📬 TELEGRAM configured: %s", bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID))


@app.get("/health")
def health(db: Any = Depends(get_db)):
    db_ok = False
    session_ok = False
    try:
        db.execute(func.now())
        db_ok = True
        session_ok = db.query(PatreonSession).first() is not None
    except Exception:
        pass
    return {
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "patreon_session": session_ok,
        "patreon_login_creds": bool(settings.PATREON_EMAIL and settings.PATREON_PASSWORD),
        "telegram": bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID),
    }


def verify_api_key(x_api_key: Optional[str] = Header(None)):
    if settings.INGEST_API_KEY and x_api_key != settings.INGEST_API_KEY:
        log.warning("🔐 Rejected request — invalid API key")
        raise HTTPException(status_code=403, detail="invalid api key")


@app.post("/ingest")
async def ingest(
    payload: IngestPayload,
    background_tasks: BackgroundTasks,
    db: Any = Depends(get_db),
    x_api_key: Optional[str] = Depends(verify_api_key),
):
    log.info("━" * 60)
    log.info("📥 Ingest received — %d posts", len(payload.posts))
    for post in payload.posts:
        log.debug("  📦 Post: dest=%s title='%s'", post.destination_name, post.title)

    ingest_log = IngestLog(posts_count=len(payload.posts), status="queued")
    db.add(ingest_log)
    db.commit()
    db.refresh(ingest_log)
    ingest_id = ingest_log.id
    log.debug("💾 IngestLog #%d queued", ingest_id)

    posts_payload = [p.dict() for p in payload.posts]
    background_tasks.add_task(_process_ingest, ingest_id, posts_payload)

    log.info("✅ Ingest #%d accepted — processing in background", ingest_id)
    return {
        "status": "accepted",
        "ingest_id": ingest_id,
        "posts_count": len(payload.posts),
    }


def _build_telegram_message(post: dict, pub_result: dict) -> str:
    draft_url = (pub_result or {}).get("draft_url") or (pub_result or {}).get("url")
    lines = [
        f"📝 Patreon draft připraven: {post.get('title')}",
        f"📍 {post.get('destination_name')}",
    ]
    if draft_url:
        lines.append(f"🔗 {draft_url}")
    return "\n".join(lines)


async def _process_ingest(ingest_id: int, posts: List[dict]) -> None:
    """Sequentially publish each post to Patreon as a draft. Background-only."""
    import asyncio
    from .database import SessionLocal

    if SessionLocal is None:
        log.error("❌ DB unavailable — cannot process ingest #%d", ingest_id)
        return

    db = SessionLocal()
    try:
        ingest_log = db.query(IngestLog).filter(IngestLog.id == ingest_id).first()
        if ingest_log is None:
            log.error("❌ IngestLog #%d not found — aborting", ingest_id)
            return
        ingest_log.status = "processing"
        db.commit()

        try:
            patreon_pub = PatreonPublisher()
            published_count = 0
            max_attempts = 3

            for idx, post in enumerate(posts, 1):
                title = post["title"]
                body = post["body"]
                destination = post["destination_name"]

                log.info("─" * 50)
                log.info("📢 Publishing post %d/%d — destination=%s title='%s'",
                         idx, len(posts), destination, title)

                pub_result = None
                for attempt in range(1, max_attempts + 1):
                    try:
                        log.info("🎨 Publishing to Patreon (attempt %d/%d)...", attempt, max_attempts)
                        pub_result = await patreon_pub.publish(
                            title=title, body_text=body, destination=destination,
                        )
                        log.info("✅ Patreon — published successfully on attempt %d", attempt)
                        notify_telegram(_build_telegram_message(post, pub_result))
                        break
                    except SessionExpiredError as exc:
                        log.error("❌ Patreon — session expired and login fallback failed: %s", exc)
                        notify_telegram(
                            "Patreon session expired and in-process login failed. "
                            "Verify PATREON_EMAIL / PATREON_PASSWORD / 2FA settings."
                        )
                        break
                    except CloudflareChallengeError:
                        log.error("❌ Patreon — Cloudflare challenge blocking composer")
                        if attempt < max_attempts:
                            backoff = 5 * attempt + (attempt - 1) * 2
                            log.info("⏳ Retrying after %ds...", backoff)
                            await asyncio.sleep(backoff)
                        else:
                            log.error("💥 Cloudflare challenge persisted — giving up")
                    except Exception:
                        log.exception("❌ Patreon — publish failed on attempt %d/%d", attempt, max_attempts)
                        if attempt < max_attempts:
                            backoff = 5 * attempt + (attempt - 1) * 2
                            log.info("⏳ Retrying after %ds...", backoff)
                            await asyncio.sleep(backoff)
                        else:
                            log.error("💥 Exhausted %d attempts — giving up", max_attempts)

                if pub_result and pub_result.get("success"):
                    pd = PublishedDeal(
                        destination=destination,
                        title=title,
                        body=body,
                        draft_url=pub_result.get("draft_url"),
                        post_id=pub_result.get("post_id"),
                        published_at=datetime.utcnow(),
                    )
                    db.add(pd)
                    db.commit()
                    published_count += 1
                    log.debug("💾 PublishedDeal #%d saved", pd.id)
                else:
                    log.warning("⚠️  Post '%s' not published — skipping DB write", title)

            ingest_log.published_count = published_count
            ingest_log.status = "done"
            db.commit()

            log.info("━" * 60)
            log.info("📊 Ingest #%d complete — published=%d/%d",
                     ingest_id, published_count, len(posts))

        except Exception as e:
            log.exception("💥 Fatal error during ingest pipeline (#%d)", ingest_id)
            ingest_log.status = "error"
            ingest_log.error_message = str(e)
            db.commit()
    finally:
        db.close()


@app.get("/history")
def history(db: Any = Depends(get_db)):
    rows = db.query(PublishedDeal).order_by(PublishedDeal.published_at.desc()).limit(30).all()
    log.debug("📖 /history — returned %d rows", len(rows))
    return {"data": [r.__dict__ for r in rows]}


@app.get("/ingest-log")
def ingest_log_list(db: Any = Depends(get_db)):
    rows = db.query(IngestLog).order_by(IngestLog.received_at.desc()).limit(30).all()
    log.debug("📖 /ingest-log — returned %d rows", len(rows))
    return {"data": [r.__dict__ for r in rows]}


@app.get("/deals")
def list_deals(
    db: Any = Depends(get_db),
    destination: Optional[str] = Query(None, description="Partial case-insensitive match"),
    from_date: Optional[str] = Query(None, description="Published on or after (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="Published on or before (YYYY-MM-DD)"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    q = db.query(PublishedDeal)
    if destination:
        q = q.filter(PublishedDeal.destination.ilike(f"%{destination}%"))
    if from_date:
        try:
            q = q.filter(PublishedDeal.published_at >= datetime.fromisoformat(from_date))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid from_date format, use YYYY-MM-DD")
    if to_date:
        try:
            q = q.filter(PublishedDeal.published_at <= datetime.fromisoformat(to_date) + timedelta(days=1))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid to_date format, use YYYY-MM-DD")
    total = q.count()
    rows = q.order_by(PublishedDeal.published_at.desc()).offset(offset).limit(limit).all()
    log.debug("📖 /deals — total=%d returned=%d", total, len(rows))
    return {"total": total, "offset": offset, "limit": limit, "data": [r.__dict__ for r in rows]}


@app.get("/deals/{deal_id}")
def get_deal(deal_id: int, db: Any = Depends(get_db)):
    row = db.query(PublishedDeal).filter(PublishedDeal.id == deal_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Deal not found")
    return row.__dict__


@app.delete("/deals/{deal_id}", response_model=DeleteResult)
def delete_deal(deal_id: int, db: Any = Depends(get_db), x_api_key: Optional[str] = Depends(verify_api_key)):
    row = db.query(PublishedDeal).filter(PublishedDeal.id == deal_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Deal not found")
    db.delete(row)
    db.commit()
    log.info("🗑️  Deleted PublishedDeal #%d", deal_id)
    return {"deleted": 1}


@app.delete("/deals", response_model=DeleteResult)
def delete_all_deals(db: Any = Depends(get_db), x_api_key: Optional[str] = Depends(verify_api_key)):
    n = db.query(PublishedDeal).delete()
    db.commit()
    log.warning("🗑️  Deleted ALL %d PublishedDeal rows", n)
    return {"deleted": n}


@app.delete("/ingest-log", response_model=DeleteResult)
def delete_ingest_log(db: Any = Depends(get_db), x_api_key: Optional[str] = Depends(verify_api_key)):
    n = db.query(IngestLog).delete()
    db.commit()
    log.warning("🗑️  Deleted ALL %d IngestLog rows", n)
    return {"deleted": n}


@app.get("/stats", response_model=StatsOut)
def stats(db: Any = Depends(get_db)):
    seven_days_ago = datetime.utcnow() - timedelta(days=7)

    total_posts = db.query(func.count(PublishedDeal.id)).scalar() or 0

    ingest_total = db.query(func.count(IngestLog.id)).scalar() or 0
    status_rows = (
        db.query(IngestLog.status, func.count(IngestLog.id))
        .group_by(IngestLog.status)
        .all()
    )
    ingest_by_status = {s: c for s, c in status_rows}

    top_dest_rows = (
        db.query(PublishedDeal.destination, func.count(PublishedDeal.id).label("n"))
        .group_by(PublishedDeal.destination)
        .order_by(func.count(PublishedDeal.id).desc())
        .limit(5)
        .all()
    )
    top_destinations = [{"destination": d, "count": c} for d, c in top_dest_rows]

    last_7_posts = (
        db.query(func.count(PublishedDeal.id))
        .filter(PublishedDeal.published_at >= seven_days_ago)
        .scalar() or 0
    )
    last_7_ingests = (
        db.query(func.count(IngestLog.id))
        .filter(IngestLog.received_at >= seven_days_ago)
        .scalar() or 0
    )

    return StatsOut(
        total_posts=total_posts,
        ingest_totals={"total": ingest_total},
        ingest_by_status=ingest_by_status,
        top_destinations=top_destinations,
        last_7_days_posts=last_7_posts,
        last_7_days_ingests=last_7_ingests,
    )
