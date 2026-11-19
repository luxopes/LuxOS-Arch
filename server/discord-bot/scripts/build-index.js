#!/usr/bin/env node
"use strict";
// Vytvori knowledge.json pro bota z dokumentace v repozitari (spousti deploy.sh na pocitaci spravce):
//   - packages/apps/luxos-docs/docs/**/*.md  -> https://luxos.lux-ai.cz/docs/<cesta>.html
//   - site/content/en/luxos/*.md (FAQ, LuxAI, hardware ...) -> /docs/luxos/<jmeno>.html
//   - site/landing/*.en.html, site/home.en.html -> adresy ze site/landing/pages.json
//   - site/content/en/changes/: posledni vydani + "Coming soon" -> /changes/
//
//   node scripts/build-index.js [--repo DIR] [--out FILE]

const fs = require("fs");
const path = require("path");

const SITE = "https://luxos.lux-ai.cz";
const MAX_PASSAGE = 1400;

function args() {
  const out = { repo: path.resolve(__dirname, "..", "..", ".."), out: path.resolve(__dirname, "..", "knowledge.json") };
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--repo") out.repo = path.resolve(argv[++i]);
    else if (argv[i] === "--out") out.out = path.resolve(argv[++i]);
    else { console.error(`unknown argument ${argv[i]}`); process.exit(2); }
  }
  return out;
}

function walk(dir) {
  const files = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...walk(full));
    else if (entry.name.endsWith(".md")) files.push(full);
  }
  return files.sort();
}

// Dlouhy text rozdeli na kusy po odstavcich (nejvys MAX_PASSAGE znaku)
function chunks(text) {
  const out = [];
  let current = "";
  for (const paragraph of text.split(/\n{2,}/)) {
    const piece = paragraph.length > MAX_PASSAGE ? paragraph.slice(0, MAX_PASSAGE) : paragraph;
    if (current && current.length + piece.length + 2 > MAX_PASSAGE) { out.push(current); current = ""; }
    current = current ? `${current}\n\n${piece}` : piece;
  }
  if (current.trim()) out.push(current);
  return out;
}

