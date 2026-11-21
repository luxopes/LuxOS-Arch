# LuxOS - Nastaveni > Vzhled: svetly/tmavy/automaticky rezim, ikony, kurzor, pisma, vyhlazovani a velikost textu.
# Nahrazuje xfce4-appearance-settings. Rezim jde pres luxos-appearance (X11 i Wayland), ostatni pres kanal
# xfconf xsettings (luxos_look: X11 xfconf-query, Wayland soubor kanalu + GSettings, kurzor i do luxwm).
# Barvu zvyrazneni ani jine tema aplikaci LuxOS nenabizi: WhiteSur je v baliku jen v modre variante
# a svetle/tmave tema prepina rezim.
load env
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load cairo
load luxos_date as date
load luxos_i18n as i18n
load luxos_text as text
load luxos_sun as sun
load luxos_look as look
load luxos_settings_ui as ui

MODES = [["light", "Light", ["#f5f6fb", "#d9dcea"]], ["dark", "Dark", ["#23243a", "#3a3c5c"]],
    ["auto", "Auto", ["#f5f6fb", "#d9dcea", "#23243a", "#3a3c5c"]]]
POINTER_SIZES = [["24", "Default"], ["32", "Large"], ["48", "Larger"], ["64", "Largest"]]
# sady ikon, ktere nejsou celym tematem (doplnky jinych sad, zalozni hicolor)
NOT_THEMES = ["hicolor", "locolor", "default"]
LUXOS_ICONS = "luxos"

app = {"modes": {}, "fonts": {}}

function on_off(on, yes, no):
    if on:
        return yes
    end
    return no
end

# ---- svetly / tmavy rezim (karty presunute ze stranky Plocha a Dock) -----------------------------------------

function hex_byte(pair):
    digits = "0123456789abcdef"
    return digits.find(pair[0:1].lower()) * 16 + digits.find(pair[1:2].lower())
end

function set_rgb(cr, color):
    return cairo.set_source_rgb(cr, Float(hex_byte(color[1:3])) / 255.0, Float(hex_byte(color[3:5])) / 255.0,
                                Float(hex_byte(color[5:7])) / 255.0)
end

function draw_mode(colors, cr, area):
    w = Float(gtk.widget_get_allocated_width(area))
    h = Float(gtk.widget_get_allocated_height(area))
    r = 10.0
    call cairo.new_path(cr)
    call cairo.arc(cr, w - r, r, r, -1.5708, 0.0)
    call cairo.arc(cr, w - r, h - r, r, 0.0, 1.5708)
    call cairo.arc(cr, r, h - r, r, 1.5708, 3.1416)
    call cairo.arc(cr, r, r, r, 3.1416, 4.7124)
    call cairo.close_path(cr)
    call set_rgb(cr, colors[0])
    call cairo.fill_preserve(cr)
    if len(colors) == 4:
        # Automaticky: leva pulka svetla, prava tmava
        call cairo.save(cr)
        call cairo.clip(cr)
        call set_rgb(cr, colors[2])
        call cairo.rectangle(cr, w / 2.0, 0.0, w / 2.0, h)
        call cairo.fill(cr)
        call cairo.restore(cr)
    end
    call cairo.new_path(cr)
    call set_rgb(cr, colors[1])
    call cairo.rectangle(cr, 10.0, 10.0, w - 20.0, 10.0)
    call cairo.fill(cr)
    call cairo.rectangle(cr, 10.0, 28.0, (w - 20.0) * 0.6, 34.0)
    call cairo.fill(cr)
    call cairo.set_source_rgb(cr, 0.24, 0.48, 1.0)
    call cairo.rectangle(cr, w * 0.6 + 4.0, 28.0, w * 0.4 - 14.0, 34.0)
    call cairo.fill(cr)
    return False
end

function mark(buttons, key):
    for k in buttons.keys():
        call gtk.widget_set_class(buttons[k], "current", k == key)
    end
    return 0
end

function choice_button(content, caption):
    b = gtk.button_new_empty()
    call gtk.widget_add_class(b, "mode")
    inner = gtk.box_new(gtk.VERTICAL, 6)
    call gtk.box_pack_start(inner, content, False, False, 0)
    call gtk.box_pack_start(inner, gtk.label_new(caption), False, False, 0)
    call gtk.container_add(b, inner)
    return b
end

function hhmm(t):
    tm = glib.localtime(t)
    return text.pad(tm[3], 2) + ":" + text.pad(tm[4], 2)
end

function sun_hint():
    lat_lon = sun.location()
    now = glib.localtime(glib.now())
    times = None
    safe:
        times = sun.sun_times(date.ordinal(now[0], now[1], now[2]), lat_lon[0], lat_lon[1])
    end
    if times == None:
        return ""
    end
    return i18n.TF("Auto: light from sunrise (%s) to sunset (%s), based on your time zone.", [hhmm(times[0]), hhmm(times[1])])
end

