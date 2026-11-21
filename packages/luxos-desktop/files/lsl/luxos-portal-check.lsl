# lsl: link libglib-2.0.so.0
# LuxOS - je za "omezenym pripojenim" sit s portalem (hotel, skola, vlak)? (drive Python)
#
#   luxos-portal-check        vypise jeden radek: "online", "portal URL IP" nebo "none" (cte luxos-hub
#                             a luxos-network-login)
#   luxos-portal-check --dns-servers   jen vypise DNS servery, ktere by se zkusily (ladeni, testy)
#
# NetworkManager pozna portal jen kdyz funguje systemove DNS. S Tailscale (resolv.conf ukazuje na
# 100.100.100.100) nebo jinym VPN DNS se za portalem neprelozi nic a NM hlasi jen "omezene pripojeni"
# - okno pro prihlaseni se pak neotevrelo. Tady se adresa kontroly pripojeni preklada primo DNS
# serverem site (z DHCP, NetworkManager ho zna i pod VPN) a pozadavek HTTP jde na ziskanou IP:
# odpoved jina nez text kontroly (presmerovani, prihlasovaci stranka) = portal.
#
# Kdyz DNS site neodpovi, zkusi se brana site (casto je i DNS serverem), verejne DNS (portal dotazy
# casto zachytava a vraci svou adresu) a nakonec posledni znama IP adresy kontroly (portal zachyti
# kazdy pozadavek HTTP). Kazdy vysledek se zapise do zaznamu systemu (journalctl -t luxos-portal-check).
#
# Testy: LUXOS_PORTAL_DNS (servery oddelene carkou, i "IP:port"), LUXOS_PORTAL_URI,
# LUXOS_PORTAL_RESPONSE, LUXOS_PORTAL_HTTP_PORT, LUXOS_PORTAL_CACHE (soubor s posledni IP),
# LUXOS_PORTAL_NOLOG=1.
load env, net, gio, process, random
load luxos_glib, glib as glib
load luxos_i18n as i18n
load luxos_regex as re
load luxos_text as txt

DEFAULT_URI = "http://ping.archlinux.org/nm-check.txt"
PUBLIC_DNS = ["1.1.1.1", "8.8.8.8"]
DEFAULT_RESPONSE = "NetworkManager is online"
TIMEOUT_MS = 3000

# vystup nmcli se cte jako text ("connected"): bez prekladu, jinak cesky "připojeno" nic nenajde
function command_output(argv):
    result = None
    safe:
        result = process.capture_result("/usr/bin/env", ["LC_ALL=C", "timeout", "5"] + argv)
    end
    if result == None:
        return ""
    end
    return String(result["stdout"])
end

function journal(msg):
    if env.get("LUXOS_PORTAL_NOLOG", "") == "1":
        return 0
    end
    call command_output(["logger", "-t", "luxos-portal-check", "--", msg])
end

function is_ipv4(text):
    parts = text.split(".")
    if len(parts) != 4:
        return False
    end
    for p in parts:
        if p == "" or not txt.is_digits(p):
            return False
        end
    end
    return True
end

function cache_path():
    path = env.get("LUXOS_PORTAL_CACHE", "")
    if path != "":
        return path
    end
    base = env.get("XDG_CACHE_HOME", "")
    if base == "":
        base = glib.home_dir() + "/.cache"
    end
    return base + "/luxos/portal-check-ip"
end

function cached_ip():
    ip = glib.read_text(cache_path()).strip()
    if is_ipv4(ip):
        return ip
    end
    return ""
end

function save_ip(ip):
    path = cache_path()
    safe:
        call glib.mkdir_p(path[:txt.rfind(path, "/")])
        call writefile(path, ip + "\n")
    end
end

function add_new(items, value):
    if not (value in items):
        items.append(value)
    end
end

