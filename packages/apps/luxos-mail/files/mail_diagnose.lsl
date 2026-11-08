# Posta LuxOS - diagnostika prihlaseni u poskytovatele (luxos-mail --diagnose-oauth ADRESA).
#   luxos-mail --diagnose-oauth ADRESA [--fresh] [--provider google|microsoft]
# Ziska pristupovy token (obnovovaci token uctu z klicenky, jinak / s --fresh nove prihlaseni v prohlizeci
# pres loopback jako okno) a vyzkousi vsechny varianty prihlaseni IMAP (adresa user=, token jen pro Outlook,
# /consumers, jiny server). Vypise ocistenou zpravu: varianta -> odpoved serveru. Nikdy nevypise token;
# adresy jen castecne (tw***r@outlook.com). Nic neuklada (krome rotace obnovovaciho tokenu uz ulozeneho uctu).
# Navratovy kod: 0 = nektera varianta otevrela schranku, 1 = zadna, 2 = prihlaseni/token selhalo.
load env, json, net
load crypto
load luxos_glib, glib as glib
load mail_bytes as mb
load mail_imap as imap
load mail_oauth as oauth
load mail_oauth_login as ol
load mail_provider as provider
load mail_secret as secret
load mail_store as store

# Osobni ucty Microsoft (outlook.com, hotmail.com ...) maji v id_token tento tenant
MSA_TENANT = "9188040d-6c67-4c5b-b112-36a304b66dad"

function say(text):
    print text
    return 0
end

# "twibr@outlook.com" -> "tw***r@outlook.com"
function mask(address):
    a = String(address)
    at = a.find("@")
    if at < 0:
        if a == "":
            return "-"
        end
        return "***"
    end
    name = a[0:at]
    if len(name) <= 3:
        return name[0:1] + "***" + a[at:]
    end
    return name[0:2] + "***" + name[len(name) - 1:] + a[at:]
end

function compare(address, typed):
    if address == "":
        return "-"
    end
    if address == typed:
        return mask(address) + " (same as typed)"
    end
    if address.lower() == typed.lower():
        return mask(address) + " (same as typed, different letter case)"
    end
    return mask(address) + " (DIFFERENT from typed)"
end

# Nepodepsane cteni casti JWT (jen pro zpravu; tokeny prisly primo z koncoveho bodu pres TLS)
function jwt_claims(token):
    parts = String(token).split(".")
    if len(parts) != 3 or len(parts[1]) > 16384:
        return {}
    end
    data = None
    safe:
        data = json.decode(net.text(oauth.b64url_decode(parts[1])))
    end
    if type(data) != "Dictionary":
        return {}
    end
    return data
end

function claim(d, key):
    v = d.get(key, "")
    if type(v) == "List":
        return " ".join(v)
    end
    return ol.clean(String(v))
end

# Popis pristupoveho tokenu bez tokenu: JWT (pracovni ucty) -> aud, scp; jinak nepruhledny (osobni ucty)
function describe_access(token, typed):
    c = jwt_claims(token)
    if len(c) == 0:
        call say("  access token: opaque, " + String(len(token)) + " characters (normal for personal Microsoft accounts and Google)")
        return 0
    end
    call say("  access token: JWT, audience (aud) = " + claim(c, "aud"))
    call say("  access token scopes (scp) = " + claim(c, "scp"))
    u = claim(c, "upn")
    if u == "":
        u = claim(c, "unique_name")
    end
    if u != "":
        call say("  access token user = " + compare(u, typed))
    end
    return 0
end

function describe_id(idt, typed):
    c = jwt_claims(idt)
    if len(c) == 0:
        call say("  id_token: none")
        return 0
    end
    call say("  id_token email = " + compare(claim(c, "email"), typed))
    call say("  id_token preferred_username = " + compare(claim(c, "preferred_username"), typed))
    tid = claim(c, "tid")
    if tid != "":
        kind = "work or school account (Entra ID tenant)"
        if tid == MSA_TENANT:
            kind = "personal Microsoft account"
        end
        call say("  id_token tenant = " + tid + " (" + kind + ")")
    end
    return 0
end

# ---- prihlaseni v prohlizeci (blokujici, bez GLib) ------------------------------------------------------------

function open_browser(url):
    log_path = env.get("LUXOS_MAIL_OPEN_URL_LOG", "")
    if log_path != None and log_path != "":
        safe:
            prev = ""
            if exists(log_path):
                prev = readfile(log_path)
            end
            call writefile(log_path, prev + url + "\n")
        end
        return 0
    end
    safe:
        call glib.spawn_quiet(["xdg-open", url])
    end
    return 0
end

function reply(fd, title, text, ok):
    body = oauth.page("en", title, text, "Close", ok)
    safe:
        call net.send(fd, oauth.http_response(200, "OK", body), 5000)
    end
    safe:
        call net.close(fd)
    end
    return 0
end

