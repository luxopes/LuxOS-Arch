# LuxOS - data Monitoru systemu (luxos-monitor) bez okna: cteni /proc, spotreba procesu, skupiny aplikaci,
# razeni seznamu a zapamatovana volba. Testy: tests/lsl/luxos-monitor-model-test.lsl.
#
#   read_cpu(cesta) -> [celkem, necinnost] (tiky /proc/stat), read_mem(cesta) -> [pouzito, celkem] bajtu
#   read_net(cesta) -> [prijato, odeslano] bez lo, read_disk_io(cesta, sys_block) -> bajty fyzickych disku
#   parse_stat(text) -> [comm, ppid, tiky, rss stranek] nebo None, program(comm, cmdline) -> jmeno programu
#   sort_groups({klic: skupina}, sloupec, sestupne) -> [[klic, skupina]], load_sort(cesta), save_sort(cesta, ...)
#   human_bytes(n, za_sekundu, oddelovac), fixed(hodnota, mista, oddelovac)
load json, math
load luxos_glib, glib as glib

SORT_KEYS = ["name", "cpu", "mem"]
# skripty (python3 /usr/bin/x) -> jmeno skriptu; "sh" jako drive i pro programy zacinajici na sh
INTERPRETERS = ["python", "bash", "sh", "lsh", "perl"]

function rfind(text, ch):
    i = len(text) - 1
    while i >= 0 and text[i] != ch:
        i -= 1
    end
    return i
end

# Jen cislice (jmena v /proc, uid v /etc/passwd)
function is_number(text):
    if len(text) == 0:
        return False
    end
    for ch in text:
        if ord(ch) < 48 or ord(ch) > 57:
            return False
        end
    end
    return True
end

function ints(words):
    out = []
    for w in words:
        if w != "":
            out.append(Int(w))
        end
    end
    return out
end

function read_cpu(path):
    text = glib.read_text(path)
    line = text.split("\n")[0]
    vals = ints(line.split(" ")[1:])
    if len(vals) < 4:
        return [0, 0]
    end
    idle = vals[3]
    if len(vals) > 4:
        idle += vals[4]
    end
    # guest a guest_nice (sloupce 9 a 10) uz jsou zapocteny v user a nice
    total = 0
    for v in vals[:8]:
        total += v
    end
    return [total, idle]
end

function cpu_count(path):
    n = 0
    for line in glib.read_text(path).split("\n"):
        if line.startswith("cpu") and len(line) > 3 and line[3] != " ":
            n += 1
        end
    end
    return max(n, 1)
end

function read_mem(path):
    info = {}
    for line in glib.read_text(path).split("\n"):
        cut = line.find(":")
        if cut > 0:
            words = ints(line[cut + 1:].strip().split(" ")[:1])
            if len(words) == 1:
                info[line[:cut]] = words[0] * 1024
            end
        end
    end
    total = info.get("MemTotal", 0)
    return [total - info.get("MemAvailable", info.get("MemFree", 0)), total]
end

function read_net(path):
    rx = 0
    tx = 0
    lines = glib.read_text(path).split("\n")
    for line in lines[2:]:
        cut = line.find(":")
        if cut < 0 or line[:cut].strip() == "lo":
            continue
        end
        v = ints(line[cut + 1:].split(" "))
        if len(v) > 8:
            rx += v[0]
            tx += v[8]
        end
    end
    return [rx, tx]
end

# Prectene + zapsane bajty fyzickych disku (maji /sys/block/X/device)
function read_disk_io(path, sys_block):
    total = 0
    for line in glib.read_text(path).split("\n"):
        p = [w for w in line.split(" ") if w != ""]
        if len(p) > 9 and exists(sys_block + "/" + p[2] + "/device"):
            total += (Int(p[5]) + Int(p[9])) * 512
        end
    end
    return total
end

function parse_stat(text):
    open_at = text.find("(")
    close_at = rfind(text, ")")
    if open_at < 0 or close_at < open_at:
        return None
    end
    fields = text[close_at + 2:].split(" ")
    if len(fields) < 22:
        return None
    end
    return [text[open_at + 1:close_at], Int(fields[1]), Int(fields[11]) + Int(fields[12]), Int(fields[21])]
end

function base_name(path):
    cut = rfind(path, "/")
    if cut >= 0:
        return path[cut + 1:]
    end
    return path
