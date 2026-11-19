"use strict";
// Maly klient Discord REST API (fetch z Node 20). Dodrzuje limity Discordu: 429 s retry_after,
// X-RateLimit-Remaining/Reset-After po trasach a globalni limit; 5xx a vypadky site zkusi znovu.

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

class DiscordError extends Error {
  constructor(status, body, method, route) {
    super(`Discord ${method} ${route} -> ${status}${body && body.code ? ` (code ${body.code})` : ""}`);
    this.status = status;
    this.body = body;
  }
}

// Trasa pro limity: hlavni parametr (kanal, server, webhook) zustava, ostatni id se nahradi
function routeKey(method, path) {
  const route = path
    .replace(/\?.*$/, "")
    .replace(/\/(channels|guilds|webhooks)\/(\d+)/, "/$1/<$2>")
    .replace(/\/\d{5,}/g, "/:id")
    .replace(/\/reactions\/.*/, "/reactions/:emoji");
  return `${method} ${route}`;
}

class Rest {
  constructor({ api, token, userAgent = "DiscordBot (https://github.com/luxopes/LuxOS-Arch, 1.0)", maxRetries = 4 }) {
    this.api = api;
    this.token = token;
    this.userAgent = userAgent;
    this.maxRetries = maxRetries;
    this.blockedUntil = new Map();
    this.globalUntil = 0;
  }

  async request(method, path, body, { reason } = {}) {
    const key = routeKey(method, path);
    for (let attempt = 0; ; attempt++) {
      const wait = Math.max(this.globalUntil, this.blockedUntil.get(key) || 0) - Date.now();
      if (wait > 0) await sleep(wait);
      const headers = { Authorization: `Bot ${this.token}`, "User-Agent": this.userAgent };
      if (body !== undefined) headers["Content-Type"] = "application/json";
      if (reason) headers["X-Audit-Log-Reason"] = encodeURIComponent(reason);
      let response;
      try {
        response = await fetch(this.api + path, {
          method, headers, body: body === undefined ? undefined : JSON.stringify(body),
          signal: AbortSignal.timeout(30_000)
        });
      } catch (error) {
        if (attempt >= this.maxRetries) throw error;
        await sleep(1000 * 2 ** attempt);
        continue;
      }
      const text = await response.text();
      let data = null;
      if (text) {
        try { data = JSON.parse(text); } catch { data = { raw: text.slice(0, 200) }; }
      }
      const remaining = response.headers.get("x-ratelimit-remaining");
      const resetAfter = Number(response.headers.get("x-ratelimit-reset-after"));
      if (remaining === "0" && resetAfter > 0) this.blockedUntil.set(key, Date.now() + resetAfter * 1000);

      if (response.status === 429) {
        const retryAfter = Number((data && data.retry_after) || response.headers.get("retry-after") || 1);
        const until = Date.now() + Math.ceil(retryAfter * 1000) + 50;
        if ((data && data.global) || response.headers.get("x-ratelimit-global")) this.globalUntil = until;
        else this.blockedUntil.set(key, until);
        if (attempt >= this.maxRetries) throw new DiscordError(429, data, method, key);
        continue;
      }
      if (response.status >= 500 && attempt < this.maxRetries) {
        await sleep(1000 * 2 ** attempt);
        continue;
      }
      if (!response.ok) throw new DiscordError(response.status, data, method, key);
      return data;
    }
  }

  get(path) { return this.request("GET", path); }
  post(path, body, options) { return this.request("POST", path, body === undefined ? {} : body, options); }
  patch(path, body, options) { return this.request("PATCH", path, body, options); }
  put(path, body, options) { return this.request("PUT", path, body === undefined ? {} : body, options); }
  delete(path, options) { return this.request("DELETE", path, undefined, options); }
}

module.exports = { Rest, DiscordError, routeKey };
