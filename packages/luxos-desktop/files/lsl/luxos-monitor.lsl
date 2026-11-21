# LuxOS - Monitor systemu: prehled vykonu v grafech a spustene aplikace (drive Python).
#
# Karty s kruhovymi ukazateli a grafem za posledni minutu (procesor, pamet, disk, sit), pod nimi spustene
# aplikace s ikonou a tlacitkem Ukoncit. Technicky vypis vsech procesu je az na prepnuti "Vsechny procesy".
# Seznam jde seradit klikem na zahlavi sloupce (nazev, procesor, pamet; druhy klik obrati poradi), volba se
# pamatuje v ~/.config/luxos/monitor.conf. Data cte primo z /proc, obnova kazdou sekundu.
#
# Aplikace v X11 = okna ze seznamu spravce oken (_NET_CLIENT_LIST, _NET_WM_PID) vcetne podprocesu, Ukoncit je
# zavre jako krizkem (_NET_CLOSE_WINDOW). Na Waylandu cizi okna ani jejich procesy neprivilegovany klient
# nevidi: aplikace jsou procesy uzivatele s viditelnou polozkou .desktop (nejvyssi v rodokmenu) a Ukoncit
# posle SIGTERM. Kdyz se aplikace do 5 s nezavre, okno nabidne vynucene ukonceni.
#
# LUXOS_MONITOR_DEMO=1: vymyslena data bez cteni /proc a bez ukoncovani procesu (testy rozvrzeni okna).
# Testy: LUXOS_TEST_CONTROL=1 (luxos_testctl, prikazy state, sort, quit), LUXOS_MONITOR_PROC=jiny /proc.
load env, cairo, json, math
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_monitor_model as m
load luxos_settings_ui as ui
load luxos_sys as sys
load luxos_testctl as testctl
load luxos_x11 as x11

HISTORY = 60           # bodu v grafech (1 s)
CLK = 100              # SC_CLK_TCK na Linuxu
PAGE = 4096
SIGTERM = 15
SIGKILL = 9
COLORS = {"cpu": "#3d7bff", "memory": "#a35bff", "disk": "#ff9f0a", "net": "#30c48d", "net2": "#3d7bff"}
CSS = ".card { border-radius: 16px; padding: 14px; background-color: alpha(currentColor, 0.05); }\n.card-title { font-weight: 700; font-size: 13px; }\n.card-sub { font-size: 11px; opacity: 0.6; }\n.section-title { font-size: 15px; font-weight: 700; margin-top: 6px; }\n.apps-list row { padding: 6px 10px; border-radius: 10px; }\n.apps-list row:hover { background-color: alpha(currentColor, 0.05); }\n.app-name { font-weight: 600; }\n.metric { font-feature-settings: \"tnum\"; opacity: 0.85; }\n.quit { border-radius: 999px; padding: 2px 12px; }\nbutton.sort { padding: 2px 6px; min-height: 0; border-radius: 6px; font-size: 11px; }\nbutton.sort label { opacity: 0.6; }\nbutton.sort.active label { opacity: 1; font-weight: 700; }\n"
FALLBACK_ICON = "application-x-executable"
# Casti plochy (lista, Dock, widgety ...): na Waylandu bez seznamu oken jinak vypadaji jako aplikace s .desktop
SHELL = ["luxos-bar", "luxos-dock", "luxos-dock-wayland", "plank", "luxos-widgets", "luxos-backdrop", "luxos-notify",
    "luxos-launchpad", "luxos-launchpad-wayland", "luxos-hub", "luxos-lock", "luxos-lock-session", "luxos-polkit",
    "luxwm", "labwc", "xfce4-panel", "xfdesktop"]

DEMO = env.get("LUXOS_MONITOR_DEMO", "") == "1"
PROC = env.get("LUXOS_MONITOR_PROC", "/proc")
WAYLAND = env.get("WAYLAND_DISPLAY", "") != ""
ME = sys.getuid()
NCPU = m.cpu_count(PROC + "/stat")
SEP = i18n.decimal_separator()

app = {"demo_t": 0, "prev": {}, "prev_time": 0, "groups": None, "procs": None, "cpu_prev": [0, 0], "net_prev": None,
    "disk_prev": 0, "cpu_model": None, "index": None, "users": None, "slots": [], "sort_key": "cpu", "sort_desc": True}
w = {}
cards = []

function sort_conf():
    return glib.user_config_dir() + "/luxos/monitor.conf"
end

function demo_tick():
    app["demo_t"] += 1
    return app["demo_t"]
end

# ---- C (GTK, GIO, stat) ------------------------------------------------------------------------------------------

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

# Vlastnik souboru (/proc/PID = uzivatel procesu); -1 kdyz neni
function owner(path):
    unsafe:
        buffer = __lsl_byte_zeros(256)
        base = __lsl_qbe_load64(__lsl_address(buffer) + 24)
        if __lsl_qbe_call2(__lsl_symbol("stat"), cstr(path), base) != 0:
            return -1
        end
        # struct stat x86_64: st_uid +28
        return __lsl_qbe_load32(base + 28)
    end
