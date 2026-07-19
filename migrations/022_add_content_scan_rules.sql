-- Add content_scan_rules column for premium payload scanning
-- Applied to existing databases after schema.sql is deployed

alter table public.routes
    add column if not exists content_scan_rules jsonb default '[]'::jsonb;

comment on column public.routes.content_scan_rules is
    'JSONB array of content scanning rules for premium tiers. Each rule has pattern, field, and action.';
