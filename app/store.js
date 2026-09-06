/* Data layer. Talks to Supabase when configured, otherwise runs on localStorage
   so the hub is usable the moment Pages is up. Same interface either way, so
   app.js never needs to know which mode it's in. */
(function () {
  var CFG = window.CULTSIDERS_CONFIG || {};
  var LIVE = CFG.SUPABASE_URL && CFG.SUPABASE_URL.indexOf("YOUR_") !== 0;
  var KEY = "cultsiders.local.v1";
  var sb = LIVE ? window.supabase.createClient(CFG.SUPABASE_URL, CFG.SUPABASE_ANON_KEY) : null;

  /* ---- seed -------------------------------------------------------------
     Not filler. These are the real verdicts from the conversation that
     designed this thing, so the generator starts calibrated instead of cold:
     one concept that landed, four that did not, each with its reason. */
  var SEED = {
    ideas: [
      { id: "s1", job: "attention", format: "Comparison", is_wildcard: false, verdict: "pending",
        hook: "i ordered the same shirt from 4 places. one of them made it.",
        happens: "Order the same graphic tee from 4 shops. Film all four landing.",
        you_see: "Four shirts on a table, listing photo held next to each.",
        result: "Three are the same blank from the same supplier. One isn't.",
        needs: "4 orders · ~$85 · 3 weeks", created_at: Date.now() - 120000 },
      { id: "s2", job: "attention", format: "Test", is_wildcard: false, verdict: "pending",
        hook: "ten washes. mine and the $18 one. same machine.",
        happens: "Both shirts through ten cycles. One clip per wash, same frame.",
        you_see: "The two backs side by side, day 1 and day 10.",
        result: "Unknown until you run it. That's why people watch to the end.",
        needs: "the $18 tee · 3 weeks", created_at: Date.now() - 120000 },
      { id: "s3", job: "trust", format: "Packing", is_wildcard: false, verdict: "pending",
        hook: "first package i've ever shipped to the US. i have no idea what i'm doing.",
        happens: "Pack it, write the numbered card, film the post office counter.",
        you_see: "Hands, the card, the label, the receipt.",
        result: "Follow-up clip when it lands, with the real transit time.",
        needs: "one order · nothing else", created_at: Date.now() - 120000 },
      { id: "s4", job: "desire", format: "Recognition", is_wildcard: true, verdict: "pending",
        hook: "i'll show the back for 3 seconds. name the anime.",
        happens: "Three-second reveal, then black. A challenge, not a display.",
        you_see: "The back graphic, once, then gone.",
        result: "The comments answer. That's the payoff and the reach.",
        needs: "the shirt · one take", created_at: Date.now() - 120000 },

      { id: "h1", verdict: "kept", job: "attention", format: "Comparison",
        hook: "i ordered from 5 anime clothing sites. two sent what they showed." },
      { id: "h2", verdict: "discarded", reason: "no_event", job: "desire", format: "Recognition",
        hook: "if you know, you know." },
      { id: "h3", verdict: "discarded", reason: "no_event", job: "desire", format: "On body",
        hook: "oversized. not a tent." },
      { id: "h4", verdict: "discarded", reason: "no_event", job: "attention", format: "Claim",
        hook: "printing the character's face is the easy way out." },
      { id: "h5", verdict: "discarded", reason: "too_explainy", job: "trust", format: "Honest answer",
        hook: "someone asked if this is official one piece merch. it isn't." }
    ],
    inspiration: [
      { id: "i1", saved: false, source: "hashtag", platform: "tiktok", job: "attention",
        url: "", hook_text: "i washed it 30 times so you don't have to",
        structure: "Test", why_it_works: "Outcome unknown at the hook. Product doesn't appear until 0:11.",
        adapt: "Your ten-wash test already matches. Steal the “so you don't have to” framing." },
      { id: "i2", saved: false, source: "creative_center", platform: "tiktok", job: "attention",
        url: "", hook_text: "this is what $12 gets you.",
        structure: "Open loop", why_it_works: "Price in the first four words, no adjectives anywhere.",
        adapt: "The $19 TikTok-ad tee: “this is what $19 and 26 days gets you.”" },
      { id: "i3", saved: false, source: "ad_library", platform: "instagram", job: "desire",
        url: "", hook_text: "no words · fabric in slow motion",
        structure: "No loop", why_it_works: "Running as paid retargeting — works on people who already know the brand.",
        adapt: "Not yet. Park it until people ask to see the fit." },
      { id: "i4", saved: true, saved_for: "hook", source: "pasted", platform: "instagram", job: "trust",
        url: "", hook_text: "i spent 6 months on this hoodie. it sold 3.",
        structure: "Stakes", why_it_works: "Two numbers in the first eight words, one of them bad.",
        adapt: "100 shirts, zero posts. Same admission, and it's true." },
      { id: "i5", saved: true, saved_for: "structure", source: "pasted", platform: "tiktok", job: "attention",
        url: "", hook_text: "don't buy this. i'm serious.",
        structure: "Reverse sell", why_it_works: "Refusing to sell is the curiosity gap.",
        adapt: "“don't buy the $19 one.” Then show why." }
    ],
    queue: [
      { id: "q1", kind: "concept", title: "4 shops, same shirt — which one made it", job: "attention", state: "awaiting" },
      { id: "q2", kind: "concept", title: "Ten washes, mine vs the $18", job: "attention", state: "ready" },
      { id: "q3", kind: "concept", title: "First package to the US", job: "trust", state: "ready" },
      { id: "q4", kind: "shot", title: "Back graphic, daylight, no words", job: "desire", state: "ready" },
      { id: "q5", kind: "shot", title: "Fit on a body, walking and turning", job: "desire", state: "awaiting" },
      { id: "q6", kind: "shot", title: "Print detail, raking light", job: "desire", state: "filmed" }
    ],
    posts: []
  };

  function local() {
    try { var r = localStorage.getItem(KEY); if (r) return JSON.parse(r); } catch (e) {}
    return JSON.parse(JSON.stringify(SEED));
  }
  function persist(d) { try { localStorage.setItem(KEY, JSON.stringify(d)); } catch (e) {} }
  var mem = local();
  var uid = function () { return "x" + Math.random().toString(36).slice(2, 10); };

  /* ---- generation --------------------------------------------------------
     Concepts, not captions: every one carries an event and a result. One in
     four is a wildcard, deliberately off the learned pattern, so the loop
     can't close on itself and keep proposing the last thing that worked. */
  var POOL = [
    { job: "attention", format: "Unbox", hook: "$19 tee from a tiktok ad. 26 days. let's see.",
      happens: "Open it on camera, cold, no rehearsal.", you_see: "The mailer, the shirt, the listing photo next to it.",
      result: "Whether it's the shirt in the ad.", needs: "the package · already ordered" },
    { job: "attention", format: "Claim", hook: "every anime brand uses the same 3 blanks. here they are.",
      happens: "Line up the blanks you sampled, name the supplier.", you_see: "Four white tees, tags out.",
      result: "Three share a supplier code.", needs: "the sample blanks" },
    { job: "trust", format: "Honest answer", hook: "i don't have a return policy yet. writing it now.",
      happens: "Write it on camera, reading what other brands do.", you_see: "Laptop, six tabs, the draft.",
      result: "The policy, published the same day.", needs: "an afternoon" },
    { job: "desire", format: "Detail", hook: "the X is 4cm. drawn once, printed at that size.",
      happens: "Macro pass across the chest print in raking light.", you_see: "Cotton weave and the ink edge.",
      result: "You can see the hand in it.", needs: "the shirt · a window" },
    { job: "attention", format: "Reaction", hook: "someone said my shirt is just a bootleg. let's talk about it.",
      happens: "Read the comment out loud, answer it straight.", you_see: "You, the shirt on, no cuts.",
      result: "The difference between a bootleg and a translation.", needs: "one comment" },
    { job: "desire", format: "In context", hook: "100 of these exist. this is number 1.",
      happens: "The numbered card written by hand, then the shirt folded around it.", you_see: "The card, the pen, the box.",
      result: "Number 1 goes to whoever orders first.", needs: "the cards" },
    { job: "trust", format: "Customer", hook: "first person who isn't me wearing it.",
      happens: "Repost the first tagged photo, react to it.", you_see: "Their photo, your reaction.",
      result: "Proof someone else has one.", needs: "one customer" },
    { job: "attention", format: "Test", hook: "i put it in the dryer on high. everyone says don't.",
      happens: "Do the thing the care label forbids.", you_see: "Before, the dryer, after.",
      result: "How much it actually shrinks.", needs: "one shirt you can lose" }
  ];

  function fabricate(n) {
    var out = [], used = {};
    for (var i = 0; i < n; i++) {
      var p, guard = 0;
      do { p = POOL[Math.floor(Math.random() * POOL.length)]; guard++; } while (used[p.hook] && guard < 40);
      used[p.hook] = 1;
      out.push(Object.assign({}, p, {
        id: uid(), verdict: "pending", created_at: Date.now(),
        is_wildcard: i === n - 1
      }));
    }
    return out;
  }

  async function fn(name, body) {
    var s = await sb.auth.getSession();
    var r = await fetch(CFG.SUPABASE_URL + "/functions/v1/" + name, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + (s.data.session ? s.data.session.access_token : "")
      },
      body: JSON.stringify(body || {})
    });
    if (!r.ok) throw new Error(name + " failed: " + r.status);
    return r.json();
  }

  window.Store = {
    live: LIVE,

    auth: {
      async user() { if (!LIVE) return { email: "local" }; var u = await sb.auth.getUser(); return u.data.user; },
      async signIn(email) { return sb.auth.signInWithOtp({ email: email, options: { emailRedirectTo: location.href } }); },
      async signOut() { if (LIVE) await sb.auth.signOut(); location.reload(); }
    },

    ideas: {
      async pending() {
        if (!LIVE) return mem.ideas.filter(function (i) { return i.verdict === "pending"; });
        var r = await sb.from("ideas").select("*").eq("verdict", "pending").order("created_at", { ascending: false });
        return r.data || [];
      },
      async judged() {
        if (!LIVE) return mem.ideas.filter(function (i) { return i.verdict !== "pending"; });
        var r = await sb.from("ideas").select("job,verdict,reason").neq("verdict", "pending");
        return r.data || [];
      },
      async judge(id, verdict, extra) {
        extra = extra || {};
        if (!LIVE) {
          mem.ideas.forEach(function (i) {
            if (i.id === id) { i.verdict = verdict; i.reason = extra.reason; i.final_hook = extra.final_hook; i.decided_at = Date.now(); }
          });
          persist(mem); return;
        }
        await sb.from("ideas").update({
          verdict: verdict, reason: extra.reason || null,
          final_hook: extra.final_hook || null, decided_at: new Date().toISOString()
        }).eq("id", id);
      },
      async generate(n) {
        n = n || 4;
        if (!LIVE) { var made = fabricate(n); mem.ideas = made.concat(mem.ideas); persist(mem); return made; }
        var res = await fn("generate-ideas", { count: n });
        return res.concepts || [];
      }
    },

    inspiration: {
      async list(saved) {
        if (!LIVE) return mem.inspiration.filter(function (i) { return !!i.saved === saved; });
        var r = await sb.from("inspiration").select("*").eq("saved", saved).order("created_at", { ascending: false });
        return r.data || [];
      },
      async save(id, why) {
        if (!LIVE) {
          mem.inspiration.forEach(function (i) { if (i.id === id) { i.saved = true; i.saved_for = why; } });
          persist(mem); return;
        }
        await sb.from("inspiration").update({ saved: true, saved_for: why }).eq("id", id);
      },
      async analyse(url) {
        if (!LIVE) {
          var row = { id: uid(), url: url, saved: false, source: "pasted", platform: /tiktok/.test(url) ? "tiktok" : "instagram",
            hook_text: "Pending analysis", structure: "—",
            why_it_works: "Connect Supabase and Claude reads the caption, names the structure and writes the adaptation.",
            adapt: "—", job: "attention" };
          mem.inspiration.unshift(row); persist(mem); return row;
        }
        var res = await fn("analyse-inspiration", { url: url });
        return res.item;
      },
      async toIdea(item) {
        var idea = {
          id: uid(), verdict: "pending", created_at: Date.now(), is_wildcard: false,
          job: item.job || "attention", format: item.structure || "Adapted",
          hook: item.adapt || item.hook_text, happens: "Adapted from a saved reference.",
          you_see: "—", result: "—", needs: "—"
        };
        if (!LIVE) { mem.ideas.unshift(idea); persist(mem); return idea; }
        await sb.from("ideas").insert(idea); return idea;
      }
    },

    queue: {
      async all() {
        if (!LIVE) return mem.queue;
        var r = await sb.from("queue").select("*").order("created_at", { ascending: true });
        return r.data || [];
      },
      async add(row) {
        row = Object.assign({ id: uid(), state: "idea" }, row);
        if (!LIVE) { mem.queue.push(row); persist(mem); return row; }
        await sb.from("queue").insert(row); return row;
      },
      async setState(id, state) {
        if (!LIVE) { mem.queue.forEach(function (q) { if (q.id === id) q.state = state; }); persist(mem); return; }
        await sb.from("queue").update({ state: state }).eq("id", id);
      }
    },

    posts: {
      async all() {
        if (!LIVE) return mem.posts;
        var r = await sb.from("posts").select("*,metrics(*)").order("posted_at", { ascending: false });
        return r.data || [];
      },
      async log(row) {
        row = Object.assign({ id: uid(), posted_at: new Date().toISOString() }, row);
        if (!LIVE) { mem.posts.unshift(row); persist(mem); return row; }
        var p = await sb.from("posts").insert({ platform: row.platform, permalink: row.permalink, posted_at: row.posted_at }).select().single();
        await sb.from("metrics").insert({
          post_id: p.data.id, views: row.views, retention_pct: row.retention_pct,
          saves: row.saves, comments: row.comments
        });
        return row;
      }
    },

    reset: function () { try { localStorage.removeItem(KEY); } catch (e) {} location.reload(); }
  };
})();
