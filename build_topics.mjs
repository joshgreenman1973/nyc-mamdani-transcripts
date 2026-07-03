/**
 * Offline topic + trend builder — no model, no API, no cost.
 *
 * Reads data/corpus.json and writes data/topics.json: a transparent,
 * keyword-lexicon classification of every item into policy topics, a
 * month-by-month count matrix for the trend chart, and an *extractive*
 * monthly digest (real, verbatim Mayor quotes — no AI-written prose).
 *
 * Every topic assignment is explainable: an item is tagged with a topic
 * when its text contains one of that topic's listed terms (whole-word,
 * case-insensitive). The full lexicon is published in topics.json and in
 * METHODOLOGY.md so nothing about the tagging is a black box.
 *
 * Run: node build_topics.mjs
 */
import { readFileSync, writeFileSync } from "node:fs";

// ---- the taxonomy (single source of truth) --------------------------------
// Each topic lists the terms that, when found as whole words in an item's
// text, tag that item with the topic. Terms are matched case-insensitively
// with word boundaries, so "rent" does not match "different" and "ICE" does
// not match "price". Items can carry multiple topics. Each topic has a
// distinct color used to identify it in the trend chart.
const TAXONOMY = [
  {
    id: "housing",
    label: "Housing & rent",
    color: "#E8541E", // orange
    terms: ["rent", "rent freeze", "rent-stabilized", "rent stabilized", "housing",
      "affordable housing", "NYCHA", "public housing", "CityFHEPS", "FHEPS",
      "eviction", "evicted", "landlord", "tenant", "tenants", "Section 8",
      "housing voucher", "homeless", "homelessness", "shelter"],
  },
  {
    id: "transit",
    label: "Transit & buses",
    color: "#13315C",
    terms: ["subway", "subways", "bus", "buses", "free buses", "fare", "fares",
      "MTA", "transit", "congestion pricing", "straphangers", "commute",
      "commuters"],
  },
  {
    id: "safety",
    label: "Public safety",
    color: "#C0392B",
    terms: ["police", "NYPD", "officers", "crime", "shooting", "shootings",
      "gun", "guns", "public safety", "precinct", "violence", "violent",
      "homicide", "subway safety", "police commissioner"],
  },
  {
    id: "immigration",
    label: "Immigration",
    color: "#6FBF3B",
    terms: ["ICE", "immigrant", "immigrants", "immigration", "deportation",
      "deport", "deported", "asylum", "sanctuary", "migrant", "migrants",
      "undocumented"],
  },
  {
    id: "childcare",
    label: "Child care & schools",
    color: "#7B4FA3",
    terms: ["child care", "childcare", "universal childcare", "day care",
      "daycare", "pre-K", "3-K", "schools", "public schools", "students",
      "teachers", "CUNY", "education", "DOE", "Department of Education"],
  },
  {
    id: "affordability",
    label: "Cost of living",
    color: "#E6A700",
    terms: ["affordability", "affordable", "cost of living", "groceries",
      "grocery", "city-owned grocery", "prices", "working-class",
      "working class", "minimum wage", "living wage", "wages",
      "cost-of-living"],
  },
  {
    id: "labor",
    label: "Jobs & labor",
    color: "#2E8B57",
    terms: ["union", "unions", "labor", "workers", "worker", "prevailing wage",
      "jobs", "hiring", "apprenticeship", "collective bargaining",
      "DC 37", "unionized"],
  },
  {
    id: "health",
    label: "Health & food",
    color: "#17A2B8",
    terms: ["health", "hospital", "hospitals", "mental health", "Medicaid",
      "Medicare", "SNAP", "food assistance", "food stamps", "public health",
      "health care", "healthcare", "overdose"],
  },
  {
    id: "federal",
    label: "Federal & Trump",
    color: "#6D213C",
    terms: ["Trump", "federal government", "Washington", "White House",
      "the administration", "federal funding", "federal cuts", "DOJ",
      "Department of Justice", "tariffs", "Congress"],
  },
  {
    id: "albany",
    label: "Albany & the state",
    color: "#3F6CB0",
    terms: ["Albany", "Hochul", "Governor", "state legislature",
      "New York State", "state budget", "state lawmakers", "the legislature",
      "assembly", "state senate"],
  },
  {
    id: "budget",
    label: "Budget & taxes",
    color: "#8A8D91",
    terms: ["budget", "taxes", "tax", "revenue", "fiscal", "deficit",
      "millionaire", "millionaires", "spending", "comptroller",
      "tax the rich"],
  },
  {
    id: "climate",
    label: "Climate & environment",
    color: "#A9772E",
    terms: ["climate", "environment", "emissions", "clean energy",
      "renewable", "extreme heat", "flooding", "resilience", "green",
      "solar", "Local Law 97"],
  },
];

