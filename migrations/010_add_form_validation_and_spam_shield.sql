-- Add form validation and spam shield columns to routes table.
--
-- form_schema: JSONB schema defining required fields, types, and constraints.
-- spam_honeypot_field: Name of the honeypot field to check for spam.
-- spam_blocked_ua: Array of blocked User-Agent substrings.
-- spam_allowed_countries: Array of allowed country codes (empty = all allowed).
-- email_notifications: JSONB config for email delivery (enabled, to, subject).

ALTER TABLE public.routes
    ADD COLUMN IF NOT EXISTS form_schema jsonb DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS spam_honeypot_field text,
    ADD COLUMN IF NOT EXISTS spam_blocked_ua text[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS spam_allowed_countries text[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS email_notifications jsonb DEFAULT '{}'::jsonb;
