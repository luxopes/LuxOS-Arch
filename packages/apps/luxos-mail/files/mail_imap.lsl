# Posta LuxOS - klient IMAP4rev1/IMAP4rev2 (RFC 3501, 9051) nad moduly net/tls LSL.
# Spojeni je slovnik; vse blokuje s casovym limitem (sluzba na pozadi), IDLE se cte bez blokovani
# (poll) z obsluhy glib.fd_add. TLS vzdy s overenim certifikatu systemovymi CA a jmenem serveru;
# bez sifrovani se heslo nikdy neposle (security "ssl" = port 993, "starttls" = 143 + STARTTLS).
# Chyby: Error(MailError: "druh|text"), druh: connect, cert, tls, closed, timeout, auth, nostarttls,
# insecure, no (server odmitl prikaz), protocol, nooauth (server neumi prihlaseni tokenem), unavailable
# (docasna chyba overeni na serveru), notconnected (Microsoft prijal token, ale schranku neotevrel:
# "User is authenticated but not connected").
load net, json
load tls
load mail_bytes as mb
load mail_mime as mime

CHUNK = 262144
TIMEOUT = 30000

function fail(kind, message):
    Error(MailError: kind + "|" + message)
end

# "MailError: auth|text" -> ["auth", "text"]; cizi chyba -> ["error", text]
function error_kind(text):
    t = String(text)
    p = t.find("MailError: ")
    if p >= 0:
        rest = t[p + 11:]
        bar = rest.find("|")
        if bar >= 0:
            return [rest[0:bar], rest[bar + 1:]]
        end
        return ["error", rest]
    end
    if t.find("TimeoutError") >= 0:
        return ["timeout", t]
    end
    return ["error", t]
end

function new_conn(host):
    return {"fd": -1, "tls": 0, "ctx": 0, "buf": ByteArray(), "pos": 0, "tag": 0, "caps": [], "host": host,
            "idle_tag": "", "selected": "", "qresync": False, "condstore": False, "closed": False}
end

# ---- vstup/vystup -----------------------------------------------------------------------------------------

function write(conn, data):
    try:
        if conn["tls"] != 0:
            call tls.write(conn["tls"], data, TIMEOUT)
        else:
            call net.send(conn["fd"], data, TIMEOUT)
        end
    else:
        conn["closed"] = True
        call fail("closed", String(last_error()))
    end
    return 0
end

# Jeden kus dat ze site; TimeoutError kdyz nic neprislo (limit 0 = jen co je hned k dispozici)
function read_chunk(conn, timeout):
    data = ByteArray()
    if conn["tls"] != 0:
        data = tls.read(conn["tls"], CHUNK, timeout)
    else:
        data = net.recv(conn["fd"], CHUNK, timeout)
    end
    if len(data) == 0:
        conn["closed"] = True
        call fail("closed", "The server closed the connection.")
    end
    return data
end

# Prida data do bufferu; zpracovane bajty pred pos zahodi
function feed(conn, pieces):
    buf = conn["buf"]
    rest = mb.sub(buf, conn["pos"], len(buf))
    items = [rest]
    items.extend(pieces)
    conn["buf"] = mb.join(items)
    conn["pos"] = 0
    return 0
end

# Ceka, az bude v bufferu aspon `need` bajtu od pos; nonblock: False kdyz data hned nejsou
function ensure(conn, need, timeout, nonblock):
    have = len(conn["buf"]) - conn["pos"]
    if have >= need:
        return True
    end
    pieces = []
    while have < need:
        data = ByteArray()
        if nonblock:
            got = True
            try:
                data = read_chunk(conn, 0)
            else:
                err = String(last_error())
                if err.find("TimeoutError") >= 0:
                    got = False
                else:
                    call feed(conn, pieces)
                    Error(MailError: err.replace("MailError: ", ""))
                end
            end
            if not got:
                if len(pieces) > 0:
                    call feed(conn, pieces)
                end
                return False
            end
        else:
            try:
                data = read_chunk(conn, timeout)
            else:
                err = String(last_error())
                if len(pieces) > 0:
                    call feed(conn, pieces)
                end
                if err.find("TimeoutError") >= 0:
                    call fail("timeout", "The server did not answer in time.")
                end
                Error(MailError: err.replace("MailError: ", ""))
            end
        end
        pieces.append(data)
        have += len(data)
    end
    call feed(conn, pieces)
    return True
end

# Literal "{123}" / "{123+}" na konci radku [line_start, cr): delka nebo -1
function literal_size(buf, line_start, cr):
    if cr - 1 <= line_start or buf[cr - 1] != 125:
        return -1
    end
    j = cr - 2
    if j > line_start and buf[j] == 43:
        j -= 1
    end
    value = 0
    mult = 1
    digits = 0
    while j > line_start and buf[j] >= 48 and buf[j] <= 57:
        value += (buf[j] - 48) * mult
        mult *= 10
        digits += 1
        j -= 1
    end
    if digits == 0 or buf[j] != 123:
        return -1
    end
    return value
end

