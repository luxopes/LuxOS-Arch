# LuxOS - razeni Launchpadu v relaci X11 (rofi) a lokalni pocitani spusteni aplikaci
# (/usr/lib/luxos/luxos-launchpad-order, spousti luxos-launchpad; drive luxos_launchpad.py).
#
# Launchpad na X11 je rofi (drun v combi). Rofi radi dlazdice podle sve historie (rofi3.druncache v -cache-dir:
# radky "<pocet> <desktop-id>", v poradi souboru) a zbytek abecedne. Pro kazdy zpusob razeni se proto pripravi
# vlastni "historie": alpha = jen zarazka, recent = podle casu posledniho spusteni, most = podle poctu (shoda:
# novejsi drive), category = Internet, Kancelar, Grafika, ... a v kategorii abecedne. Zarazka
# "0 luxos-launchpad-sentinel" drzi nejmensi hodnotu 0, takze rofi pri ulozeni nic neposune; spustena aplikace
# ma po zavreni rofi o 1 vic (nebo je v souboru nove) - tak se pozna, co uzivatel spustil, a zapise se do
# ~/.local/share/luxos/launchpad-usage.json (jen id, pocty a casy; stejny soubor jako Launchpad na Waylandu).
#
#   luxos-launchpad-order order MODE OUT        pripravit historii pro rofi
#   luxos-launchpad-order record BEFORE AFTER   zapsat spusteni a obnovit pripravene poradi
load env
load luxos_glib, glib as glib
load luxos_text as text
load luxos_launchpad_model as model

function home_dir(variable, fallback):
    value = env.get(variable, "")
    if value == None or value == "":
        return glib.home_dir() + "/" + fallback
    end
    return value
end

function usage_path():
    return home_dir("XDG_DATA_HOME", ".local/share") + "/luxos/launchpad-usage.json"
end

function order_path(mode):
    return home_dir("XDG_CACHE_HOME", ".cache") + "/luxos/launchpad-order-" + mode
end

function write_file(path, content):
    call glib.mkdir_p(path[0:text.rfind(path, "/")])
    return glib.write_atomic(path, content)
end

# rofi historie -> [[desktop-id, pocet]...] v poradi souboru
function read_history(path):
    out = []
    for line in text.lines(glib.read_text(path)):
        parts = text.partition(line, " ")
        num = parts[0]
        if num.startswith("-"):
            num = num[1:]
        end
        if parts[1] != "" and text.is_digits(num):
            out.append([parts[1], Int(parts[0])])
        end
    end
    return out
end

function load_usage():
    usage = model.parse_usage(glib.read_text(usage_path()))
    if usage == None:
        # prvni spusteni: prevzit pocty z puvodni historie rofi (Launchpad dosud radil podle ni)
        usage = model.parse_rofi_history(glib.read_text(home_dir("XDG_CACHE_HOME", ".cache") + "/rofi3.druncache"))
    end
    return usage
end

# Name[cs_CZ], Name[cs], Name
function name_keys():
    lang = ""
    for variable in ["LC_ALL", "LC_MESSAGES", "LANG"]:
        value = env.get(variable, "")
        if value != None and value != "":
            lang = value
            break
        end
    end
    lang = text.partition(text.partition(lang, ".")[0], "@")[0]
    keys = []
    if lang != "":
        keys.append("Name[" + lang + "]")
        if lang.find("_") >= 0:
            keys.append("Name[" + text.partition(lang, "_")[0] + "]")
        end
    end
    keys.append("Name")
    return keys
end

# Pole skupiny [Desktop Entry] (prvni vyskyt klice plati)
function desktop_fields(path):
    fields = {}
    group = ""
    for raw in text.lines(glib.read_text(path)):
        line = raw.strip()
        if line.startswith("["):
            group = line
            continue
        end
        if group == "[Desktop Entry]" and line.find("=") > 0:
            pair = text.partition(line, "=")
            key = pair[0].strip()
            if key not in fields:
                fields[key] = pair[1].strip()
            end
        end
    end
    return fields