// ---- matching --------------------------------------------------------------
// Compile each term into a whole-word, case-insensitive regex. Multi-word
// terms allow flexible internal whitespace. \b handles boundaries so short
// acronyms ("ICE") don't match inside larger words ("price").
function compile(term) {
  const pat = term
    .trim()
    .split(/\s+/)
    .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join("\\s+");
  // Use lookarounds rather than \b so hyphenated terms (pre-K, rent-stabilized)
  // and acronyms behave: a "word" boundary is a transition to/from a letter,
  // digit, or hyphen.
  return new RegExp("(?<![\\w-])(?:" + pat + ")(?![\\w-])", "iu");
}
const COMPILED = TAXONOMY.map((t) => ({
  ...t,
  res: t.terms.map((term) => ({ term, re: compile(term) })),
}));

// Count whole-word hits of a term in a body (capped — we only need presence
// and a rough weight, not an exact tally on a 50k-word transcript).
function countHits(body, re) {
  const g = new RegExp(re.source, re.flags.includes("g") ? re.flags : re.flags + "g");
  let n = 0;
  while (g.exec(body) && n < 50) n++;
  return n;
}

// ---- load corpus -----------------------------------------------------------
const corpus = JSON.parse(readFileSync("data/corpus.json", "utf8"));
const items = corpus.items;

// Tag every item. We score topics against the FULL text (so the chart counts
// what each event was about) and separately note hits in the Mayor's own
// words (for digest quote selection).
const itemTopics = []; // per item index: [topicId, ...] sorted by hit count
const monthly = {}; // "2026-05" -> { housing: itemCount, ... }
const months = new Set();
const totals = {};
COMPILED.forEach((t) => (totals[t.id] = 0));

items.forEach((it, idx) => {
  const text = it.text || "";
  const ym = (it.iso_date || "").slice(0, 7);
  const scored = [];
  for (const t of COMPILED) {
    let hits = 0;
    let matchedTerms = 0;
    for (const { re } of t.res) {
      const h = countHits(text, re);
      if (h > 0) {
        hits += h;
        matchedTerms++;
      }
    }
    // Require a real signal, not a single passing mention: either the topic
    // is hit several times, or two different terms from its lexicon appear.
    // This keeps a long press conference that name-checks everything from
    // being tagged with every topic.
    if (hits >= 3 || matchedTerms >= 2) scored.push({ id: t.id, hits, matchedTerms });
  }
  scored.sort((a, b) => b.hits - a.hits);
  // Keep only an item's dominant themes (top 3) so the chart reflects what an
  // event was actually about, not every subject grazed in passing.
  const topicIds = scored.slice(0, 3).map((s) => s.id);
  itemTopics.push(topicIds);

  if (ym) {
    months.add(ym);
    monthly[ym] = monthly[ym] || {};
    for (const id of topicIds) {
      monthly[ym][id] = (monthly[ym][id] || 0) + 1;
      totals[id]++;
    }
  }
});

const monthList = Array.from(months).sort();

// ---- extractive digest -----------------------------------------------------
// For each month, find the leading topics by item count, then pull real,
// verbatim Mayor quotes that best represent each one. Selection is fully
// deterministic: a quote scores by how many of the topic's terms it contains,
// favoring a readable length. We never paraphrase or summarize in our words.
const TOPIC_BY_ID = Object.fromEntries(COMPILED.map((t) => [t.id, t]));

function quoteScore(quote, topic) {
  let s = 0;
  for (const { re } of topic.res) if (re.test(quote)) s++;
  return s;
}

// Gather candidate Mayor quotes for a given month: attributed press-release
// quotes plus the Mayor's own transcript turns, split into sentences.
function mayorQuotesForMonth(ym) {
  const out = [];
  items.forEach((it, idx) => {
    if ((it.iso_date || "").slice(0, 7) !== ym) return;
    const push = (text) => {
      const clean = (text || "").replace(/\s+/g, " ").trim();
      if (clean.length >= 60 && clean.length <= 320) {
        out.push({ text: clean, i: idx, date: it.date, iso: it.iso_date, url: it.url, title: it.title });
      }
    };
    (it.mayor_quotes || []).forEach(push);
    // Mayor transcript turns: split into sentence-ish chunks.
    (it.speakers || []).forEach((sp) => {
      if (!sp || !sp.is_mayor || !sp.text) return;
      const sentences = sp.text.match(/[^.!?]+[.!?]+/g) || [sp.text];
      sentences.forEach(push);
    });
  });
  return out;
}

