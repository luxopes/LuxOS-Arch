# lsl: link libgtk-3.so.0 libgdk-3.so.0 libgio-2.0.so.0 libgobject-2.0.so.0 libglib-2.0.so.0 libcairo.so.2
# LuxOS - aplikace z .desktop souboru pro shell na Waylandu (Dock, Launchpad): hledani podle app_id okna,
# spusteni s aktivacnim tokenem a ikona jako cairo surface. Nad GDesktopAppInfo (GIO), ktere umi nazvy podle
# jazyka, pole Exec a adresare XDG; `load luxos_apps as apps`.
#
#   find(id)                  aplikace podle id ("firefox.desktop") nebo absolutni cesty, 0 kdyz neni
#   find_entry(id_or_path)    jako find, ale cesta se jmenem platneho id dava soubor, ktery pro to id plati
#                             (/usr/share/applications/thunar.desktop -> prekryti v /var/lib/luxos/apps)
#   match(app_id)             aplikace okna: id, StartupWMClass, X-Flatpak, posledni cast reverse-DNS,
#                             spustitelny soubor (viditelne aplikace pred skrytymi); 0
#   reload()                  zmena v adresarich aplikaci: zahodit rejstrik pro match a nactene soubory
#   all()                     vsechny .desktop aplikace (i NoDisplay; Launchpad si vybira sam)
#   monitor()                 GAppInfoMonitor (signal "changed" po zmene .desktop souboru)
#   id(a), name(a), path(a), wm_class(a), executable(a)
#   generic_name(a), keywords(a) -> [..], categories(a) ("Network;WebBrowser;"), string(a, klic) (bez prekladu)
#   nodisplay(a), shown_here(a) (OnlyShowIn/NotShowIn podle XDG_CURRENT_DESKTOP)
#   launch(a)                 spusteni (GdkAppLaunchContext = xdg-activation na Waylandu); True kdyz bezi;
#                             ze sluzby shellu ve vlastnim scope systemd (luxos_glib.app_scope)
#   launch_uri(uri)           adresa ve vychozi aplikaci (soubor, slozka, trash:///) se stejnym kontextem
#   icon(a, size, scale)      ikona aplikace jako cairo surface (volajici ji znici), 0 kdyz neni
#   own_icon(a, size, scale)  jen ikona z Icon= (bez application-x-executable), 0 kdyz neni
#   icon_named(name, size, scale), icon_gicon(gicon, size, scale), base_name(cesta)
#
# Objekty aplikaci se drzi po celou dobu behu (rejstrik a find sdileji jeden objekt na soubor). Po reload() dostane
# zmeneny soubor novy objekt; stare zustanou platne pro toho, kdo je drzi (zmena .desktop je vzacna).
load glib
load luxos_glib as lglib
load luxos_text as text

LOOKUP_FORCE_SIZE = 16
FALLBACK_ICON = "application-x-executable"

by_path = {}        # cesta .desktop souboru -> GDesktopAppInfo
index = None        # klic (mala pismena) -> GDesktopAppInfo pro match

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function cstr(text):
    unsafe:
        return __lsl_address(text) + 16
    end
end

# Jeden objekt na soubor: novy se zahodi, kdyz uz soubor zname
function keep(info):
    if info == 0:
        return 0
    end
    file = path(info)
    old = by_path.get(file)
    if old != None:
        call unref(info)
        return old
    end
    by_path[file] = info
    return info
end

function find(desktop_id):
    if desktop_id == "":
        return 0
    end
    unsafe:
        if desktop_id[0] == "/":
            info = __lsl_qbe_call1(__lsl_symbol("g_desktop_app_info_new_from_filename"), cstr(desktop_id))
        else:
            info = __lsl_qbe_call1(__lsl_symbol("g_desktop_app_info_new"), cstr(desktop_id))
        end
    end
    return keep(info)
end

# Polozky Docku a oblibene ukladaji i cesty; okno se ale hleda podle id. Stejna aplikace = stejny objekt,
# i kdyz cestu prekryva soubor se stejnym id jinde v XDG_DATA_DIRS.
function find_entry(entry):
    if entry.startswith("/") and entry.endswith(".desktop"):
        info = find(base_name(entry))
        if info != 0:
            return info
        end
    end
    return find(entry)
end

