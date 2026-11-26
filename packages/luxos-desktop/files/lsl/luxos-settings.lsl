# LuxOS - Nastaveni: jedno okno jako Nastaveni systemu v macOS. Vlevo panel z matneho skla s hledanim a seznamem
# stranek, vpravo stranka. Stranky jsou moduly luxos_page_*.lsl (seznam luxos_settings_pages.lsl), stavi se az
# pri prvnim otevreni. Nahrazuje xfce4-settings-manager a samostatna okna nastaveni.
#
#   luxos-settings [STRANKA [ARGUMENTY..]]   okno na strance (bez stranky naposledy otevrena)
#   luxos-power, luxos-bluetooth ...         odkazy na tento program: stranka podle jmena (aliases), argumenty
#                                            jako drive; prikazovy rezim stareho programu (cli) bez okna
# Jedna instance v relaci: jmeno cz.luxos.Settings na sbernici relace; druhe spusteni jen ukaze stranku v bezicim
# okne (Show) a skonci. Sklo panelu kresli luxwm (set_window_material); jinde nepruhledna barva materialu.
# Testy: LUXOS_TEST_CONTROL=1 (luxos_testctl) - page ID, search TEXT, sidebar, state, switch|combo|slider RADEK = HODNOTA.
load env, json
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load gio
load luxos_i18n as i18n
load luxos_text as text
load luxos_tokens as tokens
load luxos_material as material
load luxos_luxwm as wm
load luxos_testctl as testctl
load luxos_sys as lsys
load luxos_launchpad_model as model
load luxos_settings_ui as ui
load luxos_settings_pages as pages

BUS_NAME = "cz.luxos.Settings"
BUS_PATH = "/cz/luxos/Settings"
BUS_XML = "<node><interface name='cz.luxos.Settings'><method name='Show'><arg type='s' direction='in'/><arg type='as' direction='in'/></method></interface></node>"
WIDTH = 920
HEIGHT = 640
SIDEBAR = 220
DEFAULT_PAGE = "appearance"

S = {"window": 0, "header": 0, "stack": 0, "list": 0, "search": 0, "sidebar": 0, "pages": [], "by_id": {}, "rows": {},
     "row_of": {}, "separators": [], "built": {}, "page_rows": {}, "current": "", "host": {}, "glass": False,
     "region": [], "quiet": False, "dark": False, "css": 0, "bus": 0, "retry": 0, "glyphs": 0, "glyph_files": {}}

function wayland():
    return env.get("WAYLAND_DISPLAY", "") != ""
end

function basename(path):
    return path[text.rfind(path, "/") + 1:]
end

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function cstr(value):
    unsafe:
        return __lsl_address(value) + 16
    end
end

# ---- stranky ----------------------------------------------------------------------------------------------------

function available(p):
    if p["only"] == "wayland" and not wayland():
        return False
    end
    if p["only"] == "x11" and wayland():
        return False
    end
    if len(p["exec"]) > 0:
        return glib.find_program_in_path(p["exec"][0]) != ""
    end
    return True
end

function find_page(name):
    for p in pages.all():
        if p["id"] == name or name in p["aliases"]:
            return p
        end
    end
    return None
end

function last_page_path():
    return glib.user_cache_dir() + "/luxos/settings-page"
end

function remember(id):
    call glib.mkdir_p(glib.user_cache_dir() + "/luxos")
    return glib.write_atomic(last_page_path(), id + "\n")
end

function start_page():
    id = glib.read_text(last_page_path()).strip()
    if id in S["by_id"] and len(S["by_id"][id]["exec"]) == 0:
        return id
    end
    if DEFAULT_PAGE in S["by_id"]:
        return DEFAULT_PAGE
    end
    return [p["id"] for p in S["pages"] if len(p["exec"]) == 0][0]
end

