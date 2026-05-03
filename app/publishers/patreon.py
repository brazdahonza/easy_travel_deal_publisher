import asyncio
import base64
import json
import logging
import pathlib
import random
import re
import unicodedata

from ..config import settings
from .. import session_store
from . import patreon_login

log = logging.getLogger(__name__)


# Rotating browser profiles. Each entry is internally consistent — UA matches
# Sec-CH-UA brand list, navigator.platform and hardwareConcurrency match the OS.
_BROWSER_PROFILES = [
    {
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "platform": '"macOS"',
        "navigator_platform": "MacIntel",
        "viewports": [(1440, 900), (1512, 982), (1680, 1050), (1728, 1117)],
        "scale": 2,
        "webgl_vendor": "Apple Inc.",
        "webgl_renderer": "Apple M1",
        "hw_concurrency": 8,
    },
    {
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Google Chrome";v="130", "Chromium";v="130", "Not_A Brand";v="24"',
        "platform": '"macOS"',
        "navigator_platform": "MacIntel",
        "viewports": [(1440, 900), (1536, 960), (1680, 1050)],
        "scale": 2,
        "webgl_vendor": "Apple Inc.",
        "webgl_renderer": "Apple M2",
        "hw_concurrency": 8,
    },
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "platform": '"Windows"',
        "navigator_platform": "Win32",
        "viewports": [(1366, 768), (1536, 864), (1600, 900), (1920, 1080)],
        "scale": 1,
        "webgl_vendor": "Google Inc. (NVIDIA)",
        "webgl_renderer": "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "hw_concurrency": 12,
    },
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Google Chrome";v="130", "Chromium";v="130", "Not_A Brand";v="24"',
        "platform": '"Windows"',
        "navigator_platform": "Win32",
        "viewports": [(1366, 768), (1920, 1080)],
        "scale": 1,
        "webgl_vendor": "Google Inc. (Intel)",
        "webgl_renderer": "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "hw_concurrency": 8,
    },
]


# Note: navigator.webdriver is removed by --disable-blink-features=AutomationControlled.
# Re-defining it via Object.defineProperty (as some stealth scripts do) is itself
# detectable, so we no longer touch it here.
_STEALTH_INIT_SCRIPT = r"""
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

Object.defineProperty(navigator, 'languages', { get: () => ['cs-CZ', 'cs', 'en'] });

const __hw = window.__HW_CONCURRENCY__ || 8;
try { Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => __hw }); } catch(e) {}
try { Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 }); } catch(e) {}

window.chrome = window.chrome || {};
window.chrome.runtime = window.chrome.runtime || {};
window.chrome.app = window.chrome.app || { isInstalled: false };
window.chrome.csi = window.chrome.csi || function() { return {}; };
window.chrome.loadTimes = window.chrome.loadTimes || function() { return {}; };

const origQuery = window.navigator.permissions && window.navigator.permissions.query;
if (origQuery) {
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : origQuery(parameters);
}

const __vendor = window.__WEBGL_VENDOR__ || 'Apple Inc.';
const __renderer = window.__WEBGL_RENDERER__ || 'Apple M1';
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(p) {
    if (p === 37445) return __vendor;
    if (p === 37446) return __renderer;
    return getParameter.apply(this, [p]);
};
if (window.WebGL2RenderingContext) {
    const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
    WebGL2RenderingContext.prototype.getParameter = function(p) {
        if (p === 37445) return __vendor;
        if (p === 37446) return __renderer;
        return getParameter2.apply(this, [p]);
    };
}

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

try {
    if (window.outerWidth === 0) {
        Object.defineProperty(window, 'outerWidth', { get: () => window.innerWidth });
        Object.defineProperty(window, 'outerHeight', { get: () => window.innerHeight + 85 });
    }
} catch (e) {}
"""


_CF_TITLE_MARKERS = ("just a moment", "attention required", "cloudflare")


class SessionExpiredError(Exception):
    pass


class CloudflareChallengeError(Exception):
    """Page is stuck on a Cloudflare interstitial — session likely needs renewal."""
    pass


