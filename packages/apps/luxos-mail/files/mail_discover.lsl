# Posta LuxOS - automaticke nalezeni serveru podle e-mailove adresy (jako Thunderbird):
#   1. autoconfig poskytovatele: https://autoconfig.<domena>/mail/config-v1.1.xml?emailaddress=...
#      a https://<domena>/.well-known/autoconfig/mail/config-v1.1.xml
#   2. databaze ISPDB Thunderbirdu (https://autoconfig.thunderbird.net/v1.1/<domena>), i podle MX
#   3. zaznamy DNS SRV (RFC 6186/8314): _imaps._tcp, _imap._tcp, _submissions._tcp, _submission._tcp
#   4. odhad: imap.<domena>, mail.<domena>, <domena> (993 TLS, pak 143 STARTTLS) - jen jmena s DNS
#      zaznamem; s probe=True se server overi spojenim a pozdravem IMAP (bez prihlaseni)
# Vysledek: {"imap": {host, port, security, user}, "smtp": {...}, "source", "steps": [...], "error"}
# Testy: LUXOS_MAIL_AUTOCONFIG_URLS (sablony URL oddelene mezerou, %DOMAIN% %EMAIL%), LUXOS_MAIL_ISPDB_URL,
#        LUXOS_MAIL_FAKE_DNS (JSON {"SRV:_imaps._tcp.x": [[prio, vaha, port, cil]], "MX:x": [...], "A:x": True})
load env, json, http, net
load mail_bytes as mb
load mail_imap as imap
load mail_provider as provider

DEFAULT_URLS = "https://autoconfig.%DOMAIN%/mail/config-v1.1.xml?emailaddress=%EMAIL% https://%DOMAIN%/.well-known/autoconfig/mail/config-v1.1.xml"
ISPDB = "https://autoconfig.thunderbird.net/v1.1/%DOMAIN%"

fake = {"loaded": False, "data": {}}

function fake_dns():
    if not fake["loaded"]:
        fake["loaded"] = True
        path = env.get("LUXOS_MAIL_FAKE_DNS", "")
        if path != None and path != "" and exists(path):
            safe:
                fake["data"] = json.decode(readfile(path))
            end
        end
    end
    path = env.get("LUXOS_MAIL_FAKE_DNS", "")
    return path != None and path != ""
end

# ---- DNS ----------------------------------------------------------------------------------------------------

function read_name(b, pos):
    labels = []
    p = pos
    jumped = False
    after = -1
    guard = 0
    while p < len(b) and guard < 128:
        guard += 1
        n = b[p]
        if n == 0:
            p += 1
            break
        end
        if n >= 192:
            if p + 1 >= len(b):
                break
            end
            target = ((n & 63) << 8) | b[p + 1]
            if not jumped:
                after = p + 2
            end
            jumped = True
            p = target
            continue
        end
        labels.append(net.text(b, p + 1, n))
        p += n + 1
    end
    if not jumped:
        after = p
    end
    return [".".join(labels), after]
end

function u16(b, p):
    return (b[p] << 8) | b[p + 1]
end

# odpovedi daneho typu: SRV -> [prio, vaha, port, cil], MX -> [preference, server], A/AAAA -> True
function dns_query(name, kind):
    out = []
    if fake_dns():
        key = kind + ":" + name
        value = fake["data"].get(key, None)
        dot = name.find(".")
        if value == None and dot > 0:
            value = fake["data"].get(kind + ":*" + name[dot:], None)
        end
        if type(value) == "List":
            return value
        end
        if value == True:
            return [True]
        end
        return out
    end
    code = 33
    if kind == "MX":
        code = 15
    elif kind == "A":
        code = 1
    elif kind == "AAAA":
        code = 28
    end
    b = mb.res_query(name, code)
    if len(b) < 12:
        return out
    end
    qd = u16(b, 4)
    an = u16(b, 6)
    p = 12
    for i in range(qd):
        p = read_name(b, p)[1] + 4
    end
    for i in range(an):
        if p + 10 > len(b):
            break
        end
        p = read_name(b, p)[1]
        if p + 10 > len(b):
            break
        end
        t = u16(b, p)
        rdlen = u16(b, p + 8)
        rd = p + 10
        if t == code and rd + rdlen <= len(b):
            if code == 33 and rdlen >= 7:
                target = read_name(b, rd + 6)[0]
                out.append([u16(b, rd), u16(b, rd + 2), u16(b, rd + 4), target])
            elif code == 15 and rdlen >= 3:
                out.append([u16(b, rd), read_name(b, rd + 2)[0]])
            elif code == 1 or code == 28:
                out.append(True)
            end
        end
        p = rd + rdlen
    end
    return out
end

function srv_best(name):
    best = []
    for r in dns_query(name, "SRV"):
        target = String(r[3]).strip()
        if target.endswith("."):
            target = target[0:len(target) - 1]
        end
        if target == "" or target == "." or r[2] == 0:
            continue                   # "." = sluzba neni k dispozici (RFC 2782)
        end
        if len(best) == 0 or r[0] < best[0]:
            best = [r[0], r[1], r[2], target]
        end
    end
    return best
