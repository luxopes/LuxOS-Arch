# Posta LuxOS - prihlaseni u poskytovatele pres OAuth2 ("Prihlasit se Googlem/Microsoftem") pro nativni
# aplikace podle RFC 8252: systemovy prohlizec (xdg-open), presmerovani na loopback
# http://127.0.0.1:<nahodny port>/ (Microsoft: http://localhost:<port>/, port se u "localhost" neporovnava),
# PKCE S256 (RFC 7636) a nahodny "state". Tady jsou data poskytovatelu, sestaveni adresy, vymena kodu
# a obnoveni tokenu (bez GLib a bez okna); naslouchani a ucty ridi sluzba (mail_service).
#
# Poskytovatele (data, ne kod):
#   /usr/share/luxos-mail/oauth-providers.json   s balikem: koncove body, rozsahy, servery IMAP/SMTP, client ID
#   /etc/luxos/mail-oauth.json                   volitelne prepsani spravcem (cele polozky nebo jen client_id);
#                                                {"remote": false} vypne stahovani ID ze serveru LuxOS
#   ~/.cache/luxos-mail/mail-oauth.json          ID stazena z https://luxos.lux-ai.cz/mail-oauth.json (jen
#                                                verejne client_id a "tajemstvi" instalovane aplikace Google;
#                                                vyplni jen prazdna ID, koncove body nikdy nemeni)
# Prazdne client_id = poskytovatel bez OAuth (okno nabidne heslo aplikace jako drive).
# Testy: LUXOS_MAIL_OAUTH_PROVIDERS, LUXOS_MAIL_OAUTH_ADMIN, LUXOS_MAIL_OAUTH_REMOTE (adresa, "off" vypne).
#
# Obnovovaci token je jen v klicence (mail_secret, jako hesla); pristupovy token jen v pameti sluzby.
# Tokeny nikdy v argumentech programu, v souborech Posty ani v logu (curl dostava telo na stdin).
load env, json, http, net
load crypto
load luxos_glib, glib as glib
load mail_mime as mime

SHIPPED = "/usr/share/luxos-mail/oauth-providers.json"
ADMIN = "/etc/luxos/mail-oauth.json"
REMOTE = "https://luxos.lux-ai.cz/mail-oauth.json"
REMOTE_MAX_AGE = 86400
ID_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
KEY_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789_"
UNRESERVED = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
HEX = "0123456789ABCDEF"

function env_or(name, fallback):
    value = env.get(name, "")
    if value == None or value == "":
        return fallback
    end
    return value
end

function cache_path():
    base = env.get("XDG_CACHE_HOME", "")
    if base == None or base == "":
        base = glib.home_dir() + "/.cache"
    end
    return base + "/luxos-mail/mail-oauth.json"
end

function read_json(path):
    if path == "" or not exists(path):
        return None
    end
    data = None
    safe:
        data = json.decode(readfile(path))
    end
    return data
end

# ---- kontrola dat -----------------------------------------------------------------------------------------------

function safe_id(value, limit):
    if type(value) != "String" or len(value) > limit:
        return False
    end
    for c in value:
        if c not in ID_CHARS:
            return False
        end
    end
    return True
end

# Koncovy bod: jen HTTPS (testy: http://127.0.0.1, modul http jinde HTTP stejne odmitne)
function safe_endpoint(value):
    if type(value) != "String" or len(value) > 512 or value.find(" ") >= 0 or value.find("?") >= 0 or value.find("#") >= 0:
        return False
    end
    return value.startswith("https://") or value.startswith("http://127.0.0.1:")
end

function safe_text(value, limit):
    if type(value) != "String" or len(value) > limit:
        return False
    end
    for c in value:
        if ord(c) < 32 or ord(c) == 127:
            return False
        end
    end
    return True
end

function server(value, default_port, default_security):
    if type(value) != "Dictionary":
        return {}
    end
    host = String(value.get("host", "")).strip().lower()
    port = value.get("port", default_port)
    security = String(value.get("security", default_security))
    if host == "" or len(host) > 253 or host.find(" ") >= 0 or host.find("/") >= 0 or type(port) != "Int" or port < 1 or port > 65535:
        return {}
    end
    if security != "ssl" and security != "starttls":
        return {}
    end
    return {"host": host, "port": port, "security": security}
end

