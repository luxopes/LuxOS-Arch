#!/usr/bin/env python3
"""Nahradni sluzby D-Bus pro test_luxos_bar_wl.py (jen soukrome sbernice testu, nikdy skutecny system).

    fake_bar_services.py SYSTEM_ADDR SESSION_ADDR

Systemova sbernice: NetworkManager (Wi-Fi "LuxNet", sila 80), UPower DisplayDevice (76 %, vybiji), locale1
(X11Layout "cz,us"). Sbernice relace: historie oznameni jako luxos-notify (org.xfce.Notifyd: Log s jednim
neprectenym zaznamem, cz.luxos.NotificationHistory) a jedna StatusNotifierItem (registruje se u watcheru listy). Prikazy na stdin meni stav a posilaji PropertiesChanged:
    battery PROCENTA STAV       (UPower State: 1 nabiji, 2 vybiji, 4 nabito)
    strength N                  sila signalu pristupoveho bodu
    connectivity N              NMConnectivityState (4 plna, 3 omezena, 2 portal)
Na stdout: "ready", "popups-hidden B", "dnd B", "mark-all-read", "activate X Y", "registered".
"""
import sys
import time

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

NM_PATH = "/org/freedesktop/NetworkManager"
AC_PATH = NM_PATH + "/ActiveConnection/1"
AP_PATH = NM_PATH + "/AccessPoint/7"
DEV_PATH = "/org/freedesktop/UPower/devices/DisplayDevice"


def say(text):
    print(text, flush=True)


def node(xml):
    return Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0]


def props_iface(name, props):
    return node(f"<node><interface name='{name}'>" + "".join(
        f"<property name='{k}' type='{v.get_type_string()}' access='read'/>" for k, v in props.items()) + "</interface></node>")


class Object:
    """Objekt jen s vlastnostmi (Get/GetAll obslouzi GDBus pres get_property) a metodami z handlers."""

    def __init__(self, bus, path, name, props, methods="", handlers=None):
        self.bus, self.path, self.name, self.props = bus, path, name, props
        self.handlers = handlers or {}
        xml = f"<node><interface name='{name}'>{methods}" + "".join(
            f"<property name='{k}' type='{v.get_type_string()}' access='read'/>" for k, v in props.items()) + \
            "</interface></node>"
        bus.register_object(path, node(xml), self.call, self.get, None)

    def call(self, conn, sender, path, iface, method, params, invocation):
        result = self.handlers[method](*params.unpack())
        invocation.return_value(result)

    def get(self, conn, sender, path, iface, prop):
        return self.props[prop]

    def set(self, **changes):
        for k, v in changes.items():
            self.props[k] = v
        self.bus.emit_signal(None, self.path, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                             GLib.Variant("(sa{sv}as)", (self.name, changes, [])))


def own(bus, name):
    bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName",
                  GLib.Variant("(su)", (name, 4)), None, 0, -1, None)


