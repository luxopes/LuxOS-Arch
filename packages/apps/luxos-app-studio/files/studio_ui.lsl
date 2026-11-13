load gtk
load glib
load studio_native as native
load studio_project as projects
load gio

CS = {"Press Run (Ctrl+R) to build and start your app.": "Stiskněte Spustit (Ctrl+R) – aplikace se sestaví a spustí.", "Ready": "Připraveno", "Window app": "Okenní aplikace", "Command line": "Příkazová řádka", "Changes saved.": "Změny uloženy.", "Uninstall": "Odinstalovat", "Uninstall from This Computer": "Odinstalovat z tohoto počítače", "Installed for you – the app is in Launchpad. Install again after changes to update it.": "Nainstalováno pro vás – aplikace je v Launchpadu. Po změnách ji aktualizujete další instalací.", "Install on This Computer": "Nainstalovat do tohoto počítače", "Builds the app and adds it to Launchpad for your account only. Nothing is installed system-wide.": "Sestaví aplikaci a přidá ji do Launchpadu jen pro váš účet. Do systému se nic neinstaluje.", "No project selected": "Není vybraný projekt", "Building…": "Sestavování…", "Running…": "Běží…", "Choose folder": "Vybrat složku", "Exporting package…": "Exportování balíčku…", "Installed – find it in Launchpad.": "Nainstalováno – najdete ji v Launchpadu.", "Build succeeded": "Sestavení proběhlo úspěšně", "Package exported.": "Balíček byl exportován.", "App finished.": "Aplikace skončila.", "Exit": "Konec, kód", "Build failed": "Sestavení selhalo", "The app stopped with an error": "Aplikace skončila chybou", "Build failed – see the output below.": "Sestavení selhalo – podrobnosti jsou ve výstupu dole.", "error(s)": "chyb", "Open project": "Otevřít projekt", "Uninstalled.": "Odinstalováno.", "Stopping…": "Ukončování…", "Choose an SVG or PNG icon": "Vyberte ikonu SVG nebo PNG", "Icon updated.": "Ikona byla změněna.", "Install Icon Studio with: lux install luxos-icon-studio": "Nainstalujte Icon Studio: lux install luxos-icon-studio", "Export an SVG from Icon Studio, then choose it here.": "V Icon Studiu exportujte SVG a pak ho vyberte zde.", "Install LSL IDE with: lux install lsl-ide": "Nainstalujte LSL IDE: lux install lsl-ide", "Write, run and share native LuxOS apps in Lux Simple Lang.": "Pište, spouštějte a sdílejte nativní aplikace LuxOS v jazyce Lux Simple Lang.", "New Project…": "Nový projekt…", "Open Project…": "Otevřít projekt…", "Recent Projects": "Nedávné projekty", "Projects you create or open appear here.": "Zde se objeví projekty, které vytvoříte nebo otevřete.", "New Project": "Nový projekt", "Choose a template and fill in the details. A new folder is created; existing folders are never overwritten.": "Vyberte šablonu a vyplňte údaje. Vytvoří se nová složka; existující složky se nikdy nepřepisují.", "Template": "Šablona", "A GTK window with a button – ready for your interface.": "Okno GTK s tlačítkem – připravené pro vaše rozhraní.", "A small, fast tool for your terminal.": "Malý a rychlý nástroj pro terminál.", "Details": "Údaje", "App name": "Název aplikace", "My App": "Moje aplikace", "Package name": "Název balíčku", "Summary": "Krátký popis", "An application for LuxOS": "Aplikace pro LuxOS", "Project folder": "Složka projektu", "Choose…": "Vybrat…", "Cancel": "Zrušit", "Create Project": "Vytvořit projekt", "Saved automatically": "Ukládá se automaticky", "Show": "Ukázat", "Hide": "Skrýt", "Output": "Výstup", "App": "Aplikace", "How your app appears in Launchpad and in its package.": "Jak se aplikace zobrazí v Launchpadu a v balíčku.", "General": "Obecné", "Version": "Verze", "Category": "Kategorie", "Utilities": "Nástroje", "Development": "Vývoj", "Graphics": "Grafika", "Office": "Kancelář", "Education": "Vzdělávání", "Games": "Hry", "Internet": "Internet", "Sound & Video": "Zvuk a video", "System": "Systém", "Type": "Typ", "Save": "Uložit", "Icon": "Ikona", "SVG or PNG, at least 256 × 256 pixels.": "SVG nebo PNG, alespoň 256 × 256 pixelů.", "Choose Image…": "Vybrat obrázek…", "Design in Icon Studio": "Navrhnout v Icon Studiu", "Install and Share": "Instalace a sdílení", "Export .lux Package…": "Exportovat balíček .lux…", "Files": "Soubory", "New file": "Nový soubor", "name, e.g. helpers": "název, např. pomocne", "Name, Icon and Install": "Název, ikona a instalace", "Build": "Sestavit", "Open in LSL IDE": "Otevřít v LSL IDE", "Show Project Folder": "Zobrazit složku projektu", "Run · Ctrl+R": "Spustit · Ctrl+R", "Stop · Esc": "Zastavit · Esc"}
LANG_CS = native.env("LANG").startswith("cs") or native.env("LANGUAGE").startswith("cs")
ui = {"window": 0, "project": None, "job": None, "timer": 0, "kind": "gtk", "mode": "", "alive": True, "monitors": [], "then": "", "current": "", "errors": [], "file_buttons": {}, "details_dirty": False, "syncing": False, "page": "welcome"}

