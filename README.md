# SafeRoute API

[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue)](https://www.python.org/downloads/)
[![FastAPI 0.139](https://img.shields.io/badge/FastAPI-0.139-green)](https://fastapi.tiangolo.com/)
[![Supabase](https://img.shields.io/badge/Supabase-Ready-3ECF8E)](https://supabase.com/)
[![Sponsor](https://img.shields.io/badge/Sponsor-GitHub-white?logo=github)](https://github.com/sponsors/darestack)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange)](https://github.com/darestack/saferoute-api)

A lightweight, secure webhook proxy. Point your static forms or public webhooks at a SafeRoute URL and we'll forward them to Zapier, Make, Slack, or any destination — with spam filtering and rate limiting built in.

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
| Deployment | Vercel Functions             |
| Payments   | Stripe (planned)             |

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
├── vercel.json
└── schema.sql           # Supabase tables + RLS policies
```

## What's included

- [x] Google/GitHub OAuth via Supabase Auth
- [x] API key generation and verification for route management
- [x] Proxy forwarding with rate limiting and webhook logging
- [x] Security headers, CORS, request size limits
- [x] Supabase schema with RLS, rate-limit table, webhook logs

## What's missing

- [ ] Spam filtering (honeypot + IP rate limiting)
- [ ] Retry logic with exponential backoff
- [ ] Dashboard UI
- [ ] Stripe billing
- [ ] Webhook signature verification
- [ ] Tests

## Contributing

1. Fork and clone
2. Read [CONTRIBUTING.md](CONTRIBUTING.md)
3. Open a PR

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## License

MIT — see [LICENSE](LICENSE).
