-- Add AI trader fields to profiles
alter table public.profiles
    add column is_ai boolean not null default false,
    add column ai_model text default null;

-- Index for filtering by AI status
create index idx_profiles_is_ai on public.profiles(is_ai);

-- Drop the old leaderboard view (no longer used, scoring is now in app code)
drop view if exists public.leaderboard;
