"""LuxOS - Sprava site (luxos-router): vychozi brana, udaje o siti, pravidla pro webovou
spravu routeru, zarizeni v siti a rychle nastroje (ping, DNS, rychlost).

Bez GTK - testuje se samostatne (tests/test_luxos_netadmin.py). Prikazy ip/nmcli/ping
jdou prepsat promennymi LUXOS_IP, LUXOS_NMCLI, LUXOS_PING (testy).
"""
import ipaddress
import json
import os
import re
import socket
import subprocess
import time
import urllib.parse
import urllib.request

OUI_FILES = ("/usr/share/hwdata/oui.txt", "/usr/share/ieee-data/oui.txt", "/usr/share/misc/oui.txt")
INTERNET_HOST = "1.1.1.1"
DNS_TEST_NAME = "example.com"
PUBLIC_IP_URLS = ("https://api.ipify.org", "https://icanhazip.com")
SPEED_URL = "https://speed.cloudflare.com/__down?bytes=%d"
SPEED_BYTES = 10_000_000

# Domaci sit: privatni IPv4 (RFC 1918), link-local, IPv6 ULA a link-local
LAN_NETS = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "fc00::/7", "fe80::/10"))


def _cmd(env, default):
    return os.environ.get(env) or default


def run(argv, timeout=10):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


# ---- vychozi brana ---------------------------------------------------------------
ROUTE_RE = re.compile(r"^default\s+via\s+(\S+)\s+dev\s+(\S+)(.*)$")


def parse_routes(text):
    """Vystup "ip -j route show default" (JSON) nebo "ip route show default" (text) ->
    [{"gateway", "dev", "metric"}] serazene od nejnizsi metriky (ta se pouziva)."""
    routes = []
    text = (text or "").strip()
    if text.startswith("["):
        try:
            data = json.loads(text)
        except ValueError:
            data = []
        for r in data:
            if isinstance(r, dict) and r.get("dst") == "default" and r.get("gateway"):
                routes.append({"gateway": r["gateway"], "dev": r.get("dev", ""), "metric": int(r.get("metric", 0))})
    else:
        for line in text.splitlines():
            m = ROUTE_RE.match(line.strip())
            if not m:
                continue
            metric = re.search(r"\bmetric\s+(\d+)", m.group(3))
            routes.append({"gateway": m.group(1), "dev": m.group(2), "metric": int(metric.group(1)) if metric else 0})
    routes.sort(key=lambda r: r["metric"])
    return routes


def default_gateway():
    """Vychozi brana IPv4 {"gateway", "dev", "metric"} nebo None."""
    ip = _cmd("LUXOS_IP", "ip")
    routes = parse_routes(run([ip, "-j", "-4", "route", "show", "default"])) or \
        parse_routes(run([ip, "-4", "route", "show", "default"]))
    return routes[0] if routes else None


def default_gateway6():
    routes = parse_routes(run([_cmd("LUXOS_IP", "ip"), "-j", "-6", "route", "show", "default"]))
    return routes[0] if routes else None


# ---- NetworkManager (nmcli -t) ------------------------------------------------------
def split_terse(line):
    """Radek "nmcli -t" na pole: ':' oddeluje, "\\:" a "\\\\" jsou escapovane."""
    fields, cur, esc = [], [], False
    for ch in line:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            fields.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    fields.append("".join(cur))
    return fields


def parse_device_show(text):
    """"nmcli -t device show DEV" -> {"connection", "type", "ip4": [..], "dns": [..], "ip6": [..], "hwaddr"}."""
    info = {"connection": "", "type": "", "ip4": [], "ip6": [], "dns": [], "hwaddr": "", "gateway": ""}
    for line in (text or "").splitlines():
        key, sep, val = line.partition(":")
        if not sep:
            continue
        val = val.replace("\\:", ":").replace("\\\\", "\\").strip()
        key = key.split("[")[0]
        if not val or val == "--":
            continue
        if key == "GENERAL.CONNECTION":
            info["connection"] = val
        elif key == "GENERAL.TYPE":
            info["type"] = val
        elif key == "GENERAL.HWADDR":
            info["hwaddr"] = val
        elif key == "IP4.ADDRESS":
            info["ip4"].append(val)
        elif key == "IP6.ADDRESS":
            info["ip6"].append(val)
        elif key in ("IP4.DNS", "IP6.DNS"):
            info["dns"].append(val)
        elif key == "IP4.GATEWAY":
            info["gateway"] = val
    return info


def parse_wifi_ssid(text):
    """"nmcli -t -f ACTIVE,SSID device wifi list --rescan no" -> SSID aktivni site nebo ""."""
    for line in (text or "").splitlines():
        f = split_terse(line)
        if len(f) >= 2 and f[0] == "yes":
            return ":".join(f[1:])
    return ""


