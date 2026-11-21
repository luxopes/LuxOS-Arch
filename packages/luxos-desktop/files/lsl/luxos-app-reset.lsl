# LuxOS - Vychozi nastaveni aplikaci: aplikace s nastavenim v domovske slozce a reset jedne z nich
# (nastaveni se presune do zalohy, nic se nemaze). Logika: luxos_app_reset.lsl (drive Python).
#
#   luxos-app-reset                   okno (Nastaveni)
#   luxos-app-reset list [--json]     aplikace s nastavenim
#   luxos-app-reset reset APLIKACE [--yes] [--force]
#                                     presune nastaveni do zalohy (--force i kdyz aplikace bezi)
#   luxos-app-reset backups           zalohy
#   luxos-app-reset restore SLOZKA    vrati zalohu (soucasne nastaveni se zalohuje)
load env, json
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_sys as sys
load luxos_app_reset as core
load luxos_testctl as testctl

USAGE = [["luxos-app-reset", "window (Settings)"],
    ["luxos-app-reset list [--json]", "apps with settings in your home folder"],
    ["luxos-app-reset reset APP [--yes] [--force]", "move the app's settings to a backup (--force: even while the app is running)"],
    ["luxos-app-reset backups", "list backups"],
    ["luxos-app-reset restore FOLDER", "restore a backup (the current settings are backed up first)"]]
CSS = ".group { border-radius: 12px; border: 1px solid alpha(currentColor, 0.12); background-color: alpha(currentColor, 0.04); }\n.group-title { font-weight: 700; font-size: 13px; margin: 14px 4px 6px; }\n.row { padding: 8px 14px; }\n.row-sep { border-top: 1px solid alpha(currentColor, 0.08); }\n.hint { font-size: 11px; opacity: 0.6; }\n"

ui = {"window": 0, "search": 0, "box": 0, "status": 0, "apps": []}

# ---- prikazova radka -----------------------------------------------------------------------

function describe_paths(app):
    home = core.home_dir()
    out = []
    for item in app["paths"]:
        p = item[1]
        if p.startswith(home + "/"):
            p = "~" + p[len(home):]
        end
        out.append(p)
    end
    return out
end

function pad(value, width, right):
    gap = ""
    while len(value) + len(gap) < width:
        gap += " "
    end
    if right:
        return gap + value
    end
    return value + gap
end

function cli_list(options):
    apps = core.scan(True)
    if "--json" in options:
        rows = []
        for a in apps:
            row = a.copy()
            row["paths"] = [p[1] for p in a["paths"]]
            rows.append(row)
        end
        print json.encode(rows)
        return 0
    end
    for a in apps:
        print pad(a["label"], 28, False) + " " + pad(a["name"], 28, False) + " " + pad(core.human_size(a["size"]), 9, True) + "  " + " ".join(describe_paths(a))
    end
    return 0
end

function stdin_is_terminal():
    unsafe:
        return __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("isatty"), 0)) == 1
    end
end

function ask(question):
    if not stdin_is_terminal():
        return False
    end
    # cele slovo: "abort" nebo "absolutely not" neni souhlas
    answer = input(question + " [y/N] ").strip().lower()
    return answer == "y" or answer == "yes" or answer == "a" or answer == "ano"
end

function cli_reset(options):
    names = [a for a in options if not a.startswith("-")]
    if len(names) == 0:
        call eprint(i18n.T("Usage: luxos-app-reset reset <app>"))
        return 2
    end
    app = core.find(core.scan(False), names[0])
    if app == None:
        call eprint(i18n.TF("No settings found for %s.", [names[0]]))
        return 1
    end
    if core.is_running(app, core.running_programs()) and not ("--force" in options):
        call eprint(i18n.TF("%s is running. Quit it first.", [app["name"]]))
        return 1
    end
    print i18n.T("These folders will be moved to a backup (nothing is deleted):")
    for p in describe_paths(app):
        print "  " + p
    end
    if not ("--yes" in options) and not ask(i18n.TF("Reset the settings of %s?", [app["name"]])):
        print i18n.T("Cancelled.")
        return 1
    end
    dest = ""
    try:
        dest = core.reset(app)
    else:
        # nic nezustane napul: reset vrati presunute slozky zpet
        call eprint(i18n.T("The settings could not be moved") + ": " + core.reason(last_error()))
        return 1
    end
    print i18n.TF("Done. The previous settings are in %s", [dest])
    return 0
