# LuxOS - Nastaveni > Vychozi aplikace (drive xfce4-mime-settings a "Preferovane aplikace" exo): cim se otevre
# web, posta, slozky, text, obrazky, video, hudba a PDF a ktery terminal se spusti.
# Typy souboru a odkazu: XDG mimeapps (~/.config/mimeapps.list) pres GIO, stejne jako `xdg-mime default`; nabidka
# jen nainstalovanych aplikaci, ktere typ uvadeji a smi se ukazat (NoDisplay, Hidden, OnlyShowIn).
# Pomocne aplikace exo (~/.config/xfce4/helpers.rc): exo-open je pouziva v obou relacich (Soubory: "Otevrit terminal
# zde", odkazy); prohlizec a spravce souboru se zapisou i tam, kdyz pro ne exo ma pomocnou aplikaci. Posta zustava
# MailReader=luxos-mail-reader, ten se ridi aplikaci pro mailto.
load env, json
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_text as text
load luxos_settings_ui as ui
load luxos_sys as lsys

# [klic, nazev, typ pro zjisteni aktualni aplikace, dalsi typy (jen ty, ktere aplikace uvadi), pomocna aplikace exo]
KINDS = [["browser", "Web browser", "x-scheme-handler/http", ["x-scheme-handler/https", "text/html", "application/xhtml+xml"], "WebBrowser"],
    ["mail", "Mail", "x-scheme-handler/mailto", [], ""],
    ["files", "File manager", "inode/directory", [], "FileManager"],
    ["text", "Text editor", "text/plain", [], ""],
    ["images", "Image viewer", "image/png", ["image/jpeg", "image/gif", "image/webp", "image/bmp", "image/tiff", "image/svg+xml"], ""],
    ["video", "Videos", "video/mp4", ["video/x-matroska", "video/webm", "video/mpeg", "video/quicktime", "video/x-msvideo", "video/ogg"], ""],
    ["music", "Music", "audio/mpeg", ["audio/flac", "audio/ogg", "audio/x-vorbis+ogg", "audio/x-opus+ogg", "audio/x-wav", "audio/mp4", "audio/aac"], ""],
    ["pdf", "PDF and documents", "application/pdf", ["application/epub+zip", "application/x-cbz", "image/vnd.djvu", "application/postscript"], ""]]
# aplikace, ktere jen predavaji jine (luxos-mail-reader hleda aplikaci pro mailto)
SKIP = ["luxos-mail-reader.desktop"]

offered = {}

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

# ---- GIO ----------------------------------------------------------------------------------------------------------

function info_id(info):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_app_info_get_id"), ptr(info)))
    end
end

function info_name(info):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_app_info_get_display_name"), ptr(info)))
    end
end

function unref(object):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("g_object_unref"), ptr(object))
    end
end

# Typy, ktere aplikace uvadi (MimeType=)
function supported(info):
    out = []
    unsafe:
        list = __lsl_qbe_call1(__lsl_symbol("g_app_info_get_supported_types"), ptr(info))
        if list != 0:
            item = __lsl_qbe_load64(list)
            while item != 0:
                out.append(glib.from_c(item))
                list = list + 8
                item = __lsl_qbe_load64(list)
            end
        end
    end
    return out
end

# Aktualni aplikace pro typ podle mimeapps.list a mimeinfo.cache; "" kdyz zadna
function default_for(kind):
    id = ""
    unsafe:
        info = __lsl_qbe_call2(__lsl_symbol("g_app_info_get_default_for_type"), cstr(kind), 0)
        if info != 0:
            id = info_id(info)
            call unref(info)
        end
    end
    return id
end

# [[id, nazev]] nainstalovanych aplikaci, ktere typ uvadeji a smi se ukazat, podle nazvu
function apps_for(kind):
    keyed = {}
    unsafe:
        list = __lsl_qbe_call1(__lsl_symbol("g_app_info_get_all_for_type"), cstr(kind))
        node = list
        while node != 0:
            info = __lsl_qbe_load64(node)
            id = info_id(info)
            if __lsl_qbe_icall1(__lsl_symbol("g_app_info_should_show"), info) != 0 and id != "" and not (id in SKIP):
                name = info_name(info)
                keyed[name.lower() + "\t" + id] = [id, name]
            end
            call unref(info)
            node = __lsl_qbe_load64(node + 8)
        end
        call __lsl_qbe_call1(__lsl_symbol("g_list_free"), list)
    end
    return [keyed[k] for k in sorted(keyed.keys())]
end

# Zapis do ~/.config/mimeapps.list ([Default Applications] i [Added Associations]) jako xdg-mime default
function set_default(id, kinds):
    ok = False
    unsafe:
        info = __lsl_qbe_call1(__lsl_symbol("g_desktop_app_info_new"), cstr(id))
        if info == 0:
            return False
        end
        for kind in kinds:
            ok = __lsl_qbe_icall3(__lsl_symbol("g_app_info_set_as_default_for_type"), info, cstr(kind), 0) != 0
        end
        call unref(info)
    end
    return ok
end

# ---- pomocne aplikace exo (helpers.rc) ------------------------------------------------------------------------------

function data_dirs():
    dirs = [glib.user_data_dir()]
    for d in env.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"):
        if d != "":
            dirs.append(d)
        end
    end
    return dirs
end

