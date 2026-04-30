import logging
import re
import random
import unicodedata
from ..config import settings
import base64
import json
import pathlib

log = logging.getLogger(__name__)


_STEALTH_INIT_SCRIPT = r"""
// Hide webdriver
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Spoof plugins (non-empty array, length 3+)
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const arr = [
            { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: '' },
            { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: '' },
            { name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: '' },
            { name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer', description: '' },
        ];
        arr.item = i => arr[i];
        arr.namedItem = n => arr.find(p => p.name === n) || null;
        return arr;
    },
});

// Spoof languages
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

// Hardware concurrency + memory (typical mac values)
try { Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 }); } catch(e) {}
try { Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 }); } catch(e) {}

// chrome runtime stub
window.chrome = window.chrome || {};
window.chrome.runtime = window.chrome.runtime || {};
window.chrome.app = window.chrome.app || { isInstalled: false };
window.chrome.csi = window.chrome.csi || function() { return {}; };
window.chrome.loadTimes = window.chrome.loadTimes || function() { return {}; };

// Permissions.query — return 'prompt' for notifications instead of 'denied' (headless tell)
const origQuery = window.navigator.permissions && window.navigator.permissions.query;
if (origQuery) {
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : origQuery(parameters);
}

// WebGL vendor/renderer spoof — Apple/Apple GPU is plausible for Mac UA
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(p) {
    if (p === 37445) return 'Apple Inc.';
    if (p === 37446) return 'Apple M1';
    return getParameter.apply(this, [p]);
};
if (window.WebGL2RenderingContext) {
    const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
    WebGL2RenderingContext.prototype.getParameter = function(p) {
        if (p === 37445) return 'Apple Inc.';
        if (p === 37446) return 'Apple M1';
        return getParameter2.apply(this, [p]);
    };
}

// Canvas fingerprint: add tiny noise to toDataURL output
const toDataURL = HTMLCanvasElement.prototype.toDataURL;
HTMLCanvasElement.prototype.toDataURL = function(...args) {
    const ctx = this.getContext('2d');
    if (ctx) {
        try {
            const w = Math.min(this.width, 16);
            const h = Math.min(this.height, 16);
            if (w > 0 && h > 0) {
                const img = ctx.getImageData(0, 0, w, h);
                for (let i = 0; i < img.data.length; i += 47) {
                    img.data[i] = (img.data[i] + 1) & 255;
                }
                ctx.putImageData(img, 0, 0);
            }
        } catch (e) {}
    }
    return toDataURL.apply(this, args);
};

// AudioContext fingerprint noise
try {
    const orig = AudioBuffer.prototype.getChannelData;
    AudioBuffer.prototype.getChannelData = function(...a) {
        const data = orig.apply(this, a);
        for (let i = 0; i < data.length; i += 1000) {
            data[i] = data[i] + (Math.random() - 0.5) * 1e-7;
        }
        return data;
    };
} catch (e) {}

// outerWidth/Height === innerWidth/Height is a headless tell
try {
    if (window.outerWidth === 0) {
        Object.defineProperty(window, 'outerWidth', { get: () => window.innerWidth });
        Object.defineProperty(window, 'outerHeight', { get: () => window.innerHeight + 85 });
    }
} catch (e) {}
"""


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

    @staticmethod
    async def _human_jitter(page):
        """Perform small mouse + scroll movements to mimic human idle behavior."""
        try:
            for _ in range(random.randint(2, 4)):
                x = random.randint(50, 1200)
                y = random.randint(50, 700)
                steps = random.randint(8, 20)
                await page.mouse.move(x, y, steps=steps)
                await page.wait_for_timeout(random.randint(120, 380))
            await page.mouse.wheel(0, random.randint(80, 260))
            await page.wait_for_timeout(random.randint(300, 800))
            await page.mouse.wheel(0, -random.randint(40, 160))
            await page.wait_for_timeout(random.randint(200, 500))
        except Exception as e:
            log.debug("⚠️  human jitter failed: %s", e)

    @staticmethod
    async def _dismiss_cookie_banner(page):
        """Click 'Accept'/'Allow all' cookie banner if present. Best-effort, never raises."""
        candidates = [
            'button:has-text("Accept all")',
            'button:has-text("Accept All")',
            'button:has-text("Allow all")',
            'button:has-text("Accept")',
            'button:has-text("I agree")',
            '[data-testid="cookie-banner-accept"]',
            '[aria-label="Accept all cookies"]',
            '#onetrust-accept-btn-handler',
        ]
        for sel in candidates:
            try:
                loc = page.locator(sel).first
                if await loc.is_visible(timeout=1500):
                    await loc.click(timeout=2000)
                    log.debug("🍪 Dismissed cookie banner via %s", sel)
                    await page.wait_for_timeout(500)
                    return
            except Exception:
                continue

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
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process,AutomationControlled",
                    "--disable-site-isolation-trials",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-infobars",
                    "--disable-popup-blocking",
                    "--disable-default-apps",
                    "--disable-extensions-except",
                    "--disable-translate",
                    "--metrics-recording-only",
                    "--no-first-run",
                    "--password-store=basic",
                    "--use-mock-keychain",
                    "--lang=en-US,en",
                ],
            )
            # Randomize viewport within plausible mac ranges → fingerprint variance
            vw = random.choice([1440, 1512, 1536, 1680, 1728])
            vh = random.choice([900, 864, 982, 1050, 1117])
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                viewport={"width": vw, "height": vh},
                screen={"width": vw, "height": vh},
                locale="en-US",
                timezone_id="Europe/Prague",
                permissions=["clipboard-read", "clipboard-write"],
                color_scheme="light",
                device_scale_factor=2,
                is_mobile=False,
                has_touch=False,
                java_script_enabled=True,
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9,cs;q=0.8",
                    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
                    "Sec-Ch-Ua-Mobile": "?0",
                    "Sec-Ch-Ua-Platform": '"macOS"',
                    "Upgrade-Insecure-Requests": "1",
                },
            )
            await context.add_init_script(_STEALTH_INIT_SCRIPT)
            log.debug("🥷 Custom stealth init script injected (viewport=%dx%d)", vw, vh)
            if Stealth is not None:
                await Stealth(
                    navigator_platform_override="MacIntel",
                    chrome_runtime=True,
                ).apply_stealth_async(context)
                log.debug("🥷 playwright-stealth evasions applied")

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
                await page.wait_for_timeout(random.randint(2500, 4500))
                log.debug("🏠 Patreon home loaded — url=%s", page.url)

                if "login" in page.url or "signup" in page.url:
                    raise SessionExpiredError("Session expired — redirected to login")

                # Human-like jitter: small mouse + scroll motions before next nav
                await self._human_jitter(page)
                await self._dismiss_cookie_banner(page)

                # Step 2: Navigate directly to post composer
                log.info("📝 Navigating to post composer...")
                await page.goto("https://www.patreon.com/posts/new", wait_until="domcontentloaded", timeout=60000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    log.debug("⚠️  networkidle not reached within 20s — proceeding")
                await page.wait_for_timeout(random.randint(2000, 4000))
                await self._dismiss_cookie_banner(page)
                await self._human_jitter(page)

                if "login" in page.url or "signup" in page.url:
                    await self._dump_diagnostics(page, "composer_redirected_login")
                    raise SessionExpiredError("Session expired — redirected to login")

                log.debug("📝 Composer URL — %s", page.url)

                # Wait for composer mount with two passes — second pass scrolls
                # and waits longer in case lazy-mount missed first paint.
                composer_ready = False
                for pass_idx in (1, 2):
                    try:
                        timeout_ms = 25000 if pass_idx == 1 else 35000
                        await page.locator(
                            'textarea[placeholder="Title"], input[placeholder="Title"], '
                            '[aria-label="Title"], [data-tag="post-title-field"], '
                            'textarea[name="title"], input[name="title"]'
                        ).first.wait_for(state="visible", timeout=timeout_ms)
                        composer_ready = True
                        log.info("✅ Composer ready (pass %d) — url=%s", pass_idx, page.url)
                        break
                    except Exception:
                        log.warning("⚠️  Composer not ready on pass %d — nudging page", pass_idx)
                        try:
                            await page.mouse.wheel(0, 200)
                            await page.wait_for_timeout(800)
                            await page.mouse.wheel(0, -200)
                            await page.wait_for_timeout(1500)
                        except Exception:
                            pass

                if not composer_ready:
                    await self._dump_diagnostics(page, "composer_not_ready")
                    raise RuntimeError("Post composer did not mount title field")

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
                await page.evaluate("(text) => navigator.clipboard.writeText(text)", body_text)
                await page.keyboard.press("Control+a")
                await page.keyboard.press("Control+v")
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

                # Wait long enough for Patreon's autosave to flush title, body and
                # uploaded image before we navigate away. Image upload in particular
                # finishes async — too short a wait drops the picture from the draft.
                log.info("⏳ Waiting 25s for autosave to capture title/body/image...")
                await page.wait_for_timeout(25000)

                # Capture composer/draft URL before navigating away.
                # Patreon composer URL contains the post id (e.g. /posts/<id>/edit or ?postId=<id>).
                draft_url = page.url
                post_id = None
                m = re.search(r"/posts/(\d+)", draft_url) or re.search(r"[?&]postId=(\d+)", draft_url)
                if m:
                    post_id = m.group(1)
                    draft_url = f"https://www.patreon.com/posts/{post_id}/edit"
                log.info("🔗 Captured draft URL — %s (post_id=%s)", draft_url, post_id or "n/a")

                # Navigate away to trigger Patreon's auto-save of the draft
                log.info("💾 Navigating away to trigger draft save...")
                await page.goto("https://www.patreon.com", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)
                log.info("💾 Draft save triggered — url=%s", page.url)

                # Persist updated cookies
                try:
                    updated_cookies = await context.cookies()
                    self.session["cookies"] = updated_cookies
                    log.debug("🍪 Session cookies refreshed — %d cookies stored", len(updated_cookies))
                except Exception as e:
                    log.debug("⚠️  Failed to refresh session cookies: %s", e)

                result = {"success": True, "url": page.url, "draft_url": draft_url, "post_id": post_id}
                log.info("🎉 Patreon publish complete — browser will close and restart for next post")
                return result

            except Exception:
                log.exception("💥 Patreon publish failed during browser automation")
                raise
            finally:
                await context.close()
                await browser.close()
                log.debug("🌐 Browser closed")
