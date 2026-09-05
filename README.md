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

## Layout

```
index.html                            the hub (GitHub Pages serves this)
assets/                               logo files — see assets/README.md
supabase/schema.sql                   tables + row level security
supabase/functions/generate-ideas/    edge function that calls Claude
```

## Setup

**1. Pages.** Settings → Pages → deploy from `main`, root. The hub is live at
`ivanmontenegror.github.io/cultsiders`.

**2. Supabase.** New project, then run `supabase/schema.sql` in the SQL editor.

**3. Secrets.** `supabase secrets set ANTHROPIC_API_KEY=sk-ant-...`
The key lives only in the Edge Function. It must never appear in `index.html` —
this page is public.

**4. Deploy the function.** `supabase functions deploy generate-ideas`

**5. Wire the front end.** Add your Supabase URL and anon key in `index.html`,
and swap the hardcoded sample cards for a fetch. The anon key is safe to publish
as long as RLS is on, which `schema.sql` sets up.

## The three jobs

Every concept does one of three things. If the mix drifts too far toward
attention you get traffic and no customers, which is why the hub measures it.

| Job | Brings | Formats |
|---|---|---|
| Attention | strangers | unbox, test, comparison, claim, reaction |
| Desire | wanting the shirt | on body, detail, in context, recognition |
| Trust | the sale | packing, customer, honest answer |

## How the loop learns

Every verdict is stored. The next generation gets the last ~20 keeps, the last
~20 discards **with their reason**, and every edit as a before → after pair. The
edits teach most: a keep says "fine", an edit says exactly what was wrong.

This is few-shot in the prompt, not fine-tuning. It improves fast for the first
~50 verdicts and then plateaus.

**One in four generated concepts is a wildcard** — deliberately outside the
learned pattern. Without it the loop closes on itself and only ever proposes the
last thing that worked.
