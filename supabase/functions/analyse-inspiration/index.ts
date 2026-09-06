// Takes a TikTok or Reel URL, pulls the public oEmbed metadata, and has Claude
// name the structure and write the adaptation. Discovery is the user's own or
// comes from public libraries — this never crawls a feed.
//
// Deploy: supabase functions deploy analyse-inspiration

import Anthropic from "npm:@anthropic-ai/sdk";
import { createClient } from "npm:@supabase/supabase-js";

const anthropic = new Anthropic();

// Official oEmbed endpoints. Embedding is allowed; scraping is not.
const OEMBED: Record<string, string> = {
  tiktok: "https://www.tiktok.com/oembed?url=",
  instagram: "https://api.instagram.com/oembed?url=", // needs a token in prod
};

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

  const { url } = await req.json();
  const platform = url.includes("tiktok") ? "tiktok" : "instagram";

  let caption = "";
  try {
    const r = await fetch(OEMBED[platform] + encodeURIComponent(url));
    if (r.ok) caption = (await r.json()).title ?? "";
  } catch { /* best-effort: Claude still reads the URL */ }

  const res = await anthropic.messages.create({
    model: "claude-opus-5",
    max_tokens: 1200,
    system: `You break down short-form video for a small anime streetwear brand
run by one person in Paraguay, selling to the US, filming alone on a phone at
weekends. He does not draw his own designs.

Name the STRUCTURE (open loop / test / comparison / claim / reaction / stakes /
reverse sell / no loop), say in one sentence WHY IT HOLDS attention, and write
ADAPT: how he could do the same thing with what he actually has — 100 cream
tees, packages arriving from cheap anime shops, and no audience yet.

Voice for the adaptation: lowercase, short, no adjectives, no explaining.
Assign one JOB: attention, desire, or trust.`,
    messages: [{
      role: "user",
      content: `URL: ${url}\nCaption: ${caption || "(not available)"}\n\n` +
        `Return JSON: {hook_text, structure, why_it_works, adapt, job}`,
    }],
  });

  const block = res.content.find((b) => b.type === "text");
  const parsed = JSON.parse(block && "text" in block ? block.text : "{}");

  const row = { ...parsed, url, platform, source: "pasted", saved: false };
  const { data } = await db.from("inspiration").insert(row).select().single();

  return new Response(JSON.stringify({ item: data ?? row }), {
    headers: { "Content-Type": "application/json" },
  });
});
