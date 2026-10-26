# LuxOS Kalendar - widget pod hodinami v horni liste (jako v macOS); prepis luxos-calendar do LSL.
# Den: velke cislo dne + den v tydnu a dnesni udalosti jako barevne karty. Mesic: mrizka dnu (dnesek
# zvyrazneny, tecka = udalost), klik na den ukaze jeho udalosti. Rok: 12 malych mesicu (cairo + Pango),
# klik otevre mesic. Tlacitko + pridava udalosti, klik na kartu je upravi nebo smaze.
# Pod dneskem pocasi z aplikace Pocasi (jen cerstvy souhrn, Kalendar sam nic nestahuje).
# Data: ~/.local/share/luxos/calendar/events.ics, dalsi *.ics ve slozce jen pro cteni (luxos_ics).
# Na pozadi drzi okno skryte a hlida pripominky (notify-send 10 minut predem).
#
#   call cal.create(background)   skryte okno + pripominky + sledovani slozky (pouziva luxos-hub i samostatny program)
#   call cal.toggle()             ukaze/skryje okno (klik na hodiny)
# Stav drzi slovniky (zadne tridy): cal (okno), store (uloziste), views, form, reminders.
load env, cairo, pango, json
load luxos_glib, glib as glib
load luxos_gio, gio as gio
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_date as date
load luxos_ics as ics
load luxos_text as text

WIDTH = 324
REMINDER_MIN = 10
MAX_WAIT = 900
CELL_W = 13
CELL_H = 11
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAY_SHORT = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
REPEAT_KEYS = ["", "FREQ=DAILY", "FREQ=WEEKLY", "FREQ=MONTHLY", "FREQ=YEARLY"]
REPEAT_NAMES = ["Never", "Daily", "Weekly", "Monthly", "Yearly"]

CSS = ("window.lc { background: transparent; }\n"
    + ".lc-box { background-color: @lc_bg; border-radius: 18px; border: 1px solid @lc_border; padding: 14px; color: @lc_fg; }\n"
    + ".lc-box label { color: @lc_fg; }\n"
    + ".lc-box label.dim, .lc-dim { color: @lc_dim; }\n"
    + ".lc-daynum { font-size: 44px; font-weight: 700; }\n"
    + ".lc-weekday { font-size: 14px; font-weight: 800; color: @lc_accent; }\n"
    + ".lc-monthyear { font-size: 12px; }\n"
    + ".lc-title { font-size: 15px; font-weight: 700; }\n"
    + ".lc-title .year { font-weight: 400; }\n"
    + ".lc-section { font-size: 12px; font-weight: 700; }\n"
    + ".lc-empty { font-size: 12px; padding: 10px 2px; }\n"
    + ".lc-seg { background-color: @lc_tile; border-radius: 9px; padding: 2px; }\n"
    + ".lc-seg button { border-radius: 7px; padding: 1px 11px; min-height: 20px; font-size: 11px; font-weight: 600; background: none; border: none; box-shadow: none; color: @lc_fg; outline: none; }\n"
    + ".lc-seg button:hover { background-color: @lc_tile; }\n"
    + ".lc-seg button.active { background-color: @lc_seg_on; box-shadow: 0 1px 2px rgba(0, 0, 0, 0.18); }\n"
    + ".lc-seg.small button { padding: 1px 6px; font-size: 11px; }\n"
    + "button.lc-icon { border-radius: 999px; min-width: 24px; min-height: 24px; padding: 0; background: none; border: none; box-shadow: none; color: @lc_fg; outline: none; }\n"
    + "button.lc-icon:hover { background-color: @lc_tile_hover; }\n"
    + "button.lc-add { background-color: @lc_tile; }\n"
    + "button.lc-wx { padding: 0; min-height: 0; border: none; background: none; box-shadow: none; font-size: 12px; }\n"
    + "button.lc-wx:hover label { text-decoration: underline; }\n"
    + "button.lc-pill { border-radius: 999px; padding: 1px 10px; min-height: 22px; font-size: 11px; font-weight: 600; background-color: @lc_tile; border: none; box-shadow: none; color: @lc_fg; outline: none; }\n"
    + "button.lc-pill:hover { background-color: @lc_tile_hover; }\n"
    + "button.lc-pill:disabled { opacity: 0.4; }\n"
    + ".lc-box button { transition: background-color 120ms ease-out; }\n"
    + "button.lc-card { border-radius: 10px; padding: 0; border: none; box-shadow: none; outline: none; background-image: none; }\n"
    + ".lc-card .stripe { min-width: 4px; border-radius: 2px; margin: 6px 0 6px 6px; }\n"
    + ".lc-card .ctext { padding: 6px 10px 6px 4px; }\n"
    + ".lc-card .ctitle { font-size: 13px; font-weight: 600; }\n"
    + ".lc-card .ctime { font-size: 11px; }\n"
    + "button.lc-day { border-radius: 999px; padding: 0; min-width: 34px; min-height: 34px; margin: 1px 4px; background: none; border: none; box-shadow: none; outline: none; color: @lc_fg; }\n"
    + "button.lc-day label { font-size: 12px; font-weight: 500; }\n"
    + "button.lc-day:hover { background-color: @lc_tile_hover; }\n"
    + "button.lc-day.other label { color: @lc_faint; }\n"
    + "button.lc-day.weekend label { color: @lc_dim; }\n"
    + "button.lc-day.selected { background-color: @lc_tile_hover; }\n"
    + "button.lc-day.today { background-color: @lc_accent; }\n"
    + "button.lc-day.today label { color: white; font-weight: 700; }\n"
    + ".lc-dot { min-width: 4px; min-height: 4px; border-radius: 2px; }\n"
    + ".lc-wdh { font-size: 10px; font-weight: 700; color: @lc_dim; }\n"
    + ".lc-form label.field { font-size: 11px; font-weight: 600; color: @lc_dim; }\n"
    + ".lc-form entry { background-color: @lc_tile; background-image: none; border: 1px solid transparent; border-radius: 8px; padding: 4px 8px; min-height: 22px; color: @lc_fg; box-shadow: none; caret-color: @lc_accent; }\n"
    + ".lc-form entry:focus { border-color: alpha(@lc_accent, 0.7); }\n"
    + ".lc-form entry.error { border-color: #ff453a; }\n"
    + ".lc-form entry:disabled { opacity: 0.6; }\n"
    + ".lc-form .error-text { color: #ff453a; font-size: 11px; }\n"
    + "button.lc-swatch { border-radius: 999px; min-width: 20px; min-height: 20px; padding: 0; border: none; box-shadow: none; outline: none; background-image: none; }\n"
    + "button.lc-swatch label { color: white; font-weight: 800; font-size: 11px; }\n"
    + "button.lc-swatch.selected { box-shadow: 0 0 0 2px @lc_bg, 0 0 0 4px alpha(@lc_fg, 0.35); }\n"
    + "button.lc-save { border-radius: 8px; padding: 2px 14px; min-height: 24px; font-weight: 600; font-size: 12px; background-color: @lc_accent; background-image: none; color: white; border: none; box-shadow: none; }\n"
    + "button.lc-save label { color: white; }\n"
    + "button.lc-save:hover { background-color: shade(@lc_accent, 1.08); }\n"
    + "button.lc-plain { border-radius: 8px; padding: 2px 12px; min-height: 24px; font-size: 12px; font-weight: 600; background-color: @lc_tile; background-image: none; border: none; box-shadow: none; color: @lc_fg; }\n"
    + "button.lc-plain:hover { background-color: @lc_tile_hover; }\n"
    + "button.lc-danger label { color: #ff453a; }\n"
    + "button.lc-danger.confirm { background-color: #ff453a; }\n"
    + "button.lc-danger.confirm label { color: white; }\n")

DARK = ("@define-color lc_bg rgba(32, 33, 52, 0.86); @define-color lc_border rgba(255, 255, 255, 0.14);\n"
    + "@define-color lc_fg #f4f4fa; @define-color lc_dim rgba(244, 244, 250, 0.60);\n"
    + "@define-color lc_faint rgba(244, 244, 250, 0.28);\n"
    + "@define-color lc_tile rgba(255, 255, 255, 0.08); @define-color lc_tile_hover rgba(255, 255, 255, 0.14);\n"
    + "@define-color lc_seg_on rgba(255, 255, 255, 0.22); @define-color lc_accent #ff453a;\n")

LIGHT = ("@define-color lc_bg rgba(246, 247, 252, 0.88); @define-color lc_border rgba(0, 0, 0, 0.10);\n"
    + "@define-color lc_fg #1d1d2b; @define-color lc_dim rgba(29, 29, 43, 0.58);\n"
    + "@define-color lc_faint rgba(29, 29, 43, 0.28);\n"
    + "@define-color lc_tile rgba(0, 0, 0, 0.05); @define-color lc_tile_hover rgba(0, 0, 0, 0.09);\n"
    + "@define-color lc_seg_on #ffffff; @define-color lc_accent #ff3b30;\n")

