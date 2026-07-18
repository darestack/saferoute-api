# SafeRoute API Setup Guide

## Prerequisites

- Python 3.12+
- Supabase account (free tier works)
- Google Cloud account (for Google OAuth) OR GitHub account (for GitHub OAuth)

## 1. Create a Supabase project

1. Go to [supabase.com](https://supabase.com) and create a new project
2. Copy your **Project URL** and **API keys** from Project Settings → API
3. Find your **project ref** from the URL: `https://<PROJECT_REF>.supabase.co`
4. Open the SQL Editor and run `schema.sql`
5. Row Level Security policies are included in the schema

## 2. Enable OAuth providers

1. Go to [Supabase Auth Providers](https://supabase.com/dashboard/project/_/auth/providers)
2. Toggle **ON** the providers you want (Google, GitHub)

### Google OAuth

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create OAuth 2.0 Client ID (Web application)
3. Add authorized redirect URI: `https://<PROJECT_REF>.supabase.co/auth/v1/callback`
4. Add authorized JavaScript origin: `https://<PROJECT_REF>.supabase.co`
5. Copy Client ID and Client Secret into Supabase dashboard

### GitHub OAuth

1. Go to [GitHub Developer Settings](https://github.com/settings/applications/new)
2. Create OAuth App
3. Authorization callback URL: `https://<PROJECT_REF>.supabase.co/auth/v1/callback`
4. Copy Client ID and Client Secret into Supabase dashboard

## 3. Configure environment variables

Copy `.env.example` to `.env` and fill in the values below.

```env
# Required
SUPABASE_URL=https://<PROJECT_REF>.supabase.co
SUPABASE_KEY=<anon-public-key>
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
DATABASE_URL=postgresql://postgres:[PASSWORD]@db.<PROJECT-REF>.supabase.co:5432/postgres
ENCRYPTION_KEY=<32+ character random string>
API_KEY_SALT=<16+ character random string>
ALLOWED_HOSTS=<your-domain.com>  # Required in production; empty allowed in development
RETRY_ENDPOINT_SECRET=<32+ character shared secret for internal endpoints>
WEBHOOK_SECRET=<32+ character shared secret for webhook HMAC verification>
ADMIN_SECRET_KEY=<32+ character secret for admin endpoints>

# Optional (have defaults)
FRONTEND_URL=http://localhost:8000
ENVIRONMENT=development
TRUSTED_PROXIES=<comma-separated proxy IPs>
RETENTION_DAYS=30
OUTBOUND_HEALTH_CHECK_URL=https://www.google.com/generate_204
FORWARD_TIMEOUT_SECONDS=10.0
RATE_LIMIT_WINDOW_SECONDS=60
DEFAULT_RATE_LIMIT=30
MAX_REQUEST_BODY_BYTES=1048576
MAX_LOG_BODY_BYTES=10000
MAX_RETRIES=3
RETRY_BATCH_SIZE=100
RETRY_CLAIM_STALE_SECONDS=300
EMAIL_RETRY_ATTEMPTS=3
EMAIL_RETRY_BACKOFF_BASE=1.0
GEOLOCATION_TIMEOUT_SECONDS=2.0
CIRCUIT_BREAKER_TIMEOUT_SECONDS=60.0
OAUTH_CALLBACK_RATE_LIMIT=10
OAUTH_CALLBACK_RATE_WINDOW_SECONDS=60
EMAIL_FROM=noreply@saferoute.dev
EMAIL_REPLY_TO=
RESEND_API_KEY=
TURNSTILE_SECRET_KEY=
PAYSTACK_SECRET_KEY=
PAYSTACK_BASE_URL=https://api.paystack.co
PAYSTACK_WEBHOOK_URL=
SENTRY_DSN=
APP_VERSION=0.7.0
OTEL_ENABLED=false
ADMIN_ALLOWED_IPS=
DISPOSABLE_EMAIL_LIST_URL=https://raw.githubusercontent.com/ivolo/disposable-email-domains/master/index.json
```

### Key variable descriptions

- `SUPABASE_URL` and `SUPABASE_KEY` — from Project Settings → API in your Supabase dashboard.
- `SUPABASE_SERVICE_ROLE_KEY` — server-side key that bypasses RLS. Keep this secret.
- `API_KEY_SALT` — any random string; used to HMAC-hash route API keys.
- `RETRY_ENDPOINT_SECRET` — shared secret for `/internal/process-retries` and `/internal/cleanup`. Required for cron jobs.
- `ENCRYPTION_KEY` — **required outside local development** for webhook-secret encryption. The app uses Fernet encryption (`v1:` prefix) via `app/crypto.py`. When missing, the app logs a warning and can still run in development with degraded security.
- `WEBHOOK_SECRET` — optional global HMAC secret for webhook signature verification. Per-route secrets take precedence when set.
- `ALLOWED_HOSTS` — **required in production** (comma-separated). On Vercel set to your app domain(s). In development all hosts are allowed.
- `TRUSTED_PROXIES` — comma-separated edge/CDN IPs whose `X-Forwarded-For` header is trusted for per-IP rate limiting. **Required when deployed behind a CDN/Vercel** so clients aren't grouped into one rate-limit bucket.
- `FRONTEND_URL` — where Supabase redirects after OAuth (e.g. `http://localhost:8000` for dev, `https://your-app.vercel.app` for production).
- `RETENTION_DAYS` — how many days of webhook delivery history to retain (1–365). Defaults to `30`.
- `OUTBOUND_HEALTH_CHECK_URL` — endpoint used by `/internal/health/outbound` to verify egress. Defaults to `https://www.google.com/generate_204`.
- `FORWARD_TIMEOUT_SECONDS` — timeout for outbound webhook delivery requests. Defaults to `10.0`.
- `RATE_LIMIT_WINDOW_SECONDS` — sliding window duration for per-IP rate limiting. Defaults to `60`.
- `DEFAULT_RATE_LIMIT` — default max requests per IP per route within the window. Defaults to `30`.
- `MAX_REQUEST_BODY_BYTES` — maximum inbound request body size. Defaults to `1048576` (1 MiB).
- `MAX_LOG_BODY_BYTES` — truncate stored response bodies to this size. Defaults to `10000`.
- `MAX_RETRIES` — maximum retry attempts for failed deliveries. Defaults to `3`.
- `RETRY_BATCH_SIZE` — max retry entries processed per `/internal/process-retries` call. Defaults to `100`.
- `RETRY_CLAIM_STALE_SECONDS` — how long a claimed retry may sit before the reaper resets it. Defaults to `300`.
- `EMAIL_RETRY_ATTEMPTS` — maximum email delivery retry attempts. Defaults to `3`.
- `EMAIL_RETRY_BACKOFF_BASE` — base backoff seconds for email retries. Defaults to `1.0`.
- `GEOLOCATION_TIMEOUT_SECONDS` — timeout for IP geolocation lookups. Defaults to `2.0`.
- `CIRCUIT_BREAKER_TIMEOUT_SECONDS` — circuit breaker cooldown before half-open. Defaults to `60.0`.
- `OAUTH_CALLBACK_RATE_LIMIT` — max OAuth callback attempts per IP. Defaults to `10`.
- `OAUTH_CALLBACK_RATE_WINDOW_SECONDS` — OAuth rate limit window in seconds. Defaults to `60`.
- `RESEND_API_KEY` — optional Resend API key for email notifications. If empty, email delivery is skipped.
- `EMAIL_FROM` — sender address for notification emails. Defaults to `noreply@saferoute.dev`.
- `EMAIL_REPLY_TO` — optional reply-to address for notification emails.
- `TURNSTILE_SECRET_KEY` — optional Cloudflare Turnstile secret key. Required per-route when Turnstile is enabled.
- `PAYSTACK_SECRET_KEY` — Paystack secret key for payment processing.
- `PAYSTACK_BASE_URL` — Paystack API base URL. Defaults to `https://api.paystack.co`.
- `PAYSTACK_WEBHOOK_URL` — public URL where Paystack sends webhook events.
- `SENTRY_DSN` — Sentry DSN for error tracking (optional).
- `APP_VERSION` — application version string. Defaults to `0.7.0`.
- `OTEL_ENABLED` — enable OpenTelemetry tracing. Defaults to `false`.
- `ADMIN_SECRET_KEY` — shared secret for admin endpoints (`/v1/admin/credits/adjust`, `/v1/webhooks/paystack/retry`).
- `ADMIN_ALLOWED_IPS` — comma-separated IP allowlist for admin endpoints. Empty means all IPs are allowed.
- `DISPOSABLE_EMAIL_LIST_URL` — optional URL to a JSON array of disposable email domains. Set to empty string to disable external fetching and use the embedded fallback list.

## 4. Run locally

```bash
uvicorn app.main:app --reload
```

Visit http://localhost:8000/docs for interactive API docs.

## 5. Test OAuth

```bash
curl http://localhost:8000/auth/oauth/google
# Returns: {"auth_url":"https://accounts.google.com/...","provider":"google"}
```

Open the `auth_url` in a browser, sign in, and you'll be redirected back with a JWT token.

## 6. Key Rotation

### Encryption Key

1. Set the new `ENCRYPTION_KEY` in your environment
2. Restart the application
3. Re-encrypt existing webhook secrets by reading each route and updating the `webhook_secret` field with the newly encrypted value

**Note:** The application caches the Fernet instance per process. After rotation, call `clear_fernet_cache()` or restart to use the new key.

### API Key

Use `POST /v1/routes/{route_id}/rotate-key` to rotate a route's API key. The new key is returned once and cannot be retrieved again.


