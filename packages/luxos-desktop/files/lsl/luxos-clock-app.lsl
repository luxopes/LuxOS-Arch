# LuxOS - aplikace Hodiny (jako Hodiny v Androidu): Budik, Svetovy cas, Stopky a Minutka.
#   Budik      seznam budiku (cas, popisek, dny v tydnu nebo jednou), vypinac u kazdeho, + novy, x smaze;
#              zazvoni okno nad ostatnimi se zvukem: Odlozit (10 min) / Vypnout
#   Svetovy cas mistni cas a zvolena mesta s rozdilem casu (hledani mezi mesty casovych pasem)
#   Stopky     start/stop, mezicasy
#   Minutka    hodiny/minuty/sekundy nebo rychla volba 1-30 min, start/pauza/vynulovat; konec = zvoneni
# Zavreni okna: s aktivnim budikem nebo bezici minutkou proces zustane na pozadi (budik zazvoni i bez
# okna), jinak skonci. Po prihlaseni ho spusti "luxos-clock-app --background" (bez zapnuteho budiku
# hned skonci). Jedna instance na uzivatele a displej: dalsi spusteni jen ukaze okno (abstraktni socket).
# Data: ~/.local/share/luxos/clock/clock.json {"alarms": [...], "cities": ["Europe/London", ...]}.
load env, json
load luxos_glib, glib as glib
load luxos_gio, gio as gio
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_sys as sys

SOUND = "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"
SNOOZE_MIN = 10
SOCKET = "luxos-clock-app-"
DAY_KEYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
DEFAULT_CITIES = ["Europe/London", "America/New_York", "Asia/Tokyo"]

CSS = ("window.lca { background-color: @c_bg; }\n"
    + ".lca label { color: @c_fg; }\n"
    + ".lca .dim { color: @c_dim; }\n"
    + ".lca-seg { background-color: @c_tile; border-radius: 10px; padding: 3px; }\n"
    + ".lca-seg button { border-radius: 8px; padding: 4px 12px; background: none; border: none; box-shadow: none; color: @c_fg; font-weight: 600; font-size: 12px; outline: none; }\n"
    + ".lca-seg button.active { background-color: @c_on; box-shadow: 0 1px 2px rgba(0, 0, 0, 0.2); }\n"
    + ".lca-big { font-size: 56px; font-weight: 300; font-feature-settings: \"tnum\"; }\n"
    + ".lca-mid { font-size: 30px; font-weight: 400; font-feature-settings: \"tnum\"; }\n"
    + ".lca-row { background-color: @c_tile; border-radius: 14px; padding: 12px 16px; }\n"
    + ".lca-row.off label { color: @c_dim; }\n"
    + ".lca-title { font-size: 13px; font-weight: 600; }\n"
    + ".lca-small { font-size: 12px; }\n"
    + "button.lca-round { border-radius: 999px; min-width: 64px; min-height: 64px; padding: 0; font-weight: 600; border: none; box-shadow: none; background-image: none; background-color: @c_tile; color: @c_fg; }\n"
    + "button.lca-round.go { background-color: @c_accent; color: white; }\n"
    + "button.lca-round.go label { color: white; }\n"
    + "button.lca-round:disabled { opacity: 0.4; }\n"
    + "button.lca-icon { border-radius: 999px; min-width: 30px; min-height: 30px; padding: 0; background: none; border: none; box-shadow: none; }\n"
    + "button.lca-icon:hover { background-color: @c_tile; }\n"
    + "button.lca-add { border-radius: 999px; min-width: 40px; min-height: 40px; background-color: @c_accent; background-image: none; border: none; color: white; }\n"
    + "button.lca-chip { border-radius: 999px; padding: 2px 10px; min-height: 26px; background-image: none; background-color: @c_tile; border: none; box-shadow: none; color: @c_fg; font-size: 12px; }\n"
    + "button.lca-chip:checked { background-color: @c_accent; color: white; }\n"
    + "button.lca-chip:checked label { color: white; }\n"
    + "button.lca-city { border-radius: 10px; padding: 6px 10px; background: none; border: none; box-shadow: none; }\n"
    + "button.lca-city:hover { background-color: @c_tile; }\n"
    + "window.lca-ring { background-color: @c_bg; border-radius: 22px; }\n")

DARK = ("@define-color c_bg #1c1c22; @define-color c_fg #f4f4f8; @define-color c_dim rgba(244, 244, 248, 0.58);\n"
    + "@define-color c_tile rgba(255, 255, 255, 0.07); @define-color c_on rgba(255, 255, 255, 0.2); @define-color c_accent #ff7a2f;\n")
LIGHT = ("@define-color c_bg #f6f6f9; @define-color c_fg #1d1d27; @define-color c_dim rgba(29, 29, 39, 0.55);\n"
    + "@define-color c_tile rgba(0, 0, 0, 0.05); @define-color c_on #ffffff; @define-color c_accent #f26a1b;\n")

