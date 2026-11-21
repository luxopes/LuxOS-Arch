# LuxOS - okna Klavesnice v relaci X11 (drive bin/luxos-keyboard a bin/luxos-shortcuts v Pythonu): spousti je
# luxos-keyboard-settings, kdyz nebezi Wayland.
#
#   layouts_main()    Rozlozeni klavesnice: seznam rozlozeni (prvni = vychozi, nejvyse 4), prepinani zkratkou
#                     a "Pouzit pro vsechny uzivatele a prihlasovaci obrazovku" pres localectl (systemd-localed,
#                     opravneni overi polkit). Zmeny se hned zkusi v bezici relaci (setxkbmap); bez pouziti se
#                     pri zavreni okna vrati puvodni stav. Uzivateli se zaroven vypne vlastni rozlozeni Xfce
#                     (keyboard-layout /Default/XkbDisable = true), aby se ridil systemem.
#   shortcuts_main()  Klavesove zkratky: prehled, zmena (Esc zrusi, Backspace vypne), vlastni zkratky, samotna
#                     klavesa Super a Alt+Tab po aplikacich; zapis pres xfconf (luxos_shortcuts_model), takze je
#                     xfsettingsd (prikazy) a xfwm4 (okna) hned pouziji.
#
# Testy (LUXOS_TEST_CONTROL=1, luxos_testctl): state, layout up|down|remove N, add-layout ROZLOZENI:VARIANTA,
# pick ROZLOZENI:VARIANTA (radek otevreneho dialogu), apply, close, change ID, key MODIFIKATORY KLAVESA
# (stisk v dialogu zkratky), set ID ZKRATKA|off, row ID, super on|off, group on|off, custom-dialog, ...
load env, json
load luxos_glib, glib as glib
load luxos_glib as lglib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_settings_ui as ui
load luxos_testctl as testctl
load luxos_sys as sys
load luxos_apps as apps
load luxos_keyboard_model as kb
load luxos_shortcuts_model as ls

KEYBOARD_CSS = ".group { border-radius: 12px; border: 1px solid alpha(currentColor, 0.12); background-color: alpha(currentColor, 0.04); }\n.group-title { font-weight: 700; font-size: 13px; margin: 14px 4px 6px; }\n.row { padding: 8px 14px; }\n.row-sep { border-top: 1px solid alpha(currentColor, 0.08); }\n.hint { font-size: 11px; opacity: 0.6; }\n.badge { font-size: 10px; font-weight: 700; padding: 1px 7px; border-radius: 8px; color: #ffffff; background-color: #3d7bff; }\n.flat-icon { padding: 2px; min-width: 24px; min-height: 24px; }\n"
SHORTCUTS_CSS = ".group { border-radius: 12px; border: 1px solid alpha(currentColor, 0.12); background-color: alpha(currentColor, 0.04); }\n.group-title { font-weight: 700; font-size: 13px; margin: 14px 4px 6px; }\n.row { padding: 8px 10px 8px 14px; }\n.row-sep { border-top: 1px solid alpha(currentColor, 0.08); }\n.hint { font-size: 11px; opacity: 0.6; }\n.keycap { padding: 3px 10px; border-radius: 7px; border: 1px solid alpha(currentColor, 0.18); background-image: none; background-color: alpha(currentColor, 0.07); box-shadow: none; font-weight: 600; min-height: 0; }\n.keycap:hover { background-color: alpha(currentColor, 0.13); }\n.keycap.off { font-weight: 400; opacity: 0.55; }\n.keycap.fixed { opacity: 0.8; }\n.icon-btn { padding: 2px; min-height: 0; min-width: 0; }\n.header-btn { padding: 4px; min-width: 28px; min-height: 28px; border-radius: 8px; background-image: none; border: none; box-shadow: none; background-color: transparent; }\n.header-btn:hover { background-color: alpha(currentColor, 0.08); }\n.header-btn:active, .header-btn:checked { background-color: alpha(currentColor, 0.14); }\n.capture-keys { font-size: 22px; font-weight: 700; margin: 14px 0 6px; }\n.capture-box { border-radius: 12px; border: 2px dashed alpha(@theme_selected_bg_color, 0.7); background-color: alpha(@theme_selected_bg_color, 0.07); padding: 6px 18px; }\n"
XFCE_KEYBOARD = "/usr/bin/xfce4-keyboard-settings"
ICON_BUTTON = 4         # GTK_ICON_SIZE_BUTTON
ICON_MENU = 1
RELIEF_NONE = 2
RESPONSE_OK = -5
RESPONSE_CANCEL = -6
SECTION_HINTS = {"custom": "Your own shortcuts that open an app or run a command.",
                 "other": "Standard Xfce shortcuts kept for compatibility."}

T = i18n.T
buttons = {}            # tlacitko -> [akce, data]

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

function hint_label(value, chars):
    l = ui.label(value, "hint")
    if chars > 0:
        call gtk.label_set_max_width_chars(l, chars)
    end
    return l
end

function button(caption, action, data):
    b = gtk.button_new(caption)
    buttons[b] = [action, data]
    call gtk.connect(b, "clicked", on_button)
    return b
end

function icon_button(icon, tip, action, data, sensitive, css):
    b = gtk.button_new_from_icon_name(icon, ICON_BUTTON if css == "flat-icon" else ICON_MENU)
    call gtk.button_set_relief(b, RELIEF_NONE)
    call gtk.widget_add_class(b, css)
    call gtk.widget_set_tooltip(b, tip)
    call gtk.widget_set_sensitive(b, sensitive)
    buttons[b] = [action, data]
    call gtk.connect(b, "clicked", on_button)
    return b
end

function clear(box):
    for child in gtk.container_get_children(box):
        call gtk.widget_destroy(child)
    end
end

# Spusteni v nove relaci (jako Popen(start_new_session=True)); chybejici program nevadi
function launch(argv):
    call glib.spawn_quiet(argv)
end

# Synchronni prikaz se stdout i stderr; [kod, vystup]
function run(argv):
    program = glib.find_program_in_path(argv[0])
    if program == "":
        return [1, argv[0] + ": not found"]
    end
    result = None
    safe:
        result = process_capture(program, argv[1:])
    end
    if result == None:
        return [1, ""]
    end
    return [result[0], result[1]]
end

function process_capture(program, rest):
    output = capture(program, rest)
    return [capture_status(), (output + capture_stderr()).strip()]
end

function window_titlebar(window):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_window_get_titlebar"), ptr(window))
    end
end

function scrolled_page(window, top):
    scroll = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(scroll, 2, 1)
    page = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_margins(page, 22, 22, top, 22)
    call gtk.container_add(scroll, page)
    call gtk.container_add(window, scroll)
    return [scroll, page]
end

function message(parent, kind, text, secondary, ok_label, destructive):
    dlg = gtk.message_dialog_new(parent, kind, gtk.BUTTONS_NONE if ok_label != "" else gtk.BUTTONS_OK, text)
    if secondary != "":
        call gtk.object_set_string(dlg, "secondary-text", secondary)
    end
    if ok_label != "":
        call gtk.dialog_add_button(dlg, T("Cancel"), RESPONSE_CANCEL)
        b = gtk.dialog_add_button(dlg, ok_label, RESPONSE_OK)
        call gtk.widget_add_class(b, "destructive-action" if destructive else "suggested-action")
        call gtk.dialog_set_default_response(dlg, RESPONSE_OK)
    end
    r = gtk.dialog_run(dlg)
    call gtk.widget_destroy(dlg)
    return r == RESPONSE_OK
end

function ask(parent, text, secondary, ok_label, destructive):
    return message(parent, gtk.MESSAGE_QUESTION, text, secondary, ok_label, destructive)
end

function warn(parent, text):
    call message(parent, gtk.MESSAGE_WARNING, text, "", "", False)
end

# ======== Rozlozeni klavesnice ======================================================================

