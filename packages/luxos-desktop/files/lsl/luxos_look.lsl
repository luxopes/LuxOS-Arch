# LuxOS - spolecne casti stranek Vzhled, Zpristupneni a Okna a plochy (luxos-settings): kanaly xfconf v obou
# relacich, GSettings org.gnome.desktop.interface a nastaveni luxwm.
#
# Kanal xsettings je zdroj pravdy pro obe relace: na X11 ho meni xfconf-query (xfsettingsd zmenu hned rozesle),
# na Waylandu se zapise primo soubor kanalu (luxos_xfconf) a GTK aplikace dostanou zmenu hned pres GSettings;
# pri dalsim prihlaseni ho do GSettings prenese luxos-wayland-settings.
#
#   look.channel(nazev) -> {cesta: hodnota}       X11 xfconf-query -l -v, Wayland soubory kanalu
#   look.xf_set(nazev, cesta, typ, hodnota)       jedna vlastnost (typ int/bool/string)
#   look.iface()                                  GSettings org.gnome.desktop.interface nebo 0
#   look.wm_conf() -> {klic: hodnota}             luxwm.conf (system + uzivatel)
#   look.wm_save({klic: hodnota nebo None})       uzivatelsky luxwm.conf a reload bezicimu luxwm
#   look.set_cursor(tema, velikost)               kurzor v obou relacich i v luxwm
#   look.TEXT_SIZES, look.text_size(), look.set_text_size(index)   velikost textu jako v Displejich (Xft/DPI)
load env
load luxos_glib, glib as glib
load luxos_text as text
load luxos_xfconf as xfconf
load luxos_wm_config as wmconf
load luxos_luxwm as wm
load luxos_settings_ui as ui

LUXOS_SYSTEM = "/etc/xdg/luxos/xfce4/xfconf/xfce-perchannel-xml/"
IFACE = "org.gnome.desktop.interface"
# Stejne kroky jako Nastaveni > Displeje na X11 (luxos_xrandr.TEXT_SIZES, None = vychozi 96 DPI)
TEXT_SIZES = [84, 96, 108, 120, 132]
TEXT_LABELS = ["Smaller", "Default", "Large", "Larger", "Largest"]
DEFAULT_DPI = 96

cache = {"iface": None}

function wayland():
    return ui.wayland()
end

# Na Waylandu vychozi hodnoty LuxOS z /etc/xdg/luxos (luxos_xfconf.channel cte jen /etc/xdg)
function channel(name):
    out = {}
    if not wayland():
        for line in ui.run(["xfconf-query", "-c", name, "-l", "-v"]).split("\n"):
            line = line.strip()
            cut = line.find(" ")
            if line.startswith("/") and cut > 0:
                out[line[:cut]] = line[cut:].strip()
            elif line.startswith("/"):
                out[line] = ""
            end
        end
        return out
    end
    call xfconf.read_into(xfconf.SYSTEM + name + ".xml", out)
    call xfconf.read_into(LUXOS_SYSTEM + name + ".xml", out)
    return xfconf.read_into(xfconf.user_path(name), out)
end

function xf_set(name, prop, kind, value):
    value = String(value)
    if wayland():
        return xfconf.write(name, {prop: [kind, value]})
    end
    call ui.run(["xfconf-query", "-c", name, "-p", prop, "-n", "-t", kind, "-s", value])
    return True
end

# ---- GSettings ---------------------------------------------------------------------------------------------

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

# Schema s pevnou cestou: g_settings_new (ui.gsettings je pro premistitelna schemata)
function iface():
    if cache["iface"] != None:
        return cache["iface"]
    end
    cache["iface"] = 0
    unsafe:
        source = __lsl_qbe_call0(__lsl_symbol("g_settings_schema_source_get_default"))
        if source != 0:
            found = __lsl_qbe_call3(__lsl_symbol("g_settings_schema_source_lookup"), source, cstr(IFACE), 1)
            if found != 0:
                call __lsl_qbe_call1(__lsl_symbol("g_settings_schema_unref"), found)
                cache["iface"] = __lsl_qbe_call1(__lsl_symbol("g_settings_new"), cstr(IFACE))
            end
        end
    end
    return cache["iface"]
