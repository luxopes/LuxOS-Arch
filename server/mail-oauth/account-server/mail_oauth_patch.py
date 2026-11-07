#!/usr/bin/env python3
"""Uprava serveru uctu LuxAI (/opt/lux-account/server.js) pro Postu LuxOS.

    python3 mail_oauth_patch.py [cesta/k/server.js]      (vychozi /opt/lux-account/server.js)

Prida (vse v jednom souboru server.js, bez novych zavislosti):
  GET  /api/mail/mailboxes   nativni klient (X-Lux-Client + session cookie jako /api/ide/*): schranky
                             na serveru LuxAI, ke kterym ma ucet pristup (mapovani v MAIL_MAILBOXES_FILE)
  POST /api/mail/token       {"address"} -> kratkodoby pristupovy token (15 min) pro IMAP/SMTP
                             (SASL OAUTHBEARER / XOAUTH2), vazany na ucet, relaci a schranku
  POST /oauth/introspect     RFC 7662 pro Dovecot (passdb oauth2, introspection_mode = post); jen primo
                             z loopbacku (bez hlavicek proxy) a s tajnym klicem klienta (HTTP Basic)

Skript je idempotentni (podruhe nic nezmeni) a kazdy kotevni text musi v souboru byt prave jednou,
jinak skonci chybou a soubor nezmeni.
"""
import sys

MARK = "// Posta LuxOS: schranky LuxAI pro nativni klienty"

DECL_ANCHOR = "const accessTokens = new Map();\n"
DECL = DECL_ANCHOR + MARK + """ (IMAP/SMTP pres SASL OAUTHBEARER/XOAUTH2).
// Mapovani ucet -> schranka je v MAIL_MAILBOXES_FILE (JSON bez tajnych udaju), tokeny jen v pameti.
const MAIL_MAILBOXES_FILE = String(process.env.MAIL_MAILBOXES_FILE || "/etc/lux-account-mailboxes.json");
const MAIL_INTROSPECTION_CLIENT_ID = String(process.env.MAIL_INTROSPECTION_CLIENT_ID || "lux-dovecot");
const MAIL_INTROSPECTION_SECRET = String(process.env.MAIL_INTROSPECTION_SECRET || "");
const MAIL_TOKEN_TTL_MS = Math.max(60_000, Number(process.env.MAIL_TOKEN_TTL_SECONDS || 900) * 1000);
const MAIL_TOKEN_MAX = 20_000;
const MAIL_MECHANISMS = Object.freeze(["OAUTHBEARER", "XOAUTH2"]);
const mailTokens = new Map();
let mailboxConfigCache = { fingerprint: "", value: { mailboxes: [] } };
"""

REVOKE_ANCHOR = "  for (const [token, record] of accessTokens) if (record.userId === userId) accessTokens.delete(token);\n"
REVOKE = REVOKE_ANCHOR + "  for (const [token, record] of mailTokens) if (record.userId === userId) mailTokens.delete(token);\n"