CSS = ".studio-sidebar { background-color: alpha(currentColor, 0.035); border-right: 1px solid alpha(currentColor, 0.09); }\n.studio-sidebar button.nav { border: none; background: none; box-shadow: none; border-radius: 7px; padding: 4px 8px; min-height: 0; }\n.studio-sidebar button.nav:hover { background-color: alpha(currentColor, 0.06); }\n.studio-sidebar button.nav.active { background-color: alpha(@theme_selected_bg_color, 0.15); }\n.studio-sidebar button.nav.active label, .studio-sidebar button.nav.active image { color: @theme_selected_bg_color; }\n.studio-sidebar button.small { padding: 0 4px; min-height: 20px; min-width: 20px; }\n.sidebar-caption { font-size: 11px; font-weight: 700; opacity: 0.5; margin: 0 8px; }\n.page-title { font-size: 22px; font-weight: 700; }\n.hero-title { font-size: 26px; font-weight: 700; }\n.dim { opacity: 0.62; }\n.group-title { font-weight: 700; font-size: 13px; }\n.group { background-color: alpha(currentColor, 0.035); border: 1px solid alpha(currentColor, 0.08); border-radius: 12px; padding: 16px; }\nbutton.template, button.recent { border-radius: 12px; padding: 12px 14px; background: alpha(currentColor, 0.02); border: 1px solid alpha(currentColor, 0.12); box-shadow: none; }\nbutton.recent { border-radius: 9px; padding: 8px 12px; }\nbutton.template:hover, button.recent:hover { background-color: alpha(currentColor, 0.05); }\nbutton.template.selected { border-color: @theme_selected_bg_color; box-shadow: inset 0 0 0 1px @theme_selected_bg_color; background-color: alpha(@theme_selected_bg_color, 0.08); }\nbutton.template.selected image { color: @theme_selected_bg_color; }\n.template-title { font-weight: 700; }\n.field-label { font-size: 12px; font-weight: 600; opacity: 0.75; }\n.file-bar { padding: 6px 14px; border-bottom: 1px solid alpha(currentColor, 0.09); }\n.file-name { font-weight: 600; }\n.error-bar { background-color: alpha(#e5484d, 0.12); border-bottom: 1px solid alpha(#e5484d, 0.35); padding: 6px 14px; }\n.error-bar image { color: #e5484d; }\n.ok-bar { background-color: alpha(#30a46c, 0.12); border-bottom: 1px solid alpha(#30a46c, 0.35); padding: 6px 14px; }\n.ok-bar image { color: #30a46c; }\n.console-title { font-size: 11px; font-weight: 700; opacity: 0.6; padding: 4px 14px; border-top: 1px solid alpha(currentColor, 0.09); }\n.console, .console text { background-color: #1d1f24; color: #e3e6ec; font-family: monospace; font-size: 11px; }\n.console { padding: 8px 12px; }\n.editor { font-size: 12px; }\n"

function T(text):
    if LANG_CS:
        return CS.get(text, text)
    end
    return text
end

function box(vertical=True, spacing=0, style=""):
    direction = 0
    if vertical:
        direction = 1
    end
    result = gtk.box_new(direction, spacing)
    if style:
        call gtk.widget_add_class(result, style)
    end
    return result
end

function pack(parent, child, expand=False):
    call gtk.box_pack_start(parent, child, expand, True, 0)
    return child
end

function spacer(parent, height):
    gap = box(True, 0)
    call gtk.widget_set_size_request(gap, -1, height)
    call pack(parent, gap)
end

function label(text, style="", wrap=False):
    result = gtk.label_new(T(text))
    call gtk.label_set_xalign(result, 0.0)
    if style:
        call gtk.widget_add_class(result, style)
    end
    if wrap:
        call gtk.label_set_line_wrap(result, True)
        call __lsl_qbe_call2(__lsl_symbol("gtk_label_set_line_wrap_mode"), native.ptr(result), 2)
    end
    return result
end

function button(title, action, style=""):
    result = gtk.button_new(T(title))
    if style:
        call gtk.widget_add_class(result, style)
    end
    call native.connect(result, "clicked", clicked, action)
    return result
end

function icon_button(icon, tip, action, style=""):
    result = gtk.button_new_from_icon_name(icon, 1)
    call gtk.widget_set_tooltip(result, T(tip))
    if style:
        call gtk.widget_add_class(result, style)
    end
    call native.connect(result, "clicked", clicked, action)
    return result
end

function icon_label(icon, text, spacing=8):
    row = box(False, spacing)
    call pack(row, gtk.image_new_from_icon_name(icon, 1))
    title = label(text)
    call gtk.label_set_ellipsize(title, 3)
    call pack(row, title, True)
    return row
end

function nav_button(action, icon, title):
    result = gtk.button_new_empty()
    call gtk.widget_add_class(result, "nav")
    call gtk.container_add(result, icon_label(icon, title))
    call native.connect(result, "clicked", clicked, action)
    return result
end

# --- stav okna -----------------------------------------------------------------

function show_page(name):
    ui["page"] = name
    top = name
    if name == "editor" or name == "details":
        top = "workspace"
        call __lsl_qbe_call2(__lsl_symbol("gtk_stack_set_visible_child_name"), native.ptr(ui["main"]), native.cstr(name))
        call gtk.widget_remove_class(ui["nav_details"], "active")
        for key in ui["file_buttons"].keys():
            call gtk.widget_remove_class(ui["file_buttons"][key], "active")
        end
        if name == "details":
            call gtk.widget_add_class(ui["nav_details"], "active")
        elif ui["current"] in ui["file_buttons"]:
            call gtk.widget_add_class(ui["file_buttons"][ui["current"]], "active")
        end
    end
    call __lsl_qbe_call2(__lsl_symbol("gtk_stack_set_visible_child_name"), native.ptr(ui["stack"]), native.cstr(top))
    call update_header()
end

function update_header():
    project = ui["project"]
    title = "App Studio"
    if project != None and ui["page"] in ["editor", "details"]:
        title = project["title"]
    end
    call native.header_set(ui["header"], title, ui.get("status_text", ""))
    workspace = project != None and ui["page"] in ["editor", "details"]
    call gtk.widget_set_visible(ui["run"], workspace)
    call gtk.widget_set_visible(ui["stop"], workspace)
