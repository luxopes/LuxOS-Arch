# LuxOS - Klavesnice: rozlozeni a jejich prepinani, klavesove zkratky (/usr/lib/luxos/luxos-keyboard-settings,
# spousti ho luxos-keyboard a luxos-shortcuts). Na X11 okna Rozlozeni klavesnice a Klavesove zkratky nad
# localectl/setxkbmap a xfconf (luxos_keyboard_x11.lsl), na Waylandu (luxwm) jedno okno s kartami nize.
#
#   luxos-keyboard-settings [--shortcuts]       okno (karta Rozlozeni, s --shortcuts karta Zkratky)
#   luxos-keyboard-settings --import-shortcuts  jen jednou prevede zkratky Xfce do ~/.config/luxwm/luxwm.conf
#   luxos-keyboard-settings --migrate-switch    jednou za zivot systemu stare vychozi prepinani Alt+Shift ->
#                                               obe klavesy Shift (luxos-desktop.install, jako root)
#
# Rozlozeni: zdroj je localed (cely system, prihlaseni, konzole). Zmena v okne plati hned jen pro uzivatele
# (xkb_* v ~/.config/luxwm/luxwm.conf, luxwm je hned nacte); "Pouzit pro vsechny" ji zapise pres localectl
# (polkit) a vlastni rozlozeni uzivatele smaze. Zkratky: polozky [keys] v uzivatelskem luxwm.conf.
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
load luxos_testctl as testctl
load luxos_sys as sys

MAX_LAYOUTS = kb.MAX_LAYOUTS
XORG_CONF = kb.CONF
DEFAULT_SWITCH = kb.DEFAULT_SWITCH
SWITCH_OPTIONS = kb.SWITCH_OPTIONS
# Zkratky v okne: [nazev, hodnota luxwm]; stejne nazvy jako luxos-shortcuts (maji preklady)
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
CSS = ".group { border-radius: 12px; border: 1px solid alpha(currentColor, 0.12); background-color: alpha(currentColor, 0.04); }\n.group-title { font-weight: 700; font-size: 13px; margin: 14px 4px 6px; }\n.row { padding: 8px 14px; }\n.row-sep { border-top: 1px solid alpha(currentColor, 0.08); }\n.hint { font-size: 11px; opacity: 0.65; }\n.accel { font-weight: 600; }\n"

ui = {"window": 0, "stack": 0, "pages": {}, "buttons": {}, "catalog": [], "layouts": [], "options": [], "model": "",
      "own": False, "system": [], "status": "", "capture": None, "dialog": 0, "search": 0, "rows": []}

# ---- rozlozeni: stav ---------------------------------------------------------------------------------

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
    ui["system"] = system
    ui["model"] = system[2]
    user = cfg.user_conf()["general"]
    ui["own"] = user.get("xkb_layout", "") != ""
    if ui["own"]:
        ui["layouts"] = split_names(user["xkb_layout"], user.get("xkb_variant", ""))
    else:
        ui["layouts"] = system[0]
    end
    if "xkb_options" in user:
        ui["options"] = split_options(user["xkb_options"])
    else:
        ui["options"] = system[1]
    end
end

function switch_of(options):
    return kb.switch_of(options)
end

function with_switch(options, switch):
    return kb.with_switch(options, switch)
end

function joined(layouts, index):
    return ",".join([item[index] for item in layouts])
end

function luxwm_reload():
    call wm.request({"cmd": "reload"}, None)
end

# Zmena v okne: hned pro uzivatele (luxwm nacte xkb_* z luxwm.conf)
function save_user_keyboard():
    call cfg.save({"xkb_layout": joined(ui["layouts"], 0), "xkb_variant": joined(ui["layouts"], 1),
                   "xkb_options": ",".join(ui["options"])}, {})
    ui["own"] = True
    call luxwm_reload()
    call build()
end

function apply_system():
    argv = ["localectl", "set-x11-keymap", joined(ui["layouts"], 0), ui["model"], joined(ui["layouts"], 1),
            ",".join(ui["options"])]
    ui["status"] = i18n.T("Saving…")
    call build()
    if glib.spawn_capture(argv, on_applied, 0) == 0:
        ui["status"] = i18n.T("Could not save the keyboard layouts: %s").replace("%s", "localectl")
        call build()
    end
end

function on_applied(unused, output, status):
    if status == 0:
        # system je ted stejny: vlastni rozlozeni uzivatele uz neni potreba
        call cfg.save({"xkb_layout": None, "xkb_variant": None, "xkb_options": None}, {})
        ui["own"] = False
        ui["status"] = i18n.T("Saved for all users and the login screen.")
        call luxwm_reload()
    else:
        low = output.lower()
        if low.find("denied") >= 0 or low.find("not authorized") >= 0 or low.find("dismissed") >= 0:
            ui["status"] = i18n.T("Not saved: administrator authentication was cancelled.")
        else:
            ui["status"] = i18n.T("Could not save the keyboard layouts: %s").replace("%s", output.strip())
        end
    end
    call build()
    return 0
