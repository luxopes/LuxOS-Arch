#!/usr/bin/env node
"use strict";
// Spusteni bota: nacte nastaveni a tajne udaje, index dokumentace, pripoji se ke Discord Gateway.

const path = require("path");
const { load, readSecret } = require("./config");
const { Rest } = require("./rest");
const { Gateway } = require("./gateway");
const { Knowledge } = require("./knowledge");
const { State } = require("./state");
const { Assistant } = require("./assistant");
const { Mailer } = require("./mailer");
const { Bot } = require("./bot");
const { Announcer } = require("./announce");

// GUILDS | GUILD_MESSAGES | DIRECT_MESSAGES | MESSAGE_CONTENT (privilegovany, zapina se v Developer Portalu)
const INTENTS = (1 << 0) | (1 << 9) | (1 << 12) | (1 << 15);
// Chyba nastaveni: systemd sluzbu znovu nespousti (RestartPreventExitStatus=78)
const EXIT_CONFIG = 78;

function log(line) {
  console.log(line);
}

function start() {
  let config;
  let token;
  let luxaiKey;
  try {
    config = load();
    token = readSecret(config.tokenFile, "Discord bot token");
    luxaiKey = readSecret(config.luxaiKeyFile, "LuxAI API key");
  } catch (error) {
    console.error(error.message);
    process.exit(EXIT_CONFIG);
  }

  let knowledge = null;
  try {
    knowledge = Knowledge.fromFile(config.knowledgeFile);
    log(`knowledge: ${knowledge.passages.length} passages`);
  } catch (error) {
    console.error(`knowledge index not loaded (${error.message}); answering without docs`);
  }

  const state = new State(path.join(config.stateDir, "state.json"));
  const rest = new Rest({ api: config.discordApi, token });
  const assistant = new Assistant({ ...config.luxai, key: luxaiKey });
  const mailer = new Mailer(config.mail, state);
  const bot = new Bot({ config, rest, assistant, knowledge, mailer, state, log });
  const announcer = new Announcer({ config, rest, state, bot, log });
  const gateway = new Gateway({ rest, token, intents: INTENTS });

  gateway.on("dispatch", (type, data) => bot.onDispatch(type, data));
  gateway.on("fatal", (error) => {
    console.error(`${error.message} - check the token and that Message Content Intent is enabled`);
    state.flush();
    process.exit(EXIT_CONFIG);
  });
  gateway.connect();
  announcer.start();

  const stop = () => {
    log("stopping");
    announcer.stop();
    gateway.close();
    try { state.flush(); } catch (error) { console.error(`state not saved: ${error.message}`); }
    process.exit(0);
  };
  process.on("SIGTERM", stop);
  process.on("SIGINT", stop);
}

if (require.main === module) start();

module.exports = { INTENTS };
