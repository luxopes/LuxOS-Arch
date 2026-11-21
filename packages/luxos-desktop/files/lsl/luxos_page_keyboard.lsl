# LuxOS - Nastaveni > Klavesnice (drive luxos-keyboard-settings; /usr/lib/luxos/luxos-keyboard-settings je odkaz
# na luxos-settings, spousti ho luxos-keyboard a luxos-shortcuts): opakovani drzene klavesy, karty Rozlozeni
# a Zkratky. Na X11 karty z luxos_keyboard_x11.lsl (localectl/setxkbmap a xfconf), na Waylandu (luxwm) nize.
#
#   luxos-keyboard-settings [--shortcuts]       stranka (s --shortcuts karta Zkratky)
#   luxos-keyboard-settings --import-shortcuts  jen jednou prevede zkratky Xfce do ~/.config/luxwm/luxwm.conf
#   luxos-keyboard-settings --migrate-switch    jednou za zivot systemu stare vychozi prepinani Alt+Shift ->
#                                               obe klavesy Shift (luxos-desktop.install, jako root)
#
# Opakovani klavesy: Wayland repeat_rate/repeat_delay v ~/.config/luxwm/luxwm.conf (luxwm je po reload hned
# pouzije), X11 kanal xfconf keyboards /Default/KeyRepeat (Rate, Delay; pouzije xfsettingsd).
# Rozlozeni (Wayland): zdroj je localed (cely system, prihlaseni, konzole). Zmena na strance plati hned jen pro
# uzivatele (xkb_* v luxwm.conf); "Pouzit pro vsechny" ji zapise pres localectl (polkit) a vlastni rozlozeni
# uzivatele smaze. Zkratky: polozky [keys] v uzivatelskem luxwm.conf.
# Testy: page-state, tab|switcher layouts|shortcuts, layout-search TEXT (hledani v dialogu rozlozeni); na X11 ostatni
# prikazy dostane karta, ktera je videt (luxos_keyboard_x11).
load env, json
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_gio, gio as gio
load luxos_i18n as i18n
load luxos_luxwm as wm
load luxos_wm_config as cfg
load luxos_glib as lglib
load luxos_keyboard_model as kb
load luxos_keyboard_x11 as x11
load luxos_settings_ui as ui
load luxos_sys as sys

MAX_LAYOUTS = kb.MAX_LAYOUTS
XORG_CONF = kb.CONF
DEFAULT_SWITCH = kb.DEFAULT_SWITCH
SWITCH_OPTIONS = kb.SWITCH_OPTIONS
# Zkratky na karte: [nazev, hodnota luxwm]; stejne nazvy jako na X11 (maji preklady)
CATALOG = [["Windows", [["Close window", "close_window_key"], ["Minimize window", "hide_window_key"],
        ["Switch windows", "cycle_windows_key"], ["Switch windows backwards", "cycle_reverse_windows_key"],
        ["Switch windows of the current app", "cycle_app_windows_key"], ["Maximize window", "maximize_window_key"],
        ["Tile window left", "tile_left_key"], ["Tile window right", "tile_right_key"], ["Full screen", "fullscreen_key"],
        ["Show desktop", "show_desktop_key"], ["Previous workspace", "left_workspace_key"],
        ["Next workspace", "right_workspace_key"]]],
    ["Apps & System", [["Search", "exec luxos-search"], ["Launchpad", "exec luxos-launchpad"], ["Files", "exec thunar"],
        ["Terminal", "exec luxos-terminal"], ["Settings", "exec luxos-settings"], ["Lock screen", "exec loginctl lock-session"],
        ["System monitor (force quit)", "exec luxos-monitor"], ["Calculator", "exec luxos-calculator"],
        ["Emoji & Symbols", "exec luxos-emoji"]]],
    ["Screenshots", [["Screenshot", "exec luxos-screenshot --screen"], ["Screenshot of region", "exec luxos-screenshot --portion"],
        ["Screenshot tool", "exec luxos-screenshot"]]]]
KEY_LABELS = {"space": "Space", "Escape": "Esc", "Tab": "Tab", "Return": "Return", "Up": "↑", "Down": "↓", "Left": "←",
    "Right": "→", "Print": "Print Screen", "grave": "`", "comma": ",", "period": ".", "minus": "-", "equal": "=",
    "slash": "/", "BackSpace": "Backspace", "Delete": "Delete", "XF86Calculator": "Calculator", "XF86LaunchA": "Launch A"}