end

# ---- katalog rozlozeni (evdev.lst) -------------------------------------------------------------------

function catalog():
    if len(ui["catalog"]) == 0:
        ui["catalog"] = kb.catalog("")
    end
    return ui["catalog"]
end

function tr(text):
    return i18n.T(text)
end

function describe(key):
    return kb.describe(key, catalog(), tr)
end

function short(key):
    return kb.short(key)
end

# ---- zkratky ------------------------------------------------------------------------------------------

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
    rest = accel
    for pair in [["<Primary>", "Ctrl"], ["<Super>", "Super"], ["<Alt>", "Alt"], ["<Shift>", "Shift"]]:
        if rest.find(pair[0]) >= 0:
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

# ---- okno -----------------------------------------------------------------------------------------------

function label(text, css):
    l = gtk.label_new(text)
    call gtk.label_set_xalign(l, 0)
    call gtk.label_set_line_wrap(l, True)
    call gtk.label_set_max_width_chars(l, 56)
    if css != "":
        call gtk.widget_add_class(l, css)
    end
    return l
end

function group(page, title):
    call gtk.box_pack_start(page, label(title, "group-title"), False, False, 0)
    g = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_add_class(g, "group")
    call gtk.box_pack_start(page, g, False, False, 0)
    return {"box": g, "rows": 0}
end

function row(g, title, hint, widget):
    box = gtk.box_new(gtk.HORIZONTAL, 10)
    call gtk.widget_add_class(box, "row")
    if g["rows"] > 0:
        call gtk.widget_add_class(box, "row-sep")
    end
    texts = gtk.box_new(gtk.VERTICAL, 2)
    call gtk.widget_set_valign(texts, gtk.ALIGN_CENTER)
    call gtk.box_pack_start(texts, label(title, ""), False, False, 0)
    if hint != "":
        call gtk.box_pack_start(texts, label(hint, "hint"), False, False, 0)
    end
    call gtk.box_pack_start(box, texts, True, True, 0)
    if widget != 0:
        call gtk.widget_set_valign(widget, gtk.ALIGN_CENTER)
        call gtk.box_pack_end(box, widget, False, False, 0)
    end
    call gtk.box_pack_start(g["box"], box, False, False, 0)
    g["rows"] = g["rows"] + 1
    return box
end

function button(text, action, data, sensitive):
    b = gtk.button_new(text)
    ui["buttons"][b] = [action, data]
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
    n = len(ui["layouts"])
    g = group(page, i18n.T("Layouts"))
    for i in range(n):
        key = ui["layouts"][i]
        tools = gtk.box_new(gtk.HORIZONTAL, 4)
        call gtk.box_pack_start(tools, button("↑", "up", i, i > 0), False, False, 0)
        call gtk.box_pack_start(tools, button("↓", "down", i, i < n - 1), False, False, 0)
        call gtk.box_pack_start(tools, button(i18n.T("Remove"), "remove", i, n > 1), False, False, 0)
        hint = short(key)
        if i == 0:
            hint = i18n.T("Default") + " · " + hint
        end
        call row(g, describe(key), hint, tools)
    end
    call row(g, "", "", button(i18n.T("Add Layout…"), "add", None, n < MAX_LAYOUTS))
    call gtk.box_pack_start(page, label(i18n.T("The first layout is the default. Switch between them with the shortcut below or by clicking the flag in the menu bar."), "hint"), False, False, 6)

    g = group(page, i18n.T("Switching"))
    combo = gtk.combo_box_text_new()
    current = switch_of(ui["options"])
    active = 0
    for i in range(len(SWITCH_OPTIONS)):
        call gtk.combo_box_text_append(combo, String(i), i18n.T(SWITCH_OPTIONS[i][1]))
        if SWITCH_OPTIONS[i][0] == current:
            active = i
        end
    end
    call gtk.combo_box_set_active(combo, active)
    call gtk.connect(combo, "changed", on_switch_changed)
    call row(g, i18n.T("Switch layouts with"), "", combo)
    test = gtk.entry_new()
    call gtk.entry_set_placeholder_text(test, i18n.T("Type here to test your keyboard"))
    tbox = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_set_margins(tbox, 10, 10, 10, 10)
    call gtk.box_pack_start(tbox, test, True, True, 0)
    call gtk.box_pack_start(g["box"], tbox, False, False, 0)

    bottom = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_set_margins(bottom, 0, 0, 16, 0)
    differs = ui["own"] and (ui["layouts"] != ui["system"][0] or ui["options"] != ui["system"][1])
    call gtk.box_pack_start(bottom, button(i18n.T("Apply to All Users and the Login Screen"), "system", None, differs), False, False, 0)
    if ui["own"]:
        call gtk.box_pack_end(bottom, button(i18n.T("Use System Layouts"), "use-system", None, True), False, False, 0)
    end
    call gtk.box_pack_start(page, bottom, False, False, 0)
    if ui["status"] != "":
        call gtk.box_pack_start(page, label(ui["status"], ""), False, False, 8)
    end
