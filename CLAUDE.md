# easy_travel_deal_publisher

## Purpose

`easy_travel_deal_publisher` is a passive FastAPI microservice for the flynow.cz ecosystem. It receives deal batches from the upstream tracker, deduplicates recent items, asks Claude to choose the best deals, generates Czech social post text, and publishes to Patreon and X/Twitter.

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

## Patreon session renewal

The Patreon publisher uses `PATREON_SESSION`, a base64-encoded JSON session blob.

To renew the session:

1. Set `PATREON_EMAIL` and `PATREON_PASSWORD`.
2. Run the session helper:

```bash
python -m app.session.setup_session
```

3. Complete login and 2FA if prompted.
4. Copy the printed base64 session into `PATREON_SESSION`.

If the stored session expires, the service raises `SessionExpiredError` and can send a Telegram notification when `TELEGRAM_BOT_TOKEN` is configured.

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
5. Persist generated post text and publication status in `published_deals`.

## Operational notes

- `POST /ingest` is protected by `X-API-Key` matching `INGEST_API_KEY`.
- `GET /history` returns the latest published deals.
- `GET /ingest-log` returns recent ingest attempts.
- `GET /health` is the readiness check.
- The service is reactive only; no scheduler is used.