store = None
cal = {}
views = {}
form = None
reminders = {"fired": {}, "timer": 0}
theme = {"provider": 0, "dark": None}
monitor_state = {"timer": 0}
created = False
test_log = ""

function config_dir():
    base = env.get("XDG_CONFIG_HOME", "")
    if base == None or base == "":
        base = glib.home_dir() + "/.config"
    end
    return base + "/luxos"
end

function log_test(message):
    if test_log != "":
        call appendfile(test_log, message + "\n")
    end
    return 0
end

# Tridy c-<barva>: karta (pruhledna barva), pruh, tecka, vzorek
function color_css(dark):
    out = ""
    for name in ics.COLORS:
        hx = ics.COLOR_HEX[name]
        r = hex_byte(hx[1:3])
        g = hex_byte(hx[3:5])
        b = hex_byte(hx[5:7])
        a = "0.16"
        a2 = "0.24"
        if dark:
            a = "0.24"
            a2 = "0.32"
        end
        rgb = String(r) + "," + String(g) + "," + String(b)
        out = out + "button.lc-card.c-" + name + " { background-color: rgba(" + rgb + "," + a + "); }\n"
        out = out + "button.lc-card.c-" + name + ":hover { background-color: rgba(" + rgb + "," + a2 + "); }\n"
        out = out + ".c-" + name + " .stripe, .lc-dot.c-" + name + ", button.lc-swatch.c-" + name + " { background-color: " + hx + "; }\n"
    end
    return out
end

function hex_byte(pair):
    return hex_digit(pair[0]) * 16 + hex_digit(pair[1])
end

function hex_digit(ch):
    return "0123456789abcdef".find(ch.lower())
end

# ---- formatovani ------------------------------------------------------------------------------------

function is_cs():
    return i18n.lang() == "cs"
end

function month_name(m):
    return i18n.T(MONTH_NAMES[m - 1])
end

function weekday_name(day):
    return i18n.T(WEEKDAY_NAMES[date.weekday(day)])
end

function fmt_time(moment):
    return String(date.hour_of(moment)) + ":" + date.pad2(date.minute_of(moment))
end

# 'úterý 20. října' / 'Tuesday, October 20' (+ rok, neni-li letosni)
function fmt_long_date(day):
    ymd = date.from_ordinal(day)
    year = ""
    if ymd[0] != date.year_of(date.today()):
        year = " " + String(ymd[0])
    end
    if is_cs():
        return weekday_name(day) + " " + String(ymd[2]) + ". " + i18n.T("of " + MONTH_NAMES[ymd[1] - 1]) + year
    end
    comma = ""
    if year != "":
        comma = ","
    end
    return weekday_name(day) + ", " + month_name(ymd[1]) + " " + String(ymd[2]) + comma + year
end

function fmt_entry_date(day):
    ymd = date.from_ordinal(day)
    if is_cs():
        return String(ymd[2]) + ". " + String(ymd[1]) + ". " + String(ymd[0])
    end
    return date.iso_date(day)
end

# Datum z pole formulare (ordinal) nebo None
function parse_entry_date(value):
    t = value.strip().replace(" ", "")
    y = 0
    m = 0
    d = 0
    if t.find("-") >= 0:
        parts = t.split("-")
        if len(parts) != 3 or not text.is_digits(parts[0]) or not text.is_digits(parts[1]) or not text.is_digits(parts[2]):
            return None
        end
        y = Int(parts[0])
        m = Int(parts[1])
        d = Int(parts[2])
    else:
        parts = []
        for p in t.replace("/", ".").split("."):
            if p != "":
                parts.append(p)
            end
        end
        if len(parts) < 2 or not text.is_digits(parts[0]) or not text.is_digits(parts[1]):
            return None
        end
        d = Int(parts[0])
        m = Int(parts[1])
        y = date.year_of(date.today())
        if len(parts) > 2:
            if not text.is_digits(parts[2]):
                return None
            end
            y = Int(parts[2])
            if y < 100:
                y += 2000
            end
        end
    end
    if y < 1 or y > 9999 or m < 1 or m > 12 or d < 1 or d > date.days_in_month(y, m):
        return None
    end
    return date.ordinal(y, m, d)
end

# Cas z pole formulare: [hodina, minuta] nebo None
function parse_entry_time(value):
    t = value.strip().replace(".", ":")
    h = 0
    m = 0
    if t.find(":") >= 0:
        pair = text.partition(t, ":")
        if not text.is_digits(pair[0]) or (pair[1] != "" and not text.is_digits(pair[1])):
            return None
        end
        h = Int(pair[0])
        if pair[1] != "":
            m = Int(pair[1])
        end
    elif text.is_digits(t) and (len(t) == 3 or len(t) == 4):
        h = Int(t[0:len(t) - 2])
        m = Int(t[len(t) - 2:])
    elif text.is_digits(t):
        h = Int(t)
    else:
        return None
    end
    if h > 23 or m > 59:
        return None
    end
    return [h, m]
end

# Text casu karty pro dany den
function time_range(ev, s, e, day):
    if ev["all_day"]:
        return i18n.T("All day")
    end
    starts = date.date_of(s) == day
    ends = date.date_of(e) == day or (date.date_of(e) == day + 1 and e % date.DAY == 0)
    if starts and ends:
        if e == s:
            return fmt_time(s)
        end
        return fmt_time(s) + " – " + fmt_time(e)
    end
    if starts:
        return i18n.TF("From %s", [fmt_time(s)])
    end
    if date.date_of(e) == day:
        return i18n.TF("Until %s", [fmt_time(e)])
    end
    return i18n.T("All day")
end

# ---- stavebni prvky ---------------------------------------------------------------------------------------

function label(value, classes, xalign):
    lab = gtk.label_new(value)
    call gtk.label_set_xalign(lab, xalign)
    for c in classes:
        call gtk.widget_add_class(lab, c)
    end
    return lab
end

# Tlacitko s ikonou: po kliknuti handler(bound)
function icon_button(icon, handler, bound, extra_class, tooltip):
    b = gtk.button_new_empty()
    call gtk.widget_set_can_focus(b, False)
    call gtk.container_add(b, gtk.image_new_from_icon_name(icon, gtk.ICON_MENU))
    call gtk.widget_add_class(b, "lc-icon")
    if extra_class != "":
        call gtk.widget_add_class(b, extra_class)
    end
    if tooltip != "":
        call gtk.widget_set_tooltip(b, tooltip)
    end
    call gtk.connect_data(b, "clicked", 0, on_bound_click, [handler, bound])
    return b
end

function on_bound_click(pair, button):
    handler = pair[0]
    call handler(pair[1])
    return 0
end

# Prepinac ve stylu macOS (segmentovane tlacitko): {box, buttons, value, on_change}
function segmented_new(keys, names, on_change, small):
    seg = {"buttons": {}, "keys": keys, "value": None, "on_change": on_change}
    box = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_add_class(box, "lc-seg")
    if small:
        call gtk.widget_add_class(box, "small")
    end
    index = 0
    while index < len(keys):
        b = gtk.button_new(names[index])
        call gtk.widget_set_can_focus(b, False)
        call gtk.connect_data(b, "clicked", 0, on_segment_click, [seg, keys[index]])
        call gtk.box_pack_start(box, b, True, True, 0)
        seg["buttons"][keys[index]] = b
        index += 1
    end
    seg["box"] = box
    return seg
end

function on_segment_click(pair, button):
    call segmented_set(pair[0], pair[1], True)
    return 0
end

function segmented_set(seg, key, notify):
    seg["value"] = key
    for k in seg["keys"]:
        call gtk.widget_set_class(seg["buttons"][k], "active", k == key)
    end
    if notify:
        handler = seg["on_change"]
        call handler(key)
    end
    return 0
end

# ---- karty udalosti -----------------------------------------------------------------------------------------