# Jedna cela odpoved vcetne literalu: {"tag", "raw" (ByteArray), "body" (index za tagem)}
# nonblock=True: {} kdyz jeste neni cela (nic se nespotrebuje)
function read_response(conn, timeout, nonblock):
    rel = 0
    loop:
        buf = conn["buf"]
        start = conn["pos"]
        nl = mb.find_byte(buf, 10, start + rel, len(buf))
        if nl < 0:
            if not ensure(conn, len(buf) - start + 1, timeout, nonblock):
                return {}
            end
            continue
        end
        cr = nl
        if cr > start and buf[cr - 1] == 13:
            cr -= 1
        end
        lit = literal_size(buf, start + rel, cr)
        if lit >= 0:
            need = nl + 1 + lit - start
            if not ensure(conn, need, timeout, nonblock):
                return {}
            end
            rel = need
            continue
        end
        buf = conn["buf"]
        start = conn["pos"]
        stop = nl + 1
        raw = mb.sub(buf, start, stop)
        conn["pos"] = stop
        sp = mb.find_byte(raw, 32, 0, len(raw))
        tag = ""
        body = len(raw)
        if sp < 0:
            tag = net.text(raw).strip()
        else:
            tag = net.text(raw, 0, sp)
            body = sp + 1
        end
        return {"tag": tag, "raw": raw, "body": body}
    end
end

# Prvni slovo odpovedi za tagem ("OK", "EXISTS" je az druhe: "* 3 EXISTS")
function first_line(resp):
    raw = resp["raw"]
    nl = mb.find_byte(raw, 10, 0, len(raw))
    stop = len(raw)
    if nl >= 0:
        stop = nl
    end
    if stop > 0 and raw[stop - 1] == 13:
        stop -= 1
    end
    if resp["body"] >= stop:
        return ""
    end
    return net.text(raw, resp["body"], stop - resp["body"])
end

# Stavova odpoved "OK [KOD ...] text" -> [stav, kod, text]
function status_parts(line):
    sp = line.find(" ")
    word = line
    rest = ""
    if sp >= 0:
        word = line[0:sp]
        rest = line[sp + 1:]
    end
    code = ""
    if rest.startswith("["):
        close = rest.find("]")
        if close > 0:
            code = rest[1:close]
            rest = rest[close + 1:].strip()
        end
    end
    return [word.upper(), code, rest]
end

# ---- tokenizer odpovedi ---------------------------------------------------------------------------------------

function tokens(raw, start, stop):
    stack = [[]]
    i = start
    while i < stop:
        c = raw[i]
        if c == 32 or c == 13 or c == 10:
            i += 1
            continue
        end
        if c == 40:
            stack.append([])
            i += 1
            continue
        end
        if c == 41:
            if len(stack) > 1:
                top = stack.pop()
                stack[len(stack) - 1].append(top)
            end
            i += 1
            continue
        end
        current = stack[len(stack) - 1]
        if c == 34:
            out = ByteArray()
            j = i + 1
            while j < stop:
                d = raw[j]
                if d == 92 and j + 1 < stop:
                    out.append(raw[j + 1])
                    j += 2
                    continue
                end
                if d == 34:
                    break
                end
                out.append(d)
                j += 1
            end
            current.append(mime.decode_text(out, 0, len(out), ""))
            i = j + 1
            continue
        end
        if c == 123:
            close = mb.find_byte(raw, 125, i, stop)
            if close > i:
                digits = net.text(raw, i + 1, close - i - 1).replace("+", "")
                n = mime.to_int(digits, -1)
                ds = close + 1
                if ds < stop and raw[ds] == 13:
                    ds += 1
                end
                if ds < stop and raw[ds] == 10:
                    ds += 1
                end
                if n >= 0:
                    current.append(mb.sub(raw, ds, ds + n))
                    i = ds + n
                    continue
                end
            end
        end
        j = i
        depth = 0
        while j < stop:
            d = raw[j]
            if d == 91:
                depth += 1
            elif d == 93:
                depth -= 1
            elif depth <= 0 and (d == 32 or d == 40 or d == 41 or d == 13 or d == 10):
                break
            end
            j += 1
        end
        if j == i:
            j = i + 1
        end
        atom = net.text(raw, i, j - i)
        if atom == "NIL" or atom == "nil":
            current.append(None)
        else:
            current.append(atom)
        end
        i = j
    end
    while len(stack) > 1:
        top = stack.pop()
        stack[len(stack) - 1].append(top)
    end
    return stack[0]
end

function resp_tokens(resp):
    return tokens(resp["raw"], resp["body"], len(resp["raw"]))
end

# Token -> String (literal ByteArray se dekoduje, NIL je "")
function tstr(tok):
    if tok == None:
        return ""
    end
    t = type(tok)
    if t == "ByteArray":
        return mime.decode_text(tok, 0, len(tok), "")
    elif t == "String":
        return tok
    elif t == "List":
        return ""
    end
    return String(tok)
end

function tint(tok, fallback):
    return mime.to_int(tstr(tok), fallback)
end

function tlist(tok):
    if type(tok) == "List":
        return tok
    end
    return []
end

# ---- prikazy ------------------------------------------------------------------------------------------------

function next_tag(conn):
    conn["tag"] = conn["tag"] + 1
    return "L" + String(conn["tag"])
end

# Prikaz a cekani na tagovanou odpoved: {"status", "code", "text", "untagged": [odpovedi]}
# strict: NO/BAD vyvola MailError "no"
function command(conn, text, strict=True, timeout=30000):
    tag = next_tag(conn)
    call write(conn, tag + " " + text + "\r\n")
    return finish(conn, tag, strict, timeout)
end

