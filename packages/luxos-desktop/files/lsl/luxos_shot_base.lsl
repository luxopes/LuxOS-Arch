# LuxOS Snimek obrazovky - cista logika bez GTK (sdili ji maly klient luxos-screenshot, modul luxos_shot
# v luxos-hub i samostatny program a testy): volby, nazvy souboru, vyrez, prepinace, zkratky Xfce, ffmpeg
# a protokol klient -> hub.
#
#   parse_args(argv)                 {"action", "stop", "clipboard", "no_thumb", "output", "region", "close", "help"}
#                                    nebo {"error": text}
#   load_options(path), save_options(opts, path)   ~/.config/luxos/screenshot.json (verze 2)
#   file_name(cas, video), unique_path(slozka, jmeno), clamp_rect, parse_region
#   pretty_accel, global_shortcut(prikaz, soubory), pick_encoder, ffmpeg_cmd
#   request_text(argv) / request_args(text)        zprava pro hub (radky, konec prazdnym radkem)
load env, json
load luxos_i18n as i18n
load luxos_text as text
load luxos_sys

MODES = ["screen", "window", "portion", "rec_screen", "rec_portion"]
# "screenshots" = Obrazky/Snimky obrazovky (nazev slozky podle jazyka), vytvori se az pri ulozeni
SAVE_TO = ["screenshots", "desktop", "pictures", "clipboard", "other"]
TIMERS = [0, 5, 10]
OPTION_KEYS = ["save_to", "other_dir", "timer", "pointer", "remember", "selection", "mode"]
# Verze souboru voleb: do 0.9.10 (bez klice "version") byla vychozi Plocha a ukladala se
# i bez vyberu uzivatele, takze "desktop" ze starsiho souboru se prevede na novou vychozi slozku
OPTIONS_VERSION = 2
HIDE_DELAY = 180        # ms: cas na prekresleni obrazovky po skryti listy
THUMB_TIME = 5000       # ms: jak dlouho je videt nahled po ulozeni
PROTOCOL = "luxos-screenshot 1"

HELP = ("LuxOS Screenshot - floating toolbar like in macOS (Shift+Super+5, Print).\n\n"
    + "  luxos-screenshot                 toolbar: capture screen / window / portion, recording, options\n"
    + "  luxos-screenshot --screen        capture the entire screen now (Shift+Super+3)\n"
    + "  luxos-screenshot --portion       drag to select a portion (Shift+Super+4; Space = window)\n"
    + "  luxos-screenshot --window        click a window\n"
    + "  luxos-screenshot --record-screen / --record-portion   screen recording (ffmpeg x11grab -> mp4)\n"
    + "  luxos-screenshot --stop          stop recording (running the tool again also stops it)\n"
    + "  --clipboard   copy instead of saving a file      --output DIR   folder for the file\n"
    + "  --region X,Y,W,H   portion without mouse selection   --no-thumbnail  no preview after saving\n"
    + "  --close       close the open toolbar, selection or preview\n\n"
    + "Options are stored in ~/.config/luxos/screenshot.json.")

function defaults():
    return {"save_to": "screenshots", "other_dir": "", "timer": 0, "pointer": False, "remember": True, "selection": None, "mode": "portion"}
end

function config_home():
    base = env.get("XDG_CONFIG_HOME", "")
    if base == None or base == "":
        base = env.get("HOME", "") + "/.config"
    end
    return base
end

function options_path():
    return config_home() + "/luxos/screenshot.json"
end

function runtime_dir():
    value = env.get("XDG_RUNTIME_DIR", "")
    if value == None or value == "":
        return "/tmp"
    end
    return value
end

# Jmeno abstraktniho socketu UNIX (bez souboru; pristup jen pro stejneho uzivatele overuje SO_PEERCRED)
function socket_name():
    return runtime_dir() + "/luxos-screenshot"
end

# ---- volby ---------------------------------------------------------------------------------------------

function is_int(value):
    return type(value) == "Int"
end

function is_bool(value):
    return type(value) == "Bool"
end

