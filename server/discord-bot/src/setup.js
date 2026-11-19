#!/usr/bin/env node
"use strict";
// Jednorazove nastaveni Discord serveru LuxOS botem: role, kategorie, kanaly, stitky fora,
// prikaz /human, uvitaci zpravy, vyber role (Onboarding, jinak tlacitka) a trvala pozvanka.
// Pravidla serveru (Server Settings → Access → Server rules) API nema - setup vypise, co vlozit.
// Idempotentni: co uz odpovida, nemeni; druhe spusteni neudela zadnou zmenu.
//
//   node src/setup.js [--guild ID] [--enable-community | --no-community] [--cleanup-defaults]
//
// Token cte ze stejneho souboru jako bot (DISCORD_TOKEN_FILE, vychozi /etc/luxos-discord/token).
// Bot musi byt na serveru s opravnenim Administrator (jen pro setup, pak se opravneni snizi - README).

const { load, readSecret } = require("./config");
const { Rest } = require("./rest");

const P = {
  CREATE_INSTANT_INVITE: 1n << 0n, KICK_MEMBERS: 1n << 1n, ADD_REACTIONS: 1n << 6n,
  VIEW_CHANNEL: 1n << 10n, SEND_MESSAGES: 1n << 11n, MANAGE_MESSAGES: 1n << 13n, EMBED_LINKS: 1n << 14n,
  ATTACH_FILES: 1n << 15n, READ_MESSAGE_HISTORY: 1n << 16n, MENTION_EVERYONE: 1n << 17n,
  MANAGE_THREADS: 1n << 34n, CREATE_PUBLIC_THREADS: 1n << 35n, CREATE_PRIVATE_THREADS: 1n << 36n,
  SEND_MESSAGES_IN_THREADS: 1n << 38n, MODERATE_MEMBERS: 1n << 40n
};
const perms = (...names) => names.reduce((sum, name) => sum | P[name], 0n).toString();

// Opravneni bota po nastaveni (OAuth2 URL Generator); #support dostane navic Manage Threads a
// Create Public Threads prepisem kanalu jen pro bota
const BOT_PERMISSIONS = perms("VIEW_CHANNEL", "SEND_MESSAGES", "SEND_MESSAGES_IN_THREADS", "READ_MESSAGE_HISTORY");
const SITE = "https://luxos.lux-ai.cz";
const ISSUES = "https://github.com/luxopes/LuxOS-Arch/issues";
const CONTACT = "info@lux-ai.cz";

const ROLES = [
  { name: "Team", color: 0x3b82f6, hoist: true, mentionable: true,
    permissions: perms("KICK_MEMBERS", "MANAGE_MESSAGES", "MANAGE_THREADS", "MODERATE_MEMBERS", "MENTION_EVERYONE") },
  { name: "Tester", color: 0x22c55e, hoist: true, mentionable: false, permissions: "0" },
  { name: "Member", color: 0, hoist: false, mentionable: false, permissions: "0" }
];

const RULES = [
  "Be respectful. No harassment, hate speech or personal attacks.",
  "No spam and no self-promotion (ads, referral links, unrelated servers).",
  "No piracy, cracks, malware or links to them.",
  "Use English in the main channels so everyone can follow. In #support you can ask in your own language.",
  "Never post passwords, API keys, tokens or recovery codes.",
  "Support answers come from the LuxOS AI assistant based on the LuxOS documentation. Messages in #support and #bug-reports are sent to the AI model. For a human, ask the bot (or use /human) or mail info@lux-ai.cz."
];

const WELCOME = (ch) => `**Welcome to the LuxOS community!**
LuxOS is a fast Linux with a macOS-like desktop: <${SITE}>

**Rules**
${RULES.map((rule, i) => `${i + 1}. ${rule}`).join("\n")}

**Where to go**
- Questions and problems: open a post in ${ch.support} - the LuxOS AI assistant answers right away from the documentation (<${SITE}/docs/>), and the LuxOS team steps in when needed.
- Bugs: ${ch.bugs} or GitHub issues <${ISSUES}>
- Ideas: ${ch.ideas} · chat: ${ch.general} · screenshots: ${ch.desktop}
- Want to test new builds? Pick the Tester role (Channels & Roles at the top of the channel list) to see ${ch.testers}.
- Contact the team by e-mail: ${CONTACT}
- Privacy: the AI assistant receives the text of your question (and earlier messages in the same thread) through LuxAI to write an answer. Details: <${SITE}/privacy/>`;

