# SafeRoute API

[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue)](https://www.python.org/downloads/)
[![FastAPI 0.139](https://img.shields.io/badge/FastAPI-0.139-green)](https://fastapi.tiangolo.com/)
[![Supabase](https://img.shields.io/badge/Supabase-Ready-3ECF8E)](https://supabase.com/)
[![Sponsor](https://img.shields.io/badge/Sponsor-GitHub-white?logo=github)](https://github.com/sponsors/naisutech)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange)](https://github.com/naisutech/saferoute-api)

A lightweight, secure webhook proxy. Point your static forms or public webhooks at a SafeRoute URL and we'll forward them to Zapier, Make, Slack, or any destination — with spam filtering and rate limiting built in.

**Live demo:** https://saferoute-api.vercel.app  
**Docs:** [./docs/](./docs/)  
**Status:** Alpha — not production-ready. Use at your own risk.

## Why

Most static-site form backends either expose your webhook URLs to the client or gate webhook forwarding behind expensive plans. SafeRoute sits in the middle: one URL, one place to filter spam, zero leaked secrets.

## Quick start

```bash
git clone https://github.com/naisutech/saferoute-api.git
cd saferoute-api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

## Deploy

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/naisutech/saferoute-api)

1. Create a Supabase project and run `schema.sql` in the SQL Editor
2. Set environment variables in Vercel: `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `WEBHOOK_SECRET`
3. Deploy

## API

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

Returns a `slug`. Submit forms to `POST /v1/route/{slug}`.

### Forward a webhook

```bash
POST /v1/route/{slug}
Content-Type: application/json

{"name": "Alice", "email": "alice@example.com", "message": "Hello"}
```

SafeRoute validates the payload, rate-limits by IP, logs the request, and forwards it to your destination.

## Stack

| Component  | Choice                       |
| ---------- | ---------------------------- |
| API        | FastAPI + Uvicorn            |
| Database   | Supabase (PostgreSQL + Auth) |
| Deployment | Vercel Functions             |
| Payments   | Stripe (planned)             |

## Project layout

```
├── app/
│   ├── main.py          # FastAPI app, middleware, routes
│   ├── config.py        # Pydantic settings
│   ├── database.py      # Supabase clients
│   ├── models.py        # Request/response schemas
│   └── routes/
│       ├── auth.py      # Register, login, route CRUD
│       └── proxy.py     # Webhook forwarding engine
├── requirements.txt
├── vercel.json
└── schema.sql           # Supabase tables + RLS policies
```

## What's included

- [x] FastAPI app with security headers, CORS, request size limits
- [x] Supabase schema with RLS, rate-limit table, webhook logs
- [x] Pydantic models with HTTPS-only URLs, slug validation, length constraints
- [x] Vercel deployment config targeting Python 3.14
- [x] Auth scaffolding (Supabase Auth integration)

## What's missing

- [ ] Proxy forwarding logic (`routes/proxy.py`)
- [ ] Auth route implementations (`routes/auth.py`)
- [ ] Spam filtering (honeypot + IP rate limiting)
- [ ] Retry logic with exponential backoff
- [ ] Dashboard UI
- [ ] Stripe billing
- [ ] Webhook signature verification
- [ ] Tests

## Contributing

Issues and PRs are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup details.

1. Fork and clone
2. Create a `.env` with Supabase credentials
3. Run `uvicorn app.main:app --reload`
4. Open a PR

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting.

## License

MIT — see [LICENSE](LICENSE).