def parse_resolv_conf(text):
    return [line.split()[1] for line in (text or "").splitlines()
            if line.strip().startswith("nameserver") and len(line.split()) > 1]


def network_info():
    """Udaje pro prehled: brana, rozhrani, pripojeni, SSID, adresy a DNS."""
    gw = default_gateway()
    info = {"gateway": gw["gateway"] if gw else "", "dev": gw["dev"] if gw else "",
            "connection": "", "type": "", "ssid": "", "ip4": [], "ip6": [], "dns": [], "hwaddr": "",
            "gateway6": ""}
    nmcli = _cmd("LUXOS_NMCLI", "nmcli")
    if info["dev"]:
        dev = parse_device_show(run([nmcli, "-t", "device", "show", info["dev"]]))
        for k in ("connection", "type", "ip4", "ip6", "dns", "hwaddr"):
            info[k] = dev[k]
        if dev["type"] == "wifi":
            info["ssid"] = parse_wifi_ssid(run([nmcli, "-t", "-f", "ACTIVE,SSID", "device", "wifi", "list",
                                                "ifname", info["dev"], "--rescan", "no"])) or dev["connection"]
    if not info["dns"]:
        try:
            with open("/etc/resolv.conf", encoding="utf-8") as f:
                info["dns"] = parse_resolv_conf(f.read())
        except OSError:
            pass
    gw6 = default_gateway6()
    if gw6:
        info["gateway6"] = gw6["gateway"]
    return info


# ---- pravidla pro webovou spravu ------------------------------------------------------
def is_lan_ip(addr, gateway=""):
    """Je adresa v domaci siti (privatni rozsahy, nebo presne vychozi brana)?"""
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    if gateway and addr == gateway:
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in n for n in LAN_NETS)


def url_host(url):
    try:
        p = urllib.parse.urlsplit(url)
        return (p.hostname or "").lower()
    except ValueError:
        return ""


def lan_policy(url, gateway=""):
    """Co s navigaci v okne spravy routeru:

    "allow"    - http(s) na adresu v domaci siti (nebo about:blank),
    "resolve"  - http(s) na jmeno: povolit, jen kdyz se preklada vyhradne na adresy v domaci siti,
    "external" - jinam (internet, localhost): otevrit v beznem prohlizeci,
    "block"    - ostatni schemata (file:, data:, javascript: ...)."""
    if url in ("about:blank", ""):
        return "allow"
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return "block"
    scheme = p.scheme.lower()
    if scheme not in ("http", "https"):
        return "external" if scheme == "mailto" else "block"
    host = (p.hostname or "").lower()
    if not host:
        return "block"
    if p.username or p.password:
        return "block"          # http://router@zly.example - matouci adresa
    try:
        ipaddress.ip_address(host.split("%")[0])
        return "allow" if is_lan_ip(host, gateway) else "external"
    except ValueError:
        pass
    if host == "localhost" or host.endswith(".localhost"):
        return "external"
    return "resolve"


def resolves_to_lan(host, gateway="", resolver=None):
    """Preklada se jmeno jen na adresy v domaci siti (napr. fritz.box, routerlogin.net)?"""
    resolver = resolver or socket.getaddrinfo
    try:
        addrs = {a[4][0] for a in resolver(host, None)}
    except (OSError, UnicodeError):
        return False
    return bool(addrs) and all(is_lan_ip(a, gateway) for a in addrs)


def tls_exception_allowed(url, gateway):
    """Vyjimku pro nedoveryhodny certifikat (router s vlastnim certifikatem) lze povolit
    jen pro https na presnou adresu vychozi brany."""
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return bool(gateway) and p.scheme == "https" and (p.hostname or "") == gateway.lower()


def router_url(gateway, https=False, port=None):
    """Adresa webove spravy routeru (port jen pro testy: LUXOS_ROUTER_PORT)."""
    if not gateway:
        return ""
    host = f"[{gateway}]" if ":" in gateway else gateway
    port = port or os.environ.get("LUXOS_ROUTER_PORT")
    return f"{'https' if https else 'http'}://{host}{':%s' % port if port else ''}/"


# ---- zarizeni v siti (ip neigh) --------------------------------------------------------
def parse_neigh(text):
    """"ip -j neigh" (JSON) nebo text -> [{"ip", "mac", "dev", "state"}] bez neuplnych zaznamu."""
    out = []
    text = (text or "").strip()
    if text.startswith("["):
        try:
            data = json.loads(text)
        except ValueError:
            data = []
        for n in data:
            if not isinstance(n, dict) or not n.get("lladdr"):
                continue
            state = n.get("state") or []
            out.append({"ip": n.get("dst", ""), "mac": n["lladdr"].lower(), "dev": n.get("dev", ""),
                        "state": (state[0] if isinstance(state, list) and state else str(state)).upper()})
    else:
        for line in text.splitlines():
            m = re.match(r"^(\S+)\s+dev\s+(\S+)\s+lladdr\s+([0-9a-fA-F:]{17})(?:\s+\S+)*?\s+([A-Z]+)\s*$", line.strip())
            if m:
                out.append({"ip": m.group(1), "mac": m.group(3).lower(), "dev": m.group(2), "state": m.group(4)})
    seen, res = set(), []
    for n in out:
        if n["state"] in ("FAILED", "INCOMPLETE") or not n["ip"] or (n["ip"], n["mac"]) in seen:
            continue
        seen.add((n["ip"], n["mac"]))
        res.append(n)

    def key(n):
        try:
            ip = ipaddress.ip_address(n["ip"].split("%")[0])
            return (ip.version, int(ip))
        except ValueError:
            return (9, 0)
    res.sort(key=key)
    return res


