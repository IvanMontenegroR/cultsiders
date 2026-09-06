# Cultsiders Hub

Internal content tool. Generates video concepts, learns from what gets kept and
discarded, keeps a library of real reference videos, and tracks what still needs
filming.

Static front end on GitHub Pages, Postgres + Auth + Edge Functions on Supabase,
Claude for generation. Nothing runs on a server you maintain.

## Why it exists

The bottleneck is not writing captions. It is sitting down on a Saturday with a
blank page. The hub answers "what do I film" before you ask, and the generator
gets closer to your voice every time you judge an idea.

## It works before you configure anything

Open it and it runs in **local mode**: seed data in `localStorage`, no Supabase,
no Claude, no account. Everything is clickable — judge ideas, save references,
move things through the queue. Fill in `app/config.js` and the same interface
switches to live data with no other change.

## Layout

```
index.html                                 shell
app/styles.css                             all styles
app/config.js                              <- your Supabase URL and anon key
app/store.js                               data layer; Supabase or localStorage
app/app.js                                 rendering and events
assets/                                    logos
supabase/schema.sql                        tables, RLS, seeded voice
supabase/functions/generate-ideas/         concepts, weighted by your verdicts
supabase/functions/analyse-inspiration/    breaks down a pasted link
```

## Going live

1. **Pages** — Settings → Pages → deploy from `main`, root.
2. **Supabase** — new project, run `supabase/schema.sql` in the SQL editor.
3. **Secrets** — `supabase secrets set ANTHROPIC_API_KEY=sk-ant-...`
   The Anthropic key lives only in the Edge Functions. It must never appear in
   `app/config.js`, which is public.
4. **Functions** — `supabase functions deploy generate-ideas` and
   `supabase functions deploy analyse-inspiration`
5. **Config** — put your project URL and **anon** key in `app/config.js`. The
   anon key is safe to publish because `schema.sql` turns row level security on
   for every table; without a session it reads nothing.

## The three jobs

Every concept does one of three things. Drift too far toward attention and you
get traffic without customers, which is why the hub measures the mix and leans
the next batch toward whichever job is thinnest.

| Job | Brings | Formats |
|---|---|---|
| Attention | strangers | unbox, test, comparison, claim, reaction |
| Desire | wanting the shirt | on body, detail, in context, recognition |
| Trust | the sale | packing, customer, honest answer |

## How the loop learns

Every verdict is stored. The next generation gets the last ~20 keeps, the last
~20 discards **with their reason**, and every edit as a before → after pair.

The edits teach most. A keep says "fine". An edit says exactly what was wrong
and what right looks like.

This is few-shot in the prompt, not fine-tuning: it improves quickly over the
first ~50 verdicts and then plateaus. **One in four concepts is a wildcard**,
deliberately outside the learned pattern, because a pure keep/discard loop
converges on the last thing that worked and stops surprising you.

## What it will not do

- Crawl Instagram or TikTok feeds. Against their terms and heavily blocked.
  Discovery comes from Meta's Hashtag Search API, the TikTok Creative Center,
  the Meta Ad Library, or from links you paste. Embedding is allowed; scraping
  is not.
- Predict virality. It lowers the cost of each attempt so you can post three
  times a week for a year. That is the whole mechanism.
- Propose transformation or making-of concepts (you don't draw the designs),
  counts, or ambient pieces. Those rules are written into the prompt.
