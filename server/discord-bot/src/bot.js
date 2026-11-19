"use strict";
// Logika bota: kde odpovida (kazdy novy prispevek v #support a kazda zprava v tymovem #bot-testing,
// v #general jen po zmince, v DM jen
// clenum serveru), limity, sestaveni dotazu pro LuxAI, odeslani odpovedi a predani cloveku.
// Obsah zprav se neloguje; v logu jsou jen druhy udalosti a id.

const { texts, detectLanguage, shortCategory } = require("./texts");
const { tokenize } = require("./knowledge");
const { SECRET_RE } = require("./secrets");
const { BugReports } = require("./bugs");

// Zdroje, ktere smi rozhodnout o odpovedi: dokumentace, FAQ a seznam zmen (ne reklamni stranky)
const DOCS_URL_RE = /^https:\/\/luxos\.lux-ai\.cz\/(docs|changes)\//;
const baseUrl = (url) => url.split("#")[0];

const THREAD_TYPES = new Set([10, 11, 12]);
const FORUM = 15;
const MAX_DISCORD = 1900;
const HISTORY_CHARS = 8000;
const SUPPRESS_EMBEDS = 1 << 2;
const EPHEMERAL = 1 << 6;
const NEEDS_HUMAN_TAG = "Needs human";
// Role, ktere si clen muze sam prepnout tlacitkem (zalozni varianta k Onboardingu) - nikdy Team
const SELF_ROLES = new Set(["Tester", "Member"]);

