"use strict";
// Spusti bota proti falesnemu Discordu, lux-api a SMTP (vse na 127.0.0.1, docasny adresar).

const fs = require("fs");
const os = require("os");
const path = require("path");
const { FakeDiscord, FakeLuxApi, FakeSmtp, waitFor, snowflake } = require("./fakes");
const { load, readSecret } = require("../src/config");
const { Rest } = require("../src/rest");
const { Gateway } = require("../src/gateway");
const { Knowledge } = require("../src/knowledge");
const { State } = require("../src/state");
const { Assistant } = require("../src/assistant");
const { Mailer } = require("../src/mailer");
const { Bot } = require("../src/bot");
const { INTENTS } = require("../src/main");

const KEY = "lux-" + "k".repeat(40);

const PASSAGES = [
  { title: "LuxOS Apps › Store", url: "https://luxos.lux-ai.cz/docs/luxos/apps.html", text: "Install apps from the Store app. Open Store, search and click Install." },
  { title: "Care and updates › Update channel", url: "https://luxos.lux-ai.cz/docs/luxos/care-updates.html", text: "Run lux update or open Software Update to update the system." },
  { title: "Printing", url: "https://luxos.lux-ai.cz/docs/luxos/printing-scanning.html", text: "Printers are added in Printers and Scanners." }
];

let users = 0;
function user(name) {
  users += 1;
  return { id: snowflake(), username: name || `user${users}`, global_name: name || `User ${users}` };
}

async function startBot({ community = true, limits = {}, mail = {}, supportType } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "luxos-discord-test-"));
  const discord = await new FakeDiscord({ community }).start();
  const tagNeeds = { id: snowflake(), name: "Needs human", moderated: true };
  const category = discord.addChannel({ name: "SUPPORT", type: 4 });
  const support = discord.addChannel({
    name: "support", type: supportType ?? (community ? 15 : 0), parent_id: category.id,
    available_tags: [{ id: snowflake(), name: "Apps", moderated: false }, tagNeeds]
  });
  const general = discord.addChannel({ name: "general", type: 0 });
  const offTopic = discord.addChannel({ name: "off-topic", type: 0 });
  const announcements = discord.addChannel({ name: "announcements", type: community ? 5 : 0 });
  const luxapi = await new FakeLuxApi(KEY).start();
  const smtp = await new FakeSmtp().start();

  fs.writeFileSync(path.join(dir, "token"), `${discord.token}\n`, { mode: 0o600 });
  fs.writeFileSync(path.join(dir, "luxai-key"), `${KEY}\n`, { mode: 0o600 });
  const config = load();
  config.discordApi = discord.api;
  config.guildId = "";
  config.luxai.url = luxapi.url;
  Object.assign(config.mail, { host: "127.0.0.1", port: smtp.port, perHour: 6, perDay: 30, ...mail });
  Object.assign(config.limits, { userPer10Min: 50, userPerDay: 100, dailyCap: 1000, ...limits });
  const token = readSecret(path.join(dir, "token"), "token");
  const key = readSecret(path.join(dir, "luxai-key"), "key");

  const state = new State(path.join(dir, "state.json"));
  const rest = new Rest({ api: config.discordApi, token });
  const lines = [];
  const bot = new Bot({
    config, rest, state, knowledge: new Knowledge(PASSAGES),
    assistant: new Assistant({ ...config.luxai, key }),
    mailer: new Mailer(config.mail, state),
    log: (line) => lines.push(line)
  });
  const gateway = new Gateway({ rest, token, intents: INTENTS });
  gateway.on("dispatch", (t, d) => bot.onDispatch(t, d));
  gateway.connect();
  await waitFor(() => bot.guildId && bot.channels.size >= 4, 3000, "GUILD_CREATE");

  return {
    dir, discord, luxapi, smtp, state, rest, bot, gateway, lines, support, general, offTopic, announcements, tagNeeds,
    // pocka, az bot zpracuje vse, co prislo (kratka pauza na doruceni pres gateway)
    async settle(ms = 150) {
      await new Promise((r) => setTimeout(r, ms));
      await bot.idle();
    },
    async stop() {
      gateway.close();
      await bot.idle();
      state.flush();
      await Promise.all([discord.stop(), luxapi.stop(), smtp.stop()]);
      fs.rmSync(dir, { recursive: true, force: true });
    }
  };
}

const meta = (fields) => `META ${JSON.stringify({ confident: true, handoff: false, lang: "en", summary: "test", ...fields })}`;

module.exports = { startBot, user, meta, waitFor, KEY, PASSAGES };
