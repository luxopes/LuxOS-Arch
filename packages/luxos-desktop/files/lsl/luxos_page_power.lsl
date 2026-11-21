# LuxOS - Nastaveni > Baterie a napajeni (drive luxos-power): stav baterie, grafy za 24 hodin a nastaveni.
# Udaje z UPower (systemova sbernice): procenta, nabijeni/vybijeni, odhad vydrze, spotreba ve wattech, zdravi
# baterie a historie urovne a spotreby. Rezim napajeni primo pres power-profiles-daemon (D-Bus), Sporic baterie
# (luxos-powersaver), casy vypnuti obrazovky a uspani (xfce4-power-manager, jen relace X11 - na Waylandu vik
# a necinnost resi logind).
#
# LUXOS_POWER_DEMO=1 ukazkova data (zarizeni bez baterie, testy), LUXOS_POWER_DEMO=full nabijecka a plne nabita
# baterie bez poctu cyklu. Ukazkovy rezim nesaha na systemovou sbernici ani na luxos-gpu.
# Stav se obnovuje jen pri zobrazene strance (casovace zapina show, vypina leave).
load env, json
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load gio, cairo
load luxos_i18n as i18n
load luxos_power_model as m
load luxos_settings_ui as ui

UP = "org.freedesktop.UPower"
DISPLAY_DEVICE = "/org/freedesktop/UPower/devices/DisplayDevice"
PPD = [["org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles"],
    ["net.hadess.PowerProfiles", "/net/hadess/PowerProfiles"]]
PM = "xfce4-power-manager"
COLORS = {"cpu": "#3d7bff", "battery": "#30c48d", "battery_low": "#ff453a"}
CSS = ".power-pct { font-size: 44px; font-weight: 800; }\n.power-state { font-size: 14px; opacity: 0.75; }\n.power-card { padding: 14px; }\n.power-card-title { font-weight: 700; font-size: 13px; }\n.power-value { font-size: 20px; font-weight: 700; }\n.power-sub { font-size: 11px; opacity: 0.6; }\n.power-na { font-size: 15px; font-weight: 600; opacity: 0.8; }\n.power-modes .mode { padding: 8px 12px; }\n"

DEMO = env.get("LUXOS_POWER_DEMO", "") in ["1", "full"]
DEMO_FULL = env.get("LUXOS_POWER_DEMO", "") == "full"
config = glib.user_config_dir() + "/luxos"
SAVER_STATE = config + "/powersaver"
SAVER_60HZ = config + "/powersaver-60hz"
AUTO_SAVER = config + "/powersaver-auto"
# Neuspavat pri prehravani (luxos-hub): priznak vypnute volby a puvodni hodnoty xfce4-power-manager, ktere
# luxos-hub behem prehravani docasne prepsal - okno pak ukazuje a meni tyto puvodni hodnoty
SLEEP_WHILE_PLAYING = config + "/sleep-while-playing"
SLEEP_OVERRIDE = config + "/sleep-override"

app = {"bus": None, "paths": [], "modes": {}, "syncing": False, "saver": 0, "saver_touched": -60000000,
       "gpu": None, "gpu_label": 0, "pm": None, "charts": {}, "points": {}, "icon": [0.0, False], "css": 0, "timers": []}
w = {}

function wayland():
    return env.get("WAYLAND_DISPLAY", "") != ""
end

# ---- UPower a power-profiles-daemon --------------------------------------------------------------------------

function props(path):
    if app["bus"] == None:
        return {}
    end
    out = {}
    safe:
        out = gio.call_values(app["bus"], UP, path, "org.freedesktop.DBus.Properties", "GetAll", [UP + ".Device"], "(s)", 3000)[0]
    end
    return out
end

function find_batteries():
    if app["bus"] == None:
        return []
    end
    paths = []
    safe:
        paths = gio.call_values(app["bus"], UP, "/org/freedesktop/UPower", UP, "EnumerateDevices", [], "", 3000)[0]
    end
    found = []
    for path in paths:
        p = props(path)
        if p.get("Type", 0) == 2 and p.get("PowerSupply", False):
            found.append(path)
        end
    end
    return found
