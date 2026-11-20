# LuxOS - agent polkitu relace na Waylandu (sluzba uzivatele luxos-polkit.service, misto polkit-gnome).
# Kdyz program pozada o opravneni spravce (pkexec, Nastaveni, aktualizace), polkitd zavola tento agent a ten
# ukaze okno s heslem.
#
# Bez libpolkit-agent: PolkitAgentListener je abstraktni trida GObject a agent by ji musel podedit, to LSL
# neumi. Oba protokoly jsou ale male a stabilni, proto je mluvime primo:
#   D-Bus   objekt AGENT_PATH s rozhranim org.freedesktop.PolicyKit1.AuthenticationAgent, registrace
#           Authority.RegisterAuthenticationAgent pro relaci logindu. BeginAuthentication se odpovida az
#           po skonceni (uspech = prazdna odpoved, zruseni = chyba Cancelled).
#   heslo   pomocnik polkitu: soket /run/polkit/agent-helper.socket (polkit 126+, pomocnik bez setuid
#           aktivovany systemd), jinak spusteny /usr/lib/polkit-1/polkit-agent-helper-1. Posle se jmeno
#           uzivatele a cookie, pomocnik vraci radky g_strescape (PAM_PROMPT_ECHO_OFF/ON, PAM_ERROR_MSG,
#           PAM_TEXT_INFO) a nakonec SUCCESS nebo FAILURE. Vysledek hlasi polkitd sam pomocnik.
#
# GTK se nacita az s prvnim oknem: necinny agent drzi jen spojeni se systemovou sbernici.
# Kod 2 (systemd znovu nespousti): neni systemova sbernice, relace logindu nebo uz bezi jiny agent.
#
# Testy: LUXOS_POLKIT_SOCKET (jiny soket pomocnika, "" = jen spusteny pomocnik), LUXOS_POLKIT_HELPER (jiny
# pomocnik), LUXOS_POLKIT_TRACE=1 (udalosti na stdout), LUXOS_POLKIT_DUMPABLE=1 (proces jde cist, mereni PSS).
load env, glib, gio, fd
load luxos_glib as lglib
load luxos_gio as lgio
load luxos_gtk, gtk as gtk
load luxos_i18n as i18n
load luxos_sys
load luxos_lock_sys as sys

AGENT_PATH = "/cz/luxos/PolkitAgent"
AUTHORITY = "org.freedesktop.PolicyKit1"
AUTHORITY_PATH = "/org/freedesktop/PolicyKit1/Authority"
AUTHORITY_IFACE = "org.freedesktop.PolicyKit1.Authority"
CANCELLED = "org.freedesktop.PolicyKit1.Error.Cancelled"
FAILED = "org.freedesktop.PolicyKit1.Error.Failed"
LOGIN1 = "org.freedesktop.login1"
HELPER_SOCKET = "/run/polkit/agent-helper.socket"
HELPER = "/usr/lib/polkit-1/polkit-agent-helper-1"
SIGTERM = 15
# G_IO_IN | G_IO_ERR | G_IO_HUP
WATCH = 25

AGENT_XML = ("<node><interface name='org.freedesktop.PolicyKit1.AuthenticationAgent'>"
    + "<method name='BeginAuthentication'><arg type='s' direction='in'/><arg type='s' direction='in'/>"
    + "<arg type='s' direction='in'/><arg type='a{ss}' direction='in'/><arg type='s' direction='in'/>"
    + "<arg type='a(sa{sv})' direction='in'/></method>"
    + "<method name='CancelAuthentication'><arg type='s' direction='in'/></method>"
    + "</interface></node>")

CSS = ".polkit-error { color: #d0312d; }\n"
SHAKE = [8, -8, 6, -6, 4, -4, 2, -2, 0]

trace = env.get("LUXOS_POLKIT_TRACE", "") == "1"
state = {"bus": 0, "session": "", "owner": "", "gtk": False, "req": None, "gen": 0}
queue = []


function log(line):
    if trace:
        call luxos_sys.out(line + "\n")
    end
    return 0
