import logging
from fastapi import FastAPI, Header, HTTPException, Depends
from typing import Optional
from .config import settings
from .schemas import IngestPayload, PatreonSessionPayload
from .database import get_db
from typing import Any
from .deal_selector import filter_duplicates, select_with_llm
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


@app.get("/health")
def health():
    return {"status": "ok"}


def verify_api_key(x_api_key: Optional[str] = Header(None)):
    if settings.INGEST_API_KEY and x_api_key != settings.INGEST_API_KEY:
        raise HTTPException(status_code=403, detail="invalid api key")


@app.post("/session/patreon")
def set_patreon_session(payload: PatreonSessionPayload, x_api_key: Optional[str] = Depends(verify_api_key)):
    import base64
    import json
    session_data = {
        "cookies": [c.dict(exclude_none=True) for c in payload.cookies],
        "email": payload.email or "",
        "timestamp": datetime.utcnow().isoformat(),
    }
    encoded = base64.b64encode(json.dumps(session_data).encode()).decode()
    settings.PATREON_SESSION = encoded
    return {
        "patreon_session": encoded,
        "note": "Session active. Persist by setting PATREON_SESSION in .env",
    }


@app.post("/ingest")
async def ingest(payload: IngestPayload, db: Any = Depends(get_db), x_api_key: Optional[str] = Depends(verify_api_key)):
    log.info("Received ingest with %d deals", len(payload.deals))
    # create ingest log
    ingest_log = IngestLog(deals_count=len(payload.deals), status="processing")
    db.add(ingest_log)
    db.commit()
    try:
        deduped = filter_duplicates(db, [d.dict() for d in payload.deals])
        if not deduped:
            ingest_log.status = "no_new_deals"
            ingest_log.selected_count = 0
            db.add(ingest_log)
            db.commit()
            return {"status": "ok", "selected": 0, "published": {"patreon": False, "x": False}}

        selection = select_with_llm(deduped)
        if selection.get("error"):
            ingest_log.status = "llm_error"
            ingest_log.error_message = selection.get("error")
            db.add(ingest_log)
            db.commit()
            return {"status": "ok", "error": selection.get("error"), "selected": 0, "published": {"patreon": False, "x": False}}
        selected_ids = selection.get("selected", [])
        ingest_log.selected_count = len(selected_ids)

        patreon_pub = PatreonPublisher()
        twitter_pub = TwitterPublisher()

        published_summary = {"patreon": False, "x": False}

        for sid in selected_ids:
            deal = next((d for d in deduped if d.get("id") == sid), None)
            if not deal:
                continue
            # generate posts
            patreon_title, patreon_body = generate_patreon_post(deal)
            text = generate_twitter_post(deal)

            patreon_ok = False
            x_ok = False
            try:
                await patreon_pub.publish(
                    title=patreon_title,
                    body_text=patreon_body,
                    destination=deal.get("destination")
                )
                patreon_ok = True
            except SessionExpiredError:
                log.exception("Patreon session expired")
                notify_telegram("Patreon session expired for easy_travel_deal_publisher; renew session.")
                patreon_ok = False
            except Exception:
                log.exception("Patreon publish failed")

            try:
                res = twitter_pub.publish(text)
                if res.get("success"):
                    x_ok = True
            except Exception:
                log.exception("Twitter publish failed")

            # save published deal
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
                published_to=(PublishedToEnum.both if patreon_ok and x_ok else (PublishedToEnum.patreon if patreon_ok else (PublishedToEnum.x if x_ok else None))),
                post_text_patreon=patreon_body if patreon_ok else None,
                post_text_x=text if x_ok else None,
                deal_hash=deal.get("_deal_hash"),
            )
            db.add(pd)
            db.commit()
            published_summary["patreon"] = published_summary["patreon"] or patreon_ok
            published_summary["x"] = published_summary["x"] or x_ok

        ingest_log.status = "done"
        db.add(ingest_log)
        db.commit()
        return {"status": "ok", "selected": len(selected_ids), "published": published_summary}
    except Exception as e:
        log.exception("Error processing ingest")
        ingest_log.status = "error"
        ingest_log.error_message = str(e)
        db.add(ingest_log)
        db.commit()
        return {"status": "ok", "error": str(e), "selected": 0, "published": {"patreon": False, "x": False}}


@app.get("/history")
def history(db: Any = Depends(get_db)):
    rows = db.query(PublishedDeal).order_by(PublishedDeal.published_at.desc()).limit(30).all()
    return {"data": [r.__dict__ for r in rows]}


@app.get("/ingest-log")
def ingest_log(db: Any = Depends(get_db)):
    rows = db.query(IngestLog).order_by(IngestLog.received_at.desc()).limit(30).all()
    return {"data": [r.__dict__ for r in rows]}
