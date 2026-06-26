/**
 * Offline embedding builder for plain-language (semantic) search.
 *
 * Reads data/corpus.json, splits each item's text into passages, embeds every
 * passage with all-MiniLM-L6-v2 (the same model the browser loads via
 * transformers.js, so the vectors are directly comparable), and writes
 * data/embeddings.json.
 *
 * Vectors are L2-normalised then int8-quantised (value * 127) and packed into a
 * base64 blob to keep the file small. The browser dequantises, re-normalises,
 * and ranks passages by cosine similarity (a dot product on unit vectors).
 *
 * Run: node build_embeddings.mjs   (needs `npm i @huggingface/transformers`)
 * No API, no key, no cost — the model downloads once from the Hugging Face CDN.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { pipeline } from "@huggingface/transformers";

const MODEL = "Xenova/gte-small"; // 384-dim, stronger retrieval than MiniLM, no query prefix
const DIMS = 384;
const TARGET = 900; // aim for ~900-char passages
const MAX = 1600; // hard cap before forcing a split
const MIN = 200; // merge passages shorter than this into the next

// Find paragraph spans as [start, end) offsets into the body. Splitting on
// blank lines this way (rather than String.split) keeps the offsets exact even
// when separators are 3+ newlines, so the browser shows the right passage.
function paragraphSpans(body) {
  const spans = [];
  const re = /\n{2,}/g;
  let last = 0;
  let m;
  while ((m = re.exec(body))) {
    if (m.index > last) spans.push([last, m.index]);
    last = m.index + m[0].length;
  }
  if (body.length > last) spans.push([last, body.length]);
  return spans.filter(([s, e]) => body.slice(s, e).trim());
}

// Split a single over-long paragraph on sentence boundaries, returning exact
// [start, end) spans into the body.
function sentenceSpans(body, pStart, pEnd) {
  const text = body.slice(pStart, pEnd);
  const re = /[^.!?]+[.!?]+|\S[^.!?]*$/g;
  const out = [];
  let segStart = pStart;
  let segEnd = pStart;
  let m;
  while ((m = re.exec(text))) {
    const sStart = pStart + m.index;
    const sEnd = sStart + m[0].length;
    if (segEnd - segStart >= TARGET && segEnd > segStart) {
      out.push([segStart, segEnd]);
      segStart = sStart;
    }
    segEnd = sEnd;
  }
  if (segEnd > segStart) out.push([segStart, segEnd]);
  return out;
}

// Split one item's body into passages: paragraph-first, merging until ~TARGET
// chars and hard-splitting any runaway block. Returns {start, end, text} with
// exact char offsets into the original body.
function chunk(body) {
  const out = [];
  let bufStart = -1;
  let bufEnd = -1;

  const flush = () => {
    if (bufStart < 0) return;
    const text = body.slice(bufStart, bufEnd).trim();
    if (text) out.push({ start: bufStart, end: bufEnd, text });
    bufStart = bufEnd = -1;
  };

  for (const [pStart, pEnd] of paragraphSpans(body)) {
    if (pEnd - pStart > MAX) {
      flush();
      for (const [sStart, sEnd] of sentenceSpans(body, pStart, pEnd)) {
        out.push({ start: sStart, end: sEnd, text: body.slice(sStart, sEnd).trim() });
      }
      continue;
    }
    if (bufStart < 0) bufStart = pStart;
    bufEnd = pEnd;
    if (bufEnd - bufStart >= TARGET) flush();
  }
  flush();

  // Merge any passage shorter than MIN into the previous one.
  const merged = [];
  for (const p of out) {
    const prev = merged[merged.length - 1];
    if (prev && p.text.length < MIN) {
      prev.end = p.end;
      prev.text = body.slice(prev.start, prev.end).trim();
    } else {
      merged.push({ ...p });
    }
  }
  return merged;
}

const corpus = JSON.parse(readFileSync("data/corpus.json", "utf8"));
const items = corpus.items;

console.log(`Loading ${MODEL} …`);
const extractor = await pipeline("feature-extraction", MODEL);

const meta = []; // {i: itemIndex, s: startChar, e: endChar}
const texts = [];
items.forEach((it, i) => {
  const body = it.text || "";
  if (!body.trim()) return;
  // Council hearing transcripts are enormous (30k–90k words each); embedding
  // them would balloon the client-side vector download for little gain — you
  // keyword-search a hearing for a topic, not semantically. They stay fully
  // keyword-searchable and topic-tagged, just out of the semantic index.
  if (it.type === "hearing") return;
  // NYPD crime-statistics press releases are statistical write-ups, not spoken
  // transcripts — they're keyword/stat lookups, not "ask in plain language"
  // material. Keep them out of the semantic index (still keyword-searchable).
  if (it.type === "crime_briefing") return;
  for (const c of chunk(body)) {
    meta.push({ i, s: c.start, e: c.end });
    texts.push(c.text);
  }
});

console.log(`Embedding ${texts.length} passages from ${items.length} items …`);
const quant = new Int8Array(texts.length * DIMS);
// Sentence embeddings share a strong common direction (anisotropy) that
// compresses all cosine scores into a narrow band and drowns out the topical
// signal. We record the mean of every passage vector here; the browser
// subtracts it from both passages and the query before scoring, which restores
// discrimination. (Validated: without it, an off-topic civil-rights speech
// outranked passages literally about riding buses for a "free buses" query.)
const mean = new Float64Array(DIMS);
const BATCH = 32;
for (let b = 0; b < texts.length; b += BATCH) {
  const batch = texts.slice(b, b + BATCH);
  const res = await extractor(batch, { pooling: "mean", normalize: true });
  const data = res.data; // Float32Array, batch.length * DIMS
  for (let k = 0; k < batch.length; k++) {
    const base = (b + k) * DIMS;
    for (let d = 0; d < DIMS; d++) {
      const f = data[k * DIMS + d];
      mean[d] += f;
      let v = Math.round(f * 127);
      if (v > 127) v = 127;
      if (v < -127) v = -127;
      quant[base + d] = v;
    }
  }
  if (b % (BATCH * 10) === 0) process.stdout.write(`  ${b}/${texts.length}\r`);
}
for (let d = 0; d < DIMS; d++) mean[d] /= texts.length;

const out = {
  model: MODEL,
  dims: DIMS,
  count: texts.length,
  quant: "int8",
  generated_at: new Date().toISOString(),
  corpus_generated_at: corpus.generated_at || null,
  mean: Array.from(mean, (x) => +x.toFixed(6)),
  chunks: meta,
  vectors: Buffer.from(quant.buffer).toString("base64"),
};

writeFileSync("data/embeddings.json", JSON.stringify(out));
const mb = (Buffer.byteLength(JSON.stringify(out)) / 1e6).toFixed(2);
console.log(`\nWrote data/embeddings.json — ${texts.length} passages, ${mb} MB.`);