end

function cli_backups(options):
    for b in core.list_backups():
        print String(b["dir"]) + "  " + String(b.get("app", "")) + "  (" + String(b.get("time", "")) + ")"
    end
    return 0
end

function absolute(path):
    if path.startswith("/"):
        return core.normpath(path)
    end
    return core.normpath(cwd() + "/" + path)
end

function cli_restore(options):
    if len(options) == 0:
        call eprint(i18n.T("Usage: luxos-app-reset restore <backup folder>"))
        return 2
    end
    saved = ""
    try:
        saved = core.restore(absolute(options[0]))
    else:
        call eprint(i18n.TF("The backup could not be restored: %s", [core.reason(last_error())]))
        return 1
    end
    print i18n.T("The settings were restored.")
    if saved != "":
        print i18n.TF("The settings from before the restore are in %s", [saved])
    end
    return 0
end

# Napoveda jako luxos_i18n.print_usage: syntaxe zustava, popisy se prekladaji
function usage(to_stderr):
    width = 0
    for row in USAGE:
        width = max(width, len(row[0]) + 2)
    end
    width = min(34, width)
    lines = ["luxos-app-reset - " + i18n.T("reset apps to their default settings; nothing is deleted") + "\n"]
    for row in USAGE:
        if len(row[0]) + 2 > width:
            lines.append("  " + row[0] + "\n  " + pad("", width, False) + i18n.T(row[1]))
        else:
            lines.append("  " + pad(row[0], width, False) + i18n.T(row[1]))
        end
    end
    if to_stderr:
        call eprint("\n".join(lines))
    else:
        print "\n".join(lines)
    end
end

# ---- okno ----------------------------------------------------------------------------------

function label(value, css, chars):
    l = gtk.label_new(value)
    call gtk.label_set_xalign(l, 0)
    if css != "":
        call gtk.widget_add_class(l, css)
    end
    if chars > 0:
        call gtk.label_set_line_wrap(l, True)
        call gtk.label_set_max_width_chars(l, chars)
    end
    return l
end

