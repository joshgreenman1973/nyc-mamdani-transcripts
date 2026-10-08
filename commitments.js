/* Commitments ledger: specific, checkable promises from the mayor's remarks,
   City Hall press releases and executive orders, each quoted word for word
   from its source. Data: data/commitments.json (extract_commitments.py +
   build_commitments.py). Loaded lazily the first time the tab opens. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));

  const PAGE = 50;
  const MONTHS = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."];
  const TYPE_LABEL = {
    press_conference: "Press conference", media_appearance: "Interview", speech: "Speech",
    ceremony: "Event remarks", statement: "Statement", other: "City Hall release",
    executive_order: "Executive order", op_ed: "Op-ed",
  };

  let DATA = null, LOADING = null;
  let PROMISES = [];          // one per group of repeated commitments
  let ROWS = [], SHOWN = 0;
  let TOPIC = null, STATUS = "all", SORT = "due", QUERY = "", QUARTER = null, ROUTINE = false;
  const TODAY = new Date().toISOString().slice(0, 10);

  document.addEventListener("vc:viewchange", (e) => {
    if (e.detail === "commitments") ensureLoaded();
    else if (new URLSearchParams(location.search).get("view") === "commitments") {
      history.replaceState(null, "", location.pathname);
    }
  });

  function ensureLoaded() {
    if (DATA || LOADING) return LOADING;
    $("#cm-summary").textContent = "Loading the ledger…";
    LOADING = fetch("data/commitments.json?v=" + TODAY)
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((d) => { DATA = d; prepare(); restoreFromURL(); buildControls(); attach(); run(); })
      .catch((err) => { $("#cm-summary").textContent = "Could not load the ledger: " + err.message; });
    return LOADING;
  }

  // ---- dates ----------------------------------------------------------------
  // A due date can be a year, a month or a day; it has passed once the whole
  // period is over.
  function dueEnd(due) {
    if (!due) return null;
    const [y, m, d] = due.split("-").map(Number);
    if (d) return due;
    if (m) return `${y}-${String(m).padStart(2, "0")}-${new Date(Date.UTC(y, m, 0)).getUTCDate()}`;
    return `${y}-12-31`;
  }
  function fmtDue(due) {
    if (!due) return "";
    const [y, m, d] = due.split("-").map(Number);
    if (d) return `${MONTHS[m - 1]} ${d}, ${y}`;
    if (m) return `${MONTHS[m - 1]} ${y}`;
    return String(y);
  }
  function fmtDate(iso) {
    const [y, m, d] = iso.split("-").map(Number);
    return `${MONTHS[m - 1]} ${d}, ${y}`;
  }
  function quarterOf(due) {
    const [y, m] = due.split("-").map(Number);
    if (y >= 2030) return "2030+";
    return `${y} Q${m ? Math.ceil(m / 3) : 4}`; // a bare year counts as its last quarter
  }
  const status = (p) => (!p.due ? "none" : dueEnd(p.due) < TODAY ? "passed" : "upcoming");

  // ---- data -----------------------------------------------------------------
  function prepare() {
    const byGroup = new Map();
    DATA.commitments.forEach((c) => {
      if (!byGroup.has(c.group)) byGroup.set(c.group, []);
      byGroup.get(c.group).push(c);
    });
    PROMISES = [...byGroup.values()].map((list) => {
      list.sort((a, b) => a.item.date.localeCompare(b.item.date));
      // The most recently stated deadline is the one in force; earlier ones
      // show under "Dates given over time."
      const first = list[0];
      const lead = [...list].reverse().find((c) => c.due) || first;
      const p = {
        id: first.group, list, first, lead,
        summary: lead.summary, due: lead.due, due_text: lead.due_text, due_basis: lead.due_basis,
        topic: lead.topic, kind: lead.kind, agency: lead.agency,
        routine: list.some((c) => c.routine),
      };
      p.status = status(p);
      // Deadlines in the order they were stated, when they differ. Only dates
      // the source states outright count: "within six months" said in April
      // and again in May would otherwise look like a moved deadline.
      // "2029" and "2029-03" are the same deadline at different precision.
      const same = (a, b) => a.startsWith(b) || b.startsWith(a);
      const seq = [];
      list.forEach((c) => {
        const last = seq[seq.length - 1];
        // Two dates in one item are two parts of a promise, not a change over time.
        if (c.due && c.due_basis === "stated" && (!last || (!same(last.due, c.due) && last.item.date !== c.item.date))) seq.push(c);
      });
      p.dueHistory = seq.length > 1 ? seq : null;
      p.text = (list.map((c) => c.summary + " " + c.quote).join(" ") + " " + (p.agency || "")).toLowerCase();
      return p;
    });
  }

  function restoreFromURL() {
    const q = new URLSearchParams(location.search);
    if (q.get("view") !== "commitments") return;
    TOPIC = q.get("topic") || null;
    STATUS = q.get("status") || "all";
    SORT = q.get("sort") || "due";
    QUERY = q.get("q") || "";
    ROUTINE = q.get("routine") === "1";
    $("#cm-q").value = QUERY;
  }

  function writeURL() {
    const q = new URLSearchParams({ view: "commitments" });
    if (TOPIC) q.set("topic", TOPIC);
    if (STATUS !== "all") q.set("status", STATUS);
    if (SORT !== "due") q.set("sort", SORT);
    if (QUERY) q.set("q", QUERY);
    if (ROUTINE) q.set("routine", "1");
    history.replaceState(null, "", location.pathname + "?" + q.toString());
  }

  // ---- controls -------------------------------------------------------------
  const pool = () => PROMISES.filter((p) => ROUTINE || !p.routine);

  function buildControls() {
    const c = DATA.counts;
    const nRoutine = PROMISES.filter((p) => p.routine).length;
    $("#cm-meta").textContent =
      `${(PROMISES.length - nRoutine).toLocaleString()} distinct commitments, plus ${nRoutine.toLocaleString()} short-term or ` +
      `routine ones shown only on request, from ${c.items_with_commitments.toLocaleString()} of ${c.items_read.toLocaleString()} ` +
      `items read. ${c.rejected.toLocaleString()} more were found by the model but left out because their quote could not ` +
      `be matched word for word. Updated ${fmtDate(DATA.generated_at.slice(0, 10))}.`;
    $("#cm-routine").checked = ROUTINE;
    $("#cm-routine-n").textContent = nRoutine;
    buildTopics();
    $$("input[name=cm-status]").forEach((el) => (el.checked = el.value === STATUS));
    $$("input[name=cm-sort]").forEach((el) => (el.checked = el.value === SORT));
    buildTimeline();
  }

  function buildTopics() {
    $("#cm-topics").innerHTML = '<span class="topics-label">Themes</span>' + DATA.topics.map((t) =>
      `<button type="button" class="topic-chip${TOPIC === t.id ? " active" : ""}" data-topic="${t.id}">${esc(t.label)}` +
      `<span class="topic-count">${pool().filter((p) => p.topic === t.id).length}</span></button>`).join("");
  }

  // When the promises come due: one bar per quarter, past quarters muted.
  function buildTimeline() {
    const counts = new Map();
    pool().forEach((p) => {
      if (!p.due) return;
      const k = quarterOf(p.due);
      counts.set(k, (counts.get(k) || 0) + 1);
    });
    const keys = [...counts.keys()].sort((a, b) => (a === "2030+" ? 1 : b === "2030+" ? -1 : a.localeCompare(b)));
    const max = Math.max(1, ...counts.values());
    const nowQ = quarterOf(TODAY);
    $("#cm-timeline").innerHTML = keys.map((k) => {
      const past = k !== "2030+" && k.length > 4 && k < nowQ;
      return `<button type="button" class="cm-bar${past ? " past" : ""}${QUARTER === k ? " active" : ""}" data-q="${k}" ` +
        `title="${counts.get(k)} due in ${k}"><span class="cm-bar-fill" style="height:${Math.round((counts.get(k) / max) * 100)}%"></span>` +
        `<span class="cm-bar-n">${counts.get(k)}</span><span class="cm-bar-k">${k.replace(" ", "<br>")}</span></button>`;
    }).join("");
  }

  function attach() {
    $("#cm-q").addEventListener("input", () => { QUERY = $("#cm-q").value.trim(); run(); });
    $("#cm-clear").addEventListener("click", () => { $("#cm-q").value = ""; QUERY = ""; run(); });
    $("#cm-topics").addEventListener("click", (e) => {
      const b = e.target.closest("[data-topic]");
      if (!b) return;
      TOPIC = TOPIC === b.dataset.topic ? null : b.dataset.topic;
      $$("#cm-topics .topic-chip").forEach((el) => el.classList.toggle("active", el.dataset.topic === TOPIC));
      run();
    });
    $("#cm-timeline").addEventListener("click", (e) => {
      const b = e.target.closest("[data-q]");
      if (!b) return;
      QUARTER = QUARTER === b.dataset.q ? null : b.dataset.q;
      $$("#cm-timeline .cm-bar").forEach((el) => el.classList.toggle("active", el.dataset.q === QUARTER));
      run();
    });
    $$("input[name=cm-status]").forEach((el) => el.addEventListener("change", () => { STATUS = el.value; run(); }));
    $$("input[name=cm-sort]").forEach((el) => el.addEventListener("change", () => { SORT = el.value; run(); }));
    $("#cm-routine").addEventListener("change", () => {
      ROUTINE = $("#cm-routine").checked;
      buildTopics(); buildTimeline(); run();
    });
    $("#cm-more").addEventListener("click", () => render(SHOWN + PAGE));
    $("#cm-csv").addEventListener("click", downloadCSV);
    $("#cm-results").addEventListener("click", (e) => {
      const t = e.target.closest("[data-toggle]");
      if (t) $("#" + t.dataset.toggle).classList.toggle("hidden");
    });
  }

  // ---- filtering + rendering -----------------------------------------------
  function run() {
    const terms = QUERY.toLowerCase().split(/\s+/).filter(Boolean);
    ROWS = pool().filter((p) =>
      (!TOPIC || p.topic === TOPIC) &&
      (STATUS === "all" || p.status === STATUS) &&
      (!QUARTER || (p.due && quarterOf(p.due) === QUARTER)) &&
      terms.every((t) => p.text.includes(t)));
    const lastSaid = (p) => p.list[p.list.length - 1].item.date;
    if (SORT === "due") {
      // Coming due soonest first, then dates just passed, then undated (newest said first).
      const rank = { upcoming: 0, passed: 1, none: 2 };
      ROWS.sort((a, b) => rank[a.status] - rank[b.status] ||
        (a.status === "upcoming" ? dueEnd(a.due).localeCompare(dueEnd(b.due)) : 0) ||
        (a.status === "passed" ? dueEnd(b.due).localeCompare(dueEnd(a.due)) : 0) ||
        lastSaid(b).localeCompare(lastSaid(a)));
    } else {
      ROWS.sort((a, b) => b.list[b.list.length - 1].item.date.localeCompare(a.list[a.list.length - 1].item.date));
    }
    const n = { passed: 0, upcoming: 0, none: 0 };
    ROWS.forEach((p) => n[p.status]++);
    $("#cm-summary").textContent = `${ROWS.length.toLocaleString()} commitment${ROWS.length === 1 ? "" : "s"}: ` +
      `${n.upcoming} coming due, ${n.passed} past their stated date, ${n.none} with no date given.`;
    $("#cm-empty").classList.toggle("hidden", ROWS.length > 0);
    writeURL();
    render(PAGE);
  }

  function render(upTo) {
    SHOWN = Math.min(upTo, ROWS.length);
    $("#cm-results").innerHTML = ROWS.slice(0, SHOWN).map(card).join("");
    const more = ROWS.length - SHOWN;
    $("#cm-more").classList.toggle("hidden", more <= 0);
    $("#cm-more").textContent = `Show ${Math.min(PAGE, more)} more of ${more}`;
  }

  function dueLabel(p) {
    if (p.status === "none") return '<span class="cm-due none">No date given</span>';
    const basis = p.due_basis === "computed" && p.due_text
      ? ` <span class="cm-due-basis" title="Worked out from the phrase in the source">from &ldquo;${esc(p.due_text)}&rdquo;</span>` : "";
    if (p.status === "passed") return `<span class="cm-due passed">Date passed: ${fmtDue(p.due)}</span>${basis}`;
    return `<span class="cm-due upcoming">Due ${fmtDue(p.due)}</span>${basis}`;
  }

  function sourceLine(c) {
    const label = TYPE_LABEL[c.item.type] || "Item";
    const link = c.item.url ? `<a href="${esc(c.item.url)}" target="_blank" rel="noopener">${esc(c.item.title)}</a>` : esc(c.item.title);
    return `${label}, ${fmtDate(c.item.date)}: ${link}`;
  }

  function card(p) {
    const topic = (DATA.topics.find((t) => t.id === p.topic) || {}).label || "";
    const others = p.list.filter((c) => c !== p.lead);
    const repeatId = "cm-rep-" + p.id.replace(/[^a-z0-9-]/gi, "");
    const repeats = others.length
      ? `<p class="cm-repeat"><button type="button" class="cm-repeat-btn" data-toggle="${repeatId}">Said ${p.list.length} times, first on ${fmtDate(p.first.item.date)}</button></p>
         <ol id="${repeatId}" class="cm-repeat-list hidden">${others.map((c) =>
           `<li><blockquote class="cm-quote cm-quote--small">${esc(c.quote)}</blockquote><p class="cm-source">${sourceLine(c)}</p></li>`).join("")}</ol>`
      : "";
    return `<li class="cm-card">
      <div class="result-meta">${dueLabel(p)}<span>${esc(topic)}</span>${p.agency ? `<span>${esc(p.agency)}</span>` : ""}</div>
      <p class="cm-summary">${esc(p.summary)}</p>
      <blockquote class="cm-quote">${esc(p.lead.quote)}</blockquote>
      <p class="cm-source">${sourceLine(p.lead)}</p>
      ${p.dueHistory ? `<p class="cm-source cm-history"><strong>Dates given over time:</strong> ${p.dueHistory.map((c) =>
        `${fmtDue(c.due)} (said ${fmtDate(c.item.date)})`).join(" &rarr; ")}</p>` : ""}
      ${repeats}
    </li>`;
  }

  function downloadCSV() {
    const cols = ["summary", "due", "due_text", "status", "topic", "agency", "quote", "source_type", "source_date", "source_title", "source_url", "times_said"];
    const q = (v) => `"${String(v == null ? "" : v).replace(/"/g, '""')}"`;
    const lines = [cols.join(",")].concat(ROWS.map((p) => [
      p.summary, p.due, p.due_text, p.status, p.topic, p.agency, p.lead.quote,
      TYPE_LABEL[p.lead.item.type] || p.lead.item.type, p.lead.item.date, p.lead.item.title, p.lead.item.url, p.list.length,
    ].map(q).join(",")));
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
    a.download = `mamdani-commitments-${TODAY}.csv`;
    a.click();
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (ch) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
  }
})();
