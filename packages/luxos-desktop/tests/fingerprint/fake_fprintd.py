#!/usr/bin/env python3
"""LuxOS - napodobena sluzba fprintd (net.reactivated.Fprint) pro testy na session sbernici.

    fake_fprintd.py [--no-device] [--stages N] [--enrolled a,b] [--deny-claim] [--busy]
                    [--enroll-script r1,r2,...] [--state FILE]

--enroll-script: vysledky EnrollStatus po sobe (posledni ma done=true); vychozi N-1x
enroll-stage-passed a enroll-completed. Do --state zapisuje volani (pro kontrolu v testech).
"""
import argparse
import sys

from gi.repository import Gio, GLib

XML = """
<node>
  <interface name="net.reactivated.Fprint.Manager">
    <method name="GetDevices"><arg type="ao" direction="out"/></method>
    <method name="GetDefaultDevice"><arg type="o" direction="out"/></method>
  </interface>
  <interface name="net.reactivated.Fprint.Device">
    <method name="Claim"><arg type="s" direction="in"/></method>
    <method name="Release"/>
    <method name="ListEnrolledFingers"><arg type="s" direction="in"/><arg type="as" direction="out"/></method>
    <method name="DeleteEnrolledFinger"><arg type="s" direction="in"/></method>
    <method name="DeleteEnrolledFingers2"/>
    <method name="EnrollStart"><arg type="s" direction="in"/></method>
    <method name="EnrollStop"/>
    <signal name="EnrollStatus"><arg type="s"/><arg type="b"/></signal>
    <property name="name" type="s" access="read"/>
    <property name="num-enroll-stages" type="i" access="read"/>
    <property name="scan-type" type="s" access="read"/>
  </interface>
</node>
"""
DEV = "/net/reactivated/Fprint/Device/0"
E = "net.reactivated.Fprint.Error."

ap = argparse.ArgumentParser()
ap.add_argument("--no-device", action="store_true")
ap.add_argument("--stages", type=int, default=5)
ap.add_argument("--enrolled", default="")
ap.add_argument("--deny-claim", action="store_true")
ap.add_argument("--busy", action="store_true")
ap.add_argument("--enroll-script", default="")
ap.add_argument("--state", default="")
args = ap.parse_args()

enrolled = [f for f in args.enrolled.split(",") if f]
claimed = [None]
enrolling = [None]
log = []


def note(what):
    log.append(what)
    if args.state:
        with open(args.state, "a", encoding="utf-8") as f:
            f.write(what + "\n")


def manager_call(conn, sender, path, iface, method, params, inv):
    note(method)
    if args.no_device:
        inv.return_dbus_error(E + "NoSuchDevice", "No devices available")
    elif method == "GetDefaultDevice":
        inv.return_value(GLib.Variant("(o)", (DEV,)))
    else:
        inv.return_value(GLib.Variant("(ao)", ([DEV],)))


def device_call(conn, sender, path, iface, method, params, inv):
    note(method + (" " + params.unpack()[0] if params.n_children() else ""))
    needs_claim = method in ("DeleteEnrolledFinger", "DeleteEnrolledFingers2", "EnrollStart", "EnrollStop", "Release")
    if method == "Claim":
        if args.deny_claim:
            return inv.return_dbus_error(E + "PermissionDenied", "Not Authorized: net.reactivated.fprint.device.enroll")
        if args.busy or claimed[0]:
            return inv.return_dbus_error(E + "AlreadyInUse", "Device was already claimed")
        claimed[0] = sender
        return inv.return_value(None)
    if needs_claim and claimed[0] != sender:
        return inv.return_dbus_error(E + "ClaimDevice", "Device was not claimed before use")
    if method == "Release":
        if enrolling[0]:
            return inv.return_dbus_error(E + "AlreadyInUse", "Enrollment in progress")
        claimed[0] = None
        return inv.return_value(None)
    if method == "ListEnrolledFingers":
        if not enrolled:
            return inv.return_dbus_error(E + "NoEnrolledPrints", "Failed to discover prints")
        return inv.return_value(GLib.Variant("(as)", (list(enrolled),)))
    if method == "DeleteEnrolledFinger":
        f = params.unpack()[0]
        if f not in enrolled:
            return inv.return_dbus_error(E + "NoEnrolledPrints", "Fingerprint not enrolled")
        enrolled.remove(f)
        return inv.return_value(None)
    if method == "DeleteEnrolledFingers2":
        enrolled.clear()
        return inv.return_value(None)
    if method == "EnrollStart":
        finger = params.unpack()[0]
        enrolling[0] = finger
        script = [r for r in args.enroll_script.split(",") if r] or \
            ["enroll-stage-passed"] * (args.stages - 1) + ["enroll-completed"]
        inv.return_value(None)

        def emit(i=0):
            if enrolling[0] != finger:
                return False
            r = script[i]
            last = i == len(script) - 1
            if r == "enroll-completed":
                enrolled.append(finger)
            conn.emit_signal(None, DEV, "net.reactivated.Fprint.Device", "EnrollStatus",
                             GLib.Variant("(sb)", (r, last)))
            if not last:
                GLib.timeout_add(60, emit, i + 1)
            return False
        GLib.timeout_add(80, emit)
        return None
    if method == "EnrollStop":
        enrolling[0] = None
        return inv.return_value(None)
    inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)


def device_prop(conn, sender, path, iface, prop):
    return {"name": GLib.Variant("s", "Fake Sensor 3000"),
            "num-enroll-stages": GLib.Variant("i", args.stages),
            "scan-type": GLib.Variant("s", "press")}[prop]


def on_bus(conn, _name):
    info = Gio.DBusNodeInfo.new_for_xml(XML)
    conn.register_object(MANAGER_PATH, info.interfaces[0], manager_call, None, None)
    conn.register_object(DEV, info.interfaces[1], device_call, device_prop, None)


MANAGER_PATH = "/net/reactivated/Fprint/Manager"
loop = GLib.MainLoop()
Gio.bus_own_name(Gio.BusType.SESSION, "net.reactivated.Fprint", Gio.BusNameOwnerFlags.NONE,
                 on_bus, lambda *_a: print("ready", flush=True), lambda *_a: sys.exit(3))
loop.run()
