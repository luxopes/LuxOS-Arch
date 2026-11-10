# Posta LuxOS - klient SMTP pro odesilani (RFC 5321 submission, RFC 6409) nad moduly net/tls LSL.
# TLS vzdy s overenim certifikatu systemovymi CA a jmenem serveru (SNI) - stejne jako IMAP (mail_imap):
# security "ssl" = implicitni TLS (port 465, RFC 8314), "starttls" = 587 + STARTTLS (RFC 3207). Bez sifrovani
# se heslo ani token nikdy neposle. Prihlaseni: XOAUTH2 / OAUTHBEARER (RFC 7628) tokenem (Google, Microsoft,
# schranky LuxAI), PLAIN (RFC 4616) nebo LOGIN heslem. Velikost zpravy se zkontroluje proti SIZE (RFC 1870),
# 8BITMIME a SMTPUTF8 (RFC 6531) jen kdyz je zprava/adresy potrebuji. Viceradkove odpovedi "250-...".
# Chyby: Error(MailError: "druh|text") jako mail_imap; navic smtp_temp (docasna chyba 4xx - zkusit pozdeji),
# smtp_rejected (server zpravu nebo odesilatele odmitl), rcpt (odmitnuti prijemci: "adresy|duvod"), toolarge
# (limit serveru v bajtech), smtp_noauth (server prihlaseni nenabizi), smtp_utf8 (adresa mimo ASCII bez SMTPUTF8).
load net
load mail_bytes as mb
load mail_mime as mime
load mail_imap as imap

TIMEOUT = 60000
DATA_TIMEOUT = 600000
CHUNK = 65536

# Docasne chyby: zprava zustane v Odchozi a zkusi se znovu (sit, server docasne nedostupny)
function transient(kind):
    return kind in ["connect", "timeout", "closed", "tls", "smtp_temp", "unavailable", "luxai_server", "oauth_server", "service"]
end

function fail(kind, message):
    call imap.fail(kind, message)
end

# Jedna odpoved serveru (i viceradkova): {"code", "lines", "text"}
function read_reply(conn, timeout):
    lines = []
    code = 0
    loop:
        buf = conn["buf"]
        start = conn["pos"]
        nl = mb.find_byte(buf, 10, start, len(buf))
        if nl < 0:
            if len(buf) - start > 65536:
                call fail("protocol", "The outgoing server sent an invalid reply.")
            end
            call imap.ensure(conn, len(buf) - start + 1, timeout, False)
            continue
        end
        stop = nl
        if stop > start and buf[stop - 1] == 13:
            stop -= 1
        end
        line = net.text(buf, start, stop - start)
        conn["pos"] = nl + 1
        c = -1
        if len(line) >= 3:
            c = mime.to_int(line[0:3], -1)
        end
        if c < 100:
            call fail("protocol", "Not an SMTP server: " + imap.clean_text(line))
        end
        code = c
        if len(line) > 4:
            lines.append(line[4:])
        else:
            lines.append("")
        end
        if len(line) == 3 or line[3:4] != "-":
            break
        end
    end
    return {"code": code, "lines": lines, "text": imap.clean_text(" ".join(lines))}
end

function command(conn, text, timeout=60000):
    call imap.write(conn, text + "\r\n")
    return read_reply(conn, timeout)
end

# Rozsireni z odpovedi EHLO: {"AUTH": "PLAIN LOGIN", "SIZE": "35882577", "8BITMIME": "", ...}
function parse_ehlo(r):
    ext = {}
    i = 0
    for line in r["lines"]:
        i += 1
        if i == 1:
            continue
        end
        t = line.strip()
        sp = t.find(" ")
        key = t
        value = ""
        if sp >= 0:
            key = t[0:sp]
            value = t[sp + 1:].strip()
        end
        key = key.upper()
        # stary zapis "AUTH=LOGIN PLAIN" (Outlook)
        if key.startswith("AUTH="):
            value = (key[5:] + " " + value).strip()
            key = "AUTH"
            if "AUTH" in ext:
                value = ext["AUTH"] + " " + value
            end
        end
        ext[key] = value
    end
    return ext
end

