# LuxOS - Launchpad bez GTK: hledani aplikaci (bez diakritiky, fuzzy, poradi podle shody a pouzivani), razeni
# mrizky a pocty spusteni. Oddelene od luxos-launchpad.lsl, aby slo testovat bez displeje
# (tests/lsl/luxos-launchpad-model-test.lsl).
#
#   fold(text)                                 mala pismena bez diakritiky ("Prohlížeč" -> "prohlizec")
#   entry(id, fields)                          polozka pro hledani; fields: name, c_name, generic, c_generic,
#                                              keywords, c_keywords, exec, categories (texty z .desktop)
#   search(entries, query, usage, now)         polozky odpovidajici dotazu, nejlepsi prvni
#   order(entries, mode, usage)                poradi mrizky bez dotazu: alpha, recent, most, category
#   parse_usage(text), usage_text(usage), record(usage, id, now)
#                                              ~/.local/share/luxos/launchpad-usage.json jako luxos_launchpad.py
#   parse_rofi_history(text)                   pocty z rofi3.druncache (prvni spusteni po Launchpadu v rofi)
load json
load luxos_text as text

MODES = ["alpha", "recent", "most", "category"]
DEFAULT_MODE = "most"
# hlavni kategorie freedesktop v poradi Launchpadu (luxos_launchpad.py CATEGORY_ORDER), ostatni na konci
CATEGORY_ORDER = ["Network", "Office", "Graphics", "AudioVideo", "Development", "Education", "Game", "Science",
    "Utility", "Settings", "System"]
SENTINEL = "luxos-launchpad-sentinel"

# Shoda jednoho slova dotazu s textem pole; pole s nizsi vahou (popis, klicova slova, program) ztraci body
EXACT = 1000
PREFIX = 900
WORD = 800
INSIDE = 600
FUZZY = 400
FIELD_PENALTY = {"name": 0, "c_name": 20, "generic": 250, "c_generic": 270, "keywords": 300, "c_keywords": 320,
    "exec": 350, "id": 380}
DAY = 86400

FOLD = {"á": "a", "ä": "a", "à": "a", "â": "a", "ã": "a", "å": "a", "ą": "a", "č": "c", "ć": "c", "ç": "c",
    "ď": "d", "đ": "d", "é": "e", "ě": "e", "ë": "e", "è": "e", "ê": "e", "ę": "e", "í": "i", "ï": "i", "ì": "i",
    "î": "i", "ľ": "l", "ĺ": "l", "ł": "l", "ň": "n", "ń": "n", "ñ": "n", "ó": "o", "ö": "o", "ò": "o", "ô": "o",
    "õ": "o", "ő": "o", "ø": "o", "ř": "r", "ŕ": "r", "š": "s", "ś": "s", "ș": "s", "ş": "s", "ß": "ss", "ť": "t",
    "ț": "t", "ú": "u", "ů": "u", "ü": "u", "ù": "u", "û": "u", "ű": "u", "ý": "y", "ÿ": "y", "ž": "z", "ź": "z",
    "ż": "z"}
SEPARATORS = [" ", "-", "_", ".", "/", "(", ")", ":", ","]

function fold(value):
    out = ""
    for ch in value.lower():
        out = out + FOLD.get(ch, ch)
    end
    return out
end

function words(value):
    return [w for w in fold(value).replace("\t", " ").split(" ") if w != ""]
end

function entry(desktop_id, fields):
    folded = {}
    for key in FIELD_PENALTY:
        if key == "id":
            value = desktop_id
            if value.endswith(".desktop"):
                value = value[0:len(value) - 8]
            end
        else:
            value = fields.get(key, "")
        end
        if key == "keywords" or key == "c_keywords":
            value = value.replace(";", " ")
        end
        value = fold(value).strip()
        if value != "":
            folded[key] = value
        end
    end
    cats = [c for c in fields.get("categories", "").split(";") if c != ""]
    rank = len(CATEGORY_ORDER)
    for i in range(len(CATEGORY_ORDER)):
        if CATEGORY_ORDER[i] in cats and i < rank:
            rank = i
        end
    end
    name = fields.get("name", "")
    if name == "":
        name = desktop_id
    end
    return {"id": desktop_id, "name": name, "sort": fold(name), "fields": folded, "category": rank}
end

