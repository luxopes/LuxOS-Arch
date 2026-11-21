# LuxOS - Nastaveni > Bluetooth (drive luxos-bluetooth): zapnuti, sparovana zarizeni a pripojeni noveho jednim klikem.
#
# Pracuje primo s BlueZ pres D-Bus. Pri zobrazene strance hleda zarizeni v okoli; "Pripojit" u noveho zarizeni
# ho sparuje, nastavi jako duveryhodne a pripoji. Kody pri parovani resi agent BlueZ (luxos_bt_agent, stejny
# jako v luxos-hub). Pri zobrazene strance a zapnutem Bluetooth je pocitac viditelny pro ostatni zarizeni (jako
# macOS/GNOME): viditelnost zapina jen tato stranka a pri odchodu ze stranky nebo zavreni okna ji vypne (jen kdyz
# ji zapla ona); DiscoverableTimeout 180 s - kdyz okno spadne, BlueZ ji vypne sam. Jmeno pocitace viditelne pro
# ostatni zarizeni = Alias adapteru (prazdny vrati jmeno systemu); zapis povoluje politika D-Bus BlueZ, polkit ne.
# GIO respektuje DBUS_SYSTEM_BUS_ADDRESS: testy okno pousti nad soukromou sbernici s falesnym BlueZ.
load luxos_glib, glib as glib
load luxos_gtk, gtk as gtk
load luxos_gio, gio as gio
load luxos_i18n as i18n
load luxos_bt_agent as agent
load luxos_text as text
load luxos_settings_ui as ui
load json

BLUEZ = "org.bluez"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
CSS = ".bt-list row { min-height: 28px; padding: 8px 16px; }\n.bt-name { font-weight: 600; }\n.bt-sub { font-size: 11px; opacity: 0.6; }\n.bt-empty { opacity: 0.6; padding: 18px; }\n.bt-hint { margin: 8px 16px 0 16px; }\n"

VISIBLE_TIMEOUT = 180   # s, BlueZ viditelnost vypne sam (pad okna); zobrazena stranka ji obnovuje
VISIBLE_REFRESH = 60    # s, jak casto stranka obnovi DiscoverableTimeout (BlueZ znovu spusti odpocet)
SCAN_IDLE = 120         # s, po jak dlouhe dobe v pozadi okno prestane hledat zarizeni
ALIAS_MAX = 248         # nejdelsi jmeno zarizeni v Bluetooth (HCI local name, bajty UTF-8)
# Vlastnosti Device1, ktere okno nezobrazuje a ktere BlueZ pri hledani meni porad dokola
IGNORED_PROPS = ["RSSI", "TxPower", "ManufacturerData", "ServiceData", "AdvertisingData", "AdvertisingFlags"]
KIND = {"audio-headset": "Headphones", "audio-headphones": "Headphones", "audio-card": "Speaker",
    "input-mouse": "Mouse", "input-keyboard": "Keyboard", "input-gaming": "Game controller",
    "input-tablet": "Tablet", "phone": "Phone", "computer": "Computer"}

bz = {"bus": 0, "objects": {}, "reloads": 0}
bt = {"window": 0, "page": 0, "css": 0, "power": 0, "hint": 0, "name_group": 0, "name_label": 0, "name_sub": 0, "lists": {}, "heads": {},
      "scan_spinner": 0, "busy": {}, "apath": "", "hidden": True, "pending": True, "syncing": False,
      "visible_ours": False, "visible_busy": False, "visible_failed": False, "saved_timeout": None,
      "visible_timer": 0, "scan_paused": False, "scan_pause_timer": 0, "active": None}

# ---- jmeno pocitace ---------------------------------------------------------------------------------------

function clean_alias(name):
    if name == None:
        return ""
    end
    return name.strip()
end

