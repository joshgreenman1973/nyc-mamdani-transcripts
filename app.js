/* Mayor Mamdani transcript search — client-side */
(() => {
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));

  const TYPE_LABEL = {
    speech: "Speech",
    press_conference: "Press conference",
    media_appearance: "Media",
    statement: "Statement",
    ceremony: "Ceremony",
    video: "Video",
    hearing: "Council hearing",
    executive_order: "Executive order",
    other: "Press release",
    crime_briefing: "NYPD crime briefing",
    agency_release: "Agency press release",
    op_ed: "Op-ed",
  };


  // Where a transcript came from (shown only when it's not the default nyc.gov).
  const SOURCE_LABEL = {
    "nyc.gov": "Mayor's Office",
    npr: "NPR",
    wnyc: "WNYC",
    cspan: "C-SPAN",
    council: "NYC Council",
    youtube: "YouTube",
    podcast: "Podcast",
    // City agencies
    nypd: "NYPD",
    fdny: "Fire (FDNY)",
    dsny: "Sanitation (DSNY)",
    hpd: "Housing Preservation & Development",
    dep: "Environmental Protection (DEP)",
    dca: "Consumer & Worker Protection (DCWP)",
    acs: "Children's Services (ACS)",
    dcas: "Citywide Administrative Services",
    doh: "Health (DOHMH)",
    dhs: "Homeless Services (DHS)",
    sbs: "Small Business Services (SBS)",
    tlc: "Taxi & Limousine (TLC)",
    immigrants: "Immigrant Affairs (MOIA)",
    mome: "Media & Entertainment (MOME)",
    dot: "Transportation (DOT)",
  };
  function sourceLabel(src) {
    return SOURCE_LABEL[src] || (src || "").toUpperCase();
  }
  // Sources that are city agencies (press releases), for grouping the filter.
  const AGENCY_SOURCES = ["nypd", "fdny", "dsny", "hpd", "dep", "dca", "acs", "dcas",
    "doh", "dhs", "sbs", "tlc", "immigrants", "mome", "dot"];
  // "City Hall" = the Mayor's own universe: his events + interviews + the Council
  // hearings where his administration testifies. Everything not a city agency.
  function isCityHall(src) {
    return !AGENCY_SOURCES.includes(src);
  }
  // Which sources each scope preset turns on.
  function scopeSources(scope) {
    const all = (CORPUS && CORPUS.source_counts) ? Object.keys(CORPUS.source_counts) : [];
    if (scope === "admin") return all;
    if (scope === "nypd") return all.filter((s) => isCityHall(s) || s === "nypd");
    return all.filter(isCityHall); // cityhall
  }

  // How trustworthy the transcript text is.
  const RELIABILITY_LABEL = {
    official: "official transcript",
    verified: "published transcript",
    auto: "auto-caption — may contain errors",
    release: "press release — not a verbatim transcript",
  };

  // The "View on …" link label per source.
  const SOURCE_LINK_LABEL = {
    "nyc.gov": "View on nyc.gov",
    npr: "Read on NPR",
    wnyc: "Listen on WNYC",
    cspan: "Watch on C-SPAN",
    council: "Open hearing transcript (PDF)",
    podcast: "Open transcript",
    nypd: "Read NYPD release",
  };

  // Active reliability filter (Set of values), refreshed at each search.
  let RELIABILITY_ON = null;
  // Active source/agency filter (Set of source keys), refreshed at each search.
  let SOURCE_ON = null;

  // Hand-picked starter topics. These map to common substrings the user is
  // likely to want to find his position on — they're not exhaustive.
  const TOPICS = [
    "rent",
    "child care",
    "housing",
    "police",
    "subway",
    "ICE",
    "schools",
    "Albany",
    "Trump",
    "Cuomo",
    "FHEPS",
    "budget",
    "homelessness",
    "Israel",
    "Gaza",
  ];

  let CORPUS = null;
  let THEMES = null; // data/topics.json: {taxonomy, months, monthly, totals, itemTopics, digest}
  let TOPIC_FILTER = null; // active theme id restricting the result set, or null
  let FEATURED = null; // active featured filter: null | "tisch" | "nypd"
  let SPOTLIGHT_COUNT = 0; // # of Mayor + Commissioner Tisch co-appearances
  let BRIEFINGS_COUNT = 0; // # of NYPD crime briefings
  let VIEW = "search"; // "search" | "trends"
  let MS = null;
  let LAST_RESULTS = [];
  let DEBOUNCE_T = null;
  let URL_RESTORING = false; // suppress URL writes while loading params

  // ---- plain-language (semantic) search ----
  const SEM_CDN = "https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.8.1";
  const SEM_MIN_COS = 0.22; // absolute floor on centered cosine
  const SEM_MARGIN = 0.22; // also drop anything this far below the top hit
  const SEM_MAX_ROWS = 50;
  let MODE = "keyword"; // "keyword" | "semantic"
  let EMB = null; // {dims, count, chunks:[{i,s,e}], vecs:Int8Array}
  let EXTRACTOR = null; // transformers.js feature-extraction pipeline
  let SEM_READY = false;
  let SEM_LOADING = null; // in-flight load promise
  let SEM_SEQ = 0; // guards against out-of-order async results

  // ---- boot ----
  // Cache-bust by the daily-refresh date so the browser re-fetches when a
  // new corpus is committed. The `generated_at` field changes daily.
  fetch("data/corpus.json?v=" + new Date().toISOString().slice(0, 10))
    .then((r) => r.json())
    .then((data) => {
      CORPUS = data;
      $("#meta").textContent =
        `${data.total} items from ${formatRange(data.items)}. ` +
        `Last refreshed ${formatGenerated(data.generated_at)}.`;
      Object.entries(data.type_counts || {}).forEach(([t, n]) => {
        const el = document.querySelector(`.count[data-count="${t}"]`);
        if (el) el.textContent = `(${n})`;
      });
      // Reliability counts (computed client-side; default missing → official).
      const relCounts = {};
      data.items.forEach((i) => {
        const r = i.reliability || "official";
        relCounts[r] = (relCounts[r] || 0) + 1;
      });
      Object.entries(relCounts).forEach(([r, n]) => {
        const el = document.querySelector(`.count[data-rcount="${r}"]`);
        if (el) el.textContent = `(${n})`;
      });
      const dates = data.items.map((i) => i.iso_date).filter(Boolean).sort();
      if (dates.length) {
        $("#from").min = $("#to").min = dates[0];
        $("#from").max = $("#to").max = dates[dates.length - 1];
      }
      buildIndex();
      tagCoAppearances();
      buildTopics();
      buildSourceFilter();
      renderScopeCounts();
      attachHandlers();
      return fetch("data/topics.json?v=" + new Date().toISOString().slice(0, 10))
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null)
        .then((t) => {
          if (t) {
            THEMES = t;
            // Attach each item's tagged themes by index for the topic filter.
            (t.itemTopics || []).forEach((ids, i) => {
              if (CORPUS.items[i]) CORPUS.items[i]._topics = ids;
            });
            buildTrends();
          }
          restoreFromURL();
          applyMode();
          applyView();
          if (MODE === "semantic") ensureSemantic();
          runSearch();
        });
    })
    .catch((err) => {
      $("#meta").textContent = "Could not load archive: " + err.message;
    });

  // ---- index ----
  function buildIndex() {
    MS = new MiniSearch({
      fields: ["title", "text"],
      storeFields: ["id"],
      searchOptions: {
        boost: { title: 3 },
        prefix: true,
        fuzzy: 0.1,
        combineWith: "AND",
      },
    });
    CORPUS.items.forEach((it, idx) => {
      it._id = idx;
      MS.add({ id: idx, title: it.title, text: it.text || "" });
    });
  }

  // ---- "appeared together" spotlight (Mayor + Police Commissioner Tisch) ----
  // Flags transcripts where the Mayor and Police Commissioner Jessica Tisch were
  // demonstrably at the same event. The test is deliberately conservative: a
  // passing mention of Tisch — a reporter's question, "I speak with her daily" —
  // does NOT count. An item qualifies only when (1) Tisch has her own speaking
  // turn, (2) the headline pairs the two or it's a joint statement, or (3) the
  // Mayor is present and his remarks place her at the podium. Council hearings
  // are excluded because the Mayor doesn't testify. Recomputed in the browser
  // from corpus.json, so it tracks the daily refresh. See METHODOLOGY.md.
  const TISCH_RE = /\bTisch\b/i;
  const MAMDANI_RE = /\bMamdani\b/i;
  function isTischCoAppearance(it) {
    const txt = it.text || "";
    const title = it.title || "";
    if (!TISCH_RE.test(txt) && !TISCH_RE.test(title)) return false;
    // Council hearings are committee testimony — the Mayor isn't there.
    if (it.type === "hearing") return false;
    // Press releases (incl. NYPD crime briefings) are written documents, not
    // evidence the two were at the same event — keep them out of "appeared
    // together" even when both are quoted in the release.
    if (it.is_press_release || it.type === "crime_briefing") return false;
    const names = (it.speakers || []).map((s) => s.speaker || "");
    // (1) Tisch has her own speaking turn in the transcript.
    if (names.some((n) => TISCH_RE.test(n))) return true;
    // (2) The headline pairs the two, or it's a joint statement.
    if (/joint statement/i.test(title)) return true;
    if (/(mamdani|mayor)\b[^.]*\b(and|joins?|with|&)\b[^.]*\btisch/i.test(title)) return true;
    if (/\btisch\b[^.]*\b(and|joins?|with|&)\b[^.]*(mamdani|mayor)/i.test(title)) return true;
    // (3) The Mayor is present and his remarks place Tisch at the event.
    const mamPresent =
      names.some((n) => MAMDANI_RE.test(n)) ||
      it.mayor_word_count > 0 ||
      it.type === "press_conference" ||
      it.type === "ceremony" ||
      it.type === "statement";
    if (!mamPresent) return false;
    const low = txt.toLowerCase();
    let i = -1;
    while ((i = low.indexOf("tisch", i + 1)) !== -1) {
      const win = txt.slice(Math.max(0, i - 90), i + 90);
      if (/joining me|join me|with us|with me|here today|here with|joined by|alongside|standing|thank(?:s| you)?[^.]{0,40}tisch|tisch[^.]{0,40}(joining|join|thank)/i.test(win)) {
        return true;
      }
    }
    return false;
  }
  function tagCoAppearances() {
    SPOTLIGHT_COUNT = 0;
    BRIEFINGS_COUNT = 0;
    CORPUS.items.forEach((it) => {
      it._withTisch = isTischCoAppearance(it);
      if (it._withTisch) SPOTLIGHT_COUNT++;
      if (it.type === "crime_briefing") BRIEFINGS_COUNT++;
    });
  }

  function buildTopics() {
    const wrap = $("#topics");
    TOPICS.forEach((topic) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "topic-chip";
      b.dataset.topic = topic;
      b.innerHTML = `<span class="topic-label">${escapeHtml(topic)}</span><span class="topic-count" data-topic-count></span>`;
      b.addEventListener("click", () => toggleTopic(topic));
      wrap.appendChild(b);
    });
  }

  // ---- trends view (themes over time + monthly digest) ----
  function buildTrends() {
    if (!THEMES) return;
    renderTrendLegend();
    renderTrendChart();
    renderSpeech();
    renderDigest();
  }

  // ---- the mayor's language (word cloud + signature phrases) ----
  function renderSpeech() {
    const section = $("#speech");
    if (!section) return;
    const cloud = THEMES.wordcloud || [];
    const phrases = THEMES.signaturePhrases || [];
    // Older topics.json (before this feature) won't have the fields — hide.
    if (!cloud.length && !phrases.length) {
      section.hidden = true;
      return;
    }
    section.hidden = false;

    const lang = THEMES.language || {};
    if (lang.mayor_words && lang.mayor_items) {
      const note = $("#speech-note");
      if (note && !note.dataset.counted) {
        const words = Math.round(lang.mayor_words / 1000) + ",000";
        note.insertAdjacentHTML(
          "beforeend",
          ` <span class="speech-basis">Based on about ${words} words across ${lang.mayor_items} items.</span>`
        );
        note.dataset.counted = "1";
      }
    }

    // Word cloud: font size scales with the square root of frequency (so the
    // biggest word doesn't dwarf everything), colour deepens with rank.
    const cwrap = $("#wordcloud");
    if (cwrap) {
      cwrap.innerHTML = "";
      const counts = cloud.map((w) => w.count);
      const min = Math.min(...counts), max = Math.max(...counts);
      const lo = Math.sqrt(min), hi = Math.sqrt(max);
      cloud.forEach((w) => {
        const t = hi > lo ? (Math.sqrt(w.count) - lo) / (hi - lo) : 1; // 0..1
        const size = (0.8 + t * 2.0).toFixed(2); // rem
        const weight = t > 0.66 ? 700 : t > 0.33 ? 600 : 500;
        const color = t > 0.66 ? "var(--vc-orange)" : t > 0.33 ? "var(--vc-black)" : "var(--vc-charcoal)";
        const b = document.createElement("button");
        b.type = "button";
        b.className = "cloud-word";
        b.style.fontSize = size + "rem";
        b.style.fontWeight = weight;
        b.style.color = color;
        b.textContent = w.word;
        b.title = `“${w.word}” — ${w.count.toLocaleString()} times`;
        b.setAttribute("aria-label", `${w.word}, said ${w.count} times`);
        b.addEventListener("click", () => searchMayorPhrase(w.word));
        cwrap.appendChild(b);
      });
    }

    // Signature phrases.
    const pwrap = $("#signature-phrases");
    if (pwrap) {
      pwrap.innerHTML = "";
      phrases.forEach((p) => {
        const li = document.createElement("li");
        li.className = "phrase-item";
        const example = p.example
          ? `<p class="phrase-example">&ldquo;${escapeHtml(p.example)}&rdquo;` +
            (p.exampleUrl
              ? ` <a class="phrase-src" href="${escapeHtml(p.exampleUrl)}" target="_blank" rel="noopener" title="${escapeHtml(p.exampleTitle || "Source")}">↗</a>`
              : "") +
            `</p>`
          : "";
        li.innerHTML =
          `<button type="button" class="phrase-btn">` +
          `<span class="phrase-text">&ldquo;${escapeHtml(p.phrase)}&rdquo;</span>` +
          `<span class="phrase-stat">${p.events} events &middot; ${p.total}&times;</span>` +
          `</button>` +
          example;
        li.querySelector(".phrase-btn").addEventListener("click", () => searchMayorPhrase(p.phrase));
        pwrap.appendChild(li);
      });
    }
  }

  // Jump from a word/phrase to a live, mayor-only keyword search for it.
  function searchMayorPhrase(phrase) {
    TOPIC_FILTER = null;
    renderActiveTopic();
    FEATURED = null;
    renderFeatured();
    if (MODE === "semantic") setMode("keyword");
    const mo = $("#mayor-only");
    if (mo) mo.checked = true;
    // Show every item — the mayor-only filter does the narrowing to his words,
    // so enabling all types and widening scope to every agency surfaces his
    // complete usage (his quotes inside agency press releases are his words too,
    // but agencies are hidden in the default "Mayor & City Hall" scope).
    $$('input[name="type"]').forEach((c) => (c.checked = true));
    setScopeCheckboxes("admin");
    renderScope();
    const inp = $("#q");
    inp.value = /\s/.test(phrase) ? `"${phrase}"` : phrase;
    setView("search");
    runSearch();
    inp.focus();
  }

  // Themes ordered by overall volume; clicking one filters the archive to it.
  function topicsByVolume() {
    return [...THEMES.taxonomy].sort(
      (a, b) => (THEMES.totals[b.id] || 0) - (THEMES.totals[a.id] || 0)
    );
  }

  function renderTrendLegend() {
    const wrap = $("#trend-legend");
    wrap.innerHTML = "";
    topicsByVolume().forEach((t) => {
      const n = THEMES.totals[t.id] || 0;
      const b = document.createElement("button");
      b.type = "button";
      b.className = "legend-chip";
      b.dataset.topic = t.id;
      b.innerHTML =
        `<span class="legend-swatch" style="background:${t.color}"></span>` +
        `<span class="legend-name">${escapeHtml(t.label)}</span>` +
        `<span class="legend-count">${n}</span>`;
      b.addEventListener("click", () => filterByTopic(t.id));
      wrap.appendChild(b);
    });
  }

  function renderTrendChart() {
    const svg = $("#trend-chart");
    const months = THEMES.months;
    const order = topicsByVolume(); // legend order = stack order (biggest at base)
    const totalsPerMonth = months.map((m) =>
      order.reduce((s, t) => s + (THEMES.monthly[m]?.[t.id] || 0), 0)
    );
    const maxTotal = Math.max(...totalsPerMonth, 1);

    const W = 760, H = 300, padL = 8, padR = 8, padT = 18, padB = 34;
    const plotW = W - padL - padR;
    const plotH = H - padT - padB;
    const slot = plotW / months.length;
    const barW = Math.min(74, slot * 0.66);

    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("width", "100%");
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");

    let html = "";
    months.forEach((m, mi) => {
      const x = padL + mi * slot + (slot - barW) / 2;
      let yCursor = padT + plotH; // start at baseline, stack upward
      order.forEach((t) => {
        const c = THEMES.monthly[m]?.[t.id] || 0;
        if (!c) return;
        const segH = (c / maxTotal) * plotH;
        yCursor -= segH;
        html +=
          `<rect class="trend-seg" data-topic="${t.id}" data-month="${m}" ` +
          `x="${x.toFixed(1)}" y="${yCursor.toFixed(1)}" width="${barW.toFixed(1)}" height="${segH.toFixed(1)}" ` +
          `fill="${t.color}"><title>${formatMonthLong(m)} — ${escapeHtml(t.label)}: ${c} item${c === 1 ? "" : "s"}</title></rect>`;
      });
      // Month label.
      const cx = x + barW / 2;
      html += `<text x="${cx.toFixed(1)}" y="${H - 16}" text-anchor="middle" class="trend-xlabel">${formatMonthShort(m)}</text>`;
      // Partial-month note for the most recent month if it has few days.
      html += `<text x="${cx.toFixed(1)}" y="${(padT - 5).toFixed(1)}" text-anchor="middle" class="trend-total">${totalsPerMonth[mi]}</text>`;
    });
    svg.innerHTML = html;

    // Clicking a segment filters to that theme.
    svg.querySelectorAll(".trend-seg").forEach((seg) => {
      seg.style.cursor = "pointer";
      seg.addEventListener("click", () => filterByTopic(seg.dataset.topic));
    });
    $("#trend-caption").textContent =
      `Items tagged per theme, by month (an item can carry up to three themes). Number above each column is that month's total tags. Click a segment to read those items.`;
  }

  function renderDigest() {
    const wrap = $("#digest");
    wrap.innerHTML = "";
    // Most recent month first.
    const months = [...THEMES.digest].reverse();
    months.forEach((dg) => {
      if (!dg.topTopics.length) return;
      const card = document.createElement("article");
      card.className = "digest-card";
      const themeList = dg.topTopics
        .map((t) => `<button type="button" class="digest-theme" data-topic="${t.id}">${escapeHtml(t.label)} <span>${t.count}</span></button>`)
        .join("");
      let quotesHtml = "";
      dg.topTopics.forEach((tt) => {
        const qs = dg.quotes[tt.id] || [];
        qs.forEach((q) => {
          quotesHtml +=
            `<blockquote class="digest-quote">` +
            `<span class="digest-quote-theme" style="color:${(THEMES.taxonomy.find((x) => x.id === tt.id) || {}).color || ""}">${escapeHtml(tt.label)}</span>` +
            `&ldquo;${escapeHtml(q.text)}&rdquo;` +
            `<cite><a href="${q.url}" target="_blank" rel="noopener">${escapeHtml(q.title)} ↗</a></cite>` +
            `</blockquote>`;
        });
      });
      card.innerHTML =
        `<h4 class="digest-month vc-gascogne">${formatMonthLong(dg.month)}</h4>` +
        `<p class="digest-meta">${dg.items} item${dg.items === 1 ? "" : "s"} · leading themes:</p>` +
        `<div class="digest-themes">${themeList}</div>` +
        `<div class="digest-quotes">${quotesHtml}</div>`;
      card.querySelectorAll(".digest-theme").forEach((b) => {
        b.addEventListener("click", () => filterByTopic(b.dataset.topic));
      });
      wrap.appendChild(card);
    });
  }

  function formatMonthLong(ym) {
    const [y, m] = ym.split("-").map(Number);
    const months = ["January","February","March","April","May","June","July","August","September","October","November","December"];
    return `${months[m - 1]} ${y}`;
  }

  // Topic chip clicks toggle a token (or quoted phrase) in/out of the query.
  // Multi-word topics like "child care" become "child care" (a quoted phrase).
  function toggleTopic(topic) {
    const inp = $("#q");
    const current = inp.value;
    const wantTok = topic.includes(" ") ? `"${topic}"` : topic;
    // See whether wantTok is already in the query.
    const re = new RegExp(
      "(^|\\s)" + escapeRegex(wantTok) + "(\\s|$)",
      "i"
    );
    let next;
    if (re.test(current)) {
      next = current.replace(re, " ").replace(/\s+/g, " ").trim();
    } else {
      next = (current.trim() + " " + wantTok).trim();
    }
    inp.value = next;
    runSearch();
    inp.focus();
  }

  function refreshChipState() {
    const q = $("#q").value;
    $$(".topic-chip").forEach((chip) => {
      const topic = chip.dataset.topic;
      const tok = topic.includes(" ") ? `"${topic}"` : topic;
      const re = new RegExp("(^|\\s)" + escapeRegex(tok) + "(\\s|$)", "i");
      chip.classList.toggle("active", re.test(q));
    });
  }

  function refreshChipCounts(currentRows, currentQuery) {
    // Show count of how many of the current-result items would survive
    // ALSO matching this topic chip — i.e. how much each chip narrows.
    if (!currentQuery) {
      $$(".topic-count[data-topic-count]").forEach((el) => (el.textContent = ""));
      return;
    }
    const allTopics = $$(".topic-chip");
    allTopics.forEach((chip) => {
      const topic = chip.dataset.topic;
      const tok = topic.includes(" ") ? `"${topic}"` : topic;
      const queryRe = new RegExp("(^|\\s)" + escapeRegex(tok) + "(\\s|$)", "i");
      const cntEl = chip.querySelector("[data-topic-count]");
      if (queryRe.test(currentQuery)) {
        cntEl.textContent = "";
        return;
      }
      // Count rows that ALSO contain the topic substring.
      const sub = new RegExp(escapeRegex(topic), "iu");
      let n = 0;
      for (const { item } of currentRows) {
        const hay = item.title + "\n" + (item.text || "");
        if (sub.test(hay)) n++;
      }
      cntEl.textContent = n > 0 ? `+${n}` : "";
    });
  }

  // ---- handlers ----
  function attachHandlers() {
    $("#q").addEventListener("input", () => {
      clearTimeout(DEBOUNCE_T);
      DEBOUNCE_T = setTimeout(runSearch, 120);
    });
    $("#clear").addEventListener("click", () => {
      $("#q").value = "";
      runSearch();
      $("#q").focus();
    });
    $$("input[name=type]").forEach((el) =>
      el.addEventListener("change", runSearch)
    );
    $$("input[name=reliability]").forEach((el) =>
      el.addEventListener("change", runSearch)
    );
    $$("input[name=sort]").forEach((el) =>
      el.addEventListener("change", runSearch)
    );
    $("#from").addEventListener("change", runSearch);
    $("#to").addEventListener("change", runSearch);
    $("#mayor-only").addEventListener("change", runSearch);
    $("#spotlight-tisch").addEventListener("click", () => toggleFeatured("tisch"));
    $("#spotlight-nypd").addEventListener("click", () => toggleFeatured("nypd"));
    $("#scope-cityhall").addEventListener("click", () => applyScope("cityhall"));
    $("#scope-nypd").addEventListener("click", () => applyScope("nypd"));
    $("#scope-admin").addEventListener("click", () => applyScope("admin"));
    $("#share").addEventListener("click", copyShareLink);
    $("#mode-keyword").addEventListener("click", () => setMode("keyword"));
    $("#mode-semantic").addEventListener("click", () => setMode("semantic"));
    $("#view-search").addEventListener("click", () => setView("search"));
    $("#view-trends").addEventListener("click", () => setView("trends"));
    window.addEventListener("popstate", () => {
      restoreFromURL();
      applyMode();
      runSearch();
    });
  }

  function setMode(m) {
    if (m === MODE) return;
    MODE = m;
    applyMode();
    if (m === "semantic") ensureSemantic(); // warm up the model
    runSearch();
    $("#q").focus();
  }

  // Reflect MODE in the controls (button state, placeholder, hint).
  function applyMode() {
    const semantic = MODE === "semantic";
    const kb = $("#mode-keyword");
    const sb = $("#mode-semantic");
    kb.classList.toggle("active", !semantic);
    sb.classList.toggle("active", semantic);
    kb.setAttribute("aria-selected", String(!semantic));
    sb.setAttribute("aria-selected", String(semantic));
    $("#mode-hint").classList.toggle("hidden", !semantic);
    $("#q").placeholder = semantic
      ? "Ask in plain language, e.g. how will buses become free?"
      : "Search — multiple words narrow (AND); use quotes for an exact phrase, e.g. “rent freeze”";
  }

  // ---- views (search vs. trends) ----
  function setView(v) {
    if (v === VIEW) return;
    VIEW = v;
    applyView();
  }

  function applyView() {
    const trends = VIEW === "trends";
    const sv = $("#view-search");
    const tv = $("#view-trends");
    sv.classList.toggle("active", !trends);
    tv.classList.toggle("active", trends);
    sv.setAttribute("aria-selected", String(!trends));
    tv.setAttribute("aria-selected", String(trends));
    $("#search-view").classList.toggle("hidden", trends);
    $("#trends-view").classList.toggle("hidden", !trends);
    // Hide the Trends tab entirely if topics didn't load.
    tv.classList.toggle("hidden", !THEMES);
    if (trends) window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // Restrict the result set to a tagged theme, jump to search, and show a pill.
  function filterByTopic(id) {
    TOPIC_FILTER = id || null;
    renderActiveTopic();
    setView("search");
    runSearch();
  }

  // Toggle a featured filter ("tisch" or "nypd"). Mutually exclusive — clicking
  // an active chip clears it; clicking the other switches to it.
  function toggleFeatured(kind) {
    FEATURED = FEATURED === kind ? null : kind;
    // NYPD crime briefings aren't in the semantic index, so isolate them in
    // keyword mode to avoid an empty plain-language result set.
    if (FEATURED === "nypd" && MODE === "semantic") setMode("keyword");
    renderFeatured();
    setView("search");
    runSearch();
  }

  function renderFeatured() {
    const chips = [
      { id: "#spotlight-tisch", kind: "tisch", count: SPOTLIGHT_COUNT },
      { id: "#spotlight-nypd", kind: "nypd", count: BRIEFINGS_COUNT },
    ];
    chips.forEach(({ id, kind, count }) => {
      const btn = $(id);
      if (!btn) return;
      const on = FEATURED === kind;
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      btn.classList.toggle("active", on);
      const c = btn.querySelector(".spotlight-count");
      if (c) c.textContent = count ? `(${count})` : "";
    });
    // Show the note for whichever filter is active.
    const note = $("#spotlight-note");
    if (note) note.dataset.active = FEATURED || "";
  }

  function topicLabel(id) {
    const t = (THEMES && THEMES.taxonomy) ? THEMES.taxonomy.find((x) => x.id === id) : null;
    return t ? t.label : id;
  }

  function renderActiveTopic() {
    const el = $("#active-topic");
    if (!TOPIC_FILTER) {
      el.classList.add("hidden");
      el.innerHTML = "";
      return;
    }
    el.classList.remove("hidden");
    el.innerHTML =
      `<span class="active-topic-label">Theme: <strong>${escapeHtml(topicLabel(TOPIC_FILTER))}</strong></span>` +
      `<button type="button" class="active-topic-clear" aria-label="Clear theme filter">Clear &times;</button>`;
    el.querySelector(".active-topic-clear").addEventListener("click", () => {
      TOPIC_FILTER = null;
      renderActiveTopic();
      runSearch();
    });
  }

  function topicPasses(item) {
    if (!TOPIC_FILTER) return true;
    return Array.isArray(item._topics) && item._topics.includes(TOPIC_FILTER);
  }

  // Lazy-load transformers.js (from CDN) and the precomputed passage vectors.
  // Nothing here runs unless the user switches to plain-language mode, so
  // keyword users never download the model.
  function ensureSemantic() {
    if (SEM_READY) return Promise.resolve();
    if (SEM_LOADING) return SEM_LOADING;
    SEM_LOADING = (async () => {
      const [{ pipeline }, embData] = await Promise.all([
        import(SEM_CDN),
        fetch("data/embeddings.json?v=" + new Date().toISOString().slice(0, 10)).then((r) => {
          if (!r.ok) throw new Error("embeddings " + r.status);
          return r.json();
        }),
      ]);
      const bytes = Uint8Array.from(atob(embData.vectors), (c) => c.charCodeAt(0));
      const raw = new Int8Array(bytes.buffer);
      const dims = embData.dims;
      const count = embData.count;
      const mean = Float32Array.from(embData.mean);
      // Pre-center every passage vector against the corpus mean and renormalise
      // to unit length, so a query dot-product is a true cosine on the centered
      // vectors. This is what gives plain-language search its discrimination.
      const cvecs = new Float32Array(count * dims);
      for (let c = 0; c < count; c++) {
        const base = c * dims;
        let norm = 0;
        for (let d = 0; d < dims; d++) {
          const v = raw[base + d] / 127 - mean[d];
          cvecs[base + d] = v;
          norm += v * v;
        }
        norm = Math.sqrt(norm) || 1;
        for (let d = 0; d < dims; d++) cvecs[base + d] /= norm;
      }
      EMB = { dims, count, chunks: embData.chunks, mean, cvecs };
      EXTRACTOR = await pipeline("feature-extraction", embData.model);
      SEM_READY = true;
    })();
    return SEM_LOADING;
  }

  // Embed the query, score every passage by cosine similarity, and keep the
  // best-scoring passage per document.
  async function semanticRank(q) {
    await ensureSemantic();
    const out = await EXTRACTOR(q, { pooling: "mean", normalize: true });
    const { dims, count, chunks, cvecs, mean } = EMB;
    // Center the query against the same corpus mean, then renormalise.
    const qv = new Float32Array(dims);
    let qn = 0;
    for (let d = 0; d < dims; d++) {
      const v = out.data[d] - mean[d];
      qv[d] = v;
      qn += v * v;
    }
    qn = Math.sqrt(qn) || 1;
    for (let d = 0; d < dims; d++) qv[d] /= qn;

    const best = new Map(); // itemIndex -> {cos, s, e}
    for (let c = 0; c < count; c++) {
      const base = c * dims;
      let cos = 0;
      for (let d = 0; d < dims; d++) cos += qv[d] * cvecs[base + d];
      const ch = chunks[c];
      const cur = best.get(ch.i);
      if (!cur || cos > cur.cos) best.set(ch.i, { cos, s: ch.s, e: ch.e });
    }
    return best;
  }

  async function runSemanticSearch() {
    const myseq = ++SEM_SEQ;
    const q = $("#q").value.trim();
    const enabledTypes = new Set($$("input[name=type]:checked").map((el) => el.value));
    const fromIso = $("#from").value || "";
    const toIso = $("#to").value || "";
    const sortMode = $$("input[name=sort]:checked")[0]?.value || "relevance";
    const mayorOnly = $("#mayor-only").checked;
    RELIABILITY_ON = currentReliability();
    SOURCE_ON = currentSources();
    refreshChipState();

    $("#empty").classList.add("hidden");
    $("#summary").textContent = SEM_READY
      ? "Searching by meaning…"
      : "Loading the language model (first time only, ~35 MB)…";

    let best;
    try {
      best = await semanticRank(q);
    } catch (err) {
      $("#summary").textContent = "Could not load plain-language search: " + err.message;
      return;
    }
    if (myseq !== SEM_SEQ) return; // a newer query superseded this one

    let rows = [];
    for (const [i, info] of best) {
      const item = CORPUS.items[i];
      if (!itemPasses(item, enabledTypes, mayorOnly)) continue;
      if (!withinDate(item.iso_date, fromIso, toIso)) continue;
      if (!topicPasses(item)) continue;
      if (FEATURED === "tisch" && !item._withTisch) continue;
      if (FEATURED === "nypd" && item.type !== "crime_briefing") continue;
      rows.push({ item, score: info.cos, terms: [], passage: { s: info.s, e: info.e } });
    }
    // Rank by relevance, then keep the cluster near the top: above an absolute
    // floor and within a margin of the best hit. This adapts to each query so a
    // sharp query returns a tight set and a vague one returns more.
    rows.sort((a, b) => b.score - a.score);
    const top = rows.length ? rows[0].score : 0;
    const floor = Math.max(SEM_MIN_COS, top - SEM_MARGIN);
    rows = rows.filter((r) => r.score >= floor).slice(0, SEM_MAX_ROWS);
    if (sortMode === "date") {
      rows.sort((a, b) => (b.item.iso_date || "").localeCompare(a.item.iso_date || ""));
    }

    LAST_RESULTS = rows;
    writeURL({ q, fromIso, toIso, sortMode, mayorOnly, enabledTypes });
    render(rows, q, mayorOnly, { all: [] }, true);
    renderFrequency(rows, q);
    refreshChipCounts(rows, q);
  }

  async function copyShareLink() {
    const btn = $("#share");
    const url = window.location.href;
    let ok = false;
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(url);
        ok = true;
      } catch {}
    }
    if (!ok) {
      // Fallback: select a temporary input and execCommand copy.
      const tmp = document.createElement("input");
      tmp.value = url;
      document.body.appendChild(tmp);
      tmp.select();
      try { document.execCommand("copy"); ok = true; } catch {}
      document.body.removeChild(tmp);
    }
    btn.textContent = ok ? "Link copied!" : "Press Cmd+C to copy";
    btn.classList.add("copied");
    setTimeout(() => {
      btn.textContent = "Copy share link";
      btn.classList.remove("copied");
    }, 2000);
  }

  // ---- URL params ----
  function restoreFromURL() {
    URL_RESTORING = true;
    const p = new URLSearchParams(window.location.search);
    MODE = p.get("mode") === "semantic" ? "semantic" : "keyword";
    if (p.has("q")) $("#q").value = p.get("q");
    if (p.has("from")) $("#from").value = p.get("from");
    if (p.has("to")) $("#to").value = p.get("to");
    if (p.has("sort")) {
      const s = p.get("sort");
      const radio = document.querySelector(`input[name=sort][value="${s}"]`);
      if (radio) radio.checked = true;
    }
    if (p.has("mayor_only")) {
      $("#mayor-only").checked = p.get("mayor_only") === "1";
    }
    if (p.has("types")) {
      const types = new Set(p.get("types").split(","));
      $$("input[name=type]").forEach((el) => {
        el.checked = types.has(el.value);
      });
    }
    // Scope/source: ?scope= preset, ?sources= custom, else default to City Hall
    // so the Mayor stays front and center.
    if (p.has("scope")) {
      setScopeCheckboxes(p.get("scope") === "admin" ? "admin" : p.get("scope") === "nypd" ? "nypd" : "cityhall");
    } else if (p.has("sources")) {
      const srcs = new Set(p.get("sources").split(","));
      $$("input[name=source]").forEach((el) => { el.checked = srcs.has(el.value); });
    } else {
      setScopeCheckboxes("cityhall");
    }
    renderScope();
    FEATURED = p.get("with") === "tisch" ? "tisch"
      : (p.get("show") === "nypd-briefings" ? "nypd" : null);
    renderFeatured();
    URL_RESTORING = false;
  }

  function writeURL(state) {
    if (URL_RESTORING) return;
    const p = new URLSearchParams();
    if (MODE === "semantic") p.set("mode", "semantic");
    if (state.q) p.set("q", state.q);
    if (state.fromIso) p.set("from", state.fromIso);
    if (state.toIso) p.set("to", state.toIso);
    if (state.sortMode && state.sortMode !== "date") p.set("sort", state.sortMode);
    if (state.mayorOnly) p.set("mayor_only", "1");
    if (FEATURED === "tisch") p.set("with", "tisch");
    if (FEATURED === "nypd") p.set("show", "nypd-briefings");
    // Only write `types` if it's not the default set.
    const enabled = [...state.enabledTypes].sort();
    const defaults = ["agency_release", "ceremony", "crime_briefing", "hearing", "media_appearance", "op_ed", "press_conference", "speech", "statement", "video"];
    if (JSON.stringify(enabled) !== JSON.stringify(defaults)) {
      p.set("types", enabled.join(","));
    }
    // Scope/source: a recognised scope preset is written as ?scope= (City Hall
    // is the default, so it gets no param); a custom source selection as ?sources=.
    const scope = currentScope();
    if (scope === "nypd" || scope === "admin") {
      p.set("scope", scope);
    } else if (scope === null) {
      const onSrc = $$("input[name=source]").filter((b) => b.checked).map((b) => b.value);
      if (onSrc.length) p.set("sources", onSrc.sort().join(","));
    }
    const qs = p.toString();
    const newUrl = qs ? "?" + qs : window.location.pathname;
    history.replaceState(null, "", newUrl);
  }

  // ---- search ----
  // Parse a query into bare tokens and quoted phrases. `"rent freeze" Albany`
  // becomes {phrases: ["rent freeze"], tokens: ["Albany"], all: ["rent freeze", "Albany"]}.
  function parseQuery(q) {
    const phrases = [];
    let stripped = q;
    // Pull out double-quoted phrases first.
    stripped = stripped.replace(/[“"]([^”"]+)[”"]/g, (_, p) => {
      const phrase = p.trim();
      if (phrase) phrases.push(phrase);
      return " ";
    });
    const tokens = stripped
      .split(/\s+/)
      .map((s) => s.trim())
      .filter((s) => s.length >= 2);
    const all = [...phrases, ...tokens];
    // For MiniSearch we still want a token-style query (it doesn't natively
    // support phrase queries). The phrase will be re-checked as a substring
    // after the tokenized search runs.
    const minisearchQuery = [...phrases.flatMap((p) => p.split(/\s+/)), ...tokens]
      .filter((s) => s.length >= 2)
      .join(" ");
    return { phrases, tokens, all, minisearchQuery };
  }

  function runSearch() {
    const q = $("#q").value.trim();
    // Plain-language mode handles a non-empty query asynchronously. With an
    // empty query there's nothing to rank, so fall through to the shared
    // date-sorted listing below.
    if (MODE === "semantic" && q) {
      runSemanticSearch();
      return;
    }
    const enabledTypes = new Set(
      $$("input[name=type]:checked").map((el) => el.value)
    );
    const fromIso = $("#from").value || "";
    const toIso = $("#to").value || "";
    const sortMode = $$("input[name=sort]:checked")[0]?.value || "date";
    const mayorOnly = $("#mayor-only").checked;
    const parsed = parseQuery(q);
    RELIABILITY_ON = currentReliability();
    SOURCE_ON = currentSources();
    refreshChipState();

    // When "Only the Mayor's words" is on, pull press releases that have
    // Mayor quotes into the result set even if the chip isn't checked —
    // those quotes are exactly what the user is asking to see.
    const effectiveTypes = new Set(enabledTypes);
    if (mayorOnly) effectiveTypes.add("other_with_quotes");

    let rows;
    if (q.length === 0) {
      rows = CORPUS.items
        .filter((it) => itemPasses(it, enabledTypes, mayorOnly))
        .filter((it) => withinDate(it.iso_date, fromIso, toIso))
        .map((it) => ({ item: it, score: 0, terms: [] }));
    } else {
      // Use the tokenized version of the query for MiniSearch.
      const hits = parsed.minisearchQuery
        ? MS.search(parsed.minisearchQuery)
        : [];
      rows = hits
        .map((h) => ({
          item: CORPUS.items[h.id],
          score: h.score,
          terms: h.terms,
        }))
        .filter(({ item }) => itemPasses(item, enabledTypes, mayorOnly))
        .filter(({ item }) => withinDate(item.iso_date, fromIso, toIso));

      // Build the substring/phrase regex set. Every entry in parsed.all must
      // appear (AND semantics). Quoted phrases are matched as substrings; bare
      // tokens are matched word-bounded so "rent" doesn't pick up "different".
      const allRequirements = parsed.all
        .filter((s) => s.length >= 2)
        .map((s) => {
          if (s.includes(" ")) {
            // Phrase: collapse internal whitespace, match any whitespace.
            const pat = s
              .split(/\s+/)
              .map(escapeRegex)
              .join("\\s+");
            return new RegExp(pat, "iu");
          }
          // Token: substring-match if it's <=4 chars (acronyms like ICE,
          // FHEPS); otherwise allow it inside larger words too (matches
          // MiniSearch's prefix behavior).
          return new RegExp(escapeRegex(s), "iu");
        });

      // Substring/phrase fallback: pull in any docs that contain ALL phrases
      // and tokens but were missed by the tokenized index (mainly: items
      // with phrases that don't appear as separate tokens).
      if (allRequirements.length) {
        const matchedIds = new Set(rows.map((r) => r.item._id));
        for (const it of CORPUS.items) {
          if (matchedIds.has(it._id)) continue;
          if (!itemPasses(it, enabledTypes, mayorOnly)) continue;
          if (!withinDate(it.iso_date, fromIso, toIso)) continue;
          const hay = mayorOnly
            ? (it.title + "\n" + (it.mayor_text || ""))
            : (it.title + "\n" + (it.text || ""));
          if (allRequirements.every((re) => re.test(hay))) {
            rows.push({
              item: it,
              score: 0.5,
              terms: parsed.all,
              substring: true,
            });
            matchedIds.add(it._id);
          }
        }
      }

      // Strict requirement check: every doc in rows must contain every
      // phrase/token (in mayor_text if mayor-only is on, else full text).
      // This prunes MiniSearch hits that matched some terms but not all
      // phrases.
      if (allRequirements.length) {
        rows = rows.filter(({ item }) => {
          const hay = mayorOnly
            ? (item.mayor_text || "")
            : (item.title + "\n" + (item.text || ""));
          if (mayorOnly && !hay) return false;
          return allRequirements.every((re) => re.test(hay));
        });
      }
    }

    if (TOPIC_FILTER) rows = rows.filter(({ item }) => topicPasses(item));
    if (FEATURED === "tisch") rows = rows.filter(({ item }) => item._withTisch);
    if (FEATURED === "nypd") rows = rows.filter(({ item }) => item.type === "crime_briefing");

    if (sortMode === "date" || q.length === 0) {
      rows.sort((a, b) =>
        (b.item.iso_date || "").localeCompare(a.item.iso_date || "")
      );
    }
    LAST_RESULTS = rows;
    writeURL({ q, fromIso, toIso, sortMode, mayorOnly, enabledTypes });
    render(rows, q, mayorOnly, parsed);
    renderFrequency(rows, q);
    refreshChipCounts(rows, q);
  }

  // Read the reliability checkboxes; null means "no filter" (all pass).
  function currentReliability() {
    const boxes = $$("input[name=reliability]");
    if (!boxes.length) return null;
    const on = new Set(boxes.filter((b) => b.checked).map((b) => b.value));
    return on.size === boxes.length ? null : on;
  }

  // Read the source/agency checkboxes; null means "no filter" (all pass).
  function currentSources() {
    const boxes = $$("input[name=source]");
    if (!boxes.length) return null;
    const on = new Set(boxes.filter((b) => b.checked).map((b) => b.value));
    return on.size === boxes.length ? null : on;
  }

  // Build the source/agency filter from the corpus's source counts. Dynamic so
  // newly-added agencies appear automatically. Mayor's Office first, then other
  // transcript sources, then city agencies; by volume within each group.
  function buildSourceFilter() {
    const wrap = $("#sources");
    if (!wrap) return;
    const counts = (CORPUS && CORPUS.source_counts) || {};
    const rank = (s) => (s === "nyc.gov" ? 0 : AGENCY_SOURCES.includes(s) ? 2 : 1);
    const order = Object.keys(counts).sort(
      (a, b) => rank(a) - rank(b) || (counts[b] - counts[a])
    );
    wrap.innerHTML = "";
    order.forEach((src) => {
      const label = document.createElement("label");
      label.innerHTML =
        `<input type="checkbox" name="source" value="${escapeHtml(src)}" checked /> ` +
        `${escapeHtml(sourceLabel(src))} <span class="count">(${counts[src]})</span>`;
      wrap.appendChild(label);
    });
    $$("input[name=source]").forEach((el) =>
      el.addEventListener("change", () => { renderScope(); runSearch(); })
    );
  }

  // ---- search scope (City Hall / + NYPD / whole administration) -------------
  // A fast preset over the granular source checkboxes: keeps the Mayor front and
  // center by default, with the rest of the administration one click away.
  function setScopeCheckboxes(scope) {
    const on = new Set(scopeSources(scope));
    $$("input[name=source]").forEach((b) => { b.checked = on.has(b.value); });
  }
  function currentScope() {
    const checked = new Set(
      $$("input[name=source]").filter((b) => b.checked).map((b) => b.value)
    );
    for (const s of ["cityhall", "nypd", "admin"]) {
      const want = new Set(scopeSources(s));
      if (checked.size === want.size && [...checked].every((v) => want.has(v))) return s;
    }
    return null; // a custom source selection — no preset is highlighted
  }
  function applyScope(scope) {
    setScopeCheckboxes(scope);
    renderScope();
    runSearch();
  }
  function renderScope() {
    const active = currentScope();
    [["cityhall", "#scope-cityhall"], ["nypd", "#scope-nypd"], ["admin", "#scope-admin"]]
      .forEach(([s, id]) => {
        const b = $(id);
        if (!b) return;
        b.classList.toggle("active", s === active);
        b.setAttribute("aria-pressed", s === active ? "true" : "false");
      });
  }
  function renderScopeCounts() {
    const counts = (CORPUS && CORPUS.source_counts) || {};
    const sum = (srcs) => srcs.reduce((n, s) => n + (counts[s] || 0), 0);
    const map = {
      cityhall: sum(scopeSources("cityhall")),
      nypd: sum(scopeSources("nypd")),
      admin: sum(scopeSources("admin")),
    };
    Object.entries(map).forEach(([k, n]) => {
      const el = document.querySelector(`[data-scope-count="${k}"]`);
      if (el) el.textContent = n ? `(${n})` : "";
    });
  }

  function itemPasses(it, enabledTypes, mayorOnly) {
    // "Only the Mayor's words" is a deliberate lens — it always applies, even to
    // a featured set.
    if (mayorOnly) {
      // Strict: only include items where there's text we know the Mayor
      // himself said (transcript turns where he was the speaker, the entire
      // body of his speeches/statements/ceremonies, or his attributed
      // quotes inside press releases).
      if (!it.mayor_text) return false;
      // Press releases sneak in regardless of the type chip when they
      // contain a Mamdani quote.
      if (it.type === "other") return !!it.has_mayor_quotes;
    }
    // Featured chips ("Tisch together", "NYPD crime briefings") are an explicit
    // selection — authoritative over the scope/source, reliability and type
    // filters, so the highlighted set shows even from a narrower scope.
    if (FEATURED === "tisch" && it._withTisch) return true;
    if (FEATURED === "nypd" && it.type === "crime_briefing") return true;
    if (SOURCE_ON && !SOURCE_ON.has(it.source || "nyc.gov")) return false;
    if (RELIABILITY_ON && !RELIABILITY_ON.has(it.reliability || "official")) {
      return false;
    }
    return enabledTypes.has(it.type);
  }

  function tokenizeQuery(q) {
    return q
      .toLowerCase()
      .split(/\s+/)
      .map((s) => s.replace(/[^\p{L}\p{N}-]/gu, ""))
      .filter((s) => s.length >= 3);
  }

  function withinDate(iso, from, to) {
    if (!iso) return true;
    if (from && iso < from) return false;
    if (to && iso > to) return false;
    return true;
  }

  // ---- frequency sparkline ----
  function renderFrequency(rows, q) {
    const wrap = $("#frequency");
    if (!q || rows.length === 0) {
      wrap.classList.add("hidden");
      return;
    }
    // Bucket rows by month.
    const buckets = new Map();
    rows.forEach(({ item }) => {
      if (!item.iso_date) return;
      const ym = item.iso_date.slice(0, 7);
      buckets.set(ym, (buckets.get(ym) || 0) + 1);
    });
    // Build full month range from corpus min/max so empty months show.
    const allDates = CORPUS.items.map((i) => i.iso_date).filter(Boolean).sort();
    if (allDates.length === 0) return;
    const start = allDates[0].slice(0, 7);
    const end = allDates[allDates.length - 1].slice(0, 7);
    const months = monthRange(start, end);
    const counts = months.map((m) => buckets.get(m) || 0);
    const max = Math.max(...counts, 1);

    const w = 480;
    const h = 36;
    const slotW = w / months.length;
    const barW = Math.max(4, slotW * 0.55);
    const svg = $("#frequency-chart");
    svg.setAttribute("viewBox", `0 0 ${w} ${h + 14}`);
    svg.setAttribute("width", "100%");
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");

    let html = "";
    counts.forEach((c, i) => {
      const bh = c === 0 ? 1 : Math.max(2, (c / max) * h);
      const x = i * slotW + (slotW - barW) / 2;
      const y = h - bh;
      const fill = c === 0 ? "var(--vc-cloud)" : "var(--vc-orange)";
      html += `<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${barW.toFixed(2)}" height="${bh.toFixed(2)}" fill="${fill}"><title>${months[i]}: ${c}</title></rect>`;
    });
    // Month labels — first, last, and any peak.
    const labelIdxs = new Set([0, months.length - 1]);
    const peakIdx = counts.indexOf(max);
    if (peakIdx > 0 && peakIdx < months.length - 1) labelIdxs.add(peakIdx);
    labelIdxs.forEach((i) => {
      const x = i * slotW + slotW / 2;
      const m = months[i];
      const lbl = formatMonthShort(m);
      html += `<text x="${x.toFixed(2)}" y="${h + 11}" text-anchor="middle" font-size="9" font-family="halyard-text, sans-serif" fill="var(--vc-charcoal)">${lbl}${counts[i] === max && max > 1 ? ` · ${max}` : ""}</text>`;
    });
    svg.innerHTML = html;
    $("#frequency-term").textContent = `“${q}”`;
    wrap.classList.remove("hidden");
  }

  function monthRange(startYM, endYM) {
    const out = [];
    const [sy, sm] = startYM.split("-").map(Number);
    const [ey, em] = endYM.split("-").map(Number);
    let y = sy, m = sm;
    while (y < ey || (y === ey && m <= em)) {
      out.push(`${y}-${String(m).padStart(2, "0")}`);
      m++;
      if (m > 12) { m = 1; y++; }
    }
    return out;
  }

  function formatMonthShort(ym) {
    const [y, m] = ym.split("-").map(Number);
    const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return `${months[m - 1]} ${String(y).slice(2)}`;
  }

  // ---- render ----
  function render(rows, q, mayorOnly, parsed, semantic) {
    const list = $("#results");
    list.innerHTML = "";
    const empty = $("#empty");
    const summary = $("#summary");

    if (rows.length === 0) {
      empty.classList.remove("hidden");
      summary.textContent = q
        ? semantic
          ? `Nothing closely related to “${q}”${mayorOnly ? " in the mayor's words" : ""}. Try rephrasing.`
          : `No matches for “${q}”${mayorOnly ? " in the mayor's words" : ""}.`
        : "No items match your filters.";
      return;
    }
    empty.classList.add("hidden");
    const scopeNote = mayorOnly ? " in the mayor's words" : "";
    if (semantic) {
      summary.textContent =
        `${rows.length} item${rows.length === 1 ? "" : "s"} most related to “${q}”${scopeNote}, ranked by relevance.`;
    } else {
      summary.textContent = q
        ? `${rows.length} item${rows.length === 1 ? "" : "s"} matching “${q}”${scopeNote}.`
        : `Showing ${rows.length} item${rows.length === 1 ? "" : "s"}${mayorOnly ? " (mayor's words only)" : ""}.`;
    }

    // Build highlight regex from parsed query: phrases highlight as
    // whole units (longest-first so "vital city" wins over "vital" / "city").
    let re = null;
    if (parsed && parsed.all && parsed.all.length) {
      const sorted = [...parsed.all].sort((a, b) => b.length - a.length);
      const alts = sorted.map((s) => {
        if (s.includes(" ")) {
          return s.split(/\s+/).map(escapeRegex).join("\\s+");
        }
        return escapeRegex(s);
      });
      re = new RegExp("(" + alts.join("|") + ")", "giu");
    } else if (q) {
      const terms = extractTerms(q, rows);
      if (terms.length) re = buildHighlightRe(terms);
    }

    const frag = document.createDocumentFragment();
    rows.forEach((row, i) => {
      frag.appendChild(buildRow(row, i, re, mayorOnly));
    });
    list.appendChild(frag);
  }

  // Pull the matched passage out of an item's body for the semantic snippet.
  function passageText(item, passage) {
    const body = item.text || "";
    let s = passage.s, e = passage.e;
    const seg = body.slice(s, e).replace(/\s+/g, " ").trim();
    const before = s > 0 ? "<span class='ellipsis'>…</span>" : "";
    const after = e < body.length ? "<span class='ellipsis'>…</span>" : "";
    return before + escapeHtml(seg) + after;
  }

  function extractTerms(q, rows) {
    const set = new Set();
    rows.forEach((r) => (r.terms || []).forEach((t) => set.add(t.toLowerCase())));
    if (set.size === 0) {
      tokenizeQuery(q).forEach((t) => set.add(t));
    }
    return Array.from(set);
  }

  function escapeRegex(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function buildHighlightRe(terms) {
    const sorted = [...terms].sort((a, b) => b.length - a.length);
    return new RegExp("(" + sorted.map(escapeRegex).join("|") + ")", "giu");
  }

  function buildRow(row, idx, re, mayorOnly) {
    const { item, passage } = row;
    const li = document.createElement("li");
    li.dataset.idx = idx;

    const rowEl = document.createElement("div");
    rowEl.className = "result-row";

    const meta = document.createElement("div");
    meta.className = "result-meta";
    const badge = document.createElement("span");
    badge.className = "badge " + item.type;
    badge.textContent = TYPE_LABEL[item.type] || item.type;
    const date = document.createElement("span");
    date.textContent = item.date || item.iso_date;
    const wc = document.createElement("span");
    wc.textContent = `${item.word_count.toLocaleString()} words`;
    meta.append(badge, date, wc);
    // Provenance: flag the source + transcript reliability for anything that
    // isn't a default official nyc.gov transcript.
    const src = item.source || "nyc.gov";
    if (src !== "nyc.gov") {
      const prov = document.createElement("span");
      prov.className = "provenance " + (item.reliability || "verified");
      const rl = RELIABILITY_LABEL[item.reliability] || "";
      prov.textContent = sourceLabel(src) + (rl ? " · " + rl : "");
      meta.append(prov);
    }
    if (item.type === "hearing" && item.is_excerpt) {
      const ex = document.createElement("span");
      ex.className = "caption-source";
      ex.textContent = `excerpt of ${item.full_word_count.toLocaleString()} words — full transcript in linked PDF`;
      meta.append(ex);
    }
    if ((item.type === "other" || item.type === "crime_briefing") && item.mayor_quotes && item.mayor_quotes.length) {
      // Only flag "Mamdani quoted" when the search match is actually inside
      // one of the Mamdani quotes — otherwise the press release matched on
      // some third-party quote and the flag would be misleading.
      const matchInQuote = !re || item.mayor_quotes.some((q) => {
        const r = new RegExp(re.source, re.flags);
        return r.test(q);
      });
      if (matchInQuote) {
        const qm = document.createElement("span");
        qm.className = "quote-flag";
        qm.textContent = re
          ? "Mamdani quoted on this"
          : `${item.mayor_quotes.length} Mamdani quote${item.mayor_quotes.length === 1 ? "" : "s"}`;
        meta.append(qm);
      }
    }
    // Legacy video items (captured before the source/reliability schema) still
    // carry their caption-source note; newer ones use the provenance chip above.
    if (item.type === "video" && item.caption_source && !item.source) {
      const cs = document.createElement("span");
      cs.className = "caption-source";
      cs.textContent = item.caption_source === "manual"
        ? "manual captions"
        : "auto-captions (may contain errors)";
      meta.append(cs);
    }

    const title = document.createElement("h2");
    title.className = "result-title";
    title.innerHTML = highlight(item.title, re);

    const snip = document.createElement("p");
    snip.className = "result-snippet";
    // Semantic results carry the best-matching passage; show it directly
    // (there's no keyword regex to highlight in plain-language mode).
    if (passage) {
      snip.innerHTML = passageText(item, passage);
    } else {
    let snipText;
    if (mayorOnly) {
      snipText = item.mayor_text || item.text || "";
    } else if (
      (item.type === "other" || item.type === "crime_briefing")
      && item.mayor_quotes
      && item.mayor_quotes.length
      && re
    ) {
      // Press release in default mode: prefer a Mamdani-quote-bearing snippet
      // when the term appears in one of his quotes; otherwise fall through to
      // full-text snippet (we won't pretend it's his words).
      const quoteMatch = item.mayor_quotes.find((q) => {
        const r = new RegExp(re.source, re.flags);
        return r.test(q);
      });
      snipText = quoteMatch ? `"${quoteMatch}"` : (item.text || "");
    } else {
      snipText = item.text || "";
    }
    snip.innerHTML = makeSnippet(snipText, re);
    }

    const actions = document.createElement("div");
    actions.className = "result-actions";
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.textContent = mayorOnly
      ? "Read mayor's words"
      : (item.type === "hearing" && item.is_excerpt ? "Read excerpt" : "Read full text");
    toggle.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleExpand(li, item, re, toggle, mayorOnly);
    });
    actions.append(toggle);
    if (item.type === "video") {
      // Video items: only YouTube link, with timestamp jump if a match was found.
      const yt = document.createElement("a");
      yt.href = ytUrlWithTimestamp(item, re);
      yt.target = "_blank";
      yt.rel = "noopener";
      yt.textContent = re ? "Watch on YouTube at first match ↗" : "Watch on YouTube ↗";
      actions.append(yt);
    } else {
      const ext = document.createElement("a");
      ext.href = item.url;
      ext.target = "_blank";
      ext.rel = "noopener";
      const srcKey = item.source || "nyc.gov";
      const linkLabel = SOURCE_LINK_LABEL[srcKey]
        || (AGENCY_SOURCES.includes(srcKey) ? "Read release" : "View source");
      ext.textContent = linkLabel + " ↗";
      actions.append(ext);
      // If this nyc.gov event also has a YouTube video, expose it.
      if (item.youtube_url) {
        const yt = document.createElement("a");
        yt.href = item.youtube_url;
        yt.target = "_blank";
        yt.rel = "noopener";
        yt.textContent = "Watch on YouTube ↗";
        actions.append(yt);
      }
    }

    rowEl.append(meta, title, snip, actions);
    rowEl.addEventListener("click", () => toggleExpand(li, item, re, toggle, mayorOnly));
    li.appendChild(rowEl);
    return li;
  }

  // Render one paragraph-block of body text. A block whose lines are mostly
  // " | "-delimited (the pipe-row form the NYPD scraper emits for crime-stat
  // grids) becomes a real <table>; everything else stays a <p>. Input is
  // already escaped/highlighted, so cell contents are inserted as-is.
  function blockToHtml(block) {
    const lines = block.split(/\n/);
    const pipeLines = lines.filter((l) => l.includes(" | "));
    if (lines.length >= 2 && pipeLines.length >= 2 && pipeLines.length >= lines.length - 1) {
      const trs = pipeLines.map((l, idx) => {
        const tag = idx === 0 ? "th" : "td";
        const cells = l.split(" | ").map((c) => `<${tag}>${c.trim()}</${tag}>`).join("");
        return `<tr>${cells}</tr>`;
      });
      return `<table class="stat-table">${trs.join("")}</table>`;
    }
    return `<p>${block.replace(/\n/g, "<br />")}</p>`;
  }

  function toggleExpand(li, item, re, toggle, mayorOnly) {
    const existing = li.querySelector(".expanded");
    if (existing) {
      existing.remove();
      toggle.textContent = mayorOnly
      ? "Read mayor's words"
      : (item.type === "hearing" && item.is_excerpt ? "Read excerpt" : "Read full text");
      return;
    }
    const div = document.createElement("div");
    div.className = "expanded";

    let count = 0;
    const seg = (text) => {
      let body = text || "";
      if (re) {
        body = body.replace(re, (m) => {
          count++;
          return `<mark>${escapeHtml(m)}</mark>`;
        });
      } else {
        body = escapeHtml(body);
      }
      return body
        .split(/\n{2,}/)
        .map(blockToHtml)
        .join("");
    };

    let html = "";

    if (mayorOnly) {
      // Render only the Mayor's lines (or his quotes from a press release).
      if (item.speakers && item.speakers.length) {
        const mayorLines = item.speakers.filter((s) => s.is_mayor);
        if (mayorLines.length === 0) {
          html += seg(item.mayor_text || "");
        } else {
          mayorLines.forEach((s) => {
            html += `<div class="turn turn--mayor"><p class="turn-speaker">${escapeHtml(s.speaker)}</p>${seg(s.text)}</div>`;
          });
        }
      } else if (item.mayor_quotes && item.mayor_quotes.length) {
        item.mayor_quotes.forEach((q) => {
          html += `<div class="turn turn--mayor turn--quote">${seg("“" + q + "”")}</div>`;
        });
      } else {
        html += seg(item.mayor_text || item.text || "");
      }
    } else if (item.speakers && item.speakers.length) {
      // Full transcript with speaker labels per turn.
      item.speakers.forEach((s) => {
        const cls = "turn" + (s.is_mayor ? " turn--mayor" : "");
        html += `<div class="${cls}"><p class="turn-speaker">${escapeHtml(s.speaker)}</p>${seg(s.text)}</div>`;
      });
    } else {
      html += seg(item.text || "(No body text was extracted for this item.)");
    }

    div.innerHTML = html;

    if (re && count > 0) {
      const cnt = document.createElement("div");
      cnt.className = "match-count";
      cnt.textContent = `${count} match${count === 1 ? "" : "es"} highlighted${mayorOnly ? " in mayor's words" : ""}.`;
      div.prepend(cnt);
    }
    li.appendChild(div);
    toggle.textContent = "Hide";
  }

  function makeSnippet(text, re) {
    if (!text) return "<span class='ellipsis'>(No body text.)</span>";
    if (!re) {
      const s = text.slice(0, 240).replace(/\s+/g, " ").trim();
      return escapeHtml(s) + (text.length > 240 ? "<span class='ellipsis'>…</span>" : "");
    }
    const flat = text.replace(/\s+/g, " ");
    // Prefer the longest match (phrases beat single tokens) so the snippet
    // centers on "vital city" rather than the first standalone "city".
    const flatRe = new RegExp(re.source, re.flags);
    let bestMatch = null;
    let m;
    while ((m = flatRe.exec(flat)) !== null) {
      if (!bestMatch || m[0].length > bestMatch[0].length) bestMatch = m;
      if (m[0].length === 0) flatRe.lastIndex++;
      // Cap iterations so we don't scan a 50K-word body forever.
      if (flatRe.lastIndex > 30000) break;
    }
    if (!bestMatch) {
      return escapeHtml(flat.slice(0, 240)) + "<span class='ellipsis'>…</span>";
    }
    const idx = bestMatch.index;
    const start = Math.max(0, idx - 120);
    const end = Math.min(flat.length, idx + 200);
    const before = start > 0 ? "<span class='ellipsis'>…</span>" : "";
    const after = end < flat.length ? "<span class='ellipsis'>…</span>" : "";
    return before + highlight(flat.slice(start, end), re) + after;
  }

  function highlight(s, re) {
    if (!s) return "";
    if (!re) return escapeHtml(s);
    let out = "";
    let last = 0;
    const r = new RegExp(re.source, re.flags);
    let m;
    while ((m = r.exec(s)) !== null) {
      out += escapeHtml(s.slice(last, m.index)) + "<mark>" + escapeHtml(m[0]) + "</mark>";
      last = m.index + m[0].length;
      if (m[0].length === 0) r.lastIndex++;
    }
    out += escapeHtml(s.slice(last));
    return out;
  }

  function ytUrlWithTimestamp(item, re) {
    const base = item.youtube_url || item.url;
    if (!re || !item.video_segments || !item.video_segments.length) return base;
    // Find first segment whose text matches the highlight regex.
    const r = new RegExp(re.source, re.flags);
    for (const seg of item.video_segments) {
      r.lastIndex = 0;
      if (r.test(seg.text || "")) {
        const t = Math.max(0, Math.floor(seg.t || 0) - 2);
        return base + (base.includes("?") ? "&" : "?") + "t=" + t;
      }
    }
    return base;
  }

  function escapeHtml(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatRange(items) {
    const isos = items.map((i) => i.iso_date).filter(Boolean).sort();
    if (!isos.length) return "an empty range";
    return `${prettyDate(isos[0])} through ${prettyDate(isos[isos.length - 1])}`;
  }

  function prettyDate(iso) {
    if (!iso) return "";
    const [y, m, d] = iso.split("-").map(Number);
    const months = ["January","February","March","April","May","June","July","August","September","October","November","December"];
    return `${months[m - 1]} ${d}, ${y}`;
  }

  function formatGenerated(s) {
    if (!s) return "unknown";
    return s.replace("T", " ").replace("Z", " UTC");
  }
})();
