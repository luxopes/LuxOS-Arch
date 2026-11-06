# LuxOS firewall - vychozi firewall LuxOS ve vlastni tabulce nftables `table inet luxos`.
#
# Nikdy nesaha na jine tabulky (Tailscale ts-*, podman/netavark, libvirt, docker, ufw): nahrava a maze
# jen svou tabulku, vzdy jednou atomickou transakci `nft -f -` (pri chybe zustane puvodni stav).
# Prichozi nova spojeni zahodi krome: navazanych, loopbacku, nezbytneho ICMP/ICMPv6 (sousede, router,
# PMTU), DHCP klienta, mDNS, odpovedi pri hledani zarizeni (SSDP, WS-Discovery, BJNP ...), aplikaci
# LuxOS jen z mistni site (LuxDrop, Steam, KDE Connect, Syncthing - kdyz jsou nainstalovane),
# SSH odkudkoli jen se zapnutym sshd, sdileni tiskaren z mistni site jen se zapnutym sdilenim v CUPS,
# port Tailscale (WireGuard) a vyjimek uzivatele. Forward neresi (kontejnery, VM, exit node Tailscale).
# Zahozena nova spojeni na porty, kde posloucha mistni program, zapise jadro (s omezenim rychlosti)
# a `luxos-firewall watch` z nich udela zadosti pro luxos-hub (upozorneni "Povolit / Nechat blokovane").
#
#   luxos-firewall status [--json]                    stav, automaticka pravidla, vyjimky, zablokovane
#   luxos-firewall on | off                           zapnout / vypnout (trvale)
#   luxos-firewall allow PORT[/tcp|/udp] [--from lan|any] [--app NAZEV]   vyjimka (vychozi: jen mistni sit)
#   luxos-firewall deny PORT[/tcp|/udp]               zrusit vyjimku
#   luxos-firewall tailscale on | off                 zarizeni v Tailscale jako mistni sit (LuxDrop, vyjimky)
#   luxos-firewall load | refresh | unload            pro luxos-firewall.service a spousteni po zmenach
#   luxos-firewall watch                              pro luxos-firewall-watch.service (cte /dev/kmsg)
#   luxos-firewall render                             vypise pravidla nftables (bez nahrani)
#
# Nastaveni: /etc/luxos/firewall.json (pise jen tento program a lux system), stav pro uzivatele:
# /run/luxos-firewall/state.json a requests.json (cteni bez prav roota).
load env, json, time
load luxos_fw_sys as sys

VERSION = "1.0.0"
ROOT = env.get("LUXOS_FIREWALL_ROOT", "")
CONFIG = ROOT + "/etc/luxos/firewall.json"
RUN_DIR = ROOT + "/run/luxos-firewall"
STATE = RUN_DIR + "/state.json"
REQUESTS = RUN_DIR + "/requests.json"
KMSG = ROOT + "/dev/kmsg"
SELF = "/usr/bin/luxos-firewall"
TABLE = "luxos"
LOG_PREFIX = "luxos-firewall: "
# Rozhrani virtualnich siti tohoto pocitace (kontejnery, VM, Waydroid): duveryhodna, sama si resi pravidla
TRUSTED_IFACES = ["virbr*", "podman*", "cni-podman*", "docker0", "br-*", "lxcbr*", "lxdbr*", "incusbr*",
                  "waydroid*", "vboxnet*", "vmnet*"]
# Rozhrani, jejichz pripojene site nejsou "mistni sit" (VPN, Tailscale)
NOT_LAN_IFACES = ["lo", "tailscale", "wg", "tun", "tap", "ppp", "zt"]
LAN4 = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16"]
LAN6 = ["fc00::/7", "fe80::/10"]
# Odpovedi na hledani zarizeni (z dobre znameho portu zarizeni na docasny port aplikace):
# NetBIOS, SNMP (CUPS), SLP, SSDP, ENPC (Epson), WS-Discovery, mDNS, LLMNR, BJNP (Canon)
DISCOVERY_SPORTS = "137, 161, 427, 1900, 3289, 3702, 5353, 5355, 8610-8612"
EPHEMERAL_FIRST = 32768
# Nejvys jedna zadost za 10 minut pro stejny port, nejvys 30 zadosti v souboru
REQUEST_EVERY = 600
REQUEST_KEEP = 30

# ---- pomocne ----------------------------------------------------------------------------------------------

function tool(name, default):
    value = env.get(name, "")
    if value == None or value == "":
        return default
    end
    return value
end

NFT = tool("LUXOS_FIREWALL_NFT", "/usr/bin/nft")
SYSTEMCTL = tool("LUXOS_FIREWALL_SYSTEMCTL", "/usr/bin/systemctl")
SS = tool("LUXOS_FIREWALL_SS", "/usr/bin/ss")

i18n_table = None

function lang():
    for name in ["LC_ALL", "LC_MESSAGES", "LANG"]:
        value = env.get(name, "")
        if value != None and value != "":
            for sep in ["_", ".", "@"]:
                cut = value.find(sep)
                if cut >= 0:
                    value = value[0:cut]
                end
            end
            return value
        end
    end
    return "en"
end

# Preklad z /usr/share/luxos/i18n/<jazyk>.tsv (radek "anglicky<TAB>preklad"), jako luxos_i18n
function T(text):
    global i18n_table
    if i18n_table == None:
        i18n_table = ""
        code = lang()
        base = tool("LUXOS_I18N_DIR", "/usr/share/luxos/i18n")
        if code != "en" and code != "C" and code != "POSIX" and exists(base + "/" + code + ".tsv"):
            safe:
                i18n_table = "\n" + readfile(base + "/" + code + ".tsv")
            end
        end
    end
    if i18n_table == "":
        return text
    end
    needle = "\n" + text + "\t"
    start = i18n_table.find(needle)
    if start < 0:
        return text
    end
    rest = i18n_table[start + len(needle):]
    stop = rest.find("\n")
    if stop >= 0:
        rest = rest[0:stop]
    end
    rest = rest.strip()
    if rest == "":
        return text
    end
    return rest