# Proc jmeno nejde pouzit ("" = lze); prazdne jmeno = vychozi jmeno systemu
function alias_problem(name):
    size = 0
    for ch in name:
        code = ord(ch)
        if code < 32 or code == 127:
            return i18n.T("The name cannot contain line breaks or control characters.")
        end
        size += text.utf8_length(ch)
    end
    if size > ALIAS_MAX:
        return i18n.TF("The name is too long (at most %d bytes).", [ALIAS_MAX])
    end
    return ""
end

# ---- BlueZ (ObjectManager, Adapter1, Device1) ---------------------------------------------------------------

function reload():
    bz["reloads"] += 1
    objects = {}
    if bz["bus"] != 0:
        try:
            objects = gio.call_values(bz["bus"], BLUEZ, "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects", [], "", 3000)[0]
        else:
            objects = {}
        end
    end
    bz["objects"] = objects
    call schedule_refresh()
    return 0
end

function on_objects(sender, path, interface, signal, values):
    call reload()
    return 0
end

# Pri hledani posila BlueZ silu signalu (RSSI) kazdeho zarizeni v okoli nekolikrat za sekundu; okno ji
# nezobrazuje - kvuli ni nenacitat vsechno znovu a neprekreslovat
function on_props(sender, path, interface, signal, values):
    changed = values[1]
    if values[0] == DEVICE and len(changed) > 0 and len(values[2]) == 0:
        shown = [k for k in changed.keys() if not (k in IGNORED_PROPS)]
        if len(shown) == 0:
            return 0
        end
    end
    call reload()
    return 0
end

function props_of(path, interface):
    return bz["objects"].get(path, {}).get(interface, {})
end

# Prvni adapter (hci0); poradi slovniku z D-Bus neni zarucene
function adapter_path():
    for path in sorted(bz["objects"].keys()):
        if ADAPTER in bz["objects"][path]:
            return path
        end
    end
    return ""
end

function adapter_props():
    if bt["apath"] == "":
        return {}
    end
    return props_of(bt["apath"], ADAPTER)
end

function name_of(props):
    for key in ["Alias", "Name", "Address"]:
        if props.get(key, "") != "" and props.get(key) != None:
            return String(props[key])
        end
    end
    return ""
end

# Zarizeni adapteru s nazvem nebo sparovana; pripojena prvni, pak podle jmena
function devices(apath):
    keyed = []
    for path in bz["objects"].keys():
        d = props_of(path, DEVICE)
        if len(d) > 0 and d.get("Adapter") == apath and (d.get("Name", "") != "" or d.get("Paired") == True):
            first = "1"
            if d.get("Connected") == True:
                first = "0"
            end
            keyed.append(first + String(d.get("Alias", "")).lower() + "\t" + path)
        end
    end
    out = []
    for key in sorted(keyed):
        out.append(key[key.find("\t") + 1:])
    end
    return out
end

function set_prop(path, interface, name, signature, value, done, data):
    call gio.call_async(bz["bus"], BLUEZ, path, "org.freedesktop.DBus.Properties", "Set", [interface, name, [signature, value]], "(ssv)", 10000, done, data)
end

function set_prop_sync(name, signature, value):
    try:
        call gio.call_values(bz["bus"], BLUEZ, bt["apath"], "org.freedesktop.DBus.Properties", "Set", [ADAPTER, name, [signature, value]], "(ssv)", 2000)
    else:
        return False
    end
    return True
end

function ignore_reply(data, reply, error):
    return 0
end

# Text chyby BlueZ bez prefixu GDBus ("GDBus.Error:org.bluez.Error.Failed: Page Timeout" -> "Page Timeout")
function error_text(error):
    parts = error.split(":")
    return parts[len(parts) - 1].strip()
end

# ---- okno ---------------------------------------------------------------------------------------------------

function label(value, css):
    l = gtk.label_new(value)
    call gtk.label_set_xalign(l, 0)
    if css != "":
        call gtk.widget_add_class(l, css)
    end
    return l
end

