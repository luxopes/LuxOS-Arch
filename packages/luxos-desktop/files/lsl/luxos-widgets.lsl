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
# Vzhled: barevne sklo - kazda karta prebira barvu tapety pod sebou (prumer oblasti za kartou,
# tmavsi a sytejsi), bile pismo, svetly okraj a mekky stin. Pruhlednost karty se ridi jasem tapety,
# aby bile pismo bylo citelne i na svetle tapete. Tapeta z xfconf (xfce4-desktop, zmeny hned).
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

WIDTH = 340
PAD = 24
DEFAULT_WIDGETS = "today,system,music"
ALL_WIDGETS = ["today", "system", "music", "calendar"]
GRID = 8
WEATHER_MAX_AGE = 10800
SOCKET = "luxos-widgets-"
TINT_DEFAULT = [0.16, 0.17, 0.24]

CSS = ("window.lw { background: transparent; }\n"
    + ".lw-col { padding: 0 24px 12px 24px; }\n"
    + ".lw-card { background-color: @lw_bg; background-image: linear-gradient(to bottom, rgba(255, 255, 255, 0.10), rgba(255, 255, 255, 0.0));"
    + " border: 1px solid rgba(255, 255, 255, 0.30); border-radius: 20px; padding: 14px 18px; margin-bottom: 14px; color: white;"
    + " box-shadow: 0 6px 18px rgba(0, 0, 0, 0.16), inset 0 1px rgba(255, 255, 255, 0.28); }\n"
    + ".lw-card label { color: white; text-shadow: 0 1px 3px rgba(0, 0, 0, 0.45); }\n"
    + ".lw-card label.dim { color: rgba(255, 255, 255, 0.88); }\n"
    + ".lw-date { font-size: 13px; font-weight: 600; }\n"
    + ".lw-time { font-size: 40px; font-weight: 500; }\n"
    + ".lw-temp { font-size: 25px; font-weight: 500; }\n"
    + ".lw-cond { font-size: 12px; font-weight: 600; }\n"
    + ".lw-small { font-size: 11px; }\n"
    + ".lw-vsep { background-color: rgba(255, 255, 255, 0.28); min-width: 1px; margin: 4px 16px; }\n"
    + ".lw-hsep { background-color: rgba(255, 255, 255, 0.24); min-height: 1px; margin: 9px 0 4px 0; }\n"
    + ".lw-title { font-size: 14px; font-weight: 600; }\n"
    + ".lw-health { font-size: 12px; font-weight: 600; }\n"
    + ".lw-card image { color: white; -gtk-icon-shadow: 0 1px 3px rgba(0, 0, 0, 0.45); }\n"
    + "button.lw-btn { border-radius: 999px; min-width: 32px; min-height: 32px; padding: 0; background-color: rgba(255, 255, 255, 0.16); background-image: none; border: none; box-shadow: none; color: white; outline: none; }\n"
    + "button.lw-btn:hover { background-color: rgba(255, 255, 255, 0.28); }\n"
    + "button.lw-more { border-radius: 999px; min-width: 24px; min-height: 22px; padding: 0 2px; background: none; border: none; box-shadow: none; color: white; outline: none; }\n"
    + "button.lw-more:hover { background-color: rgba(255, 255, 255, 0.18); }\n"
    + "button.lw-more label { font-size: 15px; font-weight: 700; }\n"
    + ".lw-art { background-color: rgba(255, 255, 255, 0.16); border-radius: 12px; min-width: 44px; min-height: 44px; }\n")

# oblouky: [zacatek, konec] barevneho prechodu - procesor, pamet, disk
RING_COLORS = [[[1.0, 0.62, 0.26], [0.36, 0.89, 0.46]], [[0.53, 0.93, 0.35], [0.12, 0.84, 0.55]], [[0.25, 0.86, 0.85], [0.33, 0.62, 1.0]]]

