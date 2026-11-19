"use strict";
// Oznameni: kazdych 15 minut stahne https://luxos.lux-ai.cz/announcements.json (stejny kanal jako
// aplikace Novinky LuxOS) a release.json a nove polozky jednou zverejni v #announcements.
// Co uz bylo zverejneno, je ve stavovem souboru (id oznameni, posledni verze).

const MAX_BYTES = 256 * 1024;
const FIRST_RUN_MAX_AGE_DAYS = 14;
const MAX_PER_POLL = 3;
const ID_RE = /^[a-z0-9-]{1,64}$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function localized(value) {
  if (typeof value === "string") return value;
  if (value && typeof value === "object") return typeof value.en === "string" ? value.en : Object.values(value).find((v) => typeof v === "string") || "";
  return "";
}

function validItem(item) {
  if (!item || typeof item !== "object" || !ID_RE.test(item.id || "") || !DATE_RE.test(item.date || "")) return false;
  if (item.until !== undefined && !DATE_RE.test(item.until)) return false;
  const title = localized(item.title);
  if (!title || title.length > 120) return false;
  if (item.url !== undefined && (typeof item.url !== "string" || !/^https:\/\/\S+$/.test(item.url) || item.url.length > 300)) return false;
  return localized(item.body).length <= 2000;
}

function newerVersion(a, b) {
  const pa = String(a).split(".").map(Number);
  const pb = String(b).split(".").map(Number);
  for (let i = 0; i < 3; i++) if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) > (pb[i] || 0);
  return false;
}

async function fetchJson(url) {
  const response = await fetch(url, { signal: AbortSignal.timeout(15_000), headers: { "User-Agent": "luxos-discord-bot" } });
  if (!response.ok) throw new Error(`${url} -> HTTP ${response.status}`);
  const text = await response.text();
  if (text.length > MAX_BYTES) throw new Error(`${url} is larger than ${MAX_BYTES} bytes`);
  return JSON.parse(text);
}

class Announcer {
  constructor({ config, rest, state, bot, log = console.log }) {
    Object.assign(this, { config, rest, state, bot, log });
    this.timer = null;
  }

  start() {
    if (!this.config.announce.intervalMs) return;
    const run = () => this.poll().catch((error) => this.log(`announcements: ${error.message}`));
    setTimeout(run, 30_000);
    this.timer = setInterval(run, this.config.announce.intervalMs);
  }

  stop() { clearInterval(this.timer); }

  async post(channel, content) {
    const message = await this.rest.post(`/channels/${channel.id}/messages`, {
      content: content.slice(0, 2000), allowed_mentions: { parse: [] }
    });
    // kanal typu Announcement: zverejnit i na serverech, ktere ho sleduji
    if (channel.type === 5) await this.rest.post(`/channels/${channel.id}/messages/${message.id}/crosspost`).catch(() => {});
  }

  async poll(now = new Date()) {
    const channel = this.bot.findChannel(this.config.channels.announcements);
    if (!channel) return 0;
    const st = this.state.data.announcements;
    const firstRun = !st.initialized;
    const today = now.toISOString().slice(0, 10);
    const oldest = new Date(now.getTime() - FIRST_RUN_MAX_AGE_DAYS * 86400_000).toISOString().slice(0, 10);
    let posted = 0;
    const titles = [];

    const data = await fetchJson(this.config.announce.url);
    if (!data || data.version !== 1 || !Array.isArray(data.announcements)) throw new Error("announcements.json has an unknown format");
    const items = data.announcements.slice(0, 50).filter(validItem).sort((a, b) => a.date.localeCompare(b.date));
    for (const item of items) {
      titles.push(localized(item.title));
      if (st.seen.includes(item.id) || item.date > today) continue; // budouci datum = pozdeji
      if ((item.until && item.until < today) || (firstRun && item.date < oldest)) {
        st.seen.push(item.id);
        continue;
      }
      if (posted >= MAX_PER_POLL) break;
      const body = localized(item.body);
      await this.post(channel, [`**${localized(item.title)}**`, body, item.url ? `<${item.url}>` : ""].filter(Boolean).join("\n"));
      st.seen.push(item.id);
      posted += 1;
      this.state.save();
    }

    if (this.config.announce.releases) {
      try {
        const release = await fetchJson(this.config.announce.releaseUrl);
        const version = typeof release.version === "string" && /^\d+\.\d+\.\d+$/.test(release.version) ? release.version : "";
        if (version && !st.release) {
          st.release = version; // prvni beh: aktualni verzi jen zapamatovat
        } else if (version && newerVersion(version, st.release)) {
          // vydani uz ohlasene v announcements.json neopakovat
          if (!titles.some((title) => title.includes(version))) {
            const codename = typeof release.codename === "string" ? ` “${release.codename.slice(0, 40)}”` : "";
            await this.post(channel, `**LuxOS ${version}${codename} is out**\nUpdate with Software Update or \`lux update\`. What's new: <${this.config.announce.changesUrl}>`);
            posted += 1;
          }
          st.release = version;
        }
      } catch (error) {
        this.log(`release.json: ${error.message}`);
      }
    }
    st.initialized = true;
    this.state.save();
    if (posted) this.log(`announcements: posted ${posted}`);
    return posted;
  }
}

module.exports = { Announcer, validItem };
