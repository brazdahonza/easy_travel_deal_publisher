# easy_travel_deal_publisher — API Reference

A thin REST service that creates Patreon drafts from a pre-formatted `title` + `body`. There is no LLM, no deal selection, no database. Cookies live in process memory only.

## Base URL

`http://<host>:8000`

## Authentication

All write endpoints (`POST /publish/patreon`, `POST /session/patreon`, `GET /session/patreon/status`) require:

```
X-API-Key: <INGEST_API_KEY>
```

`GET /health` is unauthenticated.

If `INGEST_API_KEY` is unset in the environment, auth is disabled (development only).

---

## Endpoints

### `GET /health`

Liveness probe. Reports whether a session is currently held in memory.

**Response 200:**

```json
{
  "status": "ok",
  "cookies_present": true,
  "cookies_count": 27,
  "needs_refresh": false,
  "patreon_credentials": true
}
```

| Field                 | Meaning                                                            |
|-----------------------|--------------------------------------------------------------------|
| `cookies_present`     | A non-empty cookie set is held in memory                           |
| `cookies_count`       | Number of cookies currently held                                   |
| `needs_refresh`       | `true` after an unrecoverable session failure                      |
| `patreon_credentials` | `PATREON_EMAIL` and `PATREON_PASSWORD` are set (auto-login viable) |

---

### `POST /publish/patreon`

Create a Patreon draft from an already-formatted post. The service:

1. Ensures an in-memory session exists. If it doesn't, it runs the Playwright login automatically using `PATREON_EMAIL` / `PATREON_PASSWORD`.
2. Drives the Patreon UI to fill the title, body, and (optionally) a hero image looked up from `assets/patreon/`.
3. If Patreon redirects to the login page mid-flow, retries once after re-running login.
4. Captures the draft URL from the post composer.

**Headers:**
- `Content-Type: application/json`
- `X-API-Key: <INGEST_API_KEY>`

**Request body:**

```json
{
  "title": "Akce: Bangkok 8 500 Kč z Prahy",
  "body": "Letenka 15.6.–22.6. Sleva 39 % oproti mediánu. Detaily a odkaz uvnitř.",
  "destination": "Bangkok"
}
```

| Field         | Type     | Required | Notes                                                                    |
|---------------|----------|----------|--------------------------------------------------------------------------|
| `title`       | string   | yes      | 1–300 characters. Pasted verbatim into the Patreon title field.          |
| `body`        | string   | yes      | Pasted verbatim into the Patreon ProseMirror body editor.                |
| `destination` | string   | no       | Looks up `assets/patreon/<destination>.png` for a hero image. Optional.  |

**Response 200 (draft created):**

```json
{
  "status": "ok",
  "draft_url": "https://www.patreon.com/posts/123456789/edit",
  "post_id": "123456789"
}
```

When `PATREON_DRY_RUN=true` is set, the service short-circuits without launching a browser and returns:

```json
{ "status": "dry_run", "draft_url": null, "post_id": null }
```

**Errors:**

| Status | Body                                                                              | When                                                                                  |
|--------|-----------------------------------------------------------------------------------|---------------------------------------------------------------------------------------|
| 401    | `{"detail":{"error":"session_unavailable","reason":"<msg>"}}`                     | No session and auto-login failed (bad creds, 2FA timeout, missing creds, captcha)     |
| 403    | `{"detail":"invalid api key"}`                                                    | Missing or wrong `X-API-Key`                                                          |
| 422    | Pydantic validation error                                                         | Missing/empty `title` or `body`                                                       |
| 502    | `{"detail":"patreon_error: <msg>"}` or `{"detail":"patreon_publish_failed"}`      | Browser automation failure (selector miss, network, etc.)                             |

On 401, the service also fires a Telegram notification (when configured) and flips the `needs_refresh` flag exposed via `/session/patreon/status`.

**Example:**

```bash
curl -X POST http://localhost:8000/publish/patreon \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $INGEST_API_KEY" \
  -d '{
    "title": "Akce: Bangkok 8 500 Kč",
    "body": "Letenka z Prahy 15.6.–22.6. Detaily uvnitř.",
    "destination": "Bangkok"
  }'
```

---

### `POST /session/patreon`

Receive a pre-captured cookie blob and store it in memory. Useful when 2FA / captcha blocks the server-side auto-login: capture cookies on a workstation with `setup_session.py`, then POST them here.

**Headers:**
- `Content-Type: application/json`
- `X-API-Key: <INGEST_API_KEY>`

**Request body:**

```json
{
  "cookies": [
    {
      "name": "session_id",
      "value": "abc123",
      "domain": ".patreon.com",
      "path": "/",
      "expires": 1735689600.0,
      "httpOnly": true,
      "secure": true,
      "sameSite": "Lax"
    }
  ],
  "email": "ops@flynow.cz"
}
```

The cookie objects match Playwright's cookie shape (output of `BrowserContext.cookies()`).

**Response 200:**

```json
{
  "status": "ok",
  "cookies_count": 1,
  "email": "ops@flynow.cz"
}
```

After this call the in-memory session replaces whatever was there before; `needs_refresh` is reset to `false`.

A Telegram notification is sent on success (when configured).

---

### `GET /session/patreon/status`

Inspect the in-memory cookie state.

**Headers:**
- `X-API-Key: <INGEST_API_KEY>`

**Response 200:**

```json
{
  "cookies_present": true,
  "cookies_count": 27,
  "email": "ops@flynow.cz",
  "stored_at": "2026-05-03T10:00:00+00:00",
  "needs_refresh": false,
  "last_error": null
}
```

When auto-login has failed:

```json
{
  "cookies_present": false,
  "cookies_count": 0,
  "email": null,
  "stored_at": null,
  "needs_refresh": true,
  "last_error": "missing_credentials"
}
```

Common `last_error` values: `missing_credentials`, `two_factor_timeout`, `login_failed: ...`, `redirected_to_login`, `relogin_did_not_help`.

---

## Operator workflow

1. **Provision creds.** Set `PATREON_EMAIL`, `PATREON_PASSWORD`, and `INGEST_API_KEY` in `.env` (or your secret store).
2. **(Optional) Seed a session.** If you already have a fresh blob from `python -m app.session.setup_session`, paste it into `PATREON_SESSION` in `.env`. Skipping this step is fine — the service will auto-login on the first publish.
3. **Publish.** Send `POST /publish/patreon` whenever upstream produces a finished post.
4. **Watch `/session/patreon/status`.** If `needs_refresh: true` appears, auto-login is failing — most commonly because of 2FA. Run `python -m app.session.setup_session --manual` on a workstation with a browser, complete the login, and `POST /session/patreon` the captured cookies to the deployed instance. The next `/publish/patreon` call will use them.
5. **Monitor Telegram alerts.** Configured `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` deliver: a confirmation when cookies are uploaded, and a warning when auto-login fails.

## Curl quickstart

```bash
# Health
curl http://localhost:8000/health

# Status
curl -H "X-API-Key: $INGEST_API_KEY" http://localhost:8000/session/patreon/status

# Inject cookies from a manual login
curl -X POST http://localhost:8000/session/patreon \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $INGEST_API_KEY" \
  -d @cookies.json

# Create a draft
curl -X POST http://localhost:8000/publish/patreon \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $INGEST_API_KEY" \
  -d '{"title":"...","body":"...","destination":"Bangkok"}'
```
