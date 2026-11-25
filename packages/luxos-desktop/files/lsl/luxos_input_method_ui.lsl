# LuxOS - Nastaveni > Klavesnice > Rozlozeni: skupina Metody zadavani (psani vietnamsky pres fcitx5 + Bamboo).
# Spolecna pro X11 i Wayland. Vse dela pomocnik luxos-input-method (luxos_input_method.py): status, enable vi
# [--style S], disable, style S. Plati jen pro tento ucet a hned, bez overeni spravce. Pomocnik bezi asynchronne
# (fcitx5 se pri zmene restartuje), prepinac a volba se mezitim zamknou a po dobehu ukazou skutecny stav.
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_settings_ui as ui

STYLES = ["Telex", "VNI", "VIQR"]
HELPER = "luxos-input-method"
IM = {"switch": 0, "style": 0, "status": 0, "busy": False, "active": "none", "style_id": "Telex",
      "installed": True, "on_resize": None, "message": ""}

function parse_status(text):
    info = {"active": "none", "style": "Telex", "installed": True}
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("input-method:"):
            info["active"] = line[13:].strip()
        elif line.startswith("style:"):
            info["style"] = line[6:].strip()
        elif line.startswith("installed:"):
            info["installed"] = line[10:].strip() == "yes"
        end
    end
    return info
end

# Stavovy radek zabira misto jen s textem (prazdny by nechal mezeru pod skupinou)
function set_message(text):
    IM["message"] = text
    label = IM["status"]
    if label == 0:
        return 0
    end
    call gtk.label_set_text(label, text)
    if text == "":
        call gtk.widget_hide(label)
    else:
        call gtk.widget_show(label)
        callback = IM["on_resize"]
        if callback != None:
            call callback()
        end
    end
    return 0
end

function sync_widgets():
    if IM["switch"] == 0:
        return 0
    end
    on = IM["active"] == "vi"
    call ui.switch_set(IM["switch"], on)
    call gtk.widget_set_sensitive(IM["switch"], IM["installed"] and not IM["busy"])
    style = IM["style_id"]
    if not (style in STYLES):
        style = "Telex"
    end
    call ui.combo_set_active_id(IM["style"], style)
    call gtk.widget_set_sensitive(IM["style"], on and not IM["busy"])
    return 0
end

function on_status(unused, output, status):
    info = parse_status(output)
    IM["active"] = info["active"]
    IM["style_id"] = info["style"]
    IM["installed"] = status == 0 and info["installed"]
    IM["busy"] = False
    call sync_widgets()
    if not IM["installed"]:
        call set_message(i18n.T("Not installed (packages fcitx5, fcitx5-gtk and fcitx5-bamboo)."))
    elif IM["active"] == "user" and IM["message"] == "":
        call set_message(i18n.T("Your account uses its own fcitx5 settings. Turning Vietnamese on adds it to them."))
    end
    return 0
end

function refresh():
    if glib.spawn_capture([HELPER, "status"], on_status, 0) == 0:
        IM["installed"] = False
        call sync_widgets()
    end
    return 0
end

# Po zmene: zprava podle vysledku, pak skutecny stav z pomocnika
function on_done(message, output, status):
    if status == 0:
        call set_message(message)
    else:
        detail = output.strip()
        if detail == "":
            detail = HELPER
        end
        call set_message(i18n.T("Could not change the input method: %s").replace("%s", detail))
    end
    call refresh()
    return 0
end

function run(argv, message):
    if IM["busy"]:
        return 0
    end
    IM["busy"] = True
    call sync_widgets()
    # stderr pomocnika do vystupu (chybova zprava)
    if glib.spawn_capture(["sh", "-c", "exec \"$0\" \"$@\" 2>&1"] + argv, on_done, message) == 0:
        IM["busy"] = False
        call on_done(message, HELPER, 1)
    end
    return 0
end

function on_switch(unused, on):
    if IM["busy"]:
        return 0
    end
    if on:
        style = ui.combo_active_id(IM["style"])
        argv = [HELPER, "enable", "vi"]
        if style in STYLES:
            argv = argv + ["--style", style]
        end
        call run(argv, i18n.T("Vietnamese is on. Switch with Ctrl+Space. Apps that were already open start using it after you restart them."))
    else:
        call run([HELPER, "disable"], i18n.T("Vietnamese is off."))
    end
    return 0
end

function on_style(unused, style):
    if IM["busy"] or not (style in STYLES) or IM["active"] != "vi":
        return 0
    end
    call run([HELPER, "style", style], i18n.T("Typing style: %s").replace("%s", style))
    return 0
end

# Zapnuti z dialogu Pridat rozlozeni (polozka Vietnamstina)
function enable_from_dialog():
    if IM["switch"] != 0 and IM["active"] != "vi" and not IM["busy"]:
        call ui.switch_set(IM["switch"], True)
        call on_switch(0, True)
    end
    return 0
end

function active():
    return IM["active"] == "vi"
end

# Skupina na strance; on_resize = funkce bez argumentu, ktera okno zvetsi podle obsahu (nebo None)
function build(page, on_resize):
    IM["on_resize"] = on_resize
    IM["busy"] = False
    IM["message"] = ""
    g = ui.group(page, i18n.T("Input Methods"))
    IM["switch"] = ui.switch(False, on_switch, 0)
    call ui.row(g, i18n.T("Vietnamese"), i18n.T("Type Vietnamese on your keyboard, for example Vieejt Nam → Việt Nam. Turn it on and off with Ctrl+Space or the icon in the menu bar."), IM["switch"])
    IM["style"] = ui.combo([[s, s] for s in STYLES], "Telex", "", on_style, 0)
    call ui.row(g, i18n.T("Typing style"), i18n.T("Telex types accents with letters (aa → â, s → ´), VNI with numbers (a6 → â, 1 → ´)."), IM["style"])
    status = ui.label("", "hint")
    call gtk.label_set_max_width_chars(status, 60)
    call gtk.widget_set_margins(status, 4, 0, 6, 0)
    call gtk.widget_set_no_show_all(status, True)
    IM["status"] = status
    call gtk.box_pack_start(page, status, False, False, 0)
    call sync_widgets()
    call refresh()
    return g
end

# Polozka do hledani v dialogu Pridat rozlozeni: [popisek, text k hledani]; None, kdyz uz je zapnuta
function dialog_item():
    if IM["active"] == "vi" or not IM["installed"]:
        return None
    end
    name = i18n.T("%s (Telex, VNI)").replace("%s", i18n.T("Vietnamese"))
    return [name + "   " + i18n.T("input method"), (name + " vietnamese vietnam telex vni viqr tieng viet vi").lower()]
end