function ehlo(conn):
    # bez jmena pocitace (soukromi): adresa jako literal, jako Thunderbird
    r = command(conn, "EHLO [127.0.0.1]")
    if r["code"] != 250:
        r = command(conn, "HELO [127.0.0.1]")
        if r["code"] != 250:
            call fail("protocol", "The outgoing server refused the greeting: " + r["text"])
        end
        conn["ext"] = {}
        return conn["ext"]
    end
    conn["ext"] = parse_ehlo(r)
    return conn["ext"]
end

function has_ext(conn, name):
    return name in conn["ext"]
end

function mechanisms(conn):
    out = []
    for m in conn["ext"].get("AUTH", "").upper().split(" "):
        if m != "" and m not in out:
            out.append(m)
        end
    end
    return out
end

# Spojeni + pozdrav + sifrovani + EHLO; vraci spojeni (slovnik jako mail_imap) s rozsirenimi v conn["ext"]
function connect(host, port, security, timeout=20000):
    if security != "ssl" and security != "starttls":
        call fail("insecure", "Unencrypted connections are not allowed.")
    end
    conn = imap.new_conn(host)
    conn["ext"] = {}
    try:
        conn["fd"] = net.tcp_connect(host, port, timeout)
    else:
        call fail("connect", String(last_error()))
    end
    call net.set_nonblocking(conn["fd"], True)
    ok = True
    err = ""
    try:
        if security == "ssl":
            call imap.start_tls(conn, timeout)
        end
        greeting = read_reply(conn, timeout)
        if greeting["code"] != 220:
            call fail("smtp_temp", "The outgoing server is not available: " + greeting["text"])
        end
        call ehlo(conn)
        if security == "starttls":
            if not has_ext(conn, "STARTTLS"):
                call fail("nostarttls", "The outgoing server does not offer an encrypted connection (STARTTLS).")
            end
            r = command(conn, "STARTTLS")
            if r["code"] != 220:
                call fail("nostarttls", "The outgoing server refused STARTTLS: " + r["text"])
            end
            # data prijata pred handshake se zahodi (vlozeni prikazu, CVE-2011-0411)
            conn["buf"] = ByteArray()
            conn["pos"] = 0
            call imap.start_tls(conn, timeout)
            call ehlo(conn)
        end
    else:
        ok = False
        err = String(last_error())
    end
    if not ok:
        call imap.close(conn)
        Error(MailError: err.replace("MailError: ", ""))
    end
    return conn
end

# Odpoved na prihlaseni -> chyba (535/534 spatne udaje, 454/4xx docasne)
function auth_failed(r, extra):
    text = r["text"]
    if text == "":
        text = "Authentication failed."
    end
    if extra != "":
        text = text + " (" + extra + ")"
    end
    if r["code"] >= 400 and r["code"] < 500:
        call fail("smtp_temp", text)
    end
    call fail("auth", text)
end

function login(conn, user, password):
    mechs = mechanisms(conn)
    if len(mechs) == 0:
        call fail("smtp_noauth", "The outgoing server does not offer signing in.")
    end
    if "PLAIN" in mechs:
        token = mime.b64_encode(mb.join([imap.zero_byte(), net.bytes(user), imap.zero_byte(), net.bytes(password)]))
        r = command(conn, "AUTH PLAIN " + token)
        if r["code"] == 334:
            r = command(conn, token)
        end
        if r["code"] != 235:
            call auth_failed(r, "")
        end
        return 0
    end
    if "LOGIN" in mechs:
        r = command(conn, "AUTH LOGIN")
        if r["code"] == 334:
            r = command(conn, mime.b64_encode(net.bytes(user)))
        end
        if r["code"] == 334:
            r = command(conn, mime.b64_encode(net.bytes(password)))
        end
        if r["code"] != 235:
            call auth_failed(r, "")
        end
        return 0
    end
    if "XOAUTH2" in mechs or "OAUTHBEARER" in mechs:
        call fail("oauthonly", "The outgoing server accepts only sign-in with a token (OAuth2), not a password.")
    end
    call fail("smtp_noauth", "The outgoing server offers no supported way to sign in.")
end

