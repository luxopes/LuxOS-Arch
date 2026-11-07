"""Spusteni upraveneho serveru uctu LuxAI mistne pro testy (nikdy skutecna data ani server).

Server.js se do repozitare nedava (soukromy kod serveru); test dostane cestu k jeho mistni kopii
v LUX_ACCOUNT_SERVER_JS (napr. scp root@server:/opt/lux-account/server.js /tmp/x/), zkopiruje ji do
docasne slozky, pouzije mail_oauth_patch.py a spusti s falesnym DATA_FILE, falesnymi tajemstvimi
a nahradou modulu nodemailer (zadny e-mail se neposle).
"""
import hashlib
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
PATCH = os.path.join(HERE, "..", "account-server", "mail_oauth_patch.py")
SESSION_SECRET = "test-session-secret-0123456789abcdef"
INTROSPECTION_SECRET = "test-introspection-secret-0123456789"

ADMIN_ID = "11111111-1111-4111-8111-111111111111"
USER_ID = "22222222-2222-4222-8222-222222222222"
SUSP_ID = "33333333-3333-4333-8333-333333333333"
UNVER_ID = "44444444-4444-4444-8444-444444444444"
ADMIN_EMAIL = "owner@personal.example"
USER_EMAIL = "someone@personal.example"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def session_key(raw):
    return hashlib.sha256(("%s:%s" % (SESSION_SECRET, raw)).encode()).hexdigest()


def user(uid, email, role="user", verified=True, **extra):
    u = {"id": uid, "email": email, "username": email.split("@")[0].replace(".", ""), "displayName": "Test " + email.split("@")[0],
         "role": role, "verifiedAt": "2026-01-01T00:00:00.000Z" if verified else None,
         "createdAt": "2026-01-01T00:00:00.000Z", "updatedAt": "2026-01-01T00:00:00.000Z", "weeklyUsage": {}}
    u.update(extra)
    return u