end

function has_address(host):
    return len(dns_query(host, "A")) > 0 or len(dns_query(host, "AAAA")) > 0
end

# ---- autoconfig XML -------------------------------------------------------------------------------------------

function tag_text(block, name):
    a = block.find("<" + name + ">")
    if a < 0:
        return ""
    end
    rest = block[a + len(name) + 2:]
    e = rest.find("</" + name + ">")
    if e < 0:
        return ""
    end
    return rest[0:e].strip()
end

function expand(template, email):
    at = email.find("@")
    local = email
    domain = ""
    if at >= 0:
        local = email[0:at]
        domain = email[at + 1:]
    end
    return template.replace("%EMAILADDRESS%", email).replace("%EMAILLOCALPART%", local).replace("%EMAILDOMAIN%", domain)
end

function servers(xml, element, kind, email):
    out = []
    pos = 0
    rest = xml
    loop:
        a = rest.find("<" + element)
        if a < 0:
            break
        end
        rest = rest[a:]
        close = rest.find("</" + element + ">")
        if close < 0:
            break
        end
        block = rest[0:close]
        head_end = block.find(">")
        head = block[0:head_end]
        rest = rest[close + len(element) + 3:]
        if head.find("type=\"" + kind + "\"") < 0:
            continue
        end
        socket = tag_text(block, "socketType").upper()
        security = ""
        if socket == "SSL" or socket == "TLS":
            security = "ssl"
        elif socket == "STARTTLS":
            security = "starttls"
        else:
            continue                   # bez sifrovani nepouzivat
        end
        port = 0
        safe:
            port = Int(tag_text(block, "port"))
        end
        host = expand(tag_text(block, "hostname"), email)
        user = expand(tag_text(block, "username"), email)
        if host == "" or port <= 0:
            continue
        end
        if user == "":
            user = email
        end
        out.append({"host": host, "port": port, "security": security, "user": user})
    end
    return out
end

function pick(list):
    for s in list:
        if s["security"] == "ssl":
            return s
        end
    end
    if len(list) > 0:
        return list[0]
    end
    return {}
end

function try_url(result, url, email, source):
    resp = {}
    ok = True
    try:
        resp = http.get(url, {"Accept": "application/xml"}, 8)
    else:
        ok = False
    end
    if not ok:
        result["steps"].append({"step": source, "url": url, "result": "error: " + String(last_error())})
        return False
    end
    if not resp["ok"] or resp["text"].find("<clientConfig") < 0:
        result["steps"].append({"step": source, "url": url, "result": "HTTP " + String(resp["status"])})
        return False
    end
    imap_server = pick(servers(resp["text"], "incomingServer", "imap", email))
    if len(imap_server) == 0:
        result["steps"].append({"step": source, "url": url, "result": "no encrypted IMAP server"})
        return False
    end
    result["imap"] = imap_server
    result["smtp"] = pick(servers(resp["text"], "outgoingServer", "smtp", email))
    result["source"] = source
    result["steps"].append({"step": source, "url": url, "result": "found " + imap_server["host"]})
    return True
end

function domain_of(email):
    at = email.find("@")
    if at < 0:
        return ""
    end
    return email[at + 1:].strip().lower()
end

function url_templates():
    value = env.get("LUXOS_MAIL_AUTOCONFIG_URLS", "")
    if value == None or value == "":
        value = DEFAULT_URLS
    end
    out = []
    for u in value.split(" "):
        if u != "":
            out.append(u)
        end
    end
    return out
end

function ispdb_template():
    value = env.get("LUXOS_MAIL_ISPDB_URL", "")
    if value == None or value == "":
        return ISPDB
    end
    return value
end

function fill(template, domain, email):
    return template.replace("%DOMAIN%", domain).replace("%EMAIL%", email)
end

# Hlavni funkce; probe=False: zadne spojeni se servery posty (jen DNS a HTTPS autoconfig).
# "provider": znamy poskytovatel (mail_provider) podle domeny, nalezeneho serveru IMAP nebo MX
# (Google Workspace / Microsoft 365 na vlastni domene) - okno podle nej ukaze, jake heslo zadat.
function discover(email, probe):
    result = discover_servers(email, probe)
    host = ""
    if len(result["imap"]) > 0:
        host = String(result["imap"].get("host", ""))
    end
    mx = result.get("mx", None)
    if mx == None:
        mx = []
        if result["domain"] != "" and provider.by_domain(result["domain"]) == "" and provider.by_host(host) == "":
            mx = mx_hosts(result["domain"])
        end
    end
    result["provider"] = provider.detect(result["domain"], host, mx)
    if "mx" in result:
        call result.pop("mx")
    end
    return result
end

function mx_hosts(domain):
    out = []
    for mx in dns_query(domain, "MX"):
        host = String(mx[1]).lower()
        if host.endswith("."):
            host = host[0:len(host) - 1]
        end
        out.append(host)
    end
    return out
end

