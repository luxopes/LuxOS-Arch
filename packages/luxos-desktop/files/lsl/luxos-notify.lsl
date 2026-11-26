# LuxOS - server oznameni relace na Waylandu (org.freedesktop.Notifications), nahrada xfce4-notifyd
# s upravami LuxOS. Chovani podle docs/developers/notifications.md:
#   - bubliny vpravo nahore pod listou (layer-shell OVERLAY), nejnovejsi nahore, nejvys MAX_VISIBLE,
#     dalsi cekaji; najeti mysi zastavi odpocet, krizek pri najeti, prvni klik rozbali zkraceny text,
#     dalsi klik = akce "default" a zavreni, pravy klik zavre
#   - historie (x-luxos-keep, bez transient) v ~/.local/share/luxos, rozhrani org.xfce.Notifyd.Log
#     (jmena org.xfce.Notifyd i org.freedesktop.Notifications) a cz.luxos.NotificationHistory
#     (Activate jako luxos-notifyd.c, Nerusit, skryti bublin pod vyskakovacim oknem listy)
#   - Nerusit: bez bublin (krome kriticke nalehavosti), oznameni hned zavrene s duvodem 4, historie zustava
#   - nastaveni z ~/.config/luxos/notifications.conf (Nastaveni > Oznameni), zmena se nacte hned: DO_NOT_DISTURB,
#     BANNER_SECONDS (bez casu od aplikace), SOUNDS, HISTORY, HISTORY_SIZE, MUTED_APPS (jmena aplikaci oddelena ";",
#     jako muted_applications xfce4-notifyd: bez bublin); aplikace, ktere uz oznamovaly, v notification-apps
# Vse na udalostech: jeden casovac jen pro nejblizsi vyprseni, zadny periodicky beh.
load luxos_layer as layer
load luxos_primary as primary
load glib, gtk, gio
load luxos_glib as lglib
load luxos_tokens as tokens
load luxos_material as material
load luxos_gtk
load luxos_notify_store as store
load luxos_notify_sys as sys
load luxos_i18n as i18n
load luxos_text as ltext

FDO = "org.freedesktop.Notifications"
FDO_PATH = "/org/freedesktop/Notifications"
HISTORY_PATH = "/cz/luxos/NotificationHistory"
HISTORY_IFACE = "cz.luxos.NotificationHistory"
LOG_NAME = "org.xfce.Notifyd"
LOG_PATH = "/org/xfce/Notifyd"
LOG_IFACE = "org.xfce.Notifyd.Log"

DEFAULT_TIMEOUT = 6000
MAX_VISIBLE = 4
MAX_WAITING = 20
WIDTH = 344
GAP = 8
ICON = 36
MAX_ACTIONS = 3
# Zavrena bublina odjede doprava za okraj obrazovky (jako xfce4-notifyd na X11, slideout); ostatni stoji
SLIDE_MS = 260
MAX_SUMMARY = 200
MAX_BODY = 2000

EXPIRED = 1
DISMISSED = 2
CLOSED = 3
UNDEFINED = 4

FDO_XML = "<node><interface name='org.freedesktop.Notifications'>"
FDO_XML = FDO_XML + "<method name='Notify'><arg type='s' direction='in'/><arg type='u' direction='in'/><arg type='s' direction='in'/><arg type='s' direction='in'/><arg type='s' direction='in'/><arg type='as' direction='in'/><arg type='a{sv}' direction='in'/><arg type='i' direction='in'/><arg type='u' direction='out'/></method>"
FDO_XML = FDO_XML + "<method name='CloseNotification'><arg type='u' direction='in'/></method>"
FDO_XML = FDO_XML + "<method name='GetCapabilities'><arg type='as' direction='out'/></method>"
FDO_XML = FDO_XML + "<method name='GetServerInformation'><arg type='s' direction='out'/><arg type='s' direction='out'/><arg type='s' direction='out'/><arg type='s' direction='out'/></method>"
FDO_XML = FDO_XML + "<signal name='NotificationClosed'><arg type='u'/><arg type='u'/></signal>"
FDO_XML = FDO_XML + "<signal name='ActionInvoked'><arg type='u'/><arg type='s'/></signal>"
FDO_XML = FDO_XML + "</interface></node>"

HISTORY_XML = "<node><interface name='cz.luxos.NotificationHistory'>"
HISTORY_XML = HISTORY_XML + "<method name='Activate'><arg type='s' name='log_id' direction='in'/><arg type='b' name='handled' direction='out'/></method>"
HISTORY_XML = HISTORY_XML + "<method name='GetDoNotDisturb'><arg type='b' name='enabled' direction='out'/></method>"
HISTORY_XML = HISTORY_XML + "<method name='SetDoNotDisturb'><arg type='b' name='enabled' direction='in'/></method>"
HISTORY_XML = HISTORY_XML + "<method name='SetPopupsHidden'><arg type='b' name='hidden' direction='in'/></method>"
HISTORY_XML = HISTORY_XML + "<signal name='DoNotDisturbChanged'><arg type='b' name='enabled'/></signal>"
HISTORY_XML = HISTORY_XML + "</interface></node>"