const TESTERS = (ch) => `**Testers: the staging channel**
Staging is open to anyone who wants to test: it gets fixes and new features before a release. They may still break things, so use a computer with backups.
Switch to staging:
\`\`\`
lux config channel staging
lux update
\`\`\`
Back to stable (newer test packages stay until the release catches up):
\`\`\`
lux config channel stable
\`\`\`
Check the channel with \`lux config check\`. Report bugs in ${ch.bugs} with your LuxOS version (About This Computer); talk about the test builds here. Docs: <${SITE}/docs/luxos/care-updates.html>`;

const BUGS = (ch) => `**Reporting bugs**
Reports here are forwarded to the LuxOS team; the bot may ask for details first (it uses the LuxOS AI to check that a report is complete). You can also use GitHub issues: <${ISSUES}>
Please include: LuxOS version (About This Computer), what you did, what you expected and what happened, and screenshots or the exact error message. Don't post passwords or keys.
Not sure if it's a bug? Ask in ${ch.support} first.`;

const SUPPORT_TOPIC = "Ask anything about LuxOS: one question per post. The LuxOS AI assistant answers from the docs (your message is sent to the AI model); type /human or ask for a human to reach the LuxOS team.";
const SUPPORT_TAGS = [
  { name: "Installation", moderated: false },
  { name: "Hardware", moderated: false },
  { name: "Apps", moderated: false },
  { name: "LuxAI", moderated: false },
  { name: "Solved", moderated: false },
  { name: "Needs human", moderated: true }
];

// Vyber role: Onboarding (Community) nebo zalozni zprava s tlacitky v #welcome-and-rules.
// Bot smi prepinat jen tyto role (custom_id "role:<jmeno>"), nikdy Team.
const SELF_ROLES = [
  { role: "Tester", title: "I want to test new LuxOS builds (staging)", description: "Get the #testers channel and try fixes before a release" },
  { role: "Member", title: "I use LuxOS / I'm curious", description: "Chat, ask for help and follow the news" }
];
const ONBOARDING_PROMPT = "What brings you here?";
const ROLE_MESSAGE = `**Choose your role**
${SELF_ROLES.map((r) => `- **${r.role}**: ${r.title}`).join("\n")}
Click a button to add or remove the role. Testers see the private testers channel.`;

const COMMANDS = [
  { name: "human", type: 1, description: "Ask the LuxOS team (a human) to look at this support thread" }
];

// Vychozi kanaly a kategorie, ktere Discord vytvori se serverem (anglicky a cesky)
const DEFAULT_CHANNELS = new Set(["general", "obecné", "obecne"]);
const DEFAULT_CATEGORIES = new Set(["text channels", "voice channels", "textové kanály", "hlasové kanály"]);

function componentsKey(rows) {
  return JSON.stringify((rows || []).map((row) => (row.components || []).map((c) => [c.type, c.style, c.label, c.custom_id])));
}

function onboardingKey(o) {
  return JSON.stringify([
    Boolean(o.enabled), o.mode || 0, [...(o.default_channel_ids || [])].sort(),
    (o.prompts || []).map((p) => [p.title, p.type || 0, Boolean(p.single_select), Boolean(p.required), p.in_onboarding !== false,
      (p.options || []).map((x) => [x.title, x.description || "", [...(x.role_ids || [])].sort(), [...(x.channel_ids || [])].sort()])])
  ]);
}

// Nove id pro otazku/moznost Onboardingu (Discord chce snowflake; jako discord.py z casu)
let idCounter = 0n;
function newId() {
  idCounter += 1n;
  return String(((BigInt(Date.now()) - 1420070400000n) << 22n) + idCounter);
}

