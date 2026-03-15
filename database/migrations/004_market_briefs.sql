-- Market briefs table for AI trader daily data
create table public.market_briefs (
    id uuid default gen_random_uuid() primary key,
    brief_date date not null unique,
    brief_data jsonb not null,
    created_at timestamptz not null default now()
);

-- No RLS needed - read by backend service only (via admin client)
alter table public.market_briefs enable row level security;

create policy "Service role full access on market_briefs"
    on public.market_briefs for all
    with check (true);
