# LuxOS Emoji a symboly - cista logika bez GTK (sdili ji maly klient luxos-emoji, modul luxos_emoji
# v luxos-hub, samostatny proces luxos-emoji-ui, generator dat luxos-emoji-data a testy):
#
#   fold(text)                       mala pismena bez diakritiky (latinka i cyrilice): "Úsměv" -> "usmev"
#   load_data(dir, jazyk)            data z /usr/share/luxos/emoji (emoji.tsv + <jazyk>.tsv + en.tsv)
#   search(data, dotaz, limit, boost) indexy emoji podle shody: presny nazev > zacatek nazvu > slovo nazvu >
#                                    presne klicove slovo > zacatek klicoveho slova > podretezec
#   with_tone(data, index, ton)      emoji v odstinu pleti (0 = vychozi zluty, 1-5 = svetly..tmavy)
#   load_config / save_config        ~/.config/luxos/emoji.conf: ton a naposledy pouzite
#   add_recent(seznam, emoji)        naposledy pouzite (nejnovejsi prvni, nejvys RECENT_MAX)
#   parse_args(argv), request_text, request_args, client_run   prepinace a protokol klient -> hub
#
# Format dat (generuje luxos-emoji-data pri sestaveni baliku z emoji-test.txt a anotaci CLDR):
#   emoji.tsv     emoji<TAB>skupina<TAB>odstiny   (poradi CLDR; skupina 0-8 viz GROUPS, -1 = modifikator
#                                                 odstinu; odstiny = 5 variant oddelenych mezerou nebo "")
#   <jazyk>.tsv   emoji<TAB>nazev<TAB>(rezerva)<TAB>|nazev|slovo|slovo|  (posledni sloupec
#                                                 uz po fold(), hleda se v nem primo)
load env
load luxos_sys
load luxos_text as text

PROTOCOL = "luxos-emoji 1"
DATA_DIR = "/usr/share/luxos/emoji"
DATA_VERSION = "luxos-emoji-data 1"
COLUMNS = 9
# Body navic pro naposledy/casto pouzivane (stupne shody jsou po 20 bodech)
BOOST = 25
RECENT_MAX = 27
# Skupiny v poradi zalozek (Aktivity pred Cestovanim jako v macOS); nazvy skupin z emoji-test.txt
GROUPS = ["Smileys", "People", "Animals & Nature", "Food & Drink", "Activities", "Travel & Places", "Objects", "Symbols", "Flags"]
TEST_GROUPS = ["Smileys & Emotion", "People & Body", "Animals & Nature", "Food & Drink", "Activities", "Travel & Places", "Objects", "Symbols", "Flags"]
# Ikony zalozek (Naposledy pouzite a skupiny)
TAB_ICONS = ["🕘", "😀", "👋", "🐻", "🍔", "⚽", "🚗", "💡", "🔣", "🏁"]
TONE_MODIFIERS = ["🏻", "🏼", "🏽", "🏾", "🏿"]
# Prvni spusteni bez historie: casto pouzivane
DEFAULT_RECENT = ["😀", "😂", "❤️", "👍", "🙏", "😊", "🎉", "😍", "🔥", "😢", "😉", "🤔", "👏", "💪", "✅", "😎", "🥰", "😅"]

HELP = ("LuxOS Emoji & Symbols - emoji picker (Super+. or Ctrl+Super+Space).\n\n"
    + "  luxos-emoji                 open the picker (again: close it)\n"
    + "  luxos-emoji --search TEXT   open the picker with a search\n"
    + "  luxos-emoji --close         close the picker\n\n"
    + "Type to search by name or keyword (in your language and in English), arrows to move,\n"
    + "Enter or click inserts the emoji into the app you were typing in, Shift+Enter inserts and\n"
    + "keeps the picker open, Tab switches categories, Esc closes.\n"
    + "The skin tone and recently used emoji are stored in ~/.config/luxos/emoji.conf.")

# ---- skladani bez diakritiky ----------------------------------------------------------------------------------

FOLD = {}

