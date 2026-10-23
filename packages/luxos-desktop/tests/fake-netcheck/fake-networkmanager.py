#!/usr/bin/env python3
"""Falesny NetworkManager na sbernici D-Bus pro testy luxos-netcheck.

  fake-networkmanager.py STATE CONNECTIVITY

Vlastni jmeno org.freedesktop.NetworkManager a vraci vlastnosti State a Connectivity (uint32)
rozhrani org.freedesktop.NetworkManager. Po ziskani jmena vypise "ready".
"""
import sys

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

STATE, CONNECTIVITY = int(sys.argv[1]), int(sys.argv[2])
XML = """<node><interface name="org.freedesktop.NetworkManager">
  <property name="State" type="u" access="read"/>
  <property name="Connectivity" type="u" access="read"/>
</interface></node>"""


def get_property(conn, sender, path, iface, name):
    return GLib.Variant("u", STATE if name == "State" else CONNECTIVITY)


def on_bus(conn, name):
    info = Gio.DBusNodeInfo.new_for_xml(XML)
    conn.register_object("/org/freedesktop/NetworkManager", info.interfaces[0], None, get_property, None)


def on_acquired(conn, name):
    print("ready", flush=True)


Gio.bus_own_name(Gio.BusType.SESSION, "org.freedesktop.NetworkManager", Gio.BusNameOwnerFlags.NONE,
                 on_bus, on_acquired, lambda *a: sys.exit(1))
GLib.MainLoop().run()
