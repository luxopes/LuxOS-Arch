"use strict";
// Falesny Discord (REST + Gateway), lux-api, SMTP a web pro testy. Vse jen na 127.0.0.1.

const http = require("http");
const net = require("net");
const { WebSocketServer } = require("ws");

let nextId = 100000000000000000n;
const snowflake = () => String(nextId++);

function listen(server) {
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server.address().port)));
}

function readBody(req) {
  return new Promise((resolve) => {
    let data = "";
    req.on("data", (chunk) => { data += chunk; });
    req.on("end", () => { try { resolve(data ? JSON.parse(data) : undefined); } catch { resolve(undefined); } });
  });
}

async function waitFor(fn, timeout = 3000, what = "condition") {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const value = await fn();
    if (value) return value;
    await new Promise((r) => setTimeout(r, 10));
  }
  throw new Error(`timed out waiting for ${what}`);
}

class FakeDiscord {
  constructor({ community = false, token = "test-token" } = {}) {
    this.token = token;
    this.bot = { id: snowflake(), username: "LuxOS Support", bot: true };
    this.appId = this.bot.id;
    this.guild = {
      id: snowflake(), name: "LuxOS", features: community ? ["COMMUNITY"] : [], verification_level: 0,
      explicit_content_filter: 0, default_message_notifications: 0, rules_channel_id: null, public_updates_channel_id: null
    };
    this.roles = [{ id: this.guild.id, name: "@everyone", permissions: "1071698660929", color: 0, hoist: false, mentionable: false, managed: false },
      { id: snowflake(), name: "LuxOS Support", permissions: "8", color: 0, hoist: false, mentionable: false, managed: true }];
    this.channels = [];
    this.messages = new Map(); // channel id -> [message] (od nejstarsi)
    this.invites = [];
    this.commands = [];
    this.screening = { enabled: false, description: null, form_fields: [] };
    this.members = new Set();
    this.requests = [];
    this.interactionReplies = [];
    this.failOnce = new Map(); // "METHOD /path" -> {status, body}
    this.sockets = new Set();
    this.identifies = 0;
    this.resumes = 0;
  }

  async start() {
    this.server = http.createServer((req, res) => this.handle(req, res));
    this.port = await listen(this.server);
    this.wss = new WebSocketServer({ server: this.server });
    this.wss.on("connection", (ws) => this.onSocket(ws));
    return this;
  }

  get api() { return `http://127.0.0.1:${this.port}/api`; }

  stop() {
    for (const ws of this.sockets) ws.terminate();
    this.wss.close();
    this.server.closeAllConnections();
    return new Promise((r) => this.server.close(r));
  }

  // ---- gateway ----

  onSocket(ws) {
    this.sockets.add(ws);
    ws.on("close", () => this.sockets.delete(ws));
    ws.send(JSON.stringify({ op: 10, d: { heartbeat_interval: 30000 } }));
    ws.seq = 0;
    ws.on("message", (raw) => {
      const { op, d } = JSON.parse(raw.toString());
      if (op === 1) ws.send(JSON.stringify({ op: 11 }));
      if (op === 2) {
        this.identifies += 1;
        this.lastIdentify = d;
        if (d.token !== this.token) { ws.close(4004); return; }
        this.sendTo(ws, "READY", { v: 10, user: this.bot, session_id: "s1", resume_gateway_url: `ws://127.0.0.1:${this.port}`, guilds: [{ id: this.guild.id, unavailable: true }] });
        this.sendTo(ws, "GUILD_CREATE", { ...this.guild, channels: this.channels.filter((c) => c.type < 10 || c.type > 12), threads: this.channels.filter((c) => c.type >= 10 && c.type <= 12) });
      }
      if (op === 6) {
        this.resumes += 1;
        this.sendTo(ws, "RESUMED", {});
      }
    });
  }

  sendTo(ws, t, d) {
    ws.seq += 1;
    ws.send(JSON.stringify({ op: 0, t, s: ws.seq, d }));
  }

  dispatch(t, d) {
    for (const ws of this.sockets) this.sendTo(ws, t, d);
  }