const digest = monthList.map((ym) => {
  const counts = monthly[ym] || {};
  const topTopics = Object.entries(counts)
    .map(([id, count]) => ({ id, label: TOPIC_BY_ID[id].label, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 4);

  const candidates = mayorQuotesForMonth(ym);
  const quotes = {};
  for (const tt of topTopics) {
    const topic = TOPIC_BY_ID[tt.id];
    const ranked = candidates
      .map((c) => ({ ...c, _s: quoteScore(c.text, topic) }))
      .filter((c) => c._s > 0)
      .sort((a, b) => b._s - a._s || a.text.length - b.text.length);
    // Dedupe near-identical quotes and take the best two.
    const picked = [];
    const seen = new Set();
    for (const c of ranked) {
      const key = c.text.slice(0, 50).toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      picked.push({ text: c.text, i: c.i, date: c.date, url: c.url, title: c.title });
      if (picked.length >= 2) break;
    }
    if (picked.length) quotes[tt.id] = picked;
  }

  // Count how many items that month had any Mayor quotes, for the digest line.
  const itemsThisMonth = items.filter((it) => (it.iso_date || "").slice(0, 7) === ym);
  return {
    month: ym,
    items: itemsThisMonth.length,
    topTopics,
    quotes,
  };
});

// ---- the mayor's language: word cloud + signature phrases ------------------
// Both are computed ONLY over the mayor's own words — the `mayor_text` field,
// which holds his transcript turns and his attributed press-release quotes,
// never reporters' questions or other speakers. Fully deterministic, no model.

// Function words and low-content fillers removed before the word count. This is
// a published list so the cloud is reproducible and nothing is a black box.
const LANG_STOP = new Set(
  `a about above after again against all also am an and any are aren't as at
   be because been before being below between both but by can can't cannot could
   couldn't did didn't do does doesn't doing don't down during each few for from
   further get gets getting go goes going gone got had hadn't has hasn't have
   haven't having he he'd he'll he's her here here's hers herself him himself his
   how how's i i'd i'll i'm i've if in into is isn't it it's its itself just let
   let's me more most mustn't my myself no nor not of off on once only or other
   ought our ours ourselves out over own really said same say says see seen shan't
   she she'd she'll she's should shouldn't so some such than that that's the their
   theirs them themselves then there there's these they they'd they'll they're
   they've this those through to too under until up upon very want wants was wasn't
   way ways we we'd we'll we're we've well were weren't what what's when when's
   where where's which while who who's whom why why's will with won't would
   wouldn't you you'd you'll you're you've your yours yourself yourselves
   gonna gotta wanna kinda sorta lotta dunno cannot
   able across actually already always another any anymore anyone anything around
   back become becomes becoming came come comes coming done enough even ever every
   everybody everyone everything far give given gives giving good great happen
   happens keep kept know known knows lot lots made make makes making many maybe
   might much need needs never new next often okay part parts perhaps put puts
   quite rather right seem seems seen simply since something sometimes soon still
   sure take takes taking tell tells thing things think thinks thought today
   together took toward towards understand use used uses using whatever whatever's
   whether within without york yeah thank thanks number kind sort lot bit
   one two three four five six seven eight nine ten first second third now
   like look looks looking looked`.split(
    /\s+/,
  ),
);

function langTokens(text) {
  return (text || "")
    .replace(/ /g, " ")
    .toLowerCase()
    .replace(/[’]/g, "'")
    .split(/[^a-z']+/)
    .map((w) => w.replace(/^'+|'+$/g, ""))
    .filter(Boolean);
}

const wordFreq = {};
let mayorWordTotal = 0;
let mayorItemCount = 0;
for (const it of items) {
  if (!it.mayor_text) continue;
  mayorItemCount++;
  const toks = langTokens(it.mayor_text);
  mayorWordTotal += toks.length;
  for (const w of toks) {
    if (w.length < 3 || LANG_STOP.has(w)) continue;
    wordFreq[w] = (wordFreq[w] || 0) + 1;
  }
}
const wordcloud = Object.entries(wordFreq)
  .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  .slice(0, 110)
  .map(([word, count]) => ({ word, count }));

// Signature phrases: a *published* candidate list of recurring expressions,
// seeded from the top 2–4-word sequences in the mayor's words plus his known
// refrains. For each we count exact occurrences and — more tellingly — how many
// separate events he used it in, then keep only those he returns to across many
// events (so it's a habit, not one speech). Every count is exact; every example
// is a verbatim sentence from his own words. Ordered by event spread.
const PHRASE_CANDIDATES = [
  "across the five boroughs", "working people", "working-class", "a city where",
  "far too long", "at the heart of", "universal childcare", "public safety",
  "city government", "every single", "deliver for", "the world cup",
  "the wealthiest city", "affordability crisis", "quality of life",
  "mental health", "the greatest city in the world", "young people",
  "cost of living", "our children", "tax the rich", "rent freeze",
];
const PHRASE_MIN_EVENTS = 8; // must recur across at least this many events
const PHRASE_MIN_TOTAL = 10;

function normFlat(s) {
  return (s || "").replace(/ /g, " ").replace(/[’]/g, "'").replace(/\s+/g, " ");
}
function phraseRegex(p) {
  const pat = p
    .replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    .replace(/\s+/g, "\\s+");
  return new RegExp("(?<![\\w-])" + pat + "(?![\\w-])", "gi");
}
function firstSentence(raw, re, phrase) {
  const flat = normFlat(raw);
  const idx = flat.search(re);
  if (idx < 0) return null;
  let a = flat.lastIndexOf(".", idx);
  a = a < 0 ? 0 : a + 1;
  let b = flat.indexOf(".", idx + phrase.length);
  b = b < 0 ? Math.min(flat.length, idx + 160) : b + 1;
  let s = flat.slice(a, b).trim();
  if (s.length > 240) s = s.slice(0, 237).trimEnd() + "…";
  return s;
}

const signaturePhrases = [];
for (const phrase of PHRASE_CANDIDATES) {
  let total = 0;
  let events = 0;
  let example = null;
  let exampleUrl = null;
  let exampleTitle = null;
  for (const it of items) {
    if (!it.mayor_text) continue;
    const re = phraseRegex(phrase);
    const hits = normFlat(it.mayor_text).match(re);
    if (!hits || !hits.length) continue;
    total += hits.length;
    events++;
    if (!example) {
      example = firstSentence(it.mayor_text, phraseRegex(phrase), phrase);
      exampleUrl = it.url || it.link || null;
      exampleTitle = it.title || null;
    }
  }
  if (events >= PHRASE_MIN_EVENTS && total >= PHRASE_MIN_TOTAL) {
    signaturePhrases.push({ phrase, total, events, example, exampleUrl, exampleTitle });
  }
}
signaturePhrases.sort((a, b) => b.events - a.events || b.total - a.total);

console.log(
  `\nLanguage: ${mayorItemCount} items, ${mayorWordTotal.toLocaleString()} mayor words, ` +
    `${wordcloud.length} cloud words, ${signaturePhrases.length}/${PHRASE_CANDIDATES.length} phrases kept.`,
);

// ---- write -----------------------------------------------------------------
const out = {
  generated_at: new Date().toISOString(),
  corpus_generated_at: corpus.generated_at || null,
  method: "Keyword-lexicon tagging on item full text; whole-word, case-insensitive. " +
    "Monthly values are counts of items tagged with each topic (an item may carry several). " +
    "Digest quotes are verbatim Mayor statements selected by topic-term density — no paraphrase.",
  taxonomy: TAXONOMY.map(({ id, label, color, terms }) => ({ id, label, color, terms })),
  months: monthList,
  monthly,
  totals,
  itemTopics,
  digest,
  language: {
    method:
      "Computed only over the mayor's own words (his transcript turns and his " +
      "attributed quotes inside press releases), never reporters' questions or " +
      "other speakers. Word cloud: word frequency after removing a published " +
      "stop-word list. Signature phrases: exact counts of a published candidate " +
      "list of recurring expressions, kept only when he used them across at " +
      "least " + PHRASE_MIN_EVENTS + " separate events. Not a distinctiveness " +
      "(TF-IDF) measure — just how often he says them.",
    mayor_items: mayorItemCount,
    mayor_words: mayorWordTotal,
    phrase_candidates: PHRASE_CANDIDATES,
    phrase_min_events: PHRASE_MIN_EVENTS,
  },
  wordcloud,
  signaturePhrases,
};

writeFileSync("data/topics.json", JSON.stringify(out));
const kb = (Buffer.byteLength(JSON.stringify(out)) / 1024).toFixed(0);
console.log(`Wrote data/topics.json — ${items.length} items, ${monthList.length} months, ${kb} KB.`);
console.log("Totals by topic:");
Object.entries(totals)
  .sort((a, b) => b[1] - a[1])
  .forEach(([id, n]) => console.log(`  ${id.padEnd(14)} ${n}`));