end

function report(message):
    ui["status_text"] = T(message)
    call update_header()
end

function error(message):
    call report(message)
    call show_bar("error", message, False)
end

# Lista nad editorem: chyba prekladu (s tlacitkem na radek) nebo uspech
function show_bar(kind, message, can_jump):
    call gtk.widget_remove_class(ui["bar"], "error-bar")
    call gtk.widget_remove_class(ui["bar"], "ok-bar")
    icon = "dialog-error-symbolic"
    if kind == "ok":
        icon = "emblem-ok-symbolic"
        call gtk.widget_add_class(ui["bar"], "ok-bar")
    else:
        call gtk.widget_add_class(ui["bar"], "error-bar")
    end
    call gtk.image_set_from_icon_name(ui["bar_icon"], icon, 1)
    call gtk.label_set_text(ui["bar_text"], message)
    call gtk.widget_set_visible(ui["bar_jump"], can_jump)
    call gtk.widget_set_visible(ui["bar"], True)
end

function hide_bar():
    call gtk.widget_set_visible(ui["bar"], False)
end

function sensitivity(busy):
    has = ui["project"] != None
    # Spustit pri bezici aplikaci ji spusti znovu (s novym kodem)
    call gtk.widget_set_sensitive(ui["run"], has and (not busy or ui["mode"] == "run"))
    call gtk.widget_set_sensitive(ui["stop"], busy)
    for key in ["menu_build", "menu_export", "menu_install", "menu_edit", "menu_icon", "menu_folder", "install_button", "export_button", "icon_choose", "icon_design"]:
        call gtk.widget_set_sensitive(ui[key], has and not busy)
    end
    for key in ["create_button", "menu_new", "menu_open", "welcome_new", "welcome_open"]:
        call gtk.widget_set_sensitive(ui[key], not busy)
    end
end

# --- projekt -------------------------------------------------------------------------

function update_project(project):
    call save_current()
    for monitor in ui["monitors"]:
        call gio.file_monitor_cancel(monitor)
    end
    ui["monitors"] = []
    ui["project"] = project
    ui["current"] = ""
    ui["errors"] = []
    call projects.remember(project)
    call native.set_text(ui["console"], T("Press Run (Ctrl+R) to build and start your app.") + "\n")
    call hide_bar()
    pending = [project["path"] + "/src"]
    while pending and len(ui["monitors"]) < 100:
        directory = pending.pop(0)
        if not native.symlink(directory):
            ui["monitors"].append(gio.file_monitor(directory, source_changed))
            for name in listdir(directory):
                child = directory + "/" + name
                if native.directory(child) and not native.symlink(child):
                    pending.append(child)
                end
            end
        end
    end
    call refresh_files()
    call load_details()
    call open_file("src/main.lsl")
    call report("Ready")
    call sensitivity(False)
    call show_page("editor")
end

function refresh_files():
    for key in ui["file_buttons"].keys():
        call gtk.widget_destroy(ui["file_buttons"][key])
    end
    ui["file_buttons"] = {}
    for relative in projects.sources(ui["project"]):
        title = relative[4:]
        item = nav_button("file:" + relative, "text-x-generic-symbolic", title)
        call gtk.widget_set_tooltip(item, relative)
        ui["file_buttons"][relative] = item
        call pack(ui["files"], item)
    end
    call gtk.widget_show_all(ui["files"])
    if ui["current"] in ui["file_buttons"] and ui["page"] == "editor":
        call gtk.widget_add_class(ui["file_buttons"][ui["current"]], "active")
    end
end

function source_changed(path, event, other):
    if not ui["alive"] or ui["project"] == None:
        return
    end
    # 2 smazano, 3 vytvoreno, 8-10 presunuto
    if event in [2, 3, 8, 9, 10]:
        call refresh_files()
    end
    current = ui["project"]["path"] + "/" + ui["current"]
    if ui["current"] and path == current and native.exists(current) and not native.modified(ui["editor"]):
        text = readfile(current)
        if text != native.get_text(ui["editor"]):
            call native.load_text(ui["editor"], text)
        end
    end
end

function open_file(relative):
    if ui["project"] == None:
        return
    end
    if relative != ui["current"]:
        call save_current()
        path = ui["project"]["path"] + "/" + relative
        if native.symlink(path) or not native.exists(path):
            Error(ProjectError: "Cannot open " + relative)
        end
        ui["current"] = relative
        call native.load_text(ui["editor"], readfile(path))
        call gtk.label_set_text(ui["file_name"], relative)
    end
    call show_page("editor")
end

# Editor se uklada sam (pred sestavenim, prepnutim souboru a zavrenim) - jako Xcode
function save_current():
    if ui["project"] == None or not ui["current"] or not native.modified(ui["editor"]):
        return False
    end
    path = ui["project"]["path"] + "/" + ui["current"]
    if native.symlink(path):
        Error(ProjectError: "Source files must not be symbolic links.")
    end
    call writefile(path, native.get_text(ui["editor"]))
    call native.set_modified(ui["editor"], False)
    return True
end

function load_details():
    project = ui["project"]
    values = projects.details(project)
    ui["syncing"] = True
    call gtk.entry_set_text(ui["d_title"], values["title"])
    call gtk.entry_set_text(ui["d_summary"], values["summary"])
    call gtk.entry_set_text(ui["d_version"], values["version"])
    call gtk.combo_box_set_active(ui["d_category"], projects.CATEGORIES.index(values["category"]))
    call gtk.label_set_text(ui["d_name"], project["name"])
    kind = T("Window app")
    if project["type"] == "cli":
        kind = T("Command line")
    end
    call gtk.label_set_text(ui["d_type"], kind)
    ui["syncing"] = False
    ui["details_dirty"] = False
    call update_icon()
    call update_install()
end

function details_changed(state, widget):
    if not ui["syncing"]:
        ui["details_dirty"] = True
    end
end

