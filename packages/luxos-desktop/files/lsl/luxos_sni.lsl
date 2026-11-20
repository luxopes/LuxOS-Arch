# lsl: internal-abi
# LuxOS - oznamovaci oblast horni listy na Waylandu: StatusNotifierItem (Freedesktop/KDE) misto systray XEmbed.
# Lista je zaroven StatusNotifierWatcher (org.kde.StatusNotifierWatcher, kdyz ho uz nedrzi nekdo jiny) i host:
# aplikace (nm-applet --indicator, blueman, Electron, Telegram...) se registruji u ni a jejich ikony jsou v liste.
# Klik: levy Activate (nebo nabidka u ItemIsMenu), prostredni SecondaryActivate, pravy nabidka com.canonical.dbusmenu
# (jinak ContextMenu). Zmeny ikony chodi signaly polozky (NewIcon, NewStatus...), nic se neobnovuje casovacem.
#
#   sni.start(trace)     prevzit jmeno watcheru (nebo se prihlasit k cizimu) na sbernici relace
#   sni.attach(box)      ikony do boxu listy (kazdy monitor ma svuj), sni.detach(box) pri odpojeni monitoru
load glib, gtk, gio, cairo
load luxos_glib as lglib
load luxos_gio, gio as lgio

WATCHER = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
ITEM = "org.kde.StatusNotifierItem"
MENU = "com.canonical.dbusmenu"
PROPS = "org.freedesktop.DBus.Properties"
WATCHER_XML = ("<node><interface name='org.kde.StatusNotifierWatcher'>"
    + "<method name='RegisterStatusNotifierItem'><arg name='service' type='s' direction='in'/></method>"
    + "<method name='RegisterStatusNotifierHost'><arg name='service' type='s' direction='in'/></method>"
    + "<property name='RegisteredStatusNotifierItems' type='as' access='read'/>"
    + "<property name='IsStatusNotifierHostRegistered' type='b' access='read'/>"
    + "<property name='ProtocolVersion' type='i' access='read'/>"
    + "<signal name='StatusNotifierItemRegistered'><arg type='s'/></signal>"
    + "<signal name='StatusNotifierItemUnregistered'><arg type='s'/></signal>"
    + "<signal name='StatusNotifierHostRegistered'/>"
    + "</interface></node>")
SIZE = 16

S = {"bus": 0, "own": False, "items": {}, "order": [], "boxes": [], "menu": 0, "theme_paths": [], "trace": None}

function trace(message):
    if S["trace"] != None:
        call S["trace"](message)
    end
    return 0
end

function ptr(value):
    unsafe:
        return __lsl_unbox_int(value)
    end
end

function flag(value):
    if value:
        return 1
    end
    return 0
end

function log(message):
    return eprint("luxos-bar: tray: " + message)
end

# "jmeno", "jmeno/cesta" nebo jen "/cesta" (pak plati odesilatel) -> [jmeno, cesta]
function split_service(service, sender):
    if service.startswith("/"):
        return [sender, service]
    end
    cut = service.find("/")
    if cut > 0:
        return [service[0:cut], service[cut:]]
    end
    return [service, "/StatusNotifierItem"]
end

# ---- watcher -------------------------------------------------------------------------------------

function on_watcher_call(sender, path, interface, method, values, invocation):
    if method == "RegisterStatusNotifierItem":
        target = split_service(values[0], sender)
        call add_item(target[0], target[1])
        call gio.return_value(invocation, [], "")
    elif method == "RegisterStatusNotifierHost":
        call gio.return_value(invocation, [], "")
        call gio.emit_values(S["bus"], WATCHER_PATH, WATCHER, "StatusNotifierHostRegistered", [], "")
    elif method == "Get":
        call gio.return_value(invocation, [watcher_property(values[1])], "(v)")
    elif method == "GetAll":
        all = {}
        for name in ["RegisteredStatusNotifierItems", "IsStatusNotifierHostRegistered", "ProtocolVersion"]:
            all[name] = watcher_property(name)
        end
        call gio.return_value(invocation, [all], "(a{sv})")
    else:
        call gio.return_value(invocation, [], "")
    end
    return 0
end

function watcher_property(name):
    if name == "RegisteredStatusNotifierItems":
        return ["as", List(S["order"])]
    elif name == "IsStatusNotifierHostRegistered":
        return ["b", True]
    end
    return ["i", 0]
end

