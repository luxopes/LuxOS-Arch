#!/usr/bin/env python3
"""LuxOS - testy prehravacu MPRIS (luxos_mpris.lsl, ovladani hudby v Ovladacim centru) a neuspavani pri prehravani
(luxos_awake.lsl, luxos-hub) na soukrome sbernici.

    env -u DISPLAY python3 -m unittest packages/luxos-desktop/tests/test_luxos_awake.py -v

Prekladane moduly bezi v tests/lsl/luxos-awake-probe.lsl; falesny prehravac, xfconfd, UPower a
org.freedesktop.PowerManagement jsou na soukrome sbernici (Gio.TestDBus), ktera slouzi i jako systemova.
Drive testovalo puvodni luxos-hub a luxos_mpris.py v Pythonu (test_luxos_power.py).
"""
# LuxOS: testy GUI nikdy na skutecne obrazovce a v relaci uzivatele (scripts/luxos_testguard.py)
import os as _tg_os, sys as _tg_sys  # noqa: E401
_tg_d = _tg_os.path.dirname(_tg_os.path.abspath(__file__))
while _tg_d != "/" and not _tg_os.path.exists(_tg_os.path.join(_tg_d, "scripts", "luxos_testguard.py")):
    _tg_d = _tg_os.path.dirname(_tg_d)
if _tg_d != "/":
    _tg_sys.path.insert(0, _tg_os.path.join(_tg_d, "scripts"))
    import luxos_testguard  # noqa: E402,F401
else:
    _tg_os.environ.pop("DISPLAY", None)
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import gi  # noqa: E402

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LSL_DIR = os.path.join(HERE, "..", "files", "lsl")
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
sys.path.insert(0, HERE)
import lsl_app  # noqa: E402

# az v setUpModule: test_luxos_hub_lsl a test_luxos_gpu odsud importuji falesne sluzby
TMP = PROBE = None


def setUpModule():
    global TMP, PROBE
    if not LSLC:
        raise unittest.SkipTest("lslc (lsl) is not installed")
    TMP = tempfile.mkdtemp(prefix="luxos-awake-test-")
    PROBE = os.path.join(TMP, "luxos-awake-probe")
    r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", LSL_DIR,
                        os.path.join(HERE, "lsl", "luxos-awake-probe.lsl"), PROBE],
                       capture_output=True, text=True, timeout=900)
    if r.returncode:
        raise AssertionError("lslc failed: " + (r.stdout + r.stderr)[-3000:])


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def wait(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


class ServiceThread:
    """Falesne sluzby D-Bus ve vlastnim vlakne a smycce."""

    def __init__(self):
        self.ctx = GLib.MainContext.new()
        self.loop = GLib.MainLoop.new(self.ctx, False)
        self.thread = threading.Thread(target=self._run, daemon=True)
        ready = threading.Event()
        self.ctx.invoke_full(GLib.PRIORITY_DEFAULT, lambda: ready.set() or False)
        self.thread.start()
        ready.wait(5)

    def _run(self):
        self.ctx.push_thread_default()
        self.loop.run()
        self.ctx.pop_thread_default()

    def run(self, fn, *args):
        box, done = [], threading.Event()

        def call():
            try:
                box.append(fn(*args))
            finally:
                done.set()
            return False
        self.ctx.invoke_full(GLib.PRIORITY_DEFAULT, call)
        done.wait(5)
        return box[0] if box else None

    def timeout(self, ms, fn):
        src = GLib.timeout_source_new(ms)
        src.set_callback(lambda *_a: fn() and False)
        src.attach(self.ctx)

    def stop(self):
        self.loop.quit()
        self.thread.join(5)


PLAYER_XML = """<node>
<interface name="org.mpris.MediaPlayer2.Player">
  <method name="PlayPause"/><method name="Next"/><method name="Previous"/>
  <property name="PlaybackStatus" type="s" access="read"/>
  <property name="Metadata" type="a{sv}" access="read"/>
  <property name="CanGoNext" type="b" access="read"/>
  <property name="CanGoPrevious" type="b" access="read"/>
</interface></node>"""

XFCONF_XML = """<node><interface name="org.xfce.Xfconf">
  <method name="GetProperty"><arg type="s" direction="in"/><arg type="s" direction="in"/>
    <arg type="v" direction="out"/></method>
  <method name="SetProperty"><arg type="s" direction="in"/><arg type="s" direction="in"/>
    <arg type="v" direction="in"/></method>
</interface></node>"""

UPOWER_XML = """<node><interface name="org.freedesktop.UPower">
  <property name="OnBattery" type="b" access="read"/>
  <property name="LidIsClosed" type="b" access="read"/>
</interface></node>"""

PM_XML = """<node><interface name="org.freedesktop.PowerManagement">
  <method name="Suspend"/><method name="Hibernate"/>
</interface></node>"""


def connect(address):
    return Gio.DBusConnection.new_for_address_sync(
        address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
        None, None)


def own(conn, name):
    conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName",
                   GLib.Variant("(su)", (name, 4)), None, 0, 2000, None)


