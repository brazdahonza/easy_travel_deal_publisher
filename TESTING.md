# Testing Guide: easy_travel_deal_publisher

This guide covers how to test the service locally — from unit tests to manual endpoint testing.

For the REST API contract see [API.md](API.md).

## Quick Start: Unit Tests

```bash
pytest -q
```

Tests mock Playwright and the login flow; they require neither a live Patreon session nor a browser.

## Local Development Setup (without Docker)

### 1. Install dependencies

```bash
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
playwright install chromium
```

### 2. Set up environment

```bash
cp .env.example .env
```

Minimum values for end-to-end Patreon publishing:

```env
INGEST_API_KEY=test-key-12345
PATREON_EMAIL=your-email@example.com
PATREON_PASSWORD=your-password
PATREON_HEADLESS=true
```

`PATREON_SESSION` is optional. If unset, the service runs the Playwright login on the first `/publish/patreon` call.

### 3. Run the app

```bash
uvicorn app.main:app --reload
```

Server is live at `http://localhost:8000`.

## Manual Endpoint Testing

### Health

```bash
curl http://localhost:8000/health
# {"status":"ok","cookies_present":false,"cookies_count":0,"needs_refresh":false,"patreon_credentials":true}
```

### Session status

```bash
curl -H "X-API-Key: test-key-12345" http://localhost:8000/session/patreon/status
# {"cookies_present":false,"cookies_count":0,"email":null,"stored_at":null,"needs_refresh":false,"last_error":null}
```

### Inject a pre-captured cookie blob

```bash
python -m app.session.setup_session --manual
# Copy the printed JSON payload into the body below.

curl -X POST http://localhost:8000/session/patreon \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-key-12345" \
  -d '{"cookies": [...], "email": "you@example.com"}'
# {"status":"ok","cookies_count":27,"email":"you@example.com"}
```

### Create a Patreon draft

```bash
curl -X POST http://localhost:8000/publish/patreon \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-key-12345" \
  -d '{
    "title": "Akce: Bangkok 8 500 Kč",
    "body": "Letenka z Prahy 15.6.–22.6. Sleva 39 % oproti mediánu.",
    "destination": "Bangkok"
  }'
# {"status":"ok","draft_url":"https://www.patreon.com/posts/123456789/edit","post_id":"123456789"}
```

If no in-memory session exists, the service auto-launches Playwright, logs in with `PATREON_EMAIL` / `PATREON_PASSWORD`, then creates the draft. If Patreon redirects to the login page mid-flow, the service runs the login once more and retries.

### Missing API key

```bash
curl -X POST http://localhost:8000/publish/patreon \
  -H "Content-Type: application/json" \
  -d '{"title":"x","body":"y"}'
# 403: {"detail":"invalid api key"}
```

### Session can't be obtained (e.g. wrong creds, 2FA timeout)

```bash
# Clear creds and any session.
unset PATREON_EMAIL PATREON_PASSWORD PATREON_SESSION
uvicorn app.main:app --reload &

curl -X POST http://localhost:8000/publish/patreon \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-key-12345" \
  -d '{"title":"t","body":"b"}'
# 401: {"detail":{"error":"session_unavailable","reason":"..."}}

curl -H "X-API-Key: test-key-12345" http://localhost:8000/session/patreon/status
# {"cookies_present":false,"needs_refresh":true,"last_error":"missing_credentials",...}
```

A Telegram notification is also sent (when `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` are configured).

## Docker

```bash
docker compose up --build
```

Single `app` container — no Postgres. Cookies are not persisted across restarts; either set `PATREON_SESSION` in `.env`, POST to `/session/patreon`, or rely on auto-login after each restart.

## CI Notes

- All tests mock Playwright and the login function — no real network access required.
- The dev shell needs `playwright install chromium` only for end-to-end testing.