FUNC_ANCHOR = "function discovery(res) {\n"
FUNCS = MARK + """: mapovani, tokeny a introspekce (RFC 7662) pro Dovecot.
function mailServerSettings(value, fallbackPort) {
  const input = value && typeof value === "object" ? value : {};
  const host = String(input.host || "").trim().toLowerCase();
  const port = Number(input.port || fallbackPort);
  const security = String(input.security || "ssl");
  if (!/^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$/.test(host) || !Number.isInteger(port) || port < 1 || port > 65535
    || !["ssl", "starttls"].includes(security)) return null;
  return { host, port, security };
}

function loadMailboxConfig() {
  let stat;
  try { stat = fs.statSync(MAIL_MAILBOXES_FILE); } catch { return { mailboxes: [] }; }
  const fingerprint = `${stat.ino}:${stat.size}:${stat.mtimeMs}`;
  if (mailboxConfigCache.fingerprint === fingerprint) return mailboxConfigCache.value;
  let parsed = {};
  try {
    parsed = JSON.parse(fs.readFileSync(MAIL_MAILBOXES_FILE, "utf8"));
  } catch (error) {
    console.error(`mail mailboxes load failed error=${String(error.message).replace(/[^a-zA-Z0-9_.-]/g, "-").slice(0, 100)}`);
  }
  const imap = mailServerSettings(parsed?.imap, 993);
  const smtp = mailServerSettings(parsed?.smtp, 465);
  const lowerSet = (list) => new Set((Array.isArray(list) ? list : []).map((item) => String(item).trim().toLowerCase()).filter(Boolean));
  const mailboxes = [];
  for (const entry of Array.isArray(parsed?.mailboxes) ? parsed.mailboxes : []) {
    const address = String(entry?.address || "").trim().toLowerCase();
    if (address.length > 254 || !/^[a-z0-9._%+-]+@[a-z0-9.-]+\\.[a-z]{2,}$/.test(address)) continue;
    mailboxes.push({
      address,
      displayName: String(entry.display_name || "").replace(/[\\u0000-\\u001f\\u007f]/g, "").slice(0, 120),
      users: lowerSet(entry.users), emails: lowerSet(entry.emails), group: String(entry.require_group || ""),
      imap: mailServerSettings(entry.imap, 993) || imap, smtp: mailServerSettings(entry.smtp, 465) || smtp
    });
  }
  mailboxConfigCache = { fingerprint, value: { mailboxes } };
  return mailboxConfigCache.value;
}

// Stejna pravidla jako prihlaseni do webmailu (Roundcube luxai_sso): overeny e-mail, ucet neni pozastaveny,
// ucet (id nebo registracni e-mail) je u schranky uvedeny a pripadne ma pozadovanou skupinu (luxai-admin).
function mailboxesForUser(user) {
  if (!user || !user.verifiedAt || suspensionIsActive(user)) return [];
  const groups = userClaims(user).groups;
  const id = String(user.id || "").toLowerCase();
  const email = String(user.email || "").trim().toLowerCase();
  return loadMailboxConfig().mailboxes.filter((box) => box.imap
    && (box.users.has(id) || (email && box.emails.has(email)))
    && (!box.group || groups.includes(box.group)));
}

function publicMailbox(box) {
  return { address: box.address, display_name: box.displayName, imap: box.imap, smtp: box.smtp, auth: "luxai-oauth", mechanisms: MAIL_MECHANISMS };
}

function mailNativeUser(req, res) {
  if (!isIdeClient(req)) { json(res, 403, { error: "client" }); return null; }
  const session = currentSession(req);
  const user = currentUser(req);
  if (!session || !user || !user.verifiedAt) { json(res, 401, { error: "auth" }); return null; }
  return { user, session };
}

function mailMailboxes(req, res) {
  const auth = mailNativeUser(req, res);
  if (!auth) return;
  const rate = rateHit(`mail-list:${auth.user.id}`, 60, 60_000);
  if (!rate.allowed) { json(res, 429, { error: "rate" }, { "Retry-After": String(rate.retryAfter) }); return; }
  json(res, 200, { mailboxes: mailboxesForUser(auth.user).map(publicMailbox) });
}

function purgeMailTokens() {
  const now = Date.now();
  for (const [key, record] of mailTokens) if (record.expiresAt <= now) mailTokens.delete(key);
  while (mailTokens.size >= MAIL_TOKEN_MAX) mailTokens.delete(mailTokens.keys().next().value);
}

async function mailToken(req, res) {
  const auth = mailNativeUser(req, res);
  if (!auth) return;
  const rate = rateHit(`mail-token:${auth.user.id}`, 30, 60_000);
  if (!rate.allowed) { json(res, 429, { error: "rate" }, { "Retry-After": String(rate.retryAfter) }); return; }
  const body = await readJson(req, 4 * 1024);
  const address = String(body.address || "").trim().toLowerCase();
  const box = mailboxesForUser(auth.user).find((candidate) => candidate.address === address);
  if (!box) { json(res, 403, { error: "mailbox" }); return; }
  purgeMailTokens();
  const raw = randomToken(32);
  const now = Date.now();
  mailTokens.set(sha256(raw), {
    userId: auth.user.id, sessionKey: auth.session.key, address: box.address,
    client: String(req.headers["x-lux-client"] || "").slice(0, 40), issuedAt: now, expiresAt: now + MAIL_TOKEN_TTL_MS
  });
  json(res, 200, { access_token: raw, token_type: "Bearer", expires_in: Math.floor(MAIL_TOKEN_TTL_MS / 1000), address: box.address, mechanisms: MAIL_MECHANISMS });
}

// Introspekce jen pro Dovecot na tomtez stroji: primo z loopbacku, bez hlavicek reverzni proxy (Caddy je
// vzdy pridava), a s klientskym tajemstvim. Jinak 404, jako by cesta neexistovala.
function directLoopback(req) {
  const remote = String(req.socket.remoteAddress || "");
  return ["127.0.0.1", "::1", "::ffff:127.0.0.1"].includes(remote)
    && !req.headers["x-forwarded-for"] && !req.headers["x-forwarded-host"] && !req.headers.forwarded && !req.headers["x-real-ip"];
}

function mailTokenRecord(raw) {
  if (!raw || raw.length > 512) return { reason: "format" };
  const key = sha256(raw);
  const record = mailTokens.get(key);
  if (!record) return { reason: "unknown" };
  if (record.expiresAt <= Date.now()) { mailTokens.delete(key); return { reason: "expired" }; }
  const user = state.users[record.userId];
  const session = state.sessions[record.sessionKey];
  if (!session || Number(session.expiresAt) <= Date.now() || session.userId !== record.userId) { mailTokens.delete(key); return { reason: "session" }; }
  if (!mailboxesForUser(user).some((box) => box.address === record.address)) { mailTokens.delete(key); return { reason: "denied" }; }
  return { record, user };
}

async function mailIntrospect(req, res) {
  if (!MAIL_INTROSPECTION_SECRET || !directLoopback(req)) { json(res, 404, { error: "not_found" }); return; }
  const form = new URLSearchParams(await readBody(req, 8 * 1024));
  const credentials = clientCredentials(req, form);
  if (credentials.id !== MAIL_INTROSPECTION_CLIENT_ID || !timingEqualText(MAIL_INTROSPECTION_SECRET, credentials.secret)) {
    console.log("mail introspection rejected reason=client");
    json(res, 401, { error: "invalid_client" }, { "WWW-Authenticate": "Basic" }); return;
  }
  const found = mailTokenRecord(String(form.get("token") || ""));
  if (!found.record) {
    console.log(`mail introspection inactive reason=${found.reason}`);
    json(res, 200, { active: false }); return;
  }
  const { record, user } = found;
  json(res, 200, {
    active: true, username: record.address, sub: user.id, client_id: "luxos-mail", scope: "mail", token_type: "Bearer",
    iat: Math.floor(record.issuedAt / 1000), exp: Math.floor(record.expiresAt / 1000)
  });
}

"""

