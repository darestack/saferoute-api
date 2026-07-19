-- Add secret_rotation_checks table for tracking secret rotation dates
-- Applied to existing databases after schema.sql is deployed

create table if not exists public.secret_rotation_checks (
    id bigint generated always as identity primary key,
    secret_name text not null unique,
    last_rotated_at timestamp with time zone default timezone('utc'::text, now()) not null,
    owner text,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

create index if not exists idx_secret_rotation_checks_name on public.secret_rotation_checks(secret_name);

alter table public.secret_rotation_checks enable row level security;

drop policy if exists "Service role full access secret_rotation_checks" on public.secret_rotation_checks;
create policy "Service role full access secret_rotation_checks"
    on public.secret_rotation_checks for all
    to service_role
    using (true);
