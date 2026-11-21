# LuxOS - Nastaveni > Zpristupneni: omezit pohyb, velikost textu a kurzoru, na X11 lepkave/pomale/odskakujici
# klavesy, mys z klavesnice a klavesnice na obrazovce. Nahrazuje xfce4-accessibility-settings.
# Omezit pohyb: Gtk/EnableAnimations v xsettings (GTK aplikace, Launchpad, kolecko luxos-scroll, posun ploch
# xfwm4 na X11), na Waylandu GSettings enable-animations a reduce_motion v luxwm.conf (posun ploch luxwm).
# Klavesy pro zpristupneni umi jen X11 (xfsettingsd podle kanalu accessibility); luxcomp zatim nema XKB
# AccessX, na Waylandu se proto nenabizi. Vysoky kontrast LuxOS nenabizi: lista, Dock a zahlavi oken luxwm
# kresli vlastni barvy (luxos_tokens) a tema HighContrast by zmenilo jen cast aplikaci.
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_look as look
load luxos_page_appearance as appearance
load luxos_settings_ui as ui

A11Y = "accessibility"
KEYS = [["/StickyKeys", "Sticky Keys", "Modifier keys such as Shift and Ctrl stay pressed until the next key, so shortcuts can be typed one key at a time."],
    ["/SlowKeys", "Slow Keys", "A key has to be held for a moment before it is accepted."],
    ["/BounceKeys", "Bounce Keys", "Quickly repeated presses of the same key are ignored."]]

function on_reduce_motion(unused, on):
    call look.xf_set("xsettings", "/Gtk/EnableAnimations", "bool", "false" if on else "true")
    call look.gs_bool("enable-animations", not on)
    call look.wm_save({"reduce_motion": "yes" if on else None})
    return 0
end

function on_key(prop, on):
    return look.xf_set(A11Y, prop, "bool", "true" if on else "false")
end

function on_keyboard(unused, button):
    return ui.launch(["onboard"])
end

function build(host):
    page = ui.page_box()
    xs = look.channel("xsettings")
    g = ui.group(page, i18n.T("Display"))
    call ui.row(g, i18n.T("Reduce motion"),
                i18n.T("Turns off sliding between workspaces and animations in apps."),
                ui.switch(xs.get("/Gtk/EnableAnimations", "true") == "false", on_reduce_motion, 0))
    call ui.row(g, i18n.T("Text size"), "", appearance.text_size_combo())
    call ui.row(g, i18n.T("Pointer size"), "", appearance.pointer_size_combo(look.cursor()[1]))
    if ui.wayland():
        return page
    end
    a11y = look.channel(A11Y)
    g = ui.group(page, i18n.T("Keyboard"))
    for item in KEYS:
        call ui.row(g, i18n.T(item[1]), i18n.T(item[2]), ui.switch(a11y.get(item[0], "false") == "true", on_key, item[0]))
    end
    call ui.row(g, i18n.T("Mouse Keys"), i18n.T("Move the pointer with the numeric keypad."),
                ui.switch(a11y.get("/MouseKeys", "false") == "true", on_key, "/MouseKeys"))
    # onboard pise jen do aplikaci X11
    if glib.find_program_in_path("onboard") != "":
        show = gtk.button_new(i18n.T("Show"))
        call glib.connect_data(show, "clicked", 0, on_keyboard, 0)
        call ui.row(g, i18n.T("On-screen keyboard"), "", show)
    end
    return page
end

function test(command, rest):
    return False
end
