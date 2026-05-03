"""Patreon session setup helpers.

Two flavors of login:

* `perform_patreon_login(email, password, headless=True, ...)` — automated, importable
  from the FastAPI publisher to refresh expired cookies on demand.
* `perform_patreon_login_manual()` — opens a visible browser and waits for the
  operator to complete login (handy when 2FA / captcha trips the headless flow).

Run from the CLI:

```
python -m app.session.setup_session            # automated
python -m app.session.setup_session --manual   # manual
```

The CLI prints a base64 blob (for `PATREON_SESSION` in `.env`) and a JSON body
suitable for `POST /session/patreon`.
"""
import asyncio
import base64
import getpass
import json
import logging
import sys
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _print_result(encoded: str, email: str, cookies: list) -> None:
    print("\n" + "=" * 60)
    print("Session setup complete!")
    print("=" * 60)
    print("\nOption A — paste into .env:")
    print(f"\nPATREON_SESSION={encoded}\n")
    print("Option B — POST to a running service (recommended for production):")
    print("POST /session/patreon")
    print("Content-Type: application/json")
    print("X-API-Key: <INGEST_API_KEY>\n")
    payload = {"cookies": cookies, "email": email or ""}
    print(json.dumps(payload, indent=2))
    print("\n" + "=" * 60)


async def perform_patreon_login(
    email: str,
    password: str,
    headless: bool = True,
    two_fa_timeout_s: int = 120,
) -> dict:
    """Drive Patreon's email/password login with Playwright and return captured cookies.

    Returns a dict shaped like the in-memory session blob:

        {"cookies": [...], "email": email, "timestamp": <ISO8601>}

    Raises `RuntimeError` on any unrecoverable failure (Playwright missing,
    bad credentials, 2FA timeout, login-page redirect loop).
    """
    if not email or not password:
        raise RuntimeError("Email and password are required for Patreon login")

    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise RuntimeError(f"Playwright not installed: {e}") from e

    log.info("🔑 Starting Patreon login flow — email=%s headless=%s", email, headless)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = await context.new_page()

        try:
            log.info("🌍 Navigating to Patreon login page...")
            try:
                await page.goto("https://www.patreon.com/login", wait_until="load", timeout=30000)
            except Exception as e:
                log.debug("⚠️  Initial nav timed out, proceeding: %s", e)
            await page.wait_for_timeout(3000)

            # Best-effort cookie-consent dismissal (Shadow DOM banner)
            try:
                consented = await page.evaluate(
                    """() => {
                        const el = document.getElementById('transcend-consent-manager');
                        if (el && el.shadowRoot) {
                            const btn = el.shadowRoot.querySelector('button.sc-gTrWKw');
                            if (btn) { btn.click(); return true; }
                        }
                        return false;
                    }"""
                )
                if not consented:
                    accept = page.locator(
                        'button:has-text("Accept all"), button:has-text("Accept")'
                    ).first
                    if await accept.count() > 0:
                        await accept.click(force=True)
                await page.wait_for_timeout(2000)
            except Exception as e:
                log.debug("⚠️  Cookie banner handling: %s", e)

            await page.wait_for_timeout(2000)

            log.info("✏️  Filling email")
            email_field = page.locator('input[type="email"]')
            await email_field.wait_for(state="visible", timeout=10000)
            await email_field.fill(email)
            await page.wait_for_timeout(500)

            log.info("➡️  Submitting email")
            await page.wait_for_timeout(1000)
            clicked = await page.evaluate(
                """() => {
                    for (const b of document.querySelectorAll('button[type=\"submit\"]')) {
                        if (b.innerText && b.innerText.includes('Continue')) { b.click(); return true; }
                    }
                    return false;
                }"""
            )
            if not clicked:
                try:
                    await page.locator(
                        'button[type="submit"]:has-text("Continue")'
                    ).first.click(force=True)
                except Exception as e:
                    log.debug("⚠️  Continue click failed: %s", e)

            await page.wait_for_timeout(2000)

            log.info("🔑 Filling password")
            password_field = page.locator('input[type="password"]')
            await password_field.wait_for(state="visible", timeout=10000)
            await password_field.fill(password)
            await page.wait_for_timeout(500)

            log.info("➡️  Submitting password")
            await page.wait_for_timeout(1000)
            pwd_clicked = await page.evaluate(
                """() => {
                    for (const b of document.querySelectorAll('button[type=\"submit\"]')) {
                        if (b.innerText && b.innerText.includes('Continue')) { b.click(); return true; }
                    }
                    return false;
                }"""
            )
            if not pwd_clicked:
                try:
                    await page.locator(
                        'button[type="submit"]:has-text("Continue")'
                    ).first.click(force=True)
                except Exception as e:
                    log.debug("⚠️  Password submit click failed: %s", e)

            await page.wait_for_timeout(3000)

            current_url = page.url
            if any(x in current_url for x in ("2fa", "verify", "two-factor")):
                log.warning("🔐 2FA required — waiting up to %ds for completion", two_fa_timeout_s)
                completed = False
                for i in range(two_fa_timeout_s):
                    await page.wait_for_timeout(1000)
                    current_url = page.url
                    if not any(x in current_url for x in ("2fa", "verify", "two-factor")):
                        log.info("✅ 2FA completed")
                        completed = True
                        break
                    if i and i % 10 == 0:
                        log.info("⏳ Still waiting on 2FA — %ds elapsed", i)
                if not completed:
                    raise RuntimeError("two_factor_timeout")

            try:
                await page.wait_for_url("**/*", timeout=5000)
            except Exception:
                pass

            await page.wait_for_timeout(5000)
            current_url = page.url
            if "patreon.com" not in current_url or (
                "/login" in current_url and "redirect" not in current_url
            ):
                raise RuntimeError(f"login_failed: still on {current_url}")

            log.info("✅ Logged in — url=%s", current_url)
            await page.wait_for_timeout(5000)
            cookies = await context.cookies()
            log.info("🍪 Captured %d cookies", len(cookies))

            return {
                "cookies": cookies,
                "email": email,
                "timestamp": _utcnow_iso(),
            }
        finally:
            await context.close()
            await browser.close()