end

# T() s dosazenim %s v poradi
function TF(text, values):
    out = ""
    template = T(text)
    used = 0
    index = 0
    while index < len(template):
        ch = template[index]
        if ch == "%" and index + 1 < len(template) and template[index + 1] == "s":
            if used < len(values):
                out = out + String(values[used])
            end
            used += 1
            index += 2
            continue
        end
        out = out + ch
        index += 1
    end
    return out
end

function fail(message, code):
    call eprint("luxos-firewall: " + message)
    call exit(code)
end

function is_digits(text):
    if len(text) == 0:
        return False
    end
    for ch in text:
        if "0123456789".find(ch) < 0:
            return False
        end
    end
    return True
end

function to_port(text):
    if not is_digits(text) or len(text) > 5:
        return None
    end
    value = Int(text)
    if value < 1 or value > 65535:
        return None
    end
    return value
end

# Slova radku (mezery i tabulatory, bez prazdnych)
function fields(line):
    out = []
    for part in line.replace("\t", " ").split(" "):
        if part != "":
            out.append(part)
        end
    end
    return out
end

function read_text(path):
    text = ""
    safe:
        text = readfile(path)
    end
    if text == None:
        return ""
    end
    return text
end

function list_names(path):
    names = []
    safe:
        names = sorted(listdir(path))
    end
    return names
end

function now():
    return Int(time.time())
end

# Atomicky zapis souboru s pravy 0644
function write_file(path, text):
    tmp = path + ".tmp"
    call writefile(tmp, text)
    call sys.chmod(tmp, 420)
    if not sys.rename(tmp, path):
        Error(OSError: "cannot write " + path)
    end
    return None
end

# PORT, PORT/tcp, PORT-PORT/udp, PORT:PORT -> {"port": "8000-8010", "proto": "tcp|udp|both"}; None = chyba
function parse_spec(spec):
    s = spec.strip().lower()
    proto = "both"
    cut = s.find("/")
    if cut >= 0:
        proto = s[cut + 1:]
        s = s[0:cut]
        if proto != "tcp" and proto != "udp":
            return None
        end
    end
    parts = s.replace(":", "-").split("-")
    if len(parts) > 2:
        return None
    end
    low = to_port(parts[0])
    if low == None:
        return None
    end
    if len(parts) == 2:
        high = to_port(parts[1])
        if high == None or high <= low:
            return None
        end
        return {"port": String(low) + "-" + String(high), "proto": proto}
    end
    return {"port": String(low), "proto": proto}
end

# Nazev aplikace pro upozorneni a seznam vyjimek: jen [A-Za-z0-9._+-], nejvys 32 znaku
function clean_app(name):
    out = ""
    for ch in String(name):
        if "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._+-".find(ch) >= 0:
            out = out + ch
        elif len(out) > 0 and not out.endswith("-"):
            out = out + "-"
        end
    end
    while out.endswith("-"):
        out = out[0:len(out) - 1]
    end
    if len(out) > 32:
        out = out[0:32]
    end
    return out
end

# ---- nastaveni --------------------------------------------------------------------------------------------

function default_config():
    return {"enable": True, "trust_tailscale": False, "allow": []}
end

config_error = ""

function load_config():
    global config_error
    cfg = default_config()
    config_error = ""
    if not exists(CONFIG):
        return cfg
    end
    raw = None
    try:
        raw = json.decode(read_text(CONFIG))
    else:
        config_error = TF("%s is damaged; using the default settings", [CONFIG])
        return cfg
    end
    if type(raw) != "Dictionary":
        config_error = TF("%s is damaged; using the default settings", [CONFIG])
        return cfg
    end
    if type(raw.get("enable")) == "Bool":
        cfg["enable"] = raw["enable"]
    end
    if type(raw.get("trust_tailscale")) == "Bool":
        cfg["trust_tailscale"] = raw["trust_tailscale"]
    end
    allow = raw.get("allow", [])
    if type(allow) == "List":
        for item in allow:
            if type(item) != "Dictionary":
                continue
            end
            spec = parse_spec(String(item.get("port", "")) + "/" + String(item.get("proto", "tcp")))
            if spec == None or spec["proto"] == "both":
                continue
            end
            source = item.get("from", "lan")
            if source != "any":
                source = "lan"
            end
            call add_exception(cfg, spec["port"], spec["proto"], source, clean_app(item.get("app", "")))
        end
    end
    return cfg
end

function save_config(cfg):
    call sys.mkdir(ROOT + "/etc", 493)
    call sys.mkdir(ROOT + "/etc/luxos", 493)
    call write_file(CONFIG, json.pretty(cfg) + "\n")
    return None
end

# Vyjimka port/proto (jedna polozka na port a protokol; nova nahradi starou)
function add_exception(cfg, port, proto, source, app):
    kept = []
    for item in cfg["allow"]:
        if not (item["port"] == port and item["proto"] == proto):
            kept.append(item)
        end
    end
    entry = {"port": port, "proto": proto, "from": source}
    if app != "":
        entry["app"] = app
    end
    kept.append(entry)
    cfg["allow"] = kept
    return None
end

# ---- automaticka pravidla podle nainstalovanych aplikaci a zapnutych sluzeb ------------------------------

function flatpak_installed(app_id):
    if exists(ROOT + "/var/lib/flatpak/app/" + app_id):
        return True
    end
    for user in list_names(ROOT + "/home"):
        if exists(ROOT + "/home/" + user + "/.local/share/flatpak/app/" + app_id):
            return True
        end
    end
    return False
