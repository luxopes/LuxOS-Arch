# LuxOS - Launchpad a Hledani pro relaci na Waylandu (1.1.0) misto rofi: plocha layer-shell OVERLAY pres cely
# vystup s klavesnici jen pro sebe, uprostred panel z matneho skla (luxos_material, dobre citelny i na pestre
# tapete) s polem hledani, mrizkou aplikaci 7 x 4 po radcich a razenim dole (Abecedne, Naposledy pouzite,
# Nejpouzivanejsi, Podle kategorie; Alt+1..4). Hledani (Super+Space) je uzsi panel se seznamem vysledku.
#
# Psani hleda v nazvu, popisu, klicovych slovech, programu i nelokalizovanych nazvech, bez diakritiky a fuzzy;
# casto spoustene aplikace mezi stejne dobrymi shodami vyhravaji (luxos_launchpad_model). Vypocet ("2+2*3") je prvni
# radek a Enter ho zkopiruje (luxos_calc). Text bez shody jde dotazem do LuxAI (jako luxos-luxai-rofi).
# Enter spusti vybranou (po psani nejlepsi) polozku, Ctrl+Enter posle text LuxAI; nahoru/dolu, Tab, PageUp/PageDown
# vzdy, vlevo/vpravo a Home/End jen s prazdnym polem (jinak patri textu); Escape nebo klik mimo panel zavre.
#
# Program bezi stale (skryte okno nema plochu u kompozitoru a nebezi v nem zadny casovac): otevreni je jen
# zobrazeni hotoveho okna. Ovladani pres D-Bus cz.luxos.Launchpad (Toggle/Show "launchpad" nebo "search",
# Hide); luxos-launchpad a luxos-search ho volaji pres gdbus, D-Bus ho pri prvnim pouziti spusti sam.
#
#   luxos-launchpad [--show launchpad|search]   bez argumentu skryty; bezi-li uz, preda pozadavek jemu
#
# LUXOS_LAUNCHPAD_TRACE=1 vypisuje udalosti s casem (testy): shown ... mono_us = prvni snimek po otevreni.
load env
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load gio, cairo, pango
load luxos_layer as layer
load luxos_material as material
load luxos_tokens as tokens
load luxos_apps as apps
load luxos_launchpad_model as model
load luxos_calc as calc
load luxos_i18n as i18n

BUS_NAME = "cz.luxos.Launchpad"
BUS_PATH = "/cz/luxos/Launchpad"
BUS_XML = "<node><interface name='cz.luxos.Launchpad'><method name='Toggle'><arg type='s' direction='in'/></method><method name='Show'><arg type='s' direction='in'/></method><method name='Hide'/></interface></node>"

# Samostatne aplikace s kategorii Nastaveni, ktere Launchpad ukazuje, prestoze panely Nastaveni skryva
# (bin/luxos-launchpad LAUNCHPAD_APPS); OnlyShowIn=X-LuxOS-Launchpad = kopie panelu jen pro Launchpad
LAUNCHPAD_APPS = ["luxos-companion.desktop", "luxos-bluetooth.desktop", "luxos-update.desktop",
    "luxos-firewall-settings.desktop", "luxos-account.desktop", "org.pulseaudio.pavucontrol.desktop"]
HIDDEN_CATEGORIES = ["X-XFCE-SettingsDialog", "X-Xfce-Toplevel"]
SELF_IDS = ["luxos-launchpad.desktop", "luxos-search.desktop"]
SORT_LABELS = ["Alphabetical", "Recently used", "Most used", "Category"]

ICON = 60
LIST_ICON = 32
TILE_H = 112
GAP = 6
PAD = 24
FIELD_H = 44
SORT_H = 28
ROW_H = 48
LIST_ROWS = 8
FADE_MS = 120
SCRIM = [0.0, 0.0, 0.0, 0.25]
MOD_SHIFT = 1
MOD_CTRL = 4
MOD_ALT = 8

TRACE = env.get("LUXOS_LAUNCHPAD_TRACE", "") != ""
conf_dir = glib.user_config_dir() + "/luxos"
sort_path = conf_dir + "/launchpad-sort"
usage_path = glib.user_data_dir() + "/luxos/launchpad-usage.json"

entries = []
usage = {}
S = {"blur": material.compositor_blur(), "shadow": None, "open": False, "mode": "launchpad", "sort": model.DEFAULT_MODE, "items": [], "sel": 0, "top": 0, "calc": None,
    "query": "", "light": True, "strip": None, "geo": {}, "size": [0, 0], "pending": False, "drawn": False,
    "fade": 0, "tick": 0, "animate": True, "luxai": "", "labels": []}
window = 0
entry = 0
fixed = 0
css = 0
tick_record = 0