# Stranka se postavi pri prvnim otevreni: titulek a okraje okolo widgetu modulu, posuvnik
function build_page(p):
    ui.state["rows"] = {}
    S["host"] = {"window": S["window"], "wayland": wayland(), "args": S["host"].get("args", []), "page": p["id"]}
    body = None
    try:
        body = p["build"](S["host"])
    else:
        call glib.report("luxos-settings: page " + p["id"] + ": " + String(last_error()) + "\n")
        body = ui.label(i18n.T("This page could not be opened."), "hint")
    end
    S["page_rows"][p["id"]] = ui.state["rows"]
    box = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_margins(box, 28, 28, 18, 28)
    title = gtk.label_new(i18n.T(p["title"]))
    call gtk.label_set_xalign(title, 0)
    call gtk.widget_add_class(title, "page-title")
    call gtk.box_pack_start(box, title, False, False, 0)
    call gtk.box_pack_start(box, body, True, True, 0)
    scroll = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(scroll, gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
    call gtk.widget_add_class(scroll, "content")
    call gtk.container_add(scroll, box)
    call gtk.widget_show_all(scroll)
    call gtk.stack_add_named(S["stack"], scroll, p["id"])
    S["built"][p["id"]] = scroll
    return scroll
end

function call_hook(p, name):
    if p[name] == None:
        return 0
    end
    try:
        call p[name](S["host"])
    else:
        call glib.report("luxos-settings: " + name + " " + p["id"] + ": " + String(last_error()) + "\n")
    end
    return 0
end

function open_page(id, args):
    p = S["by_id"].get(id, None)
    if p == None:
        return False
    end
    if len(p["exec"]) > 0:
        call ui.launch(p["exec"] + args)
        return True
    end
    if S["current"] != "" and S["current"] != id:
        call call_hook(S["by_id"][S["current"]], "leave")
    end
    S["host"]["args"] = args
    if not (id in S["built"]):
        call build_page(p)
    else:
        S["host"]["args"] = args
        S["host"]["page"] = id
        ui.state["rows"] = S["page_rows"][id]
    end
    S["current"] = id
    call gtk.stack_set_visible_child_name(S["stack"], id)
    call set_title(i18n.T(p["title"]))
    call select_row(id)
    call call_hook(p, "show")
    call remember(id)
    return True
end

function set_title(title):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("gtk_header_bar_set_title"), ptr(S["header"]), cstr(title))
    end
    return gtk.window_set_title(S["window"], title)
end

# ---- postranni panel --------------------------------------------------------------------------------------------

# Znak na dlazdici vzdy z WhiteSur-light jako soubor: v jinem motivu ikon chybejici symbolicka ikona spadne na barevnou,
# mensi nez dlazdice, a zbytek dlazdice zustane tmavy. Soubor -symbolic.svg GTK prebarvi podle CSS jako ikonu z motivu.
function glyph_file(name):
    unsafe:
        if S["glyphs"] == 0:
            S["glyphs"] = __lsl_qbe_call0(__lsl_symbol("gtk_icon_theme_new"))
            call __lsl_qbe_call2(__lsl_symbol("gtk_icon_theme_set_custom_theme"), ptr(S["glyphs"]), cstr("WhiteSur-light"))
        end
        info = __lsl_qbe_call4(__lsl_symbol("gtk_icon_theme_lookup_icon"), ptr(S["glyphs"]), cstr(name), 16, 0)
        if info == 0:
            return ""
        end
        path = glib.from_c(__lsl_qbe_call1(__lsl_symbol("gtk_icon_info_get_filename"), info))
        call glib.object_unref(info)
    end
    if path.endswith("/" + name + ".svg"):
        return path
    end
    return ""
end

function glyph(p):
    path = glyph_file(p["icon"])
    S["glyph_files"][p["id"]] = path
    if path == "":
        return gtk.image_new_from_icon_name(p["icon"], gtk.ICON_MENU)
    end
    unsafe:
        file = __lsl_qbe_call1(__lsl_symbol("g_file_new_for_path"), cstr(path))
        icon = __lsl_qbe_call1(__lsl_symbol("g_file_icon_new"), file)
        image = __lsl_qbe_call2(__lsl_symbol("gtk_image_new_from_gicon"), icon, gtk.ICON_MENU)
        call glib.object_unref(icon)
        call glib.object_unref(file)
    end
    return image
end