# Polozka poskytovatele ze souboru baliku nebo spravce -> zkontrolovany slovnik, nebo {} (neplatna)
function clean_provider(id, p):
    if type(p) != "Dictionary":
        return {}
    end
    out = {"id": id, "name": String(p.get("name", id)), "enabled": p.get("enabled", True) == True}
    if not safe_text(out["name"], 40):
        return {}
    end
    for key in ["auth_url", "token_url"]:
        if not safe_endpoint(p.get(key, "")):
            return {}
        end
        out[key] = p[key]
    end
    scope = p.get("scope", "")
    if not safe_text(scope, 1000) or scope.strip() == "":
        return {}
    end
    out["scope"] = scope.strip()
    cid = p.get("client_id", "")
    secret = p.get("client_secret", "")
    if not safe_id(cid, 256) or not safe_id(secret, 256):
        return {}
    end
    out["client_id"] = cid
    out["client_secret"] = secret
    out["secret_required"] = p.get("secret_required", False) == True
    host = String(p.get("redirect_host", "127.0.0.1"))
    if host != "127.0.0.1" and host != "localhost":
        return {}
    end
    out["redirect_host"] = host
    port = p.get("redirect_port", 0)
    if type(port) != "Int" or port < 0 or port > 65535:
        return {}
    end
    out["redirect_port"] = port
    extra = p.get("auth_params", {})
    if type(extra) != "Dictionary":
        return {}
    end
    params = {}
    for k in extra.keys():
        v = extra[k]
        if type(k) != "String" or len(k) == 0 or len(k) > 40 or not safe_text(v, 200):
            return {}
        end
        for c in k:
            if c not in KEY_CHARS:
                return {}
            end
        end
        if k in ["client_id", "redirect_uri", "response_type", "state", "code_challenge", "code_challenge_method", "scope"]:
            return {}
        end
        params[k] = v
    end
    out["auth_params"] = params
    out["refresh_scope"] = p.get("refresh_scope", False) == True
    imap = server(p.get("imap"), 993, "ssl")
    if len(imap) == 0:
        return {}
    end
    out["imap"] = imap
    out["smtp"] = server(p.get("smtp"), 465, "ssl")
    return out
end

# ---- nacteni poskytovatelu ----------------------------------------------------------------------------------------

function admin_data():
    data = read_json(env_or("LUXOS_MAIL_OAUTH_ADMIN", ADMIN))
    if type(data) != "Dictionary":
        return {}
    end
    return data
end

function remote_url():
    url = env_or("LUXOS_MAIL_OAUTH_REMOTE", REMOTE)
    if url == "off" or admin_data().get("remote", True) == False:
        return ""
    end
    return url
end

# Jen client_id/client_secret ze stazeneho souboru (vse ostatni se ignoruje): {id: {"client_id", "client_secret"}}
function remote_ids(data):
    out = {}
    if type(data) != "Dictionary" or data.get("version", 0) != 1 or type(data.get("providers")) != "Dictionary":
        return out
    end
    for id in data["providers"].keys():
        p = data["providers"][id]
        if type(id) != "String" or type(p) != "Dictionary":
            continue
        end
        cid = p.get("client_id", "")
        secret = p.get("client_secret", "")
        if cid == "" or not safe_id(cid, 256) or not safe_id(secret, 256):
            continue
        end
        out[id] = {"client_id": cid, "client_secret": secret}
    end
    return out
end

function cached_remote():
    data = read_json(cache_path())
    if type(data) != "Dictionary":
        return {}
    end
    return remote_ids(data.get("data"))
end

# Vsichni poskytovatele: {id: polozka}. Poradi: balik -> spravce (cela polozka nebo jen ID) -> stazena ID
# (jen kde ID chybi)
function providers():
    shipped = read_json(env_or("LUXOS_MAIL_OAUTH_PROVIDERS", SHIPPED))
    out = {}
    if type(shipped) != "Dictionary" or type(shipped.get("providers")) != "Dictionary":
        return out
    end
    admin = admin_data().get("providers", {})
    if type(admin) != "Dictionary":
        admin = {}
    end
    remote = cached_remote()
    for id in shipped["providers"].keys():
        raw = shipped["providers"][id]
        if type(raw) != "Dictionary":
            continue
        end
        merged = {}
        for k in raw.keys():
            merged[k] = raw[k]
        end
        over = admin.get(id, None)
        if type(over) == "Dictionary":
            for k in over.keys():
                merged[k] = over[k]
            end
        end
        p = clean_provider(id, merged)
        if len(p) == 0:
            continue
        end
        if p["client_id"] == "" and id in remote:
            p["client_id"] = remote[id]["client_id"]
            p["client_secret"] = remote[id]["client_secret"]
        end
        out[id] = p
    end
    return out