function group():
    lb = gtk.list_box_new()
    call gtk.list_box_set_selection_mode(lb, 0)
    call gtk.widget_add_class(lb, "group")
    call gtk.widget_add_class(lb, "bt-list")
    return lb
end

function device_row(path, props):
    paired = props.get("Paired") == True
    connected = props.get("Connected") == True
    icon = String(props.get("Icon", ""))
    if icon == "" or icon == "None":
        icon = "bluetooth"
    end
    box = gtk.box_new(gtk.HORIZONTAL, 12)
    call gtk.box_pack_start(box, gtk.image_new_from_icon_name(icon + "-symbolic", gtk.ICON_LARGE_TOOLBAR), False, False, 0)
    texts = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_valign(texts, gtk.ALIGN_CENTER)
    name = label(name_of(props), "bt-name")
    call gtk.label_set_ellipsize(name, 3)
    call gtk.box_pack_start(texts, name, False, False, 0)
    parts = [i18n.T(KIND.get(icon, "Device"))]
    if connected:
        parts.append(i18n.T("Connected"))
    elif paired:
        parts.append(i18n.T("Not connected"))
    end
    battery = props_of(path, "org.bluez.Battery1").get("Percentage")
    if battery != None:
        parts.append(i18n.TF("battery %d %%", [battery]))
    end
    sub = label(" · ".join(parts), "bt-sub")
    call gtk.box_pack_start(texts, sub, False, False, 0)
    call gtk.box_pack_start(box, texts, True, True, 0)
    spinner = gtk.spinner_new()
    call gtk.box_pack_start(box, spinner, False, False, 0)
    row = {"path": path, "sub": sub, "spinner": spinner}
    if paired:
        b = gtk.button_new(i18n.T("Disconnect") if connected else i18n.T("Connect"))
        call gtk.widget_set_valign(b, gtk.ALIGN_CENTER)
        call gtk.connect_data(b, "clicked", 0, on_toggle, [row, connected])
        call gtk.box_pack_start(box, b, False, False, 0)
        forget = gtk.button_new_from_icon_name("user-trash-symbolic", 4)
        call gtk.widget_set_tooltip(forget, i18n.T("Forget this device"))
        call gtk.widget_set_valign(forget, gtk.ALIGN_CENTER)
        call gtk.connect_data(forget, "clicked", 0, on_forget, row)
        call gtk.box_pack_start(box, forget, False, False, 0)
    else:
        b = gtk.button_new(i18n.T("Connect"))
        call gtk.widget_set_valign(b, gtk.ALIGN_CENTER)
        call gtk.widget_add_class(b, "suggested-action")
        call gtk.connect_data(b, "clicked", 0, on_pair, row)
        call gtk.box_pack_start(box, b, False, False, 0)
    end
    call gtk.list_box_add(bt["lists"]["paired" if paired else "nearby"], box)
    if path in bt["busy"]:
        call row_busy(row, True, bt["busy"][path])
    end
end

function row_busy(row, on, value):
    call gtk.spinner_set(row["spinner"], on)
    if value != "":
        call gtk.label_set_text(row["sub"], value)
    end
end

