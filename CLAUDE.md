# easy_travel_deal_publisher

## Purpose

`easy_travel_deal_publisher` is a thin FastAPI microservice in the flynow.cz ecosystem. It receives an already-formatted post (`title` + `body`) and creates a draft on Patreon via Playwright browser automation.

There is **no LLM, no deal selection, no deduplication, no database**. Copywriting and ranking happen upstream; this service only handles the Patreon-draft mechanics. See [API.md](API.md) for the REST contract.

## Local run

1. Copy `.env.example` to `.env` and fill at least `INGEST_API_KEY`, `PATREON_EMAIL`, `PATREON_PASSWORD`.
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

3. Start the app:

   ```bash
   uvicorn app.main:app --reload
   ```

   Or with Docker Compose:

   ```bash
   docker compose up --build
   ```

## Tests

```bash
pytest -q
```

Tests mock Playwright and the login flow. See [TESTING.md](TESTING.md) for manual endpoint exercises.

## Patreon authentication

The service holds the Patreon session **in process memory only**. Three ways to populate it:

1. Set `PATREON_SESSION` in `.env` (base64 JSON blob from `setup_session.py`). It seeds the in-memory session at startup.
2. POST a cookies payload to `/session/patreon` at runtime.
3. Do nothing. On the first `/publish/patreon` call, the service auto-runs the Playwright login using `PATREON_EMAIL` / `PATREON_PASSWORD` and stores the captured cookies in memory.

After every successful publish, refreshed cookies overwrite the in-memory session. If Patreon redirects the publisher to the login page mid-flow, the service automatically re-runs the login once and retries the publish. If login itself fails (bad creds, 2FA timeout, captcha):

- `/publish/patreon` returns HTTP `401 session_unavailable`.
- A Telegram notification is sent (when configured).
- `/session/patreon/status` reports `needs_refresh: true` with `last_error` populated.

To recover from a 2FA-blocked auto-login, run the manual flow on a workstation:

```bash
python -m app.session.setup_session --manual
# log in (including 2FA) in the visible browser, copy the printed JSON,
# then POST it to /session/patreon on the deployed instance.
```

## Assets and Images

Store images and brand assets in the `assets/` directory:

- `assets/brand/` — Logo, mascot (Glido), global brand assets
- `assets/patreon/` — Patreon post hero images (filename matches destination, e.g. `Bangkok.png`)

The Patreon publisher looks up an image by destination (`PatreonDraftPayload.destination`). See [assets/README.md](assets/README.md) for sizing guidelines.

## Add a new publisher

The service is currently single-publisher (Patreon). If you need a second target:

1. Add a module under `app/publishers/`.
2. Expose a class with a single `publish(...)` method.
3. Mock all network/browser calls in tests.
4. Add a route in `app/main.py` that calls it.
5. Map publisher-specific session-failure exceptions to clear HTTP errors.

## Operational notes

- All write endpoints (`POST /publish/patreon`, `POST /session/patreon`) require `X-API-Key` matching `INGEST_API_KEY`.
- `GET /health` is the readiness check; it also reports cookie state.
- `GET /session/patreon/status` exposes the in-memory cookie state (presence, count, last error, needs-refresh flag).
- The service is reactive only — no scheduler, no background workers.