end

# Historie (graf) jen z prvni baterie, stav za vsechny
function battery_info():
    if DEMO:
        return m.demo_info(DEMO_FULL)
    end
    if len(app["paths"]) == 0:
        return None
    end
    first = props(app["paths"][0])
    if len(app["paths"]) == 1:
        return first
    end
    return m.combine(first, props(DISPLAY_DEVICE), [props(p) for p in app["paths"]])
end

function history(kind):
    if DEMO:
        return m.demo_history(kind, glib.now())
    end
    if len(app["paths"]) == 0:
        return []
    end
    raw = []
    safe:
        raw = gio.call_values(app["bus"], UP, app["paths"][0], UP + ".Device", "GetHistory", [kind, m.HISTORY_LOOKBACK, m.HISTORY_POINTS], "(suu)", 3000)[0]
    end
    info = battery_info()
    if info == None:
        info = {}
    end
    return m.clean_history(raw, kind, info, glib.now(), 7200, 86400)
end

# [aktivni profil, [dostupne profily]]; primo pres D-Bus (powerprofilesctl je skript v Pythonu)
function ppd_state():
    if app["bus"] == None:
        return ["", []]
    end
    for item in PPD:
        v = None
        safe:
            v = gio.call_values(app["bus"], item[0], item[1], "org.freedesktop.DBus.Properties", "GetAll", [item[0]], "(s)", 2000)[0]
        end
        if v != None:
            return [String(v.get("ActiveProfile", "")), [String(p.get("Profile", "")) for p in v.get("Profiles", [])]]
        end
    end
    return ["", []]
end

function ppd_set(profile):
    if app["bus"] == None:
        return False
    end
    for item in PPD:
        done = False
        safe:
            call gio.call_values(app["bus"], item[0], item[1], "org.freedesktop.DBus.Properties", "Set", [item[0], "ActiveProfile", ["s", profile]], "(ssv)", 3000)
            done = True
        end
        if done:
            return True
        end
    end
    return False
end

# {"kind", "name"} samostatne grafiky z `luxos-gpu status`, None kdyz neni
function gpu_info():
    if DEMO:
        return None
    end
    vals = {}
    for line in ui.run(["luxos-gpu", "status"]).split("\n"):
        cut = line.find("=")
        if cut > 0:
            vals[line[0:cut]] = line[cut + 1:]
        end
    end
    if vals.get("gpu", "none") in ["", "none"] or vals.get("name", "") == "":
        return None
    end
    return {"kind": vals["gpu"], "name": vals["name"]}
end

# ---- kresleni ------------------------------------------------------------------------------------------------

function hex_byte(pair):
    digits = "0123456789abcdef"
    return digits.find(pair[0:1].lower()) * 16 + digits.find(pair[1:2].lower())
end

function set_hex(cr, color, alpha):
    return cairo.set_source_rgba(cr, Float(hex_byte(color[1:3])) / 255.0, Float(hex_byte(color[3:5])) / 255.0, Float(hex_byte(color[5:7])) / 255.0, alpha)
end

function set_fg(cr, widget, alpha):
    c = gtk.widget_get_color(widget, gtk.widget_get_state_flags(widget))
    return cairo.set_source_rgba(cr, c[0], c[1], c[2], alpha)
end

function rounded_rect(cr, x, y, width, height, r):
    r = min(r, width / 2.0, height / 2.0)
    call ui.new_sub_path(cr)
    call cairo.arc(cr, x + width - r, y + r, r, -1.5707963, 0.0)
    call cairo.arc(cr, x + width - r, y + height - r, r, 0.0, 1.5707963)
    call cairo.arc(cr, x + r, y + height - r, r, 1.5707963, 3.1415927)
    call cairo.arc(cr, x + r, y + r, r, 3.1415927, 4.712389)
    return cairo.close_path(cr)
end

function hhmm(t):
    tm = glib.localtime(t)
    return text_pad(tm[3]) + ":" + text_pad(tm[4])
end

function text_pad(n):
    if n < 10:
        return "0" + String(n)
    end
    return String(n)
end

