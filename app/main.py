import logging
from fastapi import FastAPI, Header, HTTPException, Depends
from typing import Optional
from .config import settings
from .schemas import IngestPayload, PatreonSessionPayload
from .database import get_db
from typing import Any
from .deal_selector import filter_duplicates, select_with_llm, deal_hash, duration_bucket
from .post_generator import generate_patreon_post, generate_twitter_post
from .publishers import PatreonPublisher, TwitterPublisher, SessionExpiredError
from .utils import notify_telegram
from .models import PublishedDeal, IngestLog, PublishedToEnum
from datetime import datetime
log = logging.getLogger(__name__)

app = FastAPI(title="easy_travel_deal_publisher")


@app.on_event("startup")
def create_tables():
    from .database import ENGINE, Base
    from . import models  # noqa: F401 — registers table metadata
    if ENGINE is not None:
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
def health():
    log.debug("❤️  Health check")
    return {"status": "ok"}


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
async def ingest(payload: IngestPayload, db: Any = Depends(get_db), x_api_key: Optional[str] = Depends(verify_api_key)):
    log.info("━" * 60)
    log.info("📥 Ingest received — %d deals in batch", len(payload.deals))
    for deal in payload.deals:
        log.debug(
            "  📦 Deal: id=%s destination=%s departure=%s price=%s CZK discount=%s%%",
            deal.id, deal.destination, deal.departure_city, deal.price,
            f"{deal.discount_pct:.1f}" if deal.discount_pct else "n/a",
        )

    ingest_log = IngestLog(deals_count=len(payload.deals), status="processing")
    db.add(ingest_log)
    db.commit()
    log.debug("💾 IngestLog #%d created", ingest_log.id)

    try:
        if len(payload.deals) == 1:
            # ── Single-deal fast path ──────────────────────────────────
            log.info("📌 Single-deal batch — skipping deduplication and LLM selection")
            deal_dicts = [d.dict() for d in payload.deals]
            for d in deal_dicts:
                bucket = duration_bucket(d.get("duration_days") or 0)
                d["_deal_hash"] = deal_hash(d.get("destination", ""), d.get("departure_city", ""), bucket)
                d["_duration_bucket"] = bucket
            deduped = deal_dicts
            selected_ids = [deduped[0]["id"]]
            ingest_log.selected_count = 1
        else:
            # ── Deduplication ─────────────────────────────────────────
            log.info("🔍 Running deduplication...")
            deduped = filter_duplicates(db, [d.dict() for d in payload.deals])
            filtered_count = len(payload.deals) - len(deduped)
            log.info("🧹 Dedup done — %d filtered, %d remain", filtered_count, len(deduped))

            if not deduped:
                log.info("✋ All deals already published recently — nothing to do")
                ingest_log.status = "no_new_deals"
                ingest_log.selected_count = 0
                db.add(ingest_log)
                db.commit()
                return {"status": "ok", "selected": 0, "published": {"patreon": False, "x": False}}

            # ── LLM selection ─────────────────────────────────────────
            log.info("🤖 Sending %d deals to LLM for selection...", len(deduped))
            selection = select_with_llm(deduped)

            if selection.get("error"):
                log.error("❌ LLM selection failed: %s", selection["error"])
                ingest_log.status = "llm_error"
                ingest_log.error_message = selection.get("error")
                db.add(ingest_log)
                db.commit()
                return {"status": "ok", "error": selection.get("error"), "selected": 0, "published": {"patreon": False, "x": False}}

            selected_ids = selection.get("selected", [])[:2]
            log.info("🎯 LLM selected %d deal(s): %s", len(selected_ids), selected_ids)
            if selection.get("justification"):
                log.info("💬 LLM justification: %s", selection["justification"])
            ingest_log.selected_count = len(selected_ids)

        patreon_pub = PatreonPublisher()
        twitter_pub = TwitterPublisher()
        published_summary = {"patreon": False, "x": False}

        # ── Publish each selected deal ─────────────────────────────
        for idx, sid in enumerate(selected_ids, 1):
            deal = next((d for d in deduped if d.get("id") == sid), None)
            if not deal:
                log.warning("⚠️  Deal id=%s not found in deduped list — skipping", sid)
                continue

            log.info("─" * 50)
            log.info("📢 Publishing deal %d/%d — id=%s destination=%s price=%s CZK",
                     idx, len(selected_ids), sid, deal.get("destination"), deal.get("price"))

            # ── Patreon ───────────────────────────────────────────
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
                    destination=deal.get("destination")
                )
                patreon_ok = True
                log.info("✅ Patreon — published successfully")
            except SessionExpiredError:
                log.error("❌ Patreon — session expired")
                notify_telegram("Patreon session expired for easy_travel_deal_publisher; renew session.")
                patreon_ok = False
            except Exception:
                log.exception("❌ Patreon — publish failed")

            # ── Twitter ───────────────────────────────────────────
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

            # ── Persist ───────────────────────────────────────────
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
        db.add(ingest_log)
        db.commit()

        log.info("━" * 60)
        log.info("📊 Ingest complete — selected=%d patreon=%s x=%s",
                 len(selected_ids), published_summary["patreon"], published_summary["x"])
        return {"status": "ok", "selected": len(selected_ids), "published": published_summary}

    except Exception as e:
        log.exception("💥 Fatal error during ingest pipeline")
        ingest_log.status = "error"
        ingest_log.error_message = str(e)
        db.add(ingest_log)
        db.commit()
        return {"status": "ok", "error": str(e), "selected": 0, "published": {"patreon": False, "x": False}}


@app.get("/history")
def history(db: Any = Depends(get_db)):
    rows = db.query(PublishedDeal).order_by(PublishedDeal.published_at.desc()).limit(30).all()
    log.debug("📖 /history — returned %d rows", len(rows))
    return {"data": [r.__dict__ for r in rows]}


@app.get("/ingest-log")
def ingest_log(db: Any = Depends(get_db)):
    rows = db.query(IngestLog).order_by(IngestLog.received_at.desc()).limit(30).all()
    log.debug("📖 /ingest-log — returned %d rows", len(rows))
    return {"data": [r.__dict__ for r in rows]}
