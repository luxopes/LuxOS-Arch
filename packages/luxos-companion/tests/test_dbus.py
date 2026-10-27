#!/usr/bin/env python3
"""LuxOS Companion - profil BlueZ proti falesnemu BlueZ a rozhrani cz.luxos.Companion1, vse na soukrome
sbernici D-Bus (vlastni dbus-daemon spusteny testem). Skutecny BlueZ ani Bluetooth pocitace se nepouziva.

    python3 -m unittest packages/luxos-companion/tests/test_dbus.py -v
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402
from helpers import Clock, Phone, make_service, private_bus, pump  # noqa: E402

from gi.repository import Gio, GLib  # noqa: E402

from luxos_companion import SERVICE_UUID, bluez, service  # noqa: E402

DEV = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01"
DEV_UNPAIRED = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_02"
FAKE_XML = """<node>
  <interface name="org.bluez.ProfileManager1">
    <method name="RegisterProfile"><arg type="o" direction="in"/><arg type="s" direction="in"/>
      <arg type="a{sv}" direction="in"/></method>
    <method name="UnregisterProfile"><arg type="o" direction="in"/></method>
  </interface>
  <interface name="org.freedesktop.DBus.Properties">
    <method name="GetAll"><arg type="s" direction="in"/><arg type="a{sv}" direction="out"/></method>
    <method name="Set"><arg type="s" direction="in"/><arg type="s" direction="in"/>
      <arg type="v" direction="in"/></method>
  </interface>
  <interface name="org.freedesktop.DBus.ObjectManager">
    <method name="GetManagedObjects"><arg type="a{oa{sa{sv}}}" direction="out"/></method>
  </interface>