end

# ---- libc ----

# Proces nejde ladit ani vypsat jinym procesem uzivatele a nema core dump (v pameti je heslo); zapis do
# zavrene roury pomocnika nesmi proces ukoncit (SIGPIPE)
function protect():
    if env.get("LUXOS_POLKIT_DUMPABLE", "") != "1":
        call sys.protect()
    end
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("signal"), 13, 1)
    end
    return 0
end

function user_name(uid):
    unsafe:
        entry = __lsl_qbe_call1(__lsl_symbol("getpwuid"), __lsl_unbox_int(uid))
        if entry == 0:
            return ""
        end
        return glib.from_c(__lsl_qbe_load64(entry))
    end
end

# Opak g_strescape, kterym pomocnik posila texty PAM (i UTF-8 jako osmickove kody)
function unescape(line):
    unsafe:
        return glib.take_c(__lsl_qbe_call1(__lsl_symbol("g_strcompress"), glib.cstr(line)))
    end
end

function write_all(handle, text):
    unsafe:
        total = __lsl_qbe_call1(__lsl_symbol("strlen"), glib.cstr(text))
        sent = 0
        tries = 0
        while sent < total:
            n = __lsl_qbe_s32(__lsl_qbe_call3(__lsl_symbol("write"), __lsl_unbox_int(handle), glib.cstr(text) + sent, total - sent))
            if n < 0:
                tries += 1
                code = luxos_sys.errno()
                if (code == luxos_sys.EINTR or code == luxos_sys.EAGAIN) and tries < 200:
                    call __lsl_qbe_call3(__lsl_symbol("poll"), 0, 0, 5)
                    continue
                end
                return False
            end
            sent += n
        end
    end
    return True
end

function gtk_ready():
    if not state["gtk"]:
        unsafe:
            if __lsl_qbe_icall2(__lsl_symbol("gtk_init_check"), 0, 0) == 0:
                return False
            end
        end
        call gtk.css_load(CSS)
        state["gtk"] = True
    end
    return True
end

# ---- pomocnik polkitu ----

function start_helper(req):
    state["gen"] = state["gen"] + 1
    req["gen"] = state["gen"]
    req["prompted"] = False
    req["asked"] = False
    req["running"] = True
    name = req["users"][req["user"]][1]
    path = env.get("LUXOS_POLKIT_SOCKET", HELPER_SOCKET)
    if path != "" and exists(path):
        handle = -1
        try:
            handle = fd.connect_unix(path)
        else:
            call luxos_sys.eprint("luxos-polkit: " + String(last_error()))
        end
        if handle >= 0:
            req["fd"] = handle
            req["input"] = handle
            req["buf"] = ""
            req["watch"] = lglib.fd_add_data(handle, WATCH, on_socket, [req, req["gen"]])
            call log("helper socket " + name)
            call write_all(handle, name + "\n" + req["cookie"] + "\n")
            return True
        end
    end
    child = sys.spawn_lines([env.get("LUXOS_POLKIT_HELPER", HELPER), name], [], on_helper_line, [req, req["gen"]])
    if len(child) == 0:
        req["running"] = False
        call show_message(req, i18n.T("Authentication is not available."), True)
        return False
    end
    req["pid"] = child[0]
    req["input"] = child[1]
    call log("helper spawn " + name)
    call write_all(child[1], req["cookie"] + "\n")
    return True
end

function stop_helper(req):
    if req["fd"] >= 0:
        call glib.source_remove(req["watch"][0])
        call lglib.release(req["watch"][1])
        call luxos_sys.close(req["fd"])
    elif req["input"] >= 0:
        call luxos_sys.close(req["input"])
    end
    if req["pid"] > 0:
        call luxos_sys.kill(req["pid"], SIGTERM)
    end
    req["fd"] = -1
    req["input"] = -1
    req["pid"] = 0
    req["running"] = False
    # cekajici zpetna volani stareho pomocnika se zahodi
    state["gen"] = state["gen"] + 1
    return 0
