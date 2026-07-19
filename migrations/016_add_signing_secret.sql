-- Add signing_secret column for outbound webhook signing
-- Applied to existing databases after schema.sql is deployed

alter table public.routes
    add column if not exists signing_secret text;

comment on column public.routes.signing_secret is
    'Fernet-encrypted secret used to sign outbound webhook deliveries with X-SafeRoute-Signature header.';