# Jmeno watcheru: vlastni (zaregistrovany objekt), nebo cizi - pak jen host
function on_watcher_owner(unused, name, owner):
    unsafe:
        own = glib.from_c(__lsl_qbe_call1(__lsl_symbol("g_dbus_connection_get_unique_name"), ptr(S["bus"])))
    end
    S["own"] = owner == own
    call trace("tray watcher own=" + String(S["own"]))
    if S["own"]:
        return 0
    end
    call lgio.call_async(S["bus"], WATCHER, WATCHER_PATH, WATCHER, "RegisterStatusNotifierHost",
                         ["org.kde.StatusNotifierHost-" + String(glib.getpid())], "(s)", 5000, on_ignored, 0)
    call lgio.call_async(S["bus"], WATCHER, WATCHER_PATH, PROPS, "Get", [WATCHER, "RegisteredStatusNotifierItems"], "(ss)",
                         5000, on_foreign_items, 0)
    return 0
end

function on_watcher_lost(unused, name):
    return 0
end

function on_ignored(unused, values, error):
    return 0
end

function on_foreign_items(unused, values, error):
    if values == None:
        return 0
    end
    for service in values[0]:
        target = split_service(service, "")
        call add_item(target[0], target[1])
    end
    return 0
end

function on_foreign_registered(unused, sender, path, interface, signal, values):
    if S["own"] or len(values) == 0:
        return 0
    end
    target = split_service(values[0], "")
    call add_item(target[0], target[1])
    return 0
end

# Aplikace skoncila (jeji jmeno na sbernici zmizelo): ikona pryc
function on_name_owner(unused, sender, path, interface, signal, values):
    if len(values) < 3 or values[2] != "":
        return 0
    end
    for key in List(S["order"]):
        if S["items"][key]["name"] == values[0]:
            call remove_item(key)
        end
    end
    return 0
end

# ---- polozky ------------------------------------------------------------------------------------------

function add_item(name, path):
    key = name + path
    if key in S["items"] or name == "":
        return 0
    end
    item = {"key": key, "name": name, "path": path, "props": {}, "buttons": {}}
    item["sub"] = lgio.subscribe_data(S["bus"], name, ITEM, "", path, "", lgio.SIGNAL_NONE, on_item_signal, key)
    S["items"][key] = item
    S["order"].append(key)
    call refresh_item(key)
    if S["own"]:
        call gio.emit_values(S["bus"], WATCHER_PATH, WATCHER, "StatusNotifierItemRegistered", [key], "(s)")
    end
    return 0
end

function remove_item(key):
    item = S["items"].pop(key)
    call S["order"].remove(key)
    call trace("tray removed " + item["name"])
    call gio.unsubscribe(S["bus"], item["sub"])
    for pair in item["buttons"].values():
        call gtk.widget_destroy(pair[0])
    end
    if S["own"]:
        call gio.emit_values(S["bus"], WATCHER_PATH, WATCHER, "StatusNotifierItemUnregistered", [key], "(s)")
    end
    return 0
end

function on_item_signal(key, sender, path, interface, signal, values):
    call refresh_item(key)
    return 0
end

function refresh_item(key):
    item = S["items"].get(key)
    if item == None:
        return 0
    end
    call lgio.call_async(S["bus"], item["name"], item["path"], PROPS, "GetAll", [ITEM], "(s)", 5000, on_item_props, key)
    return 0
end

function on_item_props(key, values, error):
    item = S["items"].get(key)
    if item == None:
        return 0
    end
    if values == None:
        call log(item["name"] + ": " + error)
        return 0
    end
    item["props"] = values[0]
    for box in S["boxes"]:
        call render(item, box)
    end
    call trace("tray " + item["name"] + " " + item["props"].get("IconName", "") + " " + item["props"].get("Status", ""))
    return 0
end

# Nejmensi pixmapa aspon SIZE px (jinak nejvetsi) jako cairo surface; ARGB32 v sitovem poradi bajtu
function pixmap_surface(pixmaps):
    best = None
    for p in pixmaps:
        if len(p) < 3 or p[0] <= 0 or p[1] <= 0 or len(p[2]) < p[0] * p[1] * 4:
            continue
        end
        if best == None or (best[0] < SIZE and p[0] > best[0]) or (p[0] >= SIZE and p[0] < best[0]):
            best = p
        end
    end
    if best == None:
        return 0
    end
    w = best[0]
    h = best[1]
    data = best[2]
    IntArray(pixels) = IntArray()
    for i in range(w * h):
        o = i * 4
        pixels.append((data[o] << 24) | (data[o + 1] << 16) | (data[o + 2] << 8) | data[o + 3])
    end
    return cairo.intarray_to_surface(pixels, w, h)
end