end

function program(comm, cmdline):
    cmd = cmdline.split(chr(0))
    if len(cmd) == 0 or cmd[0] == "":
        return comm
    end
    exe = base_name(cmd[0])
    if len(cmd) > 1 and cmd[1] != "" and not cmd[1].startswith("-"):
        for prefix in INTERPRETERS:
            if exe.startswith(prefix):
                return base_name(cmd[1])
            end
        end
    end
    return exe
end

# ---- razeni ----

# Porovnani klicu [k1, k2, ...] po slozkach: -1, 0, 1
function compare(a, b):
    for i in range(len(a)):
        if a[i] < b[i]:
            return -1
        elif a[i] > b[i]:
            return 1
        end
    end
    return 0
end

# Stabilni razeni (merge sort) dvojic [klic razeni, polozka]; sestupne = obracene porovnani, shody zustanou
# v puvodnim poradi (jako sorted(reverse=True) v Pythonu)
function stable_sort(pairs, descending):
    if len(pairs) < 2:
        return pairs
    end
    half = len(pairs) // 2
    left = stable_sort(pairs[:half], descending)
    right = stable_sort(pairs[half:], descending)
    out = []
    i = 0
    j = 0
    while i < len(left) and j < len(right):
        c = compare(right[j][0], left[i][0])
        if descending:
            c = -c
        end
        if c < 0:
            out.append(right[j])
            j += 1
        else:
            out.append(left[i])
            i += 1
        end
    end
    return out + left[i:] + right[j:]
end

# Nazvy nejdou porovnat operatorem <: klic nazvu je poradi v serazenem seznamu malych pismen
function sort_key(group, key, ranks):
    if key == "name":
        return [ranks[String(group["name"]).lower()]]
    elif key == "cpu":
        return [group["cpu"], group["mem"]]
    end
    return [group["mem"], group["cpu"]]
end

# [[klic, skupina]] podle sloupce; shoda -> druhy ciselny sloupec a nazev (poradi se neprehazuje)
function sort_groups(groups, key, descending):
    ranks = {}
    for name in sorted([String(groups[k]["name"]).lower() for k in groups]):
        if name not in ranks:
            ranks[name] = len(ranks)
        end
    end
    items = stable_sort([[sort_key(groups[k], "name", ranks), [k, groups[k]]] for k in groups], False)
    items = stable_sort([[sort_key(item[1][1], key, ranks), item[1]] for item in items], descending)
    return [item[1] for item in items]
end

# [sloupec, sestupne] z nastaveni; vychozi procesor sestupne
function load_sort(path):
    data = None
    safe:
        data = json.decode(readfile(path))
    end
    if type(data) == "Dictionary" and data.get("sort") in SORT_KEYS:
        desc = data.get("descending", data["sort"] != "name")
        return [data["sort"], desc == True]
    end
    return ["cpu", True]
end

# Stejny zapis jako drive json.dump v Pythonu
function save_sort(path, key, descending):
    cut = rfind(path, "/")
    call glib.mkdir_p(path[:cut])
    ok = False
    safe:
        ok = glib.write_atomic(path, "{\"sort\": " + json.encode(key) + ", \"descending\": " + ("true" if descending else "false") + "}")
    end
    return ok
end

# ---- texty ----

# Kladne cislo na pevny pocet desetinnych mist (zaokrouhleni jako format Pythonu u bezne hodnoty)
function fixed(value, places, sep):
    scale = 1
    for i in range(places):
        scale *= 10
    end
    n = Int(math.round(value * Float(scale)))
    if places == 0:
        return String(n)
    end
    frac = String(n % scale)
    while len(frac) < places:
        frac = "0" + frac
    end
    return String(n // scale) + sep + frac
end

function human_bytes(n, per_second, sep):
    units = ["B", "KB", "MB", "GB", "TB"]
    v = Float(n)
    i = 0
    while v >= 1000.0 and i < len(units) - 1:
        v /= 1000.0
        i += 1
    end
    text = ""
    if v >= 100.0 or i == 0:
        text = fixed(v, 0, sep) + " " + units[i]
    else:
        text = fixed(v, 1, sep) + " " + units[i]
    end
    if per_second:
        return text + "/s"
    end
    return text
end