end

function provider(id):
    all = providers()
    if id in all:
        return all[id]
    end
    return {}
end

# Poskytovatel s vyplnenym client ID (tlacitko "Prihlasit se ..." v okne); {} = jen heslo
function available(id):
    p = provider(id)
    if len(p) == 0 or not p["enabled"] or p["client_id"] == "":
        return {}
    end
    if p["secret_required"] and p["client_secret"] == "":
        return {}
    end
    return p
end

# Je potreba stahnout ID? (nejaky zapnuty poskytovatel bez ID a mezipamet starsi nez den)
function remote_due():
    if remote_url() == "":
        return False
    end
    missing = False
    for p in providers().values():
        if p["enabled"] and p["client_id"] == "":
            missing = True
        end
    end
    if not missing:
        return False
    end
    data = read_json(cache_path())
    if type(data) == "Dictionary" and type(data.get("fetched")) == "Int" and glib.now() - data["fetched"] < REMOTE_MAX_AGE and data["fetched"] <= glib.now():
        return False
    end
    return True
end

# Stazeni ID (luxos-mail --oauth-config): {"ok", "providers": [id, ...]} nebo {"ok": False, "error"}
function fetch_remote():
    url = remote_url()
    if url == "":
        return {"ok": False, "error": "disabled"}
    end
    resp = {}
    ok = True
    try:
        resp = http.get(url, {"Accept": "application/json"}, 10)
    else:
        ok = False
    end
    if not ok or not resp.get("ok", False):
        return {"ok": False, "error": "unreachable"}
    end
    if len(resp["text"]) > 65536:
        return {"ok": False, "error": "too large"}
    end
    data = None
    safe:
        data = json.decode(resp["text"])
    end
    ids = remote_ids(data)
    if type(data) != "Dictionary" or data.get("version", 0) != 1:
        return {"ok": False, "error": "invalid"}
    end
    # ulozit jen zkontrolovana ID znamych poskytovatelu (nic jineho z odpovedi)
    known = providers()
    kept = {}
    for id in ids.keys():
        if id in known:
            kept[id] = ids[id]
        end
    end
    ids = kept
    clean = {"version": 1, "providers": ids}
    path = cache_path()
    parts = path.split("/")
    call glib.mkdir_p("/".join(parts[0:len(parts) - 1]))
    call glib.write_atomic(path, json.encode({"fetched": glib.now(), "data": clean}) + "\n")
    return {"ok": True, "providers": List(ids.keys())}
end

# ---- PKCE, kodovani ----------------------------------------------------------------------------------------------

function b64url(data):
    return mime.b64_encode(data).replace("+", "-").replace("/", "_").replace("=", "")
end

function b64url_decode(text):
    t = String(text).replace("-", "+").replace("_", "/")
    while len(t) % 4 != 0:
        t = t + "="
    end
    b = net.bytes(t)
    return mime.b64_decode(b, 0, len(b))
end

function random_token(n):
    return b64url(crypto.random_bytes(n))
end

function challenge(verifier):
    return b64url(crypto.sha256(verifier))
end

function percent(value):
    out = []
    for c in net.bytes(String(value)):
        ch = chr(c)
        if c < 128 and ch in UNRESERVED:
            out.append(ch)
        else:
            out.append("%" + HEX[c >> 4] + HEX[c & 15])
        end
    end
    return "".join(out)
end

# [[klic, hodnota], ...] -> "k=v&k2=v2"
function form(pairs):
    out = []
    for p in pairs:
        out.append(percent(p[0]) + "=" + percent(p[1]))
    end
    return "&".join(out)
end

# Parametry dotazu "a=1&b=%20" -> {"a": "1", "b": " "} ("+" je mezera)
function parse_query(q):
    out = {}
    for part in String(q).split("&"):
        if part == "":
            continue
        end
        eq = part.find("=")
        k = part
        v = ""
        if eq >= 0:
            k = part[0:eq]
            v = part[eq + 1:]
        end
        k = net.text(mime.percent_decode(k.replace("+", " ")))
        v = net.text(mime.percent_decode(v.replace("+", " ")))
        if k not in out:
            out[k] = v
        end
    end
    return out