# DNS servery z DHCP pripojenych zarizeni (Wi-Fi, kabel), ne z /etc/resolv.conf; pak brana site a verejne
# DNS (portal dotazy casto zachyti)
function dns_servers():
    forced = env.get("LUXOS_PORTAL_DNS", None)
    if forced != None:
        out = []
        for s in forced.split(","):
            if s.strip() != "":
                out.append(s.strip())
            end
        end
        return out
    end
    servers = []
    gateways = []
    for line in txt.lines(command_output(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device"])):
        parts = line.split(":")
        if len(parts) < 3 or not (parts[1] == "wifi" or parts[1] == "ethernet") or not parts[2].startswith("connected"):
            continue
        end
        out = txt.lines(command_output(["nmcli", "-g", "IP4.DNS,IP4.GATEWAY", "device", "show", parts[0]]))
        if len(out) > 0:
            for s in out[0].replace("|", " ").replace("\t", " ").split(" "):
                if is_ipv4(s):
                    call add_new(servers, s)
                end
            end
        end
        if len(out) > 1 and is_ipv4(out[1].strip()):
            call add_new(gateways, out[1].strip())
        end
    end
    result = servers + []
    for g in gateways:
        call add_new(result, g)
    end
    for p in PUBLIC_DNS:
        if not (p in servers):
            call add_new(result, p)
        end
    end
    return result
end

function check_uri():
    uri = env.get("LUXOS_PORTAL_URI", "")
    if uri != "":
        return uri
    end
    value = ""
    safe:
        value = gio.get_property(gio.system_bus(), "org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager",
                                 "org.freedesktop.NetworkManager", "ConnectivityCheckUri")
    end
    m = re.search("'(http://[^' ]+)'", value, False)
    if m != None:
        return m[1]
    end
    return DEFAULT_URI
end

# ---- adresy ----------------------------------------------------------------------------------------------

# urlsplit: [scheme, netloc, cesta, dotaz]
function split_url(url):
    scheme = ""
    rest = url
    colon = url.find(":")
    if colon > 0 and re.search("^[A-Za-z][A-Za-z0-9+.-]*$", url[:colon], False) != None:
        scheme = url[:colon].lower()
        rest = url[colon + 1:]
    end
    frag = rest.find("#")
    if frag >= 0:
        rest = rest[:frag]
    end
    netloc = ""
    if rest.startswith("//"):
        rest = rest[2:]
        cut = len(rest)
        for ch in ["/", "?"]:
            i = rest.find(ch)
            if i >= 0 and i < cut:
                cut = i
            end
        end
        netloc = rest[:cut]
        rest = rest[cut:]
    end
    query = ""
    q = rest.find("?")
    if q >= 0:
        query = rest[q + 1:]
        rest = rest[:q]
    end
    return [scheme, netloc, rest, query]
end

function hostname(netloc):
    host = netloc
    at = txt.rfind(host, "@")
    if at >= 0:
        host = host[at + 1:]
    end
    if host.startswith("["):
        end_ = host.find("]")
        if end_ > 0:
            return host[1:end_].lower()
        end
    end
    colon = host.find(":")
    if colon >= 0:
        host = host[:colon]
    end
    return host.lower()
end

function remove_dots(path):
    out = []
    parts = path.split("/")
    for i in range(len(parts)):
        seg = parts[i]
        if seg == "..":
            if len(out) > 1:
                call out.pop()
            end
            if i == len(parts) - 1:
                out.append("")
            end
        elif seg == ".":
            if i == len(parts) - 1:
                out.append("")
            end
        else:
            out.append(seg)
        end
    end
    return "/".join(out)
end

# urljoin pro adresy http(s)
function join_url(base, ref):
    if ref == "":
        return base
    end
    r = split_url(ref)
    if r[0] != "":
        return ref
    end
    b = split_url(base)
    prefix = b[0] + "://" + b[1]
    if ref.startswith("//"):
        return b[0] + ":" + ref
    end
    if ref.startswith("/"):
        return prefix + remove_dots(r[2]) + ("?" + r[3] if r[3] != "" else "")
    end
    if ref.startswith("?"):
        return prefix + b[2] + ref
    end
    if ref.startswith("#"):
        return base
    end
    dir = b[2][:txt.rfind(b[2], "/") + 1]
    if dir == "":
        dir = "/"
    end
    return prefix + remove_dots(dir + r[2]) + ("?" + r[3] if r[3] != "" else "")
end

# ---- DNS a HTTP ------------------------------------------------------------------------------------------

function u16(data, pos):
    return data[pos] * 256 + data[pos + 1]
end

function skip_name(data, pos):
    while pos < len(data):
        n = data[pos]
        if n == 0:
            return pos + 1
        end
        if n & 192 == 192:
            return pos + 2
        end
        pos += n + 1
    end
    return pos
end

function push16(buf, value):
    buf.append((value >> 8) & 255)
    buf.append(value & 255)
end

# Dotaz A primo na server (UDP); prvni IPv4 adresa nebo ""
function resolve(host, server):
    if is_ipv4(host):
        return host
    end
    addr = server
    port = 53
    colon = server.find(":")
    if colon >= 0:
        addr = server[:colon]
        if server[colon + 1:] != "":
            port = Int(server[colon + 1:])
        end
    end
    qid = random.randint(0, 65535)
    q = ByteArray()
    for value in [qid, 256, 1, 0, 0, 0]:
        call push16(q, value)
    end
    stripped = host
    while stripped.endswith("."):
        stripped = stripped[:len(stripped) - 1]
    end
    for label in stripped.split("."):
        raw = net.bytes(label)
        q.append(len(raw) & 255)
        for b in raw:
            q.append(b)
        end
    end
    q.append(0)
    call push16(q, 1)
    call push16(q, 1)
    data = None
    fd = -1
    safe:
        fd = net.udp_open("ipv4")
        call net.sendto(fd, q, addr, port)
        got = net.recvfrom(fd, 4096, TIMEOUT_MS)
        if len(got) > 0:
            data = got[0]
        end
    end
    if fd >= 0:
        call net.close(fd)
    end
    if data == None or len(data) < 12 or u16(data, 0) != qid:
        return ""
    end
    ancount = u16(data, 6)
    pos = skip_name(data, 12) + 4
    for i in range(ancount):
        pos = skip_name(data, pos)
        if pos + 10 > len(data):
            return ""
        end
        rtype = u16(data, pos)
        rdlen = u16(data, pos + 8)
        pos += 10
        if rtype == 1 and rdlen == 4 and pos + 4 <= len(data):
            return String(data[pos]) + "." + String(data[pos + 1]) + "." + String(data[pos + 2]) + "." + String(data[pos + 3])
        end
        pos += rdlen
    end
    return ""
end

function find_bytes(data, pattern):
    n = len(pattern)
    for i in range(len(data) - n + 1):
        hit = True
        for k in range(n):
            if data[i + k] != pattern[k]:
                hit = False
                break
            end
        end
        if hit:
            return i
        end
    end
    return -1
end

function latin1(data, start, stop):
    out = []
    for i in range(start, stop):
        out.append(chr(data[i]))
    end
    return "".join(out)
end

# [status, hlavicky, telo] nebo None; bez nasledovani presmerovani
function http_get(ip, host, path):
    port = Int(env.get("LUXOS_PORTAL_HTTP_PORT", "80"))
    raw = ByteArray()
    fd = -1
    ok = False
    safe:
        fd = net.tcp_connect(ip, port, TIMEOUT_MS)
        call net.send(fd, "GET " + path + " HTTP/1.0\r\nHost: " + host + "\r\nUser-Agent: LuxOS\r\nConnection: close\r\n\r\n", TIMEOUT_MS)
        while len(raw) < 65536:
            chunk = net.recv(fd, 8192, TIMEOUT_MS)
            if len(chunk) == 0:
                break
            end
            for b in chunk:
                raw.append(b)
            end
        end
        ok = True
    end
    if fd >= 0:
        call net.close(fd)
    end
    if not ok:
        return None
    end
    split = find_bytes(raw, [13, 10, 13, 10])
    head = ""
    body = ""
    if split < 0:
        head = latin1(raw, 0, len(raw))
    else:
        head = latin1(raw, 0, split)
        body = utf8(raw, split + 4)
    end
    lines = head.split("\r\n")
    m = re.search("^HTTP/\\d(?:\\.\\d)?\\s+(\\d{3})", lines[0], False)
    if m == None:
        return None
    end
    headers = {}
    for line in lines[1:]:
        colon = line.find(":")
        key = line
        value = ""
        if colon >= 0:
            key = line[:colon]
            value = line[colon + 1:]
        end
        headers[key.strip().lower()] = value.strip()
    end
    return [Int(m[1]), headers, body]
end

# Telo jako UTF-8; neplatne bajty nahradi U+FFFD (jako decode("utf-8", "replace"))
function utf8(data, start):
    clean = ByteArray()
    i = start
    n = len(data)
    while i < n:
        b = data[i]
        size = 0
        if b < 128:
            size = 1
        elif b >= 194 and b <= 223:
            size = 2
        elif b >= 224 and b <= 239:
            size = 3
        elif b >= 240 and b <= 244:
            size = 4
        end
        good = size > 0 and i + size <= n
        if good:
            for k in range(1, size):
                if data[i + k] & 192 != 128:
                    good = False
                end
            end
        end
        if good:
            for k in range(size):
                clean.append(data[i + k])
            end
            i += size
        else:
            for x in [239, 191, 189]:
                clean.append(x)
            end
            i += 1
        end
    end
    return net.text(clean)
end

# Prihlasovaci adresa z HTML bez presmerovani (meta refresh / window.location)
function page_url(body, base):
    m = re.search("http-equiv=[\"']?refresh[\"']?[^>]*url=([^\"'>\\s]+)", body, True)
    if m == None:
        m = re.search("(?:window\\.)?location(?:\\.href)?\\s*=\\s*[\"']([^\"']+)", body, False)
    end
    if m != None:
        return join_url(base, m[1])
    end
    return base
end

# ---- hlavni ----------------------------------------------------------------------------------------------

function main():
    uri = check_uri()
    expected = env.get("LUXOS_PORTAL_RESPONSE", DEFAULT_RESPONSE)
    parts = split_url(uri)
    host = hostname(parts[1])
    path = parts[2]
    if path == "":
        path = "/"
    end
    if parts[3] != "":
        path = path + "?" + parts[3]
    end
    servers = dns_servers()
    tried = []
    candidates = []                       # [IP kontroly, DNS server pro prihlasovaci stranku]
    for server in servers:
        ip = resolve(host, server)
        tried.append(server + "=" + (ip if ip != "" else "-"))
        if ip != "":
            candidates.append([ip, server])
        end
    end
    last = cached_ip()
    if last != "":
        known = False
        for c in candidates:
            if c[0] == last:
                known = True
            end
        end
        if not known:
            # portal zachyti i pozadavek na IP
            candidates.append([last, servers[0] if len(servers) > 0 else ""])
        end
    end
    for c in candidates:
        ip = c[0]
        server = c[1]
        res = http_get(ip, parts[1], path)
        if res == None:
            continue
        end
        status = res[0]
        headers = res[1]
        body = res[2]
        if status >= 200 and status < 300 and body.strip().startswith(expected):
            call save_ip(ip)
            call journal("online (" + ip + " via " + server + ")")
            print "online"
            return 0
        end
        url = ""
        if status >= 300 and status < 400 and headers.get("location", "") != "":
            url = join_url(uri, headers["location"])
        else:
            url = page_url(body, uri)
        end
        # IP prihlasovaci stranky (systemove DNS ji neprelozi): pro okno prihlaseni
        target = hostname(split_url(url)[1])
        if target == "":
            target = host
        end
        target_ip = ""
        if target == host:
            target_ip = ip
        elif server != "":
            target_ip = resolve(target, server)
        end
        if target_ip == "" and is_ipv4(target):
            target_ip = target
        end
        call journal("portal " + url + " " + target_ip + " (HTTP " + String(status) + " from " + ip + ", DNS " + " ".join(tried) + ")")
        print "portal " + url + " " + target_ip
        return 0
    end
    call journal("none (DNS " + (" ".join(tried) if len(tried) > 0 else "-") + ", cached " + (last if last != "" else "-") + ")")
    print "none"
    return 0
end

first = ""
if len(args) > 1:
    first = args[1]
end
if first == "-h" or first == "--help":
    print "luxos-portal-check - " + i18n.T("check whether the network needs a sign-in on a login page") + "\n\n" + i18n.T("Usage:") + " luxos-portal-check\n" + i18n.T("Prints online, portal URL IP or none (used by luxos-hub).")
elif first == "--dns-servers":
    for s in dns_servers():
        print s
    end
else:
    call main()
end
