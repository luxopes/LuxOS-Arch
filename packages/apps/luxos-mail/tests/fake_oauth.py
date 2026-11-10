"""Falesny poskytovatel OAuth2 (Google/Microsoft) pro testy Posty - nikdy skutecny Google ani Microsoft.

GET  /authorize   jako accounts.google.com / login.microsoftonline.com: zkontroluje client_id, redirect_uri
                  (loopback), response_type=code, PKCE S256 a state a hned presmeruje (302) zpet na loopback
                  s kodem ("uzivatel" se prihlasil uctem self.email) nebo s error=access_denied (self.deny).
POST /revoke      odvolani tokenu (RFC 7009) jako oauth2.googleapis.com/revoke: zaznamena token (self.revoked).
POST /token       authorization_code (kod jen jednou, stejne redirect_uri, overeni code_verifier proti
                  code_challenge, client_secret kdyz je nastaveny) a refresh_token (invalid_grant po revoke_refresh,
                  volitelne rotace obnovovaciho tokenu). Vydany pristupovy token zaregistruje ve falesnem IMAP
                  (rizeni "token TOKEN UZIVATEL AUD"), id_token je nepodepsany JWT s e-mailem.
POST /consumers/token  totez (Microsoft /consumers pro osobni ucty).

Napodobeni chyb Microsoftu: graph_when_oidc - rozsahy s openid/email/profile daji token pro Graph (IMAP pak
"User is authenticated but not connected"); username - preferred_username v id_token (jiny nez e-mail).

Prohlizec v testech: follow(url) - GET na /authorize bez automatickeho presmerovani, pak GET na adresu
z Location (loopback Posty) - jako skutecny prohlizec po prihlaseni.
"""
import base64
import hashlib
import http.client
import http.server
import json
import secrets
import threading
import urllib.parse


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def jwt(claims):
    head = b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    return head + "." + b64url(json.dumps(claims).encode()) + "."


class FakeOAuth:
    def __init__(self, imap_server, email, client_id, client_secret="", redirect_host="127.0.0.1", expires_in=3600,
                 rotate=False, email_claim=True):
        # jeden falesny IMAP nebo seznam (hlavni a nahradni server poskytovatele)
        self.imaps = list(imap_server) if isinstance(imap_server, (list, tuple)) else ([imap_server] if imap_server is not None else [])
        self.email = email
        self.username = None
        self.graph_when_oidc = False
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_host = redirect_host
        self.expires_in = expires_in
        self.rotate = rotate
        self.email_claim = email_claim
        self.deny = False
        self.codes = {}
        self.refresh_tokens = {}
        self.access_tokens = []
        self.authorize_requests = []
        self.token_requests = []
        self.errors = []
        self.issued = []
        self.revoked = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def reply(self, status, body, headers=None):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                if u.path != "/authorize":
                    self.reply(404, {"error": "not_found"})
                    return
                q = dict(urllib.parse.parse_qsl(u.query, keep_blank_values=True))
                outer.authorize_requests.append(q)
                redirect = q.get("redirect_uri", "")
                ru = urllib.parse.urlsplit(redirect)
                problems = []
                if q.get("client_id") != outer.client_id:
                    problems.append("client_id")
                if ru.scheme != "http" or ru.hostname != outer.redirect_host or not ru.port or ru.path != "/":
                    problems.append("redirect_uri")
                if q.get("response_type") != "code":
                    problems.append("response_type")
                if q.get("code_challenge_method") != "S256" or len(q.get("code_challenge", "")) != 43:
                    problems.append("pkce")
                if len(q.get("state", "")) < 16:
                    problems.append("state")
                if problems:
                    outer.errors.append("authorize: " + ",".join(problems))
                    self.reply(400, {"error": "invalid_request", "problems": problems})
                    return
                # prohlizec jde na 127.0.0.1 i kdyz je v adrese "localhost" (tam nasloucha Posta)
                target = "http://127.0.0.1:%d/" % ru.port
                if outer.deny:
                    location = target + "?" + urllib.parse.urlencode({"error": "access_denied", "error_description": "The user declined.", "state": q["state"]})
                else:
                    code = secrets.token_urlsafe(24)
                    outer.codes[code] = {"challenge": q["code_challenge"], "redirect_uri": redirect, "client_id": q["client_id"],
                                         "email": outer.email, "scope": q.get("scope", "")}
                    location = target + "?" + urllib.parse.urlencode({"code": code, "state": q["state"], "scope": q.get("scope", "")})
                self.send_response(302)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def issue(self, email, refresh=None, scope=""):
                access = "ya29." + secrets.token_urlsafe(32)
                outer.access_tokens.append(access)
                aud = "outlook"
                if outer.graph_when_oidc and set(scope.split()) & {"openid", "email", "profile"}:
                    aud = "graph"
                outer.issued.append(aud)
                for server in outer.imaps:
                    server.control("token %s %s %s" % (access, email, aud))
                body = {"access_token": access, "token_type": "Bearer", "expires_in": outer.expires_in,
                        "scope": "https://mail.google.com/"}
                if refresh is not None:
                    body["refresh_token"] = refresh
                claims = {"iss": "fake", "aud": outer.client_id, "sub": "1234"}
                if outer.email_claim:
                    claims["email"] = email
                else:
                    claims["preferred_username"] = email
                if outer.username is not None:
                    claims["preferred_username"] = outer.username
                body["id_token"] = jwt(claims)
                return body

            def do_POST(self):
                n = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(n).decode()
                f = dict(urllib.parse.parse_qsl(raw, keep_blank_values=True))
                outer.token_requests.append({"path": self.path, "form": f, "content_type": self.headers.get("Content-Type", "")})
                if self.path == "/revoke":
                    # jako oauth2.googleapis.com/revoke (RFC 7009): token jen v tele; odvolani obnovovaciho
                    # tokenu zrusi cele udeleni
                    tok = f.get("token", "")
                    outer.revoked.append(tok)
                    if outer.refresh_tokens.pop(tok, None) is None:
                        self.reply(400, {"error": "invalid_token", "error_description": "Token expired or revoked"})
                        return
                    self.reply(200, {})
                    return
                if self.path not in ("/token", "/consumers/token"):
                    self.reply(404, {"error": "not_found"})
                    return
                if f.get("client_id") != outer.client_id or (outer.client_secret and f.get("client_secret") != outer.client_secret):
                    self.reply(401, {"error": "invalid_client", "error_description": "Unauthorized client."})
                    return
                grant = f.get("grant_type")
                if grant == "authorization_code":
                    c = outer.codes.pop(f.get("code", ""), None)
                    if c is None:
                        self.reply(400, {"error": "invalid_grant", "error_description": "Bad code."})
                        return
                    verifier = f.get("code_verifier", "")
                    if b64url(hashlib.sha256(verifier.encode()).digest()) != c["challenge"] or not (43 <= len(verifier) <= 128):
                        outer.errors.append("token: pkce")
                        self.reply(400, {"error": "invalid_grant", "error_description": "PKCE verification failed."})
                        return
                    if f.get("redirect_uri") != c["redirect_uri"]:
                        outer.errors.append("token: redirect_uri")
                        self.reply(400, {"error": "invalid_grant", "error_description": "redirect_uri mismatch."})
                        return
                    refresh = "1//" + secrets.token_urlsafe(32)
                    outer.refresh_tokens[refresh] = c["email"]
                    self.reply(200, self.issue(c["email"], refresh, c["scope"]))
                    return
                if grant == "refresh_token":
                    rt = f.get("refresh_token", "")
                    email = outer.refresh_tokens.get(rt)
                    if email is None:
                        self.reply(400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
                        return
                    new = None
                    if outer.rotate:
                        new = "1//" + secrets.token_urlsafe(32)
                        del outer.refresh_tokens[rt]
                        outer.refresh_tokens[new] = email
                    self.reply(200, self.issue(email, new, f.get("scope", "")))
                    return
                self.reply(400, {"error": "unsupported_grant_type"})

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def origin(self):
        return "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def refreshes(self):
        return [r for r in self.token_requests if r["form"].get("grant_type") == "refresh_token"]

    def exchanges(self):
        return [r for r in self.token_requests if r["form"].get("grant_type") == "authorization_code"]

    def revoke_refresh(self):
        self.refresh_tokens.clear()

    def secrets_seen(self):
        """Vsechny vydane tokeny (pro kontrolu, ze nejsou v souborech ani v logu)."""
        return list(self.refresh_tokens.keys()) + list(self.access_tokens)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def follow(url, timeout=30):
    """Prohlizec: otevre adresu prihlaseni a nasleduje presmerovani na loopback. [stav, telo, hlavicky]"""
    status, body, headers = get(url, timeout)
    hops = 0
    while status in (301, 302, 303, 307) and hops < 5:
        status, body, headers = get(headers["location"], timeout)
        hops += 1
    return status, body, headers


def get(url, timeout=30):
    u = urllib.parse.urlsplit(url)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)
    path = u.path or "/"
    if u.query:
        path += "?" + u.query
    conn.request("GET", path, headers={"User-Agent": "Mozilla/5.0 (LuxOS test browser)", "Accept": "text/html"})
    r = conn.getresponse()
    body = r.read().decode("utf-8", "replace")
    headers = {k.lower(): v for k, v in r.getheaders()}
    conn.close()
    return r.status, body, headers


