-- Add webhook_secrets JSONB column for multi-secret rotation support.
--
-- Existing routes store a single secret in `webhook_secret`. The new
-- `webhook_secrets` column holds an array of encrypted secrets, enabling
-- zero-downtime rotation. The application code reads `webhook_secrets` first
-- and falls back to `webhook_secret` for backward compatibility.

ALTER TABLE public.routes
    ADD COLUMN IF NOT EXISTS webhook_secrets jsonb DEFAULT '[]'::jsonb;

-- Backfill existing routes: copy the legacy single secret into the new array
-- so the multi-secret verification path works immediately.
UPDATE public.routes
SET webhook_secrets = jsonb_build_array(webhook_secret)
WHERE webhook_secret IS NOT NULL
  AND webhook_secrets = '[]'::jsonb;