function discover_servers(email, probe):
    email = email.strip()
    domain = domain_of(email)
    result = {"email": email, "domain": domain, "imap": {}, "smtp": {}, "source": "", "steps": [], "error": ""}
    if domain == "" or domain.find(".") < 0:
        result["error"] = "invalid"
        return result
    end
    for t in url_templates():
        if try_url(result, fill(t, domain, email), email, "autoconfig"):
            return result
        end
    end
    if try_url(result, fill(ispdb_template(), domain, email), email, "ispdb"):
        return result
    end
    # ISPDB podle MX (domeny u Google, Microsoftu, Seznamu ...)
    mx_domains = []
    result["mx"] = mx_hosts(domain)
    for host in result["mx"]:
        parts = host.split(".")
        if len(parts) >= 2:
            base = parts[len(parts) - 2] + "." + parts[len(parts) - 1]
            if base != domain and base not in mx_domains:
                mx_domains.append(base)
            end
        end
    end
    for base in mx_domains:
        if try_url(result, fill(ispdb_template(), base, email), email, "ispdb-mx"):
            return result
        end
    end
    # DNS SRV
    srv = srv_best("_imaps._tcp." + domain)
    security = "ssl"
    if len(srv) == 0:
        srv = srv_best("_imap._tcp." + domain)
        security = "starttls"
    end
    if len(srv) > 0:
        result["imap"] = {"host": srv[3], "port": srv[2], "security": security, "user": email}
        result["source"] = "srv"
        result["steps"].append({"step": "srv", "result": "found " + srv[3]})
        sub = srv_best("_submissions._tcp." + domain)
        if len(sub) > 0:
            result["smtp"] = {"host": sub[3], "port": sub[2], "security": "ssl", "user": email}
        else:
            sub = srv_best("_submission._tcp." + domain)
            if len(sub) > 0:
                result["smtp"] = {"host": sub[3], "port": sub[2], "security": "starttls", "user": email}
            end
        end
        return result
    end
    result["steps"].append({"step": "srv", "result": "no records"})
    # odhad podle jmen: nejdriv server MX v teze domene (casto mail.<domena>), pak obvykla jmena.
    # Zastupny zaznam DNS (*.domena) by "nasel" kazde jmeno: pak bez overeni jen MX nebo mail.<domena>.
    candidates = []
    for mx in dns_query(domain, "MX"):
        host = String(mx[1]).lower()
        if host.endswith("."):
            host = host[0:len(host) - 1]
        end
        if host.endswith("." + domain) and host not in candidates:
            candidates.append(host)
        end
    end
    mx_count = len(candidates)
    for host in ["imap." + domain, "mail." + domain, domain]:
        if host not in candidates:
            candidates.append(host)
        end
    end
    wildcard = has_address("luxos-mail-check-" + String(glib_now() % 100000) + "." + domain)
    if wildcard:
        result["steps"].append({"step": "guess", "result": "wildcard DNS record"})
    end
    cert_host = []
    index = 0
    for host in candidates:
        index += 1
        if not has_address(host):
            result["steps"].append({"step": "guess", "host": host, "result": "no DNS record"})
            continue
        end
        if not probe:
            if wildcard and index > mx_count and host != "mail." + domain:
                result["steps"].append({"step": "guess", "host": host, "result": "skipped (wildcard DNS)"})
                continue
            end
            result["imap"] = {"host": host, "port": 993, "security": "ssl", "user": email}
            result["smtp"] = {"host": smtp_guess(host, domain), "port": 587, "security": "starttls", "user": email}
            result["source"] = "guess"
            result["steps"].append({"step": "guess", "host": host, "result": "DNS record (not verified)"})
            return result
        end
        for option in [[993, "ssl"], [143, "starttls"]]:
            ok = True
            err = ""
            try:
                conn = imap.connect(host, option[0], option[1], 5000)
                call imap.logout(conn)
            else:
                ok = False
                err = String(last_error())
            end
            if ok:
                result["imap"] = {"host": host, "port": option[0], "security": option[1], "user": email}
                result["smtp"] = {"host": smtp_guess(host, domain), "port": 587, "security": "starttls", "user": email}
                result["source"] = "guess"
                result["steps"].append({"step": "probe", "host": host, "port": option[0], "result": "IMAP server"})
                return result
            end
            kind = imap.error_kind(err)
            result["steps"].append({"step": "probe", "host": host, "port": option[0], "result": kind[0] + ": " + kind[1]})
            if kind[0] == "cert" and len(cert_host) == 0:
                cert_host = [host, option[0], option[1], kind[1]]
            end
        end
    end
    if len(cert_host) > 0:
        # zadny server neodpovedel s platnym certifikatem: ukazat chybu certifikatu (zadne obejiti)
        result["error"] = "cert"
        result["imap"] = {"host": cert_host[0], "port": cert_host[1], "security": cert_host[2], "user": email}
        result["cert_error"] = cert_host[3]
        return result
    end
    result["error"] = "notfound"
    return result
end

function glib_now():
    return Int(monotonic() * 1000)
end

function smtp_guess(imap_host, domain):
    if imap_host.startswith("imap."):
        return "smtp." + domain
    end
    return imap_host
end
