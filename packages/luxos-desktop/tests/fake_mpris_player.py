#!/usr/bin/env python3
# napodoba prehravace MPRIS (jako Firefox) pro test_luxos_widgets.py
"""Fake MPRIS player (Gio). Logs every method call to $FAKE_LOG.
Control: SIGUSR1 = release bus name (like Firefox closing its media session),
SIGUSR2 = own it again (same name), SIGHUP = toggle playing externally."""
import os, sys, signal, time
from gi.repository import Gio, GLib

NAME = sys.argv[1] if len(sys.argv) > 1 else "org.mpris.MediaPlayer2.firefox.instance_1_1"
LOG = os.environ.get("FAKE_LOG", "/dev/null")
XML = """<node>
<interface name="org.mpris.MediaPlayer2"><method name="Raise"/><method name="Quit"/>
<property name="Identity" type="s" access="read"/></interface>
<interface name="org.mpris.MediaPlayer2.Player">
<method name="Play"/><method name="Pause"/><method name="PlayPause"/><method name="Stop"/>
<method name="Next"/><method name="Previous"/>
<property name="PlaybackStatus" type="s" access="read"/>
<property name="Metadata" type="a{sv}" access="read"/>
<property name="CanGoNext" type="b" access="read"/>
<property name="CanGoPrevious" type="b" access="read"/>
</interface></node>"""
state = {"status": "Playing", "title": "Song", "artist": "Artist", "owner": 0, "regs": []}
conn = Gio.bus_get_sync(Gio.BusType.SESSION)
info = Gio.DBusNodeInfo.new_for_xml(XML)


def log(s):
    with open(LOG, "a") as f:
        f.write("%.3f %s\n" % (time.time(), s))


def props():
    return {"PlaybackStatus": GLib.Variant("s", state["status"]),
            "Metadata": GLib.Variant("a{sv}", {"xesam:title": GLib.Variant("s", state["title"]),
                                                "xesam:artist": GLib.Variant("as", [state["artist"]])}),
            "CanGoNext": GLib.Variant("b", True), "CanGoPrevious": GLib.Variant("b", True)}


def emit(*keys):
    conn.emit_signal(None, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "PropertiesChanged",
                     GLib.Variant("(sa{sv}as)", ("org.mpris.MediaPlayer2.Player",
                                                 {key: props()[key] for key in keys}, [])))


def method(c, sender, path, iface, name, params, inv):
    log("call %s %s" % (iface.split(".")[-1], name))
    if name == "PlayPause":
        state["status"] = "Paused" if state["status"] == "Playing" else "Playing"
    elif name == "Play":
        state["status"] = "Playing"
    elif name in ("Pause", "Stop"):
        state["status"] = "Paused" if name == "Pause" else "Stopped"
    elif name == "Next":
        state["title"] = "Cinema Paradiso · A very long title " * 12
        state["artist"] = "Ennio Morricone · A very long artist name " * 12
    inv.return_value(None)
    if iface.endswith("Player"):
        emit("Metadata" if name == "Next" else "PlaybackStatus")


def get_prop(c, sender, path, iface, name):
    if iface.endswith("Player"):
        return props()[name]
    return GLib.Variant("s", "Fake")


def own():
    state["owner"] = Gio.bus_own_name_on_connection(conn, NAME, Gio.BusNameOwnerFlags.NONE, None, None)
    log("own")


def release(*a):
    Gio.bus_unown_name(state["owner"])
    log("release")
    return True


def again(*a):
    own()
    return True


def toggle(*a):
    state["status"] = "Paused" if state["status"] == "Playing" else "Playing"
    emit("PlaybackStatus")
    return True


for i in info.interfaces:
    state["regs"].append(conn.register_object("/org/mpris/MediaPlayer2", i, method, get_prop, None))
try:
    from gi.repository import GLibUnix
    add_signal = GLibUnix.signal_add
except ImportError:
    add_signal = GLib.unix_signal_add
own()
add_signal(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, release)
add_signal(GLib.PRIORITY_DEFAULT, signal.SIGUSR2, again)
add_signal(GLib.PRIORITY_DEFAULT, signal.SIGHUP, toggle)
GLib.MainLoop().run()
