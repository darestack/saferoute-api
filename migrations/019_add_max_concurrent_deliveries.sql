-- Add max_concurrent_deliveries column for per-route parallelism control
-- Applied to existing databases after schema.sql is deployed

alter table public.routes
    add column if not exists max_concurrent_deliveries integer default 10;

comment on column public.routes.max_concurrent_deliveries is
    'Maximum number of concurrent outbound deliveries allowed for this route.';
