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

    @staticmethod
    async def _find_first_visible(page, selectors: list, timeout_ms: int = 10000):
        """Try multiple selectors, return first that becomes visible. Raise TimeoutError if none."""
        import asyncio
        per_try = max(1500, timeout_ms // max(1, len(selectors)))
        last_err = None
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                await loc.wait_for(state="visible", timeout=per_try)
                log.debug("✅ Matched selector: %s", sel)
                return loc
            except Exception as e:
                last_err = e
                log.debug("⚠️  Selector miss: %s", sel)
        raise last_err if last_err else RuntimeError("No selectors matched")

    async def _dump_diagnostics(self, page, tag: str):
        """Save screenshot + HTML for post-mortem when selectors fail."""
        try:
            out_dir = pathlib.Path("/tmp/patreon_debug")
            out_dir.mkdir(parents=True, exist_ok=True)
            import time
            stamp = int(time.time())
            shot = out_dir / f"{tag}_{stamp}.png"
            html = out_dir / f"{tag}_{stamp}.html"
            await page.screenshot(path=str(shot), full_page=True)
            content = await page.content()
            html.write_text(content, encoding="utf-8")
            log.error("📸 Diagnostics saved — url=%s screenshot=%s html=%s", page.url, shot, html)
        except Exception as e:
            log.warning("⚠️  Failed to dump diagnostics: %s", e)

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

        try:
            from playwright_stealth import Stealth
        except ImportError:
            Stealth = None
            log.warning("⚠️  playwright-stealth not installed — bot detection more likely in headless mode")

        async with async_playwright() as p:
            headless = settings.PATREON_HEADLESS
            slow_mo = settings.PATREON_SLOWMO_MS
            log.debug("🌐 Launching Chromium browser (headless=%s, slow_mo=%dms, stealth=%s)", headless, slow_mo, Stealth is not None)
            browser = await p.chromium.launch(
                headless=headless,
                slow_mo=slow_mo,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/130.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 900},
                locale="en-US",
            )
            if Stealth is not None:
                await Stealth().apply_stealth_async(context)
                log.debug("🥷 Stealth evasions applied to context")

            try:
                cookies = self.session.get("cookies", [])
                if cookies:
                    await context.add_cookies(cookies)
                    log.debug("🍪 Injected %d session cookies", len(cookies))

                page = await context.new_page()

                # Step 1: Navigate home
                log.info("🏠 Navigating to Patreon home...")
                await page.goto("https://www.patreon.com/home", wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_load_state("load", timeout=60000)
                await page.wait_for_timeout(3000)
                log.debug("🏠 Patreon home loaded — url=%s", page.url)

                if "login" in page.url or "signup" in page.url:
                    raise SessionExpiredError("Session expired — redirected to login")

                # Step 2+3: Open post composer via Create button → Post option in dropdown.
                # Direct URL (/posts/create) no longer exists — must drive UI.
                _create_selectors = [
                    '[data-tag="create-content-button"]',
                    'button[aria-label*="Create"]',
                    'button:has-text("Create")',
                ]
                MAX_FLOW_ATTEMPTS = 3
                composer_ready = False
                for attempt in range(1, MAX_FLOW_ATTEMPTS + 1):
                    log.info("🖱️  Opening composer (attempt %d/%d)...", attempt, MAX_FLOW_ATTEMPTS)

                    # Click Create
                    create_clicked = False
                    for sel in _create_selectors:
                        try:
                            btn = page.locator(sel).first
                            await btn.wait_for(state="visible", timeout=5000)
                            await btn.click()
                            await page.wait_for_timeout(1000)
                            log.debug("✅ Create clicked via: %s", sel)
                            create_clicked = True
                            break
                        except Exception:
                            log.debug("⚠️  Create selector miss: %s", sel)

                    if not create_clicked:
                        log.warning("⚠️  Create button not found — reloading home and retrying")
                        await page.goto("https://www.patreon.com/home", wait_until="domcontentloaded", timeout=60000)
                        await page.wait_for_timeout(3000)
                        continue

                    # Click Post option in dropdown
                    post_selectors = [
                        'a:has([data-tag="IconPosts"])',
                        'button:has([data-tag="IconPosts"])',
                        '[role="menuitem"]:has-text("Post")',
                        'a:has-text("Post")',
                    ]
                    post_clicked = False
                    for sel in post_selectors:
                        try:
                            opt = page.locator(sel).first
                            await opt.wait_for(state="visible", timeout=5000)
                            await opt.click()
                            await page.wait_for_timeout(2000)
                            log.debug("✅ Post option clicked via: %s — url=%s", sel, page.url)
                            post_clicked = True
                            break
                        except Exception:
                            log.debug("⚠️  Post option selector miss: %s", sel)

                    if not post_clicked:
                        log.warning("⚠️  Post option not found in dropdown — restarting flow")
                        await page.goto("https://www.patreon.com/home", wait_until="domcontentloaded", timeout=60000)
                        await page.wait_for_timeout(3000)
                        continue

                    # Wait for composer to settle
                    try:
                        await page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        log.debug("⚠️  networkidle not reached within 15s — proceeding")
                    await page.wait_for_timeout(2000)

                    if "login" in page.url or "signup" in page.url:
                        await self._dump_diagnostics(page, "composer_redirected_login")
                        raise SessionExpiredError("Session expired during composer flow")

                    # Verify composer mounted by probing for title textarea
                    try:
                        await page.locator('textarea[placeholder="Title"], input[placeholder="Title"], [aria-label="Title"]').first.wait_for(state="visible", timeout=8000)
                        composer_ready = True
                        log.info("✅ Composer ready — url=%s", page.url)
                        break
                    except Exception:
                        log.warning("⚠️  Composer did not mount title field — restarting flow")
                        await self._dump_diagnostics(page, f"composer_not_ready_attempt{attempt}")
                        await page.goto("https://www.patreon.com/home", wait_until="domcontentloaded", timeout=60000)
                        await page.wait_for_timeout(3000)

                if not composer_ready:
                    raise RuntimeError(f"Failed to reach Patreon post composer after {MAX_FLOW_ATTEMPTS} attempts")

                # Step 4: Fill title (multi-selector fallback — Patreon UI changes frequently)
                log.info("✏️  Filling title field: '%s'", title)
                title_selectors = [
                    'textarea[placeholder="Title"]',
                    'input[placeholder="Title"]',
                    'textarea[name="title"]',
                    'input[name="title"]',
                    '[data-tag="post-title-field"]',
                    '[data-tag="post-title"]',
                    '[aria-label="Title"]',
                    '[aria-label="Post title"]',
                    'textarea[placeholder*="title" i]',
                    'input[placeholder*="title" i]',
                ]
                try:
                    title_field = await self._find_first_visible(page, title_selectors, timeout_ms=20000)
                except Exception:
                    await self._dump_diagnostics(page, "title_not_found")
                    raise
                await title_field.fill(title)
                await page.wait_for_timeout(500)
                log.debug("✅ Title filled")

                # Step 5: Fill body (ProseMirror/Remirror — .fill() doesn't dispatch editor events)
                log.info("✏️  Filling body field (%d chars)...", len(body_text))
                body_selectors = [
                    'div[contenteditable="true"][aria-label="Text input field for post content"]',
                    'div[contenteditable="true"][aria-label*="post content" i]',
                    'div[contenteditable="true"][aria-label*="body" i]',
                    'div[role="textbox"][contenteditable="true"]',
                    'div.ProseMirror[contenteditable="true"]',
                    'div[contenteditable="true"]',
                ]
                try:
                    body_field = await self._find_first_visible(page, body_selectors, timeout_ms=15000)
                except Exception:
                    await self._dump_diagnostics(page, "body_not_found")
                    raise
                await body_field.click()
                await page.keyboard.press("Control+a")
                await page.keyboard.type(body_text)
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

                # Wait for Patreon's autosave to pick up the filled content before leaving
                log.info("⏳ Waiting 5s for autosave to capture content...")
                await page.wait_for_timeout(5000)

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
