# easy_travel_deal_publisher

## Purpose

`easy_travel_deal_publisher` is a passive FastAPI microservice for the flynow.cz ecosystem. It receives pre-rendered post payloads (`title`, `body`, `destination_name`) from upstream and prepares Patreon drafts via Playwright. No LLM calls, no deal selection — those run upstream. Each post is matched to a destination image from `assets/patreon/`.

## Local run

1. Copy `.env.example` to `.env` and fill secrets.
2. Install dependencies.
3. Start PostgreSQL and app with Docker Compose:

```bash
docker compose up --build
```

4. Or run locally with uvicorn once `DATABASE_URL` is set:

```bash
uvicorn app.main:app --reload
```

## Tests

Run the full test suite:

```bash
pytest -q
```

The tests mock external services. SQLite in-memory is used for DB-oriented tests where possible.

For a comprehensive testing guide including manual endpoint testing, local development setup, and Docker testing, see [TESTING.md](TESTING.md).

## Patreon session lifecycle

Session cookies live in the `patreon_sessions` table (single-row, latest wins). On startup, if the table is empty and `PATREON_SESSION` env is set, the blob is decoded once and seeded into the DB; afterwards the env var is ignored.

When `PatreonPublisher.publish()` runs:

1. It probes `/api/current_user` with the stored cookies. If 200 with a user id, it skips straight to the composer.
2. If invalid, it runs the in-process login flow (same Playwright context, same fingerprint) using `PATREON_EMAIL` / `PATREON_PASSWORD` and resolves 2FA via `PATREON_TOTP_SECRET` (preferred) or a one-shot `PATREON_2FA_CODE`.
3. After publish, refreshed cookies are written back to the database.

If login itself fails, the service raises `SessionExpiredError` and sends a Telegram notification when `TELEGRAM_BOT_TOKEN` is configured.

## Assets and Images

Store images and brand assets in the `assets/` directory:

- `assets/brand/` — Logo, mascot (Glido), and global brand assets
- `assets/patreon/` — Patreon post templates and headers
- `assets/deals/` — Optional destination-specific or deal hero images

See [assets/README.md](assets/README.md) for image guidelines, sizing, and usage examples in the Patreon publisher.

## Add a new publisher

1. Add a module under `app/publishers/`.
2. Expose a small publisher class/function with a single publish method.
3. Mock it in tests; keep all network calls isolated behind one wrapper.
4. Update the ingest pipeline in `app/main.py` so each publisher runs independently and partial failures do not block the others.
5. Persist post metadata in `published_deals`.

## Operational notes

- `POST /ingest` is protected by `X-API-Key` matching `INGEST_API_KEY`.
- `GET /history` returns the latest published deals.
- `GET /ingest-log` returns recent ingest attempts.
- `GET /health` is the readiness check.
- The service is reactive only; no scheduler is used.