function finish(conn, tag, strict, timeout):
    untagged = []
    loop:
        r = read_response(conn, timeout, False)
        if r["tag"] == tag:
            parts = status_parts(first_line(r))
            if parts[1].upper().startswith("CAPABILITY "):
                conn["caps"] = parts[1].upper().split(" ")[1:]
            end
            result = {"status": parts[0], "code": parts[1], "text": parts[2], "untagged": untagged}
            if strict and parts[0] != "OK":
                if not_connected(parts[2]):
                    call fail("notconnected", parts[2])
                end
                call fail("no", parts[2])
            end
            return result
        end
        if r["tag"] == "*":
            line = first_line(r)
            up = line.upper()
            if up.startswith("BYE"):
                conn["closed"] = True
                call fail("closed", status_parts(line)[2])
            end
            if up.startswith("CAPABILITY "):
                conn["caps"] = up.split(" ")[1:]
            end
        end
        untagged.append(r)
    end
end

function quote(s):
    return "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
end

function ascii_safe(s):
    for c in net.bytes(s):
        if c < 32 or c > 126:
            return False
        end
    end
    return True
end

function has_cap(conn, name):
    return name.upper() in conn["caps"]
end

function capability(conn):
    call command(conn, "CAPABILITY")
    return conn["caps"]
end

function start_tls(conn, timeout):
    ctx = tls.context("client")
    call tls.verify_system(ctx)
    conn["ctx"] = ctx
    ssl = 0
    try:
        ssl = tls.client(ctx, conn["fd"], conn["host"])
        conn["tls"] = ssl
        call tls.handshake(ssl, timeout)
    else:
        err = String(last_error())
        if err.find("certificate verify failed") >= 0 or err.find("certificate") >= 0 and err.find("verify") >= 0:
            detail = err
            p = err.find("(certificate:")
            if p >= 0:
                detail = err[p + 13:].replace(")", "").strip()
            end
            call close(conn)
            call fail("cert", detail)
        end
        call close(conn)
        call fail("tls", err)
    end
    return 0
end

# Spojeni + pozdrav + sifrovani; vraci spojeni s nactenymi schopnostmi (CAPABILITY)
function connect(host, port, security, timeout=15000):
    if security != "ssl" and security != "starttls":
        call fail("insecure", "Unencrypted connections are not allowed.")
    end
    conn = new_conn(host)
    try:
        conn["fd"] = net.tcp_connect(host, port, timeout)
    else:
        call fail("connect", String(last_error()))
    end
    # neblokujici soket: SSL_read na blokujicim soketu by ignoroval casovy limit (IDLE by visel)
    call net.set_nonblocking(conn["fd"], True)
    if security == "ssl":
        call start_tls(conn, timeout)
    end
    greeting = read_response(conn, timeout, False)
    parts = status_parts(first_line(greeting))
    if parts[0] == "BYE":
        call close(conn)
        call fail("closed", parts[2])
    end
    if parts[0] != "OK" and parts[0] != "PREAUTH":
        call close(conn)
        call fail("protocol", "Not an IMAP server: " + first_line(greeting))
    end
    if parts[1].upper().startswith("CAPABILITY "):
        conn["caps"] = parts[1].upper().split(" ")[1:]
    else:
        call capability(conn)
    end
    if security == "starttls":
        if not has_cap(conn, "STARTTLS"):
            call close(conn)
            call fail("nostarttls", "The server does not offer an encrypted connection (STARTTLS).")
        end
        call command(conn, "STARTTLS")
        # data prijata pred handshake se zahodi (ochrana proti vlozeni prikazu, CVE-2011-0411)
        conn["buf"] = ByteArray()
        conn["pos"] = 0
        call start_tls(conn, timeout)
        call capability(conn)
    end
    return conn
end

# Text od serveru pro uzivatele: bez ridicich znaku, nejvys 300 znaku (zpravy chyb, [ALERT])
function clean_text(text):
    out = ByteArray()
    for c in net.bytes(String(text)):
        if c < 32 or c == 127:
            out.append(32)
        else:
            out.append(c)
        end
    end
    words = []
    for w in net.text(out).split(" "):
        if w != "":
            words.append(w)
        end
    end
    t = " ".join(words)
    if len(t) > 300:
        t = t[0:297] + "..."
    end
    return t
end

# Upozorneni serveru pri prihlaseni: "* NO [ALERT] text", "* OK [WEBALERT url] text" (Gmail) a kod
# tagovane odpovedi -> text pro uzivatele, napr. Gmail: "[ALERT] Application-specific password required: ..."
function auth_reason(result):
    alerts = []
    for resp in result.get("untagged", []):
        if resp.get("tag", "") != "*":
            continue
        end
        parts = status_parts(first_line(resp))
        code = parts[1].upper()
        if (parts[0] == "NO" or parts[0] == "OK" or parts[0] == "BAD") and (code == "ALERT" or code.startswith("WEBALERT")):
            t = clean_text(parts[2])
            if t != "" and t not in alerts:
                alerts.append(t)
            end
        end
    end
    text = clean_text(result.get("text", ""))
    code = String(result.get("code", "")).upper()
    if code != "" and not code.startswith("CAPABILITY"):
        first = code.split(" ")[0]
        if first == "ALERT" or first == "WEBALERT":
            if text != "" and text not in alerts:
                alerts.append(text)
            end
            text = ""
        elif text != "":
            text = "[" + clean_text(first) + "] " + text
        end
    end
    if text != "" and text not in alerts:
        alerts.append(text)
    end
    if len(alerts) == 0:
        return "Authentication failed."
    end
    return " ".join(alerts)