end

# [celkem, volne pro uzivatele] bajtu souboroveho systemu (statvfs)
function disk_space(path):
    unsafe:
        buffer = __lsl_byte_zeros(112)
        base = __lsl_qbe_load64(__lsl_address(buffer) + 24)
        if __lsl_qbe_s32(__lsl_qbe_call2(__lsl_symbol("statvfs"), cstr(path), base)) != 0:
            return [0, 0]
        end
        # f_frsize +8, f_blocks +16, f_bavail +32
        frsize = __lsl_qbe_load64(base + 8)
        return [__lsl_qbe_load64(base + 16) * frsize, __lsl_qbe_load64(base + 32) * frsize]
    end
end

function app_display_name(info):
    unsafe:
        return glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_app_info_get_display_name"), ptr(info)))
    end
end

function app_gicon(info):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("g_app_info_get_icon"), ptr(info))
    end
end

# Ikona 32 px: GIcon aplikace nebo jmeno ikony
function set_icon(image, icon):
    if type(icon) == "String":
        call gtk.image_set_from_icon_name(image, icon, 5)
    else:
        unsafe:
            # GTK_ICON_SIZE_DND
            call __lsl_qbe_call3(__lsl_symbol("gtk_image_set_from_gicon"), ptr(image), ptr(icon), 5)
        end
    end
    call gtk.image_set_pixel_size(image, 32)
end

function titlebar(window):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gtk_window_get_titlebar"), ptr(window))
    end
end

function size_request(widget):
    unsafe:
        cells = __lsl_byte_zeros(16)
        base = __lsl_qbe_load64(__lsl_address(cells) + 24)
        call __lsl_qbe_call3(__lsl_symbol("gtk_widget_get_size_request"), ptr(widget), base, base + 4)
        return [__lsl_qbe_s32(__lsl_qbe_load32(base)), __lsl_qbe_s32(__lsl_qbe_load32(base + 4))]
    end
end

function message_dialog(text, secondary):
    unsafe:
        # GTK_MESSAGE_WARNING 1, GTK_BUTTONS_NONE 0
        return __lsl_qbe_call10(__lsl_symbol("g_object_new"), __lsl_qbe_call0(__lsl_symbol("gtk_message_dialog_get_type")), cstr("message-type"), 1, cstr("buttons"), 0, cstr("text"), cstr(text), cstr("secondary-text"), cstr(secondary), 0)
    end
end

# Spustitelny soubor a StartupWMClass (mala pismena) -> [nazev, GIcon] viditelnych aplikaci z .desktop
function app_index():
    index = {}
    unsafe:
        list = __lsl_qbe_call0(__lsl_symbol("g_app_info_get_all"))
        node = list
        while node != 0:
            info = __lsl_qbe_load64(node)
            node = __lsl_qbe_load64(node + 8)
            if __lsl_qbe_s32(__lsl_qbe_call1(__lsl_symbol("g_app_info_should_show"), info)) == 0:
                continue
            end
            exe = glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_app_info_get_executable"), info))
            if exe == "":
                continue
            end
            entry = [app_display_name(info), app_gicon(info)]
            if entry[1] == 0:
                entry[1] = FALLBACK_ICON
            end
            base = m.base_name(exe)
            if base not in index:
                index[base] = entry
            end
            wm = glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_desktop_app_info_get_startup_wm_class"), info)).lower()
            if wm != "" and wm not in index:
                index[wm] = entry
            end
        end
        # objekty aplikaci (a jejich GIcon) zustavaji po celou dobu behu; seznam ne
        call __lsl_qbe_call1(__lsl_symbol("g_list_free"), list)
    end
    return index
end

# ---- sber dat ------------------------------------------------------------------------------------------------------

function read_cpu():
    if DEMO:
        t = demo_tick()
        return [t * 100, t * 100 - t * (35 + t % 20)]
    end
    return m.read_cpu(PROC + "/stat")
end

function read_mem():
    if DEMO:
        return [6 << 30, 16 << 30]
    end
    return m.read_mem(PROC + "/meminfo")
end

function read_net():
    if DEMO:
        return [app["demo_t"] * 900000, app["demo_t"] * 120000]
    end
    return m.read_net(PROC + "/net/dev")
end

function read_disk_io():
    if DEMO:
        return app["demo_t"] * 2000000
    end
    return m.read_disk_io(PROC + "/diskstats", "/sys/block")
end

function now():
    return Float(glib.monotonic_time()) / 1000000.0
end

