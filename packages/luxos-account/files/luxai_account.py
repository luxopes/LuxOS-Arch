"""LuxOS - sdileny ucet LuxAI pro system a aplikace (LSL IDE, Lux Code, LuxAI).

Ucet je ulozeny v ~/.config/luxai/account.json (adresar 0700, soubor 0600):

    {"version": 1, "origin": "https://lux-ai.cz", "sessionToken": "...",
     "user": {...publicUser...}, "client": "luxos", "updatedAt": "ISO cas"}

Token je session cookie `lux_account_session` serveru lux-ai.cz. Aplikace ho posilaji
jako cookie spolu s hlavickou X-Lux-Client (lsl-ide | luxos | lux-code | luxai), viz
docs/luxai-account.md. Prihlaseni: heslo, e-mailovy kod, nebo pres web (PKCE na
/ide/connect?app=luxos, loopback callback).
"""
import base64
import hashlib
import json
import os
import secrets
import ssl
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

ORIGIN = os.environ.get("LUXAI_ORIGIN", "https://lux-ai.cz")
COOKIE = "lux_account_session"
CLIENT = "luxos"
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "luxai")
ACCOUNT_FILE = os.path.join(CONFIG_DIR, "account.json")


class AccountError(Exception):
    def __init__(self, code, status=0):
        super().__init__(code)
        self.code, self.status = code, status


# ---- ulozeni ------------------------------------------------------------------
def load():
    """Ulozeny ucet (dict) nebo None."""
    try:
        with open(ACCOUNT_FILE) as f:
            data = json.load(f)
        return data if data.get("sessionToken") else None
    except (OSError, ValueError):
        return None


def save(token, user, origin=ORIGIN, path=ACCOUNT_FILE):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    os.chmod(os.path.dirname(path), 0o700)
    data = {"version": 1, "origin": origin, "sessionToken": token, "user": user, "client": CLIENT,
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".account-")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return data


def forget():
    try:
        os.unlink(ACCOUNT_FILE)
    except OSError:
        pass


# ---- HTTP -----------------------------------------------------------------------
def request(method, path, body=None, token=None, origin=ORIGIN, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(origin + path, data=data, method=method)
    req.add_header("X-Lux-Client", CLIENT)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Cookie", f"{COOKIE}={token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            raw = r.read()
            return json.loads(raw or b"{}")
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read() or b"{}").get("error") or "http"
        except ValueError:
            err = "http"
        raise AccountError(err, e.code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise AccountError("network") from None


def _finish(r):
    token = r.get("sessionToken")
    if not token:
        raise AccountError("no_token")
    return save(token, r.get("user") or {})


def login_password(email, password):
    return _finish(request("POST", "/api/auth/password/login", {"email": email, "password": password}))


def request_code(email):
    return request("POST", "/api/auth/code/request", {"email": email})


def login_code(email, code):
    return _finish(request("POST", "/api/auth/code/verify", {"email": email, "code": code}))


def me(account=None):
    """Aktualni udaje o uctu ze serveru (a ulozi je); AccountError("signed_out") pri neplatne session."""
    account = account or load()
    if not account:
        raise AccountError("signed_out")
    try:
        r = request("GET", "/api/me", token=account["sessionToken"], origin=account.get("origin", ORIGIN))
    except AccountError as e:
        if e.status in (401, 403):
            raise AccountError("signed_out", e.status) from None
        raise
    user = r.get("user")
    if not user:
        raise AccountError("signed_out")
    save(account["sessionToken"], user, account.get("origin", ORIGIN))
    return r


def logout():
    account = load()
    if account:
        try:
            request("POST", "/api/ide/logout", {}, token=account["sessionToken"], origin=account.get("origin", ORIGIN))
        except AccountError:
            pass
    forget()


# ---- prihlaseni pres web (loopback + PKCE) ----------------------------------------
class WebLogin:
    """Otevre lux-ai.cz/ide/connect?app=luxos; po potvrzeni prohlizec presmeruje na
    http://127.0.0.1:PORT/callback a kod se vymeni za session token."""

    def __init__(self):
        self.state = secrets.token_urlsafe(24)
        self.verifier = secrets.token_urlsafe(48)
        self.challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).rstrip(b"=").decode()
        self.code = self.error = ""
        self.done = threading.Event()
        login = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def do_GET(self):  # noqa: N802
                u = urlparse(self.path)
                q = parse_qs(u.query)
                ok = u.path == "/callback" and q.get("state", [""])[0] == login.state and q.get("code", [""])[0]
                if u.path != "/callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                if ok:
                    login.code = q["code"][0]
                else:
                    login.error = q.get("error", ["invalid_callback"])[0]
                text = "LuxOS je propojený s účtem LuxAI. Okno můžete zavřít." if ok else "Připojení se nezdařilo."
                body = ("<!doctype html><meta charset='utf-8'><title>LuxOS</title><body style='font:16px system-ui;"
                        "background:#12131f;color:#f1f3ff;display:grid;place-items:center;height:100vh;margin:0'>"
                        f"<h2>{text}</h2>").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                login.done.set()

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"{ORIGIN}/ide/connect?state={self.state}&port={self.port}&challenge={self.challenge}&app=luxos"

    def wait(self, timeout=600):
        """Ceka na callback, vymeni kod za token a ulozi ucet."""
        try:
            if not self.done.wait(timeout):
                raise AccountError("timeout")
            if not self.code:
                raise AccountError(self.error or "cancelled")
            return _finish(request("POST", "/api/ide/token", {"code": self.code, "verifier": self.verifier}))
        finally:
            self.close()

    def close(self):
        try:
            self.server.shutdown()
            self.server.server_close()
        except OSError:
            pass