function save_details(quiet=False):
    if ui["project"] == None or not ui["details_dirty"]:
        return
    end
    category = projects.CATEGORIES[max(0, gtk.combo_box_get_active(ui["d_category"]))]
    call projects.save_details(ui["project"], gtk.entry_get_text(ui["d_title"]).strip(), gtk.entry_get_text(ui["d_summary"]).strip(), gtk.entry_get_text(ui["d_version"]).strip(), category)
    ui["details_dirty"] = False
    call projects.remember(ui["project"])
    if not quiet:
        call report("Changes saved.")
    end
    call update_header()
end

function update_icon():
    path = projects.icon_file(ui["project"])
    pixbuf = 0
    if path:
        pixbuf = gtk.pixbuf_new_from_file_at_scale(path, 96, 96, True)
    end
    if pixbuf:
        call gtk.image_set_from_pixbuf(ui["icon_preview"], pixbuf)
        call glib.object_unref(pixbuf)
    else:
        call gtk.image_set_from_icon_name(ui["icon_preview"], "application-x-executable", 6)
    end
end

function update_install():
    if projects.installed(ui["project"]):
        call gtk.button_set_label(ui["install_button"], T("Uninstall"))
        call native.menu_item_set_label(ui["menu_install"], T("Uninstall from This Computer"))
        call gtk.label_set_text(ui["install_state"], T("Installed for you – the app is in Launchpad. Install again after changes to update it."))
    else:
        call gtk.button_set_label(ui["install_button"], T("Install on This Computer"))
        call native.menu_item_set_label(ui["menu_install"], T("Install on This Computer"))
        call gtk.label_set_text(ui["install_state"], T("Builds the app and adds it to Launchpad for your account only. Nothing is installed system-wide."))
    end
end

# --- sestaveni a spusteni --------------------------------------------------------------

function start_job(mode):
    if ui["job"]:
        return
    end
    project = ui["project"]
    if project == None:
        Error(ProjectError: T("No project selected"))
    end
    root = project["path"]
    argv = []
    logfile = root + "/build/studio.log"
    if mode == "build":
        argv = projects.prepare_build(project)
        call report("Building…")
    elif mode == "run":
        executable = root + "/build/" + project["name"]
        if not projects.build_ready(project):
            Error(ProjectError: "Build the application successfully before running it.")
        end
        argv = [executable]
        call report("Running…")
        logfile = root + "/build/run.log"
    elif mode == "export":
        destination = native.choose(ui["window"], T("Choose folder"), 2, root + "/exports")
        if not destination:
            return
        end
        argv = projects.prepare_package(project, destination)
        logfile = root + "/build/export.log"
        call report("Exporting package…")
    end
    ui["job"] = native.spawn_logged(argv, root, logfile)
    ui["mode"] = mode
    ui["prefix"] = "› " + " ".join(argv) + "\n\n"
    call native.set_text(ui["console"], ui["prefix"])
    call sensitivity(True)
    ui["timer"] = glib.timeout_add(80, tick)
end

# Spustit/Exportovat/Nainstalovat: nejdriv ulozit a pripadne sestavit, pak pokracovat
function after_build(action):
    call save_current()
    call save_details(True)
    call hide_bar()
    ui["errors"] = []
    if projects.build_ready(ui["project"]):
        call finish_action(action)
    else:
        ui["then"] = action
        call start_job("build")
    end
end

function finish_action(action):
    if action == "run" or action == "export":
        call start_job(action)
    elif action == "install":
        files = projects.install(ui["project"])
        call update_install()
        call report("Installed – find it in Launchpad.")
        call show_bar("ok", T("Installed – find it in Launchpad.") + "  " + files[0], False)
    end
end

function tick():
    if not ui["alive"] or not ui["job"]:
        ui["timer"] = 0
        return False
    end
    job = ui["job"]
    status = native.poll(job)
    text = ui["prefix"] + native.log_tail(job["log"])
    if status != None:
        mode = ui["mode"]
        if mode == "build":
            try:
                call projects.finish_build(ui["project"], status)
            else:
                status = 1
                text += "\n" + String(last_error()) + "\n"
            end
        end
        text += "\n[exit " + String(status) + "]\n"
        ui["job"] = None
        ui["timer"] = 0
        call native.set_text(ui["console"], text)
        call sensitivity(False)
        following = ui["then"]
        ui["then"] = ""
        if mode == "run" and ui.get("restart"):
            ui["restart"] = False
            call clicked("run", 0)
            return False
        end
        if status == 0:
            if mode == "build":
                call report("Build succeeded")
                if following:
                    try:
                        call finish_action(following)
                    else:
                        call error(String(last_error()))
                    end
                else:
                    call show_bar("ok", T("Build succeeded"), False)
                end
            elif mode == "export":
                call report("Package exported.")
                call show_bar("ok", T("Package exported."), False)
            else:
                call report("App finished.")
            end
        elif mode == "build":
            call build_failed(text)
        elif mode == "run":
            call run_failed(text, status)
        else:
            call report(T("Exit") + " " + String(status))
        end
        return False
    end
    call native.set_text(ui["console"], text)
    return True
end

function build_failed(log):
    ui["errors"] = projects.parse_errors(log, ui["project"]["path"])
    count = len(ui["errors"])
    if count == 0:
        call report("Build failed")
        call show_bar("error", T("Build failed – see the output below."), False)
        return
    end
    first = ui["errors"][0]
    call report(T("Build failed") + " · " + String(count) + " " + T("error(s)"))
    call show_bar("error", first["file"].replace("src/", "") + ":" + String(first["line"]) + "  " + first["message"], True)
    call jump_to_error()
end