function event_card(ev, s, e, day, ids):
    b = gtk.button_new_empty()
    call gtk.widget_set_can_focus(b, False)
    call gtk.widget_add_class(b, "lc-card")
    call gtk.widget_add_class(b, "c-" + ics.event_color(ev))
    row = gtk.box_new(gtk.HORIZONTAL, 0)
    stripe = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_add_class(stripe, "stripe")
    call gtk.box_pack_start(row, stripe, False, False, 0)
    column = gtk.box_new(gtk.VERTICAL, 1)
    call gtk.widget_add_class(column, "ctext")
    summary = ev["summary"]
    if summary == "":
        summary = i18n.T("New Event")
    end
    title = label(summary, ["ctitle"], 0)
    call gtk.label_set_ellipsize(title, gtk.ELLIPSIZE_END)
    call gtk.box_pack_start(column, title, False, False, 0)
    sub = time_range(ev, s, e, day)
    if ev["location"] != "":
        sub = sub + " · " + ev["location"]
    end
    sub_label = label(sub, ["ctime", "dim"], 0)
    call gtk.label_set_ellipsize(sub_label, gtk.ELLIPSIZE_END)
    call gtk.box_pack_start(column, sub_label, False, False, 0)
    call gtk.box_pack_start(row, column, True, True, 0)
    if ev["rrule"] != None:
        img = gtk.image_new_from_icon_name("view-refresh-symbolic", gtk.ICON_MENU)
        call gtk.widget_set_margins(img, 0, 8, 0, 0)
        call gtk.widget_set_opacity(img, 0.5)
        call gtk.box_pack_end(row, img, False, False, 0)
    end
    call gtk.container_add(b, row)
    ids.append(gtk.connect_data(b, "clicked", 0, on_card_click, ev))
    return b
end

function on_card_click(ev, button):
    call open_event(ev)
    return 0
end