function sameOverwrites(a, b) {
  const norm = (list) => (list || []).map((o) => `${o.id}:${o.type}:${o.allow || "0"}:${o.deny || "0"}`).sort().join("|");
  return norm(a) === norm(b);
}

class Setup {
  constructor({ rest, guildId, mode = "auto", cleanupDefaults = false, log = console.log }) {
    Object.assign(this, { rest, guildId, mode, cleanupDefaults, log });
    this.ours = new Set(); // id kategorii a kanalu, ktere spravuje setup
    this.changes = 0;
    this.notes = [];
  }

  change(text) {
    this.changes += 1;
    this.log(`  + ${text}`);
  }

  async run() {
    this.me = await this.rest.get("/users/@me");
    if (!this.guildId) {
      const guilds = await this.rest.get("/users/@me/guilds");
      if (guilds.length !== 1) throw new Error(`the bot is in ${guilds.length} servers - pass --guild ID`);
      this.guildId = guilds[0].id;
    }
    this.guild = await this.rest.get(`/guilds/${this.guildId}`);
    this.log(`server: ${this.guild.name} (${this.guildId}), Community: ${this.community() ? "on" : "off"}`);
    this.channels = await this.rest.get(`/guilds/${this.guildId}/channels`);

    await this.ensureRoles();
    // zaklad, ktery potrebuje i pruvodce Community (kanal s pravidly a kanal pro zpravy Discordu)
    const info = await this.ensureCategory("INFO");
    const welcome = await this.ensureChannel({ name: "welcome-and-rules", type: 0, parent: info,
      topic: `Rules and where to start. Website: ${SITE}`, overwrites: this.readOnly() });
    const staff = await this.ensureCategory("STAFF", this.teamOnly());
    const team = await this.ensureChannel({ name: "team", type: 0, parent: staff,
      topic: "LuxOS team only: moderation and Discord's community updates.", overwrites: this.teamOnly() });
    await this.ensureChannel({ name: "bot-testing", type: 0, parent: staff,
      topic: "Team only: the bot answers every message here (in a thread), like in #support. Hand-off e-mails are marked [test].",
      overwrites: this.botTesting() });

    if (!this.community()) {
      if (this.mode === "enable-community") {
        await this.enableCommunity(welcome, team);
      } else if (this.mode !== "no-community") {
        this.printCommunityHelp();
        return { changes: this.changes, complete: false };
      }
    }
    await this.ensureGuildSettings(welcome, team);

    const announcements = await this.ensureChannel({ name: "announcements", type: this.community() ? 5 : 0, parent: info,
      topic: "News from the LuxOS team: releases, maintenance, important changes.", overwrites: this.readOnly() });
    const community = await this.ensureCategory("COMMUNITY");
    const general = await this.ensureChannel({ name: "general", type: 0, parent: community, topic: "Chat about LuxOS. Mention the bot to ask it something; real support questions go to #support." });
    const desktop = await this.ensureChannel({ name: "show-your-desktop", type: 0, parent: community, topic: "Screenshots of your LuxOS desktop. Hide personal info before posting." });
    const offTopic = await this.ensureChannel({ name: "off-topic", type: 0, parent: community, topic: "Anything else (keep it friendly and safe for work)." });
    const supportCategory = await this.ensureCategory("SUPPORT");
    const support = await this.ensureChannel({ name: "support", type: this.community() ? 15 : 0, parent: supportCategory,
      topic: SUPPORT_TOPIC, overwrites: this.botSupport(), tags: this.community() ? SUPPORT_TAGS : null });
    const dev = await this.ensureCategory("DEVELOPMENT");
    const ideas = await this.ensureChannel({ name: "ideas", type: 0, parent: dev, topic: "Ideas and wishes for LuxOS. One idea per message; discuss in threads." });
    const bugs = await this.ensureChannel({ name: "bug-reports", type: 0, parent: dev, overwrites: this.botBugs(),
      topic: `Bugs in LuxOS: one report per message, forwarded to the LuxOS team (the bot may ask for details). Also on GitHub: ${ISSUES}` });
    const testers = await this.ensureChannel({ name: "testers", type: 0, parent: dev,
      topic: "Testing the staging channel (open to anyone who wants to test): lux config channel staging, back with lux config channel stable. Bugs go to #bug-reports.",
      overwrites: this.testersOnly() });
    const voice = await this.ensureCategory("VOICE");
    await this.ensureChannel({ name: "General", type: 2, parent: voice });

    // zpravy az nakonec, at odkazuji na existujici kanaly (<#id>)
    const ch = Object.fromEntries(Object.entries({ support, bugs, ideas, general, desktop, testers }).map(([k, c]) => [k, `<#${c.id}>`]));
    await this.ensureMessage(welcome, WELCOME(ch));
    await this.ensureMessage(bugs, BUGS(ch));
    await this.ensureMessage(testers, TESTERS(ch));

    await this.ensureCommands();
    // vychozi kanaly Onboardingu: verejne kanaly (Discord chce >= 7, z toho >= 5 s psanim pro @everyone)
    let onboarding = false;
    if (this.community()) onboarding = await this.ensureOnboarding([welcome, announcements, general, desktop, offTopic, support, ideas, bugs]);
    this.usesRoleButtons = !onboarding;
    if (!onboarding) await this.ensureMessage(welcome, ROLE_MESSAGE, this.roleButtons());
    this.notes.push(`Server rules: Discord has no API for them. Click Server Settings → Access → "Server rules", turn it on and use "Add rule" for each:\n${RULES.map((r, i) => `     ${i + 1}. ${r}`).join("\n")}`);
    const invite = await this.ensureInvite(welcome);
    await this.removeDefaults();

    if (support.type === 0 && this.community()) {
      this.notes.push("#support is a text channel from a run without Community. To get the forum: delete #support in Discord and run setup again.");
    }
    if (announcements.type === 0 && !this.community()) {
      this.notes.push("#announcements is a read-only text channel; it becomes an Announcement channel when you enable Community and run setup again.");
    }
    for (const name of ["rules", "moderator-only"]) {
      if (this.channels.some((c) => c.name === name && c.type === 0)) {
        this.notes.push(`#${name} was created by the Community wizard; #welcome-and-rules and #team are used instead, so you can delete #${name}.`);
      }
    }
    return { changes: this.changes, complete: true, invite };
  }

