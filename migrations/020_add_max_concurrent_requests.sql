-- Add max_concurrent_requests column for per-user parallelism control
-- Applied to existing databases after schema.sql is deployed

alter table public.user_profiles
    add column if not exists max_concurrent_requests integer default 50;

comment on column public.user_profiles.max_concurrent_requests is
    'Maximum number of concurrent proxy requests allowed for this user.';
