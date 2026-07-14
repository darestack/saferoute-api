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

## Stack

| Component | Choice |
|-----------|--------|
| API | FastAPI + Uvicorn |
| Database | Supabase (PostgreSQL + Auth) |
| Deployment | Docker or ASGI hosting |

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

## What's missing

- [ ] Dashboard UI
- [ ] Managed network egress controls. Current SSRF protection is implemented in application code with standard-library URL/IP/DNS checks to keep operating cost at $0.

## Contributing

1. Fork and clone
2. Read [CONTRIBUTING.md](CONTRIBUTING.md)
3. Open a PR

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## License

MIT — see [LICENSE](LICENSE).