end

# Server bez prihlaseni heslem (LOGINDISABLED a zadne AUTH=PLAIN/LOGIN), jen tokenem OAuth2 (Microsoft)
function oauth_only(conn):
    if has_cap(conn, "AUTH=PLAIN") or has_cap(conn, "AUTH=LOGIN") or not has_cap(conn, "LOGINDISABLED"):
        return False
    end
    return has_cap(conn, "AUTH=XOAUTH2") or has_cap(conn, "AUTH=OAUTHBEARER")
end

function login(conn, user, password):
    result = {}
    if has_cap(conn, "AUTH=PLAIN"):
        # SASL PLAIN (RFC 4616): authzid (prazdne) \0 jmeno \0 heslo
        token = mime.b64_encode(mb.join([zero_byte(), net.bytes(user), zero_byte(), net.bytes(password)]))
        tag = next_tag(conn)
        if has_cap(conn, "SASL-IR"):
            call write(conn, tag + " AUTHENTICATE PLAIN " + token + "\r\n")
        else:
            call write(conn, tag + " AUTHENTICATE PLAIN\r\n")
            r = read_response(conn, TIMEOUT, False)
            if r["tag"] != "+":
                parts = status_parts(first_line(r))
                call fail("auth", auth_reason({"code": parts[1], "text": parts[2], "untagged": []}))
            end
            call write(conn, token + "\r\n")
        end
        result = finish(conn, tag, False, TIMEOUT)
    elif oauth_only(conn):
        call fail("oauthonly", "The server accepts only sign-in with a token (OAuth2), not a password.")
    elif has_cap(conn, "LOGINDISABLED"):
        call fail("auth", "The server does not allow signing in on this connection.")
    elif ascii_safe(user) and ascii_safe(password):
        result = command(conn, "LOGIN " + quote(user) + " " + quote(password), False)
    else:
        # synchronizujici literaly pro jmeno/heslo mimo ASCII
        tag = next_tag(conn)
        ub = net.bytes(user)
        pb = net.bytes(password)
        call write(conn, tag + " LOGIN {" + String(len(ub)) + "}\r\n")
        call expect_continuation(conn)
        call write(conn, ub)
        call write(conn, " {" + String(len(pb)) + "}\r\n")
        call expect_continuation(conn)
        call write(conn, pb)
        call write(conn, "\r\n")
        result = finish(conn, tag, False, TIMEOUT)
    end
    if result["status"] != "OK":
        call fail("auth", auth_reason(result))
    end
    if not result["code"].upper().startswith("CAPABILITY "):
        call capability(conn)
    end
    return 0
end

# ---- SASL OAUTHBEARER (RFC 7628) a XOAUTH2: pristupovy token misto hesla (schranky LuxAI) -----------------

# "User is authenticated but not connected." (Microsoft: token platny, schranka se neotevrela)
function not_connected(text):
    return String(text).lower().find("authenticated but not connected") >= 0
end

# Vybrany mechanismus: OAUTHBEARER (standard), jinak XOAUTH2 (Google, Microsoft, starsi Dovecot); "" = zadny.
# prefer: mechanismus poskytovatele (Microsoft: XOAUTH2), kdyz ho server nabizi
function oauth_mechanism(caps, prefer=""):
    if prefer != "" and "AUTH=" + prefer in caps:
        return prefer
    end
    if "AUTH=OAUTHBEARER" in caps:
        return "OAUTHBEARER"
    elif "AUTH=XOAUTH2" in caps:
        return "XOAUTH2"
    end
    return ""
end

# Pocatecni odpoved klienta (text pred base64). host/port jen v OAUTHBEARER (RFC 7628 3.1); IMAP i SMTP
# (faze 2) pouziji stejny tvar.
function oauth_payload(mech, user, token, host, port):
    if mech == "OAUTHBEARER":
        # gs2 saslname: "=" -> "=3D", "," -> "=2C" (RFC 5801)
        name = user.replace("=", "=3D").replace(",", "=2C")
        return "n,a=" + name + "," + chr(1) + "host=" + host + chr(1) + "port=" + String(port) + chr(1) + "auth=Bearer " + token + chr(1) + chr(1)
    end
    return "user=" + user + chr(1) + "auth=Bearer " + token + chr(1) + chr(1)
end

# Chybova zprava serveru v pokracovani "+ <base64 JSON>" ({"status": "invalid_token", ...}) -> text stavu
function oauth_error_status(line):
    text = line.strip()
    if text == "":
        return ""
    end
    out = ""
    safe:
        b = net.bytes(text)
        data = json.decode(net.text(mime.b64_decode(b, 0, len(b))))
        if type(data) == "Dictionary":
            out = String(data.get("status", ""))
        end
    end
    return out
end