# Spotreba procesoru a pameti po procesech (delta mezi obnovami)
function sample():
    if DEMO:
        names = ["firefox", "thunar", "luxos-terminal", "celluloid", "xfce4-panel", "luxos-hub"]
        return [{"pid": 1000 + i, "comm": names[i], "exe": names[i], "cpu": 2.5 * (i + 1), "mem": (i + 1) * 180 << 20,
            "uid": ME, "ppid": 1} for i in range(len(names))]
    end
    t = now()
    dt = max(t - app["prev_time"], 0.1)
    cur = {}
    result = []
    prev = app["prev"]
    for name in glib.list_dir(PROC):
        if not m.is_number(name):
            continue
        end
        dir = PROC + "/" + name
        st = m.parse_stat(glib.read_text(dir + "/stat"))
        if st == None:
            continue
        end
        uid = owner(dir)
        if uid < 0:
            continue
        end
        pid = Int(name)
        cur[pid] = st[2]
        cpu = Float(st[2] - prev.get(pid, st[2])) / Float(CLK) / dt * 100.0 / Float(NCPU)
        result.append({"pid": pid, "comm": st[0], "exe": m.program(st[0], glib.read_text(dir + "/cmdline")),
            "cpu": max(cpu, 0.0), "mem": st[3] * PAGE, "uid": uid, "ppid": st[1]})
    end
    app["prev"] = cur
    app["prev_time"] = t
    return result
end

function user_name(uid):
    if app["users"] == None:
        app["users"] = {}
        for line in glib.read_text("/etc/passwd").split("\n"):
            f = line.split(":")
            if len(f) > 2 and m.is_number(f[2]):
                app["users"][Int(f[2])] = f[0]
            end
        end
    end
    return app["users"].get(uid, String(uid))
end

function cpu_model():
    if app["cpu_model"] == None:
        app["cpu_model"] = ""
        for line in glib.read_text(PROC + "/cpuinfo").split("\n"):
            if line.startswith("model name"):
                app["cpu_model"] = line[line.find(":") + 1:].strip()
                break
            end
        end
    end
    return app["cpu_model"]
end

# ---- okna aplikaci ---------------------------------------------------------------------------------------------

# Okna z panelu uloh (X11): [[xid, pid, trida instance, trida skupiny]]
function x11_windows():
    out = []
    call x11.trap_push()
    normal = x11.atom("_NET_WM_WINDOW_TYPE_NORMAL")
    skip = x11.atom("_NET_WM_STATE_SKIP_TASKBAR")
    for xid in x11.cardinals(x11.root_xid(), "_NET_CLIENT_LIST"):
        types = x11.cardinals(xid, "_NET_WM_WINDOW_TYPE")
        if (len(types) > 0 and types[0] != normal) or skip in x11.cardinals(xid, "_NET_WM_STATE"):
            continue
        end
        pid = x11.cardinals(xid, "_NET_WM_PID")
        cls = x11.wm_class(xid)
        out.append([xid, pid[0] if len(pid) > 0 else 0, cls[0], cls[1]])
    end
    call x11.trap_pop()
    return out
end

# Zavrit okno jako krizkem: _NET_CLOSE_WINDOW spravci oken (zdroj 2 = pager)
function x11_close(xid, time):
    call x11.trap_push()
    unsafe:
        event = __lsl_byte_zeros(192)
        base = x11.data(event)
        call __lsl_qbe_store32(base, 33)                            # ClientMessage
        call __lsl_qbe_store64(base + 24, x11.xdisplay())
        call __lsl_qbe_store64(base + 32, ptr(xid))
        call __lsl_qbe_store64(base + 40, ptr(x11.atom("_NET_CLOSE_WINDOW")))
        call __lsl_qbe_store32(base + 48, 32)
        call __lsl_qbe_store64(base + 56, ptr(time))
        call __lsl_qbe_store64(base + 64, 2)
        # SubstructureRedirectMask | SubstructureNotifyMask
        call __lsl_qbe_call5(__lsl_symbol("XSendEvent"), x11.xdisplay(), x11.root_xid(), 0, 1572864, base)
        call __lsl_qbe_call1(__lsl_symbol("XFlush"), x11.xdisplay())
    end
    call x11.trap_pop()
    return 0
end

function new_group(name, icon):
    return {"name": name, "icon": icon, "cpu": 0.0, "mem": 0, "pids": [], "windows": []}
end

# Proces a jeho podprocesy do skupiny
function add_tree(g, pid, by_pid, children):
    stack = [pid]
    while len(stack) > 0:
        cur = stack.pop()
        if cur in g["pids"] or cur not in by_pid:
            continue
        end
        g["pids"].append(cur)
        g["cpu"] += by_pid[cur]["cpu"]
        g["mem"] += by_pid[cur]["mem"]
        stack = stack + children.get(cur, [])
    end
end

function lookup(p):
    return app["index"].get(p["exe"].lower(), app["index"].get(p["comm"].lower()))
end

# [nazev, ikona] procesu uzivatele s polozkou .desktop, ktery neni casti plochy; None
function wayland_app(p):
    if p["uid"] != ME or p["exe"] in SHELL:
        return None
    end
    return lookup(p)
end