data = {"alarms": [], "cities": []}
ui = {"win": 0, "views": {}, "seg": {}, "tab": "alarms", "visible": False}
alarm_ui = {"list": 0, "form": 0}
world_ui = {"list": 0, "results": 0, "entry": 0, "local": 0, "rows": []}
stopwatch = {"running": False, "start": 0.0, "elapsed": 0.0, "laps": [], "label": 0, "laps_box": 0, "go": 0, "lap": 0, "timer": 0}
timer = {"running": False, "end": 0.0, "left": 0.0, "total": 0.0, "label": 0, "go": 0, "spins": [], "timer": 0}
ringing = {"win": 0, "sound": 0, "what": ""}
snoozed = []      # [unix cas] odlozenych budiku
last_minute = {"key": ""}
zones = []        # [[mesto, identifikator]]

# ---- data ---------------------------------------------------------------------------------------

function data_path():
    return glib.user_data_dir() + "/luxos/clock/clock.json"
end

function load_data():
    raw = glib.read_text(data_path())
    data["alarms"] = []
    data["cities"] = DEFAULT_CITIES
    if raw == "":
        return 0
    end
    parsed = None
    try:
        parsed = json.decode(raw)
    else:
        return 0
    end
    if type(parsed) != "Dictionary":
        return 0
    end
    if type(parsed.get("alarms")) == "List":
        for a in parsed["alarms"]:
            if type(a) == "Dictionary" and type(a.get("h")) == "Int" and type(a.get("m")) == "Int":
                days = []
                if type(a.get("days")) == "List":
                    for d in a["days"]:
                        if type(d) == "Int" and d >= 0 and d <= 6:
                            days.append(d)
                        end
                    end
                end
                data["alarms"].append({"h": a["h"] % 24, "m": a["m"] % 60, "label": String(a.get("label", "")),
                                       "days": days, "on": a.get("on") != False})
            end
        end
    end
    if type(parsed.get("cities")) == "List":
        cities = []
        for c in parsed["cities"]:
            if type(c) == "String" and c != "":
                cities.append(c)
            end
        end
        data["cities"] = cities
    end
    return 0
end

function save_data():
    call sys.mkdir_p(glib.user_data_dir() + "/luxos/clock")
    call glib.write_atomic(data_path(), json.encode({"alarms": data["alarms"], "cities": data["cities"]}))
    return 0
end

function any_alarm_on():
    for a in data["alarms"]:
        if a["on"]:
            return True
        end
    end
    return len(snoozed) > 0
end

# ---- pomucky ------------------------------------------------------------------------------------

function label(text, classes):
    l = gtk.label_new(text)
    call gtk.label_set_xalign(l, 0.0)
    for c in classes:
        call gtk.widget_add_class(l, c)
    end
    return l
end

function two(n):
    if n < 10:
        return "0" + String(n)
    end
    return String(n)
end

function theme_is_dark():
    name = gtk.settings_theme_name().lower()
    return name.find("dark") >= 0 or gtk.settings_prefer_dark()
end

theme = {"provider": 0, "dark": None}

function theme_apply():
    dark = theme_is_dark()
    if dark == theme["dark"]:
        return 0
    end
    theme["dark"] = dark
    css = LIGHT + CSS
    if dark:
        css = DARK + CSS
    end
    if theme["provider"] == 0:
        theme["provider"] = gtk.css_load(css)
    else:
        call gtk.css_set(theme["provider"], css)
    end
    return 0
end

function on_theme_changed(pspec, settings):
    call theme_apply()
    return 0
end

function clear(box):
    for child in gtk.container_get_children(box):
        call gtk.widget_destroy(child)
    end
    return 0
end

# "Pracovni dny" / "Kazdy den" / "Jednou" / "Po St Pa"
function days_text(days):
    if len(days) == 0:
        return i18n.T("Once")
    end
    if len(days) == 7:
        return i18n.T("Every day")
    end
    if sorted(days) == [0, 1, 2, 3, 4]:
        return i18n.T("Weekdays")
    end
    if sorted(days) == [5, 6]:
        return i18n.T("Weekends")
    end
    names = []
    for d in sorted(days):
        names.append(day_short(d))
    end
    return " ".join(names)
end

# zkratka dne podle jazyka (2024-01-01 je pondeli)
function day_short(d):
    return glib.format_date(2024, 1, d + 1, "%a")
end

# ---- Budik --------------------------------------------------------------------------------------

function build_alarms():
    view = gtk.box_new(gtk.VERTICAL, 10)
    top = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.box_pack_start(top, label(i18n.T("Alarms"), ["lca-title"]), True, True, 0)
    add = gtk.button_new_from_icon_name("list-add-symbolic", 4)
    call gtk.widget_add_class(add, "lca-add")
    call gtk.widget_set_tooltip(add, i18n.T("New Alarm"))
    call gtk.connect(add, "clicked", on_alarm_add)
    call gtk.box_pack_end(top, add, False, False, 0)
    call gtk.box_pack_start(view, top, False, False, 0)
    alarm_ui["form"] = gtk.box_new(gtk.VERTICAL, 8)
    call gtk.box_pack_start(view, alarm_ui["form"], False, False, 0)
    alarm_ui["list"] = gtk.box_new(gtk.VERTICAL, 8)
    call gtk.box_pack_start(view, alarm_ui["list"], False, False, 0)
    call alarms_refresh()
    return view
