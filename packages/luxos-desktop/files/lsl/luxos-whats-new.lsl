# LuxOS - Co je noveho: novinky po aktualizaci systemu.
#
#   luxos-whats-new               novinky aktualni verze (z O tomto pocitaci, Launchpadu)
#   luxos-whats-new --auto        po prihlaseni (luxos-session): jen kdyz se od posledniho zobrazeni zmenila verze
#                                 LuxOS; ukaze novinky vsech novych verzi
#   luxos-whats-new --mark-seen   aktualni verzi oznaci jako videnou (novy uzivatel - ma Prohlidku)
#
# Novinky v /usr/share/luxos/whats-new/<verze>.json (luxos-branding), chybejici jazyk = anglicky text
# (luxos_whats_new.lsl). Videna verze: ~/.config/luxos/whats-new-seen.
load env
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_sys as sys
load luxos_whats_new as wn
load luxos_settings_ui as ui

NOTES_DIR = env.get("LUXOS_WHATS_NEW_DIR", "/usr/share/luxos/whats-new")
VERSION_FILE = env.get("LUXOS_VERSION_FILE", "/usr/lib/luxos/version")
SEEN = glib.user_config_dir() + "/luxos/whats-new-seen"
CSS = ".wn-title { font-size: 26px; font-weight: 800; }\n.wn-sub { font-size: 14px; opacity: 0.6; }\n.wn-version { font-size: 12px; font-weight: 700; opacity: 0.55; margin-top: 6px; }\n.wn-item-title { font-size: 14px; font-weight: 700; }\n.wn-item-text { font-size: 13px; opacity: 0.72; }\n.wn-icon { background-color: alpha(#3d7bff, 0.14); border-radius: 12px; color: #3d7bff;\n           min-width: 44px; min-height: 44px; }\n.primary { border-radius: 999px; padding: 6px 30px; font-weight: 700; background-image: none;\n           background-color: #3d7bff; color: white; border: none; box-shadow: none; }\n.primary:hover { background-color: #5a8fff; }\n.primary:focus { box-shadow: 0 0 0 3px alpha(#3d7bff, 0.35); }\n"

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

# Soubor ikony v motivu (24 px), "" kdyz ji motiv nema
function icon_file(theme, name):
    unsafe:
        info = __lsl_qbe_call4(__lsl_symbol("gtk_icon_theme_lookup_icon"), ptr(theme), cstr(name), 24, 0)
        if info == 0:
            return ""
        end
        path = glib.from_c(__lsl_qbe_call1(__lsl_symbol("gtk_icon_info_get_filename"), info))
        call glib.object_unref(info)
        return path
    end
end

# Ikona polozky: z aktualniho motivu, kdyz je opravdu symbolicka, jinak stejny nazev z Adwaity (zavislost
# gtk3), jinak hvezdicka; GtkIconSize LARGE_TOOLBAR = 3, prebarvi ji CSS .wn-icon
function item_icon(name):
    if name == "" or name == None:
        name = "starred-symbolic"
    end
    unsafe:
        theme = __lsl_qbe_call0(__lsl_symbol("gtk_icon_theme_get_default"))
        if wn.symbolic_file_ok(icon_file(theme, name)):
            return gtk.image_new_from_icon_name(name, 3)
        end
        adwaita = __lsl_qbe_call0(__lsl_symbol("gtk_icon_theme_new"))
        call __lsl_qbe_call2(__lsl_symbol("gtk_icon_theme_set_custom_theme"), adwaita, cstr("Adwaita"))
        path = icon_file(adwaita, name)
        call glib.object_unref(adwaita)
        if wn.symbolic_file_ok(path):
            file = __lsl_qbe_call1(__lsl_symbol("g_file_new_for_path"), cstr(path))
            icon = __lsl_qbe_call1(__lsl_symbol("g_file_icon_new"), file)
            image = __lsl_qbe_call2(__lsl_symbol("gtk_image_new_from_gicon"), icon, 3)
            call glib.object_unref(icon)
            call glib.object_unref(file)
            return image
        end
    end
    return gtk.image_new_from_icon_name("starred-symbolic", 3)
end

function label(text, css):
    l = gtk.label_new(text)
    call gtk.widget_add_class(l, css)
    return l
end

function on_continue(window, button):
    call gtk.widget_destroy(window)
    return 0
end

function on_destroy(window):
    call gtk.main_quit()
    return 0
end