ROW = "(sxssssssa(ss)ib)"
LOG_XML = "<node><interface name='org.xfce.Notifyd.Log'>"
LOG_XML = LOG_XML + "<method name='Get'><arg type='s' name='id' direction='in'/><arg type='" + ROW + "' name='entry' direction='out'/></method>"
LOG_XML = LOG_XML + "<method name='List'><arg type='s' name='start_after_id' direction='in'/><arg type='u' name='count' direction='in'/><arg type='b' name='only_unread' direction='in'/><arg type='a" + ROW + "' name='entries' direction='out'/></method>"
LOG_XML = LOG_XML + "<method name='HasUnread'><arg type='b' name='has_unread' direction='out'/></method>"
LOG_XML = LOG_XML + "<method name='GetAppIdCounts'><arg type='a(su)' name='app_id_counts' direction='out'/></method>"
LOG_XML = LOG_XML + "<method name='MarkRead'><arg type='as' name='ids' direction='in'/></method>"
LOG_XML = LOG_XML + "<method name='MarkAllRead'/>"
LOG_XML = LOG_XML + "<method name='Delete'><arg type='as' name='ids' direction='in'/></method>"
LOG_XML = LOG_XML + "<method name='Truncate'><arg type='u' name='entries_to_keep' direction='in'/></method>"
LOG_XML = LOG_XML + "<method name='Clear'/>"
LOG_XML = LOG_XML + "<signal name='RowAdded'><arg type='s' name='entry_id'/></signal>"
LOG_XML = LOG_XML + "<signal name='RowChanged'><arg type='s' name='entry_id'/></signal>"
LOG_XML = LOG_XML + "<signal name='RowDeleted'><arg type='s' name='entry_id'/></signal>"
LOG_XML = LOG_XML + "<signal name='Truncated'><arg type='u' name='n_entries_kept'/></signal>"
LOG_XML = LOG_XML + "<signal name='Cleared'/>"
LOG_XML = LOG_XML + "</interface></node>"

# notes: cislo -> oznameni; shown: cisla viditelnych bublin (nejnovejsi prvni); waiting: fronta
S = {"bus": 0, "notes": {}, "shown": [], "waiting": [], "slots": [], "window": 0, "column": 0,
     "dnd": False, "hidden": False, "paused": False, "timer": 0, "timer_record": 0, "save_id": 0,
     "save_record": 0, "css": 0, "dark": False, "tz": "", "sound": False, "banner_ms": DEFAULT_TIMEOUT,
     "sounds_on": True, "history_on": True, "muted": [], "known": [], "leaving": [], "slide_timer": 0}

function now_us():
    return glib.monotonic_time()
end

function config_dir():
    return glib.user_config_dir() + "/luxos"
end

function flag(value):
    if type(value) == "Bool":
        return value
    end
    if type(value) == "Int":
        return value != 0
    end
    return False
end

function clip(text, limit):
    if type(text) != "String":
        return ""
    end
    if len(text) > limit:
        return text[0:limit] + "…"
    end
    return text
end

# Notify(app, replaces, icon, summary, body, actions, hints, timeout) z GVariant
function parse_notify(params, sender):
    note = {"app": clip(sys.child_value(params, 0), 100), "replaces": sys.child_value(params, 1),
            "app_icon": clip(sys.child_value(params, 2), 1000), "summary": clip(sys.child_value(params, 3), MAX_SUMMARY),
            "body": clip(sys.child_value(params, 4), MAX_BODY), "actions": [], "timeout": sys.child_value(params, 7),
            "sender": sender, "image": 0, "slot": -1, "deadline": 0, "remaining": 0, "expanded": False,
            "quiet": False}
    raw = sys.child_value(params, 5)
    index = 0
    while index + 1 < len(raw) and len(note["actions"]) < 16:
        note["actions"].append([clip(raw[index], 100), clip(raw[index + 1], 100)])
        index += 2
    end
    dict = sys.child(params, 6)
    parsed = sys.notify_hints(dict, ICON)
    call sys.unref(dict)
    hints = parsed[0]
    note["image"] = parsed[1]
    urgency = hints.get("urgency", 1)
    if type(urgency) != "Int":
        urgency = 1
    end
    note["urgency"] = urgency
    note["transient"] = flag(hints.get("transient", False))
    note["keep"] = flag(hints.get("x-luxos-keep", False)) and not note["transient"]
    note["resident"] = flag(hints.get("resident", False))
    note["desktop"] = clip(hints.get("desktop-entry", ""), 200)
    note["image_path"] = clip(hints.get("image-path", hints.get("image_path", "")), 1000)
    note["sound"] = ""
    if not flag(hints.get("suppress-sound", False)):
        if type(hints.get("sound-file", None)) == "String":
            note["sound"] = "-f\n" + hints["sound-file"]
        elif type(hints.get("sound-name", None)) == "String":
            note["sound"] = "-i\n" + hints["sound-name"]
        end
    end
    return note
end

function has_default(note):
    for a in note["actions"]:
        if a[0] == "default":
            return True
        end
    end
    return False
end

# ---- D-Bus ----------------------------------------------------------------------------------

function emit(path, iface, signal, values, signature):
    safe:
        call gio.emit_values(S["bus"], path, iface, signal, values, signature)
    end
    return 0
end

function emit_log(signal, ids):
    for id in ids:
        call emit(LOG_PATH, LOG_IFACE, signal, [id], "(s)")
    end
    return 0
end

function request_name(name):
    reply = gio.call_values(S["bus"], "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName", [name, 4], "(su)", -1)
    # 1 = vlastnik, 4 = uz jsme vlastnik
    return reply[0] == 1 or reply[0] == 4
end

function name_alive(name):
    if name == "":
        return False
    end
    alive = False
    safe:
        alive = gio.call_values(S["bus"], "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner", [name], "(s)", 1000)[0] == True
    end
    return alive
end

# Obsluhy vraci [hodnoty, podpis]; odpoved jde vzdy prave jedna, i pri chybe obsluhy
function answer(invocation, method, handler, values):
    result = None
    try:
        result = handler(method, values)
    else:
        call glib.report("luxos-notify: " + method + ": " + String(last_error()) + chr(10))
        call gio.return_error(invocation, "org.freedesktop.DBus.Error.Failed", String(last_error()))
        return None
    end
    call gio.return_value(invocation, result[0], result[1])
    return result