# Chyba za behu (napr. neznama promenna ve funkci): stejny format jako u prekladace
function run_failed(log, status):
    ui["errors"] = []
    for item in projects.parse_errors(log, ui["project"]["path"]):
        if item["file"].startswith("src/"):
            ui["errors"].append(item)
        end
    end
    if not ui["errors"]:
        call report(T("Exit") + " " + String(status))
        return
    end
    first = ui["errors"][0]
    call report("The app stopped with an error")
    call show_bar("error", first["file"].replace("src/", "") + ":" + String(first["line"]) + "  " + first["message"], True)
    call jump_to_error()
end

function jump_to_error():
    if not ui["errors"]:
        return
    end
    first = ui["errors"][0]
    if first["file"].startswith("src/") and native.exists(ui["project"]["path"] + "/" + first["file"]):
        call open_file(first["file"])
        call native.select_line(ui["editor"], first["line"])
    end
end

# --- akce ------------------------------------------------------------------------

function clicked(action, widget):
    try:
        if action == "welcome" or action == "create":
            call show_page(action)
        elif action == "gtk" or action == "cli":
            ui["kind"] = action
            call gtk.widget_remove_class(ui["gtk_template"], "selected")
            call gtk.widget_remove_class(ui["cli_template"], "selected")
            call gtk.widget_add_class(ui[action + "_template"], "selected")
        elif action == "choose":
            path = native.choose(ui["window"], T("Choose folder"), 2, native.env("HOME", "/tmp"))
            if path:
                call gtk.entry_set_text(ui["destination"], path + "/" + gtk.entry_get_text(ui["name"]))
            end
        elif action == "new":
            project = projects.create(gtk.entry_get_text(ui["destination"]), gtk.entry_get_text(ui["title"]), gtk.entry_get_text(ui["name"]), ui["kind"], gtk.entry_get_text(ui["summary"]))
            call update_project(project)
        elif action == "open":
            path = native.choose(ui["window"], T("Open project"), 2, native.env("HOME", "/tmp"))
            if path:
                call update_project(projects.open_project(path))
            end
        elif action.startswith("recent:"):
            call update_project(projects.open_project(action[7:]))
        elif action.startswith("file:"):
            call open_file(action[5:])
        elif action == "details":
            call save_current()
            call show_page("details")
        elif action == "save":
            call save_current()
            call save_details()
        elif action == "build":
            call save_current()
            call save_details(True)
            call hide_bar()
            ui["errors"] = []
            ui["then"] = ""
            call start_job("build")
        elif action == "run" and ui["job"] and ui["mode"] == "run":
            ui["restart"] = True
            call native.stop(ui["job"])
        elif action == "run" or action == "export":
            call after_build(action)
        elif action == "install":
            if projects.installed(ui["project"]):
                call projects.uninstall(ui["project"])
                call update_install()
                call report("Uninstalled.")
            else:
                call after_build("install")
            end
        elif action == "stop":
            ui["then"] = ""
            ui["restart"] = False
            call native.stop(ui["job"])
            call report("Stopping…")
        elif action == "new_file":
            call gtk.revealer_set_reveal_child(ui["new_file_revealer"], True)
            call gtk.widget_grab_focus(ui["new_file_entry"])
        elif action == "new_file_add":
            relative = projects.new_source(ui["project"], gtk.entry_get_text(ui["new_file_entry"]))
            call gtk.entry_set_text(ui["new_file_entry"], "")
            call gtk.revealer_set_reveal_child(ui["new_file_revealer"], False)
            call refresh_files()
            call open_file(relative)
        elif action == "icon_choose":
            path = native.choose(ui["window"], T("Choose an SVG or PNG icon"), 0, native.env("HOME", "/tmp"))
            if path:
                call projects.set_icon(ui["project"], path)
                call update_icon()
                call report("Icon updated.")
            end
        elif action == "icon_design":
            executable = native.program("luxos-icon-studio")
            if not executable:
                Error(ToolError: T("Install Icon Studio with: lux install luxos-icon-studio"))
            end
            call glib.spawn([executable])
            call report("Export an SVG from Icon Studio, then choose it here.")
        elif action == "edit":
            call save_current()
            executable = native.program("lsl-ide")
            if not executable:
                Error(ToolError: T("Install LSL IDE with: lux install lsl-ide"))
            end
            call glib.spawn([executable, ui["project"]["path"]])
        elif action == "folder":
            call native.open_uri_folder(ui["project"]["path"])
        elif action == "jump":
            call jump_to_error()
        elif action == "close_bar":
            call hide_bar()
        end
    else:
        call error(String(last_error()))
    end
end

function close(state, event, window):
    if ui["alive"]:
        try:
            call save_current()
            call save_details(True)
        else:
            call glib.report("App Studio: " + String(last_error()) + "\n")
        end
    end
    ui["alive"] = False
    if ui["timer"]:
        call glib.source_remove(ui["timer"])
        ui["timer"] = 0
    end
    call native.dispose(ui["job"])
    if ui["mode"] == "build" and ui["project"] != None:
        call projects.finish_build(ui["project"], 1)
    end
    for monitor in ui["monitors"]:
        call gio.file_monitor_cancel(monitor)
    end
    ui["monitors"] = []
    ui["job"] = None
    if __lsl_qbe_call0(__lsl_symbol("gtk_main_level")) > 0:
        call gtk.main_quit()
    end
    return False
end

function key_pressed(state, event, window):
    key = native.cell()
    modifiers = native.cell()
    call __lsl_qbe_call2(__lsl_symbol("gdk_event_get_keyval"), native.ptr(event), native.data(key))
    call __lsl_qbe_call2(__lsl_symbol("gdk_event_get_state"), native.ptr(event), native.data(modifiers))
    value = __lsl_qbe_load32(native.data(key))
    control = (__lsl_qbe_load32(native.data(modifiers)) & 4) != 0
    action = ""
    has = ui["project"] != None
    if control:
        if value == 110 or value == 78:
            action = "create"
        elif value == 111 or value == 79:
            action = "open"
        elif (value == 115 or value == 83) and has:
            action = "save"
        elif (value == 98 or value == 66) and has:
            action = "build"
        elif (value == 114 or value == 82) and has:
            action = "run"
        elif (value == 101 or value == 69) and has:
            action = "export"
        end
    elif value == 65307 and ui["job"]:
        action = "stop"
    end
    if action:
        if ui["job"] and action != "stop" and not (action == "run" and ui["mode"] == "run"):
            return True
        end
        call clicked(action, 0)
        return True
    end
    return False
