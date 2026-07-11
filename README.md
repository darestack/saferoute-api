# SafeRoute API

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/)
[![FastAPI 0.139](https://img.shields.io/badge/FastAPI-0.139-green)](https://fastapi.tiangolo.com/)
[![Supabase](https://img.shields.io/badge/Supabase-Ready-3ECF8E)](https://supabase.com/)
[![Sponsor](https://img.shields.io/badge/Sponsor-GitHub-white?logo=github)](https://github.com/sponsors/darestack)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange)](https://github.com/darestack/saferoute-api)

A lightweight, secure webhook proxy. Point your static forms or public webhooks at a SafeRoute URL and SafeRoute forwards them to an HTTPS destination with per-route rate limiting, optional HMAC verification, retry handling, and webhook logging.

**Live demo:** https://saferoute-api.vercel.app  
**Status:** Alpha — not production-ready. Use at your own risk.

## Quick start

```bash
git clone https://github.com/darestack/saferoute-api.git
cd saferoute-api
cp .env.example .env
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

Detailed setup with Supabase + OAuth: [SETUP.md](SETUP.md)

## Stack

| Component  | Choice                       |
| ---------- | ---------------------------- |
| API        | FastAPI + Uvicorn            |
| Database   | Supabase (PostgreSQL + Auth) |
| Deployment | Docker or ASGI hosting       |

## Usage

### Create a route

```bash
POST /auth/routes
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "Contact Form",
  "destination_url": "https://hooks.zapier.com/hooks/catch/...",
  "method": "POST"
}
```

Returns a `slug` and an `api_key`. Submit forms to `POST /v1/route/{slug}`.

### Forward a webhook

```bash
POST /v1/route/{slug}
Content-Type: application/json

{"name": "Alice", "email": "alice@example.com", "message": "Hello"}
```

SafeRoute validates the payload, rate-limits by IP, logs the request, and forwards it to your destination.

## Project layout

```
├── app/
│   ├── main.py          # FastAPI app, middleware, routes
│   ├── config.py        # Pydantic settings
│   ├── database.py      # Supabase clients
│   ├── models.py        # Request/response schemas
│   └── routes/
│       ├── auth.py      # JWT auth, route CRUD, API key management
│       ├── oauth.py     # Google/GitHub OAuth flows
│       └── proxy.py     # Webhook forwarding engine
├── requirements.txt
└── schema.sql           # Supabase tables + RLS policies
```

## What's included

- [x] Google/GitHub OAuth via Supabase Auth
- [x] API key generation and verification for route management
- [x] Proxy forwarding with rate limiting and webhook logging
- [x] Retry processing for retryable delivery failures
- [x] Optional webhook signature verification
- [x] Security headers, CORS, request size limits
- [x] Basic SSRF guardrails for outbound destinations
- [x] Supabase schema with RLS, rate-limit table, webhook logs

## What's missing

- [ ] Dashboard UI
- [ ] Managed network egress controls. Current SSRF protection is implemented in application code with standard-library URL/IP/DNS checks to keep operating cost at $0.

## Security model

* **Route secret (primary):** each route's proxy URL is
  `POST /v1/route/{slug}` where `slug` ends in a 48-bit random suffix
  (`secrets.token_hex(6)`), making the URL itself the unguessable secret.
* **API key (optional, defense-in-depth):** a route may also require an
  `X-API-Key` header. If a caller presents one it is verified (constant-time
  HMAC) against the stored `api_key_hash`; an invalid key is rejected with
  `401`. A missing key is allowed (slug-only auth) for compatibility with
  webhook senders that only know the slug.
* **Webhook signatures:** routes with a `webhook_secret` require a valid
  HMAC-SHA256 signature (`X-Hub-Signature-256` / `X-Webhook-Signature`).
* **Rate limiting:** per-route, per-IP, fixed 60-second windows enforced by
  the atomic `increment_rate_limit` Postgres function. **Behind a CDN/Vercel
  you must set `TRUSTED_PROXIES`** or every client collapses into one bucket.
* **SSRF guardrails:** destinations are validated at *write time* (HTTPS only,
  no embedded credentials, resolves to a public IP). A cheap, DNS-free check
  also runs per request (scheme / literal-IP invariants). Full egress-firewall
  controls are out of scope for the $0 cost target.
* **Route cache:** an in-memory route cache (30s TTL) is invalidated on
  update/delete/key-rotation so config and `is_active` changes take effect
  immediately rather than after a stale window.

## Deploying

1. Push to GitHub
2. Deploy with Docker or an ASGI-compatible host (e.g. Vercel via `api/index.py`)
3. Set environment variables in your hosting platform
4. Update `FRONTEND_URL` to your production URL
5. Add production URL to OAuth provider dashboards if needed

### Required production trust-boundary variables

When `ENVIRONMENT=production` the app **fails to start** (fail-closed) unless
these are set:

* `ALLOWED_HOSTS` — comma-separated `Host` values permitted by
  `TrustedHostMiddleware`. **On Vercel set this to your app domain(s)**
  (e.g. `saferoute-api.vercel.app,your-domain.com`); empty rejects every
  request with `400`.
* `TRUSTED_PROXIES` — comma-separated edge/CDN IPs whose `X-Forwarded-For` is
  trusted for per-IP rate limiting. **Required behind Vercel/Cloudflare**, else
  all clients share one rate-limit bucket.
* `ENCRYPTION_KEY` — required in production for `webhook_secret` encryption at
  rest (Fernet).

## Contributing

1. Fork and clone
2. Read [CONTRIBUTING.md](CONTRIBUTING.md)
3. Open a PR

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## License

MIT — see [LICENSE](LICENSE).