end

function any_exists(paths):
    for path in paths:
        if exists(ROOT + path):
            return True
        end
    end
    return False
end

function rule(name, port, proto, source):
    return {"name": name, "port": port, "proto": proto, "from": source}
end

# Porty LuxDrop z nastaveni uzivatelu (~/.config/luxdrop/settings.json: port, localsend_port)
function luxdrop_user_ports():
    tcp = []
    udp = []
    for user in list_names(ROOT + "/home"):
        path = ROOT + "/home/" + user + "/.config/luxdrop/settings.json"
        if not exists(path):
            continue
        end
        data = None
        safe:
            data = json.decode(read_text(path))
        end
        if type(data) != "Dictionary":
            continue
        end
        for key in ["port", "localsend_port"]:
            value = data.get(key)
            if type(value) == "Int" and value >= 1 and value <= 65535:
                if not (String(value) in tcp):
                    tcp.append(String(value))
                end
                if key == "localsend_port" and not (String(value) in udp):
                    udp.append(String(value))
                end
            end
        end
    end
    return [tcp, udp]
end

function systemctl_any(verb, units, wanted):
    if not exists(SYSTEMCTL):
        return False
    end
    out = ""
    args = [verb]
    args.extend(units)
    safe:
        out = capture(SYSTEMCTL, args)
    end
    if out == None:
        return False
    end
    for line in out.split("\n"):
        if line.strip() == wanted:
            return True
        end
    end
    return False
end

function sshd_on():
    if not exists(ROOT + "/usr/bin/sshd"):
        return False
    end
    units = ["sshd.service", "sshd.socket"]
    return systemctl_any("is-enabled", units, "enabled") or systemctl_any("is-active", units, "active")
end

function sshd_ports():
    ports = []
    files = [ROOT + "/etc/ssh/sshd_config"]
    for name in list_names(ROOT + "/etc/ssh/sshd_config.d"):
        if name.endswith(".conf"):
            files.append(ROOT + "/etc/ssh/sshd_config.d/" + name)
        end
    end
    for path in files:
        for line in read_text(path).split("\n"):
            words = fields(line.strip())
            if len(words) >= 2 and words[0].lower() == "port":
                port = to_port(words[1])
                if port != None and not (String(port) in ports):
                    ports.append(String(port))
                end
            end
        end
    end
    if len(ports) == 0:
        ports.append("22")
    end
    return ports
end

# CUPS posloucha na siti (Port 631 / Listen *:631 - napr. cupsctl --share-printers)
function cups_shared():
    for line in read_text(ROOT + "/etc/cups/cupsd.conf").split("\n"):
        words = fields(line.strip())
        if len(words) < 2:
            continue
        end
        key = words[0].lower()
        if key == "port":
            return True
        end
        if key == "listen":
            where = words[1]
            if where.find("localhost") < 0 and not where.startswith("/") and not where.startswith("127.") and not where.startswith("[::1]"):
                return True
            end
        end
    end
    return False
end

function tailscale_port():
    if not exists(ROOT + "/usr/bin/tailscaled"):
        return None
    end
    port = "41641"
    for line in read_text(ROOT + "/etc/default/tailscaled").split("\n"):
        s = line.strip()
        if s.startswith("PORT="):
            value = s[5:].replace("\"", "").replace("'", "").strip()
            if value == "0":
                return None
            end
            if to_port(value) != None:
                port = value
            end
        end
    end
    return port
end

function detect():
    rules = []
    if exists(ROOT + "/usr/bin/luxdrop"):
        tcp = ["47923-47924", "53317"]
        udp = ["53317"]
        custom = luxdrop_user_ports()
        for p in custom[0]:
            if p != "47923" and p != "53317" and not (p in tcp):
                tcp.append(p)
            end
        end
        for p in custom[1]:
            if p != "53317" and not (p in udp):
                udp.append(p)
            end
        end
        for p in tcp:
            rules.append(rule("LuxDrop", p, "tcp", "lan"))
        end
        for p in udp:
            rules.append(rule("LuxDrop", p, "udp", "lan"))
        end
    end
    if any_exists(["/usr/bin/steam", "/usr/lib/steam"]) or flatpak_installed("com.valvesoftware.Steam"):
        rules.append(rule("Steam", "27036-27037", "tcp", "lan"))
        rules.append(rule("Steam", "27031-27036", "udp", "lan"))
    end
    if any_exists(["/usr/bin/kdeconnectd", "/usr/lib/kdeconnectd", "/usr/share/gnome-shell/extensions/gsconnect@andyholmes.github.io"]) or flatpak_installed("org.kde.kdeconnect"):
        rules.append(rule("KDE Connect", "1714-1764", "tcp", "lan"))
        rules.append(rule("KDE Connect", "1714-1764", "udp", "lan"))
    end
    if any_exists(["/usr/bin/syncthing"]) or flatpak_installed("com.github.zocker_160.SyncThingy"):
        rules.append(rule("Syncthing", "22000", "tcp", "lan"))
        rules.append(rule("Syncthing", "21027", "udp", "lan"))
        rules.append(rule("Syncthing", "22000", "udp", "lan"))
    end
    if cups_shared():
        rules.append(rule("Printer sharing", "631", "tcp", "lan"))
    end
    if sshd_on():
        for p in sshd_ports():
            rules.append(rule("SSH", p, "tcp", "any"))
        end
    end
    ts = tailscale_port()
    if ts != None:
        rules.append(rule("Tailscale", ts, "udp", "any"))
    end
    return rules
end

# ---- pripojene site (adresy primo na rozhranich: mistni sit i s verejnymi adresami, IPv6 prefixy) ---------

