# Posta LuxOS - ucet LuxAI tohoto pocitace a schranky na serveru LuxAI (Prihlaseni uctem LuxAI).
# Ucet: ~/.config/luxai/account.json (zapisuje jen luxos-account a instalator; Posta ho jen cte).
#   GET  <origin>/api/mail/mailboxes   schranky, ke kterym ma ucet pristup (napr. info@lux-ai.cz)
#   POST <origin>/api/mail/token       {"address"} -> kratkodoby pristupovy token pro IMAP/SMTP
#                                      (SASL OAUTHBEARER/XOAUTH2); Posta ho nikam neuklada
# Session token uctu jde jen na origin uctu jako cookie (config curl na stdin, nikdy v argumentech ani
# v logu). LUXAI_ORIGIN prepise origin (testy), stejne jako v luxai_account.py.
load env, json, http
load luxos_glib, glib as glib

CLIENT = "luxos"
COOKIE = "lux_account_session"
TOKEN_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"

function account_path():
    base = env.get("XDG_CONFIG_HOME", "")
    if base == None or base == "":
        base = glib.home_dir() + "/.config"
    end
    return base + "/luxai/account.json"
end

# {"origin", "token", "user"} nebo {} (neprihlaseno, poskozeny soubor)
function load_account():
    path = account_path()
    if not exists(path):
        return {}
    end
    data = None
    safe:
        data = json.decode(readfile(path))
    end
    if type(data) != "Dictionary":
        return {}
    end
    token = data.get("sessionToken", "")
    if type(token) != "String" or token == "" or len(token) > 512:
        return {}
    end
    # jen znaky cookie (base64url); jinak by se token mohl rozpadnout v hlavicce
    for c in token:
        if c not in TOKEN_CHARS:
            return {}
        end
    end
    site = env.get("LUXAI_ORIGIN", "")
    if site == None or site == "":
        site = data.get("origin", "")
    end
    if type(site) != "String" or site == "":
        site = "https://lux-ai.cz"
    end
    while site.endswith("/"):
        site = site[0:len(site) - 1]
    end
    user = data.get("user", {})
    if type(user) != "Dictionary":
        user = {}
    end
    return {"origin": site, "token": token, "user": user}
end

# Prihlaseny ucet bez tokenu (pro okno): {"name", "email", "username", "id"} nebo {}
function account_user():
    a = load_account()
    if len(a) == 0:
        return {}
    end
    u = a["user"]
    email = String(u.get("email", "")).strip()
    name = String(u.get("displayName", "")).strip()
    if name == "":
        name = String(u.get("username", "")).strip()
    end
    if name == "":
        name = email
    end
    return {"name": name, "email": email, "username": String(u.get("username", "")), "id": String(u.get("id", ""))}
end

function headers(a):
    return {"Cookie": COOKIE + "=" + a["token"], "X-Lux-Client": CLIENT, "Accept": "application/json"}
end

# Chybova odpoved -> {"ok": False, "kind", "error"}; druhy: luxai_signedout (zadny ucet), luxai_session
# (401: prihlaseni vyprselo), luxai_denied (403: ucet ke schrance nema pristup), luxai_rate (429),
# connect (sit), luxai_server (jine)
function failure(resp):
    status = resp.get("status", 0)
    code = ""
    safe:
        body = json.decode(resp.get("text", ""))
        if type(body) == "Dictionary":
            code = String(body.get("error", ""))
        end
    end
    if status == 0:
        return {"ok": False, "kind": "connect", "error": String(resp.get("text", "")).strip()}
    elif status == 401:
        return {"ok": False, "kind": "luxai_session", "error": "Your LuxAI sign-in has expired."}
    elif status == 403:
        return {"ok": False, "kind": "luxai_denied", "error": "The LuxAI account has no access (" + code + ")."}
    elif status == 429:
        return {"ok": False, "kind": "luxai_rate", "error": "Too many requests to LuxAI, try again later."}
    end
    return {"ok": False, "kind": "luxai_server", "error": "LuxAI answered HTTP " + String(status) + " " + code}
end

function call_api(method, path, body):
    a = load_account()
    if len(a) == 0:
        return {"ok": False, "kind": "luxai_signedout", "error": "No LuxAI account is signed in on this computer."}
    end
    resp = {}
    ok = True
    try:
        if method == "GET":
            resp = http.get(a["origin"] + path, headers(a), 15)
        else:
            h = headers(a)
            h["Content-Type"] = "application/json"
            resp = http.post(a["origin"] + path, body, h, 15)
        end
    else:
        ok = False
    end
    if not ok:
        # chyba muze obsahovat jen URL a text curl, nikdy token (ten je jen v configu na stdin)
        return {"ok": False, "kind": "connect", "error": String(last_error())}
    end
    if not resp["ok"]:
        return failure(resp)
    end
    data = None
    safe:
        data = json.decode(resp["text"])
    end
    if type(data) != "Dictionary":
        return {"ok": False, "kind": "luxai_server", "error": "LuxAI sent an invalid answer."}
    end
    return {"ok": True, "data": data, "user": a["user"]}
end

function server_settings(value, default_port):
    if type(value) != "Dictionary":
        return {}
    end
    host = String(value.get("host", "")).strip().lower()
    port = value.get("port", default_port)
    security = String(value.get("security", "ssl"))
    if host == "" or host.find(" ") >= 0 or host.find("/") >= 0 or type(port) != "Int" or port < 1 or port > 65535:
        return {}
    end
    if security != "ssl" and security != "starttls":
        return {}
    end
    return {"host": host, "port": port, "security": security}
end

# {"ok": True, "mailboxes": [{"address", "display_name", "imap", "smtp"}], "user": {...}} nebo chyba
function mailboxes():
    r = call_api("GET", "/api/mail/mailboxes", None)
    if not r["ok"]:
        return r
    end
    out = []
    list = r["data"].get("mailboxes", [])
    if type(list) != "List":
        list = []
    end
    for m in list:
        if type(m) != "Dictionary":
            continue
        end
        address = String(m.get("address", "")).strip().lower()
        imap = server_settings(m.get("imap"), 993)
        if address.find("@") <= 0 or len(imap) == 0 or m.get("auth", "luxai-oauth") != "luxai-oauth":
            continue
        end
        imap["user"] = address
        smtp = server_settings(m.get("smtp"), 465)
        if len(smtp) > 0:
            smtp["user"] = address
        end
        name = String(m.get("display_name", "")).strip()
        out.append({"address": address, "display_name": name, "imap": imap, "smtp": smtp})
    end
    return {"ok": True, "mailboxes": out, "user": r["user"]}
end

# Pristupovy token pro schranku: {"ok": True, "token", "expires_in"} nebo chyba
function token(address):
    r = call_api("POST", "/api/mail/token", {"address": address})
    if not r["ok"]:
        return r
    end
    t = r["data"].get("access_token", "")
    if type(t) != "String" or t == "" or len(t) > 1024:
        return {"ok": False, "kind": "luxai_server", "error": "LuxAI sent no access token."}
    end
    if String(r["data"].get("address", address)).lower() != address.lower():
        return {"ok": False, "kind": "luxai_server", "error": "LuxAI sent a token for another mailbox."}
    end
    return {"ok": True, "token": t, "expires_in": r["data"].get("expires_in", 0)}
end
