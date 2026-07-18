# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.0] - 2026-07-17

### Added
- Credit-based usage system with atomic deduction via `deduct_user_credits()` SQL function
- User profiles table (`user_profiles`) with `credits` and `tier` fields
- Paystack payment integration for credit pack purchases (NGN one-time payments)
  - `POST /v1/payments/initialize` — create Paystack transaction
  - `GET /v1/payments/verify/{reference}` — verify and credit account
  - `POST /v1/webhooks/paystack` — webhook handler with HMAC-SHA512 verification
- Payment transaction history (`GET /v1/payments/history`)
- Admin manual credit adjustment endpoint (`POST /v1/admin/credits/adjust`)
- Tenacity retry logic for Paystack API calls (3 attempts, exponential backoff)
- Idempotent webhook handling — prevents duplicate credit top-ups
- Payment confirmation emails via Resend on successful charge
- Frontend dashboard payment UI:
  - "Buy Credits" section with Starter/Builder/Agency tiers
  - Payment result feedback on return from Paystack checkout
  - Payment history table with status, amount, credits, and date
- GitHub Pages deployment workflow for frontend dashboard
- 18 new unit tests for payment service (`tests/test_payments.py`)

### Changed
- Updated `schema.sql` to include all tables from migrations 013–015
- Updated `user_profiles` table to include `credits` and `tier` fields
- Updated dashboard stats UI to show credit balance and tier
- Updated `.env.example` with Paystack and admin environment variables

### Fixed
- Re-added `StaticFiles` mount for dev/test environments with correct route precedence
- Fixed Vercel production deployment environment variable validation

## [0.6.0] - 2026-07-14

### Added
- Distributed cache table (`cache_entries`) with RPC functions (`cache_get`, `cache_set`, `cache_delete`, `cache_cleanup`)

## [0.5.0] - 2026-07-14

### Added
- Turnstile support for bot verification
- Spam blocked IPs column

## [0.4.0] - 2026-07-14

### Added
- Email notifications via Resend
- Form validation schema support

## [0.3.0] - 2026-07-14

### Added
- Spam shield (honeypot + UA blocklist + country blocking)
- Rate limiter optimization (UNLOGGED table, single INSERT ... ON CONFLICT)

## [0.2.0] - 2026-07-14

### Added
- Webhook secrets JSONB column for multi-secret rotation
- Standardized API responses with Pydantic models
- Manual replay endpoint for webhook logs

## [0.1.0] - 2026-07-14

### Added
- Initial release
- FastAPI backend with Supabase auth
- Proxy webhook forwarding with rate limiting
- OAuth login (Google/GitHub)
- Frontend dashboard