class FakePlayer:
    """Prehravac na vlastnim spojeni; PlayPause zmeni stav a ohlasi ho signalem (volitelne se zpozdenim)."""

    def __init__(self, svc, address, name="org.mpris.MediaPlayer2.fakeplayer", status="Paused", signal_delay=0,
                 emit=True):
        self.svc = svc
        svc.run(self._init, address, name, status, signal_delay, emit)

    def _init(self, address, name, status, signal_delay, emit):
        self.conn = connect(address)
        self.status, self.delay, self.emit = status, signal_delay, emit
        self.title = "Song A"
        self.calls = []
        node = Gio.DBusNodeInfo.new_for_xml(PLAYER_XML)
        self.conn.register_object("/org/mpris/MediaPlayer2", node.interfaces[0], self.on_call, self.on_get, None)
        self.name = name
        own(self.conn, name)

    def meta(self):
        return GLib.Variant("a{sv}", {"xesam:title": GLib.Variant("s", self.title),
                                      "xesam:artist": GLib.Variant("as", ["Artist"])})

    def on_get(self, _c, _s, _p, _i, prop):
        return {"PlaybackStatus": GLib.Variant("s", self.status), "Metadata": self.meta(),
                "CanGoNext": GLib.Variant("b", True), "CanGoPrevious": GLib.Variant("b", False)}[prop]

    def on_call(self, _c, _s, _p, _i, method, _params, inv):
        self.calls.append(method)
        if method == "PlayPause":
            self.status = "Paused" if self.status == "Playing" else "Playing"
            if self.emit:
                self.svc.timeout(self.delay, self.notify)
        inv.return_value(None)

    def notify(self, **extra):
        self.svc.run(self._notify, extra)

    def _notify(self, extra):
        changed = {"PlaybackStatus": GLib.Variant("s", self.status), **extra}
        self.conn.emit_signal(None, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties",
                              "PropertiesChanged",
                              GLib.Variant("(sa{sv}as)", ("org.mpris.MediaPlayer2.Player", changed, [])))
        return False

    def set_status(self, st):
        self.status = st
        self.notify()

    def quit(self):
        self.svc.run(self.conn.close_sync, None)


class FakeXfconf:
    def __init__(self, svc, address, values):
        self.values = dict(values)
        svc.run(self._init, address)

    def _init(self, address):
        self.conn = connect(address)
        node = Gio.DBusNodeInfo.new_for_xml(XFCONF_XML)
        self.conn.register_object("/org/xfce/Xfconf", node.interfaces[0], self.on_call, None, None)
        own(self.conn, "org.xfce.Xfconf")

    def on_call(self, _c, _s, _p, _i, method, params, inv):
        args = params.unpack()
        key = args[1].rsplit("/", 1)[-1]
        if method == "GetProperty":
            if key in self.values:
                inv.return_value(GLib.Variant("(v)", (GLib.Variant("u", self.values[key]),)))
            else:
                inv.return_dbus_error("org.xfce.Xfconf.Error.PropertyNotFound", key)
        else:
            self.values[key] = args[2]
            inv.return_value(None)


class FakePower:
    """UPower (OnBattery, LidIsClosed) a org.freedesktop.PowerManagement xfce4-power-manageru (zaznam uspani)."""

    def __init__(self, svc, address):
        self.on_battery, self.lid, self.slept = True, False, []
        svc.run(self._init, address)

    def _init(self, address):
        self.conn = connect(address)
        up = Gio.DBusNodeInfo.new_for_xml(UPOWER_XML).interfaces[0]
        self.conn.register_object("/org/freedesktop/UPower", up, None, self.on_get, None)
        pm = Gio.DBusNodeInfo.new_for_xml(PM_XML).interfaces[0]
        self.conn.register_object("/org/freedesktop/PowerManagement", pm, self.on_call, None, None)
        own(self.conn, "org.freedesktop.UPower")
        own(self.conn, "org.freedesktop.PowerManagement")

    def on_get(self, _c, _s, _p, _i, prop):
        return GLib.Variant("b", {"OnBattery": self.on_battery, "LidIsClosed": self.lid}[prop])

    def on_call(self, _c, _s, _p, _i, method, _params, inv):
        self.slept.append(method)
        inv.return_value(None)


class Probe(lsl_app.App):
    def __init__(self, mode, env):
        super().__init__([PROBE, mode], env)
        self.state = None

    def until(self, cond, timeout=3.0):
        """Ceka na radek "changed", po kterem plati cond(stav)."""
        end = time.monotonic() + timeout
        if self.state is not None and cond(self.state):
            return True
        while time.monotonic() < end:
            try:
                self.state = json.loads(self.line("changed ", max(0.01, end - time.monotonic())))
            except AssertionError:
                break
            if cond(self.state):
                return True
        return False


