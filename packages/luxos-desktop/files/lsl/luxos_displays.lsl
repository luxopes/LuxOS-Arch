# LuxOS - monitory na Waylandu: stav z wlr-output-management (luxos_wl), ulozene nastaveni pro sadu
# monitoru, plany rezimu (rozsirit, zrcadlit, jen externi, jen vestaveny) a usporadani bez mezer
# a prekryvu (port luxos_arrange.py z X11). Pouziva pomocnik luxos-displays (jediny s pravem menit
# monitory) a okno luxos-displays-settings.
#
# Monitor (read_outputs): {"head", "name", "description", "enabled", "x", "y", "width", "height" (rezim
#   v px), "refresh" (mHz), "scale" (tisiciny), "transform" (wl_output 0-7), "modes": [[w, h, mHz,
#   preferovany, aktualni]..], "key", "identity", "internal"}
# Konfigurace: {nazev: {"enabled", "width", "height", "refresh", "x", "y", "transform", "scale"}}
# Ulozeni ~/.config/luxos/displays-wayland.json (LUXOS_DISPLAYS_CONF):
#   {"version": 1, "outputs": {klic: {"width", "height", "refresh", "scale", "transform"}},
#    "sets": {klic sady: {"mode": "extend", "primary": klic, "pos": {klic: [x, y]}}}}
#   klic monitoru "NAZEV|popis" (popis od kompozitoru = vyrobce, model, seriove cislo), klic sady =
#   serazene klice spojene "+". Stejne monitory v jinych konektorech se najdou podle popisu.
load env, json, glib
load luxos_wl as wl
load luxos_glib as lglib

MODES = ["extend", "mirror", "external", "internal"]
SCALES = [1000, 1250, 1500, 1750, 2000]
MIN_CONTACT = 32      # nejmensi spolecna hrana sousednich monitoru (mys musi projit)

function conf_path():
    path = env.get("LUXOS_DISPLAYS_CONF", "")
    if path != "":
        return path
    end
    return glib.user_config_dir() + "/luxos/displays-wayland.json"
end

# LUXOS_DISPLAYS_INTERNAL = nazvy dalsich vestavenych displeju oddelene carkou (testy na headless vystupech)
function is_internal(name):
    if name in env.get("LUXOS_DISPLAYS_INTERNAL", "").split(","):
        return True
    end
    return name.startswith("eDP") or name.startswith("LVDS") or name.startswith("DSI")
end

# wlroots pise na konec popisu nazev konektoru: bez nej popis identifikuje monitor
function identity(name, description):
    tail = " (" + name + ")"
    if description.endswith(tail):
        return description[:len(description) - len(tail)]
    end
    return description
end

function key_identity(key):
    cut = key.find("|")
    if cut < 0:
        return ""
    end
    return identity(key[:cut], key[cut + 1:])
end

function by_name(items):
    names = sorted([o["name"] for o in items])
    result = []
    for name in names:
        for o in items:
            if o["name"] == name:
                result.append(o)
            end
        end
    end
    return result
end

function read_outputs():
    items = []
    for head in wl.heads():
        i = wl.head_info(head)
        items.append({"head": head, "name": i[0], "description": i[1], "enabled": i[2], "x": i[3], "y": i[4],
                      "width": i[5], "height": i[6], "refresh": i[7], "scale": i[8], "transform": i[9],
                      "modes": wl.head_modes(head), "key": i[0] + "|" + i[1], "identity": identity(i[0], i[1]),
                      "internal": is_internal(i[0])})
    end
    return by_name(items)
end

function find(outs, name):
    for o in outs:
        if o["name"] == name:
            return o
        end
    end
    return None
end

# ---- velikosti ----------------------------------------------------------------------------------

# Meritko tak, jak ho kompozitor dostane (wl_fixed, 1/256)
function scale256(scale):
    s = (scale * 256 + 500) // 1000
    if s <= 0:
        return 256
    end
    return s
end