function app_groups(procs, by_pid, children):
    groups = {}
    if app["index"] == None:
        app["index"] = app_index()
    end
    if WAYLAND:
        # aplikace = proces uzivatele s polozkou .desktop, jehoz rodic uz neni aplikaci (Firefox, ne jeho karty)
        for p in procs:
            hit = wayland_app(p)
            parent = by_pid.get(p["ppid"])
            if hit == None or (parent != None and wayland_app(parent) != None):
                continue
            end
            g = groups.get(hit[0])
            if g == None:
                g = new_group(hit[0], hit[1])
                groups[hit[0]] = g
            end
            call add_tree(g, p["pid"], by_pid, children)
        end
        return groups
    end
    # Aplikace = programy s oknem (bez panelu, docku a plochy) vcetne podprocesu
    for win in x11_windows():
        pid = win[1]
        if pid == 0 or pid not in by_pid:
            continue
        end
        hit = app["index"].get(win[2].lower())
        if hit == None:
            hit = lookup(by_pid[pid])
        end
        if hit == None:
            name = win[3]
            if name == "":
                name = by_pid[pid]["comm"]
            end
            hit = [name, FALLBACK_ICON]
        end
        g = groups.get(hit[0])
        if g == None:
            g = new_group(hit[0], hit[1])
            groups[hit[0]] = g
        end
        g["windows"].append(win[0])
        call add_tree(g, pid, by_pid, children)
    end
    return groups
end

# ---- kresleni ------------------------------------------------------------------------------------------------------

function hex_byte(pair):
    digits = "0123456789abcdef"
    return digits.find(pair[0:1].lower()) * 16 + digits.find(pair[1:2].lower())
end

function rgb(color):
    return [Float(hex_byte(color[1:3])) / 255.0, Float(hex_byte(color[3:5])) / 255.0, Float(hex_byte(color[5:7])) / 255.0]
end

function set_hex(cr, color, alpha):
    c = rgb(color)
    return cairo.set_source_rgba(cr, c[0], c[1], c[2], alpha)
end

function set_fg(cr, widget, alpha):
    c = gtk.widget_get_color(widget, gtk.widget_get_state_flags(widget))
    return cairo.set_source_rgba(cr, c[0], c[1], c[2], alpha)
end

function show_centered(cr, text, cx, y):
    call cairo.move_to(cr, cx - cairo.text_extents(cr, text)[4] / 2.0, y)
    return cairo.show_text(cr, text)
end

# Kruhovy ukazatel: podklad, vyplneny oblouk a text uprostred
function ring(cr, widget, cx, cy, radius, fraction, color, main, sub):
    fraction = max(0.0, min(1.0, fraction))
    call cairo.set_line_width(cr, 11.0)
    call cairo.set_line_cap(cr, 1)
    call set_fg(cr, widget, 0.10)
    call cairo.arc(cr, cx, cy, radius, 0.0, 2.0 * math.PI)
    call cairo.stroke(cr)
    if fraction > 0.003:
        call set_hex(cr, color, 1.0)
        start = -math.PI / 2.0
        call cairo.arc(cr, cx, cy, radius, start, start + 2.0 * math.PI * fraction)
        call cairo.stroke(cr)
    end
    call cairo.select_font_face(cr, "Inter", 0, 1)
    size = max(12.0, radius * 0.42)
    call cairo.set_font_size(cr, size)
    call set_fg(cr, widget, 1.0)
    if sub == "":
        call show_centered(cr, main, cx, cy + size * 0.35)
        return 0
    end
    call show_centered(cr, main, cx, cy)
    call cairo.select_font_face(cr, "Inter", 0, 0)
    call cairo.set_font_size(cr, max(9.0, radius * 0.2))
    call set_fg(cr, widget, 0.6)
    return show_centered(cr, sub, cx, cy + size * 0.85)
end

# Plosny graf: series = [[hodnoty, barva]], hodnoty zleva (nejstarsi) doprava; maximum None = podle dat
function area_chart(cr, widget, x, y, width, height, series, maximum):
    call cairo.set_line_width(cr, 1.0)
    call set_fg(cr, widget, 0.07)
    for i in range(1, 4):
        gy = y + height * Float(i) / 4.0
        call cairo.move_to(cr, x, gy)
        call cairo.line_to(cr, x + width, gy)
    end
    call cairo.stroke(cr)
    top = maximum
    if top == None:
        top = 0.000000001
        for s in series:
            for v in s[0]:
                top = max(top, Float(v))
            end
        end
    end
    for s in series:
        values = s[0]
        n = len(values)
        step = width / Float(n - 1)
        pts = [[x + Float(i) * step, y + height - height * min(Float(values[i]) / top, 1.0)] for i in range(n)]
        # vypln s prechodem
        call cairo.move_to(cr, pts[0][0], y + height)
        for p in pts:
            call cairo.line_to(cr, p[0], p[1])
        end
        call cairo.line_to(cr, pts[n - 1][0], y + height)
        call cairo.close_path(cr)
        c = rgb(s[1])
        grad = cairo.pattern_create_linear(0.0, y, 0.0, y + height)
        call cairo.pattern_add_color_stop_rgba(grad, 0.0, c[0], c[1], c[2], 0.35)
        call cairo.pattern_add_color_stop_rgba(grad, 1.0, c[0], c[1], c[2], 0.02)
        call cairo.set_source(cr, grad)
        call cairo.fill(cr)
        call cairo.pattern_destroy(grad)
        call cairo.set_line_width(cr, 2.0)
        call cairo.set_line_join(cr, 1)
        call set_hex(cr, s[1], 1.0)
        call cairo.move_to(cr, pts[0][0], pts[0][1])
        for p in pts[1:]:
            call cairo.line_to(cr, p[0], p[1])
        end
        call cairo.stroke(cr)
    end
    call cairo.select_font_face(cr, "Inter", 0, 0)
    call cairo.set_font_size(cr, 10.0)
    call set_fg(cr, widget, 0.5)
    call cairo.move_to(cr, x, y + height + 13.0)
    call cairo.show_text(cr, i18n.T("60 s ago"))
    right = i18n.T("now")
    call cairo.move_to(cr, x + width - cairo.text_extents(cr, right)[4], y + height + 13.0)
    return cairo.show_text(cr, right)