conf = {"enabled": True, "widgets": [], "side": "right", "pos": {}}
# wins: nazev -> okno karty; placed: nazev -> [x, y] na obrazovce; settings = galerie (nahledy)
ui = {"wins": {}, "cards": {}, "placed": {}, "settings": False, "gallery": {}}
theme = {"provider": 0, "wallpaper": "", "surface": 0, "map": []}
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

# ---- barevne sklo podle tapety --------------------------------------------------------------

function clamp(x, lo, hi):
    return max(lo, min(hi, x))
end

# [r, g, b] 0-1 -> [h 0-1, s, l]
function rgb_to_hsl(c):
    mx = max(c[0], c[1], c[2])
    mn = min(c[0], c[1], c[2])
    l = (mx + mn) / 2.0
    if mx - mn < 0.0001:
        return [0.0, 0.0, l]
    end
    d = mx - mn
    s = d / (mx + mn)
    if l > 0.5:
        s = d / (2.0 - mx - mn)
    end
    h = 0.0
    if mx == c[0]:
        h = (c[1] - c[2]) / d
        if c[1] < c[2]:
            h = h + 6.0
        end
    elif mx == c[1]:
        h = (c[2] - c[0]) / d + 2.0
    else:
        h = (c[0] - c[1]) / d + 4.0
    end
    return [h / 6.0, s, l]
end

function hue_part(p, q, t):
    if t < 0.0:
        t = t + 1.0
    end
    if t > 1.0:
        t = t - 1.0
    end
    if t < 1.0 / 6.0:
        return p + (q - p) * 6.0 * t
    end
    if t < 0.5:
        return q
    end
    if t < 2.0 / 3.0:
        return p + (q - p) * (2.0 / 3.0 - t) * 6.0
    end
    return p
end

function hsl_to_rgb(h, s, l):
    if s < 0.0001:
        return [l, l, l]
    end
    q = l + s - l * s
    if l < 0.5:
        q = l * (1.0 + s)
    end
    p = 2.0 * l - q
    return [hue_part(p, q, h + 1.0 / 3.0), hue_part(p, q, h), hue_part(p, q, h - 1.0 / 3.0)]
end

# Tapeta plochy z xfconf (LuxOS ma na vsech monitorech a plochach stejnou)
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
    best = ""
    for key in sorted(props[0].keys()):
        if key.endswith("/workspace0/last-image"):
            value = String(props[0][key])
            if best == "" or key.find("monitorHDMI") < 0:
                best = value
            end
        end
    end
    return best
end

# Tapeta zmensena do obrazku cairo (vzorkovani barvy pod kartami); map = [sirka, vyska, meritko, posun x, y]
function load_wallpaper(path):
    if theme["surface"] != 0:
        call cairo.surface_destroy(theme["surface"])
        theme["surface"] = 0
    end
    if path == "" or not exists(path):
        return 0
    end
    pb = gtk.pixbuf_new_from_file_at_scale(path, 320, 320, True)
    if pb == 0:
        return 0
    end
    pw = gtk.pixbuf_get_width(pb)
    ph = gtk.pixbuf_get_height(pb)
    surface = cairo.image_surface_create(cairo.FORMAT_ARGB32, pw, ph)
    cr = cairo.create(surface)
    call gtk.cairo_set_source_pixbuf(cr, pb, 0, 0)
    call cairo.paint(cr)
    call cairo.destroy(cr)
    call glib.object_unref(pb)
    # tapeta "priblizit" (vyplni obrazovku, prebytek oriznuty)
    geo = gtk.monitor_geometry(0)
    mw = Float(max(1, geo[2]))
    mh = Float(max(1, geo[3]))
    sc = max(Float(pw) / mw, Float(ph) / mh)
    theme["surface"] = surface
    theme["map"] = [pw, ph, sc, (Float(pw) - mw * sc) / 2.0 - Float(geo[0]) * sc, (Float(ph) - mh * sc) / 2.0 - Float(geo[1]) * sc]
    return 0