# Uroven baterie za 24 h; useky nabijeni zvyraznene zelene (jako Android)
function draw_chart(kind, cr, widget):
    points = app["points"].get(kind, [])
    width = Float(gtk.widget_get_allocated_width(widget))
    height = Float(gtk.widget_get_allocated_height(widget))
    left = 34.0
    bottom = 20.0
    top = 8.0
    cw = width - left - 6.0
    ch = height - bottom - top
    call cairo.select_font_face(cr, "Inter", 0, 0)
    call cairo.set_font_size(cr, 10.0)
    real = [p for p in points if p != None]
    maximum = 100.0
    if kind != "charge":
        maximum = max([Float(p[1]) for p in real] + [5.0]) * 1.15
    end
    # mrizka a popisky osy Y
    for i in range(5):
        y = top + ch * Float(i) / 4.0
        call set_fg(cr, widget, 0.07)
        call cairo.set_line_width(cr, 1.0)
        call cairo.move_to(cr, left, y)
        call cairo.line_to(cr, left + cw, y)
        call cairo.stroke(cr)
        value = m.fixed0(maximum * (1.0 - Float(i) / 4.0))
        label = value + " W"
        if kind == "charge":
            label = value + " %"
        end
        call set_fg(cr, widget, 0.45)
        call cairo.move_to(cr, 0.0, y + 4.0)
        call cairo.show_text(cr, label)
    end
    now = glib.now()
    start = now - 86400
    # popisky osy X po 6 hodinach
    for hrs in [24, 18, 12, 6, 0]:
        x = left + cw * (1.0 - Float(hrs) / 24.0)
        label = i18n.T("now")
        if hrs != 0:
            label = hhmm(now - hrs * 3600)
        end
        advance = cairo.text_extents(cr, label)[4]
        call cairo.move_to(cr, min(max(x - advance / 2.0, left), left + cw - advance), height - 4.0)
        call cairo.show_text(cr, label)
    end
    if len(real) < 2:
        call set_fg(cr, widget, 0.5)
        call cairo.set_font_size(cr, 12.0)
        message = i18n.T("No history yet")
        advance = cairo.text_extents(cr, message)[4]
        call cairo.move_to(cr, left + cw / 2.0 - advance / 2.0, top + ch / 2.0)
        call cairo.show_text(cr, message)
        return False
    end
    # useky bez preruseni (None = vypnuty pocitac); bod pred zacatkem okna se orizne na start
    segments = []
    current = []
    for p in points:
        if p == None:
            if len(current) > 0:
                segments.append(current)
            end
            current = []
            continue
        end
        t = max(p[0], start)
        x = left + cw * Float(t - start) / 86400.0
        y = top + ch * (1.0 - min(Float(p[1]) / maximum, 1.0))
        current.append([x, y, p[2]])
    end
    if len(current) > 0:
        segments.append(current)
    end
    segments = [s for s in segments if s[len(s) - 1][0] >= left]
    if len(segments) == 0:
        return False
    end
    base = COLORS["battery"]
    if kind == "rate":
        base = COLORS["cpu"]
    end
    # vypln pod krivkou
    for s in segments:
        call cairo.move_to(cr, s[0][0], top + ch)
        for q in s:
            call cairo.line_to(cr, q[0], q[1])
        end
        call cairo.line_to(cr, s[len(s) - 1][0], top + ch)
        call cairo.close_path(cr)
    end
    call set_hex(cr, base, 0.18)
    call cairo.fill(cr)
    pts = []
    for s in segments:
        if len(pts) > 0:
            pts.append(None)
        end
        pts = pts + s
    end
    # useky nabijeni (jen graf urovne)
    if kind == "charge":
        for i in range(1, len(pts)):
            if pts[i] != None and pts[i - 1] != None and pts[i][2] == m.STATE_CHARGING:
                call cairo.rectangle(cr, pts[i - 1][0], top, pts[i][0] - pts[i - 1][0], ch)
            end
        end
        call set_hex(cr, COLORS["battery"], 0.12)
        call cairo.fill(cr)
    end
    call cairo.set_line_width(cr, 2.2)
    call cairo.set_line_join(cr, 1)
    for i in range(1, len(pts)):
        if pts[i] == None or pts[i - 1] == None:
            continue
        end
        color = base
        if kind == "charge" and pts[i][2] != m.STATE_CHARGING:
            color = "#8e8ea0"
            if pts[i][1] > top + ch * 0.8:
                color = COLORS["battery_low"]
            end
        end
        call set_hex(cr, color, 1.0)
        call cairo.move_to(cr, pts[i - 1][0], pts[i - 1][1])
        call cairo.line_to(cr, pts[i][0], pts[i][1])
        call cairo.stroke(cr)
    end
    return False