# Prihlaseni tokenem. Spatny/odvolany token -> MailError "auth"; docasna chyba serveru (NO [UNAVAILABLE],
# napr. nedostupna introspekce) -> "unavailable" (opakuje se s odstupem, neni to spatny token).
function login_oauth(conn, user, token, port=993, prefer=""):
    mech = oauth_mechanism(conn["caps"], prefer)
    if mech == "":
        call fail("nooauth", "The server does not support signing in with an access token (OAUTHBEARER or XOAUTH2).")
    end
    if not ascii_safe(user) or not ascii_safe(token) or token == "":
        call fail("auth", "Invalid user name or access token.")
    end
    payload = mime.b64_encode(net.bytes(oauth_payload(mech, user, token, conn["host"], port)))
    tag = next_tag(conn)
    if has_cap(conn, "SASL-IR"):
        call write(conn, tag + " AUTHENTICATE " + mech + " " + payload + "\r\n")
    else:
        call write(conn, tag + " AUTHENTICATE " + mech + "\r\n")
        r = read_response(conn, TIMEOUT, False)
        if r["tag"] != "+":
            call fail("auth", status_parts(first_line(r))[2])
        end
        call write(conn, payload + "\r\n")
    end
    status = ""
    parts = []
    challenges = 0
    loop:
        r = read_response(conn, TIMEOUT, False)
        if r["tag"] == "+":
            # odmitnuty token: server posle JSON s chybou a ceka na prazdnou odpoved klienta, pak NO
            challenges += 1
            if challenges > 2:
                call close(conn)
                call fail("protocol", "Unexpected SASL challenge.")
            end
            status = oauth_error_status(first_line(r))
            if mech == "OAUTHBEARER":
                call write(conn, "AQ==\r\n")
            else:
                call write(conn, "\r\n")
            end
            continue
        end
        if r["tag"] == tag:
            parts = status_parts(first_line(r))
            break
        end
        if r["tag"] == "*":
            up = first_line(r).upper()
            if up.startswith("BYE"):
                conn["closed"] = True
                call fail("closed", status_parts(first_line(r))[2])
            end
            if up.startswith("CAPABILITY "):
                conn["caps"] = up.split(" ")[1:]
            end
        end
    end
    if parts[0] != "OK":
        text = parts[2]
        if text == "":
            text = "Authentication failed."
        end
        if status != "":
            text = text + " (" + status + ")"
        end
        if parts[1].upper().startswith("UNAVAILABLE"):
            call fail("unavailable", text)
        end
        if not_connected(parts[2]):
            call fail("notconnected", text)
        end
        call fail("auth", text)
    end
    if parts[1].upper().startswith("CAPABILITY "):
        conn["caps"] = parts[1].upper().split(" ")[1:]
    else:
        call capability(conn)
    end
    return 0
end

# Opravdu otevrena schranka (Microsoft muze prijmout AUTHENTICATE a az dalsi prikaz odmitne s "User is
# authenticated but not connected"): LIST "" "INBOX". MailError notconnected/no pri chybe.
function check_mailbox(conn):
    call command(conn, "LIST \"\" \"INBOX\"")
    return 0
end

function zero_byte():
    b = ByteArray()
    b.append(0)
    return b
end

function expect_continuation(conn):
    r = read_response(conn, TIMEOUT, False)
    if r["tag"] != "+":
        call fail("no", status_parts(first_line(r))[2])
    end
    return 0
end

# QRESYNC (RFC 7162) zahrnuje CONDSTORE; jen CONDSTORE se zapne prvnim SELECT (CONDSTORE)
function enable_extensions(conn):
    if has_cap(conn, "QRESYNC") and has_cap(conn, "ENABLE"):
        r = command(conn, "ENABLE QRESYNC", False)
        if r["status"] == "OK":
            conn["qresync"] = True
            conn["condstore"] = True
            return 0
        end
    end
    if has_cap(conn, "CONDSTORE"):
        conn["condstore"] = True
    end
    return 0
end

function logout(conn):
    safe:
        call command(conn, "LOGOUT", False, 3000)
    end
    call close(conn)
    return 0
end

function close(conn):
    if conn["tls"] != 0:
        safe:
            call tls.close(conn["tls"], True)
        end
        conn["tls"] = 0
        conn["fd"] = -1
    elif conn["fd"] >= 0:
        safe:
            call net.close(conn["fd"])
        end
        conn["fd"] = -1
    end
    if conn["ctx"] != 0:
        safe:
            call tls.context_free(conn["ctx"])
        end
        conn["ctx"] = 0
    end
    conn["closed"] = True
    return 0
end

function socket_fd(conn):
    if conn["tls"] != 0:
        return tls.fd(conn["tls"])
    end
    return conn["fd"]
end

# ---- schranky ---------------------------------------------------------------------------------------------

# Modifikovane UTF-7 (RFC 3501 5.1.3) -> text
function mutf7_decode(name):
    b = net.bytes(name)
    n = len(b)
    if mb.find_byte(b, 38, 0, n) < 0:
        return name
    end
    out = []
    i = 0
    start = 0
    while i < n:
        if b[i] != 38:
            i += 1
            continue
        end
        if i > start:
            out.append(net.text(b, start, i - start))
        end
        e = mb.find_byte(b, 45, i + 1, n)
        if e < 0:
            e = n
        end
        if e == i + 1:
            out.append("&")
        else:
            raw = mime.b64_decode(b, i + 1, e)
            k = 0
            chars = []
            while k + 1 < len(raw):
                unit = (raw[k] << 8) | raw[k + 1]
                k += 2
                if unit >= 55296 and unit <= 56319 and k + 1 < len(raw):
                    low = (raw[k] << 8) | raw[k + 1]
                    k += 2
                    unit = 65536 + ((unit - 55296) << 10) + (low - 56320)
                end
                if unit > 0 and not (unit >= 55296 and unit <= 57343):
                    chars.append(chr(unit))
                end
            end
            out.append("".join(chars))
        end
        i = e + 1
        start = i
    end
    if start < n:
        out.append(net.text(b, start, n - start))
    end
    return "".join(out)
