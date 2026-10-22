"""Lokalni napodoba serveru LuxAI (lux-ai.cz) pro testy - zadne skutecne ucty ani e-maily.

    srv = MockLuxAI().start()          # http://127.0.0.1:PORT
    os.environ["LUXAI_ORIGIN"] = srv.origin   # pred importem luxai_account

Endpointy a chybove kody podle /opt/lux-account/server.js (popis v zadani):
  POST /api/auth/register/start  {email, password, displayName, termsAccepted}
  POST /api/auth/code/request    {email}           vzdy ok (neprozradi, zda ucet existuje)
  POST /api/auth/code/verify     {email, code}     {ok, user, sessionToken}
  POST /api/auth/password/login  {email, password}
  GET  /api/me                   cookie lux_account_session
  GET  /terms                    HTML podminek
Specialni domeny vyvolaji chyby: blocked.test, review.test, down.test, busy.test.
allow_native = False napodobi dnesni stav: registrace z aplikaci -> 403 {"error": "origin"}
(z jineho procesu: POST /__mock/allow_native {"value": false}).

    python3 mock_luxai.py      # samostatny server, vypise origin a bezi do ukonceni
"""
import json
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TERMS_HTML = """<!doctype html><html lang="cs"><head><meta charset="utf-8"><title>Podmínky — LuxAI</title>
<script>var x = "<p>nezobrazovat</p>";</script><style>p{color:red}</style></head>
<body><header class="topbar compact"><a href="/">LuxAI</a><a href="/">Zpět na web</a></header>
<main><header class="legal-hero"><div class="eyebrow">Verze 2026-09-24</div><h1>Podmínky používání LuxAI</h1>
<p>Tyto podmínky   upravují
používání účtu &amp; služeb.</p></header>
<article><section><h2>1. Provozovatel</h2><p>Kontakt: <a href="mailto:info@lux-ai.cz">info@lux-ai.cz</a>.</p></section>
<section><h2>2. Zakázáno</h2><ul><li>obcházet limity;</li><li>útoky &lt;bez&gt; oprávnění.</li></ul>
<ol><li>první</li><li>druhý</li></ol></section></article></main>
<footer>Paticka webu</footer></body></html>"""

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class MockLuxAI:
    def __init__(self, code="123456", cooldown=60):
        self.code = code
        self.cooldown = cooldown
        self.allow_native = True
        self.accounts = {}     # email -> {"password", "displayName"}
        self.pending = {}      # email -> {"code", "register": {...} | None, "fails"}
        self.last_sent = {}    # email -> cas posledniho kodu
        self.sessions = {}     # token -> email
        self.log = []          # (metoda, cesta, telo, X-Lux-Client)
        self.sent_codes = []   # (email, kod) - "odeslane e-maily"
        self.lock = threading.Lock()
        self.httpd = None

    # ---- server ----
    def start(self):
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def reply(self, status, body, headers=None, ctype="application/json"):
                raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype + "; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):  # noqa: N802
                mock.log.append(("GET", self.path, None, self.headers.get("X-Lux-Client")))
                if self.path == "/terms":
                    return self.reply(200, TERMS_HTML, ctype="text/html")
                if self.path == "/api/me":
                    m = re.search(r"lux_account_session=([\w-]+)", self.headers.get("Cookie") or "")
                    email = m and mock.sessions.get(m.group(1))
                    if not email or email not in mock.accounts:
                        return self.reply(401, {"error": "unauthorized"})
                    return self.reply(200, {"user": mock.user(email)})
                self.reply(404, {"error": "not_found"})

            def do_POST(self):  # noqa: N802
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    body = {}
                client = self.headers.get("X-Lux-Client")
                mock.log.append(("POST", self.path, body, client))
                with mock.lock:
                    status, out, headers = mock.handle(self.path, body, client)
                self.reply(status, out, headers)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.origin = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()

    # ---- logika ----
    def user(self, email):
        a = self.accounts[email]
        return {"id": "u-" + email.split("@")[0], "email": email, "displayName": a["displayName"],
                "usage": {"fastTokens": 0, "fastLimit": 50000, "liteTokens": 0, "liteLimit": 1000000}}

    def session(self, email):
        token = secrets.token_urlsafe(16)
        self.sessions[token] = email
        return {"ok": True, "user": self.user(email), "sessionToken": token}

    def send_code(self, email, register=None):
        now = time.monotonic()
        if now - self.last_sent.get(email, -1e9) < self.cooldown:
            return 429, {"error": "slow_down"}, {"Retry-After": str(self.cooldown)}
        self.last_sent[email] = now
        self.pending[email] = {"code": self.code, "register": register, "fails": 0}
        self.sent_codes.append((email, self.code))
        return 200, {"ok": True}, None

    def handle(self, path, body, client):
        if path == "/__mock/allow_native":   # jen pro testy v jinem procesu (TUI)
            self.allow_native = bool(body.get("value"))
            return 200, {"ok": True}, None
        if path == "/__mock/reset_cooldown":
            self.last_sent.clear()
            return 200, {"ok": True}, None
        email = str(body.get("email") or "").strip().lower()
        domain = email.rsplit("@", 1)[-1]
        if path == "/api/auth/register/start":
            if client and not self.allow_native:
                return 403, {"error": "origin"}, None
            if not EMAIL_RE.match(email):
                return 400, {"error": "invalid_email"}, None
            pw = body.get("password")
            if not isinstance(pw, str) or not 12 <= len(pw) <= 128:
                return 400, {"error": "weak_password"}, None
            if domain == "blocked.test":
                return 400, {"error": "email_domain_blocked"}, None
            if domain == "review.test":
                return 422, {"error": "email_domain_review"}, None
            if domain == "down.test":
                return 503, {"error": "email_domain_check_unavailable"}, None
            if domain == "busy.test":
                return 429, {"error": "rate"}, None
            if body.get("termsAccepted") is not True:
                return 400, {"error": "terms_required", "termsVersion": "2026-09-24.1"}, None
            if email in self.accounts:
                return 409, {"error": "account_exists"}, None
            return self.send_code(email, {"password": pw, "displayName": str(body.get("displayName") or "")})
        if path == "/api/auth/code/request":
            if email in self.accounts:
                status, out, headers = self.send_code(email)
                if status != 200:
                    return status, out, headers
            return 200, {"ok": True}, None
        if path == "/api/auth/code/verify":
            p = self.pending.get(email)
            if not p:
                return 400, {"error": "invalid_code"}, None
            if p["fails"] >= 5:
                return 429, {"error": "rate"}, None
            if str(body.get("code")) != p["code"]:
                p["fails"] += 1
                return 400, {"error": "invalid_code"}, None
            del self.pending[email]
            if p["register"]:
                self.accounts[email] = p["register"]
            return 200, self.session(email), None
        if path == "/api/auth/password/login":
            a = self.accounts.get(email)
            if not a or a["password"] != body.get("password"):
                return 401, {"error": "invalid_credentials"}, None
            return 200, self.session(email), None
        return 404, {"error": "not_found"}, None


if __name__ == "__main__":
    import sys
    srv = MockLuxAI().start()
    print(srv.origin, flush=True)
    try:
        threading.Event().wait(float(sys.argv[1]) if len(sys.argv) > 1 else 600)
    finally:
        srv.stop()