end

function draw_icon(cr, widget):
    pct = app["icon"][0]
    charging = app["icon"][1]
    bw = 64.0
    bh = 32.0
    y = (Float(gtk.widget_get_allocated_height(widget)) - bh) / 2.0
    call cairo.set_line_width(cr, 2.5)
    call set_fg(cr, widget, 0.5)
    call rounded_rect(cr, 2.0, y, bw, bh, 8.0)
    call cairo.stroke(cr)
    call rounded_rect(cr, bw + 4.0, y + bh / 2.0 - 6.0, 5.0, 12.0, 2.0)
    call cairo.fill(cr)
    color = COLORS["battery"]
    if pct <= 20.0 and not charging:
        color = COLORS["battery_low"]
    end
    call set_hex(cr, color, 1.0)
    call rounded_rect(cr, 6.0, y + 4.0, (bw - 8.0) * pct / 100.0, bh - 8.0, 5.0)
    call cairo.fill(cr)
    if charging:
        call cairo.set_source_rgba(cr, 1.0, 1.0, 1.0, 0.95)
        cx = 2.0 + bw / 2.0
        cy = y + bh / 2.0
        call cairo.move_to(cr, cx + 3.0, cy - 11.0)
        call cairo.line_to(cr, cx - 6.0, cy + 2.0)
        call cairo.line_to(cr, cx, cy + 2.0)
        call cairo.line_to(cr, cx - 3.0, cy + 11.0)
        call cairo.line_to(cr, cx + 6.0, cy - 2.0)
        call cairo.line_to(cr, cx, cy - 2.0)
        call cairo.close_path(cr)
        call cairo.fill(cr)
    end
    return False
end

# ---- okno ------------------------------------------------------------------------------------------------------

function label(text, css):
    l = gtk.label_new(text)
    call gtk.label_set_xalign(l, 0)
    if css != "":
        call gtk.widget_add_class(l, css)
    end
    return l
end

function card(title, value, sub):
    box = gtk.box_new(gtk.VERTICAL, 2)
    call gtk.widget_add_class(box, "power-card")
    call gtk.widget_add_class(box, "group")
    call gtk.box_pack_start(box, label(title, "power-card-title"), False, False, 0)
    call gtk.label_set_xalign(value, 0)
    call gtk.widget_add_class(value, "power-value")
    call gtk.label_set_xalign(sub, 0)
    call gtk.widget_add_class(sub, "power-sub")
    call gtk.box_pack_start(box, value, False, False, 0)
    call gtk.box_pack_start(box, sub, False, False, 0)
    return box
end

function section(page, title):
    call gtk.box_pack_start(page, label(title, "group-title"), False, False, 0)
end