function id(info):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_app_info_get_id"), ptr(info)))
    end
end

# Name podle jazyka jako Plank a Launchpad na X11; display_name by dal X-GNOME-FullName ("Mozilla Firefox")
function name(info):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_app_info_get_name"), ptr(info)))
    end
end

function path(info):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_desktop_app_info_get_filename"), ptr(info)))
    end
end

function wm_class(info):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_desktop_app_info_get_startup_wm_class"), ptr(info)))
    end
end

function executable(info):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_app_info_get_executable"), ptr(info)))
    end
end

function generic_name(info):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_desktop_app_info_get_generic_name"), ptr(info)))
    end
end

function categories(info):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_desktop_app_info_get_categories"), ptr(info)))
    end
end

function keywords(info):
    out = []
    unsafe:
        list = __lsl_qbe_call1(__lsl_symbol("g_desktop_app_info_get_keywords"), ptr(info))
        if list != 0:
            at = list
            while __lsl_qbe_load64(at) != 0:
                out.append(glib.from_c(__lsl_qbe_load64(at)))
                at += 8
            end
        end
    end
    return out
end

function string(info, key):
    unsafe:
        value = __lsl_qbe_call2(__lsl_symbol("g_desktop_app_info_get_string"), ptr(info), cstr(key))
        if value == 0:
            return ""
        end
        result = glib.from_c(value)
        call __lsl_qbe_call1(__lsl_symbol("g_free"), value)
    end
    return result
end

function nodisplay(info):
    unsafe:
        return __lsl_qbe_icall1(__lsl_symbol("g_desktop_app_info_get_nodisplay"), ptr(info)) != 0
    end
end

function shown_here(info):
    unsafe:
        return __lsl_qbe_icall2(__lsl_symbol("g_desktop_app_info_get_show_in"), ptr(info), 0) != 0
    end
end

# ---- app_id okna -> aplikace ----

function base_name(file):
    cut = text.rfind(file, "/")
    if cut >= 0:
        return file[cut + 1:]
    end
    return file
end

function strip_desktop(name):
    if name.endswith(".desktop"):
        return name[0:len(name) - 8]
    end
    return name
end

function last_part(name):
    cut = text.rfind(name, ".")
    if cut >= 0:
        return name[cut + 1:]
    end
    return name
end

function add_key(key, info):
    if key != "" and not (key in index):
        index[key] = info
    end
    return 0
end

function list_field(node, offset):
    unsafe:
        return __lsl_qbe_load64(ptr(node) + ptr(offset))
    end
end

# jen .desktop aplikace (GDesktopAppInfo), jine typy GAppInfo nemaji soubor
function is_desktop_info(info):
    unsafe:
        kind = __lsl_qbe_call0(__lsl_symbol("g_desktop_app_info_get_type"))
        return __lsl_qbe_icall2(__lsl_symbol("g_type_check_instance_is_a"), ptr(info), kind) != 0
    end
end

function unref(object):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("g_object_unref"), ptr(object))
    end
end

function all_infos():
    infos = []
    unsafe:
        list = __lsl_qbe_call0(__lsl_symbol("g_app_info_get_all"))
    end
    node = list
    while node != 0:
        info = list_field(node, 0)
        if is_desktop_info(info):
            infos.append(keep(info))
        else:
            call unref(info)
        end
        node = list_field(node, 8)
    end
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("g_list_free"), ptr(list))
    end
    return infos
end

# Program z Exec bez obalu: "env A=1 prog", "flatpak run ... id" (to pokryje X-Flatpak)
function program(info):
    exe = base_name(executable(info))
    if exe != "env":
        return exe
    end
    for word in string(info, "Exec").split(" "):
        if word != "" and word != "env" and word.find("=") < 0:
            return base_name(word)
        end
    end
    return ""
end

