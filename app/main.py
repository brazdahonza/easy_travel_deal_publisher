import logging
from fastapi import FastAPI, Header, HTTPException, Depends, Query, BackgroundTasks
from typing import Optional, List
from .config import settings
from .schemas import IngestPayload, PatreonSessionPayload, StatsOut, DeleteResult
from .database import get_db
from typing import Any
from .deal_selector import select_with_llm, deal_hash, duration_bucket
from .post_generator import generate_patreon_post, generate_twitter_post
from .publishers import PatreonPublisher, TwitterPublisher, SessionExpiredError
from .utils import notify_telegram
from .models import PublishedDeal, IngestLog, PublishedToEnum
from datetime import datetime, timedelta
from sqlalchemy import func
log = logging.getLogger(__name__)

app = FastAPI(title="easy_travel_deal_publisher")


@app.on_event("startup")
def create_tables():
    from .database import ENGINE, Base, drop_stale_deal_hash_unique
    from . import models  # noqa: F401 — registers table metadata
    if ENGINE is not None:
        drop_stale_deal_hash_unique(ENGINE)
        Base.metadata.create_all(bind=ENGINE)
        log.info("💾 Database tables ready")
    else:
        log.warning("⚠️  Database engine not available — skipping table creation")
    log.info("🚀 easy_travel_deal_publisher started")
    log.info("🔐 INGEST_API_KEY configured: %s", bool(settings.INGEST_API_KEY))
    log.info("🤖 ANTHROPIC_API_KEY configured: %s", bool(settings.ANTHROPIC_API_KEY))
    log.info("🎨 PATREON_SESSION configured: %s", bool(settings.PATREON_SESSION))
    log.info("🐦 TWITTER configured: %s", bool(settings.TWITTER_API_KEY and settings.TWITTER_ACCESS_TOKEN))
    log.info("📬 TELEGRAM configured: %s", bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID))


@app.get("/health")
def health(db: Any = Depends(get_db)):
    db_ok = False
    try:
        db.execute(func.now())
        db_ok = True
    except Exception:
        pass
    return {
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "patreon_session": bool(settings.PATREON_SESSION),
        "twitter": bool(settings.TWITTER_API_KEY and settings.TWITTER_ACCESS_TOKEN),
        "llm": bool(settings.ANTHROPIC_API_KEY),
        "telegram": bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID),
    }


def verify_api_key(x_api_key: Optional[str] = Header(None)):
    if settings.INGEST_API_KEY and x_api_key != settings.INGEST_API_KEY:
        log.warning("🔐 Rejected request — invalid API key")
        raise HTTPException(status_code=403, detail="invalid api key")


@app.post("/session/patreon")
def set_patreon_session(payload: PatreonSessionPayload, x_api_key: Optional[str] = Depends(verify_api_key)):
    import base64
    import json
    log.info("🔐 Updating Patreon session — %d cookies received", len(payload.cookies))
    session_data = {
        "cookies": [c.dict(exclude_none=True) for c in payload.cookies],
        "email": payload.email or "",
        "timestamp": datetime.utcnow().isoformat(),
    }
    encoded = base64.b64encode(json.dumps(session_data).encode()).decode()
    settings.PATREON_SESSION = encoded
    log.info("✅ Patreon session stored — email=%s cookies=%d", payload.email or "n/a", len(payload.cookies))
    msg = "Cookies byly úspěšně nahrány ✅, služba je připravena k přípravě příspěvků 🚀"
    log.info(msg)
    notify_telegram(msg)
    return {
        "patreon_session": encoded,
        "note": "Session active. Persist by setting PATREON_SESSION in .env",
    }


@app.post("/ingest")
async def ingest(
    payload: IngestPayload,
    background_tasks: BackgroundTasks,
    db: Any = Depends(get_db),
    x_api_key: Optional[str] = Depends(verify_api_key),
):
    log.info("━" * 60)
    log.info("📥 Ingest received — %d deals in batch", len(payload.deals))
    for deal in payload.deals:
        log.debug(
            "  📦 Deal: id=%s destination=%s departure=%s price=%s CZK discount=%s%%",
            deal.id, deal.destination, deal.departure_city, deal.price,
            f"{deal.discount_pct:.1f}" if deal.discount_pct else "n/a",
        )

    ingest_log = IngestLog(deals_count=len(payload.deals), status="queued")
    db.add(ingest_log)
    db.commit()
    db.refresh(ingest_log)
    ingest_id = ingest_log.id
    log.debug("💾 IngestLog #%d queued", ingest_id)

    deals_payload = [d.dict() for d in payload.deals]
    background_tasks.add_task(_process_ingest, ingest_id, deals_payload)

    log.info("✅ Ingest #%d accepted — processing in background", ingest_id)
    return {
        "status": "accepted",
        "ingest_id": ingest_id,
        "deals_count": len(payload.deals),
    }


