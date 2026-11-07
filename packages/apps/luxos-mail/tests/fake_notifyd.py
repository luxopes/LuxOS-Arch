#!/usr/bin/env python3
"""Testovaci org.freedesktop.Notifications na soukrome sbernici: kazde Notify zapise jako radek JSON.

Akci "Otevrit" lze vyvolat souborem <log>.invoke (obsahuje id upozorneni) - server pak posle ActionInvoked.
Zavreni krizkem souborem <log>.dismiss (id) -> NotificationClosed s duvodem 2. Nahrazeni (replaces_id)
vrati stejne id, CloseNotification se zapise do <log>.closed a posle NotificationClosed s duvodem 3.
"""
import json
import os
import sys

from gi.repository import Gio, GLib

XML = """
<node><interface name="org.freedesktop.Notifications">
<method name="Notify"><arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/>
<arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/>
<arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="out"/></method>
<method name="CloseNotification"><arg type="u" direction="in"/></method>
<method name="GetCapabilities"><arg type="as" direction="out"/></method>
<method name="GetServerInformation"><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/></method>
<signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
<signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
</interface></node>
"""

LOG = sys.argv[1]
state = {"next": 1, "conn": None}


def on_call(conn, sender, path, iface, method, params, invocation):
    if method == "Notify":
        app, replaces, icon, summary, body, actions, hints, timeout = params.unpack()
        if replaces:
            nid = replaces
        else:
            nid = state["next"]
            state["next"] += 1
        with open(LOG, "a") as f:
            f.write(json.dumps({"id": nid, "app": app, "icon": icon, "summary": summary, "body": body,
                                "actions": actions, "replaces": replaces, "timeout": timeout,
                                "hints": {k: str(v) for k, v in hints.items()}}) + "\n")
        invocation.return_value(GLib.Variant("(u)", (nid,)))
    elif method == "CloseNotification":
        nid = params.unpack()[0]
        with open(LOG + ".closed", "a") as f:
            f.write("%d\n" % nid)
        invocation.return_value(None)
        conn.emit_signal(None, "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
                         "NotificationClosed", GLib.Variant("(uu)", (nid, 3)))
    elif method == "GetCapabilities":
        invocation.return_value(GLib.Variant("(as)", (["actions", "body", "body-markup"],)))
    elif method == "GetServerInformation":
        invocation.return_value(GLib.Variant("(ssss)", ("fake", "LuxOS", "1", "1.2")))
    else:
        invocation.return_value(None)


def check_invoke():
    path = LOG + ".invoke"
    if os.path.exists(path):
        with open(path) as f:
            nid = int(f.read().strip() or "0")
        os.remove(path)
        state["conn"].emit_signal(None, "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
                                  "ActionInvoked", GLib.Variant("(us)", (nid, "default")))
    path = LOG + ".dismiss"
    if os.path.exists(path):
        with open(path) as f:
            nid = int(f.read().strip() or "0")
        os.remove(path)
        state["conn"].emit_signal(None, "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
                                  "NotificationClosed", GLib.Variant("(uu)", (nid, 2)))
    return True


def on_bus(conn, name):
    state["conn"] = conn
    node = Gio.DBusNodeInfo.new_for_xml(XML)
    conn.register_object("/org/freedesktop/Notifications", node.interfaces[0], on_call, None, None)


def on_name(conn, name):
    print("ready", flush=True)


Gio.bus_own_name(Gio.BusType.SESSION, "org.freedesktop.Notifications", Gio.BusNameOwnerFlags.NONE, on_bus, on_name, None)
GLib.timeout_add(100, check_invoke)
GLib.MainLoop().run()
