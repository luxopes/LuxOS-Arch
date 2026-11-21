# lsl: link libglib-2.0.so.0
# LuxOS - Zpetna vazba bez okna (luxos-feedback): systemove udaje bez osobnich dat, odeslani hlaseni
# a fronta neodeslanych hlaseni. Stejne chovani jako drivejsi program v Pythonu.
#
# Hlaseni jde na POST <origin>/api/feedback (JSON). Prihlaseny ucet LuxAI (~/.config/luxai/account.json) se
# prilozi jako cookie lux_account_session, jinak je hlaseni anonymni; LUXAI_ORIGIN (vyvoj, testy): https
# kamkoli, http jen na tento pocitac. Bez internetu se hlaseni ulozi do ~/.local/share/luxos/feedback-outbox.
#
#   context() -> udaje pro redact (domov, uzivatel, pocitac, site Wi-Fi)
#   redact(text, ctx), collect_system(ctx) -> slovnik toho, co se odesle, pretty(hodnota) -> JSON s odsazenim
#   send(payload) -> {"id"} nebo {"error": kod, "status": HTTP}; save_outbox(payload), flush_outbox() -> pocet
load env, json, http, process, random, time
load luxos_glib, glib as glib
load luxos_regex as re
load luxos_sys as sys
load luxos_text as txt

ENDPOINT = "/api/feedback"
APP = "luxos-feedback"
DEFAULT_ORIGIN = "https://lux-ai.cz"
COOKIE = "lux_account_session"
MIN_LEN = 10
MAX_LEN = 8000
# nastroj jadra lux (lux-engine, mimo PATH) - jen dotazy na verze baliku
ENGINE = "/usr/lib/lux/alpm/bin/lux-engine"
SYSTEM_MAX = 30000        # server bere nejvys ~32 KB
SHOT_WIDTH = 1280
SHOT_MAX = 1400000        # WEDOS proxy nema rada velka tela
NET_RETRIES = 4
KINDS = [
    ["bug", "Bug", "Something doesn't work", "dialog-error-symbolic",
     "What happened? What did you expect? Steps to reproduce help a lot."],
    ["idea", "Idea", "Suggest an improvement", "starred-symbolic",
     "What would you like to improve? How would it help you?"],
    ["other", "Something else", "Question or comment", "dialog-question-symbolic", "Write your message…"]]
ERRORS = {
    "rate": "You have sent many reports in a short time. Please try again later.",
    "message_length": "The message must have 10 to 8000 characters.",
    "invalid_contact": "The e-mail address does not look valid.",
    "too_large": "The report is too large. Try it without the screenshot.",
    "invalid_screenshot": "The screenshot could not be accepted. Try it without the screenshot."}

RE_EMAIL = "[\\w.+-]+@[\\w-]+(\\.[\\w-]+)+"
RE_SECRET = "(?i)\\b(token|password|passwd|secret|cookie|session|authorization|api[_-]?key)\\b(\\s*[=:]\\s*)\\S+"
RE_LONG = "[A-Za-z0-9_\\-+=]{32,}"      # bez "/" - cesty nechat citelne
RE_IP = "(?<![\\w.-])\\d{1,3}(\\.\\d{1,3}){3}(?!\\w|\\.\\d)"
RE_MAC = "\\b[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}\\b"
# IPv6: plnych 8 skupin nebo zkraceny zapis s "::" (casy jako 08:25:26 tim neprojdou)
RE_IP6 = "(?<![\\w:.])(?:(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}|(?:[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4})*)?::(?:[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4})*)?)(?:%[\\w.-]+)?(?![\\w:])"
RE_SSID = "(?i)\\b(e?ssid)(\\s*[=:]?\\s*)(['\"])(.+?)\\3"
PACKAGES = "^(luxos|lux$|lux-|luxai|lsl|linux$|linux-lts$|linux-zen$|mesa$|xorg-server$|xfce4-session$)"

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function cstr(text):
    unsafe:
        return __lsl_address(text) + 16
    end
end

# stdout programu bez mezer na koncich, "" pri chybe nebo po limitu
function command(argv, seconds):
    result = None
    safe:
        result = process.capture_result("/usr/bin/env", ["timeout", String(seconds)] + argv)
    end
    if result == None or result["status"] != 0:
        return ""
    end
    return String(result["stdout"]).strip()
end

function read(path):
    return glib.read_text(path).strip()
end

function home():
    return glib.home_dir()
end

function byte_length(text):
    unsafe:
        return __lsl_text_byte_length(text)
    end
end

# ---- odstraneni osobnich udaju -----------------------------------------------------------------------------

