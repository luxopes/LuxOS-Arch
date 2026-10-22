"""LuxOS - sdileny ucet LuxAI pro system a aplikace (LSL IDE, Lux Code, LuxAI).

Ucet je ulozeny v ~/.config/luxai/account.json (adresar 0700, soubor 0600):

    {"version": 1, "origin": "https://lux-ai.cz", "sessionToken": "...",
     "user": {...publicUser...}, "client": "luxos", "updatedAt": "ISO cas"}

Token je session cookie `lux_account_session` serveru lux-ai.cz. Aplikace ho posilaji
jako cookie spolu s hlavickou X-Lux-Client (lsl-ide | luxos | lux-code | luxai), viz
docs/luxai-account.md. Prihlaseni: heslo, e-mailovy kod, nebo pres web (PKCE na
/ide/connect?app=luxos, loopback callback). Registrace: register_start() posle kod na e-mail,
verify_code() ucet zalozi a vrati session (stejne jako prihlaseni kodem).
"""
import base64
import hashlib
import html.parser
import json
import re
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


# Pravidla registrace jako na webu (/register): heslo 12-128 znaku, jmeno max. 80 znaku
PASSWORD_MIN = 12
PASSWORD_MAX = 128
NAME_MAX = 80
TERMS_VERSION = "2026-09-24.1"
REGISTER_URL = ORIGIN + "/register"
TERMS_URL = ORIGIN + "/terms"
CODE_COOLDOWN = 60    # sekund mezi odeslanim kodu (server: slow_down + Retry-After 60)


class AccountError(Exception):
    def __init__(self, code, status=0, retry_after=0, data=None):
        super().__init__(code)
        self.code, self.status, self.retry_after, self.data = code, status, retry_after, data or {}


# Srozumitelne hlasky k chybovym kodum serveru (anglicky klic, aplikace ho prelozi pres luxos_i18n._)
ERROR_TEXTS = {
    "invalid_credentials": "Wrong e-mail or password.",
    "email_unverified": "The e-mail address is not verified yet. Use the sign-in code instead.",
    "invalid_code": "The code is not valid or has expired.",
    "rate": "Too many attempts. Try again later.",
    "slow_down": "Please wait a minute before requesting another code.",
    "network": "LuxAI is not reachable. Check the internet connection.",
    "timeout": "The browser sign-in timed out.",
    "cancelled": "The sign-in was cancelled.",
    "invalid_email": "Enter a valid e-mail address.",
    "email_domain_blocked": "This e-mail domain cannot be used for a LuxAI account.",
    "disposable_email": "This e-mail domain cannot be used for a LuxAI account.",
    "email_domain_review": "This e-mail domain cannot be verified yet. Please use another address.",
    "email_domain_check_unavailable": "The e-mail check is temporarily unavailable. Try again later.",
    "weak_password": "The password must have at least 12 characters.",
    "terms_required": "You need to agree to the LuxAI Terms.",
    "account_exists": "An account with this e-mail already exists. Sign in instead.",
    "origin": "Creating an account from LuxOS is not available yet - create it at %s",
    "no_token": "The server did not finish the sign-in. Try again.",
    "server": "LuxAI is having problems right now. Try again later.",
}


def error_text(err, tr=lambda t: t):
    """Hlaska pro uzivatele k AccountError (tr = prekladova funkce, napr. luxos_i18n._)."""
    code = getattr(err, "code", "") or "error"
    if code == "origin":
        return tr(ERROR_TEXTS["origin"]) % REGISTER_URL
    if code in ERROR_TEXTS:
        return tr(ERROR_TEXTS[code])
    if getattr(err, "status", 0) >= 500:
        return tr(ERROR_TEXTS["server"])
    return tr("Sign-in failed (%s).") % code


# ---- ulozeni ------------------------------------------------------------------
def load():
    """Ulozeny ucet (dict) nebo None."""
    try:
        with open(ACCOUNT_FILE) as f:
            data = json.load(f)
        return data if data.get("sessionToken") else None
    except (OSError, ValueError):
        return None


