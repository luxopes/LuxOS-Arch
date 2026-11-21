# LuxOS - Sprava site (luxos-router): vychozi brana, udaje o siti, pravidla pro webovou spravu routeru,
# zarizeni v siti a rozbor vystupu nastroju (drive files/python/luxos_netadmin.py).
#
# Bez GTK a bez spousteni programu - jen rozbor textu a pravidla (tests/lsl/luxos-netadmin-test.lsl);
# prikazy spousti aplikace (LUXOS_IP, LUXOS_NMCLI, LUXOS_PING, LUXOS_CURL prepisou programy v testech).
#
#   parse_routes(text), parse_device_show(text), parse_wifi_ssid(text), parse_resolv_conf(text), split_terse(line)
#   is_lan_ip(adresa, brana), url_host(url), lan_policy(url, brana) -> allow | resolve | external | block
#   tls_exception_allowed(url, brana), router_url(brana, https, port), parse_hosts(getent), all_lan(adresy, brana)
#   parse_neigh(text), is_random_mac(mac), oui_prefix(mac), oui_parse(text, macs), scan_targets(cidr)
#   parse_ping(text) -> {"sent", "received", "avg" (None = bez casu)}
load json, math

INTERNET_HOST = "1.1.1.1"
DNS_TEST_NAME = "example.com"
PUBLIC_IP_URLS = ["https://api.ipify.org", "https://icanhazip.com"]
SPEED_URL = "https://speed.cloudflare.com/__down?bytes=10000000"
OUI_FILES = ["/usr/share/hwdata/oui.txt", "/usr/share/ieee-data/oui.txt", "/usr/share/misc/oui.txt"]
HEX = "0123456789abcdef"
SPACE = " \t\r\n"

# Slova oddelena libovolnymi mezerami a tabulatory (String.split dela jen jednu mezeru)
function words(text):
    out = []
    current = ""
    for ch in text:
        if SPACE.find(ch) >= 0:
            if current != "":
                out.append(current)
                current = ""
            end
        else:
            current += ch
        end
    end
    if current != "":
        out.append(current)
    end
    return out
end

function is_digits(text):
    if text == "":
        return False
    end
    for ch in text:
        if ord(ch) < 48 or ord(ch) > 57:
            return False
        end
    end
    return True
end

function hex_value(text):
    if text == "" or len(text) > 4:
        return -1
    end
    value = 0
    for ch in text.lower():
        d = HEX.find(ch)
        if d < 0:
            return -1
        end
        value = value * 16 + d
    end
    return value
end

# ---- vychozi brana --------------------------------------------------------------------------------------

function by_metric(routes):
    keyed = []
    for i in range(len(routes)):
        # stabilni razeni podle metriky (desetimistne cislo, pak poradi)
        keyed.append(String(10000000000 + routes[i]["metric"]) + "\t" + String(100000 + i))
    end
    out = []
    for k in sorted(keyed):
        out.append(routes[Int(k[k.find("\t") + 1:]) - 100000])
    end
    return out
end

# "ip -j route show default" (JSON) nebo "ip route show default" (text) -> [{gateway, dev, metric}] od nejnizsi
# metriky (ta se pouziva)
function parse_routes(text):
    routes = []
    text = text.strip()
    if text.startswith("["):
        data = None
        safe:
            data = json.decode(text)
        end
        if type(data) != "List":
            return []
        end
        for r in data:
            if type(r) == "Dictionary" and r.get("dst", "") == "default" and r.get("gateway", "") != "":
                metric = 0
                safe:
                    metric = Int(r.get("metric", 0))
                end
                routes.append({"gateway": String(r["gateway"]), "dev": String(r.get("dev", "")), "metric": metric})
            end
        end
    else:
        for line in text.split("\n"):
            w = words(line)
            if len(w) < 5 or w[0] != "default" or w[1] != "via" or w[3] != "dev":
                continue
            end
            metric = 0
            for i in range(5, len(w) - 1):
                if w[i] == "metric" and is_digits(w[i + 1]):
                    metric = Int(w[i + 1])
                    break
                end
            end
            routes.append({"gateway": w[2], "dev": w[4], "metric": metric})
        end
    end
    return by_metric(routes)
end

