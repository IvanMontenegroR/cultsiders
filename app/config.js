// Fill these in to go live. Leave them as-is and the hub runs on localStorage
// with seed data, which is enough to use it and to see how it behaves.
//
// The anon key is safe in a public file as long as row level security is on —
// schema.sql turns it on for every table. The Anthropic key is NOT here and
// never should be; it lives in the Edge Function secrets.
window.CULTSIDERS_CONFIG = {
  SUPABASE_URL: "YOUR_SUPABASE_URL",
  SUPABASE_ANON_KEY: "YOUR_SUPABASE_ANON_KEY",
};