  community() {
    return (this.guild.features || []).includes("COMMUNITY");
  }

  // ---- role ----

  async ensureRoles() {
    const roles = await this.rest.get(`/guilds/${this.guildId}/roles`);
    this.roles = {};
    for (const want of ROLES) {
      let role = roles.find((r) => r.name === want.name && !r.managed);
      if (!role) {
        role = await this.rest.post(`/guilds/${this.guildId}/roles`, want, { reason: "LuxOS setup" });
        this.change(`role ${want.name}`);
      } else if (role.permissions !== want.permissions || role.color !== want.color || role.hoist !== want.hoist || role.mentionable !== want.mentionable) {
        role = await this.rest.patch(`/guilds/${this.guildId}/roles/${role.id}`, want, { reason: "LuxOS setup" });
        this.change(`role ${want.name} updated`);
      }
      this.roles[want.name] = role.id;
    }
  }

  // ---- prepisy opravneni ----

  everyone() { return this.guildId; } // role @everyone ma id serveru

  readOnly() {
    const deny = perms("SEND_MESSAGES", "SEND_MESSAGES_IN_THREADS", "CREATE_PUBLIC_THREADS", "CREATE_PRIVATE_THREADS");
    return [
      { id: this.everyone(), type: 0, allow: "0", deny },
      { id: this.roles.Team, type: 0, allow: perms("SEND_MESSAGES", "SEND_MESSAGES_IN_THREADS", "CREATE_PUBLIC_THREADS"), deny: "0" },
      { id: this.me.id, type: 1, allow: perms("VIEW_CHANNEL", "SEND_MESSAGES", "READ_MESSAGE_HISTORY"), deny: "0" }
    ];
  }

  teamOnly() {
    return [
      { id: this.everyone(), type: 0, allow: "0", deny: perms("VIEW_CHANNEL") },
      { id: this.roles.Team, type: 0, allow: perms("VIEW_CHANNEL"), deny: "0" },
      { id: this.me.id, type: 1, allow: perms("VIEW_CHANNEL", "SEND_MESSAGES", "READ_MESSAGE_HISTORY"), deny: "0" }
    ];
  }