async def _process_ingest(ingest_id: int, deals: List[dict]) -> None:
    """Run selection + publishing pipeline asynchronously after /ingest responds."""
    from .database import SessionLocal
    if SessionLocal is None:
        log.error("❌ DB unavailable — cannot process ingest #%d", ingest_id)
        return

    db = SessionLocal()
    try:
        ingest_log = db.query(IngestLog).filter(IngestLog.id == ingest_id).first()
        if ingest_log is None:
            log.error("❌ IngestLog #%d not found — aborting background processing", ingest_id)
            return
        ingest_log.status = "processing"
        db.commit()

        try:
            # ── Prepare deals ─────────────────────────────────────────
            deduped = []
            for d_dict in deals:
                bucket = duration_bucket(d_dict.get("duration_days") or 0)
                d_dict["_deal_hash"] = deal_hash(
                    d_dict.get("destination", ""),
                    d_dict.get("departure_city", ""),
                    bucket,
                )
                d_dict["_duration_bucket"] = bucket
                deduped.append(d_dict)

            if len(deduped) == 1:
                log.info("📌 Single-deal batch — skipping LLM selection")
                selected_ids = [deduped[0]["id"]]
                ingest_log.selected_count = 1
            else:
                log.info("🤖 Sending %d deals to LLM for selection...", len(deduped))
                selection = select_with_llm(deduped)

                if selection.get("error"):
                    log.error("❌ LLM selection failed: %s", selection["error"])
                    ingest_log.status = "llm_error"
                    ingest_log.error_message = selection.get("error")
                    db.commit()
                    return

                selected_ids = selection.get("selected", [])[:2]
                log.info("🎯 LLM selected %d deal(s): %s", len(selected_ids), selected_ids)
                if selection.get("justification"):
                    log.info("💬 LLM justification: %s", selection["justification"])
                ingest_log.selected_count = len(selected_ids)

            patreon_pub = PatreonPublisher()
            twitter_pub = TwitterPublisher()
            published_summary = {"patreon": False, "x": False}

            for idx, sid in enumerate(selected_ids, 1):
                deal = next((d for d in deduped if d.get("id") == sid), None)
                if not deal:
                    log.warning("⚠️  Deal id=%s not found in deduped list — skipping", sid)
                    continue

                log.info("─" * 50)
                log.info("📢 Publishing deal %d/%d — id=%s destination=%s price=%s CZK",
                         idx, len(selected_ids), sid, deal.get("destination"), deal.get("price"))

                log.info("🎨 Generating Patreon post...")
                patreon_title, patreon_body = generate_patreon_post(deal)
                log.info("📝 Patreon title: %s", patreon_title)

                patreon_ok = False
                x_ok = False
                text = None

                try:
                    log.info("🎨 Publishing to Patreon...")
                    await patreon_pub.publish(
                        title=patreon_title,
                        body_text=patreon_body,
                        destination=deal.get("destination"),
                    )
                    patreon_ok = True
                    log.info("✅ Patreon — published successfully")
                except SessionExpiredError:
                    log.error("❌ Patreon — session expired")
                    notify_telegram("Patreon session expired for easy_travel_deal_publisher; renew session.")
                    patreon_ok = False
                except Exception:
                    log.exception("❌ Patreon — publish failed")

                twitter_configured = bool(settings.TWITTER_API_KEY and settings.TWITTER_ACCESS_TOKEN)
                if twitter_configured:
                    log.info("🐦 Generating Twitter post...")
                    text = generate_twitter_post(deal)
                    log.info("📝 Twitter text (%d chars): %s", len(text), text)
                    try:
                        log.info("🐦 Publishing to X/Twitter...")
                        res = twitter_pub.publish(text)
                        if res.get("success"):
                            x_ok = True
                            log.info("✅ Twitter — published successfully")
                        else:
                            log.warning("⚠️  Twitter — publish returned non-success: %s", res)
                    except Exception:
                        log.exception("❌ Twitter — publish failed")
                else:
                    log.info("🐦 Twitter not configured — skipping")

                published_to = (
                    PublishedToEnum.both if patreon_ok and x_ok
                    else (PublishedToEnum.patreon if patreon_ok
                          else (PublishedToEnum.x if x_ok else None))
                )

                if published_to is None:
                    log.warning("⚠️  Deal id=%s — nothing published, skipping DB write", sid)
                    continue

                log.info("💾 Saving PublishedDeal — patreon=%s x=%s published_to=%s",
                         patreon_ok, x_ok, published_to)

                pd = PublishedDeal(
                    destination=deal.get("destination"),
                    departure_city=deal.get("departure_city"),
                    price=deal.get("price"),
                    median_price=deal.get("median_price"),
                    discount_pct=deal.get("discount_pct"),
                    date_from=deal.get("date_from"),
                    date_to=deal.get("date_to"),
                    duration_days=deal.get("duration_days"),
                    published_at=datetime.utcnow(),
                    published_to=published_to,
                    post_text_patreon=patreon_body if patreon_ok else None,
                    post_text_x=text if x_ok else None,
                    deal_hash=deal.get("_deal_hash"),
                )
                db.add(pd)
                db.commit()
                log.debug("💾 PublishedDeal #%d saved", pd.id)

                published_summary["patreon"] = published_summary["patreon"] or patreon_ok
                published_summary["x"] = published_summary["x"] or x_ok

            ingest_log.status = "done"
            db.commit()

            log.info("━" * 60)
            log.info("📊 Ingest #%d complete — selected=%d patreon=%s x=%s",
                     ingest_id, len(selected_ids),
                     published_summary["patreon"], published_summary["x"])

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