end

function draw_card(card, cr, widget):
    width = Float(gtk.widget_get_allocated_width(widget))
    height = Float(gtk.widget_get_allocated_height(widget))
    chart_h = 56.0
    if card["ring"]:
        r = min(width, height - chart_h - 26.0) / 2.0 - 8.0
        call ring(cr, widget, width / 2.0, r + 8.0, r, card["fraction"], card["colors"][0], card["center"], card["center_sub"])
    else:
        call cairo.select_font_face(cr, "Inter", 0, 1)
        call cairo.set_font_size(cr, 22.0)
        call set_fg(cr, widget, 1.0)
        call show_centered(cr, card["center"], width / 2.0, (height - chart_h) / 2.0)
        call cairo.select_font_face(cr, "Inter", 0, 0)
        call cairo.set_font_size(cr, 12.0)
        call set_fg(cr, widget, 0.6)
        call show_centered(cr, card["center_sub"], width / 2.0, (height - chart_h) / 2.0 + 22.0)
    end
    series = [[card["history"][i], card["colors"][i]] for i in range(len(card["history"]))]
    return area_chart(cr, widget, 0.0, height - chart_h - 14.0, width, chart_h, series, card["maximum"])
end

function on_draw(card, cr, widget):
    call draw_card(card, cr, widget)
    return False
end

# ---- widgety ---------------------------------------------------------------------------------------------------

function label(text, css, xalign):
    l = gtk.label_new(text)
    call gtk.label_set_xalign(l, xalign)
    if css != "":
        call gtk.widget_add_class(l, css)
    end
    return l
end

function zeros(n):
    return [0.0 for i in range(n)]
end

# Karta s kruhovym ukazatelem a grafem historie
function card_new(title, color, two_series):
    box = gtk.box_new(gtk.VERTICAL, 6)
    call gtk.widget_add_class(box, "card")
    sub = label("", "card-sub", 0.0)
    # PANGO_ELLIPSIZE_END
    call gtk.label_set_ellipsize(sub, 3)
    call gtk.box_pack_start(box, label(title, "card-title", 0.0), False, False, 0)
    call gtk.box_pack_start(box, sub, False, False, 0)
    area = gtk.drawing_area_new()
    call gtk.widget_set_size_request(area, 220, 190)
    call gtk.box_pack_start(box, area, True, True, 0)
    card = {"box": box, "sub": sub, "area": area, "fraction": 0.0, "center": "", "center_sub": "",
        "history": [zeros(HISTORY)], "colors": [color], "maximum": 100.0, "ring": True}
    if two_series:
        card["history"].append(zeros(HISTORY))
        card["colors"].append(COLORS["net2"])
    end
    call gtk.connect_data(area, "draw", 1, on_draw, card)
    cards.append(card)
    return card
end

function card_update(card, fraction, center, center_sub, values, sub):
    card["fraction"] = fraction
    card["center"] = center
    card["center_sub"] = center_sub
    for i in range(len(card["history"])):
        card["history"][i] = card["history"][i][1:] + [Float(values[i])]
    end
    call gtk.label_set_text(card["sub"], sub)
    call gtk.widget_queue_draw(card["area"])
end