# Logicka velikost (pixely plochy) jako wlr_output_effective_resolution: otoceni, pak deleni meritkem
function logical(width, height, transform, scale):
    w = width
    h = height
    if transform % 2 == 1:
        w = height
        h = width
    end
    s = scale256(scale)
    return [w * 256 // s, h * 256 // s]
end

function config_size(c):
    return logical(c["width"], c["height"], c["transform"], c["scale"])
end

function preferred(o):
    for m in o["modes"]:
        if m[3] == 1:
            return [m[0], m[1], m[2]]
        end
    end
    if len(o["modes"]) > 0:
        m = o["modes"][0]
        return [m[0], m[1], m[2]]
    end
    return [o["width"], o["height"], o["refresh"]]
end

# Rezim, ktery monitor umi; virtualni vystupy (headless, vnorene okno: vsechny rezimy 0 Hz) berou
# i vlastni velikost
function has_mode(o, width, height, refresh):
    virtual = True
    for m in o["modes"]:
        if m[0] == width and m[1] == height and (refresh == 0 or m[2] == refresh):
            return True
        end
        if m[2] != 0:
            virtual = False
        end
    end
    return virtual and width > 0 and height > 0
end

# Frekvence pro velikost: doporucena, jinak nejvyssi
function best_refresh(o, width, height):
    best = 0
    for m in o["modes"]:
        if m[0] == width and m[1] == height:
            if m[3] == 1:
                return m[2]
            end
            best = max(best, m[2])
        end
    end
    return best
end

# [[w, h]..] od nejvetsi plochy, bez duplicit
function resolutions(o):
    sizes = []
    for m in o["modes"]:
        if [m[0], m[1]] not in sizes:
            sizes.append([m[0], m[1]])
        end
    end
    i = 1
    while i < len(sizes):
        j = i
        while j > 0 and sizes[j][0] * sizes[j][1] > sizes[j - 1][0] * sizes[j - 1][1]:
            t = sizes[j]
            sizes[j] = sizes[j - 1]
            sizes[j - 1] = t
            j -= 1
        end
        i += 1
    end
    return sizes
end

function refreshes(o, width, height):
    rates = []
    for m in o["modes"]:
        if m[0] == width and m[1] == height and m[2] not in rates:
            rates.append(m[2])
        end
    end
    return sorted(rates)
end

# ---- ulozena nastaveni -----------------------------------------------------------------------------

function load():
    data = None
    safe:
        data = json.decode(lglib.read_text(conf_path()))
    end
    if type(data) != "Dictionary":
        data = {}
    end
    for name in ["outputs", "sets"]:
        if type(data.get(name)) != "Dictionary":
            data[name] = {}
        end
    end
    data["version"] = 1
    return data
end

function save(data):
    path = conf_path()
    dir = path
    while dir != "" and not dir.endswith("/"):
        dir = dir[:len(dir) - 1]
    end
    if dir != "":
        call lglib.mkdir_p(dir)
    end
    return lglib.write_atomic(path, json.encode(data) + chr(10))
end

function set_key(outs):
    return "+".join(sorted([o["key"] for o in outs]))
end

# Ulozeny zaznam sady: [zaznam, {ulozeny klic: nazev vystupu}] nebo [None, {}]
function find_set(store, outs):
    rec = store["sets"].get(set_key(outs))
    if type(rec) == "Dictionary":
        names = {}
        for o in outs:
            names[o["key"]] = o["name"]
        end
        return [rec, names]
    end
    ids = [o["identity"] for o in outs]
    for i in ids:
        if i == "" or ids.count(i) > 1:
            return [None, {}]
        end
    end
    for k in sorted(store["sets"].keys()):
        rec = store["sets"][k]
        keys = k.split("+")
        if type(rec) != "Dictionary" or sorted([key_identity(x) for x in keys]) != sorted(ids):
            continue
        end
        names = {}
        for x in keys:
            for o in outs:
                if o["identity"] == key_identity(x):
                    names[x] = o["name"]
                end
            end
        end
        return [rec, names]
    end
    return [None, {}]
end

function entry_for(store, o):
    e = store["outputs"].get(o["key"])
    if type(e) == "Dictionary":
        return e
    end
    if o["identity"] == "":
        return None
    end
    for k in sorted(store["outputs"].keys()):
        if key_identity(k) == o["identity"] and type(store["outputs"][k]) == "Dictionary":
            return store["outputs"][k]
        end
    end
    return None
end

function int_of(d, name, fallback):
    value = d.get(name)
    if type(value) == "Int":
        return value
    end
    return fallback
end

# Rezim, meritko a otoceni monitoru: ulozene (kdyz je rezim porad nabizeny), jinak doporucene
function settings_for(store, o):
    mode = preferred(o)
    c = {"enabled": True, "width": mode[0], "height": mode[1], "refresh": mode[2], "x": 0, "y": 0,
         "transform": 0, "scale": 1000}
    e = entry_for(store, o)
    if e == None:
        return c
    end
    w = int_of(e, "width", 0)
    h = int_of(e, "height", 0)
    r = int_of(e, "refresh", 0)
    if has_mode(o, w, h, r):
        c["width"] = w
        c["height"] = h
        c["refresh"] = r
    end
    t = int_of(e, "transform", 0)
    if t >= 0 and t <= 7:
        c["transform"] = t
    end
    s = int_of(e, "scale", 1000)
    if s >= 500 and s <= 4000:
        c["scale"] = s
    end
    return c
end

function current_config(outs):
    config = {}
    for o in outs:
        if o["enabled"] and o["width"] > 0:
            config[o["name"]] = {"enabled": True, "width": o["width"], "height": o["height"], "refresh": o["refresh"],
                                 "x": o["x"], "y": o["y"], "transform": o["transform"], "scale": o["scale"]}
        else:
            config[o["name"]] = {"enabled": False}
        end
    end
    return config
end

# Rezim podle skutecneho stavu (okno nastaveni, kdyz sada nema ulozeny)
function detect_mode(outs):
    on = [o for o in outs if o["enabled"] and o["width"] > 0]
    if len(on) > 1:
        for o in on:
            if o["x"] != on[0]["x"] or o["y"] != on[0]["y"]:
                return "extend"
            end
        end
        return "mirror"
    end
    if len(on) == 1 and len(outs) > 1:
        if on[0]["internal"]:
            return "internal"
        end
        return "external"
    end
    return "extend"
end

# Zapamatovat potvrzene nastaveni: rezim, hlavni monitor a polohy sady (polohy jen v rozsirenem rezimu,
# zrcadleni nebo jeden monitor je neprepisou), s_outputs = i rezim/meritko/otoceni jednotlivych monitoru
function remember(store, outs, config, primary, mode, with_outputs):
    if with_outputs:
        for o in outs:
            c = config.get(o["name"])
            if c != None and c["enabled"]:
                store["outputs"][o["key"]] = {"width": c["width"], "height": c["height"], "refresh": c["refresh"],
                                              "scale": c["scale"], "transform": c["transform"]}
            end
        end
    end
    found = find_set(store, outs)
    rec = {}
    if found[0] != None:
        rec = found[0].copy()
        # zaznam nalezeny podle popisu (jine konektory) se prepise pod presnym klicem sady
        for k in [k for k in store["sets"].keys() if store["sets"][k] == found[0]]:
            call store["sets"].pop(k)
        end
        old = rec.get("pos")
        if type(old) == "Dictionary":
            pos = {}
            for k in old.keys():
                name = found[1].get(k)
                o = find(outs, name) if name != None else None
                if o != None:
                    pos[o["key"]] = old[k]
                end
            end
            rec["pos"] = pos
        end
    end
    rec["mode"] = mode
    p = find(outs, primary)
    if p != None:
        rec["primary"] = p["key"]
    end
    if mode == "extend":
        pos = {}
        for o in outs:
            c = config.get(o["name"])
            if c != None and c["enabled"]:
                pos[o["key"]] = [c["x"], c["y"]]
            end
        end
        rec["pos"] = pos
    end
    store["sets"][set_key(outs)] = rec
    return store
end

# ---- geometrie (obdelnik [x, y, w, h] v pixelech plochy) -----------------------------------------

function overlaps(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]
end

function shared(a0, alen, b0, blen):
    return min(a0 + alen, b0 + blen) - max(a0, b0)
end

function touches(a, b):
    if (a[0] + a[2] == b[0] or b[0] + b[2] == a[0]) and shared(a[1], a[3], b[1], b[3]) > 0:
        return True
    end
    return (a[1] + a[3] == b[1] or b[1] + b[3] == a[1]) and shared(a[0], a[2], b[0], b[2]) > 0
end

# Bez prekryvu a jeden celek (kazdy dosazitelny pres dotyky hran)
function valid(rects):
    items = rects.values()
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if overlaps(items[i], items[j]):
                return False
            end
        end
    end
    if len(items) < 2:
        return True
    end
    seen = [0]
    todo = [0]
    while len(todo) > 0:
        i = todo.pop()
        for j in range(len(items)):
            if j not in seen and touches(items[i], items[j]):
                seen.append(j)
                todo.append(j)
            end
        end
    end
    return len(seen) == len(items)
end

function clamp(v, lo, hi):
    return max(lo, min(hi, v))
end

# Prichyceni k zarovnani hran (nahore, dole, na stred), je-li blizko
function align(v, targets, lo, hi, snap):
    best = None
    for t in targets:
        if t >= lo and t <= hi and abs(v - t) <= snap and (best == None or abs(v - t) < abs(v - best)):
            best = t
        end
    end
    if best == None:
        return v
    end
    return best
end

# Polohy obdelniku w x h u nektere hrany umistenych monitoru, co nejbliz navrhu (px, py)
function candidates(w, h, px, py, placed, snap):
    result = []
    for b in placed:
        c = min(MIN_CONTACT, h, b[3])
        lo = b[1] - h + c
        hi = b[1] + b[3] - c
        y = align(clamp(py, lo, hi), [b[1], b[1] + b[3] - h, b[1] + (b[3] - h) // 2], lo, hi, snap)
        result.append([b[0] - w, y])
        result.append([b[0] + b[2], y])
        c = min(MIN_CONTACT, w, b[2])
        lo = b[0] - w + c
        hi = b[0] + b[2] - c
        x = align(clamp(px, lo, hi), [b[0], b[0] + b[2] - w, b[0] + (b[2] - w) // 2], lo, hi, snap)
        result.append([x, b[1] - h])
        result.append([x, b[1] + b[3]])
    end
    return result
end

function place(w, h, px, py, placed, snap):
    if len(placed) == 0:
        return [px, py]
    end
    best = None
    dist = 0
    for p in candidates(w, h, px, py, placed, snap):
        r = [p[0], p[1], w, h]
        hit = False
        for q in placed:
            if overlaps(r, q):
                hit = True
                break
            end
        end
        if hit:
            continue
        end
        d = (p[0] - px) * (p[0] - px) + (p[1] - py) * (p[1] - py)
        if best == None or d < dist:
            best = p
            dist = d
        end
    end
    if best == None:
        # vpravo od celku je misto vzdy
        right = max([q[0] + q[2] for q in placed])
        top = min([q[1] for q in placed])
        return [right, top]
    end
    return best
end

# Levy horni roh celku na 0,0
function normalize(pos):
    if len(pos) == 0:
        return {}
    end
    x0 = min([p[0] for p in pos.values()])
    y0 = min([p[1] for p in pos.values()])
    result = {}
    for name in pos.keys():
        result[name] = [pos[name][0] - x0, pos[name][1] - y0]
    end
    return result
end

# Monitory postupne v poradi order: prvni zustane, kazdy dalsi se prichyti k uz umistenym co nejbliz
# sve navrzene poloze. Vysledek {nazev: [x, y]} od 0,0.
function settle(sizes, proposals, order, snaps):
    placed = []
    result = {}
    for name in order:
        w = sizes[name][0]
        h = sizes[name][1]
        p = place(w, h, proposals[name][0], proposals[name][1], placed, snaps.get(name, 0))
        result[name] = p
        placed.append([p[0], p[1], w, h])
    end
    return normalize(result)
end

function center_dist(a, b):
    dx = (2 * a[0] + a[2]) - (2 * b[0] + b[2])
    dy = (2 * a[1] + a[3]) - (2 * b[1] + b[3])
    return dx * dx + dy * dy
end

# Kotva, pak ostatni od nejblizsich (stredy, pri shode podle nazvu)
function settle_order(rects, anchor):
    rest = sorted([n for n in rects.keys() if n != anchor])
    i = 1
    while i < len(rest):
        j = i
        while j > 0 and center_dist(rects[rest[j]], rects[anchor]) < center_dist(rects[rest[j - 1]], rects[anchor]):
            t = rest[j]
            rest[j] = rest[j - 1]
            rest[j - 1] = t
            j -= 1
        end
        i += 1
    end
    return [anchor] + rest
end

# Monitor, ktery se pri pretazeni `moving` nepohne: hlavni, jinak nejvetsi z ostatnich
function drop_anchor(rects, moving, primary):
    best = None
    for n in sorted(rects.keys()):
        if n == moving:
            continue
        end
        if n == primary:
            return n
        end
        if best == None or rects[n][2] * rects[n][3] > rects[best][2] * rects[best][3]:
            best = n
        end
    end
    return best
end

# Pustenim monitoru `moving` na (px, py): nove polohy vsech monitoru bez mezer a prekryvu
function drop(rects, moving, px, py, primary, snap):
    others = {}
    for n in rects.keys():
        if n != moving:
            others[n] = rects[n]
        end
    end
    if len(others) == 0:
        return {moving: [0, 0]}
    end
    order = settle_order(others, drop_anchor(rects, moving, primary)) + [moving]
    sizes = {}
    proposals = {}
    for n in rects.keys():
        sizes[n] = [rects[n][2], rects[n][3]]
        proposals[n] = [rects[n][0], rects[n][1]]
    end
    proposals[moving] = [px, py]
    return settle(sizes, proposals, order, {moving: snap})
end

# Polohy zapnutych monitoru konfigurace znovu usadit (jina velikost po zmene rezimu, meritka nebo otoceni
# nesmi udelat mezeru ani prekryv); hlavni zustava
function resettle(config, primary):
    sizes = {}
    proposals = {}
    rects = {}
    for name in config.keys():
        c = config[name]
        if c["enabled"]:
            sizes[name] = config_size(c)
            proposals[name] = [c["x"], c["y"]]
            rects[name] = [c["x"], c["y"], sizes[name][0], sizes[name][1]]
        end
    end
    if len(rects) == 0:
        return config
    end
    anchor = primary
    if anchor not in rects:
        anchor = sorted(rects.keys())[0]
    end
    pos = settle(sizes, proposals, settle_order(rects, anchor), {})
    for name in pos.keys():
        config[name]["x"] = pos[name][0]
        config[name]["y"] = pos[name][1]
    end
    return config
end

# ---- plany rezimu ----------------------------------------------------------------------------------

function pick_primary(outs, rec, names, hint):
    if rec != None:
        name = names.get(rec.get("primary", ""))
        if name != None:
            return name
        end
    end
    if hint != "" and find(outs, hint) != None:
        return hint
    end
    for o in outs:
        if o["internal"]:
            return o["name"]
        end
    end
    return outs[0]["name"]
end

# Rozsirena plocha z monitoru `active`: ulozene polohy sady, jinak soucasne, monitory bez polohy
# (nove pripojene, vypnute) vpravo
function extend_config(store, outs, active, rec, names, primary):
    config = {}
    stored = {}
    if rec != None and type(rec.get("pos")) == "Dictionary":
        for k in rec["pos"].keys():
            p = rec["pos"][k]
            if k in names and type(p) == "List" and len(p) == 2 and type(p[0]) == "Int" and type(p[1]) == "Int":
                stored[names[k]] = p
            end
        end
    end
    have = {}
    right = 0
    for o in outs:
        if o["name"] not in active:
            config[o["name"]] = {"enabled": False}
            continue
        end
        c = settings_for(store, o)
        config[o["name"]] = c
        if o["name"] in stored:
            have[o["name"]] = stored[o["name"]]
        elif len(stored) == 0 and o["enabled"] and o["width"] > 0:
            have[o["name"]] = [o["x"], o["y"]]
        end
        if o["name"] in have:
            right = max(right, have[o["name"]][0] + config_size(c)[0])
        end
    end
    for name in active:
        c = config[name]
        if name in have:
            c["x"] = have[name][0]
            c["y"] = have[name][1]
        else:
            c["x"] = right
            c["y"] = 0
            right += config_size(c)[0]
        end
    end
    return resettle(config, primary)
end

# Zrcadleni: vsechny na 0,0; vzor je hlavni monitor, ostatni ve stejnem rezimu, jinak ve svem doporucenem
# s meritkem, aby logicka plocha pokryla vzor (obraz se zmensi cely, nic se neorizne; pri jinem pomeru
# stran zbyde pruh vpravo nebo dole)
function mirror_config(store, outs, primary):
    config = {}
    ref = settings_for(store, find(outs, primary))
    ref_size = config_size(ref)
    config[primary] = ref
    for o in outs:
        if o["name"] == primary:
            continue
        end
        c = {"enabled": True, "width": ref["width"], "height": ref["height"], "refresh": 0, "x": 0, "y": 0,
             "transform": ref["transform"], "scale": ref["scale"]}
        if has_mode(o, ref["width"], ref["height"], 0):
            c["refresh"] = best_refresh(o, ref["width"], ref["height"])
        else:
            mode = preferred(o)
            c["width"] = mode[0]
            c["height"] = mode[1]
            c["refresh"] = mode[2]
            c["transform"] = 0
            s = max(64, min(mode[0] * 256 // ref_size[0], mode[1] * 256 // ref_size[1]))
            c["scale"] = s * 1000 // 256
        end
        config[o["name"]] = c
    end
    return config
end

# Plan pro pripojene monitory: {"config", "primary", "mode"}; mode "" = ulozeny pro sadu, jinak rozsirit
function plan(store, outs, mode, hint):
    if len(outs) == 0:
        return None
    end
    found = find_set(store, outs)
    rec = found[0]
    names = found[1]
    if mode == "":
        mode = "extend"
        if rec != None and rec.get("mode") in MODES:
            mode = rec["mode"]
        end
    end
    internal = [o["name"] for o in outs if o["internal"]]
    external = [o["name"] for o in outs if not o["internal"]]
    if len(outs) == 1 or ((mode == "internal" or mode == "external") and (len(internal) == 0 or len(external) == 0)):
        mode = "extend"
    end
    primary = pick_primary(outs, rec, names, hint)
    if mode == "mirror":
        return {"config": mirror_config(store, outs, primary), "primary": primary, "mode": mode}
    end
    active = [o["name"] for o in outs]
    if mode == "internal":
        active = internal[:1]
        primary = active[0]
    elif mode == "external":
        active = external
        if primary not in active:
            primary = active[0]
        end
    end
    return {"config": extend_config(store, outs, active, rec, names, primary), "primary": primary, "mode": mode}
end

# Spravna konfigurace: kazdy monitor zna, aspon jeden zapnuty, zapnute bez mezer a prekryvu (zrcadleni:
# vsechny na stejnem miste)
function check_config(outs, config, mirror):
    rects = {}
    for o in outs:
        c = config.get(o["name"])
        if type(c) != "Dictionary" or type(c.get("enabled")) != "Bool":
            return "missing " + o["name"]
        end
        if not c["enabled"]:
            continue
        end
        for f in ["width", "height", "refresh", "x", "y", "transform", "scale"]:
            if type(c.get(f)) != "Int":
                return "bad " + f + " for " + o["name"]
            end
        end
        if not has_mode(o, c["width"], c["height"], c["refresh"]) or c["transform"] < 0 or c["transform"] > 7 or c["scale"] < 250 or c["scale"] > 4000:
            return "unsupported mode for " + o["name"]
        end
        s = config_size(c)
        rects[o["name"]] = [c["x"], c["y"], s[0], s[1]]
    end
    if len(rects) == 0:
        return "no display enabled"
    end
    if mirror:
        for r in rects.values():
            if r[0] != 0 or r[1] != 0:
                return "mirrored displays must be at 0,0"
            end
        end
        return ""
    end
    if not valid(rects):
        return "displays overlap or have a gap"
    end
    return ""
end

# ---- spojeni a pouziti -------------------------------------------------------------------------------

link = {"apply": None, "heads": None}

function on_wl(kind, handle, a, b):
    if kind == wl.OUTPUT_CONFIG_RESULT and link["apply"] != None:
        f = link["apply"]
        link["apply"] = None
        call f(a)
    elif (kind == wl.HEAD_NEW or kind == wl.HEAD_CHANGED or kind == wl.HEAD_REMOVED) and link["heads"] != None:
        call link["heads"](kind)
    end
    return 0
end

# Spojeni s kompozitorem; heads(f): f(druh) pri zmene monitoru. False = neni Wayland nebo pravo.
function connect(heads):
    link["heads"] = heads
    if not wl.on_event(on_wl) or not wl.connect(""):
        return False
    end
    call wl.roundtrip()
    return wl.has("zwlr_output_manager_v1") > 0
end

# Cela konfigurace jednou zmenou; done(1 ok / 0 odmitnuto / 2 zmena mezitim)
function apply(outs, config, done):
    if not wl.output_config_begin():
        call done(0)
        return False
    end
    for o in outs:
        c = config.get(o["name"])
        if c == None or not c["enabled"]:
            call wl.output_config_head(o["head"], False, 0, 0, 0, 0, 0, 0, 0)
        else:
            call wl.output_config_head(o["head"], True, c["width"], c["height"], c["refresh"], c["x"], c["y"],
                                       c["transform"], c["scale"])
        end
    end
    link["apply"] = done
    return wl.output_config_apply(False)
end