K = {"window": 0, "catalog": [], "system": None, "layouts": [], "options": [], "override": False, "session": None,
     "applied": False, "busy": False, "group": None, "switch": 0, "note": 0, "apply": 0, "spinner": 0, "status": 0,
     "dialog": None, "quiet": False}

function tr(value):
    return T(value)
end

# True, kdyz si uzivatel v Xfce nastavil vlastni rozlozeni (pak system prepisuje)
function user_override():
    r = run(["xfconf-query", "-c", "keyboard-layout", "-p", "/Default/XkbDisable"])
    return r[0] == 0 and r[1].strip().lower() == "false"
end

# Rozlozeni bezici relace (setxkbmap -query) - pro navrat, kdyz se zmeny nepouziji
function session_state():
    r = run(["setxkbmap", "-query"])
    if r[0] != 0:
        return None
    end
    vals = {}
    for line in r[1].split("\n"):
        cut = line.find(":")
        if cut > 0:
            vals[line[:cut].strip()] = line[cut + 1:].strip()
        end
    end
    cfg = kb.from_strings(vals.get("layout", ""), vals.get("variant", ""), vals.get("options", ""), "")
    if len(cfg["layouts"]) == 0:
        return None
    end
    return cfg
end

function layouts_main():
    call glib.set_prgname("luxos-keyboard")
    call gtk.init()
    call gtk.css_load(KEYBOARD_CSS)
    K["catalog"] = kb.catalog("")
    K["system"] = kb.read_system("", "")
    K["layouts"] = K["system"]["layouts"].copy()
    K["options"] = K["system"]["options"].copy()
    K["override"] = user_override()
    K["session"] = session_state()
    ui.state["hint_chars"] = 46
    window = ui.window(T("Keyboard Layouts"), "preferences-desktop-keyboard", 560, -1, 0, 0)
    K["window"] = window
    call gtk.window_set_wmclass(window, "luxos-keyboard", "luxos-keyboard")
    parts = scrolled_page(window, 6)
    scroll = parts[0]
    page = parts[1]
    # okno podle obsahu (drive 600 px s prazdnou plochou dole), nejvys na obrazovku
    call gtk.scrolled_window_set_propagate_natural_height(scroll, True)
    call gtk.scrolled_window_set_max_content_height(scroll, ui.max_content_height())
    call gtk.widget_set_size_request(window, 360, 260)

    K["group"] = ui.group(page, T("Layouts"))
    call gtk.widget_set_name(K["group"]["box"], "layouts")
    hint = hint_label(T("The first layout is the default. Switch between them with the shortcut below or by clicking the flag in the menu bar."), 60)
    call gtk.widget_set_margins(hint, 4, 0, 6, 0)
    call gtk.box_pack_start(page, hint, False, False, 0)

    g = ui.group(page, T("Switching"))
    combo = gtk.combo_box_text_new()
    for item in kb.SWITCH_OPTIONS:
        call gtk.combo_box_text_append(combo, item[0] if item[0] != "" else "none", T(item[1]))
    end
    current = kb.switch_of(K["options"])
    if current != "" and not (current in [o[0] for o in kb.SWITCH_OPTIONS]):
        # jina volba z localectl - nabidnout ji, at se neztrati
        call gtk.combo_box_text_append(combo, current, current)
    end
    call ui.combo_set_active_id(combo, current if current != "" else "none")
    call gtk.connect(combo, "changed", on_switch_changed)
    K["switch"] = combo
    call ui.row(g, T("Switch layouts with"), "", combo)
    test = gtk.entry_new()
    call gtk.entry_set_placeholder_text(test, T("Type here to test your keyboard"))
    call gtk.widget_set_hexpand(test, True)
    tbox = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_set_margins(tbox, 10, 10, 10, 10)
    call gtk.box_pack_start(tbox, test, True, True, 0)
    call gtk.box_pack_start(g["box"], tbox, False, False, 0)

    note = hint_label("", 60)
    call gtk.widget_set_margins(note, 0, 0, 12, 0)
    call gtk.widget_set_no_show_all(note, True)
    K["note"] = note
    call gtk.box_pack_start(page, note, False, False, 0)

    bottom = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_set_margins(bottom, 0, 0, 16, 0)
    apply = button(T("Apply to All Users and the Login Screen"), "apply", None)
    call gtk.widget_add_class(apply, "suggested-action")
    K["apply"] = apply
    call gtk.box_pack_start(bottom, apply, False, False, 0)
    K["spinner"] = gtk.spinner_new()
    call gtk.box_pack_start(bottom, K["spinner"], False, False, 0)
    if exists(XFCE_KEYBOARD):
        more = button(T("More Keyboard Settings…"), "more", None)
        call gtk.widget_set_tooltip(more, T("Key repeat and other keyboard settings"))
        call gtk.box_pack_end(bottom, more, False, False, 0)
    end
    call gtk.box_pack_start(page, bottom, False, False, 0)
    status = ui.label("", "")
    call gtk.label_set_max_width_chars(status, 60)
    call gtk.widget_set_margins(status, 0, 0, 8, 0)
    K["status"] = status
    call gtk.box_pack_start(page, status, False, False, 0)

    call gtk.connect(window, "delete-event", on_layouts_close)
    call fill()
    call gtk.widget_show_all(window)
    call update()
    call testctl.start(on_layouts_test)
    call gtk.main()
end

function fill():
    g = K["group"]
    call clear(g["box"])
    g["rows"] = 0
    n = len(K["layouts"])
    for i in range(n):
        key = K["layouts"][i]
        tools = gtk.box_new(gtk.HORIZONTAL, 4)
        if i == 0:
            badge = gtk.label_new(T("Default"))
            call gtk.widget_add_class(badge, "badge")
            call gtk.box_pack_start(tools, badge, False, False, 6)
        end
        call gtk.box_pack_start(tools, icon_button("go-up-symbolic", T("Move up"), "up", i, i > 0, "flat-icon"), False, False, 0)
        call gtk.box_pack_start(tools, icon_button("go-down-symbolic", T("Move down"), "down", i, i < n - 1, "flat-icon"), False, False, 0)
        call gtk.box_pack_start(tools, icon_button("list-remove-symbolic", T("Remove"), "remove", i, n > 1, "flat-icon"), False, False, 0)
        call ui.row(g, kb.describe(key, K["catalog"], tr), kb.short(key), tools)
    end
    add = button(T("Add Layout…"), "add", None)
    call gtk.widget_set_sensitive(add, n < kb.MAX_LAYOUTS)
    if n >= kb.MAX_LAYOUTS:
        call gtk.widget_set_tooltip(add, i18n.TF("At most %d layouts are possible.", [String(kb.MAX_LAYOUTS)]))
    end
    call ui.row(g, "", "", add)
    call gtk.widget_show_all(g["box"])
    call update()
end

function move(i, d):
    j = i + d
    if j >= 0 and j < len(K["layouts"]):
        item = K["layouts"][i]
        K["layouts"][i] = K["layouts"][j]
        K["layouts"][j] = item
        call changed(True)
    end
end

function remove_layout(i):
    if len(K["layouts"]) > 1:
        call K["layouts"].pop(i)
        call changed(True)
    end
end

function add_layout(key):
    if key == None or key in K["layouts"] or len(K["layouts"]) >= kb.MAX_LAYOUTS:
        return 0
    end
    K["layouts"].append(key)
    # druhe rozlozeni bez prepinani by neslo zapnout klavesnici - nabidnout obe klavesy Shift
    if len(K["layouts"]) == 2 and kb.switch_of(K["options"]) == "":
        K["options"] = kb.with_switch(K["options"], kb.DEFAULT_SWITCH)
        K["quiet"] = True
        call ui.combo_set_active_id(K["switch"], kb.DEFAULT_SWITCH)
        K["quiet"] = False
    end
    call changed(True)
end

function on_switch_changed(combo):
    if K["quiet"]:
        return 0
    end
    sel = ui.combo_active_id(combo)
    K["options"] = kb.with_switch(K["options"], "" if sel == "none" else sel)
    call changed(False)
    return 0
end