CSS = ".accel { font-weight: 600; }\n.keyboard-tabs { margin: 22px 0 2px 0; }\n"
# Polohy posuvniku: znaky za sekundu (0 = vypnuto) a prodleva v ms (od dlouhe po kratkou jako v macOS)
RATES = [0, 3, 6, 10, 15, 20, 25, 30, 40, 50]
DELAYS = [2000, 1500, 1200, 900, 600, 500, 400, 300, 250, 200]
# Vychozi hodnoty: libluxcomp (Wayland) a xfsettingsd (X11)
WL_REPEAT = [25, 600]
X11_REPEAT = [20, 500]

P = {"window": 0, "wayland": False, "stack": 0, "tabs": {}, "built": {}, "css": 0, "repeat": [0, 0]}
ui_kb = {"buttons": {}, "catalog": [], "layouts": [], "options": [], "model": "", "own": False, "system": [],
         "status": "", "capture": None, "dialog": 0, "rows": []}

# ---- opakovani klavesy ------------------------------------------------------------------------------

function xfconf_query():
    value = env.get("LUXOS_XFCONF_QUERY", "")
    if value == "":
        return "xfconf-query"
    end
    return value
end

function xfconf_get(prop):
    return ui.run([xfconf_query(), "-c", "keyboards", "-p", prop]).strip()
end

function xfconf_set(prop, kind, value):
    return ui.run([xfconf_query(), "-c", "keyboards", "-p", prop, "-n", "-t", kind, "-s", value])
end

function number(text, default):
    value = default
    safe:
        value = Int(text.strip())
    end
    return value
end

# [znaky za sekundu, prodleva ms]; 0 znaku = opakovani vypnute
function read_repeat():
    if P["wayland"]:
        general = cfg.system_conf()["general"]
        general.update(cfg.user_conf()["general"])
        return [number(general.get("repeat_rate", ""), WL_REPEAT[0]), number(general.get("repeat_delay", ""), WL_REPEAT[1])]
    end
    rate = number(xfconf_get("/Default/KeyRepeat/Rate"), X11_REPEAT[0])
    delay = number(xfconf_get("/Default/KeyRepeat/Delay"), X11_REPEAT[1])
    if xfconf_get("/Default/KeyRepeat") == "false":
        rate = 0
    end
    return [rate, delay]
end

function nearest(values, value):
    best = 0
    for i in range(len(values)):
        if abs(values[i] - value) < abs(values[best] - value):
            best = i
        end
    end
    return best
end

function write_repeat():
    rate = P["repeat"][0]
    delay = P["repeat"][1]
    if P["wayland"]:
        call cfg.save({"repeat_rate": String(rate), "repeat_delay": String(delay)}, {})
        call luxwm_reload()
        return 0
    end
    call xfconf_set("/Default/KeyRepeat", "bool", "true" if rate > 0 else "false")
    if rate > 0:
        call xfconf_set("/Default/KeyRepeat/Rate", "int", String(rate))
    end
    call xfconf_set("/Default/KeyRepeat/Delay", "int", String(delay))
    return 0
end

function on_rate(unused, index):
    P["repeat"][0] = RATES[max(0, min(len(RATES) - 1, index))]
    return write_repeat()
end

function on_delay(unused, index):
    P["repeat"][1] = DELAYS[max(0, min(len(DELAYS) - 1, index))]
    return write_repeat()
end

# Posuvnik s popisky na koncich; testy ho nastavuji pres nazev radku (slider RADEK = N)
function repeat_row(g, title, values, current, left, right, handler):
    slider = ui.slider(0, len(values) - 1, nearest(values, current), 200, handler, 0)
    unsafe:
        for i in range(len(values)):
            call __lsl_qbe_call4(__lsl_symbol("gtk_scale_add_mark"), glib.ptr(slider), Float(i), 3, 0)
        end
    end
    box = gtk.box_new(gtk.HORIZONTAL, 8)
    start = ui.label(left, "hint")
    # oba posuvniky pod sebou stejne siroke i s ruzne dlouhymi popisky
    call gtk.label_set_xalign(start, 1)
    call gtk.widget_set_size_request(start, 64, -1)
    call gtk.box_pack_start(box, start, False, False, 0)
    call gtk.box_pack_start(box, slider, False, False, 0)
    call gtk.box_pack_start(box, ui.label(right, "hint"), False, False, 0)
    call ui.row(g, title, "", box)
    ui.state["rows"][title] = slider
    return slider