# Seznam karet udalosti jednoho dne (posouvatelny od urcite vysky): {sw, box, ids}
function event_list_new(max_height):
    lst = {"ids": []}
    sw = gtk.scrolled_window_new()
    call gtk.scrolled_window_set_policy(sw, gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
    call gtk.scrolled_window_set_propagate_natural_height(sw, True)
    call gtk.scrolled_window_set_max_content_height(sw, max_height)
    box = gtk.box_new(gtk.VERTICAL, 6)
    call gtk.container_add(sw, box)
    lst["sw"] = sw
    lst["box"] = box
    return lst
end

function event_list_show_day(lst, day, empty_text):
    for child in gtk.container_get_children(lst["box"]):
        call gtk.widget_destroy(child)
    end
    for id in lst["ids"]:
        call glib.release(id)
    end
    lst["ids"] = []
    items = ics.day_instances(store, day)
    if len(items) == 0:
        call gtk.box_pack_start(lst["box"], label(empty_text, ["lc-empty", "dim"], 0), False, False, 0)
    end
    for item in items:
        call gtk.box_pack_start(lst["box"], event_card(item[0], item[1], item[2], day, lst["ids"]), False, False, 0)
    end
    call gtk.widget_show_all(lst["box"])
    # okno se zmensuje na minimalni velikost -> minimum = obsah (nejvyse max_height, pak posuvnik)
    call gtk.scrolled_window_set_min_content_height(lst["sw"], -1)
    nat = gtk.widget_get_preferred_height(lst["box"])[1]
    call gtk.scrolled_window_set_min_content_height(lst["sw"], min(nat, gtk.scrolled_window_get_max_content_height(lst["sw"])))
    return 0
end

# ---- pohledy -----------------------------------------------------------------------------------------------

function day_view_new():
    vw = {"kind": "day"}
    box = gtk.box_new(gtk.VERTICAL, 10)
    head = gtk.box_new(gtk.HORIZONTAL, 10)
    vw["num"] = label("", ["lc-daynum"], 0)
    call gtk.widget_set_valign(vw["num"], gtk.ALIGN_CENTER)
    call gtk.box_pack_start(head, vw["num"], False, False, 0)
    column = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_valign(column, gtk.ALIGN_CENTER)
    vw["wd"] = label("", ["lc-weekday"], 0)
    vw["my"] = label("", ["lc-monthyear", "dim"], 0)
    call gtk.box_pack_start(column, vw["wd"], False, False, 0)
    call gtk.box_pack_start(column, vw["my"], False, False, 0)
    wx = gtk.button_new("")
    call gtk.widget_set_can_focus(wx, False)
    call gtk.widget_add_class(wx, "lc-wx")
    call gtk.widget_set_halign(wx, gtk.ALIGN_START)
    call gtk.widget_set_tooltip(wx, i18n.T("Weather"))
    call gtk.widget_set_no_show_all(wx, True)
    wx_label = gtk.bin_get_child(wx)
    call gtk.label_set_ellipsize(wx_label, gtk.ELLIPSIZE_END)
    call gtk.label_set_max_width_chars(wx_label, 22)
    call gtk.connect(wx, "clicked", on_weather_click)
    vw["wx"] = wx
    call gtk.box_pack_start(column, wx, False, False, 0)
    call gtk.box_pack_start(head, column, True, True, 0)
    nav = gtk.box_new(gtk.HORIZONTAL, 2)
    call gtk.widget_set_valign(nav, gtk.ALIGN_CENTER)
    today_btn = gtk.button_new(i18n.T("Today"))
    call gtk.widget_set_can_focus(today_btn, False)
    call gtk.widget_add_class(today_btn, "lc-pill")
    call gtk.connect(today_btn, "clicked", on_go_today)
    vw["today_btn"] = today_btn
    call gtk.box_pack_start(nav, icon_button("go-previous-symbolic", go_day_delta, -1, "", i18n.T("Previous day")), False, False, 0)
    call gtk.box_pack_start(nav, today_btn, False, False, 0)
    call gtk.box_pack_start(nav, icon_button("go-next-symbolic", go_day_delta, 1, "", i18n.T("Next day")), False, False, 0)
    call gtk.box_pack_end(head, nav, False, False, 0)
    call gtk.box_pack_start(box, head, False, False, 0)
    vw["list"] = event_list_new(330)
    call gtk.box_pack_start(box, vw["list"]["sw"], False, False, 0)
    vw["box"] = box
    call glib.object_ref_sink(box)
    return vw
end

function on_go_today(button):
    call go_day(date.today())
    return 0
end

function go_day_delta(delta):
    call go_day(cal["day"] + delta)
    return 0
end

# Souhrn z aplikace Pocasi ($XDG_CACHE_HOME/luxos/weather/summary.json), starsi nez 3 hodiny se neukaze
function weather_line():
    base = env.get("XDG_CACHE_HOME", "")
    if base == None or base == "":
        base = glib.home_dir() + "/.cache"
    end
    raw = glib.read_text(base + "/luxos/weather/summary.json")
    if raw == "":
        return ""
    end
    data = None
    try:
        data = json.decode(raw)
    else:
        data = None
    end
    if data == None or type(data) != "Dictionary":
        return ""
    end
    fetched = data.get("fetched")
    temp = data.get("temp")
    if fetched == None or temp == None or glib.now() - fetched > 10800:
        return ""
    end
    return String(temp) + "°  " + i18n.T(String(data.get("condition"))) + " · " + String(data.get("name"))
end

function on_weather_click(button):
    call log_test("weather")
    call glib.spawn_quiet(["luxos-weather"])
    call hide()
    return 0
end

function day_view_refresh(vw):
    d = cal["day"]
    ymd = date.from_ordinal(d)
    call gtk.label_set_text(vw["num"], String(ymd[2]))
    call gtk.label_set_text(vw["wd"], weekday_name(d).upper())
    call gtk.label_set_text(vw["my"], month_name(ymd[1]) + " " + String(ymd[0]))
    call gtk.widget_set_sensitive(vw["today_btn"], d != date.today())
    wx = ""
    if d == date.today():
        wx = weather_line()
    end
    call gtk.button_set_label(vw["wx"], wx)
    call gtk.widget_set_visible(vw["wx"], wx != "")
    if wx != "":
        call log_test("weather-line")
    end
    empty = i18n.T("No events")
    if d == date.today():
        empty = i18n.T("No events today")
    end
    call event_list_show_day(vw["list"], d, empty)
    return 0
end

function month_view_new():
    vw = {"kind": "month", "cells": [], "dates": []}
    box = gtk.box_new(gtk.VERTICAL, 6)
    head = gtk.box_new(gtk.HORIZONTAL, 4)
    vw["title"] = label("", ["lc-title"], 0)
    call gtk.box_pack_start(head, vw["title"], True, True, 0)
    today_btn = gtk.button_new(i18n.T("Today"))
    call gtk.widget_set_can_focus(today_btn, False)
    call gtk.widget_add_class(today_btn, "lc-pill")
    call gtk.connect(today_btn, "clicked", on_go_today)
    call gtk.box_pack_end(head, icon_button("go-next-symbolic", month_shift, 1, "", i18n.T("Next month")), False, False, 0)
    call gtk.box_pack_end(head, today_btn, False, False, 0)
    call gtk.box_pack_end(head, icon_button("go-previous-symbolic", month_shift, -1, "", i18n.T("Previous month")), False, False, 0)
    call gtk.box_pack_start(box, head, False, False, 0)

    grid = gtk.grid_new()
    call gtk.grid_set_column_homogeneous(grid, True)
    call gtk.grid_set_row_spacing(grid, 0)
    c = 0
    while c < 7:
        call gtk.grid_attach(grid, label(i18n.T(WEEKDAY_SHORT[c]), ["lc-wdh"], 0.5), c, 0, 1, 1)
        c += 1
    end
    r = 0
    while r < 6:
        c = 0
        while c < 7:
            b = gtk.button_new_empty()
            call gtk.widget_set_can_focus(b, False)
            call gtk.widget_add_class(b, "lc-day")
            inner = gtk.box_new(gtk.VERTICAL, 1)
            call gtk.widget_set_valign(inner, gtk.ALIGN_CENTER)
            num = gtk.label_new("")
            dot = gtk.box_new(gtk.HORIZONTAL, 0)
            call gtk.widget_set_halign(dot, gtk.ALIGN_CENTER)
            call gtk.widget_add_class(dot, "lc-dot")
            call gtk.box_pack_start(inner, num, False, False, 0)
            call gtk.box_pack_start(inner, dot, False, False, 0)
            call gtk.container_add(b, inner)
            cell = {"button": b, "num": num, "dot": dot, "index": len(vw["cells"]), "view": vw}
            call gtk.connect_data(b, "clicked", 0, on_cell_click, cell)
            call gtk.grid_attach(grid, b, c, r + 1, 1, 1)
            vw["cells"].append(cell)
            c += 1
        end
        r += 1
    end
    call gtk.box_pack_start(box, grid, False, False, 0)
    vw["sel_title"] = label("", ["lc-section"], 0)
    call gtk.widget_set_margins(vw["sel_title"], 0, 0, 6, 0)
    call gtk.box_pack_start(box, vw["sel_title"], False, False, 0)
    vw["list"] = event_list_new(170)
    call gtk.box_pack_start(box, vw["list"]["sw"], False, False, 0)
    vw["box"] = box
    call glib.object_ref_sink(box)
    return vw
end

function month_shift(delta):
    ym = date.add_months(cal["month"][0], cal["month"][1], delta)
    cal["month"] = ym
    call month_view_refresh(views["month"])
    return 0
end

function on_cell_click(cell, button):
    vw = cell["view"]
    d = vw["dates"][cell["index"]]
    cal["day"] = d
    ymd = date.from_ordinal(d)
    if ymd[0] != cal["month"][0] or ymd[1] != cal["month"][1]:
        cal["month"] = [ymd[0], ymd[1]]
    end
    call month_view_refresh(vw)
    return 0
end

function month_view_refresh(vw):
    y = cal["month"][0]
    m = cal["month"][1]
    call gtk.label_set_markup(vw["title"], glib.markup_escape(month_name(m)) + " <span weight='400'>" + String(y) + "</span>")
    dates = []
    for week in date.month_grid(y, m, 0, 6):
        dates.extend(week)
    end
    vw["dates"] = dates
    busy = ics.busy_days(store, dates[0], dates[len(dates) - 1] + 1)
    today = date.today()
    index = 0
    while index < 42:
        d = dates[index]
        cell = vw["cells"][index]
        ymd = date.from_ordinal(d)
        call gtk.label_set_text(cell["num"], String(ymd[2]))
        b = cell["button"]
        call gtk.widget_set_class(b, "other", ymd[1] != m)
        call gtk.widget_set_class(b, "today", d == today)
        call gtk.widget_set_class(b, "selected", d == cal["day"] and d != today)
        call gtk.widget_set_class(b, "weekend", date.weekday(d) >= 5)
        dot = cell["dot"]
        for c in ics.COLORS:
            call gtk.widget_remove_class(dot, "c-" + c)
        end
        call gtk.widget_remove_class(dot, "c-white")
        color = busy.get(d)
        if color == None:
            call gtk.widget_set_opacity(dot, 0.0)
        else:
            if ymd[1] == m:
                call gtk.widget_set_opacity(dot, 1.0)
            else:
                call gtk.widget_set_opacity(dot, 0.45)
            end
            if d == today:
                call gtk.widget_add_class(dot, "c-white")
            else:
                call gtk.widget_add_class(dot, "c-" + color)
            end
        end
        index += 1
    end
    call gtk.label_set_text(vw["sel_title"], fmt_long_date(cal["day"]))
    call event_list_show_day(vw["list"], cal["day"], i18n.T("No events"))
    return 0
end

# Rocni prehled: 12 malych mesicu kreslenych pres cairo (lehke - zadne stovky widgetu)
function year_view_new():
    vw = {"kind": "year", "year": date.year_of(date.today()), "areas": [], "busy": {}}
    box = gtk.box_new(gtk.VERTICAL, 8)
    head = gtk.box_new(gtk.HORIZONTAL, 4)
    vw["title"] = label("", ["lc-title"], 0)
    call gtk.box_pack_start(head, vw["title"], True, True, 0)
    today_btn = gtk.button_new(i18n.T("Today"))
    call gtk.widget_set_can_focus(today_btn, False)
    call gtk.widget_add_class(today_btn, "lc-pill")
    call gtk.connect(today_btn, "clicked", on_year_today)
    call gtk.box_pack_end(head, icon_button("go-next-symbolic", year_shift, 1, "", i18n.T("Next year")), False, False, 0)
    call gtk.box_pack_end(head, today_btn, False, False, 0)
    call gtk.box_pack_end(head, icon_button("go-previous-symbolic", year_shift, -1, "", i18n.T("Previous year")), False, False, 0)
    call gtk.box_pack_start(box, head, False, False, 0)
    grid = gtk.grid_new()
    call gtk.grid_set_column_homogeneous(grid, True)
    call gtk.grid_set_row_spacing(grid, 10)
    call gtk.grid_set_column_spacing(grid, 6)
    i = 0
    while i < 12:
        ev = gtk.event_box_new()
        area = gtk.drawing_area_new()
        call gtk.widget_set_size_request(area, 7 * CELL_W, 18 + 6 * CELL_H)
        cellinfo = {"view": vw, "month": i + 1, "area": area, "eventbox": ev}
        call gtk.connect_data(area, "draw", 1, on_draw_month, cellinfo)
        call gtk.container_add(ev, area)
        call gtk.connect_data(ev, "button-release-event", 1, on_month_release, cellinfo)
        call gtk.connect_data(ev, "realize", 0, on_month_realize, cellinfo)
        call gtk.grid_attach(grid, ev, i % 3, i // 3, 1, 1)
        vw["areas"].append(area)
        i += 1
    end
    call gtk.box_pack_start(box, grid, False, False, 0)
    vw["box"] = box
    call glib.object_ref_sink(box)
    return vw
end

function on_year_today(button):
    call year_set(date.year_of(date.today()))
    return 0
end

function year_shift(delta):
    call year_set(views["year"]["year"] + delta)
    return 0
end

function year_set(y):
    views["year"]["year"] = y
    call year_view_refresh(views["year"])
    return 0
end

function year_view_refresh(vw):
    call gtk.label_set_markup(vw["title"], "<span>" + String(vw["year"]) + "</span>")
    vw["busy"] = ics.busy_days(store, date.ordinal(vw["year"], 1, 1), date.ordinal(vw["year"] + 1, 1, 1))
    for area in vw["areas"]:
        call gtk.widget_queue_draw(area)
    end
    return 0
end

function on_month_release(info, event, widget):
    call open_month(info["view"]["year"], info["month"])
    return 0
end

function on_month_realize(info, widget):
    call gtk.widget_set_cursor(widget, "pointer")
    return 0
end

function accent_rgba():
    if theme["dark"]:
        return [1.0, 0.27, 0.23, 1.0]
    end
    return [1.0, 0.23, 0.19, 1.0]
end

function on_draw_month(info, cr, area):
    vw = info["view"]
    month = info["month"]
    year = vw["year"]
    fg = gtk.widget_get_color(vw["box"], 0)
    accent = accent_rgba()
    w = gtk.widget_get_allocated_width(area)
    x0 = max(0, (w - 7 * CELL_W) // 2)
    layout = pango.cairo_create_layout(cr)
    family = gtk.widget_get_font_family(vw["box"])
    if family == "":
        family = "Sans"
    end
    call pango.layout_set_font(layout, family + " Bold 11px")
    call pango.layout_set_text(layout, month_name(month))
    today = date.today()
    today_ymd = date.from_ordinal(today)
    is_current = year == today_ymd[0] and month == today_ymd[1]
    if is_current:
        call cairo.set_source_color(cr, accent)
    else:
        call cairo.set_source_rgba(cr, fg[0], fg[1], fg[2], 1.0)
    end
    call cairo.move_to(cr, x0 + 2, 0)
    call pango.cairo_show_layout(cr, layout)
    weeks = date.month_grid(year, month, 0, date.weeks_needed(year, month, 0))
    r = 0
    while r < len(weeks):
        c = 0
        while c < 7:
            d = weeks[r][c]
            if date.month_of(d) == month:
                cx = Float(x0 + c * CELL_W) + Float(CELL_W) / 2.0
                cy = Float(18 + r * CELL_H) + Float(CELL_H) / 2.0
                busy = d in vw["busy"]
                if d == today:
                    call cairo.set_source_color(cr, accent)
                    call cairo.arc(cr, cx, cy, Float(CELL_H) / 2.0 + 0.5, 0.0, 6.2832)
                    call cairo.fill(cr)
                end
                if busy or d == today:
                    call pango.layout_set_font(layout, family + " Bold 7.5px")
                else:
                    call pango.layout_set_font(layout, family + " 7.5px")
                end
                call pango.layout_set_text(layout, String(date.day_of(d)))
                size = pango.layout_get_pixel_size(layout)
                if d == today:
                    call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 1.0)
                else:
                    alpha = 0.75
                    if busy:
                        alpha = 1.0
                    elif date.weekday(d) >= 5:
                        alpha = 0.5
                    end
                    call cairo.set_source_rgba(cr, fg[0], fg[1], fg[2], alpha)
                end
                call cairo.move_to(cr, cx - Float(size[0]) / 2.0, cy - Float(size[1]) / 2.0)
                call pango.cairo_show_layout(cr, layout)
                if busy and d != today:
                    hx = ics.COLOR_HEX[vw["busy"][d]]
                    call cairo.set_source_rgba(cr, Float(hex_byte(hx[1:3])) / 255.0, Float(hex_byte(hx[3:5])) / 255.0, Float(hex_byte(hx[5:7])) / 255.0, 1.0)
                    call cairo.arc(cr, cx, cy + Float(size[1]) / 2.0 + 0.5, 1.1, 0.0, 6.2832)
                    call cairo.fill(cr)
                end
            end
            c += 1
        end
        r += 1
    end
    call pango.layout_unref(layout)
    return False
end

# ---- formular udalosti ----------------------------------------------------------------------------------------

function field(title, widget):
    box = gtk.box_new(gtk.VERTICAL, 3)
    call gtk.box_pack_start(box, label(title, ["field"], 0), False, False, 0)
    call gtk.box_pack_start(box, widget, False, False, 0)
    return box
end

function form_new():
    f = {"ev": None, "readonly": False, "confirm": False, "color": ics.DEFAULT_COLOR, "swatches": {}}
    box = gtk.box_new(gtk.VERTICAL, 8)
    call gtk.widget_add_class(box, "lc-form")
    head = gtk.box_new(gtk.HORIZONTAL, 6)
    f["heading"] = label("", ["lc-title"], 0)
    call gtk.box_pack_start(head, f["heading"], True, True, 0)
    call gtk.box_pack_end(head, icon_button("window-close-symbolic", form_cancel, 0, "", i18n.T("Cancel")), False, False, 0)
    call gtk.box_pack_start(box, head, False, False, 0)

    f["title"] = gtk.entry_new()
    call gtk.entry_set_placeholder_text(f["title"], i18n.T("Title"))
    call gtk.connect(f["title"], "activate", on_form_activate)
    call gtk.box_pack_start(box, f["title"], False, False, 0)

    row = gtk.box_new(gtk.HORIZONTAL, 6)
    f["date"] = gtk.entry_new()
    call gtk.entry_set_width_chars(f["date"], 11)
    call gtk.connect(f["date"], "changed", on_entry_changed)
    call gtk.box_pack_start(row, field(i18n.T("Date"), f["date"]), True, True, 0)
    steps = gtk.box_new(gtk.HORIZONTAL, 0)
    call gtk.widget_set_valign(steps, gtk.ALIGN_END)
    call gtk.box_pack_start(steps, icon_button("go-previous-symbolic", form_step_date, -1, "", i18n.T("Previous day")), False, False, 0)
    call gtk.box_pack_start(steps, icon_button("go-next-symbolic", form_step_date, 1, "", i18n.T("Next day")), False, False, 0)
    call gtk.box_pack_start(row, steps, False, False, 0)
    call gtk.box_pack_start(box, row, False, False, 0)

    times = gtk.box_new(gtk.HORIZONTAL, 8)
    f["start"] = gtk.entry_new()
    call gtk.entry_set_width_chars(f["start"], 6)
    call gtk.entry_set_placeholder_text(f["start"], "9:00")
    f["end"] = gtk.entry_new()
    call gtk.entry_set_width_chars(f["end"], 6)
    call gtk.entry_set_placeholder_text(f["end"], "10:00")
    for e in [f["start"], f["end"]]:
        call gtk.connect(e, "changed", on_entry_changed)
        call gtk.connect(e, "activate", on_form_activate)
    end
    call gtk.box_pack_start(times, field(i18n.T("Starts"), f["start"]), True, True, 0)
    call gtk.box_pack_start(times, field(i18n.T("Ends"), f["end"]), True, True, 0)
    allday = gtk.box_new(gtk.VERTICAL, 3)
    call gtk.box_pack_start(allday, label(i18n.T("All day"), ["field"], 0), False, False, 0)
    f["allday"] = gtk.switch_new()
    call gtk.widget_set_halign(f["allday"], gtk.ALIGN_START)
    call gtk.widget_set_valign(f["allday"], gtk.ALIGN_CENTER)
    call gtk.widget_set_can_focus(f["allday"], False)
    call gtk.connect(f["allday"], "notify::active", on_allday_notify)
    call gtk.box_pack_start(allday, f["allday"], True, False, 0)
    call gtk.box_pack_start(times, allday, False, False, 0)
    call gtk.box_pack_start(box, times, False, False, 0)

    call gtk.box_pack_start(box, label(i18n.T("Repeat"), ["field"], 0), False, False, 0)
    names = []
    for n in REPEAT_NAMES:
        names.append(i18n.T(n))
    end
    keys = []
    keys.extend(REPEAT_KEYS)
    keys.append("custom")
    names.append(i18n.T("Custom"))
    f["repeat"] = segmented_new(keys, names, on_repeat_change, True)
    call gtk.widget_set_no_show_all(f["repeat"]["buttons"]["custom"], True)
    call gtk.box_pack_start(box, f["repeat"]["box"], False, False, 0)

    crow = gtk.box_new(gtk.HORIZONTAL, 12)
    sw_box = gtk.box_new(gtk.HORIZONTAL, 10)
    call gtk.widget_set_valign(sw_box, gtk.ALIGN_CENTER)
    for c in ics.COLORS:
        b = gtk.button_new_empty()
        call gtk.widget_set_can_focus(b, False)
        call gtk.widget_add_class(b, "lc-swatch")
        call gtk.widget_add_class(b, "c-" + c)
        call gtk.container_add(b, gtk.label_new(""))
        call gtk.connect_data(b, "clicked", 0, on_swatch_click, c)
        call gtk.box_pack_start(sw_box, b, False, False, 0)
        f["swatches"][c] = b
    end
    call gtk.box_pack_start(crow, sw_box, False, False, 2)
    call gtk.box_pack_start(box, crow, False, False, 2)
    f["sw_box"] = sw_box

    rrow = gtk.box_new(gtk.HORIZONTAL, 8)
    remind_label = label(i18n.TF("Remind %d minutes before", [REMINDER_MIN]), [], 0)
    call gtk.widget_set_valign(remind_label, gtk.ALIGN_CENTER)
    call gtk.box_pack_start(rrow, remind_label, True, True, 0)
    f["remind"] = gtk.switch_new()
    call gtk.widget_set_can_focus(f["remind"], False)
    call gtk.widget_set_valign(f["remind"], gtk.ALIGN_CENTER)
    call gtk.box_pack_end(rrow, f["remind"], False, False, 0)
    call gtk.box_pack_start(box, rrow, False, False, 0)

    f["note"] = label("", ["dim"], 0)
    call gtk.label_set_line_wrap(f["note"], True)
    call gtk.label_set_max_width_chars(f["note"], 40)
    call gtk.widget_set_no_show_all(f["note"], True)
    call gtk.box_pack_start(box, f["note"], False, False, 0)
    f["err"] = label("", ["error-text"], 0)
    call gtk.label_set_line_wrap(f["err"], True)
    call gtk.widget_set_no_show_all(f["err"], True)
    call gtk.box_pack_start(box, f["err"], False, False, 0)

    btns = gtk.box_new(gtk.HORIZONTAL, 6)
    f["delete_btn"] = gtk.button_new(i18n.T("Delete"))
    call gtk.widget_set_can_focus(f["delete_btn"], False)
    call gtk.widget_add_class(f["delete_btn"], "lc-plain")
    call gtk.widget_add_class(f["delete_btn"], "lc-danger")
    call gtk.connect(f["delete_btn"], "clicked", on_delete_click)
    call gtk.box_pack_start(btns, f["delete_btn"], False, False, 0)
    call gtk.widget_set_no_show_all(f["delete_btn"], True)
    f["save_btn"] = gtk.button_new(i18n.T("Save"))
    call gtk.widget_set_can_focus(f["save_btn"], False)
    call gtk.widget_set_no_show_all(f["save_btn"], True)
    call gtk.widget_add_class(f["save_btn"], "lc-save")
    call gtk.connect(f["save_btn"], "clicked", on_save_click)
    call gtk.box_pack_end(btns, f["save_btn"], False, False, 0)
    f["cancel_btn"] = gtk.button_new(i18n.T("Cancel"))
    call gtk.widget_set_can_focus(f["cancel_btn"], False)
    call gtk.widget_add_class(f["cancel_btn"], "lc-plain")
    call gtk.connect(f["cancel_btn"], "clicked", on_cancel_click)
    call gtk.box_pack_end(btns, f["cancel_btn"], False, False, 0)
    call gtk.widget_set_margins(btns, 0, 0, 4, 0)
    call gtk.box_pack_start(box, btns, False, False, 0)
    f["box"] = box
    call glib.object_ref_sink(box)
    f["inputs"] = [f["title"], f["date"], f["start"], f["end"], f["allday"], f["repeat"]["box"], sw_box, f["remind"]]
    return f
end

function on_form_activate(entry):
    call form_save()
    return 0
end

function on_entry_changed(entry):
    call gtk.widget_remove_class(entry, "error")
    return 0
end

function on_allday_notify(pspec, switch):
    call form_sync_allday()
    return 0
end

function on_repeat_change(key):
    return 0
end

function on_swatch_click(color, button):
    call form_set_color(color)
    return 0
end

function on_delete_click(button):
    call form_delete()
    return 0
end

function on_save_click(button):
    call form_save()
    return 0
end

function on_cancel_click(button):
    call form_cancel(0)
    return 0
end

function form_set_color(c):
    form["color"] = c
    for k in ics.COLORS:
        b = form["swatches"][k]
        call gtk.widget_set_class(b, "selected", k == c)
        mark = ""
        if k == c:
            mark = "✓"
        end
        call gtk.label_set_text(gtk.bin_get_child(b), mark)
    end
    return 0
end

function form_step_date(delta):
    d = parse_entry_date(gtk.entry_get_text(form["date"]))
    if d == None:
        d = cal["day"]
    end
    call gtk.entry_set_text(form["date"], fmt_entry_date(d + delta))
    return 0
end

function form_sync_allday():
    timed = not gtk.switch_get_active(form["allday"])
    enabled = timed and not form["readonly"]
    call gtk.widget_set_sensitive(form["start"], enabled)
    call gtk.widget_set_sensitive(form["end"], enabled)
    call gtk.widget_set_sensitive(form["remind"], enabled)
    return 0
end

# ev = None -> nova udalost na den `day`
function form_load(ev, day):
    f = form
    f["ev"] = ev
    f["readonly"] = ev != None and ev["readonly"]
    f["confirm"] = False
    call gtk.button_set_label(f["delete_btn"], i18n.T("Delete"))
    call gtk.widget_remove_class(f["delete_btn"], "confirm")
    call gtk.widget_hide(f["err"])
    for w in [f["date"], f["start"], f["end"]]:
        call gtk.widget_remove_class(w, "error")
    end
    if ev == None:
        call gtk.label_set_text(f["heading"], i18n.T("New Event"))
        now = date.now()
        start = date.make(day, 9, 0, 0)
        if day == date.date_of(now):
            start = date.make(day, min(date.hour_of(now) + 1, 23), 0, 0)
        end
        finish = min(start + 3600, date.make(day, 23, 59, 0))
        call gtk.entry_set_text(f["title"], "")
        call gtk.entry_set_text(f["date"], fmt_entry_date(day))
        call gtk.entry_set_text(f["start"], fmt_time(start))
        call gtk.entry_set_text(f["end"], fmt_time(finish))
        call gtk.switch_set_active(f["allday"], False)
        call segmented_set(f["repeat"], "", False)
        call gtk.widget_hide(f["repeat"]["buttons"]["custom"])
        call form_set_color(cal["last_color"])
        call gtk.switch_set_active(f["remind"], True)
        call gtk.widget_hide(f["note"])
    else:
        if f["readonly"]:
            call gtk.label_set_text(f["heading"], i18n.T("Event"))
        else:
            call gtk.label_set_text(f["heading"], i18n.T("Edit Event"))
        end
        call gtk.entry_set_text(f["title"], ev["summary"])
        sd = ev["start"]
        if not ev["all_day"]:
            sd = date.date_of(ev["start"])
        end
        call gtk.entry_set_text(f["date"], fmt_entry_date(sd))
        call gtk.switch_set_active(f["allday"], ev["all_day"])
        if ev["all_day"]:
            call gtk.entry_set_text(f["start"], "9:00")
            call gtk.entry_set_text(f["end"], "10:00")
        else:
            call gtk.entry_set_text(f["start"], fmt_time(ev["start"]))
            call gtk.entry_set_text(f["end"], fmt_time(ev["start"] + ics.duration(ev)))
        end
        raw = ""
        if ev["rrule_raw"] != None:
            raw = ev["rrule_raw"].upper()
        end
        simple = ""
        for k in REPEAT_KEYS:
            if k != "" and raw == k:
                simple = k
            end
        end
        if raw == "":
            call segmented_set(f["repeat"], "", False)
        elif simple != "":
            call segmented_set(f["repeat"], simple, False)
        else:
            call segmented_set(f["repeat"], "custom", False)
        end
        call gtk.widget_set_visible(f["repeat"]["buttons"]["custom"], raw != "" and simple == "")
        call form_set_color(ics.event_color(ev))
        call gtk.switch_set_active(f["remind"], ics.reminder_minutes(ev) != None)
        notes = []
        if f["readonly"]:
            notes.append(i18n.TF("Read-only calendar: %s", [ev["source"]]))
        elif ev["rrule"] != None:
            notes.append(i18n.T("Changes apply to all occurrences."))
        end
        call gtk.label_set_text(f["note"], text.join(notes, " "))
        call gtk.widget_set_visible(f["note"], len(notes) > 0)
    end
    call gtk.widget_set_visible(f["delete_btn"], ev != None and not f["readonly"])
    call gtk.widget_set_visible(f["save_btn"], not f["readonly"])
    if f["readonly"]:
        call gtk.button_set_label(f["cancel_btn"], i18n.T("Close"))
    else:
        call gtk.button_set_label(f["cancel_btn"], i18n.T("Cancel"))
    end
    for w in f["inputs"]:
        call gtk.widget_set_sensitive(w, not f["readonly"])
    end
    call form_sync_allday()
    if not f["readonly"]:
        call glib.idle_add(focus_title)
    end
    return 0
end

function focus_title():
    call gtk.widget_grab_focus(form["title"])
    return False
end

function form_fail(message, widget):
    call gtk.label_set_text(form["err"], message)
    call gtk.widget_show(form["err"])
    if widget != 0:
        call gtk.widget_add_class(widget, "error")
    end
    return False
end

function form_save():
    f = form
    if f["readonly"]:
        return False
    end
    day = parse_entry_date(gtk.entry_get_text(f["date"]))
    if day == None:
        return form_fail(i18n.T("Invalid date."), f["date"])
    end
    allday = gtk.switch_get_active(f["allday"])
    ev = f["ev"]
    start = 0
    finish = 0
    if allday:
        span = 1
        if ev != None and ev["all_day"]:
            span = max(1, ics.duration(ev))
        end
        start = day
        finish = day + span
    else:
        st = parse_entry_time(gtk.entry_get_text(f["start"]))
        et = parse_entry_time(gtk.entry_get_text(f["end"]))
        if st == None:
            return form_fail(i18n.T("Invalid time."), f["start"])
        end
        if et == None:
            return form_fail(i18n.T("Invalid time."), f["end"])
        end
        span = 0
        if ev != None and not ev["all_day"]:
            span = date.date_of(ev["start"] + ics.duration(ev)) - date.date_of(ev["start"])
        end
        start = date.make(day, st[0], st[1], 0)
        finish = date.make(day + span, et[0], et[1], 0)
        if finish <= start:
            return form_fail(i18n.T("The event must end after it starts."), f["end"])
        end
    end
    is_new = ev == None
    if is_new:
        ev = ics.event_new("", allday, start, finish, None)
    end
    summary = gtk.entry_get_text(f["title"]).strip()
    if summary == "":
        summary = i18n.T("New Event")
    end
    ev["summary"] = summary
    ev["all_day"] = allday
    ev["start"] = start
    ev["end"] = finish
    ev["color"] = f["color"]
    rep = f["repeat"]["value"]
    if rep != "custom":
        call ics.set_rrule(ev, rep)
        if rep == "":
            ev["exdate_lines"] = []
            ev["exdates"] = []
        end
    end
    if not allday:
        if not gtk.switch_get_active(f["remind"]):
            call ics.set_reminder(ev, None)
        elif ics.reminder_minutes(ev) == None:
            call ics.set_reminder(ev, REMINDER_MIN)
        end
    end
    cal["last_color"] = f["color"]
    ok = True
    message = ""
    try:
        if is_new:
            call ics.add(store, ev)
        else:
            call ics.update(store, ev)
        end
    else:
        ok = False
        message = String(last_error())
    end
    if not ok:
        if is_new:
            call ics.forget(store, ev)
        end
        return form_fail(i18n.TF("Could not save: %s", [message]), 0)
    end
    cal["day"] = day
    ymd = date.from_ordinal(day)
    cal["month"] = [ymd[0], ymd[1]]
    call close_form(True)
    call log_test("saved " + ev["uid"])
    return False
end

function form_delete():
    f = form
    if not f["confirm"]:
        f["confirm"] = True
        if f["ev"]["rrule"] != None:
            call gtk.button_set_label(f["delete_btn"], i18n.T("Delete All?"))
        else:
            call gtk.button_set_label(f["delete_btn"], i18n.T("Delete Event?"))
        end
        call gtk.widget_add_class(f["delete_btn"], "confirm")
        return 0
    end
    ok = True
    message = ""
    try:
        call ics.delete(store, f["ev"])
    else:
        ok = False
        message = String(last_error())
    end
    if not ok:
        return form_fail(i18n.TF("Could not save: %s", [message]), 0)
    end
    call close_form(True)
    return 0
end

function form_cancel(unused):
    call close_form(False)
    return 0
end

# ---- okno -----------------------------------------------------------------------------------------------------

function theme_is_dark():
    name = gtk.settings_theme_name().lower()
    return name.find("dark") >= 0 or gtk.settings_prefer_dark()
end

# CSS podle svetleho/tmaveho rezimu; prepina se zaroven se systemovym tematem
function theme_apply():
    dark = theme_is_dark()
    if dark == theme["dark"]:
        return 0
    end
    theme["dark"] = dark
    css = CSS + color_css(dark) + "\n.lc-dot.c-white { background-color: white; }"
    if dark:
        css = DARK + css
    else:
        css = LIGHT + css
    end
    if theme["provider"] == 0:
        theme["provider"] = gtk.css_load(css)
    else:
        call gtk.css_set(theme["provider"], css)
    end
    if created:
        call gtk.widget_queue_draw(cal["win"])
    end
    return 0
end

function on_theme_changed(pspec, settings):
    call theme_apply()
    return 0
end

function view(name):
    if name not in views:
        # pohledy se tvori az pri prvnim pouziti (rychly start na pozadi)
        if name == "day":
            views[name] = day_view_new()
        elif name == "month":
            views[name] = month_view_new()
        else:
            views[name] = year_view_new()
        end
    end
    return views[name]
end

function view_refresh(v):
    if v["kind"] == "day":
        return day_view_refresh(v)
    elif v["kind"] == "month":
        return month_view_refresh(v)
    end
    return year_view_refresh(v)
end

function show_view(name):
    for child in gtk.container_get_children(cal["holder"]):
        call gtk.container_remove(cal["holder"], child)
    end
    w = 0
    if name == "form":
        w = form["box"]
    else:
        v = view(name)
        cal["mode"] = name
        call view_refresh(v)
        w = v["box"]
    end
    call gtk.box_pack_start(cal["holder"], w, False, False, 0)
    call gtk.widget_show_all(w)
    call gtk.widget_set_visible(cal["top"], name != "form")
    # zmensit po prepnuti na mensi pohled
    call gtk.window_resize(cal["win"], WIDTH, 1)
    cal["showing"] = name
    call log_test("view " + name)
    return 0
end

function set_mode(name):
    if name == "month":
        ymd = date.from_ordinal(cal["day"])
        cal["month"] = [ymd[0], ymd[1]]
    end
    if name == "year":
        y = view("year")
        if cal["mode"] == "month":
            y["year"] = cal["month"][0]
        else:
            y["year"] = date.year_of(cal["day"])
        end
    end
    call show_view(name)
    return 0
end

function go_day(d):
    cal["day"] = d
    ymd = date.from_ordinal(d)
    cal["month"] = [ymd[0], ymd[1]]
    if cal["mode"] == "year":
        y = view("year")
        y["year"] = ymd[0]
    end
    call show_view(cal["mode"])
    return 0
end

function open_month(y, m):
    cal["month"] = [y, m]
    today = date.today()
    tymd = date.from_ordinal(today)
    if tymd[0] == y and tymd[1] == m:
        cal["day"] = today
    else:
        cal["day"] = date.ordinal(y, m, 1)
    end
    call segmented_set(cal["seg"], "month", False)
    call show_view("month")
    return 0
end

function ensure_form():
    global form
    if form == None:
        form = form_new()
    end
    return form
end

function new_event(unused):
    call ensure_form()
    call form_load(None, cal["day"])
    call show_view("form")
    return 0
end

function open_event(ev):
    call ensure_form()
    call form_load(ev, cal["day"])
    call show_view("form")
    return 0
end

function close_form(changed):
    call segmented_set(cal["seg"], cal["mode"], False)
    call show_view(cal["mode"])
    if changed:
        call reminders_schedule()
    end
    return 0
end

function refresh():
    if cal["showing"] != "form":
        call show_view(cal["mode"])
    end
    return 0
end

function is_visible():
    if not created:
        return False
    end
    return gtk.widget_get_visible(cal["win"])
end

function toggle():
    if not created:
        call create(True)
    end
    if gtk.widget_get_visible(cal["win"]):
        call hide()
        return 0
    end
    call ics.reload_if_changed(store)
    cal["day"] = date.today()
    ymd = date.from_ordinal(cal["day"])
    cal["month"] = [ymd[0], ymd[1]]
    call segmented_set(cal["seg"], cal["mode"], False)
    call show_view(cal["mode"])
    call place()
    call gtk.widget_show(cal["win"])
    call place()
    stamp = gtk.get_current_event_time()
    if stamp == 0:
        stamp = gtk.CURRENT_TIME
    end
    call gtk.window_present_with_time(cal["win"], stamp)
    call log_test("shown")
    return 0
end

function hide():
    call gtk.widget_hide(cal["win"])
    call log_test("hidden")
    return 0
end

# Vpravo pod horni listou na monitoru s kurzorem (sirka okna je pevna)
function place():
    pointer = gtk.pointer_position()
    geo = gtk.monitor_at_point_workarea(pointer[0], pointer[1])
    w = max(WIDTH, gtk.window_get_size(cal["win"])[0], gtk.widget_get_preferred_width(cal["root"])[1])
    call gtk.window_move(cal["win"], geo[0] + geo[2] - w - 8, geo[1] + 6)
    return 0
end

function on_focus_out(event, window):
    # testy pod Xvfb bez spravce oken: okno by se po zobrazeni hned zavrelo
    if env.get("LUXOS_HUB_NO_AUTOHIDE", "") == "1":
        return False
    end
    call glib.timeout_add(150, close_if_unfocused)
    return False
end

# is_active() zustava po kliknuti na plochu (xfdesktop drzi grab) chybne True,
# proto rozhoduje i skutecne aktivni okno podle spravce oken (_NET_ACTIVE_WINDOW)
function close_if_unfocused():
    active = gtk.screen_active_window()
    own = gtk.widget_get_window(cal["win"])
    if not gtk.window_is_active(cal["win"]) or (active != 0 and active != own):
        call hide()
    end
    if active != 0:
        call glib.object_unref(active)
    end
    return False
end

function on_key(event, window):
    if gtk.event_key_keyval(event) == gtk.KEY_Escape:
        if cal["showing"] == "form":
            call close_form(False)
        else:
            call hide()
        end
        return True
    end
    return False
end

function on_delete(event, window):
    call hide()
    return True
end

function on_seg_change(key):
    call set_mode(key)
    return 0
end

# ---- pripominky ---------------------------------------------------------------------------------------------------
# Casovac na pozadi: notify-send pred udalosti podle VALARM. Budi se jen kdyz je treba
# (nejblizsi pripominka, nejdele po 15 minutach) a po probuzeni z uspani (logind).

# [[cas pripominky, klic, ev, zacatek, konec, minuty]] pro dnesek a zitrek, serazene podle casu
function reminders_pending(now):
    today = date.date_of(now)
    buckets = {}
    for item in ics.instances(store, today - 1, today + 3):
        ev = item[0]
        mins = ics.reminder_minutes(ev)
        if mins == None:
            continue
        end
        start = item[1]
        finish = item[2]
        if ev["all_day"]:
            start = item[1] * date.DAY
            finish = item[2] * date.DAY
        end
        at = start - mins * 60
        key = String(ev["source"]) + "|" + ev["uid"] + "|" + String(start)
        if key in reminders["fired"] or start <= now:
            continue
        end
        sort_key = text.pad(at, 20) + key
        buckets[sort_key] = [at, key, ev, start, finish, mins]
    end
    out = []
    for k in sorted(buckets.keys()):
        out.append(buckets[k])
    end
    return out
end

function reminders_check():
    reminders["timer"] = 0
    now = date.now()
    call ics.reload_if_changed(store)
    for item in reminders_pending(now):
        at = item[0]
        if at > now:
            break
        end
        ev = item[2]
        start = item[3]
        finish = item[4]
        reminders["fired"][item[1]] = start
        left = max(0, (start - now + 30) // 60)
        when = i18n.T("Now")
        if left != 0:
            when = i18n.TF("In %d minutes", [left])
        end
        if not ev["all_day"]:
            when = when + " · " + fmt_time(start)
            if finish > start:
                when = when + " – " + fmt_time(finish)
            end
        end
        summary = ev["summary"]
        if summary == "":
            summary = i18n.T("New Event")
        end
        call glib.spawn_quiet(["notify-send", "-a", i18n.T("Calendar"), "-h", "boolean:x-luxos-keep:true", "-i", "x-office-calendar", summary, when])
        call log_test("reminder " + summary)
    end
    kept = {}
    for key in reminders["fired"].keys():
        if reminders["fired"][key] > now - date.DAY:
            kept[key] = reminders["fired"][key]
        end
    end
    reminders["fired"] = kept
    call reminders_schedule()
    return False
end

function reminders_schedule():
    if reminders["timer"] != 0:
        call glib.source_remove(reminders["timer"])
    end
    now = date.now()
    pending = reminders_pending(now)
    wait = MAX_WAIT
    if len(pending) > 0:
        wait = max(1, min(MAX_WAIT, pending[0][0] - now + 1))
    end
    reminders["timer"] = glib.timeout_add_seconds(wait, reminders_check)
    return 0
end

function on_sleep_signal(sender, path, interface, signal, values):
    call reminders_schedule()
    return 0
end

# ---- horni lista: nahrada pluginu hodin --------------------------------------------------------------------------
CLOCK_FORMAT = "%a %-d. %b  %H:%M"

function xfconf(args):
    argv = ["xfconf-query", "-c", "xfce4-panel"]
    argv.extend(args)
    out = ""
    ok = True
    try:
        out = capture("xfconf-query", argv[1:])
    else:
        ok = False
    end
    if not ok or capture_status() != 0:
        return None
    end
    return out.strip()
end

# Starsi instalace maji v liste plugin 'clock', ktery neumi spustit prikaz po kliknuti.
# Jednou ho nahradi pluginem genmon s luxos-clock (stejny vzhled, klik = kalendar); jen pokud uzivatel format hodin nezmenil.
function migrate_panel():
    mark = config_dir() + "/calendar-clock-migrated"
    if exists(mark):
        return False
    end
    props = xfconf(["-l", "-p", "/plugins"])
    if props == None:
        return False
    end
    done = False
    for prop in props.split("\n"):
        if prop.count("/") != 2 or not prop.startswith("/plugins/plugin-"):
            continue
        end
        if xfconf(["-p", prop]) != "clock":
            continue
        end
        fmt = xfconf(["-p", prop + "/digital-time-format"])
        if fmt != None and fmt != CLOCK_FORMAT:
            continue
        end
        call xfconf(["-p", prop, "-r", "-R"])
        call xfconf(["-p", prop, "-n", "-t", "string", "-s", "genmon"])
        call xfconf(["-p", prop + "/command", "-n", "-t", "string", "-s", "luxos-clock"])
        call xfconf(["-p", prop + "/update-period", "-n", "-t", "int", "-s", "3000"])
        call xfconf(["-p", prop + "/use-label", "-n", "-t", "bool", "-s", "false"])
        call xfconf(["-p", prop + "/enable-single-row", "-n", "-t", "bool", "-s", "true"])
        call xfconf(["-p", prop + "/font", "-n", "-t", "string", "-s", "Inter Semi-Bold 10"])
        done = True
    end
    call glib.mkdir_p(config_dir())
    call writefile(mark, "")
    if done:
        call glib.spawn_quiet(["xfce4-panel", "-r"])
    end
    return False
end

# ---- zmeny souboru (import .ics, jina aplikace): inotify, bez dotazovani -------------------------------------------

function on_dir_event(path, event, other):
    if monitor_state["timer"] == 0:
        monitor_state["timer"] = glib.timeout_add(400, on_dir_changed)
    end
    return 0
end

function on_dir_changed():
    monitor_state["timer"] = 0
    if ics.reload_if_changed(store):
        call refresh()
        call reminders_schedule()
    end
    return False
end

# ---- start -------------------------------------------------------------------------------------------------------

# Skryte okno kalendare s pripominkami a hlidanim souboru (pouziva i luxos-hub)
function create(background):
    global store, created, test_log
    if created:
        return 0
    end
    created = True
    test_log = env.get("LUXOS_CAL_TEST_LOG", "")
    if test_log == None:
        test_log = ""
    end
    store = ics.store_new(env.get("LUXOS_CALENDAR_DIR", ""))
    call ics.reload_if_changed(store)
    cal["day"] = date.today()
    ymd = date.from_ordinal(cal["day"])
    cal["month"] = [ymd[0], ymd[1]]
    cal["mode"] = "day"
    cal["showing"] = ""
    cal["last_color"] = ics.DEFAULT_COLOR

    win = gtk.window_new(i18n.T("Calendar"))
    cal["win"] = win
    call gtk.widget_add_class(win, "lc")
    call gtk.window_set_decorated(win, False)
    call gtk.window_set_resizable(win, False)
    call gtk.window_set_skip_taskbar_hint(win, True)
    call gtk.window_set_skip_pager_hint(win, True)
    call gtk.window_set_keep_above(win, True)
    call gtk.window_set_type_hint(win, gtk.TYPE_HINT_DIALOG)
    call gtk.window_stick(win)
    call gtk.window_set_rgba(win)
    # vlastni WM_CLASS i ve sdilenem procesu luxos-hub
    call gtk.window_set_wmclass(win, "luxos-calendar", "Luxos-calendar")

    root = gtk.box_new(gtk.VERTICAL, 12)
    call gtk.widget_add_class(root, "lc-box")
    call gtk.widget_set_size_request(root, WIDTH, -1)
    call gtk.container_add(win, root)
    cal["root"] = root
    top = gtk.box_new(gtk.HORIZONTAL, 8)
    cal["seg"] = segmented_new(["day", "month", "year"], [i18n.T("Day"), i18n.T("Month"), i18n.T("Year")], on_seg_change, False)
    call gtk.box_pack_start(top, cal["seg"]["box"], False, False, 0)
    cal["add_btn"] = icon_button("list-add-symbolic", new_event, 0, "lc-add", i18n.T("New Event"))
    call gtk.box_pack_end(top, cal["add_btn"], False, False, 0)
    cal["top"] = top
    call gtk.box_pack_start(root, top, False, False, 0)
    cal["holder"] = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.box_pack_start(root, cal["holder"], False, False, 0)
    call theme_apply()
    call gtk.connect(gtk.settings_get_default(), "notify::gtk-theme-name", on_theme_changed)
    call segmented_set(cal["seg"], "day", False)
    call show_view("day")

    call gtk.connect(win, "focus-out-event", on_focus_out)
    call gtk.connect(win, "key-press-event", on_key)
    call gtk.connect(win, "delete-event", on_delete)
    call gtk.widget_show_all(root)

    # pripominky: po probuzeni z uspani znovu naplanovat
    safe:
        call gio.subscribe_values(gio.system_bus(), "org.freedesktop.login1", "org.freedesktop.login1.Manager", "PrepareForSleep", "/org/freedesktop/login1", on_sleep_signal)
    end
    safe:
        call glib.mkdir_p(store["dir"])
        call gio.file_monitor(store["dir"], on_dir_event)
    end
    call reminders_schedule()
    if background:
        call glib.timeout_add_seconds(5, migrate_panel)
    end
    return 0
end