# Volby ze souboru; neplatne nebo chybejici hodnoty nahradi vychozimi
function load_options(path):
    opts = defaults()
    raw = ""
    safe:
        raw = readfile(path)
    end
    if raw == "":
        return opts
    end
    data = None
    try:
        data = json.decode(raw)
    else:
        data = None
    end
    if data == None or type(data) != "Dictionary":
        return opts
    end
    value = data.get("save_to", None)
    if type(value) == "String" and value in SAVE_TO:
        opts["save_to"] = value
    end
    version = data.get("version", None)
    if opts["save_to"] == "desktop" and not (is_int(version) and version == OPTIONS_VERSION):
        opts["save_to"] = "screenshots"
    end
    value = data.get("other_dir", None)
    if type(value) == "String":
        opts["other_dir"] = value
    end
    value = data.get("timer", None)
    if is_int(value) and value in TIMERS:
        opts["timer"] = value
    end
    for key in ["pointer", "remember"]:
        value = data.get(key, None)
        if is_bool(value):
            opts[key] = value
        end
    end
    value = data.get("mode", None)
    if type(value) == "String" and value in MODES:
        opts["mode"] = value
    end
    sel = data.get("selection", None)
    if type(sel) == "List" and len(sel) == 4:
        ok = True
        for v in sel:
            if not is_int(v):
                ok = False
            end
        end
        if ok and sel[2] > 0 and sel[3] > 0:
            opts["selection"] = [sel[0], sel[1], sel[2], sel[3]]
        end
    end
    if opts["save_to"] == "other" and opts["other_dir"] == "":
        opts["save_to"] = "screenshots"
    end
    return opts
end

function json_value(value):
    if value == None:
        return "null"
    end
    if type(value) == "List":
        parts = []
        for v in value:
            parts.append(json_value(v))
        end
        return "[\n  " + text.join(parts, ",\n  ") + "\n ]"
    end
    return json.encode(value)
end

# Stejny tvar jako json.dump(indent=1) v drivejsi verzi v Pythonu
function options_text(opts):
    base = defaults()
    lines = []
    for key in OPTION_KEYS:
        value = base[key]
        if key in opts:
            value = opts[key]
        end
        lines.append(" " + json.encode(key) + ": " + json_value(value))
    end
    lines.append(" \"version\": " + String(OPTIONS_VERSION))
    return "{\n" + text.join(lines, ",\n") + "\n}"
end

function dirname(path):
    hit = text.rfind(path, "/")
    if hit < 0:
        return ""
    end
    if hit == 0:
        return "/"
    end
    return path[0:hit]
end

function basename(path):
    return path[text.rfind(path, "/") + 1:]
end

function save_options(opts, path):
    ok = False
    safe:
        call luxos_sys.mkdir_p(dirname(path))
        tmp = path + ".tmp"
        call writefile(tmp, options_text(opts))
        ok = luxos_sys.rename(tmp, path)
    end
    return ok
end

# ---- nazvy souboru ----------------------------------------------------------------------------------------

function pad2(n):
    return text.pad(n, 2)
end

# Sablona prekladu s presne dvema %s (jinak poskozeny preklad -> None)
function fill_two(template, a, b):
    count = 0
    index = 0
    while index < len(template):
        if template[index] == "%":
            if index + 1 >= len(template):
                return None
            end
            code = template[index + 1]
            if code == "s":
                count += 1
            elif code != "%":
                return None
            end
            index += 2
            continue
        end
        index += 1
    end
    if count != 2:
        return None
    end
    return i18n.format(template, [a, b])
end

# 'Screenshot 2026-10-22 at 11.12.03.png' (slova podle jazyka, tecky v case jako v macOS);
# when = [rok, mesic, den, hodina, minuta, sekunda]
function file_name(when, video):
    date = String(when[0]) + "-" + pad2(when[1]) + "-" + pad2(when[2])
    clock = pad2(when[3]) + "." + pad2(when[4]) + "." + pad2(when[5])
    english = "Screenshot %s at %s"
    ext = ".png"
    if video:
        english = "Screen Recording %s at %s"
        ext = ".mp4"
    end
    name = fill_two(i18n.T(english), date, clock)
    if name == None:
        name = i18n.format(english, [date, clock])
    end
    return name.replace("/", "-") + ext
end

# [zaklad, pripona] jako os.path.splitext (tecky na zacatku jmena nejsou pripona)
function splitext(name):
    base = basename(name)
    start = len(name) - len(base)
    lead = 0
    while lead < len(base) and base[lead] == ".":
        lead += 1
    end
    hit = text.rfind(base, ".")
    if hit <= lead - 1 or hit < lead:
        return [name, ""]
    end
    return [name[0:start + hit], name[start + hit:]]
end

function join_path(folder, name):
    if folder.endswith("/"):
        return folder + name
    end
    return folder + "/" + name
end

# Cesta v adresari, ktera jeste neexistuje: 'X.png', 'X (2).png', ...
function unique_path(folder, name):
    parts = splitext(name)
    path = join_path(folder, name)
    n = 2
    while luxos_sys.lexists(path):
        path = join_path(folder, parts[0] + " (" + String(n) + ")" + parts[1])
        n += 1
    end
    return path