end

function build_repeat(page):
    P["repeat"] = read_repeat()
    g = ui.group(page, i18n.T("Key Repeat"))
    call repeat_row(g, i18n.T("Key repeat rate"), RATES, P["repeat"][0], i18n.T("Off"), i18n.T("Fast"), on_rate)
    call repeat_row(g, i18n.T("Delay until repeat"), DELAYS, P["repeat"][1], i18n.T("Long"), i18n.T("Short"), on_delay)
    return g
end

# ---- rozlozeni (Wayland): stav -------------------------------------------------------------------

function split_names(layout, variant):
    codes = layout.split(",")
    variants = variant.split(",")
    out = []
    for i in range(len(codes)):
        if codes[i].strip() != "":
            out.append([codes[i].strip(), variants[i].strip() if i < len(variants) else ""])
        end
    end
    return out
end

function split_options(text):
    out = []
    for o in text.split(","):
        if o.strip() != "":
            out.append(o.strip())
        end
    end
    return out
end

# localed, bez nej 00-keyboard.conf; [rozlozeni, volby, model]
function system_keyboard():
    try:
        bus = gio.system_bus()
        v = gio.call_values(bus, "org.freedesktop.locale1", "/org/freedesktop/locale1", "org.freedesktop.DBus.Properties",
                            "GetAll", ["org.freedesktop.locale1"], "(s)", 2000)[0]
        layouts = split_names(String(v.get("X11Layout", "")), String(v.get("X11Variant", "")))
        if len(layouts) > 0:
            return [layouts, split_options(String(v.get("X11Options", ""))), String(v.get("X11Model", ""))]
        end
    else:
        layouts = []
    end
    vals = {}
    for line in lglib.read_text(env.get("LUXOS_KEYBOARD_CONF", XORG_CONF)).split("\n"):
        parts = line.strip().split("\"")
        if len(parts) >= 4 and parts[0].strip() == "Option":
            vals[parts[1]] = parts[3]
        end
    end
    layouts = split_names(vals.get("XkbLayout", ""), vals.get("XkbVariant", ""))
    if len(layouts) == 0:
        layouts = [["us", ""]]
    end
    return [layouts, split_options(vals.get("XkbOptions", "")), vals.get("XkbModel", "")]
end

function load_keyboard():
    system = system_keyboard()
    ui_kb["system"] = system
    ui_kb["model"] = system[2]
    user = cfg.user_conf()["general"]
    ui_kb["own"] = user.get("xkb_layout", "") != ""
    if ui_kb["own"]:
        ui_kb["layouts"] = split_names(user["xkb_layout"], user.get("xkb_variant", ""))
    else:
        ui_kb["layouts"] = system[0]
    end
    if "xkb_options" in user:
        ui_kb["options"] = split_options(user["xkb_options"])
    else:
        ui_kb["options"] = system[1]
    end
end

function joined(layouts, index):
    return ",".join([item[index] for item in layouts])
end

function luxwm_reload():
    call wm.request({"cmd": "reload"}, None)
end

# Zmena na strance: hned pro uzivatele (luxwm nacte xkb_* z luxwm.conf)
function save_user_keyboard():
    call cfg.save({"xkb_layout": joined(ui_kb["layouts"], 0), "xkb_variant": joined(ui_kb["layouts"], 1),
                   "xkb_options": ",".join(ui_kb["options"])}, {})
    ui_kb["own"] = True
    call luxwm_reload()
    call fill_wayland()
end

function apply_system():
    argv = ["localectl", "set-x11-keymap", joined(ui_kb["layouts"], 0), ui_kb["model"], joined(ui_kb["layouts"], 1),
            ",".join(ui_kb["options"])]
    ui_kb["status"] = i18n.T("Saving…")
    call fill_wayland()
    if glib.spawn_capture(argv, on_applied, 0) == 0:
        ui_kb["status"] = i18n.T("Could not save the keyboard layouts: %s").replace("%s", "localectl")
        call fill_wayland()
    end