function render(item, box):
    p = item["props"]
    pair = item["buttons"].get(box)
    if pair == None:
        button = gtk.button_new_empty()
        call gtk.widget_add_class(button, "lb")
        call gtk.widget_set_can_focus(button, False)
        image = gtk.image_new_from_icon_name("image-missing", 1)
        call gtk.image_set_pixel_size(image, SIZE)
        call gtk.container_add(button, image)
        call lglib.connect_data(button, "button-press-event", 1, on_press, item["key"])
        call gtk.box_pack_start(box, button, False, False, 0)
        call gtk.widget_show_all(button)
        pair = [button, image]
        item["buttons"][box] = pair
    end
    button = pair[0]
    image = pair[1]
    theme_path = p.get("IconThemePath", "")
    if theme_path != "" and theme_path not in S["theme_paths"]:
        S["theme_paths"].append(theme_path)
        unsafe:
            call __lsl_qbe_call2(__lsl_symbol("gtk_icon_theme_append_search_path"), __lsl_qbe_call0(__lsl_symbol("gtk_icon_theme_get_default")), glib.cstr(theme_path))
        end
    end
    icon = p.get("IconName", "")
    if p.get("Status", "") == "NeedsAttention" and p.get("AttentionIconName", "") != "":
        icon = p["AttentionIconName"]
    end
    surface = 0
    if icon == "":
        surface = pixmap_surface(p.get("IconPixmap", []))
    end
    if surface != 0:
        unsafe:
            call __lsl_qbe_call2(__lsl_symbol("gtk_image_set_from_surface"), ptr(image), ptr(surface))
        end
        call cairo.surface_destroy(surface)
    else:
        if icon == "":
            icon = "application-x-executable-symbolic"
        end
        call gtk.image_set_from_icon_name(image, icon, 1)
        call gtk.image_set_pixel_size(image, SIZE)
    end
    tip = p.get("Title", "")
    tooltip = p.get("ToolTip", [])
    if len(tooltip) >= 3 and tooltip[2] != "":
        tip = tooltip[2]
    end
    call gtk.widget_set_tooltip(button, tip)
    call gtk.widget_set_visible(button, p.get("Status", "Active") != "Passive")
    return 0
end

# ---- kliky a nabidky ---------------------------------------------------------------------------------

function on_press(key, event, widget):
    item = S["items"].get(key)
    if item == None:
        return False
    end
    unsafe:
        # jen GDK_BUTTON_PRESS (4), ne dvojklik
        if __lsl_qbe_s32(__lsl_qbe_load32(ptr(event))) != 4:
            return True
        end
    end
    b = gtk.event_button(event)
    p = item["props"]
    menu = p.get("Menu", "")
    if (b == 1 and p.get("ItemIsMenu", False) and menu != "") or (b == 3 and menu != "" and menu != "/"):
        call show_menu(item, widget, event)
    elif b == 1:
        call lgio.call_async(S["bus"], item["name"], item["path"], ITEM, "Activate", [0, 0], "(ii)", 5000, on_activated,
                             [key, widget, copy_event(event)])
    elif b == 2:
        call lgio.call_async(S["bus"], item["name"], item["path"], ITEM, "SecondaryActivate", [0, 0], "(ii)", 5000, on_ignored, 0)
    elif b == 3:
        call lgio.call_async(S["bus"], item["name"], item["path"], ITEM, "ContextMenu", [0, 0], "(ii)", 5000, on_ignored, 0)
    end
    return True
end

# Aplikace bez Activate (jen nabidka): levy klik ukaze nabidku
function on_activated(ctx, values, error):
    item = S["items"].get(ctx[0])
    if values == None and item != None and item["props"].get("Menu", "") != "":
        call show_menu(item, ctx[1], ctx[2])
    end
    call free_event(ctx[2])
    return 0
end

function copy_event(event):
    unsafe:
        return __lsl_qbe_call1(__lsl_symbol("gdk_event_copy"), ptr(event))
    end
end

function free_event(event):
    unsafe:
        call __lsl_qbe_call1(__lsl_symbol("gdk_event_free"), ptr(event))
    end
    return 0
end

# Nabidka dbusmenu: AboutToShow, pak GetLayout; udalost kliku se kopiruje (xdg_popup potrebuje serial vstupu)
function show_menu(item, widget, event):
    call lgio.call_async(S["bus"], item["name"], item["props"]["Menu"], MENU, "AboutToShow", [0], "(i)", 2000, on_ignored, 0)
    call lgio.call_async(S["bus"], item["name"], item["props"]["Menu"], MENU, "GetLayout", [0, -1, []], "(iias)", 5000,
                         on_layout, [item["key"], widget, copy_event(event)])
    return 0
