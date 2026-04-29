# Patreon Session Management

This directory contains tools for managing Patreon authentication sessions for the post publisher.

## Quick Start

### 1. Setup Session Interactively

```bash
python -m app.session.setup_session
```

This script will:

- Open a browser window
- Prompt for your Patreon email and password
- Guide you through login
- Handle 2FA if enabled
- Extract and print the session as base64

### 2. Add to .env

Copy the printed `PATREON_SESSION=...` value to your `.env` file.

## How It Works

### Session File Format

The session is stored as base64-encoded JSON:

```json
{
  "cookies": [
    {
      "name": "session_id",
      "value": "...",
      "domain": ".patreon.com",
      "path": "/",
      "secure": true,
      "httpOnly": true,
      "sameSite": "Lax"
    }
  ],
  "email": "your-email@example.com",
  "timestamp": "1234567890"
}
```

This is then base64-encoded for use in environment variables.

### Usage in Application

The `PatreonPublisher` class:

1. Reads `PATREON_SESSION` from `.env`
2. Decodes the base64 session
3. Parses the JSON
4. Restores cookies in Playwright browser context
5. Uses authenticated session to post

## Session Renewal

Sessions can expire due to:

- Cookie expiration (typically 30-90 days)
- Password changes
- Security policies
- Patreon logout

### Check Session Status

The publisher will raise `SessionExpiredError` if the session is invalid. You'll see in logs:

```
ERROR: Patreon session expired
```

When this happens, renew the session:

```bash
python -m app.session.setup_session
```

### Automated Alerts

If `TELEGRAM_BOT_TOKEN` is configured, the app will send a notification when the session expires:

```
"Patreon session expired for easy_travel_deal_publisher; renew session."
```

## Environment Variables

Required for session setup:

- `PATREON_EMAIL` - Your Patreon email (optional if prompted)
- `PATREON_PASSWORD` - Your Patreon password (optional if prompted)

Used by the publisher:

- `PATREON_SESSION` - Base64-encoded session (set by setup_session.py)
- `CREATOR_EDITOR_URL` - URL for post creation (default: https://www.patreon.com/creator/posts/new)

## Security Notes

⚠️ **Important Security Considerations:**

1. **Never commit `.env` to version control** - It contains session data
2. **Session cookies are persistent** - They authenticate all requests
3. **Treat PATREON_SESSION like a password** - Keep it secure
4. **Rotate sessions periodically** - Renew every 90 days for security
5. **Use environment variables** - Don't hardcode credentials in code
6. **Use different accounts for different environments** - Separate dev/prod sessions

### Secure Setup for Production

1. Use a dedicated Patreon account for automated posting
2. Enable 2FA on the account
3. Store `PATREON_SESSION` in your secrets manager (not in git)
4. Rotate sessions quarterly
5. Monitor for unauthorized posts
6. Set up alerts for session expiration

## Troubleshooting

### "Session expired" after setup

The session may have already expired. Try again:

```bash
python -m app.session.setup_session
```

### 2FA not completing

The setup script waits 2 minutes for 2FA. If you need more time:

1. Check the browser window
2. Complete 2FA manually
3. The script will detect completion

### Browser doesn't open

The setup script requires a display server (headless mode won't work for interactive login).

For remote servers, use local machine instead:

```bash
# On local machine
python -m app.session.setup_session

# Copy PATREON_SESSION to remote .env
```

## Technical Details

### Playwright Integration

The session setup uses Playwright's async API to:

- Launch a real browser (Chromium)
- Navigate to Patreon login
- Fill credentials
- Extract cookies after authentication

The `publish()` method uses the same cookies to:

- Restore session in new browser context
- Navigate to post creation page
- Automate post content entry
- Upload images
- Publish

### Cookie Scope

Cookies are captured at `.patreon.com` domain level and restored with:

- Domain: `.patreon.com`
- Path: `/`
- Secure: true (HTTPS only)
- HttpOnly: true (not accessible to JavaScript)
- SameSite: Lax (some cross-site requests allowed)

## Testing

For testing procedures, see [PATREON_TESTING.md](../../PATREON_TESTING.md).

Quick test:

```bash
# Setup session
python -m app.session.setup_session

# Run publisher test
python -c "
import asyncio
from app.publishers.patreon import PatreonPublisher
async def test():
    pub = PatreonPublisher()
    result = await pub.publish(
        title='Test Post',
        body_text='Testing the publisher',
        destination='Prague'
    )
    print(f'✅ {result}')
asyncio.run(test())
"
```

## References

- Patreon Creator Dashboard: https://www.patreon.com/creator/dashboard
- Patreon Creator Posts: https://www.patreon.com/creator/posts
- Playwright Docs: https://playwright.dev/python/