end

function redirect_uri(p, port):
    return "http://" + p["redirect_host"] + ":" + String(port) + "/"
end

# Adresa pro prohlizec
function authorize_url(p, port, state, verifier, login_hint):
    pairs = [["response_type", "code"], ["client_id", p["client_id"]], ["redirect_uri", redirect_uri(p, port)],
             ["scope", p["scope"]], ["state", state], ["code_challenge", challenge(verifier)], ["code_challenge_method", "S256"]]
    keys = List(p["auth_params"].keys())
    keys.sort()
    for k in keys:
        pairs.append([k, p["auth_params"][k]])
    end
    if login_hint != "" and safe_text(login_hint, 254):
        pairs.append(["login_hint", login_hint])
    end
    return p["auth_url"] + "?" + form(pairs)
end

# ---- koncovy bod tokenu ----------------------------------------------------------------------------------------------

# Odpoved koncoveho bodu tokenu -> {"ok": True, "access_token", "refresh_token", "expires_in", "id_token"} nebo
# {"ok": False, "kind", "error"}. Druhy: connect (sit), oauth_expired (invalid_grant: obnovovaci token
# neplati - prihlasit znovu), oauth_config (spatne client ID/tajemstvi), oauth_server (jine)
function token_request(p, pairs, refreshing):
    pairs.append(["client_id", p["client_id"]])
    if p["client_secret"] != "":
        pairs.append(["client_secret", p["client_secret"]])
    end
    resp = {}
    ok = True
    try:
        resp = http.post(p["token_url"], form(pairs), {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}, 20)
    else:
        ok = False
    end
    if not ok:
        return {"ok": False, "kind": "connect", "error": String(last_error())}
    end
    status = resp.get("status", 0)
    if status == 0:
        return {"ok": False, "kind": "connect", "error": String(resp.get("text", "")).strip()[0:300]}
    end
    data = None
    safe:
        data = json.decode(resp.get("text", ""))
    end
    if type(data) != "Dictionary":
        data = {}
    end
    if not resp["ok"]:
        code = String(data.get("error", ""))
        desc = String(data.get("error_description", ""))
        clean = []
        for c in (code + ": " + desc)[0:300]:
            if ord(c) >= 32:
                clean.append(c)
            end
        end
        text = "".join(clean)
        if code == "invalid_grant":
            if refreshing:
                return {"ok": False, "kind": "oauth_expired", "error": text}
            end
            return {"ok": False, "kind": "oauth_failed", "error": text}
        elif code == "invalid_client" or code == "unauthorized_client":
            return {"ok": False, "kind": "oauth_config", "error": text}
        end
        if code == "":
            text = "HTTP " + String(status)
        end
        return {"ok": False, "kind": "oauth_server", "error": text}
    end
    access = data.get("access_token", "")
    if type(access) != "String" or access == "" or len(access) > 8192:
        return {"ok": False, "kind": "oauth_server", "error": "No access token in the answer."}
    end
    expires = data.get("expires_in", 3600)
    if type(expires) == "String":
        expires = mime.to_int(expires, 3600)
    end
    if type(expires) != "Int" or expires <= 0:
        expires = 3600
    end
    refresh = data.get("refresh_token", "")
    if type(refresh) != "String" or len(refresh) > 8192:
        refresh = ""
    end
    idt = data.get("id_token", "")
    if type(idt) != "String":
        idt = ""
    end
    return {"ok": True, "access_token": access, "refresh_token": refresh, "expires_in": expires, "id_token": idt}
end

function exchange_code(p, code, verifier, port):
    return token_request(p, [["grant_type", "authorization_code"], ["code", code], ["redirect_uri", redirect_uri(p, port)],
                             ["code_verifier", verifier]], False)
end

function refresh(p, refresh_token):
    pairs = [["grant_type", "refresh_token"], ["refresh_token", refresh_token]]
    if p["refresh_scope"]:
        pairs.append(["scope", p["scope"]])
    end
    return token_request(p, pairs, True)
end

