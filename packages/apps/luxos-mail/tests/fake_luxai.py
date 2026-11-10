"""Falesny server uctu LuxAI pro testy Posty (nikdy skutecny ucet ani server).

GET /api/mail/mailboxes a POST /api/mail/token jako na lux-ai.cz (cookie lux_account_session +
X-Lux-Client). Vydany token zaregistruje ve falesnem IMAP serveru (rizeni "token TOKEN UZIVATEL"),
takze ho IMAP prijme pro danou schranku. fail_token / fail_list nastavi chybovy HTTP stav.
"""
import http.server
import json
import os
import secrets
import threading

SESSION = "test-session-" + "x" * 32


class FakeLuxAI:
    def __init__(self, imap_server, mailboxes, session=SESSION):
        self.imap = imap_server
        self.mailboxes = mailboxes
        self.session = session
        self.requests = []
        self.tokens = []
        self.fail_token = 0
        self.fail_list = 0
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def reply(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def authorized(self):
                cookie = self.headers.get("Cookie", "")
                outer.requests.append({"method": self.command, "path": self.path, "client": self.headers.get("X-Lux-Client", ""),
                                       "cookie_ok": cookie == "lux_account_session=" + outer.session})
                if self.headers.get("X-Lux-Client", "") not in ("luxos", "lsl-ide", "lux-code", "luxai"):
                    self.reply(403, {"error": "client"})
                    return False
                if cookie != "lux_account_session=" + outer.session:
                    self.reply(401, {"error": "auth"})
                    return False
                return True

            def do_GET(self):
                if self.path != "/api/mail/mailboxes":
                    self.reply(404, {"error": "not_found"})
                    return
                if not self.authorized():
                    return
                if outer.fail_list:
                    self.reply(outer.fail_list, {"error": "auth" if outer.fail_list == 401 else "test"})
                    return
                self.reply(200, {"mailboxes": outer.mailboxes})

            def do_POST(self):
                n = int(self.headers.get("Content-Length", "0") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                if self.path != "/api/mail/token":
                    self.reply(404, {"error": "not_found"})
                    return
                if not self.authorized():
                    return
                if outer.fail_token:
                    self.reply(outer.fail_token, {"error": "auth" if outer.fail_token == 401 else "mailbox"})
                    return
                address = str(body.get("address", "")).lower()
                if address not in [m["address"].lower() for m in outer.mailboxes]:
                    self.reply(403, {"error": "mailbox"})
                    return
                token = secrets.token_urlsafe(32)
                outer.tokens.append(token)
                if outer.imap is not None:
                    outer.imap.control("token %s %s" % (token, address))
                self.reply(200, {"access_token": token, "token_type": "Bearer", "expires_in": 900, "address": address,
                                 "mechanisms": ["OAUTHBEARER", "XOAUTH2"]})

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def origin(self):
        return "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def token_requests(self):
        return [r for r in self.requests if r["path"] == "/api/mail/token"]

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def write_account(session_env, origin, token=SESSION, name="Antonín Test", email="owner@personal.example"):
    """~/.config/luxai/account.json docasneho HOME testu (jako luxos-account: 0700/0600)."""
    d = os.path.join(session_env["XDG_CONFIG_HOME"], "luxai")
    os.makedirs(d, mode=0o700, exist_ok=True)
    path = os.path.join(d, "account.json")
    with open(path, "w") as f:
        json.dump({"version": 1, "origin": origin, "sessionToken": token,
                   "user": {"id": "u-1", "email": email, "displayName": name, "username": "antonin"},
                   "client": "luxos", "updatedAt": "2026-11-07T18:00:00+0100"}, f)
    os.chmod(path, 0o600)
    return path


def mailbox(address, port, host="localhost", name="LuxAI", smtp_port=9):
    return {"address": address, "display_name": name, "imap": {"host": host, "port": port, "security": "ssl"},
            "smtp": {"host": host, "port": smtp_port, "security": "ssl"}, "auth": "luxai-oauth", "mechanisms": ["OAUTHBEARER", "XOAUTH2"]}
