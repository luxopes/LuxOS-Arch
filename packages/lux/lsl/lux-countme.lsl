# LuxOS - lux-countme: anonymni tydenni pocitani aktivnich instalaci (nahrada lux_countme.py).
#
# Nejvys jednou za kalendarni tyden (ISO tyden od pondeli, UTC), kdyz lux jako root uz stahuje seznamy
# baliku, posle jeden maly pozadavek navic:
#
#     GET https://luxos.lux-ai.cz/countme?v=1.0.0&arch=x86_64&ch=stable&age=2
#
# a NIC jineho: verze LuxOS, architektura, kanal aktualizaci a stari instalace (1 = prvni tyden,
# 2 = do mesice, 3 = do pul roku, 4 = dele). Zadny identifikator, nazev pocitace, hardware, seznam
# aplikaci ani data uzivatele. Hlavicky jen Host, User-Agent "LuxOS-countme" a Connection: close - proto
# se pozadavek sklada rucne nad TLS (OpenSSL, overeni systemovymi CA), ne pres curl, ktery by pridal
# Accept a dalsi.
#
#   lux-countme status    co by se poslalo a proc (ne)
#   lux-countme send      poslat hned, kdyz je tento tyden na rade (jen root; pro ladeni)
#
# Stav: /var/lib/lux/countme (JSON), uzamceni /var/lib/lux/countme.lock - stejne soubory a format jako
# lux_countme.py, obe verze se mohou stridat. Pro testy: LUX_COUNTME_ROOT (predpona souboru),
# LUX_COUNTME_STATE, LUX_COUNTME_LOCK, LUX_COUNTME_HOST/PORT, LUX_COUNTME_HTTP=1 (obycejne HTTP), LUX_COUNTME_NOW (cas).
load env
load glib
load json
load luxos_i18n as i18n
load luxos_sys as sys
load luxos_glib as lglib
load luxfs as fs
load net
load tls
load process

HOST = "luxos.lux-ai.cz"
PATH = "/countme"
TIMEOUT_MS = 5000
USER_AGENT = "LuxOS-countme"
LUX_CONFIG = "/usr/lib/lux/lux-config"
VERSION_FILE = "/usr/lib/luxos/version"
OS_RELEASE = ["/etc/os-release", "/usr/lib/os-release"]
INSTALL_LOG = "/var/log/luxos-install.log"
OEM_CONF = "/etc/luxos/oem.conf"
OEM_DONE = "/var/lib/luxos/oem/done"
LIVE_MARKERS = ["/run/archiso", "/run/archiso/bootmnt"]
CONTAINER_MARKERS = ["/run/.containerenv", "/.dockerenv"]
DAY = 86400

# status ukazuje, co by poslal root (lux update, LuxOS Care), i kdyz ho spousti bezny uzivatel
assume = {"root": False}

function _(text):
    return i18n.T(text)
end

function root_prefix():
    return env.get("LUX_COUNTME_ROOT", "")
end

function state_path():
    return env.get("LUX_COUNTME_STATE", "/var/lib/lux/countme")
end

function lock_path():
    return env.get("LUX_COUNTME_LOCK", "/var/lib/lux/countme.lock")
end

function read_file(path):
    text = None
    safe:
        text = lglib.read_text(root_prefix() + path)
    end
    if text == None:
        return None
    end
    return text[0:65536] if len(text) > 65536 else text
end

# ---- cas: ISO tyden (UTC) ----

# [rok, mesic, den] z poctu dni od 1970-01-01 (civil_from_days, Howard Hinnant)
function civil_from_days(days):
    z = days + 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    if m <= 2:
        y += 1
    end
    return [y, m, d]
end

function is_leap(y):
    return (y % 4 == 0 and y % 100 != 0) or y % 400 == 0
end