  // #bug-reports: bot reaguje ✅ a pta se ve vlaknech na hlaseni
  botBugs() {
    return [{ id: this.me.id, type: 1, deny: "0",
      allow: perms("VIEW_CHANNEL", "SEND_MESSAGES", "ADD_REACTIONS", "SEND_MESSAGES_IN_THREADS", "CREATE_PUBLIC_THREADS", "READ_MESSAGE_HISTORY") }];
  }

  botTesting() {
    return [
      { id: this.everyone(), type: 0, allow: "0", deny: perms("VIEW_CHANNEL") },
      { id: this.roles.Team, type: 0, allow: perms("VIEW_CHANNEL", "SEND_MESSAGES", "SEND_MESSAGES_IN_THREADS", "READ_MESSAGE_HISTORY"), deny: "0" },
      { id: this.me.id, type: 1, deny: "0",
        allow: perms("VIEW_CHANNEL", "SEND_MESSAGES", "SEND_MESSAGES_IN_THREADS", "CREATE_PUBLIC_THREADS", "MANAGE_THREADS", "READ_MESSAGE_HISTORY") }
    ];
  }

  testersOnly() {
    return [
      { id: this.everyone(), type: 0, allow: "0", deny: perms("VIEW_CHANNEL") },
      { id: this.roles.Tester, type: 0, allow: perms("VIEW_CHANNEL"), deny: "0" },
      { id: this.roles.Team, type: 0, allow: perms("VIEW_CHANNEL"), deny: "0" },
      { id: this.me.id, type: 1, allow: perms("VIEW_CHANNEL", "SEND_MESSAGES", "READ_MESSAGE_HISTORY"), deny: "0" }
    ];
  }

  botSupport() {
    return [{ id: this.me.id, type: 1, deny: "0",
      allow: perms("VIEW_CHANNEL", "SEND_MESSAGES", "SEND_MESSAGES_IN_THREADS", "CREATE_PUBLIC_THREADS", "MANAGE_THREADS", "READ_MESSAGE_HISTORY") }];
  }

  // ---- kategorie a kanaly ----

  async ensureCategory(name, overwrites = []) {
    let category = this.channels.find((c) => c.type === 4 && c.name.toLowerCase() === name.toLowerCase());
    if (!category) {
      category = await this.rest.post(`/guilds/${this.guildId}/channels`, { name, type: 4, permission_overwrites: overwrites }, { reason: "LuxOS setup" });
      this.channels.push(category);
      this.change(`category ${name}`);
      this.ours.add(category.id);
      return category;
    } else if (!sameOverwrites(category.permission_overwrites, overwrites)) {
      category = await this.rest.patch(`/channels/${category.id}`, { permission_overwrites: overwrites }, { reason: "LuxOS setup" });
      this.replace(category);
      this.change(`category ${name} permissions`);
    }
    this.ours.add(category.id);
    return category;
  }

  // Prazdne vychozi kanaly Discordu ("obecné", "Obecné", "general" mimo nase kategorie) a jejich
  // prazdne kategorie: smaze jen s --cleanup-defaults, jinak jen vypise
  async removeDefaults() {
    const candidates = [];
    for (const c of this.channels) {
      if (this.ours.has(c.id) || this.ours.has(c.parent_id) || (c.type !== 0 && c.type !== 2) || !DEFAULT_CHANNELS.has(c.name.toLowerCase())) continue;
      if (c.type === 0) {
        const messages = await this.rest.get(`/channels/${c.id}/messages?limit=1`);
        if (messages.length) {
          this.notes.push(`#${c.name} (a default Discord channel) has messages, so it is not deleted. Delete it in Discord if you don't need it.`);
          continue;
        }
      }
      candidates.push(c);
    }
    const leaving = new Set(candidates.map((c) => c.id));
    for (const c of this.channels) {
      if (c.type !== 4 || this.ours.has(c.id) || !DEFAULT_CATEGORIES.has(c.name.toLowerCase())) continue;
      if (this.channels.every((x) => x.parent_id !== c.id || leaving.has(x.id))) candidates.push(c);
    }
    if (!candidates.length) return;
    const label = (c) => (c.type === 4 ? `category ${c.name}` : c.type === 2 ? `voice ${c.name}` : `#${c.name}`);
    if (!this.cleanupDefaults) {
      this.notes.push(`Empty default Discord channels outside the LuxOS categories: ${candidates.map(label).join(", ")}. Run setup with --cleanup-defaults to delete them.`);
      return;
    }
    // nejdriv kanaly, pak kategorie
    for (const c of candidates.sort((a, b) => (a.type === 4) - (b.type === 4))) {
      await this.rest.delete(`/channels/${c.id}`, { reason: "LuxOS setup: remove empty default channel" });
      this.channels = this.channels.filter((x) => x.id !== c.id);
      this.change(`deleted default ${label(c)}`);
    }
  }