function changed(refill):
    call gtk.label_set_text(K["status"], "")
    call preview(K["layouts"], K["options"])
    if refill:
        call fill()
    else:
        call update()
    end
end

function dirty():
    return K["layouts"] != K["system"]["layouts"] or K["options"] != K["system"]["options"]
end

function update():
    if K["override"]:
        call gtk.label_set_text(K["note"], T("Your account uses its own keyboard layouts from Xfce settings. Applying switches it back to the layouts set here."))
        call gtk.widget_show(K["note"])
    else:
        call gtk.widget_hide(K["note"])
    end
    call gtk.widget_set_sensitive(K["apply"], not K["busy"] and (dirty() or K["override"]))
end

# Vyzkouseni v bezici relaci (jen tato relace, nic se neuklada)
function preview(layouts, options):
    if kb.validate(layouts, options, "") == "":
        call launch(kb.setxkbmap_cmd(layouts, options))
    end
end

function on_apply():
    layouts = K["layouts"].copy()
    options = K["options"].copy()
    model = K["system"]["model"]
    error = kb.validate(layouts, options, model)
    if error != "":
        call gtk.label_set_text(K["status"], error)
        return 0
    end
    K["busy"] = True
    call update()
    call gtk.spinner_set(K["spinner"], True)
    call gtk.label_set_text(K["status"], T("Saving…"))
    # localectl ceka na overeni (polkit): asynchronne, stderr ("Access denied") do vystupu
    argv = ["sh", "-c", "exec \"$@\" 2>&1", "sh"] + kb.localectl_cmd(layouts, options, model)
    if lglib.spawn_capture(argv, on_applied, [layouts, options, model]) == 0:
        call applied_done([layouts, options, model], 1, "localectl")
    end
end

function on_applied(saved, output, status):
    if status == 0:
        call run(["xfconf-query", "-c", "keyboard-layout", "-p", "/Default/XkbDisable", "-n", "-t", "bool", "-s", "true"])
        call run(kb.setxkbmap_cmd(saved[0], saved[1]))
    end
    call applied_done(saved, status, output)
    return 0
end

function applied_done(saved, status, output):
    K["busy"] = False
    call gtk.spinner_set(K["spinner"], False)
    low = output.lower()
    if status == 0:
        K["system"] = {"layouts": saved[0], "model": saved[2], "options": saved[1]}
        K["override"] = False
        K["applied"] = True
        call gtk.label_set_text(K["status"], T("Saved for all users and the login screen."))
    elif low.find("denied") >= 0 or low.find("not authorized") >= 0 or low.find("dismissed") >= 0:
        call gtk.label_set_text(K["status"], T("Not saved: administrator authentication was cancelled."))
    else:
        lines = [line for line in output.strip().split("\n") if line != ""]
        last = lines[len(lines) - 1] if len(lines) > 0 else "?"
        call gtk.label_set_text(K["status"], i18n.TF("Could not save the keyboard layouts: %s", [last]))
    end
    call update()
end

# Nepouzite zmeny: vratit relaci do posledniho pouziteho stavu (nebo stavu pred otevrenim okna)
function revert_session():
    back = K["system"] if K["applied"] else K["session"]
    if dirty() and back != None and kb.validate(back["layouts"], back["options"], "") == "":
        call run(kb.setxkbmap_cmd(back["layouts"], back["options"]))
    end
end

function on_layouts_close(event, window):
    call revert_session()
    call gtk.main_quit()
    return False
end

# Pridani rozlozeni: hledani v katalogu (nazev, popis, kod); vybrany radek -> Pridat
function add_dialog():
    dlg = gtk.dialog_new()
    call gtk.window_set_title(dlg, T("Add Layout"))
    call gtk.window_set_transient_for(dlg, K["window"])
    call gtk.window_set_modal(dlg, True)
    call gtk.window_set_default_size(dlg, 420, 460)
    call gtk.dialog_add_button(dlg, T("Cancel"), RESPONSE_CANCEL)
    ok = gtk.dialog_add_button(dlg, T("Add"), RESPONSE_OK)
    call gtk.widget_add_class(ok, "suggested-action")
    call gtk.widget_set_sensitive(ok, False)
    call gtk.dialog_set_default_response(dlg, RESPONSE_OK)
    area = gtk.dialog_get_content_area(dlg)
    call gtk.box_set_spacing(area, 8)
    call gtk.container_set_border_width(area, 12)
    entry = gtk.search_entry_new()
    call gtk.entry_set_placeholder_text(entry, T("Type to search"))
    call gtk.box_pack_start(area, entry, False, False, 0)
    lb = gtk.list_box_new()
    rows = []
    for item in K["catalog"]:
        key = item[0]
        if key in K["layouts"]:
            continue
        end
        name = kb.describe(key, K["catalog"], tr)
        box = gtk.box_new(gtk.HORIZONTAL, 8)
        call gtk.widget_set_margins(box, 6, 6, 6, 6)
        l = gtk.label_new(name)
        call gtk.label_set_xalign(l, 0)
        call gtk.box_pack_start(box, l, True, True, 0)
        code = gtk.label_new(kb.short(key))
        call gtk.widget_add_class(code, "hint")
        call gtk.box_pack_end(box, code, False, False, 0)
        call gtk.list_box_insert(lb, box, -1)
        rows.append({"key": key, "hay": (name + " " + item[1] + " " + key[0] + " " + key[1]).lower(), "row": gtk.widget_get_parent(box)})
    end
    sw = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(sw, 2, 1)
    call gtk.container_add(sw, lb)
    call gtk.widget_set_vexpand(sw, True)
    call gtk.box_pack_start(area, sw, True, True, 0)
    K["dialog"] = {"dialog": dlg, "entry": entry, "list": lb, "rows": rows, "ok": ok}
    call gtk.connect(entry, "search-changed", on_add_search)
    call gtk.connect(entry, "activate", on_add_activate)
    call gtk.connect(lb, "row-selected", on_add_selected)
    call gtk.connect(lb, "row-activated", on_add_row_activated)
    call gtk.widget_show_all(dlg)
    resp = gtk.dialog_run(dlg)
    key = None
    if resp == RESPONSE_OK:
        key = add_chosen()
    end
    call gtk.widget_destroy(dlg)
    K["dialog"] = None
    call add_layout(key)
end

function add_visible(item):
    q = gtk.entry_get_text(K["dialog"]["entry"]).strip().lower()
    return q == "" or item["hay"].find(q) >= 0
end

function on_add_search(entry):
    for item in K["dialog"]["rows"]:
        if add_visible(item):
            call gtk.widget_show(item["row"])
        else:
            call gtk.widget_hide(item["row"])
        end
    end
    return 0
end

function on_add_activate(entry):
    for item in K["dialog"]["rows"]:
        if add_visible(item):
            call select_row(item["row"])
            call gtk.dialog_response(K["dialog"]["dialog"], RESPONSE_OK)
            return 0
        end
    end
    return 0
end

function on_add_selected(row, lb):
    call gtk.widget_set_sensitive(K["dialog"]["ok"], row != 0)
    return 0
end

function on_add_row_activated(row, lb):
    call gtk.dialog_response(K["dialog"]["dialog"], RESPONSE_OK)
    return 0
end

function select_row(row):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("gtk_list_box_select_row"), ptr(K["dialog"]["list"]), ptr(row))
    end
end

function selected_row(lb):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_list_box_get_selected_row"), ptr(lb))
    end
end

function add_chosen():
    row = selected_row(K["dialog"]["list"])
    for item in K["dialog"]["rows"]:
        if item["row"] == row:
            return item["key"]
        end
    end
    return None
end

function key_of(spec):
    cut = spec.find(":")
    if cut < 0:
        return [spec, ""]
    end
    return [spec[:cut], spec[cut + 1:]]
end