# ---- NetworkManager (nmcli -t) ----------------------------------------------------------------------------

# Radek "nmcli -t" na pole: ':' oddeluje, "\:" a "\\" jsou escapovane
function split_terse(line):
    fields = []
    current = ""
    escaped = False
    for ch in line:
        if escaped:
            current += ch
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ":":
            fields.append(current)
            current = ""
        else:
            current += ch
        end
    end
    fields.append(current)
    return fields
end

# "nmcli -t device show DEV" -> {connection, type, ip4, ip6, dns, hwaddr, gateway}
function parse_device_show(text):
    info = {"connection": "", "type": "", "ip4": [], "ip6": [], "dns": [], "hwaddr": "", "gateway": ""}
    for line in text.split("\n"):
        cut = line.find(":")
        if cut < 0:
            continue
        end
        key = line[:cut]
        value = line[cut + 1:].replace("\\:", ":").replace("\\\\", "\\").strip()
        if key.find("[") >= 0:
            key = key[:key.find("[")]
        end
        if value == "" or value == "--":
            continue
        end
        if key == "GENERAL.CONNECTION":
            info["connection"] = value
        elif key == "GENERAL.TYPE":
            info["type"] = value
        elif key == "GENERAL.HWADDR":
            info["hwaddr"] = value
        elif key == "IP4.ADDRESS":
            info["ip4"].append(value)
        elif key == "IP6.ADDRESS":
            info["ip6"].append(value)
        elif key == "IP4.DNS" or key == "IP6.DNS":
            info["dns"].append(value)
        elif key == "IP4.GATEWAY":
            info["gateway"] = value
        end
    end
    return info
end

# "nmcli -t -f ACTIVE,SSID device wifi list --rescan no" -> SSID aktivni site nebo ""
function parse_wifi_ssid(text):
    for line in text.split("\n"):
        f = split_terse(line)
        if len(f) >= 2 and f[0] == "yes":
            return ":".join(f[1:])
        end
    end
    return ""
end

function parse_resolv_conf(text):
    out = []
    for line in text.split("\n"):
        w = words(line)
        if len(w) > 1 and line.strip().startswith("nameserver"):
            out.append(w[1])
        end
    end
    return out
end

# ---- adresy IP ------------------------------------------------------------------------------------------

# "192.168.1.1" -> [192, 168, 1, 1], None kdyz neni platna (bez nul na zacatku, jako ipaddress v Pythonu)
function parse_ipv4(text):
    parts = text.split(".")
    if len(parts) != 4:
        return None
    end
    out = []
    for p in parts:
        if not is_digits(p) or len(p) > 3 or (len(p) > 1 and p[0] == "0"):
            return None
        end
        n = Int(p)
        if n > 255:
            return None
        end
        out.append(n)
    end
    return out
end

# "fe80::1" -> 8 skupin po 16 bitech, None kdyz neni platna; IPv4 na konci ("::ffff:192.168.0.1") jde
function parse_ipv6(text):
    if text.find(":") < 0:
        return None
    end
    tail = []
    # posledni pole muze byt IPv4
    cut = len(text) - 1
    while cut >= 0 and text[cut] != ":":
        cut -= 1
    end
    if text[cut + 1:].find(".") >= 0:
        v4 = parse_ipv4(text[cut + 1:])
        if v4 == None:
            return None
        end
        tail = [v4[0] * 256 + v4[1], v4[2] * 256 + v4[3]]
        text = text[:cut + 1]
        if text.endswith(":") and not text.endswith("::"):
            text = text[:len(text) - 1]
        end
    end
    halves = text.split("::")
    if len(halves) > 2:
        return None
    end
    groups = []
    for half in halves:
        items = []
        if half != "":
            for g in half.split(":"):
                v = hex_value(g)
                if v < 0:
                    return None
                end
                items.append(v)
            end
        end
        groups.append(items)
    end
    count = len(groups[0]) + len(tail)
    if len(groups) == 2:
        count += len(groups[1])
        if count > 7:
            return None
        end
        zeros = []
        for i in range(8 - count):
            zeros.append(0)
        end
        return groups[0] + zeros + groups[1] + tail
    end
    if count != 8:
        return None
    end
    return groups[0] + tail
end

