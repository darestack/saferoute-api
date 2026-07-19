-- Add per-route payload size limit column
-- Applied to existing databases after schema.sql is deployed

alter table public.routes
    add column if not exists max_payload_bytes integer default 1048576;

comment on column public.routes.max_payload_bytes is
    'Maximum allowed request body size in bytes for this route. Defaults to 1 MiB (1048576).';