async def perform_patreon_login_manual() -> dict:
    """Open a visible browser, wait for the operator to complete login, capture cookies."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise RuntimeError(f"Playwright not installed: {e}") from e

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = await context.new_page()
        try:
            print("Opening Patreon login page...")
            await page.goto("https://www.patreon.com/login", wait_until="load", timeout=30000)
            print("\nLog in to Patreon in the browser window (2FA, passkey, whatever you need).")
            print("When you are fully logged in, come back here and press Enter.")
            input("Press Enter when logged in > ")
            print("Capturing cookies...")
            await page.wait_for_timeout(2000)
            cookies = await context.cookies()
            print(f"Found {len(cookies)} cookies")
            email = input("Enter your Patreon email (optional, for reference): ").strip()
            return {
                "cookies": cookies,
                "email": email,
                "timestamp": _utcnow_iso(),
            }
        finally:
            await context.close()
            await browser.close()


def _cli_automated() -> None:
    from ..config import settings

    email = settings.PATREON_EMAIL or input("Enter Patreon email: ").strip()
    password = settings.PATREON_PASSWORD or getpass.getpass("Enter Patreon password: ")
    if not email or not password:
        print("ERROR: Email and password are required")
        sys.exit(1)

    try:
        result = asyncio.run(perform_patreon_login(email, password, headless=False))
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    payload = json.dumps(
        {"cookies": result["cookies"], "email": result["email"], "timestamp": result["timestamp"]}
    ).encode()
    encoded = base64.b64encode(payload).decode()
    _print_result(encoded, result["email"], result["cookies"])


def _cli_manual() -> None:
    try:
        result = asyncio.run(perform_patreon_login_manual())
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    payload = json.dumps(
        {"cookies": result["cookies"], "email": result["email"], "timestamp": result["timestamp"]}
    ).encode()
    encoded = base64.b64encode(payload).decode()
    _print_result(encoded, result["email"], result["cookies"])


def main() -> None:
    manual = "--manual" in sys.argv
    print(
        """
    ╔══════════════════════════════════════════════════════════════╗
    ║     Patreon Session Setup for easy_travel_deal_publisher     ║
    ╚══════════════════════════════════════════════════════════════╝
    """
    )
    if manual:
        print("Mode: manual (you log in yourself)\n")
        _cli_manual()
    else:
        print("Mode: automated (use --manual to log in yourself)\n")
        _cli_automated()


if __name__ == "__main__":
    main()
