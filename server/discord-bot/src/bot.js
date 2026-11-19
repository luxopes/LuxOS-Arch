"use strict";
// Logika bota: kde odpovida (kazdy novy prispevek v #support, v #general jen po zmince, v DM jen
// clenum serveru), limity, sestaveni dotazu pro LuxAI, odeslani odpovedi a predani cloveku.
// Obsah zprav se neloguje; v logu jsou jen druhy udalosti a id.

const { texts, detectLanguage } = require("./texts");

const THREAD_TYPES = new Set([10, 11, 12]);
const FORUM = 15;
const MAX_DISCORD = 1900;
const HISTORY_CHARS = 8000;
const SUPPRESS_EMBEDS = 1 << 2;
const EPHEMERAL = 1 << 6;
const NEEDS_HUMAN_TAG = "Needs human";

// Zjevna zadost o cloveka (bez volani modelu); ostatni pozna model priznakem "handoff"
const HUMAN_RE = /\b((talk|speak|chat) (to|with) (a |an )?(human|person|real person|team member|moderator|admin)|need (a )?(human|real person)|real person|human please)\b|^\s*human\s*[.!?]*\s*$|(chci|potřebuji|potrebuji) (mluvit s |)(člověk|clovek)|s (živým )?(člověkem|clovekem)/i;
// Tajne udaje, ktere nesmi odejit modelu: klice LuxAI, tokeny Discordu, GitHubu, AWS, privatni klice
const SECRET_RE = /\blux-[A-Za-z0-9_-]{32,}|\b[MNO][A-Za-z\d_-]{23,27}\.[A-Za-z\d_-]{6}\.[A-Za-z\d_-]{27,}|\bgh[pousr]_[A-Za-z0-9]{36}|\bAKIA[0-9A-Z]{16}\b|-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(password|passwd|heslo)\s*[:=]\s*\S{4,}/i;

function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