</node>"""


def connect_bus(address):
    return Gio.DBusConnection.new_for_address_sync(
        address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
        None, None)


class FakeBluez:
    """org.bluez s ProfileManager1 a Device1 (GetAll) ve vlastnim vlakne a kontextu."""

    def __init__(self, address):
        self.address = address
        self.calls = []
        self.devices = {
            DEV: {"Address": GLib.Variant("s", "AA:BB:CC:DD:EE:01"), "Alias": GLib.Variant("s", "Pixel 8 Antonín"),
                  "Paired": GLib.Variant("b", True), "Trusted": GLib.Variant("b", False)},
            DEV_UNPAIRED: {"Address": GLib.Variant("s", "AA:BB:CC:DD:EE:02"), "Alias": GLib.Variant("s", "Cizí"),
                           "Paired": GLib.Variant("b", False), "Trusted": GLib.Variant("b", False)},
        }
        self.sets = []
        ready = threading.Event()
        self.thread = threading.Thread(target=self._run, args=(ready,))
        self.thread.start()
        ready.wait(5)

    def _run(self, ready):
        self.ctx = GLib.MainContext.new()
        self.ctx.push_thread_default()
        self.loop = GLib.MainLoop.new(self.ctx, False)
        self.bus = connect_bus(self.address)
        info = Gio.DBusNodeInfo.new_for_xml(FAKE_XML)

        def manager(_b, sender, path, iface, method, params, inv):
            self.calls.append((method, params.unpack()))
            inv.return_value(None)

        def props(_b, _s, path, _i, method, params, inv):
            if method == "Set":
                iface, name, value = params.unpack()
                self.sets.append((path, iface, name, value))
                self.devices[path][name] = GLib.Variant("b", value)
                inv.return_value(None)
                return
            inv.return_value(GLib.Variant("(a{sv})", (self.devices.get(path, {}),)))

        def objects(_b, _s, _p, _i, _m, _params, inv):
            inv.return_value(GLib.Variant("(a{oa{sa{sv}}})", (
                {path: {"org.bluez.Device1": dict(props)} for path, props in self.devices.items()},)))
        self.ids = [self.bus.register_object("/org/bluez", info.interfaces[0], manager, None, None),
                    self.bus.register_object("/", info.interfaces[2], objects, None, None)]
        for path in self.devices:
            self.ids.append(self.bus.register_object(path, info.interfaces[1], props, None, None))
        self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName",
                           GLib.Variant("(su)", ("org.bluez", 4)), None, 0, 2000, None)
        ready.set()
        self.loop.run()
        self.bus.close_sync(None)        # jako konec bluetoothd: jmeno org.bluez zmizi

    def quit(self):
        if not self.thread.is_alive():
            return
        self.ctx.invoke_full(GLib.PRIORITY_DEFAULT, lambda: self.loop.quit() or False)
        self.thread.join(5)


@unittest.skipUnless(shutil.which("dbus-daemon"), "dbus-daemon missing")
class TestBluezProfile(unittest.TestCase):
    def setUp(self):
        self.proc, self.address = private_bus()
        self.addCleanup(self.proc.wait, 5)
        self.addCleanup(self.proc.terminate)
        self.fake = FakeBluez(self.address)
        self.addCleanup(self.fake.quit)
        self.bus = connect_bus(self.address)
        self.conns, self.disc, self.states = [], [], []
        self.profile = bluez.BluezProfile(self.bus, lambda fd, peer: self.conns.append((fd, peer)),
                                          self.disc.append, lambda r, e: self.states.append((r, e)))
        self.profile.start()
        self.addCleanup(self.profile.stop)
        self.assertTrue(pump(lambda: self.profile.registered, 5))

    def call_from(self, bus, device, sock):
        out = {}

        def run():
            fdl = Gio.UnixFDList.new()
            fdl.append(sock.fileno())
            try:
                bus.call_with_unix_fd_list_sync(self.bus.get_unique_name(), bluez.PROFILE_PATH, "org.bluez.Profile1",
                                                "NewConnection", GLib.Variant("(oha{sv})", (device, 0, {})), None,
                                                0, 5000, fdl, None)
                out["ok"] = True
            except GLib.Error as e:
                out["error"] = e.message
        t = threading.Thread(target=run)
        t.start()
        pump(lambda: not t.is_alive(), 5)
        t.join(1)
        return out

    def test_register_profile_options(self):
        method, (path, uuid, opts) = self.fake.calls[0]
        self.assertEqual((method, path, uuid), ("RegisterProfile", bluez.PROFILE_PATH, SERVICE_UUID))
        self.assertEqual(opts, {"Name": "LuxOS Companion", "Role": "server", "RequireAuthentication": True,
                                "RequireAuthorization": True, "AutoConnect": False})
        self.assertNotIn("Discoverable", json.dumps(opts))

    def test_new_connection_passes_socket_and_peer(self):
        a, b = socket.socketpair()
        out = self.call_from(self.fake.bus, DEV, a)
        a.close()
        self.assertEqual(out, {"ok": True})
        self.assertTrue(pump(lambda: self.conns, 5))
        fd, peer = self.conns[0]
        self.assertEqual((peer["address"], peer["name"]), ("AA:BB:CC:DD:EE:01", "Pixel 8 Antonín"))
        os.write(fd, b"hi\n")
        self.assertEqual(b.recv(10), b"hi\n")
        os.close(fd)
        b.close()

    def test_unpaired_device_rejected(self):
        a, b = socket.socketpair()
        self.call_from(self.fake.bus, DEV_UNPAIRED, a)
        a.close()
        b.settimeout(3)
        self.assertEqual(b.recv(10), b"")          # nase kopie fd se zavrela
        self.assertEqual(self.conns, [])
        b.close()

    def test_other_sender_rejected(self):
        intruder = connect_bus(self.address)
        a, b = socket.socketpair()
        out = self.call_from(intruder, DEV, a)
        self.assertIn("only BlueZ", out.get("error", ""))
        pump(timeout=0.2)
        self.assertEqual(self.conns, [])
        a.close()
        b.close()

    def test_request_disconnection_and_release(self):
        def call(method, args, sig):
            out = {}

            def run():
                self.fake.bus.call_sync(self.bus.get_unique_name(), bluez.PROFILE_PATH, "org.bluez.Profile1", method,
                                        GLib.Variant(sig, args) if sig else None, None, 0, 5000, None)
                out["ok"] = True
            t = threading.Thread(target=run)
            t.start()
            pump(lambda: not t.is_alive(), 5)
        call("RequestDisconnection", (DEV,), "(o)")
        self.assertEqual(self.disc, ["AA:BB:CC:DD:EE:01"])
        call("Release", None, None)
        self.assertFalse(self.profile.registered)

    def set_trusted(self, address, trusted):
        out = []
        self.profile.set_trusted(address, trusted, out.append)
        self.assertTrue(pump(lambda: out, 5))
        return out[0]

    def test_set_trusted(self):
        self.assertEqual(self.set_trusted("aa:bb:cc:dd:ee:01", True), 1)
        self.assertEqual(self.fake.sets, [(DEV, "org.bluez.Device1", "Trusted", True)])
        self.assertEqual(self.fake.devices[DEV_UNPAIRED]["Trusted"].unpack(), False)
        self.assertEqual(self.set_trusted("AA:BB:CC:DD:EE:01", True), 0)     # uz duveryhodny: nic
        self.assertEqual(self.set_trusted("AA:BB:CC:DD:EE:01", False), 1)
        self.assertEqual(self.fake.devices[DEV]["Trusted"].unpack(), False)
        self.assertEqual(self.set_trusted("AA:BB:CC:DD:EE:99", True), 0)     # nezname zarizeni
        self.assertEqual(len(self.fake.sets), 2)

    def test_reregister_after_bluez_restart(self):
        n = len([c for c in self.fake.calls if c[0] == "RegisterProfile"])
        self.fake.quit()
        self.assertTrue(pump(lambda: not self.profile.available, 5))
        self.assertFalse(self.profile.registered)
        self.fake = FakeBluez(self.address)
        self.addCleanup(self.fake.quit)
        self.assertTrue(pump(lambda: self.profile.registered, 5))
        self.assertEqual(len([c for c in self.fake.calls if c[0] == "RegisterProfile"]), 1)
        self.assertGreaterEqual(n, 1)


@unittest.skipUnless(shutil.which("dbus-daemon"), "dbus-daemon missing")
class TestCompanionInterface(unittest.TestCase):
    """cz.luxos.Companion1 na soukrome sbernici: GetLocation, LocationChanged, GetStatus, AnswerApproval."""

    def setUp(self):
        self.proc, self.address = private_bus()
        self.addCleanup(self.proc.wait, 5)
        self.addCleanup(self.proc.terminate)
        self.bus = connect_bus(self.address)
        self.clock = Clock()
        self.svc = make_service(self.clock)
        self.svc.bus = self.bus
        self.svc.export()
        self.addCleanup(self.svc.unexport)
        self.client = connect_bus(self.address)
        self.signals = []
        self.client.signal_subscribe(None, "cz.luxos.Companion1", None, "/cz/luxos/Companion1", None, 0,
                                     lambda *a: self.signals.append((a[4], a[5].unpack())))

    def call(self, method, args=None):
        out = {}

        def run():
            try:
                out["r"] = self.client.call_sync(self.bus.get_unique_name(), "/cz/luxos/Companion1",
                                                 "cz.luxos.Companion1", method, args, None, 0, 5000, None).unpack()
            except GLib.Error as e:
                out["e"] = e.message
        t = threading.Thread(target=run)
        t.start()
        pump(lambda: not t.is_alive(), 5)
        return out.get("r", out.get("e"))

    def test_location_over_dbus(self):
        self.assertEqual(self.call("GetLocation")[0], {"valid": False})
        a, b = socket.socketpair()
        s = self.svc.new_connection(a.detach(), helpers.PHONE)
        phone = Phone(b)
        phone.send("hello", "h1", protocol=1)
        phone.wait(1)
        phone.send("location.update", latitude=50.0755, longitude=14.4378, accuracy_m=6.5,
                   timestamp_ms=1793098800000, age_ms=500, speed_mps=1.3, mock=False)
        self.assertTrue(pump(lambda: any(n == "LocationChanged" and v[0].get("valid") for n, v in self.signals), 5))
        loc = self.call("GetLocation")[0]
        self.assertEqual((loc["valid"], loc["latitude"], loc["longitude"], loc["accuracy"], loc["speed"]),
                         (True, 50.0755, 14.4378, 6.5, 1.3))
        self.assertEqual(loc["age_ms"], 500)
        self.assertNotIn("altitude", loc)
        # zastarani po 15 s: signal valid=false
        self.signals.clear()
        self.clock.advance(14.6)
        self.svc.tick()
        self.assertTrue(pump(lambda: any(n == "LocationChanged" and not v[0]["valid"] for n, v in self.signals), 5))
        s.close("test")

    def test_status_and_approval_over_dbus(self):
        st = json.loads(self.call("GetStatus")[0])
        self.assertEqual((st["connections"], st["pending"]), ([], []))
        a, b = socket.socketpair()
        stranger = {"address": "AA:BB:CC:DD:EE:77", "name": "Nový"}
        s = self.svc.new_connection(a.detach(), stranger)
        phone = Phone(b)
        phone.send("hello", "h1", protocol=1)
        self.assertTrue(pump(lambda: s.state == "approving", 5))
        st = json.loads(self.call("GetStatus")[0])
        self.assertEqual(st["pending"], [{"address": "AA:BB:CC:DD:EE:77", "name": "Nový"}])
        self.call("AnswerApproval", GLib.Variant("(sb)", ("aa:bb:cc:dd:ee:77", True)))
        self.assertEqual(phone.wait(1)[0]["type"], "hello.ok")
        self.assertTrue(self.svc.settings.is_approved("AA:BB:CC:DD:EE:77"))
        self.assertTrue(pump(lambda: any(n == "StatusChanged" for n, _v in self.signals), 5))
        self.call("Disconnect", GLib.Variant("(s)", ("AA:BB:CC:DD:EE:77",)))
        self.assertTrue(phone.wait_closed())

    def test_property(self):
        out = {}

        def run():
            out["r"] = self.client.call_sync(self.bus.get_unique_name(), "/cz/luxos/Companion1",
                                             "org.freedesktop.DBus.Properties", "Get",
                                             GLib.Variant("(ss)", ("cz.luxos.Companion1", "CurrentLocation")),
                                             None, 0, 5000, None).unpack()
        t = threading.Thread(target=run)
        t.start()
        pump(lambda: not t.is_alive(), 5)
        self.assertEqual(out["r"][0], {"valid": False})


@unittest.skipUnless(shutil.which("dbus-daemon"), "dbus-daemon missing")
class TestServiceProcess(unittest.TestCase):
    """luxos-companion --service jako proces: sbernice relace i "systemova" sbernice BlueZ jsou soukrome."""

    def test_service_lifecycle(self):
        proc, address = private_bus()
        self.addCleanup(proc.wait, 5)
        self.addCleanup(proc.terminate)
        fake = FakeBluez(address)
        self.addCleanup(fake.quit)
        env = dict(os.environ, DBUS_SESSION_BUS_ADDRESS=address, LUXOS_COMPANION_BLUEZ_BUS=address)
        env.pop("DISPLAY", None)
        env.pop("LUXOS_COMPANION_QUIET", None)
        exe = os.path.join(helpers.FILES, "luxos-companion")
        svc = subprocess.Popen([sys.executable, exe, "--service"], env=env, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: svc.poll() is None and svc.kill())
        bus = connect_bus(address)

        def status():
            r = subprocess.run([sys.executable, exe, "--status"], env=env, capture_output=True, text=True)
            return json.loads(r.stdout)

        def status_safe():
            r = subprocess.run([sys.executable, exe, "--status"], env=env, capture_output=True, text=True)
            return (r.returncode, r.stdout[-500:], r.stderr[-1500:])
        ok = pump(lambda: status().get("bluetooth", {}).get("registered"), 10)
        if not ok:
            svc.kill()
            err = svc.communicate(timeout=5)[1]
            self.fail("service did not register the profile; status=%r stderr=%s" % (status_safe(), err[-3000:]))
        st = status()
        self.assertEqual((st["running"], st["connections"], st["phone_location"]), (True, [], {"valid": False}))
        # druha instance skonci a profil prvni nechá byt
        second = subprocess.run([sys.executable, exe, "--service"], env=env, capture_output=True, text=True,
                                timeout=20)
        self.assertEqual(second.returncode, 0)
        self.assertIn("already running", second.stderr)
        self.assertEqual([c[0] for c in fake.calls], ["RegisterProfile"])
        svc.terminate()
        self.assertEqual(svc.wait(10), 0)
        self.assertEqual([c[0] for c in fake.calls], ["RegisterProfile", "UnregisterProfile"])
        bus.close_sync(None)


class TestServiceVariant(unittest.TestCase):
    def test_location_variant_types(self):
        v = GLib.Variant("a{sv}", service.location_variant({"valid": True, "latitude": 1.0, "longitude": 2.0,
                                                            "accuracy": 3.0, "timestamp_ms": 2 ** 41, "age_ms": 5,
                                                            "mock": False, "device": "P", "bearing": 90.0}))
        self.assertEqual(v.unpack()["timestamp_ms"], 2 ** 41)


def tearDownModule():
    shutil.rmtree(helpers.TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