function show(versions, notes):
    call glib.set_prgname("luxos-whats-new")
    call gtk.init()
    call gtk.css_load(CSS)
    langs = wn.lang_codes()
    newest = notes[versions[0]]
    window = ui.window(i18n.T("What's New"), "luxos-app", 580, 720, 420, 400)
    call gtk.window_set_wmclass(window, "luxos-whats-new", "luxos-whats-new")
    # GTK_WIN_POS_CENTER = 1
    call gtk.window_set_position(window, 1)
    call gtk.connect(window, "destroy", on_destroy)
    outer = gtk.box_new(gtk.VERTICAL, 6)
    call gtk.widget_set_margins(outer, 36, 36, 0, 24)
    logo = gtk.image_new_from_icon_name("luxos-app", 6)
    call gtk.image_set_pixel_size(logo, 72)
    call gtk.box_pack_start(outer, logo, False, False, 0)
    title = label(i18n.TF("What's New in LuxOS %s", [versions[0]]), "wn-title")
    call gtk.label_set_line_wrap(title, True)
    # GTK_JUSTIFY_CENTER = 2
    call gtk.label_set_justify(title, 2)
    call gtk.box_pack_start(outer, title, False, False, 0)
    if String(newest.get("codename", "")) != "":
        call gtk.box_pack_start(outer, label(newest["codename"], "wn-sub"), False, False, 0)
    end
    rows = gtk.box_new(gtk.VERTICAL, 16)
    call gtk.widget_set_margins(rows, 0, 8, 18, 0)
    for v in versions:
        if len(versions) > 1:
            head = label(i18n.TF("LuxOS %s", [v]), "wn-version")
            call gtk.label_set_xalign(head, 0)
            call gtk.box_pack_start(rows, head, False, False, 0)
        end
        for item in notes[v].get("items", []):
            row = gtk.box_new(gtk.HORIZONTAL, 14)
            icon = item_icon(item.get("icon", ""))
            call gtk.image_set_pixel_size(icon, 24)
            call gtk.widget_add_class(icon, "wn-icon")
            call gtk.widget_set_valign(icon, gtk.ALIGN_START)
            call gtk.box_pack_start(row, icon, False, False, 0)
            texts = gtk.box_new(gtk.VERTICAL, 2)
            call gtk.widget_set_valign(texts, gtk.ALIGN_CENTER)
            t = label(wn.tr(item.get("title", ""), langs), "wn-item-title")
            call gtk.label_set_xalign(t, 0)
            call gtk.label_set_line_wrap(t, True)
            call gtk.box_pack_start(texts, t, False, False, 0)
            body = wn.tr(item.get("text", ""), langs)
            if body != "":
                b = label(body, "wn-item-text")
                call gtk.label_set_xalign(b, 0)
                call gtk.label_set_line_wrap(b, True)
                call gtk.label_set_max_width_chars(b, 50)
                call gtk.box_pack_start(texts, b, False, False, 0)
            end
            call gtk.box_pack_start(row, texts, True, True, 0)
            call gtk.box_pack_start(rows, row, False, False, 0)
        end
    end
    scroll = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(scroll, gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
    call gtk.scrolled_window_set_propagate_natural_height(scroll, True)
    call gtk.container_add(scroll, rows)
    call gtk.box_pack_start(outer, scroll, True, True, 0)
    ok = gtk.button_new(i18n.T("Continue"))
    call gtk.widget_set_halign(ok, gtk.ALIGN_CENTER)
    call gtk.widget_set_margins(ok, 0, 0, 14, 0)
    call gtk.widget_add_class(ok, "primary")
    call glib.connect_data(ok, "clicked", 0, on_continue, window)
    call gtk.box_pack_end(outer, ok, False, False, 0)
    call gtk.container_add(window, outer)
    call gtk.widget_show_all(window)
    call gtk.widget_grab_focus(ok)
    call gtk.main()
    return 0
end

function main():
    current = wn.current_version(VERSION_FILE)
    notes = wn.load_notes(NOTES_DIR)
    if "--mark-seen" in args:
        call wn.mark_seen(SEEN, current)
        return 0
    end
    if "--auto" in args:
        if exists("/run/archiso") or current == "":
            return 0
        end
        versions = wn.pending(notes, wn.read_seen(SEEN), current)
        # jen jednou, i kdyz se relace ukonci s otevrenym oknem
        call wn.mark_seen(SEEN, current)
        if len(versions) > 0:
            call show(versions, notes)
        end
        return 0
    end
    versions = [v for v in wn.by_version(notes.keys()) if current == "" or wn.compare(v, current) <= 0]
    if len(versions) == 0:
        call sys.eprint(i18n.T("No release notes are available."))
        return 1
    end
    return show(versions[0:1], notes)
end

exit(main())
