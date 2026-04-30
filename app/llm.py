import logging
from .config import settings
from typing import List, Dict, Tuple

log = logging.getLogger(__name__)


class AnthropicWrapper:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        if not self.api_key:
            log.warning("⚠️  ANTHROPIC_API_KEY not set — client will not be created")
        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key) if self.api_key else anthropic.Anthropic()
            log.debug("✅ Anthropic client initialized")
        except Exception:
            log.exception("❌ Failed to initialize Anthropic client")
            self._client = None

    def select(self, deals: List[Dict]) -> Dict:
        deals_with_extra = []
        for d in deals:
            entry = {k: v for k, v in d.items() if not k.startswith("_")}
            if d.get("extra"):
                entry["extra_context"] = d["extra"]
            deals_with_extra.append(entry)

        prompt = (
            "You are deal selector for flynow.cz. Receive JSON list of deals. "
            "Each deal may contain 'extra_context' with additional information — use it when selecting. "
            "Return XML tags <selection><ids>id1,id2</ids><justification>... in Czech</justification>. "
            f"DATA: {deals_with_extra}"
        )

        if not self._client:
            log.error("❌ Anthropic client unavailable — cannot select deals")
            raise RuntimeError("Anthropic client unavailable")

        log.info("📡 Sending %d deals to Anthropic (claude-haiku-4-5-20251001)...", len(deals_with_extra))
        log.debug("📝 Prompt length: %d chars", len(prompt))

        try:
            resp = self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=350,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text if resp.content else ""
            log.info("✅ Anthropic response received — %d chars", len(text))
            log.debug("📊 Usage — input_tokens=%s output_tokens=%s",
                      getattr(resp.usage, "input_tokens", "?"),
                      getattr(resp.usage, "output_tokens", "?"))
            log.debug("🤖 Response text: %s", text[:300])
            return {"raw": text}
        except Exception as e:
            log.exception("❌ Anthropic API call failed: %s", e)
            raise

    def generate_post(self, deal: Dict, system_prompt: str, max_tokens: int = 1024) -> str:
        import json
        import datetime
        if not self._client:
            raise RuntimeError("Anthropic client unavailable")

        def _default(obj):
            if isinstance(obj, (datetime.date, datetime.datetime)):
                return obj.isoformat()
            if hasattr(obj, "__str__"):
                return str(obj)
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

        user_msg = json.dumps(
            {k: v for k, v in deal.items() if not k.startswith("_")},
            ensure_ascii=False,
            default=_default,
        )
        log.info("📡 Generating post via Anthropic — destination=%s", deal.get("destination"))
        resp = self._client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text.strip() if resp.content else ""
        log.info("✅ Post generated — %d chars", len(text))
        log.debug("📊 Usage — input=%s output=%s",
                  getattr(resp.usage, "input_tokens", "?"),
                  getattr(resp.usage, "output_tokens", "?"))
        return text
