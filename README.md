# SafeRoute API

A lightweight, secure proxy service that sits between public static forms (or third-party webhooks) and internal automation tools. It filters spam, masks sensitive endpoints, and forwards clean data to your Zapier, Make, CRM, or Slack workflows.

## The Problem

Front-end developers hate building custom backend infrastructure just to handle a basic contact form or capture an external webhook payload securely. Existing solutions either require heavy configurations, force users into bloated marketing automation platforms, or leak sensitive API keys in client-side code.

The danger zone: if you redirect a public form straight to an endpoint or automation webhook without a middleware layer, bad actors can spam the endpoint, blow through Zapier/Make automation task limits, and trigger massive unexpected bills.

## The Solution

SafeRoute API is a secure, zero-config webhook proxy. Instead of spending hours writing a secure serverless function, configuring anti-spam, and setting up error handling for every project, developers simply point their frontend forms or external webhooks to a unique SafeRoute URL.

```
┌────────────────┐       ┌────────────────┐       ┌─────────────────┐
│  Static Form / │ ───>  │  SafeRoute API │ ───>  │  Internal Tools │
│ Public Webhook │       │  (Vercel Edge) │       │ (Zapier / CRM)  │
└────────────────┘       └────────────────┘       └─────────────────┘
                             • Filters Spam           • Hidden Endpoint
                             • Rate Limits            • Zero Task Waste
```

## Features

- **Zero-config proxy**: Generate a route, get a SafeRoute URL, point your form to it
- **Spam filtering**: Honeypot checks and IP rate limiting
- **Endpoint masking**: Your Zapier/Make URLs never touch client-side code
- **Request queuing**: Async forwarding with automatic retries
- **Dashboard**: Create and manage routes with a clean UI
- **Usage analytics**: Track requests per route with built-in logging
- **Freemium pricing**: Free tier for hobbyists, paid tiers for power users

## Tech Stack

- **Backend**: FastAPI + Vercel Serverless Functions
- **Database**: Supabase (PostgreSQL)
- **Auth**: Supabase Auth
- **Deployment**: Vercel
- **Payments**: Stripe Checkout

## Project Structure

```
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI entrypoint & Vercel handler
│   ├── config.py            # Environment variables & settings
│   ├── database.py          # Supabase connection client
│   ├── models.py            # Pydantic validation schemas
│   └── routes/
│       ├── __init__.py
│       ├── auth.py          # User authentication endpoints
│       └── proxy.py         # Core webhook forwarding engine
├── requirements.txt         # Python dependencies
├── vercel.json              # Vercel deployment configuration
└── schema.sql               # Supabase database schema
```

## Getting Started

### Prerequisites

- Python 3.14+
- Node.js 18+
- Supabase account
- Vercel account
- Stripe account (for payments)

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/saferoute-api.git
cd saferoute-api
```

### 2. Set up Supabase

1. Create a new project at [supabase.com](https://supabase.com)
2. Go to the SQL Editor and run the migrations from `schema.sql`
3. Enable Row Level Security (RLS) policies are included in the schema

### 3. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy `.env.example` to `.env` and fill in your values:

```env
SUPABASE_URL=your_supabase_project_url
SUPABASE_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
WEBHOOK_SECRET=your_webhook_secret_key
STRIPE_SECRET_KEY=your_stripe_secret_key
STRIPE_WEBHOOK_SECRET=your_stripe_webhook_secret
ENVIRONMENT=development
```

### 5. Run locally

```bash
uvicorn app.main:app --reload
```

Visit `http://localhost:8000/docs` for the API documentation.

### 6. Deploy to Vercel

```bash
vercel link
vercel --prod
```

## API Endpoints

### Proxy Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/route/{slug}` | Forward webhook to destination |
| GET | `/v1/route/{slug}` | Route health check |

### Auth Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register` | Register new user |
| POST | `/auth/login` | Login user |
| GET | `/auth/me` | Get current user |

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | API health check |

## Usage

### Creating a Route

1. Sign up at `/auth/register`
2. Create a route via the dashboard or API:
   ```bash
   POST /auth/routes
   {
     "name": "Contact Form to Zapier",
     "destination_url": "https://hooks.zapier.com/hooks/catch/...",
     "method": "POST"
   }
   ```
3. Use the returned `slug` in your frontend:
   ```html
   <form action="https://saferoute-api.vercel.app/v1/route/YOUR_SLUG" method="POST">
     <input name="name" type="text" />
     <input name="email" type="email" />
     <button type="submit">Send</button>
   </form>
   ```

### Frontend Integration

```javascript
// JavaScript example
async function submitForm(data) {
  const response = await fetch('https://saferoute-api.vercel.app/v1/route/YOUR_SLUG', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  return response.json();
}
```

## Pricing

| Tier | Price | Requests | Features |
|------|-------|----------|----------|
| Free | $0 | 500/mo | Basic proxy, 1 route |
| Pro | $9/mo | 10,000/mo | Advanced spam filter, 10 routes |
| Business | $29/mo | 100,000/mo | Retries, analytics, unlimited routes |

## Roadmap

- [x] Core routing engine
- [x] Supabase database schema with RLS
- [x] Basic spam filtering (honeypot + rate limiting)
- [x] Request logging
- [ ] Dashboard UI
- [ ] Stripe billing integration
- [ ] Advanced spam filters (Turnstile, Akismet)
- [ ] Retry logic with exponential backoff
- [ ] Webhook signature verification
- [ ] Usage analytics dashboard
- [ ] Team/workspace support

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built with [FastAPI](https://fastapi.tiangolo.com/)
- Database powered by [Supabase](https://supabase.com/)
- Deployed on [Vercel](https://vercel.com/)