# Pismena slova v textu po poradi (nemusi jit za sebou): mene mezer a start na zacatku slova = vic bodu
function fuzzy(hay, word):
    if len(word) < 2:
        return 0
    end
    pos = 0
    gaps = 0
    first = -1
    for ch in word:
        found = text.find_from(hay, ch, pos)
        if found < 0:
            return 0
        end
        if first < 0:
            first = found
        elif found > pos:
            gaps += found - pos
        end
        pos = found + 1
    end
    if gaps > 3 * len(word):
        return 0
    end
    return FUZZY - 10 * min(gaps, 15) - min(first, 10)
end

function word_score(hay, word):
    if hay == word:
        return EXACT
    end
    if hay.startswith(word):
        return PREFIX
    end
    at = hay.find(word)
    if at < 0:
        return fuzzy(hay, word)
    end
    while at >= 0:
        if hay[at - 1] in SEPARATORS:
            return WORD
        end
        at = text.find_from(hay, word, at + 1)
    end
    return INSIDE
end

# Kazde slovo dotazu musi sedet na nektere pole; body = prumer nejlepsich shod
function score(e, query_words):
    if len(query_words) == 0:
        return 0
    end
    total = 0
    for word in query_words:
        best = 0
        for key in e["fields"]:
            s = word_score(e["fields"][key], word)
            if s > 0:
                best = max(best, s - FIELD_PENALTY[key])
            end
        end
        if best <= 0:
            return 0
        end
        total += best
    end
    return total // len(query_words)
end

# Casto a nedavno spoustene aplikace mezi stejne dobrymi shodami vyhravaji, slabou shodu ale nepreskoci
function boost(used, now):
    if used == None:
        return 0
    end
    b = min(used["count"], 20) * 3
    if used["last"] > 0 and now - used["last"] < 3 * DAY:
        b += 30
    end
    return b
end

function pad(n, width):
    value = String(n)
    while len(value) < width:
        value = "0" + value
    end
    return value
end

# Seradit podle textovych klicu (sorted() v LSL bere jen cisla nebo texty): klic + poradi = jedinecny
function sort_by(entries, keys):
    by_key = {}
    for i in range(len(entries)):
        by_key[keys[i] + "\n" + pad(i, 5)] = entries[i]
    end
    return [by_key[k] for k in sorted(by_key.keys())]
end

function search(entries, query, usage, now):
    q = words(query)
    hits = []
    keys = []
    for e in entries:
        s = score(e, q)
        if s > 0:
            s += boost(usage.get(e["id"]), now)
            hits.append(e)
            keys.append(pad(99999 - s, 5) + " " + e["sort"])
        end
    end
    return sort_by(hits, keys)
end

function order(entries, mode, usage):
    keys = []
    for e in entries:
        used = usage.get(e["id"], {"count": 0, "last": 0})
        if mode == "recent" and used["last"] > 0:
            key = "0" + pad(99999999999 - used["last"], 11)
        elif mode == "most" and used["count"] > 0:
            key = "0" + pad(9999999 - used["count"], 7) + pad(99999999999 - used["last"], 11)
        elif mode == "category":
            key = pad(e["category"], 2)
        else:
            key = "1"
        end
        keys.append(key + " " + e["sort"])
    end
    return sort_by(entries, keys)
end

# ---- pocty spusteni ----

function parse_usage(content):
    usage = {}
    data = None
    safe:
        data = json.decode(content)
    end
    if type(data) != "Dictionary" or type(data.get("apps")) != "Dictionary":
        return None
    end
    for key in data["apps"]:
        v = data["apps"][key]
        if type(v) == "Dictionary":
            count = 0
            last = 0
            safe:
                count = Int(v.get("count", 0))
                last = Int(v.get("last", 0))
            end
            usage[key] = {"count": count, "last": last}
        end
    end
    return usage
end

function usage_text(usage):
    return json.encode({"version": 1, "apps": usage}) + "\n"
end

function record(usage, desktop_id, now):
    used = usage.get(desktop_id)
    if used == None:
        used = {"count": 0, "last": 0}
        usage[desktop_id] = used
    end
    used["count"] += 1
    used["last"] = now
    return usage
end

# "pocet id" na radek (rofi -cache-dir); zarazka Launchpadu se nepocita
function parse_rofi_history(content):
    usage = {}
    for line in text.lines(content):
        parts = text.partition(line.strip(), " ")
        if parts[1] != "" and parts[1] != SENTINEL and text.is_digits(parts[0]):
            usage[parts[1]] = {"count": max(1, Int(parts[0])), "last": 0}
        end
    end
    return usage
end