function wifi_names():
    names = []
    for line in txt.lines(command(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"], 8)):
        if line.endswith(":802-11-wireless"):
            names.append(line[:txt.rfind(line, ":")].replace("\\:", ":"))
        end
    end
    return names
end

function context():
    user = env.get("USER", "")
    if user == "":
        user = home()[txt.rfind(home(), "/") + 1:]
    end
    return {"home": home(), "user": user, "host": glib.host_name(), "ssids": None}
end

# Odstrani cestu domu, jmeno uzivatele/pocitace, e-maily, IP/MAC, nazvy siti Wi-Fi a vse, co vypada jako
# tajny klic
function redact(text, ctx):
    if ctx["home"] != "":
        text = text.replace(ctx["home"], "~")
    end
    text = re.sub(RE_EMAIL, text, "<email>")
    text = re.sub(RE_SECRET, text, "\\1\\2<redacted>")
    text = re.sub(RE_LONG, text, "<redacted>")
    text = re.sub(RE_MAC, text, "<mac>")
    text = re.sub(RE_IP, text, "<ip>")
    text = re.sub(RE_IP6, text, "<ip>")
    text = re.sub(RE_SSID, text, "\\1\\2\\3<ssid>\\3")
    if ctx["ssids"] == None:
        ctx["ssids"] = wifi_names()
    end
    for ssid in ctx["ssids"]:
        if len(ssid) >= 3:
            text = text.replace(ssid, "<ssid>")
        end
    end
    for pair in [[ctx["user"], "<user>"], [ctx["host"], "<host>"]]:
        if len(pair[0]) >= 3:
            text = re.sub("(?<![\\w-])" + re.escape(pair[0]) + "(?![\\w-])", text, pair[1])
        end
    end
    return text
end

function log_lines(text, ctx, n):
    out = []
    for line in text.split("\n"):
        if line.strip() != "" and not line.startswith("-- "):
            clean = redact(line, ctx)
            if len(clean) > 300:
                clean = clean[:300]
            end
            out.append(clean)
        end
    end
    if len(out) > n:
        out = out[len(out) - n:]
    end
    return out
end

# ---- systemove udaje ------------------------------------------------------------------------------------------

function cpu_count():
    unsafe:
        # _SC_NPROCESSORS_ONLN
        return __lsl_qbe_call1(__lsl_symbol("sysconf"), 84)
    end
end

# volne misto pro uzivatele v bajtech (statvfs: f_frsize +8, f_bavail +32)
function disk_free(path):
    unsafe:
        st = __lsl_byte_zeros(112)
        base = __lsl_qbe_load64(__lsl_address(st) + 24)
        if __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("statvfs"), cstr(path), base)) != 0:
            return 0
        end
        return __lsl_qbe_load64(base + 32) * __lsl_qbe_load64(base + 8)
    end
end

function round1(value):
    return Float(math_round(value * 10.0)) / 10.0
end

function math_round(value):
    return Int(value + 0.5) if value >= 0.0 else -Int(-value + 0.5)
end

function join_present(items):
    out = []
    for x in items:
        if x != "":
            out.append(x)
        end
    end
    return " ".join(out)
end