function weeks_in_year(y):
    p = (y + y // 4 - y // 100 + y // 400) % 7
    q = (y - 1 + (y - 1) // 4 - (y - 1) // 100 + (y - 1) // 400) % 7
    return 53 if (p == 4 or q == 3) else 52
end

function ordinal(y, m, d):
    cum = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    n = cum[m - 1] + d
    if m > 2 and is_leap(y):
        n += 1
    end
    return n
end

function pad2(n):
    return ("0" + String(n)) if n < 10 else String(n)
end

# "2026-W45"
function iso_week(now):
    days = now // DAY
    cal = civil_from_days(days)
    weekday = (days + 3) % 7 + 1
    week = (ordinal(cal[0], cal[1], cal[2]) - weekday + 10) // 7
    year = cal[0]
    if week < 1:
        year -= 1
        week = weeks_in_year(year)
    elif week > weeks_in_year(year):
        year += 1
        week = 1
    end
    return String(year) + "-W" + pad2(week)
end

function age_bucket(since, now):
    days = Float(max(0, now - since)) / Float(DAY)
    if days < 7.0:
        return 1
    elif days < 30.0:
        return 2
    elif days < 182.0:
        return 3
    end
    return 4
end

# ---- verze, architektura, nastaveni ----

function is_digits(t):
    if t == "":
        return False
    end
    for ch in t:
        if not (ch in "0123456789"):
            return False
        end
    end
    return True
end

# X.Y.Z (1-2, 1-3, 1-3 cislice)
function valid_version(v):
    parts = v.split(".")
    if len(parts) != 3:
        return False
    end
    limits = [2, 3, 3]
    i = 0
    for p in parts:
        if not is_digits(p) or len(p) > limits[i]:
            return False
        end
        i += 1
    end
    return True
end

# hodnota klice na zacatku radku (^KEY=["']?([^"'\s]+)), prvni platna
function key_value(text, key):
    for line in text.split(chr(10)):
        if line.startswith(key + "="):
            rest = line[len(key) + 1:]
            if rest.startswith(chr(34)) or rest.startswith("'"):
                rest = rest[1:]
            end
            out = ""
            for ch in rest:
                if ch in [chr(34), "'", " ", chr(9), chr(13)]:
                    break
                end
                out = out + ch
            end
            if out != "":
                return out
            end
        end
    end
    return None
end

function os_version():
    text = read_file(VERSION_FILE)
    if text != None:
        v = key_value(text, "VERSION")
        if v != None and valid_version(v):
            return v
        end
    end
    for p in OS_RELEASE:
        t = read_file(p)
        if t != None:
            v = key_value(t, "VERSION_ID")
            if v != None and valid_version(v):
                return v
            end
        end
    end
    return None
end

function machine_arch():
    a = fs.machine()
    return a if a == "x86_64" else None
end

# [zapnuto, kanal]; rozbita nebo chybejici konfigurace = nic neposilat
function settings():
    conf = env.get("LUX_COUNTME_CONF", "")
    argv = ["json"] + (["--config", conf] if conf != "" else [])
    res = None
    try:
        res = process.capture_result(LUX_CONFIG, argv)
    else:
        return [False, None]
    end
    if res["status"] != 0:
        return [False, None]
    end
    cfg = None
    try:
        cfg = json.decode(res["stdout"])
    else:
        return [False, None]
    end
    general = cfg.get("general", {}) if type(cfg) == "Dictionary" else {}
    on = general.get("countme", None)
    ch = general.get("channel", None)
    if ch == None or ch == "":
        ch = "stable"
    end
    # klic chybi (starsi lux-engine): vychozi zapnuto
    if on == None:
        on = True
    end
    return [on == True or on == "on", ch]
end

# ---- stav ----

function load_state():
    text = None
    safe:
        text = lglib.read_text(state_path())
    end
    if text == None:
        return {}
    end
    d = None
    try:
        d = json.decode(text)
    else:
        return {}
    end
    return d if type(d) == "Dictionary" else {}
end

function save_state(since, last_week):
    lw = "null" if last_week == None else json.encode(last_week)
    return lglib.write_atomic(state_path(), "{\"since\": " + String(since) + ", \"last_week\": " + lw + "}" + chr(10))
end

function oem_pending():
    text = read_file(OEM_CONF)
    if text == None:
        return False
    end
    found = False
    for line in text.split(chr(10)):
        if line.rstrip() == "OEM=1":
            found = True
        end
    end
    return found and not exists(root_prefix() + OEM_DONE)
end

# Dokonceni Pruvodce (OEM), jinak zmena protokolu instalatoru, jinak ted
function install_time(now):
    for p in [OEM_DONE, INSTALL_LOG]:
        st = fs.stat(root_prefix() + p)
        if st != None:
            t = st["mtime"][0]
            if t > 0 and t <= now:
                return t
            end
        end
    end
    return now
end

# Duvod, proc se tento pocitac nepocita (None = muze)
function blocked():
    if fs.geteuid() != 0 and not assume["root"]:
        return "not root"
    end
    rootdir = env.get("LUX_COUNTME_ROOTDIR", "/")
    if lglib.realpath(rootdir) != "/":
        return "other root"
    end
    for m in LIVE_MARKERS:
        if exists(root_prefix() + m):
            return "live system"
        end
    end
    cmd = read_file("/proc/cmdline")
    if cmd != None and ("archisobasedir=" in cmd or "archisolabel=" in cmd):
        return "live system"
    end
    for m in CONTAINER_MARKERS:
        if exists(root_prefix() + m):
            return "container"
        end
    end
    if oem_pending():
        return "setup assistant not finished (OEM)"
    end
    return None
end

# [parametry [[klic, hodnota]...], since, last_week] nebo [None, duvod]
function plan(now, check_week=True):
    why = blocked()
    if why != None:
        return [None, why]
    end
    s = settings()
    if not s[0]:
        return [None, "turned off (countme = false in /etc/lux/lux.conf)"]
    end
    if not (s[1] in ["stable", "staging"]):
        return [None, "unknown channel"]
    end
    v = os_version()
    arch = machine_arch()
    if v == None:
        return [None, "unknown LuxOS version"]
    end
    if arch == None:
        return [None, "unsupported architecture"]
    end
    st = load_state()
    since = st.get("since", None)
    if not (type(since) == "Int" or type(since) == "Float") or since <= 0 or since > now + DAY:
        since = install_time(now)
    end
    since = Int(since)
    last = st.get("last_week", None)
    if type(last) != "String":
        last = None
    end
    week = iso_week(now)
    if check_week and last == week:
        return [None, "already counted this week (" + week + ")"]
    end
    return [[["v", v], ["arch", arch], ["ch", s[1]], ["age", String(age_bucket(since, now))]], since, last]
end

function quote_plus(t):
    out = ""
    safe_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-~"
    for ch in t:
        if ch in safe_chars:
            out = out + ch
        elif ch == " ":
            out = out + "+"
        else:
            out = out + "%" + hex2(ord(ch))
        end
    end
    return out
end

function hex2(n):
    digits = "0123456789ABCDEF"
    return digits[n // 16] + digits[n % 16]
end

function query(params):
    return PATH + "?" + "&".join([quote_plus(p[0]) + "=" + quote_plus(p[1]) for p in params])
end

# ---- odeslani ----

# Jeden GET; True = server odpovedel 2xx. Zadne presmerovani, cookies ani opakovani.
function send(params):
    host = env.get("LUX_COUNTME_HOST", HOST)
    plain = env.get("LUX_COUNTME_HTTP", "") != ""
    port = Int(env.get("LUX_COUNTME_PORT", "80" if plain else "443"))
    # jako http.client: nestandardni port patri do Host
    host_header = host if port == (80 if plain else 443) else host + ":" + String(port)
    request = "GET " + query(params) + " HTTP/1.1" + chr(13) + chr(10) + "Host: " + host_header + chr(13) + chr(10)
    request = request + "User-Agent: " + USER_AGENT + chr(13) + chr(10) + "Connection: close" + chr(13) + chr(10) + chr(13) + chr(10)
    status_line = ""
    fd = net.tcp_connect(host, port, TIMEOUT_MS)
    if plain:
        call net.send(fd, net.bytes(request), TIMEOUT_MS)
        status_line = net.text(net.recv(fd, 1024, TIMEOUT_MS))
        call net.close(fd)
    else:
        ctx = tls.context("client")
        call tls.verify_system(ctx)
        ssl = tls.client(ctx, fd, host)
        call tls.handshake(ssl, TIMEOUT_MS)
        call tls.write(ssl, net.bytes(request), TIMEOUT_MS)
        status_line = net.text(tls.read(ssl, 1024, TIMEOUT_MS))
        call tls.close(ssl)
        call tls.context_free(ctx)
    end
    parts = status_line.split(" ")
    if len(parts) < 2 or not is_digits(parts[1]):
        return False
    end
    code = Int(parts[1])
    return code >= 200 and code < 300
end

# "sent" | "failed" | "busy" | duvod, proc ne
function run_once(now):
    fd = fs.open(lock_path(), fs.O_WRONLY + fs.O_CREAT + fs.O_APPEND + fs.O_CLOEXEC, 420)
    if fd < 0:
        return "no state directory"
    end
    result = ""
    if not fs.flock_nb(fd):
        call fs.close(fd)
        return "busy"
    end
    p = plan(now)
    if p[0] == None:
        result = p[1]
    else:
        ok = False
        try:
            ok = send(p[0])
        else:
            ok = False
        end
        if not ok:
            result = "failed"
        elif not save_state(p[1], iso_week(now)):
            result = "failed"
        else:
            result = "sent"
        end
    end
    call fs.close(fd)
    return result
end

function status_text():
    now = current_time()
    # co by poslal root (lux update, LuxOS Care)
    assume["root"] = True
    p = plan(now, False)
    last = load_state().get("last_week", None)
    if type(last) != "String" or last == "":
        last = _("never")
    end
    lines = [i18n.TF("countme: last counted week: %s", [last])]
    if p[0] == None:
        lines.append(i18n.TF("countme: not sent - %s", [_(p[1])]))
    else:
        lines.append(i18n.TF("countme: request (once per week, when the package lists are refreshed): %s", ["https://" + HOST + query(p[0])]))
        lines.append(i18n.TF("countme: headers: %s", ["Host: " + HOST + ", User-Agent: " + USER_AGENT + ", Connection: close"]))
        if p[2] == iso_week(now):
            lines.append(_("countme: this week is already counted"))
        end
    end
    if settings()[0]:
        lines.append(_("countme: turn off: lux config countme off"))
    else:
        lines.append(_("countme: turn on: lux config countme on"))
    end
    return chr(10).join(lines)
end

# LUX_COUNTME_NOW: pevny cas pro testy
function current_time():
    t = env.get("LUX_COUNTME_NOW", "")
    return Int(t) if is_digits(t) else lglib.now()
end

function main():
    cmd = "status"
    if arg_count() > 1:
        cmd = arg(1)
    end
    if cmd == "status":
        print status_text()
        return 0
    elif cmd == "send":
        r = run_once(current_time())
        print "countme: " + r
        return 0 if (r == "sent" or r.startswith("already")) else 1
    end
    call sys.eprint("usage: lux-countme status|send")
    return 2
end

call exit(main())