function on_layouts_test(command, rest):
    if command == "state":
        dlg = K["dialog"]
        visible = []
        hay = []
        if dlg != None:
            visible = [item["key"][0] + ":" + item["key"][1] for item in dlg["rows"] if add_visible(item)]
            hay = [item["hay"] for item in dlg["rows"] if add_visible(item)]
        end
        call sys.out("state " + json.encode({"layouts": K["layouts"], "options": K["options"], "dirty": dirty(),
            "busy": K["busy"], "applied": K["applied"], "status": gtk.label_get_text(K["status"]),
            "apply": gtk.widget_get_sensitive(K["apply"]), "note": gtk.widget_get_visible(K["note"]),
            "switch": ui.combo_active_id(K["switch"]), "dialog": dlg != None, "visible": visible, "hay": hay,
            "system": K["system"]}) + "\n")
    elif command == "layout":
        parts = rest.split(" ")
        i = Int(parts[1])
        if parts[0] == "up":
            call move(i, -1)
        elif parts[0] == "down":
            call move(i, 1)
        else:
            call remove_layout(i)
        end
    elif command == "add-layout":
        call add_layout(key_of(rest))
    elif command == "pick":
        key = key_of(rest)
        for item in K["dialog"]["rows"]:
            if item["key"] == key:
                call select_row(item["row"])
            end
        end
    elif command == "search":
        call gtk.entry_set_text(K["dialog"]["entry"], rest)
    elif command == "chosen":
        chosen = add_chosen()
        call sys.out("chosen " + json.encode(chosen) + "\n")
    elif command == "switch-id":
        call ui.combo_set_active_id(K["switch"], rest)
    elif command == "close":
        call revert_session()
        call gtk.widget_destroy(K["window"])
        call gtk.main_quit()
    end
end

# ======== Klavesove zkratky ========================================================================

S = {"window": 0, "scroll": 0, "page": 0, "model": None, "rows": {}, "super": 0, "group": 0, "capture": None,
     "custom": None, "chooser": None}

function shortcuts_main():
    call glib.set_prgname("luxos-shortcuts")
    call gtk.init()
    call gtk.css_load(SHORTCUTS_CSS)
    ui.state["hint_chars"] = 0
    window = ui.window(T("Keyboard Shortcuts"), "shortcuts", 620, 720, 480, 420)
    S["window"] = window
    call gtk.window_set_wmclass(window, "luxos-shortcuts", "luxos-shortcuts")
    bar = window_titlebar(window)
    add = gtk.button_new_from_icon_name("list-add-symbolic", ICON_BUTTON)
    call gtk.widget_set_tooltip(add, T("Add Shortcut…"))
    buttons[add] = ["add-custom", None]
    call gtk.connect(add, "clicked", on_button)
    menu = gtk.button_new_from_icon_name("open-menu-symbolic", ICON_BUTTON)
    buttons[menu] = ["menu", None]
    call gtk.connect(menu, "clicked", on_button)
    # + a ... vpravo jako ploche ikony horni listy
    for b in [add, menu]:
        call gtk.widget_add_class(b, "header-btn")
        call gtk.widget_set_valign(b, gtk.ALIGN_CENTER)
    end
    call gtk.header_bar_pack_end(bar, menu)
    call gtk.header_bar_pack_end(bar, add)
    scroll = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(scroll, 2, 1)
    call gtk.container_add(window, scroll)
    S["scroll"] = scroll
    S["model"] = ls.new_model(None, "")
    call build()
    call gtk.connect(window, "delete-event", on_shortcuts_close)
    call gtk.widget_show_all(window)
    call testctl.start(on_shortcuts_test)
    call gtk.main()
end

function on_shortcuts_close(event, window):
    call gtk.main_quit()
    return False
end

function scroll_adjustment():
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_scrolled_window_get_vadjustment"), ptr(S["scroll"]))
    end
end

function restore_scroll(value):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("gtk_adjustment_set_value"), ptr(scroll_adjustment()), Float(value))
    end
    return False
end

function section_title(key):
    for s in ls.SECTIONS:
        if s[0] == key:
            return T(s[1])
        end
    end
    return key
end

function spacer():
    box = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_set_size_request(box, 24, -1)
    return box
end

function keycap(caption, action, data, off, tip):
    b = gtk.button_new(caption)
    call gtk.widget_add_class(b, "keycap")
    if off:
        call gtk.widget_add_class(b, "off")
    end
    if action != "":
        buttons[b] = [action, data]
        call gtk.connect(b, "clicked", on_button)
        call gtk.widget_set_tooltip(b, tip if tip != "" else T("Click to change the shortcut"))
    else:
        call gtk.widget_add_class(b, "fixed")
        call gtk.widget_set_can_focus(b, False)
        if tip != "":
            call gtk.widget_set_tooltip(b, tip)
        end
    end
    return b
end

function group_box(page, title, hint):
    call gtk.box_pack_start(page, ui.label(title, "group-title"), False, False, 0)
    if hint != "":
        h = ui.label(hint, "hint")
        call gtk.widget_set_margins(h, 4, 0, 0, 6)
        call gtk.box_pack_start(page, h, False, False, 0)
    end
    g = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_add_class(g, "group")
    call gtk.box_pack_start(page, g, False, False, 0)
    return {"box": g, "rows": 0}
end

# Radek: nazev (zkraceny), napoveda (prikaz zkraceny uprostred, nebo zalomene vysvetleni) a prvky vpravo
function shortcut_row(g, title, widgets, hint, wrap):
    box = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_add_class(box, "row")
    if g["rows"] > 0:
        call gtk.widget_add_class(box, "row-sep")
    end
    texts = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_valign(texts, gtk.ALIGN_CENTER)
    t = gtk.label_new(title)
    call gtk.label_set_xalign(t, 0)
    call gtk.label_set_ellipsize(t, 3)
    call gtk.box_pack_start(texts, t, False, False, 0)
    if hint != "":
        h = gtk.label_new(hint)
        call gtk.label_set_xalign(h, 0)
        if wrap:
            call gtk.label_set_line_wrap(h, True)
            call gtk.label_set_max_width_chars(h, 60)
        else:
            call gtk.label_set_ellipsize(h, 2)
        end
        call gtk.widget_add_class(h, "hint")
        call gtk.box_pack_start(texts, h, False, False, 0)
    end
    call gtk.box_pack_start(box, texts, True, True, 0)
    i = len(widgets) - 1
    while i >= 0:
        call gtk.widget_set_valign(widgets[i], gtk.ALIGN_CENTER)
        call gtk.box_pack_end(box, widgets[i], False, False, 0)
        i -= 1
    end
    call gtk.box_pack_start(g["box"], box, False, False, 0)
    g["rows"] = g["rows"] + 1
    return box
end

function build():
    old = 0.0
    if S["page"] != 0:
        old = ui.scroll_position(S["scroll"])
        # stranka je ve viewportu, ktery pridal GtkScrolledWindow
        call gtk.widget_destroy(gtk.bin_get_child(S["scroll"]))
    end
    for b in buttons.keys():
        if not (buttons[b][0] in ["add-custom", "menu"]):
            call buttons.pop(b)
        end
    end
    m = S["model"]
    page = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_margins(page, 22, 22, 8, 22)
    S["page"] = page
    call gtk.container_add(S["scroll"], page)
    S["rows"] = {}
    if not m["available"]:
        msg = ui.label(T("Shortcuts could not be read from the Xfce settings service. Changes will not be saved."), "hint")
        call gtk.box_pack_start(page, msg, False, False, 4)
    end
    all = ls.actions(m)
    for sec in ls.SECTIONS:
        key = sec[0]
        items = [a for a in all if a["section"] == key]
        if key == "custom":
            call build_custom(page, items)
            continue
        end
        if len(items) == 0:
            continue
        end
        g = group_box(page, section_title(key), T(SECTION_HINTS[key]) if key in SECTION_HINTS else "")
        if key == "apps":
            call add_layout_row(g)
        end
        for a in items:
            call add_action_row(g, a)
            if a["id"] == "launchpad":
                call add_super_row(g)
            end
            if a["id"] == "cycle-app-reverse":
                call add_group_apps_row(g)
            end
        end
    end
    bottom = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_set_margins(bottom, 0, 0, 18, 0)
    call gtk.box_pack_end(bottom, button(T("Restore All Defaults…"), "restore-all", None), False, False, 0)
    call gtk.box_pack_start(page, bottom, False, False, 0)
    call gtk.widget_show_all(page)
    # zachovat pozici po prestaveni
    call lglib.idle_add_data(restore_scroll, old)
