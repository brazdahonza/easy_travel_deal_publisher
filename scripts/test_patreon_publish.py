"""Local debug runner for PatreonPublisher.

Runs a single publish() call against Patreon with a visible browser so you
can watch the automation, see exactly where it breaks, and inspect the DOM
in DevTools.

Usage:
    # From project root, with .env populated (PATREON_SESSION required):
    PATREON_HEADLESS=false PATREON_SLOWMO_MS=300 python -m scripts.test_patreon_publish

    # Or pass title/body/destination as args:
    PATREON_HEADLESS=false python -m scripts.test_patreon_publish "My Title" "My body text" "Praha"

After failure, screenshot + HTML are saved under /tmp/patreon_debug/.
"""
import asyncio
import logging
import sys

from app.publishers.patreon import PatreonPublisher


async def main():
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    title = sys.argv[1] if len(sys.argv) > 1 else "TEST — debug post (delete me)"
    body = sys.argv[2] if len(sys.argv) > 2 else "Local debug run. Ignore."
    destination = sys.argv[3] if len(sys.argv) > 3 else None

    pub = PatreonPublisher()
    result = await pub.publish(title=title, body_text=body, destination=destination)
    print("RESULT:", result)


if __name__ == "__main__":
    asyncio.run(main())