end

function current(bound):
    return state["req"] != None and bound[0] == state["req"] and bound[1] == bound[0]["gen"]
end

function on_socket(bound, handle, condition):
    if not current(bound):
        return False
    end
    req = bound[0]
    got = luxos_sys.recv_text(handle)
    if got[0] < 0:
        return True
    end
    if got[0] == 0:
        call lglib.release(req["watch"][1])
        call luxos_sys.close(handle)
        req["fd"] = -1
        req["input"] = -1
        call helper_ended(req)
        return False
    end
    text = req["buf"] + got[1]
    cut = text.find("\n")
    while cut >= 0:
        call helper_line(req, text[0:cut])
        if not current(bound):
            # okno se zavrelo nebo pomocnik skoncil: zdroj uz odebral stop_helper
            return True
        end
        text = text[cut + 1:]
        cut = text.find("\n")
    end
    req["buf"] = text
    return True
end

function on_helper_line(bound, line, status):
    if not current(bound):
        return 0
    end
    req = bound[0]
    if line == "":
        req["pid"] = 0
        call luxos_sys.close(req["input"])
        req["input"] = -1
        call helper_ended(req)
        return 0
    end
    call helper_line(req, line)
    return 0
end

function helper_line(req, raw):
    line = unescape(raw)
    if line.startswith("PAM_PROMPT_ECHO_OFF ") or line.startswith("PAM_PROMPT_ECHO_ON "):
        cut = line.find(" ")
        call prompt(req, line[cut + 1:], line.startswith("PAM_PROMPT_ECHO_ON "))
    elif line.startswith("PAM_ERROR_MSG "):
        call show_message(req, line[14:], True)
    elif line.startswith("PAM_TEXT_INFO "):
        call show_message(req, line[14:], False)
    elif line.startswith("SUCCESS"):
        call log("result success")
        call finish(req, True)
    else:
        call log("result failure")
        call failed(req)
    end
    return 0
end

function helper_ended(req):
    call log("helper ended")
    call failed(req)
    return 0
end

# Neuspech bez dotazu na heslo: pomocnik nejde pouzit (soket odmita, chybi setuid). Znovu jen po kliknuti,
# ne dokola.
function unavailable(req):
    call stop_helper(req)
    call show_message(req, i18n.T("Authentication is not available."), True)
    call gtk.widget_set_sensitive(req["ok"], True)
    return 0
end

function failed(req):
    if not req["asked"]:
        return unavailable(req)
    end
    call stop_helper(req)
    call show_message(req, i18n.T("Wrong password."), True)
    # hlaska zustava, dokud uzivatel znovu neodesle heslo (informace PAM noveho pokusu ji neprepise)
    req["sticky"] = True
    call gtk.entry_set_text(req["entry"], "")
    call shake(req)
    call start_helper(req)
    return 0
end

# ---- okno ----

function prompt(req, text, echo):
    req["prompted"] = True
    req["asked"] = True
    hint = text.strip()
    if hint.endswith(":"):
        hint = hint[0:len(hint) - 1].strip()
    end
    call log("prompt " + hint)
    call gtk.label_set_text(req["prompt"], text.strip())
    call gtk.entry_set_visibility(req["entry"], echo)
    call gtk.widget_set_sensitive(req["entry"], True)
    call gtk.widget_set_sensitive(req["ok"], True)
    call gtk.widget_grab_focus(req["entry"])
    return 0
end

function show_message(req, text, error):
    call log("message " + text)
    if req["sticky"] and not error:
        return 0
    end
    call gtk.label_set_text(req["info"], text)
    call gtk.widget_set_class(req["info"], "polkit-error", error)
    call gtk.widget_set_visible(req["info"], text != "")
    return 0
end