# Radek seznamu (pozice v seznamu, obsah podle skupiny na teto pozici)
function slot_new():
    box = gtk.box_new(gtk.HORIZONTAL, 12)
    slot = {"box": box, "key": None, "icon": None, "image": gtk.image_new()}
    call gtk.box_pack_start(box, slot["image"], False, False, 0)
    text = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_valign(text, gtk.ALIGN_CENTER)
    slot["name"] = label("", "app-name", 0.0)
    call gtk.label_set_ellipsize(slot["name"], 3)
    slot["detail"] = label("", "card-sub", 0.0)
    call gtk.box_pack_start(text, slot["name"], False, False, 0)
    call gtk.box_pack_start(text, slot["detail"], False, False, 0)
    call gtk.box_pack_start(box, text, True, True, 0)
    slot["cpu"] = label("", "metric", 1.0)
    call gtk.label_set_width_chars(slot["cpu"], 8)
    slot["mem"] = label("", "metric", 1.0)
    call gtk.label_set_width_chars(slot["mem"], 10)
    call gtk.box_pack_start(box, slot["cpu"], False, False, 0)
    call gtk.box_pack_start(box, slot["mem"], False, False, 0)
    quit = gtk.button_new(i18n.T("Quit"))
    call gtk.widget_set_valign(quit, gtk.ALIGN_CENTER)
    call gtk.widget_add_class(quit, "quit")
    call gtk.connect_data(quit, "clicked", 0, on_quit, slot)
    call gtk.box_pack_start(box, quit, False, False, 0)
    call gtk.list_box_insert(w["list"], box, -1)
    call gtk.widget_show_all(gtk.widget_get_parent(box))
    return slot
end

function slot_update(slot, key, g):
    if slot["key"] != key:
        slot["key"] = key
        call gtk.label_set_text(slot["name"], g["name"])
    end
    if slot["icon"] != g["icon"]:
        slot["icon"] = g["icon"]
        call set_icon(slot["image"], g["icon"])
    end
    call gtk.label_set_text(slot["cpu"], m.fixed(g["cpu"], 1, SEP) + " %")
    call gtk.label_set_text(slot["mem"], m.human_bytes(g["mem"], False, SEP))
    count = len(g["pids"])
    if count > 1:
        call gtk.label_set_text(slot["detail"], i18n.TF("%d processes", [count]))
    else:
        call gtk.label_set_text(slot["detail"], i18n.T("1 process"))
    end
end

function build():
    window = ui.window(i18n.T("System Monitor"), "utilities-system-monitor", 1000, 760, 640, 420)
    w["window"] = window
    header = titlebar(window)
    w["all"] = gtk.switch_new()
    call gtk.widget_set_valign(w["all"], gtk.ALIGN_CENTER)
    call gtk.widget_set_name(w["all"], "all-processes")
    call gtk.connect_data(w["all"], "notify::active", 1, on_all, 0)
    call gtk.header_bar_pack_end(header, w["all"])
    call gtk.header_bar_pack_end(header, gtk.label_new(i18n.T("All processes")))

    scroll = gtk.scrolled_window_new()
    # vodorovne GTK_POLICY_NEVER, svisle AUTOMATIC
    call gtk.scrolled_window_set_policy(scroll, 2, 1)
    call gtk.container_add(window, scroll)
    page = gtk.box_new(gtk.VERTICAL, 14)
    call gtk.widget_set_margin(page, 20)
    call gtk.container_add(scroll, page)

    grid = gtk.grid_new()
    call gtk.grid_set_column_spacing(grid, 12)
    call gtk.grid_set_row_spacing(grid, 12)
    call gtk.grid_set_column_homogeneous(grid, True)
    w["cpu"] = card_new(i18n.T("Processor"), COLORS["cpu"], False)
    w["mem"] = card_new(i18n.T("Memory"), COLORS["memory"], False)
    w["disk"] = card_new(i18n.T("Disk"), COLORS["disk"], False)
    w["disk"]["maximum"] = None
    w["net"] = card_new(i18n.T("Network"), COLORS["net"], True)
    w["net"]["ring"] = False
    w["net"]["maximum"] = None
    for i in range(4):
        call gtk.grid_attach(grid, cards[i]["box"], i, 0, 1, 1)
    end
    call gtk.box_pack_start(page, grid, False, False, 0)

    w["apps_title"] = label("", "section-title", 0.0)
    call gtk.widget_set_name(w["apps_title"], "apps-title")
    call gtk.box_pack_start(page, w["apps_title"], False, False, 0)
    # zahlavi sloupcu = tlacitka razeni
    saved = m.load_sort(sort_conf())
    app["sort_key"] = saved[0]
    app["sort_desc"] = saved[1]
    head = gtk.box_new(gtk.HORIZONTAL, 12)
    call gtk.widget_set_margins(head, 50, 90, 0, 0)
    w["sort"] = {}
    for col in [["name", i18n.T("Name"), 0, True], ["cpu", i18n.T("Processor"), 8, False], ["mem", i18n.T("Memory"), 10, False]]:
        btn = gtk.button_new_empty()
        # GTK_RELIEF_NONE
        call gtk.button_set_relief(btn, 2)
        call gtk.widget_add_class(btn, "sort")
        call gtk.widget_set_name(btn, "sort-" + col[0])
        lab = label("", "", 0.0 if col[0] == "name" else 1.0)
        call gtk.label_set_width_chars(lab, col[2])
        call gtk.container_add(btn, lab)
        call gtk.connect_data(btn, "clicked", 0, on_sort, col[0])
        call gtk.box_pack_start(head, btn, col[3], col[3], 0)
        if col[0] == "name":
            call gtk.widget_set_halign(btn, gtk.ALIGN_START)
        end
        w["sort"][col[0]] = [btn, lab, col[1]]
    end
    call update_sort_buttons()
    call gtk.box_pack_start(page, head, False, False, 0)
    w["list"] = gtk.list_box_new()
    # GTK_SELECTION_NONE
    call gtk.list_box_set_selection_mode(w["list"], 0)
    call gtk.widget_add_class(w["list"], "apps-list")
    call gtk.box_pack_start(page, w["list"], False, False, 0)
    call gtk.connect_data(window, "destroy", 0, on_destroy, 0)