def providers_file(path, google=None, microsoft=None, google_imap=None, microsoft_imap=None, google_id="test-google-client.apps.example",
                   google_secret="GOCSPX-test-secret", microsoft_id="00000000-1111-2222-3333-444444444444", microsoft_alt_imap=None,
                   google_smtp=None, microsoft_smtp=None):
    """oauth-providers.json pro test: koncove body falesnych poskytovatelu, IMAP na falesny server."""
    with open(path_of_shipped()) as f:
        data = json.load(f)
    g = data["providers"]["google"]
    m = data["providers"]["microsoft"]
    if google is not None:
        g["auth_url"] = google.origin + "/authorize"
        g["token_url"] = google.origin + "/token"
        g["revoke_url"] = google.origin + "/revoke"
        g["client_id"] = google_id
        g["client_secret"] = google_secret
    if google_imap is not None:
        g["imap"] = {"host": "localhost", "port": google_imap, "security": "ssl"}
    if microsoft is not None:
        m["auth_url"] = microsoft.origin + "/authorize"
        m["token_url"] = microsoft.origin + "/token"
        m["client_id"] = microsoft_id
        m["consumer_token_url"] = microsoft.origin + "/consumers/token"
    if microsoft_imap is not None:
        m["imap"] = {"host": "localhost", "port": microsoft_imap, "security": "ssl"}
        # nahradni server (imap-mail.outlook.com) nikdy skutecny: jinak falesny, nebo zadny
        m["imap_alternates"] = []
    # SMTP nikdy skutecny Google/Microsoft: falesny server testu, jinak zavreny mistni port
    g["smtp"] = google_smtp or {"host": "localhost", "port": 9, "security": "ssl"}
    m["smtp"] = microsoft_smtp or {"host": "localhost", "port": 9, "security": "starttls"}
    if microsoft_alt_imap is not None:
        m["imap_alternates"] = [{"host": "localhost", "port": microsoft_alt_imap, "security": "ssl"}]
    with open(path, "w") as f:
        json.dump(data, f)
    return path


def path_of_shipped():
    import os
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "files", "oauth-providers.json")