end

function build_shortcuts(page):
    keys = effective_keys()
    for section in CATALOG:
        g = group(page, i18n.T(section[0]))
        for item in section[1]:
            accels = accels_for(keys, item[1])
            text = ", ".join([format_accel(a) for a in accels])
            if text == "":
                text = i18n.T("Off")
            end
            tools = gtk.box_new(gtk.HORIZONTAL, 6)
            shown = label(text, "accel")
            call gtk.box_pack_start(tools, shown, False, False, 6)
            call gtk.box_pack_start(tools, button(i18n.T("Change…"), "change", item, True), False, False, 0)
            call gtk.box_pack_start(tools, button(i18n.T("Restore"), "restore", item[1], not is_default(item[1])), False, False, 0)
            call row(g, i18n.T(item[0]), "", tools)
        end
    end
    call gtk.box_pack_start(page, label(i18n.T("Press the new shortcut. Esc cancels, Backspace turns the shortcut off."), "hint"), False, False, 8)
end

function build():
    ui["buttons"] = {}
    for name in ["layouts", "shortcuts"]:
        page = ui["pages"][name]
        call clear(page)
        if name == "layouts":
            call build_layouts(page)
        else:
            call build_shortcuts(page)
        end
        call gtk.widget_show_all(page)
    end
end

# ---- udalosti -------------------------------------------------------------------------------------------

function on_switch_changed(combo):
    choice = SWITCH_OPTIONS[gtk.combo_box_get_active(combo)][0]
    if choice != switch_of(ui["options"]):
        ui["options"] = with_switch(ui["options"], choice)
        call save_user_keyboard()
    end
    return 0
end

function on_button(b):
    if not (b in ui["buttons"]):
        return 0
    end
    action = ui["buttons"][b][0]
    data = ui["buttons"][b][1]
    ui["status"] = ""
    if action == "up" or action == "down":
        j = data - 1 if action == "up" else data + 1
        item = ui["layouts"][data]
        ui["layouts"][data] = ui["layouts"][j]
        ui["layouts"][j] = item
        call save_user_keyboard()
    elif action == "remove":
        call ui["layouts"].pop(data)
        call save_user_keyboard()
    elif action == "add":
        call add_dialog()
    elif action == "system":
        call apply_system()
    elif action == "use-system":
        call cfg.save({"xkb_layout": None, "xkb_variant": None, "xkb_options": None}, {})
        call load_keyboard()
        call luxwm_reload()
        call build()
    elif action == "change":
        call capture_dialog(data)
    elif action == "restore":
        call restore(data)
        call build()
    end
    return 0
end

# Pridani rozlozeni: hledani v katalogu (nazev, kod)
function add_dialog():
    dialog = gtk.dialog_new()
    call gtk.window_set_title(dialog, i18n.T("Add Layout"))
    call gtk.window_set_transient_for(dialog, ui["window"])
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
    used = [k[0] + ":" + k[1] for k in ui["layouts"]]
    rows = []
    for item in catalog():
        if (item[0][0] + ":" + item[0][1]) in used:
            continue
        end
        b = gtk.button_new(describe(item[0]) + "   " + short(item[0]))
        call gtk.button_set_relief(b, gtk.RELIEF_NONE)
        call gtk.label_set_xalign(gtk.bin_get_child(b), 0)
        call lglib.connect_data(b, "clicked", 0, on_pick, item[0])
        call gtk.box_pack_start(list_box, b, False, False, 0)
        rows.append([b, (describe(item[0]) + " " + item[1] + " " + item[0][0] + " " + item[0][1]).lower()])
    end
    ui["rows"] = rows
    ui["dialog"] = dialog
    call gtk.connect(search, "changed", on_search)
    call gtk.widget_show_all(dialog)
    call gtk.dialog_run(dialog)
    call gtk.widget_destroy(dialog)
    ui["dialog"] = 0
end

function on_search(entry):
    q = gtk.entry_get_text(entry).strip().lower()
    for item in ui["rows"]:
        if q == "" or item[1].find(q) >= 0:
            call gtk.widget_show(item[0])
        else:
            call gtk.widget_hide(item[0])
        end
    end
    return 0
