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
SUPABASE_URL=https://<PROJECT_REF>.supabase.co
SUPABASE_KEY=eyJhbGciOi...
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOi...
WEBHOOK_SECRET=dev-secret-change-in-production
API_KEY_SALT=dev-salt-change-in-production
RETRY_ENDPOINT_SECRET=dev-retry-secret-change-in-production
ENCRYPTION_KEY=dev-encryption-key-change-outside-development
FRONTEND_URL=http://localhost:8000
ENVIRONMENT=development
```

- `SUPABASE_URL` and `SUPABASE_KEY` from Project Settings → API
- `SUPABASE_SERVICE_ROLE_KEY` from the same page
- `API_KEY_SALT` — any random string, used to hash API keys
- `RETRY_ENDPOINT_SECRET` — shared secret for `/internal/process-retries`
- `ENCRYPTION_KEY` — required outside local development for webhook-secret encryption
- `FRONTEND_URL` — where Supabase redirects after OAuth (e.g. `http://localhost:8000` for dev, `https://your-app.vercel.app` for production)

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

## Deploying

1. Push to GitHub
2. Deploy with Docker or an ASGI-compatible host
3. Set environment variables in your hosting platform
4. Update `FRONTEND_URL` to your production URL
5. Add production URL to OAuth provider dashboards if needed
