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

```env
# Required
SUPABASE_URL=https://<PROJECT_REF>.supabase.co
SUPABASE_KEY=eyJhbGciOi...
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOi...
DATABASE_URL=postgresql://postgres:[PASSWORD]@db.<PROJECT_REF>.supabase.co:5432/postgres
API_KEY_SALT=dev-salt-change-in-production

# Secrets
WEBHOOK_SECRET=dev-secret-change-in-production
RETRY_ENDPOINT_SECRET=dev-retry-secret-change-in-production
ENCRYPTION_KEY=dev-encryption-key-change-outside-development

# App behavior
ENVIRONMENT=development
FRONTEND_URL=http://localhost:8000
ALLOWED_HOSTS=localhost:8000
TRUSTED_PROXIES=
RETENTION_DAYS=30

# Outbound / network
OUTBOUND_HEALTH_CHECK_URL=https://www.google.com/generate_204
FORWARD_TIMEOUT_SECONDS=10.0

# Rate limiting
RATE_LIMIT_WINDOW_SECONDS=60
DEFAULT_RATE_LIMIT=30

# Retry / cleanup
MAX_RETRIES=3
RETRY_BATCH_SIZE=100
RETRY_CLAIM_STALE_SECONDS=300
MAX_LOG_BODY_BYTES=10000

# Disposable email detection
DISPOSABLE_EMAIL_LIST_URL=https://raw.githubusercontent.com/ivolo/disposable-email-domains/master/index.json

# Email notifications (Resend)
RESEND_API_KEY=
EMAIL_FROM=noreply@saferoute.dev
EMAIL_REPLY_TO=

# Cloudflare Turnstile
TURNSTILE_SECRET_KEY=

# Payments (Paystack)
PAYSTACK_SECRET_KEY=sk_test_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
PAYSTACK_BASE_URL=https://api.paystack.co
PAYSTACK_WEBHOOK_URL=https://saferoute-api.vercel.app/v1/webhooks/paystack

# Monitoring
SENTRY_DSN=
APP_VERSION=0.7.0
OTEL_ENABLED=false
```

- `SUPABASE_URL` and `SUPABASE_KEY` from Project Settings → API
- `SUPABASE_SERVICE_ROLE_KEY` from the same page
- `API_KEY_SALT` — any random string, used to hash API keys
- `RETRY_ENDPOINT_SECRET` — shared secret for `/internal/process-retries`
- `ENCRYPTION_KEY` — required outside local development for webhook-secret encryption. Encryption is performed **in the application** by `app/crypto.py` using Fernet (prefix `v1:`), falling back to the `safe_plain:` prefix when no key is configured. (The older, DB-side `pgcrypto` scheme was removed.)
- `FRONTEND_URL` — where Supabase redirects after OAuth (e.g. `http://localhost:8000` for dev, `https://your-app.vercel.app` for production)
- `ALLOWED_HOSTS` — **required in production** (comma-separated). On Vercel set to your app domain(s); empty (or missing) makes the app refuse to start.
- `TRUSTED_PROXIES` — comma-separated edge/CDN IPs whose `X-Forwarded-For` is trusted for per-IP rate limiting. **Required when deployed behind a CDN/Vercel** so clients aren't all grouped into one rate-limit bucket.
- `RETENTION_DAYS` — how many days of webhook delivery history to retain (1-365). Defaults to 30.
- `OUTBOUND_HEALTH_CHECK_URL` — endpoint used by `/internal/health/outbound` to verify egress. Defaults to `https://www.google.com/generate_204`.
- `FORWARD_TIMEOUT_SECONDS` — timeout for outbound webhook delivery requests. Defaults to `10.0`.
- `RATE_LIMIT_WINDOW_SECONDS` — sliding window duration for per-IP rate limiting. Defaults to `60`.
- `DEFAULT_RATE_LIMIT` — default max requests per IP per route within the window. Defaults to `30`.
- `MAX_RETRIES` — maximum retry attempts for failed deliveries. Defaults to `3`.
- `RETRY_BATCH_SIZE` — max retry entries processed per `/internal/process-retries` call. Defaults to `100`.
- `RETRY_CLAIM_STALE_SECONDS` — how long a claimed retry may sit before the reaper resets it. Defaults to `300`.
- `MAX_LOG_BODY_BYTES` — truncate stored response bodies to this size. Defaults to `10000`.
- `RESEND_API_KEY` — optional Resend API key for email notifications. If empty, email delivery is skipped.
- `EMAIL_FROM` — sender address for notification emails. Defaults to `noreply@saferoute.dev`.
- `EMAIL_REPLY_TO` — optional reply-to address for notification emails.
- `TURNSTILE_SECRET_KEY` — optional Cloudflare Turnstile secret key. Required per-route when Turnstile is enabled.
- `DISPOSABLE_EMAIL_LIST_URL` — optional URL to a JSON array of disposable email domains. Defaults to the maintained list at `https://raw.githubusercontent.com/ivolo/disposable-email-domains/master/index.json`. Set to empty string to disable external fetching and use the embedded fallback list.
- `DATABASE_URL` — PostgreSQL connection string for direct database access (required for CI tasks and direct DB operations). Format: `postgresql://user:password@host:port/database`.
- `PAYSTACK_SECRET_KEY` — Paystack API secret key for payment processing. Start with `sk_test_` for test mode or `sk_live_` for production.
- `PAYSTACK_BASE_URL` — Paystack API base URL. Defaults to `https://api.paystack.co`.
- `PAYSTACK_WEBHOOK_URL` — Public URL where Paystack sends webhook events. Must be reachable from the internet.
- `ADMIN_SECRET_KEY` — Shared secret for admin endpoints (`/v1/admin/credits/adjust`, `/v1/webhooks/paystack/retry`). Required when using admin features.
- `ADMIN_ALLOWED_IPS` — Comma-separated IP allowlist for admin endpoints. Leave empty to allow all IPs (not recommended for production).
- `SENTRY_DSN` — Sentry DSN for error tracking. If empty, error tracking is disabled.
- `APP_VERSION` — Application version string for health checks and monitoring. Defaults to `0.7.0`.
- `OTEL_ENABLED` — Enable OpenTelemetry tracing. Set to `true` to enable. Defaults to `false`.

## 4. Run locally

```bash
uvicorn app.main:app --reload
```

Visit http://localhost:8000/docs for interactive API docs.

## 5. Test OAuth

```bash
curl http://localhost:8000/auth/oauth/google
# Returns: {"auth_url":"https://..."}
```

Open the `auth_url` in a browser, sign in, and you'll get a JWT token back.

## 6. Key Rotation

### Encryption Key

1. Set the new `ENCRYPTION_KEY` in your environment
2. Restart the application
3. Re-encrypt existing webhook secrets by reading each route and updating the `webhook_secret` field with the newly encrypted value

**Note:** The application caches the Fernet instance in memory. After rotation, restart the process to use the new key.

### API Key

Use `POST /v1/routes/{route_id}/rotate-key` to rotate a route's API key. The new key is returned once and cannot be retrieved again.

## Deploying

1. Push to GitHub
2. Deploy with Docker or an ASGI-compatible host
3. Set environment variables in your hosting platform
4. Update `FRONTEND_URL` to your production URL
5. Add production URL to OAuth provider dashboards if needed