function fold_table():
    groups = [["a", "àáâãäåāăąǎ"], ["c", "çćĉċč"], ["d", "ďđ"], ["e", "èéêëēĕėęěẽ"], ["g", "ĝğġģ"], ["h", "ĥħ"],
              ["i", "ìíîïĩīĭįı"], ["j", "ĵ"], ["k", "ķ"], ["l", "ĺļľŀł"], ["n", "ñńņňŉ"], ["o", "òóôõöøōŏőǒ"],
              ["r", "ŕŗř"], ["s", "śŝşšș"], ["t", "ţťŧț"], ["u", "ùúûüũūŭůűųǔ"], ["w", "ŵ"], ["y", "ýÿŷ"],
              ["z", "źżž"], ["ss", "ß"], ["ae", "æ"], ["oe", "œ"], ["'", "’‘`´"], ["\"", "“”„"], ["-", "–—"],
              # cyrilice: e/je/i bez dvojtecky a breve jako u latinky
              ["е", "ё"], ["и", "й"], ["і", "ї"], ["г", "ґ"]]
    for pair in groups:
        for ch in pair[1]:
            FOLD[ch] = pair[0]
        end
    end
    return 0
end

# Mala pismena bez diakritiky; velka pismena latinky resi lower(), cyrilice se prevadi zde
function fold(value):
    if len(FOLD) == 0:
        call fold_table()
    end
    low = value.lower()
    out = ""
    for ch in low:
        code = ord(ch)
        if code < 128:
            out = out + ch
            continue
        end
        if code >= 1040 and code <= 1071:          # А-Я
            ch = chr(code + 32)
        elif code >= 1024 and code <= 1039:        # Ѐ-Џ
            ch = chr(code + 80)
        elif code == 1168:                         # Ґ
            ch = chr(1169)
        end
        mapped = FOLD.get(ch, None)
        if mapped != None:
            out = out + mapped
        else:
            out = out + ch
        end
    end
    return out
end

# Prvni pismeno velke (nazvy CLDR jsou malymi pismeny; "vlajka: Česko" zustane, jen "V")
function cap_first(value):
    if value == "":
        return value
    end
    first = value[0]
    code = ord(first)
    if code >= 1072 and code <= 1103:
        first = chr(code - 32)
    elif code >= 1104 and code <= 1119:
        first = chr(code - 80)
    else:
        first = first.upper()
    end
    return first + value[1:]
end

# Slova dotazu po fold(), bez prazdnych
function query_words(query):
    out = []
    for w in fold(query).replace("\t", " ").split(" "):
        if w != "":
            out.append(w)
        end
    end
    return out
end

# ---- data -------------------------------------------------------------------------------------------------------

function data_dir():
    d = env.get("LUXOS_EMOJI_DATA", "")
    if d == None or d == "":
        return DATA_DIR
    end
    return d
end

# Jazyk pro nazvy a hledani: LC_ALL / LC_MESSAGES / LANG (cs_CZ.UTF-8 -> cs, pt_BR -> pt)
function lang():
    for name in ["LC_ALL", "LC_MESSAGES", "LANG"]:
        value = env.get(name, "")
        if value != None and value != "" and value != "C" and value != "POSIX":
            for sep in ["_", ".", "@"]:
                cut = value.find(sep)
                if cut >= 0:
                    value = value[0:cut]
                end
            end
            return value.lower()
        end
    end
    return "en"
end

function read_text(path):
    content = ""
    if exists(path):
        safe:
            content = readfile(path)
        end
    end
    return content
end

# {emoji: [nazev, klicova slova, nazev po fold, |slova po fold|]} z <jazyk>.tsv
function load_names(path):
    names = {}
    for line in read_text(path).split("\n"):
        if line == "" or line.startswith("# "):            # "#️⃣" je emoji, ne komentar
            continue
        end
        f = line.split("\t")
        if len(f) < 4:
            continue
        end
        hay = f[3]
        cut = hay.find("|", 1)
        if cut < 0:
            continue
        end
        names[f[0]] = [f[1], f[2], hay[1:cut], hay[cut:]]
    end
    return names
end