end

# ---- razeni ----------------------------------------------------------------------------------------------------

function on_sort(key, button):
    call set_sort(key)
    return 0
end

function set_sort(key):
    if key == app["sort_key"]:
        app["sort_desc"] = not app["sort_desc"]
    else:
        # cisla od nejvetsiho, nazvy od A
        app["sort_key"] = key
        app["sort_desc"] = key != "name"
    end
    call m.save_sort(sort_conf(), app["sort_key"], app["sort_desc"])
    call update_sort_buttons()
    if app["groups"] != None and app["procs"] != None:
        call show_groups(app["groups"], app["procs"])
    end
end

function update_sort_buttons():
    for key in w["sort"]:
        b = w["sort"][key]
        arrow = ""
        if key == app["sort_key"]:
            arrow = " ▼" if app["sort_desc"] else " ▲"
            call gtk.widget_add_class(b[0], "active")
        else:
            call gtk.widget_remove_class(b[0], "active")
        end
        call gtk.label_set_text(b[1], b[2] + arrow)
    end
end

# ---- obnova ------------------------------------------------------------------------------------------------------

function pct(fraction):
    return m.fixed(fraction * 100.0, 0, SEP) + " %"
end

function refresh():
    cpu_now = read_cpu()
    pt = app["cpu_prev"]
    cpu = 100.0 * (1.0 - Float(cpu_now[1] - pt[1]) / Float(max(cpu_now[0] - pt[0], 1)))
    app["cpu_prev"] = cpu_now
    call card_update(w["cpu"], cpu / 100.0, pct(cpu / 100.0), i18n.TF("%d cores", [NCPU]), [cpu], cpu_model())

    mem = read_mem()
    frac = Float(mem[0]) / Float(max(mem[1], 1))
    used = m.human_bytes(mem[0], False, SEP)
    call card_update(w["mem"], frac, pct(frac), used, [frac * 100.0], i18n.TF("%s of %s used", [used, m.human_bytes(mem[1], False, SEP)]))

    d_total = 512 << 30
    d_used = 200 << 30
    if not DEMO:
        st = disk_space("/")
        d_total = max(st[0], 1)
        d_used = st[0] - st[1]
    end
    io = read_disk_io()
    rate = max(io - app["disk_prev"], 0)
    app["disk_prev"] = io
    dfrac = Float(d_used) / Float(max(d_total, 1))
    call card_update(w["disk"], dfrac, pct(dfrac), m.human_bytes(d_used, False, SEP), [rate], i18n.TF("%s free · activity %s", [m.human_bytes(d_total - d_used, False, SEP), m.human_bytes(rate, True, SEP)]))

    net = read_net()
    t = now()
    prev = app["net_prev"]
    dt = max(t - prev[1], 0.1)
    down = Float(max(net[0] - prev[0][0], 0)) / dt
    up = Float(max(net[1] - prev[0][1], 0)) / dt
    app["net_prev"] = [net, t]
    call card_update(w["net"], 0.0, "↓ " + m.human_bytes(down, True, SEP), "↑ " + m.human_bytes(up, True, SEP), [down, up], i18n.T("Download and upload"))
    call refresh_lists()
end

function on_tick(unused):
    call refresh()
    return True
end

function refresh_lists():
    procs = sample()
    app["procs"] = procs
    by_pid = {}
    children = {}
    for p in procs:
        by_pid[p["pid"]] = p
        if p["ppid"] not in children:
            children[p["ppid"]] = []
        end
        children[p["ppid"]].append(p["pid"])
    end
    groups = {}
    if gtk.switch_get_active(w["all"]):
        for p in procs:
            g = new_group(p["comm"] + "  (" + String(p["pid"]) + ", " + user_name(p["uid"]) + ")", FALLBACK_ICON)
            g["cpu"] = p["cpu"]
            g["mem"] = p["mem"]
            g["pids"] = [p["pid"]]
            groups[p["pid"]] = g
        end
    elif DEMO:
        for p in procs[:4]:
            g = new_group(p["exe"][:1].upper() + p["exe"][1:], FALLBACK_ICON)
            g["cpu"] = p["cpu"]
            g["mem"] = p["mem"]
            g["pids"] = [p["pid"]]
            groups[p["exe"]] = g
        end
    else:
        groups = app_groups(procs, by_pid, children)
    end
    call show_groups(groups, procs)
end

