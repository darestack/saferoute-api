-- Add Cloudflare Turnstile support to routes table.
--
-- turnstile_enabled: Whether Turnstile verification is required for this route.
-- turnstile_site_key: Public site key for the Turnstile widget.
-- turnstile_secret_key: Secret key for server-side verification.

ALTER TABLE public.routes
    ADD COLUMN IF NOT EXISTS turnstile_enabled boolean DEFAULT false,
    ADD COLUMN IF NOT EXISTS turnstile_site_key text,
    ADD COLUMN IF NOT EXISTS turnstile_secret_key text;