# Prihlaseni tokenem (OAUTHBEARER nebo XOAUTH2; prefer = mechanismus poskytovatele). Odmitnuty token: server
# posle 334 s JSON chybou, klient odpovi prazdnou zpravou (XOAUTH2) / ^A (OAUTHBEARER), server pak 535.
function login_oauth(conn, user, token, port, prefer=""):
    caps = []
    for m in mechanisms(conn):
        caps.append("AUTH=" + m)
    end
    mech = imap.oauth_mechanism(caps, prefer)
    if mech == "":
        call fail("nooauth", "The outgoing server does not support signing in with an access token (OAUTHBEARER or XOAUTH2).")
    end
    if not imap.ascii_safe(user) or not imap.ascii_safe(token) or token == "":
        call fail("auth", "Invalid user name or access token.")
    end
    payload = mime.b64_encode(net.bytes(imap.oauth_payload(mech, user, token, conn["host"], port)))
    r = command(conn, "AUTH " + mech + " " + payload)
    status = ""
    if r["code"] == 334:
        if len(r["lines"]) > 0:
            status = imap.oauth_error_status(r["lines"][0])
        end
        if mech == "OAUTHBEARER":
            r = command(conn, "AQ==")
        else:
            r = command(conn, "")
        end
    end
    if r["code"] != 235:
        call auth_failed(r, status)
    end
    return 0
end

function needs_utf8(addresses):
    for a in addresses:
        if not mime.ascii_only(a):
            return True
        end
    end
    return False
end

function reply_error(r, what):
    if r["code"] == 552 or (r["code"] == 452 and r["text"].lower().find("size") >= 0):
        call fail("toolarge", "0")
    end
    if r["code"] >= 400 and r["code"] < 500:
        call fail("smtp_temp", r["text"])
    end
    call fail("smtp_rejected", what + r["text"])
end

# Odeslani jedne zpravy: obalka (MAIL FROM, RCPT TO) + DATA. Odmitnuty prijemce -> zadny neodejde (RSET) a
# chyba "rcpt" s adresami. Vraci text posledni odpovedi (cislo ve fronte serveru).
function send(conn, mail_from, rcpts, data):
    limit = mime.to_int(conn["ext"].get("SIZE", "0").split(" ")[0], 0)
    if limit > 0 and len(data) > limit:
        call fail("toolarge", String(limit))
    end
    params = ""
    if has_ext(conn, "SIZE"):
        params = params + " SIZE=" + String(len(data))
    end
    if mime.has_8bit(data, 0, len(data)) and has_ext(conn, "8BITMIME"):
        params = params + " BODY=8BITMIME"
    end
    all_addresses = [mail_from] + rcpts
    if needs_utf8(all_addresses):
        if not has_ext(conn, "SMTPUTF8"):
            call fail("smtp_utf8", "The outgoing server does not accept addresses with non-ASCII characters.")
        end
        params = params + " SMTPUTF8"
    end
    r = command(conn, "MAIL FROM:<" + mime.addr_spec(mail_from) + ">" + params)
    if r["code"] != 250:
        call reply_error(r, "")
    end
    rejected = []
    reason = ""
    for rcpt in rcpts:
        r = command(conn, "RCPT TO:<" + mime.addr_spec(rcpt) + ">")
        if r["code"] == 250 or r["code"] == 251:
            continue
        end
        if r["code"] >= 400 and r["code"] < 500:
            safe:
                call command(conn, "RSET")
            end
            call fail("smtp_temp", r["text"])
        end
        rejected.append(rcpt)
        if reason == "":
            reason = r["text"]
        end
    end
    if len(rejected) > 0:
        safe:
            call command(conn, "RSET")
        end
        call fail("rcpt", ", ".join(rejected) + "|" + reason)
    end
    r = command(conn, "DATA")
    if r["code"] != 354:
        call reply_error(r, "")
    end
    body = mb.dot_stuff(data)
    n = len(body)
    pos = 0
    while pos < n:
        stop = min(n, pos + CHUNK)
        call imap.write(conn, mb.sub(body, pos, stop))
        pos = stop
    end
    if n < 2 or body[n - 2] != 13 or body[n - 1] != 10:
        call imap.write(conn, "\r\n")
    end
    r = command(conn, ".", DATA_TIMEOUT)
    if r["code"] != 250:
        call reply_error(r, "")
    end
    return r["text"]
end

function quit(conn):
    safe:
        call command(conn, "QUIT", 5000)
    end
    call imap.close(conn)
    return 0
end
