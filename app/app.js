/* UI. Reads and writes through Store, which hides whether we're on Supabase or
   localStorage. */
(function () {
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var esc = function (s) { return String(s == null ? "" : s).replace(/[<>&"]/g, function (c) {
    return { "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;" }[c]; }); };

  var REASONS = [["no_event","No event"],["too_explainy","Too explainy"],["not_my_voice","Not my voice"],["cant_film","Can't film it"],["too_slow","Too slow"]];
  var WHYS = [["hook","The hook"],["structure","The structure"],["edit","The edit"],["tone","The tone"]];
  var STATES = ["idea","awaiting","ready","filmed","posted"];
  var SLABEL = { idea:"Idea", awaiting:"Waiting", ready:"Ready", filmed:"Filmed", posted:"Posted" };
  var VIEWS = {
    ideas:["Ideas","Keep, edit or discard. Every choice trains the next batch."],
    inspo:["Inspiration","Real videos, broken down into what you could copy."],
    queue:["Queue","Concepts to film, shots to capture."],
    stats:["Metrics","Entered by hand until Instagram is connected."]
  };

  var state = { view:"ideas", filter:"all", inspoTab:"discover" };

  function toast(msg) {
    var t = $("#toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(t._t); t._t = setTimeout(function(){ t.classList.remove("show"); }, 2200);
  }
  var ico = {
    yes:'<svg viewBox="0 0 24 24"><path d="M20 6L9 17l-5-5"/></svg>',
    ed:'<svg viewBox="0 0 24 24"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>',
    no:'<svg viewBox="0 0 24 24"><path d="M18 6L6 18M6 6l12 12"/></svg>'
  };

  /* ------------------------------------------------------------- ideas */
  function conceptRow(k, v) { return v ? '<dt>'+k+'</dt><dd>'+esc(v)+'</dd>' : ''; }

  function ideaCard(i) {
    return '<article class="card'+(i.is_wildcard?' wild':'')+'" data-id="'+i.id+'" data-job="'+esc(i.job)+'">'
      + '<div class="chead"><span class="job '+esc(i.job)+'">'+esc(i.job)+'</span>'
      + '<span class="fmt">'+esc(i.format)+'</span>'
      + (i.is_wildcard?'<span class="wc">Wildcard</span>':'')
      + '<span class="when">new</span></div>'
      + '<dl class="concept"><dt>Hook</dt><dd class="hook">'+esc(i.hook)+'</dd>'
      + conceptRow("Happens", i.happens) + conceptRow("You see", i.you_see)
      + conceptRow("Result", i.result) + conceptRow("Needs", i.needs) + '</dl>'
      + '<div class="acts"><button class="yes">'+ico.yes+'Keep</button>'
      + '<button class="ed">'+ico.ed+'Edit</button>'
      + '<button class="no">'+ico.no+'Discard</button></div>'
      + '<div class="reasons"><span class="q">Why not?</span>'
      + REASONS.map(function(r){return '<button data-r="'+r[0]+'">'+r[1]+'</button>';}).join("")
      + '</div>'
      + '<div class="editor"><textarea>'+esc(i.hook)+'</textarea>'
      + '<div class="row"><button class="btn solid save">Save edit</button>'
      + '<span class="hint">The change teaches more than a keep.</span></div></div></article>';
  }

  function mixBlock(judged) {
    var kept = judged.filter(function(j){return j.verdict==="kept"||j.verdict==="edited";});
    var n = kept.length || 1;
    var c = { attention:0, desire:0, trust:0 };
    kept.forEach(function(k){ if (c[k.job]!=null) c[k.job]++; });
    var pct = function(x){ return Math.round(c[x]/n*100); };
    var low = ["attention","desire","trust"].sort(function(a,b){return c[a]-c[b];})[0];
    var reasons = {};
    judged.filter(function(j){return j.verdict==="discarded"&&j.reason;})
      .forEach(function(j){ reasons[j.reason]=(reasons[j.reason]||0)+1; });
    var top = Object.keys(reasons).sort(function(a,b){return reasons[b]-reasons[a];})[0];
    var note = kept.length < 3
      ? 'Not enough verdicts yet. Judge a few and the generator starts following your pattern.'
      : 'Weakest job is <b>'+low+'</b>, so the next batch leans there.'
        + (top ? ' Most common rejection: <b>'+(REASONS.filter(function(r){return r[0]===top;})[0]||["","—"])[1].toLowerCase()+'</b> ×'+reasons[top]+'.' : '');
    return '<div class="mix"><div class="mixhead"><b>Mix of what you kept</b>'
      + '<span>'+kept.length+' kept · '+judged.length+' judged</span></div>'
      + '<div class="bars">'
      + '<i style="background:var(--att);width:'+pct("attention")+'%"></i>'
      + '<i style="background:var(--des);width:'+pct("desire")+'%"></i>'
      + '<i style="background:var(--tru);width:'+pct("trust")+'%"></i></div>'
      + '<div class="legend">'
      + '<span><i style="background:var(--att)"></i>Attention '+pct("attention")+'%</span>'
      + '<span><i style="background:var(--des)"></i>Desire '+pct("desire")+'%</span>'
      + '<span><i style="background:var(--tru)"></i>Trust '+pct("trust")+'%</span></div>'
      + '<div class="warn">'+note+'</div></div>';
  }

  async function renderIdeas() {
    var host = $('[data-view="ideas"]');
    host.innerHTML = '<div class="skel">Loading…</div>';
    var pending = await Store.ideas.pending();
    var judged = await Store.ideas.judged();
    var cards = pending.filter(function(i){ return state.filter==="all" || i.job===state.filter; });
    host.innerHTML = mixBlock(judged)
      + '<div class="filters" id="filters">'
      + [["all","All"],["attention","Attention"],["desire","Desire"],["trust","Trust"]].map(function(f){
          return '<button aria-pressed="'+(state.filter===f[0])+'" data-f="'+f[0]+'">'+f[1]+'</button>'; }).join("")
      + '</div>'
      + '<div class="feed">'
      + (cards.length ? cards.map(ideaCard).join("")
        : '<div class="empty">Nothing pending. Hit Generate.</div>')
      + '</div>';
    $("#navIdeas .cnt").textContent = pending.length;
  }

  /* ------------------------------------------------------- inspiration */
  function inspCard(i) {
    var head = i.url
      ? '<a href="'+esc(i.url)+'" target="_blank" rel="noopener">'+esc(i.hook_text)+'</a>'
      : esc(i.hook_text);
    var srcLabel = i.saved ? "Saved for: " + esc(i.saved_for || "—")
      : ({ hashtag:"#hashtag search", creative_center:"Creative Center", ad_library:"Ad Library", pasted:"Pasted" }[i.source] || "Discovered");
    return '<div class="ic'+(i.saved?' saved':'')+'" data-id="'+i.id+'">'
      + '<div class="embed"><div><div class="p">'+esc(i.platform||"")+'</div><div class="h">'+head+'</div></div></div>'
      + '<div class="icb"><div class="meta"><span class="src">'+srcLabel+'</span>'
      + (i.job?'<span class="job '+esc(i.job)+'">'+esc(i.job)+'</span>':'')+'</div>'
      + '<div class="dec"><b>'+esc(i.structure)+'.</b> '+esc(i.why_it_works)+'</div>'
      + '<div class="adapt"><b>Adapt</b>'+esc(i.adapt)+'</div>'
      + '<div class="icfoot">'
      + (i.saved?'':'<button class="btn sm savebtn">Save</button>')
      + '<button class="btn sm toidea">Turn into idea</button></div>'
      + '<div class="savewhy">'+WHYS.map(function(w){return '<button data-w="'+w[0]+'">'+w[1]+'</button>';}).join("")+'</div>'
      + '</div></div>';
  }

  async function renderInspo() {
    var host = $('[data-view="inspo"]');
    host.innerHTML = '<div class="skel">Loading…</div>';
    var saved = state.inspoTab === "saved";
    var items = await Store.inspiration.list(saved);
    var savedCount = (await Store.inspiration.list(true)).length;
    host.innerHTML = '<div class="tabs" id="itabs">'
      + '<button aria-pressed="'+(!saved)+'" data-i="discover">Discover</button>'
      + '<button aria-pressed="'+saved+'" data-i="saved">Saved <span style="opacity:.6">'+savedCount+'</span></button>'
      + '</div>'
      + (saved ? '' :
        '<div class="srcbar"><input type="text" id="inspUrl" placeholder="Paste a TikTok or Reel link">'
        + '<button class="btn solid" id="analyse">Analyse</button></div>')
      + '<div class="insp">'
      + (items.length ? items.map(inspCard).join("")
        : '<div class="empty">'+(saved?'Nothing saved yet. Save from Discover and it lands here.':'Nothing to discover. Paste a link.')+'</div>')
      + '</div>';
    $("#navInspo .cnt").textContent = savedCount;
  }

  /* --------------------------------------------------------------- queue */
  async function renderQueue() {
    var rows = await Store.queue.all();
    $('[data-view="queue"]').innerHTML = '<div class="tw"><table>'
      + '<thead><tr><th>Item</th><th>Type</th><th>Job</th><th>State</th></tr></thead><tbody>'
      + rows.map(function (q) {
          return '<tr><td>'+esc(q.title)+'</td><td>'+esc(q.kind==="shot"?"Shot":"Concept")+'</td>'
            + '<td><span class="job '+esc(q.job)+'">'+esc((q.job||"").slice(0,3))+'</span></td>'
            + '<td><button class="pill" data-q="'+q.id+'" data-s="'+esc(q.state)+'">'+SLABEL[q.state]+'</button></td></tr>';
        }).join("")
      + '</tbody></table></div>'
      + '<div class="empty" style="margin-top:14px">Concepts get generated. Shots just get checked off.</div>';
    $("#navQueue .cnt").textContent = rows.filter(function(q){return q.state!=="posted";}).length;
  }

  /* --------------------------------------------------------------- stats */
  async function renderStats() {
    var judged = await Store.ideas.judged();
    var q = await Store.queue.all();
    var posts = await Store.posts.all();
    var saved = await Store.inspiration.list(true);
    var kept = judged.filter(function(j){return j.verdict==="kept"||j.verdict==="edited";}).length;
    var cards = [
      ["Posted", posts.length, posts.length ? "logged by hand" : "nothing yet"],
      ["Kept", kept, "of " + judged.length + " judged"],
      ["Ready", q.filter(function(x){return x.state==="ready";}).length, "in queue"],
      ["Saved refs", saved.length, "inspiration"]
    ];
    $('[data-view="stats"]').innerHTML = '<div class="stats">'
      + cards.map(function(c){ return '<div class="stat"><div class="k">'+c[0]+'</div>'
          + '<div class="v">'+c[1]+'</div><div class="d">'+c[2]+'</div></div>'; }).join("")
      + '</div>'
      + '<div class="form"><h3>Log a post</h3>'
      + '<p>Instagram numbers by hand for now. Connecting the Graph API is a weekend of setup with Meta — do it once posting is regular.</p>'
      + '<div class="grid">'
      + '<label><span class="k">Platform</span><select id="mPlatform"><option>Instagram</option><option>TikTok</option></select></label>'
      + '<label><span class="k">Views</span><input id="mViews" type="number" inputmode="numeric"></label>'
      + '<label><span class="k">Retention %</span><input id="mRet" type="number" inputmode="numeric"></label>'
      + '<label><span class="k">Saves</span><input id="mSaves" type="number" inputmode="numeric"></label>'
      + '<label><span class="k">Comments</span><input id="mComments" type="number" inputmode="numeric"></label>'
      + '</div>'
      + '<button class="btn solid" id="logPost">Save</button></div>'
      + (posts.length ? '<div class="tw" style="margin-top:16px"><table><thead><tr><th>When</th><th>Platform</th><th>Views</th><th>Retention</th><th>Saves</th></tr></thead><tbody>'
          + posts.map(function(p){ return '<tr><td>'+new Date(p.posted_at).toLocaleDateString()+'</td><td>'+esc(p.platform)+'</td><td>'+(p.views||"—")+'</td><td>'+(p.retention_pct?p.retention_pct+"%":"—")+'</td><td>'+(p.saves||"—")+'</td></tr>'; }).join("")
          + '</tbody></table></div>' : '');
  }

  var RENDER = { ideas: renderIdeas, inspo: renderInspo, queue: renderQueue, stats: renderStats };

  async function show(v) {
    state.view = v;
    $$(".view").forEach(function (s) { s.classList.toggle("on", s.dataset.view === v); });
    $$("#nav button").forEach(function (b) { b.setAttribute("aria-current", String(b.dataset.v === v)); });
    $("#vt").textContent = VIEWS[v][0];
    $("#vs").textContent = VIEWS[v][1];
    $("#gen").hidden = v !== "ideas";
    await RENDER[v]();
  }

  /* --------------------------------------------------------------- events */
  document.addEventListener("click", async function (e) {
    var t = e.target;

    var nb = t.closest("#nav button"); if (nb) return show(nb.dataset.v);
    if (t.closest("#col")) {
      $("#app").classList.toggle("collapsed");
      try { localStorage.setItem("hub.collapsed", $("#app").classList.contains("collapsed") ? "1" : "0"); } catch (x) {}
      return;
    }
    if (t.closest("#signout")) return Store.auth.signOut();

    var f = t.closest("#filters button"); if (f) { state.filter = f.dataset.f; return renderIdeas(); }
    var it = t.closest("#itabs button"); if (it) { state.inspoTab = it.dataset.i; return renderInspo(); }

    if (t.closest("#gen")) {
      var b = $("#gen"); b.disabled = true; var lbl = b.textContent; b.textContent = "Generating…";
      try { var made = await Store.ideas.generate(4); toast(made.length + " new concepts"); await renderIdeas(); }
      catch (err) { toast("Generation failed — check the Edge Function"); }
      b.disabled = false; b.textContent = lbl;
      return;
    }

    // idea card
    var card = t.closest(".card");
    if (card) {
      var id = card.dataset.id;
      var drop = function () { card.classList.add("gone"); setTimeout(function () { renderIdeas(); }, 220); };
      if (t.closest(".yes")) { await Store.ideas.judge(id, "kept");
        await Store.queue.add({ kind:"concept", title:$(".hook",card).textContent, job:card.dataset.job });
        toast("Kept — added to queue"); return drop(); }
      if (t.closest(".save")) { await Store.ideas.judge(id, "edited", { final_hook:$("textarea",card).value });
        await Store.queue.add({ kind:"concept", title:$("textarea",card).value, job:card.dataset.job });
        toast("Edit saved — that's the strongest signal"); return drop(); }
      var rb = t.closest(".reasons button");
      if (rb) { await Store.ideas.judge(id, "discarded", { reason: rb.dataset.r }); toast("Noted"); return drop(); }
      if (t.closest(".no")) { $(".reasons",card).classList.toggle("open"); $(".editor",card).classList.remove("open"); return; }
      if (t.closest(".ed")) { $(".editor",card).classList.toggle("open"); $(".reasons",card).classList.remove("open"); return; }
    }

    // inspiration
    var ic = t.closest(".ic");
    if (ic) {
      if (t.closest(".savebtn")) { $(".savewhy",ic).classList.toggle("open"); return; }
      var wb = t.closest(".savewhy button");
      if (wb) { await Store.inspiration.save(ic.dataset.id, wb.dataset.w); toast("Saved for the "+wb.textContent.toLowerCase()); return renderInspo(); }
      if (t.closest(".toidea")) {
        var all = (await Store.inspiration.list(true)).concat(await Store.inspiration.list(false));
        var item = all.filter(function(x){return x.id===ic.dataset.id;})[0];
        await Store.inspiration.toIdea(item); toast("Added to Ideas"); return;
      }
    }

    if (t.closest("#analyse")) {
      var url = $("#inspUrl").value.trim(); if (!url) return;
      try { await Store.inspiration.analyse(url); toast("Analysed"); await renderInspo(); }
      catch (err) { toast("Analysis failed"); }
      return;
    }

    var pill = t.closest(".pill");
    if (pill) {
      var next = STATES[(STATES.indexOf(pill.dataset.s) + 1) % STATES.length];
      pill.dataset.s = next; pill.textContent = SLABEL[next];
      await Store.queue.setState(pill.dataset.q, next);
      return;
    }

    if (t.closest("#logPost")) {
      await Store.posts.log({
        platform: $("#mPlatform").value,
        views: +$("#mViews").value || null, retention_pct: +$("#mRet").value || null,
        saves: +$("#mSaves").value || null, comments: +$("#mComments").value || null
      });
      toast("Logged"); return renderStats();
    }

    if (t.closest("#signin")) {
      var em = $("#email").value.trim(); if (!em) return;
      await Store.auth.signIn(em); toast("Check your email for the link");
      return;
    }
  });

  /* ---------------------------------------------------------------- boot */
  (async function () {
    try { if (localStorage.getItem("hub.collapsed") === "1") $("#app").classList.add("collapsed"); } catch (e) {}
    var user = await Store.auth.user();
    if (Store.live && !user) { $("#app").hidden = true; $("#auth").hidden = false; return; }
    $("#auth").hidden = true; $("#app").hidden = false;
    if (!Store.live) $("#localBanner").hidden = false;
    await show("ideas");
  })();
})();
