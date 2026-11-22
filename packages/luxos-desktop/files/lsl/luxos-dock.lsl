# LuxOS - Dock pro relaci na Waylandu (1.1.0) misto Planku: plocha layer-shell dole uprostred z matneho skla,
# pripnute aplikace (~/.config/luxos/dock.conf, poprve prevzate z Planku) a bezici okna (wlr-foreign-toplevel),
# tecka pod bezici aplikaci, zvetseni ikon pod mysi, skryvani, cisla a prubeh z com.canonical.Unity.LauncherEntry.
#
# Klik = aktivovat okna aplikace nebo ji spustit, klik na aktivni aplikaci = minimalizovat, prostredni tlacitko =
# nove okno, prave = nabidka (Ponechat v Docku / Odebrat z Docku, Ukoncit), tazeni = jine poradi.
# Zvetseni (zaseknuta lupa v Planku, LuxOS 1.0.4): po odchodu mysi do 0,45 s pryc v kazdem smeru, pri navratu jde za
# mysi; snimek drazsi nez rozpocet (4 ms) zvetseni vypne. Bez animace Dock nebezi v zadnem casovaci.
#
# Rezimy skryvani (HIDE): none a dodge vyhradi misto u spodniho okraje (exkluzivni zona: okna se neotviraji pod Dockem,
# maximalizovane konci nad nim; design review 1.1.0), dodge navic uhne oknu, ktere na Dock uzivatel presune (ram
# zamereneho okna posila luxwm, pod jinym kompozitorem jen celoobrazovkovemu oknu z foreign-toplevel), autohide = skryty,
# dokud mys nenajede ke spodnimu okraji. Mimo autohide Dock hlasi luxwm i svou vysku (dock_zone) pro umisteni oken.
# Nad oknem (autohide, presunute okno) Dock kresli nepruhledny podklad misto skla z tapety, aby byl citelny nad
# cernym i bilym oknem.
#
# LUXOS_DOCK_DEBUG=1 vypisuje udalosti a cenu snimku (testy), LUXOS_DOCK_FRAME_BUDGET_US jiny rozpocet snimku.
load env, process
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load gio, cairo, pango
load luxos_layer as layer
load luxos_primary as primary
load luxos_luxwm as wm
load luxos_wl as wl
load luxos_material as material
load luxos_tokens as tokens
load luxos_apps as apps
load luxos_dock_model as model
load luxos_i18n as i18n
load luxos_text as text

ZOOM_IN_MS = 180
ZOOM_OUT_MS = 200
# pojistka: kdyby kompozitor prestal posilat snimky, zvetseni doskoci nejpozdeji tady (MOTION dock_zoom_leave = 450)
ZOOM_GUARD_MS = 380
HIDE_MS = 250
# pridani a odebrani ikony: sousedi se posunou, nova ikona naroste, odebrana zmizi (Plank ItemMoveTime)
MOVE_MS = 200
HIDE_DELAY_MS = 300
DRAG_START = 6
LABEL_H = 30
SIDE = 8
# mezera pod panelem: zadna, Dock lezi na spodnim okraji jako Plank s motivem WhiteSur
MARGIN = 0
BUDGET_SKIP = 4
BUDGET_FRAMES = 24
# barva tecky: vybrana barva motivu WhiteSur (#0860f2), naleha-li aplikace, posunuty odstin (UrgentHueShift 150)
INDICATOR = [0.031, 0.376, 0.949]
INDICATOR_URGENT = [0.949, 0.145, 0.031]

DEBUG = env.get("LUXOS_DOCK_DEBUG", "") != ""
BUDGET_US = 4000
if env.get("LUXOS_DOCK_FRAME_BUDGET_US", "") != "":
    BUDGET_US = Int(env.get("LUXOS_DOCK_FRAME_BUDGET_US", ""))
end

conf_dir = glib.user_config_dir() + "/luxos"
conf_path = conf_dir + "/dock.conf"
trash_dir = glib.user_data_dir() + "/Trash/files"

conf = {}
conf_text = ""
items = []              # polozky Docku zleva: slovniky (viz new_item)
windows = {}            # handle okna -> {"app_id", "key", "state", "seq"}
running_order = []      # klice nepripnutych aplikaci v poradi spusteni
app_keys = {}           # app_id -> klic polozky
entries = {}            # id .desktop -> LauncherEntry {"count", "count-visible", "progress", ..., "sender"}
geo = {}
output = {"name": "", "w": 0, "h": 0, "monitor": 0}
view = {"blur": material.compositor_blur(), "hovered": False, "px": 0.0, "py": 0.0, "press": None, "dragging": False, "menu_open": False,
    "menu_key": "", "zoom_on": True, "trash_full": False, "region": [], "seq": 0,
    "strip": None, "light": True, "over_window": False}
anims = {"zoom": [0.0, 0.0, 0.0, 0, 1], "hide": [0.0, 0.0, 0.0, 0, 1], "move": [1.0, 1.0, 1.0, 0, 1]}
# posun ikon: kreslene polohy z posledniho snimku (klic -> [levy okraj od stredu okna, velikost], panel [x, w]),
# polohy na zacatku posunu a odebirane polozky [polozka, levy okraj, velikost]
move = {"drawn": {}, "drawn_panel": None, "from": {}, "panel": None, "leaving": [], "hold": False}
timers = {"tick": 0, "hide": 0, "guard": 0}
costs = []
window = 0
menu = {}
tick_record = 0
# zamerene okno od luxwm (ram v souradnicich rozlozeni) a posledni vyska poslana jako dock_zone
focus = {"known": False, "frame": []}
zone = {"sent": None}