  // ---- model serveru ----

  addChannel(fields) {
    const channel = { id: snowflake(), guild_id: this.guild.id, permission_overwrites: [], topic: null, parent_id: null, ...fields };
    this.channels.push(channel);
    return channel;
  }

  channel(name) { return this.channels.find((c) => c.name === name); }

  addMessage(channelId, author, content, extra = {}) {
    const message = { id: extra.id || snowflake(), channel_id: channelId, author, content, type: 0, mentions: [], mention_everyone: false, ...extra };
    if (!this.messages.has(channelId)) this.messages.set(channelId, []);
    this.messages.get(channelId).push(message);
    return message;
  }

  posted(channelId) { return (this.messages.get(channelId) || []).filter((m) => m.author.id === this.bot.id); }

  mutations() { return this.requests.filter((r) => r.method !== "GET"); }

  // Uzivatel posle zpravu: ulozit a poslat MESSAGE_CREATE pres gateway
  userMessage(channelId, user, content, extra = {}) {
    const channel = this.channels.find((c) => c.id === channelId);
    const message = this.addMessage(channelId, user, content, extra);
    this.dispatch("MESSAGE_CREATE", { ...message, guild_id: channel ? this.guild.id : undefined });
    return message;
  }

  // Novy prispevek ve foru: THREAD_CREATE + prvni zprava se stejnym id
  forumPost(forumId, user, title, content) {
    const thread = this.addChannel({ name: title, type: 11, parent_id: forumId, owner_id: user.id, applied_tags: [] });
    this.dispatch("THREAD_CREATE", { ...thread, newly_created: true });
    this.userMessage(thread.id, user, content, { id: thread.id });
    return thread;
  }

  // ---- REST ----

  async handle(req, res) {
    const url = new URL(req.url, "http://x");
    const path = url.pathname.replace(/^\/api/, "");
    const body = await readBody(req);
    this.requests.push({ method: req.method, path, query: url.search, body });
    const send = (status, data, headers = {}) => {
      res.writeHead(status, { "Content-Type": "application/json", ...headers });
      res.end(data === undefined ? "" : JSON.stringify(data));
    };
    if (req.headers.authorization !== `Bot ${this.token}`) return send(401, { message: "401: Unauthorized", code: 0 });
    const failure = this.failOnce.get(`${req.method} ${path}`);
    if (failure) {
      this.failOnce.delete(`${req.method} ${path}`);
      return send(failure.status, failure.body, failure.headers);
    }
    try {
      const out = this.route(req.method, path, body, url);
      if (out === null) return send(404, { message: "Unknown", code: 10003 });
      if (out && out.status) return send(out.status, out.body);
      return out === undefined ? send(204) : send(200, out);
    } catch (error) {
      return send(500, { message: error.message });
    }
  }