end

# --- stranky ------------------------------------------------------------------------

function field(parent, title, value, name):
    column = box(True, 6)
    call pack(column, label(title, "field-label"))
    entry = gtk.entry_new()
    call gtk.entry_set_text(entry, value)
    call pack(column, entry)
    call pack(parent, column, True)
    ui[name] = entry
    return entry
end

function group(parent, title):
    if title:
        call pack(parent, label(title, "group-title"))
    end
    result = box(True, 12, "group")
    call pack(parent, result)
    return result
end

function centered(child, width):
    outer = box(False, 0)
    call gtk.widget_set_halign(child, 3)
    call gtk.widget_set_size_request(child, width, -1)
    call pack(outer, child, True)
    return outer
end

function welcome_page():
    page = box(True, 10)
    call gtk.widget_set_margins(page, 32, 32, 48, 32)
    name = "luxos-app-studio"
    if not gtk.icon_theme_has_icon(name):
        name = "applications-development"
    end
    icon = gtk.image_new_from_icon_name(name, 6)
    call gtk.image_set_pixel_size(icon, 96)
    call gtk.widget_set_halign(icon, 3)
    call pack(page, icon)
    heading = label("App Studio", "hero-title")
    call gtk.widget_set_halign(heading, 3)
    call pack(page, heading)
    intro = label("Write, run and share native LuxOS apps in Lux Simple Lang.", "dim")
    call gtk.widget_set_halign(intro, 3)
    call pack(page, intro)
    call spacer(page, 10)
    actions = box(False, 10)
    call gtk.widget_set_halign(actions, 3)
    ui["welcome_new"] = button("New Project…", "create", "suggested-action")
    ui["welcome_open"] = button("Open Project…", "open")
    call pack(actions, ui["welcome_new"])
    call pack(actions, ui["welcome_open"])
    call pack(page, actions)
    call spacer(page, 18)
    items = projects.recent()
    column = box(True, 6)
    call pack(column, label("Recent Projects", "group-title"))
    if not items:
        call pack(column, label("Projects you create or open appear here.", "dim"))
    end
    for item in items:
        entry = gtk.button_new_empty()
        call gtk.widget_add_class(entry, "recent")
        text = box(True, 2)
        call pack(text, label(item.get("title", ""), "template-title"))
        where = label(item["path"], "dim")
        call gtk.label_set_ellipsize(where, 1)
        call pack(text, where)
        row = box(False, 12)
        image = gtk.image_new_from_icon_name("folder-symbolic", 5)
        call gtk.image_set_pixel_size(image, 24)
        call pack(row, image)
        call pack(row, text, True)
        call gtk.container_add(entry, row)
        call native.connect(entry, "clicked", clicked, "recent:" + item["path"])
        call pack(column, entry)
    end
    call pack(page, centered(column, 520))
    return page
end

function new_page():
    page = box(True, 10)
    call gtk.widget_set_margins(page, 32, 32, 26, 24)
    call pack(page, label("New Project", "page-title"))
    call pack(page, label("Choose a template and fill in the details. A new folder is created; existing folders are never overwritten.", "dim", True))
    call spacer(page, 8)
    call pack(page, label("Template", "group-title"))
    templates = box(False, 12)
    for kind in ["gtk", "cli"]:
        title = "Window app"
        subtitle = "A GTK window with a button – ready for your interface."
        icon = "window-new-symbolic"
        if kind == "cli":
            title = "Command line"
            subtitle = "A small, fast tool for your terminal."
            icon = "utilities-terminal-symbolic"
        end
        tile = gtk.button_new_empty()
        call gtk.widget_add_class(tile, "template")
        contents = box(False, 12)
        image = gtk.image_new_from_icon_name(icon, 5)
        call gtk.image_set_pixel_size(image, 28)
        call gtk.widget_set_valign(image, 1)
        call pack(contents, image)
        text = box(True, 3)
        call pack(text, label(title, "template-title"))
        call pack(text, label(subtitle, "dim", True))
        call pack(contents, text, True)
        call gtk.container_add(tile, contents)
        call native.connect(tile, "clicked", clicked, kind)
        call pack(templates, tile, True)
        ui[kind + "_template"] = tile
    end
    call gtk.widget_add_class(ui["gtk_template"], "selected")
    call pack(page, templates)
    call spacer(page, 6)
    card = group(page, "Details")
    names = box(False, 16)
    call field(names, "App name", T("My App"), "title")
    call field(names, "Package name", "my-app", "name")
    call pack(card, names)
    call field(card, "Summary", T("An application for LuxOS"), "summary")
    folder = box(True, 6)
    call pack(folder, label("Project folder", "field-label"))
    pathrow = box(False, 8)
    ui["destination"] = gtk.entry_new()
    call gtk.entry_set_text(ui["destination"], native.env("HOME", "/tmp") + "/Projects/my-app")
    call pack(pathrow, ui["destination"], True)
    call pack(pathrow, button("Choose…", "choose"))
    call pack(folder, pathrow)
    call pack(card, folder)
    buttons = box(False, 8)
    call gtk.widget_set_halign(buttons, 2)
    call pack(buttons, button("Cancel", "welcome"))
    ui["create_button"] = button("Create Project", "new", "suggested-action")
    call pack(buttons, ui["create_button"])
    call spacer(page, 4)
    call pack(page, buttons)
    return page
end