# Radek s casem v ms (monotonni hodiny, jako time.monotonic v testech)
function debug(line):
    if DEBUG:
        print String(glib.monotonic_time() // 1000) + " " + line
    end
    return 0
end

function now():
    return glib.monotonic_time()
end

# ---- nastaveni ----

function load_conf():
    global conf, conf_text
    conf_text = glib.read_text(conf_path)
    conf = model.parse_conf(conf_text)
    return 0
end

function save_conf():
    global conf_text
    conf_text = model.conf_text(conf)
    call glib.mkdir_p(conf_dir)
    call glib.write_atomic(conf_path, conf_text)
    return 0
end

function dconf_read(key):
    program = glib.find_program_in_path("dconf")
    if program == "":
        return ""
    end
    result = None
    safe:
        result = process.capture_result(program, ["read", "/net/launchpad/plank/docks/dock1/" + key])
    end
    if result == None or not result["ok"]:
        return ""
    end
    return result["stdout"].strip()
end

# Id .desktop souboru, kdyz ho GIO pod timto id najde (prenositelne mezi systemy a prekrytimi
# /var/lib/luxos/apps), jinak cesta
function item_entry(file):
    desktop_id = apps.base_name(file)
    if apps.find(desktop_id) != 0:
        return desktop_id
    end
    return file
end

# Prvni spusteni: polozky, velikost, zvetseni a skryvani z Planku (skel i nastaveni uzivatele z LuxOS na X11)
function migrate_plank():
    launchers = glib.user_config_dir() + "/plank/dock1/launchers"
    names = [name for name in glib.list_dir(launchers) if name.endswith(".dockitem")]
    if len(names) == 0:
        return False
    end
    order = model.plank_order(dconf_read("dock-items"), names)
    found = []
    for name in order:
        item = model.item_for_launcher(model.dockitem_launcher(glib.read_text(launchers + "/" + name)))
        if item == "trash":
            found.append(item)
        elif item != "":
            found.append(item_entry(item))
        end
    end
    conf["items"] = found
    size = dconf_read("icon-size")
    if text.is_digits(size):
        conf["icon_size"] = max(24, min(128, Int(size)))
    end
    if dconf_read("zoom-enabled") == "false":
        conf["zoom"] = 100
    else:
        percent = dconf_read("zoom-percent")
        if text.is_digits(percent):
            conf["zoom"] = max(100, min(200, Int(percent)))
        end
    end
    conf["hide"] = model.plank_hide(dconf_read("hide-mode"))
    return True
end

# ---- polozky ----

function new_item(key, info, pinned):
    return {"key": key, "info": info, "pinned": pinned, "windows": [], "app_id": "", "icon": 0, "big": 0,
        "name": "", "desktop_id": ""}
end

function item_desktop_id(item):
    if item["key"].startswith("app:"):
        return item["app_id"] + ".desktop"
    end
    return apps.base_name(item["key"])
end

function resolve(app_id):
    key = app_keys.get(app_id)
    if key != None:
        return key
    end
    info = apps.match(app_id)
    key = "app:" + app_id
    if info != 0:
        key = apps.path(info)
    end
    app_keys[app_id] = key
    return key
end

function free_icons(item):
    for slot in ["icon", "big"]:
        if item[slot] != 0:
            call cairo.surface_destroy(item[slot])
            item[slot] = 0
        end
    end
    return 0
end

function load_icon(item, size, scale):
    if item["key"] == "trash":
        name = "user-trash"
        if view["trash_full"]:
            name = "user-trash-full"
        end
        return apps.icon_named(name, size, scale)
    end
    icon = 0
    if item["info"] != 0:
        icon = apps.own_icon(item["info"], size, scale)
    elif item["app_id"] != "":
        icon = apps.icon_named(item["app_id"].lower(), size, scale)
    end
    if icon == 0:
        icon = letter_icon(item_name(item), size, scale)
    end
    return icon
end

# Aplikace bez ikony: neutralni zaobleny ctverec s prvnim pismenem nazvu (sablona ikon 56/64, polomer 13/64),
# ne obecne ozubene kolo, ktere vypadalo jako Nastaveni
function letter_icon(name, size, scale):
    surface = cairo.image_surface_create(cairo.FORMAT_ARGB32, size * scale, size * scale)
    call material.set_device_scale(surface, scale)
    cr = cairo.create(surface)
    s = Float(size)
    plate = s * 56.0 / 64.0
    x = (s - plate) / 2.0
    y = x - s / 64.0
    radius = s * 13.0 / 64.0
    shade = cairo.pattern_create_linear(0.0, y, 0.0, y + plate)
    call cairo.pattern_add_color_stop_rgba(shade, 0.0, 0.96, 0.96, 0.97, 1.0)
    call cairo.pattern_add_color_stop_rgba(shade, 1.0, 0.84, 0.85, 0.87, 1.0)
    call cairo.set_source(cr, shade)
    call cairo.rounded_rectangle(cr, x, y, plate, plate, radius)
    call cairo.fill(cr)
    call cairo.pattern_destroy(shade)
    # spodni stin 2 px a jemny okraj jako u ostatnich ikon (svetlo zleva shora)
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.12)
    call cairo.set_line_width(cr, 1.0)
    call cairo.rounded_rectangle(cr, x + 0.5, y + 0.5, plate - 1.0, plate - 1.0, radius - 0.5)
    call cairo.stroke(cr)
    letter = name.strip()[:1].upper()
    if letter != "":
        font = tokens.FONT["family"] + " Semi-Bold " + String(max(6, Int(plate * 0.42)))
        dim = pango.text_size(cr, letter, font)
        call cairo.set_source_rgba(cr, 0.27, 0.29, 0.33, 1.0)
        call pango.draw_text(cr, (s - Float(dim[0])) / 2.0, y + (plate - Float(dim[1])) / 2.0, letter, font)
    end
    call cairo.destroy(cr)
    call cairo.surface_flush(surface)
    return surface
end

function load_icons(item):
    call free_icons(item)
    scale = gtk.widget_scale_factor(window)
    item["icon"] = load_icon(item, geo["size"], scale)
    if view["zoom_on"]:
        item["big"] = load_icon(item, geo["zoom_size"], scale)
    end
    return 0
end

function item_name(item):
    if item["key"] == "trash":
        return i18n.T("Trash")
    end
    if item["info"] != 0:
        return apps.name(item["info"])
    end
    for handle in item["windows"]:
        title = wl.toplevel_title(handle)
        if title != "":
            return title
        end
    end
    return item["app_id"]
end

# Pripnute v poradi nastaveni (chybejici .desktop se preskoci), za nimi bezici nepripnute v poradi spusteni
function sync_items():
    global items
    old = {}
    for item in items:
        old[item["key"]] = item
    end
    wanted = []
    keys = []
    for entry in conf["items"]:
        key = "trash"
        info = 0
        if entry != "trash":
            info = apps.find_entry(entry)
            if info == 0:
                continue
            end
            key = apps.path(info)
        end
        if not (key in keys):
            keys.append(key)
            wanted.append([key, info, True])
        end
    end
    for key in List(running_order):
        alive = False
        for handle in windows:
            if windows[handle]["key"] == key:
                alive = True
            end
        end
        if not alive:
            call running_order.remove(key)
        elif not (key in keys):
            keys.append(key)
            info = 0
            if not key.startswith("app:"):
                info = apps.find(key)
            end
            wanted.append([key, info, False])
        end
    end
    fresh = []
    for spec in wanted:
        item = old.get(spec[0])
        if item == None:
            item = new_item(spec[0], spec[1], spec[2])
        end
        item["pinned"] = spec[2]
        item["windows"] = []
        fresh.append(item)
    end
    for handle in windows:
        w = windows[handle]
        for item in fresh:
            if item["key"] == w["key"]:
                item["windows"].append(handle)
                item["app_id"] = w["app_id"]
            end
        end
    end
    changed = len(fresh) != len(items)
    if not changed:
        for i in range(len(fresh)):
            if fresh[i]["key"] != items[i]["key"]:
                changed = True
            end
        end
    end
    if changed and len(items) > 0 and window != 0:
        call start_move(keys)
    else:
        for item in items:
            if not (item["key"] in keys):
                call free_icons(item)
            end
        end
    end
    items = fresh
    for item in items:
        item["name"] = item_name(item)
        item["desktop_id"] = item_desktop_id(item)
    end
    if changed:
        call debug("items " + text.join([item["key"] for item in items], " "))
        call update_geometry()
    end
    call queue_redraw()
    return 0