# Slovnik presne toho, co se odesle (zobrazuje se i v okne)
function collect_system(ctx):
    osr = {}
    for line in read("/etc/os-release").split("\n"):
        eq = line.find("=")
        if eq >= 0:
            value = line[eq + 1:]
            while value.startswith("\""):
                value = value[1:]
            end
            while value.endswith("\""):
                value = value[:len(value) - 1]
            end
            osr[line[:eq]] = value
        end
    end
    mem = re.search("MemTotal:\\s+(\\d+)", read("/proc/meminfo"), False)
    cpu = re.search("model name\\s*:\\s*(.+)", read("/proc/cpuinfo"), False)
    gpu = []
    for line in txt.lines(command(["lspci"], 8)):
        if re.search("VGA|3D|Display", line, False) != None and len(gpu) < 3:
            cut = line.find(": ")
            name = line[cut + 2:] if cut >= 0 else line
            gpu.append(re.sub(" \\(rev .*\\)$", name, ""))
        end
    end
    pkgs = {}
    for line in txt.lines(command([ENGINE, "-Q"], 8)):
        space = line.find(" ")
        name = line[:space] if space >= 0 else line
        ver = line[space + 1:] if space >= 0 else ""
        if re.search(PACKAGES, name, False) != None:
            pkgs[name] = ver
        end
    end
    uptime = read("/proc/uptime").split(" ")[0]
    up = 0
    safe:
        up = Int(Float(uptime) / 60.0)
    end
    build = osr.get("BUILD_ID", "")
    if build == "":
        build = osr.get("VERSION_ID", "")
    end
    info = {
        "os": osr.get("PRETTY_NAME", "LuxOS"),
        "osVersion": osr.get("VERSION_ID", ""),
        "osBuild": build,
        "kernel": read("/proc/sys/kernel/osrelease"),
        "computer": join_present([read("/sys/class/dmi/id/sys_vendor"), read("/sys/class/dmi/id/product_name")]),
        "cpu": re.sub("\\s+", cpu[1], " ") if cpu != None else "",
        "cpuCores": cpu_count(),
        "gpu": gpu,
        "memoryGB": round1(Float(Int(mem[1])) / 1024.0 / 1024.0) if mem != None else 0,
        "diskFreeGB": round1(Float(disk_free("/")) / 1.0e9),
        "session": join_present([env.get("XDG_CURRENT_DESKTOP", ""), env.get("XDG_SESSION_TYPE", "")]),
        "language": env.get("LANG", ""),
        "uptimeMin": up,
        "packages": pkgs,
        "userErrors": log_lines(command(["journalctl", "--user", "-b", "-p", "err", "-n", "50", "--no-pager", "-o", "short"], 10), ctx, 50),
        "systemErrors": log_lines(command(["journalctl", "-b", "-p", "err", "-n", "50", "--no-pager", "-o", "short"], 10), ctx, 50),
        "xsessionErrors": log_lines(read(home() + "/.xsession-errors"), ctx, 50)}
    # Systemovy zurnal muze obsahovat i radky uzivatelskeho - neposilat je dvakrat
    seen = {}
    for line in info["userErrors"]:
        seen[line] = True
    end
    system = []
    for line in info["systemErrors"]:
        if not (line in seen):
            system.append(line)
        end
    end
    info["systemErrors"] = system
    # Limit velikosti: nejdriv zkratit logy
    while byte_length(json.encode(info)) > SYSTEM_MAX:
        longest = "userErrors"
        for key in ["systemErrors", "xsessionErrors"]:
            if len(info[key]) > len(info[longest]):
                longest = key
            end
        end
        items = info[longest]
        if len(items) == 0:
            break
        end
        info[longest] = items[len(items) // 2 + 1:]
    end
    return info
end

function app_version():
    out = command([ENGINE, "-Q", "luxos-desktop"], 8)
    space = out.find(" ")
    return out[space + 1:] if space >= 0 else ""
end

# JSON s odsazenim 2 jako json.dumps(indent=2, ensure_ascii=False)
function pretty(value):
    return pretty_at(value, "")
end

function pretty_at(value, indent):
    inner = indent + "  "
    if type(value) == "Dictionary":
        if len(value) == 0:
            return "{}"
        end
        parts = []
        for key in value:
            parts.append(inner + json.encode(key) + ": " + pretty_at(value[key], inner))
        end
        return "{\n" + ",\n".join(parts) + "\n" + indent + "}"
    elif type(value) == "List":
        if len(value) == 0:
            return "[]"
        end
        parts = []
        for item in value:
            parts.append(inner + pretty_at(item, inner))
        end
        return "[\n" + ",\n".join(parts) + "\n" + indent + "]"
    end
    return json.encode(value)
end

# ---- ucet a odeslani ------------------------------------------------------------------------------------------

function config_dir():
    base = env.get("XDG_CONFIG_HOME", "")
    if base == "":
        base = home() + "/.config"
    end
    return base
end

# Ulozeny ucet LuxAI (slovnik se sessionToken) nebo None
function load_account():
    raw = glib.read_text(config_dir() + "/luxai/account.json")
    data = None
    safe:
        data = json.decode(raw)
    end
    if data == None or type(data) != "Dictionary":
        return None
    end
    token = data.get("sessionToken", "")
    if type(token) != "String" or token == "":
        return None
    end
    return data
end

function account_email():
    account = load_account()
    if account == None:
        return ""
    end
    user = account.get("user", None)
    if user == None or type(user) != "Dictionary":
        return ""
    end
    email = user.get("email", "")
    return email if type(email) == "String" else ""
end

# LUXAI_ORIGIN: https kamkoli, http jen na tento pocitac (session cookie nesmi jit nesifrovane po siti)
function default_origin():
    return origin_from(env.get("LUXAI_ORIGIN", ""))
end

function origin_from(value):
    m = re.search("^(https?)://(\\[[^]]*\\]|[^/:?#]+)", value, False)
    if m != None:
        host = m[2].replace("[", "").replace("]", "")
        if m[1] == "https" or host == "127.0.0.1" or host == "localhost" or host == "::1":
            while value.endswith("/"):
                value = value[:len(value) - 1]
            end
            return value
        end
    end
    return DEFAULT_ORIGIN
end

# Jeden pozadavek: {"data": slovnik} nebo {"error": kod, "status": HTTP}
function request(payload, token, origin):
    headers = {"X-Lux-Client": "luxos", "Accept": "application/json", "Content-Type": "application/json"}
    if token != "":
        headers["Cookie"] = COOKIE + "=" + token
    end
    body = json.encode(payload)
    for attempt in range(NET_RETRIES):
        r = None
        safe:
            r = http.post(origin + ENDPOINT, body, headers, 45)
        end
        if r == None:
            return {"error": "network", "status": 0}
        end
        status = Int(r["status"])
        text = String(r["text"])
        if status == 0:
            # spojeni vubec nevzniklo (DNS jeste nebezi po pripojeni k Wi-Fi, odmitnute spojeni): pozadavek server
            # nedostal, opakovani je bezpecne i u POST
            if text.find("(6)") >= 0 or text.find("(7)") >= 0:
                if attempt + 1 < NET_RETRIES:
                    call time.sleep(1.5 * (attempt + 1))
                    continue
                end
                return {"error": "network", "status": 0}
            end
            if text.find("(60)") >= 0 and text.lower().find("not yet valid") >= 0:
                return {"error": "clock", "status": 0}
            end
            return {"error": "network", "status": 0}
        end
        data = None
        safe:
            data = json.decode(text if text.strip() != "" else "{}")
        end
        if status >= 200 and status < 300:
            if data == None or type(data) != "Dictionary":
                return {"error": "http", "status": status}
            end
            return {"data": data}
        end
        code = "http"
        if data != None and type(data) == "Dictionary" and type(data.get("error", None)) == "String" and data["error"] != "":
            code = data["error"]
        end
        return {"error": code, "status": status}
    end
    return {"error": "network", "status": 0}
end

# Odesle hlaseni; pri vypadku site / chybe serveru zkusi jeste jednou
function send(payload):
    account = load_account()
    token = ""
    origin = default_origin()
    if account != None:
        token = account["sessionToken"]
        if type(account.get("origin", None)) == "String":
            origin = account["origin"]
        end
    end
    for attempt in [1, 2]:
        r = request(payload, token, origin)
        if r.get("data", None) != None:
            rid = r["data"].get("id", "")
            return {"id": rid if type(rid) == "String" else String(rid)}
        end
        retry = r["error"] == "network" or r["status"] >= 500
        if attempt == 2 or not retry:
            return r
        end
        call time.sleep(2)
    end
end

function outbox():
    base = env.get("XDG_DATA_HOME", "")
    if base == "":
        base = home() + "/.local/share"
    end
    return base + "/luxos/feedback-outbox"
end

function hex8():
    value = random.getrandbits(32)
    digits = "0123456789abcdef"
    out = ""
    for i in range(8):
        out = digits[value & 15] + out
        value = value >> 4
    end
    return out
end

# Novy soubor jen pro uzivatele (O_EXCL, 0600); False pri chybe
function write_new(path, text):
    unsafe:
        # O_WRONLY 1 | O_CREAT 64 | O_EXCL 128 | O_CLOEXEC 524288
        fd = __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("open"), cstr(path), 1 + 64 + 128 + 524288, 384))
        if fd < 0:
            return False
        end
        size = __lsl_text_byte_length(text)
        done = 0
        while done < size:
            n = __lsl_qbe_call3(__lsl_symbol("write"), fd, cstr(text) + done, size - done)
            if n <= 0:
                call __lsl_qbe_call1(__lsl_symbol("close"), fd)
                return False
            end
            done += n
        end
        return __lsl_qbe_call1(__lsl_symbol("close"), fd) == 0
    end