end

function gs_string(key, value):
    s = iface()
    if s != 0:
        call ui.gs_set_string(s, key, value)
        call ui.gs_sync()
    end
    return 0
end

function gs_int(key, value):
    s = iface()
    if s != 0:
        call ui.gs_set_int(s, key, value)
        call ui.gs_sync()
    end
    return 0
end

function gs_bool(key, value):
    s = iface()
    if s != 0:
        call ui.gs_set_bool(s, key, value)
        call ui.gs_sync()
    end
    return 0
end

function gs_double(key, value):
    s = iface()
    if s != 0:
        unsafe:
            call __lsl_qbe_call3(__lsl_symbol("g_settings_set_double"), ptr(s), cstr(key), Float(value))
        end
        call ui.gs_sync()
    end
    return 0
end

# ---- luxwm -------------------------------------------------------------------------------------------------

function wm_conf():
    out = wmconf.system_conf()["general"]
    out.update(wmconf.user_conf()["general"])
    return out
end

# Soubor plati i pro dalsi prihlaseni do Waylandu; bezici luxwm ho nacte hned (bez luxwm, napr. na X11, jen soubor)
function wm_save(changes):
    ok = wmconf.save(changes, {})
    if wayland() and wm.connected():
        call wm.request({"cmd": "reload"}, None)
    end
    return ok
end

function wm_request(message):
    if wayland() and wm.connected():
        return wm.request(message, None)
    end
    return False
end

# ---- kurzor a velikost textu (sdili Vzhled a Zpristupneni) --------------------------------------------------

function cursor():
    xs = channel("xsettings")
    theme = xs.get("/Gtk/CursorThemeName", "")
    if theme == "":
        theme = "WhiteSur-cursors"
    end
    size = 24
    if text.is_digits(xs.get("/Gtk/CursorThemeSize", "")):
        size = Int(xs["/Gtk/CursorThemeSize"])
    end
    return [theme, size]
end

function set_cursor(theme, size):
    call xf_set("xsettings", "/Gtk/CursorThemeName", "string", theme)
    call xf_set("xsettings", "/Gtk/CursorThemeSize", "int", size)
    call gs_string("cursor-theme", theme)
    call gs_int("cursor-size", size)
    call wm_request({"cmd": "set_cursor", "theme": theme, "size": size})
    return 0
end

# Index v TEXT_SIZES pro Xft/DPI (bez hodnoty = vychozi, jinak nejblizsi) - jako luxos_xrandr.text_size_index
function text_size():
    value = channel("xsettings").get("/Xft/DPI", "")
    if not text.is_digits(value) or Int(value) <= 0:
        return 1
    end
    dpi = Int(value)
    best = 0
    for i in range(len(TEXT_SIZES)):
        if abs(TEXT_SIZES[i] - dpi) < abs(TEXT_SIZES[best] - dpi):
            best = i
        end
    end
    return best
end

# X11 stejne jako Displeje (vychozi krok vlastnost smaze); Wayland soubor kanalu + meritko textu GTK
function set_text_size(index):
    dpi = TEXT_SIZES[index]
    if not wayland():
        if dpi == DEFAULT_DPI:
            call ui.run(["xfconf-query", "-c", "xsettings", "-p", "/Xft/DPI", "-r"])
        else:
            call ui.run(["xfconf-query", "-c", "xsettings", "-p", "/Xft/DPI", "-n", "-t", "int", "-s", String(dpi)])
        end
    else:
        call xfconf.write("xsettings", {"/Xft/DPI": ["int", String(dpi)]})
        call gs_double("text-scaling-factor", Float(dpi) / Float(DEFAULT_DPI))
    end
    return 0
end