function build_page():
    page = ui.page_box()
    bt["page"] = page
    power = group()
    top = gtk.box_new(gtk.HORIZONTAL, 12)
    call gtk.box_pack_start(top, label(i18n.T("Bluetooth"), ""), True, True, 0)
    bt["power"] = gtk.switch_new()
    call gtk.widget_set_name(bt["power"], "power")
    call gtk.widget_set_valign(bt["power"], gtk.ALIGN_CENTER)
    call gtk.connect_data(bt["power"], "notify::active", 1, on_power, 0)
    call gtk.box_pack_end(top, bt["power"], False, False, 0)
    call gtk.list_box_add(power, top)
    call gtk.box_pack_start(page, power, False, False, 0)
    bt["hint"] = label("", "bt-sub")
    call gtk.widget_add_class(bt["hint"], "bt-hint")
    call gtk.widget_set_name(bt["hint"], "hint")
    call gtk.label_set_line_wrap(bt["hint"], True)
    call gtk.box_pack_start(page, bt["hint"], False, False, 0)

    # Jmeno tohoto pocitace (Alias adapteru) - vidi ho telefon, sluchatka...
    bt["name_group"] = group()
    call gtk.widget_set_name(bt["name_group"], "name-group")
    call gtk.widget_set_margins(bt["name_group"], 0, 0, 16, 0)
    nbox = gtk.box_new(gtk.HORIZONTAL, 12)
    call gtk.box_pack_start(nbox, gtk.image_new_from_icon_name("computer-symbolic", gtk.ICON_LARGE_TOOLBAR), False, False, 0)
    ntext = gtk.box_new(gtk.VERTICAL, 0)
    call gtk.widget_set_valign(ntext, gtk.ALIGN_CENTER)
    bt["name_label"] = label("", "bt-name")
    call gtk.widget_set_name(bt["name_label"], "name-label")
    call gtk.label_set_ellipsize(bt["name_label"], 3)
    bt["name_sub"] = label("", "bt-sub")
    call gtk.widget_set_name(bt["name_sub"], "name-sub")
    call gtk.label_set_line_wrap(bt["name_sub"], True)
    call gtk.box_pack_start(ntext, bt["name_label"], False, False, 0)
    call gtk.box_pack_start(ntext, bt["name_sub"], False, False, 0)
    call gtk.box_pack_start(nbox, ntext, True, True, 0)
    rename_button = gtk.button_new(i18n.T("Rename…"))
    call gtk.widget_set_valign(rename_button, gtk.ALIGN_CENTER)
    call gtk.connect_data(rename_button, "clicked", 0, on_rename, 0)
    call gtk.box_pack_start(nbox, rename_button, False, False, 0)
    call gtk.list_box_add(bt["name_group"], nbox)
    call gtk.box_pack_start(page, bt["name_group"], False, False, 0)

    for key in ["paired", "nearby"]:
        head = gtk.box_new(gtk.HORIZONTAL, 8)
        call gtk.widget_set_name(head, "head-" + key)
        title = i18n.T("My devices") if key == "paired" else i18n.T("Nearby devices")
        call gtk.box_pack_start(head, label(title, "group-title"), False, False, 0)
        if key == "nearby":
            bt["scan_spinner"] = gtk.spinner_new()
            call gtk.widget_set_valign(bt["scan_spinner"], gtk.ALIGN_CENTER)
            call gtk.widget_set_margins(bt["scan_spinner"], 0, 0, 8, 0)
            call gtk.box_pack_start(head, bt["scan_spinner"], False, False, 0)
        end
        call gtk.box_pack_start(page, head, False, False, 0)
        lb = group()
        call gtk.widget_set_name(lb, "list-" + key)
        empty = gtk.label_new(i18n.T("No devices") if key == "paired" else i18n.T("Searching… Put the device into pairing mode."))
        call gtk.widget_add_class(empty, "bt-empty")
        call gtk.widget_show(empty)
        call gtk.list_box_set_placeholder(lb, empty)
        call gtk.box_pack_start(page, lb, False, False, 0)
        bt["lists"][key] = lb
        bt["heads"][key] = head
    end
    return page
end

# Udalosti chodi v davkach - prekreslit jednou
function schedule_refresh():
    if not bt["pending"]:
        bt["pending"] = True
        call glib.timeout_add_data(250, refresh, 0)
    end
end

function show_lists(on):
    for key in ["paired", "nearby"]:
        call gtk.widget_set_visible(bt["lists"][key], on)
        call gtk.widget_set_visible(bt["heads"][key], on)
    end
end

