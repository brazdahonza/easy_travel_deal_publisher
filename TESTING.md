# Testing Guide: easy_travel_deal_publisher

This guide covers how to test the service locally — from unit tests to manual endpoint testing.

## Quick Start: Unit Tests

Run the full test suite (mocks all external services):

```bash
pytest -q
```

Or with verbose output:

```bash
pytest -v
```

Expected: 11+ tests pass, 3 skipped (for optional dependencies like SQLAlchemy).

## Local Development Setup (without Docker)

### 1. Install dependencies

```bash
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
```

### 2. Set up environment

```bash
cp .env.example .env
```

Edit `.env` to set minimal required values:

```env
DATABASE_URL=sqlite:///./test.db
INGEST_API_KEY=test-key-12345
ANTHROPIC_API_KEY=sk-...  # optional; if missing, LLM falls back to simple selection
PATREON_SESSION=  # optional; if missing, Patreon publisher returns 404
TWITTER_API_KEY=  # optional; if missing, Twitter publisher is skipped
TELEGRAM_BOT_TOKEN=  # optional; Telegram notifications skipped if empty
```

### 3. Run the app locally

```bash
uvicorn app.main:app --reload
```

Server is live at `http://localhost:8000`.

**Health check:**

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

## Manual Endpoint Testing

### Test `/ingest` endpoint

Send a sample deal batch:

```bash
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -H "X-API-Key: test-key-12345" \
  -d '{
    "deals": [
      {
        "id": "deal1",
        "destination": "Bangkok",
        "departure_city": "Praha",
        "price": 8500,
        "median_price": 14000,
        "discount_pct": 0.39,
        "date_from": "2026-06-15",
        "date_to": "2026-06-22",
        "duration_days": 7,
        "ticket_url": "https://example.com/booking/1",
        "is_nearby": false
      },
      {
        "id": "deal2",
        "destination": "Budapest",
        "departure_city": "Praha",
        "price": 3200,
        "median_price": 5500,
        "discount_pct": 0.42,
        "date_from": "2026-05-10",
        "date_to": "2026-05-12",
        "duration_days": 2,
        "ticket_url": "https://example.com/booking/2",
        "is_nearby": true
      }
    ]
  }'
```

**Expected response** (200 OK):

```json
{
  "status": "ok",
  "selected": 2,
  "published": {
    "patreon": false,
    "x": false
  }
}
```

Note: `published` shows `false` because Patreon/Twitter are not fully configured.

---

### Test `/history` endpoint

Retrieve recently published deals:

```bash
curl http://localhost:8000/history
# {"data": []}  # empty until deals are published
```

---

### Test `/ingest-log` endpoint

Check ingest history:

```bash
curl http://localhost:8000/ingest-log
# {"data": [{"id": 1, "deals_count": 2, "selected_count": 2, "status": "done", ...}]}
```

---

### Missing API Key (test auth)

```bash
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"deals": []}'
# 403: {"detail":"invalid api key"}
```

## Docker Setup

### Build and run with Docker Compose

```bash
docker compose up --build
```

This starts:

- **PostgreSQL** on `localhost:5432` (user: `user`, pass: `pass`, db: `easy_travel_deal_publisher`)
- **FastAPI** on `localhost:8000`

**Test health:**

```bash
curl http://localhost:8000/health
```

**Stop services:**

```bash
docker compose down
```

---

## Testing with Anthropic (LLM Selection)

If you have an Anthropic API key:

1. **Set the key in `.env`:**

```env
ANTHROPIC_API_KEY=sk-ant-...
```

2. **Run the app and send an ingest request** (as shown above).

3. **Check logs** for LLM selection output:

```bash
# Watch logs in docker
docker compose logs -f app
```

---

## Testing Patreon Publisher

**To enable Patreon publishing:**

1. **Get session blob:**

```bash
export PATREON_EMAIL="your-email@example.com"
export PATREON_PASSWORD="your-password"
python -m app.session.setup_session
```

2. Copy the printed base64 session into `PATREON_SESSION` in `.env`.

3. **Run ingest** (from above) — Patreon publisher will attempt to post.

---

## Testing Twitter Publisher

**To enable Twitter posting:**

Set these in `.env`:

```env
TWITTER_API_KEY=your-api-key
TWITTER_API_SECRET=your-api-secret
TWITTER_ACCESS_TOKEN=your-access-token
TWITTER_ACCESS_SECRET=your-access-secret
```

Then run an ingest request. Publisher will post to Twitter.

---

## Testing Deduplication

**Send the same deal twice** to test dedup logic:

```bash
# First ingest
curl -X POST http://localhost:8000/ingest \
  -H "X-API-Key: test-key-12345" \
  -H "Content-Type: application/json" \
  -d '{"deals": [{"id": "dup1", "destination": "Bangkok", "departure_city": "Praha", "duration_days": 7, "price": 5000}]}'

# Second ingest (same deal)
curl -X POST http://localhost:8000/ingest \
  -H "X-API-Key: test-key-12345" \
  -H "Content-Type: application/json" \
  -d '{"deals": [{"id": "dup1", "destination": "Bangkok", "departure_city": "Praha", "duration_days": 7, "price": 5000}]}'
```

**Expected behavior:** Second ingest returns `selected: 0` (deal is a duplicate, filtered within 7 days).

---

## Unit Test Breakdown

| Test File                    | Coverage                                          |
| ---------------------------- | ------------------------------------------------- |
| `test_api.py`                | Health endpoint, auth                             |
| `test_deal_selector.py`      | Duration buckets, dedup hash, fallback selection  |
| `test_deal_selector_llm.py`  | LLM prompt parsing, response handling             |
| `test_generator.py`          | Patreon HTML generation, Twitter 280-char limit   |
| `test_publishers.py`         | Publisher initialization, missing config handling |
| `test_database.py`           | ORM model creation, DB operations                 |
| `test_api_ingest.py`         | Full `/ingest` pipeline (mocked LLM + publishers) |
| `test_llm_wrapper.py`        | Anthropic client wrapper                          |
| `test_patreon_playwright.py` | Patreon async publisher (mocked)                  |

---

## Common Issues

### SQLite "database is locked"

If using SQLite locally and tests run in parallel, use:

```bash
pytest -n0  # disable parallel execution
```

Or use PostgreSQL in Docker.

### Anthropic API errors

If `ANTHROPIC_API_KEY` is invalid or quota exceeded, the service falls back to simple selection (no error):

```json
{"status": "ok", "selected": 2, "published": {...}}
```

Check ingest logs to see if LLM was attempted.

### Patreon session expired

If `PATREON_SESSION` is invalid/expired, the service skips Patreon and publishes only to Twitter:

```json
{ "status": "ok", "selected": 2, "published": { "patreon": false, "x": true } }
```

Renew the session using `python -m app.session.setup_session`.

---

## CI/Testing Notes

- All tests mock external services (no real API calls).
- Tests use in-memory SQLite by default.
- Optional dependencies (SQLAlchemy, Playwright, etc.) are skipped if not installed.
- Full Docker + PostgreSQL integration test is recommended before deployment.