function on_submit(req, widget):
    if req != state["req"]:
        return 0
    end
    if not req["running"]:
        call show_message(req, "", False)
        call start_helper(req)
        return 0
    end
    if not req["prompted"]:
        return 0
    end
    req["prompted"] = False
    req["sticky"] = False
    call gtk.widget_set_sensitive(req["entry"], False)
    call gtk.widget_set_sensitive(req["ok"], False)
    call write_all(req["input"], gtk.entry_get_text(req["entry"]) + "\n")
    call gtk.entry_set_text(req["entry"], "")
    call log("answered")
    return 0
end

function on_cancel(req, widget):
    if req == state["req"]:
        call log("cancel")
        call finish(req, False)
    end
    return 0
end

function on_key(req, event, window):
    if gtk.event_key_keyval(event) == gtk.KEY_Escape:
        call on_cancel(req, window)
        return True
    end
    return False
end

function on_delete(req, event, window):
    call on_cancel(req, window)
    return True
end

function on_user(req, combo):
    if req != state["req"]:
        return 0
    end
    req["user"] = gtk.combo_box_get_active(combo)
    call stop_helper(req)
    call show_message(req, "", False)
    call start_helper(req)
    return 0
end

# Spatne heslo: okno se kratce zatrese (posun obsahu, okno na Waylandu nejde presunout)
function shake(req):
    req["shake"] = 0
    call lglib.timeout_add_data(30, on_shake, req)
    return 0
end

function on_shake(req):
    if req["win"] == 0:
        return False
    end
    offset = SHAKE[req["shake"]]
    call gtk.widget_set_margins(req["body"], 20 + offset, 20 - offset, 20, 16)
    req["shake"] = req["shake"] + 1
    return req["shake"] < len(SHAKE)
end

function build_window(req):
    win = gtk.window_new(i18n.T("Authentication required"))
    call gtk.window_set_type_hint(win, gtk.TYPE_HINT_DIALOG)
    call gtk.window_set_position(win, gtk.WIN_POS_CENTER)
    call gtk.window_set_resizable(win, False)
    call gtk.window_set_keep_above(win, True)
    call gtk.window_set_icon_name(win, "dialog-password")
    body = gtk.box_new(gtk.HORIZONTAL, 16)
    call gtk.widget_set_margins(body, 20, 20, 20, 16)
    icon = req["icon"]
    if icon == "" or not gtk.icon_theme_has_icon(icon):
        icon = "dialog-password"
    end
    image = gtk.image_new_from_icon_name(icon, 6)
    call gtk.image_set_pixel_size(image, 48)
    call gtk.widget_set_valign(image, gtk.ALIGN_START)
    call gtk.box_pack_start(body, image, False, False, 0)
    column = gtk.box_new(gtk.VERTICAL, 8)
    title = gtk.label_new("")
    call gtk.label_set_markup(title, "<b><big>" + glib.markup_escape(i18n.T("Authentication required")) + "</big></b>")
    call gtk.label_set_xalign(title, 0.0)
    call gtk.box_pack_start(column, title, False, False, 0)
    message = gtk.label_new(req["message"])
    call gtk.label_set_line_wrap(message, True)
    call gtk.label_set_max_width_chars(message, 48)
    call gtk.label_set_xalign(message, 0.0)
    call gtk.box_pack_start(column, message, False, False, 0)
    if req["choose"]:
        combo = gtk.combo_box_text_new()
        for user in req["users"]:
            call gtk.combo_box_text_append(combo, String(user[0]), user[1])
        end
        call gtk.combo_box_set_active(combo, req["user"])
        call gtk.connect_data(combo, "changed", 0, on_user, req)
        call gtk.widget_set_margins(combo, 0, 0, 4, 0)
        call gtk.box_pack_start(column, combo, False, False, 0)
    end
    row = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_set_margins(row, 0, 0, 4, 0)
    label = gtk.label_new(i18n.T("Password") + ":")
    call gtk.box_pack_start(row, label, False, False, 0)
    entry = gtk.entry_new()
    call gtk.entry_set_visibility(entry, False)
    call gtk.widget_set_sensitive(entry, False)
    call gtk.connect_data(entry, "activate", 0, on_submit, req)
    call gtk.box_pack_start(row, entry, True, True, 0)
    call gtk.box_pack_start(column, row, False, False, 0)
    info = gtk.label_new("")
    call gtk.label_set_line_wrap(info, True)
    call gtk.label_set_max_width_chars(info, 48)
    call gtk.label_set_xalign(info, 0.0)
    call gtk.widget_set_no_show_all(info, True)
    call gtk.box_pack_start(column, info, False, False, 0)
    buttons = gtk.box_new(gtk.HORIZONTAL, 8)
    call gtk.widget_set_halign(buttons, gtk.ALIGN_END)
    call gtk.widget_set_margins(buttons, 0, 0, 8, 0)
    cancel = gtk.button_new(i18n.T("Cancel"))
    call gtk.connect_data(cancel, "clicked", 0, on_cancel, req)
    call gtk.box_pack_start(buttons, cancel, False, False, 0)
    ok = gtk.button_new(i18n.T("Authenticate"))
    call gtk.widget_add_class(ok, "suggested-action")
    call gtk.widget_set_sensitive(ok, False)
    call gtk.connect_data(ok, "clicked", 0, on_submit, req)
    call gtk.box_pack_start(buttons, ok, False, False, 0)
    call gtk.box_pack_start(column, buttons, False, False, 0)
    call gtk.box_pack_start(body, column, True, True, 0)
    call gtk.container_add(win, body)
    call gtk.connect_data(win, "key-press-event", 1, on_key, req)
    call gtk.connect_data(win, "delete-event", 1, on_delete, req)
    req["win"] = win
    req["body"] = body
    req["entry"] = entry
    req["prompt"] = label
    req["info"] = info
    req["ok"] = ok
    call gtk.widget_show_all(win)
    call gtk.window_present(win)
    return 0