end

# Prumerna barva tapety v obdelniku obrazovky ([r, g, b] 0-1) nebo None
function sample_rect(x, y, w, h):
    if theme["surface"] == 0:
        return None
    end
    m = theme["map"]
    rx0 = Int(clamp(m[3] + Float(x) * m[2], 0.0, Float(m[0] - 1)))
    rx1 = Int(clamp(m[3] + Float(x + w) * m[2], 0.0, Float(m[0] - 1)))
    ry0 = Int(clamp(m[4] + Float(y) * m[2], 0.0, Float(m[1] - 1)))
    ry1 = Int(clamp(m[4] + Float(y + h) * m[2], 0.0, Float(m[1] - 1)))
    r = 0.0
    g = 0.0
    b = 0.0
    n = 0
    yy = ry0
    while yy <= ry1:
        xx = rx0
        while xx <= rx1:
            px = cairo.image_surface_pixel(theme["surface"], xx, yy)
            r = r + Float((px >> 16) & 255)
            g = g + Float((px >> 8) & 255)
            b = b + Float(px & 255)
            n = n + 1
            xx = xx + 2
        end
        yy = yy + 2
    end
    if n == 0:
        return None
    end
    return [r / Float(n) / 255.0, g / Float(n) / 255.0, b / Float(n) / 255.0]
end

# Barva skla: odstin tapety, tmavsi a sytejsi. Vetsinou pruhledne (tapeta prosvita); na svetle tapete
# o neco hustsi, citelnost bileho pisma drzi hlavne stin textu (CSS text-shadow, shadow_text).
function tint_rgba(avg):
    if avg == None:
        avg = TINT_DEFAULT
    end
    hsl = rgb_to_hsl(avg)
    sat = clamp(hsl[1] * 1.3 + 0.15, 0.0, 0.9)
    card = hsl_to_rgb(hsl[0], sat, 0.34)
    lum_wall = 0.2126 * avg[0] + 0.7152 * avg[1] + 0.0722 * avg[2]
    alpha = 0.18
    if lum_wall > 0.40:
        alpha = clamp(0.18 + (lum_wall - 0.40) * 0.45, 0.18, 0.34)
    end
    return ("rgba(" + String(Int(card[0] * 255.0)) + ", " + String(Int(card[1] * 255.0)) + ", "
            + String(Int(card[2] * 255.0)) + ", " + String(Float(Int(alpha * 100.0)) / 100.0) + ")")
end

