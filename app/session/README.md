# Patreon Session Management

This directory holds the Patreon-cookie state for the publisher.

## Two ways to get a session

### A. Auto-login (default)

Set `PATREON_EMAIL` + `PATREON_PASSWORD` in `.env` and just call `POST /publish/patreon`. The publisher will detect that no session is held in memory, run a headless Playwright login, store the captured cookies in process memory, and proceed with the draft.

If Patreon's login redirect fires mid-publish, the same flow is invoked once more and the publish is retried.

### B. Manual login → REST receiver (2FA / captcha workaround)

When 2FA or a captcha blocks server-side login, capture cookies on a workstation and POST them to the running service:

```bash
python -m app.session.setup_session --manual
# A browser opens. Log in (with 2FA / passkey / whatever).
# Press Enter. The script prints a JSON payload.

curl -X POST http://<host>:8000/session/patreon \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $INGEST_API_KEY" \
  -d @-  <<'JSON'
{
  "cookies": [...],
  "email": "you@example.com"
}
JSON
```

The same script in automated mode (`python -m app.session.setup_session`) prints both a `PATREON_SESSION=` line for `.env` and a `POST /session/patreon` payload — pick whichever suits your deployment.

## How it works

* `state.py` owns an in-memory dict — the *only* place cookies live.
* At app startup `seed_from_env()` decodes `PATREON_SESSION` (base64 JSON) into memory if set.
* `setup_session.py:perform_patreon_login()` is the importable Playwright login helper used both by the CLI and by `PatreonPublisher` for auto-login.
* After a successful publish, refreshed cookies overwrite the in-memory store.
* On unrecoverable session failure, the state is flagged `needs_refresh=true` (visible at `GET /session/patreon/status`) and `/publish/patreon` returns `401 session_unavailable`.

## Status / debugging

```bash
curl -H "X-API-Key: $INGEST_API_KEY" http://localhost:8000/session/patreon/status
```

Common `last_error` values:

| Value                  | Meaning                                                          |
|------------------------|------------------------------------------------------------------|
| `missing_credentials`  | Auto-login attempted but `PATREON_EMAIL`/`PATREON_PASSWORD` empty |
| `two_factor_timeout`   | 2FA prompt appeared and was not completed in time                 |
| `login_failed: ...`    | Login submitted but did not land on a post-login URL              |
| `redirected_to_login`  | Mid-flow redirect (will trigger one auto-relogin retry)           |
| `relogin_did_not_help` | Retry after relogin still hit the login redirect                  |

## Security notes

- Cookies live only in process memory and the optional `PATREON_SESSION` env var — there is no cookie file on disk.
- `.env` is sensitive; never commit it.
- Treat `INGEST_API_KEY` like any other server credential.
- `PATREON_EMAIL` / `PATREON_PASSWORD` give full account access; consider a dedicated Patreon account for automated posting.

## Files

| File                | Role                                                                 |
|---------------------|----------------------------------------------------------------------|
| `state.py`          | In-memory session store (set / get / clear / status / seed-from-env) |
| `setup_session.py`  | `perform_patreon_login()` + CLI for manual / automated login         |
| `__init__.py`       | Marker (empty)                                                       |