# Ceka na presmerovani prohlizece na loopback: kod, nebo {"ok": False, "error"}
function wait_code(listeners, state, seconds):
    deadline = glib.now() + seconds
    while glib.now() < deadline:
        for lfd in listeners:
            r = []
            safe:
                r = net.accept(lfd, 200)
            end
            if len(r) == 0:
                continue
            end
            fd = r[0]
            if r[1] != "127.0.0.1" and r[1] != "::1":
                safe:
                    call net.close(fd)
                end
                continue
            end
            buf = ByteArray()
            ok = True
            loop:
                data = ByteArray()
                try:
                    data = net.recv(fd, 16384, 5000)
                else:
                    ok = False
                    break
                end
                if len(data) == 0:
                    break
                end
                buf = mb.concat(buf, data)
                t = net.text(buf)
                if t.find("\r\n\r\n") >= 0 or t.find("\n\n") >= 0 or len(buf) > 32768:
                    break
                end
            end
            req = oauth.parse_request_line(net.text(buf))
            if not ok or len(req) == 0 or req["method"] != "GET" or req["path"] != "/":
                safe:
                    call net.send(fd, "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n", 2000)
                    call net.close(fd)
                end
                continue
            end
            q = req["query"]
            got = String(q.get("state", ""))
            if len(got) != len(state) or not crypto.constant_time_equal(got, state):
                call reply(fd, "Signing in did not finish", "This sign-in page is out of date.", False)
                continue
            end
            if "error" in q:
                call reply(fd, "Signing in did not finish", "Return to the terminal.", False)
                return {"ok": False, "error": ol.clean(String(q["error"]) + ": " + String(q.get("error_description", "")))}
            end
            code = String(q.get("code", ""))
            if code == "" or len(code) > 4096:
                call reply(fd, "Signing in did not finish", "Return to the terminal.", False)
                return {"ok": False, "error": "no authorization code"}
            end
            call reply(fd, "You are signed in", "LuxOS Mail diagnostics continue in the terminal. You can close this page.", True)
            return {"ok": True, "code": code}
        end
    end
    return {"ok": False, "error": "the sign-in in the browser did not finish within " + String(seconds) + " seconds"}
end

function browser_sign_in(p, typed):
    listeners = []
    port = 0
    try:
        fd = net.tcp_listen("127.0.0.1", p["redirect_port"], 16)
        listeners.append(fd)
        port = net.local_address(fd)[1]
    else:
        return {"ok": False, "kind": "oauth_listen", "error": String(last_error())}
    end
    if p["redirect_host"] == "localhost":
        safe:
            listeners.append(net.tcp_listen("::1", port, 16))
        end
    end
    state = oauth.random_token(24)
    verifier = oauth.random_token(48)
    url = oauth.authorize_url(p, port, state, verifier, typed)
    call say("Sign in in the browser. If no browser opened, open this address:")
    call say("  " + url)
    call open_browser(url)
    w = wait_code(listeners, state, 600)
    for fd in listeners:
        safe:
            call net.close(fd)
        end
    end
    if not w["ok"]:
        return {"ok": False, "kind": "oauth_failed", "error": w["error"]}
    end
    return oauth.exchange_code(p, w["code"], verifier, port)
end

# ---- hlavni cast --------------------------------------------------------------------------------------------------

function find_account(address):
    for a in store.load_accounts():
        if String(a.get("email", "")).lower() == address.lower() and a.get("auth", "") == "oauth":
            return a
        end
    end
    return {}
end

function host_caps(s):
    conn = {}
    err = ""
    try:
        conn = imap.connect(s["host"], s["port"], s["security"], 15000)
    else:
        err = String(last_error())
    end
    if err != "":
        return "cannot connect: " + ol.clean(imap.error_kind(err)[1])
    end
    out = []
    for c in conn["caps"]:
        if c.startswith("AUTH=") or c == "SASL-IR" or c == "LOGINDISABLED":
            out.append(c)
        end
    end
    safe:
        call imap.logout(conn)
    end
    return " ".join(out)
end