function build_battery(page):
    box = gtk.box_new(gtk.VERTICAL, 14)
    call gtk.box_pack_start(page, box, False, False, 0)
    w["battery_box"] = box
    hero = gtk.box_new(gtk.HORIZONTAL, 16)
    icon = gtk.drawing_area_new()
    call gtk.widget_set_size_request(icon, 74, 40)
    call gtk.connect(icon, "draw", draw_icon)
    w["icon"] = icon
    call gtk.box_pack_start(hero, icon, False, False, 0)
    texts = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_valign(texts, gtk.ALIGN_CENTER)
    w["pct"] = label("", "power-pct")
    w["state"] = label("", "power-state")
    call gtk.box_pack_start(texts, w["pct"], False, False, 0)
    call gtk.box_pack_start(texts, w["state"], False, False, 0)
    call gtk.box_pack_start(hero, texts, True, True, 0)
    call gtk.box_pack_start(box, hero, False, False, 0)
    # Box (ne Grid): skryta karta Cykly (baterie je neudava) nenecha prazdny sloupec
    cards = gtk.box_new(gtk.HORIZONTAL, 12)
    call gtk.box_set_homogeneous(cards, True)
    for item in [["rate", "Power usage"], ["health", "Battery health"], ["cycles", "Charge cycles"], ["energy", "Energy"]]:
        value = gtk.label_new("")
        sub = gtk.label_new("")
        if item[0] == "cycles":
            call gtk.label_set_line_wrap(value, True)
        end
        w["v_" + item[0]] = value
        w["s_" + item[0]] = sub
        c = card(i18n.T(item[1]), value, sub)
        w["card_" + item[0]] = c
        call gtk.box_pack_start(cards, c, True, True, 0)
    end
    call gtk.box_pack_start(box, cards, False, False, 0)
    for item in [["Battery level - last 24 hours", "charge"], ["Power usage - last 24 hours", "rate"]]:
        call gtk.box_pack_start(box, label(i18n.T(item[0]), "group-title"), False, False, 0)
        chart = gtk.drawing_area_new()
        call gtk.widget_set_size_request(chart, -1, 170)
        call glib.connect_data(chart, "draw", 1, draw_chart, item[1])
        frame = gtk.box_new(gtk.HORIZONTAL, 0)
        call gtk.widget_add_class(frame, "power-card")
        call gtk.widget_add_class(frame, "group")
        call gtk.box_pack_start(frame, chart, True, True, 0)
        call gtk.box_pack_start(box, frame, False, False, 0)
        app["charts"][item[1]] = chart
    end
    w["no_battery"] = label(i18n.T("This computer runs on mains power - there is no battery."), "power-state")
    call gtk.box_pack_start(page, w["no_battery"], False, False, 0)
end