end

function on_applied(unused, output, status):
    if status == 0:
        # system je ted stejny: vlastni rozlozeni uzivatele uz neni potreba
        call cfg.save({"xkb_layout": None, "xkb_variant": None, "xkb_options": None}, {})
        ui_kb["own"] = False
        ui_kb["status"] = i18n.T("Saved for all users and the login screen.")
        call luxwm_reload()
    else:
        low = output.lower()
        if low.find("denied") >= 0 or low.find("not authorized") >= 0 or low.find("dismissed") >= 0:
            ui_kb["status"] = i18n.T("Not saved: administrator authentication was cancelled.")
        else:
            ui_kb["status"] = i18n.T("Could not save the keyboard layouts: %s").replace("%s", output.strip())
        end
    end
    call fill_wayland()
    return 0
end

function catalog():
    if len(ui_kb["catalog"]) == 0:
        ui_kb["catalog"] = kb.catalog("")
    end
    return ui_kb["catalog"]
end

function tr(text):
    return i18n.T(text)
end

function describe(key):
    return kb.describe(key, catalog(), tr)
end

# ---- zkratky (Wayland) ----------------------------------------------------------------------------

function effective_keys():
    keys = cfg.system_conf()["keys"]
    user = cfg.user_conf()["keys"]
    for accel in user.keys():
        keys[accel] = user[accel]
    end
    return keys
end

function accels_for(keys, value):
    return sorted([a for a in keys.keys() if keys[a] == value])
end

function key_of(accel):
    parts = accel.split(">")
    return parts[len(parts) - 1]
end

function format_accel(accel):
    parts = []
    for pair in [["<Primary>", "Ctrl"], ["<Super>", "Super"], ["<Alt>", "Alt"], ["<Shift>", "Shift"]]:
        if accel.find(pair[0]) >= 0:
            parts.append(pair[1])
        end
    end
    key = key_of(accel)
    if key in KEY_LABELS:
        key = KEY_LABELS[key]
    elif len(key) == 1:
        key = key.upper()
    end
    parts.append(key)
    return " + ".join(parts)
end

# Pouzitelna globalni zkratka: s Ctrl/Alt/Super, nebo samotna funkcni, multimedialni klavesa ci Print
function accel_allowed(accel):
    key = key_of(accel)
    if key == "" or key.startswith("Shift") or key.startswith("Control") or key.startswith("Alt") or key.startswith("Super") or key.startswith("ISO_"):
        return False
    end
    if accel.find("<Primary>") >= 0 or accel.find("<Alt>") >= 0 or accel.find("<Super>") >= 0:
        return True
    end
    return key.startswith("XF86") or key == "Print" or key == "Pause" or (key.startswith("F") and len(key) <= 3 and len(key) >= 2)
end

# Nova zkratka akce: puvodni zkratky akce se vypnou (systemove prazdnou hodnotou), kolidujici zkratka
# jine akce se prepise
function assign(value, accel):
    system = cfg.system_conf()["keys"]
    changes = {}
    for old in accels_for(effective_keys(), value):
        if old != accel:
            changes[old] = "" if old in system else None
        end
    end
    changes[accel] = value
    if system.get(accel, None) == value:
        changes[accel] = None
    end
    call cfg.save({}, changes)
    call luxwm_reload()
end

function restore(value):
    system = cfg.system_conf()["keys"]
    user = cfg.user_conf()["keys"]
    changes = {}
    for accel in user.keys():
        if user[accel] == value or system.get(accel, None) == value:
            changes[accel] = None
        end
    end
    if len(changes) > 0:
        call cfg.save({}, changes)
        call luxwm_reload()
    end
end

function is_default(value):
    system = cfg.system_conf()["keys"]
    return accels_for(effective_keys(), value) == accels_for(system, value)
end

# ---- karty (Wayland) -------------------------------------------------------------------------------

function button(text, action, data, sensitive):
    b = gtk.button_new(text)
    ui_kb["buttons"][b] = [action, data]
    call gtk.connect(b, "clicked", on_button)
    call gtk.widget_set_sensitive(b, sensitive)
    return b