// Markdown -> useky podle nadpisu ## a ### (nadpisy v blocich kodu se nepocitaji)
function markdownSections(markdown) {
  const lines = markdown.replace(/\r/g, "").split("\n");
  let docTitle = "";
  const sections = [];
  let current = { heading: "", lines: [] };
  let fence = false;
  for (const line of lines) {
    if (/^(```|~~~)/.test(line)) fence = !fence;
    const h1 = !fence && /^# (.+)/.exec(line);
    const h23 = !fence && /^#{2,3} (.+)/.exec(line);
    if (h1 && !docTitle) { docTitle = h1[1].trim(); continue; }
    if (h23) {
      sections.push(current);
      current = { heading: h23[1].trim(), lines: [] };
      continue;
    }
    current.lines.push(line);
  }
  sections.push(current);
  return { docTitle, sections: sections.map((s) => ({ heading: s.heading, text: s.lines.join("\n").trim() })).filter((s) => s.text) };
}

function addMarkdown(passages, file, url, extra = {}) {
  const { docTitle, sections } = markdownSections(fs.readFileSync(file, "utf8"));
  const title = extra.title || docTitle || path.basename(file, ".md");
  sections.forEach((section, i) => {
    for (const [j, text] of chunks(section.text).entries()) {
      passages.push({
        title: section.heading ? `${title} › ${section.heading}` : title,
        url,
        text,
        ...(i === 0 && j === 0 && extra.keywords ? { keywords: extra.keywords } : {})
      });
    }
  });
}

function htmlToText(html, fill) {
  return html
    .replace(/<(script|style|svg|noscript)[\s\S]*?<\/\1>/gi, " ")
    .replace(/\{([A-Z_]+)\}/g, (_, key) => fill[key] || "")
    .replace(/<\/(p|li|tr|h[1-6]|div|section)>/gi, "\n\n")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&quot;/g, "\"").replace(/&#39;|&rsquo;/g, "'").replace(/&ndash;/g, "–").replace(/&mdash;/g, "—")
    .replace(/[ \t]+/g, " ")
    .replace(/\n[ \t]+/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

// HTML stranka -> useky podle <h2 id="..."> (odkaz s kotvou)
function addHtml(passages, file, url, title, fill) {
  const html = fs.readFileSync(file, "utf8");
  const parts = html.split(/(?=<h2[\s>])/i);
  for (const part of parts) {
    const heading = /<h2(?:\s+id="([^"]+)")?[^>]*>([\s\S]*?)<\/h2>/i.exec(part);
    const name = heading ? htmlToText(heading[2], fill) : "";
    const body = htmlToText(heading ? part.slice(heading.index + heading[0].length) : part, fill);
    if (body.length < 40) continue;
    for (const text of chunks(body)) {
      passages.push({ title: name ? `${title} › ${name}` : title, url: heading && heading[1] ? `${url}#${heading[1]}` : url, text });
    }
  }
}

function versionKey(name) {
  const m = /^(\d+)\.(\d+)\.(\d+)-(\d{4}-\d{2}-\d{2})/.exec(name);
  return m ? [Number(m[1]), Number(m[2]), Number(m[3]), m[4]] : null;
}

function compareKeys(a, b) {
  for (let i = 0; i < 4; i++) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1;
  return 0;
}

// Seznam zmen: kazda polozka (radek "- **...**") je jeden usek
function addChanges(passages, file, heading) {
  const text = fs.readFileSync(file, "utf8");
  let section = "";
  let intro = "";
  for (const line of text.split("\n")) {
    if (/^## /.test(line)) { intro = line.replace(/^## /, ""); continue; }
    if (/^### /.test(line)) { section = line.replace(/^### /, ""); continue; }
    if (!/^- /.test(line)) continue;
    passages.push({
      title: `${heading}${intro ? ` (${intro})` : ""}${section ? ` › ${section}` : ""}`,
      url: `${SITE}/changes/`,
      text: line.slice(2, 2 + MAX_PASSAGE)
    });
  }
}

function readKv(file) {
  const out = {};
  for (const line of fs.readFileSync(file, "utf8").split("\n")) {
    const m = /^([A-Z_]+)=(.*)$/.exec(line);
    if (m) out[m[1]] = m[2];
  }
  return out;
}

function main() {
  const opt = args();
  const repo = opt.repo;
  const passages = [];

  const docsDir = path.join(repo, "packages", "apps", "luxos-docs", "docs");
  const meta = new Map();
  try {
    const index = JSON.parse(fs.readFileSync(path.join(docsDir, "index.json"), "utf8"));
    for (const collection of index.collections || []) {
      for (const file of collection.files || []) meta.set(file.path, file);
    }
  } catch (error) {
    console.error(`warning: docs index.json not read (${error.message})`);
  }
  for (const file of walk(docsDir)) {
    const rel = path.relative(docsDir, file).split(path.sep).join("/");
    const info = meta.get(rel) || {};
    addMarkdown(passages, file, `${SITE}/docs/${rel.slice(0, -3)}.html`, {
      title: info.title,
      keywords: [info.summary, ...(info.keywords || [])].filter(Boolean).join(" ")
    });
  }

  const siteDocs = path.join(repo, "site", "content", "en", "luxos");
  if (fs.existsSync(siteDocs)) {
    for (const file of walk(siteDocs)) {
      addMarkdown(passages, file, `${SITE}/docs/luxos/${path.basename(file, ".md")}.html`);
    }
  }

  const version = readKv(path.join(repo, "packages", "luxos-branding", "files", "version"));
  let iso = {};
  try { iso = JSON.parse(fs.readFileSync(path.join(repo, "site", "iso.json"), "utf8")); } catch { /* bez ISO udaju */ }
  const fill = {
    VERSION: version.VERSION || "", CODENAME: version.CODENAME || "",
    ISO_VERSION: iso.version || "", ISO_SIZE: iso.size ? `${(iso.size / 1e9).toFixed(1)} GB` : "", ISO_DATE: iso.date || ""
  };
  const landing = path.join(repo, "site", "landing");
  try {
    const pages = JSON.parse(fs.readFileSync(path.join(landing, "pages.json"), "utf8")).pages || {};
    for (const [key, page] of Object.entries(pages)) {
      const file = path.join(landing, `${key}.en.html`);
      if (page.en && fs.existsSync(file)) {
        addHtml(passages, file, SITE + page.en.path, (page.en.title || key).replace(/\{([A-Z_]+)\}/g, (_, k) => fill[k] || ""), fill);
      }
    }
  } catch (error) {
    console.error(`warning: landing pages not read (${error.message})`);
  }
  const home = path.join(repo, "site", "home.en.html");
  if (fs.existsSync(home)) addHtml(passages, home, `${SITE}/`, "LuxOS website", fill);

  const changes = path.join(repo, "site", "content", "en", "changes");
  if (fs.existsSync(changes)) {
    const releases = fs.readdirSync(changes).filter((name) => versionKey(name)).sort((a, b) => compareKeys(versionKey(a), versionKey(b)));
    if (releases.length) addChanges(passages, path.join(changes, releases[releases.length - 1]), "Changelog, latest release");
    if (fs.existsSync(path.join(changes, "unreleased.md"))) addChanges(passages, path.join(changes, "unreleased.md"), "Changelog, coming soon (staging)");
  }

  const out = {
    version: 1,
    built: new Date().toISOString(),
    luxos: { version: version.VERSION || "", codename: version.CODENAME || "" },
    passages
  };
  fs.writeFileSync(opt.out, JSON.stringify(out));
  const size = fs.statSync(opt.out).size;
  console.log(`knowledge index: ${passages.length} passages, ${(size / 1024).toFixed(0)} kB -> ${opt.out}`);
  if (passages.length < 50) { console.error("too few passages - wrong --repo?"); process.exit(1); }
}

main();
