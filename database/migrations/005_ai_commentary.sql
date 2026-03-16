-- AI commentary: daily blog posts from each AI trader explaining their decisions
create table public.ai_commentary (
    id uuid default gen_random_uuid() primary key,
    user_id uuid not null references auth.users(id),
    commentary_date date not null,
    display_name text not null,
    personality text not null,
    model text not null,
    commentary text not null,
    trades_summary jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    unique(user_id, commentary_date)
);

-- Index for fast lookups by date
create index idx_ai_commentary_date on public.ai_commentary(commentary_date desc);

-- RLS: read-only for everyone, write via service role
alter table public.ai_commentary enable row level security;

create policy "Anyone can read AI commentary"
    on public.ai_commentary for select
    using (true);

create policy "Service role full access on ai_commentary"
    on public.ai_commentary for all
    with check (true);