class AccountServer:
    def __init__(self, mailboxes, env_overrides=None):
        src = os.environ.get("LUX_ACCOUNT_SERVER_JS", "")
        if not src or not os.path.isfile(src):
            raise FileNotFoundError("LUX_ACCOUNT_SERVER_JS not set")
        self.root = tempfile.mkdtemp(prefix="lux-account-test-")
        self.js = os.path.join(self.root, "server.js")
        shutil.copy(src, self.js)
        out = subprocess.run([sys.executable, "-I", PATCH, self.js], capture_output=True, text=True, check=True)
        self.patch_output = out.stdout
        stub = os.path.join(self.root, "node_modules", "nodemailer")
        os.makedirs(stub)
        with open(os.path.join(stub, "index.js"), "w") as f:
            f.write("module.exports = { createTransport() { return { async sendMail() { return {}; } }; } };\n")
        self.mailboxes_file = os.path.join(self.root, "mailboxes.json")
        self.write_mailboxes(mailboxes)
        self.tokens = {"admin": "session-admin-" + "a" * 30, "user": "session-user-" + "b" * 30,
                       "susp": "session-susp-" + "c" * 30, "unver": "session-unver-" + "d" * 30,
                       "expired": "session-expired-" + "e" * 30, "admin2": "session-admin2-" + "f" * 30}
        far = int(time.time() * 1000) + 86400000
        state = {"version": 1,
                 "users": {ADMIN_ID: user(ADMIN_ID, ADMIN_EMAIL, "admin"),
                           USER_ID: user(USER_ID, USER_EMAIL),
                           SUSP_ID: user(SUSP_ID, "blocked@personal.example", suspendedAt="2026-01-01T00:00:00.000Z"),
                           UNVER_ID: user(UNVER_ID, "new@personal.example", verified=False)},
                 "sessions": {session_key(self.tokens["admin"]): {"userId": ADMIN_ID, "authMethod": "password", "createdAt": 1, "expiresAt": far},
                              session_key(self.tokens["admin2"]): {"userId": ADMIN_ID, "authMethod": "password", "createdAt": 1, "expiresAt": far},
                              session_key(self.tokens["user"]): {"userId": USER_ID, "authMethod": "password", "createdAt": 1, "expiresAt": far},
                              session_key(self.tokens["susp"]): {"userId": SUSP_ID, "authMethod": "password", "createdAt": 1, "expiresAt": far},
                              session_key(self.tokens["unver"]): {"userId": UNVER_ID, "authMethod": "password", "createdAt": 1, "expiresAt": far}},
                 "loginCodes": {}, "apiKeys": {}, "adminAudit": []}
        self.data_file = os.path.join(self.root, "data", "state.json")
        os.makedirs(os.path.dirname(self.data_file))
        with open(self.data_file, "w") as f:
            json.dump(state, f)
        self.port = free_port()
        env = {"PATH": os.environ.get("PATH", "/usr/bin"), "NODE_ENV": "test", "HOST": "127.0.0.1", "PORT": str(self.port),
               "PUBLIC_ORIGIN": "https://lux-ai.test", "DATA_FILE": self.data_file, "SESSION_SECRET": SESSION_SECRET,
               "CODE_SECRET": "test-code-secret-0123456789", "INTERNAL_API_SECRET": "test-internal-0123456789",
               "ADMIN_EMAILS": ADMIN_EMAIL, "MAIL_CAPTURE_FILE": os.path.join(self.root, "mail.jsonl"),
               "MAIL_MAILBOXES_FILE": self.mailboxes_file, "MAIL_INTROSPECTION_SECRET": INTROSPECTION_SECRET,
               "FEEDBACK_DIR": os.path.join(self.root, "feedback"), "IDE_CLOUD_DIR": os.path.join(self.root, "cloud"),
               "EMAIL_DOMAIN_BLOCKLIST_FILE": os.path.join(self.root, "none-block"),
               "EMAIL_DOMAIN_ALLOWLIST_FILE": os.path.join(self.root, "none-allow")}
        env.update(env_overrides or {})
        self.log_path = os.path.join(self.root, "server.log")
        self.log = open(self.log_path, "ab")
        self.proc = subprocess.Popen(["node", self.js], cwd=self.root, env=env, stdout=self.log, stderr=self.log)
        end = time.time() + 15
        while time.time() < end:
            try:
                if self.request("GET", "/health")[0] == 200:
                    return
            except OSError:
                time.sleep(0.1)
        self.stop()
        raise RuntimeError("account server did not start: " + self.read_log())

    @property
    def origin(self):
        return "http://127.0.0.1:%d" % self.port

    def write_mailboxes(self, value):
        tmp = self.mailboxes_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(value, f)
        os.replace(tmp, self.mailboxes_file)

    def read_log(self):
        try:
            with open(self.log_path, errors="replace") as f:
                return f.read()
        except OSError:
            return ""

    def request(self, method, path, body=None, headers=None, session=None, client="luxos"):
        h = dict(headers or {})
        if client:
            h["X-Lux-Client"] = client
        if session:
            h["Cookie"] = "lux_account_session=" + self.tokens.get(session, session)
        data = None
        if isinstance(body, dict):
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        elif isinstance(body, (bytes, str)):
            data = body.encode() if isinstance(body, str) else body
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            return r.status, json.loads(raw or b"null")
        except ValueError:
            return r.status, raw

    def introspect(self, token, secret=INTROSPECTION_SECRET, client_id="lux-dovecot", headers=None):
        import base64
        h = {"Content-Type": "application/x-www-form-urlencoded",
             "Authorization": "Basic " + base64.b64encode(("%s:%s" % (client_id, secret)).encode()).decode()}
        h.update(headers or {})
        return self.request("POST", "/oauth/introspect", urllib.parse.urlencode({"token": token}), headers=h, client=None)

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.log.close()

    def close(self):
        self.stop()
        shutil.rmtree(self.root, ignore_errors=True)


def default_mailboxes(imap_port=993, smtp_port=465, host="mail.lux-ai.test", security="ssl"):
    return {"imap": {"host": host, "port": imap_port, "security": security},
            "smtp": {"host": host, "port": smtp_port, "security": "ssl"},
            "mailboxes": [{"address": "info@lux-ai.test", "display_name": "LuxAI", "emails": [ADMIN_EMAIL],
                           "users": [], "require_group": "luxai-admin"},
                          {"address": "Team@Lux-AI.test", "display_name": "Team", "users": [USER_ID]},
                          {"address": "broken", "users": [USER_ID]}]}
