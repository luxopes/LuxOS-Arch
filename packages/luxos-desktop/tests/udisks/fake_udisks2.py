#!/usr/bin/env python3
"""LuxOS - napodobeny UDisks2 (org.freedesktop.UDisks2) pro test automatickeho pripojeni (luxos_automount.lsl)
na soukrome sbernici.

    FAKE_UDISKS_ADDR=adresa FAKE_UDISKS_LOG=soubor fake_udisks2.py

Disky (Drive) /org/freedesktop/UDisks2/drives/usb (USB) a .../dvd (Optical=optical_dvd). Rozhrani cz.luxos.Test na
/org/freedesktop/UDisks2: Plug(jmeno, druh) vysle InterfacesAdded pro .../block_devices/JMENO; druh usb, dvd, system
(HintSystem, vnitrni disk), ignore (HintIgnore), media (jen Filesystem - Block uz existoval, cte se pres GetAll).
Filesystem.Mount(a{sv}) vytvori a vrati $FAKE_UDISKS_MEDIA/<jmeno, _ jako mezera> a zapise volani do $FAKE_UDISKS_LOG
(JSON radky).
Skutecne disky se nikdy nepouziji: jen soukroma sbernice z promenne prostredi.
"""
import json
import os

from gi.repository import Gio, GLib

LOG = os.environ["FAKE_UDISKS_LOG"]
MEDIA = os.environ["FAKE_UDISKS_MEDIA"]
ROOT = "/org/freedesktop/UDisks2"
BLOCK = "org.freedesktop.UDisks2.Block"
FS = "org.freedesktop.UDisks2.Filesystem"
DRIVE = "org.freedesktop.UDisks2.Drive"
XML = """<node>
<interface name="org.freedesktop.DBus.ObjectManager">
 <method name="GetManagedObjects"><arg type="a{oa{sa{sv}}}" direction="out"/></method>
</interface>
<interface name="org.freedesktop.DBus.Properties">
 <method name="Get"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/></method>
 <method name="GetAll"><arg type="s" direction="in"/><arg type="a{sv}" direction="out"/></method>
</interface>
<interface name="org.freedesktop.UDisks2.Filesystem">
 <method name="Mount"><arg type="a{sv}" direction="in"/><arg type="s" direction="out"/></method>
</interface>
<interface name="cz.luxos.Test">
 <method name="Plug"><arg type="s" direction="in"/><arg type="s" direction="in"/></method>
</interface>
</node>"""
node = Gio.DBusNodeInfo.new_for_xml(XML)
loop = GLib.MainLoop()
bus = Gio.DBusConnection.new_for_address_sync(
    os.environ["FAKE_UDISKS_ADDR"],
    Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
# cesta -> {rozhrani: {vlastnost: GLib.Variant}}
objects = {
    ROOT + "/drives/usb": {DRIVE: {"Optical": GLib.Variant("s", ""), "Removable": GLib.Variant("b", True),
                                   "ConnectionBus": GLib.Variant("s", "usb")}},
    ROOT + "/drives/dvd": {DRIVE: {"Optical": GLib.Variant("s", "optical_dvd"), "Removable": GLib.Variant("b", True),
                                   "ConnectionBus": GLib.Variant("s", "")}},
}


def log(entry):
    with open(LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


def block(drive, auto=True, system=False, ignore=False):
    return {"Drive": GLib.Variant("o", ROOT + "/drives/" + drive), "HintAuto": GLib.Variant("b", auto),
            "HintSystem": GLib.Variant("b", system), "HintIgnore": GLib.Variant("b", ignore),
            "IdLabel": GLib.Variant("s", "")}


def register(path):
    for i in node.interfaces:
        if i.name != "cz.luxos.Test":
            bus.register_object(path, i, call, None, None)


def plug(name, kind):
    path = ROOT + "/block_devices/" + name
    fs = {"MountPoints": GLib.Variant("aay", [])}
    blocks = {"usb": block("usb"), "dvd": block("dvd"), "system": block("usb", auto=False, system=True),
              "ignore": block("usb", ignore=True), "media": block("usb")}
    objects[path] = {BLOCK: blocks[kind], FS: fs}
    register(path)
    added = {FS: fs} if kind == "media" else objects[path]
    bus.emit_signal(None, ROOT, "org.freedesktop.DBus.ObjectManager", "InterfacesAdded",
                    GLib.Variant("(oa{sa{sv}})", (path, added)))


def call(conn, sender, path, iface, method, params, inv):
    args = params.unpack()
    if method == "GetManagedObjects":
        inv.return_value(GLib.Variant("(a{oa{sa{sv}}})", (objects,)))
    elif method == "GetAll":
        inv.return_value(GLib.Variant("(a{sv})", (objects.get(path, {}).get(args[0], {}),)))
    elif method == "Get":
        inv.return_value(GLib.Variant("(v)", (objects[path][args[0]][args[1]],)))
    elif method == "Plug":
        inv.return_value(None)
        plug(args[0], args[1])
    elif method == "Mount":
        log({"call": "Mount", "path": path, "options": args[0]})
        target = os.path.join(MEDIA, path.rsplit("/", 1)[1].replace("_", " "))
        os.makedirs(target, exist_ok=True)
        inv.return_value(GLib.Variant("(s)", (target,)))
    else:
        inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)


for p in (ROOT, *objects):
    register(p)
bus.register_object(ROOT, node.lookup_interface("cz.luxos.Test"), call, None, None)
Gio.bus_own_name_on_connection(bus, "org.freedesktop.UDisks2", Gio.BusNameOwnerFlags.NONE,
                               lambda *a: print("READY", flush=True), lambda *a: loop.quit())
loop.run()