end

# ---- geometrie ---------------------------------------------------------------------------------------------

function round_int(value):
    if type(value) == "Int":
        return value
    end
    return Int(round(value))
end

# Obdelnik oriznuty na obrazovku [x, y, w, h] nebo None, kdyz z nej nic nezbude
function clamp_rect(rect, width, height):
    x = round_int(rect[0])
    y = round_int(rect[1])
    w = round_int(rect[2])
    h = round_int(rect[3])
    if w < 0:
        x = x + w
        w = -w
    end
    if h < 0:
        y = y + h
        h = -h
    end
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(width, x + w)
    y1 = min(height, y + h)
    if x1 - x0 < 1 or y1 - y0 < 1:
        return None
    end
    return [x0, y0, x1 - x0, y1 - y0]
end

# "X,Y,W,H" (mezery kolem cisel povolene, W a H kladne) -> [x, y, w, h] nebo None
function parse_region(value):
    if value == None:
        return None
    end
    parts = value.split(",")
    if len(parts) != 4:
        return None
    end
    out = []
    index = 0
    for part in parts:
        p = part.strip()
        digits = p
        if index < 2 and p.startswith("-"):
            digits = p[1:]
        end
        if not text.is_digits(digits):
            return None
        end
        out.append(Int(p))
        index += 1
    end
    if out[2] < 1 or out[3] < 1:
        return None
    end
    return out
end

# ---- klavesove zkratky Xfce (napoveda v liste) --------------------------------------------------------------

MOD_NAMES = [["Super", ["super", "mod4", "meta", "hyper"]], ["Ctrl", ["primary", "control", "ctrl"]], ["Alt", ["alt", "mod1"]], ["Shift", ["shift"]]]

function is_word_char(ch):
    code = ord(ch)
    return (code >= 48 and code <= 57) or (code >= 65 and code <= 90) or (code >= 97 and code <= 122) or code == 95 or code > 127
end

# '<Super><Shift>4' -> 'Super+Shift+4' (poradi jako v dokumentaci LuxOS); None bez klavesy
function pretty_accel(accel):
    if accel == None:
        return None
    end
    mods = []
    key = ""
    index = 0
    while index < len(accel):
        ch = accel[index]
        if ch == "<":
            stop = text.find_from(accel, ">", index + 1)
            if stop > index + 1:
                word = accel[index + 1:stop]
                ok = True
                for c in word:
                    if not is_word_char(c):
                        ok = False
                    end
                end
                if ok:
                    mods.append(word.lower())
                    index = stop + 1
                    continue
                end
            end
        end
        key = key + ch
        index += 1
    end
    if key == "":
        return None
    end
    parts = []
    for pair in MOD_NAMES:
        for alias in pair[1]:
            if alias in mods:
                parts.append(pair[0])
                break
            end
        end
    end
    if len(key) == 1:
        key = key.upper()
    end
    parts.append(key)
    return text.join(parts, "+")
end

SHORTCUTS_XML = "xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml"

# Uzivatelske nastaveni zkratek Xfce, pak vychozi (XDG_CONFIG_DIRS, v LuxOS /etc/xdg/luxos)
function shortcut_files():
    dirs = [config_home()]
    extra = env.get("XDG_CONFIG_DIRS", "")
    if extra == None or extra == "":
        extra = "/etc/xdg"
    end
    for d in extra.split(":"):
        dirs.append(d)
    end
    out = []
    for d in dirs:
        if d != "":
            out.append(d + "/" + SHORTCUTS_XML)
        end
    end
    return out
end

function xml_unescape(value):
    return value.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", "\"").replace("&apos;", "'").replace("&amp;", "&")
end

# Hodnota atributu ve znacce (<property name="x" value="y"/>), None kdyz chybi
function xml_attr(tag, name):
    for quote in ["\"", "'"]:
        needle = " " + name + "=" + quote
        hit = tag.find(needle)
        if hit >= 0:
            start = hit + len(needle)
            stop = text.find_from(tag, quote, start)
            if stop < 0:
                return None
            end
            return xml_unescape(tag[start:stop])
        end
    end
    return None
end