# Data pro vyber a hledani; jazyk "en" jen anglicky. Vraci slovnik se seznamy po indexech emoji:
#   emoji, group, tones (seznam 5 variant nebo []), name (v jazyce, jinak anglicky), name_en,
#   loc_name/loc_kw (po fold, "" bez prekladu), en_name/en_kw, index {emoji: index}, groups [[indexy]...],
#   tone_names (nazvy 5 odstinu v jazyce)
function load_data(directory, language):
    data = {"emoji": [], "group": [], "tones": [], "name": [], "name_en": [], "keywords": [], "loc_name": [], "loc_kw": [],
            "en_name": [], "en_kw": [], "index": {}, "plain": {}, "groups": [], "tone_names": ["", "", "", "", ""], "lang": language, "ok": False}
    for g in GROUPS:
        data["groups"].append([])
    end
    base = read_text(directory + "/emoji.tsv")
    if base == "":
        return data
    end
    en = load_names(directory + "/en.tsv")
    loc = {}
    if language != "en":
        loc = load_names(directory + "/" + language + ".tsv")
    end
    for line in base.split("\n"):
        if line == "" or line.startswith("# "):            # "#️⃣" je emoji, ne komentar
            continue
        end
        f = line.split("\t")
        if len(f) < 3:
            continue
        end
        e = f[0]
        group = text.to_int(f[1], -2)
        if group == -1:
            # modifikator odstinu: jen nazev pro nabidku odstinu
            if e in TONE_MODIFIERS:
                pos = TONE_MODIFIERS.index(e)
                name = ""
                if e in loc:
                    name = loc[e][0]
                elif e in en:
                    name = en[e][0]
                end
                data["tone_names"][pos] = name
            end
            continue
        end
        if group < 0 or group >= len(GROUPS):
            continue
        end
        index = len(data["emoji"])
        data["emoji"].append(e)
        data["group"].append(group)
        tones = []
        if f[2] != "":
            tones = f[2].split(" ")
            if len(tones) != 5:
                tones = []
            end
        end
        data["tones"].append(tones)
        ename = ""
        ekw = ""
        en_name = ""
        en_kw = ""
        if e in en:
            row = en[e]
            ename = row[0]
            ekw = row[1]
            en_name = row[2]
            en_kw = row[3]
        end
        data["name_en"].append(ename)
        data["en_name"].append(en_name)
        data["en_kw"].append(en_kw)
        if e in loc:
            row = loc[e]
            data["name"].append(row[0])
            data["keywords"].append(row[1])
            data["loc_name"].append(row[2])
            data["loc_kw"].append(row[3])
        else:
            data["name"].append(ename)
            data["keywords"].append(ekw)
            data["loc_name"].append("")
            data["loc_kw"].append("")
        end
        data["index"][e] = index
        data["plain"][e.replace(chr(65039), "")] = index
        data["groups"][group].append(index)
    end
    data["ok"] = len(data["emoji"]) > 0
    return data
end

function count(data):
    return len(data["emoji"])
end

# Index emoji (i varianty s odstinem nebo bez FE0F), -1 kdyz ho data nemaji
function find_index(data, e):
    index = data["index"].get(e, None)
    if index != None:
        return index
    end
    stripped = strip_tone(e)
    index = data["index"].get(stripped, None)
    if index != None:
        return index
    end
    plain = stripped.replace(chr(65039), "")
    index = data["plain"].get(plain, None)
    if index != None:
        return index
    end
    return -1
end

# Emoji bez modifikatoru odstinu pleti
function strip_tone(e):
    out = e
    for m in TONE_MODIFIERS:
        out = out.replace(m, "")
    end
    return out
end

function with_tone(data, index, tone):
    if tone <= 0 or tone > 5:
        return data["emoji"][index]
    end
    tones = data["tones"][index]
    if len(tones) != 5:
        return data["emoji"][index]
    end
    return tones[tone - 1]
end

function has_tones(data, index):
    return len(data["tones"][index]) == 5
end

# ---- hledani ----------------------------------------------------------------------------------------------------

# Body shody jednoho slova w s nazvem n a klicovymi slovy kw ("|slovo|slovo|"); 0 = neshoduje se
function word_score(w, n, kw):
    if n == w:
        return 100
    end
    if n.startswith(w):
        return 90
    end
    if (" " + n + " ").find(" " + w + " ") >= 0:
        return 85                               # cele slovo nazvu ("red heart")
    end
    if (" " + n).find(" " + w) >= 0:
        return 80                               # zacatek slova nazvu ("smiling face with hearts")
    end
    if kw.find("|" + w + "|") >= 0:
        return 70
    end
    if kw.find("|" + w) >= 0:
        return 60
    end
    if kw.find(" " + w) >= 0:
        return 50
    end
    if len(w) >= 2 and (n.find(w) >= 0 or kw.find(w) >= 0):
        return 30
    end
    return 0