end

ROLE_NAMES = {"sent": "sent", "sent items": "sent", "sent messages": "sent", "sent mail": "sent", "odeslané": "sent",
              "odeslana posta": "sent", "odeslaná pošta": "sent", "gesendet": "sent", "envoyés": "sent", "wysłane": "sent",
              "drafts": "drafts", "draft": "drafts", "koncepty": "drafts", "rozepsané": "drafts", "entwürfe": "drafts",
              "trash": "trash", "deleted items": "trash", "deleted messages": "trash", "koš": "trash", "papierkorb": "trash",
              "bin": "trash", "junk": "junk", "spam": "junk", "junk e-mail": "junk", "nevyžádaná pošta": "junk",
              "archive": "archive", "archiv": "archive", "archives": "archive"}

function role_from_flags(flags):
    for f in flags:
        if f in ["\\sent", "\\drafts", "\\trash", "\\junk", "\\archive", "\\all", "\\important", "\\flagged"]:
            return f
        end
    end
    return ""
end

function mailbox_role(name, flags, delim):
    for f in flags:
        if f == "\\sent":
            return "sent"
        elif f == "\\drafts":
            return "drafts"
        elif f == "\\trash":
            return "trash"
        elif f == "\\junk":
            return "junk"
        elif f == "\\archive":
            return "archive"
        elif f == "\\all":
            # Gmail "[Gmail]/All Mail": vsechny zpravy (i z Dorucene) - jen pod "Dalsi", nestahovat
            return "all"
        elif f == "\\important":
            return "important"
        elif f == "\\flagged":
            return "starred"
        end
    end
    if name.upper() == "INBOX":
        return "inbox"
    end
    leaf = name
    if delim != "":
        p = name.find(delim)
        while p >= 0:
            leaf = leaf[p + len(delim):]
            p = leaf.find(delim)
        end
    end
    if name.upper().startswith("INBOX" + delim) and delim != "":
        leaf = name[6:]
    end
    return ROLE_NAMES.get(leaf.lower(), "")
end

# LIST -> [{"raw", "name", "delim", "flags", "role", "selectable"}]
function list_mailboxes(conn):
    r = command(conn, "LIST \"\" \"*\"")
    out = []
    for resp in r["untagged"]:
        t = resp_tokens(resp)
        if len(t) < 4 or tstr(t[0]).upper() != "LIST":
            continue
        end
        flags = []
        for f in tlist(t[1]):
            flags.append(tstr(f).lower())
        end
        delim = tstr(t[2])
        raw = tstr(t[3])
        name = mutf7_decode(raw)
        if raw.upper() == "INBOX":
            raw = "INBOX"
        end
        selectable = not ("\\noselect" in flags or "\\nonexistent" in flags)
        out.append({"raw": raw, "name": name, "delim": delim, "flags": flags, "role": mailbox_role(name, flags, delim), "selectable": selectable})
    end
    # role podle jmena jen tam, kde ji zadna schranka nema z priznaku SPECIAL-USE, a jen jednou
    flagged = {}
    for b in out:
        if role_from_flags(b["flags"]) != "":
            flagged[b["role"]] = True
        end
    end
    seen = {}
    for b in out:
        r = b["role"]
        if r == "" or r == "inbox":
            continue
        end
        if role_from_flags(b["flags"]) == "":
            if r in flagged or r in seen:
                b["role"] = ""
                continue
            end
        end
        seen[r] = True
    end
    return out
end

# SELECT (CONDSTORE / QRESYNC) -> {"exists", "uidvalidity", "uidnext", "highestmodseq", "vanished": [uid], "fetches": [...]}
function select(conn, raw, known_validity=0, known_modseq=0):
    arg = ""
    if conn["qresync"] and known_validity > 0 and known_modseq > 0:
        arg = " (QRESYNC (" + String(known_validity) + " " + String(known_modseq) + "))"
    elif conn["condstore"]:
        arg = " (CONDSTORE)"
    end
    r = command(conn, "SELECT " + quote(raw) + arg)
    info = {"exists": 0, "uidvalidity": 0, "uidnext": 0, "highestmodseq": 0, "vanished": [], "fetches": [], "readonly": False}
    call absorb(info, r["untagged"])
    code = r["code"].upper()
    if code.startswith("READ-ONLY"):
        info["readonly"] = True
    end
    conn["selected"] = raw
    return info
end

# Zpracuje nevyzadane odpovedi (EXISTS, OK [UIDNEXT], VANISHED, FETCH ...) do slovniku stavu
function absorb(info, untagged):
    for resp in untagged:
        line = first_line(resp)
        up = line.upper()
        if up.startswith("OK [") or up.startswith("NO [") or up.startswith("BAD ["):
            code = status_parts(line)[1]
            words = code.split(" ")
            key = words[0].upper()
            if len(words) > 1:
                value = mime.to_int(words[1], 0)
                if key == "UIDVALIDITY":
                    info["uidvalidity"] = value
                elif key == "UIDNEXT":
                    info["uidnext"] = value
                elif key == "HIGHESTMODSEQ":
                    info["highestmodseq"] = value
                end
            end
            if key == "NOMODSEQ":
                info["highestmodseq"] = 0
            end
            continue
        end
        t = resp_tokens(resp)
        if len(t) >= 2 and tstr(t[1]).upper() == "EXISTS":
            info["exists"] = tint(t[0], 0)
        elif len(t) >= 2 and tstr(t[0]).upper() == "VANISHED":
            set_text = tstr(t[len(t) - 1])
            info["vanished"].extend(expand_set(set_text))
        elif len(t) >= 3 and tstr(t[1]).upper() == "FETCH":
            info["fetches"].append(fetch_dict(t))
        end
    end
    return 0