class Bus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved_env = {k: os.environ.get(k) for k in ("DISPLAY", "DBUS_SESSION_BUS_ADDRESS")}
        cls.tdbus = Gio.TestDBus.new(Gio.TestDBusFlags.NONE)
        cls.tdbus.up()
        cls.address = cls.tdbus.get_bus_address()
        cls.svc = ServiceThread()

    @classmethod
    def tearDownClass(cls):
        cls.svc.stop()
        cls.tdbus.down()
        for k, v in cls.saved_env.items():
            if v is not None:
                os.environ[k] = v

    def setUp(self):
        self.players = []
        self.probes = []
        self.cfg = tempfile.mkdtemp(prefix="cfg-", dir=TMP)
        self.drm = os.path.join(self.cfg, "drm")
        os.makedirs(self.drm)

    def tearDown(self):
        for p in self.probes:
            p.stop()
        for p in self.players:
            p.quit()
        shutil.rmtree(self.cfg, ignore_errors=True)

    def player(self, **kw):
        p = FakePlayer(self.svc, self.address, **kw)
        self.players.append(p)
        return p

    def probe(self, mode):
        env = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "DISPLAY")}
        env.update(DBUS_SESSION_BUS_ADDRESS=self.address, DBUS_SYSTEM_BUS_ADDRESS=self.address,
                   XDG_CONFIG_HOME=self.cfg, LUXOS_PLAYBACK_GRACE="1", LUXOS_DRM_DIR=self.drm)
        p = Probe(mode, env)
        self.probes.append(p)
        return p


class Pure(unittest.TestCase):
    def test_pure(self):
        r = subprocess.run([PROBE, "pure"], capture_output=True, text=True, timeout=30)
        lines = r.stdout.splitlines()
        self.assertEqual([x for x in lines if not x.startswith("ok ")], [])
        self.assertEqual(len(lines), 12)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_external_monitor(self):
        with tempfile.TemporaryDirectory(dir=TMP) as d:
            drm = os.path.join(d, "drm")
            write(f"{drm}/card1-eDP-1/status", "connected\n")
            write(f"{drm}/card1-HDMI-A-1/status", "disconnected\n")
            os.makedirs(f"{drm}/card1")

            def external():
                r = subprocess.run([PROBE, "external"], env=dict(os.environ, LUXOS_DRM_DIR=drm),
                                   capture_output=True, text=True, timeout=30)
                return r.stdout.strip()
            self.assertEqual(external(), "external False")
            write(f"{drm}/card1-HDMI-A-1/status", "connected\n")
            self.assertEqual(external(), "external True")


class Mpris(Bus):
    def test_events_without_polling(self):
        p0 = self.player(status="Playing")            # bezi uz pred startem hlidace
        w = self.probe("mpris")
        self.assertTrue(w.until(lambda s: s["playing"]))
        self.assertEqual(w.state["current"]["title"], "Song A")
        p0.set_status("Paused")
        self.assertTrue(w.until(lambda s: not s["playing"]))
        p0.title = "Song B"
        p0.notify(Metadata=p0.meta())
        self.assertTrue(w.until(lambda s: s["current"]["title"] == "Song B"))
        # novy prehravac za behu, pak jeho konec
        p1 = self.player(name="org.mpris.MediaPlayer2.other", status="Playing")
        self.assertTrue(w.until(lambda s: s["current"] and s["current"]["bus"] == p1.name))
        self.players.remove(p1)
        p1.quit()
        self.assertTrue(w.until(lambda s: p1.name not in s["players"]))
        self.assertFalse(w.state["playing"])

    def test_play_pause_is_immediate(self):
        p = self.player(status="Playing", signal_delay=400)    # pomaly prehravac (signal az za 0,4 s)
        w = self.probe("mpris")
        self.assertTrue(w.until(lambda s: s["playing"]))
        t0 = time.monotonic()
        w.send("send %s PlayPause" % p.name)
        w.state = json.loads(w.line("changed ", 1.0))
        self.assertFalse(w.state["current"]["playing"])          # hned "pozastaveno"
        self.assertLess(time.monotonic() - t0, 0.2)              # bez cekani na prehravac
        self.assertTrue(wait(lambda: p.calls == ["PlayPause"]))
        time.sleep(0.6)
        w.until(lambda s: False, 0.3)
        self.assertFalse(w.state["playing"])                     # signal prehravace stav potvrdil

    def test_silent_player_corrected(self):
        # Prehravac, ktery prikaz odmitne/ignoruje a nic neohlasi: stav se do 1 s opravi dotazem
        p = self.player(status="Playing", emit=False)
        w = self.probe("mpris")
        self.assertTrue(w.until(lambda s: s["playing"]))
        w.send("send %s Next" % p.name)                          # Next stav nemeni
        self.assertTrue(wait(lambda: p.calls == ["Next"]))
        self.assertTrue(w.state["playing"])
        time.sleep(0.9)                                          # dotaz po Next (0,7 s) probehl
        p.status = "Paused"                                      # zmena bez signalu (hlidac mysli "hraje")
        w.send("send %s PlayPause" % p.name)                     # optimisticky "pozastaveno", prehravac ale spusti
        self.assertTrue(w.until(lambda s: not s["playing"], 1.0))
        self.assertTrue(w.until(lambda s: s["playing"], 2.0))    # dotaz po 0,7 s vrati skutecnost


