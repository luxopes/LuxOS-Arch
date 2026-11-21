#!/usr/bin/env python3
"""LuxOS - napodobeny BlueZ (org.bluez) pro testy luxos-bluetooth na soukromem dbus-daemonu.

    FAKE_BLUEZ_ADDR=adresa FAKE_BLUEZ_LOG=soubor fake_bluez.py

ObjectManager na /, adapter hci0 (Properties Get/GetAll/Set, StartDiscovery, StopDiscovery, RemoveDevice),
zarizeni dev_AA_BB_CC_DD_EE_01 v okoli (Pair, Connect, Disconnect), AgentManager1 na /org/bluez.
Set Alias "" vrati jmeno systemu (jako BlueZ). Kazde volani se zapise do $FAKE_BLUEZ_LOG (JSON radky).
Soubory vedle logu menit chovani: .deny (Alias odmitnut), .deny-visible (Discoverable odmitnut),
.fail-connect (Connect selze s Page Timeout).
Rozhrani cz.luxos.Test na /: Emit(cesta, rozhrani, zmenene, zneplatnene) vysle PropertiesChanged.
Skutecny Bluetooth se nikdy nepouzije: jen soukroma sbernice z promenne prostredi.
"""
import json
import os

from gi.repository import Gio, GLib

LOG = os.environ["FAKE_BLUEZ_LOG"]
A = "/org/bluez/hci0"
DEV = A + "/dev_AA_BB_CC_DD_EE_01"
SIG = {"Address": "s", "Name": "s", "Alias": "s", "Powered": "b", "Discoverable": "b", "DiscoverableTimeout": "u",
       "Discovering": "b", "Paired": "b", "Trusted": "b", "Connected": "b", "Icon": "s", "RSSI": "n", "Adapter": "o"}
adapter = {"Address": "00:11:22:33:44:55", "Name": "luxos-pc", "Alias": "luxos-pc",
           "Powered": os.environ.get("FAKE_BLUEZ_POWERED", "1") == "1",
           "Discoverable": False, "DiscoverableTimeout": 0, "Discovering": False}
devices = {DEV: {"Address": "AA:BB:CC:DD:EE:01", "Alias": "Pixel Test", "Name": "Pixel Test", "RSSI": -55,
                 "Adapter": A, "Paired": False, "Trusted": False, "Connected": False, "Icon": "phone"}}
XML = """<node>
<interface name="org.freedesktop.DBus.ObjectManager">
 <method name="GetManagedObjects"><arg type="a{oa{sa{sv}}}" direction="out"/></method>
</interface>
<interface name="org.freedesktop.DBus.Properties">
 <method name="Get"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/></method>
 <method name="GetAll"><arg type="s" direction="in"/><arg type="a{sv}" direction="out"/></method>
 <method name="Set"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/></method>
</interface>
<interface name="org.bluez.Adapter1">
 <method name="StartDiscovery"/><method name="StopDiscovery"/>
 <method name="RemoveDevice"><arg type="o" direction="in"/></method>
</interface>
<interface name="org.bluez.Device1">
 <method name="Pair"/><method name="Connect"/><method name="Disconnect"/>
</interface>
<interface name="org.bluez.AgentManager1">
 <method name="RegisterAgent"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
 <method name="RequestDefaultAgent"><arg type="o" direction="in"/></method>
</interface>
<interface name="cz.luxos.Test">
 <method name="Emit"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="a{sv}" direction="in"/>
  <arg type="as" direction="in"/></method>
</interface>
</node>"""
node = Gio.DBusNodeInfo.new_for_xml(XML)
loop = GLib.MainLoop()
bus = Gio.DBusConnection.new_for_address_sync(
    os.environ["FAKE_BLUEZ_ADDR"],
    Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)


def variants(props):
    return {k: GLib.Variant(SIG[k], v) for k, v in props.items()}


def objects():
    out = {A: {"org.bluez.Adapter1": variants(adapter)}}
    for path, props in devices.items():
        out[path] = {"org.bluez.Device1": variants(props)}
    return out


def log(entry):
    with open(LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def changed(path, iface, props):
    bus.emit_signal(None, path, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                    GLib.Variant("(sa{sv}as)", (iface, variants(props), [])))


def flag(name):
    return os.path.exists(LOG + "." + name)


def set_prop(path, name, value, inv):
    log({"set": name, "value": value, "path": path})
    if path == A and name in ("Alias", "Powered", "Discoverable", "DiscoverableTimeout"):
        if (name == "Alias" and flag("deny")) or (name == "Discoverable" and value and flag("deny-visible")):
            inv.return_dbus_error("org.freedesktop.DBus.Error.AccessDenied", "Rejected send message")
            return
        adapter[name] = value if not (name == "Alias" and value == "") else adapter["Name"]
        inv.return_value(None)
        changed(A, "org.bluez.Adapter1", {name: adapter[name]})
    elif path in devices and name == "Trusted":
        devices[path][name] = value
        inv.return_value(None)
        changed(path, "org.bluez.Device1", {name: value})
    else:
        inv.return_dbus_error("org.bluez.Error.InvalidArguments", "Invalid arguments")


def call(conn, sender, path, iface, method, params, inv):
    args = params.unpack()
    props = adapter if path == A else devices.get(path, {})
    if method == "GetManagedObjects":
        inv.return_value(GLib.Variant("(a{oa{sa{sv}}})", (objects(),)))
    elif method == "GetAll":
        inv.return_value(GLib.Variant("(a{sv})", (variants(props),)))
    elif method == "Get":
        inv.return_value(GLib.Variant("(v)", (variants(props)[args[1]],)))
    elif method == "Set":
        set_prop(path, args[1], args[2], inv)
    elif method == "Emit":
        bus.emit_signal(None, args[0], "org.freedesktop.DBus.Properties", "PropertiesChanged",
                        GLib.Variant.new_tuple(GLib.Variant("s", args[1]), params.get_child_value(2),
                                               GLib.Variant("as", args[3])))
        inv.return_value(None)
    else:
        log({"call": method, "path": path, "sender": sender, "args": [str(a) for a in args]})
        if method == "Pair" and path in devices:
            devices[path]["Paired"] = True
            inv.return_value(None)
            changed(path, "org.bluez.Device1", {"Paired": True})
        elif method == "Connect" and path in devices:
            if flag("fail-connect"):
                inv.return_dbus_error("org.bluez.Error.Failed", "Page Timeout")
                return
            devices[path]["Connected"] = True
            inv.return_value(None)
            changed(path, "org.bluez.Device1", {"Connected": True})
        elif method == "Disconnect" and path in devices:
            devices[path]["Connected"] = False
            inv.return_value(None)
            changed(path, "org.bluez.Device1", {"Connected": False})
        elif method == "RemoveDevice":
            gone = devices.pop(args[0], None)
            inv.return_value(None)
            if gone is not None:
                bus.emit_signal(None, "/", "org.freedesktop.DBus.ObjectManager", "InterfacesRemoved",
                                GLib.Variant("(oas)", (args[0], ["org.bluez.Device1"])))
        else:
            inv.return_value(None)


for path in ("/", "/org/bluez", A, DEV):
    for i in node.interfaces:
        bus.register_object(path, i, call, None, None)
Gio.bus_own_name_on_connection(bus, "org.bluez", Gio.BusNameOwnerFlags.NONE,
                               lambda *a: print("READY", flush=True), lambda *a: loop.quit())
loop.run()
