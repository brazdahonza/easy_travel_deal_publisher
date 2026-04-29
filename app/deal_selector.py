import hashlib
from typing import List, Dict, Any
from datetime import datetime, timedelta
import logging
from .config import settings

log = logging.getLogger(__name__)


def duration_bucket(days: int) -> str:
    if days is None:
        return "unknown"
    if 2 <= days <= 4:
        return "weekend"
    if 5 <= days <= 9:
        return "week"
    if days >= 10:
        return "twoweeks"
    return "short"


def deal_hash(destination: str, departure_city: str, duration_bucket_str: str) -> str:
    s = f"{destination}|{departure_city}|{duration_bucket_str}"
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def filter_duplicates(db: Any, deals: List[Dict]) -> List[Dict]:
    cutoff = datetime.utcnow() - timedelta(days=7)
    filtered = []
    for d in deals:
        bucket = duration_bucket(d.get("duration_days") or 0)
        h = deal_hash(d.get("destination",""), d.get("departure_city",""), bucket)
        try:
            from .models import PublishedDeal  # lazy import so tests can run without sqlalchemy
        except Exception:
            PublishedDeal = None

        exists = None
        if PublishedDeal is not None:
            try:
                exists = db.query(PublishedDeal).filter(PublishedDeal.deal_hash == h, PublishedDeal.published_at >= cutoff).first()
            except Exception:
                exists = None
        if not exists:
            d["_deal_hash"] = h
            d["_duration_bucket"] = bucket
            filtered.append(d)
        else:
            log.debug("Duplicate filtered: %s", h)
    return filtered


def build_anthropic_prompt(deals: List[Dict]) -> str:
    # Build JSON payload and instruct Claude to return XML-wrapped response
    payload = {"deals": deals}
    prompt = (
        "You are deal selector for flynow.cz. Receive JSON list of deals. "
        "Return XML tags <selection><ids>... and <justification> in Czech. "
        "Select exactly two deals: prefer one nearby and one foreign, but if no nearby, pick two foreign.\n"
        f"DATA: {payload}"
    )
    return prompt


def parse_anthropic_response(text: str) -> Dict:
    # naive parser for expected XML-like response
    res = {"selected": [], "justification": ""}
    try:
        if "<ids>" in text and "</ids>" in text:
            inside = text.split("<ids>",1)[1].split("</ids>",1)[0]
            ids = [i.strip() for i in inside.split(",") if i.strip()]
            res["selected"] = ids
        if "<justification>" in text and "</justification>" in text:
            res["justification"] = text.split("<justification>",1)[1].split("</justification>",1)[0].strip()
    except Exception:
        pass
    return res


def select_with_llm(deals: List[Dict]) -> Dict:
    # try using Anthropic wrapper; fallback to simple selection
    try:
        from .llm import AnthropicWrapper
        wrapper = AnthropicWrapper()
        if not getattr(wrapper, "_client", None) or not settings.ANTHROPIC_API_KEY:
            raise RuntimeError("Anthropic not configured")
        raw = wrapper.select(deals)
        text = raw.get("raw") if isinstance(raw, dict) else str(raw)
        parsed = parse_anthropic_response(text)
        if parsed.get("selected"):
            return parsed
    except Exception:
        if settings.ANTHROPIC_API_KEY:
            log.exception("Anthropic selection failed")
            return {"selected": [], "justification": "", "error": "Anthropic selection failed"}
        log.debug("Anthropic not available or not configured, using fallback")

    # fallback: pick first two, prefer is_nearby flag
    nearby = [d for d in deals if d.get("is_nearby")]
    foreign = [d for d in deals if not d.get("is_nearby")]
    selected = []
    if nearby:
        selected.append(nearby[0]["id"])
        if foreign:
            selected.append(foreign[0]["id"])
        elif len(nearby) > 1:
            selected.append(nearby[1]["id"])
    else:
        for d in deals[:2]:
            selected.append(d["id"])
    return {"selected": selected, "justification": "fallback selection"}