end

function on_fdo(sender, method, params, invocation):
    result = answer(invocation, method, fdo_call, [sender, params])
    if result != None and method == "Notify":
        call after_reply(result[0][0])
    end
    return 0
end

function fdo_call(method, args):
    if method == "Notify":
        return [[notify(parse_notify(args[1], args[0]))], "(u)"]
    elif method == "CloseNotification":
        call close_by_app(sys.child_value(args[1], 0))
        return [[], ""]
    elif method == "GetCapabilities":
        caps = ["actions", "body", "body-markup", "icon-static", "persistence", "x-luxos-keep"]
        if S["sound"]:
            caps.append("sound")
        end
        return [[caps], "(as)"]
    elif method == "GetServerInformation":
        return [["luxos-notify", "LuxOS", "1.1.0", "1.2"], "(ssss)"]
    end
    Error(DBusError: "unknown method " + method)
end

function on_history(sender, path, interface, method, values, invocation):
    call answer(invocation, method, history_call, values)
    return 0
end

function history_call(method, values):
    if method == "Activate":
        return [[activate(values[0])], "(b)"]
    elif method == "GetDoNotDisturb":
        return [[S["dnd"]], "(b)"]
    elif method == "SetDoNotDisturb":
        call set_dnd(values[0] == True)
        return [[], ""]
    elif method == "SetPopupsHidden":
        call set_hidden(values[0] == True)
        return [[], ""]
    end
    Error(DBusError: "unknown method " + method)
end

function on_log(sender, path, interface, method, values, invocation):
    call answer(invocation, method, log_call, values)
    return 0
end

function log_call(method, values):
    if method == "List":
        return [[store.rows(values[0], values[1], values[2] == True)], "(a" + ROW + ")"]
    elif method == "Get":
        e = store.find(values[0])
        if e == None:
            Error(DBusError: "no entry " + values[0])
        end
        return [[store.row(e)], "(" + ROW + ")"]
    elif method == "HasUnread":
        return [[store.has_unread()], "(b)"]
    elif method == "GetAppIdCounts":
        return [[store.app_counts()], "(a(su))"]
    elif method == "MarkRead":
        call history_changed("RowChanged", store.mark_read(values[0]))
    elif method == "MarkAllRead":
        call history_changed("RowChanged", store.mark_all_read())
    elif method == "Delete":
        call history_delete(values[0])
    elif method == "Truncate":
        call forget_icons(store.truncate(values[0]))
        call schedule_save()
        call emit(LOG_PATH, LOG_IFACE, "Truncated", [len(store.state["entries"])], "(u)")
    elif method == "Clear":
        call forget_icons(store.clear())
        call schedule_save()
        call emit(LOG_PATH, LOG_IFACE, "Cleared", [], "")
    else:
        Error(DBusError: "unknown method " + method)
    end
    return [[], ""]
end

# ---- historie -------------------------------------------------------------------------------

function icons_dir():
    return store.state["dir"] + "/notification-icons"
end

# Obrazek z image-data ulozeny k zaznamu historie (smaze se se zaznamem)
function forget_icons(ids):
    for id in ids:
        call lglib.unlink(icons_dir() + "/" + id + ".png")
    end
    return 0
end

function save_icon(note, id):
    path = icons_dir() + "/" + id + ".png"
    call lglib.mkdir_p(icons_dir())
    if not sys.save_png(note["image"], path):
        return ""
    end
    return path
end

function history_icon(note):
    if note["image_path"] != "":
        return note["image_path"]
    end
    if note["app_icon"] != "":
        return note["app_icon"]
    end
    return note["desktop"]
end

function history_changed(signal, ids):
    if len(ids) > 0:
        call schedule_save()
        call emit_log(signal, ids)
    end
    return 0
end

function history_delete(ids):
    removed = store.remove(ids)
    call forget_icons(removed)
    call history_changed("RowDeleted", removed)
    return 0
end

function history_add(note, nid):
    # nahrazeni stejnym cislem: jeden souhrn misto hromady zaznamu
    call history_delete([e["id"] for e in store.with_nid(nid)])
    e = {"time": sys.real_time(), "tz": S["tz"], "app_id": note["desktop"], "app": note["app"],
         "icon": history_icon(note), "summary": note["summary"], "body": note["body"], "actions": note["actions"],
         "timeout": note["timeout"], "read": False, "nid": nid, "sender": note["sender"], "gone": False}
    ids = store.add(e)
    if note["image"] != 0:
        path = save_icon(note, ids[0])
        if path != "":
            e["icon"] = path
        end
    end
    call forget_icons(ids[1:])
    call schedule_save()
    call emit_log("RowAdded", [ids[0]])
    call emit_log("RowDeleted", ids[1:])
    return 0
end

function on_save():
    S["save_id"] = 0
    call store.save()
    return False
end

# Ukladani az v necinnosti: davka oznameni = jeden zapis
function schedule_save():
    if S["save_id"] == 0:
        S["save_id"] = sys.add_idle(S["save_record"], 200)
    end
    return 0
end

# Klik na zaznam v okne Oznameni: akce "default" aplikaci, dokud bezi a oznameni nezavrela
function activate(log_id):
    e = store.find(log_id)
    if e == None or e.get("gone", False) or not name_alive(e.get("sender", "")):
        return False
    end
    if not ("default" in [a[0] for a in e["actions"]]):
        return False
    end
    nid = e["nid"]
    call emit(FDO_PATH, FDO, "ActionInvoked", [nid, "default"], "(us)")
    if nid in S["notes"]:
        call close(nid, DISMISSED)
    else:
        call emit(FDO_PATH, FDO, "NotificationClosed", [nid, DISMISSED], "(uu)")
    end
    call history_delete([e["id"] for e in store.with_nid(nid)])
    return True