end

function add_action_row(g, a):
    m = S["model"]
    accels = ls.accels_for(m, a)
    caption = T("Off")
    if len(accels) > 0:
        caption = ", ".join([ls.format_accel(x) for x in accels])
    end
    widgets = [keycap(caption, "change", a["id"], len(accels) == 0, "")]
    if not ls.is_default(m, a):
        widgets.append(icon_button("edit-undo-symbolic", T("Restore Default"), "restore", a["id"], True, "icon-btn"))
    else:
        widgets.append(spacer())
    end
    hint = ""
    if a["section"] == "other" and a["values"][0] != a["label"]:
        hint = a["values"][0]
    end
    S["rows"][a["id"]] = shortcut_row(g, a["label"], widgets, hint, False)
end

function add_layout_row(g):
    toggle = ls.layout_switch("")
    if toggle == "":
        return 0
    end
    # meni se v okne Rozlozeni klavesnice (XkbOptions grp:...), pokud je nainstalovane
    app = glib.find_program_in_path("luxos-keyboard")
    cap = keycap(toggle, "launch" if app != "" else "", [app], False, T("Set together with the keyboard layouts."))
    S["rows"]["layout"] = shortcut_row(g, T("Switch keyboard layout"), [cap, spacer()], "", False)
end

function add_super_row(g):
    # tuknuti na samotnou Super (luxos-menubar); Super+klavesa zustava zkratkou
    sw = ui.switch(ls.super_tap_enabled(""), on_super_tap, 0)
    S["super"] = sw
    S["rows"]["super-tap"] = shortcut_row(g, T("Super key alone opens Launchpad"), [sw, spacer()], T("Tap and release Super without another key."), False)
end

function add_group_apps_row(g):
    # Alt+Tab po aplikacich (xfwm4 /general/cycle_group_apps); Dolu nebo ` ukaze okna aplikace
    sw = ui.switch(ls.group_apps_enabled(), on_group_apps, 0)
    S["group"] = sw
    S["rows"]["group-apps"] = shortcut_row(g, T("Group windows by app in Alt+Tab"), [sw, spacer()], T("Each app is shown once. While holding Alt, press Down or ` to see the windows of the selected app."), True)
end

function on_super_tap(unused, on):
    if not ls.set_super_tap(on, ""):
        call warn(S["window"], T("The setting could not be saved."))
    end
end

function on_group_apps(unused, on):
    if not ls.set_group_apps(on):
        call warn(S["window"], T("The setting could not be saved."))
    end
end

function build_custom(page, items):
    g = group_box(page, section_title("custom"), T(SECTION_HINTS["custom"]))
    for a in items:
        norm = a["id"][7:]
        widgets = [keycap(ls.format_accel(norm), "change", a["id"], False, ""),
                   icon_button("document-edit-symbolic", T("Edit…"), "edit-custom", a["id"], True, "icon-btn"),
                   icon_button("user-trash-symbolic", T("Delete"), "delete-custom", a["id"], True, "icon-btn")]
        hint = a["values"][0] if a["label"] != a["values"][0] else ""
        S["rows"][a["id"]] = shortcut_row(g, a["label"], widgets, hint, False)
    end
    add = button(T("Add Shortcut…"), "add-custom", None)
    call gtk.widget_set_halign(add, gtk.ALIGN_START)
    box = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_set_margins(box, 10, 8, 8, 8)
    call gtk.widget_add_class(box, "row")
    if g["rows"] > 0:
        call gtk.widget_add_class(box, "row-sep")
    end
    call gtk.box_pack_start(box, add, False, False, 0)
    call gtk.box_pack_start(g["box"], box, False, False, 0)
end

# ---- zachyceni zkratky ----

# Zakladni klavesa stisku (bez Shift: 4, ne dolar) podle rozlozeni klavesnice
function base_keyval(event):
    unsafe:
        keyval = __lsl_qbe_load32(ptr(event) + 28)
        code = __lsl_qbe_load32(ptr(event) + 48) & 65535
        group = __lsl_qbe_load32(ptr(event) + 50) & 255
        keymap = __lsl_qbe_call1(__lsl_symbol("gdk_keymap_get_for_display"), __lsl_qbe_call0(__lsl_symbol("gdk_display_get_default")))
        cell = __lsl_byte_zeros(8)
        if __lsl_qbe_call8(__lsl_symbol("gdk_keymap_translate_keyboard_state"), keymap, ptr(code), 0, ptr(group), lglib.data(cell), 0, 0, 0) != 0:
            got = __lsl_qbe_load32(lglib.data(cell))
            if got != 0:
                keyval = got
            end
        end
        return keyval
    end
end

function keyval_name(keyval):
    unsafe:
        lower = __lsl_qbe_call1(__lsl_symbol("gdk_keyval_to_lower"), ptr(keyval))
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("gdk_keyval_name"), lower))
    end
end

function accel_from_keyval(keyval, state):
    name = keyval_name(keyval)
    if name == "":
        return ""
    end
    if name == "ISO_Left_Tab":
        name = "Tab"
    end
    mods = []
    if state & gtk.CONTROL_MASK:
        mods.append("ctrl")
    end
    if state & gtk.SHIFT_MASK:
        mods.append("shift")
    end
    if state & gtk.MOD1_MASK:
        mods.append("alt")
    end
    # SUPER_MASK | MOD4_MASK
    if state & (gtk.SUPER_MASK | 64):
        mods.append("super")
    end
    return ls.make_accel(mods, name)
end

function show_mods(state, pressed, released):
    cap = S["capture"]
    mods = []
    for item in [[gtk.CONTROL_MASK, "Ctrl", "Control"], [gtk.SUPER_MASK | 64, "Super", "Super"], [gtk.MOD1_MASK, "Alt", "Alt"], [gtk.SHIFT_MASK, "Shift", "Shift"]]:
        held = (state & item[0]) != 0 or pressed.startswith(item[2]) or (item[2] == "Super" and pressed.startswith("Meta"))
        if released.startswith(item[2]) or (item[2] == "Super" and released.startswith("Meta")):
            held = False
        end
        if held:
            mods.append(item[1])
        end
    end
    call gtk.label_set_text(cap["keys"], " + ".join(mods + ["…"]) if len(mods) > 0 else "…")
end