# [nalezena sekce commands/custom, zkratka nebo None] z obsahu souboru xfconf
# (jeden pruchod po znackach pres split: indexovani v dlouhem textu je v LSL drahe)
function shortcut_in(content, command):
    stack = []
    depth = 0
    found = False
    pieces = content.split("<")
    index = 1
    while index < len(pieces):
        piece = pieces[index]
        index += 1
        stop = piece.find(">")
        if stop < 0:
            break
        end
        tag = "<" + piece[0:stop + 1]
        if tag.startswith("<?") or tag.startswith("<!"):
            continue
        end
        closing = tag.startswith("</")
        self_closing = tag.endswith("/>")
        name = tag[1:]
        if closing:
            name = tag[2:]
        end
        cut = 0
        while cut < len(name) and is_word_char(name[cut]):
            cut += 1
        end
        name = name[0:cut]
        if closing:
            if name == "channel":
                depth -= 1
            elif name == "property" and len(stack) > 0:
                call stack.pop()
            end
            continue
        end
        if name == "channel":
            if not self_closing:
                depth += 1
            end
            continue
        end
        if name != "property" or depth != 1:
            continue
        end
        pname = xml_attr(tag, "name")
        if pname == None:
            pname = ""
        end
        if len(stack) == 2 and stack[0] == "commands" and stack[1] == "custom":
            value = xml_attr(tag, "value")
            if value == None:
                value = ""
            end
            if pname != "override" and value.strip() == command:
                return [True, pretty_accel(pname)]
            end
        end
        if len(stack) == 1 and stack[0] == "commands" and pname == "custom":
            found = True
        end
        if not self_closing:
            stack.append(pname)
        end
    end
    return [found, None]
end

# Prvni zkratka pro prikaz ze zkratek Xfce ('Super+Shift+3') nebo None.
# Plati prvni soubor, ktery ma vlastni zkratky (commands/custom) - uzivatelsky prebiji vychozi.
function global_shortcut(command, files):
    if files == None:
        files = shortcut_files()
    end
    for path in files:
        content = ""
        safe:
            content = readfile(path)
        end
        if content == "":
            continue
        end
        result = shortcut_in(content, command)
        if result[0]:
            return result[1]
        end
    end
    return None
end

# ---- nahravani (ffmpeg) ------------------------------------------------------------------------------------

function encoders():
    return [["libx264", ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]],
            ["libopenh264", ["-c:v", "libopenh264", "-b:v", "8M", "-pix_fmt", "yuv420p"]],
            ["mpeg4", ["-c:v", "mpeg4", "-q:v", "3", "-pix_fmt", "yuv420p"]]]
end

# Slova radku oddelena bilymi znaky
function words(line):
    out = []
    current = ""
    for ch in line:
        if ch == " " or ch == "\t" or ch == "\r":
            if current != "":
                out.append(current)
                current = ""
            end
        else:
            current = current + ch
        end
    end
    if current != "":
        out.append(current)
    end
    return out
end

# Argumenty kodeku podle vypisu 'ffmpeg -encoders' (prvni dostupny H.264, zaloha mpeg4) nebo None
function pick_encoder(listing):
    if listing == None:
        return None
    end
    lines = listing.split("\n")
    for pair in encoders():
        for line in lines:
            w = words(line)
            if len(w) >= 3 and w[0].startswith("V") and w[1] == pair[0]:
                return pair[1].copy()
            end
        end
    end
    return None
end

# Prikaz ffmpeg pro nahravani obdelniku obrazovky (sude rozmery kvuli yuv420p)
function ffmpeg_cmd(display, rect, out, enc, fps, pointer):
    w = max(2, rect[2] - rect[2] % 2)
    h = max(2, rect[3] - rect[3] % 2)
    mouse = "0"
    if pointer:
        mouse = "1"
    end
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-f", "x11grab", "-framerate", String(fps),
           "-video_size", String(w) + "x" + String(h), "-draw_mouse", mouse, "-i", display + "+" + String(rect[0]) + "," + String(rect[1])]
    cmd.extend(enc)
    cmd.extend(["-movflags", "+faststart", "-f", "mp4", "-y", out])
    return cmd
end

# ---- prepinace ---------------------------------------------------------------------------------------------

function normpath(path):
    parts = []
    for part in path.split("/"):
        if part == "" or part == ".":
            continue
        end
        if part == "..":
            if len(parts) > 0:
                call parts.pop()
            end
            continue
        end
        parts.append(part)
    end
    return "/" + text.join(parts, "/")
end

# os.path.abspath(os.path.expanduser(path)) vuci adresari cwd_path
function abspath(path, cwd_path):
    if path == "~" or path.startswith("~/"):
        path = env.get("HOME", "") + path[1:]
    end
    if not path.startswith("/"):
        path = cwd_path + "/" + path
    end
    return normpath(path)
end

FLAGS = {"--screen": "screen", "--portion": "portion", "--selection": "portion", "--window": "window", "--record-screen": "rec_screen", "--record-portion": "rec_portion", "--toolbar": "toolbar"}