end

# Soucet bodu vsech slov (kazde musi sedet); cely dotaz = nazev -> 1000
function entry_score(words, whole, n, kw):
    if n == "":
        return 0
    end
    if n == whole:
        return 1000
    end
    total = 0
    for w in words:
        if n.find(w) < 0 and kw.find(w) < 0:
            return 0
        end
        s = word_score(w, n, kw)
        if s == 0:
            return 0
        end
        total += s
    end
    return total
end

# Indexy emoji serazene podle shody (lepsi prvni, pri shode poradi CLDR); nejvys limit (0 = vse).
# boost {index: True}: naposledy pouzite a casto pouzivane o neco vys (o vic nez jeden stupen shody,
# "srdce" -> rude srdce pred "srdce se sipem"), presny nazev ale vzdy prvni
function search(data, query, limit, boost):
    words = query_words(query)
    if len(words) == 0:
        return []
    end
    whole = " ".join(words)
    keys = []
    total = len(data["emoji"])
    loc_names = data["loc_name"]
    loc_kws = data["loc_kw"]
    en_names = data["en_name"]
    en_kws = data["en_kw"]
    index = 0
    while index < total:
        best = 0
        n = loc_names[index]
        if n != "":
            s = entry_score(words, whole, n, loc_kws[index])
            if s > 0:
                best = s * 2 + 1           # pri shode jazyk uzivatele pred anglictinou
            end
        end
        n = en_names[index]
        s = entry_score(words, whole, n, en_kws[index])
        if s > 0 and s * 2 > best:
            best = s * 2
        end
        if best > 0:
            if boost != None and index in boost:
                best += BOOST
            end
            # razeni vzestupne: vyssi body = mensi klic, pri shode poradi v datech
            keys.append((100000 - best) * 100000 + index)
        end
        index += 1
    end
    keys.sort()
    out = []
    for k in keys:
        out.append(k % 100000)
        if limit > 0 and len(out) >= limit:
            break
        end
    end
    return out
end

# ---- nastaveni (odstin, naposledy pouzite) -------------------------------------------------------------------

function config_home():
    base = env.get("XDG_CONFIG_HOME", "")
    if base == None or base == "":
        base = env.get("HOME", "") + "/.config"
    end
    return base
end

function config_path():
    return config_home() + "/luxos/emoji.conf"
end

function default_config():
    return {"tone": 0, "recent": []}
end

function load_config(path):
    cfg = default_config()
    for line in read_text(path).split("\n"):
        if line.startswith("tone="):
            tone = text.to_int(line[5:].strip(), 0)
            if tone >= 0 and tone <= 5:
                cfg["tone"] = tone
            end
        elif line.startswith("recent="):
            for e in line[7:].strip().split(" "):
                if e != "" and e not in cfg["recent"] and len(cfg["recent"]) < RECENT_MAX:
                    cfg["recent"].append(e)
                end
            end
        end
    end
    return cfg
end

function config_text(cfg):
    return "# LuxOS Emoji & Symbols\ntone=" + String(cfg["tone"]) + "\nrecent=" + " ".join(cfg["recent"]) + "\n"
end

function save_config(cfg, path):
    cut = text.rfind(path, "/")
    if cut > 0:
        call luxos_sys.mkdir_p(path[0:cut])
    end
    tmp = path + ".tmp"
    ok = True
    try:
        call writefile(tmp, config_text(cfg))
    else:
        ok = False
    end
    if ok:
        ok = luxos_sys.rename(tmp, path)
    end
    return ok
end

# Pouzite emoji na zacatek (bez odstinu - zobrazi se v aktualnim odstinu), nejvys RECENT_MAX
function add_recent(recent, e):
    base = strip_tone(e)
    out = [base]
    for r in recent:
        if r != base and len(out) < RECENT_MAX:
            out.append(r)
        end
    end
    return out
