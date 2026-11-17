# LuxOS - widgety na plose jako na Androidu: kazdy widget je samostatna karta, ktera jde chytit
# a presunout kamkoli (pozice se zaokrouhli na mrizku 8 px a zapamatuje), pravym tlacitkem
# "Upravit widgety..." a "Odebrat widget". Galerie widgetu (luxos-widgets settings, v Launchpadu
# "Widgety") ukaze zive nahledy vsech widgetu s tlacitkem Pridat / Odebrat, vypinac vsech widgetu
# a "Vychozi rozmisteni".
#   today     datum a velky cas (klik: Hodiny), vpravo pocasi z aplikace Pocasi (klik: Pocasi)
#   system    nazev systemu, stav (Vyborne / Dobre / Vytizene) a oblouky procesor, pamet, disk
#   music     prave hrajici hudba/video (MPRIS) s Prehrat/Pozastavit a Dalsi; jen kdyz neco hraje
#   calendar  mesic s vyznacenym dneskem (klik: Kalendar)
#
# Vzhled: prusvitne sklo - rozostrena tapeta, jemny mlecny zavoj a svetly odlesk.
# Svetle sklo ma tmavy text, tmave bile; kontrast se upravuje jen nezbytnym zavojem.
# Material se pripravi jen pri zmene tapety/monitoru/plochy; pri presunu se meni pouze vyrez.
# Tapeta = tapeta hlavniho monitoru na aktivni plose (stejne jako horni lista luxos-bar).
# Na velmi svetle tapete (bila, bezova, bily len) ma kazda karta pod sebou mekky tmavy "stin"
# (jako macOS): tapeta kolem karty plynule ztmavne, svetla karta s tmavym textem se od tapety odlisi.
# Bezne tapety vcetne Sunrise beze zmeny. Vypnuti spolu se zavojem pod listou: DESKTOP_SCRIM=0
# v ~/.config/luxos/appearance.conf.
#
# Nastaveni ~/.config/luxos/widgets.conf (zmeny se nacitaji hned, zapisuje ho i galerie):
#   ENABLED=1                         zapnute (vychozi vypnute: program hned skonci)
#   WIDGETS=today,system,music        poradi a vyber karet
#   POS_today=1580,4                  pozice karty vuci pracovni plose hlavniho monitoru (jinak pod sebou)
#   SIDE=right                        strana pro vychozi rozmisteni (right / left)
#
#   luxos-widgets           bezi na pozadi (automaticke spusteni po prihlaseni; vypnute = hned skonci)
#   luxos-widgets on|off    zapne (a spusti) / vypne widgety
#   luxos-widgets settings  galerie widgetu (samostatny proces, meni jen widgets.conf)
#
# Okna jsou pod ostatnimi okny (keep below), na vsech plochach, bez ikony v liste a bez zamereni.
# Data: /proc/stat a /proc/meminfo kazde 2 s (jen kdyz je karta system zobrazena), disk kazdou minutu;
# pocasi ze souhrnu aplikace Pocasi ($XDG_CACHE_HOME/luxos/weather/summary.json, nejvys 3 hodiny staty)
# nebo z "luxos-weather --json forecast" kazdych 30 minut, kdyz Pocasi ma ulozene misto.
load env, cairo, pango, json
load luxos_glib, glib as glib
load luxos_gio, gio as gio
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_sys as sys
load luxos_mpris as mpris
load luxos_text as text
load luxos_x11 as x11

WIDTH = 340
PAD = 24
# Stin na svetle tapete (jako vrzeny shora): dosah do stran, dolu navic POOL_OFFSET, nahore
# nic (okno karty zacina hornim okrajem karty, spravce oken ho nepusti pod listu); nejvyssi alfa
# cerne u karty; sila podle prumerneho linearniho jasu tapety kolem karty od POOL_LUM_NONE
# (zadny) do POOL_LUM_FULL (plny). Dosah se vejde do pruhledneho okraje okna (24 px do stran, 26 dolu).
POOL_REACH = 20.0
POOL_OFFSET = 4.0
POOL_MAX = 0.20
POOL_LUM_NONE = 0.72
POOL_LUM_FULL = 0.85
DEFAULT_WIDGETS = "today,system,music"
ALL_WIDGETS = ["today", "system", "music", "calendar"]
GRID = 8
WEATHER_MAX_AGE = 10800
SOCKET = "luxos-widgets-"
GLASS_RADIUS = 22.0

CSS = ("window.lw { background: transparent; }\n"
    + ".lw-col { padding: 0 24px 12px 24px; }\n"
    + ".lw-card { background: transparent;"
    + " border: 1px solid rgba(255, 255, 255, 0.38); border-top-color: rgba(255, 255, 255, 0.62); border-bottom-color: rgba(255, 255, 255, 0.20); border-radius: 22px; padding: 16px 18px; color: white;"
    + " box-shadow: 0 8px 16px -8px rgba(8, 12, 24, 0.16), inset 0 1px rgba(255, 255, 255, 0.18); }\n"
    + ".lw-card label { color: white; text-shadow: none; }\n"
    + ".lw-card label.dim { color: rgba(255, 255, 255, 0.90); }\n"
    + ".lw-card.lw-light label, .lw-card.lw-light image, .lw-card.lw-light button { color: rgb(25, 31, 43); }\n"
    + ".lw-card.lw-light label.dim { color: rgba(25, 31, 43, 0.90); }\n"
    + ".lw-card.lw-light .lw-vsep, .lw-card.lw-light .lw-hsep { background-color: rgba(25, 31, 43, 0.12); }\n"
    + ".lw-card.lw-light .lw-btn, .lw-card.lw-light .lw-art { background-color: rgba(255, 255, 255, 0.28); }\n"
    + ".lw-card.lw-light button:hover { background-color: rgba(255, 255, 255, 0.42); }\n"
    + ".lw-date { font-size: 13px; font-weight: 600; }\n"
    + ".lw-time { font-size: 42px; font-weight: 400; }\n"
    + ".lw-temp { font-size: 26px; font-weight: 400; }\n"
    + ".lw-cond { font-size: 12px; font-weight: 600; }\n"
    + ".lw-small { font-size: 11px; }\n"
    + ".lw-vsep { background-color: rgba(255, 255, 255, 0.14); min-width: 1px; margin: 4px 16px; }\n"
    + ".lw-hsep { background-color: rgba(255, 255, 255, 0.12); min-height: 1px; margin: 12px 0 6px 0; }\n"
    + ".lw-title { font-size: 14px; font-weight: 600; }\n"
    + ".lw-health { font-size: 12px; font-weight: 600; }\n"
    + ".lw-card image { color: white; -gtk-icon-shadow: none; }\n"
    + "button.lw-btn { border-radius: 999px; min-width: 32px; min-height: 32px; padding: 0; background-color: rgba(255, 255, 255, 0.10); background-image: none; border: none; box-shadow: none; color: white; outline: none; }\n"
    + "button.lw-btn:hover { background-color: rgba(255, 255, 255, 0.28); }\n"
    + "button.lw-more { border-radius: 999px; min-width: 24px; min-height: 22px; padding: 0 2px; background: none; border: none; box-shadow: none; color: white; outline: none; }\n"
    + "button.lw-more:hover { background-color: rgba(255, 255, 255, 0.18); }\n"
    + "button.lw-more label { font-size: 15px; font-weight: 700; }\n"
    + ".lw-art { background-color: rgba(255, 255, 255, 0.10); border-radius: 12px; min-width: 44px; min-height: 44px; }\n")

# Tlumene akcenty: procesor, pamet, disk. Barva slouzi jen k rozliseni metrik.
RING_COLORS = [[[0.65, 0.76, 1.0], [0.78, 0.85, 1.0]], [[0.52, 0.83, 0.77], [0.72, 0.92, 0.84]], [[0.72, 0.66, 0.94], [0.85, 0.79, 1.0]]]

conf = {"enabled": True, "widgets": [], "side": "right", "pos": {}}
# wins: nazev -> okno karty; placed: nazev -> [x, y] na obrazovce; settings = galerie (nahledy)
ui = {"wins": {}, "cards": {}, "placed": {}, "settings": False, "gallery": {}}
theme = {"provider": 0, "wallpaper": "", "surface": 0, "raw": 0, "map": [], "geometry": [], "pool": True, "cache": {}}
drag = {"name": "", "start": [], "origin": [], "moved": False}
cpu = {"busy": 0, "total": 0, "pct": 0, "recent": []}
stats = {"cpu": 0, "mem": 0, "disk": 0, "disk_at": 0.0}
weather = {"data": None, "fetching": False}
timers = {"stats": 0}
bus = {"session": 0}

function conf_path():
    return glib.user_config_dir() + "/luxos/widgets.conf"
end

function read_conf():
    conf["enabled"] = False
    conf["widgets"] = DEFAULT_WIDGETS.split(",")
    conf["side"] = "right"
    conf["pos"] = {}
    raw = glib.read_text(conf_path())
    for line in raw.split("\n"):
        parts = line.split("=")
        if len(parts) < 2:
            continue
        end
        key = parts[0].strip()
        value = parts[1].strip()
        if key == "ENABLED":
            conf["enabled"] = value == "1"
        elif key == "SIDE" and (value == "left" or value == "right"):
            conf["side"] = value
        elif key == "WIDGETS":
            names = []
            for n in value.split(","):
                n = n.strip()
                if n in ALL_WIDGETS and n not in names:
                    names.append(n)
                end
            end
            conf["widgets"] = names
        elif key.startswith("POS_") and key[4:] in ALL_WIDGETS:
            xy = value.split(",")
            if len(xy) == 2 and text.is_digits(xy[0].strip().replace("-", "")) and text.is_digits(xy[1].strip().replace("-", "")):
                conf["pos"][key[4:]] = [Int(xy[0].strip()), Int(xy[1].strip())]
            end
        end
    end
    return 0
end

