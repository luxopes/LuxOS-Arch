"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");
const { FakeDiscord } = require("./fakes");
const { Rest, routeKey } = require("../src/rest");
const { Gateway } = require("../src/gateway");
const { splitMessage, HUMAN_RE, SECRET_RE } = require("../src/bot");
const { parseReply } = require("../src/assistant");
const { detectLanguage } = require("../src/texts");
const { Knowledge, tokenize } = require("../src/knowledge");
const { readSecret, load } = require("../src/config");
const { redact } = require("../src/secrets");
const { Bot } = require("../src/bot");

test("REST: waits out a 429 and retries; route keys keep the major parameter", async (t) => {
  const discord = await new FakeDiscord().start();
  t.after(() => discord.stop());
  const channel = discord.addChannel({ name: "general", type: 0 });
  discord.failOnce.set(`POST /channels/${channel.id}/messages`, { status: 429, body: { retry_after: 0.2, global: false } });
  const rest = new Rest({ api: discord.api, token: discord.token });
  const started = Date.now();
  const message = await rest.post(`/channels/${channel.id}/messages`, { content: "hi" });
  assert.equal(message.content, "hi");
  assert.ok(Date.now() - started >= 200, "waited retry_after");
  assert.equal(discord.requests.filter((r) => r.method === "POST").length, 2);
  assert.equal(routeKey("PATCH", "/channels/123456789012/messages/987654321098"), "PATCH /channels/<123456789012>/messages/:id");
  await assert.rejects(new Rest({ api: discord.api, token: "wrong" }).get("/users/@me"), (e) => e.status === 401);
});

test("gateway: a rejected token is fatal (no reconnect loop)", async (t) => {
  const discord = await new FakeDiscord().start();
  t.after(() => discord.stop());
  const gateway = new Gateway({ rest: new Rest({ api: discord.api, token: discord.token }), token: "bad", intents: 1 });
  const fatal = new Promise((resolve) => gateway.on("fatal", resolve));
  gateway.connect();
  const error = await fatal;
  assert.match(error.message, /4004/);
  gateway.close();
});