# Poradi klicu = priorita: presne id pred StartupWMClass a X-Flatpak pred zkracenym jmenem a programem.
# V kazdem kroku viditelne aplikace pred skrytymi (NoDisplay, OnlyShowIn jinde), at okno nedostane
# ikonu a nazev pomocneho .desktop (nastaveni, akce) se stejnym programem.
function build_index():
    global index
    index = {}
    visible = []
    hidden = []
    for info in all_infos():
        if nodisplay(info) or not shown_here(info):
            hidden.append(info)
        else:
            visible.append(info)
        end
    end
    infos = visible + hidden
    for info in infos:
        call add_key(strip_desktop(id(info)).lower(), info)
    end
    for info in infos:
        call add_key(wm_class(info).lower(), info)
        call add_key(string(info, "X-Flatpak").lower(), info)
    end
    for info in infos:
        call add_key(last_part(strip_desktop(id(info))).lower(), info)
    end
    for info in infos:
        call add_key(program(info).lower(), info)
    end
    return 0
end

function match(app_id):
    app_id = strip_desktop(app_id)
    if app_id == "":
        return 0
    end
    direct = find(app_id + ".desktop")
    if direct != 0:
        return direct
    end
    if index == None:
        call build_index()
    end
    key = app_id.lower()
    for candidate in [key, last_part(key)]:
        info = index.get(candidate)
        if info != None:
            return info
        end
    end
    return 0
end

function reload():
    global index, by_path
    index = None
    by_path = {}
    return 0
end

function all():
    return all_infos()
end

function monitor():
    unsafe:
        return __lsl_qbe_call0(__lsl_symbol("g_app_info_monitor_get"))
    end
end

# ---- spusteni ----

function launch_context():
    unsafe:
        display = __lsl_qbe_call0(__lsl_symbol("gdk_display_get_default"))
        if display == 0:
            return 0
        end
        return __lsl_qbe_call1(__lsl_symbol("gdk_display_get_app_launch_context"), display)
    end
end

function launch_info(info):
    context = launch_context()
    unsafe:
        cell = __lsl_byte_zeros(8)
        cell_at = __lsl_qbe_load64(__lsl_address(cell) + 24)
        ok = __lsl_qbe_icall4(__lsl_symbol("g_app_info_launch"), ptr(info), 0, ptr(context), cell_at)
        error = __lsl_qbe_load64(cell_at)
        if error != 0:
            call __lsl_qbe_call1(__lsl_symbol("g_error_free"), error)
        end
    end
    if context != 0:
        call unref(context)
    end
    return ok != 0
end

# Prikaz pres GAppInfo z prikazove radky: GLib mu da token xdg-activation z kontextu GDK v prostredi
# (XDG_ACTIVATION_TOKEN projde pres systemd-run a gio az do aplikace). Radka ma pravidla Exec: % jako %%.
function launch_command(argv):
    line = " ".join([glib.shell_quote(a) for a in argv]).replace("%", "%%")
    unsafe:
        # G_APP_INFO_CREATE_SUPPORTS_STARTUP_NOTIFICATION = 4
        info = __lsl_qbe_call4(__lsl_symbol("g_app_info_create_from_commandline"), cstr(line), 0, 4, 0)
    end
    if info == 0:
        return False
    end
    ok = launch_info(info)
    call unref(info)
    return ok
end

# Ze sluzby shellu ve vlastnim scope (luxos_glib.app_scope); DBusActivatable spousti D-Bus ve vlastni jednotce
function launch(info):
    file = path(info)
    scope = lglib.app_scope(strip_desktop(base_name(file)))
    if scope == [] or string(info, "DBusActivatable") == "true":
        return launch_info(info)
    end
    return launch_command(scope + ["gio", "launch", file])
end