# Prepinace prikazove radky (bez argv[0]); vystupni slozka uz jako absolutni cesta
function parse_args(argv, cwd_path):
    a = {"action": "toolbar", "stop": False, "clipboard": False, "no_thumb": False, "output": "", "region": None, "close": False, "help": False}
    index = 0
    while index < len(argv):
        item = argv[index]
        index += 1
        if item in FLAGS:
            a["action"] = FLAGS[item]
        elif item == "--stop":
            a["stop"] = True
        elif item == "--close":
            a["close"] = True
        elif item == "--clipboard":
            a["clipboard"] = True
        elif item == "--no-thumbnail":
            a["no_thumb"] = True
        elif item == "--output":
            value = "."
            if index < len(argv):
                value = argv[index]
                index += 1
            end
            a["output"] = abspath(value, cwd_path)
        elif item == "--region":
            value = ""
            if index < len(argv):
                value = argv[index]
                index += 1
            end
            a["region"] = parse_region(value)
            if a["region"] == None:
                return {"error": "luxos-screenshot: --region X,Y,W,H"}
            end
        elif item == "-h" or item == "--help":
            a["help"] = True
        else:
            return {"error": "luxos-screenshot: unknown option " + item}
        end
    end
    return a
end

# Normalizovane prepinace pro predani hubu (vystupni slozka uz absolutni)
function canonical_args(a):
    out = []
    for flag in ["--screen", "--portion", "--window", "--record-screen", "--record-portion"]:
        if FLAGS[flag] == a["action"]:
            out.append(flag)
        end
    end
    if a["stop"]:
        out.append("--stop")
    end
    if a["close"]:
        out.append("--close")
    end
    if a["clipboard"]:
        out.append("--clipboard")
    end
    if a["no_thumb"]:
        out.append("--no-thumbnail")
    end
    if a["output"] != "":
        out.append("--output")
        out.append(a["output"])
    end
    if a["region"] != None:
        r = a["region"]
        out.append("--region")
        out.append(String(r[0]) + "," + String(r[1]) + "," + String(r[2]) + "," + String(r[3]))
    end
    return out
end

# ---- protokol klient -> hub ---------------------------------------------------------------------------------
# Klient posle "luxos-screenshot 1\n", prepinace po radcich a prazdny radek. Hub odpovi "ok\n" (az pak
# zacne jednat; kdyz klient mezitim odesel, pozadavek zahodi), pak "out CESTA\n" pro kazdy ulozeny soubor
# a nakonec "exit KOD\n".

function request_text(argv):
    out = PROTOCOL + "\n"
    for item in argv:
        out = out + item.replace("\n", " ") + "\n"
    end
    return out + "\n"
end

# Prepinace ze zpravy, None kdyz zprava neni cela nebo neni nase
function request_args(message):
    if not message.endswith("\n\n"):
        return None
    end
    lines = message[0:len(message) - 2].split("\n")
    if len(lines) == 0 or lines[0] != PROTOCOL:
        return None
    end
    return lines[1:]
end

# Klient: preda prepinace bezicimu hubu (nebo samostatnemu procesu), vypise ulozene cesty a vrati kod
# ukonceni; -1 = nikdo neposloucha, -2 = server neodpovedel do ack_ms (pozadavek zahodi)
function client_run(argv, ack_ms):
    fd = luxos_sys.unix_connect(socket_name())
    if fd < 0:
        return -1
    end
    if not luxos_sys.send_text(fd, request_text(argv)):
        call luxos_sys.close(fd)
        return -1
    end
    buf = ""
    acked = False
    while True:
        wait = -1
        if not acked:
            wait = ack_ms
        end
        if not luxos_sys.wait_readable(fd, wait):
            if not acked:
                call luxos_sys.close(fd)
                return -2
            end
            continue
        end
        r = luxos_sys.recv_text(fd)
        if r[0] == 0:
            call luxos_sys.close(fd)
            if acked:
                return 1
            end
            return -2
        end
        if r[0] < 0:
            continue
        end
        buf = buf + r[1]
        while buf.find("\n") >= 0:
            pair = text.partition(buf, "\n")
            line = pair[0]
            buf = pair[1]
            if line == "ok":
                acked = True
            elif line.startswith("out "):
                call luxos_sys.out(line[4:] + "\n")
            elif line.startswith("err "):
                call eprint(line[4:])
            elif line.startswith("exit "):
                call luxos_sys.close(fd)
                return text.to_int(line[5:], 1)
            end
        end
    end
    return 1
end
