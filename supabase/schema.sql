-- Cultsiders hub schema
-- Single user. RLS is on everywhere so the public anon key can't read anything
-- without a session.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------- brand voice
-- Voice rules live as EXAMPLES, not adjectives. "short, dry, doesn't explain"
-- produces inconsistent output; fifteen real captions produce consistent output.
create table brand_docs (
  key         text primary key,          -- 'voice' | 'rules' | 'house_codes'
  content     text not null,
  updated_at  timestamptz default now()
);

-- --------------------------------------------------------------------- ideas
create table ideas (
  id          uuid primary key default gen_random_uuid(),
  job         text not null check (job in ('attention','desire','trust')),
  format      text not null,
  hook        text not null,
  happens     text,                      -- what you do
  you_see     text,                      -- what's in frame
  result      text,                      -- the payoff
  needs       text,                      -- cost, time, dependencies
  is_wildcard boolean default false,
  verdict     text default 'pending'
                check (verdict in ('pending','kept','edited','discarded')),
  final_hook  text,                      -- set when edited — the diff is the signal
  reason      text,                      -- 'no_event' | 'too_explainy' | 'not_my_voice'
                                         -- | 'cant_film' | 'too_slow'
  created_at  timestamptz default now(),
  decided_at  timestamptz
);
create index on ideas (verdict, created_at desc);

-- --------------------------------------------------------------- inspiration
create table inspiration (
  id          uuid primary key default gen_random_uuid(),
  url         text not null,
  platform    text,                      -- 'tiktok' | 'instagram'
  source      text default 'pasted'
                check (source in ('pasted','hashtag','creative_center','ad_library')),
  hook_text   text,
  structure   text,                      -- claude's read
  why_it_works text,
  adapt       text,                      -- how it maps to Cultsiders
  job         text check (job in ('attention','desire','trust')),
  saved       boolean default false,     -- false = still in Discover
  saved_for   text,                      -- 'hook' | 'structure' | 'edit' | 'tone'
  created_at  timestamptz default now()
);
create index on inspiration (saved, created_at desc);

-- --------------------------------------------------------------------- queue
create table queue (
  id          uuid primary key default gen_random_uuid(),
  idea_id     uuid references ideas(id) on delete set null,
  kind        text not null check (kind in ('concept','shot')),
  title       text not null,
  job         text check (job in ('attention','desire','trust')),
  state       text default 'idea'
                check (state in ('idea','awaiting','ready','filmed','posted')),
  created_at  timestamptz default now()
);

-- ------------------------------------------------------------------- posts
create table posts (
  id          uuid primary key default gen_random_uuid(),
  queue_id    uuid references queue(id) on delete set null,
  platform    text,
  permalink   text,
  posted_at   timestamptz
);

create table metrics (
  post_id        uuid references posts(id) on delete cascade,
  views          int, retention_pct numeric,
  saves          int, shares int, comments int,
  profile_visits int, link_clicks int,
  captured_at    timestamptz default now(),
  primary key (post_id, captured_at)
);

-- ----------------------------------------------------------------------- RLS
alter table brand_docs  enable row level security;
alter table ideas       enable row level security;
alter table inspiration enable row level security;
alter table queue       enable row level security;
alter table posts       enable row level security;
alter table metrics     enable row level security;

do $$
declare t text;
begin
  foreach t in array array['brand_docs','ideas','inspiration','queue','posts','metrics']
  loop
    execute format(
      'create policy "authenticated only" on %I for all
         to authenticated using (true) with check (true)', t);
  end loop;
end $$;