end

function make_outbox():
    dir = outbox()
    call sys.mkdir_p(dir[:txt.rfind(dir, "/")])
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("mkdir"), cstr(dir), 448)
    end
    return dir
end

# Ulozi hlaseni do fronty; cesta, nebo "" pri chybe
function save_outbox(payload):
    path = make_outbox() + "/" + sys.strftime_local("%Y%m%d-%H%M%S-") + hex8() + ".json"
    if write_new(path, json.encode(payload)):
        return path
    end
    return ""
end

# Odesle ulozena hlaseni; vraci pocet odeslanych. Pri vypadku site skonci.
function flush_outbox():
    names = []
    for name in glib.list_dir(outbox()):
        if name.endswith(".json"):
            names.append(name)
        end
    end
    sent = 0
    for name in sorted(names):
        path = outbox() + "/" + name
        payload = None
        safe:
            payload = json.decode(readfile(path))
        end
        if payload == None or type(payload) != "Dictionary":
            call glib.rename(path, path + ".bad")
            continue
        end
        r = send(payload)
        if r.get("error", None) != None:
            # 401/403: prihlaseni vyprselo - hlaseni pockat na nove prihlaseni, nezahazovat
            status = r["status"]
            if r["error"] == "network" or status >= 500 or status == 401 or status == 403 or status == 429:
                break
            end
            # server ho odmitl - neposilat porad dokola
            call glib.rename(path, path + ".rejected")
            continue
        end
        call glib.unlink(path)
        sent += 1
    end
    return sent
end