end

function clear(box):
    for child in gtk.container_get_children(box):
        call gtk.widget_destroy(child)
    end
end

function build_layouts(page):
    n = len(ui_kb["layouts"])
    g = ui.group(page, i18n.T("Layouts"))
    for i in range(n):
        key = ui_kb["layouts"][i]
        tools = gtk.box_new(gtk.HORIZONTAL, 4)
        call gtk.box_pack_start(tools, button("↑", "up", i, i > 0), False, False, 0)
        call gtk.box_pack_start(tools, button("↓", "down", i, i < n - 1), False, False, 0)
        call gtk.box_pack_start(tools, button(i18n.T("Remove"), "remove", i, n > 1), False, False, 0)
        hint = kb.short(key)
        if i == 0:
            hint = i18n.T("Default") + " · " + hint
        end
        call ui.row(g, describe(key), hint, tools)
    end
    call ui.row(g, "", "", button(i18n.T("Add Layout…"), "add", None, n < MAX_LAYOUTS))
    note = ui.label(i18n.T("The first layout is the default. Switch between them with the shortcut below or by clicking the flag in the menu bar."), "hint")
    call gtk.widget_set_margins(note, 4, 0, 6, 0)
    call gtk.box_pack_start(page, note, False, False, 0)

    g = ui.group(page, i18n.T("Switching"))
    combo = gtk.combo_box_text_new()
    current = kb.switch_of(ui_kb["options"])
    active = 0
    for i in range(len(SWITCH_OPTIONS)):
        call gtk.combo_box_text_append(combo, String(i), i18n.T(SWITCH_OPTIONS[i][1]))
        if SWITCH_OPTIONS[i][0] == current:
            active = i
        end
    end
    call gtk.combo_box_set_active(combo, active)
    call gtk.connect(combo, "changed", on_switch_changed)
    call ui.row(g, i18n.T("Switch layouts with"), "", combo)
    test = gtk.entry_new()
    call gtk.entry_set_placeholder_text(test, i18n.T("Type here to test your keyboard"))
    tbox = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_set_margins(tbox, 10, 10, 10, 10)
    call gtk.box_pack_start(tbox, test, True, True, 0)
    call gtk.box_pack_start(g["box"], tbox, False, False, 0)

    bottom = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_set_margins(bottom, 0, 0, 16, 0)
    differs = ui_kb["own"] and (ui_kb["layouts"] != ui_kb["system"][0] or ui_kb["options"] != ui_kb["system"][1])
    call gtk.box_pack_start(bottom, button(i18n.T("Apply to All Users and the Login Screen"), "system", None, differs), False, False, 0)
    if ui_kb["own"]:
        call gtk.box_pack_end(bottom, button(i18n.T("Use System Layouts"), "use-system", None, True), False, False, 0)
    end
    call gtk.box_pack_start(page, bottom, False, False, 0)
    if ui_kb["status"] != "":
        call gtk.box_pack_start(page, ui.label(ui_kb["status"], ""), False, False, 8)
    end
end

function build_shortcuts(page):
    keys = effective_keys()
    for section in CATALOG:
        g = ui.group(page, i18n.T(section[0]))
        for item in section[1]:
            accels = accels_for(keys, item[1])
            text = ", ".join([format_accel(a) for a in accels])
            if text == "":
                text = i18n.T("Off")
            end
            tools = gtk.box_new(gtk.HORIZONTAL, 6)
            shown = ui.label(text, "accel")
            call gtk.box_pack_start(tools, shown, False, False, 6)
            call gtk.box_pack_start(tools, button(i18n.T("Change…"), "change", item, True), False, False, 0)
            call gtk.box_pack_start(tools, button(i18n.T("Restore"), "restore", item[1], not is_default(item[1])), False, False, 0)
            call ui.row(g, i18n.T(item[0]), "", tools)
        end
    end
    note = ui.label(i18n.T("Press the new shortcut. Esc cancels, Backspace turns the shortcut off."), "hint")
    call gtk.widget_set_margins(note, 4, 0, 8, 0)
    call gtk.box_pack_start(page, note, False, False, 0)
end

