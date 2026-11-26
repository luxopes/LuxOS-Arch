# LuxOS - Nastaveni > Jazyk a oblast: jazyk prostredi a formaty (datum, cisla, mena, jednotky) uzivatele
# a jazyk prihlasovaci obrazovky a novych uzivatelu.
#
# Uzivatel: ~/.config/locale.conf (LANG a LC_TIME/LC_NUMERIC/LC_MONETARY/LC_PAPER/LC_MEASUREMENT); relace ho nacte
# pri prihlaseni (luxos-wayland-session, /etc/profile.d/locale.sh), proto se zmena projevi po odhlaseni. System:
# `localectl set-locale` (systemd-localed, polkit - okno pro heslo spravce), asynchronne. Jazyky = preklady LuxOS
# (luxos-i18n); jazyk, ktery glibc nema vygenerovany, se ukaze s poznamkou (texty LuxOS jsou prelozene i tak).
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_settings_ui as ui
load env

# kod jazyka, vlastni nazev (v tom jazyce, at ho uzivatel najde i v cizim prostredi)
LANGUAGES = [["en_US", "English (United States)"], ["en_GB", "English (United Kingdom)"], ["cs_CZ", "Čeština"],
    ["sk_SK", "Slovenčina"], ["de_DE", "Deutsch"], ["es_ES", "Español"], ["fr_FR", "Français"], ["hu_HU", "Magyar"],
    ["it_IT", "Italiano"], ["nl_NL", "Nederlands"], ["pl_PL", "Polski"], ["pt_PT", "Português"],
    ["sv_SE", "Svenska"], ["uk_UA", "Українська"]]
FORMAT_KEYS = ["LC_TIME", "LC_NUMERIC", "LC_MONETARY", "LC_PAPER", "LC_MEASUREMENT"]

app = {"lang": 0, "formats": 0, "note": 0, "system": 0, "error": 0, "system_lang": ""}

function user_conf():
    return glib.user_config_dir() + "/locale.conf"
end

function base(value):
    # "cs_CZ.UTF-8" -> "cs_CZ"
    return value.strip().strip("\"'").split(".")[0].split("@")[0]
end

function current():
    conf = ui.read_kv(user_conf())
    lang = conf.get("LANG", "")
    if lang == "":
        lang = env.get("LANG", "")
    end
    if lang == "":
        lang = ui.read_kv("/etc/locale.conf").get("LANG", "en_US.UTF-8")
    end
    fmt = conf.get("LC_TIME", "")
    return {"lang": base(lang), "formats": base(fmt) if fmt != "" else ""}
end

# glibc ma jazyk vygenerovany? (locale -a: "cs_CZ.utf8")
function generated(code):
    for line in ui.run(["locale", "-a"]).split("\n"):
        if base(line.strip()) == code:
            return True
        end
    end
    return False
end

# Zapis ~/.config/locale.conf: LANG a formaty; ostatni radky souboru zustanou
function write_conf(lang, formats):
    path = user_conf()
    keep = []
    safe:
        for line in readfile(path).split("\n"):
            key = line.split("=")[0].strip()
            if line.strip() != "" and key != "LANG" and not (key in FORMAT_KEYS):
                keep.append(line)
            end
        end
    end
    lines = keep + ["LANG=" + lang + ".UTF-8"]
    if formats != "" and formats != lang:
        for key in FORMAT_KEYS:
            lines.append(key + "=" + formats + ".UTF-8")
        end
    end
    safe:
        call writefile(path + ".tmp", "\n".join(lines) + "\n")
        call glib.rename(path + ".tmp", path)
    end
    return 0
end

function update_note():
    cur = current()
    missing = []
    for code in [cur["lang"], cur["formats"]]:
        if code != "" and not (code in missing) and not generated(code):
            missing.append(code)
        end
    end
    message = i18n.T("Log out and back in to use the new language everywhere.")
    if len(missing) > 0:
        message = message + " " + i18n.T("Some older programs will stay in English: the system does not have this language installed.")
    end
    call gtk.label_set_text(app["note"], message)
    return 0
end

function on_lang(unused, code):
    if code == "":
        return 0
    end
    cur = current()
    call write_conf(code, cur["formats"])
    call update_note()
    return 0
end

function on_formats(unused, code):
    cur = current()
    call write_conf(cur["lang"], "" if code == "same" else code)
    call update_note()
    return 0
end

function on_system_done(unused, output, status):
    call gtk.widget_set_sensitive(app["system"], True)
    if status != 0:
        call gtk.label_set_text(app["error"], i18n.T("The change was not made (cancelled or not allowed)."))
    else:
        call gtk.label_set_text(app["error"], i18n.T("The login screen and new users will use this language."))
    end
    call gtk.widget_set_visible(app["error"], True)
    return 0
end

# Jazyk prihlasovaci obrazovky a novych uzivatelu = jazyk tohoto uzivatele
function on_system(unused):
    cur = current()
    call gtk.widget_set_sensitive(app["system"], False)
    call glib.spawn_capture(["localectl", "set-locale", "LANG=" + cur["lang"] + ".UTF-8"], on_system_done, 0)
    return 0
end

function on_keyboard(unused):
    call ui.launch(["luxos-settings", "keyboard"])
    return 0
end

function build(host):
    page = ui.page_box()
    cur = current()
    g = ui.group(page, i18n.T("Language"))
    options = LANGUAGES
    if not (cur["lang"] in [l[0] for l in LANGUAGES]):
        options = LANGUAGES + [[cur["lang"], cur["lang"]]]
    end
    app["lang"] = ui.combo(options, cur["lang"], "", on_lang, 0)
    call ui.row(g, i18n.T("Language"), i18n.T("Menus, apps and messages."), app["lang"])
    formats = [["same", i18n.T("Same as language")]] + LANGUAGES
    app["formats"] = ui.combo(formats, cur["formats"] if cur["formats"] != "" else "same", "", on_formats, 0)
    call ui.row(g, i18n.T("Formats"), i18n.T("Dates, times, numbers, currency and units."), app["formats"])
    app["note"] = ui.label("", "hint")
    call gtk.box_pack_start(page, app["note"], False, False, 6)
    call update_note()

    g2 = ui.group(page, i18n.T("Login Screen"))
    app["system"] = gtk.button_new(i18n.T("Use My Language"))
    call gtk.connect(app["system"], "clicked", on_system)
    call ui.row(g2, i18n.T("Login screen and new users"), i18n.T("Needs an administrator password."), app["system"])
    app["error"] = ui.label("", "")
    call gtk.box_pack_start(page, app["error"], False, False, 6)
    call gtk.widget_set_no_show_all(app["error"], True)

    g3 = ui.group(page, i18n.T("Keyboard"))
    kb = gtk.button_new(i18n.T("Keyboard Layouts…"))
    call gtk.connect(kb, "clicked", on_keyboard)
    call ui.row(g3, i18n.T("Typing in other languages"), "", kb)
    return page
end

function test(command, rest):
    return False
end