# "Stisknete novou zkratku": Esc zrusi, Backspace vypne. Klavesnice je zachycena, aby stisk nespustil
# existujici globalni zkratku. Vysledek ["set", zkratka] / ["off", None] / None = zruseno.
function capture_shortcut(parent, title, allow_disable):
    dlg = gtk.dialog_new()
    call gtk.window_set_title(dlg, T("Keyboard Shortcuts"))
    call gtk.window_set_transient_for(dlg, parent)
    call gtk.window_set_modal(dlg, True)
    call gtk.window_set_resizable(dlg, False)
    # GTK_WIN_POS_CENTER_ON_PARENT
    call gtk.window_set_position(dlg, 4)
    call gtk.dialog_add_button(dlg, T("Cancel"), RESPONSE_CANCEL)
    box = gtk.dialog_get_content_area(dlg)
    call gtk.container_set_border_width(box, 18)
    call gtk.box_set_spacing(box, 4)
    head = gtk.label_new("")
    call gtk.label_set_markup(head, "<b>" + glib.markup_escape(i18n.TF("Press the new shortcut for “%s”", [title])) + "</b>")
    call gtk.label_set_line_wrap(head, True)
    call gtk.label_set_max_width_chars(head, 40)
    call gtk.box_pack_start(box, head, False, False, 0)
    frame = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_set_halign(frame, gtk.ALIGN_CENTER)
    call gtk.widget_set_size_request(frame, 260, -1)
    call gtk.widget_add_class(frame, "capture-box")
    keys = gtk.label_new("…")
    call gtk.widget_set_hexpand(keys, True)
    call gtk.widget_add_class(keys, "capture-keys")
    call gtk.box_pack_start(frame, keys, False, False, 0)
    call gtk.box_pack_start(box, frame, False, False, 8)
    hint = gtk.label_new(T("Esc cancels, Backspace turns the shortcut off.") if allow_disable else T("Esc cancels."))
    call gtk.label_set_line_wrap(hint, True)
    call gtk.label_set_max_width_chars(hint, 44)
    call gtk.widget_add_class(hint, "hint")
    call gtk.box_pack_start(box, hint, False, False, 0)
    S["capture"] = {"dialog": dlg, "keys": keys, "hint": hint, "allow": allow_disable, "result": None, "grabbed": False}
    call gtk.connect(dlg, "key-press-event", on_capture_key)
    call gtk.connect(dlg, "key-release-event", on_capture_release)
    call gtk.connect(dlg, "map-event", on_capture_map)
    call gtk.widget_show_all(dlg)
    call gtk.dialog_run(dlg)
    result = S["capture"]["result"]
    if S["capture"]["grabbed"]:
        call gtk.seat_ungrab()
    end
    call gtk.widget_destroy(dlg)
    S["capture"] = None
    return result
end

function on_capture_map(event, dlg):
    if S["capture"] != None:
        S["capture"]["grabbed"] = gtk.seat_grab_keyboard(dlg)
    end
    return False
end

function on_capture_release(event, dlg):
    if S["capture"] != None:
        call show_mods(gtk.event_key_state(event), "", gtk.event_key_name(event))
    end
    return True
end

function on_capture_key(event, dlg):
    cap = S["capture"]
    if cap == None:
        return False
    end
    name = gtk.event_key_name(event)
    state = gtk.event_key_state(event)
    plain = state & (gtk.CONTROL_MASK | gtk.MOD1_MASK | gtk.SUPER_MASK | 64 | gtk.SHIFT_MASK) == 0
    if ls.is_modifier_key(name) or name.startswith("ISO_Level"):
        call show_mods(state, name, "")
        return True
    end
    if plain and name == "Escape":
        call gtk.dialog_response(dlg, RESPONSE_CANCEL)
        return True
    end
    if plain and name == "BackSpace" and cap["allow"]:
        cap["result"] = ["off", None]
        call gtk.dialog_response(dlg, RESPONSE_OK)
        return True
    end
    return offer(accel_from_keyval(base_keyval(event), state))
end

# Prijme zkratku, pokud je pouzitelna; jinak upozorni a ceka dal
function offer(accel):
    cap = S["capture"]
    if accel == "":
        return True
    end
    call gtk.label_set_text(cap["keys"], ls.format_accel(accel))
    if not ls.accel_allowed(accel):
        call gtk.label_set_text(cap["hint"], T("Use at least one of Ctrl, Alt or Super."))
        return True
    end
    cap["result"] = ["set", accel]
    call gtk.dialog_response(cap["dialog"], RESPONSE_OK)
    return True
end

# ---- zmeny ----

function action_of(aid):
    return ls.find_action(S["model"], aid)
end

function change(a):
    res = capture_shortcut(S["window"], a["label"], True)
    if res != None:
        call apply_change(a, res)
    end
end

# Pouzije vysledek zachyceni; True, kdyz se zapsalo
function apply_change(a, res):
    m = S["model"]
    ok = False
    if res[0] == "off":
        ok = ls.disable(m, a)
        if a["custom"]:
            call ls.forget_name(m, a["id"][7:])
        end
    else:
        norm = ls.normalize(res[1])
        clash = ls.conflict(m, a, norm)
        if clash != None and not confirm_replace(norm, clash):
            return False
        end
        if a["custom"]:
            old = a["id"][7:]
            name = a["label"] if old in m["names"] else a["values"][0]
            ok = ls.save_custom(m, name, a["values"][0], norm, old)
        else:
            accels = ls.accels_for(m, a)
            ok = ls.assign(m, a, norm, accels[0] if len(accels) > 0 else "")
        end
    end
    call after_write(ok)
    return ok
end

function confirm_replace(norm, clash):
    return ask(S["window"], i18n.TF("“%s” is already used by “%s”.", [ls.format_accel(norm), clash]), T("Replace it? The other action will lose this shortcut."), T("Replace"), False)
end

function restore_action(a):
    call after_write(ls.restore(S["model"], a))
end

function restore_all():
    if not ask(S["window"], T("Restore all shortcuts to their defaults?"), T("Your custom shortcuts are kept unless their keys are needed by a default shortcut."), T("Restore Defaults"), True):
        return 0
    end
    call after_write(ls.restore_all(S["model"]))
end

function edit_custom(a):
    norm = a["id"][7:]
    name = ""
    if norm in S["model"]["names"]:
        name = S["model"]["names"][norm]["name"]
    end
    call custom_dialog(name, a["values"][0], norm)
end

function delete_custom(a):
    if not ask(S["window"], i18n.TF("Delete the shortcut “%s”?", [a["label"]]), "", T("Delete"), True):
        return 0
    end
    call after_write(ls.delete_custom(S["model"], a["id"][7:]))
end

function after_write(ok):
    call ls.reload(S["model"])
    call build()
    if not ok:
        call warn(S["window"], T("The shortcut could not be saved."))
    end
end

function feedback_menu():
    menu = gtk.menu_new()
    item = gtk.menu_item_new(T("Send Feedback…"))
    call lglib.connect_data(item, "activate", 0, on_menu_launch, ["luxos-feedback"])
    call gtk.menu_append(menu, item)
    call gtk.widget_show_all(menu)
    call gtk.menu_popup_at_pointer(menu)
end

function on_menu_launch(argv, item):
    call launch(argv)
    return 0
end

# ---- vlastni zkratka: nazev, prikaz (nebo aplikace) a zkratka ----

function custom_dialog(name, command, accel):
    dlg = gtk.dialog_new()
    call gtk.window_set_title(dlg, T("Edit Shortcut") if accel != "" else T("Add Shortcut"))
    call gtk.window_set_transient_for(dlg, S["window"])
    call gtk.window_set_modal(dlg, True)
    call gtk.window_set_resizable(dlg, False)
    call gtk.dialog_add_button(dlg, T("Cancel"), RESPONSE_CANCEL)
    save = gtk.dialog_add_button(dlg, T("Save"), RESPONSE_OK)
    call gtk.widget_add_class(save, "suggested-action")
    box = gtk.dialog_get_content_area(dlg)
    call gtk.container_set_border_width(box, 16)
    grid = gtk.grid_new()
    call gtk.grid_set_row_spacing(grid, 10)
    call gtk.grid_set_column_spacing(grid, 12)
    call gtk.box_pack_start(box, grid, False, False, 0)
    name_entry = gtk.entry_new()
    call gtk.entry_set_text(name_entry, name)
    call gtk.entry_set_width_chars(name_entry, 32)
    call gtk.entry_set_placeholder_text(name_entry, T("e.g. Open my notes"))
    cmd_entry = gtk.entry_new()
    call gtk.entry_set_text(cmd_entry, command)
    call gtk.widget_set_hexpand(cmd_entry, True)
    call gtk.entry_set_placeholder_text(cmd_entry, T("Command, e.g. firefox"))
    choose = button(T("Choose App…"), "choose-app", None)
    cmd_box = gtk.box_new(gtk.HORIZONTAL, 6)
    call gtk.box_pack_start(cmd_box, cmd_entry, True, True, 0)
    call gtk.box_pack_start(cmd_box, choose, False, False, 0)
    key = button("", "record", None)
    call gtk.widget_add_class(key, "keycap")
    call gtk.widget_set_halign(key, gtk.ALIGN_START)
    items = [[T("Name"), name_entry], [T("Command"), cmd_box], [T("Shortcut"), key]]
    for i in range(len(items)):
        l = gtk.label_new(items[i][0])
        call gtk.label_set_xalign(l, 1)
        call gtk.grid_attach(grid, l, 0, i, 1, 1)
        call gtk.grid_attach(grid, items[i][1], 1, i, 1, 1)
    end
    note = gtk.label_new("")
    call gtk.label_set_xalign(note, 0)
    call gtk.label_set_line_wrap(note, True)
    call gtk.label_set_max_width_chars(note, 50)
    call gtk.widget_set_margins(note, 0, 0, 10, 0)
    call gtk.widget_add_class(note, "hint")
    call gtk.box_pack_start(box, note, False, False, 0)
    S["custom"] = {"dialog": dlg, "name": name_entry, "command": cmd_entry, "key": key, "note": note, "save": save,
                   "old": accel, "accel": accel, "clash": None}
    call gtk.connect(name_entry, "changed", on_custom_changed)
    call gtk.connect(cmd_entry, "changed", on_custom_changed)
    call custom_update()
    call gtk.widget_show_all(dlg)
    resp = gtk.dialog_run(dlg)
    vals = custom_values()
    call gtk.widget_destroy(dlg)
    S["custom"] = None
    if resp == RESPONSE_OK:
        call after_write(ls.save_custom(S["model"], vals[0], vals[1], vals[2], accel))
    end
