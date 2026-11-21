# LuxOS - Nastaveni > Mys a touchpad (drive luxos-scrolling): rychlost ukazatele, smer posouvani, primarni tlacitko,
# klepnuti, posouvani a kliknuti na touchpadu, plynule kolecko a setrvacnost.
# Wayland: polozky mouse_* a touchpad_* v ~/.config/luxwm/luxwm.conf; luxwm je po reload hned pouzije na vsechna
# zarizeni libinput (i pozdeji pripojena), co zarizeni skutecne maji, vraci jeho IPC get_input.
# X11: hned xinput (vlastnosti xf86-input-libinput) a trvale kanal xfconf pointers po zarizenich jako dialog Xfce;
# xfsettingsd ho pouzije po prihlaseni i po znovupripojeni zarizeni a zadny dalsi proces relace neni potreba.
# luxwm.conf se zapise i na X11, aby relace na Waylandu mela stejne nastaveni.
# Hodnota, ktera v luxwm.conf neni, se ukaze podle prvniho zarizeni toho druhu (jinak vychozi libinput).
# Posouvani: ~/.config/luxos/scrolling.conf ([scrolling] smooth_wheel, kinetic) pro modul GTK luxos-scroll,
# aplikace soubor sleduji a zmena plati hned i v otevrenych oknech.
#
#   luxos-scrolling status               vypise smooth_wheel=... a kinetic=...
#   luxos-scrolling smooth-wheel on|off  plynule kolecko
#   luxos-scrolling kinetic on|off       setrvacnost touchpadu
# Testy: page-state (hodnoty, zarizeni, viditelnost touchpadu).
load json
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_luxwm as wm
load luxos_wm_config as cfg
load luxos_settings_ui as ui
load luxos_sys as sys

SCROLL_KEYS = ["smooth_wheel", "kinetic"]
# Vychozi hodnoty libinput pro zarizeni, ktere volbu nema nebo jeste neodpovedelo
DEFAULTS = {"speed": 0, "accel": "adaptive", "natural_scroll": False, "left_handed": False, "middle_emulation": False,
            "tap": False, "tap_drag": True, "disable_while_typing": True, "click_method": "areas", "scroll_method": "two_finger"}
# Vlastnosti xf86-input-libinput; vice hodnot = jedna z voleb v tomto poradi
XPROPS = {"speed": "libinput Accel Speed", "accel": "libinput Accel Profile Enabled",
          "natural_scroll": "libinput Natural Scrolling Enabled", "left_handed": "libinput Left Handed Enabled",
          "middle_emulation": "libinput Middle Emulation Enabled", "tap": "libinput Tapping Enabled",
          "tap_drag": "libinput Tapping Drag Enabled", "disable_while_typing": "libinput Disable While Typing Enabled",
          "click_method": "libinput Click Method Enabled", "scroll_method": "libinput Scroll Method Enabled"}
XFCONF_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
XCHOICES = {"accel": ["adaptive", "flat"], "click_method": ["areas", "clickfinger"],
            "scroll_method": ["two_finger", "edge", "button"]}

P = {"wayland": False, "conf": {}, "devices": [], "values": {}, "widgets": {}, "touchpad": 0, "tries": 0}

# ---- posouvani (scrolling.conf) ---------------------------------------------------------------------------

function scroll_dir():
    return glib.user_config_dir() + "/luxos"
end

function scroll_path():
    return scroll_dir() + "/scrolling.conf"
end

# Chybejici soubor nebo klic = zapnuto (stejne jako modul luxos-scroll)
function read_scroll():
    values = {"smooth_wheel": True, "kinetic": True}
    section = ""
    for raw in glib.read_text(scroll_path()).split("\n"):
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:len(line) - 1].strip()
        elif section == "scrolling" and "=" in line and not line.startswith("#"):
            cut = line.find("=")
            key = line[0:cut].strip()
            value = on_off(line[cut + 1:].strip().lower())
            if key in values and value != None:
                values[key] = value
            end
        end
    end
    return values
end

function write_scroll(values):
    call sys.mkdir_p(scroll_dir())
    text = "# LuxOS - posouvani (Nastaveni > Mys a touchpad); chybejici klic = zapnuto\n[scrolling]\n"
    for key in SCROLL_KEYS:
        text = text + key + "=" + ("true" if values[key] else "false") + "\n"
    end
    # atomicky: aplikace nikdy neprectou pulku souboru
    return glib.write_atomic(scroll_path(), text)
end

function set_scroll(key, value):
    values = read_scroll()
    values[key] = value
    return write_scroll(values)
end

function on_off(value):
    if value in ["on", "true", "1", "yes"]:
        return True
    end
    if value in ["off", "false", "0", "no"]:
        return False
    end
    return None