  replace(channel) {
    this.channels = this.channels.map((c) => (c.id === channel.id ? channel : c));
  }

  async ensureChannel({ name, type, parent, topic = null, overwrites = [], tags = null }) {
    const family = (t) => (t === 0 || t === 5 || t === 15 ? "text" : String(t));
    let channel = this.channels.find((c) => c.name.toLowerCase() === name.toLowerCase() && family(c.type) === family(type));
    const body = { name, type, parent_id: parent.id, permission_overwrites: overwrites };
    if (type !== 2) body.topic = topic;
    if (tags) body.available_tags = tags;
    if (type === 15) body.default_forum_layout = 1;
    if (!channel) {
      channel = await this.rest.post(`/guilds/${this.guildId}/channels`, body, { reason: "LuxOS setup" });
      this.channels.push(channel);
      this.change(`channel ${type === 2 ? "voice " : "#"}${name}`);
      this.ours.add(channel.id);
      return channel;
    }
    const patch = {};
    if (channel.parent_id !== parent.id) patch.parent_id = parent.id;
    if (type !== 2 && (channel.topic || null) !== (topic || null)) patch.topic = topic;
    if (!sameOverwrites(channel.permission_overwrites, overwrites)) patch.permission_overwrites = overwrites;
    if (channel.type === 0 && type === 5) patch.type = 5; // textovy -> Announcement (jen s Community)
    if (tags && channel.type === 15) {
      const existing = channel.available_tags || [];
      const merged = tags.map((tag) => {
        const found = existing.find((x) => x.name === tag.name);
        return found ? { ...found, moderated: tag.moderated } : tag;
      });
      const extra = existing.filter((x) => !tags.some((tag) => tag.name === x.name));
      const differs = tags.some((tag) => {
        const found = existing.find((x) => x.name === tag.name);
        return !found || found.moderated !== tag.moderated;
      });
      if (differs) patch.available_tags = [...merged, ...extra].slice(0, 20);
    }
    if (Object.keys(patch).length) {
      channel = await this.rest.patch(`/channels/${channel.id}`, patch, { reason: "LuxOS setup" });
      this.replace(channel);
      this.change(`channel #${name}: ${Object.keys(patch).join(", ")}`);
    }
    this.ours.add(channel.id);
    return channel;
  }

  // Zprava bota v kanalu: hleda se podle prvniho radku, rozdilny text se upravi
  async ensureMessage(channel, content, components = []) {
    const firstLine = content.split("\n")[0];
    const messages = await this.rest.get(`/channels/${channel.id}/messages?limit=50`);
    const mine = messages.find((m) => m.author && m.author.id === this.me.id && (m.content || "").split("\n")[0] === firstLine);
    const body = { content, components, allowed_mentions: { parse: [] }, flags: 1 << 2 };
    if (!mine) {
      await this.rest.post(`/channels/${channel.id}/messages`, body);
      this.change(`message "${firstLine.replace(/\*/g, "")}" in #${channel.name}`);
    } else if (mine.content !== content || componentsKey(mine.components) !== componentsKey(components)) {
      await this.rest.patch(`/channels/${channel.id}/messages/${mine.id}`, { content, components, allowed_mentions: { parse: [] } });
      this.change(`message "${firstLine.replace(/\*/g, "")}" in #${channel.name} updated`);
    }
  }