end

# ---- pozadavky polkitd ----

function start_next():
    if state["req"] != None or len(queue) == 0:
        return 0
    end
    req = queue.pop(0)
    if not gtk_ready():
        call luxos_sys.eprint("luxos-polkit: cannot open a window")
        call gio.return_error(req["invocation"], FAILED, "No display for the authentication dialog")
        return start_next()
    end
    state["req"] = req
    call build_window(req)
    call log("dialog " + req["users"][req["user"]][1])
    call start_helper(req)
    return 0
end

function finish(req, ok):
    call stop_helper(req)
    call gtk.widget_destroy(req["win"])
    req["win"] = 0
    state["req"] = None
    if ok:
        call gio.return_value(req["invocation"], [], "")
    else:
        call gio.return_error(req["invocation"], CANCELLED, "Authentication dialog was dismissed by the user")
    end
    call log("closed " + String(ok))
    call start_next()
    return 0
end

# Identity unix-user [uid, jmeno]; prednost ma prihlaseny uzivatel, jinak prvni spravce z nabidky polkitd
function begin(values, invocation):
    users = []
    for identity in values[5]:
        if identity[0] == "unix-user" and "uid" in identity[1]:
            name = user_name(identity[1]["uid"])
            if name != "":
                users.append([identity[1]["uid"], name])
            end
        end
    end
    if len(users) == 0:
        call gio.return_error(invocation, FAILED, "No user to authenticate as")
        return 0
    end
    me = luxos_sys.getuid()
    index = 0
    found = False
    while index < len(users) and not found:
        if users[index][0] == me:
            found = True
        else:
            index += 1
        end
    end
    if not found:
        index = 0
    end
    req = {"invocation": invocation, "action": values[0], "message": values[1], "icon": values[2],
           "cookie": values[4], "users": users, "user": index, "choose": not found and len(users) > 1,
           "gen": 0, "fd": -1, "input": -1, "pid": 0, "watch": [], "buf": "", "running": False,
           "prompted": False, "asked": False, "sticky": False, "win": 0, "shake": 0}
    call log("begin " + values[0])
    queue.append(req)
    call start_next()
    return 0
end

