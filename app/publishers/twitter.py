import logging
from ..config import settings

log = logging.getLogger(__name__)


class TwitterPublisher:
    def __init__(self):
        try:
            import tweepy
        except Exception:
            tweepy = None
        self._tweepy = tweepy
        self.client = None
        if tweepy and settings.TWITTER_API_KEY:
            self.client = tweepy.Client(
                consumer_key=settings.TWITTER_API_KEY,
                consumer_secret=settings.TWITTER_API_SECRET,
                access_token=settings.TWITTER_ACCESS_TOKEN,
                access_token_secret=settings.TWITTER_ACCESS_SECRET,
            )

    def publish(self, text: str) -> dict:
        if not self.client:
            log.warning("Twitter client not configured")
            return {"success": False, "reason": "not_configured"}
        resp = self.client.create_tweet(text=text)
        return {"success": True, "result": resp}