# E-mail z id_token (OpenID Connect). Token prisel primo z koncoveho bodu tokenu pres TLS, podpis se proto
# neoveruje (OpenID Connect Core 3.1.3.7). {"email", "username"} ("" kdyz chybi)
function id_token_identity(idt):
    out = {"email": "", "username": ""}
    parts = String(idt).split(".")
    if len(parts) < 2 or len(parts[1]) > 16384:
        return out
    end
    data = None
    safe:
        data = json.decode(net.text(b64url_decode(parts[1])))
    end
    if type(data) != "Dictionary":
        return out
    end
    e = data.get("email", "")
    if type(e) == "String" and e.find("@") > 0 and safe_text(e, 254):
        out["email"] = e.strip()
    end
    u = data.get("preferred_username", "")
    if type(u) == "String" and safe_text(u, 254):
        out["username"] = u.strip()
    end
    return out
end

# Adresa schranky: e-mail z id_token (uzivatel se v prohlizeci mohl prihlasit jinym uctem nez zadal),
# jinak zadana adresa, jinak preferred_username (Microsoft)
function mailbox_address(typed, identity):
    t = String(typed).strip()
    e = identity.get("email", "")
    if e != "":
        if t != "" and t.lower() == e.lower():
            return t
        end
        return e
    end
    if t != "":
        return t
    end
    u = identity.get("username", "")
    if u.find("@") > 0:
        return u
    end
    return ""
end

# ---- stranka v prohlizeci po prihlaseni -----------------------------------------------------------------------------

function html_escape(text):
    return String(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;")
end

# Mala stranka "Vratit se do Posty" ve vzhledu LuxOS (svetly i tmavy rezim, bez externich zdroju)
function page(lang, title, text, button, ok):
    accent = "#0a84ff"
    if not ok:
        accent = "#e0a100"
    end
    icon = "<svg width=\"64\" height=\"64\" viewBox=\"0 0 64 64\" aria-hidden=\"true\"><rect x=\"6\" y=\"14\" width=\"52\" height=\"36\" rx=\"7\" fill=\"" + accent + "\"/><path d=\"M10 19l22 16 22-16\" fill=\"none\" stroke=\"#fff\" stroke-width=\"4\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/></svg>"
    css = ":root{color-scheme:light dark;--bg:#f5f5f7;--card:#fff;--fg:#1d1d1f;--dim:#6e6e73}@media (prefers-color-scheme:dark){:root{--bg:#1c1c1e;--card:#2c2c2e;--fg:#f5f5f7;--dim:#a1a1a6}}body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:var(--bg);color:var(--fg);font:15px/1.5 Inter,\"SF Pro Text\",Cantarell,\"Noto Sans\",sans-serif}main{background:var(--card);border-radius:16px;padding:36px 40px;max-width:420px;margin:16px;text-align:center;box-shadow:0 10px 40px rgba(0,0,0,.12)}h1{font-size:22px;margin:14px 0 8px}p{color:var(--dim);margin:0 0 22px}button{font:inherit;font-weight:600;color:#fff;background:" + accent + ";border:0;border-radius:8px;padding:9px 22px;cursor:pointer}"
    return "<!doctype html><html lang=\"" + html_escape(lang) + "\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>" + html_escape(title) + "</title><style>" + css + "</style></head><body><main>" + icon + "<h1>" + html_escape(title) + "</h1><p>" + html_escape(text) + "</p><button type=\"button\" onclick=\"window.close()\">" + html_escape(button) + "</button></main></body></html>"
end

function http_response(status, reason, body):
    b = net.bytes(body)
    return "HTTP/1.1 " + String(status) + " " + reason + "\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: " + String(len(b)) + "\r\nCache-Control: no-store\r\nReferrer-Policy: no-referrer\r\nX-Content-Type-Options: nosniff\r\nContent-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'\r\nConnection: close\r\n\r\n" + body
end

# Prvni radek pozadavku "GET /?code=..&state=.. HTTP/1.1" -> {"method", "path", "query"} nebo {}
function parse_request_line(text):
    end_line = text.find("\r\n")
    if end_line < 0:
        end_line = text.find("\n")
    end
    if end_line < 0:
        return {}
    end
    parts = text[0:end_line].split(" ")
    if len(parts) != 3 or not parts[2].startswith("HTTP/1."):
        return {}
    end
    target = parts[1]
    q = ""
    qm = target.find("?")
    path = target
    if qm >= 0:
        path = target[0:qm]
        q = target[qm + 1:]
    end
    return {"method": parts[0], "path": path, "query": parse_query(q)}
end