function cancel(cookie, invocation):
    req = state["req"]
    if req != None and req["cookie"] == cookie:
        call log("cancelled by authority")
        call finish(req, False)
        call gio.return_value(invocation, [], "")
        return 0
    end
    for waiting in List(queue):
        if waiting["cookie"] == cookie:
            call queue.remove(waiting)
            call gio.return_error(waiting["invocation"], CANCELLED, "Authentication was cancelled")
            call gio.return_value(invocation, [], "")
            return 0
        end
    end
    call gio.return_error(invocation, FAILED, "No such authentication session")
    return 0
end

function on_method(sender, path, interface, method, values, invocation):
    # politika sbernice pousti jen polkitd; kontrola navic, kdyby ji nekdo rozvolnil
    if sender != state["owner"]:
        call gio.return_error(invocation, FAILED, "Only the authority may call the agent")
        return 0
    end
    if method == "BeginAuthentication":
        call begin(values, invocation)
    elif method == "CancelAuthentication":
        call cancel(values[0], invocation)
    end
    return 0
end

# ---- registrace ----

function session_id():
    id = env.get("XDG_SESSION_ID", "")
    if id != "":
        return id
    end
    bus = state["bus"]
    safe:
        path = gio.call_values(bus, LOGIN1, "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "GetSessionByPID",
                               [glib.getpid()], "(u)", 5000)[0]
        return gio.get_property_value(bus, LOGIN1, path, "org.freedesktop.login1.Session", "Id")
    end
    # sluzba uzivatele nepatri do zadne relace: graficka relace uzivatele
    safe:
        return gio.get_property_value(bus, LOGIN1, "/org/freedesktop/login1/user/self", "org.freedesktop.login1.User", "Display")[0]
    end
    return ""
end

function locale():
    for name in ["LC_ALL", "LC_MESSAGES", "LANG"]:
        value = env.get(name, "")
        if value != "":
            return value
        end
    end
    return "C"
end

# "" nebo text chyby
function register():
    subject = ["unix-session", {"session-id": ["s", state["session"]]}]
    try:
        call gio.call_values(state["bus"], AUTHORITY, AUTHORITY_PATH, AUTHORITY_IFACE, "RegisterAuthenticationAgent",
                             [subject, locale(), AGENT_PATH], "((sa{sv})ss)", 25000)
    else:
        return String(last_error())
    end
    safe:
        state["owner"] = gio.call_values(state["bus"], "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                         "GetNameOwner", [AUTHORITY], "(s)", 5000)[0]
    end
    call log("registered " + state["session"])
    return ""
end

# polkitd po restartu agenty nezna: znovu se zaregistrovat; otevrene okno uz nema komu odpovedet
function on_owner(data, sender, path, interface, signal, values):
    state["owner"] = values[2]
    if values[2] == "":
        for waiting in List(queue):
            call queue.remove(waiting)
        end
        if state["req"] != None:
            call finish(state["req"], False)
        end
        return 0
    end
    error = register()
    if error != "":
        call luxos_sys.eprint("luxos-polkit: " + error)
    end
    return 0
end

function main():
    call protect()
    try:
        state["bus"] = gio.system_bus()
    else:
        call luxos_sys.eprint("luxos-polkit: no system bus: " + String(last_error()))
        call exit(2)
    end
    state["session"] = session_id()
    if state["session"] == "":
        call luxos_sys.eprint("luxos-polkit: no logind session")
        call exit(2)
    end
    try:
        call gio.register_object(state["bus"], AGENT_PATH, AGENT_XML, on_method)
    else:
        call luxos_sys.eprint("luxos-polkit: " + String(last_error()))
        call exit(1)
    end
    error = register()
    if error != "":
        call luxos_sys.eprint("luxos-polkit: " + error)
        if error.find("already exists") >= 0:
            call exit(2)
        end
        call exit(1)
    end
    call lgio.subscribe_data(state["bus"], "org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
                             "/org/freedesktop/DBus", AUTHORITY, lgio.SIGNAL_NONE, on_owner, 0)
    call glib.main()
    return 0
end

call main()