# ── Deals ─────────────────────────────────────────────────────────────────────

@app.get("/deals")
def list_deals(
    db: Any = Depends(get_db),
    platform: Optional[str] = Query(None, description="Filter by platform: patreon | x | both"),
    destination: Optional[str] = Query(None, description="Partial case-insensitive match"),
    departure_city: Optional[str] = Query(None, description="Partial case-insensitive match"),
    from_date: Optional[str] = Query(None, description="Published on or after (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="Published on or before (YYYY-MM-DD)"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    q = db.query(PublishedDeal)
    if platform:
        try:
            q = q.filter(PublishedDeal.published_to == PublishedToEnum(platform))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid platform '{platform}'. Use: patreon, x, both")
    if destination:
        q = q.filter(PublishedDeal.destination.ilike(f"%{destination}%"))
    if departure_city:
        q = q.filter(PublishedDeal.departure_city.ilike(f"%{departure_city}%"))
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


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/stats", response_model=StatsOut)
def stats(db: Any = Depends(get_db)):
    seven_days_ago = datetime.utcnow() - timedelta(days=7)

    total_deals = db.query(func.count(PublishedDeal.id)).scalar() or 0

    platform_rows = (
        db.query(PublishedDeal.published_to, func.count(PublishedDeal.id))
        .group_by(PublishedDeal.published_to)
        .all()
    )
    by_platform = {str(p): c for p, c in platform_rows}

    ingest_total = db.query(func.count(IngestLog.id)).scalar() or 0
    status_rows = (
        db.query(IngestLog.status, func.count(IngestLog.id))
        .group_by(IngestLog.status)
        .all()
    )
    ingest_by_status = {s: c for s, c in status_rows}

    avg_discount = db.query(func.avg(PublishedDeal.discount_pct)).scalar()
    avg_price = db.query(func.avg(PublishedDeal.price)).scalar()
    min_price = db.query(func.min(PublishedDeal.price)).scalar()
    max_price = db.query(func.max(PublishedDeal.price)).scalar()

    top_dest_rows = (
        db.query(PublishedDeal.destination, func.count(PublishedDeal.id).label("n"))
        .group_by(PublishedDeal.destination)
        .order_by(func.count(PublishedDeal.id).desc())
        .limit(5)
        .all()
    )
    top_destinations = [{"destination": d, "count": c} for d, c in top_dest_rows]

    last_7_deals = (
        db.query(func.count(PublishedDeal.id))
        .filter(PublishedDeal.published_at >= seven_days_ago)
        .scalar() or 0
    )
    last_7_ingests = (
        db.query(func.count(IngestLog.id))
        .filter(IngestLog.received_at >= seven_days_ago)
        .scalar() or 0
    )

    log.debug("📊 /stats — %d deals total", total_deals)
    return StatsOut(
        total_deals=total_deals,
        by_platform=by_platform,
        ingest_totals={"total": ingest_total},
        ingest_by_status=ingest_by_status,
        avg_discount_pct=round(avg_discount, 2) if avg_discount is not None else None,
        avg_price=round(float(avg_price), 2) if avg_price is not None else None,
        min_price=min_price,
        max_price=max_price,
        top_destinations=top_destinations,
        last_7_days_deals=last_7_deals,
        last_7_days_ingests=last_7_ingests,
    )