end

# ---- hodnoty ------------------------------------------------------------------------------------------------

# Text z luxwm.conf -> hodnota (None = neni nastaveno nebo spatne)
function parse(option, text):
    if text == "":
        return None
    end
    if option == "speed":
        value = None
        safe:
            value = max(-100, min(100, Int(text)))
        end
        return value
    end
    if option in XCHOICES:
        return text
    end
    return on_off(text)
end

function conf_text(option, value):
    if option == "speed":
        return String(value)
    end
    if option in XCHOICES:
        return value
    end
    return "yes" if value else "no"
end

function current(kind, option):
    value = parse(option, P["conf"].get(kind + "_" + option, "").strip())
    if value != None:
        return value
    end
    for d in P["devices"]:
        if d["kind"] == kind and option in d:
            return d[option]
        end
    end
    return DEFAULTS[option]
end

function load_conf():
    conf = cfg.system_conf()["general"]
    conf.update(cfg.user_conf()["general"])
    P["conf"] = conf
end

# ---- X11: xinput a xfconf pointers -------------------------------------------------------------------------

# {"id", "name", "props": {nazev: [hodnoty]}} pro zarizeni s ovladacem libinput (bez XTEST a hlavnich zarizeni)
function x11_devices():
    out = []
    names = ui.run(["xinput", "list", "--name-only"]).split("\n")
    ids = ui.run(["xinput", "list", "--id-only"]).split("\n")
    for i in range(min(len(names), len(ids))):
        name = names[i].strip()
        if name == "" or name.find("XTEST") >= 0 or ids[i].strip() == "":
            continue
        end
        props = {}
        for raw in ui.run(["xinput", "list-props", ids[i].strip()]).split("\n"):
            line = raw.strip()
            cut = line.find(" (")
            colon = line.find(":")
            if cut > 0 and colon > cut:
                props[line[:cut]] = [v.strip() for v in line[colon + 1:].split(",")]
            end
        end
        kind = ""
        if XPROPS["tap"] in props:
            kind = "touchpad"
        elif XPROPS["speed"] in props or XPROPS["natural_scroll"] in props:
            kind = "mouse"
        end
        if kind != "":
            d = {"id": ids[i].strip(), "name": name, "kind": kind, "props": props}
            for option in XPROPS.keys():
                if XPROPS[option] in props:
                    d[option] = x11_value(option, props[XPROPS[option]])
                end
            end
            out.append(d)
        end
    end
    return out
end

function x11_value(option, values):
    if option == "speed":
        f = 0.0
        safe:
            f = Float(values[0])
        end
        return Int(f * 100 - 0.5) if f < 0 else Int(f * 100 + 0.5)
    end
    if option in XCHOICES:
        for i in range(min(len(values), len(XCHOICES[option]))):
            if values[i] == "1":
                return XCHOICES[option][i]
            end
        end
        return "none"
    end
    return values[0] == "1"
end