end

function custom_values():
    c = S["custom"]
    return [gtk.entry_get_text(c["name"]).strip(), gtk.entry_get_text(c["command"]).strip(), c["accel"]]
end

function on_custom_changed(entry):
    call custom_update()
    return 0
end

function custom_update():
    c = S["custom"]
    vals = custom_values()
    call gtk.button_set_label(c["key"], ls.format_accel(c["accel"]) if c["accel"] != "" else T("Record Shortcut…"))
    clash = None
    if c["accel"] != "" and c["accel"] != c["old"]:
        probe = ls.action("x", "custom", "", "cmd", [vals[1] if vals[1] != "" else chr(1)], False)
        clash = ls.conflict(S["model"], probe, c["accel"])
    end
    c["clash"] = clash
    call gtk.label_set_text(c["note"], i18n.TF("Already used by “%s” - it will be replaced.", [clash]) if clash != None else "")
    call gtk.widget_set_sensitive(c["save"], vals[0] != "" and vals[1] != "" and c["accel"] != "")
end

function custom_record():
    c = S["custom"]
    title = gtk.entry_get_text(c["name"]).strip()
    res = capture_shortcut(c["dialog"], title if title != "" else T("New Shortcut"), False)
    if res != None and res[0] == "set" and S["custom"] != None:
        S["custom"]["accel"] = ls.normalize(res[1])
        call custom_update()
    end
end

# Aplikace z .desktop souboru: [nazev, prikaz, ikona] serazene podle nazvu
function installed_apps():
    found = {}
    seen = set()
    for info in apps.all_infos():
        unsafe:
            show = __lsl_qbe_icall1(__lsl_symbol("g_app_info_should_show"), ptr(info)) != 0
            cmd = glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_app_info_get_commandline"), ptr(info)))
            name = glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_app_info_get_display_name"), ptr(info)))
            terminal = __lsl_qbe_icall2(__lsl_symbol("g_desktop_app_info_get_boolean"), ptr(info), cstr("Terminal")) != 0
            icon = __lsl_qbe_call1(__lsl_symbol("g_app_info_get_icon"), ptr(info))
        end
        if not show or cmd == "" or name == "":
            continue
        end
        command = ls.strip_field_codes(cmd)
        if terminal:
            command = "luxos-terminal -x " + command
        end
        if (name + "\n" + command) in seen:
            continue
        end
        seen.add(name + "\n" + command)
        found[name.lower() + "\n" + String(len(found))] = [name, command, icon]
    end
    return [found[k] for k in sorted(found.keys())]
end

# Vyber aplikace pro vlastni zkratku (s hledanim); [nazev, prikaz] nebo None
function app_chooser(parent):
    dlg = gtk.dialog_new()
    call gtk.window_set_title(dlg, T("Choose App"))
    call gtk.window_set_transient_for(dlg, parent)
    call gtk.window_set_modal(dlg, True)
    call gtk.window_set_default_size(dlg, 380, 460)
    call gtk.dialog_add_button(dlg, T("Cancel"), RESPONSE_CANCEL)
    ok = gtk.dialog_add_button(dlg, T("Choose"), RESPONSE_OK)
    call gtk.widget_add_class(ok, "suggested-action")
    call gtk.widget_set_sensitive(ok, False)
    box = gtk.dialog_get_content_area(dlg)
    call gtk.container_set_border_width(box, 10)
    call gtk.box_set_spacing(box, 8)
    search = gtk.search_entry_new()
    call gtk.entry_set_placeholder_text(search, T("Search apps"))
    call gtk.box_pack_start(box, search, False, False, 0)
    lb = gtk.list_box_new()
    rows = []
    for app in installed_apps():
        hb = gtk.box_new(gtk.HORIZONTAL, 10)
        call gtk.widget_set_margins(hb, 6, 6, 6, 6)
        img = 0
        unsafe:
            if app[2] != 0:
                # GTK_ICON_SIZE_LARGE_TOOLBAR 3
                img = __lsl_qbe_call2(__lsl_symbol("gtk_image_new_from_gicon"), ptr(app[2]), 3)
            end
        end
        if img == 0:
            img = gtk.image_new_from_icon_name("application-x-executable", 3)
        end
        call gtk.box_pack_start(hb, img, False, False, 0)
        l = gtk.label_new(app[0])
        call gtk.label_set_xalign(l, 0)
        call gtk.label_set_ellipsize(l, 3)
        call gtk.box_pack_start(hb, l, True, True, 0)
        call gtk.list_box_insert(lb, hb, -1)
        rows.append({"app": [app[0], app[1]], "row": gtk.widget_get_parent(hb), "hay": [app[0].lower(), app[1].lower()]})
    end
    sw = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(sw, 2, 1)
    call gtk.container_add(sw, lb)
    call gtk.widget_set_vexpand(sw, True)
    call gtk.box_pack_start(box, sw, True, True, 0)
    S["chooser"] = {"dialog": dlg, "search": search, "list": lb, "rows": rows, "ok": ok}
    call gtk.connect(search, "search-changed", on_chooser_search)
    call gtk.connect(lb, "row-selected", on_chooser_selected)
    call gtk.connect(lb, "row-activated", on_chooser_activated)
    call gtk.widget_show_all(dlg)
    resp = gtk.dialog_run(dlg)
    chosen = chooser_chosen() if resp == RESPONSE_OK else None
    call gtk.widget_destroy(dlg)
    S["chooser"] = None
    return chosen
end

function chooser_chosen():
    row = selected_row(S["chooser"]["list"])
    for item in S["chooser"]["rows"]:
        if item["row"] == row:
            return item["app"]
        end
    end
    return None
end

function on_chooser_search(entry):
    q = gtk.entry_get_text(entry).strip().lower()
    for item in S["chooser"]["rows"]:
        if q == "" or item["hay"][0].find(q) >= 0 or item["hay"][1].find(q) >= 0:
            call gtk.widget_show(item["row"])
        else:
            call gtk.widget_hide(item["row"])
        end
    end
    return 0
end

function on_chooser_selected(row, lb):
    call gtk.widget_set_sensitive(S["chooser"]["ok"], row != 0)
    return 0
end

function on_chooser_activated(row, lb):
    call gtk.dialog_response(S["chooser"]["dialog"], RESPONSE_OK)
    return 0
end

function choose_app():
    chosen = app_chooser(S["custom"]["dialog"])
    if chosen != None and S["custom"] != None:
        c = S["custom"]
        if gtk.entry_get_text(c["name"]).strip() == "":
            call gtk.entry_set_text(c["name"], chosen[0])
        end
        call gtk.entry_set_text(c["command"], chosen[1])
    end