end

# ---- oznameni -------------------------------------------------------------------------------

function known_nid(nid):
    return nid in S["notes"] or len(store.with_nid(nid)) > 0
end

function notify(note):
    nid = note["replaces"]
    if nid == 0 or not known_nid(nid):
        nid = store.take_nid()
        while known_nid(nid):
            nid = store.take_nid()
        end
    end
    note["id"] = nid
    call remember_app(note["app"])
    if note["keep"] and S["history_on"]:
        call history_add(note, nid)
    end
    old = S["notes"].get(nid, None)
    if old != None:
        # nahrazeni: stejne misto ve sloupci, odpocet znovu
        note["slot"] = old["slot"]
        call free_image(old)
        S["notes"][nid] = note
        if note["slot"] >= 0:
            call fill(S["slots"][note["slot"]], note)
            call start_countdown(note)
            call schedule()
        end
        return nid
    end
    S["notes"][nid] = note
    note["quiet"] = (S["dnd"] or note["app"] in S["muted"]) and note["urgency"] < 2
    if not note["quiet"]:
        S["waiting"].append(nid)
        call drop_overflow()
        call show_waiting()
    end
    return nid
end

# Az po odpovedi na Notify (aplikace musi znat cislo, nez prijde signal)
function after_reply(nid):
    note = S["notes"].get(nid, None)
    if note != None and note["quiet"]:
        call close(nid, UNDEFINED)
    end
    return 0
end

function free_image(note):
    if note["image"] != 0:
        call glib.object_unref(note["image"])
        note["image"] = 0
    end
    return 0
end

# Prilis mnoho cekajicich (davka): nejstarsi nekriticke vyprsi hned
function drop_overflow():
    while len(S["waiting"]) > MAX_WAITING:
        victim = S["waiting"][0]
        for nid in S["waiting"]:
            if S["notes"][nid]["urgency"] < 2:
                victim = nid
                break
            end
        end
        call close(victim, EXPIRED)
    end
    return 0
end

function close_by_app(nid):
    if nid in S["notes"]:
        call close(nid, CLOSED)
    elif len(store.with_nid(nid)) > 0:
        call emit(FDO_PATH, FDO, "NotificationClosed", [nid, CLOSED], "(uu)")
    end
    # vyrizeno v aplikaci: z historie pryc
    call history_delete([e["id"] for e in store.with_nid(nid)])
    return 0
end

function close(nid, reason):
    note = S["notes"].pop(nid)
    if note["slot"] >= 0:
        call slide_out(note)
    elif nid in S["waiting"]:
        call S["waiting"].remove(nid)
    end
    call free_image(note)
    if reason == DISMISSED:
        # zavrel uzivatel: zaznam precteny a akce uz nema komu (aplikace oznameni zapomnela)
        for e in store.with_nid(nid):
            e["gone"] = True
        end
        call history_changed("RowChanged", store.mark_read([e["id"] for e in store.with_nid(nid)]))
    end
    call emit(FDO_PATH, FDO, "NotificationClosed", [nid, reason], "(uu)")
    call show_waiting()
    call schedule()
    return 0
end

function timeout_of(note):
    if note["urgency"] >= 2 or note["timeout"] == 0:
        return 0
    end
    if note["timeout"] < 0:
        return S["banner_ms"]
    end
    return note["timeout"]
end

function start_countdown(note):
    ms = timeout_of(note)
    note["remaining"] = ms
    note["deadline"] = 0
    if ms > 0 and not S["paused"]:
        note["deadline"] = now_us() + ms * 1000
    end
    return 0
end

function on_timer():
    S["timer"] = 0
    limit = now_us() + 5000
    for nid in S["shown"].copy():
        note = S["notes"][nid]
        if note["deadline"] > 0 and note["deadline"] <= limit:
            call close(nid, EXPIRED)
        end
    end
    call schedule()
    return False
end

