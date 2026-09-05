// Generates video concepts in Ivan's voice, weighted by what he has kept and
// discarded. Deploy: supabase functions deploy generate-ideas
//
// The API key lives here and only here. index.html is public.

import Anthropic from "npm:@anthropic-ai/sdk";
import { createClient } from "npm:@supabase/supabase-js";

const anthropic = new Anthropic(); // reads ANTHROPIC_API_KEY

const JOBS = `
Every concept does exactly one job:
  attention — brings strangers (unbox, test, comparison, claim, reaction)
  desire    — makes someone want the shirt (on body, detail, in context, recognition)
  trust     — closes the sale (packing, customer, honest answer)
`;

const RULES = `
A concept is not a caption. It must contain an EVENT and a RESULT.
"if you know, you know" is a caption and gets discarded every time.
"i ordered from 5 sites, two sent what they showed" is a concept.

Never propose:
  - transformation / making-of (he does not draw the designs himself)
  - counts and listicles
  - ambient or texture-only pieces
  - anything he cannot film alone, on a phone, on a weekend

Voice: lowercase, short, no adjectives, no hype, never explains the joke.
US English, native register.
`;

Deno.serve(async (req) => {
  const auth = req.headers.get("Authorization");
  if (!auth) return new Response("unauthorized", { status: 401 });

  const db = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_ANON_KEY")!,
    { global: { headers: { Authorization: auth } } },
  );

  const { data: user } = await db.auth.getUser();
  if (!user?.user) return new Response("unauthorized", { status: 401 });

  const { count = 4 } = await req.json().catch(() => ({}));

  const [voice, kept, discarded, edited, saved] = await Promise.all([
    db.from("brand_docs").select("content").eq("key", "voice").single(),
    db.from("ideas").select("job,format,hook").eq("verdict", "kept")
      .order("decided_at", { ascending: false }).limit(20),
    db.from("ideas").select("hook,reason").eq("verdict", "discarded")
      .order("decided_at", { ascending: false }).limit(20),
    db.from("ideas").select("hook,final_hook").eq("verdict", "edited")
      .order("decided_at", { ascending: false }).limit(10),
    db.from("inspiration").select("hook_text,structure,saved_for")
      .eq("saved", true).order("created_at", { ascending: false }).limit(20),
  ]);

  // Stable first, volatile after — so adding one swipe entry doesn't blow the
  // whole cache. Check usage.cache_read_input_tokens; zero means something
  // upstream is changing between calls.
  const system = [
    { type: "text" as const,
      text: `${JOBS}\n${RULES}\n\nVOICE\n${voice.data?.content ?? ""}`,
      cache_control: { type: "ephemeral" as const } },
    { type: "text" as const,
      text:
        `KEPT — write more like these:\n` +
        (kept.data ?? []).map((i) => `- [${i.job}/${i.format}] ${i.hook}`).join("\n") +
        `\n\nDISCARDED — and why:\n` +
        (discarded.data ?? []).map((i) => `- ${i.hook}  → ${i.reason}`).join("\n") +
        `\n\nEDITED — he rewrote mine into his. Learn this transformation:\n` +
        (edited.data ?? []).map((i) => `- mine: ${i.hook}\n  his:  ${i.final_hook}`).join("\n") +
        `\n\nREFERENCES he saved:\n` +
        (saved.data ?? []).map((i) => `- "${i.hook_text}" (${i.structure}) — kept for the ${i.saved_for}`).join("\n"),
      cache_control: { type: "ephemeral" as const } },
  ];

  const res = await anthropic.messages.create({
    model: "claude-opus-5",
    max_tokens: 4000,
    system,
    messages: [{
      role: "user",
      content:
        `Generate ${count} concepts. One must be a wildcard: deliberately outside ` +
        `the kept pattern, flagged is_wildcard. Weight the rest toward whichever ` +
        `job is underrepresented in KEPT.\n\n` +
        `Return JSON: [{job, format, hook, happens, you_see, result, needs, is_wildcard}]`,
    }],
  });

  const text = res.content.find((b) => b.type === "text");
  const concepts = JSON.parse(text && "text" in text ? text.text : "[]");

  await db.from("ideas").insert(concepts);

  return new Response(JSON.stringify({
    concepts,
    usage: {
      cache_read: res.usage.cache_read_input_tokens,
      input: res.usage.input_tokens,
      output: res.usage.output_tokens,
    },
  }), { headers: { "Content-Type": "application/json" } });
});
