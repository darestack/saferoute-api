# SafeRoute API

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/)
[![FastAPI 0.139](https://img.shields.io/badge/FastAPI-0.139-green)](https://fastapi.tiangolo.com/)
[![Supabase](https://img.shields.io/badge/Supabase-Ready-3ECF8E)](https://supabase.com/)
[![Sponsor](https://img.shields.io/badge/Sponsor-GitHub-white?logo=github)](https://github.com/sponsors/darestack)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: Stable](https://img.shields.io/badge/status-stable-brightgreen)](https://github.com/darestack/saferoute-api)

**Add a secure backend to any static website in under 60 seconds.**

SafeRoute is a form backend for static sites. Point your HTML form at a SafeRoute endpoint, and we handle validation, spam filtering, email notifications, and secure delivery to your inbox or webhook.

**Live demo:** https://saferoute-api.vercel.app
**Dashboard:** https://darestack.github.io/saferoute-api/

## Quick start

```bash
git clone https://github.com/darestack/saferoute-api.git
cd saferoute-api
cp .env.example .env
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

## Why SafeRoute?

Static sites are fast, secure, and cheap to host. But they can't process form submissions. You need a backend.

SafeRoute gives you a backend without the backend:

| Problem | SafeRoute Solution |
|---------|-------------------|
| Exposing your real email/webhook | Secret endpoint masking (`/v1/r/contact-form`) |
| Spam and bots | Honeypot + rate limiting + User-Agent filtering |
| Invalid submissions | Server-side form validation before delivery |
| No visibility | Simple request logs with replay |
| Platform lock-in | Works with GitHub Pages, Vercel, Netlify, or plain HTML |

## Stack

| Component | Choice |
|-----------|--------|
| API | FastAPI + Uvicorn |
| Database | Supabase (PostgreSQL + Auth) |
| Deployment | Vercel / Docker / ASGI hosting |
| Email | Resend (optional) |

## Project layout

```
├── api/
│   └── index.py              # Mangum ASGI adapter for Vercel
├── app/
│   ├── main.py               # FastAPI app, middleware, routes
│   ├── config.py             # Pydantic settings
│   ├── database.py           # Supabase clients
│   ├── crypto.py             # Webhook secret encryption
│   ├── logging_config.py     # Structured JSON logging
│   ├── models.py             # Request/response schemas
│   ├── monitoring.py         # Sentry / OpenTelemetry initialization
│   ├── repositories/         # Data access layer
│   ├── routes/               # HTTP route handlers
│   │   ├── auth.py           # JWT auth, route CRUD, payments, admin
│   │   ├── oauth.py          # Google/GitHub OAuth flows
│   │   └── proxy.py          # Webhook forwarding engine
│   ├── services/             # Business logic layer
│   │   ├── cache.py          # Distributed cache (L1 + L2)
│   │   ├── circuit_breaker.py # Outbound circuit breaker
│   │   ├── exchange_rates.py # FX rate fetching
│   │   ├── payments.py       # Paystack integration
│   │   ├── retention.py      # Database cleanup jobs
│   │   ├── retry_processor.py # Failed webhook retry logic
│   │   └── route_cache.py    # Route config caching
│   └── utils/                # Shared helpers
│       ├── captcha.py        # Cloudflare Turnstile verification
│       ├── disposable_domains.json # Embedded fallback list
│       ├── email.py          # Resend email delivery
│       ├── ip_allowlist.py   # Admin IP allowlist
│       ├── pkce.py           # PKCE code verifier storage
│       ├── retry.py          # Retry scheduling utilities
│       ├── routes.py         # Route helper functions
│       └── security.py       # IP extraction, URL validation
├── frontend/                 # Static dashboard (GitHub Pages)
│   ├── src/                  # TypeScript source
│   │   ├── main.ts           # Homepage entry
│   │   ├── dashboard.ts      # Dashboard SPA entry
│   │   ├── login.ts          # Login page logic
│   │   ├── callback.ts       # OAuth callback handler
│   │   ├── components/       # Dashboard UI components
│   │   ├── lib/              # API and auth utilities
│   │   ├── types/            # TypeScript interfaces
│   │   └── global.css        # Custom animations
│   ├── auth/
│   │   └── callback.html     # OAuth callback handler
│   ├── dashboard.html        # Authenticated dashboard
│   ├── login.html            # OAuth login
│   ├── index.html            # Marketing homepage
│   └── assets/               # CSS, JS, images
├── tests/                    # Backend test suite
├── load-tests/               # k6 load testing scripts
├── requirements.txt
├── schema.sql                # Supabase tables + RLS policies
└── docs/                     # Documentation
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
- [x] Webhook secret rotation support
- [x] Form validation schema support
- [x] Spam shield (honeypot + rate limiting + User-Agent filtering + country blocking + IP blacklist + disposable email detection + Cloudflare Turnstile)
- [x] Manual replay queue for failed deliveries
- [x] Bulk log cleanup endpoint
- [x] Email notifications via Resend
- [x] Standardized API responses with Pydantic models
- [x] Credit-based usage system with atomic deduction
- [x] Paystack payment integration for credit pack purchases
- [x] Payment webhook verification and automatic credit top-up
- [x] Admin manual credit adjustment endpoint
- [x] Frontend dashboard with OAuth login, route management, and payment UI
- [x] GitHub Pages deployment for frontend
- [x] Sentry error tracking and OpenTelemetry tracing support

## Deployment

### Vercel (recommended for backend)

1. Clone and install dependencies
2. Set environment variables in Vercel dashboard
3. Deploy with `vercel --prod`

Required env vars: `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `DATABASE_URL`, `API_KEY_SALT`, `ENCRYPTION_KEY`, `ALLOWED_HOSTS`, `WEBHOOK_SECRET`, `RETRY_ENDPOINT_SECRET`

### Docker

```bash
docker build -t saferoute-api .
docker run -p 8000:8000 --env-file .env saferoute-api
```

### GitHub Pages (frontend only)

The frontend dashboard is automatically deployed to GitHub Pages via the included workflow. Enable GitHub Pages in your repository settings and push to `main`.

## Example Form HTML

### Plain HTML

```html
<form action="/v1/r/contact-form" method="POST">
  <input type="text" name="name" required>
  <input type="email" name="email" required>
  <textarea name="message" required></textarea>
  <button type="submit">Send</button>
</form>
```

### With Cloudflare Turnstile

```html
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
<form action="/v1/r/contact-form" method="POST">
  <input type="text" name="name" required>
  <input type="email" name="email" required>
  <div class="cf-turnstile" data-sitekey="your-site-key"></div>
  <button type="submit">Send</button>
</form>
```

### With fetch() API

```javascript
const form = document.querySelector('#contact-form');
form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const response = await fetch('/v1/r/contact-form', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: 'John', email: 'john@example.com', message: 'Hello' }),
  });
  const result = await response.json();
  console.log(result);
});
```

## What's missing

- [ ] Managed network egress controls

## Documentation

| Topic | Guide |
|-------|-------|
| Detailed setup (Supabase, OAuth, env vars) | [docs/guides/setup.md](docs/guides/setup.md) |
| API endpoint reference | [docs/reference/api.md](docs/reference/api.md) |
| Architecture and data flow | [docs/reference/architecture.md](docs/reference/architecture.md) |
| Operations and incident response | [docs/runbook.md](docs/runbook.md) |
| Zero-dollar constraint & tradeoffs | [docs/reference/zero-dollar-constraint.md](docs/reference/zero-dollar-constraint.md) |
| Database migrations | [docs/migrations.md](docs/migrations.md) |
| Contributing | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Security policy | [SECURITY.md](SECURITY.md) |

## Contributing

1. Fork and clone
2. Read [CONTRIBUTING.md](CONTRIBUTING.md)
3. Open a PR

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## License

MIT — see [LICENSE](LICENSE).
