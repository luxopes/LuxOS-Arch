# LuxOS - Nastaveni > Posouvani: plynule posouvani koleckem mysi a setrvacnost na touchpadu (modul GTK
# luxos-scroll v kazde aplikaci GTK 3, Firefox, Posta). Volby v ~/.config/luxos/scrolling.conf
# ([scrolling] smooth_wheel, kinetic); aplikace soubor sleduji, zmena plati hned i v otevrenych oknech.
#
#   luxos-scrolling                      okno nastaveni
#   luxos-scrolling status               vypise smooth_wheel=... a kinetic=...
#   luxos-scrolling smooth-wheel on|off  plynule kolecko
#   luxos-scrolling kinetic on|off       setrvacnost touchpadu
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_sys as sys

KEYS = ["smooth_wheel", "kinetic"]
CSS = ".group { border-radius: 12px; border: 1px solid alpha(currentColor, 0.12); background-color: alpha(currentColor, 0.04); }\n.group-title { font-weight: 700; font-size: 13px; margin: 14px 4px 6px; }\n.row { padding: 10px 14px; }\n.row-sep { border-top: 1px solid alpha(currentColor, 0.08); }\n.hint { font-size: 11px; opacity: 0.65; }\n"

function conf_dir():
    return glib.user_config_dir() + "/luxos"
end

function conf_path():
    return conf_dir() + "/scrolling.conf"
end

# Hodnoty z konfigurace; chybejici soubor nebo klic = zapnuto (stejne jako modul luxos-scroll)
function read_conf():
    values = {"smooth_wheel": True, "kinetic": True}
    section = ""
    for raw in glib.read_text(conf_path()).split("\n"):
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:len(line) - 1].strip()
        elif section == "scrolling" and "=" in line and not line.startswith("#"):
            cut = line.find("=")
            key = line[0:cut].strip()
            value = line[cut + 1:].strip().lower()
            if key in values:
                if value == "false" or value == "0" or value == "no" or value == "off":
                    values[key] = False
                elif value == "true" or value == "1" or value == "yes" or value == "on":
                    values[key] = True
                end
            end
        end
    end
    return values
end

function bool_text(value):
    if value:
        return "true"
    end
    return "false"
end

function write_conf(values):
    call sys.mkdir_p(conf_dir())
    text = "# LuxOS - posouvani (luxos-scrolling); chybejici klic = zapnuto\n[scrolling]\n"
    for key in KEYS:
        text = text + key + "=" + bool_text(values[key]) + "\n"
    end
    # atomicky (docasny soubor + prejmenovani): aplikace nikdy neprectou pulku souboru
    return glib.write_atomic(conf_path(), text)
end

function set_value(key, value):
    values = read_conf()
    values[key] = value
    return write_conf(values)
end

# ---- okno -------------------------------------------------------------------------------------------------

ui = {"switches": {}}

function label(text, css):
    l = gtk.label_new(text)
    call gtk.label_set_xalign(l, 0)
    call gtk.label_set_line_wrap(l, True)
    call gtk.label_set_max_width_chars(l, 52)
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
    box = gtk.box_new(gtk.HORIZONTAL, 12)
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

function switch_for(key, active):
    sw = gtk.switch_new()
    call gtk.switch_set_active(sw, active)
    ui["switches"][sw] = key
    call gtk.connect(sw, "state-set", on_switch)
    return sw
end

function on_switch(state, sw):
    if sw in ui["switches"]:
        call set_value(ui["switches"][sw], state != 0)
    end
    return False
end

function on_mouse_settings(button):
    call glib.spawn_quiet(["xfce4-mouse-settings"])
    return 0
end

function on_delete(event, window):
    call gtk.main_quit()
    return False
end

function settings():
    values = read_conf()
    call glib.set_prgname("luxos-scrolling")
    call gtk.init()
    call gtk.css_load(CSS)
    window = gtk.window_new(i18n.T("Scrolling"))
    call gtk.window_set_wmclass(window, "luxos-scrolling", "luxos-scrolling")
    call gtk.window_set_icon_list(window, "input-mouse")
    call gtk.window_set_default_size(window, 560, -1)
    call gtk.window_set_resizable(window, False)
    page = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_margins(page, 22, 22, 6, 22)

    g = group(page, i18n.T("Scrolling"))
    call row(g, i18n.T("Smooth scrolling with the mouse wheel"),
             i18n.T("The page glides to the new position instead of jumping. Off while animations are off (battery saver)."),
             switch_for("smooth_wheel", values["smooth_wheel"]))
    call row(g, i18n.T("Inertia on the touchpad"),
             i18n.T("After a quick swipe on the touchpad the content keeps moving and slows down. Moving the pointer or clicking stops it."),
             switch_for("kinetic", values["kinetic"]))

    g = group(page, i18n.T("Mouse and touchpad"))
    more = gtk.button_new(i18n.T("Open"))
    call gtk.connect(more, "clicked", on_mouse_settings)
    call row(g, i18n.T("Mouse and touchpad settings"),
             i18n.T("Pointer speed, scrolling direction, edge or two-finger scrolling, tap to click."), more)

    call gtk.box_pack_start(page, label(i18n.T("Changes apply right away, also in open windows. Firefox and Mail scroll smoothly by themselves."), "hint"), False, False, 16)
    call gtk.container_add(window, page)
    call gtk.connect(window, "delete-event", on_delete)
    call gtk.widget_show_all(window)
    call gtk.main()
    return 0
end

function on_off(value):
    if value == "on" or value == "true" or value == "1":
        return True
    end
    if value == "off" or value == "false" or value == "0":
        return False
    end
    return None
end

function main(command, value):
    if command == None or command == "settings":
        return settings()
    end
    if command == "status":
        current = read_conf()
        for name in KEYS:
            call sys.out(name + "=" + bool_text(current[name]) + "\n")
        end
        return 0
    end
    if (command == "smooth-wheel" or command == "kinetic") and on_off(value) != None:
        name = "kinetic"
        if command == "smooth-wheel":
            name = "smooth_wheel"
        end
        if not set_value(name, on_off(value)):
            call sys.eprint("luxos-scrolling: cannot write " + conf_path())
            return 1
        end
        return 0
    end
    call sys.eprint("Usage: luxos-scrolling [status | smooth-wheel on|off | kinetic on|off]")
    return 2
end

call exit(main(arg(1), arg(2)))