function fill_wayland():
    ui_kb["buttons"] = {}
    for name in ["layouts", "shortcuts"]:
        page = P["tabs"][name]
        call clear(page)
        if name == "layouts":
            call build_layouts(page)
        else:
            call build_shortcuts(page)
        end
        call gtk.widget_show_all(page)
    end
end

function on_switch_changed(combo):
    choice = SWITCH_OPTIONS[gtk.combo_box_get_active(combo)][0]
    if choice != kb.switch_of(ui_kb["options"]):
        ui_kb["options"] = kb.with_switch(ui_kb["options"], choice)
        call save_user_keyboard()
    end
    return 0
end

function on_button(b):
    if not (b in ui_kb["buttons"]):
        return 0
    end
    action = ui_kb["buttons"][b][0]
    data = ui_kb["buttons"][b][1]
    ui_kb["status"] = ""
    if action == "up" or action == "down":
        j = data - 1 if action == "up" else data + 1
        item = ui_kb["layouts"][data]
        ui_kb["layouts"][data] = ui_kb["layouts"][j]
        ui_kb["layouts"][j] = item
        call save_user_keyboard()
    elif action == "remove":
        call ui_kb["layouts"].pop(data)
        call save_user_keyboard()
    elif action == "add":
        call add_dialog()
    elif action == "system":
        call apply_system()
    elif action == "use-system":
        call cfg.save({"xkb_layout": None, "xkb_variant": None, "xkb_options": None}, {})
        call load_keyboard()
        call luxwm_reload()
        call fill_wayland()
    elif action == "change":
        call capture_dialog(data)
    elif action == "restore":
        call restore(data)
        call fill_wayland()
    end
    return 0
end

