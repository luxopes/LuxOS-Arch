# LuxOS - Novinky: oznameni od vyvojaru LuxOS (nove vydani, planovana udrzba serveru, dulezite zmeny).
#
# Kanal: https://luxos.lux-ai.cz/announcements.json (zdroj site/announcements.json v repozitari, vydava ho
# scripts/publish-site.sh se zbytkem webu). Format (docs/developers/announcements.md):
#   {"version": 1, "announcements": [
#     {"id": "2026-11-20-luxos-1-1", "date": "2026-11-20", "until": "2026-12-31", "level": "info|important",
#      "title": {"en": "...", "cs": "..."}, "body": {"en": "...", "cs": "..."}, "url": "https://..."}]}
# Kazda polozka se kontroluje (id, data, delky, odkaz jen https://); neplatne polozky se preskoci, cely
# kanal nad 256 kB nebo s jinou verzi se zahodi. Text se nikde nevyklada jako znacky (oznameni: escapovany).
#
#   ~/.cache/luxos/news.json         posledni stazeny kanal (jen zkontrolovane polozky)
#   ~/.local/state/luxos/news.json   {"notified": [id], "read": [id], "enabled": bool, "since": "YYYY-MM-DD"}
#
# LUXOS_NEWS_URL prepise adresu kanalu (testy): jen https://, nebo http:// na 127.0.0.1 / localhost.
load env, json, http
load luxos_glib, glib as glib
load luxos_gio, gio as gio
load luxos_i18n as i18n

DEFAULT_URL = "https://luxos.lux-ai.cz/announcements.json"
MAX_FEED = 262144
MAX_ITEMS = 50
MAX_TITLE = 120
MAX_BODY = 2000
MAX_URL = 300
NOTIFY_PER_CHECK = 3
FIRST_RUN_DAYS = 14          # pri prvnim spusteni se neohlasuji starsi novinky (zadna lavina)

function feed_url():
    url = env.get("LUXOS_NEWS_URL", "")
    if url == None or url == "":
        return DEFAULT_URL
    end
    if url.startswith("https://") or url.startswith("http://127.0.0.1:") or url.startswith("http://localhost:"):
        return url
    end
    return DEFAULT_URL
end

function dir_of(var, fallback):
    value = env.get(var, "")
    if value == None or value == "":
        value = env.get("HOME", "") + fallback
    end
    return value
end

function cache_path():
    return dir_of("XDG_CACHE_HOME", "/.cache") + "/luxos/news.json"
end

function state_path():
    return dir_of("XDG_STATE_HOME", "/.local/state") + "/luxos/news.json"
end

function parent(path):
    parts = path.split("/")
    return "/".join(parts[0:len(parts) - 1])
end

function read_json(path):
    data = None
    if exists(path):
        safe:
            data = json.decode(glib.read_text(path))
        end
    end
    return data
end

function write_json(path, data):
    call glib.mkdir_p(parent(path))
    call glib.write_atomic(path, json.encode(data) + "\n")
    return 0
end

# ---- kontrola polozek ---------------------------------------------------------------------------

function is_date(value):
    if type(value) != "String" or len(value) != 10 or value[4] != "-" or value[7] != "-":
        return False
    end
    for i in [0, 1, 2, 3, 5, 6, 8, 9]:
        if "0123456789".find(value[i]) < 0:
            return False
        end
    end
    month = Int(value[5:7])
    day = Int(value[8:10])
    return month >= 1 and month <= 12 and day >= 1 and day <= 31
end

function is_id(value):
    if type(value) != "String" or len(value) < 1 or len(value) > 64:
        return False
    end
    for ch in value:
        if "abcdefghijklmnopqrstuvwxyz0123456789-".find(ch) < 0:
            return False
        end
    end
    return True
end

# Odkaz bez mezer a ridicich znaku (otevre ho jen klik, vychozi prohlizec dostane cely retezec)
function has_space(url):
    for ch in [" ", "\t", "\n", "\r"]:
        if url.find(ch) >= 0:
            return True
        end
    end
    return False
end

# Text: retezec, nebo {jazyk: retezec}; kazdy neprazdny a do limitu. Vraci prazdny slovnik pri chybe.
function texts(value, limit):
    out = {}
    if type(value) == "String":
        out["en"] = value
    elif type(value) == "Dictionary":
        for key in value.keys():
            if type(key) == "String" and len(key) >= 2 and len(key) <= 5 and type(value[key]) == "String":
                out[key] = value[key]
            end
        end
    end
    for key in out.keys():
        if out[key].strip() == "" or len(out[key]) > limit:
            return {}
        end
    end
    return out
