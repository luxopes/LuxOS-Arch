# LuxOS - Nastaveni > Datum a cas: automaticky cas ze site (NTP), casove pasmo, rucni nastaveni data a casu
# a 12/24hodinovy format hodin v liste.
#
# Systemova nastaveni jdou pres `timedatectl` (systemd-timedated, opravneni polkit: okno pro heslo spravce ukaze
# luxos-polkit). Prikazy bezi asynchronne (spawn_capture), okno Nastaveni se pri cekani na heslo nezasekne; po
# dokonceni se stav nacte znovu (zrusene heslo = prepinac se vrati). Format hodin je nastaveni uzivatele:
# CLOCK_24H=yes|no v ~/.config/luxos/appearance.conf (lista ho sleduje); bez klice podle jazyka (en_US = 12 h).
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_sys as lsys
load luxos_settings_ui as ui
load env
load luxos_text as text

app = {"hidden": True, "ntp": 0, "zone": 0, "now": 0, "set_row": 0, "date": 0, "time": 0, "h24": 0,
       "error": 0, "tick": 0, "zones": [], "state": {}}

function appearance_conf():
    return glib.user_config_dir() + "/luxos/appearance.conf"
end

# Vychozi format podle jazyka: 12 h pro anglictinu v USA a dalsich zemich s 12h zvykem
function default_24h():
    lang = env.get("LC_TIME", "")
    if lang == "":
        lang = env.get("LANG", "")
    end
    for prefix in ["en_US", "en_CA", "en_AU", "en_NZ", "en_PH", "en_IN"]:
        if lang.startswith(prefix):
            return False
        end
    end
    return True
end

function clock_24h():
    value = ui.read_kv(appearance_conf()).get("CLOCK_24H", "")
    if value == "yes":
        return True
    elif value == "no":
        return False
    end
    return default_24h()
end

# ---- stav timedated ---------------------------------------------------------------------------------------

function read_state():
    st = {"zone": "", "ntp": False, "can_ntp": False, "synced": False}
    for line in ui.run(["timedatectl", "show"]).split("\n"):
        kv = line.split("=")
        if len(kv) < 2:
            continue
        end
        key = kv[0]
        value = "=".join(kv[1:])
        if key == "Timezone":
            st["zone"] = value
        elif key == "NTP":
            st["ntp"] = value == "yes"
        elif key == "CanNTP":
            st["can_ntp"] = value == "yes"
        elif key == "NTPSynchronized":
            st["synced"] = value == "yes"
        end
    end
    app["state"] = st
    return st
end

function zone_label(zone):
    # "America/Argentina/Buenos_Aires" -> "America – Argentina – Buenos Aires"
    return " – ".join(zone.replace("_", " ").split("/"))
end

function apply():
    st = app["state"]
    ui.state["quiet"] = True
    call ui.switch_set(app["ntp"], st["ntp"])
    call gtk.widget_set_sensitive(app["ntp"], st["can_ntp"])
    if st["zone"] != "":
        call ui.combo_set_active_id(app["zone"], st["zone"])
    end
    ui.state["quiet"] = False
    # rucni nastaveni jen bez automatickeho casu (timedatectl set-time jinak odmitne)
    call gtk.widget_set_sensitive(app["set_row"], not st["ntp"])
    call update_now(0)
    return 0
end

function update_now(unused):
    if app["now"] == 0:
        return False
    end
    fmt = "%H:%M:%S" if clock_24h() else "%-I:%M:%S %p"
    label = lsys.strftime_local("%Y-%m-%d") + "  " + lsys.strftime_local(fmt)
    if app["state"].get("ntp", False):
        label = label + "  ·  " + (i18n.T("synchronized") if app["state"].get("synced", False) else i18n.T("not synchronized yet"))
    end
    call gtk.label_set_text(app["now"], label)
    if app["hidden"]:
        app["tick"] = 0
        return False
    end
    return True
end

function show_error(message):
    if app["error"] != 0:
        call gtk.label_set_text(app["error"], message)
        call gtk.widget_set_visible(app["error"], message != "")
    end
    return 0
end

# ---- zmeny (asynchronne, polkit) --------------------------------------------------------------------------

function on_done(what, output, status):
    if status != 0:
        call show_error(i18n.T("The change was not made (cancelled or not allowed)."))
    else:
        call show_error("")
    end
    call read_state()
    call apply()
    return 0
end

function timedatectl(args, what):
    call show_error("")
    call glib.spawn_capture(["timedatectl"] + args, on_done, what)
    return 0