end

# Indexy naposledy pouzitych (nezname vynechane); bez historie casto pouzivane
function recent_indexes(data, recent):
    out = []
    for e in recent:
        index = find_index(data, e)
        if index >= 0 and index not in out:
            out.append(index)
        end
    end
    return out
end

function default_indexes(data):
    return recent_indexes(data, DEFAULT_RECENT)
end

# {index: True} pro search(): naposledy pouzite a casto pouzivane
function boost_set(data, recent):
    out = {}
    for i in recent_indexes(data, recent):
        out[i] = True
    end
    for i in default_indexes(data):
        out[i] = True
    end
    return out
end

# ---- vlozeni do aplikace ----------------------------------------------------------------------------------------

# Terminaly (WM_CLASS malymi pismeny): VTE a podobne vkladaji Ctrl+Shift+V, xterm a rxvt Shift+Insert (PRIMARY)
SHIFT_TERMINALS = ["luxos-terminal", "xfce4-terminal", "gnome-terminal", "gnome-terminal-server", "mate-terminal", "tilix",
                   "terminator", "lxterminal", "sakura", "guake", "tilda", "kitty", "alacritty", "konsole", "terminology",
                   "qterminal", "cool-retro-term", "ptyxis", "kgx", "org.gnome.console", "blackbox", "wezterm",
                   "org.wezfurlong.wezterm", "terminal", "roxterm", "deepin-terminal", "termite", "foot", "ghostty", "com.mitchellh.ghostty"]
INSERT_TERMINALS = ["xterm", "uxterm", "urxvt", "rxvt", "rxvt-unicode", "st", "st-256color", "aterm", "eterm", "xvt"]

# "ctrl-v", "ctrl-shift-v" nebo "shift-insert" podle WM_CLASS [jmeno, trida] ciloveho okna
function paste_method(wm_class):
    for part in wm_class:
        low = part.lower()
        if low in SHIFT_TERMINALS:
            return "ctrl-shift-v"
        end
        if low in INSERT_TERMINALS:
            return "shift-insert"
        end
    end
    return "ctrl-v"
end

# ---- prepinace a protokol klient -> hub -------------------------------------------------------------------------

function runtime_dir():
    value = env.get("XDG_RUNTIME_DIR", "")
    if value == None or value == "":
        return "/tmp"
    end
    return value
end

# Abstraktni socket UNIX (bez souboru; uzivatele protistrany overuje SO_PEERCRED)
function socket_name():
    return runtime_dir() + "/luxos-emoji"
end

# {"action": "toggle"|"open"|"close", "search": text|None, "help": bool} nebo {"error": text}
function parse_args(argv):
    a = {"action": "toggle", "search": None, "help": False}
    index = 0
    while index < len(argv):
        item = argv[index]
        if item == "-h" or item == "--help":
            a["help"] = True
        elif item == "--close":
            a["action"] = "close"
        elif item == "--open":
            a["action"] = "open"
        elif item == "--search" or item == "-s":
            if index + 1 >= len(argv):
                return {"error": "luxos-emoji: --search needs a text"}
            end
            a["search"] = argv[index + 1]
            a["action"] = "open"
            index += 1
        elif item.startswith("--search="):
            a["search"] = item[9:]
            a["action"] = "open"
        else:
            return {"error": "luxos-emoji: unknown option " + item + " (see luxos-emoji --help)"}
        end
        index += 1
    end
    return a
end

function canonical_args(a):
    if a["action"] == "close":
        return ["--close"]
    end
    if a["search"] != None:
        return ["--search", a["search"]]
    end
    if a["action"] == "open":
        return ["--open"]
    end
    return []
end

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

# Klient: preda prepinace bezicimu hubu (nebo samostatnemu procesu) a vrati kod ukonceni;
# -1 = nikdo neposloucha, -2 = server neodpovedel do ack_ms
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
        wait = 5000
        if not acked:
            wait = ack_ms
        end
        if not luxos_sys.wait_readable(fd, wait):
            call luxos_sys.close(fd)
            if acked:
                return 0
            end
            return -2
        end
        r = luxos_sys.recv_text(fd)
        if r[0] == 0:
            call luxos_sys.close(fd)
            if acked:
                return 0
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