function build_mode(page):
    g = ui.group(page, i18n.T("Appearance"))
    box = gtk.box_new(gtk.HORIZONTAL, 12)
    call gtk.widget_set_margins(box, 12, 12, 12, 12)
    call gtk.widget_set_halign(box, gtk.ALIGN_START)
    current = ui.run(["luxos-appearance", "mode"])
    if current == "":
        current = "light"
    end
    for mode in MODES:
        preview = gtk.drawing_area_new()
        call gtk.widget_set_size_request(preview, 120, 76)
        call glib.connect_data(preview, "draw", 1, draw_mode, mode[2])
        b = choice_button(preview, i18n.T(mode[1]))
        call glib.connect_data(b, "clicked", 0, on_mode, mode[0])
        app["modes"][mode[0]] = b
        call gtk.box_pack_start(box, b, False, False, 0)
    end
    call mark(app["modes"], current)
    call gtk.box_pack_start(g["box"], box, False, False, 0)
    hint = sun_hint()
    if hint != "":
        l = ui.label(hint, "hint")
        call gtk.widget_set_margins(l, 12, 0, 0, 8)
        call gtk.box_pack_start(g["box"], l, False, False, 0)
    end
    return 0
end

# luxos-appearance prepne i ikony WhiteSur (svetle/tmave); vlastni sadu ikon necha
function on_mode(mode, button):
    call mark(app["modes"], mode)
    call ui.launch(["luxos-appearance", mode])
    return 0
end

# ---- ikony a kurzor ----------------------------------------------------------------------------------------

function icon_dirs():
    dirs = env.get("LUXOS_ICON_DIRS", "")
    if dirs != "":
        return dirs.split(":")
    end
    out = [glib.home_dir() + "/.icons", glib.user_data_dir() + "/icons"]
    for d in env.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"):
        if d != "":
            out.append(d + "/icons")
        end
    end
    return out
end

function index_theme(path):
    out = {}
    for raw in glib.read_text(path + "/index.theme").split("\n"):
        line = raw.strip()
        cut = line.find("=")
        if cut > 0 and not (line[:cut].strip() in out):
            out[line[:cut].strip()] = line[cut + 1:].strip()
        end
    end
    return out
end

# [[id, popisek]] nainstalovanych sad: kurzory (podslozka cursors) nebo ikony (Directories v index.theme)
function themes(cursors):
    found = {}
    for d in icon_dirs():
        for name in glib.list_dir(d):
            path = d + "/" + name
            if name in found or name.startswith(".") or not glib.is_dir(path):
                continue
            end
            info = index_theme(path)
            if cursors:
                if glib.is_dir(path + "/cursors"):
                    found[name] = info.get("Name", name)
                end
            elif info.get("Directories", "") != "" and info.get("Hidden", "") != "true" and not (name in NOT_THEMES):
                found[name] = info.get("Name", name)
            end
        end
    end
    return [[k, found[k]] for k in sorted(found.keys())]
end

function icon_options():
    out = [[LUXOS_ICONS, i18n.T("LuxOS (follows Light and Dark)")]]
    for item in themes(False):
        if not item[0].startswith("WhiteSur"):
            out.append(item)
        end
    end
    return out
end

function current_mode():
    if glib.read_text(glib.user_config_dir() + "/luxos/appearance").strip() == "dark":
        return "dark"
    end
    return "light"
end

function on_icons(unused, id):
    name = id
    if id == LUXOS_ICONS:
        name = "WhiteSur-" + current_mode()
    end
    call look.xf_set("xsettings", "/Net/IconThemeName", "string", name)
    return look.gs_string("icon-theme", name)
end

# kurzor je i na strance Zpristupneni: druha hodnota vzdy z kanalu, ne z doby otevreni stranky
function on_cursor_theme(unused, id):
    return look.set_cursor(id, look.cursor()[1])
end

function on_cursor_size(unused, id):
    return look.set_cursor(look.cursor()[0], Int(id))
end

function pointer_size_combo(size):
    options = [[item[0], i18n.T(item[1])] for item in POINTER_SIZES]
    return ui.combo(options, String(size), i18n.T("%s px"), on_cursor_size, 0)
end

function build_icons(page, xs):
    g = ui.group(page, i18n.T("Icons and Pointer"))
    icons = xs.get("/Net/IconThemeName", "")
    if icons == "" or icons.startswith("WhiteSur"):
        icons = LUXOS_ICONS
    end
    call ui.row(g, i18n.T("Icons"), "", ui.combo(icon_options(), icons, "", on_icons, 0))
    current = look.cursor()
    cursors = themes(True)
    if not (current[0] in [c[0] for c in cursors]):
        cursors.append([current[0], current[0]])
    end
    call ui.row(g, i18n.T("Pointer"), "", ui.combo(cursors, current[0], "", on_cursor_theme, 0))
    call ui.row(g, i18n.T("Pointer size"), "", pointer_size_combo(current[1]))
    return 0
end

# ---- pisma -------------------------------------------------------------------------------------------------

function font_button(font):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_font_button_new_with_font"), __lsl_address(font) + 16)
    end
end

