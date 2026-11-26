const historyLimit = 400;
const resultLimit = 6;

function fold(text) {
  return text.normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase().trim().replace(/\s+/g, ' ');
}

function displayAddress(value) {
  return value.replace(/^https?:\/\/(www\.)?/i, '').replace(/\/$/, '');
}

function historyEntry(value, title = '') {
  try {
    const url = new URL(value);
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return null;
    const host = url.hostname.replace(/^www\./, '');
    const searchPage = (host === 'duckduckgo.com' && url.pathname === '/') ||
      (['google.com', 'google.cz', 'search.seznam.cz'].includes(host) && url.pathname === '/search') ||
      (host === 'search.seznam.cz' && url.pathname === '/');
    const query = searchPage ? url.searchParams.get('q')?.trim() : '';
    if (query && query.length <= 512) return { kind: 'search', value: query, title: '' };
    // Callback URLs can contain one-time authentication credentials.
    if ([...url.searchParams.keys()].some(key => /^(code|state|session|access_token|id_token|refresh_token|token|password|samlresponse)$/i.test(key))) {
      return null;
    }
    url.hash = '';
    if (url.href.length > 2048) return null;
    return { kind: 'page', value: url.href, title: String(title).slice(0, 300) };
  } catch {
    return null;
  }
}

function keyFor(entry) {
  return entry.kind === 'search' ? 'search:' + fold(entry.value) : entry.value;
}

class History {
  constructor(saved, openTabs) {
    this.entries = new Map();
    if (!Array.isArray(saved)) {
      for (const url of openTabs) this.record(url);
      return;
    }
    for (const item of saved.slice(0, historyLimit)) {
      if (!item || typeof item.value !== 'string') continue;
      const entry = item.kind === 'search' && item.value.trim() && item.value.length <= 512
        ? { kind: 'search', value: item.value, title: '' }
        : historyEntry(item.value, item.title);
      if (!entry) continue;
      entry.visits = Number.isFinite(item.visits) ? Math.max(1, Math.min(1000, item.visits)) : 1;
      entry.last = Number.isFinite(item.last) ? item.last : 0;
      this.entries.set(keyFor(entry), entry);
    }
  }

  record(url, title) {
    const entry = historyEntry(url, title);
    if (!entry) return '';
    const key = keyFor(entry);
    const previous = this.entries.get(key);
    entry.title ||= previous?.title ?? '';
    entry.visits = Math.min(1000, (previous?.visits ?? 0) + 1);
    entry.last = Date.now();
    this.entries.delete(key);
    this.entries.set(key, entry);
    if (this.entries.size > historyLimit) this.entries.delete(this.entries.keys().next().value);
    return key;
  }

  updateTitle(key, title) {
    const entry = this.entries.get(key);
    if (!entry || entry.kind !== 'page' || !title || entry.title === title) return;
    entry.title = title.slice(0, 300);
    return true;
  }

  suggestions(input) {
    const query = fold(input).replace(/^https?:\/\/(www\.)?/, '');
    const tokens = query ? query.split(' ') : [];
    const now = Date.now();
    const results = [];
    for (const entry of this.entries.values()) {
      const address = entry.kind === 'page' ? displayAddress(entry.value) : entry.value;
      const value = fold(address);
      const title = fold(entry.title);
      let match = 0;
      if (query) {
        if (value === query) match = 30;
        else if (value.startsWith(query)) match = 20;
        else if (title.startsWith(query)) match = 15;
        else if (tokens.every(token => value.includes(token) || title.includes(token))) match = 8;
        else continue;
      }
      const days = Math.max(0, (now - entry.last) / 86400000);
      const score = match + Math.log2(entry.visits + 1) * 4 + 5 / (days + 1);
      results.push({ score, kind: entry.kind, value: entry.value, title: entry.title || address,
        subtitle: entry.kind === 'page' && entry.title ? address : '' });
    }
    return results.sort((a, b) => b.score - a.score).slice(0, resultLimit);
  }

  clear() {
    this.entries.clear();
  }

  get size() {
    return this.entries.size;
  }

  serialize() {
    return [...this.entries.values()];
  }
}

module.exports = { History };