end

# ---- rozmery ----

function update_output():
    monitors = layer.monitors()
    if len(monitors) == 0:
        return 0
    end
    if output["monitor"] not in monitors:
        output["monitor"] = monitors[0]
    end
    g = layer.monitor_geometry(output["monitor"])
    output["w"] = g[2]
    output["h"] = g[3]
    output["name"] = ""
    if wl.available():
        for o in wl.outputs():
            og = wl.output_geometry(o)
            if og[0] == g[0] and og[1] == g[1]:
                output["name"] = wl.output_name(o)
            end
        end
    end
    view["strip"] = None
    return 0
end

function update_geometry():
    n = len(items)
    size = conf["icon_size"]
    view["zoom_on"] = view["zoom_on"] and conf["zoom"] > 100
    zoom = conf["zoom"]
    if not view["zoom_on"]:
        zoom = 100
    end
    # sirsi Dock nez vystup: mensi ikony (jako Plank)
    if output["w"] > 0:
        while size > 24 and model.panel_width(n, size, size // 6, size // 4) + model.max_zoom_extra(n, size, size // 6, size // 4, zoom) + 2 * SIDE > output["w"]:
            size -= 4
        end
    end
    old_size = geo.get("size", 0)
    old_zoom = geo.get("zoom", 0)
    geo["size"] = size
    geo["zoom"] = zoom
    geo["zoom_size"] = (size * zoom + 99) // 100
    # rozestup jako Plank s motivem LuxOS na X11 (48 px ikony po 62 px)
    geo["gap"] = size * 7 // 24
    geo["pad"] = size // 4
    geo["top"] = size // 6
    geo["bottom"] = size // 5
    geo["panel_h"] = geo["top"] + size + geo["bottom"]
    geo["zoom_h"] = geo["zoom_size"] - size
    geo["base_w"] = model.panel_width(n, size, geo["gap"], geo["pad"])
    geo["width"] = geo["base_w"] + model.max_zoom_extra(n, size, geo["gap"], geo["pad"], zoom) + 2 * SIDE
    # behem posunu se plocha nezmensi (odebirana ikona by se orizla), az po nem (anims_done)
    if anims["move"][3] != 0:
        geo["width"] = max(geo["width"], geo.get("old_width", 0))
    end
    geo["old_width"] = geo["width"]
    geo["height"] = LABEL_H + geo["zoom_h"] + geo["panel_h"] + MARGIN
    geo["x0"] = (geo["width"] - geo["base_w"]) // 2
    geo["panel_y"] = geo["height"] - MARGIN - geo["panel_h"]
    for item in items:
        if item["icon"] == 0 or size != old_size or zoom != old_zoom:
            call load_icons(item)
        end
    end
    view["strip"] = None
    view["region"] = []
    centers = [geo["x0"] + geo["pad"] + size // 2 + i * (size + geo["gap"]) for i in range(n)]
    call debug("slots " + String(geo["width"]) + " " + String(geo["height"]) + " " + text.join(centers, " "))
    if window != 0:
        call gtk.widget_set_size_request(window, geo["width"], geo["height"])
        call gtk.window_resize(window, geo["width"], geo["height"])
        if conf["hide"] != "autohide":
            call layer.set_exclusive_zone(window, MARGIN + geo["panel_h"])
        else:
            call layer.set_exclusive_zone(window, 0)
        end
    end
    call send_zone()
    return 0
end

# Panel Docku na vystupu v souradnicich rozlozeni (bez zvetseni a skryti)
function panel_area():
    if output["monitor"] == 0 or len(geo) == 0:
        return []
    end
    g = layer.monitor_geometry(output["monitor"])
    return [g[0] + (g[2] - geo["base_w"]) // 2, g[1] + g[3] - MARGIN - geo["panel_h"], geo["base_w"], geo["panel_h"] + MARGIN]
end

function send_zone():
    if len(geo) == 0 or output["name"] == "" or not wm.connected():
        return 0
    end
    want = [output["name"], 0]
    if conf["hide"] != "autohide":
        want[1] = geo["panel_h"] + MARGIN
    end
    if want != zone["sent"]:
        zone["sent"] = want
        call wm.request({"cmd": "dock_zone", "output": want[0], "height": want[1]}, None)
        call debug("zone " + want[0] + " " + String(want[1]))
    end
    return 0
end

function current_layout():
    z = anims["zoom"][0]
    if not view["zoom_on"]:
        z = 0.0
    end
    return model.layout(len(items), geo["size"], geo["gap"], geo["pad"], geo["zoom"], z, view["px"], geo["x0"])
end

function hide_offset():
    return Int(anims["hide"][0] * Float(geo["panel_h"] + MARGIN + 2) + 0.5)
end

# Viditelny Dock: panel a zvetsene ikony [x, y, w, h] (bez popisku), jen celociselne
function dock_rect(lay):
    dy = hide_offset()
    top = geo["panel_y"]
    if view["zoom_on"]:
        for z in lay[1]:
            top = min(top, Int(Float(geo["panel_y"] + geo["top"] + geo["size"]) - z))
        end
    end
    x = Int(lay[2])
    return [x, top + dy, Int(lay[2] + lay[3] + 0.999) - x, geo["height"] - top]
end

# Oblast pro mys = viditelny Dock: kliknuti nad nim (i do mista zvetseni, kdyz zrovna neni) jde oknum pod nim.
# Se zvetsenim panel a nad nim uzsi obdelnik ikon: luxcomp dava sklo jen panelu, ikony vystoupi nad nej (Plank).
function update_region(lay):
    py = geo["panel_y"] + hide_offset()
    if anims["hide"][0] >= 1.0 and not view["hovered"]:
        region = [[geo["x0"], geo["height"] - 2, geo["base_w"], 2]]
    elif anims["zoom"][0] > 0.0 or view["hovered"]:
        r = dock_rect(lay)
        region = [[r[0], py, r[2], geo["panel_h"] + MARGIN]]
        if r[1] < py and len(items) > 0:
            x = Int(lay[0][0])
            region.append([x, r[1], Int(lay[0][-1] + lay[1][-1] + 0.999) - x, py - r[1]])
        end
    else:
        region = [[geo["x0"], py, geo["base_w"], geo["panel_h"] + MARGIN]]
    end
    if region != view["region"]:
        view["region"] = region
        call gtk.widget_input_rects(window, region)
    end
    return 0
end

# Cela plocha: popisek krajni ikony siri nez Dock a jeho zbytek by po odchodu mysi zustal v bufferu;
# plocha je jen o rozsireni zvetsenim a SIDE sirsi nez Dock
function queue_redraw():
    if window != 0 and len(geo) > 0:
        call gtk.widget_queue_draw_area(window, 0, 0, geo["width"], geo["height"])
    end
    return 0
end

# ---- animace ----

function ease(t):
    u = 1.0 - t
    return 1.0 - u * u * u
end

function step_anims(t):
    active = False
    for name in ["zoom", "hide", "move"]:
        a = anims[name]
        if a[3] != 0:
            f = Float(t - a[3]) / Float(a[4])
            if f >= 1.0:
                a[0] = a[2]
                a[3] = 0
                call debug(name + "-end " + String(a[0]))
            else:
                a[0] = a[1] + (a[2] - a[1]) * ease(max(0.0, f))
                active = True
            end
        end
    end
    return active
end

function on_tick(widget, clock):
    active = step_anims(now())
    call queue_redraw()
    if not active:
        timers["tick"] = 0
        call anims_done()
        return False
    end
    return True
end

function ensure_tick():
    global tick_record
    if timers["tick"] == 0 and window != 0:
        if tick_record == 0:
            tick_record = glib.record_new(on_tick, 2)
        end
        timers["tick"] = gtk.widget_add_tick_callback(window, tick_record)
    end
    return 0
end

# Delka podle zbyvajici cesty: obraceni v pulce trva pulku
function animate(name, target, ms):
    a = anims[name]
    if a[2] == target and (a[3] != 0 or a[0] == target):
        return 0
    end
    a[1] = a[0]
    a[2] = target
    a[4] = max(1000, Int(Float(ms) * 1000.0 * abs(target - a[0])))
    a[3] = now()
    call ensure_tick()
    return 0
end

# Posun od poloh posledniho snimku: zmena uprostred posunu pokracuje odtud, ne skokem
function start_move(keys):
    call drop_leaving()
    move["from"] = move["drawn"]
    move["panel"] = move["drawn_panel"]
    for item in items:
        if not (item["key"] in keys):
            old = move["drawn"].get(item["key"])
            if old != None:
                move["leaving"].append([item, old[0], old[1]])
            else:
                call free_icons(item)
            end
        end
    end
    move["hold"] = True
    anims["move"] = [0.0, 0.0, 0.0, 0, 1]
    call animate("move", 1.0, MOVE_MS)
    return 0
end

function drop_leaving():
    for gone in move["leaving"]:
        call free_icons(gone[0])
    end
    move["leaving"] = []
    return 0
end

function anims_done():
    if move["hold"] and anims["move"][3] == 0:
        move["hold"] = False
        call drop_leaving()
        call update_geometry()
    end
    # rozpocet snimku prekroceny: Dock bez zvetseni az po dobehu, aby se plocha nemenila pod mysi
    if view.get("zoom_off_pending", False) and anims["zoom"][0] == 0.0:
        view["zoom_off_pending"] = False
        view["zoom_on"] = False
        call update_geometry()
    end
    call update_region(current_layout())
    return 0
end

function check_budget():
    if len(costs) < BUDGET_SKIP + BUDGET_FRAMES:
        return 0
    end
    sample = costs[BUDGET_SKIP:]
    call sample.sort()
    p90 = sample[len(sample) * 9 // 10]
    print "luxos-dock: zoom frame cost p50 " + String(sample[len(sample) // 2]) + " us, p90 " + String(p90) + " us, max " + String(sample[-1]) + " us"
    if p90 > BUDGET_US:
        print "luxos-dock: magnification off (frame budget " + String(BUDGET_US) + " us)"
        view["zoom_off_pending"] = True
    end
    costs.append(-1)
    return 0
end

# ---- skryvani ----

function want_hidden():
    if view["hovered"] or view["menu_open"] or view["dragging"]:
        return False
    end
    if conf["hide"] == "autohide":
        return True
    end
    if conf["hide"] == "dodge" and focus["known"]:
        return over_window()
    end
    # bez luxwm: maximalizovane okno konci nad vyhrazenym mistem, uhnout jen cele obrazovce
    if conf["hide"] == "dodge":
        for handle in windows:
            state = windows[handle]["state"]
            if (state & wl.STATE_ACTIVATED) != 0 and (state & wl.STATE_MINIMIZED) == 0 and (state & wl.STATE_FULLSCREEN) != 0:
                return True
            end
        end
    end
    return False
end

# Zamerene okno (ram od luxwm) zasahuje do panelu Docku
function over_window():
    a = panel_area()
    f = focus["frame"]
    return focus["known"] and len(a) == 4 and len(f) == 4 and f[0] < a[0] + a[2] and a[0] < f[0] + f[2] and f[1] < a[1] + a[3] and a[1] < f[1] + f[3]
end

function hide_now(unused):
    timers["hide"] = 0
    if want_hidden():
        call animate("hide", 1.0, HIDE_MS)
    end
    return False
end

function update_hide(delay):
    if timers["hide"] != 0:
        call glib.source_remove(timers["hide"])
        timers["hide"] = 0
    end
    if not want_hidden():
        call animate("hide", 0.0, HIDE_MS)
    elif delay:
        timers["hide"] = glib.timeout_add_data(HIDE_DELAY_MS, hide_now, 0)
    else:
        call animate("hide", 1.0, HIDE_MS)
    end
    return 0
end

# ---- kresleni ----

function dark_mode():
    return glib.read_text(conf_dir + "/appearance").strip() == "dark"
end

function glass_strip():
    if view["strip"] == None:
        view["strip"] = []
        if output["w"] > 0:
            x = (output["w"] - geo["width"]) // 2
            y = output["h"] - MARGIN - geo["panel_h"]
            hit = material.strip(output["name"], output["w"], output["h"], x, y, geo["width"], geo["panel_h"], 0, -1, gtk.widget_scale_factor(window))
            if hit != None:
                view["strip"] = hit
                view["light"] = hit[1]
            end
        end
        if len(view["strip"]) == 0:
            view["light"] = not dark_mode()
        end
    end
    return view["strip"]
end

function draw_panel(cr, x, y, w, h):
    if view["blur"]:
        # rozmazane pozadi kresli kompozitor pod vstupni oblasti (panel); tonovani, odlesk nahore a obrys: nad bilym
        # oknem je svetle sklo bile a panel by bez obrysu zmizel
        view["light"] = not dark_mode()
        call material.paint_tint(cr, "dock", dark_mode(), True, x, y, w, h, True)
        return 0
    end
    radius = tokens.radius_of("dock")
    strip = glass_strip()
    call cairo.save(cr)
    call cairo.rounded_rectangle(cr, x, y, w, h, radius)
    call cairo.clip(cr)
    # nad oknem (bez rozmazani v kompozitoru) nepruhledny material, sklo z tapety by lhalo
    if view["over_window"]:
        call cairo.set_source_color(cr, tokens.rgb01(tokens.material("dock", not view["light"], False)))
        call cairo.paint(cr)
    elif len(strip) > 0:
        call cairo.set_source_surface(cr, strip[0], 0, y)
        call cairo.paint(cr)
    else:
        call cairo.set_source_color(cr, tokens.rgb01(tokens.material("dock", not view["light"], False)))
        call cairo.paint(cr)
    end
    call cairo.restore(cr)
    edge = tokens.COLORS["card_edge"]
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, edge[3])
    call cairo.set_line_width(cr, 1.0)
    call cairo.rounded_rectangle(cr, x + 0.5, y + 0.5, w - 1.0, h - 1.0, radius - 0.5)
    call cairo.stroke(cr)
    return 0
end

function draw_icon(cr, item, x, y, z):
    s = Float(geo["size"])
    surface = item["icon"]
    native = s
    if abs(z - s) >= 0.5 and item["big"] != 0:
        surface = item["big"]
        native = Float(geo["zoom_size"])
    end
    if surface == 0:
        return 0
    end
    call cairo.save(cr)
    if abs(z - native) < 0.5:
        call cairo.set_source_surface(cr, surface, Float(Int(x + 0.5)), Float(Int(y + 0.5)))
    else:
        call cairo.translate(cr, x, y)
        call cairo.scale(cr, z / native, z / native)
        call cairo.set_source_surface(cr, surface, 0.0, 0.0)
        call gtk.cairo_source_filter(cr, gtk.CAIRO_FILTER_BILINEAR)
    end
    if view["dragging"] and view["press"] != None and view["press"][0] == item["key"]:
        call cairo.paint_with_alpha(cr, 0.7)
    else:
        call cairo.paint(cr)
    end
    call cairo.restore(cr)
    return 0
end

function draw_badge(cr, entry, x, y, z):
    if entry.get("count-visible", False) and entry.get("count", 0) > 0:
        count = entry["count"]
        label = String(count)
        if count > 99:
            label = "99+"
        end
        font = tokens.FONT["family"] + " Bold 9"
        size = pango.text_size(cr, label, font)
        h = Float(size[1]) + 2.0
        w = max(h, Float(size[0]) + 10.0)
        bx = x + z - w + 4.0
        by = y - 4.0
        call cairo.set_source_color(cr, tokens.rgb01(tokens.COLORS["error"]))
        call cairo.rounded_rectangle(cr, bx, by, w, h, h / 2.0)
        call cairo.fill(cr)
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 1.0)
        call pango.draw_text(cr, bx + (w - Float(size[0])) / 2.0, by + 1.0, label, font)
    end
    if entry.get("progress-visible", False):
        p = max(0.0, min(1.0, Float(entry.get("progress", 0.0))))
        bw = z - 8.0
        by = y + z - 7.0
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.75)
        call cairo.rounded_rectangle(cr, x + 4.0, by, bw, 5.0, 2.5)
        call cairo.fill(cr)
        if p > 0.0:
            call cairo.set_source_color(cr, tokens.rgb01(tokens.COLORS["accent"]))
            call cairo.rounded_rectangle(cr, x + 4.0, by, max(5.0, bw * p), 5.0, 2.5)
            call cairo.fill(cr)
        end
    end
    return 0
end

# Popisek nad ikonou: footnote medium na tmave pilulce (polomer s, odsazeni 10 x 5), 8 px nad ikonou
function draw_label(cr, name, center, icon_top):
    font = tokens.FONT["family"] + " Medium 9"
    size = pango.text_size(cr, name, font)
    w = Float(size[0]) + 20.0
    h = Float(size[1]) + 10.0
    x = max(2.0, min(Float(geo["width"]) - w - 2.0, center - w / 2.0))
    y = max(1.0, icon_top - h - 8.0)
    call cairo.set_source_color(cr, tokens.rgb01(tokens.material("menu", True, False)))
    call cairo.rounded_rectangle(cr, x, y, w, h, tokens.RADIUS["s"])
    call cairo.fill(cr)
    call cairo.set_source_color(cr, tokens.rgb01(tokens.color("fg", True)))
    call pango.draw_text(cr, x + 10.0, y + 5.0, name, font)
    return 0
end

# Nabidka Docku (xdg_popup) dostane od kompozitoru material menu; barvy a polozky z tokenu
function apply_menu_css():
    text = tokens.menu_css(dark_mode(), view["blur"])
    if view.get("menu_css", 0) == 0:
        view["menu_css"] = gtk.css_load(text)
    else:
        call gtk.css_set(view["menu_css"], text)
    end
    return 0
end

# Tecka bezici aplikace jako Plank s motivem WhiteSur v relaci X11 (DockTheme.create_indicator): zarici kruh
# o polomeru ctvrtiny ikony (IndicatorSize 5) se stredem na spodnim okraji panelu, spodni pulka za okrajem
function draw_indicator(cr, cx, cy, radius, c):
    g = cairo.pattern_create_radial(cx, cy, 0.0, cx, cy, radius)
    call cairo.pattern_add_color_stop_rgba(g, 0.0, 1.0, 1.0, 1.0, 1.0)
    for stop in [[0.1, 1.0], [0.2, 0.6], [0.25, 0.25], [0.5, 0.15], [1.0, 0.0]]:
        call cairo.pattern_add_color_stop_rgba(g, stop[0], c[0], c[1], c[2], stop[1])
    end
    call cairo.set_source(cr, g)
    call cairo.arc(cr, cx, cy, radius, 0.0, 2.0 * cairo.PI)
    call cairo.fill(cr)
    call cairo.pattern_destroy(g)
    return 0
end

function hovered_index(lay):
    if not view["hovered"] or view["dragging"] or view["menu_open"]:
        return -1
    end
    return model.item_at(lay, geo["gap"], view["px"])
end

function on_draw(cr, widget):
    started = now()
    call cairo.save(cr)
    call cairo.set_operator(cr, cairo.OPERATOR_CLEAR)
    call cairo.paint(cr)
    call cairo.restore(cr)
    if len(items) == 0:
        return True
    end
    lay = current_layout()
    dy = hide_offset()
    py = geo["panel_y"] + dy
    half = Float(geo["width"]) / 2.0
    moving = anims["move"][3] != 0
    t = anims["move"][0]
    panel = [lay[2], lay[3]]
    if moving and move["panel"] != None:
        panel = [half + move["panel"][0] + (lay[2] - half - move["panel"][0]) * t, move["panel"][1] + (lay[3] - move["panel"][1]) * t]
    end
    move["drawn_panel"] = [panel[0] - half, panel[1]]
    call draw_panel(cr, panel[0], py, panel[1], geo["panel_h"])
    base = Float(py + geo["top"] + geo["size"])
    hover = hovered_index(lay)
    for gone in move["leaving"]:
        z = gone[2] * (1.0 - t)
        if z >= 1.0:
            call draw_icon(cr, gone[0], half + gone[1] + (gone[2] - z) / 2.0, base - z, z)
        end
    end
    drawn = {}
    for i in range(len(items)):
        item = items[i]
        z = lay[1][i]
        x = lay[0][i]
        if moving:
            old = move["from"].get(item["key"])
            if old == None:
                # nova ikona naroste ze stredu sveho mista
                x = x + z * (1.0 - t) / 2.0
                z = z * t
            else:
                x = half + old[0] + (x - half - old[0]) * t
                z = old[1] + (z - old[1]) * t
            end
        end
        drawn[item["key"]] = [x - half, z]
        if z < 1.0:
            continue
        end
        call draw_icon(cr, item, x, base - z, z)
        entry = entries.get(item["desktop_id"])
        if entry != None:
            call draw_badge(cr, entry, x, base - z, z)
        end
        if len(item["windows"]) > 0:
            color = INDICATOR
            if entry != None and entry.get("urgent", False):
                color = INDICATOR_URGENT
            end
            call draw_indicator(cr, x + z / 2.0, Float(py + geo["panel_h"]), Float(geo["size"]) / 4.0, color)
        end
    end
    move["drawn"] = drawn
    if hover >= 0 and not moving:
        call draw_label(cr, items[hover]["name"], lay[0][hover] + lay[1][hover] / 2.0, base - lay[1][hover])
    end
    call update_region(lay)
    if timers["tick"] != 0 and anims["zoom"][3] != 0:
        cost = now() - started
        call debug("frame " + String(cost) + " " + String(anims["zoom"][0]))
        if len(costs) < BUDGET_SKIP + BUDGET_FRAMES:
            costs.append(cost)
            call check_budget()
        end
    end
    return True
end

# ---- mys ----

function pointer(event):
    xy = gtk.event_coords(event)
    view["px"] = xy[0]
    view["py"] = xy[1]
    return 0
end

function on_enter(event, widget):
    call pointer(event)
    if not view["hovered"]:
        call debug("hover 1")
    end
    view["hovered"] = True
    if timers["guard"] != 0:
        call glib.source_remove(timers["guard"])
        timers["guard"] = 0
    end
    if view["zoom_on"] and not view["menu_open"]:
        call animate("zoom", 1.0, ZOOM_IN_MS)
    end
    call update_hide(False)
    call queue_redraw()
    return False
end

function zoom_guard(unused):
    timers["guard"] = 0
    if not view["hovered"] and not view["menu_open"] and anims["zoom"][0] > 0.0:
        call debug("zoom-guard")
        anims["zoom"] = [0.0, 0.0, 0.0, 0, 1]
        call queue_redraw()
    end
    return False
end

function leave():
    call animate("zoom", 0.0, ZOOM_OUT_MS)
    if timers["guard"] == 0:
        timers["guard"] = glib.timeout_add_data(ZOOM_GUARD_MS, zoom_guard, 0)
    end
    call update_hide(True)
    call queue_redraw()
    return 0
end

function on_leave(event, widget):
    if view["dragging"]:
        return False
    end
    if view["hovered"]:
        call debug("hover 0")
    end
    view["hovered"] = False
    if not view["menu_open"]:
        call leave()
    end
    return False
end

function item_index(key):
    for i in range(len(items)):
        if items[i]["key"] == key:
            return i
        end
    end
    return -1
end

# Tazeni: polozka se presouva mezi svymi (pripnute mezi pripnutymi, bezici mezi bezicimi)
function drag_to(x):
    source = item_index(view["press"][0])
    if source < 0:
        return 0
    end
    target = model.item_at(current_layout(), geo["gap"], x)
    if target < 0 or target == source or items[target]["pinned"] != items[source]["pinned"]:
        return 0
    end
    item = items.pop(source)
    items.insert(target, item)
    return 0
end

function on_motion(event, widget):
    call pointer(event)
    if not view["hovered"]:
        # pohyb bez vstupu (vstup se ztratil): stejne jako vstup
        call on_enter(event, widget)
    end
    press = view["press"]
    if press != None and not view["dragging"] and abs(view["px"] - press[1]) > DRAG_START:
        view["dragging"] = True
        call debug("drag " + press[0])
    end
    if view["dragging"]:
        call drag_to(view["px"])
    end
    call queue_redraw()
    return False
end

function on_press(event, widget):
    call pointer(event)
    index = model.item_at(current_layout(), geo["gap"], view["px"])
    if index < 0:
        return True
    end
    button = gtk.event_button(event)
    if button == 1:
        view["press"] = [items[index]["key"], view["px"]]
    elif button == 3:
        call open_menu(items[index])
    end
    return True
end

function finish_drag():
    view["dragging"] = False
    order = [item for item in items if item["pinned"]]
    pinned = []
    for item in order:
        if item["key"] == "trash":
            pinned.append("trash")
        else:
            pinned.append(item_entry(item["key"]))
        end
    end
    # .desktop, ktere ted chybi, zustavaji v nastaveni na konci (po reinstalaci se vrati)
    for entry in conf["items"]:
        if entry != "trash" and apps.find_entry(entry) == 0:
            pinned.append(entry)
        end
    end
    if pinned != conf["items"]:
        conf["items"] = pinned
        call save_conf()
        call debug("order " + text.join(pinned, " "))
    end
    running = [item["key"] for item in items if not item["pinned"]]
    for key in running_order:
        if not (key in running):
            running.append(key)
        end
    end
    running_order.clear()
    running_order.extend(running)
    return 0
end

function on_release(event, widget):
    call pointer(event)
    button = gtk.event_button(event)
    press = view["press"]
    view["press"] = None
    if button == 1 and press != None:
        if view["dragging"]:
            call finish_drag()
        else:
            index = item_index(press[0])
            if index >= 0:
                call click(items[index])
            end
        end
    elif button == 2:
        index = model.item_at(current_layout(), geo["gap"], view["px"])
        if index >= 0:
            call launch(items[index])
        end
    end
    call queue_redraw()
    return True
end

# ---- akce ----

function launch(item):
    if item["key"] == "trash":
        call glib.launch_uri("trash:///")
    elif item["info"] != 0:
        call debug("launch " + item["key"])
        call apps.launch(item["info"])
    end
    return 0
end

function click(item):
    handles = item["windows"]
    if item["key"] == "trash" or len(handles) == 0:
        call launch(item)
        return 0
    end
    for handle in handles:
        state = windows[handle]["state"]
        if (state & wl.STATE_ACTIVATED) != 0 and (state & wl.STATE_MINIMIZED) == 0:
            call debug("minimize " + item["key"])
            for h in handles:
                call wl.minimize(h, True)
            end
            return 0
        end
    end
    # posledni aktivni okno nakonec, aby skoncilo navrchu
    order = sorted([windows[h]["seq"] * 1000000 + h for h in handles])
    call debug("activate " + item["key"])
    for value in order:
        call wl.activate(value % 1000000)
    end
    return 0
end

function pin(item):
    entry = "trash"
    if item["key"] != "trash":
        entry = item_entry(item["key"])
    end
    if entry in conf["items"]:
        return 0
    end
    if len(conf["items"]) > 0 and conf["items"][-1] == "trash":
        conf["items"].insert(len(conf["items"]) - 1, entry)
    else:
        conf["items"].append(entry)
    end
    call save_conf()
    call sync_items()
    return 0
end

function unpin(item):
    keep = []
    for entry in conf["items"]:
        info = 0
        if entry != "trash":
            info = apps.find_entry(entry)
        end
        key = "trash"
        if info != 0:
            key = apps.path(info)
        elif entry != "trash":
            key = entry
        end
        if key != item["key"]:
            keep.append(entry)
        end
    end
    conf["items"] = keep
    if len(item["windows"]) > 0 and not (item["key"] in running_order):
        running_order.append(item["key"])
    end
    call save_conf()
    call sync_items()
    return 0
end

# ---- nabidka ----

function menu_item(key):
    index = item_index(view["menu_key"])
    if index < 0:
        return None
    end
    return items[index]
end

function on_menu_new(widget):
    item = menu_item(view["menu_key"])
    if item != None:
        call launch(item)
    end
    return 0
end

function on_menu_pin(widget):
    item = menu_item(view["menu_key"])
    if item != None:
        if item["pinned"]:
            call unpin(item)
        else:
            call pin(item)
        end
    end
    return 0
end

function on_menu_quit(widget):
    item = menu_item(view["menu_key"])
    if item != None:
        for handle in item["windows"]:
            call wl.close(handle)
        end
    end
    return 0
end

function on_menu_closed(widget):
    view["menu_open"] = False
    call layer.set_keyboard_mode(window, layer.KEYBOARD_NONE)
    call debug("menu 0")
    if not view["hovered"]:
        call leave()
    end
    return 0
end

# Jedna nabidka na cely beh (zaznamy obsluh LSL se neuvolnuji); pred otevrenim se jen prepisi popisky
function build_menu():
    m = gtk.menu_new()
    menu["menu"] = m
    menu["title"] = gtk.menu_item_new("")
    call gtk.widget_set_sensitive(menu["title"], False)
    menu["new"] = gtk.menu_item_new(i18n.T("New Window"))
    menu["pin"] = gtk.menu_item_new(i18n.T("Keep in Dock"))
    menu["sep"] = gtk.separator_menu_item_new()
    menu["quit"] = gtk.menu_item_new(i18n.T("Quit"))
    for name in ["title", "new", "pin", "sep", "quit"]:
        call gtk.menu_append(m, menu[name])
    end
    call gtk.connect(menu["new"], "activate", on_menu_new)
    call gtk.connect(menu["pin"], "activate", on_menu_pin)
    call gtk.connect(menu["quit"], "activate", on_menu_quit)
    call gtk.connect(m, "deactivate", on_menu_closed)
    call gtk.widget_show_all(m)
    call gtk.menu_attach(m, window)
    return 0
end

function open_menu(item):
    if len(menu) == 0:
        call build_menu()
    end
    view["menu_key"] = item["key"]
    running = len(item["windows"]) > 0
    call gtk.menu_item_set_label(menu["title"], item["name"])
    if item["key"] == "trash":
        call gtk.menu_item_set_label(menu["new"], i18n.T("Open"))
    else:
        call gtk.menu_item_set_label(menu["new"], i18n.T("New Window"))
    end
    call gtk.widget_set_visible(menu["new"], item["key"] == "trash" or item["info"] != 0)
    if item["pinned"]:
        call gtk.menu_item_set_label(menu["pin"], i18n.T("Remove from Dock"))
    else:
        call gtk.menu_item_set_label(menu["pin"], i18n.T("Keep in Dock"))
    end
    call gtk.widget_set_visible(menu["pin"], item["key"] == "trash" or item["info"] != 0 or item["pinned"])
    call gtk.widget_set_visible(menu["sep"], running)
    call gtk.widget_set_visible(menu["quit"], running)
    view["menu_open"] = True
    call debug("menu 1 " + item["key"])
    # klavesnice pro nabidku (sipky, Enter, Escape) jen po dobu nabidky; jinak Dock fokus nebere
    call layer.set_keyboard_mode(window, layer.KEYBOARD_ON_DEMAND)
    # nad ikonou jako v Planku: mys nezustane nad polozkou nabidky
    lay = current_layout()
    index = item_index(item["key"])
    top = Int(Float(geo["panel_y"] + geo["top"] + geo["size"]) - lay[1][index])
    call gtk.menu_popup_above_rect(menu["menu"], window, Int(lay[0][index]), top, Int(lay[1][index]), 4)
    call queue_redraw()
    return 0
end

# ---- okna (wlr-foreign-toplevel) ----

function on_wl(kind, handle, a, b):
    if kind == wl.TOPLEVEL_NEW or kind == wl.TOPLEVEL_CHANGED:
        app_id = wl.toplevel_app_id(handle)
        state = wl.toplevel_state(handle)
        w = windows.get(handle)
        if w == None:
            w = {"app_id": "", "key": "", "state": 0, "seq": 0}
            windows[handle] = w
        end
        if (state & wl.STATE_ACTIVATED) != 0 and (w["state"] & wl.STATE_ACTIVATED) == 0:
            view["seq"] += 1
            w["seq"] = view["seq"]
        end
        changed = w["app_id"] != app_id or w["state"] != state
        w["state"] = state
        if w["app_id"] != app_id:
            w["app_id"] = app_id
            w["key"] = resolve(app_id)
            if not (w["key"] in running_order):
                running_order.append(w["key"])
            end
            call debug("window " + String(handle) + " " + app_id + " " + w["key"])
        end
        if changed:
            call sync_items()
            call update_hide(True)
        end
    elif kind == wl.TOPLEVEL_CLOSED:
        if handle in windows:
            call windows.pop(handle)
            call sync_items()
            call update_hide(True)
        end
    elif kind == wl.OUTPUT_NEW or kind == wl.OUTPUT_REMOVED:
        call update_output()
        call update_geometry()
        call queue_redraw()
    end
    return 0
end

# Zamerene okno a jeho ram od luxwm: Dock uhne, kdyz ho okno prekryva
function on_wm_event(event):
    if event.get("event") == "window":
        focus["known"] = True
        focus["frame"] = event.get("frame", [])
        call update_hide(True)
        call update_over_window()
    end
    return 0
end

function update_over_window():
    over = over_window()
    if over != view["over_window"]:
        view["over_window"] = over
        call debug("over-window " + ("1" if over else "0"))
        call queue_redraw()
    end
    return 0
end

function on_wm_state(up):
    focus["known"] = False
    call update_over_window()
    zone["sent"] = None
    if up:
        call send_zone()
    else:
        call update_hide(True)
    end
    return 0
end

# Dock je na hlavnim monitoru luxwm (Monitory, bily pruh)
function on_primary(monitor):
    output["monitor"] = monitor
    call layer.set_monitor(window, monitor)
    call update_output()
    call update_geometry()
    call queue_redraw()
    return 0
end

# ---- LauncherEntry (cislo a prubeh na ikone) ----

function on_launcher_entry(sender, path, interface, signal, values):
    if len(values) < 2 or not values[0].startswith("application://"):
        return 0
    end
    desktop_id = values[0][14:]
    entry = entries.get(desktop_id)
    if entry == None:
        entry = {}
        entries[desktop_id] = entry
    end
    for key in values[1]:
        entry[key] = values[1][key]
    end
    entry["sender"] = sender
    call debug("entry " + desktop_id + " " + String(entry.get("count", 0)) + " " + String(entry.get("count-visible", False)))
    call queue_redraw()
    return 0
end

# Aplikace skoncila: jeji cisla zmizi (jako Plank)
function on_name_owner(sender, path, interface, signal, values):
    if len(values) < 3 or values[2] != "":
        return 0
    end
    for desktop_id in List(entries):
        if entries[desktop_id].get("sender", "") == values[0]:
            call entries.pop(desktop_id)
            call queue_redraw()
        end
    end
    return 0
end

function watch_launcher_entries():
    safe:
        bus = gio.session_bus()
        if bus != 0:
            call gio.subscribe_values(bus, "", "com.canonical.Unity.LauncherEntry", "Update", "", on_launcher_entry)
            call gio.subscribe_values(bus, "org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged", "/org/freedesktop/DBus", on_name_owner)
        end
    end
    return 0
end

# ---- zmeny souboru ----

function update_trash():
    full = len(glib.list_dir(trash_dir)) > 0
    if full != view["trash_full"]:
        view["trash_full"] = full
        for item in items:
            if item["key"] == "trash":
                call load_icons(item)
            end
        end
        call queue_redraw()
    end
    return 0
end

function on_trash(file, event, other):
    call update_trash()
    return 0
end

function on_config(file, event, other):
    if file.endswith("/dock.conf"):
        if glib.read_text(conf_path) != conf_text:
            call load_conf()
            view["zoom_on"] = True
            call update_geometry()
            call sync_items()
        end
    elif file.endswith("/appearance.conf") or file.endswith("/appearance"):
        call material.reload()
        call apply_menu_css()
        view["strip"] = None
        call queue_redraw()
    end
    return 0
end

function on_apps_changed(monitor):
    call apps.reload()
    app_keys.clear()
    for handle in windows:
        windows[handle]["key"] = resolve(windows[handle]["app_id"])
    end
    call sync_items()
    return 0
end

function watch_files():
    call glib.mkdir_p(conf_dir)
    safe:
        call gio.file_monitor(conf_dir, on_config)
    end
    call glib.mkdir_p(trash_dir)
    safe:
        call gio.file_monitor(trash_dir, on_trash)
    end
    call glib.signal_connect(apps.monitor(), "changed", on_apps_changed, 0)
    return 0
end

# ---- start ----

call glib.set_prgname("luxos-dock")
call gtk.init()
call material.grayscale_text()
if not layer.is_wayland() or not layer.is_supported():
    print "luxos-dock: needs a Wayland compositor with layer-shell (the X11 session uses Plank)"
    exit(1)
end
if exists(conf_path):
    call load_conf()
else:
    conf = model.parse_conf("")
    if migrate_plank():
        print "luxos-dock: dock items taken over from Plank"
    end
    call save_conf()
end
view["trash_full"] = len(glib.list_dir(trash_dir)) > 0

window = gtk.window_new("luxos-dock")
call gtk.window_set_rgba(window)
call apply_menu_css()
call layer.init_for_window(window)
call layer.set_namespace(window, tokens.namespace("luxos-dock", "dock"))
call layer.set_layer(window, layer.LAYER_TOP)
call layer.set_anchors(window, [layer.EDGE_BOTTOM])
call layer.set_keyboard_mode(window, layer.KEYBOARD_NONE)
screens = layer.monitors()
if len(screens) > 0:
    call layer.set_monitor(window, screens[0])
end
call wm.subscribe(["window"])
call wm.on_state(on_wm_state)
call primary.also(on_wm_event)
call primary.follow(on_primary)
call gtk.widget_add_events(window, gtk.POINTER_MOTION_MASK + gtk.BUTTON_PRESS_MASK + gtk.BUTTON_RELEASE_MASK + gtk.ENTER_NOTIFY_MASK + gtk.LEAVE_NOTIFY_MASK)
call gtk.connect(window, "draw", on_draw)
call gtk.connect(window, "enter-notify-event", on_enter)
call gtk.connect(window, "leave-notify-event", on_leave)
call gtk.connect(window, "motion-notify-event", on_motion)
call gtk.connect(window, "button-press-event", on_press)
call gtk.connect(window, "button-release-event", on_release)

# jedno spojeni s kompozitorem: protokoly luxos_wl jdou pres soket GTK
if wl.on_event(on_wl):
    call wl.attach(layer.wl_display())
end
call update_output()
call sync_items()
call update_geometry()
if want_hidden():
    anims["hide"] = [1.0, 1.0, 1.0, 0, 1]
end
call gtk.widget_show_all(window)
call update_region(current_layout())
call watch_launcher_entries()
call watch_files()
call debug("ready " + String(geo["width"]) + " " + String(geo["height"]))
call gtk.main()