end

# ---- udalosti ----

function on_button(b):
    if not (b in buttons):
        return 0
    end
    action = buttons[b][0]
    data = buttons[b][1]
    if action == "up":
        call move(data, -1)
    elif action == "down":
        call move(data, 1)
    elif action == "remove":
        call remove_layout(data)
    elif action == "add":
        call add_dialog()
    elif action == "apply":
        call on_apply()
    elif action == "more":
        call launch([XFCE_KEYBOARD])
    elif action == "change":
        a = action_of(data)
        if a != None:
            call change(a)
        end
    elif action == "restore":
        a = action_of(data)
        if a != None:
            call restore_action(a)
        end
    elif action == "restore-all":
        call restore_all()
    elif action == "add-custom":
        call custom_dialog("", "", "")
    elif action == "edit-custom":
        a = action_of(data)
        if a != None:
            call edit_custom(a)
        end
    elif action == "delete-custom":
        a = action_of(data)
        if a != None:
            call delete_custom(a)
        end
    elif action == "record":
        call custom_record()
    elif action == "choose-app":
        call choose_app()
    elif action == "launch":
        call launch(data)
    elif action == "menu":
        call feedback_menu()
    end
    return 0
end

# ---- testy ----

# Stisk klavesy jako udalost GDK (keyval, modifikatory, hardwarovy kod z rozlozeni) do dialogu zkratky
function send_key(mods, name):
    cap = S["capture"]
    if cap == None:
        return 0
    end
    state = 0
    for m in mods.split("+"):
        if m == "ctrl":
            state = state | gtk.CONTROL_MASK
        elif m == "shift":
            state = state | gtk.SHIFT_MASK
        elif m == "alt":
            state = state | gtk.MOD1_MASK
        elif m == "super":
            state = state | gtk.SUPER_MASK
        end
    end
    unsafe:
        keyval = __lsl_qbe_call1(__lsl_symbol("gdk_keyval_from_name"), cstr(name))
        keymap = __lsl_qbe_call1(__lsl_symbol("gdk_keymap_get_for_display"), __lsl_qbe_call0(__lsl_symbol("gdk_display_get_default")))
        cells = __lsl_byte_zeros(16)
        code = 0
        if __lsl_qbe_call4(__lsl_symbol("gdk_keymap_get_entries_for_keyval"), keymap, keyval, lglib.data(cells), lglib.data(cells) + 8) != 0:
            keys = __lsl_qbe_load64(lglib.data(cells))
            code = __lsl_qbe_load32(keys)
            call __lsl_qbe_call1(__lsl_symbol("g_free"), keys)
        end
        # GDK_KEY_PRESS 8
        ev = __lsl_qbe_call1(__lsl_symbol("gdk_event_new"), 8)
        win = __lsl_qbe_call1(__lsl_symbol("gtk_widget_get_window"), ptr(cap["dialog"]))
        call __lsl_qbe_store64(ev + 8, __lsl_qbe_call1(__lsl_symbol("g_object_ref"), win))
        call __lsl_qbe_store32(ev + 24, ptr(state))
        call __lsl_qbe_store32(ev + 28, keyval)
        call __lsl_qbe_store32(ev + 48, code)
        call __lsl_qbe_call2(__lsl_symbol("gtk_widget_event"), ptr(cap["dialog"]), ev)
        call __lsl_qbe_call1(__lsl_symbol("gdk_event_free"), ev)
    end
end

function rows_state():
    out = {}
    for aid in S["rows"].keys():
        out[aid] = row_texts(S["rows"][aid])
    end
    return out
end

function row_texts(widget):
    texts = []
    for w in testctl.walk(widget, []):
        if testctl.is_a(w, "label"):
            texts.append(testctl.text_of(w, "label"))
        elif testctl.is_a(w, "button"):
            if testctl.text_of(w, "button") != "":
                texts.append(testctl.text_of(w, "button"))
            end
            tip = testctl.tooltip(w)
            if tip != "":
                texts.append("tip:" + tip)
            end
        elif testctl.is_a(w, "switch"):
            texts.append("switch:" + ("on" if gtk.switch_get_active(w) else "off"))
        end
    end
    return texts
end

function on_shortcuts_test(command, rest):
    m = S["model"]
    if command == "state":
        order = []
        page_rows = []
        if S["page"] != 0:
            for w in testctl.walk(S["page"], []):
                for aid in S["rows"].keys():
                    if S["rows"][aid] == w:
                        page_rows.append(aid)
                    end
                end
            end
        end
        cap = S["capture"]
        custom = S["custom"]
        info = {"rows": rows_state(), "order": page_rows, "available": m["available"],
                "capture": None if cap == None else {"keys": gtk.label_get_text(cap["keys"]), "hint": gtk.label_get_text(cap["hint"]), "result": cap["result"]},
                "custom": None if custom == None else {"accel": custom["accel"], "note": gtk.label_get_text(custom["note"]), "save": gtk.widget_get_sensitive(custom["save"]), "values": custom_values()},
                "chooser": None if S["chooser"] == None else [item["app"] for item in S["chooser"]["rows"]],
                "customs": [[a["id"], a["label"], a["values"][0]] for a in ls.custom_actions(m)]}
        call sys.out("state " + json.encode(info) + "\n")
    elif command == "accels":
        a = action_of(rest)
        call sys.out("accels " + json.encode(ls.accels_for(m, a) if a != None else None) + "\n")
    elif command == "change":
        a = action_of(rest)
        if a != None:
            call change(a)
        end
    elif command == "capture":
        parts = rest.split(" ")
        res = capture_shortcut(S["window"], parts[1] if len(parts) > 1 else "Files", parts[0] == "1")
        if res != None and res[0] == "set":
            res = ["set", ls.normalize(res[1])]
        end
        call sys.out("captured " + json.encode(res) + "\n")
    elif command == "key":
        parts = rest.split(" ")
        call send_key(parts[0], parts[1])
    elif command == "set":
        # ID ZKRATKA|off: vysledek zachyceni bez dialogu (jako apply_change v testu Pythonu)
        cut = rest.find(" ")
        a = action_of(rest[:cut])
        value = rest[cut + 1:]
        ok = False
        if a != None:
            ok = apply_change(a, ["off", None] if value == "off" else ["set", value])
        end
        call sys.out("set " + json.encode(ok) + "\n")
    elif command == "super":
        call gtk.switch_set_active(S["super"], rest == "on")
    elif command == "group":
        call gtk.switch_set_active(S["group"], rest == "on")
    elif command == "custom-dialog":
        call custom_dialog("", "", "")
    elif command == "custom-accel":
        S["custom"]["accel"] = rest
        call custom_update()
    elif command == "custom-name":
        call gtk.entry_set_text(S["custom"]["name"], rest)
    elif command == "custom-command":
        call gtk.entry_set_text(S["custom"]["command"], rest)
    elif command == "save-custom":
        parts = rest.split("\t")
        ok = ls.save_custom(m, parts[0], parts[1], parts[2], "")
        call build()
        call sys.out("save-custom " + json.encode(ok) + "\n")
    elif command == "delete-custom":
        a = action_of(rest)
        if a != None:
            call delete_custom(a)
        end
    elif command == "chooser":
        call app_chooser(S["window"])
    elif command == "chooser-pick":
        rows = S["chooser"]["rows"]
        if len(rows) > 0:
            call select_row_in(S["chooser"]["list"], rows[Int(rest)]["row"])
        end
        chosen = chooser_chosen()
        call sys.out("chooser-pick " + json.encode(chosen) + "\n")
    elif command == "assign":
        parts = rest.split(" ")
        call ls.assign(m, action_of(parts[0]), parts[1], parts[2] if len(parts) > 2 else "")
    elif command == "restore-all":
        call restore_all()
    elif command == "reopen":
        call build()
    end
end

function select_row_in(lb, row):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("gtk_list_box_select_row"), ptr(lb), ptr(row))
    end
end