  route(method, path, body, url) {
    const g = this.guild.id;
    let m;
    if (method === "GET" && path === "/gateway/bot") return { url: `ws://127.0.0.1:${this.port}`, shards: 1 };
    if (method === "GET" && path === "/users/@me") return this.bot;
    if (method === "GET" && path === "/users/@me/guilds") return [{ id: g, name: this.guild.name }];
    if (method === "GET" && path === "/oauth2/applications/@me") return { id: this.appId, name: "LuxOS Support" };
    if (path === `/guilds/${g}`) {
      if (method === "GET") return this.guild;
      if (method === "PATCH") {
        if (body.features && body.features.includes("COMMUNITY") && !this.guild.features.includes("COMMUNITY")) {
          if (!body.rules_channel_id || !body.public_updates_channel_id) return { status: 400, body: { code: 50035 } };
        }
        Object.assign(this.guild, body);
        return this.guild;
      }
    }
    if (path === `/guilds/${g}/roles`) {
      if (method === "GET") return this.roles;
      if (method === "POST") { const role = { id: snowflake(), managed: false, ...body }; this.roles.push(role); return role; }
    }
    if ((m = /^\/guilds\/\d+\/roles\/(\d+)$/.exec(path)) && method === "PATCH") {
      const role = this.roles.find((r) => r.id === m[1]);
      Object.assign(role, body);
      return role;
    }
    if (path === `/guilds/${g}/channels`) {
      if (method === "GET") return this.channels.filter((c) => c.type < 10 || c.type > 12);
      if (method === "POST") {
        if ((body.type === 15 || body.type === 5) && !this.guild.features.includes("COMMUNITY")) return { status: 400, body: { code: 50024 } };
        const tags = (body.available_tags || []).map((t) => ({ id: snowflake(), emoji_id: null, emoji_name: null, ...t }));
        const { permission_overwrites: ow = [], ...rest } = body;
        return this.addChannel({ ...rest, available_tags: body.type === 15 ? tags : undefined, permission_overwrites: ow, parent_id: body.parent_id || null, topic: body.topic ?? null });
      }
    }
    if ((m = /^\/guilds\/\d+\/members\/(\d+)$/.exec(path)) && method === "GET") {
      return this.members.has(m[1]) ? { user: { id: m[1] } } : null;
    }
    if (path === `/guilds/${g}/invites` && method === "GET") return this.invites;
    if (path === `/guilds/${g}/member-verification` && method === "GET") return this.screening;
    if (path === `/guilds/${g}/member-verification` && method === "PATCH") { Object.assign(this.screening, body); return this.screening; }
    if ((m = /^\/applications\/(\d+)\/guilds\/(\d+)\/commands$/.exec(path))) {
      if (method === "GET") return this.commands;
      if (method === "PUT") { this.commands = body.map((c) => ({ id: snowflake(), application_id: this.appId, ...c })); return this.commands; }
    }
    if ((m = /^\/interactions\/(\d+)\/([^/]+)\/callback$/.exec(path)) && method === "POST") {
      this.interactionReplies.push(body);
      return undefined;
    }
    if ((m = /^\/channels\/(\d+)$/.exec(path))) {
      const channel = this.channels.find((c) => c.id === m[1]);
      if (!channel) return null;
      if (method === "GET") return channel;
      if (method === "PATCH") {
        if (body.type === 5 && !this.guild.features.includes("COMMUNITY")) return { status: 400, body: { code: 50024 } };
        if (body.available_tags) body.available_tags = body.available_tags.map((t) => ({ id: t.id || snowflake(), ...t }));
        Object.assign(channel, body);
        return channel;
      }
    }
    if ((m = /^\/channels\/(\d+)\/messages$/.exec(path))) {
      if (method === "GET") {
        const limit = Number(url.searchParams.get("limit") || 50);
        return [...(this.messages.get(m[1]) || [])].reverse().slice(0, limit);
      }
      if (method === "POST") {
        if (body.content.length > 2000) return { status: 400, body: { code: 50035 } };
        return this.addMessage(m[1], this.bot, body.content, { flags: body.flags, message_reference: body.message_reference, allowed_mentions: body.allowed_mentions });
      }
    }
    if ((m = /^\/channels\/(\d+)\/messages\/(\d+)$/.exec(path)) && method === "PATCH") {
      const message = (this.messages.get(m[1]) || []).find((x) => x.id === m[2]);
      Object.assign(message, { content: body.content });
      return message;
    }
    if ((m = /^\/channels\/(\d+)\/messages\/(\d+)\/crosspost$/.exec(path)) && method === "POST") return {};
    if ((m = /^\/channels\/(\d+)\/messages\/(\d+)\/threads$/.exec(path)) && method === "POST") {
      const thread = this.addChannel({ name: body.name, type: 11, parent_id: m[1], owner_id: this.bot.id });
      return thread;
    }
    if ((m = /^\/channels\/(\d+)\/typing$/.exec(path)) && method === "POST") return undefined;
    if ((m = /^\/channels\/(\d+)\/invites$/.exec(path)) && method === "POST") {
      const invite = { code: `luxos${this.invites.length}`, channel: { id: m[1] }, max_age: body.max_age, max_uses: body.max_uses, temporary: body.temporary, inviter: this.bot };
      this.invites.push(invite);
      return invite;
    }
    return { status: 404, body: { message: `fake: no route ${method} ${path}` } };
  }
}