end

function scan(root, folder, prefix, keys, apps):
    for name in glib.list_dir(folder):
        path = folder + "/" + name
        if glib.is_dir(path):
            call scan(root, path, prefix + name + "-", keys, apps)
            continue
        end
        did = prefix + name
        if not name.endswith(".desktop") or did in apps:
            continue
        end
        fields = desktop_fields(path)
        title = ""
        for k in keys:
            if fields.get(k, "") != "":
                title = fields[k]
                break
            end
        end
        apps[did] = model.entry(did, {"name": title, "categories": fields.get("Categories", "")})
    end
    return 0
end

# {desktop-id: polozka modelu} jako drun: uzivatelske prvni, pak systemove
function desktop_apps():
    dirs = [home_dir("XDG_DATA_HOME", ".local/share")]
    data_dirs = env.get("XDG_DATA_DIRS", "")
    if data_dirs == None or data_dirs == "":
        data_dirs = "/usr/local/share:/usr/share"
    end
    for d in data_dirs.split(":"):
        if d != "":
            dirs.append(d)
        end
    end
    keys = name_keys()
    apps = {}
    for d in dirs:
        call scan(d + "/applications", d + "/applications", "", keys, apps)
    end
    return apps
end

# desktop-id v poradi pro dany zpusob razeni (nepouzite aplikace doplni rofi abecedne); shoda podle id
function order_ids(mode, usage):
    keyed = {}
    if mode == "recent":
        for k in usage.keys():
            if usage[k]["last"] > 0:
                keyed[model.pad(99999999999 - usage[k]["last"], 11) + " " + k] = k
            end
        end
    elif mode == "most":
        for k in usage.keys():
            if usage[k]["count"] > 0:
                keyed[model.pad(9999999 - usage[k]["count"], 7) + model.pad(99999999999 - usage[k]["last"], 11) + " " + k] = k
            end
        end
    elif mode == "category":
        apps = desktop_apps()
        for k in apps.keys():
            keyed[model.pad(apps[k]["category"], 2) + " " + apps[k]["sort"] + "\n" + k] = k
        end
    end
    return [keyed[key] for key in sorted(keyed.keys())]
end

function history_text(ids):
    out = ""
    n = len(ids)
    for i in range(n):
        out = out + String(n - i) + " " + ids[i] + "\n"
    end
    return out + "0 " + model.SENTINEL + "\n"
end

function write_order(mode, out, usage):
    if mode not in model.MODES:
        mode = model.DEFAULT_MODE
    end
    if usage == None:
        usage = load_usage()
    end
    return write_file(out, history_text(order_ids(mode, usage)))
end

# desktop-id spustene aplikace (pocet o 1 vyssi nebo nova polozka), jinak ""
function launched(before, after):
    counts = {}
    for item in before:
        counts[item[0]] = item[1]
    end
    # stejne jako slovnik: poradi prvniho vyskytu, plati posledni hodnota
    now = {}
    names = []
    for item in after:
        if item[0] not in now:
            names.append(item[0])
        end
        now[item[0]] = item[1]
    end
    for name in names:
        if name != model.SENTINEL and now[name] > counts.get(name, 0):
            return name
        end
    end
    return ""
end

function record(before_path, after_path):
    app = launched(read_history(before_path), read_history(after_path))
    if app == "":
        return 0
    end
    usage = model.record(load_usage(), app, glib.now())
    call write_file(usage_path(), model.usage_text(usage))
    # pripravene poradi pro dalsi otevreni (Launchpad pak jen kopiruje soubor)
    for mode in ["recent", "most"]:
        call write_order(mode, order_path(mode), usage)
    end
    return 0
end

if len(args) == 4 and args[1] == "order":
    call write_order(args[2], args[3], None)
    call exit(0)
end
if len(args) == 4 and args[1] == "record":
    call record(args[2], args[3])
    call exit(0)
end
call eprint("usage: luxos-launchpad-order order MODE OUT | record BEFORE AFTER  (used by luxos-launchpad)")
call exit(2)