end

function alarms_refresh():
    box = alarm_ui["list"]
    call clear(box)
    if len(data["alarms"]) == 0:
        call gtk.box_pack_start(box, label(i18n.T("No alarms. Add one with +."), ["dim", "lca-small"]), False, False, 8)
    end
    # podle casu (klic = minuta dne * 1000 + index)
    order = []
    for i in range(len(data["alarms"])):
        a = data["alarms"][i]
        order.append((a["h"] * 60 + a["m"]) * 1000 + i)
    end
    for k in sorted(order):
        i = k % 1000
        a = data["alarms"][i]
        row = gtk.box_new(gtk.HORIZONTAL, 12)
        call gtk.widget_add_class(row, "lca-row")
        if not a["on"]:
            call gtk.widget_add_class(row, "off")
        end
        col = gtk.box_new(gtk.VERTICAL, 0)
        call gtk.box_pack_start(col, label(two(a["h"]) + ":" + two(a["m"]), ["lca-mid"]), False, False, 0)
        sub = days_text(a["days"])
        if a["label"] != "":
            sub = a["label"] + " · " + sub
        end
        call gtk.box_pack_start(col, label(sub, ["dim", "lca-small"]), False, False, 0)
        call gtk.box_pack_start(row, col, True, True, 0)
        sw = gtk.switch_new()
        call gtk.switch_set_active(sw, a["on"])
        call gtk.widget_set_valign(sw, gtk.ALIGN_CENTER)
        call gtk.connect_data(sw, "state-set", 1, on_alarm_switch, i)
        call gtk.box_pack_start(row, sw, False, False, 0)
        rm = gtk.button_new_from_icon_name("window-close-symbolic", 2)
        call gtk.widget_add_class(rm, "lca-icon")
        call gtk.widget_set_valign(rm, gtk.ALIGN_CENTER)
        call gtk.widget_set_tooltip(rm, i18n.T("Delete"))
        call gtk.connect_data(rm, "clicked", 0, on_alarm_delete, i)
        call gtk.box_pack_start(row, rm, False, False, 0)
        call gtk.box_pack_start(box, row, False, False, 0)
    end
    call gtk.widget_show_all(box)
    return 0
end

function on_alarm_switch(index, state, switch):
    if index < len(data["alarms"]):
        data["alarms"][index]["on"] = state != 0
        call save_data()
        call glib.idle_add(alarms_refresh_once)
    end
    return False
end

function alarms_refresh_once():
    call alarms_refresh()
    return False
end

function on_alarm_delete(index, button):
    if index < len(data["alarms"]):
        call data["alarms"].pop(index)
        call save_data()
        call glib.idle_add(alarms_refresh_once)
    end
    return 0
end

# Formular noveho budiku: hodiny, minuty, popisek, dny
function on_alarm_add(button):
    form = alarm_ui["form"]
    if len(gtk.container_get_children(form)) > 0:
        call clear(form)
        return 0
    end
    box = gtk.box_new(gtk.VERTICAL, 10)
    call gtk.widget_add_class(box, "lca-row")
    times = gtk.box_new(gtk.HORIZONTAL, 6)
    d = glib.local_date()
    hs = gtk.spin_button_new_with_range(0, 23, 1)
    ms = gtk.spin_button_new_with_range(0, 59, 1)
    call gtk.spin_button_set_value(hs, d[3])
    call gtk.spin_button_set_value(ms, d[4])
    call gtk.box_pack_start(times, hs, False, False, 0)
    call gtk.box_pack_start(times, label(":", ["lca-mid"]), False, False, 0)
    call gtk.box_pack_start(times, ms, False, False, 0)
    entry = gtk.entry_new()
    call gtk.entry_set_placeholder_text(entry, i18n.T("Label"))
    call gtk.box_pack_start(times, entry, True, True, 8)
    call gtk.box_pack_start(box, times, False, False, 0)
    days = gtk.box_new(gtk.HORIZONTAL, 4)
    chips = []
    for i in range(7):
        chip = gtk.toggle_button_new(day_short(i))
        call gtk.widget_add_class(chip, "lca-chip")
        call gtk.box_pack_start(days, chip, True, True, 0)
        chips.append(chip)
    end
    call gtk.box_pack_start(box, days, False, False, 0)
    buttons = gtk.box_new(gtk.HORIZONTAL, 8)
    save = gtk.button_new(i18n.T("Save"))
    cancel = gtk.button_new(i18n.T("Cancel"))
    call gtk.widget_add_class(save, "suggested-action")
    call gtk.box_pack_end(buttons, save, False, False, 0)
    call gtk.box_pack_end(buttons, cancel, False, False, 0)
    call gtk.box_pack_start(box, buttons, False, False, 0)
    state = {"h": hs, "m": ms, "label": entry, "chips": chips}
    call gtk.connect_data(save, "clicked", 0, on_alarm_save, state)
    call gtk.connect(cancel, "clicked", on_alarm_cancel)
    call gtk.box_pack_start(form, box, False, False, 0)
    call gtk.widget_show_all(form)
    return 0