function build_settings(page):
    call section(page, i18n.T("Power mode"))
    modes = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_add_class(modes, "power-modes")
    state = ppd_state()
    first = 0
    for item in [["power-saver", "Power Saver", "Longest battery life"], ["balanced", "Balanced", "Recommended"],
                 ["performance", "Performance", "Fastest, uses more power"]]:
        if len(state[1]) > 0 and not (item[0] in state[1]):
            continue
        end
        b = ui.radio_button(first)
        if first == 0:
            first = b
        end
        call gtk.widget_add_class(b, "mode")
        inner = gtk.box_new(gtk.VERTICAL, 0)
        call gtk.box_pack_start(inner, label(i18n.T(item[1]), ""), False, False, 0)
        call gtk.box_pack_start(inner, label(i18n.T(item[2]), "power-sub"), False, False, 0)
        call gtk.container_add(b, inner)
        call gtk.toggle_button_set_active(b, item[0] == state[0])
        call glib.connect_data(b, "toggled", 0, on_mode, item[0])
        app["modes"][item[0]] = b
        call gtk.box_pack_start(modes, b, True, True, 0)
    end
    call gtk.box_pack_start(page, modes, False, False, 0)
    call mark_mode(state[0])
    # Grafika v rezimu Vykon (luxos-gpu): radek jen u pocitace se samostatnou grafikou
    app["gpu"] = gpu_info()
    gpu = label("", "power-sub")
    call gtk.label_set_line_wrap(gpu, True)
    call gtk.widget_set_no_show_all(gpu, app["gpu"] == None)
    call gtk.box_pack_start(page, gpu, False, False, 0)
    app["gpu_label"] = gpu
    call update_gpu(state[0])

    g = ui.group(page, i18n.T("Battery Saver"))
    # na pozadi: prepnuti monitoru na 60 Hz apod. nesmi zdrzet okno
    app["saver"] = ui.switch(exists(SAVER_STATE), on_saver, 0)
    call ui.row(g, i18n.T("Battery Saver"), i18n.T("Longer battery life: slower processor without turbo, slightly lower brightness, idle devices sleep and background tasks pause."), app["saver"])
    call ui.row(g, i18n.T("Turn on automatically at 20 %"), i18n.T("Turns off again when the computer is charging."), ui.switch(exists(AUTO_SAVER), on_flag, AUTO_SAVER))
    call ui.row(g, i18n.T("Lower the screen to 60 Hz"), i18n.T("A little more battery on 90-165 Hz screens. The screen goes dark for a moment when Battery Saver turns on or off."), ui.switch(exists(SAVER_60HZ), on_flag, SAVER_60HZ))

    g = ui.group(page, i18n.T("Screen and sleep"))
    if not wayland():
        # xfce4-power-manager: u necinnosti znamena 14 "nikdy" (nejmensi hodnota je 15 minut)
        times = [[0, i18n.T("Never")], [1, i18n.T("1 minute")], [2, i18n.T("2 minutes")], [5, i18n.T("5 minutes")],
                 [10, i18n.T("10 minutes")], [15, i18n.T("15 minutes")], [30, i18n.T("30 minutes")], [60, i18n.T("1 hour")]]
        sleep = [[14, i18n.T("Never")], [15, i18n.T("15 minutes")], [30, i18n.T("30 minutes")], [60, i18n.T("1 hour")], [120, i18n.T("2 hours")]]
        for item in [["Turn off the screen on battery after", "dpms-on-battery-off", times],
                     ["Turn off the screen on power adapter after", "dpms-on-ac-off", times],
                     ["Sleep on battery after", "inactivity-on-battery", sleep], ["Sleep on power adapter after", "inactivity-on-ac", sleep]]:
            call ui.row(g, i18n.T(item[0]), "", pm_combo_x11(item[1], item[2], [item[1]]))
        end
        lid = [[1, i18n.T("Sleep")], [3, i18n.T("Lock screen")], [0, i18n.T("Turn off the screen")], [2, i18n.T("Hibernate")]]
        call ui.row(g, i18n.T("When the lid is closed"), "", pm_combo_x11("lid-action-on-battery", lid, ["lid-action-on-battery", "lid-action-on-ac"]))
    end
    call ui.row(g, i18n.T("Stay awake while music or video is playing"), i18n.T("Music keeps playing even with the lid closed (the screen turns off). The computer goes to sleep when playback stops."), ui.switch(not exists(SLEEP_WHILE_PLAYING), on_playing, 0))
    if not wayland():
        more = gtk.button_new(i18n.T("Advanced Power Settings…"))
        call gtk.widget_set_halign(more, gtk.ALIGN_START)
        call gtk.widget_set_margins(more, 0, 0, 8, 0)
        call glib.connect_data(more, "clicked", 0, on_launch, ["xfce4-power-manager-settings"])
        call gtk.box_pack_start(page, more, False, False, 0)
    end
end

function update_gpu(profile):
    if app["gpu"] == None:
        return 0
    end
    name = app["gpu"]["name"]
    if profile == "performance":
        return gtk.label_set_text(app["gpu_label"], i18n.TF("Graphics: %s for games and demanding apps", [name]))
    end
    return gtk.label_set_text(app["gpu_label"], i18n.TF("Graphics: integrated (Performance mode uses %s for games)", [name]))
end

# Vybrany rezim ma prstenec v barve zvyrazneni (.mode.current z ui.css)
function mark_mode(profile):
    for key in app["modes"]:
        call gtk.widget_set_class(app["modes"][key], "current", key == profile)
    end
    return 0
end

# ---- xfce4-power-manager ----------------------------------------------------------------------------------------

function read_override():
    vals = {}
    for line in glib.read_text(SLEEP_OVERRIDE).split("\n"):
        cut = line.find("=")
        if cut > 0 and ui_digits(line[cut + 1:].strip()):
            vals[line[0:cut]] = line[cut + 1:].strip()
        end
    end
    return vals
end

function ui_digits(value):
    if value == "":
        return False
    end
    for ch in value:
        if ord(ch) < 48 or ord(ch) > 57:
            return False
        end
    end
    return True
end

function write_override(vals):
    body = ""
    for key in vals.keys():
        body = body + key + "=" + vals[key] + "\n"
    end
    return glib.write_atomic(SLEEP_OVERRIDE, body)
end