class KeepAwake(Bus):
    def setUp(self):
        super().setUp()
        self.xf = FakeXfconf(self.svc, self.address, {"lid-action-on-battery": 1, "lid-action-on-ac": 3,
                                                      "inactivity-on-battery": 30, "inactivity-on-ac": 14})
        self.power = FakePower(self.svc, self.address)
        self.override = os.path.join(self.cfg, "luxos", "sleep-override")
        self.option = os.path.join(self.cfg, "luxos", "sleep-while-playing")
        os.makedirs(os.path.dirname(self.option))    # ~/.config/luxos v relaci vzdy je (hlidani volby)

    def tearDown(self):
        super().tearDown()
        self.svc.run(self.xf.conn.close_sync, None)
        self.svc.run(self.power.conn.close_sync, None)

    def vals(self):
        return {k: (v.unpack() if hasattr(v, "unpack") else v) for k, v in self.xf.values.items()}

    def start(self):
        hub = self.probe("awake")
        hub.line("ready")
        return hub

    def test_play_with_lid_closed_then_stop(self):
        p = self.player(status="Paused")
        self.start()
        p.set_status("Playing")
        self.assertTrue(wait(lambda: self.vals()["inactivity-on-battery"] == 14))
        self.assertEqual(self.vals(), {"lid-action-on-battery": 0, "lid-action-on-ac": 3,
                                       "inactivity-on-battery": 14, "inactivity-on-ac": 14})
        self.assertTrue(os.path.exists(self.override))
        self.power.lid = True                 # vik zavren behem hrani - xfpm jen vypne obrazovku
        p.set_status("Paused")
        time.sleep(0.2)
        p.set_status("Playing")               # mezera mezi skladbami: nic se nevraci
        time.sleep(1.3)
        self.assertEqual(self.vals()["lid-action-on-battery"], 0)
        p.set_status("Paused")
        self.assertTrue(wait(lambda: self.power.slept, 4))
        self.assertEqual(self.power.slept, ["Suspend"])
        self.assertEqual(self.vals(), {"lid-action-on-battery": 1, "lid-action-on-ac": 3,
                                       "inactivity-on-battery": 30, "inactivity-on-ac": 14})
        self.assertFalse(os.path.exists(self.override))

    def test_lid_open_no_sleep_and_option_off(self):
        p = self.player(status="Paused")
        self.start()
        p.set_status("Playing")
        self.assertTrue(wait(lambda: os.path.exists(self.override)))
        write(self.option, "")                                   # uzivatel volbu vypnul behem hrani
        self.assertTrue(wait(lambda: not os.path.exists(self.override), 4))
        self.assertEqual(self.vals()["lid-action-on-battery"], 1)
        self.assertEqual(self.power.slept, [])
        p.set_status("Paused")
        p.set_status("Playing")                                  # volba vypnuta -> beze zmeny
        time.sleep(0.5)
        self.assertEqual(self.vals()["lid-action-on-battery"], 1)
        self.assertFalse(os.path.exists(self.override))

    def test_crash_recovery(self):
        self.xf.values["lid-action-on-battery"] = 0
        write(self.override, "lid-action-on-battery=1\n")
        self.start()                                             # novy start luxos-hub
        self.assertTrue(wait(lambda: not os.path.exists(self.override)))
        self.assertEqual(self.vals()["lid-action-on-battery"], 1)

    def test_restore_on_quit(self):
        # konec hubu behem prehravani (odhlaseni) vrati nastaveni a neuspava
        p = self.player(status="Playing")
        hub = self.start()
        self.assertTrue(wait(lambda: os.path.exists(self.override)))
        self.assertEqual(self.vals()["lid-action-on-battery"], 0)
        hub.send("quit")
        hub.line("bye")
        self.assertFalse(os.path.exists(self.override))
        self.assertEqual(self.vals()["lid-action-on-battery"], 1)
        self.assertEqual(p.calls, [])
        self.assertEqual(self.power.slept, [])


if __name__ == "__main__":
    unittest.main()
