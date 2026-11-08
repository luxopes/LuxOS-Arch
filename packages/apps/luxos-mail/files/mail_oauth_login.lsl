# Posta LuxOS - prihlaseni do IMAP tokenem poskytovatele (OAuth2) a zachrana pri chybe Microsoftu
# "User is authenticated but not connected" (token prijaty, schranka se neotevrela).
#
# Znama priciny te chyby a co se zkousi samo (poradi pokusu v recover):
#   1. jina adresa v XOAUTH2 user= (Microsoft chce hlavni adresu schranky, ne alias ani jine jmeno uctu):
#      e-mail a preferred_username z id_token, zadana adresa
#   2. token pro jiny prostredek nez https://outlook.office.com: novy pristupovy token obnovenim jen s rozsahy
#      Outlooku (bez openid/email)
#   3. osobni ucet (outlook.com, hotmail.com): obnoveni pres koncovy bod /consumers
#   4. jiny server IMAP tehoz poskytovatele (outlook.office365.com <-> imap-mail.outlook.com)
#   5. docasna chyba na serveru Microsoftu: po kratke pauze znovu
# Kdyz nic nepomuze, zbyva nastaveni uctu u Microsoftu (IMAP vypnuty v Outlook.com, prihlaseni ceka na
# potvrzeni na account.live.com/activity) - to okno rekne uzivateli (chyba "notconnected").
#
# Tokeny nikdy v logu ani ve zprave diagnostiky: zprava obsahuje jen nazev pokusu a odpoved serveru.
# Testy: LUXOS_MAIL_NOTCONNECTED_WAIT (ms pauzy pred poslednim pokusem, vychozi 3000).
load env
load time as tm
load mail_imap as imap
load mail_oauth as oauth

# Spojeni a prihlaseni tokenem; check: overit i otevreni schranky (LIST INBOX). MailError pri chybe
# (spojeni se zavre).
function token_connect(s, user, token, prefer="", check=False):
    conn = imap.connect(s["host"], s["port"], s["security"], 15000)
    try:
        call imap.login_oauth(conn, user, token, s["port"], prefer)
        if check:
            call imap.check_mailbox(conn)
        end
    else:
        err = last_error()
        call imap.close(conn)
        Error(MailError: String(err).replace("MailError: ", ""))
    end
    return conn
end

function wait_ms():
    v = env.get("LUXOS_MAIL_NOTCONNECTED_WAIT", "")
    if v != None and v != "":
        n = 3000
        safe:
            n = Int(v)
        end
        if n >= 0 and n <= 60000:
            return n
        end
    end
    return 3000
end

# Text odpovedi serveru pro zpravu (bez ridicich znaku, max 200 znaku)
function clean(text):
    out = []
    for ch in String(text)[0:200]:
        if ord(ch) >= 32 and ord(ch) != 127:
            out.append(ch)
        end
    end
    return "".join(out)
end

function same_server(a, b):
    return a["host"] == b["host"] and a["port"] == b["port"] and a["security"] == b["security"]
end

# Jeden pokus: {"ok", "conn", "kind", "error"}; zapise radek do report
function attempt(name, s, user, token, prefer, report):
    conn = {}
    err = ""
    try:
        conn = token_connect(s, user, token, prefer, True)
    else:
        err = String(last_error())
    end
    if err == "":
        report.append({"variant": name, "host": s["host"], "ok": True, "kind": "", "response": "OK"})
        return {"ok": True, "conn": conn}
    end
    k = imap.error_kind(err)
    report.append({"variant": name, "host": s["host"], "ok": False, "kind": k[0], "response": clean(k[1])})
    return {"ok": False, "kind": k[0], "error": k[1]}
end

# Vysledek pokusu do found; True = skoncit (uspech a ne vse)
function done(found, r, name, server, user):
    if not r["ok"]:
        return False
    end
    if found["all"]:
        safe:
            call imap.logout(r["conn"])
        end
        if not found["ok"]:
            found["ok"] = True
            found["conn"] = {}
            found["variant"] = name
            found["user"] = user
            found["server"] = server
        end
        return False
    end
    found["ok"] = True
    found["conn"] = r["conn"]
    found["variant"] = name
    found["user"] = user
    found["server"] = server
    return True
end

# Pokus o zachranu po "notconnected" na serveru s s adresou users[0] a tokenem token.
# st: {"token", "expires_in", "refresh_token" (muze se zmenit rotaci), "rt_changed"}
# all: True = vyzkouset vsechno (diagnostika, bez zastaveni na prvnim uspechu; spojeni se hned zavrou)
# Vraci {"ok", "conn", "variant", "user", "server"} nebo {"ok": False}; report: radky pokusu
function recover(p, s, users, st, report, all=False):
    prefer = p.get("sasl", "")
    found = {"ok": False, "all": all}

    # 1. jina adresa schranky se stejnym tokenem
    for u in users[1:]:
        if done(found, attempt("address " + u, s, u, st["token"], prefer, report), "address", s, u):
            return found
        end
    end
    # 2. a 3. novy token jen s rozsahy Outlooku (bez OpenID), pak pres /consumers
    urls = []
    if st["refresh_token"] != "":
        urls.append(["outlook-scope", ""])
        if p.get("consumer_token_url", "") != "":
            urls.append(["consumers", p["consumer_token_url"]])
        end
    end
    for pair in urls:
        r = oauth.refresh(p, st["refresh_token"], pair[1])
        if not r["ok"]:
            report.append({"variant": pair[0] + " token", "host": "", "ok": False, "kind": r["kind"], "response": clean(r["error"])})
            continue
        end
        if r["refresh_token"] != "" and r["refresh_token"] != st["refresh_token"]:
            st["refresh_token"] = r["refresh_token"]
            st["rt_changed"] = True
        end
        st["token"] = r["access_token"]
        st["expires_in"] = r["expires_in"]
        for u in users:
            if done(found, attempt(pair[0] + " " + u, s, u, st["token"], prefer, report), pair[0], s, u):
                return found
            end
        end
    end
    # 4. jiny server IMAP poskytovatele
    for alt in p.get("imap_alternates", []):
        if same_server(alt, s):
            continue
        end
        for u in users:
            if done(found, attempt("host " + alt["host"] + " " + u, alt, u, st["token"], prefer, report), "host", alt, u):
                return found
            end
        end
    end
    # 5. docasna chyba: chvili pockat a znovu
    if not all and len(users) > 0:
        call tm.sleep(Float(wait_ms()) / 1000.0)
        if done(found, attempt("retry " + users[0], s, users[0], st["token"], prefer, report), "retry", s, users[0]):
            return found
        end
    end
    return found
end

# Radek do logu: "variant -> odpoved; ..." (bez tokenu)
function report_text(report):
    out = []
    for r in report:
        out.append(r["variant"] + " @" + r["host"] + " -> " + r["response"])
    end
    return "; ".join(out)
end