def main():
    system = Gio.DBusConnection.new_for_address_sync(
        sys.argv[1], Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION)
    session = Gio.DBusConnection.new_for_address_sync(
        sys.argv[2], Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION)
    nm = Object(system, NM_PATH, "org.freedesktop.NetworkManager", {
        "State": GLib.Variant("u", 70), "Connectivity": GLib.Variant("u", 4),
        "PrimaryConnection": GLib.Variant("o", AC_PATH), "PrimaryConnectionType": GLib.Variant("s", "802-11-wireless"),
        "WirelessEnabled": GLib.Variant("b", True)})
    Object(system, AC_PATH, "org.freedesktop.NetworkManager.Connection.Active", {
        "Id": GLib.Variant("s", "LuxNet"), "Type": GLib.Variant("s", "802-11-wireless"),
        "SpecificObject": GLib.Variant("o", AP_PATH)})
    ap = Object(system, AP_PATH, "org.freedesktop.NetworkManager.AccessPoint", {"Strength": GLib.Variant("y", 80)})
    battery = Object(system, DEV_PATH, "org.freedesktop.UPower.Device", {
        "IsPresent": GLib.Variant("b", True), "Type": GLib.Variant("u", 2), "Percentage": GLib.Variant("d", 76.0),
        "State": GLib.Variant("u", 2), "TimeToEmpty": GLib.Variant("x", 7380), "TimeToFull": GLib.Variant("x", 0)})
    Object(system, "/org/freedesktop/locale1", "org.freedesktop.locale1", {"X11Layout": GLib.Variant("s", "cz,us")})
    for name in ("org.freedesktop.NetworkManager", "org.freedesktop.UPower", "org.freedesktop.locale1"):
        own(system, name)

    notes = {"read": False, "dnd": False}
    row = "(sxssssssa(ss)ib)"

    def entry():
        return ("7", int(time.time() * 1e6), "", "luxos-mail", "Posta", "mail-unread", "Nova zprava", "Ahoj", [], 0,
                notes["read"])

    def log_signal(name):
        session.emit_signal(None, "/org/xfce/Notifyd", "org.xfce.Notifyd.Log", name, GLib.Variant("(s)", ("7",)))

    def mark_all():
        notes["read"] = True
        say("mark-all-read")
        log_signal("RowChanged")
        return None

    def popups_hidden(hidden):
        say(f"popups-hidden {hidden}")
        return None

    def set_dnd(on):
        notes["dnd"] = on
        say(f"dnd {on}")
        return None
    Object(session, "/org/xfce/Notifyd", "org.xfce.Notifyd.Log", {},
           f"<method name='List'><arg type='s'/><arg type='u'/><arg type='b'/><arg type='a{row}' direction='out'/></method>"
           "<method name='HasUnread'><arg type='b' direction='out'/></method><method name='MarkAllRead'/>",
           {"List": lambda *a: GLib.Variant(f"(a{row})", ([entry()],)),
            "HasUnread": lambda: GLib.Variant("(b)", (not notes["read"],)), "MarkAllRead": mark_all})
    Object(session, "/cz/luxos/NotificationHistory", "cz.luxos.NotificationHistory", {},
           "<method name='GetDoNotDisturb'><arg type='b' direction='out'/></method>"
           "<method name='SetDoNotDisturb'><arg type='b'/></method><method name='SetPopupsHidden'><arg type='b'/></method>",
           {"GetDoNotDisturb": lambda: GLib.Variant("(b)", (notes["dnd"],)), "SetDoNotDisturb": set_dnd,
            "SetPopupsHidden": popups_hidden})
    own(session, "org.xfce.Notifyd")

    def activate(x, y):
        say(f"activate {x} {y}")
        return None
    Object(session, "/StatusNotifierItem", "org.kde.StatusNotifierItem", {
        "Id": GLib.Variant("s", "fake"), "Title": GLib.Variant("s", "Fake tray"), "Status": GLib.Variant("s", "Active"),
        "IconName": GLib.Variant("s", "audio-volume-high-symbolic"), "ItemIsMenu": GLib.Variant("b", False),
        "Menu": GLib.Variant("o", "/")},
        "<method name='Activate'><arg type='i'/><arg type='i'/></method>", {"Activate": activate})

    def register(*args):
        session.call("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher",
                     "RegisterStatusNotifierItem", GLib.Variant("(s)", ("/StatusNotifierItem",)), None, 0, -1, None,
                     lambda c, r: (c.call_finish(r), say("registered")))
    Gio.bus_watch_name_on_connection(session, "org.kde.StatusNotifierWatcher", 0, register, None)

    def command(channel, condition):
        line = sys.stdin.readline()
        if not line:
            loop.quit()
            return False
        f = line.split()
        if f[0] == "battery":
            battery.set(Percentage=GLib.Variant("d", float(f[1])), State=GLib.Variant("u", int(f[2])))
        elif f[0] == "strength":
            ap.set(Strength=GLib.Variant("y", int(f[1])))
        elif f[0] == "connectivity":
            nm.set(Connectivity=GLib.Variant("u", int(f[1])))
        say("done " + f[0])
        return True
    GLib.io_add_watch(GLib.IOChannel.unix_new(0), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP, command)
    loop = GLib.MainLoop()
    say("ready")
    loop.run()


if __name__ == "__main__":
    main()