function refresh(unused):
    bt["pending"] = False
    if bt["hidden"]:
        return False
    end
    apath = adapter_path()
    bt["apath"] = apath
    if apath == "":
        call gtk.widget_set_sensitive(bt["power"], False)
        call gtk.label_set_text(bt["hint"], i18n.T("No Bluetooth adapter was found on this computer."))
        call show_lists(False)
        call gtk.widget_set_visible(bt["name_group"], False)
        return False
    end
    adapter = props_of(apath, ADAPTER)
    on = adapter.get("Powered") == True
    discoverable = adapter.get("Discoverable") == True
    call gtk.widget_set_sensitive(bt["power"], True)
    bt["syncing"] = True
    call gtk.switch_set_active(bt["power"], on)
    bt["syncing"] = False
    alias = name_of({"Alias": adapter.get("Alias"), "Name": adapter.get("Name")})
    call keep_visible(on, adapter)
    if not on:
        call gtk.label_set_text(bt["hint"], i18n.T("Turn on Bluetooth to connect headphones, a mouse, a keyboard or a phone."))
    elif discoverable and bt["visible_ours"]:
        call gtk.label_set_text(bt["hint"], i18n.TF("Visible as “%s” while this window is open.", [alias]))
    elif discoverable:
        call gtk.label_set_text(bt["hint"], i18n.TF("Visible to nearby devices as “%s”.", [alias]))
    else:
        call gtk.label_set_text(bt["hint"], i18n.T("Not visible to other devices."))
    end
    call gtk.label_set_text(bt["name_label"], alias)
    sub = i18n.T("This computer's name, shown to other Bluetooth devices")
    if on and discoverable:
        sub = sub + " · " + i18n.T("visible now")
    end
    call gtk.label_set_text(bt["name_sub"], sub)
    call gtk.spinner_set(bt["scan_spinner"], adapter.get("Discovering") == True)
    for key in ["paired", "nearby"]:
        for child in gtk.container_get_children(bt["lists"][key]):
            call gtk.widget_destroy(child)
        end
    end
    for path in devices(apath):
        call device_row(path, props_of(path, DEVICE))
    end
    call gtk.widget_show_all(bt["page"])
    call show_lists(on)
    return False
end

# ---- viditelnost pocitace (Discoverable adapteru) ------------------------------------------------------------

# Stranka zobrazena a Bluetooth zapnuty -> pocitac viditelny. Uz viditelny (bluetoothctl, jina aplikace) se
# nemeni; kdyz viditelnost od stranky vyprsi nebo ji nekdo vypne, zapne se znovu.
function keep_visible(on, adapter):
    if bt["hidden"] or not on or bt["apath"] == "" or bt["visible_busy"] or bt["visible_failed"]:
        return 0
    end
    if adapter.get("Discoverable") == True:
        return 0
    end
    bt["visible_busy"] = True
    bt["visible_ours"] = True
    if bt["saved_timeout"] == None:
        bt["saved_timeout"] = adapter.get("DiscoverableTimeout")
    end
    # nejdriv casovac, pak viditelnost: i kdyz okno hned spadne, BlueZ ji za 3 minuty vypne
    call set_prop(bt["apath"], ADAPTER, "DiscoverableTimeout", "u", VISIBLE_TIMEOUT, on_timeout_set, 0)
end

function on_timeout_set(unused, reply, error):
    call set_prop(bt["apath"], ADAPTER, "Discoverable", "b", True, on_visible, 0)
    return 0
end

function on_visible(unused, reply, error):
    bt["visible_busy"] = False
    if error != "":
        bt["visible_failed"] = True
        call eprint("luxos-bluetooth: discoverable: " + error)
    end
    call schedule_refresh()
    return 0
end

# Novy DiscoverableTimeout znovu spusti odpocet BlueZ - pri zobrazene strance viditelnost nevyprsi
function renew_visible(unused):
    if bt["hidden"]:
        return False
    end
    if bt["visible_ours"] and adapter_props().get("Discoverable") == True:
        call set_prop(bt["apath"], ADAPTER, "DiscoverableTimeout", "u", VISIBLE_TIMEOUT, ignore_reply, 0)
    end
    return True
end