end

function on_layout(ctx, values, error):
    item = S["items"].get(ctx[0])
    if values == None or item == None:
        call free_event(ctx[2])
        return 0
    end
    if S["menu"] != 0:
        call gtk.widget_destroy(S["menu"])
    end
    S["menu"] = build_menu(item, values[1])
    call gtk.widget_show_all(S["menu"])
    unsafe:
        # GDK_GRAVITY_SOUTH_WEST 7 / NORTH_WEST 1: pod ikonou
        call __lsl_qbe_call5(__lsl_symbol("gtk_menu_popup_at_widget"), ptr(S["menu"]), ptr(ctx[1]), 7, 1, ptr(ctx[2]))
    end
    call free_event(ctx[2])
    return 0
end

# Uzel (id, vlastnosti, deti) -> GtkMenu
function build_menu(item, node):
    unsafe:
        menu = __lsl_qbe_call0(__lsl_symbol("gtk_menu_new"))
    end
    for child in node[2]:
        id = child[0]
        p = child[1]
        if not p.get("visible", True):
            continue
        end
        if p.get("type", "") == "separator":
            unsafe:
                entry = __lsl_qbe_call0(__lsl_symbol("gtk_separator_menu_item_new"))
            end
        else:
            text = p.get("label", "")
            toggle = p.get("toggle-type", "")
            unsafe:
                if toggle == "checkmark" or toggle == "radio":
                    entry = __lsl_qbe_call1(__lsl_symbol("gtk_check_menu_item_new_with_mnemonic"), glib.cstr(text))
                    call __lsl_qbe_call2(__lsl_symbol("gtk_check_menu_item_set_draw_as_radio"), entry, flag(toggle == "radio"))
                    call __lsl_qbe_call2(__lsl_symbol("gtk_check_menu_item_set_active"), entry, flag(p.get("toggle-state", 0) == 1))
                else:
                    entry = __lsl_qbe_call1(__lsl_symbol("gtk_menu_item_new_with_mnemonic"), glib.cstr(text))
                end
                call __lsl_qbe_call2(__lsl_symbol("gtk_widget_set_sensitive"), entry, flag(p.get("enabled", True)))
                if p.get("children-display", "") == "submenu" and len(child[2]) > 0:
                    call __lsl_qbe_call2(__lsl_symbol("gtk_menu_item_set_submenu"), entry, ptr(build_menu(item, child)))
                else:
                    call lglib.connect_data(entry, "activate", 0, on_menu_activate, [item["key"], id])
                end
            end
        end
        unsafe:
            call __lsl_qbe_call2(__lsl_symbol("gtk_menu_shell_append"), menu, entry)
        end
    end
    return menu
end

function on_menu_activate(pair, entry):
    item = S["items"].get(pair[0])
    if item == None:
        return 0
    end
    call lgio.call_async(S["bus"], item["name"], item["props"]["Menu"], MENU, "Event", [pair[1], "clicked", ["i", 0], 0],
                         "(isvu)", 5000, on_ignored, 0)
    return 0
end

# ---- lista ----------------------------------------------------------------------------------------------

function attach(box):
    if box in S["boxes"]:
        return 0
    end
    S["boxes"].append(box)
    for key in S["order"]:
        call render(S["items"][key], box)
    end
    return 0
end

function detach(box):
    if box not in S["boxes"]:
        return 0
    end
    call S["boxes"].remove(box)
    for item in S["items"].values():
        if box in item["buttons"]:
            call item["buttons"].pop(box)
        end
    end
    return 0
end

function start(trace_fn):
    S["trace"] = trace_fn
    bus = 0
    safe:
        bus = gio.session_bus()
    end
    if bus == 0 or bus == None:
        return 0
    end
    S["bus"] = bus
    try:
        call gio.register_object(bus, WATCHER_PATH, WATCHER_XML, on_watcher_call)
    else:
        call log("watcher object: " + String(last_error()))
    end
    call gio.own_name(bus, WATCHER)
    call gio.own_name(bus, "org.kde.StatusNotifierHost-" + String(glib.getpid()))
    call lgio.watch_name_data(bus, WATCHER, on_watcher_owner, on_watcher_lost, 0)
    call lgio.subscribe_data(bus, "", WATCHER, "StatusNotifierItemRegistered", WATCHER_PATH, "", lgio.SIGNAL_NONE,
                             on_foreign_registered, 0)
    call lgio.subscribe_data(bus, "org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged", "/org/freedesktop/DBus",
                             "", lgio.SIGNAL_NONE, on_name_owner, 0)
    return 0
end
