"""
Interactive Patreon session setup script.

Usage:
  python -m app.session.setup_session           # automated login
  python -m app.session.setup_session --manual  # open browser, log in yourself
"""
import asyncio
import base64
import json
import sys
import getpass
from pathlib import Path


def _print_result(encoded: str, email: str, cookies: list) -> None:
    print("\n" + "=" * 60)
    print("Session setup complete!")
    print("=" * 60)
    print("\nCopy the following base64 string to your .env file:")
    print(f"\nPATREON_SESSION={encoded}\n")
    print("=" * 60)
    print(f"\nOr run:\necho 'PATREON_SESSION={encoded}' >> .env\n")
    print("=" * 60)
    print("\nAlternatively, you can send the following JSON payload via Postman to the API:")
    print("POST /session/patreon")
    print("Content-Type: application/json\n")
    payload = {
        "cookies": cookies,
        "email": email or ""
    }
    print(json.dumps(payload, indent=2))
    print("\n" + "=" * 60)


async def setup_patreon_session_manual():
    """Open browser, wait for user to log in manually, then capture cookies."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("ERROR: Playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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
            session_data = {
                "cookies": cookies,
                "email": email,
                "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
            }
            encoded = base64.b64encode(json.dumps(session_data).encode()).decode()
            _print_result(encoded, email, cookies)

        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
        finally:
            await context.close()
            await browser.close()


async def setup_patreon_session():
    """Automated login flow (email + password + 2FA wait)."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("ERROR: Playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    from ..config import settings

    email = settings.PATREON_EMAIL or input("Enter Patreon email: ").strip()
    password = settings.PATREON_PASSWORD or getpass.getpass("Enter Patreon password: ")

    if not email or not password:
        print("ERROR: Email and password are required")
        sys.exit(1)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            print("Navigating to Patreon login...")
            try:
                await page.goto("https://www.patreon.com/login", wait_until="load", timeout=30000)
            except Exception as e:
                print(f"Network idle timed out, proceeding: {e}")
            await page.wait_for_timeout(3000)

            # Accept cookies (Shadow DOM)
            try:
                has_consent = await page.evaluate('''() => {
                    const el = document.getElementById('transcend-consent-manager');
                    if (el && el.shadowRoot) {
                        const btn = el.shadowRoot.querySelector('button.sc-gTrWKw');
                        if (btn) { btn.click(); return true; }
                    }
                    return false;
                }''')
                if not has_consent:
                    accept = page.locator('button:has-text("Accept all"), button:has-text("Accept")').first
                    if await accept.count() > 0:
                        await accept.click(force=True)
                await page.wait_for_timeout(2000)
            except Exception as e:
                print(f"Cookie handling: {e}")

            await page.wait_for_timeout(2000)

            print(f"Entering email: {email}")
            email_field = page.locator('input[type="email"]')
            await email_field.wait_for(state="visible", timeout=10000)
            await email_field.fill(email)
            await page.wait_for_timeout(500)

            print("Clicking Continue...")
            await page.wait_for_timeout(1000)
            clicked = await page.evaluate('''() => {
                for (const b of document.querySelectorAll('button[type="submit"]')) {
                    if (b.innerText && b.innerText.includes('Continue')) { b.click(); return true; }
                }
                return false;
            }''')
            if not clicked:
                try:
                    await page.locator('button[type="submit"]:has-text("Continue")').first.click(force=True)
                except Exception as e:
                    print(f"Continue click failed: {e}")

            await page.wait_for_timeout(2000)

            print("Entering password...")
            password_field = page.locator('input[type="password"]')
            await password_field.wait_for(state="visible", timeout=10000)
            await password_field.fill(password)
            await page.wait_for_timeout(500)

            await page.wait_for_timeout(1000)
            pwd_clicked = await page.evaluate('''() => {
                for (const b of document.querySelectorAll('button[type="submit"]')) {
                    if (b.innerText && b.innerText.includes('Continue')) { b.click(); return true; }
                }
                return false;
            }''')
            if not pwd_clicked:
                try:
                    await page.locator('button[type="submit"]:has-text("Continue")').first.click(force=True)
                except Exception as e:
                    print(f"Password submit click failed: {e}")

            await page.wait_for_timeout(3000)

            current_url = page.url
            if "2fa" in current_url or "verify" in current_url or "two-factor" in current_url:
                print("2FA required. Complete verification in the browser. Waiting up to 2 minutes...")
                for i in range(120):
                    await page.wait_for_timeout(1000)
                    current_url = page.url
                    if not any(x in current_url for x in ("2fa", "verify", "two-factor")):
                        print("2FA completed!")
                        break
                    if i % 10 == 0 and i > 0:
                        print(f"  Still waiting... {i}s")

            try:
                await page.wait_for_url("**/*", timeout=5000)
            except Exception:
                pass

            await page.wait_for_timeout(5000)
            current_url = page.url
            if "patreon.com" not in current_url or ("/login" in current_url and "redirect" not in current_url):
                print("WARNING: May not have logged in successfully")
            else:
                print(f"Logged in (URL: {current_url})")

            await page.wait_for_timeout(5000)
            cookies = await context.cookies()
            print(f"Found {len(cookies)} cookies")

            session_data = {
                "cookies": cookies,
                "email": email,
                "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
            }
            encoded = base64.b64encode(json.dumps(session_data).encode()).decode()
            _print_result(encoded, email, cookies)

        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
        finally:
            await context.close()
            await browser.close()


def main():
    manual = "--manual" in sys.argv
    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║     Patreon Session Setup for easy_travel_deal_publisher     ║
    ╚══════════════════════════════════════════════════════════════╝
    """)
    if manual:
        print("Mode: manual (you log in yourself)\n")
        asyncio.run(setup_patreon_session_manual())
    else:
        print("Mode: automated (use --manual to log in yourself)\n")
        asyncio.run(setup_patreon_session())


if __name__ == "__main__":
    main()
