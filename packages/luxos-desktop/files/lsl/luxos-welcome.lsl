# LuxOS - Uvitani: po prvnim prihlaseni (po Prohlidce) a na live ISO. Logo, zakladni zkratky a tlacitka Tmavy rezim,
# Obchod, Aktualizovat, Prihlasit se k LuxAI, Prohlidka, Zkratky a Zavrit (na live ISO Nainstalovat LuxOS). Drive
# yad (bash): sedm tlacitek v jedne rade roztahlo okno na Waylandu pres 1260 px; tady dve rady jako v okne
# O tomto pocitaci. Po zavreni ~/.config/luxos/welcome-done (relace ho pak znovu neotevre).
# Testy: LUXOS_UI_TEST (luxos_settings_ui), LUXOS_WELCOME_LIVE=1 jako na live ISO.
load env
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_settings_ui as ui

CSS = ".welcome-title { font-size: 24px; font-weight: 700; }\n.welcome-dim { opacity: 0.7; }\n"
COLUMNS = 4

cfg = glib.user_config_dir() + "/luxos"
state = {"window": 0, "dark": False, "theme": 0, "luxai": 0}

function live():
    return exists("/run/archiso") or env.get("LUXOS_WELCOME_LIVE", "") == "1"
end

function signed_in():
    return glib.read_text(glib.user_config_dir() + "/luxai/account.json").strip() != ""
end

function theme_text():
    return i18n.T("Light Mode") if state["dark"] else i18n.T("Dark Mode")
end

function finish():
    call ui.touch(cfg + "/welcome-done")
    call gtk.main_quit()
    return 0
end

function on_install(button):
    call ui.launch(["luxos-install-gui"])
    return finish()
end

function on_theme(button):
    state["dark"] = not state["dark"]
    call ui.launch(["luxos-appearance", "toggle"])
    call gtk.button_set_label(button, theme_text())
    return 0
end

function on_store(button):
    return ui.launch(["luxos-store"])
end

function on_update(button):
    return ui.launch(["luxos-update"])
end

function on_luxai(button):
    return ui.launch(["luxos-account", "login"])
end

function on_tour(button):
    return ui.launch(["luxos-tour"])
end

function on_shortcuts(button):
    return ui.launch(["luxos-shortcuts"])
end

function on_close(button):
    return finish()
end

# Zavreni okna (i krizkem): stejne jako Zavrit
function on_destroy(window):
    return finish()
end

# Prihlaseni k LuxAI bezi v jinem okne: po navratu tlacitko zmizi
function on_focus(event, window):
    if state["luxai"] != 0 and signed_in():
        call gtk.widget_hide(state["luxai"])
    end
    return False
end

function button(text, icon, handler):
    b = gtk.button_new(text)
    image = gtk.image_new_from_icon_name(icon, gtk.ICON_MENU)
    # ikony aplikaci jen ve velkych PNG by GTK nezmensilo
    call gtk.image_set_pixel_size(image, 16)
    call gtk.button_set_image(b, image)
    call gtk.button_set_always_show_image(b, True)
    call gtk.connect(b, "clicked", handler)
    return b
end

function shortcut_lines():
    rows = [["Super + Space", i18n.T("Search: apps, files and windows")],
            ["Super, Super + A", i18n.T("Launchpad: all applications")],
            ["Super + Q", i18n.T("close window")],
            ["Super + Shift + 4", i18n.T("screenshot of a region")],
            ["lux", i18n.T("install and update software from Terminal")]]
    return "\n".join(["<b>" + glib.markup_escape(r[0]) + "</b>  ·  " + glib.markup_escape(r[1]) for r in rows])
end

function welcome():
    call glib.set_prgname("luxos-welcome")
    call gtk.init()
    call gtk.css_load(CSS)
    state["dark"] = ui.run(["luxos-appearance", "status"]) == "dark"
    window = gtk.window_new(i18n.T("Welcome to LuxOS"))
    state["window"] = window
    call gtk.window_set_wmclass(window, "luxos-welcome", "luxos-welcome")
    call gtk.window_set_icon_list(window, "luxos-app")
    call gtk.window_set_resizable(window, False)
    call gtk.window_set_position(window, gtk.WIN_POS_CENTER)

    page = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_margins(page, 24, 24, 24, 24)
    head = gtk.box_new(gtk.HORIZONTAL, 22)
    logo = gtk.image_new_from_icon_name("luxos-app", gtk.ICON_DIALOG)
    call gtk.image_set_pixel_size(logo, 112)
    call gtk.widget_set_valign(logo, gtk.ALIGN_START)
    call gtk.box_pack_start(head, logo, False, False, 0)
    texts = gtk.box_new(gtk.VERTICAL, 10)
    call gtk.box_pack_start(texts, ui.label(i18n.T("Welcome to LuxOS"), "welcome-title"), False, False, 0)
    call gtk.box_pack_start(texts, ui.label(i18n.T("Fast, light and beautifully simple."), "welcome-dim"), False, False, 0)
    keys = ui.label("", "")
    call gtk.label_set_markup(keys, shortcut_lines())
    call gtk.label_set_line_wrap(keys, False)
    call gtk.box_pack_start(texts, keys, False, False, 4)
    call gtk.box_pack_start(head, texts, True, True, 0)
    call gtk.box_pack_start(page, head, False, False, 0)

    buttons = []
    if live():
        buttons.append(button(i18n.T("Install LuxOS"), "luxos-installer", on_install))
    end
    state["theme"] = button(theme_text(), "preferences-desktop-theme", on_theme)
    buttons.append(state["theme"])
    if not live():
        buttons.append(button(i18n.T("LuxOS Store"), "luxos-store", on_store))
        buttons.append(button(i18n.T("Update"), "system-software-update", on_update))
        if not signed_in():
            state["luxai"] = button(i18n.T("Sign in to LuxAI"), "luxos-app", on_luxai)
            buttons.append(state["luxai"])
        end
    end
    buttons.append(button(i18n.T("LuxOS Tour"), "luxos-tour", on_tour))
    buttons.append(button(i18n.T("Shortcuts"), "shortcuts", on_shortcuts))
    close = button(i18n.T("Close"), "window-close", on_close)
    buttons.append(close)
    # tlacitka v mrizce po ctyrech (stejne siroka), okno tak zustane kolem 660 px jako v X11
    grid = gtk.grid_new()
    call gtk.grid_set_column_homogeneous(grid, True)
    call gtk.grid_set_column_spacing(grid, 8)
    call gtk.grid_set_row_spacing(grid, 8)
    call gtk.widget_set_margins(grid, 0, 0, 22, 0)
    for i in range(len(buttons)):
        call gtk.grid_attach(grid, buttons[i], i % COLUMNS, i // COLUMNS, 1, 1)
    end
    call gtk.box_pack_start(page, grid, False, False, 0)

    call gtk.container_add(window, page)
    call gtk.connect(window, "destroy", on_destroy)
    call gtk.connect(window, "focus-in-event", on_focus)
    call ui.attach_test(window)
    call gtk.widget_show_all(window)
    call gtk.widget_grab_focus(close)
    call gtk.main()
    return 0
end

call exit(welcome())