ROUTE_OAUTH_ANCHOR = '    if (req.method === "GET" && url.pathname === "/oauth/userinfo") { userInfo(req, res); return; }\n'
ROUTE_OAUTH = ROUTE_OAUTH_ANCHOR + '    if (req.method === "POST" && url.pathname === "/oauth/introspect") { await mailIntrospect(req, res); return; }\n'

ROUTE_API_ANCHOR = '    if (req.method === "POST" && url.pathname === "/api/ide/logout") {\n'
ROUTE_API = ('    if (req.method === "GET" && url.pathname === "/api/mail/mailboxes") { mailMailboxes(req, res); return; }\n'
             '    if (req.method === "POST" && url.pathname === "/api/mail/token") { await mailToken(req, res); return; }\n'
             + ROUTE_API_ANCHOR)

STEPS = [
    ("declarations", DECL_ANCHOR, DECL),
    ("revokeUserAccess", REVOKE_ANCHOR, REVOKE),
    ("functions", FUNC_ANCHOR, FUNCS + FUNC_ANCHOR),
    ("oauth route", ROUTE_OAUTH_ANCHOR, ROUTE_OAUTH),
    ("api routes", ROUTE_API_ANCHOR, ROUTE_API),
]


def patch(text):
    if MARK in text:
        return text, False
    for name, anchor, replacement in STEPS:
        count = text.count(anchor)
        if count != 1:
            raise SystemExit("anchor '%s' found %d times (expected 1) - server.js changed, patch not applied" % (name, count))
        text = text.replace(anchor, replacement, 1)
    return text, True


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/opt/lux-account/server.js"
    with open(path, encoding="utf-8") as f:
        text = f.read()
    new, changed = patch(text)
    if not changed:
        print("already patched: " + path)
        return 0
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)
    print("patched: " + path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