# Vypne viditelnost, jen kdyz ji zapla tato stranka; restore vrati puvodni DiscoverableTimeout. Synchronne -
# po zavreni okna proces hned konci.
function hide_visible(restore):
    if bt["apath"] == "":
        return 0
    end
    if bt["visible_ours"]:
        bt["visible_ours"] = False
        call set_prop_sync("Discoverable", "b", False)
    end
    saved = bt["saved_timeout"]
    if restore and saved != None and saved != VISIBLE_TIMEOUT:
        call set_prop_sync("DiscoverableTimeout", "u", saved)
    end
end

# ---- hledani zarizeni -------------------------------------------------------------------------------------------

function start_scan(unused):
    if bt["apath"] != "":
        call gio.call_async(bz["bus"], BLUEZ, bt["apath"], ADAPTER, "StartDiscovery", [], "", 60000, ignore_reply, 0)
    end
    return False
end

function stop_scan():
    if bt["apath"] != "":
        try:
            call gio.call_values(bz["bus"], BLUEZ, bt["apath"], ADAPTER, "StopDiscovery", [], "", 2000)
        else:
            return 0
        end
    end
end

function is_active():
    if bt["active"] != None:
        return bt["active"]
    end
    return gtk.window_is_active(bt["window"])
end

# Hledani zbytecne zatezuje radio (horsi zvuk sluchatek, baterie) a BlueZ pri nem posila stale udalosti -
# okno odlozene v pozadi ho po chvili zastavi, po navratu obnovi
function on_active(unused, pspec, window):
    if bt["scan_pause_timer"] != 0:
        call glib.source_remove(bt["scan_pause_timer"])
        bt["scan_pause_timer"] = 0
    end
    if bt["hidden"]:
        return 0
    end
    if is_active():
        if bt["scan_paused"]:
            bt["scan_paused"] = False
            call start_scan(0)
        end
    else:
        bt["scan_pause_timer"] = glib.timeout_add_seconds_data(SCAN_IDLE, pause_scan, 0)
    end
    return 0
end

function pause_scan(unused):
    bt["scan_pause_timer"] = 0
    if not bt["hidden"] and not bt["scan_paused"]:
        bt["scan_paused"] = True
        call stop_scan()
    end
    return False
end

# ---- stranka v okne Nastaveni ----------------------------------------------------------------------------------

function build(host):
    bt["window"] = host["window"]
    if bt["css"] == 0:
        bt["css"] = gtk.css_load(CSS)
    end
    try:
        bz["bus"] = gio.system_bus()
    else:
        bz["bus"] = 0
        call eprint("luxos-bluetooth: " + String(last_error()))
    end
    page = build_page()
    # okno je spolecne pro vsechny stranky: obsluha jen pri zobrazene strance (bt["hidden"])
    call gtk.connect_data(host["window"], "notify::is-active", 1, on_active, 0)
    if bz["bus"] != 0:
        call gio.subscribe_values(bz["bus"], BLUEZ, "org.freedesktop.DBus.ObjectManager", "InterfacesAdded", "", on_objects)
        call gio.subscribe_values(bz["bus"], BLUEZ, "org.freedesktop.DBus.ObjectManager", "InterfacesRemoved", "", on_objects)
        call gio.subscribe_values(bz["bus"], BLUEZ, "org.freedesktop.DBus.Properties", "PropertiesChanged", "", on_props)
        call agent.set_parent(host["window"])
        call agent.watch(bz["bus"])
    end
    call reload()
    return page
end

function show(host):
    if not bt["hidden"]:
        return 0
    end
    bt["hidden"] = False
    bt["visible_failed"] = False
    call refresh(0)
    call start_scan(0)
    bt["visible_timer"] = glib.timeout_add_seconds_data(VISIBLE_REFRESH, renew_visible, 0)
    call on_active(0, 0, host["window"])
    return 0
end