function config_dirs():
    dirs = [glib.user_config_dir()]
    for d in env.get("XDG_CONFIG_DIRS", "/etc/xdg").split(":"):
        if d != "":
            dirs.append(d)
        end
    end
    return dirs
end

function helpers_rc():
    return glib.user_config_dir() + "/xfce4/helpers.rc"
end

# Pomocna aplikace exo podle jmena souboru (xfce4/helpers/NAME.desktop), "" kdyz neni
function helper_file(name):
    for d in data_dirs():
        path = d + "/xfce4/helpers/" + name + ".desktop"
        if exists(path):
            return path
        end
    end
    return ""
end

function key_file(path):
    out = {}
    for raw in glib.read_text(path).split("\n"):
        line = raw.strip()
        if line.startswith("[") and line != "[Desktop Entry]" and len(out) > 0:
            break
        end
        cut = line.find("=")
        if cut > 0:
            out[line[0:cut]] = line[cut + 1:]
        end
    end
    return out
end

# Nazev v jazyku uzivatele (Name[cs_CZ], Name[cs], Name)
function local_name(entry):
    lang = env.get("LC_ALL", "")
    if lang == "":
        lang = env.get("LC_MESSAGES", "")
    end
    if lang == "":
        lang = env.get("LANG", "")
    end
    lang = lang.split(".")[0]
    for key in ["Name[" + lang + "]", "Name[" + lang.split("_")[0] + "]", "Name"]:
        if entry.get(key, "") != "":
            return entry[key]
        end
    end
    return ""
end

# Nainstalovane pomocne aplikace kategorie (X-XFCE-Category, nektery z X-XFCE-Binaries v PATH)
function helpers_for(category):
    seen = []
    keyed = {}
    for d in data_dirs():
        for file in glib.list_dir(d + "/xfce4/helpers"):
            if not file.endswith(".desktop") or file in seen:
                continue
            end
            seen.append(file)
            entry = key_file(d + "/xfce4/helpers/" + file)
            if entry.get("X-XFCE-Category", "") != category:
                continue
            end
            found = False
            for binary in entry.get("X-XFCE-Binaries", "").split(";"):
                if binary != "" and glib.find_program_in_path(binary) != "":
                    found = True
                end
            end
            if found:
                name = file[0:len(file) - 8]
                title = local_name(entry)
                keyed[title.lower() + "\t" + name] = [name, title]
            end
        end
    end
    return [keyed[k] for k in sorted(keyed.keys())]
end

function helper_current(key):
    for d in config_dirs():
        value = ui.read_kv(d + "/xfce4/helpers.rc").get(key, "")
        if value != "":
            return value
        end
    end
    return ""
end

# Jmeno pomocne aplikace k .desktop jako luxos-new-user-defaults: org.mozilla.firefox -> firefox
function helper_name(id):
    name = id
    if name.endswith(".desktop"):
        name = name[0:len(name) - 8]
    end
    cut = text.rfind(name, ".")
    if cut >= 0:
        name = name[cut + 1:]
    end
    return name.lower()
end

# ---- stranka --------------------------------------------------------------------------------------------------------

function on_app(kind, id):
    if id == "":
        return 0
    end
    kinds = [kind[2]]
    have = supported_types(id)
    for extra in kind[3]:
        if extra in have:
            kinds.append(extra)
        end
    end
    call set_default(id, kinds)
    if kind[4] != "" and helper_file(helper_name(id)) != "":
        call ui.write_kv(helpers_rc(), kind[4], helper_name(id))
    end
    return 0
end

function supported_types(id):
    out = []
    unsafe:
        info = __lsl_qbe_call1(__lsl_symbol("g_desktop_app_info_new"), cstr(id))
        if info != 0:
            out = supported(info)
            call unref(info)
        end
    end
    return out
end

function on_terminal(unused, name):
    if name != "":
        call ui.write_kv(helpers_rc(), "TerminalEmulator", name)
    end
    return 0
end

function none_label():
    return ui.label(i18n.T("No app installed"), "hint")
end

function build(host):
    page = ui.page_box()
    g = ui.group(page, i18n.T("Open with"))
    for kind in KINDS:
        options = apps_for(kind[2])
        current = default_for(kind[2])
        if current != "" and not (current in [o[0] for o in options]):
            # skryta nebo jen v mimeapps.list: ukazat skutecny stav, ne prvni polozku
            options.append([current, current])
        end
        offered[kind[0]] = [o[0] for o in options]
        widget = 0
        if len(options) == 0:
            widget = none_label()
        else:
            widget = ui.combo(options, current, "", on_app, kind)
        end
        call ui.row(g, i18n.T(kind[1]), "", widget)
    end
    terminals = helpers_for("TerminalEmulator")
    offered["terminal"] = [t[0] for t in terminals]
    widget = none_label()
    if len(terminals) > 0:
        widget = ui.combo(terminals, helper_current("TerminalEmulator"), "", on_terminal, 0)
    end
    call ui.row(g, i18n.T("Terminal"), i18n.T("Used for “Open Terminal Here” in Files and for apps that run in a terminal."), widget)
    note = ui.label(i18n.T("Apps you install later appear here automatically if they can open these files."), "hint")
    call gtk.widget_set_margins(note, 16, 16, 8, 0)
    call gtk.box_pack_start(page, note, False, False, 0)
    return page
end

# options: nabidnute aplikace kazdeho radku
function test(command, rest):
    if command == "options":
        call lsys.out("options " + json.encode(offered) + "\n")
        return True
    end
    return False
end