end

# [polozky, chyby]: zkontrolovane polozky a seznam chyb (pro vyvojare - luxos-news validate)
function validate(data):
    items = []
    errors = []
    if type(data) != "Dictionary" or data.get("version", 0) != 1:
        return [[], ["feed: \"version\" must be 1"]]
    end
    raw = data.get("announcements", [])
    if type(raw) != "List":
        return [[], ["feed: \"announcements\" must be a list"]]
    end
    if len(raw) > MAX_ITEMS:
        errors.append("feed: more than " + String(MAX_ITEMS) + " announcements (only the first are used)")
        raw = raw[0:MAX_ITEMS]
    end
    seen = {}
    index = 0
    for a in raw:
        index += 1
        where = "announcement " + String(index)
        if type(a) != "Dictionary":
            errors.append(where + ": must be an object")
            continue
        end
        problems = []
        if not is_id(a.get("id")):
            problems.append("\"id\" must be 1-64 characters a-z, 0-9, -")
        elif a["id"] in seen:
            problems.append("duplicate \"id\" " + a["id"])
        end
        if not is_date(a.get("date")):
            problems.append("\"date\" must be YYYY-MM-DD")
        end
        until = a.get("until", "")
        if until != "" and not is_date(until):
            problems.append("\"until\" must be YYYY-MM-DD")
        end
        level = a.get("level", "info")
        if level != "info" and level != "important":
            problems.append("\"level\" must be info or important")
        end
        title = texts(a.get("title"), MAX_TITLE)
        raw_body = a.get("body", "")
        if raw_body == None or (type(raw_body) == "Dictionary" and len(raw_body) == 0):
            raw_body = ""                  # bez textu (mezipamet uklada prazdny slovnik)
        end
        body = texts(raw_body, MAX_BODY)
        if len(title) == 0:
            problems.append("\"title\" must be text (or {language: text}) up to " + String(MAX_TITLE) + " characters")
        end
        if raw_body != "" and len(body) == 0:
            problems.append("\"body\" must be text (or {language: text}) up to " + String(MAX_BODY) + " characters")
        end
        url = a.get("url", "")
        if url != "" and (type(url) != "String" or not url.startswith("https://") or len(url) > MAX_URL or has_space(url)):
            problems.append("\"url\" must be https:// and up to " + String(MAX_URL) + " characters")
        end
        if len(problems) > 0:
            label = where
            if type(a.get("id")) == "String":
                label = where + " (" + a["id"] + ")"
            end
            for p in problems:
                errors.append(label + ": " + p)
            end
            continue
        end
        seen[a["id"]] = True
        items.append({"id": a["id"], "date": a["date"], "until": until, "level": level,
                      "title": title, "body": body, "url": url})
    end
    return [items, errors]
end

# YYYY-MM-DD jako cislo (LSL neporovnava retezce <, <=)
function day_number(day):
    return Int(day[0:4] + day[5:7] + day[8:10])
end

function today():
    return glib.date_time_format("%Y-%m-%d")
end

# Platne dnes (od data, do until vcetne), nejnovejsi prvni
function active(items, day):
    out = []
    d = day_number(day)
    for it in items:
        if day_number(it["date"]) <= d and (it["until"] == "" or d <= day_number(it["until"])):
            i = 0
            while i < len(out) and day_number(out[i]["date"]) >= day_number(it["date"]):
                i += 1
            end
            out.insert(i, it)
        end
    end
    return out
end

# Text v jazyce uzivatele, jinak anglicky, jinak jakykoli
function localized(value):
    if type(value) != "Dictionary" or len(value) == 0:
        return ""
    end
    lang = i18n.lang()
    if lang in value:
        return value[lang]
    end
    if "en" in value:
        return value["en"]
    end
    return value[List(value.keys())[0]]
end

# ---- stav, mezipamet, stazeni --------------------------------------------------------------------

function load_state():
    st = read_json(state_path())
    if type(st) != "Dictionary":
        st = {}
    end
    for key in ["notified", "read"]:
        if type(st.get(key)) != "List":
            st[key] = []
        end
    end
    if type(st.get("enabled")) != "Bool":
        st["enabled"] = True
    end
    return st
end

function save_state(st):
    return write_json(state_path(), st)
end

function cached_items():
    data = read_json(cache_path())
    if type(data) != "Dictionary" or type(data.get("items")) != "List":
        return []
    end
    # mezipamet uz je zkontrolovana, ale soubor muze nekdo zmenit - znovu stejna kontrola
    return validate({"version": 1, "announcements": data["items"]})[0]