function trace(line):
    if TRACE:
        print String(glib.monotonic_time() // 1000) + " " + line
    end
    return 0
end

function wall_s():
    return Int(glib.now())
end

# ---- aplikace ----

function launchpad_visible(info):
    if apps.nodisplay(info):
        return False
    end
    desktop_id = apps.id(info)
    if desktop_id in SELF_IDS:
        return False
    end
    if not apps.shown_here(info) and not ("X-LuxOS-Launchpad" in apps.string(info, "OnlyShowIn").split(";")):
        return False
    end
    if desktop_id in LAUNCHPAD_APPS:
        return True
    end
    for cat in apps.categories(info).split(";"):
        if cat in HIDDEN_CATEGORIES:
            return False
        end
    end
    return True
end

function free_icons():
    for e in entries:
        if e["icon"] != 0:
            call cairo.surface_destroy(e["icon"])
            e["icon"] = 0
        end
    end
    return 0
end

function load_entries():
    global entries
    call free_icons()
    entries = []
    seen = {}
    for info in apps.all():
        desktop_id = apps.id(info)
        if desktop_id == "" or desktop_id in seen or not launchpad_visible(info):
            continue
        end
        seen[desktop_id] = True
        e = model.entry(desktop_id, {"name": apps.name(info), "c_name": apps.string(info, "Name"),
            "generic": apps.generic_name(info), "c_generic": apps.string(info, "GenericName"),
            "keywords": ";".join(apps.keywords(info)), "c_keywords": apps.string(info, "Keywords"),
            "exec": apps.base_name(apps.executable(info)), "categories": apps.categories(info)})
        e["info"] = info
        e["icon"] = 0
        entries.append(e)
    end
    return 0
end

function icon_of(e):
    if e["icon"] == 0 and window != 0:
        e["icon"] = apps.icon(e["info"], ICON, gtk.widget_scale_factor(window))
    end
    return e["icon"]
end

# Ikony predem v necinnosti po startu: prvni otevreni uz je nenacita
# Po startu v necinnosti jednou nakreslit panel mimo obrazovku pro prvni monitor: ikony, rozmazana tapeta pro sklo
# a pisma se nactou predem, prvni otevreni uz jen kresli
function warm_up(unused):
    screens = layer.monitors()
    if not S["open"] and len(screens) > 0:
        g = layer.monitor_geometry(screens[0])
        S["size"] = [g[2], g[3]]
        call refresh()
        call update_geometry()
        surface = cairo.image_surface_create(cairo.FORMAT_ARGB32, g[2], g[3])
        cr = cairo.create(surface)
        call paint(cr)
        call cairo.destroy(cr)
        call cairo.surface_destroy(surface)
    end
    for e in entries:
        call icon_of(e)
    end
    call trace("icons " + String(len(entries)))
    return False
end

function load_usage():
    global usage
    if exists(usage_path):
        usage = model.parse_usage(glib.read_text(usage_path))
    else:
        # prvni spusteni: pocty z historie rofi (Launchpad na X11 dosud radil podle ni)
        usage = model.parse_rofi_history(glib.read_text(glib.user_cache_dir() + "/rofi3.druncache"))
    end
    if usage == None:
        usage = {}
    end
    return 0
end

function save_usage():
    call glib.mkdir_p(glib.user_data_dir() + "/luxos")
    call glib.write_atomic(usage_path, model.usage_text(usage))
    return 0
end

function load_sort():
    value = glib.read_text(sort_path).strip()
    if value in model.MODES:
        S["sort"] = value
    else:
        S["sort"] = model.DEFAULT_MODE
    end
    return 0
end

# ---- vysledky ----

function app_item(e):
    return {"kind": "app", "entry": e}
end

function refresh():
    query = S["query"].strip()
    items = []
    S["calc"] = None
    if query == "":
        if S["mode"] == "search":
            found = model.order(entries, "recent", usage)
        else:
            found = model.order(entries, S["sort"], usage)
        end
    else:
        value = calc.evaluate(query)
        if value != None:
            S["calc"] = value
            items.append({"kind": "calc", "value": value})
        end
        found = model.search(entries, query, usage, wall_s())
    end
    for e in found:
        items.append(app_item(e))
    end
    if query != "" and S["luxai"] != "":
        items.append({"kind": "luxai"})
    end
    S["items"] = items
    S["sel"] = 0
    S["top"] = 0
    if TRACE and query != "":
        names = []
        for item in items[0:8]:
            if item["kind"] == "app":
                names.append(item["entry"]["id"])
            elif item["kind"] == "calc":
                names.append("=" + calc_text(item["value"], False))
            else:
                names.append("luxai")
            end
        end
        call trace("results " + query + " : " + " ".join(names))
    end
    return 0
end

function calc_text(value, grouped):
    group = ""
    if grouped:
        group = chr(8239)
        if i18n.decimal_separator() == ".":
            group = ","
        end
    end
    return calc.format(value, i18n.decimal_separator(), group)
end

# ---- rozmery ----

function has_calc_row():
    return len(S["items"]) > 0 and S["items"][0]["kind"] == "calc"
end

function update_geometry():
    w = S["size"][0]
    h = S["size"][1]
    if w <= 0 or h <= 0:
        return 0
    end
    g = {}
    if S["mode"] == "search":
        g["w"] = min(w - 32, 680)
        rows = min(LIST_ROWS, len(S["items"]))
        g["rows"] = rows
        g["cols"] = 1
        g["h"] = 12 + FIELD_H + 12
        if rows > 0:
            g["h"] += rows * ROW_H + 8
        end
        g["x"] = (w - g["w"]) // 2
        g["y"] = max(16, h // 5)
        g["field"] = [g["x"] + 12, g["y"] + 12, g["w"] - 24, FIELD_H]
        g["grid"] = [g["x"] + 8, g["y"] + 12 + FIELD_H + 10]
        g["tile_w"] = g["w"] - 16
    else:
        # 6 sloupcu po ~136 px (navrh 1.1.0): dvouradkove ceske nazvy se vejdou bez vypustky
        g["w"] = max(min(w - 32, 560), min(880, w * 7 // 10))
        g["cols"] = 6
        if g["w"] < 700:
            g["cols"] = 5
        end
        fixed_h = 2 * PAD + FIELD_H + 18 + 14 + SORT_H
        g["rows"] = max(2, min(4, (h - 48 - fixed_h + GAP) // (TILE_H + GAP)))
        g["h"] = fixed_h + g["rows"] * TILE_H + (g["rows"] - 1) * GAP
        g["x"] = (w - g["w"]) // 2
        g["y"] = max(0, (h - g["h"]) // 2)
        g["field"] = [g["x"] + PAD, g["y"] + PAD, g["w"] - 2 * PAD, FIELD_H]
        g["grid"] = [g["x"] + PAD, g["y"] + PAD + FIELD_H + 18]
        g["tile_w"] = (g["w"] - 2 * PAD) // g["cols"]
        g["sort_y"] = g["y"] + g["h"] - PAD - SORT_H
    end
    if S["geo"].get("w") != g["w"] or S["geo"].get("h") != g["h"] or S["geo"].get("x") != g["x"]:
        S["strip"] = None
    end
    S["geo"] = g
    # pole se posune jen pri zmene (fixed_move jinak znovu pocita rozlozeni okna)
    f = g["field"]
    place = [f[0] + 40, f[1] + (FIELD_H - 30) // 2, f[2] - 52]
    if entry != 0 and place != S.get("entry_at"):
        S["entry_at"] = place
        call gtk.fixed_move(fixed, entry, place[0], place[1])
        call gtk.widget_set_size_request(entry, place[2], 30)
    end
    return 0
end

# radek a sloupec polozky; vypocet zabira cely prvni radek mrizky
function slot(i):
    cols = S["geo"]["cols"]
    if has_calc_row():
        if i == 0:
            return [0, 0]
        end
        k = i - 1 + cols
        return [k // cols, k % cols]
    end
    return [i // cols, i % cols]
end

function index_at(row, col):
    cols = S["geo"]["cols"]
    if row < 0:
        return -1
    end
    if has_calc_row():
        if row == 0:
            return 0
        end
        i = (row - 1) * cols + col + 1
    else:
        i = row * cols + col
    end
    if i >= len(S["items"]):
        return -1
    end
    return i
end

function last_row():
    if len(S["items"]) == 0:
        return 0
    end
    return slot(len(S["items"]) - 1)[0]
end

function item_rect(i):
    g = S["geo"]
    pos = slot(i)
    row = pos[0] - S["top"]
    if row < 0 or row >= g["rows"]:
        return None
    end
    if S["mode"] == "search":
        return [g["grid"][0], g["grid"][1] + row * ROW_H, g["tile_w"], ROW_H]
    end
    y = g["grid"][1] + row * (TILE_H + GAP)
    if S["items"][i]["kind"] == "calc":
        return [g["grid"][0], y, g["tile_w"] * g["cols"], TILE_H]
    end
    return [g["grid"][0] + pos[1] * g["tile_w"], y, g["tile_w"], TILE_H]
end

function item_at(x, y):
    for i in range(len(S["items"])):
        r = item_rect(i)
        if r != None and x >= r[0] and x < r[0] + r[2] and y >= r[1] and y < r[1] + r[3]:
            return i
        end
    end
    return -1
end

function sort_rects(cr):
    g = S["geo"]
    font = tokens.FONT["family"] + " 9.5"
    widths = []
    total = 0
    for label in SORT_LABELS:
        size = pango.text_size(cr, i18n.T(label), font)
        widths.append(size[0] + 24)
        total += size[0] + 24
    end
    x = g["x"] + (g["w"] - total - 4 * 3) // 2
    out = []
    for wd in widths:
        out.append([x, g["sort_y"], wd, SORT_H])
        x += wd + 4
    end
    return out
end

function in_panel(x, y):
    g = S["geo"]
    return x >= g["x"] and x < g["x"] + g["w"] and y >= g["y"] and y < g["y"] + g["h"]
end

# ---- kresleni ----

function panel_redraw():
    if window == 0 or len(S["geo"]) == 0:
        return 0
    end
    g = S["geo"]
    call gtk.widget_queue_draw_area(window, g["x"] - 2, g["y"] - 2, g["w"] + 4, g["h"] + 4)
    return 0
end

function dark():
    return not S["light"]
end

function color(name):
    return tokens.rgb01(tokens.color(name, dark()))
end

function glass():
    if S["strip"] == None:
        g = S["geo"]
        S["strip"] = []
        hit = None
        if not S["blur"]:
            hit = material.strip("", S["size"][0], S["size"][1], g["x"], g["y"], g["w"], g["h"], 0, -1, gtk.widget_scale_factor(window))
        end
        if hit != None:
            S["strip"] = hit
            S["light"] = hit[1]
        else:
            S["light"] = glib.read_text(conf_dir + "/appearance").strip() != "dark"
        end
        if S.get("css_light") != S["light"]:
            S["css_light"] = S["light"]
            call apply_css()
        end
    end
    return S["strip"]
end

function apply_css():
    fg = tokens.css_color(tokens.color("fg", dark()))
    sel = tokens.css_color(tokens.COLORS["accent"])
    text = ("#luxos-launchpad-entry { background: transparent; border: none; box-shadow: none; outline: none; "
        + "padding: 0; min-height: 0; color: " + fg + "; caret-color: " + fg + "; font-family: " + tokens.FONT["fallback"]
        + "; font-size: 17px; } #luxos-launchpad-entry selection { background-color: " + sel + "; color: white; }")
    call gtk.css_set(css, text)
    return 0
end

# Pod luxwm: celou obrazovku rozmaze kompozitor (material dim), panel je material sheet se stinem urovne 4
# (stin uvnitr povrchu, kresli se jednou pro velikost panelu)
function draw_sheet(cr):
    g = S["geo"]
    call glass()
    radius = tokens.radius_of("sheet")
    key = [g["w"], g["h"], dark()]
    if S["shadow"] == None or S["shadow"][1] != key:
        if S["shadow"] != None:
            call cairo.surface_destroy(S["shadow"][0])
        end
        S["shadow"] = [material.shadow_surface(g["w"], g["h"], radius, "sheet", dark()), key]
    end
    reach = tokens.elevation("sheet", dark())[0]
    call cairo.set_source_surface(cr, S["shadow"][0], Float(g["x"] - reach), Float(g["y"] - reach))
    call cairo.paint(cr)
    call material.paint_tint(cr, "sheet", dark(), True, g["x"], g["y"], g["w"], g["h"], True)
    return 0
end

function draw_panel(cr):
    if S["blur"]:
        return draw_sheet(cr)
    end
    g = S["geo"]
    radius = Float(tokens.radius_of("sheet"))
    strip = glass()
    call cairo.save(cr)
    call cairo.rounded_rectangle(cr, g["x"], g["y"], g["w"], g["h"], radius)
    call cairo.clip(cr)
    if len(strip) > 0:
        call cairo.set_source_surface(cr, strip[0], g["x"], g["y"])
        call cairo.paint(cr)
    else:
        # bez tapety: neprusvitny podklad (U-15: pruhledny panel byl na pestrem pozadi necitelny)
        c = tokens.opaque(tokens.material("sheet", dark(), False))
        call cairo.set_source_color(cr, tokens.rgb01(c))
        call cairo.paint(cr)
    end
    call cairo.restore(cr)
    call cairo.set_source_color(cr, color("border"))
    call cairo.set_line_width(cr, 1.0)
    call cairo.rounded_rectangle(cr, g["x"] + 0.5, g["y"] + 0.5, g["w"] - 1.0, g["h"] - 1.0, radius - 0.5)
    call cairo.stroke(cr)
    return 0
end

function draw_field(cr):
    f = S["geo"]["field"]
    call cairo.set_source_color(cr, color("field"))
    call cairo.rounded_rectangle(cr, f[0], f[1], f[2], f[3], 12.0)
    call cairo.fill(cr)
    call cairo.set_source_color(cr, color("border"))
    call cairo.set_line_width(cr, 1.0)
    call cairo.rounded_rectangle(cr, f[0] + 0.5, f[1] + 0.5, f[2] - 1.0, f[3] - 1.0, 11.5)
    call cairo.stroke(cr)
    # lupa
    cx = Float(f[0] + 22)
    cy = Float(f[1] + FIELD_H // 2 - 1)
    call cairo.set_source_color(cr, color("dim"))
    call cairo.set_line_width(cr, 2.0)
    call cairo.arc(cr, cx - 1.5, cy - 1.5, 6.0, 0.0, 2.0 * cairo.PI)
    call cairo.stroke(cr)
    call cairo.move_to(cr, cx + 3.0, cy + 3.0)
    call cairo.line_to(cr, cx + 7.5, cy + 7.5)
    call cairo.stroke(cr)
    if S["query"] == "":
        hint = "Search apps or ask LuxAI"
        if S["mode"] == "search":
            hint = "Search or ask LuxAI"
        end
        if S["luxai"] == "":
            hint = "Search apps"
        end
        layout = pango.cairo_create_layout(cr)
        call pango.layout_set_font(layout, tokens.FONT["family"] + " 13")
        call pango.layout_set_text(layout, i18n.T(hint))
        size = pango.layout_get_pixel_size(layout)
        call cairo.move_to(cr, f[0] + 43, f[1] + (FIELD_H - size[1]) // 2)
        call pango.cairo_show_layout(cr, layout)
        call pango.layout_unref(layout)
    end
    return 0
end

function draw_icon(cr, surface, x, y, size):
    if surface == 0:
        return 0
    end
    call cairo.save(cr)
    call cairo.translate(cr, x, y)
    if size != ICON:
        k = Float(size) / Float(ICON)
        call cairo.scale(cr, k, k)
    end
    call cairo.set_source_surface(cr, surface, 0.0, 0.0)
    if size != ICON:
        call gtk.cairo_source_filter(cr, gtk.CAIRO_FILTER_GOOD)
    end
    call cairo.paint(cr)
    call cairo.restore(cr)
    return 0
end

function draw_text(cr, value, font, x, y, width, align):
    layout = pango.cairo_create_layout(cr)
    call pango.layout_set_font(layout, font)
    call pango.layout_set_text(layout, value)
    call pango.layout_set_width(layout, width)
    call pango.layout_set_ellipsize(layout, pango.ELLIPSIZE_END)
    call pango.layout_set_alignment(layout, align)
    call pango.layout_set_single_paragraph_mode(layout, True)
    size = pango.layout_get_pixel_size(layout)
    call cairo.move_to(cr, x, y)
    call pango.cairo_show_layout(cr, layout)
    call pango.layout_unref(layout)
    return size
end

# Popisek dlazdice: nejvys dva radky zalomene mezi slovy, vypustka jen na konci druheho radku
# ("Aktualizace softwaru" misto "Aktualizace s...")
function draw_label(cr, value, font, x, y, width):
    layout = pango.cairo_create_layout(cr)
    call pango.layout_set_font(layout, font)
    call pango.layout_set_text(layout, value)
    call pango.layout_set_width(layout, width)
    call pango.layout_set_wrap(layout, pango.WRAP_WORD_CHAR)
    call pango.layout_set_height(layout, -2)
    call pango.layout_set_ellipsize(layout, pango.ELLIPSIZE_END)
    call pango.layout_set_alignment(layout, pango.ALIGN_CENTER)
    call cairo.move_to(cr, x, y)
    call pango.cairo_show_layout(cr, layout)
    if TRACE and not (value in S["labels"]):
        S["labels"].append(value)
        widest = 0
        for word in value.split(" "):
            widest = max(widest, pango.text_size(cr, word, font)[0])
        end
        call trace("label lines=" + String(pango.layout_get_line_count(layout)) + " ellipsized="
            + String(1 if pango.layout_is_ellipsized(layout) else 0) + " word=" + String(widest) + " width=" + String(width)
            + " " + value)
    end
    call pango.layout_unref(layout)
    return 0
end

function item_label(item):
    if item["kind"] == "app":
        return item["entry"]["name"]
    end
    return i18n.T("Ask LuxAI")
end

function item_icon(item):
    if item["kind"] == "app":
        return icon_of(item["entry"])
    end
    if S.get("luxai_icon", 0) == 0:
        S["luxai_icon"] = apps.icon_named("luxai", ICON, gtk.widget_scale_factor(window))
    end
    return S["luxai_icon"]
end

function draw_calc(cr, r, item, selected):
    if selected:
        call cairo.set_source_color(cr, color("tile_hover"))
    else:
        call cairo.set_source_color(cr, color("tile"))
    end
    call cairo.rounded_rectangle(cr, r[0] + 3, r[1] + 3, r[2] - 6, r[3] - 6, Float(tokens.RADIUS["l"]))
    call cairo.fill(cr)
    big = 30
    if S["mode"] == "search":
        big = 20
    end
    call cairo.set_source_color(cr, color("fg"))
    value = "= " + calc_text(item["value"], True)
    font = tokens.FONT["family"] + " Light " + String(big)
    height = pango.text_size(cr, value, font)[1]
    size = draw_text(cr, value, font, r[0] + 20, r[1] + (r[3] - height) // 2, r[2] - 220, pango.ALIGN_LEFT)
    call cairo.set_source_color(cr, color("dim"))
    hint = i18n.T("Copy") + "  ↵"
    call draw_text(cr, hint, tokens.FONT["family"] + " 10", r[0] + r[2] - 200, r[1] + (r[3] - 16) // 2, 180, pango.ALIGN_RIGHT)
    return size
end

function draw_tile(cr, r, item, selected):
    if selected:
        call cairo.set_source_color(cr, color("tile_hover"))
        call cairo.rounded_rectangle(cr, r[0] + 3, r[1] + 2, r[2] - 6, r[3] - 4, Float(tokens.RADIUS["l"]))
        call cairo.fill(cr)
    end
    if S["mode"] == "search":
        call draw_icon(cr, item_icon(item), r[0] + 10, r[1] + (ROW_H - LIST_ICON) // 2, LIST_ICON)
        call cairo.set_source_color(cr, color("fg"))
        x = r[0] + 22 + LIST_ICON
        size = draw_text(cr, item_label(item), tokens.FONT["family"] + " 11.5", x, r[1] + (ROW_H - 18) // 2, (r[2] - (x - r[0]) - 12) // 2, pango.ALIGN_LEFT)
        if item["kind"] == "app":
            generic = item["entry"]["fields"].get("generic", "")
            if generic != "":
                call cairo.set_source_color(cr, color("dim"))
                call draw_text(cr, apps.generic_name(item["entry"]["info"]), tokens.FONT["family"] + " 10", x + size[0] + 12, r[1] + (ROW_H - 15) // 2, r[2] - (x - r[0]) - size[0] - 24, pango.ALIGN_LEFT)
            end
        end
        return 0
    end
    call draw_icon(cr, item_icon(item), r[0] + (r[2] - ICON) // 2, r[1] + 10, ICON)
    call cairo.set_source_color(cr, color("fg"))
    call draw_label(cr, item_label(item), tokens.FONT["family"] + " 10", r[0] + 4, r[1] + 10 + ICON + 5, r[2] - 8)
    return 0
end

function draw_sort(cr):
    rects = sort_rects(cr)
    for i in range(len(SORT_LABELS)):
        r = rects[i]
        active = model.MODES[i] == S["sort"]
        if active:
            call cairo.set_source_color(cr, color("tile_hover"))
            call cairo.rounded_rectangle(cr, r[0], r[1], r[2], r[3], 10.0)
            call cairo.fill(cr)
            call cairo.set_source_color(cr, color("fg"))
        else:
            call cairo.set_source_color(cr, color("dim"))
        end
        call draw_text(cr, i18n.T(SORT_LABELS[i]), tokens.FONT["family"] + " 9.5", r[0], r[1] + (SORT_H - 15) // 2, r[2], pango.ALIGN_CENTER)
    end
    return 0
end

# posuvnik vpravo, kdyz se radky nevejdou
function draw_scroll(cr):
    g = S["geo"]
    total = last_row() + 1
    if total <= g["rows"]:
        return 0
    end
    if S["mode"] == "search":
        top = g["grid"][1]
        height = g["rows"] * ROW_H
    else:
        top = g["grid"][1]
        height = g["rows"] * (TILE_H + GAP) - GAP
    end
    x = Float(g["x"] + g["w"] - 9)
    bar = max(24.0, Float(height) * Float(g["rows"]) / Float(total))
    y = Float(top) + (Float(height) - bar) * Float(S["top"]) / Float(total - g["rows"])
    call cairo.set_source_color(cr, color("trough"))
    call cairo.rounded_rectangle(cr, x, y, 4.0, bar, 2.0)
    call cairo.fill(cr)
    return 0
end

function update_size():
    w = gtk.widget_get_allocated_width(window)
    h = gtk.widget_get_allocated_height(window)
    if w != S["size"][0] or h != S["size"][1]:
        S["size"] = [w, h]
        call update_geometry()
    end
    return 0
end

function on_size(allocation, widget):
    call update_size()
    return 0
end

function paint(cr):
    call cairo.save(cr)
    call cairo.set_operator(cr, cairo.OPERATOR_SOURCE)
    if S["blur"]:
        # zatemneni nad rozmazanou obrazovkou (material dim od kompozitoru)
        d = tokens.DIM["dark" if dark() else "light"]
        call cairo.set_source_rgba(cr, 0.0, 0.0, 0.0, d[3])
    else:
        call cairo.set_source_rgba(cr, SCRIM[0], SCRIM[1], SCRIM[2], SCRIM[3])
    end
    call cairo.paint(cr)
    call cairo.restore(cr)
    alpha = fade_alpha()
    if alpha < 1.0:
        call gtk.cairo_push_group(cr)
    end
    call draw_panel(cr)
    call draw_field(cr)
    for i in range(len(S["items"])):
        r = item_rect(i)
        if r != None:
            item = S["items"][i]
            if item["kind"] == "calc":
                call draw_calc(cr, r, item, i == S["sel"])
            else:
                call draw_tile(cr, r, item, i == S["sel"])
            end
        end
    end
    if S["query"].strip() != "" and len(S["items"]) == 0 and S["mode"] == "launchpad":
        g = S["geo"]
        call cairo.set_source_color(cr, color("dim"))
        call draw_text(cr, i18n.T("No results"), tokens.FONT["family"] + " 12", g["x"], g["grid"][1] + TILE_H, g["w"], pango.ALIGN_CENTER)
    end
    call draw_scroll(cr)
    if S["mode"] == "launchpad":
        call draw_sort(cr)
    end
    if alpha < 1.0:
        call gtk.cairo_pop_group_to_source(cr)
        call cairo.paint_with_alpha(cr, alpha)
    end
    return 0
end

function on_draw(cr, widget):
    started = glib.monotonic_time()
    call update_size()
    call paint(cr)
    cost = glib.monotonic_time() - started
    if S["pending"] and not S["drawn"]:
        call trace("first-draw us=" + String(cost))
    end
    if S["fade"] != 0:
        call trace("fade-frame us=" + String(cost))
        S["fade_frames"] = S.get("fade_frames", 0) + 1
    end
    S["drawn"] = True
    return False
end

# ---- otevreni a zavreni ----

function fade_alpha():
    if S["fade"] == 0:
        return 1.0
    end
    t = Float(glib.monotonic_time() - S["fade"]) / Float(FADE_MS * 1000)
    if t >= 1.0:
        return 1.0
    end
    u = 1.0 - max(0.0, t)
    return 1.0 - 0.5 * u * u * u
end

function on_tick(widget, clock):
    call panel_redraw()
    if fade_alpha() >= 1.0:
        call trace("fade frames=" + String(S.get("fade_frames", 0)))
        S["fade"] = 0
        S["tick"] = 0
        S["fade_frames"] = 0
        return False
    end
    return True
end

function start_fade():
    global tick_record
    if not S["animate"]:
        return 0
    end
    S["fade"] = glib.monotonic_time()
    if S["tick"] == 0:
        if tick_record == 0:
            tick_record = glib.record_new(on_tick, 2)
        end
        S["tick"] = gtk.widget_add_tick_callback(window, tick_record)
    end
    return 0
end

# GDK commituje plochu v after-paint pred touto obsluhou: prvni snimek po otevreni je na obrazovce
function on_after_paint(data, clock):
    if S["pending"] and S["drawn"]:
        S["pending"] = False
        call trace("shown mode=" + S["mode"] + " mono_us=" + String(glib.monotonic_time()) + " items=" + String(len(S["items"])))
    end
    return 0
end

function on_realize(widget):
    unsafe:
        clock = __lsl_qbe_call1(__lsl_symbol("gdk_window_get_frame_clock"), __lsl_unbox_int(gtk.widget_get_window(widget)))
    end
    call glib.connect_data(clock, "after-paint", 0, on_after_paint, 0)
    return 0
end

function show(mode):
    if not (mode in ["launchpad", "search"]):
        mode = "launchpad"
    end
    S["mode"] = mode
    S["query"] = ""
    call gtk.entry_set_text(entry, "")
    call load_sort()
    call refresh()
    call update_geometry()
    if not S["open"]:
        S["open"] = True
        S["pending"] = True
        S["drawn"] = False
        call layer.set_keyboard_mode(window, layer.KEYBOARD_EXCLUSIVE)
        call gtk.widget_show_all(window)
        call start_fade()
    else:
        call gtk.widget_queue_draw(window)
    end
    call gtk.widget_grab_focus(entry)
    call trace("show " + mode)
    return 0
end

function hide():
    if not S["open"]:
        return 0
    end
    S["open"] = False
    S["pending"] = False
    call gtk.widget_hide(window)
    # sklo panelu je az 4 MB; zmenseniny tapety zustanou, dalsi otevreni ho rychle slozi znovu
    S["strip"] = None
    call material.forget_output("")
    call trace("hidden")
    return 0
end

function toggle(mode):
    if S["open"] and S["mode"] == mode:
        call hide()
    else:
        call show(mode)
    end
    return 0
end

function activate(i):
    if i < 0 or i >= len(S["items"]):
        return 0
    end
    item = S["items"][i]
    query = S["query"].strip()
    if item["kind"] == "calc":
        value = calc_text(item["value"], False)
        call gtk.selection_set_text(gtk.clipboard_object(), value)
        call trace("copy " + value)
    elif item["kind"] == "luxai":
        call trace("luxai " + query)
        call glib.spawn_quiet([S["luxai"], "--agent", query])
    else:
        e = item["entry"]
        call trace("launch " + e["id"])
        if apps.launch(e["info"]):
            call model.record(usage, e["id"], wall_s())
            safe:
                call save_usage()
            end
        end
    end
    call hide()
    return 0
end

# ---- vyber ----

function ensure_visible():
    rows = S["geo"]["rows"]
    row = slot(S["sel"])[0]
    if row < S["top"]:
        S["top"] = row
    elif row >= S["top"] + rows:
        S["top"] = row - rows + 1
    end
    return 0
end

function select(i):
    n = len(S["items"])
    if n == 0:
        return 0
    end
    S["sel"] = max(0, min(n - 1, i))
    call ensure_visible()
    call panel_redraw()
    if TRACE:
        item = S["items"][S["sel"]]
        name = item["kind"]
        if name == "app":
            name = item["entry"]["id"]
        end
        call trace("sel " + String(S["sel"]) + " " + name + " top=" + String(S["top"]))
    end
    return 0
end

function move_rows(delta):
    if len(S["items"]) == 0:
        return 0
    end
    pos = slot(S["sel"])
    row = max(0, min(last_row(), pos[0] + delta))
    target = index_at(row, pos[1])
    while target < 0 and row > 0:
        # kratsi posledni radek nebo radek vypoctu
        target = index_at(row, 0)
        col = pos[1]
        while target >= 0 and index_at(row, col) < 0 and col > 0:
            col -= 1
        end
        target = index_at(row, col)
        if target < 0:
            row -= 1
        end
    end
    call select(target)
    return 0
end

function scroll(delta):
    S["top"] = max(0, min(max(0, last_row() - S["geo"]["rows"] + 1), S["top"] + delta))
    call panel_redraw()
    return 0
end

function set_sort(index):
    S["sort"] = model.MODES[index]
    call glib.mkdir_p(conf_dir)
    call glib.write_atomic(sort_path, S["sort"] + "\n")
    call trace("sort " + S["sort"])
    if S["query"].strip() == "":
        call refresh()
    end
    call panel_redraw()
    return 0
end

# ---- vstup ----

function on_key(event, widget):
    name = gtk.event_key_name(event)
    state = gtk.event_key_state(event)
    typing = S["query"] != ""
    if name == "Escape":
        call hide()
    elif name == "Return" or name == "KP_Enter":
        if (state & MOD_CTRL) != 0 and S["luxai"] != "" and S["query"].strip() != "":
            call activate(len(S["items"]) - 1)
        else:
            call activate(S["sel"])
        end
    elif name == "Down":
        call move_rows(1)
    elif name == "Up":
        call move_rows(-1)
    elif (name == "Left" or name == "Right") and not typing:
        if name == "Left":
            call select(S["sel"] - 1)
        else:
            call select(S["sel"] + 1)
        end
    elif name == "Tab":
        call select((S["sel"] + 1) % max(1, len(S["items"])))
    elif name == "ISO_Left_Tab":
        call select((S["sel"] - 1 + len(S["items"])) % max(1, len(S["items"])))
    elif name == "Page_Down":
        call move_rows(S["geo"]["rows"])
    elif name == "Page_Up":
        call move_rows(-S["geo"]["rows"])
    elif (name == "Home" or name == "End") and not typing:
        if name == "Home":
            call select(0)
        else:
            call select(len(S["items"]) - 1)
        end
    elif (state & MOD_ALT) != 0 and name in ["1", "2", "3", "4"] and S["mode"] == "launchpad":
        call set_sort(Int(name) - 1)
    else:
        return False
    end
    return True
end

function on_changed(widget):
    S["query"] = gtk.entry_get_text(entry)
    call refresh()
    if S["mode"] == "search":
        call update_geometry()
        call gtk.widget_queue_draw(window)
    else:
        call panel_redraw()
    end
    return 0
end

function on_motion(event, widget):
    xy = gtk.event_coords(event)
    i = item_at(xy[0], xy[1])
    if i >= 0 and i != S["sel"]:
        S["sel"] = i
        call panel_redraw()
    end
    return False
end

function on_press(event, widget):
    if gtk.event_button(event) != 1:
        return True
    end
    xy = gtk.event_coords(event)
    x = xy[0]
    y = xy[1]
    if not in_panel(x, y):
        call hide()
        return True
    end
    i = item_at(x, y)
    if i >= 0:
        call activate(i)
        return True
    end
    if S["mode"] == "launchpad":
        cr = gdk_cairo()
        rects = sort_rects(cr)
        call cairo.destroy(cr)
        for k in range(len(rects)):
            r = rects[k]
            if x >= r[0] and x < r[0] + r[2] and y >= r[1] and y < r[1] + r[3]:
                call set_sort(k)
            end
        end
    end
    return False
end

# cairo jen na mereni textu tlacitek razeni
function gdk_cairo():
    surface = cairo.image_surface_create(cairo.FORMAT_ARGB32, 1, 1)
    cr = cairo.create(surface)
    call cairo.surface_destroy(surface)
    return cr
end

function on_scroll(event, widget):
    deltas = gtk.event_scroll_deltas(event)
    direction = gtk.event_scroll_direction(event)
    if direction == 0 or (direction == 4 and deltas[1] < 0.0):
        call scroll(-1)
    elif direction == 1 or (direction == 4 and deltas[1] > 0.0):
        call scroll(1)
    end
    return True
end

# ---- D-Bus a soubory ----

function on_method(sender, path, interface, method, values, invocation):
    mode = "launchpad"
    if len(values) > 0:
        mode = values[0]
    end
    if method == "Toggle":
        call toggle(mode)
    elif method == "Show":
        call show(mode)
    else:
        call hide()
    end
    call gio.return_value(invocation, [], "")
    return 0
end

function on_apps_changed(monitor):
    call apps.reload()
    call load_entries()
    call trace("apps " + String(len(entries)))
    if S["open"]:
        call refresh()
        call gtk.widget_queue_draw(window)
    end
    return 0
end

function on_config(file, event, other):
    if file.endswith("/appearance.conf") or file.endswith("/appearance"):
        call material.reload()
        S["strip"] = None
        # tmavy rezim muze mit jine tema ikon
        call free_icons()
        S["luxai_icon"] = 0
        if S["open"]:
            call gtk.widget_queue_draw(window)
        else:
            call glib.idle_add_data(warm_up, 0)
        end
    end
    return 0
end

# ---- start ----

mode_arg = ""
index = 1
while index < arg_count():
    if arg(index) == "--show" and index + 1 < arg_count():
        mode_arg = arg(index + 1)
        index += 1
    elif arg(index) == "--show":
        mode_arg = "launchpad"
    end
    index += 1
end

call glib.set_prgname("luxos-launchpad")
call gtk.init()
if not layer.is_wayland() or not layer.is_supported():
    print "luxos-launchpad: needs a Wayland compositor with layer-shell (the X11 session uses rofi)"
    exit(2)
end

bus = 0
safe:
    bus = gio.session_bus()
end
if bus != 0:
    owner = 0
    safe:
        call gio.register_object(bus, BUS_PATH, BUS_XML, on_method)
        owner = gio.call_values(bus, "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName", [BUS_NAME, 4], "(su)", -1)[0]
    end
    if owner == 3:
        # uz bezi: predat pozadavek jemu
        if mode_arg != "":
            call gio.call_values(bus, BUS_NAME, BUS_PATH, BUS_NAME, "Show", [mode_arg], "(s)", 2000)
        end
        exit(0)
    end
end

S["luxai"] = glib.find_program_in_path("luxai")
call load_usage()
call load_sort()
call load_entries()

window = gtk.window_new("luxos-launchpad")
call gtk.window_set_rgba(window)
call layer.init_for_window(window)
call layer.set_namespace(window, tokens.namespace("luxos-launchpad", "dim"))
call layer.set_layer(window, layer.LAYER_OVERLAY)
call layer.set_anchors(window, [layer.EDGE_TOP, layer.EDGE_BOTTOM, layer.EDGE_LEFT, layer.EDGE_RIGHT])
# pres celou obrazovku vcetne listy a Docku
call layer.set_exclusive_zone(window, -1)
call layer.set_keyboard_mode(window, layer.KEYBOARD_EXCLUSIVE)
call gtk.widget_add_events(window, gtk.POINTER_MOTION_MASK + gtk.BUTTON_PRESS_MASK + gtk.SCROLL_MASK + gtk.SMOOTH_SCROLL_MASK)
fixed = gtk.fixed_new()
call gtk.container_add(window, fixed)
entry = gtk.entry_new()
call gtk.widget_set_name(entry, "luxos-launchpad-entry")
call gtk.entry_set_max_length(entry, 200)
call gtk.fixed_put(fixed, entry, 0, 0)
css = gtk.css_load("")
call apply_css()
S["animate"] = gtk.object_get_bool(gtk.settings_get_default(), "gtk-enable-animations")

call gtk.connect(window, "draw", on_draw)
call gtk.connect(window, "key-press-event", on_key)
call gtk.connect(window, "motion-notify-event", on_motion)
call gtk.connect(window, "button-press-event", on_press)
call gtk.connect(window, "scroll-event", on_scroll)
call gtk.connect(window, "realize", on_realize)
call gtk.connect(window, "size-allocate", on_size)
call gtk.connect(entry, "changed", on_changed)
call gtk.widget_realize(window)

call glib.signal_connect(apps.monitor(), "changed", on_apps_changed, 0)
call glib.mkdir_p(conf_dir)
safe:
    call gio.file_monitor(conf_dir, on_config)
end
call trace("ready pid=" + String(glib.getpid()) + " apps=" + String(len(entries)))
if mode_arg != "":
    call show(mode_arg)
end
call glib.idle_add_data(warm_up, 0)
call gtk.main()