function plate(p):
    box = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_add_class(box, "plate")
    call gtk.widget_set_name(box, "plate-" + p["id"])
    call gtk.widget_set_valign(box, gtk.ALIGN_CENTER)
    image = glyph(p)
    # navrh WhiteSur je na mrizce 16 px: 14 px rozmaze tahy a necha znak maly
    call gtk.image_set_pixel_size(image, 16)
    call gtk.widget_set_halign(image, gtk.ALIGN_CENTER)
    call gtk.box_pack_start(box, image, True, True, 0)
    return box
end

function row_widget(p):
    box = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_add_class(box, "side-row")
    call gtk.box_pack_start(box, plate(p), False, False, 0)
    label = gtk.label_new(i18n.T(p["title"]))
    call gtk.label_set_xalign(label, 0)
    call gtk.label_set_ellipsize(label, 3)
    call gtk.box_pack_start(box, label, True, True, 0)
    if len(p["exec"]) > 0:
        # samostatna aplikace: otevre se v novem okne
        arrow = gtk.image_new_from_icon_name("go-next-symbolic", gtk.ICON_MENU)
        call gtk.image_set_pixel_size(arrow, 12)
        call gtk.widget_add_class(arrow, "side-arrow")
        call gtk.box_pack_end(box, arrow, False, False, 0)
    end
    return box
end

function list_row(child, selectable):
    unsafe:
        row = __lsl_qbe_call0(__lsl_symbol("gtk_list_box_row_new"))
        call __lsl_qbe_call2(__lsl_symbol("gtk_list_box_row_set_selectable"), row, gtk.flag(selectable))
        call __lsl_qbe_call2(__lsl_symbol("gtk_list_box_row_set_activatable"), row, gtk.flag(selectable))
        call gtk.container_add(row, child)
        call gtk.container_add(ptr(S["list"]), row)
        return row
    end
end

function select_row(id):
    row = S["row_of"].get(id, 0)
    S["quiet"] = True
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("gtk_list_box_select_row"), ptr(S["list"]), ptr(row))
    end
    S["quiet"] = False
    return 0
end

function on_row_selected(row, listbox):
    if S["quiet"] or row == 0 or not (row in S["rows"]):
        return 0
    end
    id = S["rows"][row]
    p = S["by_id"][id]
    call open_page(id, [])
    if len(p["exec"]) > 0 and S["current"] != "":
        # aplikace se otevrela ve vlastnim okne, vyber zustava na strance
        call select_row(S["current"])
    end
    return 0
end