# CSS: vychozi barva (stred tapety, nahledy v galerii) a barva kazde umistene karty podle tapety pod ni
function theme_css():
    geo = gtk.primary_monitor_workarea()
    bg = tint_rgba(sample_rect(geo[0] + geo[2] // 3, geo[1] + geo[3] // 3, geo[2] // 3, geo[3] // 3))
    if ui["settings"]:
        # nahledy v galerii: svetle sklo na barevnem podkladu
        bg = "rgba(255, 255, 255, 0.16)"
    end
    css = "@define-color lw_bg " + bg + ";\n" + CSS
    for name in ui["placed"].keys():
        xy = ui["placed"][name]
        win = ui["wins"].get(name, 0)
        h = 140
        if win != 0:
            h = max(60, gtk.window_get_size(win)[1])
        end
        css = css + ".lw-card.lw-" + name + " { background-color: " + tint_rgba(sample_rect(xy[0] + PAD, xy[1], WIDTH - 2 * PAD, h)) + "; }\n"
    end
    return css
end

function theme_refresh():
    css = theme_css()
    if theme["provider"] == 0:
        theme["provider"] = gtk.css_load(css)
    else:
        call gtk.css_set(theme["provider"], css)
    end
    return 0
end

function theme_apply():
    path = wallpaper_path()
    if path != theme["wallpaper"] or theme["surface"] == 0:
        theme["wallpaper"] = path
        call load_wallpaper(path)
    end
    call theme_refresh()
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
    call gtk.widget_add_events(ev, gtk.BUTTON_PRESS_MASK + gtk.BUTTON_RELEASE_MASK + gtk.POINTER_MOTION_MASK)
    box = gtk.box_new(orientation, 0)
    call gtk.widget_add_class(box, "lw-card")
    call gtk.widget_add_class(box, "lw-" + name)
    call gtk.container_add(ev, box)
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
    call cairo.pattern_add_color_stop_rgba(pat, 0.0, 1.0, 1.0, 1.0, 1.0)
    call cairo.pattern_add_color_stop_rgba(pat, 1.0, shade, shade, shade + 0.04, 1.0)
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

# Text kresleny cairem se stinem jako CSS text-shadow karet (citelnost na pruhlednem skle)
function shadow_text(cr, x, y, text, font, alpha):
    call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, 0.40 * alpha)
    call pango.draw_text(cr, Float(x), Float(y) + 1.0, text, font)
    call white(cr, alpha)
    call pango.draw_text(cr, Float(x), Float(y), text, font)
    return 0
end

function on_calendar_draw(cr, area):
    width = Float(gtk.widget_get_allocated_width(area))
    d = glib.local_date()
    year = d[0]
    month = d[1]
    today = d[2]
    call shadow_text(cr, 2, 0, glib.format_date(year, month, 1, "%OB %Y"), "Inter Bold 10", 1.0)
    first = glib.first_weekday()
    col_w = width / 7.0
    # zkratky dnu (2024-01-01 je pondeli)
    for i in range(7):
        wd = ((first - 1 + i) % 7) + 1
        name = glib.format_date(2024, 1, wd, "%a")
        size = pango.text_size(cr, name, "Inter 8")
        call shadow_text(cr, Float(i) * col_w + (col_w - Float(size[0])) / 2.0, 22, name, "Inter 8", 0.75)
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
            call white(cr, 1.0)
            call cairo.arc(cr, x + col_w / 2.0, y + 8.0, 9.5, 0.0, 2.0 * cairo.PI)
            call cairo.fill(cr)
        end
        size = pango.text_size(cr, num, font)
        tx = x + (col_w - Float(size[0])) / 2.0
        if day == today:
            call cairo.set_source_rgba(cr, 0.10, 0.10, 0.14, 1.0)
            call pango.draw_text(cr, tx, y, num, font)
        elif glib.weekday(year, month, day) >= 6:
            call shadow_text(cr, tx, y, num, font, 0.72)
        else:
            call shadow_text(cr, tx, y, num, font, 1.0)
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
    call white(cr, 0.95)
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
        call cairo.set_line_width(cr, 5.0)
        call cairo.set_line_cap(cr, 1)
        call white(cr, 0.22)
        call cairo.new_path(cr)
        call cairo.arc(cr, cx, cy, r, start, start + sweep)
        call cairo.stroke(cr)
        frac = Float(max(0, min(100, values[i]))) / 100.0
        if frac > 0.0:
            colors = RING_COLORS[i]
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
        num = String(values[i]) + " %"
        size = pango.text_size(cr, num, "Inter Bold 10")
        call shadow_text(cr, cx - Float(size[0]) / 2.0, cy + 3.0, num, "Inter Bold 10", 1.0)
        size = pango.text_size(cr, names[i], "Inter 9")
        call shadow_text(cr, cx - Float(size[0]) / 2.0, cy + r - 1.0, names[i], "Inter 9", 0.9)
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
    call gtk.widget_set_size_request(area, WIDTH - 2 * PAD - 38, 82)
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

GALLERY_CSS = (".lw-stage { background-image: linear-gradient(135deg, #3a1c71, #d76d77 55%, #ffaf7b); border-radius: 18px; padding: 18px 0 4px 0; }\n"
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