# Hodnoty v souboru nastaveni: values {klic: hodnota}, drop = predpona klicu k odstraneni;
# ostatni radky zustanou. Zapis pres docasny soubor (sledovani vidi jen hotovy soubor).
function write_conf(values, drop):
    path = conf_path()
    call sys.mkdir_p(glib.user_config_dir() + "/luxos")
    out = ""
    for line in glib.read_text(path).split("\n"):
        key = line.split("=")[0]
        if line == "" or key in values or (drop != "" and key.startswith(drop)):
            continue
        end
        out = out + line + "\n"
    end
    for key in values.keys():
        out = out + key + "=" + values[key] + "\n"
    end
    call writefile(path + ".new", out)
    call sys.rename(path + ".new", path)
    return 0
end

function write_conf_value(key, value):
    return write_conf({key: value}, "")
end

function set_widgets(names):
    return write_conf_value("WIDGETS", ",".join(names))
end

# ---- matne sklo podle tapety ---------------------------------------------------------------

function clamp(x, lo, hi):
    return max(lo, min(hi, x))
end

# Aktivni plocha (_NET_CURRENT_DESKTOP korenoveho okna), 0 kdyz neni spravce oken
function current_workspace():
    value = []
    safe:
        value = x11.cardinals(x11.root_xid(), "_NET_CURRENT_DESKTOP")
    end
    if len(value) > 0:
        return Int(value[0])
    end
    return 0
end

# Tapeta hlavniho monitoru na aktivni plose z xfconf - stejny vyber jako lista (luxos-bar wallpaper_for):
# nejlepe monitor i plocha, pak monitor, pak plocha, jinak jakakoli. Drive vzdy plocha 0 posledniho
# monitoru v abecede - se starymi zaznamy jinych monitoru (jiny vystup, drive pripojeny monitor) mely
# karty sklo i barvu textu podle jine tapety, nez byla videt.
function wallpaper_path():
    if bus["session"] == 0:
        return ""
    end
    props = None
    safe:
        props = gio.call_values(bus["session"], "org.xfce.Xfconf", "/org/xfce/Xfconf", "org.xfce.Xfconf",
                                "GetAllProperties", ["xfce4-desktop", "/backdrop"], "(ss)", 3000)
    end
    if props == None or len(props) == 0 or type(props[0]) != "Dictionary":
        return ""
    end
    return pick_wallpaper(props[0], current_workspace(), String(gtk.primary_monitor_info()[4]))
end

# Vyber z vlastnosti /backdrop (slovnik): ws = aktivni plocha, model = nazev vystupu hlavniho monitoru
function pick_wallpaper(values, ws, model):
    # xfdesktop bez ulozene volby: tapeta jedne plochy pro vsechny (vychozi zapnuto)
    if values.get("/backdrop/single-workspace-mode", True) == True:
        ws = Int(values.get("/backdrop/single-workspace-number", 0))
    end
    best = ""
    score = -1
    for key in sorted(values.keys()):
        if not key.endswith("/last-image"):
            continue
        end
        sc = 0
        if model != "" and key.find("/monitor" + model + "/") >= 0:
            sc = sc + 2
        end
        if key.endswith("/workspace" + String(ws) + "/last-image"):
            sc = sc + 1
        end
        value = String(values[key])
        if sc > score and value != "" and exists(value):
            best = value
            score = sc
        end
    end
    return best
end

# Dvoupruchodovy Gaussuv filtr na malem obrazku (1, 4, 6, 4, 1).
# Barvy tapety zustanou viditelne, s mirnou desaturaci a mlecnym zavojem.
# Kontrast se resi az podle oblasti karty, nikoli ztmavenim cele tapety.
function glass_surface(source, w, h):
    weights = [1.0, 4.0, 6.0, 4.0, 1.0]
    for axis in range(2):
        out = cairo.image_surface_create(cairo.FORMAT_RGB24, w, h)
        cr = cairo.create(out)
        for y in range(h):
            for x in range(w):
                rgb = [0.0, 0.0, 0.0]
                for k in range(5):
                    sx = x
                    sy = y
                    if axis == 0:
                        sx = Int(clamp(x + k - 2, 0, w - 1))
                    else:
                        sy = Int(clamp(y + k - 2, 0, h - 1))
                    end
                    px = cairo.image_surface_pixel(source, sx, sy)
                    rgb[0] = rgb[0] + Float((px >> 16) & 255) * weights[k] / 4080.0
                    rgb[1] = rgb[1] + Float((px >> 8) & 255) * weights[k] / 4080.0
                    rgb[2] = rgb[2] + Float(px & 255) * weights[k] / 4080.0
                end
                if axis == 1:
                    lum = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
                    rgb = [0.22 + (rgb[0] * 0.72 + lum * 0.28) * 0.72,
                           0.22 + (rgb[1] * 0.72 + lum * 0.28) * 0.72,
                           0.22 + (rgb[2] * 0.72 + lum * 0.28) * 0.72]
                end
                call cairo.set_source_rgb(cr, rgb[0], rgb[1], rgb[2])
                call cairo.rectangle(cr, x, y, 1, 1)
                call cairo.fill(cr)
            end
        end
        call cairo.destroy(cr)
        call cairo.surface_destroy(source)
        source = out
    end
    return source
end

# [svetle sklo, nepruhlednost zavoje]. Extremy se berou z celeho vyrezu v malem
# podkladu: i na tapete s prechodem drzi citelnost jednotna barva textu v cele karte.
function glass_style(surface, sx, sy, sw, sh):
    pw = cairo.image_surface_get_width(surface)
    ph = cairo.image_surface_get_height(surface)
    lo = 1.0
    hi = 0.0
    total = 0.0
    count = 0
    for y in range(Int(max(0, sy)), Int(min(ph - 1, sy + sh + 1)) + 1):
        for x in range(Int(max(0, sx)), Int(min(pw - 1, sx + sw + 1)) + 1):
            px = cairo.image_surface_pixel(surface, x, y)
            r = Float((px >> 16) & 255) / 255.0
            g = Float((px >> 8) & 255) / 255.0
            b = Float(px & 255) / 255.0
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            # RMS drzi rezervu i pro syte cervene/modre pozadi (prostemu prumeru by uniklo).
            energy = 0.2126 * r * r + 0.7152 * g * g + 0.0722 * b * b
            peak = 1.0
            for step in range(6):
                peak = (peak + energy / peak) / 2.0
            end
            lo = min(lo, lum)
            hi = max(hi, peak)
            total = total + lum
            count = count + 1
        end
    end
    light = total / Float(max(1, count)) >= 0.56
    if light:
        return [True, clamp((0.64 - lo) / max(0.001, 1.0 - lo), 0.0, 1.0)]
    end
    return [False, clamp(1.0 - 0.37 / max(0.001, hi), 0.0, 1.0)]
end

# Jeden sdileny rozostreny podklad pro vsechny karty; bez snimani obrazovky a bez kompozitoroveho blur.
# Mapa = [sirka, vyska, meritko, posun x, y], tapeta "priblizit" vyplni monitor a prebytek orizne.
# Pripravene materialy podle tapety (prepinani ploch s ruznymi tapetami nic znovu nenacita):
# cesta|velikost a zmena souboru|monitor -> [sklo, puvodni maly obrazek (jas pro stin), mapa]
function load_wallpaper(path):
    geo = primary_geometry()
    theme["geometry"] = geo
    theme["surface"] = 0
    theme["raw"] = 0
    if path == "" or not exists(path):
        return 0
    end
    key = path + "|" + String(glib.stat(path)) + "|" + String(geo)
    hit = theme["cache"].get(key)
    if hit == None:
        hit = prepare_wallpaper(path, geo)
        if hit == None:
            return 0
        end
        if len(theme["cache"]) >= 8:
            for old in theme["cache"].values():
                call cairo.surface_destroy(old[0])
                call cairo.surface_destroy(old[1])
            end
            theme["cache"] = {}
        end
        theme["cache"][key] = hit
    end
    theme["surface"] = hit[0]
    theme["raw"] = hit[1]
    theme["map"] = hit[2]
    return 0
end

function prepare_wallpaper(path, geo):
    pb = gtk.pixbuf_new_from_file_at_scale(path, 96, 96, True)
    if pb == 0:
        return None
    end
    pw = gtk.pixbuf_get_width(pb)
    ph = gtk.pixbuf_get_height(pb)
    surfaces = []
    for i in range(2):
        surface = cairo.image_surface_create(cairo.FORMAT_RGB24, pw, ph)
        cr = cairo.create(surface)
        call cairo.set_source_rgb(cr, 0.15, 0.17, 0.21)
        call cairo.paint(cr)
        call gtk.cairo_set_source_pixbuf(cr, pb, 0, 0)
        call cairo.paint(cr)
        call cairo.destroy(cr)
        surfaces.append(surface)
    end
    call glib.object_unref(pb)
    mw = Float(max(1, geo[2]))
    mh = Float(max(1, geo[3]))
    sc = min(Float(pw) / mw, Float(ph) / mh)
    return [glass_surface(surfaces[0], pw, ph), surfaces[1],
            [pw, ph, sc, (Float(pw) - mw * sc) / 2.0 - Float(geo[0]) * sc, (Float(ph) - mh * sc) / 2.0 - Float(geo[1]) * sc]]
end

# ---- stin karty na svetle tapete --------------------------------------------------------------

# sRGB -> linearni jas (polynom, odchylka od presne krivky pod 1 %)
function srgb_linear(v):
    return v * (v * (v * 0.305306011 + 0.682171111) + 0.012522878)
end

# Sila stinu 0-1: prumerny linearni jas puvodni tapety v okoli karty (x, y, w, h na obrazovce)
function pool_strength(x, y, w, h):
    surface = theme["raw"]
    if surface == 0 or not theme["pool"]:
        return 0.0
    end
    m = theme["map"]
    pw = cairo.image_surface_get_width(surface)
    ph = cairo.image_surface_get_height(surface)
    x0 = Int(clamp(m[3] + (x - POOL_REACH) * m[2], 0.0, Float(pw - 1)))
    x1 = Int(clamp(m[3] + (x + w + POOL_REACH) * m[2], 0.0, Float(pw - 1)))
    y0 = Int(clamp(m[4] + (y - POOL_REACH) * m[2], 0.0, Float(ph - 1)))
    y1 = Int(clamp(m[4] + (y + h + POOL_REACH) * m[2], 0.0, Float(ph - 1)))
    total = 0.0
    count = 0
    for py in range(y0, y1 + 1):
        for px in range(x0, x1 + 1):
            v = cairo.image_surface_pixel(surface, px, py)
            total = total + 0.2126 * srgb_linear(Float((v >> 16) & 255) / 255.0) + 0.7152 * srgb_linear(Float((v >> 8) & 255) / 255.0) + 0.0722 * srgb_linear(Float(v & 255) / 255.0)
            count = count + 1
        end
    end
    t = clamp((total / Float(max(1, count)) - POOL_LUM_NONE) / (POOL_LUM_FULL - POOL_LUM_NONE), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)