# -35 -> "-0.35" (xinput i xfconf chteji desetinne cislo)
function speed_text(value):
    a = abs(value)
    frac = String(a % 100)
    if len(frac) < 2:
        frac = "0" + frac
    end
    return ("-" if value < 0 else "") + String(a // 100) + "." + frac
end

# Nazev zarizeni v kanalu pointers jako v xfsettingsd: pismena, cisla, _ a -, mezera = _
function xfconf_name(name):
    out = ""
    for i in range(len(name)):
        ch = name[i]
        if ch == " ":
            out += "_"
        elif XFCONF_CHARS.find(ch) >= 0:
            out += ch
        end
    end
    return out
end

function x11_apply(kind, option, value):
    prop = XPROPS[option]
    for d in P["devices"]:
        if d["kind"] != kind or not (prop in d["props"]):
            continue
        end
        values = []
        kinds = []
        if option == "speed":
            values = [speed_text(value)]
            kinds = ["double"]
        elif option in XCHOICES:
            for i in range(len(d["props"][prop])):
                values.append("1" if i < len(XCHOICES[option]) and XCHOICES[option][i] == value else "0")
                kinds.append("int")
            end
        else:
            values = ["1" if value else "0"]
            kinds = ["int"]
        end
        call ui.run(["xinput", "set-prop", d["id"], prop] + values)
        base = "/" + xfconf_name(d["name"])
        argv = ["xfconf-query", "-c", "pointers", "-p", base + "/Properties/" + prop.replace(" ", "_"), "-n"]
        if len(values) > 1:
            argv.append("-a")
        end
        for i in range(len(values)):
            argv = argv + ["-t", kinds[i], "-s", values[i]]
        end
        call ui.run(argv)
        # stejne volby dialogu Xfce, at je xfsettingsd po prihlaseni nepouzije v opacnem smyslu
        if option == "natural_scroll":
            call ui.run(["xfconf-query", "-c", "pointers", "-p", base + "/ReverseScrolling", "-n", "-t", "bool", "-s", "true" if value else "false"])
        elif option == "left_handed":
            call ui.run(["xfconf-query", "-c", "pointers", "-p", base + "/RightHanded", "-n", "-t", "bool", "-s", "false" if value else "true"])
        end
    end
end

# ---- zmena -------------------------------------------------------------------------------------------------

function on_change(key, value):
    if P["values"].get(key, None) == value:
        return 0
    end
    P["values"][key] = value
    cut = key.find("_")
    kind = key[:cut]
    option = key[cut + 1:]
    text = conf_text(option, value)
    P["conf"][key] = text
    call cfg.save({key: text}, {})
    if P["wayland"]:
        call wm.request({"cmd": "reload"}, None)
    else:
        call x11_apply(kind, option, value)
    end
    return 0
end

function on_speed(key, value):
    return on_change(key, value)
end

function on_switch(key, on):
    return on_change(key, on)
end

function on_accel(key, on):
    return on_change(key, "adaptive" if on else "flat")
end

function on_combo(key, id):
    if key == "mouse_left_handed":
        return on_change(key, id == "right")
    end
    return on_change(key, id)
end

function on_scroll_switch(key, on):
    call set_scroll(key, on)
    return 0
end

# ---- stranka -----------------------------------------------------------------------------------------------

function slider_row(g, kind, title):
    key = kind + "_speed"
    P["values"][key] = current(kind, "speed")
    box = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.box_pack_start(box, ui.label(i18n.T("Slow"), "hint"), False, False, 0)
    s = ui.slider(-100, 100, P["values"][key], 200, on_speed, key)
    P["widgets"][key] = s
    call gtk.box_pack_start(box, s, False, False, 0)
    call gtk.box_pack_start(box, ui.label(i18n.T("Fast"), "hint"), False, False, 0)
    call ui.row(g, title, "", box)
    # radek testctl (slider TITULEK = N) ukazuje na posuvnik, ne na box
    ui.state["rows"][title] = s
end

function switch_row(g, kind, option, title, hint):
    key = kind + "_" + option
    P["values"][key] = current(kind, option)
    sw = ui.switch(P["values"][key], on_switch, key)
    P["widgets"][key] = sw
    call ui.row(g, title, hint, sw)
end

function combo_row(g, kind, option, title, hint, options):
    key = kind + "_" + option
    P["values"][key] = current(kind, option)
    active = P["values"][key]
    if option == "left_handed":
        active = "right" if active else "left"
    end
    c = ui.combo(options, active, "", on_combo, key)
    P["widgets"][key] = c
    call ui.row(g, title, hint, c)
end

function build_mouse(page, scroll):
    g = ui.group(page, i18n.T("Mouse"))
    call slider_row(g, "mouse", i18n.T("Pointer speed"))
    P["values"]["mouse_accel"] = current("mouse", "accel")
    sw = ui.switch(P["values"]["mouse_accel"] != "flat", on_accel, "mouse_accel")
    P["widgets"]["mouse_accel"] = sw
    call ui.row(g, i18n.T("Pointer acceleration"), i18n.T("Faster movements move the pointer farther."), sw)
    call switch_row(g, "mouse", "natural_scroll", i18n.T("Natural wheel direction"), i18n.T("Content moves the same way as the wheel, like on a touchpad."))
    call combo_row(g, "mouse", "left_handed", i18n.T("Primary mouse button"), "",
                   [["left", i18n.T("Left button")], ["right", i18n.T("Right button")]])
    call switch_row(g, "mouse", "middle_emulation", i18n.T("Middle click with both buttons"), i18n.T("Pressing the left and right buttons together acts as the middle button."))
    call ui.row(g, i18n.T("Smooth scrolling with the mouse wheel"),
                i18n.T("The page glides to the new position instead of jumping. Off while animations are off (battery saver)."),
                ui.switch(scroll["smooth_wheel"], on_scroll_switch, "smooth_wheel"))
end

function build_touchpad(page, scroll):
    g = ui.group(page, i18n.T("Touchpad"))
    call slider_row(g, "touchpad", i18n.T("Tracking speed"))
    call switch_row(g, "touchpad", "tap", i18n.T("Tap to click"), i18n.T("A light tap clicks, a two-finger tap is a right click."))
    call switch_row(g, "touchpad", "tap_drag", i18n.T("Tap and drag"), i18n.T("Tap, then touch again and move to drag a window or select text."))
    call switch_row(g, "touchpad", "natural_scroll", i18n.T("Natural scrolling"), i18n.T("Content follows your fingers."))
    call combo_row(g, "touchpad", "scroll_method", i18n.T("Scroll with"), "",
                   [["two_finger", i18n.T("Two fingers")], ["edge", i18n.T("Right edge")]])
    call combo_row(g, "touchpad", "click_method", i18n.T("Right click"), "",
                   [["areas", i18n.T("Click in the bottom right corner")], ["clickfinger", i18n.T("Click with two fingers")]])
    call switch_row(g, "touchpad", "disable_while_typing", i18n.T("Ignore the touchpad while typing"), i18n.T("Prevents accidental clicks with your palm."))
    call ui.row(g, i18n.T("Inertia on the touchpad"),
                i18n.T("After a quick swipe on the touchpad the content keeps moving and slows down. Moving the pointer or clicking stops it."),
                ui.switch(scroll["kinetic"], on_scroll_switch, "kinetic"))
end

function has_touchpad():
    for d in P["devices"]:
        if d["kind"] == "touchpad":
            return True
        end
    end
    return False
end

function show_touchpad():
    box = P["touchpad"]
    on = has_touchpad()
    call gtk.widget_set_no_show_all(box, not on)
    if on:
        call gtk.widget_show_all(box)
    else:
        call gtk.widget_hide(box)
    end
end

# Hodnoty, ktere v luxwm.conf nejsou, podle zarizeni z odpovedi luxwm
function refresh_widgets():
    for key in P["widgets"].keys():
        cut = key.find("_")
        kind = key[:cut]
        option = key[cut + 1:]
        value = current(kind, option)
        if value == P["values"][key]:
            continue
        end
        P["values"][key] = value
        w = P["widgets"][key]
        if option == "speed":
            call gtk.range_set_value(w, Float(value))
        elif option == "accel":
            call ui.switch_set(w, value != "flat")
        elif option == "left_handed":
            ui.state["quiet"] = True
            call ui.combo_set_active_id(w, "right" if value else "left")
            ui.state["quiet"] = False
        elif option in XCHOICES:
            ui.state["quiet"] = True
            call ui.combo_set_active_id(w, value)
            ui.state["quiet"] = False
        else:
            call ui.switch_set(w, value)
        end
    end
end

function on_input(reply):
    if reply == None or not reply.get("ok", False):
        return 0
    end
    P["devices"] = reply.get("devices", [])
    call refresh_widgets()
    call show_touchpad()
    return 0
end

# Okno se k luxwm pripoji az po postaveni prvni stranky
function ask_input(unused):
    if wm.connected():
        call wm.request({"cmd": "get_input"}, on_input)
        return False
    end
    P["tries"] += 1
    return P["tries"] < 20
end

function build(host):
    P["wayland"] = host["wayland"]
    P["values"] = {}
    P["widgets"] = {}
    P["tries"] = 0
    P["devices"] = [] if P["wayland"] else x11_devices()
    call load_conf()
    scroll = read_scroll()
    page = ui.page_box()
    call build_mouse(page, scroll)
    box = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.box_pack_start(page, box, False, False, 0)
    P["touchpad"] = box
    call build_touchpad(box, scroll)
    call show_touchpad()
    if P["wayland"] and ask_input(0):
        call glib.timeout_add_data(250, ask_input, 0)
    end
    return page
end

# luxos-scrolling status | smooth-wheel on|off | kinetic on|off
function cli(args):
    if len(args) == 0:
        return None
    end
    command = args[0]
    if command == "status":
        values = read_scroll()
        for name in SCROLL_KEYS:
            call sys.out(name + "=" + ("true" if values[name] else "false") + "\n")
        end
        return 0
    end
    value = on_off(args[1]) if len(args) > 1 else None
    if (command == "smooth-wheel" or command == "kinetic") and value != None:
        name = "smooth_wheel" if command == "smooth-wheel" else "kinetic"
        if not set_scroll(name, value):
            call sys.eprint("luxos-scrolling: cannot write " + scroll_path())
            return 1
        end
        return 0
    end
    call sys.eprint("Usage: luxos-scrolling [status | smooth-wheel on|off | kinetic on|off]")
    return 2
end

function test(command, rest):
    if command == "page-state":
        devices = []
        for d in P["devices"]:
            item = {}
            for k in d.keys():
                if k != "props":
                    item[k] = d[k]
                end
            end
            devices.append(item)
        end
        call sys.out("page-state " + json.encode({"values": P["values"], "devices": devices, "touchpad": has_touchpad(),
                                                   "wayland": P["wayland"]}) + "\n")
        return True
    end
    return False
end
