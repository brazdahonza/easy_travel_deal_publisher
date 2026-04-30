import logging
from ..config import settings

log = logging.getLogger(__name__)


class TwitterPublisher:
    def __init__(self):
        try:
            import tweepy
            self._tweepy = tweepy
            log.debug("✅ tweepy imported successfully")
        except Exception:
            log.warning("⚠️  tweepy not installed — Twitter publishing disabled")
            self._tweepy = None

        self.client = None
        if self._tweepy and settings.TWITTER_API_KEY:
            try:
                self.client = self._tweepy.Client(
                    consumer_key=settings.TWITTER_API_KEY,
                    consumer_secret=settings.TWITTER_API_SECRET,
                    access_token=settings.TWITTER_ACCESS_TOKEN,
                    access_token_secret=settings.TWITTER_ACCESS_SECRET,
                )
                log.info("✅ Twitter client initialized")
            except Exception:
                log.exception("❌ Failed to initialize Twitter client")
        else:
            if not self._tweepy:
                log.info("🐦 Twitter disabled — tweepy not installed")
            else:
                log.info("🐦 Twitter disabled — TWITTER_API_KEY not configured")

    def publish(self, text: str) -> dict:
        if not self.client:
            log.warning("⚠️  Twitter client not configured — skipping publish")
            return {"success": False, "reason": "not_configured"}

        log.info("🐦 Posting tweet (%d chars)...", len(text))
        try:
            resp = self.client.create_tweet(text=text)
            tweet_id = getattr(resp.data, "id", None) if resp.data else None
            log.info("✅ Tweet published — id=%s", tweet_id)
            return {"success": True, "result": resp, "tweet_id": tweet_id}
        except Exception:
            log.exception("❌ Twitter create_tweet failed")
            raise