end

# Alfa stinu ve vzdalenosti d px od okraje karty (u karty nejvys, na dosahu nula bez hrany)
function pool_alpha(strength, d):
    if d >= POOL_REACH:
        return 0.0
    end
    u = d / POOL_REACH
    e = (1.0 - u * u) * (1.0 - u * u)
    return strength * POOL_MAX * e * e
end

# Stin pod kartou v okne karty (pred kartou; okolo pruhledne, skutecna pruhlednost s kompozitorem).
# Vrstvy po 1 px od nejvzdalenejsi: pres sebe davaji pozadovany prubeh alfy. Horni hrana vrstvy
# klesa s dosahem - na hornim okraji okna je jen vrstva pod samotnou kartou (bez hrany nahore).
function on_window_draw(cr, window):
    name = ""
    for n in ui["wins"].keys():
        if ui["wins"][n] == window:
            name = n
        end
    end
    c = ui["cards"].get(name)
    if c == None or not gtk.widget_get_visible(c["ev"]):
        return False
    end
    a = gtk.widget_get_allocation(c["box"])
    if a[2] < 2 or a[3] < 2:
        return False
    end
    pos = gtk.window_get_position(window)
    strength = pool_strength(Float(pos[0] + a[0]), Float(pos[1] + a[1]), Float(a[2]), Float(a[3]))
    c["pool"] = strength
    if strength <= 0.004:
        return False
    end
    steps = Int(POOL_REACH)
    prev = 0.0
    for i in range(steps + 1):
        d = POOL_REACH - Float(i)
        want = pool_alpha(strength, d)
        if want <= prev:
            continue
        end
        step = 1.0 - (1.0 - want) / (1.0 - prev)
        prev = want
        top = Float(a[1]) + 0.6 * d
        bottom = Float(a[1] + a[3]) + d + POOL_OFFSET * d / POOL_REACH
        call cairo.rounded_rectangle(cr, Float(a[0]) - d, top, Float(a[2]) + 2.0 * d, bottom - top, GLASS_RADIUS + 0.8 * d)
        call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, step)
        call cairo.fill(cr)
    end
    return False
end

# Mys jen nad kartou: pruhledny okraj okna (stin) kliky nebere, jdou na plochu pod nim
function on_box_allocate(alloc, box):
    for name in ui["cards"].keys():
        c = ui["cards"][name]
        if c["box"] == box:
            win = ui["wins"].get(name, 0)
            a = gtk.widget_get_allocation(box)
            if win != 0:
                call gtk.widget_input_rect(win, a[0], a[1], a[2], a[3])
            end
        end
    end
    return 0
end