function hexval(text):
    value = 0
    for ch in text.lower():
        digit = "0123456789abcdef".find(ch)
        if digit < 0:
            return -1
        end
        value = value * 16 + digit
    end
    return value
end

function lan_iface(name):
    for prefix in NOT_LAN_IFACES:
        if name.startswith(prefix):
            return False
        end
    end
    return True
end

# [site IPv4, site IPv6] z /proc/net/route a /proc/net/ipv6_route (trasy bez brany, ne vychozi)
function read_nets():
    v4 = []
    lines = read_text(ROOT + "/proc/net/route").split("\n")
    first = True
    for line in lines:
        if first:
            first = False
            continue
        end
        f = fields(line)
        if len(f) < 8 or not lan_iface(f[0]):
            continue
        end
        dest = f[1]
        gateway = f[2]
        flags = hexval(f[3])
        mask = hexval(f[7])
        if len(dest) != 8 or gateway != "00000000" or flags < 0 or mask <= 0 or (flags // 2) % 2 == 1:
            continue
        end
        bits = 0
        m = mask
        while m > 0:
            bits += m % 2
            m = m // 2
        end
        if bits < 8 or bits > 32:
            continue
        end
        net = String(hexval(dest[6:8])) + "." + String(hexval(dest[4:6])) + "." + String(hexval(dest[2:4])) + "." + String(hexval(dest[0:2])) + "/" + String(bits)
        if not (net in v4):
            v4.append(net)
        end
    end
    v6 = []
    for line in read_text(ROOT + "/proc/net/ipv6_route").split("\n"):
        f = fields(line)
        if len(f) < 10 or not lan_iface(f[9]):
            continue
        end
        dest = f[0].lower()
        plen = hexval(f[1])
        flags = hexval(f[8])
        if len(dest) != 32 or plen < 32 or plen > 127 or f[4] != "00000000000000000000000000000000":
            continue
        end
        if flags < 0 or (flags // 2) % 2 == 1 or dest.startswith("ff") or dest.startswith("fe8"):
            continue
        end
        groups = []
        i = 0
        while i < 32:
            groups.append(dest[i:i + 4])
            i += 4
        end
        net = ":".join(groups) + "/" + String(plen)
        if not (net in v6):
            v6.append(net)
        end
    end
    return [sorted(v4), sorted(v6), shared_ifaces()]
end

# Rozhrani se sdilenim pripojeni z NetworkManageru (hotspot, "Sdilet s ostatnimi pocitaci"): NM na nem spousti
# dnsmasq (/run/nm-dnsmasq-<rozhrani>.pid) pro DHCP a DNS pripojenych zarizeni
function shared_ifaces():
    out = []
    for name in list_names(ROOT + "/run"):
        if name.startswith("nm-dnsmasq-") and name.endswith(".pid") and len(name) > 15:
            iface = name[11:len(name) - 4]
            if clean_app(iface) == iface and not (iface in out):
                out.append(iface)
            end
        end
    end
    return sorted(out)
end

# ---- pravidla nftables ------------------------------------------------------------------------------------

function element_set(name, kind, items):
    text = "\tset " + name + " {\n\t\ttype " + kind + "\n\t\tflags interval\n\t\tauto-merge\n"
    if len(items) > 0:
        text = text + "\t\telements = { " + ", ".join(items) + " }\n"
    end
    return text + "\t}\n"
end

function ports_for(rules, allow, proto, source):
    out = []
    for r in rules:
        if r["proto"] == proto and r["from"] == source and not (r["port"] in out):
            out.append(r["port"])
        end
    end
    for item in allow:
        if item["proto"] == proto and item["from"] == source and not (item["port"] in out):
            out.append(item["port"])
        end
    end
    return out
end

function render(cfg, rules, nets):
    allow = cfg["allow"]
    t = "# LuxOS firewall (luxos-firewall " + VERSION + ") - only table inet " + TABLE + "\n"
    # vytvorit a hned smazat: stejny skript funguje s tabulkou i bez ni, vse v jedne transakci
    t = t + "table inet " + TABLE + " {}\ndelete table inet " + TABLE + "\n"
    t = t + "table inet " + TABLE + " {\n"
    t = t + element_set("lan4", "ipv4_addr", LAN4) + element_set("lan6", "ipv6_addr", LAN6)
    t = t + element_set("net4", "ipv4_addr", nets[0]) + element_set("net6", "ipv6_addr", nets[1])
    shared = []
    for name in nets[2]:
        shared.append("\"" + name + "\"")
    end
    t = t + "\tset shared_if {\n\t\ttype ifname\n"
    if len(shared) > 0:
        t = t + "\t\telements = { " + ", ".join(shared) + " }\n"
    end
    t = t + "\t}\n"
    t = t + element_set("lan_tcp", "inet_service", ports_for(rules, allow, "tcp", "lan"))
    t = t + element_set("lan_udp", "inet_service", ports_for(rules, allow, "udp", "lan"))
    t = t + element_set("any_tcp", "inet_service", ports_for(rules, allow, "tcp", "any"))
    t = t + element_set("any_udp", "inet_service", ports_for(rules, allow, "udp", "any"))
    t = t + "\n\tchain input {\n\t\ttype filter hook input priority filter + 10; policy accept;\n"
    t = t + "\t\tiif \"lo\" accept\n"
    t = t + "\t\tct state established,related accept\n"
    for name in TRUSTED_IFACES:
        t = t + "\t\tiifname \"" + name + "\" accept\n"
    end
    t = t + "\t\ticmp type { destination-unreachable, time-exceeded, parameter-problem } accept\n"
    t = t + "\t\ticmpv6 type { destination-unreachable, packet-too-big, time-exceeded, parameter-problem } accept\n"
    t = t + "\t\ticmpv6 type { nd-router-solicit, nd-router-advert, nd-neighbor-solicit, nd-neighbor-advert } ip6 hoplimit 255 accept\n"
    t = t + "\t\tip6 saddr fe80::/10 icmpv6 type { mld-listener-query, mld-listener-report, mld-listener-done, mld2-listener-report } accept\n"
    t = t + "\t\tmeta l4proto igmp accept\n"
    t = t + "\t\tudp sport 67 udp dport 68 accept\n"
    t = t + "\t\tip6 saddr fe80::/10 udp sport 547 udp dport 546 accept\n"
    t = t + "\t\tip daddr 224.0.0.251 udp dport 5353 accept\n"
    t = t + "\t\tip6 daddr ff02::fb udp dport 5353 accept\n"
    # sdileni pripojeni (hotspot): DHCP a DNS pro pripojena zarizeni (dnsmasq z NetworkManageru)
    t = t + "\t\tiifname @shared_if udp dport { 53, 67, 547 } accept\n"
    t = t + "\t\tiifname @shared_if tcp dport 53 accept\n"
    t = t + "\t\ttcp dport @any_tcp accept\n"
    t = t + "\t\tudp dport @any_udp accept\n"
    t = t + "\t\tiifname \"tailscale0\" goto from_tailscale\n"
    t = t + "\t\tip saddr @lan4 jump from_lan\n\t\tip saddr @net4 jump from_lan\n"
    t = t + "\t\tip6 saddr @lan6 jump from_lan\n\t\tip6 saddr @net6 jump from_lan\n"
    t = t + "\t\tgoto blocked\n\t}\n"
    t = t + "\n\tchain from_lan {\n"
    t = t + "\t\ticmp type echo-request accept\n\t\ticmpv6 type echo-request accept\n"
    t = t + "\t\ttcp dport @lan_tcp accept\n\t\tudp dport @lan_udp accept\n"
    t = t + "\t\tudp dport 5353 accept\n"
    t = t + "\t\tip daddr 239.255.255.250 udp dport { 1900, 3702 } accept\n"
    t = t + "\t\tip6 daddr ff02::c udp dport { 1900, 3702 } accept\n"
    t = t + "\t\tudp sport { " + DISCOVERY_SPORTS + " } udp dport " + String(EPHEMERAL_FIRST) + "-65535 accept\n"
    t = t + "\t}\n"
    t = t + "\n\tchain from_tailscale {\n"
    if cfg["trust_tailscale"]:
        t = t + "\t\tjump from_lan\n"
    end
    t = t + "\t\tgoto blocked\n\t}\n"
    t = t + "\n\tchain blocked {\n"
    t = t + "\t\tmeta pkttype host ct state new limit rate 30/minute burst 20 packets log prefix \"" + LOG_PREFIX + "\" level info\n"
    t = t + "\t\tcounter drop\n\t}\n}\n"
    return t
end

# ---- nahrani, stav ----------------------------------------------------------------------------------------

function nft_run(script):
    result = {"ok": False, "error": ""}
    out = ""
    try:
        out = capture_input(NFT, ["-f", "-"], script)
    else:
        result["error"] = String(last_error())
        return result
    end
    if capture_status() != 0:
        result["error"] = String(capture_stderr()).strip()
        return result
    end
    result["ok"] = True
    return result
end

function write_state(cfg, rules, nets, loaded, error):
    call sys.mkdir(RUN_DIR, 493)
    state = {"version": VERSION, "enable": cfg["enable"], "loaded": loaded, "error": error, "time": now(),
             "trust_tailscale": cfg["trust_tailscale"], "rules": rules, "allow": cfg["allow"],
             "nets": nets[0] + nets[1], "shared": nets[2]}
    if config_error != "":
        state["config_error"] = config_error
    end
    safe:
        call write_file(STATE, json.pretty(state) + "\n")
    end
    return None
end

function unload_table():
    return nft_run("table inet " + TABLE + " {}\ndelete table inet " + TABLE + "\n")
end

# Nahraje (nebo pri vypnutem firewallu odebere) tabulku podle nastaveni; vraci True pri uspechu
function apply():
    cfg = load_config()
    rules = detect()
    nets = read_nets()
    if not cfg["enable"]:
        result = unload_table()
        call write_state(cfg, rules, nets, False, result["error"])
        if not result["ok"]:
            call eprint("luxos-firewall: " + result["error"])
        end
        return result["ok"]
    end
    result = nft_run(render(cfg, rules, nets))
    if not result["ok"]:
        call eprint("luxos-firewall: " + T("the firewall rules could not be loaded:") + " " + result["error"])
        call write_state(cfg, rules, nets, False, result["error"])
        return False
    end
    call write_state(cfg, rules, nets, True, "")
    return True
end

function table_loaded():
    ok = False
    safe:
        call capture(NFT, ["list", "table", "inet", TABLE])
        ok = capture_status() == 0
    end
    return ok
end

function read_state():
    data = None
    safe:
        data = json.decode(read_text(STATE))
    end
    if type(data) != "Dictionary":
        return {}
    end
    return data
end

function read_requests():
    data = None
    safe:
        data = json.decode(read_text(REQUESTS))
    end
    if type(data) != "List":
        return []
    end
    return data
end

function service_active():
    out = ""
    safe:
        out = capture(SYSTEMCTL, ["is-active", "luxos-firewall.service"])
    end
    if out == None:
        return False
    end
    return out.strip() == "active"
end

function source_text(source):
    if source == "any":
        return T("everywhere")
    end
    return T("this network only")
end

function status(as_json):
    cfg = load_config()
    state = read_state()
    loaded = False
    if sys.getuid() == 0:
        loaded = table_loaded()
    else:
        loaded = state.get("loaded") == True and service_active()
    end
    rules = state.get("rules")
    if type(rules) != "List":
        rules = detect()
    end
    blocked = read_requests()
    if as_json:
        out = {"version": VERSION, "enable": cfg["enable"], "active": loaded, "trust_tailscale": cfg["trust_tailscale"],
               "rules": rules, "allow": cfg["allow"], "blocked": blocked, "error": state.get("error", "")}
        if config_error != "":
            out["config_error"] = config_error
        end
        print json.pretty(out)
        return 0
    end
    if cfg["enable"] and loaded:
        print T("Firewall: on - incoming connections from the network are blocked, except:")
    elif cfg["enable"]:
        print T("Firewall: on, but the rules are not loaded (the network is open).")
        err = state.get("error", "")
        if err != "" and err != None:
            print "  " + String(err)
        end
        print "  " + T("Try: sudo systemctl restart luxos-firewall")
    else:
        print T("Firewall: off - the computer accepts connections from the network.")
    end
    if config_error != "":
        print "  " + config_error
    end
    print ""
    print T("Allowed automatically:")
    if len(rules) == 0:
        print "  -"
    end
    for r in rules:
        print "  " + String(r.get("name", "")) + "  " + String(r.get("port", "")) + "/" + String(r.get("proto", "")) + "  (" + source_text(r.get("from", "lan")) + ")"
    end
    print ""
    print T("Your exceptions:")
    if len(cfg["allow"]) == 0:
        print "  -  (" + T("add one with: luxos-firewall allow PORT") + ")"
    end
    for item in cfg["allow"]:
        line = "  " + item["port"] + "/" + item["proto"] + "  (" + source_text(item["from"]) + ")"
        if item.get("app", "") != "":
            line = line + "  " + item["app"]
        end
        print line
    end
    if cfg["trust_tailscale"]:
        print ""
        print T("Tailscale devices are treated as this network.")
    end
    if len(blocked) > 0:
        print ""
        print T("Recently blocked (a program on this computer was listening):")
        for b in blocked:
            if type(b) == "Dictionary":
                print "  " + String(b.get("port", "")) + "/" + String(b.get("proto", "")) + "  " + String(b.get("app", "")) + "  " + T("from") + " " + String(b.get("src", ""))
            end
        end
    end
    return 0
end

# ---- zahozena spojeni -> zadosti pro luxos-hub ------------------------------------------------------------

function log_field(text, name):
    for word in text.split(" "):
        if word.startswith(name + "="):
            return word[len(name) + 1:].strip()
        end
    end
    return ""
end

function is_lan_address(addr):
    a = addr.lower()
    if a.startswith("10.") or a.startswith("192.168.") or a.startswith("169.254."):
        return True
    end
    if a.startswith("172."):
        parts = a.split(".")
        if len(parts) > 1 and is_digits(parts[1]):
            second = Int(parts[1])
            return second >= 16 and second <= 31
        end
    end
    return a.startswith("fe8") or a.startswith("fe9") or a.startswith("fea") or a.startswith("feb") or a.startswith("fc") or a.startswith("fd")
end

function ipv4_int(addr):
    parts = addr.split(".")
    if len(parts) != 4:
        return -1
    end
    value = 0
    for part in parts:
        if not is_digits(part) or len(part) > 3:
            return -1
        end
        value = value * 256 + Int(part)
    end
    return value
end

# Adresa v nektere pripojene siti (sada net4/net6 ze stavu; IPv6 v plnem tvaru jako v zaznamu jadra)
function in_nets(addr, nets):
    a = addr.lower()
    for net in nets:
        cut = net.find("/")
        if cut < 0:
            continue
        end
        base = net[0:cut]
        bits = Int(net[cut + 1:])
        if a.find(":") < 0 and base.find(":") < 0:
            x = ipv4_int(a)
            y = ipv4_int(base)
            if x >= 0 and y >= 0:
                block = 1
                i = 0
                while i < 32 - bits:
                    block = block * 2
                    i += 1
                end
                if x // block == y // block:
                    return True
                end
            end
        elif a.find(":") >= 0 and base.find(":") >= 0 and bits % 4 == 0:
            n = bits // 4
            ha = a.replace(":", "")
            hb = base.replace(":", "")
            if len(ha) == 32 and len(hb) == 32 and ha[0:n] == hb[0:n]:
                return True
            end
        end
    end
    return False
end

# Plny tvar IPv6 ze zaznamu jadra -> kratky (2001:db8:77::1) pro upozorneni
function short_ip(addr):
    groups = addr.lower().split(":")
    if len(groups) != 8:
        return addr
    end
    parts = []
    for g in groups:
        while len(g) > 1 and g.startswith("0"):
            g = g[1:]
        end
        parts.append(g)
    end
    best = -1
    best_len = 0
    i = 0
    while i < 8:
        if parts[i] == "0":
            j = i
            while j < 8 and parts[j] == "0":
                j += 1
            end
            if j - i > best_len:
                best = i
                best_len = j - i
            end
            i = j
        else:
            i += 1
        end
    end
    if best_len < 2:
        return ":".join(parts)
    end
    return ":".join(parts[0:best]) + "::" + ":".join(parts[best + best_len:])
end

function loopback_local(local):
    return local.startswith("127.") or local.startswith("[::1]") or local.startswith("[::ffff:127.") or local.find("%lo:") >= 0
end

# Nazev programu (python3 skript -> nazev skriptu, kontejnery Podmanu -> Podman)
function app_name(comm, pid):
    if comm == "pasta" or comm.startswith("pasta.") or comm == "passt" or comm.startswith("passt.") or comm == "rootlessport" or comm == "slirp4netns" or comm == "conmon":
        return "Podman"
    end
    if comm.startswith("python") and pid != "":
        args = read_text("/proc/" + pid + "/cmdline").split("\0")
        index = 1
        while index < len(args):
            a = args[index]
            if a == "-m" and index + 1 < len(args):
                return clean_app(args[index + 1])
            end
            if a != "" and not a.startswith("-"):
                parts = a.split("/")
                return clean_app(parts[len(parts) - 1])
            end
            index += 1
        end
    end
    if comm == "node":
        return "Node.js"
    end
    return clean_app(comm)
end

# Mistni program poslouchajici na portu mimo loopback: {"app", "pid"} nebo None
function find_listener(proto, port):
    flag = "-Hlnpt"
    if proto == "udp":
        flag = "-Hlnpu"
    end
    out = ""
    safe:
        out = capture(SS, [flag, "sport", "=", ":" + String(port)])
    end
    if out == None:
        return None
    end
    for line in out.split("\n"):
        f = fields(line)
        if len(f) < 5 or loopback_local(f[3]):
            continue
        end
        comm = ""
        pid = ""
        start = line.find("users:((\"")
        if start >= 0:
            rest = line[start + 9:]
            stop = rest.find("\"")
            if stop > 0:
                comm = rest[0:stop]
            end
            p = rest.find("pid=")
            if p >= 0:
                digits = ""
                for ch in rest[p + 4:]:
                    if "0123456789".find(ch) < 0:
                        break
                    end
                    digits = digits + ch
                end
                pid = digits
            end
        end
        name = app_name(comm, pid)
        if name == "":
            name = "unknown"
        end
        return {"app": name, "pid": pid}
    end
    return None
end

seen = {}
requests = []

function on_drop(text):
    global requests
    cut = text.find(LOG_PREFIX)
    if cut < 0:
        return 0
    end
    line = text[cut + len(LOG_PREFIX):].replace("\n", " ")
    proto = log_field(line, "PROTO").lower()
    port = to_port(log_field(line, "DPT"))
    if port == None or (proto != "tcp" and proto != "udp"):
        return 0
    end
    if proto == "udp" and port >= EPHEMERAL_FIRST:
        return 0
    end
    # Jen spojeni z mistni site a Tailscale: "Povolit" povoluje mistni sit; pokusy z internetu
    # (skenovani portu) se neoznamuji, zustanou jen v zaznamu jadra
    src = log_field(line, "SRC")
    iface = log_field(line, "IN")
    lan = is_lan_address(src)
    if not lan:
        state = read_state()
        nets = state.get("nets")
        if type(nets) == "List":
            lan = in_nets(src, nets)
        end
    end
    if not lan and not iface.startswith("tailscale"):
        return 0
    end
    key = String(port) + "/" + proto
    t = now()
    if key in seen and t - seen[key] < REQUEST_EVERY:
        return 0
    end
    seen[key] = t
    listener = find_listener(proto, port)
    if listener == None:
        return 0
    end
    entry = {"port": port, "proto": proto, "app": listener["app"], "src": short_ip(src), "iface": iface,
             "lan": lan, "tailscale": iface.startswith("tailscale"), "time": t}
    kept = [entry]
    for old in requests:
        if type(old) == "Dictionary" and not (old.get("port") == port and old.get("proto") == proto) and len(kept) < REQUEST_KEEP:
            kept.append(old)
        end
    end
    requests = kept
    call sys.mkdir(RUN_DIR, 493)
    safe:
        call write_file(REQUESTS, json.pretty(requests) + "\n")
    end
    call eprint("blocked " + key + " (" + listener["app"] + ") from " + src + " on " + iface)
    return 0
end

# Aktualizace sady pripojenych siti v nahrane tabulce (zmena Wi-Fi, novy prefix IPv6)
function update_nets(nets):
    script = "flush set inet " + TABLE + " net4\nflush set inet " + TABLE + " net6\nflush set inet " + TABLE + " shared_if\n"
    if len(nets[0]) > 0:
        script = script + "add element inet " + TABLE + " net4 { " + ", ".join(nets[0]) + " }\n"
    end
    if len(nets[1]) > 0:
        script = script + "add element inet " + TABLE + " net6 { " + ", ".join(nets[1]) + " }\n"
    end
    if len(nets[2]) > 0:
        quoted = []
        for name in nets[2]:
            quoted.append("\"" + name + "\"")
        end
        script = script + "add element inet " + TABLE + " shared_if { " + ", ".join(quoted) + " }\n"
    end
    return nft_run(script)
end

function nets_key(nets):
    return ",".join(nets[0] + nets[1]) + "|" + ",".join(nets[2])
end

function watch():
    global requests
    requests = read_requests()
    fd = sys.open_kmsg(KMSG)
    if fd < 0:
        call eprint("luxos-firewall: cannot read " + KMSG + "; notifications about blocked programs are off")
    end
    last_nets = ""
    state = read_state()
    if type(state.get("nets")) == "List" and type(state.get("shared")) == "List":
        last_nets = ",".join(state["nets"]) + "|" + ",".join(state["shared"])
    end
    last_check = 0
    while True:
        if fd >= 0:
            if sys.wait_readable(fd, 10000):
                count = 0
                while count < 200:
                    record = sys.read_record(fd)
                    if record == None:
                        break
                    end
                    if record.find(LOG_PREFIX) >= 0:
                        safe:
                            call on_drop(record)
                        end
                    end
                    count += 1
                end
            end
        else:
            call sys.sleep_ms(10000)
        end
        t = now()
        if t - last_check >= 10:
            last_check = t
            nets = read_nets()
            text = nets_key(nets)
            if text != last_nets:
                state = read_state()
                if state.get("loaded") == True:
                    result = update_nets(nets)
                    if result["ok"]:
                        last_nets = text
                        state["nets"] = nets[0] + nets[1]
                        state["shared"] = nets[2]
                        safe:
                            call write_file(STATE, json.pretty(state) + "\n")
                        end
                        call eprint("local networks: " + text)
                    end
                end
            end
        end
    end
    return 0
end

# ---- prikazy ----------------------------------------------------------------------------------------------

function usage():
    print "luxos-firewall " + VERSION + " - " + T("LuxOS firewall")
    print ""
    print "  luxos-firewall status [--json]"
    print "  luxos-firewall on | off"
    print "  luxos-firewall allow PORT[/tcp|/udp] [--from lan|any] [--app NAME]"
    print "  luxos-firewall deny PORT[/tcp|/udp]"
    print "  luxos-firewall tailscale on | off"
    print ""
    print T("allow: --from lan (default) = only devices on this network, --from any = everywhere")
    print T("You can also change it in Settings > Firewall.")
    return 0
end

# Prikazy s pravy roota: bez nich znovu pres pkexec (polkit; spravce v aktivni relaci)
function need_root():
    if sys.getuid() == 0:
        return None
    end
    if ROOT == "" and exists("/usr/bin/pkexec"):
        argv = ["/usr/bin/pkexec", SELF]
        index = 1
        while index < arg_count():
            argv.append(arg(index))
            index += 1
        end
        call sys.exec(argv)
    end
    call fail(T("administrator rights are needed (sudo luxos-firewall ...)"), 4)
    return None
end

function changed(cfg, message):
    call save_config(cfg)
    ok = apply()
    print message
    if not cfg["enable"]:
        print T("The firewall is off; the change applies when you turn it on.")
    end
    if not ok:
        return 1
    end
    return 0
end

function ensure_units():
    if ROOT != "" or not exists(SYSTEMCTL):
        return None
    end
    safe:
        call capture(SYSTEMCTL, ["enable", "--now", "luxos-firewall.service", "luxos-firewall-watch.service", "luxos-firewall-refresh.path"])
    end
    return None
end

function main():
    command = "help"
    if arg_count() > 1:
        command = arg(1)
    end
    rest = []
    index = 2
    while index < arg_count():
        rest.append(arg(index))
        index += 1
    end

    if command == "help" or command == "--help" or command == "-h":
        return usage()
    end
    if command == "version" or command == "--version":
        print VERSION
        return 0
    end
    if command == "status":
        return status("--json" in rest)
    end
    if command == "render":
        cfg = load_config()
        print render(cfg, detect(), read_nets())
        return 0
    end
    if command == "blocked":
        print json.pretty(read_requests())
        return 0
    end

    if command == "load" or command == "refresh" or command == "reload":
        call need_root()
        if apply():
            return 0
        end
        return 1
    end
    if command == "unload":
        call need_root()
        result = unload_table()
        cfg = load_config()
        call write_state(cfg, [], [[], [], []], False, "")
        if not result["ok"]:
            call eprint("luxos-firewall: " + result["error"])
            return 1
        end
        return 0
    end
    if command == "watch":
        call need_root()
        return watch()
    end
    if command == "on" or command == "off":
        call need_root()
        cfg = load_config()
        cfg["enable"] = command == "on"
        call save_config(cfg)
        if command == "on":
            call ensure_units()
        end
        if not apply():
            return 1
        end
        if command == "on":
            print T("The firewall is on.")
        else:
            print T("The firewall is off. Turn it on again with: luxos-firewall on")
        end
        return 0
    end
    if command == "tailscale":
        if len(rest) != 1 or (rest[0] != "on" and rest[0] != "off"):
            call fail("usage: luxos-firewall tailscale on|off", 2)
        end
        call need_root()
        cfg = load_config()
        cfg["trust_tailscale"] = rest[0] == "on"
        if rest[0] == "on":
            return changed(cfg, T("Tailscale devices are treated as this network."))
        end
        return changed(cfg, T("Tailscale devices are no longer treated as this network."))
    end
    if command == "allow" or command == "deny" or command == "remove":
        if len(rest) == 0:
            call fail("usage: luxos-firewall " + command + " PORT[/tcp|/udp]", 2)
        end
        spec = parse_spec(rest[0])
        if spec == None:
            call fail(TF("\"%s\" is not a valid port (e.g. 8080, 8080/tcp, 8000-8010/udp)", [rest[0]]), 2)
        end
        source = "lan"
        app = ""
        i = 1
        while i < len(rest):
            if rest[i] == "--from" and i + 1 < len(rest) and (rest[i + 1] == "lan" or rest[i + 1] == "any"):
                source = rest[i + 1]
                i += 2
            elif rest[i] == "--app" and i + 1 < len(rest):
                app = clean_app(rest[i + 1])
                i += 2
            else:
                call fail("unknown option: " + rest[i], 2)
            end
        end
        call need_root()
        cfg = load_config()
        protos = [spec["proto"]]
        if spec["proto"] == "both":
            protos = ["tcp", "udp"]
        end
        if command == "allow":
            for p in protos:
                call add_exception(cfg, spec["port"], p, source, app)
            end
            shown = spec["port"]
            if spec["proto"] != "both":
                shown = shown + "/" + spec["proto"]
            end
            return changed(cfg, TF("Allowed incoming connections to %s (%s).", [shown, source_text(source)]))
        end
        kept = []
        removed = 0
        for item in cfg["allow"]:
            if item["port"] == spec["port"] and item["proto"] in protos:
                removed += 1
            else:
                kept.append(item)
            end
        end
        if removed == 0:
            print TF("There is no exception for %s.", [rest[0]])
            return 1
        end
        cfg["allow"] = kept
        return changed(cfg, TF("Port %s is blocked again.", [rest[0]]))
    end
    call eprint("luxos-firewall: unknown command: " + command)
    call usage()
    return 2
end

call exit(main())
