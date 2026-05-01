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
    executive_order: "Executive order",
    other: "Press release",
  };

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
  let MS = null;
  let LAST_RESULTS = [];
  let DEBOUNCE_T = null;
  let URL_RESTORING = false; // suppress URL writes while loading params

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
      const dates = data.items.map((i) => i.iso_date).filter(Boolean).sort();
      if (dates.length) {
        $("#from").min = $("#to").min = dates[0];
        $("#from").max = $("#to").max = dates[dates.length - 1];
      }
      buildIndex();
      buildTopics();
      attachHandlers();
      restoreFromURL();
      runSearch();
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
    $$("input[name=sort]").forEach((el) =>
      el.addEventListener("change", runSearch)
    );
    $("#from").addEventListener("change", runSearch);
    $("#to").addEventListener("change", runSearch);
    $("#mayor-only").addEventListener("change", runSearch);
    window.addEventListener("popstate", () => {
      restoreFromURL();
      runSearch();
    });
  }

  // ---- URL params ----
  function restoreFromURL() {
    URL_RESTORING = true;
    const p = new URLSearchParams(window.location.search);
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
    URL_RESTORING = false;
  }

  function writeURL(state) {
    if (URL_RESTORING) return;
    const p = new URLSearchParams();
    if (state.q) p.set("q", state.q);
    if (state.fromIso) p.set("from", state.fromIso);
    if (state.toIso) p.set("to", state.toIso);
    if (state.sortMode && state.sortMode !== "date") p.set("sort", state.sortMode);
    if (state.mayorOnly) p.set("mayor_only", "1");
    // Only write `types` if it's not the default set.
    const enabled = [...state.enabledTypes].sort();
    const defaults = ["ceremony", "media_appearance", "press_conference", "speech", "statement"];
    if (JSON.stringify(enabled) !== JSON.stringify(defaults)) {
      p.set("types", enabled.join(","));
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
    const enabledTypes = new Set(
      $$("input[name=type]:checked").map((el) => el.value)
    );
    const fromIso = $("#from").value || "";
    const toIso = $("#to").value || "";
    const sortMode = $$("input[name=sort]:checked")[0]?.value || "date";
    const mayorOnly = $("#mayor-only").checked;
    const parsed = parseQuery(q);
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

    if (sortMode === "date" || q.length === 0) {
      rows.sort((a, b) =>
        (b.item.iso_date || "").localeCompare(a.item.iso_date || "")
      );
    }
    LAST_RESULTS = rows;
    writeURL({ q, fromIso, toIso, sortMode, mayorOnly, enabledTypes });
    render(rows, q, mayorOnly);
    renderFrequency(rows, q);
    refreshChipCounts(rows, q);
  }

  function itemPasses(it, enabledTypes, mayorOnly) {
    if (mayorOnly) {
      // Mayor-only: only include items where there's some Mayor text.
      if (!it.mayor_text) return false;
      // And: pull press releases with quotes in even if chip is off.
      if (it.type === "other") return !!it.has_mayor_quotes;
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

    const w = 320;
    const h = 36;
    const barW = w / months.length;
    const svg = $("#frequency-chart");
    svg.setAttribute("viewBox", `0 0 ${w} ${h + 14}`);
    svg.setAttribute("width", "100%");
    svg.setAttribute("preserveAspectRatio", "none");

    let html = "";
    counts.forEach((c, i) => {
      const bh = c === 0 ? 1 : Math.max(2, (c / max) * h);
      const x = i * barW + 0.5;
      const y = h - bh;
      const fill = c === 0 ? "var(--vc-cloud)" : "var(--vc-orange)";
      html += `<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${(barW - 1).toFixed(2)}" height="${bh.toFixed(2)}" fill="${fill}"><title>${months[i]}: ${c}</title></rect>`;
    });
    // Month labels — first, last, and any peak.
    const labelIdxs = new Set([0, months.length - 1]);
    const peakIdx = counts.indexOf(max);
    if (peakIdx > 0 && peakIdx < months.length - 1) labelIdxs.add(peakIdx);
    labelIdxs.forEach((i) => {
      const x = i * barW + barW / 2;
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
  function render(rows, q, mayorOnly) {
    const list = $("#results");
    list.innerHTML = "";
    const empty = $("#empty");
    const summary = $("#summary");

    if (rows.length === 0) {
      empty.classList.remove("hidden");
      summary.textContent = q
        ? `No matches for “${q}”${mayorOnly ? " in the Mayor's words" : ""}.`
        : "No items match your filters.";
      return;
    }
    empty.classList.add("hidden");
    const scopeNote = mayorOnly ? " in the Mayor's words" : "";
    summary.textContent = q
      ? `${rows.length} item${rows.length === 1 ? "" : "s"} matching “${q}”${scopeNote}.`
      : `Showing ${rows.length} item${rows.length === 1 ? "" : "s"}${mayorOnly ? " (Mayor's words only)" : ""}.`;

    const terms = q ? extractTerms(q, rows) : [];
    const re = terms.length ? buildHighlightRe(terms) : null;

    const frag = document.createDocumentFragment();
    rows.forEach((row, i) => {
      frag.appendChild(buildRow(row, i, re, mayorOnly));
    });
    list.appendChild(frag);
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

  function buildRow({ item }, idx, re, mayorOnly) {
    const li = document.createElement("li");
    li.dataset.idx = idx;

    const row = document.createElement("div");
    row.className = "result-row";

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
    if (item.type === "other" && item.mayor_quotes && item.mayor_quotes.length) {
      const qm = document.createElement("span");
      qm.className = "quote-flag";
      qm.textContent = `${item.mayor_quotes.length} mayor quote${item.mayor_quotes.length === 1 ? "" : "s"}`;
      meta.append(qm);
    }

    const title = document.createElement("h2");
    title.className = "result-title";
    title.innerHTML = highlight(item.title, re);

    const snip = document.createElement("p");
    snip.className = "result-snippet";
    const snipText = mayorOnly
      ? (item.mayor_text || item.text || "")
      : (item.text || "");
    snip.innerHTML = makeSnippet(snipText, re);

    const actions = document.createElement("div");
    actions.className = "result-actions";
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.textContent = mayorOnly ? "Read Mayor's words" : "Read full text";
    toggle.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleExpand(li, item, re, toggle, mayorOnly);
    });
    const ext = document.createElement("a");
    ext.href = item.url;
    ext.target = "_blank";
    ext.rel = "noopener";
    ext.textContent = "View on nyc.gov ↗";
    actions.append(toggle, ext);

    row.append(meta, title, snip, actions);
    row.addEventListener("click", () => toggleExpand(li, item, re, toggle, mayorOnly));
    li.appendChild(row);
    return li;
  }

  function toggleExpand(li, item, re, toggle, mayorOnly) {
    const existing = li.querySelector(".expanded");
    if (existing) {
      existing.remove();
      toggle.textContent = mayorOnly ? "Read Mayor's words" : "Read full text";
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
        .map((p) => `<p>${p.replace(/\n/g, "<br />")}</p>`)
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
      cnt.textContent = `${count} match${count === 1 ? "" : "es"} highlighted${mayorOnly ? " in Mayor's words" : ""}.`;
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
    const flatRe = new RegExp(re.source, re.flags);
    const fm = flatRe.exec(flat);
    if (!fm) {
      return escapeHtml(flat.slice(0, 240)) + "<span class='ellipsis'>…</span>";
    }
    const idx = fm.index;
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