function editor_page():
    page = box(True, 0)
    bar = box(False, 8, "file-bar")
    ui["file_name"] = label("src/main.lsl", "file-name")
    call pack(bar, ui["file_name"], True)
    call pack(bar, label("Saved automatically", "dim"))
    call pack(page, bar)
    ui["bar"] = box(False, 10, "error-bar")
    ui["bar_icon"] = gtk.image_new_from_icon_name("dialog-error-symbolic", 1)
    call pack(ui["bar"], ui["bar_icon"])
    ui["bar_text"] = label("")
    call gtk.label_set_ellipsize(ui["bar_text"], 3)
    call gtk.label_set_selectable(ui["bar_text"], True)
    call pack(ui["bar"], ui["bar_text"], True)
    ui["bar_jump"] = button("Show", "jump")
    call pack(ui["bar"], ui["bar_jump"])
    call pack(ui["bar"], icon_button("window-close-symbolic", "Hide", "close_bar", "flat"))
    call pack(page, ui["bar"])
    ui["editor"] = native.source_view(native.dark_theme())
    call gtk.widget_add_class(ui["editor"], "editor")
    scroll = gtk.scrolled_window_new()
    call gtk.container_add(scroll, ui["editor"])
    lower = box(True, 0)
    call pack(lower, label("Output", "console-title"))
    ui["console"] = __lsl_qbe_call0(__lsl_symbol("gtk_text_view_new"))
    call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_set_editable"), native.ptr(ui["console"]), 0)
    call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_set_cursor_visible"), native.ptr(ui["console"]), 0)
    call __lsl_qbe_call2(__lsl_symbol("gtk_text_view_set_wrap_mode"), native.ptr(ui["console"]), 3)
    call gtk.widget_add_class(ui["console"], "console")
    output = gtk.scrolled_window_new()
    call gtk.widget_set_size_request(output, -1, 150)
    call gtk.container_add(output, ui["console"])
    call pack(lower, output, True)
    split = native.paned(True)
    call native.paned_pack(split, scroll, lower)
    call pack(page, split, True)
    return page
end

function details_page():
    page = box(True, 10)
    call gtk.widget_set_margins(page, 32, 32, 26, 24)
    call pack(page, label("App", "page-title"))
    call pack(page, label("How your app appears in Launchpad and in its package.", "dim", True))
    call spacer(page, 8)
    general = group(page, "General")
    row = box(False, 16)
    call field(row, "App name", "", "d_title")
    call field(row, "Version", "", "d_version")
    call gtk.widget_set_size_request(ui["d_version"], 110, -1)
    call pack(general, row)
    call field(general, "Summary", "", "d_summary")
    row2 = box(False, 16)
    column = box(True, 6)
    call pack(column, label("Category", "field-label"))
    ui["d_category"] = gtk.combo_box_text_new()
    names = {"Utility": "Utilities", "Development": "Development", "Graphics": "Graphics", "Office": "Office", "Education": "Education", "Game": "Games", "Network": "Internet", "AudioVideo": "Sound & Video", "System": "System"}
    for key in projects.CATEGORIES:
        call gtk.combo_box_text_append(ui["d_category"], key, T(names[key]))
    end
    call pack(column, ui["d_category"])
    call pack(row2, column, True)
    column = box(True, 6)
    call pack(column, label("Package name", "field-label"))
    ui["d_name"] = label("", "dim")
    call gtk.widget_set_margins(ui["d_name"], 0, 0, 6, 0)
    call pack(column, ui["d_name"])
    call pack(row2, column, True)
    column = box(True, 6)
    call pack(column, label("Type", "field-label"))
    ui["d_type"] = label("", "dim")
    call gtk.widget_set_margins(ui["d_type"], 0, 0, 6, 0)
    call pack(column, ui["d_type"])
    call pack(row2, column, True)
    call pack(general, row2)
    for key in ["d_title", "d_version", "d_summary"]:
        call native.connect(ui[key], "changed", details_changed, None)
    end
    call native.connect(ui["d_category"], "changed", details_changed, None)
    save = button("Save", "save", "suggested-action")
    call gtk.widget_set_halign(save, 2)
    call pack(general, save)
    call spacer(page, 6)
    icon = group(page, "Icon")
    row = box(False, 18)
    ui["icon_preview"] = gtk.image_new_from_icon_name("application-x-executable", 6)
    call gtk.widget_set_size_request(ui["icon_preview"], 96, 96)
    call pack(row, ui["icon_preview"])
    column = box(True, 8)
    call gtk.widget_set_valign(column, 3)
    call pack(column, label("SVG or PNG, at least 256 × 256 pixels.", "dim", True))
    buttons = box(False, 8)
    ui["icon_choose"] = button("Choose Image…", "icon_choose")
    ui["icon_design"] = button("Design in Icon Studio", "icon_design")
    call pack(buttons, ui["icon_choose"])
    call pack(buttons, ui["icon_design"])
    call pack(column, buttons)
    call pack(row, column, True)
    call pack(icon, row)
    call spacer(page, 6)
    share = group(page, "Install and Share")
    ui["install_state"] = label("", "dim", True)
    call pack(share, ui["install_state"])
    buttons = box(False, 8)
    ui["install_button"] = button("Install on This Computer", "install", "suggested-action")
    ui["export_button"] = button("Export .lux Package…", "export")
    call pack(buttons, ui["install_button"])
    call pack(buttons, ui["export_button"])
    call pack(share, buttons)
    return page
end

