"use strict";
// Minimalni klient Discord Gateway (v10, JSON, bez komprese): heartbeat, identify, resume,
// znovupripojeni s narustajici prodlevou. Udalosti (op 0) vydava jako EventEmitter("dispatch").

const { EventEmitter } = require("events");
const WebSocket = require("ws");

// Kody zavreni, po kterych nema smysl se pripojovat znovu (spatny token, nepovolene intenty...)
const FATAL_CLOSE = new Set([4004, 4010, 4011, 4012, 4013, 4014]);
// Po techto kodech uz session nejde obnovit, je nutny novy identify
const NO_RESUME_CLOSE = new Set([4007, 4009]);

class Gateway extends EventEmitter {
  constructor({ rest, token, intents, maxBackoffMs = 60_000 }) {
    super();
    this.rest = rest;
    this.token = token;
    this.intents = intents;
    this.maxBackoffMs = maxBackoffMs;
    this.ws = null;
    this.seq = null;
    this.sessionId = null;
    this.resumeUrl = null;
    this.gatewayUrl = null;
    this.heartbeatTimer = null;
    this.firstBeat = null;
    this.ackPending = false;
    this.failures = 0;
    this.stopped = false;
  }

  async connect() {
    if (this.stopped) return;
    try {
      if (!this.gatewayUrl) {
        const info = await this.rest.get("/gateway/bot");
        this.gatewayUrl = info.url;
      }
    } catch (error) {
      if (error.status === 401) { this.emit("fatal", new Error("Discord rejected the bot token (401)")); return; }
      this.scheduleReconnect();
      return;
    }
    const base = this.sessionId && this.resumeUrl ? this.resumeUrl : this.gatewayUrl;
    const ws = new WebSocket(`${base.replace(/\/$/, "")}/?v=10&encoding=json`, { maxPayload: 16 * 1024 * 1024 });
    this.ws = ws;
    ws.on("message", (raw) => {
      let packet;
      try { packet = JSON.parse(raw.toString()); } catch { return; }
      this.onPacket(packet);
    });
    ws.on("close", (code) => this.onClose(ws, code));
    ws.on("error", () => {}); // nasleduje close
  }

  send(op, d) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ op, d }));
  }

  onPacket({ op, d, s, t }) {
    if (s !== null && s !== undefined) this.seq = s;
    switch (op) {
      case 10: // HELLO
        this.startHeartbeat(d.heartbeat_interval);
        if (this.sessionId && this.seq !== null) {
          this.send(6, { token: this.token, session_id: this.sessionId, seq: this.seq });
        } else {
          this.send(2, {
            token: this.token,
            intents: this.intents,
            properties: { os: "linux", browser: "luxos-discord-bot", device: "luxos-discord-bot" }
          });
        }
        break;
      case 11: this.ackPending = false; break;
      case 1: this.send(1, this.seq); break;
      case 7: this.reconnect(true); break; // server chce znovupripojeni
      case 9: // neplatna session; d = jde obnovit
        if (!d) { this.sessionId = null; this.seq = null; }
        setTimeout(() => this.reconnect(Boolean(d)), 1000 + Math.random() * 4000);
        break;
      case 0:
        if (t === "READY") {
          this.sessionId = d.session_id;
          this.resumeUrl = d.resume_gateway_url;
          this.failures = 0;
        } else if (t === "RESUMED") {
          this.failures = 0;
        }
        this.emit("dispatch", t, d);
        break;
      default: break;
    }
  }

  startHeartbeat(interval) {
    clearInterval(this.heartbeatTimer);
    clearTimeout(this.firstBeat);
    this.ackPending = false;
    const beat = () => {
      // bez ACK na predchozi heartbeat je spojeni mrtve ("zombie") - zavrit a obnovit
      if (this.ackPending) { this.reconnect(true); return; }
      this.ackPending = true;
      this.send(1, this.seq);
    };
    this.firstBeat = setTimeout(beat, Math.floor(interval * Math.random()));
    this.heartbeatTimer = setInterval(beat, interval);
  }

  reconnect(resume) {
    if (!resume) { this.sessionId = null; this.seq = null; }
    const ws = this.ws;
    if (ws) ws.close(resume ? 4900 : 1000);
    else this.scheduleReconnect();
  }

  onClose(ws, code) {
    if (ws !== this.ws) return;
    this.ws = null;
    clearInterval(this.heartbeatTimer);
    clearTimeout(this.firstBeat);
    if (this.stopped) return;
    if (FATAL_CLOSE.has(code)) {
      this.emit("fatal", new Error(`Discord gateway closed with fatal code ${code}`));
      return;
    }
    if (NO_RESUME_CLOSE.has(code)) { this.sessionId = null; this.seq = null; }
    this.scheduleReconnect();
  }

  scheduleReconnect() {
    if (this.stopped) return;
    const delay = Math.min(this.maxBackoffMs, 1000 * 2 ** Math.min(this.failures, 6)) * (0.5 + Math.random() / 2);
    this.failures += 1;
    setTimeout(() => this.connect(), delay);
  }

  close() {
    this.stopped = true;
    clearInterval(this.heartbeatTimer);
    clearTimeout(this.firstBeat);
    if (this.ws) this.ws.close(1000);
  }
}

module.exports = { Gateway };
