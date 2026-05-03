"""In-process Patreon login. Drives the same Playwright context used for publishing
so Cloudflare sees one continuous fingerprint across login + post-creation."""
import logging

log = logging.getLogger(__name__)


_TWOFA_SELECTORS = [
    'input[autocomplete="one-time-code"]',
    'input[name="otp"]',
    'input[name="code"]',
    'input[type="tel"]',
    'input[type="text"][maxlength="6"]',
    'input[inputmode="numeric"]',
]


_CONSENT_SCRIPT = """() => {
    const el = document.getElementById('transcend-consent-manager');
    if (el && el.shadowRoot) {
        const btn = el.shadowRoot.querySelector('button.sc-gTrWKw');
        if (btn) { btn.click(); return true; }
    }
    return false;
}"""


_CLICK_CONTINUE_SCRIPT = """() => {
    for (const b of document.querySelectorAll('button[type="submit"]')) {
        if (b.innerText && b.innerText.includes('Continue')) { b.click(); return true; }
    }
    return false;
}"""


_CLICK_VERIFY_SCRIPT = """() => {
    for (const b of document.querySelectorAll('button[type="submit"], button')) {
        const t = (b.innerText || "").toLowerCase();
        if (t.includes("verify") || t.includes("continue") || t.includes("submit")) {
            b.click(); return true;
        }
    }
    return false;
}"""


def _resolve_2fa_code(totp_secret: str | None, one_shot_code: str | None) -> str | None:
    """TOTP wins so renewals stay autonomous; fall back to single-use code."""
    if totp_secret:
        try:
            import pyotp
        except ImportError:
            log.error("❌ PATREON_TOTP_SECRET set but `pyotp` not installed")
            return None
        return pyotp.TOTP(totp_secret.replace(" ", "")).now()
    return one_shot_code or None


async def _dismiss_consent(page) -> None:
    try:
        clicked = await page.evaluate(_CONSENT_SCRIPT)
        if not clicked:
            accept = page.locator('button:has-text("Accept all"), button:has-text("Accept")').first
            if await accept.count() > 0:
                await accept.click(force=True, timeout=2000)
        await page.wait_for_timeout(1500)
    except Exception as e:
        log.debug("⚠️  Consent dismissal best-effort: %s", e)


async def _submit_2fa(page, code: str) -> None:
    field = None
    for sel in _TWOFA_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                await loc.wait_for(state="visible", timeout=5000)
                field = loc
                break
        except Exception:
            continue
    if field is None:
        raise RuntimeError("Could not locate 2FA input field")
    await field.fill(code)
    await page.wait_for_timeout(500)
    submitted = await page.evaluate(_CLICK_VERIFY_SCRIPT)
    if not submitted:
        try:
            await field.press("Enter")
        except Exception:
            pass


async def login(
    page,
    email: str,
    password: str,
    totp_secret: str | None = None,
    one_shot_code: str | None = None,
) -> None:
    """Drive Patreon login on `page`. Caller already has the stealth context.
    On return, page is on a logged-in Patreon URL. Raises on failure."""
    log.info("🔑 Patreon login — navigating to /login as %s", email)
    try:
        await page.goto("https://www.patreon.com/login", wait_until="load", timeout=30000)
    except Exception as e:
        log.debug("⚠️  /login load timed out, proceeding: %s", e)
    await page.wait_for_timeout(2500)

    await _dismiss_consent(page)

    log.info("🔑 Filling email field")
    email_field = page.locator('input[type="email"]')
    await email_field.wait_for(state="visible", timeout=10000)
    await email_field.fill(email)
    await page.wait_for_timeout(500)

    await page.wait_for_timeout(800)
    clicked = await page.evaluate(_CLICK_CONTINUE_SCRIPT)
    if not clicked:
        try:
            await page.locator('button[type="submit"]:has-text("Continue")').first.click(force=True, timeout=5000)
        except Exception as e:
            log.debug("⚠️  Continue (post-email) click fallback failed: %s", e)

    await page.wait_for_timeout(2000)

    log.info("🔑 Filling password field")
    password_field = page.locator('input[type="password"]')
    await password_field.wait_for(state="visible", timeout=10000)
    await password_field.fill(password)
    await page.wait_for_timeout(500)

    await page.wait_for_timeout(800)
    pwd_clicked = await page.evaluate(_CLICK_CONTINUE_SCRIPT)
    if not pwd_clicked:
        try:
            await page.locator('button[type="submit"]:has-text("Continue")').first.click(force=True, timeout=5000)
        except Exception as e:
            log.debug("⚠️  Continue (post-password) click fallback failed: %s", e)

    await page.wait_for_timeout(3000)

    if any(x in page.url for x in ("2fa", "verify", "two-factor")):
        code = _resolve_2fa_code(totp_secret, one_shot_code)
        if not code:
            raise RuntimeError(
                "2FA required but no code source configured "
                "(set PATREON_TOTP_SECRET or PATREON_2FA_CODE)"
            )
        log.info("🔑 2FA challenge — submitting code")
        await _submit_2fa(page, code)
        await page.wait_for_timeout(3000)

    try:
        await page.wait_for_url("**/*", timeout=5000)
    except Exception:
        pass
    await page.wait_for_timeout(3000)

    if "patreon.com" not in page.url or ("/login" in page.url and "redirect" not in page.url):
        raise RuntimeError(f"Login did not complete — landed on {page.url}")
    log.info("🔑 Login complete — url=%s", page.url)
