-- ============================================================
-- Trixa v2: Subscriptions + Daily Message Counts
-- Kör i Supabase SQL Editor EFTER setup_db.sql
-- ============================================================

-- Subscriptions table
create table if not exists public.subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  tier text not null default 'free',
  status text not null default 'trialing',
  stripe_customer_id text,
  stripe_subscription_id text,
  trial_ends_at timestamptz,
  current_period_end timestamptz,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique(user_id)
);

-- Daily message counts for rate limiting
create table if not exists public.daily_message_counts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  message_date date not null default current_date,
  count integer not null default 0,
  unique(user_id, message_date)
);

-- Enable RLS
alter table public.subscriptions enable row level security;
alter table public.daily_message_counts enable row level security;

-- Subscriptions: users can read their own
create policy "Users can read own subscription"
  on public.subscriptions for select
  using (auth.uid() = user_id);

-- Daily message counts: users can read and upsert their own
create policy "Users can read own message counts"
  on public.daily_message_counts for select
  using (auth.uid() = user_id);

create policy "Users can insert own message counts"
  on public.daily_message_counts for insert
  with check (auth.uid() = user_id);

create policy "Users can update own message counts"
  on public.daily_message_counts for update
  using (auth.uid() = user_id);

-- Auto-update updated_at on subscriptions
create trigger update_subscriptions_updated_at
  before update on public.subscriptions
  for each row execute function update_updated_at();

-- Modify handle_new_user to also create a subscription row
create or replace function public.handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id, name, email)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'name', ''),
    new.email
  );
  insert into public.subscriptions (user_id, tier, status, trial_ends_at)
  values (
    new.id,
    'free',
    'trialing',
    now() + interval '30 days'
  );
  return new;
end;
$$ language plpgsql security definer;

-- Create subscription rows for existing users that don't have one
insert into public.subscriptions (user_id, tier, status, trial_ends_at)
select id, 'free', 'trialing', now() + interval '30 days'
from auth.users
where id not in (select user_id from public.subscriptions);