test("splitMessage keeps messages under 2000 chars and code blocks closed", () => {
  const text = "Intro\n\n```\n" + "line of code\n".repeat(300) + "```\n\nEnd";
  const parts = splitMessage(text);
  assert.ok(parts.length >= 2);
  for (const part of parts) {
    assert.ok(part.length <= 2000);
    assert.equal((part.match(/```/g) || []).length % 2, 0, "balanced fences");
  }
  assert.deepEqual(splitMessage("short"), ["short"]);
});

test("parseReply reads and strips the META flag", () => {
  const r = parseReply('Answer text.\nMETA {"confident": false, "handoff": true, "lang": "cs", "summary": "s"}');
  assert.equal(r.text, "Answer text.");
  assert.deepEqual(r.meta, { confident: false, handoff: true, lang: "cs", summary: "s" });
  // bez platneho META = nejiste; kazdy radek META se odstrani, i useknuty
  const plain = parseReply("Just an answer");
  assert.equal(plain.meta.confident, false);
  assert.equal(plain.meta.handoff, false);
  const broken = parseReply("Text\nMETA {broken");
  assert.equal(broken.meta.confident, false);
  assert.equal(broken.text, "Text");
  const truncated = parseReply('Odpověď.\nMETA {"confident": true, "handoff": false, "lang": "cs", "summ');
  assert.equal(truncated.text, "Odpověď.");
  assert.equal(truncated.meta.confident, false);
  assert.equal(parseReply('A\nMETA {"confident": "yes"}').meta.confident, false, "only literal true counts");
  assert.equal(parseReply('A\nMETA {"lang": "english"}').meta.lang, "");
});

test("language detection, human requests and secrets", () => {
  assert.equal(detectLanguage("How do I install Steam?"), "en");
  assert.equal(detectLanguage("Jak nainstaluji Steam?"), "cs");
  assert.equal(detectLanguage("jak nastavit tiskarnu prosim"), "cs");
  assert.equal(detectLanguage("Wie installiere ich Steam unter LuxOS"), "other");
  assert.equal(detectLanguage("wifi"), "en");
  assert.equal(detectLanguage("printer question number 2"), "en");
  assert.equal(detectLanguage("¿Cómo instalo Steam?"), "other");
  assert.equal(detectLanguage("Como instalar Steam en LuxOS"), "other");
  assert.equal(detectLanguage("Где настройки?"), "other");
  for (const text of ["I want to talk to a human", "human", "Can I speak with a real person?", "chci mluvit s člověkem"]) assert.ok(HUMAN_RE.test(text), text);
  for (const text of ["how do I make text human readable", "the humanity", "personal folder"]) assert.ok(!HUMAN_RE.test(text), text);
  assert.ok(SECRET_RE.test(`key lux-${"x".repeat(40)}`));
  assert.ok(SECRET_RE.test("password: hunter22"));
  assert.ok(SECRET_RE.test("-----BEGIN OPENSSH PRIVATE KEY-----"));
  assert.ok(!SECRET_RE.test("I forgot my password, how do I reset it?"));
  const redacted = redact(`login fails, password: hunter2 and token=abcd1234efgh, key lux-${"k".repeat(40)}\n-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----\nrest`);
  assert.doesNotMatch(redacted, /hunter2|abcd1234|kkkkkk|AAAA/);
  assert.match(redacted, /^login fails, \[redacted\] and \[redacted\] key \[redacted\]\n\[redacted\]\nrest$/);
});

test("knowledge: BM25 ranks the relevant passage first, diacritics and plurals normalised", () => {
  const k = new Knowledge([
    { title: "Printing", url: "u1", text: "Add printers in Printers and Scanners." },
    { title: "Wi-Fi", url: "u2", text: "Join a wireless network from the menu bar." },
    { title: "Store", url: "u3", text: "Install applications from the Store." }
  ]);
  assert.equal(k.search("my printer doesn't print")[0].url, "u1");
  assert.equal(k.search("installing applications")[0].url, "u3");
  assert.deepEqual(tokenize("Tiskárna nefunguje"), ["tiskarna", "nefunguje"]);
  assert.deepEqual(k.search("zzzz"), []);
});

test("knowledge index from the repository", () => {
  const out = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "luxos-discord-idx-")), "knowledge.json");
  execFileSync(process.execPath, [path.join(__dirname, "..", "scripts", "build-index.js"), "--out", out], { stdio: "pipe" });
  const k = Knowledge.fromFile(out);
  assert.ok(k.passages.length > 300);
  assert.ok(k.passages.every((p) => p.url.startsWith("https://luxos.lux-ai.cz/") && p.text.length <= 1400 && p.title));
  assert.match(k.search("switch to the staging update channel")[0].url, /care-updates\.html$/);
  assert.ok(k.passages.some((p) => p.url === "https://luxos.lux-ai.cz/changes/"), "changelog included");
  assert.ok(k.passages.some((p) => /\/docs\/luxos\/faq\.html$/.test(p.url)), "site FAQ included");

  // prah shody (vychozi MIN_MATCH_SCORE / MIN_MATCH_COVERAGE) na skutecnem indexu: klicova slova
  // od modelu; tema z dokumentace projde, cizi tema ne
  const bot = new Bot({ config: load(), rest: null, assistant: null, knowledge: k, mailer: null, state: null, log: () => {} });
  for (const terms of ["install apps store", "printer not printing", "wifi password QR code", "switch staging update channel",
    "secure boot MOK key", "LuxAI credits limit", "Steam games", "bluetooth headphones", "nvidia driver", "dual boot windows", "change wallpaper",
    // keywords in the style of KEYWORDS_PROMPT for "how is LuxOS protected against damage during an update?" (live miss 2026-11-20)
    "update snapshot rollback broken system", "update protection snapshot rollback"]) {
    assert.ok(bot.matchQuality(terms), `docs cover: ${terms}`);
  }
  for (const terms of ["goulash recipe dumplings", "capital of France", "football match result", "bitcoin price", "pizza Prague", "poem about cats", "Roman empire history essay"]) {
    assert.equal(bot.matchQuality(terms), null, `not in the docs: ${terms}`);
  }
  fs.rmSync(path.dirname(out), { recursive: true, force: true });
});

test("secrets are read from files and never accepted empty", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "luxos-discord-sec-"));
  fs.writeFileSync(path.join(dir, "ok"), "abc.def\n");
  fs.writeFileSync(path.join(dir, "empty"), "\n");
  assert.equal(readSecret(path.join(dir, "ok"), "t"), "abc.def");
  assert.throws(() => readSecret(path.join(dir, "empty"), "t"), /empty/);
  assert.throws(() => readSecret(path.join(dir, "missing"), "t"), /cannot read t/);
  fs.rmSync(dir, { recursive: true, force: true });
});