def account_data(token, user, origin=ORIGIN):
    """Obsah account.json (bez zapisu - instalator ho preda do instalovaneho systemu)."""
    return {"version": 1, "origin": origin, "sessionToken": token, "user": user, "client": CLIENT,
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


def save(token, user, origin=ORIGIN, path=ACCOUNT_FILE):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    os.chmod(os.path.dirname(path), 0o700)
    data = account_data(token, user, origin)
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
            with e:
                body = json.loads(e.read() or b"{}")
            body = body if isinstance(body, dict) else {}
        except ValueError:
            body = {}
        try:
            retry = int((e.headers or {}).get("Retry-After") or 0)
        except ValueError:
            retry = 0
        raise AccountError(body.get("error") or "http", e.code, retry, body) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise AccountError("network") from None


def session_data(r):
    """Odpoved serveru se sessionToken -> obsah account.json (bez zapisu)."""
    token = r.get("sessionToken")
    if not token:
        raise AccountError("no_token")
    return account_data(token, r.get("user") or {})


def _finish(r):
    data = session_data(r)
    return save(data["sessionToken"], data["user"])


def password_session(email, password):
    """Prihlaseni heslem; vraci obsah account.json, neuklada ho (instalator)."""
    return session_data(request("POST", "/api/auth/password/login", {"email": email.strip(), "password": password}))


def login_password(email, password):
    data = password_session(email, password)
    return save(data["sessionToken"], data["user"])


def request_code(email):
    return request("POST", "/api/auth/code/request", {"email": email})


def verify_code(email, code):
    """Over kod z e-mailu (prihlaseni i dokonceni registrace); vraci obsah account.json, neuklada ho."""
    return session_data(request("POST", "/api/auth/code/verify",
                                {"email": email.strip().lower(), "code": code.strip()}))


def login_code(email, code):
    data = verify_code(email, code)
    return save(data["sessionToken"], data["user"])


def password_problem(password):
    """Kontrola hesla pred odeslanim jako na webu: "" = v poradku, jinak chybovy kod."""
    if len(password) < PASSWORD_MIN or len(password) > PASSWORD_MAX:
        return "weak_password"
    return ""


def register_start(email, password, display_name):
    """Zahajeni registrace: server posle 6mistny kod na e-mail, ucet vznikne az ve verify_code().
    Volat jen po zaskrtnuti souhlasu s podminkami v UI (posila termsAccepted: true).
    Chyby: invalid_email, email_domain_blocked, weak_password, terms_required, account_exists (409),
    rate / slow_down (429), email_domain_check_unavailable (503), email_domain_review (422),
    origin (403 - server zatim nepovoluje registraci z aplikaci)."""
    email = email.strip().lower()
    if not email or "@" not in email:
        raise AccountError("invalid_email")
    if password_problem(password):
        raise AccountError("weak_password")
    return request("POST", "/api/auth/register/start",
                   {"email": email, "password": password, "displayName": display_name.strip()[:NAME_MAX],
                    "termsAccepted": True})


# ---- podminky pouzivani (HTML -> prosty text pro zobrazeni v aplikaci) -------------
class _TextParser(html.parser.HTMLParser):
    SKIP = {"head", "script", "style", "noscript", "nav", "footer", "form", "button", "svg", "template"}
    BLOCK = {"p", "div", "section", "article", "main", "header", "ul", "ol", "table", "tr", "blockquote",
             "h1", "h2", "h3", "h4", "h5", "h6", "dl", "dt", "dd", "pre", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.stack, self.in_main, self.has_main = [], 0, [], False, False
        self.lists = []

    def _skip_tag(self, tag, attrs):
        cls = dict(attrs).get("class") or ""
        return tag in self.SKIP or (tag == "header" and "topbar" in cls.split())

    def handle_starttag(self, tag, attrs):
        if tag in ("br", "hr", "img", "meta", "link", "input", "wbr"):
            if not self.skip and tag in ("br", "hr"):
                self.out.append("\n")
            return
        skip = self._skip_tag(tag, attrs)
        self.stack.append((tag, skip))
        if skip:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "main":
            self.has_main = self.in_main = True
        nested = tag in ("ul", "ol") and bool(self.lists)
        if tag in ("ul", "ol"):
            self.lists.append([tag, 0])
        if tag in self.BLOCK:
            self.out.append("" if nested else "\n\n")
        elif tag == "li":
            depth = max(len(self.lists), 1)
            if self.lists and self.lists[-1][0] == "ol":
                self.lists[-1][1] += 1
                mark = f"{self.lists[-1][1]}."
            else:
                mark = "•"
            self.out.append("\n" + "  " * (depth - 1) + mark + " ")

    def handle_endtag(self, tag):
        if not any(t == tag for t, _s in self.stack):
            return   # osamocena koncova znacka
        # zavre i neuzavrene vnorene znacky (tolerance k chybnemu HTML)
        while self.stack:
            t, skip = self.stack.pop()
            if skip:
                self.skip -= 1
            elif not self.skip:
                if t == "main":
                    self.in_main = False
                if t in ("ul", "ol") and self.lists:
                    self.lists.pop()
                    self.out.append("\n" if self.lists else "\n\n")
                elif t in self.BLOCK:
                    self.out.append("\n\n")
            if t == tag:
                break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(("M" if self.in_main else "O", data))


def html_to_text(source):
    """HTML stranky (napr. /terms) -> citelny prosty text: odstavce, nadpisy a odrazky.
    Je-li v HTML <main>, bere se jen jeho obsah (bez horni listy a paticky webu)."""
    p = _TextParser()
    p.feed(source)
    p.close()
    parts = []
    for item in p.out:
        if isinstance(item, tuple):
            where, data = item
            if p.has_main and where != "M":
                continue
            parts.append(re.sub(r"\s+", " ", data))
        else:
            parts.append(item)
    text = "".join(parts)
    lines = []
    for ln in text.split("\n"):
        ln = re.sub(r"(?<=\S)\s+", " ", ln).rstrip()
        # odsazeni ponechat jen u vnorenych odrazek
        lines.append(ln if re.match(r"\s+(•|\d+\.) ", ln) else ln.lstrip())
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def fetch_terms(origin=ORIGIN, timeout=20):
    """Podminky pouzivani LuxAI jako prosty text (GET /terms)."""
    req = urllib.request.Request(origin + "/terms", headers={"Accept": "text/html", "X-Lux-Client": CLIENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            charset = r.headers.get_content_charset() or "utf-8"
            raw = r.read(2 * 1024 * 1024).decode(charset, "replace")
    except urllib.error.HTTPError as e:
        e.close()
        raise AccountError("http", e.code) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise AccountError("network") from None
    text = html_to_text(raw)
    if not text:
        raise AccountError("http")
    return text


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