# Jediny casovac na nejblizsi vyprseni; bez viditelne bubliny s odpoctem zadny
function schedule():
    if S["timer"] != 0:
        call glib.source_remove(S["timer"])
        S["timer"] = 0
    end
    if S["paused"] or S["hidden"]:
        return 0
    end
    first = 0
    for nid in S["shown"]:
        d = S["notes"][nid]["deadline"]
        if d > 0 and (first == 0 or d < first):
            first = d
        end
    end
    if first == 0:
        return 0
    end
    ms = max(1, (first - now_us()) // 1000 + 1)
    S["timer"] = sys.add_timeout(ms, S["timer_record"])
    return 0
end

function pause(on):
    if on == S["paused"]:
        return 0
    end
    S["paused"] = on
    now = now_us()
    for nid in S["shown"]:
        note = S["notes"][nid]
        if on and note["deadline"] > 0:
            note["remaining"] = max(0, (note["deadline"] - now) // 1000)
            note["deadline"] = 0
        elif not on and note["remaining"] > 0:
            # po odjeti mysi jeste chvili, at bublina nezmizi pod rukou
            note["deadline"] = now + max(note["remaining"], 1500) * 1000
        end
    end
    call schedule()
    return 0
end

function conf_path():
    return config_dir() + "/notifications.conf"
end

# KLIC=hodnota v notifications.conf; ostatni radky (TIME_CHANGE pro luxos-hub, volby Nastaveni) zustanou
function conf_write(key, value):
    lines = [line for line in lglib.read_text(conf_path()).split("\n") if line != "" and not line.startswith(key + "=")]
    lines.append(key + "=" + value)
    call lglib.mkdir_p(config_dir())
    return lglib.write_atomic(conf_path(), "\n".join(lines) + "\n")
end

function set_dnd(on):
    if on == S["dnd"]:
        return 0
    end
    S["dnd"] = on
    value = "false"
    if on:
        value = "true"
    end
    call conf_write("DO_NOT_DISTURB", value)
    call emit(HISTORY_PATH, HISTORY_IFACE, "DoNotDisturbChanged", [on], "(b)")
    return 0
end

function number(value, default, lo, hi):
    if ltext.is_digits(value):
        return min(hi, max(lo, Int(value)))
    end
    return default
end

function load_config():
    conf = {}
    for line in lglib.read_text(conf_path()).split("\n"):
        cut = line.find("=")
        if cut > 0:
            conf[line[0:cut].strip()] = line[cut + 1:].strip()
        end
    end
    S["banner_ms"] = number(conf.get("BANNER_SECONDS", ""), DEFAULT_TIMEOUT // 1000, 1, 600) * 1000
    S["sounds_on"] = conf.get("SOUNDS", "1") != "0"
    S["history_on"] = conf.get("HISTORY", "1") != "0"
    call store.set_max(number(conf.get("HISTORY_SIZE", ""), store.MAX, 1, 1000))
    S["muted"] = [a for a in conf.get("MUTED_APPS", "").split(";") if a != ""]
    return conf.get("DO_NOT_DISTURB", "") == "true"
end

# Zmena z Nastaveni nebo zapis vlastniho Nerusit (pak beze zmeny a bez signalu)
function on_config(path, event, other):
    dnd = load_config()
    if dnd != S["dnd"]:
        S["dnd"] = dnd
        call emit(HISTORY_PATH, HISTORY_IFACE, "DoNotDisturbChanged", [dnd], "(b)")
    end
    if not S["history_on"]:
        return 0
    end
    removed = store.truncate(store.state["max"])
    if len(removed) > 0:
        call forget_icons(removed)
        call schedule_save()
        call emit_log("RowDeleted", removed)
    end
    return 0
end

# Seznam aplikaci pro Nastaveni > Oznameni (jako known_applications xfce4-notifyd); zapis jen u nove aplikace
function apps_path():
    return glib.user_data_dir() + "/luxos/notification-apps"
end

function remember_app(name):
    if name == "" or name in S["known"] or len(S["known"]) >= 200:
        return 0
    end
    S["known"].append(name)
    call lglib.mkdir_p(glib.user_data_dir() + "/luxos")
    return lglib.write_atomic(apps_path(), "\n".join(S["known"]) + "\n")
end

# Vyskakovaci okno listy je otevrene: bubliny pod nim nemaji byt, odpocet stoji a po zavreni bezi znovu cely
function set_hidden(on):
    if on == S["hidden"]:
        return 0
    end
    S["hidden"] = on
    if on:
        call gtk.widget_hide(S["window"])
    else:
        for nid in S["shown"]:
            call start_countdown(S["notes"][nid])
        end
        call update_window()
        call show_waiting()
    end
    call schedule()
    return 0
end

function play_sound(note):
    if S["sound"] and S["sounds_on"] and note["sound"] != "":
        parts = note["sound"].split("\n")
        call lglib.spawn_quiet(["canberra-gtk-play", parts[0], parts[1], "-d", "luxos-notify"])
    end
    return 0
end

function show_waiting():
    while len(S["waiting"]) > 0 and len(S["shown"]) < MAX_VISIBLE and not S["hidden"]:
        nid = S["waiting"].pop(0)
        note = S["notes"][nid]
        slot = None
        for s in S["slots"]:
            if s["nid"] == 0:
                slot = s
                break
            end
        end
        slot["nid"] = nid
        note["slot"] = slot["index"]
        call fill(slot, note)
        call gtk.box_reorder_child(S["column"], slot["card"], 0)
        call gtk.widget_show(slot["card"])
        S["shown"].insert(0, nid)
        call start_countdown(note)
        call play_sound(note)
    end
    call update_window()
    call schedule()
    return 0
end

# Bublina pryc s odjezdem doprava: oznameni uz neexistuje, karta (slot) se uvolni az po animaci. Skryte bubliny
# (Nerusit, vyskakovaci okno listy) a vic nez jedna odjizdejici naraz funguji taky: kazda ma vlastni posun,
# okno vrstvy se posune o nejvetsi a ostatni karty to vyrovnaji okrajem.
function slide_out(note):
    slot = S["slots"][note["slot"]]
    if S["hidden"] or not gtk.widget_get_visible(S["window"]):
        return release_slot(note)
    end
    slot["nid"] = -1
    slot["leave_start"] = glib.monotonic_time()
    note["slot"] = -1
    call S["shown"].remove(note["id"])
    call gtk.widget_hide(slot["close"])
    S["leaving"].append(slot)
    if len(S["shown"]) == 0:
        S["paused"] = False
    end
    if S["slide_timer"] == 0:
        S["slide_timer"] = glib.timeout_add(tokens.MOTION["frame"], slide_step)
    end
    call slide_step()
    return 0
end

function set_margin_end(widget, px):
    unsafe:
        call __lsl_qbe_call2(__lsl_symbol("gtk_widget_set_margin_end"), __lsl_unbox_int(widget), __lsl_unbox_int(px))
    end
    return 0
end

function slide_step():
    now = glib.monotonic_time()
    offsets = {}
    most = 0
    for slot in S["leaving"].copy():
        p = min(1.0, Float(now - slot["leave_start"]) / (SLIDE_MS * 1000.0))
        if p >= 1.0:
            call S["leaving"].remove(slot)
            call free_slot(slot)
            continue
        end
        # zrychleni na odjezdu (ease-in), cela sirka bubliny i s mezerou
        d = Int(p * p * Float(WIDTH + GAP))
        offsets[slot["index"]] = d
        most = max(most, d)
    end
    for slot in S["slots"]:
        call set_margin_end(slot["card"], GAP // 2 + most - offsets.get(slot["index"], 0))
    end
    call layer.set_margin(S["window"], layer.EDGE_RIGHT, GAP // 2 - most)
    if len(S["leaving"]) == 0:
        S["slide_timer"] = 0
        call update_window()
        return False
    end
    return True
end

function free_slot(slot):
    slot["nid"] = 0
    call gtk.widget_hide(slot["card"])
    call gtk.widget_hide(slot["close"])
    call gtk.image_clear(slot["icon"])
    return 0
end

function release_slot(note):
    slot = S["slots"][note["slot"]]
    slot["nid"] = 0
    note["slot"] = -1
    call S["shown"].remove(note["id"])
    call gtk.widget_hide(slot["card"])
    call gtk.widget_hide(slot["close"])
    call gtk.image_clear(slot["icon"])
    if len(S["shown"]) == 0:
        # posledni bublina pryc: mys uz nad nicim neni
        S["paused"] = False
    end
    call update_window()
    return 0
end

function update_window():
    if len(S["leaving"]) > 0:
        return 0
    end
    if len(S["shown"]) == 0 or S["hidden"]:
        call gtk.widget_hide(S["window"])
        return 0
    end
    # sloupec se po zavreni bubliny zmensi (vrstva ma velikost obsahu)
    call gtk.window_resize(S["window"], 1, 1)
    call gtk.widget_show(S["window"])
    return 0
end

# ---- vzhled bubliny -------------------------------------------------------------------------

# Telo smi mit <b>, <i>, <u> (body-markup); ostatni znacky a neplatny zapis jako prosty text
function body_markup(text):
    safe_text = glib.markup_escape(text)
    for entity in ["amp;", "lt;", "gt;", "quot;", "apos;", "#"]:
        safe_text = safe_text.replace("&amp;" + entity, "&" + entity)
    end
    plain = safe_text
    for tag in ["b", "i", "u"]:
        safe_text = safe_text.replace("&lt;" + tag + "&gt;", "<" + tag + ">").replace("&lt;/" + tag + "&gt;", "</" + tag + ">")
        plain = plain.replace("&lt;" + tag + "&gt;", "").replace("&lt;/" + tag + "&gt;", "")
    end
    if not sys.markup_ok(safe_text):
        return plain
    end
    return safe_text
end

function local_file(name):
    if name.startswith("file://"):
        return glib.filename_from_uri(name)
    end
    if name.startswith("/"):
        return name
    end
    return ""
end

# Ikona: image-data, image-path, app_icon, desktop-entry (jak radi specifikace)
function set_icon(image, note):
    if note["image"] != 0:
        call gtk.image_set_from_pixbuf(image, note["image"])
        return True
    end
    for name in [note["image_path"], note["app_icon"], note["desktop"]]:
        if name == "":
            continue
        end
        path = local_file(name)
        if path != "":
            pixbuf = gtk.pixbuf_new_from_file_at_scale(path, ICON, ICON, True)
            if pixbuf != 0:
                call gtk.image_set_from_pixbuf(image, pixbuf)
                call glib.object_unref(pixbuf)
                return True
            end
        elif gtk.icon_theme_has_icon(name):
            call gtk.image_set_from_icon_name(image, name, 6)
            call gtk.image_set_pixel_size(image, ICON)
            return True
        end
    end
    return False
end

function set_expanded(slot, on):
    if on:
        call sys.label_set_lines(slot["summary"], 6)
        call sys.label_set_lines(slot["body"], 40)
    else:
        call sys.label_set_lines(slot["summary"], 1)
        call sys.label_set_lines(slot["body"], 3)
    end
    return 0
end

function fill(slot, note):
    app = note["app"]
    if app == "":
        app = note["desktop"]
    end
    # nazev aplikace jen v tipu a v historii, v bubline je prvni nadpis (navrh 1.1.0)
    call gtk.label_set_text(slot["app"], app)
    call gtk.widget_set_visible(slot["app"], False)
    call gtk.widget_set_tooltip(slot["card"], app)
    call gtk.label_set_text(slot["summary"], note["summary"])
    call gtk.label_set_markup(slot["body"], body_markup(note["body"]))
    call gtk.widget_set_visible(slot["body"], note["body"] != "")
    call gtk.image_clear(slot["icon"])
    call gtk.widget_set_visible(slot["icon"], set_icon(slot["icon"], note))
    call set_expanded(slot, note["expanded"])
    call gtk.widget_set_class(slot["box"], "critical", note["urgency"] >= 2)
    # tlacitka akci s popisem (i "default": aplikace ho tak ukazuji, klik na bublinu ho vyvola take)
    # hlavni akce modre a vpravo ("default", jinak prvni s popisem), ostatni sede pred ni
    main_key = ""
    for a in note["actions"]:
        if a[1] != "" and (main_key == "" or a[0] == "default"):
            main_key = a[0]
        end
    end
    # bez popisu se nezobrazuji; hlavni se vejde vzdy (nejvys MAX_ACTIONS tlacitek)
    ordered = []
    for a in note["actions"]:
        if a[0] != main_key and a[1] != "" and len(ordered) < MAX_ACTIONS - 1:
            ordered.append(a)
        end
    end
    for a in note["actions"]:
        if a[0] == main_key:
            ordered.append(a)
        end
    end
    shown = 0
    for a in ordered:
        if a[1] != "" and shown < MAX_ACTIONS:
            button = slot["buttons"][shown]
            call gtk.button_set_label(button, a[1])
            slot["keys"][shown] = a[0]
            call gtk.widget_set_class(button, "lx-accent", a[0] == main_key)
            call gtk.widget_set_class(button, "lx-button", a[0] != main_key)
            call gtk.widget_show(button)
            shown += 1
        end
    end
    index = shown
    while index < MAX_ACTIONS:
        call gtk.widget_hide(slot["buttons"][index])
        index += 1
    end
    call gtk.widget_set_visible(slot["actions"], shown > 0)
    return 0
end

# Prechod mysi na vnoreny widget (tlacitko) neni odchod z bubliny
function on_enter(slot, event, widget):
    if slot["nid"] > 0 and not sys.crossing_inferior(event):
        call gtk.widget_show(slot["close"])
        call pause(True)
    end
    return False
end

function on_leave(slot, event, widget):
    if not sys.crossing_inferior(event):
        call gtk.widget_hide(slot["close"])
        call pause(False)
    end
    return False
end

function on_press(slot, event, widget):
    nid = slot["nid"]
    if nid <= 0:
        return True
    end
    note = S["notes"][nid]
    if gtk.event_button(event) != 1:
        call close(nid, DISMISSED)
        return True
    end
    if not note["expanded"] and (sys.label_cut(slot["summary"]) or sys.label_cut(slot["body"])):
        note["expanded"] = True
        call set_expanded(slot, True)
        call gtk.window_resize(S["window"], 1, 1)
        return True
    end
    call invoke(nid, "default")
    return True
end

function invoke(nid, key):
    note = S["notes"][nid]
    if key == "default" and not has_default(note):
        call close(nid, DISMISSED)
        return 0
    end
    call emit(FDO_PATH, FDO, "ActionInvoked", [nid, key], "(us)")
    if not note["resident"]:
        call close(nid, DISMISSED)
    end
    return 0
end

function on_action(bound, button):
    slot = S["slots"][bound[0]]
    if slot["nid"] > 0:
        call invoke(slot["nid"], slot["keys"][bound[1]])
    end
    return 0
end

function on_close_clicked(slot, button):
    if slot["nid"] > 0:
        call close(slot["nid"], DISMISSED)
    end
    return 0
end

function label(css_class, xalign):
    l = gtk.label_new("")
    call gtk.widget_add_class(l, css_class)
    call gtk.label_set_xalign(l, xalign)
    call gtk.label_set_line_wrap(l, True)
    # PANGO_WRAP_WORD_CHAR, PANGO_ELLIPSIZE_END
    call sys.label_set_wrap_mode(l, 2)
    call gtk.label_set_ellipsize(l, 3)
    call gtk.label_set_max_width_chars(l, 1)
    call gtk.widget_set_hexpand(l, True)
    return l
end

# Bubliny jsou pevna sada widgetu (MAX_VISIBLE), jen se plni: pamet ani obsluhy nerostou s poctem oznameni
function new_slot(index):
    slot = {"index": index, "nid": 0, "keys": ["", "", ""], "buttons": []}
    card = gtk.event_box_new()
    # vlastni GdkWindow: okna tlacitek jsou pod nim, prechod na ne je pak "inferior"
    call gtk.event_box_set_visible_window(card, True)
    # GDK_ENTER_NOTIFY_MASK | GDK_LEAVE_NOTIFY_MASK | GDK_BUTTON_PRESS_MASK
    call gtk.widget_add_events(card, 4096 + 8192 + 256)
    call gtk.widget_set_margin(card, GAP // 2)
    # u praveho okraje okna: pri odjezdu jine bubliny se okno posune doprava a tahle to vyrovna okrajem
    call gtk.widget_set_halign(card, gtk.ALIGN_END)
    overlay = gtk.overlay_new()
    call gtk.container_add(card, overlay)
    box = gtk.box_new(gtk.VERTICAL, 8)
    call gtk.widget_add_class(box, "lx-notification")
    call gtk.widget_set_size_request(box, WIDTH, -1)
    call gtk.container_add(overlay, box)
    row = gtk.box_new(gtk.HORIZONTAL, 10)
    call gtk.box_pack_start(box, row, False, False, 0)
    slot["icon"] = gtk.image_new_from_icon_name("", 6)
    call gtk.widget_set_valign(slot["icon"], gtk.ALIGN_START)
    call gtk.widget_set_size_request(slot["icon"], ICON, ICON)
    call gtk.box_pack_start(row, slot["icon"], False, False, 0)
    texts = gtk.box_new(gtk.VERTICAL, 2)
    call gtk.box_pack_start(row, texts, True, True, 0)
    slot["app"] = label("lx-dim", 0.0)
    call sys.label_set_lines(slot["app"], 1)
    slot["summary"] = label("lx-summary", 0.0)
    slot["body"] = label("lx-body", 0.0)
    for l in [slot["app"], slot["summary"], slot["body"]]:
        call gtk.box_pack_start(texts, l, False, False, 0)
    end
    slot["actions"] = gtk.box_new(gtk.HORIZONTAL, 6)
    call gtk.widget_set_halign(slot["actions"], gtk.ALIGN_END)
    call gtk.box_pack_start(box, slot["actions"], False, False, 0)
    i = 0
    while i < MAX_ACTIONS:
        b = gtk.button_new("")
        call gtk.widget_add_class(b, "lx-button")
        call gtk.widget_set_can_focus(b, False)
        call lglib.connect_data(b, "clicked", 0, on_action, [index, i])
        call gtk.box_pack_start(slot["actions"], b, False, False, 0)
        slot["buttons"].append(b)
        i += 1
    end
    close_button = gtk.button_new("×")
    call gtk.widget_add_class(close_button, "lx-close")
    call gtk.widget_set_can_focus(close_button, False)
    call gtk.widget_set_halign(close_button, gtk.ALIGN_START)
    call gtk.widget_set_valign(close_button, gtk.ALIGN_START)
    call gtk.widget_set_tooltip(close_button, i18n.T("Close"))
    call gtk.overlay_add_overlay(overlay, close_button)
    call lglib.connect_data(close_button, "clicked", 0, on_close_clicked, slot)
    call lglib.connect_data(card, "enter-notify-event", 1, on_enter, slot)
    call lglib.connect_data(card, "leave-notify-event", 1, on_leave, slot)
    call lglib.connect_data(card, "button-press-event", 1, on_press, slot)
    slot["card"] = card
    slot["box"] = box
    slot["close"] = close_button
    call gtk.widget_show_all(card)
    call gtk.widget_hide(close_button)
    call gtk.widget_hide(card)
    return slot
end

CSS = ".lx-notification.critical { border-color: @lx_error; }\n"
CSS = CSS + ".lx-notification button.lx-button, .lx-notification button.lx-accent { min-height: 28px; min-width: 64px; padding: 0 14px; }\n"
CSS = CSS + ".lx-notification button.lx-accent label { font-weight: 600; }\n"
CSS = CSS + "button.lx-close { margin: 4px; }\n"

function load_css():
    dark = lglib.read_text(config_dir() + "/appearance").strip() == "dark"
    if S["css"] != 0:
        if dark == S["dark"]:
            return 0
        end
        call gtk.css_remove(S["css"])
    end
    S["dark"] = dark
    S["css"] = gtk.css_load(tokens.gtk3_css(dark, material.compositor_blur()) + CSS)
    return 0
end

function on_appearance(path, event, other):
    call load_css()
    return 0
end

function build_window():
    window = gtk.window_new("luxos-notify")
    call layer.init_for_window(window)
    call layer.set_namespace(window, tokens.namespace("luxos-notify", "toast"))
    call layer.set_layer(window, layer.LAYER_OVERLAY)
    call layer.set_anchors(window, [layer.EDGE_TOP, layer.EDGE_RIGHT])
    # vyhradni zona 0: kompozitor bubliny posune pod listu
    call layer.set_margin(window, layer.EDGE_TOP, GAP // 2)
    call layer.set_margin(window, layer.EDGE_RIGHT, GAP // 2)
    call layer.set_keyboard_mode(window, layer.KEYBOARD_NONE)
    call gtk.window_set_rgba(window)
    call gtk.widget_add_class(window, "lx")
    column = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.container_add(window, column)
    S["window"] = window
    S["column"] = column
    index = 0
    while index < MAX_VISIBLE:
        slot = new_slot(index)
        S["slots"].append(slot)
        call gtk.box_pack_start(column, slot["card"], False, False, 0)
        index += 1
    end
    call gtk.widget_show(column)
    call lglib.connect_data(column, "size-allocate", 1, on_column_allocated, 0)
    # bubliny na hlavnim monitoru luxwm (jinak vybere kompozitor)
    call primary.follow(on_primary)
    return 0
end

# Vstupni oblast = bubliny (mezery mezi nimi propousti kliky); kompozitor pod kazdou da material toast. Karta ma
# vlastni GdkWindow, jeji alokace je v souradnicich okna. Nastavuje se az po rozlozeni (GDK ji posle s dalsim
# commitem plochy, proto i prekresleni).
function on_column_allocated(unused, allocation, widget):
    # pri odjezdu bubliny hned (material kompozitoru pod kartou jede ve stejnem snimku, ne o snimek pozdeji)
    if len(S["leaving"]) > 0:
        call update_input(0)
        return 0
    end
    if not S.get("input_pending", False):
        S["input_pending"] = True
        call lglib.idle_add_data(update_input, 0)
    end
    return 0
end

function update_input(unused):
    S["input_pending"] = False
    rects = []
    for slot in S["slots"]:
        if gtk.widget_get_visible(slot["card"]):
            rects.append(gtk.widget_get_allocation(slot["card"]))
        end
    end
    if len(rects) > 0 and rects != S.get("input", None):
        S["input"] = rects
        call luxos_gtk.widget_input_rects(S["window"], rects)
        call gtk.widget_queue_draw(S["window"])
    end
    return False
end

function on_primary(monitor):
    call layer.set_monitor(S["window"], monitor)
    return 0
end

function main():
    call glib.set_prgname("luxos-notify")
    call gtk.init()
    call material.grayscale_text()
    if not layer.is_supported():
        call glib.report("luxos-notify: compositor without layer-shell\n")
        exit(1)
    end
    try:
        S["bus"] = gio.session_bus()
    else:
        call glib.report("luxos-notify: " + String(last_error()) + "\n")
        exit(1)
    end
    S["tz"] = sys.local_tz()
    S["dnd"] = load_config()
    S["known"] = [a for a in lglib.read_text(apps_path()).split("\n") if a != ""]
    S["sound"] = glib.find_program_in_path("canberra-gtk-play") != ""
    S["timer_record"] = glib.record_new(on_timer, 0)
    S["save_record"] = glib.record_new(on_save, 0)
    call store.load(glib.user_data_dir() + "/luxos")
    call load_css()
    safe:
        S["appearance"] = gio.file_monitor(config_dir() + "/appearance", on_appearance)
    end
    safe:
        call lglib.mkdir_p(config_dir())
        S["config"] = gio.file_monitor(conf_path(), on_config)
    end
    call build_window()
    call sys.register_raw(S["bus"], FDO_PATH, FDO_XML, on_fdo)
    call gio.register_object(S["bus"], HISTORY_PATH, HISTORY_XML, on_history)
    call gio.register_object(S["bus"], LOG_PATH, LOG_XML, on_log)
    if not request_name(FDO):
        call glib.report("luxos-notify: another notification server owns " + FDO + "\n")
        exit(1)
    end
    # historie i pod jmenem xfce4-notifyd (stavajici okna listy); jmeno muze drzet jiny proces
    call request_name(LOG_NAME)
    call gtk.main()
    return 0
end

call main()