# Je adresa v domaci siti (privatni IPv4, link-local, IPv6 ULA a link-local, nebo presne vychozi brana)?
function is_lan_ip(addr, gateway):
    plain = addr
    if plain.find("%") >= 0:
        plain = plain[:plain.find("%")]
    end
    v4 = parse_ipv4(plain)
    v6 = None
    if v4 == None:
        v6 = parse_ipv6(plain)
        if v6 == None:
            return False
        end
    end
    if gateway != "" and addr == gateway:
        return True
    end
    if v6 != None:
        if v6[:6] == [0, 0, 0, 0, 0, 65535]:
            v4 = [v6[6] // 256, v6[6] % 256, v6[7] // 256, v6[7] % 256]
        else:
            # fc00::/7, fe80::/10
            return (v6[0] & 65024) == 64512 or (v6[0] & 65472) == 65152
        end
    end
    return v4[0] == 10 or (v4[0] == 172 and v4[1] >= 16 and v4[1] <= 31) or (v4[0] == 192 and v4[1] == 168) or (v4[0] == 169 and v4[1] == 254)
end

function is_ip(host):
    plain = host
    if plain.find("%") >= 0:
        plain = plain[:plain.find("%")]
    end
    return parse_ipv4(plain) != None or parse_ipv6(plain) != None
end

# ---- adresy URL -----------------------------------------------------------------------------------------

function is_scheme(text):
    if text == "":
        return False
    end
    for i in range(len(text)):
        code = ord(text[i].lower())
        letter = code >= 97 and code <= 122
        if not (letter or (i > 0 and ((code >= 48 and code <= 57) or text[i] == "+" or text[i] == "-" or text[i] == "."))):
            return False
        end
    end
    return True
end

# {"scheme", "netloc", "user" (je jmeno/heslo), "host"} jako urllib.parse.urlsplit; None = neplatna adresa
function split_url(url):
    scheme = ""
    rest = url
    colon = url.find(":")
    if colon > 0 and is_scheme(url[:colon]):
        scheme = url[:colon].lower()
        rest = url[colon + 1:]
    end
    netloc = ""
    if rest.startswith("//"):
        rest = rest[2:]
        end_at = len(rest)
        for sep in ["/", "?", "#"]:
            i = rest.find(sep)
            if i >= 0 and i < end_at:
                end_at = i
            end
        end
        netloc = rest[:end_at]
    end
    hostport = netloc
    user = False
    at = -1
    for i in range(len(netloc)):
        if netloc[i] == "@":
            at = i
        end
    end
    if at >= 0:
        user = True
        hostport = netloc[at + 1:]
    end
    host = ""
    if hostport.startswith("["):
        close = hostport.find("]")
        if close < 0:
            return None
        end
        host = hostport[1:close]
    else:
        if hostport.find("]") >= 0:
            return None
        end
        host = hostport
        if host.find(":") >= 0:
            host = host[:host.find(":")]
        end
    end
    return {"scheme": scheme, "netloc": netloc, "user": user, "host": host.lower()}
end

function url_host(url):
    parts = split_url(url)
    if parts == None:
        return ""
    end
    return parts["host"]
end

# Co s navigaci v okne spravy routeru:
#   allow    - http(s) na adresu v domaci siti (nebo about:blank),
#   resolve  - http(s) na jmeno: povolit, jen kdyz se preklada vyhradne na adresy v domaci siti,
#   external - jinam (internet, localhost): otevrit v beznem prohlizeci,
#   block    - ostatni schemata (file:, data:, javascript: ...)
function lan_policy(url, gateway):
    if url == "about:blank" or url == "":
        return "allow"
    end
    p = split_url(url)
    if p == None:
        return "block"
    end
    if p["scheme"] != "http" and p["scheme"] != "https":
        if p["scheme"] == "mailto":
            return "external"
        end
        return "block"
    end
    host = p["host"]
    if host == "":
        return "block"
    end
    # http://router@zly.example - matouci adresa
    if p["user"]:
        return "block"
    end
    if is_ip(host):
        if is_lan_ip(host, gateway):
            return "allow"
        end
        return "external"
    end
    if host == "localhost" or host.endswith(".localhost"):
        return "external"
    end
    return "resolve"
end

# Adresy z "getent ahosts JMENO" (prvni sloupec, bez opakovani)
function parse_hosts(text):
    out = []
    for line in text.split("\n"):
        w = words(line)
        if len(w) > 0 and not (w[0] in out):
            out.append(w[0])
        end
    end
    return out
end

# Preklada se jmeno jen na adresy v domaci siti (fritz.box, routerlogin.net)?
function all_lan(addrs, gateway):
    if len(addrs) == 0:
        return False
    end
    for a in addrs:
        if not is_lan_ip(a, gateway):
            return False
        end
    end
    return True
end

# Vyjimku pro nedoveryhodny certifikat lze povolit jen pro https na presnou adresu vychozi brany
function tls_exception_allowed(url, gateway):
    p = split_url(url)
    if p == None or gateway == "":
        return False
    end
    return p["scheme"] == "https" and p["host"] == gateway.lower()
end

# Adresa webove spravy routeru (port jen pro testy: LUXOS_ROUTER_PORT)
function router_url(gateway, https, port):
    if gateway == "":
        return ""
    end
    host = gateway
    if gateway.find(":") >= 0:
        host = "[" + gateway + "]"
    end
    url = ("https" if https else "http") + "://" + host
    if port != "":
        url += ":" + port
    end
    return url + "/"
end

# ---- zarizeni v siti (ip neigh) ---------------------------------------------------------------------------

function hex2(n):
    return HEX[n // 16] + HEX[n % 16]
end

# Klic razeni: IPv4 pred IPv6, pak podle cisla adresy
function ip_key(ip):
    plain = ip
    if plain.find("%") >= 0:
        plain = plain[:plain.find("%")]
    end
    v4 = parse_ipv4(plain)
    if v4 != None:
        return "4" + "".join([hex2(n) for n in v4])
    end
    v6 = parse_ipv6(plain)
    if v6 != None:
        return "6" + "".join([hex2(g // 256) + hex2(g % 256) for g in v6])
    end
    return "9"
end

function is_mac(text):
    if len(text) != 17:
        return False
    end
    for ch in text.lower():
        if ch != ":" and HEX.find(ch) < 0:
            return False
        end
    end
    return True
end

function is_upper_word(text):
    if text == "":
        return False
    end
    for ch in text:
        if ord(ch) < 65 or ord(ch) > 90:
            return False
        end
    end
    return True
end

# "ip -j neigh" (JSON) nebo text -> [{ip, mac, dev, state}] bez neuplnych zaznamu, serazene podle adresy
function parse_neigh(text):
    found = []
    text = text.strip()
    if text.startswith("["):
        data = None
        safe:
            data = json.decode(text)
        end
        if type(data) != "List":
            data = []
        end
        for n in data:
            if type(n) != "Dictionary" or n.get("lladdr", "") == "" or n.get("lladdr") == None:
                continue
            end
            state = n.get("state", [])
            if type(state) == "List":
                state = state[0] if len(state) > 0 else ""
            end
            dst = n.get("dst", "")
            found.append({"ip": String(dst if dst != None else ""), "mac": String(n["lladdr"]).lower(),
                "dev": String(n.get("dev", "")), "state": String(state if state != None else "").upper()})
        end
    else:
        for line in text.split("\n"):
            w = words(line)
            if len(w) >= 6 and w[1] == "dev" and w[3] == "lladdr" and is_mac(w[4]) and is_upper_word(w[len(w) - 1]):
                found.append({"ip": w[0], "mac": w[4].lower(), "dev": w[2], "state": w[len(w) - 1]})
            end
        end
    end
    seen = []
    kept = []
    keyed = []
    for n in found:
        pair = n["ip"] + " " + n["mac"]
        if n["state"] == "FAILED" or n["state"] == "INCOMPLETE" or n["ip"] == "" or pair in seen:
            continue
        end
        seen.append(pair)
        keyed.append(ip_key(n["ip"]) + "\t" + String(100000 + len(kept)))
        kept.append(n)
    end
    return [kept[Int(k[k.find("\t") + 1:]) - 100000] for k in sorted(keyed)]
end

# Lokalne spravovana (nahodna, soukroma) adresa MAC - telefony, novejsi notebooky
function is_random_mac(mac):
    first = mac.split(":")[0]
    if len(first) == 0 or len(first) > 2:
        return False
    end
    v = hex_value(first)
    return v >= 0 and (v & 2) != 0
end

function oui_prefix(mac):
    return mac.replace("-", ":").upper()[:8].replace(":", "-")
end

# {mac: vyrobce} z radku "00-1A-2B   (hex)\t\tVyrobce" souboru OUI (hwdata); nahodne MAC se nehledaji
function oui_parse(text, macs):
    result = {}
    vendors = {}
    for line in text.split("\n"):
        cut = line.find("(hex)")
        if cut < 0:
            continue
        end
        prefix = line[:8].upper()
        if not (prefix in vendors):
            vendors[prefix] = line[cut + 5:].strip()
        end
    end
    for mac in macs:
        if not is_random_mac(mac) and oui_prefix(mac) in vendors:
            result[mac] = vendors[oui_prefix(mac)]
        end
    end
    return result
end

# Vzory pro grep -F (jeden pruchod souborem OUI bez nacteni do pameti)
function oui_patterns(macs):
    out = []
    for mac in macs:
        p = oui_prefix(mac) + "   (hex)"
        if not is_random_mac(mac) and not (p in out):
            out.append(p)
        end
    end
    return out
end

# Adresy k probuzeni (ping) v siti rozhrani; vetsi sit nez 256 adres jen /24 kolem vlastni adresy
function scan_targets(cidr):
    parts = cidr.split("/")
    if len(parts) > 2:
        return []
    end
    ip = parse_ipv4(parts[0])
    if ip == None:
        return []
    end
    prefix = 32
    if len(parts) == 2:
        if not is_digits(parts[1]) or Int(parts[1]) > 32:
            return []
        end
        prefix = Int(parts[1])
    end
    if prefix < 24:
        prefix = 24
    end
    own = ((ip[0] * 256 + ip[1]) * 256 + ip[2]) * 256 + ip[3]
    size = 1 << (32 - prefix)
    base = own - own % size
    out = []
    first = base + 1
    last = base + size - 2
    if size <= 2:
        # /31 a /32: vsechny adresy jsou hosty (ipaddress.hosts)
        first = base
        last = base + size - 1
    end
    for a in range(first, last + 1):
        if a != own:
            out.append(String(a >> 24) + "." + String((a >> 16) & 255) + "." + String((a >> 8) & 255) + "." + String(a & 255))
        end
    end
    return out
end

# ---- nastroje ---------------------------------------------------------------------------------------------

function number_before(text, at):
    start = at
    while start > 0 and ord(text[start - 1]) >= 48 and ord(text[start - 1]) <= 57:
        start -= 1
    end
    if start == at:
        return -1
    end
    return Int(text[start:at])
end

# Vystup ping (LC_ALL=C) -> {sent, received, avg v ms nebo None}
function parse_ping(text):
    res = {"sent": 0, "received": 0, "avg": None}
    at = text.find(" packets transmitted, ")
    if at >= 0:
        sent = number_before(text, at)
        rest = text[at + 22:]
        stop = 0
        while stop < len(rest) and ord(rest[stop]) >= 48 and ord(rest[stop]) <= 57:
            stop += 1
        end
        if sent >= 0 and stop > 0 and (rest[stop:].startswith(" received") or rest[stop:].startswith(" packets received")):
            res["sent"] = sent
            res["received"] = Int(rest[:stop])
        end
    end
    eq = text.find("= ")
    while eq >= 0:
        tail = text[eq + 2:]
        nl = tail.find("\n")
        if nl >= 0:
            tail = tail[:nl]
        end
        if tail.endswith(" ms"):
            nums = tail[:len(tail) - 3].split("/")
            if len(nums) == 4:
                value = None
                safe:
                    value = Float(nums[1])
                end
                if value != None:
                    res["avg"] = value
                    break
                end
            end
        end
        nxt = text[eq + 2:].find("= ")
        eq = -1 if nxt < 0 else eq + 2 + nxt
    end
    return res
end

# "%.1f" pro nezaporne cislo
function fixed1(value):
    n = Int(math.round(value * 10.0))
    return String(n // 10) + "." + String(n % 10)
end