# Podklad pred detmi event boxu; False ponecha GTK vykreslit text a ovladaci prvky.
function on_card_draw(cr, widget):
    c = card_of(widget)
    if c == None:
        return False
    end
    a = gtk.widget_get_allocation(c["box"])
    e = gtk.widget_get_allocation(widget)
    x = Float(a[0] - e[0])
    y = Float(a[1] - e[1])
    w = Float(a[2])
    h = Float(a[3])
    if w < 2.0 or h < 2.0:
        return False
    end
    call cairo.save(cr)
    call cairo.rounded_rectangle(cr, x, y, w, h, GLASS_RADIUS)
    call cairo.clip(cr)
    call cairo.set_source_rgba(cr, 0.92, 0.94, 0.98, 0.86)
    call cairo.paint(cr)
    style = [True, 0.0]
    if theme["surface"] != 0:
        m = theme["map"]
        geo = gtk.primary_monitor_workarea()
        pos = [geo[0] + geo[2] // 2, geo[1] + geo[3] // 3]
        win = ui["wins"].get(c["name"], 0)
        if win != 0:
            pos = gtk.window_get_position(win)
            pos = [pos[0] + e[0], pos[1] + e[1]]
        end
        # Polovicni pixel navic drzi bilinearni filtr uvnitr obrazku i na hrane monitoru.
        sx = clamp(m[3] + Float(pos[0]) * m[2], 0.5, Float(m[0]) - 0.5 - w * m[2])
        sy = clamp(m[4] + Float(pos[1]) * m[2], 0.5, Float(m[1]) - 0.5 - h * m[2])
        style = glass_style(theme["surface"], sx, sy, w * m[2], h * m[2])
        call cairo.save(cr)
        call cairo.translate(cr, x, y)
        call cairo.scale(cr, 1.0 / m[2], 1.0 / m[2])
        call cairo.set_source_surface(cr, theme["surface"], -sx, -sy)
        call cairo.paint(cr)
        call cairo.restore(cr)
    end
    if c.get("light") != style[0]:
        c["light"] = style[0]
        call gtk.widget_set_class(c["box"], "lw-light", style[0])
    end
    veil = 0.0
    if style[0]:
        veil = 1.0
    end
    call cairo.set_source_rgba(cr, veil, veil, veil, style[1])
    call cairo.paint(cr)
    sheen = cairo.pattern_create_linear(x, y, x + w * 0.35, y + h)
    call cairo.pattern_add_color_stop_rgba(sheen, 0.0, 1.0, 1.0, 1.0, 0.08)
    call cairo.pattern_add_color_stop_rgba(sheen, 1.0, 1.0, 1.0, 1.0, 0.0)
    call cairo.set_source(cr, sheen)
    call cairo.paint(cr)
    call cairo.pattern_destroy(sheen)
    call cairo.restore(cr)
    return False
end

function theme_refresh():
    for c in ui["cards"].values():
        call gtk.widget_queue_draw(c["ev"])
    end
    return 0
end

function primary_geometry():
    geo = gtk.primary_monitor_info()
    return [geo[0], geo[1], geo[2], geo[3]]
end

function theme_apply():
    if theme["provider"] == 0:
        theme["provider"] = gtk.css_load(CSS)
    end
    theme["pool"] = read_scrim_pref()
    path = wallpaper_path()
    if path != theme["wallpaper"] or theme["geometry"] != primary_geometry():
        theme["wallpaper"] = path
        call load_wallpaper(path)
    end
    call theme_refresh()
    return 0
end

# DESKTOP_SCRIM=0 v appearance.conf vypne stin karet (spolu se zavojem pod listou)
function appearance_path():
    return glib.user_config_dir() + "/luxos/appearance.conf"
end

function read_scrim_pref():
    on = True
    for line in glib.read_text(appearance_path()).split("\n"):
        parts = line.split("=")
        if len(parts) >= 2 and parts[0].strip() == "DESKTOP_SCRIM":
            on = parts[1].strip() != "0"
        end
    end
    return on
end

function on_appearance_event(path, event, other):
    if read_scrim_pref() != theme["pool"]:
        call theme_apply()
    end
    return 0
end

# Jina aktivni plocha: tapeta te plochy (pripravena z mezipameti, kdyz uz byla videt)
function on_root_property(bound, kind, window, detail, mods):
    if kind == x11.PROPERTY_NOTIFY and detail == x11.atom("_NET_CURRENT_DESKTOP"):
        call glib.timeout_add(0, theme_once)
    end
    return 0
end

function on_xfconf_changed(sender, path, interface, signal, values):
    if len(values) >= 2 and values[0] == "xfce4-desktop" and String(values[1]).endswith("last-image"):
        call glib.timeout_add(300, theme_once)
    end
    return 0
end

function theme_once():
    call theme_apply()
    return False
end

# ---- pomucky ---------------------------------------------------------------------------------

function label(text, classes):
    l = gtk.label_new(text)
    call gtk.label_set_xalign(l, 0.0)
    for c in classes:
        call gtk.widget_add_class(l, c)
    end
    return l
end

function card_new(name, on_click, orientation):
    ev = gtk.event_box_new()
    call gtk.event_box_set_visible_window(ev, False)
    call gtk.widget_set_margins(ev, 0, 0, 0, 14)
    call gtk.widget_add_events(ev, gtk.BUTTON_PRESS_MASK + gtk.BUTTON_RELEASE_MASK + gtk.POINTER_MOTION_MASK)
    box = gtk.box_new(orientation, 0)
    call gtk.widget_add_class(box, "lw-card")
    call gtk.widget_add_class(box, "lw-" + name)
    call gtk.container_add(ev, box)
    call gtk.connect(ev, "draw", on_card_draw)
    c = {"ev": ev, "box": box, "name": name, "click": on_click}
    if not ui["settings"]:
        call gtk.connect(ev, "button-press-event", on_card_press)
        call gtk.connect(ev, "motion-notify-event", on_card_motion)
        call gtk.connect(ev, "button-release-event", on_card_release)
        if on_click != None:
            call gtk.connect(ev, "realize", on_card_realize)
        end
    end
    return c
end

# Kreslici plocha karty: ma vlastni okno X, bez masky by klik a tazeni dostalo hlavni okno misto karty
# (obsluha vrati False a GTK udalost preda karte)
function area_new():
    area = gtk.drawing_area_new()
    call gtk.widget_add_events(area, gtk.BUTTON_PRESS_MASK + gtk.BUTTON_RELEASE_MASK + gtk.POINTER_MOTION_MASK)
    return area
end

function card_of(widget):
    for name in ui["cards"].keys():
        if ui["cards"][name]["ev"] == widget:
            return ui["cards"][name]
        end
    end
    return None
end

# Leve tlacitko: klik (bez pohybu) = akce karty, tazeni = presun karty; prave tlacitko = nabidka
function on_card_press(event, widget):
    c = card_of(widget)
    if c == None:
        return False
    end
    button = gtk.event_button(event)
    if button == 3:
        call card_menu(c["name"])
        return True
    end
    if button != 1 or gtk.event_is_double_click(event):
        return False
    end
    drag["name"] = c["name"]
    drag["start"] = [gtk.event_x_root(event), gtk.event_y_root(event)]
    drag["origin"] = ui["placed"].get(c["name"], [0, 0])
    drag["moved"] = False
    return True
end

function on_card_motion(event, widget):
    if drag["name"] == "" or len(drag["start"]) != 2:
        return False
    end
    dx = gtk.event_x_root(event) - drag["start"][0]
    dy = gtk.event_y_root(event) - drag["start"][1]
    if not drag["moved"] and abs(dx) + abs(dy) < 6.0:
        return True
    end
    drag["moved"] = True
    win = ui["wins"].get(drag["name"], 0)
    if win != 0:
        call gtk.window_move(win, drag["origin"][0] + Int(dx), drag["origin"][1] + Int(dy))
        call gtk.widget_queue_draw(widget)
    end
    return True
end

function on_card_release(event, widget):
    name = drag["name"]
    drag["name"] = ""
    if name == "":
        return False
    end
    c = ui["cards"].get(name)
    if not drag["moved"]:
        if c != None and c["click"] != None:
            call c["click"](event, widget)
        end
        return True
    end
    # misto upusteni: na mrizku, do pracovni plochy; pozice vuci pracovni plose
    geo = gtk.primary_monitor_workarea()
    x = drag["origin"][0] + Int(gtk.event_x_root(event) - drag["start"][0])
    y = drag["origin"][1] + Int(gtk.event_y_root(event) - drag["start"][1])
    x = geo[0] + snap(x - geo[0])
    y = geo[1] + snap(y - geo[1])
    xy = clamp_to_area(name, x, y)
    call write_conf_value("POS_" + name, String(xy[0] - geo[0]) + "," + String(xy[1] - geo[1]))
    return True
end

function snap(v):
    if v >= 0:
        return ((v + GRID // 2) // GRID) * GRID
    end
    return -(((-v) + GRID // 2) // GRID) * GRID
end

# ---- nabidka karty ---------------------------------------------------------------------------

WIDGET_TITLES = {"today": "Clock & Weather", "system": "System Health", "music": "Now Playing", "calendar": "Calendar"}

function card_menu(name):
    menu = gtk.menu_new()
    edit = gtk.menu_item_new(i18n.T("Edit Widgets…"))
    call gtk.connect(edit, "activate", on_menu_edit)
    call gtk.menu_append(menu, edit)
    call gtk.menu_append(menu, gtk.separator_menu_item_new())
    remove = gtk.menu_item_new(i18n.TF("Remove “%s”", [i18n.T(WIDGET_TITLES[name])]))
    ui["menu_target"] = name
    call gtk.connect(remove, "activate", on_menu_remove)
    call gtk.menu_append(menu, remove)
    call gtk.widget_show_all(menu)
    call gtk.menu_popup_at_pointer(menu)
    return 0
end

function on_menu_edit(item):
    call spawn(["luxos-widgets", "settings"])
    return 0
end

function on_menu_remove(item):
    name = ui.get("menu_target", "")
    names = []
    for n in conf["widgets"]:
        if n != name:
            names.append(n)
        end
    end
    call set_widgets(names)
    return 0
end

function on_card_realize(widget):
    call gtk.widget_set_cursor(widget, "pointer")
    return 0
end

function spawn(argv):
    call glib.spawn_quiet(argv)
    return 0
end

function is_primary_click(event):
    return gtk.event_button(event) == 1 and not gtk.event_is_double_click(event)
end

function white(cr, alpha):
    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, alpha)
    return 0
end

# ---- barevne ikony pocasi (cairo) ------------------------------------------------------------

# sin/cos bez modulu math: Taylor po redukci na <-pi, pi>
function sin_approx(x):
    while x > cairo.PI:
        x = x - 2.0 * cairo.PI
    end
    while x < -cairo.PI:
        x = x + 2.0 * cairo.PI
    end
    x2 = x * x
    return x * (1.0 - x2 / 6.0 * (1.0 - x2 / 20.0 * (1.0 - x2 / 42.0 * (1.0 - x2 / 72.0 * (1.0 - x2 / 110.0)))))
end

function cos_approx(x):
    return sin_approx(x + cairo.PI / 2.0)
end

function draw_sun(cr, cx, cy, r):
    pat = cairo.pattern_create_linear(cx, cy - r, cx, cy + r)
    call cairo.pattern_add_color_stop_rgba(pat, 0.0, 1.0, 0.86, 0.32, 1.0)
    call cairo.pattern_add_color_stop_rgba(pat, 1.0, 1.0, 0.62, 0.10, 1.0)
    call cairo.set_line_width(cr, 2.0)
    call cairo.set_line_cap(cr, 1)
    call cairo.set_source(cr, pat)
    for i in range(8):
        a = Float(i) * cairo.PI / 4.0
        call cairo.move_to(cr, cx + (r + 2.5) * cos_approx(a), cy + (r + 2.5) * sin_approx(a))
        call cairo.line_to(cr, cx + (r + 5.5) * cos_approx(a), cy + (r + 5.5) * sin_approx(a))
        call cairo.stroke(cr)
    end
    call cairo.arc(cr, cx, cy, r, 0.0, 2.0 * cairo.PI)
    call cairo.fill(cr)
    call cairo.pattern_destroy(pat)
    return 0
end

function draw_moon(cr, cx, cy, r):
    call cairo.set_source_rgba(cr, 1.0, 0.93, 0.62, 1.0)
    call cairo.arc(cr, cx, cy, r, 0.0, 2.0 * cairo.PI)
    call cairo.arc_negative(cr, cx + r * 0.55, cy - r * 0.35, r * 0.85, 2.0 * cairo.PI, 0.0)
    call cairo.fill(cr)
    return 0
end

function draw_cloud(cr, x, y, w, shade):
    # tri kruhy a zaobleny spodek, svetly prechod
    h = w * 0.58
    pat = cairo.pattern_create_linear(x, y, x, y + h)
    if ui["cards"].get("today", {}).get("light", False):
        call cairo.pattern_add_color_stop_rgba(pat, 0.0, 0.65, 0.70, 0.79, 1.0)
        call cairo.pattern_add_color_stop_rgba(pat, 1.0, 0.48, 0.55, 0.66, 1.0)
    else:
        call cairo.pattern_add_color_stop_rgba(pat, 0.0, 1.0, 1.0, 1.0, 1.0)
        call cairo.pattern_add_color_stop_rgba(pat, 1.0, shade, shade, shade + 0.04, 1.0)
    end
    call cairo.set_source(cr, pat)
    call cairo.new_path(cr)
    call cairo.arc(cr, x + w * 0.30, y + h * 0.62, h * 0.36, 0.0, 2.0 * cairo.PI)
    call cairo.fill(cr)
    call cairo.arc(cr, x + w * 0.55, y + h * 0.45, h * 0.46, 0.0, 2.0 * cairo.PI)
    call cairo.fill(cr)
    call cairo.arc(cr, x + w * 0.76, y + h * 0.66, h * 0.32, 0.0, 2.0 * cairo.PI)
    call cairo.fill(cr)
    call cairo.rounded_rectangle(cr, x + w * 0.10, y + h * 0.58, w * 0.82, h * 0.42, h * 0.21)
    call cairo.fill(cr)
    call cairo.pattern_destroy(pat)
    return 0
end

# kind: clear, partly, cloudy, fog, rain, snow, storm; s = velikost ctverce
function draw_weather(cr, kind, day, x, y, s):
    if kind == "clear":
        if day:
            call draw_sun(cr, x + s / 2.0, y + s / 2.0, s * 0.26)
        else:
            call draw_moon(cr, x + s / 2.0, y + s / 2.0, s * 0.32)
        end
        return 0
    end
    if kind == "partly":
        if day:
            call draw_sun(cr, x + s * 0.62, y + s * 0.34, s * 0.20)
        else:
            call draw_moon(cr, x + s * 0.64, y + s * 0.32, s * 0.22)
        end
        call draw_cloud(cr, x + s * 0.02, y + s * 0.36, s * 0.80, 0.86)
        return 0
    end
    shade = 0.84
    if kind == "rain" or kind == "storm":
        shade = 0.74
    end
    call draw_cloud(cr, x + s * 0.06, y + s * 0.14, s * 0.88, shade)
    if kind == "fog":
        call cairo.set_line_width(cr, 2.0)
        call cairo.set_line_cap(cr, 1)
        call white(cr, 0.85)
        for i in range(2):
            yy = y + s * (0.80 + Float(i) * 0.14)
            call cairo.move_to(cr, x + s * 0.18 + Float(i) * s * 0.08, yy)
            call cairo.line_to(cr, x + s * 0.86 - Float(i) * s * 0.08, yy)
            call cairo.stroke(cr)
        end
    elif kind == "rain":
        call cairo.set_line_width(cr, 2.0)
        call cairo.set_line_cap(cr, 1)
        call cairo.set_source_rgba(cr, 0.45, 0.78, 1.0, 1.0)
        for i in range(3):
            xx = x + s * (0.30 + Float(i) * 0.20)
            call cairo.move_to(cr, xx, y + s * 0.74)
            call cairo.line_to(cr, xx - s * 0.06, y + s * 0.94)
            call cairo.stroke(cr)
        end
    elif kind == "snow":
        call white(cr, 1.0)
        for i in range(3):
            call cairo.arc(cr, x + s * (0.30 + Float(i) * 0.20), y + s * (0.82 + Float(i % 2) * 0.10), s * 0.05, 0.0, 2.0 * cairo.PI)
            call cairo.fill(cr)
        end
    elif kind == "storm":
        call cairo.set_source_rgba(cr, 1.0, 0.80, 0.20, 1.0)
        call cairo.move_to(cr, x + s * 0.54, y + s * 0.66)
        call cairo.line_to(cr, x + s * 0.40, y + s * 0.86)
        call cairo.line_to(cr, x + s * 0.52, y + s * 0.86)
        call cairo.line_to(cr, x + s * 0.44, y + s * 1.0)
        call cairo.line_to(cr, x + s * 0.66, y + s * 0.78)
        call cairo.line_to(cr, x + s * 0.54, y + s * 0.78)
        call cairo.close_path(cr)
        call cairo.fill(cr)
    end
    return 0
end

# WMO kod pocasi -> druh ikony
function weather_kind(code):
    if code == 0:
        return "clear"
    end
    if code == 1 or code == 2:
        return "partly"
    end
    if code == 3:
        return "cloudy"
    end
    if code == 45 or code == 48:
        return "fog"
    end
    if (code >= 71 and code <= 77) or code == 85 or code == 86:
        return "snow"
    end
    if code >= 95:
        return "storm"
    end
    return "rain"
end

# ---- karta Dnes: datum, cas, pocasi ---------------------------------------------------------

function on_today_click(event, widget):
    if not is_primary_click(event):
        return False
    end
    # pocasi vpravo otevre aplikaci Pocasi, cas aplikaci Hodiny (bez ni Kalendar)
    card = ui["cards"]["today"]
    # poloha v okne karty (udalost muze prijit z kreslici plochy s vlastnimi souradnicemi)
    x = gtk.event_x_root(event) - Float(ui["placed"].get("today", [0, 0])[0] + PAD)
    if gtk.widget_get_visible(card["wx"]) and x > Float(gtk.widget_get_allocated_width(widget)) * 0.55:
        call spawn(["luxos-weather"])
    elif glib.find_program_in_path("luxos-clock-app") != "":
        call spawn(["luxos-clock-app"])
    else:
        call spawn(["luxos-calendar-toggle"])
    end
    return True
end

function on_wx_icon_draw(cr, area):
    w = weather["data"]
    if w == None:
        return True
    end
    call draw_weather(cr, weather_kind(w["code"]), w["day"], 1.0, 1.0, 30.0)
    return True
end

function build_today():
    c = card_new("today", on_today_click, gtk.HORIZONTAL)
    left = gtk.box_new(gtk.VERTICAL, 0)
    c["date"] = label("", ["lw-date"])
    c["time"] = label("", ["lw-time"])
    call gtk.box_pack_start(left, c["date"], False, False, 0)
    call gtk.box_pack_start(left, c["time"], False, False, 0)
    call gtk.widget_set_valign(left, gtk.ALIGN_CENTER)
    call gtk.box_pack_start(c["box"], left, True, True, 0)

    wx = gtk.box_new(gtk.HORIZONTAL, 0)
    sep = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_add_class(sep, "lw-vsep")
    call gtk.box_pack_start(wx, sep, False, False, 0)
    col = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_valign(col, gtk.ALIGN_CENTER)
    top = gtk.box_new(gtk.HORIZONTAL, 6)
    c["wx_icon"] = area_new()
    call gtk.widget_set_size_request(c["wx_icon"], 32, 32)
    call gtk.connect(c["wx_icon"], "draw", on_wx_icon_draw)
    c["wx_temp"] = label("", ["lw-temp"])
    call gtk.box_pack_start(top, c["wx_icon"], False, False, 0)
    call gtk.box_pack_start(top, c["wx_temp"], False, False, 0)
    c["wx_cond"] = label("", ["lw-cond"])
    c["wx_city"] = label("", ["lw-small", "dim"])
    for l in [c["wx_cond"], c["wx_city"]]:
        call gtk.label_set_ellipsize(l, gtk.ELLIPSIZE_END)
        call gtk.label_set_max_width_chars(l, 13)
    end
    call gtk.box_pack_start(col, top, False, False, 0)
    call gtk.box_pack_start(col, c["wx_cond"], False, False, 2)
    call gtk.box_pack_start(col, c["wx_city"], False, False, 0)
    call gtk.box_pack_start(wx, col, False, False, 0)
    call gtk.box_pack_start(c["box"], wx, False, False, 0)
    c["wx"] = wx
    call gtk.widget_set_no_show_all(wx, True)
    call gtk.widget_show_all(col)
    call gtk.widget_show_all(sep)
    return c
end

function update_today():
    if "today" not in ui["cards"]:
        return 0
    end
    c = ui["cards"]["today"]
    call gtk.label_set_text(c["date"], glib.date_time_format("%a %-d. %b"))
    call gtk.label_set_text(c["time"], glib.date_time_format("%H:%M"))
    w = weather["data"]
    if w == None:
        call gtk.widget_hide(c["wx"])
        return 0
    end
    call gtk.label_set_text(c["wx_temp"], String(w["temp"]) + w["unit"])
    call gtk.label_set_text(c["wx_cond"], i18n.T(w["condition"]))
    call gtk.label_set_text(c["wx_city"], w["name"])
    call gtk.widget_queue_draw(c["wx_icon"])
    call gtk.widget_show(c["wx"])
    return 0
end

# ---- pocasi ---------------------------------------------------------------------------------

function cache_dir():
    base = env.get("XDG_CACHE_HOME", "")
    if base == None or base == "":
        base = glib.home_dir() + "/.cache"
    end
    return base
end

function unit_of(system):
    if system == "imperial":
        return "°F"
    end
    return "°C"
end

function weather_from_summary():
    raw = glib.read_text(cache_dir() + "/luxos/weather/summary.json")
    if raw == "":
        return None
    end
    data = None
    try:
        data = json.decode(raw)
    else:
        return None
    end
    if type(data) != "Dictionary" or data.get("temp") == None or data.get("fetched") == None:
        return None
    end
    if glib.now() - data["fetched"] > WEATHER_MAX_AGE:
        return None
    end
    return {"temp": data["temp"], "code": data.get("code", 3), "day": data.get("is_day") != False,
            "condition": String(data.get("condition", "")), "name": String(data.get("name", "")),
            "unit": unit_of(data.get("units", "metric")), "fetched": data["fetched"]}
end

function forecast_file():
    return glib.user_runtime_dir() + "/luxos-widgets-weather.json"
end

function weather_from_forecast():
    raw = glib.read_text(forecast_file())
    if raw == "":
        return None
    end
    data = None
    try:
        data = json.decode(raw)
    else:
        return None
    end
    if type(data) != "Dictionary" or data.get("ok") != True:
        return None
    end
    cur = data["data"]["current"]
    temp = Float(cur["temp"])
    rounded = Int(temp + 0.5)
    if temp < 0.0:
        rounded = -Int(-temp + 0.5)
    end
    return {"temp": rounded, "code": cur["code"], "day": cur.get("is_day") != False,
            "condition": String(cur.get("condition", "")), "name": String(data["location"]["name"]),
            "unit": unit_of(data.get("unit_system", "metric")), "fetched": data.get("fetched", glib.now())}
end

function weather_reload():
    best = weather_from_summary()
    f = weather_from_forecast()
    if f != None and (best == None or f["fetched"] > best["fetched"]):
        best = f
    end
    weather["data"] = best
    call update_today()
    return 0
end

function on_forecast_done(pid, status):
    weather["fetching"] = False
    call weather_reload()
    return 0
end

# Cerstva predpoved jen kdyz Pocasi ma ulozene misto (luxos-weather --json nikdy nezjistuje polohu z IP)
function weather_refresh():
    if weather["fetching"] or "today" not in conf["widgets"]:
        return True
    end
    # starsi Pocasi bez datoveho rozhrani by s neznamym prepinacem otevrelo okno
    prog = glib.find_program_in_path("luxos-weather")
    if prog == "" or glib.read_text(prog).find("\"--json\"") < 0:
        return True
    end
    weather["fetching"] = True
    cmd = "luxos-weather --json forecast --days 1 --hours 0 > " + glib.shell_quote(forecast_file() + ".new") + " 2>/dev/null && mv -f " + glib.shell_quote(forecast_file() + ".new") + " " + glib.shell_quote(forecast_file())
    if glib.spawn_watched(["sh", "-c", cmd], on_forecast_done) == 0:
        weather["fetching"] = False
    end
    return True
end

function on_weather_cache(path, event, other):
    call weather_reload()
    return 0
end

# ---- karta Kalendar -------------------------------------------------------------------------

function on_calendar_click(event, widget):
    if not is_primary_click(event):
        return False
    end
    call spawn(["luxos-calendar-toggle"])
    return True
end

# Text je citelny diky omezenemu jasu skla, bez tvrdeho obrysu a stinu.
function ink(cr, name, alpha):
    if ui["cards"].get(name, {}).get("light", False):
        call cairo.set_source_rgba(cr, 0.098, 0.122, 0.169, alpha)
    else:
        call white(cr, alpha)
    end
    return 0
end

function glass_text(cr, name, x, y, text, font, alpha):
    call ink(cr, name, alpha)
    call pango.draw_text(cr, Float(x), Float(y), text, font)
    return 0
end

function on_calendar_draw(cr, area):
    width = Float(gtk.widget_get_allocated_width(area))
    d = glib.local_date()
    year = d[0]
    month = d[1]
    today = d[2]
    call glass_text(cr, "calendar", 2, 0, glib.format_date(year, month, 1, "%OB %Y"), "Inter Bold 10", 1.0)
    first = glib.first_weekday()
    col_w = width / 7.0
    # zkratky dnu (2024-01-01 je pondeli)
    for i in range(7):
        wd = ((first - 1 + i) % 7) + 1
        name = glib.format_date(2024, 1, wd, "%a")
        size = pango.text_size(cr, name, "Inter 8")
        call glass_text(cr, "calendar", Float(i) * col_w + (col_w - Float(size[0])) / 2.0, 22, name, "Inter 8", 0.90)
    end
    offset = (glib.weekday(year, month, 1) - first + 7) % 7
    days = glib.days_in_month(year, month)
    row_h = 19.0
    for day in range(1, days + 1):
        cell = offset + day - 1
        x = Float(cell % 7) * col_w
        y = 40.0 + Float(cell // 7) * row_h
        num = String(day)
        font = "Inter 9"
        if day == today:
            font = "Inter Bold 9"
            call ink(cr, "calendar", 1.0)
            call cairo.arc(cr, x + col_w / 2.0, y + 8.0, 9.5, 0.0, 2.0 * cairo.PI)
            call cairo.fill(cr)
        end
        size = pango.text_size(cr, num, font)
        tx = x + (col_w - Float(size[0])) / 2.0
        if day == today:
            if ui["cards"]["calendar"].get("light", False):
                call white(cr, 1.0)
            else:
                call cairo.set_source_rgba(cr, 0.10, 0.10, 0.14, 1.0)
            end
            call pango.draw_text(cr, tx, y, num, font)
        elif glib.weekday(year, month, day) >= 6:
            call glass_text(cr, "calendar", tx, y, num, font, 0.90)
        else:
            call glass_text(cr, "calendar", tx, y, num, font, 1.0)
        end
    end
    return True
end

function build_calendar():
    c = card_new("calendar", on_calendar_click, gtk.HORIZONTAL)
    area = area_new()
    call gtk.widget_set_size_request(area, WIDTH - 2 * PAD - 38, 40 + 6 * 19 + 2)
    call gtk.connect(area, "draw", on_calendar_draw)
    call gtk.box_pack_start(c["box"], area, True, True, 0)
    c["area"] = area
    return c
end

function update_calendar():
    if "calendar" in ui["cards"]:
        call gtk.widget_queue_draw(ui["cards"]["calendar"]["area"])
    end
    return 0
end

# ---- karta Stav systemu ---------------------------------------------------------------------

function on_system_click(event, widget):
    if not is_primary_click(event):
        return False
    end
    call spawn(["luxos-monitor"])
    return True
end

function on_more(button):
    call spawn(["luxos-monitor"])
    return 0
end

function read_cpu():
    line = glib.read_text("/proc/stat").split("\n")[0]
    nums = []
    for part in line.split(" "):
        if part != "" and part != "cpu":
            nums.append(Int(part))
        end
    end
    if len(nums) < 4:
        return 0
    end
    total = 0
    for n in nums[:8]:
        total = total + n
    end
    idle = nums[3]
    if len(nums) > 4:
        idle = idle + nums[4]
    end
    busy = total - idle
    if cpu["total"] > 0 and total > cpu["total"]:
        cpu["pct"] = Int(100.0 * Float(busy - cpu["busy"]) / Float(total - cpu["total"]) + 0.5)
        # stav systemu podle prumeru za posledni 4 mereni (kratka spicka ho neprepne)
        cpu["recent"].append(cpu["pct"])
        if len(cpu["recent"]) > 4:
            cpu["recent"] = cpu["recent"][1:]
        end
    end
    cpu["busy"] = busy
    cpu["total"] = total
    return cpu["pct"]
end

function read_mem():
    total = 0
    avail = 0
    for line in glib.read_text("/proc/meminfo").split("\n"):
        if line.startswith("MemTotal:") or line.startswith("MemAvailable:"):
            value = 0
            for part in line.split(" "):
                if part != "" and text.is_digits(part):
                    value = Int(part)
                end
            end
            if line.startswith("MemTotal:"):
                total = value
            else:
                avail = value
            end
        end
    end
    if total <= 0:
        return 0
    end
    return Int(100.0 * Float(total - avail) / Float(total) + 0.5)
end

function read_disk():
    d = sys.disk_usage("/")
    if len(d) != 3 or d[0] - d[1] + d[2] <= 0:
        return 0
    end
    return Int(100.0 * Float(d[0] - d[1]) / Float(d[0] - d[1] + d[2]) + 0.5)
end

# [klic textu, barva tecky]: Vyborny / Dobry / Vytizeny
function health():
    avg = 0
    if len(cpu["recent"]) > 0:
        avg = sum(cpu["recent"]) // len(cpu["recent"])
    end
    if avg >= 85 or stats["mem"] >= 90 or stats["disk"] >= 95:
        return ["Busy", [1.0, 0.42, 0.32]]
    end
    if avg >= 60 or stats["mem"] >= 80 or stats["disk"] >= 90:
        return ["Good", [1.0, 0.80, 0.25]]
    end
    return ["Excellent", [0.20, 0.82, 0.38]]
end

function stats_tick():
    if "system" not in ui["cards"]:
        timers["stats"] = 0
        return False
    end
    stats["cpu"] = read_cpu()
    stats["mem"] = read_mem()
    if monotonic() - stats["disk_at"] > 60.0 or stats["disk_at"] == 0.0:
        stats["disk"] = read_disk()
        stats["disk_at"] = monotonic()
    end
    c = ui["cards"]["system"]
    h = health()
    call gtk.label_set_text(c["status"], i18n.T(h[0]))
    c["dot_color"] = h[1]
    call gtk.widget_queue_draw(c["dot"])
    call gtk.widget_queue_draw(c["area"])
    return True
end

function on_dot_draw(cr, area):
    color = ui["cards"]["system"].get("dot_color", [0.20, 0.82, 0.38])
    call cairo.set_source_rgba(cr, color[0], color[1], color[2], 1.0)
    call cairo.arc(cr, 8.0, 8.0, 7.5, 0.0, 2.0 * cairo.PI)
    call cairo.fill(cr)
    call white(cr, 1.0)
    call cairo.set_line_width(cr, 1.8)
    call cairo.set_line_cap(cr, 1)
    call cairo.set_line_join(cr, 1)
    call cairo.move_to(cr, 4.6, 8.2)
    call cairo.line_to(cr, 7.0, 10.6)
    call cairo.line_to(cr, 11.6, 5.6)
    call cairo.stroke(cr)
    return True
end

# male ikony uvnitr oblouku (bile obrysy): 0 procesor, 1 pamet, 2 disk
function draw_gauge_icon(cr, kind, cx, cy):
    call ink(cr, "system", 0.95)
    call cairo.set_line_width(cr, 1.4)
    call cairo.set_line_cap(cr, 1)
    if kind == 0:
        call cairo.rounded_rectangle(cr, cx - 5.0, cy - 5.0, 10.0, 10.0, 2.0)
        call cairo.stroke(cr)
        call cairo.rectangle(cr, cx - 2.0, cy - 2.0, 4.0, 4.0)
        call cairo.fill(cr)
        for i in range(3):
            o = -3.0 + Float(i) * 3.0
            call cairo.move_to(cr, cx + o, cy - 5.0)
            call cairo.line_to(cr, cx + o, cy - 7.5)
            call cairo.move_to(cr, cx + o, cy + 5.0)
            call cairo.line_to(cr, cx + o, cy + 7.5)
            call cairo.move_to(cr, cx - 5.0, cy + o)
            call cairo.line_to(cr, cx - 7.5, cy + o)
            call cairo.move_to(cr, cx + 5.0, cy + o)
            call cairo.line_to(cr, cx + 7.5, cy + o)
        end
        call cairo.stroke(cr)
    elif kind == 1:
        call cairo.rounded_rectangle(cr, cx - 7.5, cy - 4.0, 15.0, 8.0, 1.5)
        call cairo.stroke(cr)
        for i in range(4):
            call cairo.rectangle(cr, cx - 5.5 + Float(i) * 3.2, cy - 2.0, 1.8, 3.0)
        end
        call cairo.fill(cr)
        for i in range(5):
            call cairo.move_to(cr, cx - 6.0 + Float(i) * 3.0, cy + 4.0)
            call cairo.line_to(cr, cx - 6.0 + Float(i) * 3.0, cy + 6.0)
        end
        call cairo.stroke(cr)
    else:
        for i in range(3):
            yy = cy - 5.0 + Float(i) * 4.0
            call cairo.rounded_rectangle(cr, cx - 6.0, yy, 12.0, 3.2, 1.6)
            call cairo.stroke(cr)
        end
    end
    return 0
end

function on_system_draw(cr, area):
    width = Float(gtk.widget_get_allocated_width(area))
    values = [stats["cpu"], stats["mem"], stats["disk"]]
    names = [i18n.T("CPU"), i18n.T("Memory"), i18n.T("Storage")]
    col_w = width / 3.0
    r = 27.0
    start = cairo.PI * 0.75
    sweep = cairo.PI * 1.5
    for i in range(3):
        cx = Float(i) * col_w + col_w / 2.0
        cy = 34.0
        call cairo.set_line_width(cr, 3.5)
        call cairo.set_line_cap(cr, 1)
        call ink(cr, "system", 0.14)
        call cairo.new_path(cr)
        call cairo.arc(cr, cx, cy, r, start, start + sweep)
        call cairo.stroke(cr)
        frac = Float(max(0, min(100, values[i]))) / 100.0
        if frac > 0.0:
            colors = RING_COLORS[i]
            if ui["cards"]["system"].get("light", False):
                colors = [[[0.20, 0.37, 0.70], [0.31, 0.49, 0.83]], [[0.10, 0.44, 0.36], [0.17, 0.56, 0.43]], [[0.43, 0.29, 0.67], [0.57, 0.40, 0.78]]][i]
            end
            pat = cairo.pattern_create_linear(cx - r, cy + r, cx + r, cy - r)
            call cairo.pattern_add_color_stop_rgba(pat, 0.0, colors[0][0], colors[0][1], colors[0][2], 1.0)
            call cairo.pattern_add_color_stop_rgba(pat, 1.0, colors[1][0], colors[1][1], colors[1][2], 1.0)
            call cairo.set_source(cr, pat)
            call cairo.new_path(cr)
            call cairo.arc(cr, cx, cy, r, start, start + sweep * frac)
            call cairo.stroke(cr)
            call cairo.pattern_destroy(pat)
        end
        call draw_gauge_icon(cr, i, cx, cy - 9.0)
        num = String(values[i]) + "%"
        size = pango.text_size(cr, num, "Inter Bold 10")
        call glass_text(cr, "system", cx - Float(size[0]) / 2.0, cy + 3.0, num, "Inter Bold 10", 1.0)
        size = pango.text_size(cr, names[i], "Inter 9")
        call glass_text(cr, "system", cx - Float(size[0]) / 2.0, cy + r + 3.0, names[i], "Inter 9", 0.90)
    end
    return True
end

# "LuxOS Sirius" z /etc/os-release
function system_title():
    name = "LuxOS"
    codename = ""
    for line in glib.read_text("/etc/os-release").split("\n"):
        if line.startswith("NAME="):
            name = line[5:].replace("\"", "")
        elif line.startswith("VERSION_CODENAME="):
            codename = line[17:].replace("\"", "")
        end
    end
    if codename == "":
        return name
    end
    return name + " " + codename[:1].upper() + codename[1:]
end

function build_system():
    c = card_new("system", on_system_click, gtk.VERTICAL)
    head = gtk.box_new(gtk.HORIZONTAL, 8)
    logo = gtk.image_new_from_icon_name("luxos-logo-symbolic", 4)
    call gtk.image_set_pixel_size(logo, 18)
    call gtk.box_pack_start(head, logo, False, False, 0)
    call gtk.box_pack_start(head, label(system_title(), ["lw-title"]), True, True, 0)
    more = gtk.button_new("⋯")
    call gtk.widget_add_class(more, "lw-more")
    call gtk.widget_set_tooltip(more, i18n.T("System Monitor"))
    call gtk.connect(more, "clicked", on_more)
    call gtk.box_pack_start(head, more, False, False, 0)
    call gtk.box_pack_start(c["box"], head, False, False, 0)

    row = gtk.box_new(gtk.HORIZONTAL, 8)
    dot = area_new()
    call gtk.widget_set_size_request(dot, 16, 16)
    call gtk.widget_set_valign(dot, gtk.ALIGN_CENTER)
    call gtk.connect(dot, "draw", on_dot_draw)
    call gtk.box_pack_start(row, dot, False, False, 0)
    call gtk.box_pack_start(row, label(i18n.T("System Health"), ["lw-health"]), True, True, 0)
    c["status"] = label("", ["lw-small", "dim"])
    call gtk.box_pack_end(row, c["status"], False, False, 0)
    call gtk.widget_set_margins(row, 0, 0, 10, 0)
    call gtk.box_pack_start(c["box"], row, False, False, 0)
    sep = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_add_class(sep, "lw-hsep")
    call gtk.box_pack_start(c["box"], sep, False, False, 0)

    area = area_new()
    call gtk.widget_set_size_request(area, WIDTH - 2 * PAD - 38, 88)
    call gtk.connect(area, "draw", on_system_draw)
    call gtk.box_pack_start(c["box"], area, False, False, 0)
    c["area"] = area
    c["dot"] = dot
    return c
end

# ---- karta Hudba ----------------------------------------------------------------------------

function on_play(button):
    cur = mpris.current()
    if cur != None:
        call mpris.send(cur["bus"], "PlayPause")
    end
    return 0
end

function on_next(button):
    cur = mpris.current()
    if cur != None:
        call mpris.send(cur["bus"], "Next")
    end
    return 0
end

function build_music():
    c = card_new("music", None, gtk.HORIZONTAL)
    call gtk.box_set_spacing(c["box"], 12)
    art = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_add_class(art, "lw-art")
    c["art_icon"] = gtk.image_new_from_icon_name("audio-x-generic-symbolic", 4)
    call gtk.image_set_pixel_size(c["art_icon"], 22)
    call gtk.box_pack_start(art, c["art_icon"], True, True, 0)
    call gtk.widget_set_valign(art, gtk.ALIGN_CENTER)
    call gtk.box_pack_start(c["box"], art, False, False, 0)
    col = gtk.box_new(gtk.VERTICAL, 1)
    call gtk.widget_set_valign(col, gtk.ALIGN_CENTER)
    c["title"] = label("", ["lw-title"])
    c["artist"] = label("", ["lw-small", "dim"])
    for l in [c["title"], c["artist"]]:
        call gtk.label_set_ellipsize(l, gtk.ELLIPSIZE_END)
        call gtk.label_set_max_width_chars(l, 18)
        call gtk.box_pack_start(col, l, False, False, 0)
    end
    call gtk.box_pack_start(c["box"], col, True, True, 0)
    c["play"] = gtk.button_new_from_icon_name("media-playback-start-symbolic", 4)
    c["next"] = gtk.button_new_from_icon_name("media-skip-forward-symbolic", 4)
    for b in [c["play"], c["next"]]:
        call gtk.widget_add_class(b, "lw-btn")
        call gtk.widget_set_valign(b, gtk.ALIGN_CENTER)
        call gtk.box_pack_start(c["box"], b, False, False, 0)
    end
    call gtk.widget_set_tooltip(c["play"], i18n.T("Play/Pause"))
    call gtk.widget_set_tooltip(c["next"], i18n.T("Next"))
    call gtk.connect(c["play"], "clicked", on_play)
    call gtk.connect(c["next"], "clicked", on_next)
    call gtk.widget_set_no_show_all(c["ev"], True)
    call gtk.widget_show_all(c["box"])
    return c
end

function update_music():
    if "music" not in ui["cards"]:
        return 0
    end
    c = ui["cards"]["music"]
    cur = mpris.current()
    if cur == None and ui["settings"]:
        # nahled v galerii
        call gtk.label_set_text(c["title"], i18n.T("Nothing is playing"))
        call gtk.label_set_text(c["artist"], i18n.T("Music and videos appear here"))
        call gtk.widget_show(c["ev"])
        return 0
    end
    win = ui["wins"].get("music", 0)
    if cur == None:
        call gtk.widget_hide(c["ev"])
        if win != 0:
            call gtk.widget_hide(win)
        end
        call place_all()
        return 0
    end
    title = cur["title"]
    if title == "":
        title = cur["app"]
    end
    artist = cur["artist"]
    if artist == "":
        artist = cur["app"]
    end
    call gtk.label_set_text(c["title"], title)
    call gtk.label_set_text(c["artist"], artist)
    icon = "media-playback-start-symbolic"
    if cur["playing"]:
        icon = "media-playback-pause-symbolic"
    end
    call gtk.button_set_image(c["play"], gtk.image_new_from_icon_name(icon, 4))
    call gtk.widget_set_sensitive(c["next"], cur["can_next"])
    was = gtk.widget_get_visible(c["ev"])
    call gtk.widget_show(c["ev"])
    if win != 0:
        call gtk.widget_show(win)
    end
    if not was:
        # karta pod ostatnimi: vychozi rozmisteni pocita jen viditelne karty
        call place_all()
    end
    return 0
end

function on_music_changed():
    call update_music()
    return 0
end

# ---- okna karet ------------------------------------------------------------------------------

function create_window(name):
    win = gtk.window_new(i18n.T("Widget"))
    call gtk.widget_add_class(win, "lw")
    call gtk.window_set_decorated(win, False)
    call gtk.window_set_resizable(win, False)
    call gtk.window_set_skip_taskbar_hint(win, True)
    call gtk.window_set_skip_pager_hint(win, True)
    call gtk.window_set_keep_below(win, True)
    call gtk.window_set_accept_focus(win, False)
    call gtk.window_stick(win)
    call gtk.window_set_rgba(win)
    call gtk.window_set_wmclass(win, "luxos-widgets", "Luxos-widgets")
    box = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_add_class(box, "lw-col")
    call gtk.widget_set_size_request(box, WIDTH, -1)
    call gtk.container_add(win, box)
    call gtk.connect(win, "delete-event", on_delete)
    call gtk.connect(win, "draw", on_window_draw)
    return [win, box]
end

function on_delete(event, window):
    return True
end

function build_card(name):
    if name == "today":
        return build_today()
    elif name == "calendar":
        return build_calendar()
    elif name == "system":
        return build_system()
    end
    return build_music()
end

# Pozice [x, y] karty na obrazovce, aby byla cela na pracovni plose hlavniho monitoru
function clamp_to_area(name, x, y):
    geo = gtk.primary_monitor_workarea()
    h = 120
    win = ui["wins"].get(name, 0)
    if win != 0:
        h = max(40, gtk.window_get_size(win)[1])
    end
    x = max(geo[0] - PAD, min(x, geo[0] + geo[2] - WIDTH + PAD))
    y = max(geo[1], min(y, geo[1] + geo[3] - h))
    return [x, y]
end

# Ulozene pozice, ostatni karty pod sebou na zvolene strane (jako drive v jednom sloupci)
function place_all():
    geo = gtk.primary_monitor_workarea()
    x_default = geo[0] + geo[2] - WIDTH
    if conf["side"] == "left":
        x_default = geo[0]
    end
    y_next = geo[1] + 4
    changed = False
    for name in conf["widgets"]:
        win = ui["wins"].get(name, 0)
        if win == 0:
            continue
        end
        h = gtk.widget_get_preferred_height(win)[1]
        visible = gtk.widget_get_visible(ui["cards"][name]["ev"])
        if name in conf["pos"]:
            xy = clamp_to_area(name, geo[0] + conf["pos"][name][0], geo[1] + conf["pos"][name][1])
        else:
            xy = [x_default, y_next]
            if visible:
                y_next = y_next + h
            end
        end
        if ui["placed"].get(name) != xy:
            ui["placed"][name] = xy
            call gtk.window_move(win, xy[0], xy[1])
            changed = True
        end
    end
    if changed:
        # jina oblast tapety pod kartami
        call theme_refresh()
    end
    return 0
end

# Pracovni plocha se meni (lista nastavi rezervovane misto az po startu, jiny monitor, vyska listy)
function place_tick():
    if theme["geometry"] != primary_geometry():
        call theme_apply()
    end
    call place_all()
    return True
end

function rebuild():
    for name in List(ui["wins"].keys()):
        if name not in conf["widgets"]:
            call gtk.widget_destroy(ui["wins"][name])
            del(ui["wins"][name])
            del(ui["cards"][name])
            if name in ui["placed"]:
                del(ui["placed"][name])
            end
        end
    end
    for name in conf["widgets"]:
        if name in ui["wins"]:
            continue
        end
        pair = create_window(name)
        c = build_card(name)
        ui["cards"][name] = c
        ui["wins"][name] = pair[0]
        call gtk.connect(c["box"], "size-allocate", on_box_allocate)
        call gtk.box_pack_start(pair[1], c["ev"], False, False, 0)
        if name != "music":
            call gtk.widget_show_all(c["ev"])
        end
        call gtk.widget_show(pair[1])
        if name != "music":
            call gtk.widget_show(pair[0])
        end
    end
    call update_today()
    call update_music()
    call start_stats()
    return 0
end

function start_stats():
    if "system" in ui["cards"]:
        if timers["stats"] == 0:
            call read_cpu()
            timers["stats"] = glib.timeout_add_seconds(2, stats_tick)
        end
        call stats_tick()
    end
    return 0
end

function on_conf_event(path, event, other):
    call read_conf()
    if ui["settings"]:
        call gallery_refresh()
        return 0
    end
    if not conf["enabled"]:
        call gtk.main_quit()
        return 0
    end
    call rebuild()
    call place_all()
    return 0
end

# kazdou minutu: cas, datum, mesic (pulnoc)
function minute_tick():
    call update_today()
    call update_calendar()
    d = glib.local_date()
    call glib.timeout_add((60 - d[5]) * 1000 + 50, minute_tick)
    return False
end

function start_common():
    safe:
        bus["session"] = gio.session_bus()
    end
    call theme_apply()
    if bus["session"] != 0:
        call mpris.init(bus["session"])
        call mpris.connect(on_music_changed)
        safe:
            call gio.subscribe_values(bus["session"], "org.xfce.Xfconf", "org.xfce.Xfconf", "PropertyChanged", "/org/xfce/Xfconf", on_xfconf_changed)
        end
    end
    call weather_reload()
    safe:
        call sys.mkdir_p(glib.user_config_dir() + "/luxos")
        call gio.file_monitor(conf_path(), on_conf_event)
    end
    safe:
        call gio.file_monitor(appearance_path(), on_appearance_event)
    end
    if not ui["settings"]:
        safe:
            call x11.root_filter(on_root_property, 0)
            call x11.root_watch_properties()
        end
    end
    safe:
        call sys.mkdir_p(cache_dir() + "/luxos/weather")
        call gio.file_monitor(cache_dir() + "/luxos/weather/summary.json", on_weather_cache)
    end
    return 0
end

function start():
    call gtk.init()
    call read_conf()
    if not conf["enabled"]:
        return 0
    end
    # jedna instance na uzivatele a displej (abstraktni socket zmizi s procesem)
    if sys.unix_listen(SOCKET + String(sys.getuid()) + "-" + glib.getenv("DISPLAY")) < 0:
        return 0
    end
    call start_common()
    call rebuild()
    call place_all()
    call minute_tick()
    call glib.timeout_add_seconds(5, place_tick)
    call weather_refresh()
    call glib.timeout_add_seconds(1800, weather_refresh)
    call gtk.main()
    return 0
end

# ---- galerie widgetu (luxos-widgets settings) ------------------------------------------------

WIDGET_DESCRIPTIONS = {"today": "Large time and date with the weather of your place. Click the time for Clock.",
                       "system": "System health with CPU, memory and storage usage.",
                       "music": "What is playing, with Play/Pause and Next. Shown only while something plays.",
                       "calendar": "This month with today highlighted."}

GALLERY_CSS = (".lw-stage { background-image: linear-gradient(135deg, #23334f, #65798f); border-radius: 18px; padding: 18px 0 4px 0; }\n"
    + ".lw-gname { font-weight: 700; font-size: 14px; }\n"
    + ".lw-gdesc { font-size: 12px; opacity: 0.7; }\n"
    + "button.lw-add { border-radius: 999px; padding: 4px 16px; font-weight: 600; }\n"
    + "button.lw-add.on { background-image: none; background-color: #2f6fed; color: white; border-color: #2f6fed; }\n"
    + "button.lw-add.on label { color: white; }\n")

function gallery_refresh():
    g = ui["gallery"]
    call gtk.switch_set_active(g["switch"], conf["enabled"])
    for name in ALL_WIDGETS:
        b = g["buttons"][name]
        on = name in conf["widgets"]
        if on:
            call gtk.button_set_label(b, i18n.T("Remove"))
        else:
            call gtk.button_set_label(b, i18n.T("Add"))
        end
        call gtk.widget_set_class(b, "on", not on)
    end
    return 0
end

function on_gallery_toggle(button):
    name = ""
    for n in ALL_WIDGETS:
        if ui["gallery"]["buttons"][n] == button:
            name = n
        end
    end
    names = []
    for n in conf["widgets"]:
        if n != name:
            names.append(n)
        end
    end
    if name not in conf["widgets"]:
        names.append(name)
    end
    call set_widgets(names)
    # pridany widget zobrazit: zapnout widgety, kdyz byly vypnute
    if name not in conf["widgets"] and not conf["enabled"]:
        call write_conf_value("ENABLED", "1")
        call spawn(["luxos-widgets"])
    end
    return 0
end

function on_gallery_switch(state, switch):
    if state == conf["enabled"]:
        return False
    end
    if state:
        call write_conf_value("ENABLED", "1")
        call spawn(["luxos-widgets"])
    else:
        call write_conf_value("ENABLED", "0")
    end
    return False
end

function on_gallery_reset(button):
    call write_conf({}, "POS_")
    return 0
end

function on_gallery_close(event, window):
    call gtk.main_quit()
    return False
end

function settings():
    ui["settings"] = True
    call gtk.init()
    call read_conf()
    call start_common()
    call gtk.css_load(GALLERY_CSS)
    win = gtk.window_new(i18n.T("Widgets"))
    call gtk.window_set_default_size(win, 760, 640)
    call gtk.window_set_icon_name(win, "preferences-desktop")
    call gtk.window_set_wmclass(win, "luxos-widgets-settings", "Luxos-widgets-settings")
    call gtk.connect(win, "delete-event", on_gallery_close)
    scroll = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(scroll, gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
    call gtk.container_add(win, scroll)
    page = gtk.box_new(gtk.VERTICAL, 16)
    call gtk.widget_set_margins(page, 24, 24, 20, 24)
    call gtk.container_add(scroll, page)

    top = gtk.box_new(gtk.HORIZONTAL, 12)
    head = gtk.box_new(gtk.VERTICAL, 2)
    title = label(i18n.T("Widgets"), [])
    call gtk.label_set_markup(title, "<span size='x-large' weight='bold'>" + glib.markup_escape(i18n.T("Widgets")) + "</span>")
    call gtk.box_pack_start(head, title, False, False, 0)
    call gtk.box_pack_start(head, label(i18n.T("Drag a widget on the desktop to move it. Right-click it for more."), ["lw-gdesc"]), False, False, 0)
    call gtk.box_pack_start(top, head, True, True, 0)
    call gtk.box_pack_start(top, label(i18n.T("Show widgets"), []), False, False, 0)
    sw = gtk.switch_new()
    call gtk.widget_set_valign(sw, gtk.ALIGN_CENTER)
    call gtk.box_pack_start(top, sw, False, False, 0)
    call gtk.box_pack_start(page, top, False, False, 0)

    grid = gtk.grid_new()
    call gtk.grid_set_column_spacing(grid, 20)
    call gtk.grid_set_row_spacing(grid, 20)
    call gtk.grid_set_column_homogeneous(grid, True)
    buttons = {}
    index = 0
    for name in ALL_WIDGETS:
        cell = gtk.box_new(gtk.VERTICAL, 8)
        stage = gtk.box_new(gtk.VERTICAL, 0)
        call gtk.widget_add_class(stage, "lw-stage")
        c = build_card(name)
        ui["cards"][name] = c
        call gtk.widget_set_halign(c["ev"], gtk.ALIGN_CENTER)
        call gtk.widget_set_size_request(c["ev"], WIDTH - 2 * PAD, -1)
        call gtk.box_pack_start(stage, c["ev"], False, False, 0)
        call gtk.box_pack_start(cell, stage, False, False, 0)
        row = gtk.box_new(gtk.HORIZONTAL, 8)
        texts = gtk.box_new(gtk.VERTICAL, 2)
        call gtk.box_pack_start(texts, label(i18n.T(WIDGET_TITLES[name]), ["lw-gname"]), False, False, 0)
        d = label(i18n.T(WIDGET_DESCRIPTIONS[name]), ["lw-gdesc"])
        call gtk.label_set_line_wrap(d, True)
        call gtk.label_set_max_width_chars(d, 34)
        call gtk.box_pack_start(texts, d, False, False, 0)
        call gtk.box_pack_start(row, texts, True, True, 0)
        b = gtk.button_new(i18n.T("Add"))
        call gtk.widget_add_class(b, "lw-add")
        call gtk.widget_set_valign(b, gtk.ALIGN_START)
        call gtk.connect(b, "clicked", on_gallery_toggle)
        call gtk.box_pack_start(row, b, False, False, 0)
        buttons[name] = b
        call gtk.box_pack_start(cell, row, False, False, 0)
        call gtk.grid_attach(grid, cell, index % 2, index // 2, 1, 1)
        index = index + 1
    end
    call gtk.box_pack_start(page, grid, False, False, 0)

    bottom = gtk.box_new(gtk.HORIZONTAL, 8)
    reset = gtk.button_new(i18n.T("Default Layout"))
    call gtk.widget_set_tooltip(reset, i18n.T("Put all widgets back under each other in the corner"))
    call gtk.connect(reset, "clicked", on_gallery_reset)
    call gtk.box_pack_end(bottom, reset, False, False, 0)
    call gtk.box_pack_start(page, bottom, False, False, 0)

    ui["gallery"] = {"switch": sw, "buttons": buttons}
    call gallery_refresh()
    call gtk.connect(sw, "state-set", on_gallery_switch)
    call update_today()
    call update_music()
    call start_stats()
    call minute_tick()
    call gtk.widget_show_all(win)
    call gtk.main()
    return 0
end

command = arg(1)
if command == "on":
    call write_conf_value("ENABLED", "1")
    call glib.spawn_quiet(["luxos-widgets"])
elif command == "off":
    call write_conf_value("ENABLED", "0")
elif command == "settings":
    call settings()
elif command == None or command == "run":
    call start()
else:
    call sys.eprint("Usage: luxos-widgets [on|off|settings]")
    call exit(2)
end