// Rozdeli text na zpravy do 1900 znaku, nejradeji na odstavcich; rozdeleny blok kodu uzavre a znovu otevre
function splitMessage(text, max = MAX_DISCORD) {
  const out = [];
  let rest = text;
  while (rest.length > max) {
    let cut = rest.lastIndexOf("\n\n", max);
    if (cut < max / 2) cut = rest.lastIndexOf("\n", max);
    if (cut < max / 2) cut = rest.lastIndexOf(" ", max);
    if (cut < max / 2) cut = max;
    let part = rest.slice(0, cut).trimEnd();
    rest = rest.slice(cut).trimStart();
    if ((part.match(/```/g) || []).length % 2 === 1) { part += "\n```"; rest = "```\n" + rest; }
    out.push(part);
  }
  if (rest.trim()) out.push(rest);
  return out;
}

class Bot {
  constructor({ config, rest, assistant, knowledge, mailer, state, log = console.log }) {
    Object.assign(this, { config, rest, assistant, knowledge, mailer, state, log });
    this.user = null;
    this.guildId = config.guildId || "";
    this.channels = new Map();
    this.members = new Map(); // id uzivatele -> {member, at} (cache pro DM)
    this.userAnswers = new Map(); // id uzivatele -> casy odpovedi
    this.notified = new Map(); // klic -> do kdy uz upozorneni neopakovat
    this.active = 0;
    this.waiting = [];
    this.pending = new Set(); // bezici odpovedi (pro testy a cisty konec)
  }

  // ---- udalosti z gateway ----

  onDispatch(type, d) {
    switch (type) {
      case "READY":
        this.user = d.user;
        if (!this.guildId && d.guilds && d.guilds.length === 1) this.guildId = d.guilds[0].id;
        this.log(`ready as ${d.user.username} (${d.user.id}), guilds=${d.guilds ? d.guilds.length : 0}`);
        break;
      case "GUILD_CREATE":
        if (!this.guildId) this.guildId = d.id;
        if (d.id !== this.guildId) { this.log(`ignoring guild ${d.id} (not DISCORD_GUILD_ID)`); break; }
        for (const channel of [...(d.channels || []), ...(d.threads || [])]) this.cacheChannel({ ...channel, guild_id: d.id });
        break;
      case "CHANNEL_CREATE": case "CHANNEL_UPDATE": case "THREAD_CREATE": case "THREAD_UPDATE":
        if (d.guild_id === this.guildId) this.cacheChannel(d);
        break;
      case "CHANNEL_DELETE": case "THREAD_DELETE":
        this.channels.delete(d.id);
        break;
      case "THREAD_LIST_SYNC":
        for (const thread of d.threads || []) this.cacheChannel(thread);
        break;
      case "MESSAGE_CREATE":
        this.track(this.onMessage(d));
        break;
      case "INTERACTION_CREATE":
        this.track(this.onInteraction(d));
        break;
      default: break;
    }
  }

  track(promise) {
    const p = promise.catch((error) => this.log(`error: ${error.message}`)).finally(() => this.pending.delete(p));
    this.pending.add(p);
  }

  async idle() {
    while (this.pending.size) await Promise.all([...this.pending]);
  }

  cacheChannel(c) {
    const old = this.channels.get(c.id) || {};
    this.channels.set(c.id, {
      id: c.id, name: c.name ?? old.name, type: c.type ?? old.type, parent_id: c.parent_id ?? old.parent_id,
      owner_id: c.owner_id ?? old.owner_id, applied_tags: c.applied_tags ?? old.applied_tags,
      available_tags: c.available_tags ?? old.available_tags
    });
  }

  findChannel(name) {
    for (const channel of this.channels.values()) {
      if (channel.name === name && !THREAD_TYPES.has(channel.type) && channel.type !== 4) return channel;
    }
    return null;
  }

  async channel(id) {
    if (this.channels.has(id)) return this.channels.get(id);
    try {
      const c = await this.rest.get(`/channels/${id}`);
      if (c.guild_id && c.guild_id !== this.guildId) return null;
      this.cacheChannel(c);
      return this.channels.get(id);
    } catch {
      return null;
    }
  }

  mentioned(msg) {
    if (!this.user) return false;
    if ((msg.mentions || []).some((u) => u.id === this.user.id)) return true;
    if (msg.referenced_message && msg.referenced_message.author && msg.referenced_message.author.id === this.user.id) return true;
    return new RegExp(`<@!?${this.user.id}>`).test(msg.content || "");
  }

  // ---- zpravy ----

  async onMessage(msg) {
    if (!msg.author || msg.author.bot || msg.webhook_id || msg.author.system) return;
    if (msg.type !== 0 && msg.type !== 19) return;
    if (msg.mention_everyone) return;
    if (!(msg.content || "").trim()) return;
    if (!msg.guild_id) { await this.onDirectMessage(msg); return; }
    if (msg.guild_id !== this.guildId) return;
    const channel = await this.channel(msg.channel_id);
    if (!channel) return;
    const support = this.findChannel(this.config.channels.support);
    const general = this.findChannel(this.config.channels.general);

    // #support jako textovy kanal (server bez Community): z otazky udelat vlakno a odpovedet v nem
    if (support && channel.id === support.id && support.type !== FORUM) {
      const name = this.cleanContent(msg.content).replace(/\s+/g, " ").slice(0, 90) || "Question";
      const thread = await this.rest.post(`/channels/${channel.id}/messages/${msg.id}/threads`, { name, auto_archive_duration: 1440 });
      this.cacheChannel({ ...thread, owner_id: msg.author.id });
      this.state.setThread(thread.id, { op: msg.author.id, replies: 0 });
      await this.respond({ msg, channelId: thread.id, threadId: thread.id, title: name, fresh: true });
      return;
    }

    if (support && THREAD_TYPES.has(channel.type) && channel.parent_id === support.id) {
      let info = this.state.thread(channel.id);
      const mention = this.mentioned(msg);
      if (!info) {
        // prvni zprava ve vlakne, ktere bot jeste nezna: prispevek ve foru ma id zpravy = id vlakna
        if (msg.id !== channel.id && channel.owner_id !== msg.author.id && !mention) return;
        info = this.state.setThread(channel.id, { op: channel.owner_id || msg.author.id, replies: 0 });
        await this.respond({ msg, channelId: channel.id, threadId: channel.id, title: channel.name, fresh: msg.id === channel.id });
        return;
      }
      if (msg.author.id !== info.op && !mention) return;
      if (info.escalated && !mention) return; // vlakno uz resi clovek
      await this.respond({ msg, channelId: channel.id, threadId: channel.id, title: channel.name, fresh: false });
      return;
    }

    const inGeneral = general && (channel.id === general.id || (THREAD_TYPES.has(channel.type) && channel.parent_id === general.id));
    if (inGeneral && this.mentioned(msg)) {
      await this.respond({ msg, channelId: channel.id, replyTo: msg.id, fresh: true });
    }
  }

  async onDirectMessage(msg) {
    if (!this.guildId) return;
    if (!(await this.isMember(msg.author.id))) {
      if (this.notifyOnce(`members:${msg.author.id}`, 24 * 3600 * 1000)) {
        await this.send(msg.channel_id, texts(detectLanguage(msg.content)).membersOnly);
      }
      return;
    }
    await this.respond({ msg, channelId: msg.channel_id, dm: true, fresh: false });
  }

  async isMember(userId) {
    const cached = this.members.get(userId);
    if (cached && Date.now() - cached.at < 10 * 60 * 1000) return cached.member;
    let member = false;
    try {
      await this.rest.get(`/guilds/${this.guildId}/members/${userId}`);
      member = true;
    } catch (error) {
      if (error.status !== 404) throw error;
    }
    this.members.set(userId, { member, at: Date.now() });
    return member;
  }

  cleanContent(content) {
    return String(content || "").replace(/<@!?\d+>/g, "").replace(/<@&\d+>/g, "").trim();
  }

  notifyOnce(key, ms) {
    const until = this.notified.get(key) || 0;
    if (until > Date.now()) return false;
    this.notified.set(key, Date.now() + ms);
    if (this.notified.size > 5000) {
      for (const [k, t] of this.notified) if (t < Date.now()) this.notified.delete(k);
    }
    return true;
  }

  // Limit na uzivatele: N odpovedi za 10 minut a M za den
  userLimit(userId) {
    const now = Date.now();
    const times = (this.userAnswers.get(userId) || []).filter((t) => now - t < 24 * 3600 * 1000);
    this.userAnswers.set(userId, times);
    const recent = times.filter((t) => now - t < 10 * 60 * 1000);
    if (times.length >= this.config.limits.userPerDay) return { ok: false, kind: "day" };
    if (recent.length >= this.config.limits.userPer10Min) {
      return { ok: false, kind: "slow", minutes: Math.max(1, Math.ceil((recent[0] + 10 * 60 * 1000 - now) / 60000)) };
    }
    return { ok: true };
  }

  async withSlot(fn) {
    if (this.active >= this.config.limits.concurrent) {
      if (this.waiting.length >= this.config.limits.queue) return false;
      await new Promise((resolve) => this.waiting.push(resolve));
    } else {
      this.active += 1;
    }
    try {
      await fn();
    } finally {
      const next = this.waiting.shift();
      if (next) next(); else this.active -= 1;
    }
    return true;
  }

  // ctx: {msg, channelId, threadId?, replyTo?, dm?, title?, fresh}
  async respond(ctx) {
    const { msg } = ctx;
    const limits = this.config.limits;
    let lang = detectLanguage(msg.content);
    const t = texts(lang);
    const mail = this.config.contactMail;
    const info = ctx.threadId ? this.state.thread(ctx.threadId) : null;

    if (SECRET_RE.test(msg.content)) {
      await this.send(ctx.channelId, t.secret, ctx.replyTo);
      this.log(`secret warning channel=${ctx.channelId}`);
      return;
    }
    if (HUMAN_RE.test(msg.content) && msg.content.length < 300) {
      await this.handoff(ctx, lang, "user asked for a human", "");
      return;
    }
    const limit = this.userLimit(msg.author.id);
    if (!limit.ok) {
      if (this.notifyOnce(`limit:${msg.author.id}`, 10 * 60 * 1000)) {
        await this.send(ctx.channelId, limit.kind === "day" ? t.dailyUser : t.slow(limit.minutes), ctx.replyTo);
      }
      return;
    }
    if (info && info.replies >= limits.threadReplies) {
      if (!info.capped) {
        this.state.setThread(ctx.threadId, { capped: true });
        await this.send(ctx.channelId, t.threadCap(mail));
        await this.escalate(ctx, "thread reached the bot's reply limit", "");
      }
      return;
    }
    if (!this.state.takeDailyAnswer(limits.dailyCap)) {
      if (this.notifyOnce(`daily:${ctx.threadId || msg.author.id}`, 24 * 3600 * 1000)) {
        await this.send(ctx.channelId, t.dailyGlobal(mail), ctx.replyTo);
      }
      this.log("daily answer cap reached");
      return;
    }
    this.userAnswers.get(msg.author.id).push(Date.now());

    const started = await this.withSlot(async () => {
      this.rest.post(`/channels/${ctx.channelId}/typing`).catch(() => {});
      let question = this.cleanContent(msg.content);
      let truncated = false;
      if (question.length > limits.questionChars) { question = question.slice(0, limits.questionChars); truncated = true; }
      const history = await this.history(ctx, question);
      let query = `${ctx.title || ""} ${question}`;
      if (lang !== "en") {
        try { query += " " + await this.assistant.searchTerms(`${ctx.title || ""}\n${question}`); } catch { /* hledat i tak */ }
      }
      const passages = this.knowledge ? this.knowledge.search(query, 5) : [];
      let reply;
      try {
        reply = await this.assistant.answer(history, passages);
      } catch (error) {
        this.log(`luxai error: ${error.message}`);
        await this.send(ctx.channelId, t.error(mail), ctx.replyTo);
        return;
      }
      const { meta } = reply;
      if (meta.lang) lang = meta.lang;
      const tt = texts(lang);
      let text = reply.text;
      if (truncated) text = `${tt.tooLong(limits.questionChars)}\n\n${text}`;
      if (!/luxos\.lux-ai\.cz/.test(text) && passages.length) {
        const links = [...new Set(passages.map((p) => p.url))].slice(0, 3).map((u) => `<${u}>`);
        text += `\n\n-# ${tt.docs}: ${links.join(" · ")}`;
      }
      const needsHuman = meta.handoff || !meta.confident;
      if (needsHuman && !ctx.threadId) text += `\n\n${tt.elsewhere(this.supportMention(), mail)}`;
      await this.send(ctx.channelId, text, ctx.replyTo);
      if (ctx.threadId) this.state.setThread(ctx.threadId, { replies: ((this.state.thread(ctx.threadId) || {}).replies || 0) + 1 });
      this.log(`answered channel=${ctx.channelId} passages=${passages.length} confident=${meta.confident} handoff=${meta.handoff}`);
      if (needsHuman && ctx.threadId) {
        await this.handoff(ctx, lang, meta.handoff ? "the assistant suggests the LuxOS team" : "the assistant was not confident", meta.summary, !meta.handoff);
      }
    });
    if (!started) await this.send(ctx.channelId, t.busy, ctx.replyTo);
  }

  // Historie konverzace pro model: ve vlakne / DM poslednich par zprav tazatele a bota
  async history(ctx, question) {
    const first = ctx.title && ctx.fresh ? `${ctx.title}\n\n${question}` : question;
    if (ctx.fresh) return [{ role: "user", content: first }];
    let messages = [];
    try {
      messages = await this.rest.get(`/channels/${ctx.channelId}/messages?limit=12`);
    } catch {
      return [{ role: "user", content: first }];
    }
    const op = ctx.dm ? ctx.msg.author.id : (this.state.thread(ctx.threadId) || {}).op;
    const out = [];
    let chars = 0;
    for (const m of messages) { // od nejnovejsi
      if (m.id === ctx.msg.id) continue;
      let role = null;
      if (this.user && m.author.id === this.user.id) role = "assistant";
      else if (m.author.id === op || m.author.id === ctx.msg.author.id) role = "user";
      if (!role || !m.content) continue;
      let content = role === "assistant" ? m.content.replace(/\n-# .*$/gm, "").trim() : this.cleanContent(m.content);
      if (role === "user" && ctx.threadId && m.id === ctx.threadId && ctx.title) content = `${ctx.title}\n\n${content}`;
      chars += content.length;
      if (chars > HISTORY_CHARS) break;
      out.unshift({ role, content });
    }
    while (out.length && out[0].role === "assistant") out.shift();
    out.push({ role: "user", content: question });
    return out;
  }

  supportMention() {
    const support = this.findChannel(this.config.channels.support);
    return support ? `<#${support.id}>` : "#support";
  }

  // Zprava pro uzivatele + oznaceni vlakna + e-mail; mimo vlakno #support jen odkaz kam se obratit
  async handoff(ctx, lang, reason, summary, notConfident = false) {
    const t = texts(lang);
    const mail = this.config.contactMail;
    if (!ctx.threadId) {
      await this.send(ctx.channelId, t.elsewhere(this.supportMention(), mail), ctx.replyTo);
      return;
    }
    const info = this.state.thread(ctx.threadId) || {};
    if (info.escalated) {
      await this.send(ctx.channelId, t.handoffAlready(mail));
      return;
    }
    await this.send(ctx.channelId, notConfident ? `${t.notConfident} ${t.handoff(mail)}` : t.handoff(mail));
    await this.escalate(ctx, reason, summary);
  }

  async escalate(ctx, reason, summary) {
    const info = this.state.thread(ctx.threadId) || {};
    if (info.escalated) return;
    this.state.setThread(ctx.threadId, { escalated: true });
    const thread = await this.channel(ctx.threadId);
    try {
      await this.tagNeedsHuman(thread);
    } catch (error) {
      this.log(`tagging failed thread=${ctx.threadId}: ${error.message}`);
    }
    if (!this.mailer) return;
    try {
      const sent = await this.mailer.escalate({
        title: (thread && thread.name) || ctx.title || "Discord question",
        link: `https://discord.com/channels/${this.guildId}/${ctx.threadId}`,
        author: ctx.msg.author.global_name ? `${ctx.msg.author.global_name} (@${ctx.msg.author.username})` : `@${ctx.msg.author.username}`,
        reason,
        summary,
        question: this.cleanContent(ctx.msg.content).slice(0, 600)
      });
      this.log(sent ? `escalation mail sent thread=${ctx.threadId}` : `escalation mail skipped (rate limit) thread=${ctx.threadId}`);
    } catch (error) {
      this.log(`escalation mail failed thread=${ctx.threadId}: ${error.message}`);
    }
  }

  async tagNeedsHuman(thread) {
    if (!thread) return;
    const parent = await this.channel(thread.parent_id);
    if (parent && parent.type === FORUM) {
      const tag = (parent.available_tags || []).find((x) => x.name === NEEDS_HUMAN_TAG);
      if (!tag) return;
      const tags = thread.applied_tags || [];
      if (tags.includes(tag.id)) return;
      const updated = await this.rest.patch(`/channels/${thread.id}`, { applied_tags: [tag.id, ...tags].slice(0, 5) });
      this.cacheChannel(updated || { id: thread.id, applied_tags: [tag.id, ...tags].slice(0, 5) });
    } else if (thread.name && !thread.name.startsWith("[Needs human]")) {
      // textovy #support nema stitky: oznacit nazvem vlakna
      const name = `[Needs human] ${thread.name}`.slice(0, 100);
      await this.rest.patch(`/channels/${thread.id}`, { name });
      this.cacheChannel({ id: thread.id, name });
    }
  }

  async send(channelId, content, replyTo) {
    const parts = splitMessage(content);
    for (let i = 0; i < parts.length && i < 4; i++) {
      const body = { content: parts[i], allowed_mentions: { parse: [], replied_user: false }, flags: SUPPRESS_EMBEDS };
      if (i === 0 && replyTo) body.message_reference = { message_id: replyTo, fail_if_not_exists: false };
      await this.rest.post(`/channels/${channelId}/messages`, body);
      if (i + 1 < parts.length) await sleep(300);
    }
  }

  // ---- prikaz /human ----

  async onInteraction(interaction) {
    if (interaction.type !== 2 || !interaction.data || interaction.data.name !== "human") return;
    const user = (interaction.member && interaction.member.user) || interaction.user;
    const locale = String(interaction.locale || "en");
    const lang = locale.startsWith("cs") || locale.startsWith("sk") ? "cs" : "en";
    const t = texts(lang);
    const mail = this.config.contactMail;
    const channel = interaction.guild_id === this.guildId ? await this.channel(interaction.channel_id) : null;
    const support = this.findChannel(this.config.channels.support);
    const reply = (content, ephemeral) => this.rest.post(`/interactions/${interaction.id}/${interaction.token}/callback`, {
      type: 4, data: { content, flags: (ephemeral ? EPHEMERAL : 0) | SUPPRESS_EMBEDS, allowed_mentions: { parse: [] } }
    });
    if (!channel || !support || !THREAD_TYPES.has(channel.type) || channel.parent_id !== support.id) {
      await reply(t.elsewhere(this.supportMention(), mail), true);
      return;
    }
    const info = this.state.thread(channel.id) || this.state.setThread(channel.id, { op: channel.owner_id || user.id, replies: 0 });
    if (info.escalated) { await reply(t.handoffAlready(mail), false); return; }
    await reply(t.handoff(mail), false);
    const msg = { author: user, content: `/human in "${channel.name}"` };
    await this.escalate({ msg, channelId: channel.id, threadId: channel.id, title: channel.name }, "user used /human", "");
  }
}

module.exports = { Bot, splitMessage, HUMAN_RE, SECRET_RE };