end

# ---- FETCH ------------------------------------------------------------------------------------------------

function fetch_key(name):
    k = name.upper()
    lt = k.find("<")
    if lt > 0 and k.endswith(">"):
        k = k[0:lt]
    end
    return k.replace(".PEEK", "")
end

function fetch_dict(t):
    d = {"SEQ": tint(t[0], 0)}
    items = tlist(t[2])
    i = 0
    while i + 1 < len(items):
        d[fetch_key(tstr(items[i]))] = items[i + 1]
        i += 2
    end
    return d
end

function fetches(untagged):
    out = []
    for resp in untagged:
        t = resp_tokens(resp)
        if len(t) >= 3 and tstr(t[1]).upper() == "FETCH":
            out.append(fetch_dict(t))
        end
    end
    return out
end

function uid_fetch(conn, uidset, items, modifiers=""):
    extra = ""
    if modifiers != "":
        extra = " (" + modifiers + ")"
    end
    r = command(conn, "UID FETCH " + uidset + " (" + items + ")" + extra, True, 120000)
    return r
end

function fetch_seq(conn, seqset, items):
    return command(conn, "FETCH " + seqset + " (" + items + ")", True, 120000)
end

function uid_search(conn, criteria):
    r = command(conn, "UID SEARCH " + criteria, True, 120000)
    out = []
    for resp in r["untagged"]:
        line = first_line(resp)
        if line.upper().startswith("SEARCH"):
            for w in line.split(" ")[1:]:
                v = mime.to_int(w, -1)
                if v > 0:
                    out.append(v)
                end
            end
        end
    end
    return out
end

# "1:3,7,9:10" -> [1, 2, 3, 7, 9, 10] (nejvys 200000 polozek)
function expand_set(text):
    out = []
    for part in text.split(","):
        colon = part.find(":")
        if colon < 0:
            v = mime.to_int(part, -1)
            if v > 0:
                out.append(v)
            end
            continue
        end
        a = mime.to_int(part[0:colon], -1)
        b = mime.to_int(part[colon + 1:], -1)
        if a < 0 or b < 0:
            continue
        end
        if a > b:
            tmp = a
            a = b
            b = tmp
        end
        if b - a > 200000:
            a = b - 200000
        end
        v = a
        while v <= b:
            out.append(v)
            v += 1
        end
    end
    return out
end

# serazena cisla -> "1:3,7,9:10"
function compress_set(numbers):
    items = sorted(numbers)
    out = []
    i = 0
    n = len(items)
    while i < n:
        start = items[i]
        j = i
        while j + 1 < n and items[j + 1] == items[j] + 1:
            j += 1
        end
        if j > i:
            out.append(String(start) + ":" + String(items[j]))
        else:
            out.append(String(start))
        end
        i = j + 1
    end
    return ",".join(out)
end

# ---- ENVELOPE a BODYSTRUCTURE --------------------------------------------------------------------------------

function addresses(tok):
    out = []
    for a in tlist(tok):
        if type(a) != "List" or len(a) < 4:
            continue
        end
        if a[3] == None:
            continue                     # zacatek/konec skupiny (RFC 3501 7.4.2)
        end
        email = tstr(a[2]) + "@" + tstr(a[3])
        out.append([mime.decode_words(tstr(a[0])), email])
    end
    return out
end

function envelope(tok):
    e = tlist(tok)
    if len(e) < 10:
        return {"date": 0, "subject": "", "from": [], "to": [], "cc": [], "reply_to": [], "message_id": "", "in_reply_to": ""}
    end
    return {"date": mime.parse_date(tstr(e[0])), "subject": mime.decode_words(tstr(e[1])), "from": addresses(e[2]),
            "to": addresses(e[5]), "cc": addresses(e[6]), "reply_to": addresses(e[4]), "in_reply_to": tstr(e[8]),
            "message_id": tstr(e[9])}
end

function plist(tok):
    out = {}
    items = tlist(tok)
    i = 0
    while i + 1 < len(items):
        out[tstr(items[i]).lower()] = tstr(items[i + 1])
        i += 2
    end
    return out
end

# parametry vcetne RFC 2231 (filename*0*=...) pres parser MIME
function params_2231(p):
    has_star = False
    for k in p.keys():
        if k.find("*") >= 0:
            has_star = True
        end
    end
    if not has_star:
        out = {}
        for k in p.keys():
            out[k] = mime.decode_words(p[k])
        end
        return out
    end
    text = "x"
    for k in p.keys():
        text = text + "; " + k + "=" + quote(p[k])
    end
    return mime.parse_params(text)[1]
end

function child_section(section, index):
    if section == "":
        return String(index)
    end
    return section + "." + String(index)
end

function disposition(tok):
    d = tlist(tok)
    if len(d) == 0:
        return ["", {}]
    end
    params = {}
    if len(d) > 1:
        params = params_2231(plist(d[1]))
    end
    return [tstr(d[0]).lower(), params]
end