function main(argv):
    typed = ""
    fresh = False
    pid = ""
    i = 2
    while i < len(argv):
        a = argv[i]
        if a == "--fresh":
            fresh = True
        elif a == "--provider" and i + 1 < len(argv):
            i += 1
            pid = argv[i]
        elif typed == "":
            typed = a.strip()
        end
        i += 1
    end
    if typed == "" or typed.find("@") <= 0:
        call say("Usage: luxos-mail --diagnose-oauth ADDRESS [--fresh] [--provider google|microsoft]")
        return 2
    end
    acc = find_account(typed)
    p = {}
    if len(acc) > 0 and pid == "":
        pid = String(acc.get("oauth", {}).get("provider", ""))
    end
    if pid == "":
        pid = provider.by_domain(provider.domain_of(typed))
        if pid != "google":
            pid = "microsoft"
        end
    end
    p = oauth.available(pid)
    if len(acc) > 0 and String(acc.get("oauth", {}).get("client_id", "")) != "":
        base = oauth.provider(pid)
        if len(base) > 0:
            p = base
            p["client_id"] = acc["oauth"]["client_id"]
            p["client_secret"] = String(acc["oauth"].get("client_secret", ""))
        end
    end
    if len(p) == 0 or p.get("client_id", "") == "":
        call say("Signing in with " + pid + " is not set up on this computer (no client ID). Run: luxos-mail --oauth-config")
        return 2
    end
    call say("LuxOS Mail sign-in diagnostics")
    call say("  address: " + mask(typed))
    call say("  provider: " + p["name"] + ", client ID " + p["client_id"])
    call say("  token endpoint: " + p["token_url"])
    call say("  scopes (sign-in): " + p["scope"])
    call say("  scopes (renewal): " + oauth.resource_scope(p["scope"]))
    mech = p["sasl"]
    if mech == "":
        mech = "by server capabilities"
    end
    call say("  SASL mechanism: " + mech)
    s = {"host": p["imap"]["host"], "port": p["imap"]["port"], "security": p["imap"]["security"]}
    user = typed
    rt = ""
    stored = False
    if len(acc) > 0:
        if len(acc.get("imap", {})) > 0:
            s = {"host": acc["imap"]["host"], "port": acc["imap"]["port"], "security": acc["imap"]["security"]}
            user = String(acc["imap"].get("user", acc["email"]))
        end
        if not fresh:
            rt = secret.lookup(acc["id"])
        end
    end
    r = {}
    if rt != "":
        stored = True
        call say("  sign-in: stored in the keyring (account " + acc["id"] + "); renewing the access token")
        r = oauth.refresh(p, rt)
    else:
        call say("  sign-in: new sign-in in the browser (nothing is saved)")
        r = browser_sign_in(p, typed)
    end
    if not r["ok"]:
        call say("RESULT: getting a token failed: " + String(r.get("kind", "")) + ": " + ol.clean(String(r.get("error", ""))))
        return 2
    end
    if r["refresh_token"] == "" and rt != "":
        r["refresh_token"] = rt
    end
    call say("Tokens:")
    call describe_access(r["access_token"], typed)
    call describe_id(r["id_token"], typed)
    if r["refresh_token"] != "":
        call say("  refresh token: received")
    else:
        call say("  refresh token: none")
    end
    identity = oauth.id_token_identity(r["id_token"])
    users = oauth.address_candidates(user, typed, identity)
    call say("Servers:")
    call say("  " + s["host"] + ":" + String(s["port"]) + " " + host_caps(s))
    for alt in p["imap_alternates"]:
        if not ol.same_server(alt, s):
            call say("  " + alt["host"] + ":" + String(alt["port"]) + " " + host_caps(alt))
        end
    end
    report = []
    first = ol.attempt("initial " + users[0], s, users[0], r["access_token"], p["sasl"], report)
    any_ok = first["ok"]
    if first["ok"]:
        safe:
            call imap.logout(first["conn"])
        end
    end
    rec = {"token": r["access_token"], "expires_in": r["expires_in"], "refresh_token": r["refresh_token"], "rt_changed": stored and r["refresh_token"] != rt}
    found = ol.recover(p, s, users, rec, report, True)
    if stored and rec["rt_changed"]:
        # rotace u Microsoftu: novy obnovovaci token uctu do klicenky (stary muze prestat platit)
        call secret.store(acc["id"], acc["email"], s["host"], rec["refresh_token"], "LuxOS Mail (" + p["name"] + "): " + acc["email"])
    end
    call say("Attempts (variant -> server response):")
    for line in report:
        v = line["variant"]
        for u in users:
            v = v.replace(u, mask(u))
        end
        where = ""
        if line["host"] != "":
            where = " @" + line["host"]
        end
        resp = line["response"]
        if line["kind"] != "" and not line["ok"]:
            resp = line["kind"] + ": " + resp
        end
        call say("  " + v + where + " -> " + resp)
    end
    if any_ok:
        call say("RESULT: the mailbox opens with the normal settings.")
        return 0
    end
    if found["ok"]:
        call say("RESULT: the mailbox opens with variant '" + found["variant"] + "' (" + mask(found["user"]) + " @" + found["server"]["host"] + "). Mail uses it automatically.")
        return 0
    end
    nc = False
    for line in report:
        if line["kind"] == "notconnected":
            nc = True
        end
    end
    if nc and p["id"] == "microsoft":
        call say("RESULT: Microsoft accepts the token but does not open the mailbox with any variant. Turn on IMAP at outlook.com: Settings, Mail, Forwarding and IMAP, \"Let devices and apps use IMAP\"; confirm the sign-in at https://account.live.com/activity (\"This was me\"); then try again.")
    else:
        call say("RESULT: no variant opened the mailbox.")
    end
    return 1
end
