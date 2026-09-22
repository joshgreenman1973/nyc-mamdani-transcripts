/* Press Q&A catalogue — every question put to Mayor Mamdani at an officially
   transcribed event, and what he said back. Data: data/qa.json (build_qa.py).
   Loaded lazily the first time the "Press Q&A" tab opens. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));

  const PAGE = 40;
  const ANSWER_PREVIEW = 700; // characters of answer shown before "Show full answer"
  const WHO_LABEL = { reporter: "Reporter", host: "Interviewer", public: "Caller, audience or non-press host" };
  const KIND_LABEL = { press: "Press event", interview: "Interview", forum: "City Hall livestream / forum" };
  const KIND_BADGE = { press: "press_conference", interview: "media_appearance", forum: "ceremony" };

  let DATA = null;
  let LOADING = null;
  let EVENTS = {};
  let EX_BY_ID = {};
  let EX_BY_EVENT = {};
  let TOPIC_BY_ID = {};
  let ROWS = [];
  let SHOWN = 0;
  let RE = null;
  let TOPIC = null;
  let FOCUS = null; // exchange id when showing a single linked exchange
  let T = null;
  let RESTORING = false;

  // ---- boot: app.js tells us when the view changes -------------------------
  document.addEventListener("vc:viewchange", (e) => {
    if (e.detail === "qa") ensureLoaded();
  });

  function ensureLoaded() {
    if (DATA || LOADING) return LOADING;
    $("#qa-summary").textContent = "Loading the question catalogue…";
    LOADING = fetch("data/qa.json?v=" + new Date().toISOString().slice(0, 10))
      .then((r) => {
        if (!r.ok) throw new Error(r.status);
        return r.json();
      })
      .then((d) => {
        DATA = d;
        prepare();
        buildControls();
        restoreFromURL();
        attach();
        run();
      })
      .catch((err) => {
        $("#qa-summary").textContent = "Could not load the question catalogue: " + err.message;
      });
    return LOADING;
  }

  function prepare() {
    DATA.events.forEach((e) => (EVENTS[e.id] = e));
    (DATA.topics || []).forEach((t) => (TOPIC_BY_ID[t.id] = t));
    DATA.exchanges.forEach((x) => {
      x.ev = EVENTS[x.e];
      x.qText = x.q.map((q) => q.t).join("\n\n");
      x.mText = x.a.filter((a) => a.m).map((a) => a.t).join("\n\n");
      x.aText = x.a.map((a) => a.t).join("\n\n");
      x._q = norm(x.qText);
      x._a = norm(x.aText);
      EX_BY_ID[x.id] = x;
      (EX_BY_EVENT[x.e] = EX_BY_EVENT[x.e] || []).push(x);
    });
    Object.values(EX_BY_EVENT).forEach((list) => list.sort((a, b) => a.n - b.n));
    const dates = DATA.events.map((e) => e.date).sort();
    ["#qa-from", "#qa-to"].forEach((s) => {
      $(s).min = dates[0];
      $(s).max = dates[dates.length - 1];
    });
    const c = DATA.counts;
    const press = c.from_reporters + c.from_hosts;
    $("#qa-meta").innerHTML =
      `<strong>${fmt(press)}</strong> questions from reporters and interviewers across <strong>${fmt(c.events)}</strong> ` +
      `officially transcribed events, ${prettyDate(dates[0])} through ${prettyDate(dates[dates.length - 1])}. ` +
      `Another ${fmt(c.from_public)} came from callers, audiences and the hosts of City Hall&rsquo;s own ` +
      `livestreams; they&rsquo;re under &ldquo;More filters.&rdquo;`;
  }

  // Normalise curly quotes / dashes so a typed "don't" matches "don’t".
  function norm(s) {
    return (s || "")
      .toLowerCase()
      .replace(/[‘’]/g, "'")
      .replace(/[“”]/g, '"')
      .replace(/[–—]/g, "-");
  }

  // ---- controls ---------------------------------------------------------------
  function buildControls() {
    const box = $("#qa-topics");
    const counts = {};
    DATA.exchanges.forEach((x) => x.tp.forEach((t) => (counts[t] = (counts[t] || 0) + 1)));
    const topics = (DATA.topics || []).filter((t) => counts[t.id]).sort((a, b) => counts[b.id] - counts[a.id]);
    box.innerHTML = '<span class="topics-label">Themes:</span>';
    topics.forEach((t) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "topic-chip";
      b.dataset.topic = t.id;
      b.innerHTML = `${escapeHtml(t.label)} <span class="topic-count" data-qa-tcount="${t.id}"></span>`;
      b.addEventListener("click", () => {
        TOPIC = TOPIC === t.id ? null : t.id;
        FOCUS = null;
        run();
      });
      box.appendChild(b);
    });
    const kc = { press: 0, interview: 0, forum: 0 };
    const wc = { reporter: 0, host: 0, public: 0 };
    DATA.exchanges.forEach((x) => {
      kc[x.ev.kind]++;
      wc[x.w]++;
    });
    Object.entries(kc).forEach(([k, n]) => { const el = $(`[data-qa-kcount="${k}"]`); if (el) el.textContent = `(${fmt(n)})`; });
    Object.entries(wc).forEach(([k, n]) => { const el = $(`[data-qa-wcount="${k}"]`); if (el) el.textContent = `(${fmt(n)})`; });
    const others = DATA.counts.answered_by_others_only + DATA.counts.no_answer_recorded;
    $("[data-qa-ocount]").textContent = `(${fmt(others)})`;
  }

  function attach() {
    $("#qa-q").addEventListener("input", () => {
      clearTimeout(T);
      T = setTimeout(() => { FOCUS = null; run(); }, 160);
    });
    $("#qa-clear").addEventListener("click", () => {
      $("#qa-q").value = "";
      FOCUS = null;
      run();
      $("#qa-q").focus();
    });
    $$("#qa-view input[type=checkbox], #qa-view input[type=radio], #qa-view input[type=date]").forEach((el) =>
      el.addEventListener("change", () => { FOCUS = null; run(); })
    );
    $("#qa-more").addEventListener("click", () => renderMore());
    $("#qa-csv").addEventListener("click", downloadCSV);
    $("#qa-share").addEventListener("click", () => copyLink($("#qa-share"), location.href));
    $$("[data-qa-example]").forEach((a) =>
      a.addEventListener("click", (e) => {
        e.preventDefault();
        $("#qa-q").value = a.dataset.qaExample;
        FOCUS = null;
        run();
      })
    );
    window.addEventListener("popstate", () => {
      if (new URLSearchParams(location.search).get("view") !== "qa") return;
      restoreFromURL();
      run();
    });
  }

  function state() {
    return {
      q: $("#qa-q").value.trim(),
      field: ($("input[name=qa-field]:checked") || {}).value || "both",
      who: new Set($$("input[name=qa-who]:checked").map((el) => el.value)),
      kinds: new Set($$("input[name=qa-kind]:checked").map((el) => el.value)),
      others: $("#qa-others").checked,
      from: $("#qa-from").value,
      to: $("#qa-to").value,
      sort: ($("input[name=qa-sort]:checked") || {}).value || "new",
    };
  }

  // ---- search -----------------------------------------------------------------
  // Words narrow (AND) and match as word-starts, so "evict" finds "evictions";
  // "quoted phrases" match exactly.
  function parse(q) {
    const phrases = [];
    const rest = norm(q).replace(/"([^"]+)"/g, (_, p) => {
      if (p.trim()) phrases.push(p.trim());
      return " ";
    });
    const tokens = rest.split(/[^\w'\-]+/).map((t) => t.replace(/^['\-]+|['\-]+$/g, "")).filter((t) => t.length > 0);
    const res = [
      ...phrases.map((p) => new RegExp("(?<![\\w])" + p.split(/\s+/).map(esc).join("\\s+") + "(?![\\w])", "g")),
      ...tokens.map((t) => new RegExp("(?<![\\w])" + esc(t), "g")),
    ];
    // Highlighting runs on the original text, so let straight quotes and
    // hyphens in the query match their typographic forms.
    const loose = (w) => esc(w).replace(/'/g, "['’]").replace(/\\-/g, "[-–—]").replace(/-/g, "[-–—]");
    const hlSrc = [
      ...phrases.map((p) => p.split(/\s+/).map(loose).join("\\s+")),
      ...tokens.map((t) => loose(t) + "[\\w'’]*"),
    ];
    return {
      res,
      highlight: hlSrc.length ? new RegExp("(?<![\\w])(" + hlSrc.sort((a, b) => b.length - a.length).join("|") + ")", "giu") : null,
    };
  }

  function count(re, s) {
    re.lastIndex = 0;
    let n = 0;
    while (re.exec(s) && n < 50) n++;
    return n;
  }

  function run() {
    if (!DATA) return;
    const st = state();
    const parsed = parse(st.q);
    RE = parsed.highlight;
    let rows = [];
    for (const x of DATA.exchanges) {
      if (!st.who.has(x.w)) continue;
      if (!st.kinds.has(x.ev.kind)) continue;
      if (!st.others && x.by !== "mayor") continue;
      if (st.from && x.ev.date < st.from) continue;
      if (st.to && x.ev.date > st.to) continue;
      let score = 0;
      let ok = true;
      for (const re of parsed.res) {
        const inQ = st.field !== "a" ? count(re, x._q) : 0;
        const inA = st.field !== "q" ? count(re, x._a) : 0;
        if (!inQ && !inA) { ok = false; break; }
        score += inQ * 3 + inA;
      }
      if (!ok) continue;
      rows.push({ x, score });
    }
    // Topic counts reflect everything else that's filtered, before the theme.
    const tc = {};
    rows.forEach((r) => r.x.tp.forEach((t) => (tc[t] = (tc[t] || 0) + 1)));
    $$("[data-qa-tcount]").forEach((el) => {
      const n = tc[el.dataset.qaTcount] || 0;
      el.textContent = n ? fmt(n) : "0";
    });
    $$("#qa-topics .topic-chip").forEach((b) => {
      const on = b.dataset.topic === TOPIC;
      b.classList.toggle("active", on);
      b.setAttribute("aria-pressed", String(on));
    });
    if (TOPIC) rows = rows.filter((r) => r.x.tp.includes(TOPIC));

    // "Best match" only means something with a search; without one it's newest first.
    const relBtn = $("input[name=qa-sort][value=rel]");
    relBtn.disabled = !st.q;
    relBtn.parentElement.title = st.q ? "" : "Search for something to rank by best match";
    if (!st.q && relBtn.checked) { $("input[name=qa-sort][value=new]").checked = true; st.sort = "new"; }
    const byDate = (a, b) =>
      a.x.ev.date < b.x.ev.date ? 1 : a.x.ev.date > b.x.ev.date ? -1 : a.x.e !== b.x.e ? b.x.e - a.x.e : a.x.n - b.x.n;
    const byDateAsc = (a, b) =>
      a.x.ev.date < b.x.ev.date ? -1 : a.x.ev.date > b.x.ev.date ? 1 : a.x.e !== b.x.e ? a.x.e - b.x.e : a.x.n - b.x.n;
    if (st.sort === "old") rows.sort(byDateAsc);
    else if (st.sort === "rel" && st.q) rows.sort((a, b) => b.score - a.score || byDate(a, b));
    else rows.sort(byDate);

    ROWS = rows.map((r) => r.x);
    writeURL(st);
    render(st);
  }

  // ---- render -----------------------------------------------------------------
  function render(st) {
    const list = $("#qa-results");
    list.innerHTML = "";
    SHOWN = 0;
    const empty = $("#qa-empty");
    const summary = $("#qa-summary");

    if (FOCUS && EX_BY_ID[FOCUS]) {
      const x = EX_BY_ID[FOCUS];
      summary.innerHTML = `One exchange, linked directly. <button type="button" class="qa-linkbtn" id="qa-unfocus">Show all questions</button>`;
      $("#qa-unfocus").addEventListener("click", () => { FOCUS = null; run(); });
      empty.classList.add("hidden");
      $("#qa-more").classList.add("hidden");
      const li = buildCard(x, true);
      list.appendChild(li);
      toggleContext(li, x, true);
      return;
    }

    if (!ROWS.length) {
      empty.classList.remove("hidden");
      const th = TOPIC ? ` under the theme “${TOPIC_BY_ID[TOPIC].label}”` : "";
      summary.textContent = st.q
        ? `No questions or answers match “${st.q.replace(/^"|"$/g, "")}”${th} with these filters.`
        : `No questions${th} match these filters.`;
      $("#qa-more").classList.add("hidden");
      return;
    }
    empty.classList.add("hidden");
    const evCount = new Set(ROWS.map((x) => x.e)).size;
    const shown = /^".*"$/.test(st.q) ? st.q.replace(/^"|"$/g, "") : st.q;
    const where = st.field === "q" ? " in the question" : st.field === "a" ? " in the answer" : "";
    const topic = TOPIC ? ` on ${TOPIC_BY_ID[TOPIC].label.toLowerCase()}` : "";
    summary.textContent = st.q
      ? `${fmt(ROWS.length)} exchange${ROWS.length === 1 ? "" : "s"}${topic} matching “${shown}”${where}, from ${fmt(evCount)} event${evCount === 1 ? "" : "s"}.`
      : `${fmt(ROWS.length)} exchange${ROWS.length === 1 ? "" : "s"}${topic} from ${fmt(evCount)} event${evCount === 1 ? "" : "s"}.`;
    renderMore();
  }

  function renderMore() {
    const list = $("#qa-results");
    const frag = document.createDocumentFragment();
    const next = ROWS.slice(SHOWN, SHOWN + PAGE);
    next.forEach((x) => frag.appendChild(buildCard(x, false)));
    list.appendChild(frag);
    SHOWN += next.length;
    const more = $("#qa-more");
    const left = ROWS.length - SHOWN;
    more.classList.toggle("hidden", left <= 0);
    more.textContent = `Show ${Math.min(PAGE, left)} more (${fmt(left)} left)`;
  }

  function buildCard(x, focused) {
    const ev = x.ev;
    const li = document.createElement("li");
    li.className = "qa-card" + (focused ? " qa-card--focus" : "");
    li.id = "qa-" + x.id;
    const badgeType = KIND_BADGE[ev.kind];
    const prog = ev.kind === "interview" && ev.program ? `<span>${escapeHtml(ev.program)}</span>` : "";
    const who = x.w === "reporter"
      ? (x.live ? "Reporter (livestream)" : "Reporter")
      : WHO_LABEL[x.w];
    const topics = x.tp.map((t) => TOPIC_BY_ID[t] ? `<span class="qa-tag">${escapeHtml(TOPIC_BY_ID[t].label)}</span>` : "").join("");
    li.innerHTML = `
      <div class="result-meta">
        <span>${prettyDate(ev.date)}</span>
        <span class="badge ${badgeType}">${KIND_LABEL[ev.kind]}</span>
        ${prog}
        <span class="qa-pos">Question ${x.n} of ${x.of}</span>
      </div>
      <p class="qa-event"><a href="${escapeAttr(ev.url)}" target="_blank" rel="noopener">${escapeHtml(ev.title)}</a></p>
      <div class="qa-q">
        <p class="qa-label">${escapeHtml(who)} asked</p>
        ${x.q.map((q) => (q.s && q.s !== "Question" ? `<p class="qa-inline-speaker">${escapeHtml(q.s)}</p>` : "") + paras(q.t)).join("")}
      </div>
      <div class="qa-a"></div>
      ${topics ? `<div class="qa-tags">${topics}</div>` : ""}
      <div class="result-actions">
        <button type="button" class="qa-ctx">Show the exchanges around it</button>
        <a href="${escapeAttr(ev.url)}" target="_blank" rel="noopener">Full transcript on nyc.gov</a>
        <button type="button" class="qa-permalink">Copy link to this exchange</button>
      </div>
      <div class="qa-context hidden"></div>`;
    fillAnswer($(".qa-a", li), x, false);
    $(".qa-ctx", li).addEventListener("click", () => toggleContext(li, x));
    $(".qa-permalink", li).addEventListener("click", (e) => {
      const u = new URL(location.href);
      u.search = "";
      u.searchParams.set("view", "qa");
      u.searchParams.set("ex", x.id);
      copyLink(e.currentTarget, u.toString());
    });
    return li;
  }

  function answerHtml(x, full) {
    if (!x.a.length) return `<p class="qa-none">No answer recorded in the transcript.</p>`;
    let budget = full ? Infinity : ANSWER_PREVIEW;
    let out = "";
    let truncated = false;
    for (const a of x.a) {
      if (budget <= 0) { truncated = true; break; }
      let t = a.t;
      if (t.length > budget) {
        const cut = t.lastIndexOf(" ", budget);
        t = t.slice(0, cut > 0 ? cut : budget) + "…";
        truncated = true;
      }
      budget -= t.length;
      const who = a.m ? "Mayor Mamdani" : a.s;
      out += `<div class="turn ${a.m ? "turn--mayor" : "turn--other"}"><p class="turn-speaker">${escapeHtml(who)}</p>${paras(t)}</div>`;
    }
    return { html: out, truncated };
  }

  function fillAnswer(box, x, full) {
    const r = answerHtml(x, full);
    if (typeof r === "string") { box.innerHTML = r; return; }
    box.innerHTML = r.html + (r.truncated || full && x.aText.length > ANSWER_PREVIEW
      ? `<button type="button" class="qa-linkbtn qa-fulltoggle">${full ? "Show less" : "Show full answer"}</button>` : "");
    const b = $(".qa-fulltoggle", box);
    if (b) b.addEventListener("click", () => fillAnswer(box, x, !full));
  }

  // Neighbouring exchanges from the same event — follow-ups usually live here.
  function toggleContext(li, x, force) {
    const box = $(".qa-context", li);
    const btn = $(".qa-ctx", li);
    const open = force || box.classList.contains("hidden");
    box.classList.toggle("hidden", !open);
    btn.textContent = open ? "Hide the exchanges around it" : "Show the exchanges around it";
    if (!open || box.dataset.built) return;
    box.dataset.built = "1";
    const list = EX_BY_EVENT[x.e];
    const i = list.indexOf(x);
    const before = list.slice(Math.max(0, i - 2), i);
    const after = list.slice(i + 1, i + 3);
    const item = (y) => {
      const r = answerHtml(y, false);
      const ans = typeof r === "string" ? r : r.html;
      return `<div class="qa-ctx-item">
        <p class="qa-label">Question ${y.n} of ${y.of}</p>
        <div class="qa-q qa-q--small">${y.q.map((q) => (q.s && q.s !== "Question" ? `<p class="qa-inline-speaker">${escapeHtml(q.s)}</p>` : "") + paras(q.t)).join("")}</div>
        ${ans}
      </div>`;
    };
    box.innerHTML =
      (before.length ? `<p class="qa-ctx-head">Before</p>` + before.map(item).join("") : `<p class="qa-ctx-head">First question of the event.</p>`) +
      (after.length ? `<p class="qa-ctx-head">After</p>` + after.map(item).join("") : `<p class="qa-ctx-head">Last question of the event.</p>`);
  }

  function paras(t) {
    return String(t)
      .split(/\n{2,}/)
      .map((p) => `<p>${hl(p.trim())}</p>`)
      .join("");
  }

  function hl(s) {
    if (!RE) return escapeHtml(s);
    let out = "";
    let last = 0;
    const r = new RegExp(RE.source, RE.flags);
    let m;
    while ((m = r.exec(s)) !== null) {
      out += escapeHtml(s.slice(last, m.index)) + "<mark>" + escapeHtml(m[0]) + "</mark>";
      last = m.index + m[0].length;
      if (!m[0].length) r.lastIndex++;
    }
    return out + escapeHtml(s.slice(last));
  }

  // ---- CSV --------------------------------------------------------------------
  function downloadCSV() {
    const rows = FOCUS && EX_BY_ID[FOCUS] ? [EX_BY_ID[FOCUS]] : ROWS;
    const head = ["date", "event", "event_type", "program", "transcript_url", "question_number",
      "questions_at_event", "asked_by", "question", "answered_by", "mayor_answer", "full_response"];
    const cell = (v) => {
      const s = String(v == null ? "" : v);
      return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    const lines = [head.join(",")];
    rows.forEach((x) => {
      lines.push([
        x.ev.date, x.ev.title, KIND_LABEL[x.ev.kind], x.ev.program || "", x.ev.url, x.n, x.of,
        x.q.map((q) => q.s).filter(Boolean)[0] || WHO_LABEL[x.w],
        x.qText,
        x.by === "mayor" ? "Mayor" : x.by === "others" ? [...new Set(x.a.map((a) => a.s))].join("; ") : "",
        x.mText,
        x.a.map((a) => `${a.m ? "Mayor Mamdani" : a.s}: ${a.t}`).join("\n\n"),
      ].map(cell).join(","));
    });
    const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `mamdani-press-qa-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  }

  // ---- URL state --------------------------------------------------------------
  const DEFAULT_WHO = "host,reporter";
  const DEFAULT_KINDS = "forum,interview,press";

  function restoreFromURL() {
    RESTORING = true;
    const p = new URLSearchParams(location.search);
    $("#qa-q").value = p.get("qq") || "";
    const field = p.get("in") || "both";
    $$("input[name=qa-field]").forEach((el) => (el.checked = el.value === field));
    const who = new Set((p.get("who") || DEFAULT_WHO).split(","));
    $$("input[name=qa-who]").forEach((el) => (el.checked = who.has(el.value)));
    const kinds = new Set((p.get("kind") || DEFAULT_KINDS).split(","));
    $$("input[name=qa-kind]").forEach((el) => (el.checked = kinds.has(el.value)));
    $("#qa-others").checked = p.get("others") === "1";
    $("#qa-from").value = p.get("qfrom") || "";
    $("#qa-to").value = p.get("qto") || "";
    const sort = p.get("qsort") || "new";
    $$("input[name=qa-sort]").forEach((el) => (el.checked = el.value === sort));
    TOPIC = p.get("theme") && TOPIC_BY_ID[p.get("theme")] ? p.get("theme") : null;
    FOCUS = p.get("ex") && EX_BY_ID[p.get("ex")] ? p.get("ex") : null;
    const anyFilter = p.get("in") || p.get("who") || p.get("kind") || p.get("others") || p.get("qfrom") || p.get("qto");
    if (anyFilter) $("#qa-refine").open = true;
    RESTORING = false;
  }

  function writeURL(st) {
    if (RESTORING) return;
    const p = new URLSearchParams();
    p.set("view", "qa");
    if (FOCUS) {
      p.set("ex", FOCUS);
    } else {
      if (st.q) p.set("qq", st.q);
      if (st.field !== "both") p.set("in", st.field);
      if (TOPIC) p.set("theme", TOPIC);
      const who = [...st.who].sort().join(",");
      if (who !== DEFAULT_WHO) p.set("who", who || "none");
      const kinds = [...st.kinds].sort().join(",");
      if (kinds !== DEFAULT_KINDS) p.set("kind", kinds || "none");
      if (st.others) p.set("others", "1");
      if (st.from) p.set("qfrom", st.from);
      if (st.to) p.set("qto", st.to);
      if (st.sort !== "new") p.set("qsort", st.sort);
    }
    history.replaceState(null, "", "?" + p.toString());
  }

  // ---- utils ------------------------------------------------------------------
  async function copyLink(btn, url) {
    let ok = false;
    try { await navigator.clipboard.writeText(url); ok = true; } catch {}
    if (!ok) {
      const tmp = document.createElement("input");
      tmp.value = url;
      document.body.appendChild(tmp);
      tmp.select();
      try { document.execCommand("copy"); ok = true; } catch {}
      tmp.remove();
    }
    const old = btn.textContent;
    btn.textContent = ok ? "Link copied!" : "Copy failed";
    setTimeout(() => (btn.textContent = old), 1800);
  }
  function esc(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
  function fmt(n) { return Number(n).toLocaleString("en-US"); }
  function escapeHtml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function escapeAttr(s) { return escapeHtml(s); }
  function prettyDate(iso) {
    const [y, m, d] = iso.split("-").map(Number);
    const M = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."];
    return `${M[m - 1]} ${d}, ${y}`;
  }
})();