def neighbours(dev=None):
    argv = [_cmd("LUXOS_IP", "ip"), "-j", "neigh", "show"]
    if dev:
        argv += ["dev", dev]
    return parse_neigh(run(argv))


def is_random_mac(mac):
    """Lokalne spravovana (nahodna, soukroma) adresa MAC - telefony, novejsi notebooky."""
    try:
        return bool(int(mac.split(":")[0], 16) & 0x02)
    except (ValueError, IndexError):
        return False


def oui_prefix(mac):
    return mac.replace("-", ":").upper()[:8].replace(":", "-")


def oui_lookup(macs, paths=OUI_FILES):
    """{mac: vyrobce} z mistniho souboru OUI (hwdata); jeden pruchod souborem, bez site."""
    want = {}
    for mac in macs:
        if not is_random_mac(mac):
            want.setdefault(oui_prefix(mac), []).append(mac)
    result = {}
    if not want:
        return result
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if "(hex)" not in line:
                        continue
                    pre = line[:8].upper()
                    if pre in want:
                        vendor = line.split("(hex)", 1)[1].strip()
                        for mac in want.pop(pre):
                            result[mac] = vendor
                        if not want:
                            break
            break
        except OSError:
            continue
    return result


def scan_targets(cidr, limit=256):
    """Adresy k probuzeni (ping) v siti rozhrani; vetsi sit jen /24 kolem vlastni adresy."""
    try:
        iface = ipaddress.ip_interface(cidr)
    except ValueError:
        return []
    if iface.version != 4:
        return []
    net = iface.network
    if net.num_addresses > limit:
        net = ipaddress.ip_network(f"{iface.ip}/24", strict=False)
    return [str(h) for h in net.hosts() if h != iface.ip]


# ---- nastroje ----------------------------------------------------------------------
PING_LOSS = re.compile(r"(\d+) packets transmitted, (\d+) (?:packets )?received")
PING_RTT = re.compile(r"= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms")


def parse_ping(text):
    """Vystup ping -> {"sent", "received", "avg"} (avg v ms nebo None)."""
    res = {"sent": 0, "received": 0, "avg": None}
    m = PING_LOSS.search(text or "")
    if m:
        res["sent"], res["received"] = int(m.group(1)), int(m.group(2))
    m = PING_RTT.search(text or "")
    if m:
        res["avg"] = float(m.group(2))
    return res


def ping(host, count=4, timeout=2):
    argv = [_cmd("LUXOS_PING", "ping"), "-n", "-c", str(count), "-W", str(timeout), host]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=count * (timeout + 1) + 5)
        return parse_ping(r.stdout)
    except (OSError, subprocess.TimeoutExpired):
        return parse_ping("")


def dns_test(name=DNS_TEST_NAME, resolver=None):
    """(uspech, doba v ms, adresy) prekladu jmena systemovym resolverem."""
    resolver = resolver or socket.getaddrinfo
    t = time.monotonic()
    try:
        addrs = sorted({a[4][0] for a in resolver(name, 443)})
    except (OSError, UnicodeError):
        return False, (time.monotonic() - t) * 1000, []
    return True, (time.monotonic() - t) * 1000, addrs


def public_ip(urls=PUBLIC_IP_URLS, timeout=8):
    """Verejna adresa (jen na vyzadani uzivatele)."""
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LuxOS"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                text = r.read(100).decode("ascii", "replace").strip()
            ipaddress.ip_address(text)
            return text
        except (OSError, ValueError):
            continue
    return ""


def speed_test(nbytes=SPEED_BYTES, url=SPEED_URL, timeout=30):
    """Odhad rychlosti stahovani v Mbit/s (stahne nbytes), nebo None."""
    try:
        req = urllib.request.Request(url % nbytes, headers={"User-Agent": "LuxOS"})
        t = time.monotonic()
        got = 0
        with urllib.request.urlopen(req, timeout=timeout) as r:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                got += len(chunk)
                if time.monotonic() - t > timeout:
                    break
        dt = time.monotonic() - t
    except (OSError, ValueError):
        return None
    if got < 100_000 or dt <= 0:
        return None
    return got * 8 / dt / 1e6