# Zkopiruje spoustec do Plochy. Docasna slozka skryje rozpracovany soubor pred spravcem plochy.
# Bez prepisu: opakovane pridani ani soubezny zapis neprepise uzivateluv soubor.
function add_desktop_shortcut(info):
    desktop_id = id(info)
    source = path(info)
    dir = lglib.desktop_dir()
    if not desktop_id.endswith(".desktop") or desktop_id.startswith(".") or desktop_id.find("/") >= 0 or source == "" or not lglib.mkdir_p(dir):
        return "failed"
    end
    template = dir + "/.luxos-shortcut-XXXXXX"
    unsafe:
        buffer = __lsl_byte_zeros(__lsl_text_byte_length(template) + 1)
        base = __lsl_qbe_load64(__lsl_address(buffer) + 24)
        call __lsl_qbe_call3(__lsl_symbol("memcpy"), base, cstr(template), __lsl_text_byte_length(template))
        if __lsl_qbe_call1(__lsl_symbol("g_mkdtemp"), base) == 0:
            return "failed"
        end
        temporary = glib.from_c(base)
        staged = temporary + "/" + desktop_id
        original = __lsl_qbe_call1(__lsl_symbol("g_file_new_for_path"), cstr(source))
        draft = __lsl_qbe_call1(__lsl_symbol("g_file_new_for_path"), cstr(staged))
        result = "failed"
        if __lsl_qbe_icall7(__lsl_symbol("g_file_copy"), original, draft, 0, 0, 0, 0, 0) != 0 and __lsl_qbe_icall2(__lsl_symbol("chmod"), cstr(staged), 448) == 0:
            target = __lsl_qbe_call1(__lsl_symbol("g_file_new_for_path"), cstr(dir + "/" + desktop_id))
            error_cell = __lsl_byte_zeros(8)
            error_at = __lsl_qbe_load64(__lsl_address(error_cell) + 24)
            if __lsl_qbe_icall7(__lsl_symbol("g_file_move"), draft, target, 0, 0, 0, 0, error_at) != 0:
                result = "added"
            end
            error = __lsl_qbe_load64(error_at)
            if error != 0:
                # G_IO_ERROR_EXISTS = 2
                if __lsl_qbe_icall3(__lsl_symbol("g_error_matches"), error, __lsl_qbe_icall0(__lsl_symbol("g_io_error_quark")), 2) != 0:
                    result = "exists"
                end
                call __lsl_qbe_call1(__lsl_symbol("g_error_free"), error)
            end
            call unref(target)
        end
        call unref(draft)
        call unref(original)
        call lglib.unlink(staged)
        call __lsl_qbe_icall1(__lsl_symbol("rmdir"), cstr(temporary))
    end
    return result
end

function launch_uri(uri):
    scope = lglib.app_scope("open")
    if scope != []:
        return launch_command(scope + ["gio", "open", uri])
    end
    context = launch_context()
    unsafe:
        cell = __lsl_byte_zeros(8)
        cell_at = __lsl_qbe_load64(__lsl_address(cell) + 24)
        ok = __lsl_qbe_icall3(__lsl_symbol("g_app_info_launch_default_for_uri"), cstr(uri), ptr(context), cell_at)
        error = __lsl_qbe_load64(cell_at)
        if error != 0:
            call __lsl_qbe_call1(__lsl_symbol("g_error_free"), error)
        end
    end
    if context != 0:
        call unref(context)
    end
    return ok != 0
end

# ---- ikony ----

function load_icon(icon_info):
    if icon_info == 0:
        return 0
    end
    unsafe:
        surface = __lsl_qbe_call3(__lsl_symbol("gtk_icon_info_load_surface"), ptr(icon_info), 0, 0)
        call __lsl_qbe_call1(__lsl_symbol("g_object_unref"), ptr(icon_info))
        return surface
    end
end

function icon_named(icon_name, size, scale):
    unsafe:
        theme = __lsl_qbe_call0(__lsl_symbol("gtk_icon_theme_get_default"))
        found = __lsl_qbe_call5(__lsl_symbol("gtk_icon_theme_lookup_icon_for_scale"), theme, cstr(icon_name), ptr(size), ptr(scale), LOOKUP_FORCE_SIZE)
    end
    return load_icon(found)
end

function icon_gicon(gicon, size, scale):
    if gicon == 0:
        return 0
    end
    unsafe:
        theme = __lsl_qbe_call0(__lsl_symbol("gtk_icon_theme_get_default"))
        found = __lsl_qbe_call5(__lsl_symbol("gtk_icon_theme_lookup_by_gicon_for_scale"), theme, ptr(gicon), ptr(size), ptr(scale), LOOKUP_FORCE_SIZE)
    end
    return load_icon(found)
end

# Jen vlastni ikona aplikace (Icon= v tematu nebo cesta), bez nahradni; 0 kdyz neni
function own_icon(info, size, scale):
    unsafe:
        gicon = __lsl_qbe_call1(__lsl_symbol("g_app_info_get_icon"), ptr(info))
    end
    return icon_gicon(gicon, size, scale)
end

function icon(info, size, scale):
    surface = own_icon(info, size, scale)
    if surface == 0:
        return icon_named(FALLBACK_ICON, size, scale)
    end
    return surface
end