# Odchod ze stranky i zavreni okna: hledani a viditelnost jen pri zobrazene strance
function leave(host):
    bt["hidden"] = True
    for timer in ["visible_timer", "scan_pause_timer"]:
        if bt[timer] != 0:
            call glib.source_remove(bt[timer])
            bt[timer] = 0
        end
    end
    bt["scan_paused"] = False
    call stop_scan()
    call hide_visible(True)
    bt["saved_timeout"] = None
    return 0
end

# ---- akce --------------------------------------------------------------------------------------------------------

function on_power(unused, pspec, switch):
    if bt["syncing"] or bt["apath"] == "":
        return 0
    end
    on = gtk.switch_get_active(switch)
    if on:
        call glib.spawn_sync_quiet(["rfkill", "unblock", "bluetooth"])
    else:
        # po zapnuti ji refresh zapne znovu
        call hide_visible(False)
        bt["visible_failed"] = False
    end
    call set_prop(bt["apath"], ADAPTER, "Powered", "b", on, ignore_reply, 0)
    if on:
        call glib.timeout_add_data(800, start_scan, 0)
    end
    return 0
end

function mark(row, value):
    bt["busy"][row["path"]] = value
    call row_busy(row, True, value)
end

function on_done(row, reply, error):
    if row["path"] in bt["busy"]:
        call bt["busy"].pop(row["path"])
    end
    if error != "":
        call show_error(i18n.T("Could not connect"), error_text(error), True)
    end
    call schedule_refresh()
    return 0
end

function device_call(row, method, done):
    call gio.call_async(bz["bus"], BLUEZ, row["path"], DEVICE, method, [], "", 60000, done, row)
end

function on_pair(row, button):
    call mark(row, i18n.T("Pairing…"))
    call device_call(row, "Pair", on_paired)
    return 0
end

function on_paired(row, reply, error):
    if error != "" and error.find("AlreadyExists") < 0:
        return on_done(row, reply, error)
    end
    call set_prop(row["path"], DEVICE, "Trusted", "b", True, ignore_reply, 0)
    call mark(row, i18n.T("Connecting…"))
    call device_call(row, "Connect", on_done)
    return 0
end

function on_toggle(bound, button):
    row = bound[0]
    connected = bound[1]
    call mark(row, i18n.T("Disconnecting…") if connected else i18n.T("Connecting…"))
    call device_call(row, "Disconnect" if connected else "Connect", on_done)
    return 0
end

function on_forget(row, button):
    call gio.call_async(bz["bus"], BLUEZ, bt["apath"], ADAPTER, "RemoveDevice", [row["path"]], "(o)", 60000, on_done, row)
    return 0
end

function show_error(title, message, advice):
    if advice:
        message = message + "\n\n" + i18n.T("Make sure the device is on, close by and in pairing mode.")
    end
    parts = agent.build_dialog(title, glib.markup_escape(message), False, False, i18n.T("Close"))
    call gtk.window_set_transient_for(parts[0], bt["window"])
    call gtk.window_set_modal(parts[0], True)
    call gtk.dialog_run(parts[0])
    call gtk.widget_destroy(parts[0])
end

# ---- prejmenovani pocitace (Alias adapteru) --------------------------------------------------------------------

function default_name():
    name = adapter_props().get("Name", "")
    if name == "" or name == None:
        return glib.host_name()
    end
    return String(name)
end