function font_of(button):
    unsafe:
        return glib.take_c(__lsl_qbe_call1(__lsl_symbol("gtk_font_chooser_get_font"), glib.ptr(button)))
    end
end

function set_font_of(button, font):
    unsafe:
        return __lsl_qbe_call2(__lsl_symbol("gtk_font_chooser_set_font"), glib.ptr(button), __lsl_address(font) + 16)
    end
end

# what = [vlastnost xsettings, klic GSettings]
function on_font(what, button):
    font = font_of(button)
    if font == "":
        return 0
    end
    call look.xf_set("xsettings", what[0], "string", font)
    return look.gs_string(what[1], font)
end

function smoothing_of(xs):
    if xs.get("/Xft/Antialias", "1") == "0":
        return "none"
    end
    # bez hodnoty vychozi LuxOS (xsettings.xml: subpixel rgb)
    if xs.get("/Xft/RGBA", "rgb") in ["rgb", "bgr", "vrgb", "vbgr"]:
        return "rgba"
    end
    return "grayscale"
end

function on_smoothing(rgba, id):
    call look.xf_set("xsettings", "/Xft/Antialias", "int", on_off(id == "none", "0", "1"))
    if id == "rgba":
        call look.xf_set("xsettings", "/Xft/RGBA", "string", rgba)
    elif id == "grayscale":
        call look.xf_set("xsettings", "/Xft/RGBA", "string", "none")
    end
    return look.gs_string("font-antialiasing", id)
end

function hinting_of(xs):
    if xs.get("/Xft/Hinting", "1") == "0":
        return "none"
    end
    style = xs.get("/Xft/HintStyle", "hintslight")
    if style.startswith("hint"):
        return style[4:]
    end
    return "slight"
end

function on_hinting(unused, id):
    call look.xf_set("xsettings", "/Xft/Hinting", "int", on_off(id == "none", "0", "1"))
    call look.xf_set("xsettings", "/Xft/HintStyle", "string", "hint" + id)
    return look.gs_string("font-hinting", id)
end

function build_fonts(page, xs):
    g = ui.group(page, i18n.T("Fonts"))
    for item in [["interface", "Interface font", "/Gtk/FontName", "font-name", "Inter 10"],
                 ["monospace", "Monospace font", "/Gtk/MonospaceFontName", "monospace-font-name", "JetBrainsMono Nerd Font 10"]]:
        font = xs.get(item[2], "")
        if font == "":
            font = item[4]
        end
        b = font_button(font)
        call glib.connect_data(b, "font-set", 0, on_font, [item[2], item[3]])
        app["fonts"][item[0]] = [b, [item[2], item[3]]]
        call ui.row(g, i18n.T(item[1]), "", b)
    end
    rgba = xs.get("/Xft/RGBA", "rgb")
    if not (rgba in ["rgb", "bgr", "vrgb", "vbgr"]):
        rgba = "rgb"
    end
    smooth = ui.combo([["rgba", i18n.T("Subpixel (LCD screens)")], ["grayscale", i18n.T("Grayscale")], ["none", i18n.T("Off")]],
                      smoothing_of(xs), "", on_smoothing, rgba)
    call ui.row(g, i18n.T("Font smoothing"), i18n.T("Subpixel smoothing is sharpest on most laptop and desktop screens."), smooth)
    hint = ui.combo([["none", i18n.T("None")], ["slight", i18n.T("Slight")], ["medium", i18n.T("Medium")], ["full", i18n.T("Full")]],
                    hinting_of(xs), "", on_hinting, 0)
    call ui.row(g, i18n.T("Hinting"), "", hint)
    return 0
end

# ---- velikost textu (stejna hodnota jako Displeje na X11 a Zpristupneni) ------------------------------------

function text_size_combo():
    options = []
    for i in range(len(look.TEXT_LABELS)):
        options.append([String(i), i18n.T(look.TEXT_LABELS[i])])
    end
    return ui.combo(options, String(look.text_size()), "", on_text_size, 0)
end

function on_text_size(unused, id):
    return look.set_text_size(Int(id))
end

function build_text(page):
    g = ui.group(page, i18n.T("Text Size"))
    call ui.row(g, i18n.T("Text size"),
                i18n.T("Changes the size of text in the menu bar, window titles and apps. Some apps need to be reopened."),
                text_size_combo())
    return 0
end

# ---- stranka ----------------------------------------------------------------------------------------------

function build(host):
    xs = look.channel("xsettings")
    page = ui.page_box()
    call build_mode(page)
    call build_icons(page, xs)
    call build_fonts(page, xs)
    call build_text(page)
    return page
end

# Testy: "font interface|monospace PISMO" jako vyber v dialogu pisma
function test(command, rest):
    if command != "font":
        return False
    end
    cut = rest.find(" ")
    entry = app["fonts"].get(rest[:cut], None)
    if cut < 0 or entry == None:
        return False
    end
    call set_font_of(entry[0], rest[cut + 1:])
    call on_font(entry[1], entry[0])
    return True
end
