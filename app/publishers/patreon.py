import logging
import unicodedata
from ..config import settings
from ..utils import notify_telegram
import base64
import json
import pathlib

log = logging.getLogger(__name__)


class SessionExpiredError(Exception):
    pass


class PatreonPublisher:
    def __init__(self):
        self.session = None
        if settings.PATREON_SESSION:
            try:
                data = base64.b64decode(settings.PATREON_SESSION)
                self.session = json.loads(data)
                cookie_count = len(self.session.get("cookies", []))
                timestamp = self.session.get("timestamp", "unknown")
                log.info("🔐 Patreon session loaded — %d cookies, stored at %s", cookie_count, timestamp)
            except Exception:
                log.exception("❌ Failed to decode PATREON_SESSION")
        else:
            log.warning("⚠️  PATREON_SESSION not set — Patreon publishing disabled")

    @staticmethod
    def _normalize(text: str) -> str:
        nfkd = unicodedata.normalize("NFKD", text)
        return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()

    def _get_image_path(self, destination: str) -> str:
        app_dir = pathlib.Path(__file__).parent.parent.parent
        patreon_dir = app_dir / "assets" / "patreon"
        dest_norm = self._normalize(destination)

        candidates = list(patreon_dir.glob("*.png"))

        # Exact match against any " - "-separated variant in filename
        for img_path in candidates:
            variants = [v.strip() for v in img_path.stem.split(" - ")]
            if any(self._normalize(v) == dest_norm for v in variants):
                log.info("🖼️  Image found for destination '%s': %s", destination, img_path)
                return str(img_path)

        # Partial match: destination contained in any variant or vice-versa
        for img_path in candidates:
            variants = [v.strip() for v in img_path.stem.split(" - ")]
            if any(dest_norm in self._normalize(v) or self._normalize(v) in dest_norm for v in variants):
                log.info("🖼️  Fuzzy image match for destination '%s': %s", destination, img_path)
                return str(img_path)

        log.warning("🖼️  No image found for destination '%s' — post will have no image", destination)
        return None

    async def publish(self, title: str, body_text: str, destination: str = None) -> dict:
        if not self.session:
            log.error("❌ Cannot publish — Patreon session missing or invalid")
            raise SessionExpiredError("Missing or invalid Patreon session")

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            log.error("❌ Playwright not installed — cannot publish to Patreon")
            raise RuntimeError("Playwright not installed")

        log.info("🎨 Starting Patreon publish — title='%s' destination=%s", title, destination or "n/a")

        async with async_playwright() as p:
            log.debug("🌐 Launching Chromium browser (headless=True)")
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()

            try:
                cookies = self.session.get("cookies", [])
                if cookies:
                    await context.add_cookies(cookies)
                    log.debug("🍪 Injected %d session cookies", len(cookies))

                page = await context.new_page()

                # Step 1: Navigate home
                log.info("🏠 Navigating to Patreon home...")
                await page.goto("https://www.patreon.com/home", wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(2000)
                log.debug("🏠 Patreon home loaded — url=%s", page.url)

                if "login" in page.url or "signup" in page.url:
                    raise SessionExpiredError("Session expired — redirected to login")

                # Step 2: Click Create button
                log.info("🖱️  Clicking Create button...")
                create_btn = page.locator('[data-tag="create-content-button"]').first
                await create_btn.wait_for(state="visible", timeout=10000)
                await create_btn.click()
                await page.wait_for_timeout(1000)
                log.debug("✅ Create button clicked")

                # Step 3: Select Post from dropdown
                log.info("🖱️  Selecting Post option from dropdown...")
                post_option = page.locator('a:has([data-tag="IconPosts"])')
                await post_option.wait_for(state="visible", timeout=5000)
                await post_option.click()
                await page.wait_for_timeout(2000)
                log.debug("✅ Post option selected — url=%s", page.url)

                # Step 4: Fill title
                log.info("✏️  Filling title field: '%s'", title)
                title_field = page.locator('textarea[placeholder="Title"]')
                await title_field.wait_for(state="visible", timeout=10000)
                await title_field.fill(title)
                await page.wait_for_timeout(500)
                log.debug("✅ Title filled")

                # Step 5: Fill body
                log.info("✏️  Filling body field (%d chars)...", len(body_text))
                body_field = page.locator('div[contenteditable="true"][aria-label="Text input field for post content"]')
                await body_field.wait_for(state="visible", timeout=10000)
                await body_field.click()
                await body_field.fill(body_text)
                await page.wait_for_timeout(500)
                log.debug("✅ Body filled")

                # Step 6: Image upload
                if destination:
                    image_path = self._get_image_path(destination)
                    if image_path:
                        log.info("🖼️  Uploading image for '%s'...", destination)
                        try:
                            image_btn = page.locator('button:has([data-tag="IconPhoto"])')
                            await image_btn.wait_for(state="visible", timeout=5000)
                            await image_btn.click()
                            await page.wait_for_timeout(1000)

                            browse_btn = page.locator('button:has-text("Browse")').last
                            await browse_btn.wait_for(state="visible", timeout=5000)
                            async with page.expect_file_chooser() as fc_info:
                                await browse_btn.click()
                            file_chooser = await fc_info.value
                            await file_chooser.set_files(image_path)
                            await page.wait_for_timeout(2000)
                            log.info("✅ Image uploaded successfully")
                        except Exception as e:
                            log.warning("⚠️  Image upload failed — continuing without image: %s", e)
                    else:
                        log.info("🖼️  No image available for '%s' — skipping upload", destination)

                log.info("✅ Patreon draft prepared — title='%s'", title)

                # Navigate away to trigger Patreon's auto-save of the draft
                log.info("💾 Navigating away to trigger draft save...")
                await page.goto("https://www.patreon.com", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)
                log.info("💾 Draft save triggered — url=%s", page.url)

                notify_telegram(f"Patreon draft připraven: {title}")

                # Persist updated cookies
                try:
                    updated_cookies = await context.cookies()
                    self.session["cookies"] = updated_cookies
                    log.debug("🍪 Session cookies refreshed — %d cookies stored", len(updated_cookies))
                except Exception as e:
                    log.debug("⚠️  Failed to refresh session cookies: %s", e)

                result = {"success": True, "url": page.url}
                log.info("🎉 Patreon publish complete — browser will close and restart for next post")
                return result

            except Exception:
                log.exception("💥 Patreon publish failed during browser automation")
                raise
            finally:
                await context.close()
                await browser.close()
                log.debug("🌐 Browser closed")
