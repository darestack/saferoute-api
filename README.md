# SafeRoute API

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/)
[![FastAPI 0.139](https://img.shields.io/badge/FastAPI-0.139-green)](https://fastapi.tiangolo.com/)
[![Supabase](https://img.shields.io/badge/Supabase-Ready-3ECF8E)](https://supabase.com/)
[![Sponsor](https://img.shields.io/badge/Sponsor-GitHub-white?logo=github)](https://github.com/sponsors/darestack)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: Beta](https://img.shields.io/badge/status-beta-blue)](https://github.com/darestack/saferoute-api)

**Add a secure backend to any static website in under 60 seconds.**

SafeRoute is a form backend for static sites. Point your HTML form at a SafeRoute endpoint, and we handle validation, spam filtering, email notifications, and secure delivery to your inbox or webhook.

**Live demo:** https://saferoute-api.vercel.app

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
├── app/
│   ├── main.py              # FastAPI app, middleware, routes
│   ├── config.py            # Pydantic settings
│   ├── database.py          # Supabase clients
│   ├── crypto.py            # Webhook secret encryption
│   ├── models.py            # Request/response schemas
│   ├── repositories/        # Data access layer
│   ├── routes/              # HTTP route handlers
│   │   ├── auth.py          # JWT auth, route CRUD, API key management
│   │   ├── oauth.py         # Google/GitHub OAuth flows
│   │   └── proxy.py         # Webhook forwarding engine
│   ├── services/            # Business logic layer
│   └── utils/               # Shared helpers
├── requirements.txt
├── schema.sql               # Supabase tables + RLS policies
└── tests/                   # Test suite
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

## What's missing

- [ ] Dashboard UI
- [ ] Managed network egress controls

## Documentation

| Topic | Guide |
|-------|-------|
| Detailed setup (Supabase, OAuth, env vars) | [docs/guides/setup.md](docs/guides/setup.md) |
| API endpoint reference | [docs/reference/api.md](docs/reference/api.md) |
| Architecture and data flow | [docs/reference/architecture.md](docs/reference/architecture.md) |
| Operations and incident response | [docs/runbook.md](docs/runbook.md) |
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
