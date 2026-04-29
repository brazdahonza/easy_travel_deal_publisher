import logging
from ..config import settings
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
            except Exception:
                log.exception("Invalid PATREON_SESSION")

    def _get_image_path(self, destination: str) -> str:
        app_dir = pathlib.Path(__file__).parent.parent.parent
        image_path = app_dir / "assets" / "patreon" / f"{destination}.png"
        if image_path.exists():
            return str(image_path)
        log.warning(f"Image not found for destination: {destination}")
        return None

    async def publish(self, title: str, body_text: str, destination: str = None) -> dict:
        if not self.session:
            raise SessionExpiredError("Missing or invalid Patreon session")

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError("Playwright not installed")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()

            try:
                cookies = self.session.get("cookies", [])
                if cookies:
                    await context.add_cookies(cookies)

                page = await context.new_page()

                # Step 1: Home
                log.info("Navigating to Patreon home")
                await page.goto("https://www.patreon.com/home", wait_until="networkidle")
                await page.wait_for_timeout(2000)

                # Step 2: Create button
                log.info("Clicking Create button")
                create_btn = page.locator('[data-tag="create-content-button"]').first
                await create_btn.wait_for(state="visible", timeout=10000)
                await create_btn.click()
                await page.wait_for_timeout(1000)

                # Step 3: Post option from dropdown
                log.info("Clicking Post option")
                post_option = page.locator('a:has([data-tag="IconPosts"])')
                await post_option.wait_for(state="visible", timeout=5000)
                await post_option.click()
                await page.wait_for_timeout(2000)

                # Step 4: Title
                log.info(f"Filling title: {title}")
                title_field = page.locator('textarea[placeholder="Title"]')
                await title_field.wait_for(state="visible", timeout=10000)
                await title_field.fill(title)
                await page.wait_for_timeout(500)

                # Step 5: Body
                log.info("Filling body")
                body_field = page.locator('div[contenteditable="true"][aria-label="Text input field for post content"]')
                await body_field.wait_for(state="visible", timeout=10000)
                await body_field.click()
                await body_field.fill(body_text)
                await page.wait_for_timeout(500)

                # Step 6 & 7: Image upload
                if destination:
                    image_path = self._get_image_path(destination)
                    if image_path:
                        try:
                            log.info(f"Uploading image for {destination}")
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
                        except Exception as e:
                            log.warning(f"Image upload failed: {e}")

                log.info("Post prepared as draft")

                # Persist updated cookies
                try:
                    updated_cookies = await context.cookies()
                    self.session["cookies"] = updated_cookies
                    log.debug("Session cookies refreshed")
                except Exception as e:
                    log.debug(f"Failed to refresh session cookies: {e}")

                return {"success": True, "url": page.url}

            finally:
                await context.close()
                await browser.close()
