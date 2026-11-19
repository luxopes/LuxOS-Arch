"use strict";
// Vyhledavani v dokumentaci LuxOS: BM25 nad useky z knowledge.json (vytvari scripts/build-index.js
// pri nasazeni). Zadna vektorova databaze - na par set useku staci klicova slova.

const fs = require("fs");

const STOPWORDS = new Set((
  "a an and are as at be been but by can could do does did for from has have how i if in into is it its " +
  "me my no not of on or our so that the their them then there these they this to too us was we were what " +
  "when where which who why will with would you your yours please hi hello thanks thank help need want " +
  "get got use using luxos " +
  // cestina (bez diakritiky, normalizuje se)
  "a aby ale ani asi az bez by byl byla bylo byt co do i jak jako je jeho jej jen jsem jsi jsou k kde " +
  "kdyz ktera ktere ktery mam me mi mit mne mozna muj na nad ne nebo neni nez o od po pod pro proc se si " +
  "s ta tak take tam te tedy ten to toho tu ty u uz v ve vsak z za ze zda dobry den diky dekuji prosim"
).split(/\s+/));

function normalize(text) {
  return String(text).toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
}

function tokenize(text) {
  const out = [];
  for (const token of normalize(text).split(/[^a-z0-9]+/)) {
    if (token.length < 2 || token.length > 40 || STOPWORDS.has(token)) continue;
    out.push(stem(token));
  }
  return out;
}

// Velmi hruby anglicky "stemmer": jen nejcastejsi koncovky, at "printers" najde "printer"
function stem(token) {
  if (token.length > 5 && token.endsWith("ing")) return token.slice(0, -3);
  if (token.length > 4 && token.endsWith("ies")) return token.slice(0, -3) + "y";
  if (token.length > 4 && token.endsWith("es") && /(ss|sh|ch|x)es$/.test(token)) return token.slice(0, -2);
  if (token.length > 3 && token.endsWith("s") && !token.endsWith("ss")) return token.slice(0, -1);
  if (token.length > 4 && token.endsWith("ed")) return token.slice(0, -2);
  return token;
}

class Knowledge {
  constructor(passages, { k1 = 1.4, b = 0.75 } = {}) {
    this.passages = passages;
    this.k1 = k1;
    this.b = b;
    this.postings = new Map(); // term -> Uint32Array [index, tf, index, tf, ...] (malo objektu = malo pameti)
    this.lengths = [];
    let total = 0;
    passages.forEach((passage, index) => {
      // nadpis a klicova slova vazi vic nez text
      const tokens = [...tokenize(passage.title), ...tokenize(passage.title), ...tokenize(passage.keywords || ""), ...tokenize(passage.text)];
      this.lengths.push(tokens.length);
      total += tokens.length;
      const counts = new Map();
      for (const token of tokens) counts.set(token, (counts.get(token) || 0) + 1);
      for (const [term, tf] of counts) {
        if (!this.postings.has(term)) this.postings.set(term, []);
        this.postings.get(term).push(index, tf);
      }
    });
    for (const [term, list] of this.postings) this.postings.set(term, Uint32Array.from(list));
    this.avgLength = passages.length ? total / passages.length : 1;
  }

  static fromFile(file) {
    const data = JSON.parse(fs.readFileSync(file, "utf8"));
    if (!data || data.version !== 1 || !Array.isArray(data.passages)) throw new Error(`${file} is not a knowledge index`);
    return new Knowledge(data.passages);
  }

  search(query, limit = 5) {
    const terms = [...new Set(tokenize(query))];
    const scores = new Map();
    const n = this.passages.length;
    for (const term of terms) {
      const postings = this.postings.get(term);
      if (!postings) continue;
      const df = postings.length / 2;
      const idf = Math.log(1 + (n - df + 0.5) / (df + 0.5));
      for (let i = 0; i < postings.length; i += 2) {
        const index = postings[i];
        const tf = postings[i + 1];
        const norm = tf * (this.k1 + 1) / (tf + this.k1 * (1 - this.b + this.b * this.lengths[index] / this.avgLength));
        scores.set(index, (scores.get(index) || 0) + idf * norm);
      }
    }
    // nejvys dva useky z jedne stranky, at se do promptu vejde vic zdroju
    const perUrl = new Map();
    const results = [];
    for (const [index, score] of [...scores].sort((a, b) => b[1] - a[1])) {
      const passage = this.passages[index];
      const count = perUrl.get(passage.url) || 0;
      if (count >= 2) continue;
      perUrl.set(passage.url, count + 1);
      results.push({ ...passage, score });
      if (results.length >= limit) break;
    }
    return results;
  }
}

module.exports = { Knowledge, tokenize, normalize };