function build_sidebar():
    side = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_add_class(side, "sidebar")
    call gtk.widget_set_size_request(side, SIDEBAR, -1)
    search = gtk.search_entry_new()
    call gtk.entry_set_placeholder_text(search, i18n.T("Search"))
    call gtk.widget_set_margins(search, 12, 12, 10, 8)
    call gtk.connect(search, "search-changed", on_search)
    call gtk.connect(search, "activate", on_search_activate)
    S["search"] = search
    call gtk.box_pack_start(side, search, False, False, 0)
    scroll = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(scroll, gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
    call gtk.widget_add_class(scroll, "sidebar-scroll")
    S["list"] = gtk.list_box_new()
    call gtk.widget_add_class(S["list"], "side-list")
    call gtk.container_add(scroll, S["list"])
    call gtk.box_pack_start(side, scroll, True, True, 0)
    group = -1
    for p in S["pages"]:
        if p["group"] != group and group >= 0:
            sep = list_row(gtk.box_new(gtk.HORIZONTAL, 0), False)
            call gtk.widget_add_class(sep, "side-gap")
            S["separators"].append(sep)
        end
        group = p["group"]
        row = list_row(row_widget(p), True)
        call gtk.widget_set_name(row, "side-" + p["id"])
        S["rows"][row] = p["id"]
        S["row_of"][p["id"]] = row
    end
    call gtk.connect(S["list"], "row-selected", on_row_selected)
    S["sidebar"] = side
    return side
end

function search_words(p):
    words = [i18n.T(p["title"]), p["title"]]
    for k in p["keywords"]:
        # klicova slova jsou v prekladech vetsinou s velkym pismenem (nadpisy skupin a radku)
        words.append(i18n.T(k))
        words.append(i18n.T(k[0:1].upper() + k[1:]))
        words.append(k)
    end
    return model.fold(" | ".join(words))
end

function matches(p, query):
    hay = search_words(p)
    for word in model.words(query):
        if hay.find(word) < 0:
            return False
        end
    end
    return True
end

function on_search(entry):
    query = gtk.entry_get_text(entry).strip()
    for row in S["rows"]:
        call gtk.widget_set_visible(row, query == "" or matches(S["by_id"][S["rows"][row]], query))
    end
    for sep in S["separators"]:
        call gtk.widget_set_visible(sep, query == "")
    end
    return 0
end

function visible_ids():
    return [p["id"] for p in S["pages"] if gtk.widget_get_visible(S["row_of"][p["id"]])]
end

function on_search_activate(entry):
    ids = visible_ids()
    if len(ids) > 0:
        call open_page(ids[0], [])
    end
    return 0
end

# ---- vzhled a sklo -----------------------------------------------------------------------------------------------

function sidebar_css():
    dark = S["dark"]
    tint = tokens.material("popup", dark, S["glass"])
    if not S["glass"]:
        tint = [tint[0], tint[1], tint[2], 1.0]
    end
    out = ".sidebar, .sidebar-scroll, .side-list, .side-list row { background-color: transparent; }\n"
    # Oddelovac lezi na souvislem sklu, CSS border by zabral pixel s nezatonavanym pozadim.
    out = out + ".sidebar { background-color: " + tokens.css_color(tint) + "; color: " + ui.c("fg", dark) + "; box-shadow: inset -1px 0 " + ui.c("border", dark) + "; }\n"
    out = out + ".side-list row { min-height: 30px; padding: 0 8px; margin: 0 10px; border-radius: 6px; }\n"
    out = out + ".side-list row:hover { background-color: " + ui.c("tile", dark) + "; }\n"
    out = out + ".side-list row:selected { background-color: " + ui.c("accent", dark) + "; color: #ffffff; }\n"
    out = out + ".side-list row:selected label { color: #ffffff; }\n"
    out = out + ".side-list row.side-gap { min-height: 10px; }\n"
    out = out + ".side-arrow { opacity: 0.45; }\n"
    out = out + ".plate { min-width: 20px; min-height: 20px; border-radius: 5px; color: #ffffff; }\n"
    out = out + ".plate image { -gtk-icon-style: symbolic; color: #ffffff; }\n"
    for p in S["pages"]:
        out = out + "#plate-" + p["id"] + " { background-color: " + p["color"] + "; }\n"
    end
    if S["glass"]:
        out = out + "window.settings-window.glass, window.settings-window.glass > box { background-color: transparent; }\n"
    end
    return out
end

function apply_css():
    css = ui.css(S["dark"]) + sidebar_css()
    if S["css"] == 0:
        S["css"] = gtk.css_load(css)
    else:
        call gtk.css_set(S["css"], css)
    end
    call gtk.widget_set_class(S["window"], "glass", S["glass"])
    return 0
end

function on_appearance(file, event, other):
    dark = ui.dark_mode()
    if dark != S["dark"]:
        S["dark"] = dark
        call apply_css()
    end
    return 0
end

# Obdelnik panelu v souradnicich okna bez stinu CSD (od leveho horniho rohu HeaderBar)
function sidebar_region():
    unsafe:
        xy = __lsl_byte_zeros(16)
        hb = __lsl_byte_zeros(16)
        call __lsl_qbe_call6(__lsl_symbol("gtk_widget_translate_coordinates"), ptr(S["sidebar"]), ptr(S["window"]), 0, 0,
                             gtk.data(xy), gtk.data(xy) + 4)
        call __lsl_qbe_call6(__lsl_symbol("gtk_widget_translate_coordinates"), ptr(S["header"]), ptr(S["window"]), 0, 0,
                             gtk.data(hb), gtk.data(hb) + 4)
        x = __lsl_qbe_s32(__lsl_qbe_load32(gtk.data(xy))) - __lsl_qbe_s32(__lsl_qbe_load32(gtk.data(hb)))
        y = __lsl_qbe_s32(__lsl_qbe_load32(gtk.data(xy) + 4)) - __lsl_qbe_s32(__lsl_qbe_load32(gtk.data(hb) + 4))
    end
    return [x, y, gtk.widget_get_allocated_width(S["sidebar"]), gtk.widget_get_allocated_height(S["sidebar"])]
end

function send_region():
    if not wayland() or not wm.connected() or not gtk.widget_get_visible(S["window"]):
        return False
    end
    r = sidebar_region()
    if r == S["region"] or r[2] <= 1:
        return False
    end
    S["region"] = r
    call wm.request({"cmd": "set_window_material", "app_id": "luxos-settings", "material": "popup", "radius": 0,
                     "x": r[0], "y": r[1], "w": r[2], "h": r[3]}, on_material_reply)
    return False
end

function on_material_reply(reply):
    glass = reply != None and reply.get("ok", False) == True
    # pozadavek predbehl namapovani okna: luxwm sklo da az s oknem, panel se to dozvi dalsim pozadavkem
    if not glass and reply != None and reply.get("error", "") == "no such window" and S["retry"] < 10:
        S["retry"] += 1
        S["region"] = []
        call glib.timeout_add(300, send_region)
    end
    if glass != S["glass"]:
        S["glass"] = glass
        call apply_css()
    end
    return 0
end

function on_sidebar_allocate(allocation, widget):
    call glib.idle_add(send_region)
    return 0
end

function on_wm_state(up):
    if up:
        S["region"] = []
        call glib.idle_add(send_region)
    elif S["glass"]:
        S["glass"] = False
        call apply_css()
    end
    return 0
end

function on_wm_event(event):
    return 0
end

# ---- okno ---------------------------------------------------------------------------------------------------------

function on_destroy(window):
    if S["current"] != "":
        call call_hook(S["by_id"][S["current"]], "leave")
    end
    call ui.gs_sync()
    call gtk.main_quit()
    return 0
end

function build_window():
    w = gtk.window_new(i18n.T("Settings"))
    S["window"] = w
    call gtk.window_set_wmclass(w, "luxos-settings", "luxos-settings")
    call gtk.window_set_icon_list(w, "preferences-system")
    call gtk.widget_add_class(w, "settings-window")
    if wayland():
        call gtk.widget_set_rgba_visual(w)
    end
    unsafe:
        bar = __lsl_qbe_call0(__lsl_symbol("gtk_header_bar_new"))
        call __lsl_qbe_call2(__lsl_symbol("gtk_header_bar_set_show_close_button"), bar, 1)
        call __lsl_qbe_call2(__lsl_symbol("gtk_window_set_titlebar"), ptr(w), bar)
        S["header"] = bar
    end
    area = gtk.primary_monitor_workarea()
    width = min(WIDTH, max(ui.MIN_WIDTH, area[2] - 2 * ui.MARGIN))
    height = min(HEIGHT, ui.max_content_height())
    call gtk.window_set_default_size(w, width, height)
    call gtk.widget_set_size_request(w, min(640, width), min(420, height))
    body = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.box_pack_start(body, build_sidebar(), False, False, 0)
    S["stack"] = gtk.stack_new(False)
    call gtk.stack_set_transition_duration(S["stack"], 0)
    call gtk.widget_add_class(S["stack"], "content")
    call gtk.box_pack_start(body, S["stack"], True, True, 0)
    call gtk.container_add(w, body)
    call gtk.connect(w, "destroy", on_destroy)
    call gtk.connect(S["sidebar"], "size-allocate", on_sidebar_allocate)
    call ui.attach_test(w)
    return w
end

# ---- jedna instance ---------------------------------------------------------------------------------------------

function on_bus_call(sender, path, interface, method, values, invocation):
    call gio.return_value(invocation, [], "")
    if method == "Show":
        call glib.idle_add_data(show_request, values)
    end
    return 0
end

# Az po odpovedi: druhe spusteni neceka na postaveni stranky
function show_request(values):
    p = find_page(values[0])
    id = S["current"]
    if p != None and p["id"] in S["by_id"]:
        id = p["id"]
    end
    call open_page(id, values[1])
    call gtk.window_present(S["window"])
    return False
end

# True = jsme jedina instance (nebo sbernice neni); False = stranku ukazala bezici instance
function claim_instance(id, args):
    bus = 0
    safe:
        bus = gio.session_bus()
    end
    if bus == 0:
        return True
    end
    S["bus"] = bus
    reply = None
    safe:
        reply = gio.call_values(bus, "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName",
                                [BUS_NAME, 4], "(su)", 2000)
    end
    if reply == None or reply[0] == 1 or reply[0] == 4:
        safe:
            call gio.register_object(bus, BUS_PATH, BUS_XML, on_bus_call)
        end
        return True
    end
    shown = False
    safe:
        call gio.call_values(bus, BUS_NAME, BUS_PATH, BUS_NAME, "Show", [id, args], "(sas)", 5000)
        shown = True
    end
    return not shown
end

# ---- testy --------------------------------------------------------------------------------------------------------

function test_row(kind, rest):
    cut = rest.find(" = ")
    if cut < 0:
        return False
    end
    title = rest[:cut]
    value = rest[cut + 3:]
    w = ui.state["rows"].get(title, 0)
    if w == 0:
        call lsys.out("missing " + title + "\n")
        return True
    end
    if kind == "switch":
        call gtk.switch_set_active(w, value == "on")
    elif kind == "combo":
        call ui.combo_set_active_id(w, value)
    else:
        call gtk.range_set_value(w, Float(Int(value)))
    end
    return True
end

function on_test(command, rest):
    if command == "page":
        parts = [a for a in rest.split(" ") if a != ""]
        call open_page(parts[0], parts[1:])
    elif command == "search":
        call gtk.entry_set_text(S["search"], rest)
        call on_search(S["search"])
    elif command == "sidebar":
        call lsys.out("sidebar " + json.encode(visible_ids()) + "\n")
    elif command == "glyphs":
        call lsys.out("glyphs " + json.encode(S["glyph_files"]) + "\n")
    elif command == "state":
        call lsys.out("state " + json.encode({"page": S["current"], "glass": S["glass"], "region": S["region"],
                                                       "dark": S["dark"], "built": [k for k in S["built"]]}) + "\n")
    elif command in ["switch", "combo", "slider"] and rest.find(" = ") > 0:
        call test_row(command, rest)
    elif S["current"] != "" and S["by_id"][S["current"]]["test"] != None:
        call S["by_id"][S["current"]]["test"](command, rest)
    end
    return 0
end

# ---- start --------------------------------------------------------------------------------------------------------

function main():
    argv = [a for a in args]
    name = basename(argv[0])
    rest = argv[1:]
    target = None
    if name != "luxos-settings":
        target = find_page(name)
    end
    if target == None and len(rest) > 0 and find_page(rest[0]) != None:
        target = find_page(rest[0])
        rest = rest[1:]
    end
    # prikazovy rezim stareho programu (luxos-app-reset list, luxos-scrolling status ...)
    if target != None and target["cli"] != None:
        code = target["cli"](rest)
        if code != None:
            exit(code)
        end
    end
    call glib.set_prgname("luxos-settings")
    call gtk.init()
    # postranni panel je sklo kompozitoru (set_window_material): pismo v odstinech sedi
    call material.grayscale_text()
    for p in pages.all():
        if available(p):
            S["pages"].append(p)
            S["by_id"][p["id"]] = p
        end
    end
    id = ""
    if target != None and target["id"] in S["by_id"]:
        id = target["id"]
    end
    if not claim_instance(id, rest):
        exit(0)
    end
    if id == "":
        id = start_page()
    end
    if not (id in S["by_id"]):
        id = S["pages"][0]["id"]
    end
    S["dark"] = ui.dark_mode()
    call build_window()
    call apply_css()
    safe:
        call glib.mkdir_p(glib.user_config_dir() + "/luxos")
        call gio.file_monitor(glib.user_config_dir() + "/luxos/appearance", on_appearance)
    end
    call gtk.widget_show_all(S["window"])
    call open_page(id, rest)
    if len(S["by_id"][id]["exec"]) > 0:
        call open_page(start_page(), [])
    end
    if wayland():
        call wm.on_state(on_wm_state)
        call wm.connect(on_wm_event)
    end
    call testctl.start(on_test)
    ui.state["on_test"] = on_test
    call gtk.main()
end

call main()