  // ---- server ----

  async enableCommunity(welcome, team) {
    const body = {
      features: [...new Set([...(this.guild.features || []), "COMMUNITY"])],
      verification_level: Math.max(1, this.guild.verification_level || 0),
      explicit_content_filter: 2,
      rules_channel_id: welcome.id,
      public_updates_channel_id: team.id
    };
    this.guild = await this.rest.patch(`/guilds/${this.guildId}`, body, { reason: "LuxOS setup: enable Community" });
    this.change("Community enabled (rules: #welcome-and-rules, Discord updates: #team)");
    if (!this.community()) throw new Error("Discord did not enable Community - enable it in Server Settings (see README)");
  }

  async ensureGuildSettings(welcome, team) {
    const patch = {};
    if (this.guild.default_message_notifications !== 1) patch.default_message_notifications = 1; // jen zminky
    if (this.guild.explicit_content_filter !== 2) patch.explicit_content_filter = 2;
    if ((this.guild.verification_level || 0) < 1) patch.verification_level = 1; // overeny e-mail
    if (this.community()) {
      if (this.guild.rules_channel_id !== welcome.id) patch.rules_channel_id = welcome.id;
      if (this.guild.public_updates_channel_id !== team.id) patch.public_updates_channel_id = team.id;
    }
    if (Object.keys(patch).length) {
      this.guild = await this.rest.patch(`/guilds/${this.guildId}`, patch, { reason: "LuxOS setup" });
      this.change(`server settings: ${Object.keys(patch).join(", ")}`);
    }
  }

  async ensureCommands() {
    const app = await this.rest.get("/oauth2/applications/@me");
    const path = `/applications/${app.id}/guilds/${this.guildId}/commands`;
    const existing = await this.rest.get(path);
    const same = existing.length === COMMANDS.length && COMMANDS.every((want) =>
      existing.some((c) => c.name === want.name && c.description === want.description && (c.type || 1) === want.type));
    if (!same) {
      await this.rest.put(path, COMMANDS);
      this.change("slash command /human");
    }
    this.appId = app.id;
  }

  roleButtons() {
    return [{ type: 1, components: SELF_ROLES.map((r, i) => ({ type: 2, style: i === 0 ? 1 : 2, label: r.role, custom_id: `role:${r.role}` })) }];
  }

  // Onboarding: jedna povinna otazka s vyberem jedne role. Kdyz ho Discord odmitne, vrati false
  // a setup pouzije zpravu s tlacitky.
  async ensureOnboarding(defaults) {
    const path = `/guilds/${this.guildId}/onboarding`;
    const fallback = (error) => {
      this.notes.push(`Onboarding could not be set (${error.message}); a message with role buttons in #welcome-and-rules is used instead. The bot then needs the Manage Roles permission (README, step 5).`);
      return false;
    };
    let current;
    try {
      current = await this.rest.get(path);
    } catch (error) {
      return fallback(error);
    }
    const oldPrompt = (current.prompts || []).find((p) => p.title === ONBOARDING_PROMPT);
    const want = {
      enabled: true,
      mode: 0, // ONBOARDING_DEFAULT: pocitaji se jen vychozi kanaly
      default_channel_ids: defaults.map((c) => c.id),
      prompts: [{
        id: oldPrompt ? oldPrompt.id : newId(),
        type: 0, title: ONBOARDING_PROMPT, single_select: true, required: true, in_onboarding: true,
        options: SELF_ROLES.map((r) => {
          const old = oldPrompt && (oldPrompt.options || []).find((o) => o.title === r.title);
          return { id: old ? old.id : newId(), title: r.title, description: r.description, role_ids: [this.roles[r.role]], channel_ids: [] };
        })
      }, ...(current.prompts || []).filter((p) => p.title !== ONBOARDING_PROMPT)]
    };
    if (onboardingKey(current) === onboardingKey(want)) return true;
    try {
      await this.rest.put(path, want, { reason: "LuxOS setup: choose Tester or Member" });
    } catch (error) {
      return fallback(error);
    }
    this.change(`Onboarding: "${ONBOARDING_PROMPT}" → Tester / Member`);
    return true;
  }