# Pridani rozlozeni: hledani v katalogu (nazev, kod)
function add_dialog():
    dialog = gtk.dialog_new()
    call gtk.window_set_title(dialog, i18n.T("Add Layout"))
    call gtk.window_set_transient_for(dialog, P["window"])
    call gtk.window_set_modal(dialog, True)
    call gtk.window_set_default_size(dialog, 420, 460)
    call gtk.dialog_add_button(dialog, i18n.T("Cancel"), 0)
    area = gtk.dialog_get_content_area(dialog)
    call gtk.box_set_spacing(area, 8)
    call gtk.container_set_border_width(area, 12)
    search = gtk.entry_new()
    call gtk.entry_set_placeholder_text(search, i18n.T("Type to search"))
    call gtk.box_pack_start(area, search, False, False, 0)
    scroll = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(scroll, gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
    list_box = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.container_add(scroll, list_box)
    call gtk.box_pack_start(area, scroll, True, True, 0)
    used = [k[0] + ":" + k[1] for k in ui_kb["layouts"]]
    rows = []
    for item in catalog():
        if (item[0][0] + ":" + item[0][1]) in used:
            continue
        end
        b = gtk.button_new(describe(item[0]) + "   " + kb.short(item[0]))
        call gtk.button_set_relief(b, gtk.RELIEF_NONE)
        call gtk.label_set_xalign(gtk.bin_get_child(b), 0)
        call lglib.connect_data(b, "clicked", 0, on_pick, item[0])
        call gtk.box_pack_start(list_box, b, False, False, 0)
        rows.append([b, (describe(item[0]) + " " + item[1] + " " + item[0][0] + " " + item[0][1]).lower()])
    end
    ui_kb["rows"] = rows
    ui_kb["dialog"] = dialog
    ui_kb["search"] = search
    call gtk.connect(search, "changed", on_search)
    call gtk.widget_show_all(dialog)
    call gtk.dialog_run(dialog)
    call gtk.widget_destroy(dialog)
    ui_kb["dialog"] = 0
end

function on_search(entry):
    q = gtk.entry_get_text(entry).strip().lower()
    for item in ui_kb["rows"]:
        if q == "" or item[1].find(q) >= 0:
            call gtk.widget_show(item[0])
        else:
            call gtk.widget_hide(item[0])
        end
    end
    return 0
end

function on_pick(key, b):
    if len(ui_kb["layouts"]) < MAX_LAYOUTS:
        ui_kb["layouts"].append(key)
        # druhe rozlozeni bez prepinani by neslo zapnout z klavesnice
        if len(ui_kb["layouts"]) == 2 and kb.switch_of(ui_kb["options"]) == "":
            ui_kb["options"] = kb.with_switch(ui_kb["options"], DEFAULT_SWITCH)
        end
        call save_user_keyboard()
    end
    if ui_kb["dialog"] != 0:
        call gtk.dialog_response(ui_kb["dialog"], 1)
    end
    return 0
end

# Nova zkratka: dialog chyta klavesy; luxwm mezitim zkratky vypne, jinak by napr. Super+Q zavrelo okno
function capture_dialog(item):
    dialog = gtk.dialog_new()
    call gtk.window_set_title(dialog, i18n.T(item[0]))
    call gtk.window_set_transient_for(dialog, P["window"])
    call gtk.window_set_modal(dialog, True)
    call gtk.dialog_add_button(dialog, i18n.T("Cancel"), 0)
    area = gtk.dialog_get_content_area(dialog)
    call gtk.container_set_border_width(area, 18)
    note = ui.label(i18n.T("Press the new shortcut. Esc cancels, Backspace turns the shortcut off."), "")
    call gtk.label_set_max_width_chars(note, 56)
    call gtk.box_pack_start(area, note, False, False, 0)
    ui_kb["capture"] = {"item": item, "note": note, "dialog": dialog}
    call gtk.connect(dialog, "key-press-event", on_capture_key)
    call wm.request({"cmd": "suspend_shortcuts", "on": True}, None)
    call gtk.widget_show_all(dialog)
    call gtk.dialog_run(dialog)
    call wm.request({"cmd": "suspend_shortcuts", "on": False}, None)
    call gtk.widget_destroy(dialog)
    ui_kb["capture"] = None
    call fill_wayland()
end

function on_capture_key(event, dialog):
    cap = ui_kb["capture"]
    if cap == None:
        return False
    end
    name = gtk.event_key_name(event)
    state = gtk.event_key_state(event)
    if name == "Escape" and state & (gtk.CONTROL_MASK | gtk.SHIFT_MASK | gtk.MOD1_MASK | gtk.SUPER_MASK) == 0:
        call gtk.dialog_response(dialog, 0)
        return True
    end
    if name == "BackSpace" and state & (gtk.CONTROL_MASK | gtk.MOD1_MASK | gtk.SUPER_MASK) == 0:
        call assign(cap["item"][1], "")
        call gtk.dialog_response(dialog, 1)
        return True
    end
    accel = ""
    if state & gtk.CONTROL_MASK:
        accel += "<Primary>"
    end
    if state & gtk.SHIFT_MASK:
        accel += "<Shift>"
    end
    if state & gtk.MOD1_MASK:
        accel += "<Alt>"
    end
    if state & gtk.SUPER_MASK:
        accel += "<Super>"
    end
    accel = cfg.normalize(accel + name)
    if accel == "" or not accel_allowed(accel):
        return True
    end
    owner = effective_keys().get(accel, "")
    if owner != "" and owner != cap["item"][1]:
        call gtk.label_set_text(cap["note"], format_accel(accel) + ": " + i18n.T("This shortcut is used by another action. Press it again to use it here."))
        if cap.get("confirm", "") != accel:
            cap["confirm"] = accel
            return True
        end
    end
    call assign(cap["item"][1], accel)
    call gtk.dialog_response(dialog, 1)
    return True
end

# ---- karty -----------------------------------------------------------------------------------------

# Obsah karty az pri prvnim zobrazeni (na X11 cte karta Zkratky desitky hodnot xfconf)
function open_tab(name):
    if not P["built"].get(name, False):
        P["built"][name] = True
        box = P["tabs"][name]
        if P["wayland"]:
            call fill_wayland()
        elif name == "layouts":
            call x11.layouts_build(box, P["window"])
        else:
            call x11.shortcuts_build(box, P["window"])
        end
        call gtk.widget_show_all(box)
    end
    call gtk.stack_set_visible_child_name(P["stack"], name)
end

# Prepinac karet; stavet az mimo signal (prvni karta se zobrazi uz pri gtk_widget_show_all okna)
function on_tab(pspec, unused):
    name = gtk.stack_get_visible_child_name(P["stack"])
    if name != "" and not P["built"].get(name, False):
        call glib.idle_add_data(open_later, name)
    end
    return 0
end

function open_later(name):
    if gtk.stack_get_visible_child_name(P["stack"]) == name:
        call open_tab(name)
    end
    return False
end

function build_tabs(page):
    stack = gtk.stack_new(False)
    call gtk.stack_set_transition_duration(stack, 0)
    P["stack"] = stack
    for tab in [["layouts", "Layouts"], ["shortcuts", "Shortcuts"]]:
        box = ui.page_box()
        P["tabs"][tab[0]] = box
        unsafe:
            call __lsl_qbe_call4(__lsl_symbol("gtk_stack_add_titled"), glib.ptr(stack), glib.ptr(box), glib.cstr(tab[0]),
                                 glib.cstr(i18n.T(tab[1])))
        end
    end
    unsafe:
        switcher = __lsl_qbe_call0(__lsl_symbol("gtk_stack_switcher_new"))
        call __lsl_qbe_call2(__lsl_symbol("gtk_stack_switcher_set_stack"), switcher, glib.ptr(stack))
    end
    call gtk.widget_set_halign(switcher, gtk.ALIGN_CENTER)
    call gtk.widget_add_class(switcher, "keyboard-tabs")
    call gtk.box_pack_start(page, switcher, False, False, 0)
    call gtk.box_pack_start(page, stack, False, False, 0)
    call gtk.connect(stack, "notify::visible-child-name", on_tab)
end

# ---- hooky stranky ---------------------------------------------------------------------------------

function build(host):
    P["window"] = host["window"]
    P["wayland"] = host["wayland"]
    P["built"] = {}
    if P["css"] == 0:
        P["css"] = gtk.css_load(CSS)
    end
    if P["wayland"]:
        # zkratky z X11 relace, pokud je jeste nikdo neprevedl (session je jinak prevede pri startu)
        call cfg.import_xfce()
        call load_keyboard()
    end
    page = ui.page_box()
    call build_repeat(page)
    call build_tabs(page)
    return page
end

function show(host):
    if "--shortcuts" in host["args"]:
        call open_tab("shortcuts")
    elif len(P["built"]) == 0 or len(host["args"]) > 0:
        call open_tab("layouts")
    end
    if not P["wayland"] and P["built"].get("layouts", False):
        call x11.layouts_show()
    end
    return 0
end

# Odchod ze stranky nebo zavreni okna: na X11 vratit nepouzite rozlozeni v relaci
function leave(host):
    if not P["wayland"] and P["built"].get("layouts", False):
        call x11.layouts_leave()
    end
    return 0
end

function cli(args):
    if "--migrate-switch" in args:
        if kb.migrate_default_switch("", "", ""):
            print "==> Keyboard layouts now switch with both Shift keys (from the next login)."
        end
        return 0
    end
    if "--import-shortcuts" in args:
        count = cfg.import_xfce()
        print "imported " + String(count)
        if count > 0:
            call wm.connect(None)
            call luxwm_reload()
        end
        return 0
    end
    return None
end

# Testy: vlastni prikazy, na X11 ostatni prikazy karte, ktera je videt
function test(command, rest):
    tab = gtk.stack_get_visible_child_name(P["stack"])
    if command == "tab":
        call open_tab(rest)
    elif command == "switcher":
        # jako klik v prepinaci karet: jen viditelna karta, obsah postavi on_tab
        call gtk.stack_set_visible_child_name(P["stack"], rest)
    elif command == "close":
        call gtk.window_close(P["window"])
    elif command == "repeat-state":
        call sys.out("repeat " + json.encode({"rate": P["repeat"][0], "delay": P["repeat"][1], "tab": tab}) + "\n")
    elif P["wayland"]:
        if command == "page-state":
            call sys.out("state " + json.encode({"layouts": ui_kb["layouts"], "options": ui_kb["options"], "own": ui_kb["own"]}) + "\n")
        elif command == "layout-search" and ui_kb["dialog"] != 0:
            call gtk.entry_set_text(ui_kb["search"], rest)
        else:
            return False
        end
    else:
        if command == "page-state":
            command = "state"
        elif command == "layout-search":
            command = "search"
        end
        if tab == "shortcuts":
            call x11.on_shortcuts_test(command, rest)
        else:
            call x11.on_layouts_test(command, rest)
        end
    end
    return True
end
