# Changelog

All notable changes to this project will be documented in this file. See [standard-version](https://github.com/conventional-changelog/standard-version) for commit guidelines.

### [0.7.7](https://github.com/darestack/saferoute-api/compare/v0.7.6...v0.7.7) (2026-07-20)


### Bug Fixes

* add changelog, terms, privacy to frontend CSP paths ([e413c74](https://github.com/darestack/saferoute-api/commit/e413c74d1ca1e64276904f394c6252337cac7f18))

### [0.7.6](https://github.com/darestack/saferoute-api/compare/v0.7.5...v0.7.6) (2026-07-20)

### [0.7.5](https://github.com/darestack/saferoute-api/compare/v0.7.4...v0.7.5) (2026-07-20)


### Bug Fixes

* add missing frontend pages, fix routing, CSP, and dead links ([618fc59](https://github.com/darestack/saferoute-api/commit/618fc5953599f096e9a543e6a7bcde9e362776e8))

### [0.7.4](https://github.com/darestack/saferoute-api/compare/v0.7.3...v0.7.4) (2026-07-19)


### Bug Fixes

* remove frontend-dist from Dockerfile to match CI build ([245f8c2](https://github.com/darestack/saferoute-api/commit/245f8c2a70f8d971ba08f31680724a62b795ee6c))

### [0.7.3](https://github.com/darestack/saferoute-api/compare/v0.7.2...v0.7.3) (2026-07-19)


### Bug Fixes

* apply formatting and type ignore for CI compatibility ([748e9e4](https://github.com/darestack/saferoute-api/commit/748e9e43e8c2bd2a9e65062f22a816a9020a0bfc))

### [0.7.2](https://github.com/darestack/saferoute-api/compare/v0.7.1...v0.7.2) (2026-07-19)


### Bug Fixes

* resolve GitHub Actions failures and update dependencies ([cb7fdef](https://github.com/darestack/saferoute-api/commit/cb7fdef44184712d72390fbc8b23a55a95a4d9d5))

### [0.7.1](https://github.com/darestack/saferoute-api/compare/v0.7.0...v0.7.1) (2026-07-19)


### Features

* add monitoring, payments, CAPTCHA fallback, signing, IP allowlist ([f6fcd90](https://github.com/darestack/saferoute-api/commit/f6fcd90b94815dc20c61355b4355db08670b8f12))
* add multi-currency support with USD base pricing ([56c7db3](https://github.com/darestack/saferoute-api/commit/56c7db37a73cb04c338895550a62904040e759f9))
* add root endpoint with API info and links ([b456cd4](https://github.com/darestack/saferoute-api/commit/b456cd4b3707e4aa90b27d61fc2099159708b21b))
* expose signing secrets, IP allowlist, and route limits in frontend ([da470e8](https://github.com/darestack/saferoute-api/commit/da470e821fb019a930014ec95fe4da3658eb6e6e))
* **frontend:** migrate to Vite + TypeScript SPA architecture ([8e093f1](https://github.com/darestack/saferoute-api/commit/8e093f19a7476e3253e510d8110d9effcbab3d03))
* implement four priority platform improvements ([f9816f3](https://github.com/darestack/saferoute-api/commit/f9816f3401ca5f8e3dc2b51644388dac5131cfb7))
* implement sprints 0-4 safety, security, scalability, and tech debt improvements ([a05eb13](https://github.com/darestack/saferoute-api/commit/a05eb13e4781a05ee28a2ae1d39c12e6cd452177))
* improve frontend type safety and chart data ([b042815](https://github.com/darestack/saferoute-api/commit/b042815a7e077776e350c0f2276152a96df4e1fa))


### Bug Fixes

* add missing signing utilities and tests ([d14aae1](https://github.com/darestack/saferoute-api/commit/d14aae16fd93688f21b5fd528177898f564a2893))
* add root lock file and install frontend deps in build ([d290acc](https://github.com/darestack/saferoute-api/commit/d290acc131750bbb31914b49243a77b85fa9da53))
* add runtime dependencies to pyproject.toml for Vercel ([369241b](https://github.com/darestack/saferoute-api/commit/369241b6315c8189fd5bda19ad2ac6d5d50c8a73))
* allow X-Admin-Secret for admin IP endpoints and secure frontend admin UI ([0c1a251](https://github.com/darestack/saferoute-api/commit/0c1a2519c7fb2385ef8ab13b35045ac5a3db9c1b))
* always serve index.html from root in production ([db61af7](https://github.com/darestack/saferoute-api/commit/db61af7fb97d035f45579291dd7d95561bfa0832))
* backend security and code quality improvements ([0c1a6bb](https://github.com/darestack/saferoute-api/commit/0c1a6bb37b43bc626bcc4a5795bc515b042a01e1))
* **backend:** remediate critical correctness, security, and dead-code issues (batch 1) ([a9a2c9a](https://github.com/darestack/saferoute-api/commit/a9a2c9ab2f35f4ca035453dc2d7652be681fd7d0))
* **backend:** security hardening and ownership checks ([4ab14bf](https://github.com/darestack/saferoute-api/commit/4ab14bfdcf435bda0af8a1db6bd95a9c628d56ed))
* build frontend in CI and configure standard-version ([29103c8](https://github.com/darestack/saferoute-api/commit/29103c8a2b64d056b69e8e52241c51a5f347cb79))
* configure setuptools packages in pyproject.toml ([86882cf](https://github.com/darestack/saferoute-api/commit/86882cf0c19b46de0f1ecbce90b1376e3eb67ef2))
* correct OpenTelemetry test assertion ([33e69c5](https://github.com/darestack/saferoute-api/commit/33e69c57d7eea48e7e18b3079d6b181297548a06))
* credit-accounting integrity for replay, webhook, and verify flows ([a38787b](https://github.com/darestack/saferoute-api/commit/a38787bdcfe8376d2b9ba839e5e579df1d73b1ec))
* harden /rates error semantics, unify proxy URL, make rate tests offline ([10ac500](https://github.com/darestack/saferoute-api/commit/10ac500bca400e574cfe78d78f270c6410f6ad5d))
* include all app subpackages in wheel ([84a9bb4](https://github.com/darestack/saferoute-api/commit/84a9bb4b1150f663c5ec91dfae8b4fefaf18b70d))
* move frontend build output to app/public for Vercel deployment ([5287b6a](https://github.com/darestack/saferoute-api/commit/5287b6a82181cb54a96ef8847ccadef3246036aa))
* move frontend build to public/ root for Vercel static serving ([4669b71](https://github.com/darestack/saferoute-api/commit/4669b71bf4b1cf9702379b24d1dd3142a1342c38))
* populate logs/stats, expand route form, fix docs ([686087b](https://github.com/darestack/saferoute-api/commit/686087b8dada4a2b27560ab921552bc1f7ab039f))
* resolve GitHub Actions failures ([e3a29ee](https://github.com/darestack/saferoute-api/commit/e3a29ee84a299b1f6fd2de6e6f286acad92d93aa))
* resolve test failures from backend PR cherry-pick ([26b6f0b](https://github.com/darestack/saferoute-api/commit/26b6f0bb9f04c4e9da8ca224f9f4cc1358445d4d))
* route all requests to Python function on Vercel ([95e7bc6](https://github.com/darestack/saferoute-api/commit/95e7bc6b4d67cf9ca4b516b3113f80defecdec73))
* route API requests to Python function in Vercel ([0399cf4](https://github.com/darestack/saferoute-api/commit/0399cf4be0ba5848722179f764e7191c46fb8cff))
* search multiple paths for public/ in Vercel Lambda ([48e36b6](https://github.com/darestack/saferoute-api/commit/48e36b694928995affbb135f8b1e7c7d93fbe6dd))
* serve frontend index.html from root endpoint in production ([666229b](https://github.com/darestack/saferoute-api/commit/666229bd00591b80f1abd136467936cb2d4d7f16))
* update dashboard URL in README to Vercel ([e15c04f](https://github.com/darestack/saferoute-api/commit/e15c04f24e39304d0acdd870470a31a71add9cf3))
* update public path references to app/public ([52d810d](https://github.com/darestack/saferoute-api/commit/52d810da1158c7b5a0b553ccc1b91e9f13eb36d5))
* use API_BASE for all remaining hardcoded API calls ([04f6511](https://github.com/darestack/saferoute-api/commit/04f65117ec7f21ebf64978caa0afe71718eefc6f))
* use SPDX license string in pyproject.toml ([4d3ad09](https://github.com/darestack/saferoute-api/commit/4d3ad099e7a85a5fce8bf66e2e8f15d8d3521cd0))
* use VITE_API_BASE for OAuth and callback endpoints ([7bda6e9](https://github.com/darestack/saferoute-api/commit/7bda6e9d7d346fc3fb6f90af3b3787450844044d))
* wait for webhook retry button before asserting visibility ([ee4f82e](https://github.com/darestack/saferoute-api/commit/ee4f82e86167e4d33a997a245391420838d3b01a))

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