end

function on_alarm_save(state, button):
    days = []
    for i in range(7):
        if gtk.toggle_button_get_active(state["chips"][i]):
            days.append(i)
        end
    end
    data["alarms"].append({"h": Int(gtk.spin_button_get_value(state["h"])), "m": Int(gtk.spin_button_get_value(state["m"])),
                           "label": gtk.entry_get_text(state["label"]).strip(), "days": days, "on": True})
    call save_data()
    call clear(alarm_ui["form"])
    call alarms_refresh()
    return 0
end

function on_alarm_cancel(button):
    call clear(alarm_ui["form"])
    return 0
end

# Kazdou sekundu: budik v novou minutu (den v tydnu 0 = pondeli), odlozene budiky
function check_alarms():
    d = glib.local_date()
    key = String(d[0]) + "-" + String(d[1]) + "-" + String(d[2]) + " " + String(d[3]) + ":" + String(d[4])
    if key != last_minute["key"]:
        last_minute["key"] = key
        weekday = d[6] - 1
        changed = False
        for a in data["alarms"]:
            if a["on"] and a["h"] == d[3] and a["m"] == d[4] and (len(a["days"]) == 0 or weekday in a["days"]):
                if len(a["days"]) == 0:
                    a["on"] = False
                    changed = True
                end
                call ring(a["label"], two(a["h"]) + ":" + two(a["m"]))
            end
        end
        if changed:
            call save_data()
            call alarms_refresh()
        end
    end
    now = glib.now()
    keep = []
    for t in snoozed:
        if t <= now:
            call ring(i18n.T("Snoozed alarm"), glib.date_time_format("%H:%M"))
        else:
            keep.append(t)
        end
    end
    snoozed.clear()
    for t in keep:
        snoozed.append(t)
    end
    return True
end

# ---- Zvoneni ------------------------------------------------------------------------------------

function ring(title, big):
    call stop_ringing()
    ringing["what"] = title
    # zvuk dokola, dokud se zvoneni nevypne
    ringing["sound"] = glib.spawn(["sh", "-c", "while :; do paplay " + glib.shell_quote(SOUND) + " 2>/dev/null || sleep 2; done"])
    call glib.spawn_quiet(["notify-send", "-a", i18n.T("Clock"), "-i", "org.gnome.clocks", "-u", "critical", big, title])
    win = gtk.window_new(i18n.T("Clock"))
    ringing["win"] = win
    call gtk.widget_add_class(win, "lca")
    call gtk.window_set_keep_above(win, True)
    call gtk.window_set_decorated(win, False)
    call gtk.window_set_position(win, gtk.WIN_POS_CENTER)
    call gtk.window_stick(win)
    box = gtk.box_new(gtk.VERTICAL, 12)
    call gtk.widget_set_margins(box, 40, 40, 30, 30)
    b = label(big, ["lca-big"])
    call gtk.label_set_xalign(b, 0.5)
    call gtk.box_pack_start(box, b, False, False, 0)
    t = label(title, ["lca-title"])
    call gtk.label_set_xalign(t, 0.5)
    call gtk.box_pack_start(box, t, False, False, 0)
    buttons = gtk.box_new(gtk.HORIZONTAL, 24)
    call gtk.widget_set_halign(buttons, gtk.ALIGN_CENTER)
    snooze = gtk.button_new(i18n.T("Snooze"))
    stop = gtk.button_new(i18n.T("Stop"))
    for btn in [snooze, stop]:
        call gtk.widget_add_class(btn, "lca-round")
        call gtk.box_pack_start(buttons, btn, False, False, 0)
    end
    call gtk.widget_add_class(stop, "go")
    call gtk.connect(snooze, "clicked", on_snooze)
    call gtk.connect(stop, "clicked", on_stop)
    call gtk.box_pack_start(box, buttons, False, False, 8)
    call gtk.container_add(win, box)
    call gtk.widget_show_all(win)
    call gtk.window_present(win)
    return 0
end

function stop_ringing():
    if ringing["sound"] != 0:
        # cela skupina procesu (sh + paplay, spusteno v nove relaci)
        call glib.kill(-ringing["sound"], 15)
        call glib.kill(ringing["sound"], 15)
        ringing["sound"] = 0
    end
    if ringing["win"] != 0:
        call gtk.widget_destroy(ringing["win"])
        ringing["win"] = 0
    end
    return 0
end

function on_snooze(button):
    snoozed.append(glib.now() + SNOOZE_MIN * 60)
    call stop_ringing()
    return 0
end

function on_stop(button):
    call stop_ringing()
    call maybe_quit()
    return 0
end

# ---- Svetovy cas --------------------------------------------------------------------------------