class PatreonPublisher:
    def __init__(self):
        self.session = session_store.load()
        if self.session is None:
            log.warning("⚠️  No stored Patreon session — login flow will run on first publish")

    @staticmethod
    def _normalize(text: str) -> str:
        nfkd = unicodedata.normalize("NFKD", text)
        return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()

    def _get_image_path(self, destination: str) -> str | None:
        app_dir = pathlib.Path(__file__).parent.parent.parent
        patreon_dir = app_dir / "assets" / "patreon"
        dest_norm = self._normalize(destination)

        candidates = list(patreon_dir.glob("*.png"))

        for img_path in candidates:
            variants = [v.strip() for v in img_path.stem.split(" - ")]
            if any(self._normalize(v) == dest_norm for v in variants):
                log.info("🖼️  Image found for destination '%s': %s", destination, img_path)
                return str(img_path)

        for img_path in candidates:
            variants = [v.strip() for v in img_path.stem.split(" - ")]
            if any(dest_norm in self._normalize(v) or self._normalize(v) in dest_norm for v in variants):
                log.info("🖼️  Fuzzy image match for destination '%s': %s", destination, img_path)
                return str(img_path)

        log.warning("🖼️  No image found for destination '%s' — post will have no image", destination)
        return None

    @staticmethod
    async def _find_first_visible(page, selectors: list, timeout_ms: int = 10000):
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

    async def _check_cloudflare(self, page, tag: str) -> None:
        """Raise CloudflareChallengeError if the page title carries CF markers."""
        try:
            title = (await page.title()) or ""
        except Exception:
            return
        if any(m in title.lower() for m in _CF_TITLE_MARKERS):
            await self._dump_diagnostics(page, f"cf_{tag}")
            raise CloudflareChallengeError(f"Cloudflare challenge ({tag}) — title={title!r}")

    async def _is_session_valid(self, context) -> bool:
        """Cheap auth probe via /api/current_user. Avoids a wasted UI round-trip."""
        try:
            resp = await context.request.get(
                "https://www.patreon.com/api/current_user",
                headers={"Accept": "application/vnd.api+json"},
                timeout=15000,
            )
            if resp.status != 200:
                log.info("🔐 Session probe — HTTP %s, treating as invalid", resp.status)
                return False
            body = await resp.json()
            ok = bool((body.get("data") or {}).get("id"))
            log.info("🔐 Session probe — %s", "valid" if ok else "anonymous")
            return ok
        except Exception as e:
            log.debug("⚠️  Session probe error (treating as invalid): %s", e)
            return False

    async def _persist_cookies(self, context) -> None:
        try:
            cookies = await context.cookies()
            email = (self.session or {}).get("email")
            session_store.save(cookies, email=email)
            self.session = {"cookies": cookies, "email": email}
        except Exception as e:
            log.debug("⚠️  Failed to persist cookies: %s", e)

    async def publish(self, title: str, body_text: str, destination: str | None = None) -> dict:
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

            profile = random.choice(_BROWSER_PROFILES)
            vw, vh = random.choice(profile["viewports"])
            launch_args = [
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
                "--lang=cs-CZ,cs",
            ]

            log.debug(
                "🌐 Launching browser — profile=%s viewport=%dx%d headless=%s slow_mo=%dms",
                profile["platform"], vw, vh, headless, slow_mo,
            )

            browser = None
            for channel in ("chrome", None):
                try:
                    kwargs = {"headless": headless, "slow_mo": slow_mo, "args": launch_args}
                    if channel:
                        kwargs["channel"] = channel
                    browser = await p.chromium.launch(**kwargs)
                    log.debug("🌐 Launched with channel=%s", channel or "chromium")
                    break
                except Exception as exc:
                    log.debug("⚠️  Launch with channel=%s failed: %s", channel or "chromium", exc)
            if browser is None:
                raise RuntimeError("Could not launch any Chromium-based browser")

            context = await browser.new_context(
                user_agent=profile["ua"],
                viewport={"width": vw, "height": vh},
                # Real screens are taller than the viewport because of OS chrome.
                screen={"width": vw, "height": vh + 85},
                locale="cs-CZ",
                timezone_id="Europe/Prague",
                permissions=["clipboard-read", "clipboard-write"],
                color_scheme="light",
                device_scale_factor=profile["scale"],
                is_mobile=False,
                has_touch=False,
                java_script_enabled=True,
                extra_http_headers={
                    "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
                    "Sec-Ch-Ua": profile["sec_ch_ua"],
                    "Sec-Ch-Ua-Mobile": "?0",
                    "Sec-Ch-Ua-Platform": profile["platform"],
                    "Upgrade-Insecure-Requests": "1",
                },
            )
            await context.add_init_script(
                f"window.__WEBGL_VENDOR__ = {json.dumps(profile['webgl_vendor'])};"
                f"window.__WEBGL_RENDERER__ = {json.dumps(profile['webgl_renderer'])};"
                f"window.__HW_CONCURRENCY__ = {profile['hw_concurrency']};"
            )
            await context.add_init_script(_STEALTH_INIT_SCRIPT)
            log.debug(
                "🥷 Stealth injected — UA=%s WebGL=%s/%s platform=%s hw=%d",
                profile["ua"][:60], profile["webgl_vendor"], profile["webgl_renderer"],
                profile["navigator_platform"], profile["hw_concurrency"],
            )
            if Stealth is not None:
                await Stealth(
                    navigator_platform_override=profile["navigator_platform"],
                    chrome_runtime=True,
                ).apply_stealth_async(context)
                log.debug("🥷 playwright-stealth evasions applied (platform=%s)", profile["navigator_platform"])

            page = None
            try:
                if self.session and self.session.get("cookies"):
                    await context.add_cookies(self.session["cookies"])
                    log.debug("🍪 Injected %d session cookies", len(self.session["cookies"]))

                page = await context.new_page()
                # Auto-accept any beforeunload/discard-draft dialog so we can navigate
                # away cleanly after the autosave wait.
                page.on("dialog", lambda d: asyncio.create_task(d.accept()))

                # ── Step 1: validate session ─────────────────────────────
                session_ok = await self._is_session_valid(context)

                # ── Step 2: login if needed ──────────────────────────────
                if not session_ok:
                    if not (settings.PATREON_EMAIL and settings.PATREON_PASSWORD):
                        raise SessionExpiredError(
                            "Stored session invalid and no PATREON_EMAIL/PATREON_PASSWORD for login"
                        )
                    log.info("🔑 Session invalid — running in-process login")
                    await patreon_login.login(
                        page,
                        email=settings.PATREON_EMAIL,
                        password=settings.PATREON_PASSWORD,
                        totp_secret=settings.PATREON_TOTP_SECRET,
                        one_shot_code=settings.PATREON_2FA_CODE,
                    )
                    if not await self._is_session_valid(context):
                        raise SessionExpiredError("Login completed but session probe still fails")
                    await self._persist_cookies(context)
                    self.session = self.session or {}
                    self.session["email"] = settings.PATREON_EMAIL

                # ── Step 3: open composer + fill ─────────────────────────
                # Warm up on patreon.com root before authenticated nav. Real
                # users typically land here first.
                log.info("🌍 Warming up on patreon.com root...")
                try:
                    await page.goto("https://www.patreon.com/", wait_until="domcontentloaded", timeout=60000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    await page.wait_for_timeout(random.randint(2500, 5000))
                    await self._dismiss_cookie_banner(page)
                    await self._human_jitter(page)
                except Exception as e:
                    log.debug("⚠️  Root warmup failed (non-fatal): %s", e)

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
                    raise SessionExpiredError("Composer redirected to login")

                composer_ready = False
                composer_mount_selector = (
                    'textarea[placeholder="Title"], input[placeholder="Title"], '
                    '[aria-label="Title"], [data-tag="post-title-field"], '
                    'textarea[name="title"], input[name="title"], '
                    'textarea[class*="titleTextArea"], '
                    'textarea[aria-multiline="true"][placeholder="Title"], '
                    '[class*="titleTextAreaWrapper"] textarea'
                )
                for pass_idx in (1, 2):
                    try:
                        timeout_ms = 25000 if pass_idx == 1 else 35000
                        await page.locator(composer_mount_selector).first.wait_for(state="visible", timeout=timeout_ms)
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
                    await self._check_cloudflare(page, "composer_mount")
                    raise RuntimeError("Post composer did not mount title field")

                # Title
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
                    'textarea[class*="titleTextArea"]',
                    'textarea[aria-multiline="true"][placeholder="Title"]',
                    'textarea[aria-multiline="true"][aria-label="Title"]',
                    '[class*="titleTextAreaWrapper"] textarea',
                    '[class*="tokensPostPage"] textarea[placeholder="Title"]',
                    'textarea[placeholder*="title" i]',
                    'input[placeholder*="title" i]',
                ]
                try:
                    title_field = await self._find_first_visible(page, title_selectors, timeout_ms=20000)
                except Exception:
                    await self._dump_diagnostics(page, "title_not_found")
                    await self._check_cloudflare(page, "title_fill")
                    raise
                await title_field.fill(title)
                await page.wait_for_timeout(500)
                log.debug("✅ Title filled")

                # Body — use type() so ProseMirror's input handlers fire naturally.
                # Clipboard-paste fails silently on headless Linux (no DBus backend).
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
                    await self._check_cloudflare(page, "body_fill")
                    raise
                await body_field.click()
                await body_field.type(body_text, delay=8)
                await page.wait_for_timeout(500)
                log.debug("✅ Body filled")

                # Image upload. The composer's hidden file inputs (#photosInput,
                # #mainMedia, ...) only mount AFTER the user clicks the toolbar
                # "Image" button — the dropzone div is rendered conditionally.
                # Grabbing input[type=file] before that opens hits some unrelated
                # input (avatar, etc.) and never attaches the picture to the post.
                #
                # Flow:
                #   1. Click toolbar button[data-tag=IconPhoto] → dropzone mounts.
                #   2. set_input_files on #photosInput (image-only). Falls back to
                #      #mainMedia or finally to clicking Browse + file chooser.
                if destination:
                    image_path = self._get_image_path(destination)
                    if image_path:
                        log.info("🖼️  Uploading image for '%s'...", destination)
                        uploaded = False
                        try:
                            image_btn = page.locator('button:has([data-tag="IconPhoto"])').first
                            await image_btn.wait_for(state="visible", timeout=8000)
                            await image_btn.click()
                            log.debug("🖼️  Image toolbar button clicked — waiting for dropzone")

                            for sel in ("input#photosInput", "input#mainMedia", "input[type='file']"):
                                try:
                                    inp = page.locator(sel).first
                                    await inp.wait_for(state="attached", timeout=4000)
                                    await inp.set_input_files(image_path)
                                    await page.wait_for_timeout(2500)
                                    uploaded = True
                                    log.info("✅ Image uploaded via %s", sel)
                                    break
                                except Exception as e:
                                    log.debug("⚠️  %s miss: %s", sel, e)
                        except Exception as e:
                            log.debug("⚠️  Image button / hidden-input path failed: %s", e)

                        if not uploaded:
                            try:
                                browse_btn = page.locator('button:has-text("Browse")').last
                                await browse_btn.wait_for(state="visible", timeout=5000)
                                async with page.expect_file_chooser() as fc_info:
                                    await browse_btn.click()
                                file_chooser = await fc_info.value
                                await file_chooser.set_files(image_path)
                                await page.wait_for_timeout(2500)
                                uploaded = True
                                log.info("✅ Image uploaded via Browse picker")
                            except Exception as e:
                                log.warning("⚠️  Image upload failed — continuing without image: %s", e)
                    else:
                        log.info("🖼️  No image available for '%s' — skipping upload", destination)

                log.info("✅ Patreon draft prepared — title='%s'", title)

                # Wait for Patreon's autosave to flush title/body/image before
                # navigating away. Image upload finishes async — short wait drops it.
                log.info("⏳ Waiting 25s for autosave to capture title/body/image...")
                await page.wait_for_timeout(25000)

                draft_url = page.url
                post_id = None
                m = re.search(r"/posts/(\d+)", draft_url) or re.search(r"[?&]postId=(\d+)", draft_url)
                if m:
                    post_id = m.group(1)
                    draft_url = f"https://www.patreon.com/posts/{post_id}/edit"
                log.info("🔗 Captured draft URL — %s (post_id=%s)", draft_url, post_id or "n/a")

                # Trigger server-side draft save by navigating away.
                log.info("💾 Navigating away to trigger draft save...")
                await page.goto("https://www.patreon.com", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)

                await self._persist_cookies(context)

                result = {"success": True, "url": page.url, "draft_url": draft_url, "post_id": post_id}
                log.info("🎉 Patreon publish complete")
                return result

            except Exception:
                fail_url = "<unknown>"
                fail_title = "<unknown>"
                if page is not None:
                    try:
                        fail_url = page.url
                        fail_title = await page.title()
                    except Exception:
                        pass
                log.error("🛑 PATREON FAIL URL: %s", fail_url)
                log.error("🛑 PATREON FAIL PAGE TITLE: %s", fail_title)
                log.exception("💥 Patreon publish failed during browser automation — url=%s title=%s", fail_url, fail_title)
                raise
            finally:
                await context.close()
                await browser.close()
                log.debug("🌐 Browser closed")
