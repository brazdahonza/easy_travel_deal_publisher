import hashlib
from typing import List, Dict, Any
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



def build_anthropic_prompt(deals: List[Dict]) -> str:
    payload = {"deals": deals}
    prompt = (
        "You are deal selector for flynow.cz. Receive JSON list of deals. "
        "Return XML tags <selection><ids>... and <justification> in Czech. "
        "Select exactly two deals: prefer one nearby and one foreign, but if no nearby, pick two foreign.\n"
        f"DATA: {payload}"
    )
    return prompt


def parse_anthropic_response(text: str) -> Dict:
    res = {"selected": [], "justification": ""}
    try:
        if "<ids>" in text and "</ids>" in text:
            inside = text.split("<ids>", 1)[1].split("</ids>", 1)[0]
            ids = [i.strip() for i in inside.split(",") if i.strip()]
            res["selected"] = ids
        if "<justification>" in text and "</justification>" in text:
            res["justification"] = text.split("<justification>", 1)[1].split("</justification>", 1)[0].strip()
    except Exception:
        log.warning("⚠️  Failed to parse LLM XML response")
    return res


def select_with_llm(deals: List[Dict]) -> Dict:
    nearby_count = sum(1 for d in deals if d.get("is_nearby"))
    foreign_count = len(deals) - nearby_count
    log.info("🤖 LLM selection — %d candidates (%d nearby, %d foreign)",
             len(deals), nearby_count, foreign_count)

    try:
        from .llm import AnthropicWrapper
        wrapper = AnthropicWrapper()

        if not getattr(wrapper, "_client", None) or not settings.ANTHROPIC_API_KEY:
            log.warning("⚠️  Anthropic not configured — skipping LLM, using fallback")
            raise RuntimeError("Anthropic not configured")

        log.info("📡 Calling Anthropic API...")
        raw = wrapper.select(deals)
        text = raw.get("raw") if isinstance(raw, dict) else str(raw)
        log.debug("🤖 Raw LLM response: %s", text[:300] if text else "(empty)")

        parsed = parse_anthropic_response(text)
        if parsed.get("selected"):
            log.info("✅ LLM parsed — selected ids: %s", parsed["selected"])
            return parsed
        else:
            log.warning("⚠️  LLM response parsed but no IDs found — falling back")

    except Exception:
        if settings.ANTHROPIC_API_KEY:
            log.exception("❌ Anthropic selection failed")
            return {"selected": [], "justification": "", "error": "Anthropic selection failed"}
        log.info("🔄 Anthropic not available — using fallback selector")

    # ── Fallback selector ──────────────────────────────────────────
    log.info("🔄 Fallback selection — prefer 1 nearby + 1 foreign")
    nearby = [d for d in deals if d.get("is_nearby")]
    foreign = [d for d in deals if not d.get("is_nearby")]
    selected = []

    if nearby:
        selected.append(nearby[0]["id"])
        log.debug("  🏠 Nearby pick: %s", nearby[0].get("destination"))
        if foreign:
            selected.append(foreign[0]["id"])
            log.debug("  ✈️  Foreign pick: %s", foreign[0].get("destination"))
        elif len(nearby) > 1:
            selected.append(nearby[1]["id"])
            log.debug("  🏠 Second nearby pick: %s", nearby[1].get("destination"))
    else:
        for d in deals[:2]:
            selected.append(d["id"])
            log.debug("  ✈️  Foreign pick: %s", d.get("destination"))

    log.info("🎯 Fallback selected: %s", selected)
    return {"selected": selected, "justification": "fallback selection"}