function build():
    window = gtk.window_new(i18n.T("Reset App Settings"))
    ui["window"] = window
    call gtk.window_set_wmclass(window, "luxos-app-reset", "luxos-app-reset")
    call gtk.window_set_default_size(window, 640, 620)
    call gtk.window_set_icon_name(window, "preferences-system")
    outer = gtk.box_new(gtk.VERTICAL, 6)
    call gtk.widget_set_margin(outer, 18)
    call gtk.container_add(window, outer)
    intro = label(i18n.T("An app that misbehaves often works again with its default settings. Resetting moves its settings to a backup folder - nothing is deleted and you can restore them later."), "", 70)
    call gtk.box_pack_start(outer, intro, False, False, 0)
    ui["search"] = gtk.search_entry_new()
    call gtk.entry_set_placeholder_text(ui["search"], i18n.T("Search apps"))
    call gtk.widget_set_margins(ui["search"], 0, 0, 8, 0)
    call gtk.connect_data(ui["search"], "search-changed", 0, on_search, 0)
    call gtk.box_pack_start(outer, ui["search"], False, False, 0)
    scroll = gtk.scrolled_window_new()
    call gtk.widget_set_vexpand(scroll, True)
    call gtk.scrolled_window_set_policy(scroll, gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
    ui["box"] = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.container_add(scroll, ui["box"])
    call gtk.box_pack_start(outer, scroll, True, True, 0)
    ui["status"] = label("", "hint", 0)
    call gtk.widget_set_name(ui["status"], "status")
    call gtk.label_set_line_wrap(ui["status"], True)
    call gtk.box_pack_start(outer, ui["status"], False, False, 0)
    call gtk.label_set_text(ui["status"], i18n.T("Looking for apps…"))
    call gtk.connect_data(window, "destroy", 0, on_destroy, 0)
end

function load(unused):
    ui["apps"] = core.scan(True)
    call fill()
    return False
end

function group(title):
    call gtk.box_pack_start(ui["box"], label(title, "group-title", 0), False, False, 0)
    g = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_add_class(g, "group")
    call gtk.box_pack_start(ui["box"], g, False, False, 0)
    return g
end

function row(g, icon, title, sub, button):
    r = gtk.box_new(gtk.HORIZONTAL, 12)
    call gtk.widget_add_class(r, "row")
    if len(gtk.container_get_children(g)) > 0:
        call gtk.widget_add_class(r, "row-sep")
    end
    # GTK_ICON_SIZE_DND
    call gtk.box_pack_start(r, gtk.image_new_from_icon_name(icon if icon != "" else "application-x-executable", 5), False, False, 0)
    texts = gtk.box_new(gtk.VERTICAL, 0)
    name = label(title, "", 0)
    call gtk.widget_set_name(name, "app-name")
    call gtk.label_set_ellipsize(name, 3)
    call gtk.box_pack_start(texts, name, False, False, 0)
    detail = label(sub, "hint", 0)
    call gtk.label_set_ellipsize(detail, 3)
    call gtk.box_pack_start(texts, detail, False, False, 0)
    call gtk.box_pack_start(r, texts, True, True, 0)
    call gtk.box_pack_end(r, button, False, False, 0)
    call gtk.widget_set_valign(button, gtk.ALIGN_CENTER)
    call gtk.box_pack_start(g, r, False, False, 0)
end

function fill():
    for child in gtk.container_get_children(ui["box"]):
        call gtk.widget_destroy(child)
    end
    q = gtk.entry_get_text(ui["search"]).strip().lower()
    shown = [a for a in ui["apps"] if q == "" or a["name"].lower().find(q) >= 0 or a["label"].lower().find(q) >= 0]
    for section in [[i18n.T("Apps"), True], [i18n.T("Other folders with settings"), False]]:
        items = [a for a in shown if a["known"] == section[1]]
        if len(items) == 0:
            continue
        end
        g = group(section[0])
        for a in items:
            b = gtk.button_new(i18n.T("Reset…"))
            call gtk.connect_data(b, "clicked", 0, on_reset_clicked, a)
            call row(g, a["icon"], a["name"], core.human_size(a.get("size", 0)) + " · " + ", ".join(describe_paths(a)), b)
        end
    end
    backups = core.list_backups()
    if len(backups) > 0 and q == "":
        g = group(i18n.T("Backups"))
        for bk in backups[:20]:
            b = gtk.button_new(i18n.T("Restore"))
            call gtk.connect_data(b, "clicked", 0, on_restore_clicked, bk)
            call row(g, "document-revert", String(bk.get("app", "")), String(bk.get("time", "")).replace("_", " "), b)
        end
    end
    call gtk.label_set_text(ui["status"], i18n.TF("%d apps with settings", [len(ui["apps"])]))
    call gtk.widget_show_all(ui["box"])
end

function on_search(unused, entry):
    call fill()
    return 0
end

# Dotaz jako Gtk.MessageDialog: tucny nadpis, vysvetleni, tlacitka [popisek, odpoved, trida CSS]; odpoved
function message(title, secondary, buttons, default):
    dialog = gtk.dialog_new()
    call gtk.window_set_title(dialog, "")
    call gtk.window_set_transient_for(dialog, ui["window"])
    call gtk.window_set_modal(dialog, True)
    area = gtk.dialog_get_content_area(dialog)
    call gtk.container_set_border_width(area, 12)
    call gtk.box_set_spacing(area, 10)
    head = gtk.label_new("")
    call gtk.label_set_markup(head, "<big><b>" + glib.markup_escape(title) + "</b></big>")
    call gtk.label_set_line_wrap(head, True)
    call gtk.label_set_max_width_chars(head, 50)
    call gtk.box_pack_start(area, head, False, False, 0)
    if secondary != "":
        body = gtk.label_new(secondary)
        call gtk.label_set_line_wrap(body, True)
        call gtk.label_set_max_width_chars(body, 50)
        call gtk.box_pack_start(area, body, False, False, 0)
    end
    for b in buttons:
        button = gtk.dialog_add_button(dialog, b[0], b[1])
        if b[2] != "":
            call gtk.widget_add_class(button, b[2])
        end
    end
    call gtk.dialog_set_default_response(dialog, default)
    call gtk.widget_show_all(area)
    response = gtk.dialog_run(dialog)
    call gtk.widget_destroy(dialog)
    return response
end

function on_reset_clicked(app, b):
    call reset_app(app)
    return 0
end

function reset_app(app):
    ok = [i18n.T("OK"), gtk.RESPONSE_OK, ""]
    if core.is_running(app, core.running_programs()):
        call message(i18n.TF("%s is running", [app["name"]]), i18n.T("Quit the app first, then reset its settings."), [ok], gtk.RESPONSE_OK)
        return 0
    end
    question = i18n.T("The app will start as if it was just installed. These folders are moved to a backup (nothing is deleted):") + "\n" + "\n".join(describe_paths(app))
    answer = message(i18n.TF("Reset the settings of %s?", [app["name"]]), question,
        [[i18n.T("Cancel"), gtk.RESPONSE_CANCEL, ""], [i18n.T("Reset"), gtk.RESPONSE_OK, "destructive-action"]], gtk.RESPONSE_CANCEL)
    if answer != gtk.RESPONSE_OK:
        return 0
    end
    dest = ""
    try:
        dest = core.reset(app)
    else:
        call message(i18n.T("The settings could not be moved"), core.reason(last_error()), [ok], gtk.RESPONSE_OK)
        return 0
    end
    answer = message(i18n.TF("Settings of %s were reset", [app["name"]]), i18n.TF("The previous settings are in %s", [dest]),
        [[i18n.T("Show Backup"), 1, ""], ok], gtk.RESPONSE_OK)
    if answer == 1:
        call glib.spawn_quiet(["xdg-open", dest])
    end
    call load(0)
end

function on_restore_clicked(bk, b):
    call restore_backup(bk)
    return 0
end

function restore_backup(bk):
    answer = message(i18n.TF("Restore the settings of %s?", [String(bk.get("app", ""))]), i18n.T("Settings the app has now are moved to a new backup first."),
        [[i18n.T("Cancel"), gtk.RESPONSE_CANCEL, ""], [i18n.T("OK"), gtk.RESPONSE_OK, ""]], gtk.RESPONSE_OK)
    if answer != gtk.RESPONSE_OK:
        return 0
    end
    try:
        call core.restore(bk["dir"])
    else:
        call message(i18n.TF("The backup could not be restored: %s", [core.reason(last_error())]), "", [[i18n.T("OK"), gtk.RESPONSE_OK, ""]], gtk.RESPONSE_OK)
    end
    call load(0)
end

function on_destroy(unused, window):
    call gtk.main_quit()
    return 0
end

# ---- testy (LUXOS_TEST_CONTROL=1) ------------------------------------------------------------------------------

function on_test(command, rest):
    if command == "reset":
        call reset_app(core.find(ui["apps"], rest))
    elif command == "restore":
        call restore_backup(core.list_backups()[Int(rest)])
    elif command == "search":
        call gtk.entry_set_text(ui["search"], rest)
    end
end

function gui():
    call glib.set_prgname("luxos-app-reset")
    call gtk.init()
    call gtk.css_load(CSS)
    call build()
    call gtk.widget_show_all(ui["window"])
    call glib.idle_add_data(load, 0)
    call testctl.start(on_test)
    call gtk.main()
    return 0
end

# ---- start ---------------------------------------------------------------------------------------------------------

command = ""
if len(args) > 1:
    command = args[1]
end
rest = args[2:]
status = 0
if command == "list":
    status = cli_list(rest)
elif command == "reset":
    status = cli_reset(rest)
elif command == "backups":
    status = cli_backups(rest)
elif command == "restore":
    status = cli_restore(rest)
elif command == "-h" or command == "--help" or command == "help":
    call usage(False)
elif command != "":
    call usage(True)
    status = 2
else:
    status = gui()
end
exit(status)