function sidebar():
    rail = box(True, 0, "studio-sidebar")
    call gtk.widget_set_size_request(rail, 200, -1)
    inside = box(True, 2)
    call gtk.widget_set_margins(inside, 8, 8, 12, 12)
    head = box(False, 4)
    call pack(head, label("Files", "sidebar-caption"), True)
    call pack(head, icon_button("list-add-symbolic", "New file", "new_file", "flat"))
    call pack(inside, head)
    ui["new_file_revealer"] = gtk.revealer_new()
    ui["new_file_entry"] = gtk.entry_new()
    call gtk.entry_set_placeholder_text(ui["new_file_entry"], T("name, e.g. helpers"))
    call native.connect(ui["new_file_entry"], "activate", clicked, "new_file_add")
    call gtk.widget_set_margins(ui["new_file_entry"], 4, 4, 2, 4)
    call gtk.container_add(ui["new_file_revealer"], ui["new_file_entry"])
    call pack(inside, ui["new_file_revealer"])
    ui["files"] = box(True, 2)
    call pack(inside, ui["files"])
    call spacer(inside, 14)
    call pack(inside, label("App", "sidebar-caption"))
    call spacer(inside, 2)
    ui["nav_details"] = nav_button("details", "preferences-system-symbolic", "Name, Icon and Install")
    call pack(inside, ui["nav_details"])
    call pack(rail, inside, True)
    return rail
end

function header_menu():
    menu = native.menu_new()
    ui["menu_new"] = native.menu_item(menu, T("New Project…"), clicked, "create")
    ui["menu_open"] = native.menu_item(menu, T("Open Project…"), clicked, "open")
    call native.menu_separator(menu)
    ui["menu_build"] = native.menu_item(menu, T("Build") + "   Ctrl+B", clicked, "build")
    ui["menu_install"] = native.menu_item(menu, T("Install on This Computer"), clicked, "install")
    ui["menu_export"] = native.menu_item(menu, T("Export .lux Package…"), clicked, "export")
    call native.menu_separator(menu)
    ui["menu_icon"] = native.menu_item(menu, T("Design in Icon Studio"), clicked, "icon_design")
    ui["menu_edit"] = native.menu_item(menu, T("Open in LSL IDE"), clicked, "edit")
    ui["menu_folder"] = native.menu_item(menu, T("Show Project Folder"), clicked, "folder")
    return native.menu_button("open-menu-symbolic", menu)
end

function new_window():
    call glib.set_prgname("luxos-app-studio")
    call gtk.init()
    call gtk.css_load(CSS)
    window = gtk.window_new("App Studio")
    ui["window"] = window
    call gtk.widget_add_class(window, "app-studio")
    call gtk.window_set_default_size(window, 1120, 760)
    call gtk.window_set_icon_name(window, "luxos-app-studio")
    call __lsl_qbe_call3(__lsl_symbol("gtk_window_set_wmclass"), native.ptr(window), native.cstr("luxos-app-studio"), native.cstr("luxos-app-studio"))
    # Hlavicka jako ostatni aplikace LuxOS: tlacitka okna podle motivu, Spustit/Zastavit vlevo, nabidka vpravo
    header = __lsl_qbe_call0(__lsl_symbol("gtk_header_bar_new"))
    ui["header"] = header
    call __lsl_qbe_call2(__lsl_symbol("gtk_header_bar_set_show_close_button"), native.ptr(header), 1)
    call __lsl_qbe_call2(__lsl_symbol("gtk_window_set_titlebar"), native.ptr(window), native.ptr(header))
    ui["run"] = icon_button("media-playback-start-symbolic", "Run · Ctrl+R", "run")
    ui["stop"] = icon_button("media-playback-stop-symbolic", "Stop · Esc", "stop")
    call __lsl_qbe_call2(__lsl_symbol("gtk_header_bar_pack_start"), native.ptr(header), native.ptr(ui["run"]))
    call __lsl_qbe_call2(__lsl_symbol("gtk_header_bar_pack_start"), native.ptr(header), native.ptr(ui["stop"]))
    call __lsl_qbe_call2(__lsl_symbol("gtk_header_bar_pack_end"), native.ptr(header), native.ptr(header_menu()))
    ui["stack"] = __lsl_qbe_call0(__lsl_symbol("gtk_stack_new"))
    call __lsl_qbe_call2(__lsl_symbol("gtk_stack_set_transition_type"), native.ptr(ui["stack"]), 1)
    for name in ["welcome", "create"]:
        page = welcome_page()
        if name == "create":
            page = new_page()
        end
        scroll = gtk.scrolled_window_new()
        call gtk.scrolled_window_set_policy(scroll, 2, 1)
        call gtk.container_add(scroll, page)
        call __lsl_qbe_call3(__lsl_symbol("gtk_stack_add_named"), native.ptr(ui["stack"]), native.ptr(scroll), native.cstr(name))
    end
    workspace = box(False, 0)
    call pack(workspace, sidebar())
    ui["main"] = __lsl_qbe_call0(__lsl_symbol("gtk_stack_new"))
    call __lsl_qbe_call3(__lsl_symbol("gtk_stack_add_named"), native.ptr(ui["main"]), native.ptr(editor_page()), native.cstr("editor"))
    scroll = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(scroll, 2, 1)
    call gtk.container_add(scroll, details_page())
    call __lsl_qbe_call3(__lsl_symbol("gtk_stack_add_named"), native.ptr(ui["main"]), native.ptr(scroll), native.cstr("details"))
    call pack(workspace, ui["main"], True)
    call __lsl_qbe_call3(__lsl_symbol("gtk_stack_add_named"), native.ptr(ui["stack"]), native.ptr(workspace), native.cstr("workspace"))
    call gtk.container_add(window, ui["stack"])
    call native.connect(window, "delete-event", close, None, 1)
    call native.connect(window, "key-press-event", key_pressed, None, 1)
    call glib.unix_signal_add(2, signal_close)
    call glib.unix_signal_add(15, signal_close)
    call gtk.widget_show_all(window)
    call hide_bar()
    call show_page("welcome")
    call sensitivity(False)
    return window
end

function signal_close():
    if not ui["alive"]:
        return False
    end
    call close(None, 0, ui["window"])
    call gtk.widget_destroy(ui["window"])
    return False
end

function run(project_path=""):
    call new_window()
    if project_path:
        try:
            call update_project(projects.open_project(project_path))
        else:
            call error(String(last_error()))
        end
    end
    call gtk.main()
end