end

function on_ntp(unused, on):
    return timedatectl(["set-ntp", "true" if on else "false"], "ntp")
end

function on_zone(unused, zone):
    if zone == "" or zone == app["state"].get("zone", ""):
        return 0
    end
    return timedatectl(["set-timezone", zone], "zone")
end

function valid_date(text):
    parts = text.strip().split("-")
    if len(parts) != 3 or len(parts[0]) != 4:
        return False
    end
    for p in parts:
        if not text.is_digits(p):
            return False
        end
    end
    return Int(parts[1]) >= 1 and Int(parts[1]) <= 12 and Int(parts[2]) >= 1 and Int(parts[2]) <= 31
end

function valid_time(text):
    parts = text.strip().split(":")
    if len(parts) < 2 or len(parts) > 3:
        return False
    end
    for p in parts:
        if not text.is_digits(p):
            return False
        end
    end
    return Int(parts[0]) < 24 and Int(parts[1]) < 60 and (len(parts) == 2 or Int(parts[2]) < 60)
end

function on_set_time(unused):
    date = gtk.entry_get_text(app["date"]).strip()
    time = gtk.entry_get_text(app["time"]).strip()
    if not valid_date(date) or not valid_time(time):
        return show_error(i18n.T("Enter the date as YYYY-MM-DD and the time as HH:MM."))
    end
    return timedatectl(["set-time", date + " " + time], "time")
end

function on_h24(unused, on):
    call ui.write_kv(appearance_conf(), "CLOCK_24H", "yes" if on else "no")
    call update_now(0)
    return 0
end

# ---- stranka ----------------------------------------------------------------------------------------------

function build(host):
    page = ui.page_box()
    g = ui.group(page, i18n.T("Date & Time"))
    app["now"] = ui.label("", "")
    call ui.row(g, i18n.T("Now"), "", app["now"])
    app["ntp"] = ui.switch(False, on_ntp, 0)
    call ui.row(g, i18n.T("Set time automatically"), i18n.T("From time servers on the internet."), app["ntp"])
    zones = []
    for z in ui.run(["timedatectl", "list-timezones"]).split("\n"):
        if z.strip() != "":
            zones.append([z.strip(), zone_label(z.strip())])
        end
    end
    app["zones"] = zones
    app["zone"] = ui.combo(zones, "", "", on_zone, 0)
    call ui.row(g, i18n.T("Time zone"), "", app["zone"])

    g2 = ui.group(page, i18n.T("Set Manually"))
    box = gtk.box_new(gtk.HORIZONTAL, 6)
    app["date"] = gtk.entry_new()
    call gtk.entry_set_placeholder_text(app["date"], "2026-01-31")
    call gtk.entry_set_width_chars(app["date"], 11)
    call gtk.entry_set_text(app["date"], lsys.strftime_local("%Y-%m-%d"))
    app["time"] = gtk.entry_new()
    call gtk.entry_set_placeholder_text(app["time"], "14:30")
    call gtk.entry_set_width_chars(app["time"], 6)
    call gtk.entry_set_text(app["time"], lsys.strftime_local("%H:%M"))
    set_button = gtk.button_new(i18n.T("Set"))
    call gtk.connect(set_button, "clicked", on_set_time)
    call gtk.box_pack_start(box, app["date"], False, False, 0)
    call gtk.box_pack_start(box, app["time"], False, False, 0)
    call gtk.box_pack_start(box, set_button, False, False, 0)
    app["set_row"] = box
    call ui.row(g2, i18n.T("Date and time"), i18n.T("Turn off automatic time first."), box)
    app["error"] = ui.label("", "lx-error")
    call gtk.box_pack_start(page, app["error"], False, False, 0)
    call gtk.widget_set_no_show_all(app["error"], True)

    g3 = ui.group(page, i18n.T("Clock"))
    app["h24"] = ui.switch(clock_24h(), on_h24, 0)
    call ui.row(g3, i18n.T("24-hour time"), i18n.T("Clock in the menu bar and on the lock screen."), app["h24"])
    call read_state()
    call apply()
    return page
end

function show(host):
    if not app["hidden"]:
        return 0
    end
    app["hidden"] = False
    call read_state()
    call apply()
    app["tick"] = glib.timeout_add_data(1000, update_now, 0)
    return 0
end

function leave(host):
    app["hidden"] = True
    if app["tick"] != 0:
        call glib.source_remove(app["tick"])
        app["tick"] = 0
    end
    return 0
end

function test(command, rest):
    return False
end