# Strom casti: {"type", "params", "encoding", "size", "disposition", "filename", "section", "parts"}
function bodystructure(tok, section="", depth=0):
    node = tlist(tok)
    if len(node) == 0:
        return {"type": "text/plain", "params": {}, "encoding": "", "size": 0, "disposition": "", "filename": "", "section": "1", "parts": []}
    end
    if type(node[0]) == "List":
        parts = []
        i = 0
        while i < len(node) and type(node[i]) == "List":
            if depth < 30:
                parts.append(bodystructure(node[i], child_section(section, i + 1), depth + 1))
            end
            i += 1
        end
        subtype = "mixed"
        params = {}
        disp = ["", {}]
        if i < len(node):
            subtype = tstr(node[i]).lower()
        end
        if i + 1 < len(node):
            params = plist(node[i + 1])
        end
        if i + 2 < len(node):
            disp = disposition(node[i + 2])
        end
        return {"type": "multipart/" + subtype, "params": params, "encoding": "", "size": 0, "disposition": disp[0], "filename": "", "section": section, "parts": parts}
    end
    if len(node) < 7:
        return {"type": "application/octet-stream", "params": {}, "encoding": "", "size": 0, "disposition": "", "filename": "", "section": section, "parts": []}
    end
    main = tstr(node[0]).lower() + "/" + tstr(node[1]).lower()
    params = params_2231(plist(node[2]))
    ext = 7
    if main.startswith("text/"):
        ext = 8
    elif main == "message/rfc822" or main == "message/global":
        ext = 10
    end
    disp = ["", {}]
    if ext + 1 < len(node):
        disp = disposition(node[ext + 1])
    end
    filename = disp[1].get("filename", "")
    if filename == "":
        filename = params.get("name", "")
    end
    sec = section
    if sec == "":
        sec = "1"
    end
    return {"type": main, "params": params, "encoding": tstr(node[5]).lower(), "size": tint(node[6], 0), "disposition": disp[0],
            "filename": filename, "section": sec, "parts": []}
end

# Cast pro nahled: prvni text/plain (v alternative prednost), jinak text/html; {} kdyz zadna neni
function preview_part(node):
    t = node["type"]
    if t.startswith("multipart/"):
        if t == "multipart/alternative":
            for p in node["parts"]:
                if p["type"] == "text/plain":
                    return p
                end
            end
        end
        for p in node["parts"]:
            found = preview_part(p)
            if len(found) > 0:
                return found
            end
        end
        return {}
    end
    if (t == "text/plain" or t == "text/html") and node["disposition"] != "attachment":
        return node
    end
    return {}
end

function has_attachments(node):
    t = node["type"]
    if t.startswith("multipart/"):
        for p in node["parts"]:
            if has_attachments(p):
                return True
            end
        end
        return False
    end
    if node["disposition"] == "attachment":
        return True
    end
    if node["filename"] != "" and node["disposition"] != "inline":
        return True
    end
    return t == "message/rfc822" or t.startswith("application/")
end

# ---- zmeny ------------------------------------------------------------------------------------------------

function store_flags(conn, uidset, add, flags):
    sign = "-"
    if add:
        sign = "+"
    end
    return command(conn, "UID STORE " + uidset + " " + sign + "FLAGS.SILENT (" + " ".join(flags) + ")")
end

# Presun zprav (MOVE, jinak COPY + \Deleted + UID EXPUNGE / EXPUNGE)
function move(conn, uidset, target_raw):
    if has_cap(conn, "MOVE"):
        return command(conn, "UID MOVE " + uidset + " " + quote(target_raw))
    end
    call command(conn, "UID COPY " + uidset + " " + quote(target_raw))
    call store_flags(conn, uidset, True, ["\\Deleted"])
    return expunge(conn, uidset)
end

function expunge(conn, uidset):
    if has_cap(conn, "UIDPLUS"):
        return command(conn, "UID EXPUNGE " + uidset)
    end
    return command(conn, "EXPUNGE")
end

function create(conn, raw):
    return command(conn, "CREATE " + quote(raw), False)
end

# ---- IDLE (RFC 2177) ------------------------------------------------------------------------------------------

function idle_start(conn):
    tag = next_tag(conn)
    call write(conn, tag + " IDLE\r\n")
    loop:
        r = read_response(conn, TIMEOUT, False)
        if r["tag"] == "+":
            conn["idle_tag"] = tag
            return []
        end
        if r["tag"] == tag:
            call fail("no", status_parts(first_line(r))[2])
        end
    end
end

# Odpovedi, ktere prisly behem IDLE (neblokuje); po nich zkontrolovat tls.pending
function poll(conn):
    out = []
    loop:
        r = read_response(conn, 0, True)
        if len(r) == 0:
            break
        end
        if r["tag"] == "*":
            line = first_line(r)
            if line.upper().startswith("BYE"):
                conn["closed"] = True
                call fail("closed", status_parts(line)[2])
            end
        end
        out.append(r)
    end
    return out
end

function pending(conn):
    if len(conn["buf"]) - conn["pos"] > 0:
        return True
    end
    if conn["tls"] != 0:
        return tls.pending(conn["tls"]) > 0
    end
    return False
end

function idle_done(conn):
    tag = conn["idle_tag"]
    conn["idle_tag"] = ""
    if tag == "":
        return []
    end
    call write(conn, "DONE\r\n")
    r = finish(conn, tag, False, TIMEOUT)
    return r["untagged"]
end