// Zjevna zadost o cloveka (bez volani modelu); ostatni pozna model priznakem "handoff"
const HUMAN_RE = /\b((talk|speak|chat) (to|with) (a |an )?(human|person|real person|team member|moderator|admin)|need (a )?(human|real person)|real person|human please)\b|^\s*human\s*[.!?]*\s*$|(chci|potřebuji|potrebuji) (mluvit s |)(člověk|clovek)|s (živým )?(člověkem|clovekem)/i;

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
    this.roles = new Map(); // jmeno role -> id
    this.members = new Map(); // id uzivatele -> {member, at} (cache pro DM)
    this.userAnswers = new Map(); // id uzivatele -> casy odpovedi
    this.notified = new Map(); // klic -> do kdy uz upozorneni neopakovat
    this.active = 0;
    this.waiting = [];
    this.pending = new Set(); // bezici odpovedi (pro testy a cisty konec)
    this.bugReports = mailer && assistant ? new BugReports({ bot: this, rest, assistant, mailer, state, log }) : null;
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
        for (const role of d.roles || []) this.roles.set(role.name, role.id);
        break;
      case "GUILD_ROLE_CREATE": case "GUILD_ROLE_UPDATE":
        if (d.guild_id === this.guildId) {
          for (const [name, id] of this.roles) if (id === d.role.id) this.roles.delete(name);
          this.roles.set(d.role.name, d.role.id);
        }
        break;
      case "GUILD_ROLE_DELETE":
        for (const [name, id] of this.roles) if (id === d.role_id) this.roles.delete(name);
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
    const general = this.findChannel(this.config.channels.general);
    const testing = this.findChannel(this.config.channels.botTesting);

    // #bug-reports: hlaseni se posoudi a preposlou tymu, zadne odpovedi z dokumentace
    const bugs = this.findChannel(this.config.channels.bugs);
    if (bugs && (channel.id === bugs.id || (THREAD_TYPES.has(channel.type) && channel.parent_id === bugs.id))) {
      if (this.bugReports) await this.bugReports.onMessage(msg, channel, channel.id === bugs.id);
      return;
    }

    // #support (nebo #bot-testing) jako textovy kanal: z otazky udelat vlakno a odpovedet v nem
    const parent = this.answerParent(channel.id);
    if (parent && parent.type !== FORUM) {
      const test = Boolean(testing && parent.id === testing.id);
      const name = this.cleanContent(msg.content).replace(/\s+/g, " ").slice(0, 90) || "Question";
      const thread = await this.rest.post(`/channels/${channel.id}/messages/${msg.id}/threads`, { name, auto_archive_duration: 1440 });
      this.cacheChannel({ ...thread, owner_id: msg.author.id });
      this.state.setThread(thread.id, { op: msg.author.id, replies: 0 });
      await this.respond({ msg, channelId: thread.id, threadId: thread.id, title: name, fresh: true, test });
      return;
    }

    const threadParent = THREAD_TYPES.has(channel.type) ? this.answerParent(channel.parent_id) : null;
    if (threadParent) {
      const test = Boolean(testing && threadParent.id === testing.id);
      let info = this.state.thread(channel.id);
      const mention = this.mentioned(msg);
      if (!info) {
        // prvni zprava ve vlakne, ktere bot jeste nezna: prispevek ve foru ma id zpravy = id vlakna
        if (!test && msg.id !== channel.id && channel.owner_id !== msg.author.id && !mention) return;
        info = this.state.setThread(channel.id, { op: channel.owner_id || msg.author.id, replies: 0 });
        await this.respond({ msg, channelId: channel.id, threadId: channel.id, title: channel.name, fresh: msg.id === channel.id, test });
        return;
      }
      // v #bot-testing odpovida kazdemu clenu tymu, v #support jen tazateli (ostatnim po zmince).
      // Kdyz ve vlakne #support odpovedel jiny clovek (pomocnik, tym), bot uz mlci - krome zminky.
      // Stitek "Needs human" bot neumlci: dalsi zodpovezitelna otazka dostane normalni odpoved.
      if (!test && msg.author.id !== info.op) {
        if (!mention) {
          if (!info.humanReplied) this.state.setThread(channel.id, { humanReplied: true });
          return;
        }
      } else if (!test && info.humanReplied && !mention) {
        return;
      }
      await this.respond({ msg, channelId: channel.id, threadId: channel.id, title: channel.name, fresh: false, test });
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
    // jen zminka ("@LuxOS Support", "@LuxOS Support ?"): odpovedet na posledni nezodpovezenou
    // zpravu stejneho autora z poslednich 10 minut v tomto kanalu/vlakne
    if (this.mentionOnly(ctx.msg)) {
      const previous = await this.unanswered(ctx);
      if (!previous) {
        await this.send(ctx.channelId, texts(detectLanguage(ctx.msg.content)).whatToKnow, ctx.replyTo);
        return;
      }
      ctx = { ...ctx, msg: previous, replyTo: ctx.replyTo ? previous.id : undefined, fresh: Boolean(ctx.threadId && previous.id === ctx.threadId && ctx.fresh) };
    }
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
    // pozdrav, dik, "jsi tu?": hned kratka odpoved bez modelu - nikdy predani tymu, e-mail ani stitek
    const short = shortCategory(msg.content);
    if (short) {
      await this.casual(ctx, short, lang);
      return;
    }
    if (HUMAN_RE.test(msg.content) && msg.content.length < 300) {
      await this.handoff(ctx, lang, "user asked for a human", "");
      return;
    }
    // #bot-testing (jen tym) nema limit na uzivatele, denni strop plati
    const limit = ctx.test ? { ok: true } : this.userLimit(msg.author.id);
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
    if (!ctx.test) this.userAnswers.get(msg.author.id).push(Date.now());

    const started = await this.withSlot(async () => {
      this.rest.post(`/channels/${ctx.channelId}/typing`).catch(() => {});
      let question = this.cleanContent(msg.content);
      let truncated = false;
      if (question.length > limits.questionChars) { question = question.slice(0, limits.questionChars); truncated = true; }

      // 1) druh zpravy a tema anglickymi slovy. Pozdrav, dik, smalltalk a temata mimo LuxOS dostanou
      // kratkou odpoved a nikdy nejdou tymu; dal pokracuje jen skutecna otazka.
      let kind;
      try {
        kind = await this.assistant.classify(ctx.title || "", question);
      } catch (error) {
        this.log(`luxai error: ${error.message}`);
        await this.send(ctx.channelId, t.error(mail), ctx.replyTo);
        return;
      }
      if (kind.category !== "QUESTION") {
        await this.casual(ctx, kind.category, lang);
        return;
      }
      const terms = kind.keywords;
      const noTopic = !tokenize(terms).length;
      const passages = this.knowledge ? this.knowledge.search(`${terms} ${ctx.title || ""} ${question}`, 5) : [];

      // 2) slaba shoda s dokumentaci: model se na odpoved vubec nepta, otazka jde tymu
      const match = noTopic ? null : this.matchQuality(terms);
      if (!match) {
        this.log(`no docs match channel=${ctx.channelId}`);
        await this.notFound(ctx, lang, "no good match in the LuxOS documentation", "", passages);
        return;
      }

      const history = await this.history(ctx, question);
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

      // 3) kontrola odpovedi: musi byt jista a citovat aspon jeden z dodanych zdroju, jinak se zahodi
      const cited = passages.some((p) => DOCS_URL_RE.test(p.url) && reply.text.includes(baseUrl(p.url)));
      if (!reply.text || !meta.confident || !cited) {
        const reason = !meta.confident ? "the assistant was not confident" : "the answer cited no documentation link";
        this.log(`answer discarded (${reason}) channel=${ctx.channelId}`);
        await this.notFound(ctx, lang, reason, meta.summary, passages);
        return;
      }
      let text = reply.text;
      if (truncated) text = `${tt.tooLong(limits.questionChars)}\n\n${text}`;
      if (meta.handoff && !ctx.threadId) text += `\n\n${tt.elsewhere(this.supportMention(), mail)}`;
      await this.send(ctx.channelId, text, ctx.replyTo);
      if (ctx.threadId) this.state.setThread(ctx.threadId, { replies: ((this.state.thread(ctx.threadId) || {}).replies || 0) + 1 });
      this.log(`answered channel=${ctx.channelId} passages=${passages.length} handoff=${meta.handoff}`);
      if (meta.handoff && ctx.threadId) {
        await this.handoff(ctx, lang, "the assistant suggests the LuxOS team", meta.summary, false, passages);
      }
    });
    if (!started) await this.send(ctx.channelId, t.busy, ctx.replyTo);
  }

  mentionOnly(msg) {
    if (!this.mentioned(msg) || !/<@!?\d+>/.test(msg.content || "")) return false;
    const rest = this.cleanContent(msg.content).toLowerCase().replace(/[?!.,:;…\s]+/g, " ").trim();
    return rest === "" || /^((pls|please|help|prosim|prosím|pomoc|hey|hi|ahoj|lux)\s*)+$/.test(rest);
  }

  // Posledni zpravy autora (nejvys 3, nejvys 10 minut stare), na ktere bot jeste neodpovedel
  async unanswered(ctx) {
    let messages;
    try {
      messages = await this.rest.get(`/channels/${ctx.channelId}/messages?limit=20`);
    } catch {
      return null;
    }
    const found = [];
    const current = BigInt(ctx.msg.id);
    for (const m of messages) { // od nejnovejsi
      if (BigInt(m.id) >= current) continue;
      if (this.user && m.author.id === this.user.id) break; // po teto zprave uz bot odpovedel
      if (m.timestamp && Date.now() - Date.parse(m.timestamp) > 10 * 60 * 1000) break;
      if (m.author.id !== ctx.msg.author.id || !(m.content || "").trim() || this.mentionOnly(m)) continue;
      found.unshift(m);
      if (found.length >= 3) break;
    }
    if (!found.length) return null;
    const last = found[found.length - 1];
    return { ...last, content: found.map((m) => m.content).join("\n\n") };
  }

  // Pozdrav / smalltalk -> predstaveni, dik -> "rado se stalo", mimo tema -> "jen LuxOS".
  // Zadny e-mail, stitek ani prejmenovani; vlakno zustava otevrene pro dalsi skutecnou otazku.
  async casual(ctx, category, lang) {
    const t = texts(lang);
    const text = category === "THANKS" ? t.thanks : category === "OFFTOPIC" ? t.offTopic : t.greeting;
    await this.send(ctx.channelId, text, ctx.replyTo);
    this.log(`${category.toLowerCase()} reply channel=${ctx.channelId}`);
  }

  // Shoda klicovych slov s dokumentaci (ne s reklamnimi strankami): dost silna a pokryva vetsinu
  // slov dotazu. Slova, ktera v dokumentaci nejsou, pokryti snizuji (recept na gulas -> 0,1).
  matchQuality(terms) {
    if (!this.knowledge) return null;
    const { minScore, minCoverage } = this.config.match;
    return this.knowledge.search(terms, 10).find((p) => DOCS_URL_RE.test(p.url) && p.score >= minScore && p.coverage >= minCoverage) || null;
  }

  // Nejista odpoved / nic v dokumentaci: poctive rict, ze otazka sla tymu, a poslat e-mail.
  // V DM tym odpovedet nemuze: odkaz na #support a e-mail.
  async notFound(ctx, lang, reason, summary, passages) {
    const t = texts(lang);
    if (ctx.dm) {
      await this.send(ctx.channelId, t.notFoundDm(this.supportMention(), this.config.contactMail));
      return;
    }
    const key = ctx.threadId || `msg:${ctx.msg.id}`;
    if ((this.state.thread(key) || {}).escalated) {
      await this.send(ctx.channelId, t.handoffAlready(this.config.contactMail), ctx.replyTo);
      return;
    }
    await this.send(ctx.channelId, t.notFound, ctx.replyTo);
    await this.escalate(ctx, reason, summary, passages);
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

  // Kanal, kde bot odpovida na kazdou otazku: #support, nebo tymovy #bot-testing
  answerParent(id) {
    if (!id) return null;
    for (const name of [this.config.channels.support, this.config.channels.botTesting]) {
      const channel = this.findChannel(name);
      if (channel && channel.id === id) return channel;
    }
    return null;
  }

  supportMention() {
    const support = this.findChannel(this.config.channels.support);
    return support ? `<#${support.id}>` : "#support";
  }

  // Zprava pro uzivatele + oznaceni vlakna + e-mail; mimo vlakno #support jen odkaz kam se obratit
  async handoff(ctx, lang, reason, summary, notConfident = false, passages = []) {
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
    await this.escalate(ctx, reason, summary, passages);
  }

  // Jeden e-mail na vlakno (mimo vlakno, napr. #general, na zpravu) + stitek "Needs human"
  async escalate(ctx, reason, summary, passages = []) {
    const key = ctx.threadId || `msg:${ctx.msg.id}`;
    const info = this.state.thread(key) || {};
    if (info.escalated) return;
    this.state.setThread(key, { escalated: true });
    const thread = ctx.threadId ? await this.channel(ctx.threadId) : null;
    if (thread) {
      try {
        await this.tagNeedsHuman(thread);
      } catch (error) {
        this.log(`tagging failed thread=${ctx.threadId}: ${error.message}`);
      }
    }
    if (!this.mailer) return;
    try {
      const sent = await this.mailer.escalate({
        title: (thread && thread.name) || ctx.title || this.cleanContent(ctx.msg.content).replace(/\s+/g, " ").slice(0, 80) || "Discord question",
        link: ctx.threadId ? `https://discord.com/channels/${this.guildId}/${ctx.threadId}`
          : `https://discord.com/channels/${this.guildId}/${ctx.channelId}/${ctx.msg.id}`,
        passages: passages.map((p) => ({ title: p.title, url: p.url })),
        author: ctx.msg.author.global_name ? `${ctx.msg.author.global_name} (@${ctx.msg.author.username})` : `@${ctx.msg.author.username}`,
        reason,
        summary,
        test: Boolean(ctx.test),
        question: this.cleanContent(ctx.msg.content).slice(0, 600)
      });
      this.log(sent ? `escalation mail sent ${key}` : `escalation mail skipped (rate limit) ${key}`);
    } catch (error) {
      this.log(`escalation mail failed ${key}: ${error.message}`);
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
    if (interaction.type === 3 && interaction.data && /^role:/.test(interaction.data.custom_id || "")) {
      await this.onRoleButton(interaction);
      return;
    }
    if (interaction.type !== 2 || !interaction.data || interaction.data.name !== "human") return;
    const user = (interaction.member && interaction.member.user) || interaction.user;
    const locale = String(interaction.locale || "en");
    const lang = locale.startsWith("cs") || locale.startsWith("sk") ? "cs" : "en";
    const t = texts(lang);
    const mail = this.config.contactMail;
    const channel = interaction.guild_id === this.guildId ? await this.channel(interaction.channel_id) : null;
    const parent = channel && THREAD_TYPES.has(channel.type) ? this.answerParent(channel.parent_id) : null;
    const testing = this.findChannel(this.config.channels.botTesting);
    const reply = (content, ephemeral) => this.rest.post(`/interactions/${interaction.id}/${interaction.token}/callback`, {
      type: 4, data: { content, flags: (ephemeral ? EPHEMERAL : 0) | SUPPRESS_EMBEDS, allowed_mentions: { parse: [] } }
    });
    if (!parent) {
      await reply(t.elsewhere(this.supportMention(), mail), true);
      return;
    }
    const info = this.state.thread(channel.id) || this.state.setThread(channel.id, { op: channel.owner_id || user.id, replies: 0 });
    if (info.escalated) { await reply(t.handoffAlready(mail), false); return; }
    await reply(t.handoff(mail), false);
    const msg = { author: user, content: `/human in "${channel.name}"` };
    const test = Boolean(testing && parent.id === testing.id);
    await this.escalate({ msg, channelId: channel.id, threadId: channel.id, title: channel.name, test }, "user used /human", "");
  }

  // Tlacitko "role:Tester" / "role:Member" ve zprave v #welcome-and-rules: prepne roli, odpoved vidi jen klikajici
  async onRoleButton(interaction) {
    const name = interaction.data.custom_id.slice(5);
    const member = interaction.member;
    const lang = String(interaction.locale || "en").startsWith("cs") ? "cs" : "en";
    const t = texts(lang);
    const reply = (content) => this.rest.post(`/interactions/${interaction.id}/${interaction.token}/callback`, {
      type: 4, data: { content, flags: EPHEMERAL, allowed_mentions: { parse: [] } }
    });
    const roleId = this.roles.get(name);
    if (!SELF_ROLES.has(name) || !roleId || !member || interaction.guild_id !== this.guildId) {
      await reply(t.roleError);
      return;
    }
    const has = (member.roles || []).includes(roleId);
    const path = `/guilds/${this.guildId}/members/${member.user.id}/roles/${roleId}`;
    try {
      if (has) await this.rest.delete(path, { reason: "self-assigned role button" });
      else await this.rest.put(path, undefined, { reason: "self-assigned role button" });
    } catch (error) {
      this.log(`role button failed: ${error.message}`);
      await reply(t.roleError);
      return;
    }
    this.log(`role ${name} ${has ? "removed" : "added"}`);
    await reply(has ? t.roleRemoved(name) : t.roleAdded(name));
  }
}

module.exports = { Bot, splitMessage, HUMAN_RE, SECRET_RE };