  async ensureInvite(welcome) {
    const invites = await this.rest.get(`/guilds/${this.guildId}/invites`);
    let invite = invites.find((i) => i.channel && i.channel.id === welcome.id && i.max_age === 0 && i.max_uses === 0 &&
      !i.temporary && i.inviter && i.inviter.id === this.me.id);
    if (!invite) {
      invite = await this.rest.post(`/channels/${welcome.id}/invites`, { max_age: 0, max_uses: 0, temporary: false, unique: true }, { reason: "LuxOS setup: website invite" });
      this.change("permanent invite");
    }
    return `https://discord.gg/${invite.code}`;
  }

  printCommunityHelp() {
    this.log(`
Community is OFF on this server. The forum #support, the #announcements channel and
Onboarding (members pick Tester or Member) need it. Created so far: roles, #welcome-and-rules and the private #team and #bot-testing.

Choose one:
  a) Let the bot switch it on (verified e-mail required to chat, media filter for everyone,
     rules channel #welcome-and-rules, Discord updates channel #team):
        node src/setup.js --enable-community
  b) Click it yourself: Server Settings → Enable Community → Get Started.
     Safety check: keep "Verified email" and "Scan media from all members".
     Basics: Rules channel = #welcome-and-rules, Community updates channel = #team.
     Final step: accept, then run this setup again.
  c) Keep Community off (#support as a text channel where the bot answers in threads,
     read-only text #announcements, role buttons instead of Onboarding):
        node src/setup.js --no-community

"Discoverable" (Server Discovery) additionally needs Discord's eligibility (server age,
member count, activity) - until then use the invite link on the website.`);
  }
}

// manageRoles: zalozni tlacitka pro vyber role (bez Onboardingu) potrebuji Manage Roles
function inviteUrl(appId, manageRoles = false) {
  const permissions = manageRoles ? (BigInt(BOT_PERMISSIONS) | (1n << 28n)).toString() : BOT_PERMISSIONS;
  return `https://discord.com/oauth2/authorize?client_id=${appId}&scope=bot+applications.commands&permissions=${permissions}`;
}

async function main() {
  const argv = process.argv.slice(2);
  let guildId = "";
  let mode = "auto";
  let cleanupDefaults = false;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--guild") guildId = argv[++i] || "";
    else if (argv[i] === "--enable-community") mode = "enable-community";
    else if (argv[i] === "--no-community") mode = "no-community";
    else if (argv[i] === "--cleanup-defaults") cleanupDefaults = true;
    else { console.error(`usage: node src/setup.js [--guild ID] [--enable-community | --no-community] [--cleanup-defaults]`); process.exit(2); }
  }
  const config = load();
  const token = readSecret(config.tokenFile, "Discord bot token");
  const setup = new Setup({ rest: new Rest({ api: config.discordApi, token }), guildId: guildId || config.guildId, mode, cleanupDefaults });
  let result;
  try {
    result = await setup.run();
  } catch (error) {
    console.error(`setup failed: ${error.message}`);
    if (error.status === 403) console.error("The bot needs the Administrator permission while setup runs (README, step 3).");
    process.exit(1);
  }
  console.log(`\n${result.changes ? `${result.changes} change(s) made.` : "Nothing to change - the server is already set up."}`);
  if (!result.complete) process.exit(3);
  console.log(`
Permanent invite for the website: ${result.invite}

Next steps for the owner:
  1. Reduce the bot's permissions: open this link and authorize it for the LuxOS server
     ${inviteUrl(setup.appId, setup.usesRoleButtons)}
     then check Server Settings → Roles → (bot's role): "Administrator" must be OFF.
  2. Give yourself the Team role: Server Settings → Members → you → + → Team.
  3. Put the invite link on the website.`);
  for (const note of setup.notes) console.log(`\nNote: ${note}`);
}

if (require.main === module) main();

module.exports = { Setup, BOT_PERMISSIONS, RULES, SELF_ROLES, ONBOARDING_PROMPT, inviteUrl };