function pm_combo_x11(prop, options, props_list):
    if app["pm"] == None:
        # vsechny hodnoty jednim volanim (misto xfconf-query pro kazdou)
        app["pm"] = {}
        for line in ui.run(["xfconf-query", "-c", PM, "-lv"]).split("\n"):
            cut = line.find(" ")
            if cut > 0:
                app["pm"][line[0:cut]] = line[cut + 1:].strip()
            end
        end
    end
    current = read_override().get(prop, app["pm"].get("/" + PM + "/" + prop, ""))
    return ui.combo(options, current, i18n.T("%s minutes"), on_pm_x11, props_list)
end

# Behem prehravani drzi luxos-hub docasnou hodnotu: zmenit puvodni, kterou pak vrati
function on_pm_x11(props_list, value):
    over = read_override()
    for p in props_list:
        if p in over:
            over[p] = value
        else:
            call ui.run(["xfconf-query", "-c", PM, "-p", "/" + PM + "/" + p, "-n", "-t", "uint", "-s", value])
        end
    end
    if len(over) > 0:
        call write_override(over)
    end
    return 0
end

# ---- udalosti ----------------------------------------------------------------------------------------------------

function on_mode(key, button):
    if app["syncing"] or not gtk.toggle_button_get_active(button):
        return 0
    end
    # Vykon se Sporicem baterie nejde dohromady (procesor bez turba): Sporic nejdriv vypnout - vrati puvodni
    # profil, ktery se hned prepise na Vykon
    if key == "performance" and exists(SAVER_STATE):
        call ui.run(["luxos-powersaver", "off"])
        call ui.switch_set(app["saver"], False)
    end
    call ppd_set(key)
    call mark_mode(key)
    call update_gpu(key)
    return 0
end

function on_saver(unused, on):
    app["saver_touched"] = glib.monotonic_time()
    return ui.launch(["luxos-powersaver", "on" if on else "off"])
end

function on_flag(path, on):
    if on:
        return ui.touch(path)
    end
    return ui.remove(path)
end

# luxos-hub sleduje priznak (inotify) a pripadne hned vrati nastaveni uspavani
function on_playing(unused, on):
    if on:
        return ui.remove(SLEEP_WHILE_PLAYING)
    end
    return ui.touch(SLEEP_WHILE_PLAYING)
end

function on_launch(argv, button):
    return ui.launch(argv)
end

# Profil a Sporic mohla zmenit jina aplikace (Ovladaci centrum, automaticky Sporic pri 20 %) nebo prepinac
# Sporice tady (prepne profil na Usporny) - okno ukazuje skutecny stav
function sync_controls(profile):
    if profile in app["modes"] and not gtk.toggle_button_get_active(app["modes"][profile]):
        app["syncing"] = True
        call gtk.toggle_button_set_active(app["modes"][profile], True)
        app["syncing"] = False
    end
    # luxos-powersaver bezi na pozadi par sekund - mezitim prepinac nevracet podle souboru
    if glib.monotonic_time() - app["saver_touched"] > 15000000:
        call ui.switch_set(app["saver"], exists(SAVER_STATE))
    end
    call mark_mode(profile)
    return update_gpu(profile)
end

function set_value_class(on):
    call gtk.widget_set_class(w["v_rate"], "power-na", not on)
    return gtk.widget_set_class(w["v_rate"], "power-value", on)
end