// Falesny lux-api: /v1/chat/completions, kontroluje klic; odpoved urcuje funkce reply(body)
class FakeLuxApi {
  constructor(key) {
    this.key = key;
    this.requests = [];
    this.reply = () => "An answer.\nMETA {\"confident\": true, \"handoff\": false, \"lang\": \"en\", \"summary\": \"x\"}";
  }

  async start() {
    this.server = http.createServer(async (req, res) => {
      const body = await readBody(req);
      if (req.url !== "/v1/chat/completions" || req.method !== "POST") { res.writeHead(404); res.end(); return; }
      if (req.headers.authorization !== `Bearer ${this.key}`) {
        res.writeHead(401, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: { code: "auth" } }));
        return;
      }
      this.requests.push(body);
      const content = this.reply(body);
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ id: "x", object: "chat.completion", choices: [{ index: 0, message: { role: "assistant", content }, finish_reason: "stop" }] }));
    });
    this.port = await listen(this.server);
    return this;
  }

  get url() { return `http://127.0.0.1:${this.port}/v1/chat/completions`; }
  stop() { this.server.closeAllConnections(); return new Promise((r) => this.server.close(r)); }
}

// Falesny SMTP server (bez TLS): uklada prijate zpravy
class FakeSmtp {
  constructor() { this.mails = []; }

  async start() {
    this.server = net.createServer((socket) => {
      let buffer = "";
      let inData = false;
      let mail = { from: "", to: [], data: "" };
      socket.write("220 fake ESMTP\r\n");
      socket.on("data", (chunk) => {
        buffer += chunk.toString();
        let index;
        while ((index = buffer.indexOf("\r\n")) >= 0) {
          const line = buffer.slice(0, index);
          buffer = buffer.slice(index + 2);
          if (inData) {
            if (line === ".") {
              inData = false;
              mail.data = mail.data.replace(/=\n/g, "").replace(/=([0-9A-F]{2})/g, (_, h) => String.fromCharCode(parseInt(h, 16)));
              this.mails.push(mail);
              mail = { from: "", to: [], data: "" };
              socket.write("250 queued\r\n");
            } else mail.data += line.replace(/^\./, "") + "\n";
            continue;
          }
          const cmd = line.slice(0, 4).toUpperCase();
          if (cmd === "EHLO" || cmd === "HELO") socket.write("250-fake\r\n250 8BITMIME\r\n");
          else if (cmd === "MAIL") { mail.from = line; socket.write("250 ok\r\n"); }
          else if (cmd === "RCPT") { mail.to.push(line); socket.write("250 ok\r\n"); }
          else if (cmd === "DATA") { inData = true; socket.write("354 go\r\n"); }
          else if (cmd === "QUIT") { socket.end("221 bye\r\n"); }
          else socket.write("250 ok\r\n");
        }
      });
      socket.on("error", () => {});
    });
    this.port = await listen(this.server);
    return this;
  }

  stop() { return new Promise((r) => this.server.close(r)); }
}

// Falesny web luxos.lux-ai.cz: announcements.json a release.json
class FakeSite {
  constructor() {
    this.announcements = { version: 1, announcements: [] };
    this.release = { version: "1.0.3", codename: "Sirius" };
    this.hits = 0;
  }

  async start() {
    this.server = http.createServer((req, res) => {
      this.hits += 1;
      const data = req.url === "/announcements.json" ? this.announcements : req.url === "/release.json" ? this.release : null;
      if (!data) { res.writeHead(404); res.end(); return; }
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(data));
    });
    this.port = await listen(this.server);
    return this;
  }

  url(name) { return `http://127.0.0.1:${this.port}/${name}`; }
  stop() { this.server.closeAllConnections(); return new Promise((r) => this.server.close(r)); }
}

module.exports = { FakeDiscord, FakeLuxApi, FakeSmtp, FakeSite, waitFor, snowflake };
