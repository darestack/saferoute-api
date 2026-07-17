-- Add credit-based user profiles table.
--
-- Supabase Auth manages auth.users; this table stores app-level credit
-- balance and tier for each authenticated user.

-- ========================================
-- User Profiles Table
-- ========================================
create table public.user_profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    credits integer not null default 100,
    tier text not null default 'free',
    created_at timestamp with time zone default timezone('utc'::text, now()) not null,
    updated_at timestamp with time zone default timezone('utc'::text, now()) not null
);

-- Index for fast lookups by user id
create index idx_user_profiles_id on public.user_profiles(id);

alter table public.user_profiles enable row level security;

-- Users can view their own profile
create policy "Users can view own profile"
    on public.user_profiles for select
    to authenticated
    using (auth.uid() = id);

-- Users can update their own profile
create policy "Users can update own profile"
    on public.user_profiles for update
    to authenticated
    using (auth.uid() = id)
    with check (auth.uid() = id);

-- Service role full access (for backend credit operations)
create policy "Service role full access user_profiles"
    on public.user_profiles for all
    to service_role
    using (true);

-- ========================================
-- Triggers
-- ========================================
create trigger update_user_profiles_updated_at
    before update on public.user_profiles
    for each row
    execute function public.update_updated_at();

-- ========================================
-- Helper Functions
-- ========================================
-- Atomically deduct credits from a user's profile.
-- Returns true if deduction succeeded, false if insufficient credits.
create or replace function public.deduct_user_credits(
    p_user_id uuid,
    p_amount integer default 1
)
returns boolean as $$
declare
    v_current_credits integer;
begin
    select credits into v_current_credits
    from public.user_profiles
    where id = p_user_id
    for update;

    if v_current_credits is null then
        -- Profile doesn't exist yet; create with default 100 credits
        insert into public.user_profiles (id, credits, tier)
        values (p_user_id, 100, 'free')
        on conflict (id) do nothing;
        v_current_credits := 100;
    end if;

    if v_current_credits >= p_amount then
        update public.user_profiles
        set credits = credits - p_amount
        where id = p_user_id;
        return true;
    else
        return false;
    end if;
end;
$$ language plpgsql;