function on_rename(unused, button):
    if bt["apath"] == "":
        return 0
    end
    default = default_name()
    dialog = gtk.dialog_new()
    call gtk.window_set_title(dialog, i18n.T("Rename This Computer"))
    call gtk.window_set_transient_for(dialog, bt["window"])
    call gtk.window_set_modal(dialog, True)
    call gtk.dialog_add_button(dialog, i18n.T("Cancel"), gtk.RESPONSE_CANCEL)
    use_default = gtk.dialog_add_button(dialog, i18n.T("Use Default"), -2)
    call gtk.widget_set_tooltip(use_default, i18n.TF("Use the system name “%s”", [default]))
    ok = gtk.dialog_add_button(dialog, i18n.T("Rename"), gtk.RESPONSE_OK)
    call gtk.widget_add_class(ok, "suggested-action")
    call gtk.dialog_set_default_response(dialog, gtk.RESPONSE_OK)
    box = gtk.dialog_get_content_area(dialog)
    call gtk.box_set_spacing(box, 8)
    call gtk.widget_set_margins(box, 16, 16, 12, 8)
    info = label(i18n.T("Other Bluetooth devices, such as your phone or headphones, show this name."), "")
    call gtk.label_set_line_wrap(info, True)
    call gtk.label_set_max_width_chars(info, 48)
    call gtk.box_pack_start(box, info, False, False, 0)
    entry = gtk.entry_new()
    current = String(adapter_props().get("Alias", ""))
    call gtk.entry_set_text(entry, current if current != "" and current != "None" else default)
    call gtk.entry_set_activates_default(entry, True)
    call gtk.entry_set_placeholder_text(entry, default)
    call gtk.box_pack_start(box, entry, False, False, 0)
    err = label("", "bt-sub")
    call gtk.label_set_line_wrap(err, True)
    call gtk.label_set_max_width_chars(err, 48)
    call gtk.box_pack_start(box, err, False, False, 0)
    form = [entry, err, ok, default]
    call gtk.connect_data(entry, "changed", 0, on_name_changed, form)
    call on_name_changed(form, entry)
    call gtk.widget_show_all(box)
    response = gtk.dialog_run(dialog)
    value = clean_alias(gtk.entry_get_text(entry))
    call gtk.widget_destroy(dialog)
    if response == -2:
        call set_alias("")
    elif response == gtk.RESPONSE_OK and alias_problem(value) == "":
        call set_alias(value)
    end
    return 0
end

function on_name_changed(form, entry):
    name = clean_alias(gtk.entry_get_text(form[0]))
    problem = alias_problem(name)
    if problem == "" and name == "":
        problem = i18n.TF("An empty name uses the system name “%s”.", [form[3]])
        call gtk.widget_set_sensitive(form[2], True)
    else:
        call gtk.widget_set_sensitive(form[2], problem == "")
    end
    call gtk.label_set_text(form[1], problem)
    return 0
end

# Novy Alias adapteru ("" = vychozi jmeno systemu); BlueZ ho ulozi trvale
function set_alias(name):
    if bt["apath"] == "" or alias_problem(name) != "":
        return False
    end
    call set_prop(bt["apath"], ADAPTER, "Alias", "s", name, on_alias_set, 0)
    return True
end

function on_alias_set(unused, reply, error):
    if error != "":
        call show_error(i18n.T("Could not rename this computer"), error_text(error), False)
    end
    call reload()
    return 0
end

# ---- testy (LUXOS_TEST_CONTROL=1, luxos-settings preda prikazy, ktere nezna) -----------------------------------
# "state" patri oknu Nastaveni, stav stranky je "page-state"

function test(command, rest):
    if command == "check":
        print "check " + json.encode(alias_problem(json.decode(rest)))
    elif command == "alias":
        print "alias " + String(set_alias(json.decode(rest)))
    elif command == "reloads":
        print "reloads " + String(bz["reloads"])
    elif command == "records":
        print "records " + String(glib.record_count() + len(glib.live))
    elif command == "refresh":
        call refresh(0)
    elif command == "renew":
        print "renew " + String(renew_visible(0))
    elif command == "active":
        bt["active"] = rest == "1"
        call on_active(0, 0, bt["window"])
    elif command == "pause":
        print "pause " + String(pause_scan(0))
    elif command == "page-state":
        print "page-state " + json.encode({"scan_paused": bt["scan_paused"], "scan_timer": bt["scan_pause_timer"] != 0,
            "visible_ours": bt["visible_ours"], "shown": not bt["hidden"]})
    elif command == "close":
        call gtk.widget_destroy(bt["window"])
    else:
        return False
    end
    return True
end