function show_groups(groups, procs):
    app["groups"] = groups
    show_all = gtk.switch_get_active(w["all"])
    ordered = m.sort_groups(groups, app["sort_key"], app["sort_desc"])
    if show_all:
        ordered = ordered[:150]
    end
    slots = app["slots"]
    while len(slots) > len(ordered):
        slot = slots.pop()
        call gtk.widget_destroy(gtk.widget_get_parent(slot["box"]))
    end
    while len(slots) < len(ordered):
        slots.append(slot_new())
    end
    for i in range(len(ordered)):
        call slot_update(slots[i], ordered[i][0], ordered[i][1])
    end
    if show_all:
        call gtk.label_set_text(w["apps_title"], i18n.TF("All processes (%d)", [len(procs)]))
    else:
        call gtk.label_set_text(w["apps_title"], i18n.TF("Open apps (%d)", [len(groups)]))
    end
end

function on_all(unused, pspec, sw):
    # jiny druh seznamu: radky znovu (ikony a nazvy se neprenaseji)
    for slot in app["slots"]:
        slot["key"] = None
    end
    call refresh_lists()
    return 0
end

# ---- ukonceni aplikace -------------------------------------------------------------------------------------------

function on_quit(slot, button):
    call quit_app(slot["key"])
    return 0
end

# Zavrit okna aplikace (jako krizkem); proces bez okna (a aplikace na Waylandu) dostane SIGTERM
function quit_app(key):
    if app["groups"] == None or DEMO:
        return 0
    end
    g = app["groups"].get(key)
    if g == None:
        return 0
    end
    if len(g["windows"]) > 0:
        for xid in g["windows"]:
            call x11_close(xid, gtk.get_current_event_time())
        end
    else:
        for pid in g["pids"]:
            call sys.kill(pid, SIGTERM)
        end
    end
    call glib.timeout_add_data(5000, check_quit, [g["windows"] + [], g["pids"] + [], g["name"]])
    return 0
end

# Okno se po 5 s nezavrelo (nebo proces bez okna bezi) -> nabidnout vynucene ukonceni
function check_quit(job):
    stuck = False
    if len(job[0]) > 0:
        open_now = [win[0] for win in x11_windows()]
        for xid in job[0]:
            if xid in open_now:
                stuck = True
            end
        end
    else:
        for pid in job[1]:
            if exists(PROC + "/" + String(pid)):
                stuck = True
            end
        end
    end
    if not stuck:
        return False
    end
    dlg = message_dialog(i18n.TF("%s is not responding", [job[2]]), i18n.T("Force quit it? Unsaved changes will be lost."))
    call gtk.window_set_transient_for(dlg, w["window"])
    call gtk.window_set_modal(dlg, True)
    call gtk.dialog_add_button(dlg, i18n.T("Cancel"), gtk.RESPONSE_CANCEL)
    call gtk.widget_add_class(gtk.dialog_add_button(dlg, i18n.T("Force Quit"), gtk.RESPONSE_OK), "destructive-action")
    if gtk.dialog_run(dlg) == gtk.RESPONSE_OK:
        for pid in job[1]:
            call sys.kill(pid, SIGKILL)
        end
    end
    call gtk.widget_destroy(dlg)
    return False
end

function on_destroy(unused, window):
    call gtk.main_quit()
    return 0
end

# ---- testy (LUXOS_TEST_CONTROL=1) ------------------------------------------------------------------------------

function on_test(command, rest):
    if command == "state":
        rows = []
        for slot in app["slots"]:
            rows.append({"key": String(slot["key"]), "name": gtk.label_get_text(slot["name"]),
                "detail": gtk.label_get_text(slot["detail"]), "cpu": gtk.label_get_text(slot["cpu"]),
                "mem": gtk.label_get_text(slot["mem"])})
        end
        heads = {}
        for key in w["sort"]:
            heads[key] = gtk.label_get_text(w["sort"][key][1])
        end
        subs = [gtk.label_get_text(c["sub"]) for c in cards]
        centers = [[c["center"], c["center_sub"]] for c in cards]
        print "state " + json.encode({"rows": rows, "sort": [app["sort_key"], app["sort_desc"]], "heads": heads,
            "title": gtk.label_get_text(w["apps_title"]), "subs": subs, "centers": centers,
            "min": size_request(w["window"])})
    elif command == "sort":
        call gtk.button_clicked(w["sort"][rest][0])
    elif command == "refresh":
        call refresh()
    elif command == "quit":
        call quit_app(rest)
    elif command == "close":
        call gtk.window_close(w["window"])
    end
end

# ---- start ---------------------------------------------------------------------------------------------------------

call glib.set_prgname("luxos-monitor")
call gtk.init()
call gtk.css_load(CSS)
call build()
app["cpu_prev"] = read_cpu()
app["prev_time"] = now()
app["net_prev"] = [read_net(), now()]
app["disk_prev"] = read_disk_io()
call refresh()
call gtk.widget_show_all(w["window"])
call glib.timeout_add_data(1000, on_tick, 0)
call testctl.start(on_test)
call gtk.main()
