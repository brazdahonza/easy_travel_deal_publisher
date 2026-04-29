import logging
from .config import settings
from typing import List, Dict

log = logging.getLogger(__name__)


class AnthropicWrapper:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        try:
            import anthropic
            self._client = anthropic.Client(self.api_key) if self.api_key else anthropic.Client()
        except Exception:
            self._client = None

    def select(self, deals: List[Dict]) -> Dict:
        # Build prompt
        prompt = (
            "You are deal selector for flynow.cz. Receive JSON list of deals. "
            "Return XML tags <selection><ids>id1,id2</ids><justification>... in Czech</justification>. "
            f"DATA: {deals}"
        )
        if not self._client:
            log.debug("Anthropic client unavailable")
            raise RuntimeError("Anthropic client unavailable")

        try:
            resp = self._client.completions.create(model="claude-opus-4-5", prompt=prompt, max_tokens=350)
            # response.text often holds content
            text = getattr(resp, "text", None) or str(resp)
            return {"raw": text}
        except Exception as e:
            log.exception("Anthropic call failed")
            raise