function load_zones():
    if len(zones) > 0:
        return 0
    end
    for line in glib.read_text("/usr/share/zoneinfo/zone1970.tab").split("\n"):
        if line == "" or line.startswith("#"):
            continue
        end
        parts = line.split("\t")
        if len(parts) >= 3:
            ident = parts[2]
            zones.append([ident.split("/")[-1].replace("_", " "), ident])
        end
    end
    return 0
end

function city_name(ident):
    return ident.split("/")[-1].replace("_", " ")
end

# [cas "HH:MM", popis "Dnes, +1 h"] pro casove pasmo
function zone_time(ident):
    now = glib.now()
    here = glib.localtime(now)
    call glib.set_tz(ident)
    there = glib.localtime(now)
    call glib.unset_tz()
    # rozdil v minutach (bez sekund) pres den v roce
    day_diff = there[7] - here[7]
    if day_diff > 1:
        day_diff = -1
    elif day_diff < -1:
        day_diff = 1
    end
    minutes = day_diff * 1440 + (there[3] * 60 + there[4]) - (here[3] * 60 + here[4])
    day = i18n.T("Today")
    if day_diff > 0:
        day = i18n.T("Tomorrow")
    elif day_diff < 0:
        day = i18n.T("Yesterday")
    end
    diff = ""
    if minutes != 0:
        sign = "+"
        if minutes < 0:
            sign = "−"
        end
        a = abs(minutes)
        diff = ", " + sign + String(a // 60) + " h"
        if a % 60 != 0:
            diff = diff + " " + String(a % 60) + " min"
        end
    end
    return [two(there[3]) + ":" + two(there[4]), day + diff]
end

function build_world():
    view = gtk.box_new(gtk.VERTICAL, 10)
    world_ui["local"] = label("", ["lca-big"])
    call gtk.label_set_xalign(world_ui["local"], 0.5)
    call gtk.box_pack_start(view, world_ui["local"], False, False, 0)
    world_ui["date"] = label("", ["dim"])
    call gtk.label_set_xalign(world_ui["date"], 0.5)
    call gtk.box_pack_start(view, world_ui["date"], False, False, 4)
    entry = gtk.search_entry_new()
    call gtk.entry_set_placeholder_text(entry, i18n.T("Add a city"))
    call gtk.connect(entry, "changed", on_city_search)
    world_ui["entry"] = entry
    call gtk.box_pack_start(view, entry, False, False, 0)
    world_ui["results"] = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.box_pack_start(view, world_ui["results"], False, False, 0)
    world_ui["list"] = gtk.box_new(gtk.VERTICAL, 8)
    call gtk.box_pack_start(view, world_ui["list"], False, False, 0)
    call world_refresh()
    return view
end

function world_refresh():
    box = world_ui["list"]
    call clear(box)
    world_ui["rows"] = []
    for i in range(len(data["cities"])):
        ident = data["cities"][i]
        row = gtk.box_new(gtk.HORIZONTAL, 12)
        call gtk.widget_add_class(row, "lca-row")
        col = gtk.box_new(gtk.VERTICAL, 0)
        call gtk.box_pack_start(col, label(city_name(ident), ["lca-title"]), False, False, 0)
        sub = label("", ["dim", "lca-small"])
        call gtk.box_pack_start(col, sub, False, False, 0)
        call gtk.box_pack_start(row, col, True, True, 0)
        t = label("", ["lca-mid"])
        call gtk.box_pack_start(row, t, False, False, 0)
        rm = gtk.button_new_from_icon_name("window-close-symbolic", 2)
        call gtk.widget_add_class(rm, "lca-icon")
        call gtk.widget_set_valign(rm, gtk.ALIGN_CENTER)
        call gtk.widget_set_tooltip(rm, i18n.T("Remove"))
        call gtk.connect_data(rm, "clicked", 0, on_city_remove, i)
        call gtk.box_pack_start(row, rm, False, False, 0)
        call gtk.box_pack_start(box, row, False, False, 0)
        world_ui["rows"].append([ident, t, sub])
    end
    call world_tick()
    call gtk.widget_show_all(box)
    return 0
end

function world_tick():
    if world_ui["local"] == 0:
        return 0
    end
    call gtk.label_set_text(world_ui["local"], glib.date_time_format("%H:%M"))
    call gtk.label_set_text(world_ui["date"], glib.date_time_format("%A %-d. %B"))
    for r in world_ui["rows"]:
        z = zone_time(r[0])
        call gtk.label_set_text(r[1], z[0])
        call gtk.label_set_text(r[2], z[1])
    end
    return 0
end

function on_city_remove(index, button):
    if index < len(data["cities"]):
        call data["cities"].pop(index)
        call save_data()
        call glib.idle_add(world_refresh_once)
    end
    return 0
end

function world_refresh_once():
    call world_refresh()
    return False
end

# Hledani mesta bez ohledu na velikost pismen; nejvys 6 vysledku
function on_city_search(entry):
    box = world_ui["results"]
    call clear(box)
    q = gtk.entry_get_text(entry).strip().lower()
    if len(q) < 2:
        return 0
    end
    call load_zones()
    count = 0
    for z in zones:
        if z[0].lower().find(q) >= 0 or z[1].lower().find(q) >= 0:
            b = gtk.button_new(z[0] + "  ·  " + z[1])
            call gtk.widget_add_class(b, "lca-city")
            call gtk.connect_data(b, "clicked", 0, on_city_add, z[1])
            call gtk.box_pack_start(box, b, False, False, 0)
            count = count + 1
            if count >= 6:
                break
            end
        end
    end
    call gtk.widget_show_all(box)
    return 0
end

function on_city_add(ident, button):
    if ident not in data["cities"]:
        data["cities"].append(ident)
        call save_data()
    end
    call gtk.entry_set_text(world_ui["entry"], "")
    call glib.idle_add(world_refresh_once)
    return 0
end

# ---- Stopky -------------------------------------------------------------------------------------

function fmt_stopwatch(sec):
    cs = Int(sec * 100.0)
    return two(cs // 6000) + ":" + two((cs // 100) % 60) + "." + two(cs % 100)
end

function stopwatch_elapsed():
    if stopwatch["running"]:
        return stopwatch["elapsed"] + monotonic() - stopwatch["start"]
    end
    return stopwatch["elapsed"]
end

function build_stopwatch():
    view = gtk.box_new(gtk.VERTICAL, 16)
    stopwatch["label"] = label(fmt_stopwatch(0.0), ["lca-big"])
    call gtk.label_set_xalign(stopwatch["label"], 0.5)
    call gtk.box_pack_start(view, stopwatch["label"], False, False, 20)
    buttons = gtk.box_new(gtk.HORIZONTAL, 40)
    call gtk.widget_set_halign(buttons, gtk.ALIGN_CENTER)
    stopwatch["lap"] = gtk.button_new(i18n.T("Lap"))
    stopwatch["go"] = gtk.button_new(i18n.T("Start"))
    for b in [stopwatch["lap"], stopwatch["go"]]:
        call gtk.widget_add_class(b, "lca-round")
        call gtk.box_pack_start(buttons, b, False, False, 0)
    end
    call gtk.widget_add_class(stopwatch["go"], "go")
    call gtk.connect(stopwatch["go"], "clicked", on_stopwatch_go)
    call gtk.connect(stopwatch["lap"], "clicked", on_stopwatch_lap)
    call gtk.box_pack_start(view, buttons, False, False, 0)
    stopwatch["laps_box"] = gtk.box_new(gtk.VERTICAL, 4)
    call gtk.box_pack_start(view, stopwatch["laps_box"], False, False, 0)
    call stopwatch_buttons()
    return view
end

function stopwatch_buttons():
    if stopwatch["running"]:
        call gtk.button_set_label(stopwatch["go"], i18n.T("Stop"))
        call gtk.button_set_label(stopwatch["lap"], i18n.T("Lap"))
    else:
        call gtk.button_set_label(stopwatch["go"], i18n.T("Start"))
        call gtk.button_set_label(stopwatch["lap"], i18n.T("Reset"))
    end
    call gtk.widget_set_sensitive(stopwatch["lap"], stopwatch["running"] or stopwatch["elapsed"] > 0.0)
    return 0
end

function on_stopwatch_go(button):
    if stopwatch["running"]:
        stopwatch["elapsed"] = stopwatch_elapsed()
        stopwatch["running"] = False
    else:
        stopwatch["start"] = monotonic()
        stopwatch["running"] = True
        if stopwatch["timer"] == 0:
            stopwatch["timer"] = glib.timeout_add(40, stopwatch_tick)
        end
    end
    call stopwatch_buttons()
    call gtk.label_set_text(stopwatch["label"], fmt_stopwatch(stopwatch_elapsed()))
    return 0
end

function on_stopwatch_lap(button):
    if stopwatch["running"]:
        total = stopwatch_elapsed()
        prev = 0.0
        if len(stopwatch["laps"]) > 0:
            prev = stopwatch["laps"][-1]
        end
        stopwatch["laps"].append(total)
        row = gtk.box_new(gtk.HORIZONTAL, 8)
        call gtk.widget_add_class(row, "lca-row")
        call gtk.box_pack_start(row, label(i18n.TF("Lap %s", [String(len(stopwatch["laps"]))]), ["lca-small"]), True, True, 0)
        call gtk.box_pack_start(row, label("+" + fmt_stopwatch(total - prev), ["dim", "lca-small"]), False, False, 0)
        call gtk.box_pack_start(row, label(fmt_stopwatch(total), ["lca-title"]), False, False, 0)
        call gtk.box_pack_start(stopwatch["laps_box"], row, False, False, 0)
        call gtk.box_reorder_child(stopwatch["laps_box"], row, 0)
        call gtk.widget_show_all(row)
    else:
        stopwatch["elapsed"] = 0.0
        stopwatch["laps"] = []
        call clear(stopwatch["laps_box"])
        call gtk.label_set_text(stopwatch["label"], fmt_stopwatch(0.0))
    end
    call stopwatch_buttons()
    return 0
end

function stopwatch_tick():
    if not stopwatch["running"]:
        stopwatch["timer"] = 0
        return False
    end
    if ui["visible"] and ui["tab"] == "stopwatch":
        call gtk.label_set_text(stopwatch["label"], fmt_stopwatch(stopwatch_elapsed()))
    end
    return True
end

# ---- Minutka ------------------------------------------------------------------------------------

function fmt_timer(sec):
    s = Int(sec + 0.999)
    if s >= 3600:
        return String(s // 3600) + ":" + two((s // 60) % 60) + ":" + two(s % 60)
    end
    return two(s // 60) + ":" + two(s % 60)
end

function timer_left():
    if timer["running"]:
        return max(0.0, timer["end"] - monotonic())
    end
    return timer["left"]
end

function build_timer():
    view = gtk.box_new(gtk.VERTICAL, 14)
    timer["label"] = label("05:00", ["lca-big"])
    call gtk.label_set_xalign(timer["label"], 0.5)
    call gtk.box_pack_start(view, timer["label"], False, False, 16)
    spins = gtk.box_new(gtk.HORIZONTAL, 6)
    call gtk.widget_set_halign(spins, gtk.ALIGN_CENTER)
    timer["spins"] = []
    limits = [23, 59, 59]
    names = [i18n.T("h"), i18n.T("min"), i18n.T("s")]
    for i in range(3):
        sp = gtk.spin_button_new_with_range(0, limits[i], 1)
        call gtk.entry_set_width_chars(sp, 2)
        call gtk.connect(sp, "value-changed", on_timer_spin)
        call gtk.box_pack_start(spins, sp, False, False, 0)
        call gtk.box_pack_start(spins, label(names[i], ["dim"]), False, False, 4)
        timer["spins"].append(sp)
    end
    call gtk.spin_button_set_value(timer["spins"][1], 5)
    call gtk.box_pack_start(view, spins, False, False, 0)
    presets = gtk.box_new(gtk.HORIZONTAL, 6)
    call gtk.widget_set_halign(presets, gtk.ALIGN_CENTER)
    for m in [1, 3, 5, 10, 15, 30]:
        b = gtk.button_new(String(m) + " " + i18n.T("min"))
        call gtk.widget_add_class(b, "lca-chip")
        call gtk.connect_data(b, "clicked", 0, on_timer_preset, m)
        call gtk.box_pack_start(presets, b, False, False, 0)
    end
    call gtk.box_pack_start(view, presets, False, False, 0)
    buttons = gtk.box_new(gtk.HORIZONTAL, 40)
    call gtk.widget_set_halign(buttons, gtk.ALIGN_CENTER)
    reset = gtk.button_new(i18n.T("Reset"))
    timer["go"] = gtk.button_new(i18n.T("Start"))
    for b in [reset, timer["go"]]:
        call gtk.widget_add_class(b, "lca-round")
        call gtk.box_pack_start(buttons, b, False, False, 0)
    end
    call gtk.widget_add_class(timer["go"], "go")
    call gtk.connect(timer["go"], "clicked", on_timer_go)
    call gtk.connect(reset, "clicked", on_timer_reset)
    call gtk.box_pack_start(view, buttons, False, False, 10)
    call timer_from_spins()
    return view
end

function timer_from_spins():
    if timer["running"]:
        return 0
    end
    total = 0.0
    mult = [3600.0, 60.0, 1.0]
    for i in range(3):
        total = total + gtk.spin_button_get_value(timer["spins"][i]) * mult[i]
    end
    timer["total"] = total
    timer["left"] = total
    call gtk.label_set_text(timer["label"], fmt_timer(total))
    if timer["go"] != 0:
        call gtk.widget_set_sensitive(timer["go"], total > 0.0)
    end
    return 0
end

function on_timer_spin(spin):
    call timer_from_spins()
    return 0
end

function on_timer_preset(minutes, button):
    if timer["running"]:
        return 0
    end
    call gtk.spin_button_set_value(timer["spins"][0], 0)
    call gtk.spin_button_set_value(timer["spins"][1], minutes)
    call gtk.spin_button_set_value(timer["spins"][2], 0)
    call timer_from_spins()
    return 0
end

function on_timer_go(button):
    if timer["running"]:
        timer["left"] = timer_left()
        timer["running"] = False
        call gtk.button_set_label(timer["go"], i18n.T("Resume"))
    else:
        if timer["left"] <= 0.0:
            return 0
        end
        timer["end"] = monotonic() + timer["left"]
        timer["running"] = True
        call gtk.button_set_label(timer["go"], i18n.T("Pause"))
        if timer["timer"] == 0:
            timer["timer"] = glib.timeout_add(200, timer_tick)
        end
    end
    return 0
end

function on_timer_reset(button):
    timer["running"] = False
    call gtk.button_set_label(timer["go"], i18n.T("Start"))
    call timer_from_spins()
    return 0
end

function timer_tick():
    if not timer["running"]:
        timer["timer"] = 0
        return False
    end
    left = timer_left()
    call gtk.label_set_text(timer["label"], fmt_timer(left))
    if left <= 0.0:
        timer["running"] = False
        timer["timer"] = 0
        call gtk.button_set_label(timer["go"], i18n.T("Start"))
        call timer_from_spins()
        call ring(i18n.T("Timer"), i18n.T("Time is up"))
        return False
    end
    return True
end

# ---- okno ---------------------------------------------------------------------------------------

function on_seg(name, button):
    call show_tab(name)
    return 0
end

function show_tab(name):
    ui["tab"] = name
    for key in ui["views"].keys():
        call gtk.widget_set_visible(ui["views"][key], key == name)
        call gtk.widget_set_class(ui["seg"][key], "active", key == name)
    end
    if name == "world":
        call world_tick()
    end
    return 0
end

function second_tick():
    call check_alarms()
    if ui["visible"] and ui["tab"] == "world":
        d = glib.local_date()
        if d[5] == 0:
            call world_tick()
        end
    end
    return True
end

function build_window():
    win = gtk.window_new(i18n.T("Clock"))
    ui["win"] = win
    call gtk.widget_add_class(win, "lca")
    call gtk.window_set_default_size(win, 440, 600)
    call gtk.window_set_icon_name(win, "org.gnome.clocks")
    call gtk.window_set_wmclass(win, "luxos-clock-app", "Luxos-clock-app")
    call gtk.connect(win, "delete-event", on_close)
    root = gtk.box_new(gtk.VERTICAL, 14)
    call gtk.widget_set_margins(root, 20, 20, 16, 20)
    seg = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_add_class(seg, "lca-seg")
    call gtk.widget_set_halign(seg, gtk.ALIGN_CENTER)
    tabs = [["alarms", i18n.T("Alarm")], ["world", i18n.T("World Clock")], ["stopwatch", i18n.T("Stopwatch")], ["timer", i18n.T("Timer")]]
    for t in tabs:
        b = gtk.button_new(t[1])
        call gtk.connect_data(b, "clicked", 0, on_seg, t[0])
        call gtk.box_pack_start(seg, b, False, False, 0)
        ui["seg"][t[0]] = b
    end
    call gtk.box_pack_start(root, seg, False, False, 0)
    scroll = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(scroll, gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
    holder = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.container_add(scroll, holder)
    call gtk.box_pack_start(root, scroll, True, True, 0)
    ui["views"]["alarms"] = build_alarms()
    ui["views"]["world"] = build_world()
    ui["views"]["stopwatch"] = build_stopwatch()
    ui["views"]["timer"] = build_timer()
    for t in tabs:
        call gtk.box_pack_start(holder, ui["views"][t[0]], False, False, 0)
    end
    call gtk.container_add(win, root)
    call gtk.widget_show_all(root)
    call show_tab("alarms")
    return 0
end

function show_window():
    if ui["win"] == 0:
        call build_window()
    end
    ui["visible"] = True
    call gtk.widget_show(ui["win"])
    call gtk.window_present(ui["win"])
    call world_tick()
    return 0
end

# Zavreni: s aktivnim budikem / bezici minutkou na pozadi, jinak konec
function on_close(event, window):
    call gtk.widget_hide(window)
    ui["visible"] = False
    call maybe_quit()
    return True
end

function maybe_quit():
    if ui["visible"] or ringing["win"] != 0 or timer["running"] or stopwatch["running"] or any_alarm_on():
        return 0
    end
    call gtk.main_quit()
    return 0
end

# ---- jedna instance -----------------------------------------------------------------------------

function on_listen(listen_fd, handle, condition):
    while True:
        conn = sys.unix_accept(listen_fd)
        if conn < 0:
            break
        end
        if sys.peer_uid(conn) == sys.getuid():
            call show_window()
        end
        call sys.close(conn)
    end
    return True
end

function main(background):
    name = SOCKET + String(sys.getuid()) + "-" + glib.getenv("DISPLAY")
    fd = sys.unix_listen(name)
    if fd < 0:
        # uz bezi: jen ukazat okno
        if not background:
            c = sys.unix_connect(name)
            if c >= 0:
                call sys.send_text(c, "show\n")
                call sys.close(c)
            end
        end
        return 0
    end
    call load_data()
    if background and not any_alarm_on():
        return 0
    end
    call gtk.init()
    call glib.set_prgname("luxos-clock-app")
    call theme_apply()
    call gtk.connect(gtk.settings_get_default(), "notify::gtk-theme-name", on_theme_changed)
    call glib.fd_add_data(fd, 1, on_listen, fd)
    d = glib.local_date()
    last_minute["key"] = String(d[0]) + "-" + String(d[1]) + "-" + String(d[2]) + " " + String(d[3]) + ":" + String(d[4])
    call glib.timeout_add(1000, second_tick)
    if not background:
        call show_window()
    end
    call gtk.main()
    call stop_ringing()
    return 0
end

command = arg(1)
if command == "--background":
    call main(True)
elif command == None:
    call main(False)
else:
    call sys.eprint("Usage: luxos-clock-app [--background]")
    call exit(2)
end