function refresh():
    call sync_controls(ppd_state()[0])
    info = battery_info()
    has = info != None and info.get("IsPresent", True)
    call gtk.widget_set_visible(w["battery_box"], has)
    call gtk.widget_set_no_show_all(w["battery_box"], not has)
    call gtk.widget_set_visible(w["no_battery"], not has)
    if not has:
        return True
    end
    pct = Float(info.get("Percentage", 0.0))
    st = info.get("State", 0)
    charging = st == m.STATE_CHARGING or st == m.STATE_PENDING_CHARGE
    app["icon"] = [pct, charging]
    call gtk.widget_queue_draw(w["icon"])
    call gtk.label_set_text(w["pct"], m.fixed0(pct) + " %")
    call gtk.label_set_text(w["state"], m.status_text(info))
    rate = Float(info.get("EnergyRate", 0.0))
    if rate != 0.0:
        call gtk.label_set_text(w["v_rate"], i18n.decimal(m.fixed1(rate) + " W"))
        call gtk.label_set_text(w["s_rate"], i18n.T("charging power") if charging else i18n.T("current consumption"))
    else:
        # na nabijecce a plne nabita (nebo nenabiji) baterie nic neodebira - drive jen "-"
        if st == m.STATE_FULL:
            call gtk.label_set_text(w["v_rate"], i18n.T("Charging complete"))
        elif st in m.ON_BATTERY:
            call gtk.label_set_text(w["v_rate"], i18n.T("Not reported"))
        else:
            call gtk.label_set_text(w["v_rate"], i18n.T("Not charging"))
        end
        call gtk.label_set_text(w["s_rate"], "" if st in m.ON_BATTERY else i18n.T("running on the power adapter"))
    end
    call set_value_class(rate != 0.0)
    full = Float(info.get("EnergyFull", 0.0))
    design = Float(info.get("EnergyFullDesign", 0.0))
    health = Float(info.get("Capacity", 0.0))
    if health == 0.0 and design > 0.0:
        health = full / design * 100.0
    end
    call gtk.label_set_text(w["v_health"], m.fixed0(health) + " %" if health > 0.0 else "-")
    call gtk.label_set_text(w["s_health"], i18n.T("of original capacity"))
    cycles = Int(info.get("ChargeCycles", 0))
    if not DEMO:
        cycles = m.charge_cycles(info, "/sys/class/power_supply")
    end
    if cycles > 0:
        call gtk.label_set_text(w["v_cycles"], String(cycles))
        call gtk.label_set_text(w["s_cycles"], i18n.T("full charge cycles"))
        call gtk.widget_set_no_show_all(w["card_cycles"], False)
        call gtk.widget_show_all(w["card_cycles"])
    else:
        # mnoho notebooku (firmware baterie) pocet cyklu neudava - opotrebeni ukazuje Zdravi baterie
        call gtk.widget_set_no_show_all(w["card_cycles"], True)
        call gtk.widget_hide(w["card_cycles"])
    end
    call gtk.label_set_text(w["v_energy"], i18n.decimal(m.fixed1(info.get("Energy", 0.0)) + " Wh"))
    call gtk.label_set_text(w["s_energy"], i18n.T("of %.1f Wh").replace("%.1f", i18n.decimal(m.fixed1(full))) if full > 0.0 else "")
    return True
end

function refresh_history():
    for kind in ["charge", "rate"]:
        app["points"][kind] = history(kind)
        call gtk.widget_queue_draw(app["charts"][kind])
    end
    return True
end

function build(host):
    if app["css"] == 0:
        app["css"] = gtk.css_load(CSS)
    end
    if not DEMO:
        safe:
            app["bus"] = gio.system_bus()
        end
    end
    app["paths"] = find_batteries()
    page = ui.page_box()
    call build_battery(page)
    call build_settings(page)
    return page
end

function show(host):
    call refresh()
    call refresh_history()
    if len(app["timers"]) == 0:
        app["timers"] = [glib.timeout_add_seconds(5, refresh), glib.timeout_add_seconds(120, refresh_history)]
    end
    return 0
end

function leave(host):
    for timer in app["timers"]:
        call glib.source_remove(timer)
    end
    app["timers"] = []
    return 0
end

# Testy (LUXOS_TEST_CONTROL=1): "mode KLIC" klikne na rezim (testctl click hleda jen popisek tlacitka, rezim ma
# dva radky), "page-state" = vybrany rezim, Sporic a bezici casovace obnovy
function test(command, rest):
    if command == "mode" and rest in app["modes"]:
        call gtk.button_clicked(app["modes"][rest])
        return True
    end
    if command != "page-state":
        return False
    end
    mode = ""
    for key in app["modes"]:
        if gtk.toggle_button_get_active(app["modes"][key]):
            mode = key
        end
    end
    print "page-state " + json.encode({"mode": mode, "saver": gtk.switch_get_active(app["saver"]), "timers": len(app["timers"])})
    return True
end