end

function on_pick(key, b):
    if len(ui["layouts"]) < MAX_LAYOUTS:
        ui["layouts"].append(key)
        # druhe rozlozeni bez prepinani by neslo zapnout z klavesnice
        if len(ui["layouts"]) == 2 and switch_of(ui["options"]) == "":
            ui["options"] = with_switch(ui["options"], DEFAULT_SWITCH)
        end
        call save_user_keyboard()
    end
    if ui["dialog"] != 0:
        call gtk.dialog_response(ui["dialog"], 1)
    end
    return 0
end

# Nova zkratka: dialog chyta klavesy; luxwm mezitim zkratky vypne, jinak by napr. Super+Q zavrelo okno
function capture_dialog(item):
    dialog = gtk.dialog_new()
    call gtk.window_set_title(dialog, i18n.T(item[0]))
    call gtk.window_set_transient_for(dialog, ui["window"])
    call gtk.window_set_modal(dialog, True)
    call gtk.dialog_add_button(dialog, i18n.T("Cancel"), 0)
    area = gtk.dialog_get_content_area(dialog)
    call gtk.container_set_border_width(area, 18)
    note = label(i18n.T("Press the new shortcut. Esc cancels, Backspace turns the shortcut off."), "")
    call gtk.box_pack_start(area, note, False, False, 0)
    ui["capture"] = {"item": item, "note": note, "dialog": dialog}
    call gtk.connect(dialog, "key-press-event", on_capture_key)
    call wm.request({"cmd": "suspend_shortcuts", "on": True}, None)
    call gtk.widget_show_all(dialog)
    call gtk.dialog_run(dialog)
    call wm.request({"cmd": "suspend_shortcuts", "on": False}, None)
    call gtk.widget_destroy(dialog)
    ui["capture"] = None
    call build()
end

function on_capture_key(event, dialog):
    cap = ui["capture"]
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

# Testy (LUXOS_TEST_CONTROL=1): state = rozlozeni, volby a vlastni rozlozeni uzivatele
function on_test(command, rest):
    if command == "state":
        call sys.out("state " + json.encode({"layouts": ui["layouts"], "options": ui["options"], "own": ui["own"]}) + "\n")
    end
end

function on_delete(event, window):
    call gtk.main_quit()
    return False
end

# ---- start -------------------------------------------------------------------------------------------------

if "--migrate-switch" in args:
    if kb.migrate_default_switch("", "", ""):
        print "==> Keyboard layouts now switch with both Shift keys (from the next login)."
    end
    exit(0)
end
if "--import-shortcuts" in args:
    count = cfg.import_xfce()
    print "imported " + String(count)
    if count > 0:
        call wm.connect(None)
        call luxwm_reload()
    end
    exit(0)
end
if env.get("WAYLAND_DISPLAY", "") == "":
    if "--shortcuts" in args:
        call x11.shortcuts_main()
    else:
        call x11.layouts_main()
    end
    exit(0)
end
# app_id jako polozka .desktop, ze ktere se okno otevrelo (nazev v liste, ikona v Docku)
app_id = "luxos-shortcuts" if "--shortcuts" in args else "luxos-keyboard"
call glib.set_prgname(app_id)
call gtk.init()
call gtk.css_load(CSS)
# zkratky z X11 relace, pokud je jeste nikdo neprevedl (session je jinak prevede pri startu)
call cfg.import_xfce()
call wm.connect(None)
call load_keyboard()
window = gtk.window_new(i18n.T("Keyboard"))
ui["window"] = window
call gtk.window_set_wmclass(window, app_id, app_id)
call gtk.window_set_icon_name(window, "preferences-desktop-keyboard")
call gtk.window_set_default_size(window, 620, 640)
outer = gtk.box_new(gtk.VERTICAL, 0)
notebook = gtk.notebook_new()
for tab in ["layouts", "shortcuts"]:
    tab_scroll = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(tab_scroll, gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
    tab_page = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_margins(tab_page, 22, 22, 6, 22)
    call gtk.container_add(tab_scroll, tab_page)
    ui["pages"][tab] = tab_page
    call gtk.notebook_append_page(notebook, tab_scroll, gtk.label_new(i18n.T("Layouts" if tab == "layouts" else "Shortcuts")))
end
call gtk.box_pack_start(outer, notebook, True, True, 0)
call gtk.container_add(window, outer)
call build()
call gtk.connect(window, "delete-event", on_delete)
call gtk.widget_show_all(window)
if "--shortcuts" in args:
    call gtk.notebook_set_current_page(notebook, 1)
end
call testctl.start(on_test)
call gtk.main()