end

# Stazeni kanalu: {"ok": True, "items": [...]} nebo {"ok": False, "error": "..."}
function fetch():
    resp = {}
    ok = True
    try:
        resp = http.get(feed_url(), {"Accept": "application/json"}, 10)
    else:
        ok = False
    end
    if ok and resp.get("status", 0) == 404:
        # kanal jeste nevydany (web bez announcements.json): zadne novinky, ne chyba
        call write_json(cache_path(), {"fetched": glib.now(), "items": []})
        return {"ok": True, "items": []}
    end
    if not ok or not resp.get("ok", False):
        return {"ok": False, "error": "unreachable"}
    end
    text = resp.get("text", "")
    if len(text) > MAX_FEED:
        return {"ok": False, "error": "too large"}
    end
    data = None
    safe:
        data = json.decode(text)
    end
    checked = validate(data)
    if type(data) != "Dictionary" or data.get("version", 0) != 1:
        return {"ok": False, "error": "invalid"}
    end
    raw = []
    for it in checked[0]:
        raw.append({"id": it["id"], "date": it["date"], "until": it["until"], "level": it["level"],
                    "title": it["title"], "body": it["body"], "url": it["url"]})
    end
    call write_json(cache_path(), {"fetched": glib.now(), "items": raw})
    return {"ok": True, "items": checked[0]}
end

# ---- oznameni -----------------------------------------------------------------------------------

function shorten(text, limit):
    t = text.strip()
    if len(t) <= limit:
        return t
    end
    return t[0:limit - 1].rstrip() + "…"
end

# Oznameni: nazev (summary) je podle specifikace cisty text, text (body) muze obsahovat znacky, proto se
# escapuje - nic z kanalu se nevyklada jako znacky. Vraci cislo oznameni (0 = neodeslano).
function notify(it):
    bus = 0
    safe:
        bus = gio.session_bus()
    end
    if bus == 0:
        return 0
    end
    hints = {"desktop-entry": ["s", "luxos-news"], "x-luxos-keep": ["b", True], "category": ["s", "x-luxos.news"]}
    expire = -1
    if it["level"] == "important":
        expire = 0
    end
    id = 0
    safe:
        reply = gio.call_values(bus, "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                                "org.freedesktop.Notifications", "Notify",
                                [i18n.T("LuxOS News"), 0, "luxos-news", shorten(localized(it["title"]), MAX_TITLE),
                                 glib.markup_escape(shorten(localized(it["body"]), 200)),
                                 ["default", i18n.T("Open")], hints, expire],
                                "(susssasa{sv}i)", 5000)
        if type(reply) == "List" and len(reply) > 0 and type(reply[0]) == "Int" and reply[0] > 0:
            id = reply[0]
        end
    end
    return id
end

# Kontrola (luxos-hub po prihlaseni a pak pravidelne): stahnout, ohlasit nove platne novinky.
# Vraci cisla odeslanych oznameni.
function check():
    sent = []
    st = load_state()
    if not st["enabled"]:
        return sent
    end
    result = fetch()
    if not result["ok"]:
        return sent
    end
    first_run = type(st.get("since")) != "String"
    if first_run:
        st["since"] = glib.format_unix(glib.now() - FIRST_RUN_DAYS * 86400, "%Y-%m-%d")
    end
    for it in active(result["items"], today()):
        if it["id"] in st["notified"] or it["id"] in st["read"]:
            continue
        end
        if day_number(it["date"]) < day_number(st["since"]):
            st["notified"].append(it["id"])    # starsi nez prvni spusteni: jen v aplikaci, bez oznameni
            continue
        end
        if len(sent) < NOTIFY_PER_CHECK:
            n = notify(it)
            if n != 0:
                sent.append(n)
                st["notified"].append(it["id"])
            end
        end
    end
    # stav nerozrusta: drzet jen id, ktera v kanalu jeste jsou
    known = {}
    for it in result["items"]:
        known[it["id"]] = True
    end
    for key in ["notified", "read"]:
        kept = []
        for id in st[key]:
            if id in known:
                kept.append(id)
            end
        end
        st[key] = kept
    end
    call save_state(st)
    return sent
end

function mark_read(ids):
    st = load_state()
    for id in ids:
        if id not in st["read"]:
            st["read"].append(id)
        end
    end
    return save_state(st)
end

function set_enabled(on):
    st = load_state()
    st["enabled"] = Bool(on)
    return save_state(st)
end
