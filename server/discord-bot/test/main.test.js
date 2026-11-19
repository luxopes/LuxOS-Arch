"use strict";
// Cely proces src/main.js tak, jak ho spousti systemd (LoadCredential -> $CREDENTIALS_DIRECTORY,
// $STATE_DIRECTORY), proti falesnym sluzbam: odpoved, SIGTERM ulozi stav, spatny token = kod 78.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawn, execFileSync } = require("child_process");
const { FakeDiscord, FakeLuxApi, FakeSmtp, waitFor, snowflake } = require("./fakes");
const { KEY } = require("./harness");

const MAIN = path.join(__dirname, "..", "src", "main.js");

function startMain(env) {
  const child = spawn(process.execPath, [MAIN], { env: { PATH: process.env.PATH, ...env }, stdio: ["ignore", "pipe", "pipe"] });
  child.output = "";
  child.stdout.on("data", (d) => { child.output += d; });
  child.stderr.on("data", (d) => { child.output += d; });
  child.exited = new Promise((resolve) => child.on("exit", (code) => resolve(code)));
  return child;
}

test("main.js: answers with the real index, saves state on SIGTERM, stays small", async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "luxos-discord-main-"));
  const discord = await new FakeDiscord({ community: true }).start();
  const luxapi = await new FakeLuxApi(KEY).start();
  const smtp = await new FakeSmtp().start();
  t.after(async () => { await Promise.all([discord.stop(), luxapi.stop(), smtp.stop()]); fs.rmSync(dir, { recursive: true, force: true }); });
  const support = discord.addChannel({ name: "support", type: 15, available_tags: [] });
  discord.addChannel({ name: "announcements", type: 5 });

  const creds = path.join(dir, "creds");
  fs.mkdirSync(creds, { mode: 0o700 });
  fs.writeFileSync(path.join(creds, "discord-token"), discord.token, { mode: 0o600 });
  fs.writeFileSync(path.join(creds, "luxai-key"), KEY, { mode: 0o600 });
  const knowledge = path.join(dir, "knowledge.json");
  execFileSync(process.execPath, [path.join(__dirname, "..", "scripts", "build-index.js"), "--out", knowledge], { stdio: "pipe" });

  const child = startMain({
    CREDENTIALS_DIRECTORY: creds, STATE_DIRECTORY: path.join(dir, "state"), KNOWLEDGE_FILE: knowledge,
    DISCORD_API: discord.api, LUXAI_URL: luxapi.url, SMTP_PORT: String(smtp.port), ANNOUNCE_INTERVAL_MIN: "0",
    NODE_OPTIONS: "--max-old-space-size=64 --max-semi-space-size=2" // jako v luxos-discord-bot.service
  });
  t.after(() => child.kill("SIGKILL"));
  await waitFor(() => /ready as LuxOS Support/.test(child.output) && discord.sockets.size, 5000, "ready");
  assert.match(child.output, /knowledge: \d+ passages/);

  const user = { id: snowflake(), username: "u" };
  luxapi.reply = () => 'Use `lux config channel staging`, see https://luxos.lux-ai.cz/docs/luxos/care-updates.html\nMETA {"confident": true, "handoff": false, "lang": "en"}';
  luxapi.keywords = () => "switch staging update channel";
  const thread = discord.forumPost(support.id, user, "Staging", "How do I switch to the staging update channel?");
  await waitFor(() => discord.posted(thread.id).length === 1, 5000, "answer");
  assert.match(luxapi.requests[0].messages[0].content, /care-updates\.html/, "real docs in the prompt");
  assert.doesNotMatch(child.output, /staging update channel/, "question text is not logged");

  const rssKb = Number(/VmRSS:\s+(\d+)/.exec(fs.readFileSync(`/proc/${child.pid}/status`, "utf8"))[1]);
  assert.ok(rssKb < 100 * 1024, `RSS ${rssKb} kB fits MemoryMax=128M`);

  child.kill("SIGTERM");
  assert.equal(await child.exited, 0);
  const state = JSON.parse(fs.readFileSync(path.join(dir, "state", "state.json"), "utf8"));
  assert.equal(state.threads[thread.id].replies, 1);
  assert.equal(fs.statSync(path.join(dir, "state", "state.json")).mode & 0o777, 0o600);
});

test("main.js: missing secret or rejected token exits with 78 (no restart loop)", async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "luxos-discord-main-"));
  const discord = await new FakeDiscord().start();
  t.after(async () => { await discord.stop(); fs.rmSync(dir, { recursive: true, force: true }); });

  const missing = startMain({ CREDENTIALS_DIRECTORY: dir, STATE_DIRECTORY: dir });
  assert.equal(await missing.exited, 78);
  assert.match(missing.output, /cannot read Discord bot token/);

  fs.writeFileSync(path.join(dir, "discord-token"), "wrong-token");
  fs.writeFileSync(path.join(dir, "luxai-key"), KEY);
  const rejected = startMain({ CREDENTIALS_DIRECTORY: dir, STATE_DIRECTORY: dir, DISCORD_API: discord.api, KNOWLEDGE_FILE: path.join(dir, "none.json") });
  assert.equal(await rejected.exited, 78);
  assert.doesNotMatch(rejected.output, /wrong-token/, "token never printed");
});
