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

  let CORPUS = null;          // {items, type_counts, generated_at, ...}
  let MS = null;              // MiniSearch instance
  let LAST_QUERY = "";
  let LAST_RESULTS = [];      // current rendering: array of {item, score?, terms?}
  let DEBOUNCE_T = null;

  // ---- boot ----
  fetch("data/corpus.json")
    .then((r) => r.json())
    .then((data) => {
      CORPUS = data;
      $("#meta").textContent =
        `${data.total} items from ${formatRange(data.items)}. ` +
        `Last refreshed ${formatGenerated(data.generated_at)}.`;
      // Populate counts under each chip.
      Object.entries(data.type_counts || {}).forEach(([t, n]) => {
        const el = document.querySelector(`.count[data-count="${t}"]`);
        if (el) el.textContent = `(${n})`;
      });
      // Default date range = full archive.
      const dates = data.items.map((i) => i.iso_date).filter(Boolean).sort();
      if (dates.length) {
        $("#from").min = $("#to").min = dates[0];
        $("#from").max = $("#to").max = dates[dates.length - 1];
      }
      buildIndex();
      attachHandlers();
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
  }

  // ---- search ----
  function runSearch() {
    const q = $("#q").value.trim();
    LAST_QUERY = q;
    const enabledTypes = new Set(
      $$("input[name=type]:checked").map((el) => el.value)
    );
    const fromIso = $("#from").value || "";
    const toIso = $("#to").value || "";
    const sortMode = $$("input[name=sort]:checked")[0]?.value || "date";

    let rows;
    if (q.length === 0) {
      rows = CORPUS.items
        .filter((it) => enabledTypes.has(it.type))
        .filter((it) => withinDate(it.iso_date, fromIso, toIso))
        .map((it) => ({ item: it, score: 0, terms: [] }));
      // already sorted desc by date.
    } else {
      const hits = MS.search(q);
      rows = hits
        .map((h) => ({
          item: CORPUS.items[h.id],
          score: h.score,
          terms: h.terms,
        }))
        .filter(({ item }) => enabledTypes.has(item.type))
        .filter(({ item }) => withinDate(item.iso_date, fromIso, toIso));

      // Substring fallback. Tokenized search misses queries that appear inside
      // larger words (e.g. "FHEPS" inside "CityFHEPS", "MTA" inside
      // "MTA-related"). For each query token >= 3 chars that the index missed,
      // scan the corpus and add any documents that contain it as a substring.
      const queryTokens = q
        .toLowerCase()
        .split(/\s+/)
        .map((t) => t.replace(/[^\p{L}\p{N}-]/gu, ""))
        .filter((t) => t.length >= 3);
      if (queryTokens.length) {
        const matchedIds = new Set(rows.map((r) => r.item._id));
        const tokensRe = new RegExp(
          queryTokens.map(escapeRegex).join("|"),
          "iu"
        );
        const allTokensRe = queryTokens.map(
          (t) => new RegExp(escapeRegex(t), "iu")
        );
        for (const it of CORPUS.items) {
          if (matchedIds.has(it._id)) continue;
          if (!enabledTypes.has(it.type)) continue;
          if (!withinDate(it.iso_date, fromIso, toIso)) continue;
          const hay = it.title + "\n" + (it.text || "");
          // Require ALL query tokens to appear as substrings (matches the
          // AND combineWith of the main index).
          if (allTokensRe.every((re) => re.test(hay))) {
            rows.push({
              item: it,
              score: 0.5, // below tokenized matches when sorting by relevance
              terms: queryTokens,
              substring: true,
            });
            matchedIds.add(it._id);
          }
        }
      }
    }

    if (sortMode === "date" || q.length === 0) {
      rows.sort((a, b) => (b.item.iso_date || "").localeCompare(a.item.iso_date || ""));
    }
    LAST_RESULTS = rows;
    render(rows, q);
  }

  function withinDate(iso, from, to) {
    if (!iso) return true;
    if (from && iso < from) return false;
    if (to && iso > to) return false;
    return true;
  }

  // ---- render ----
  function render(rows, q) {
    const list = $("#results");
    list.innerHTML = "";
    const empty = $("#empty");
    const summary = $("#summary");

    if (rows.length === 0) {
      empty.classList.remove("hidden");
      summary.textContent = q
        ? `No matches for “${q}”.`
        : "No items match your filters.";
      return;
    }
    empty.classList.add("hidden");
    summary.textContent = q
      ? `${rows.length} item${rows.length === 1 ? "" : "s"} matching “${q}”.`
      : `Showing ${rows.length} item${rows.length === 1 ? "" : "s"}.`;

    const terms = q ? extractTerms(q, rows) : [];
    const re = terms.length ? buildHighlightRe(terms) : null;

    const frag = document.createDocumentFragment();
    rows.forEach((row, i) => {
      frag.appendChild(buildRow(row, i, re));
    });
    list.appendChild(frag);
  }

  function extractTerms(q, rows) {
    // Use MiniSearch-matched terms when available, fall back to query split.
    const set = new Set();
    rows.forEach((r) => (r.terms || []).forEach((t) => set.add(t.toLowerCase())));
    if (set.size === 0) {
      q.toLowerCase()
        .split(/\s+/)
        .map((s) => s.replace(/[^\p{L}\p{N}-]/gu, ""))
        .filter((s) => s.length >= 2)
        .forEach((t) => set.add(t));
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

  function buildRow({ item }, idx, re) {
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

    const title = document.createElement("h2");
    title.className = "result-title";
    title.innerHTML = highlight(item.title, re);

    const snip = document.createElement("p");
    snip.className = "result-snippet";
    snip.innerHTML = makeSnippet(item.text || "", re);

    const actions = document.createElement("div");
    actions.className = "result-actions";
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.textContent = "Read full text";
    toggle.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleExpand(li, item, re, toggle);
    });
    const ext = document.createElement("a");
    ext.href = item.url;
    ext.target = "_blank";
    ext.rel = "noopener";
    ext.textContent = "View on nyc.gov ↗";
    actions.append(toggle, ext);

    row.append(meta, title, snip, actions);
    row.addEventListener("click", () => toggleExpand(li, item, re, toggle));
    li.appendChild(row);
    return li;
  }

  function toggleExpand(li, item, re, toggle) {
    const existing = li.querySelector(".expanded");
    if (existing) {
      existing.remove();
      toggle.textContent = "Read full text";
      return;
    }
    const div = document.createElement("div");
    div.className = "expanded";
    let body = item.text || "(No body text was extracted for this item.)";
    let count = 0;
    if (re) {
      body = body.replace(re, (m) => {
        count++;
        return `<mark>${escapeHtml(m)}</mark>`;
      });
    } else {
      body = escapeHtml(body);
    }
    body = body
      .split(/\n{2,}/)
      .map((p) => `<p>${p.replace(/\n/g, "<br />")}</p>`)
      .join("");
    div.innerHTML = body;

    if (re && count > 0) {
      const cnt = document.createElement("div");
      cnt.className = "match-count";
      cnt.style.marginBottom = ".75rem";
      cnt.textContent = `${count} match${count === 1 ? "" : "es"} highlighted.`;
      div.prepend(cnt);
    }
    li.appendChild(div);
    toggle.textContent = "Hide full text";
  }

  function makeSnippet(text, re) {
    if (!text) return "<span class='ellipsis'>(No body text.)</span>";
    if (!re) {
      const s = text.slice(0, 240).replace(/\s+/g, " ").trim();
      return escapeHtml(s) + (text.length > 240 ? "<span class='ellipsis'>…</span>" : "");
    }
    const m = re.exec(text);
    re.lastIndex = 0;
    const flat = text.replace(/\s+/g, " ");
    if (!m) {
      return escapeHtml(flat.slice(0, 240)) + "<span class='ellipsis'>…</span>";
    }
    // Re-find on the flattened version so offsets line up.
    const flatRe = new RegExp(re.source, re.flags);
    const fm = flatRe.exec(flat);
    const idx = fm ? fm.index : 0;
    const start = Math.max(0, idx - 120);
    const end = Math.min(flat.length, idx + 200);
    const before = start > 0 ? "<span class='ellipsis'>…</span>" : "";
    const after = end < flat.length ? "<span class='ellipsis'>…</span>" : "";
    const slice = flat.slice(start, end);
    return before + highlight(slice, re) + after;
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
