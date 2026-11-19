"use strict";
// Trvaly stav bota v jednom JSON souboru (StateDirectory): denni pocitadla, vlakna (kdo se ptal,
// kolik odpovedi, zda uz odesel e-mail), odeslane maily a uz zverejnena oznameni.
// Obsah zprav se sem neuklada.

const fs = require("fs");
const path = require("path");

const THREAD_TTL_MS = 30 * 24 * 3600 * 1000;

class State {
  constructor(file) {
    this.file = file;
    this.data = { version: 1, day: "", answersToday: 0, threads: {}, mails: [], announcements: { seen: [], release: "" } };
    this.timer = null;
    try {
      const loaded = JSON.parse(fs.readFileSync(file, "utf8"));
      if (loaded && loaded.version === 1) this.data = { ...this.data, ...loaded };
    } catch (error) {
      if (error.code !== "ENOENT") console.error(`state: ${path.basename(file)} unreadable (${error.message}), starting fresh`);
    }
  }

  thread(id) {
    return this.data.threads[id];
  }

  setThread(id, values) {
    this.data.threads[id] = { ...(this.data.threads[id] || {}), ...values, at: Date.now() };
    this.save();
    return this.data.threads[id];
  }

  // Denni strop odpovedi (UTC den)
  takeDailyAnswer(cap) {
    const today = new Date().toISOString().slice(0, 10);
    if (this.data.day !== today) { this.data.day = today; this.data.answersToday = 0; }
    if (this.data.answersToday >= cap) return false;
    this.data.answersToday += 1;
    this.save();
    return true;
  }

  prune() {
    const now = Date.now();
    for (const [id, thread] of Object.entries(this.data.threads)) {
      if (now - (thread.at || 0) > THREAD_TTL_MS) delete this.data.threads[id];
    }
    this.data.mails = this.data.mails.filter((t) => now - t < 24 * 3600 * 1000);
    if (this.data.bugMails) this.data.bugMails = this.data.bugMails.filter((t) => now - t < 24 * 3600 * 1000);
    this.data.announcements.seen = this.data.announcements.seen.slice(-500);
  }

  save() {
    if (this.timer) return;
    this.timer = setTimeout(() => { this.timer = null; this.flush(); }, 200);
  }

  flush() {
    if (this.timer) { clearTimeout(this.timer); this.timer = null; }
    this.prune();
    fs.mkdirSync(path.dirname(this.file), { recursive: true, mode: 0o700 });
    const tmp = `${this.file}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(this.data), { mode: 0o600 });
    fs.renameSync(tmp, this.file);
  }
}

module.exports = { State };
