#!/usr/bin/env python3
"""LuxOS - testy Sporice baterie, neuspavani pri prehravani a ovladani hudby v Ovladacim centru.

    python3 -m unittest packages/luxos-desktop/tests/test_luxos_power.py -v

Nic nemeni na skutecnem systemu: sysfs je falesny strom (LUXOS_SYSROOT), prikazy gdbus,
gsettings, xfconf-query, systemctl, brightnessctl a xrandr jsou falesne (PATH / LUXOS_XRANDR)
a D-Bus je soukroma sbernice (Gio.TestDBus) s falesnym prehravacem MPRIS a falesnym xfconfd.
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
PYDIR = os.path.join(ROOT, "luxos-desktop", "files", "python")
BIN = os.path.join(ROOT, "luxos-desktop", "files", "bin")
HELPER = os.path.join(ROOT, "luxos-tweaks", "files", "power", "luxos-powersaver-helper")
UNMETERED = os.path.join(ROOT, "luxos-tweaks", "files", "power", "luxos-unmetered")
FAKE_XRANDR = os.path.join(HERE, "fake-displays", "xrandr")
sys.path.insert(0, PYDIR)
sys.path.insert(1, os.path.join(ROOT, "luxos-i18n", "files"))

import gi  # noqa: E402

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

import luxos_displays as ld  # noqa: E402
import luxos_mpris  # noqa: E402


def load_program(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def read(path):
    with open(path) as f:
        return f.read().strip()


def spin(cond, timeout=3.0):
    """Toci hlavni smycku GLib, dokud neplati cond (nebo vyprsi cas)."""
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        while ctx.pending():
            ctx.iteration(False)
        if cond():
            return True
        time.sleep(0.005)
    return cond()


# =====================================================================================
# 1. Systemova cast Sporice baterie (root helper) nad falesnym sysfs
# =====================================================================================
class Helper(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="luxos-ps-root-")
        r = self.root
        write(f"{r}/sys/devices/system/cpu/intel_pstate/no_turbo", "0\n")
        write(f"{r}/sys/devices/system/cpu/cpufreq/policy0/boost", "1\n")
        write(f"{r}/sys/module/snd_hda_intel/parameters/power_save", "0\n")
        write(f"{r}/proc/sys/vm/dirty_writeback_centisecs", "500\n")
        usb = f"{r}/sys/bus/usb/devices"
        drivers = f"{r}/sys/bus/usb/drivers"

        def dev(name, cls, ifaces):
            write(f"{usb}/{name}/power/control", "on\n")
            write(f"{usb}/{name}/bDeviceClass", cls + "\n")
            for i, drv in enumerate(ifaces):
                d = f"{usb}/{name}/{name}:1.{i}"
                os.makedirs(d)
                if drv:
                    os.makedirs(f"{drivers}/{drv}", exist_ok=True)
                    os.symlink(f"{drivers}/{drv}", f"{d}/driver")
        dev("1-1", "ef", ["uvcvideo", "uvcvideo"])      # kamera -> auto
        dev("1-2", "00", ["usbhid"])                     # mys -> beze zmeny
        dev("1-3", "e0", ["btusb", "btusb"])             # Bluetooth -> beze zmeny
        dev("1-4", "ff", [None])                         # nepouzivane (bez ovladace) -> auto
        dev("1-5", "00", ["uvcvideo", "snd-usb-audio"])  # kamera s mikrofonem -> beze zmeny
        dev("usb1", "09", ["hub"])                       # hub -> beze zmeny
        self.usb = usb

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def helper(self, arg):
        r = subprocess.run(["bash", HELPER, arg], env=dict(os.environ, LUXOS_SYSROOT=self.root),
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")

    def values(self):
        r = self.root
        return {"turbo": read(f"{r}/sys/devices/system/cpu/intel_pstate/no_turbo"),
                "boost": read(f"{r}/sys/devices/system/cpu/cpufreq/policy0/boost"),
                "hda": read(f"{r}/sys/module/snd_hda_intel/parameters/power_save"),
                "wb": read(f"{r}/proc/sys/vm/dirty_writeback_centisecs"),
                **{d: read(f"{self.usb}/{d}/power/control") for d in ("1-1", "1-2", "1-3", "1-4", "1-5", "usb1")}}

    def test_on_off_restores_everything(self):
        before = self.values()
        self.helper("on")
        on = self.values()
        self.assertEqual((on["turbo"], on["boost"], on["hda"], on["wb"]), ("1", "0", "1", "1500"))
        self.assertEqual((on["1-1"], on["1-4"]), ("auto", "auto"))
        self.assertEqual((on["1-2"], on["1-3"], on["1-5"], on["usb1"]), ("on",) * 4)
        self.assertTrue(os.path.exists(f"{self.root}/run/luxos/powersaver"))
        # druhe "on" nesmi prepsat puvodni hodnoty
        self.helper("on")
        self.helper("off")
        self.assertEqual(self.values(), before)
        self.assertFalse(os.path.exists(f"{self.root}/run/luxos/powersaver"))
        self.assertFalse(os.path.exists(f"{self.root}/run/luxos/powersaver.saved"))

    def test_hda_already_saving_untouched(self):
        write(f"{self.root}/sys/module/snd_hda_intel/parameters/power_save", "10\n")
        self.helper("on")
        self.assertEqual(self.values()["hda"], "10")
        self.helper("off")
        self.assertEqual(self.values()["hda"], "10")

    def test_missing_files_and_off_without_on(self):
        shutil.rmtree(f"{self.root}/sys/devices")
        self.helper("off")          # nic ulozeno -> nic se nedeje
        self.helper("on")
        self.assertEqual(read(f"{self.root}/proc/sys/vm/dirty_writeback_centisecs"), "1500")
        self.helper("off")
        self.assertEqual(read(f"{self.root}/proc/sys/vm/dirty_writeback_centisecs"), "500")


class Unmetered(unittest.TestCase):
    def run_with(self, out, rc=0):
        d = tempfile.mkdtemp()
        try:
            write(f"{d}/busctl", f"#!/bin/sh\necho '{out}'\nexit {rc}\n")
            os.chmod(f"{d}/busctl", 0o755)
            return subprocess.run(["bash", UNMETERED], env=dict(os.environ, PATH=d + os.pathsep + os.environ["PATH"]),
                                  capture_output=True, timeout=10).returncode
        finally:
            shutil.rmtree(d)

    def test_values(self):
        self.assertEqual(self.run_with("u 1"), 1)      # merene (Sporic dat)
        self.assertEqual(self.run_with("u 3"), 1)      # odhadem merene (telefon)
        self.assertEqual(self.run_with("u 2"), 0)
        self.assertEqual(self.run_with("u 4"), 0)
        self.assertEqual(self.run_with("u 0"), 0)
        self.assertEqual(self.run_with("", rc=1), 0)   # bez NetworkManageru se nepreskakuje


# =====================================================================================
# 2. Uzivatelska cast luxos-powersaver s falesnymi prikazy
# =====================================================================================
FAKES = {
    # stav v souborech v $FAKE_STATE; volani do $FAKE_STATE/log
    "gdbus": r'''#!/bin/bash
echo "gdbus $*" >>"$FAKE_STATE/log"
if [[ $* == *Properties.Get* ]]; then echo "(<'$(cat "$FAKE_STATE/profile")'>,)"; exit 0; fi
if [[ $* == *Properties.Set* ]]; then p=${*: -1}; p=${p#<\'}; echo "${p%\'>}" >"$FAKE_STATE/profile"; fi
''',
    "gsettings": r'''#!/bin/bash
f="$FAKE_STATE/gs-$3"
case $1 in get) cat "$f" 2>/dev/null || echo true ;; set) echo "$4" >"$f" ;; esac
''',
    "xfconf-query": r'''#!/bin/bash
ch= p= v= reset=
while (($#)); do case $1 in -c) ch=$2; shift ;; -p) p=$2; shift ;; -s) v=$2; shift ;; -r) reset=1 ;; esac; shift; done
f="$FAKE_STATE/xf-$ch${p//\//_}"
if [[ -n $reset ]]; then rm -f "$f"; elif [[ -n $v ]]; then echo "$v" >"$f"; else cat "$f" 2>/dev/null || exit 1; fi
''',
    "systemctl": '#!/bin/bash\necho "systemctl $*" >>"$FAKE_STATE/log"\n',
    "brightnessctl": r'''#!/bin/bash
b="$LUXOS_BACKLIGHT/bl"; v=${*: -1}; v=${v%\%}
echo $(( v * $(cat "$b/max_brightness") / 100 )) >"$b/brightness"
''',
}


class PowersaverScript(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="luxos-ps-user-")
        self.bin = os.path.join(self.d, "bin")
        os.makedirs(self.bin)
        for name, text in FAKES.items():
            write(os.path.join(self.bin, name), text)
            os.chmod(os.path.join(self.bin, name), 0o755)
        self.state = os.path.join(self.d, "state")
        os.makedirs(self.state)
        write(f"{self.state}/profile", "performance")
        self.bl = os.path.join(self.d, "backlight")
        write(f"{self.bl}/bl/max_brightness", "1000")
        write(f"{self.bl}/bl/brightness", "900")
        self.xr = os.path.join(self.d, "xrandr.json")
        with open(self.xr, "w") as f:
            json.dump({"outputs": [
                {"name": "eDP-1", "connected": True, "edid": "", "mm": [344, 194], "primary": True,
                 "modes": [["2560x1600", ["165.00", "120.00", "60.00"]], ["1920x1200", ["165.00", "60.00"]]],
                 "preferred": ["2560x1600", "165.00"], "current": ["2560x1600", "165.00"],
                 "rotation": "normal", "pos": [0, 0]}]}, f)
        self.cfg = os.path.join(self.d, "config")
        self.env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"], FAKE_STATE=self.state,
                        XDG_CONFIG_HOME=self.cfg, LUXOS_BACKLIGHT=self.bl, LUXOS_XRANDR=FAKE_XRANDR,
                        FAKE_XRANDR_STATE=self.xr, LUXOS_DISPLAYS_PY=os.path.join(PYDIR, "luxos_displays.py"),
                        DISPLAY=":luxos-test-fake", LUXOS_SYSROOT=self.d)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def ps(self, *args):
        r = subprocess.run(["bash", os.path.join(BIN, "luxos-powersaver"), *args], env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def rate(self):
        with open(self.xr) as f:
            return json.load(f)["outputs"][0]["current"]

    def log(self):
        try:
            return read(f"{self.state}/log")
        except OSError:
            return ""

    def test_on_off_roundtrip(self):
        self.assertEqual(self.ps("status").strip(), "off")
        self.ps("on")
        self.assertEqual(self.ps("status").strip(), "on")
        self.assertEqual(read(f"{self.state}/profile"), "power-saver")
        self.assertEqual(read(f"{self.state}/gs-zoom-enabled"), "false")
        self.assertEqual(read(f"{self.state}/xf-xsettings_Gtk_EnableAnimations"), "false")
        self.assertEqual(self.rate(), ["2560x1600", "60.00"])
        self.assertEqual(read(f"{self.bl}/bl/brightness"), "720")         # 90 % -> 72 %
        self.assertIn("systemctl --no-ask-password --no-block start luxos-powersaver.service", self.log())
        # druhe zapnuti (napr. automaticke) nesmi ztlumit znovu ani prepsat puvodni hodnoty
        self.ps("on")
        self.assertEqual(read(f"{self.bl}/bl/brightness"), "720")
        self.ps("off")
        self.assertEqual(self.ps("status").strip(), "off")
        self.assertEqual(read(f"{self.state}/profile"), "performance")   # puvodni profil, ne "balanced"
        self.assertEqual(read(f"{self.state}/gs-zoom-enabled"), "true")
        self.assertFalse(os.path.exists(f"{self.state}/xf-xsettings_Gtk_EnableAnimations"))   # vychozi
        self.assertEqual(self.rate(), ["2560x1600", "165.00"])
        self.assertEqual(read(f"{self.bl}/bl/brightness"), "900")
        self.assertIn("stop luxos-powersaver.service", self.log())
        self.assertFalse(os.path.exists(f"{self.cfg}/luxos/powersaver.saved"))

    def test_user_brightness_change_kept(self):
        self.ps("on")
        write(f"{self.bl}/bl/brightness", "300")       # uzivatel si jas zmenil sam
        self.ps("off")
        self.assertEqual(read(f"{self.bl}/bl/brightness"), "300")

    def test_low_brightness_not_dimmed(self):
        write(f"{self.bl}/bl/brightness", "350")
        self.ps("on")
        self.assertEqual(read(f"{self.bl}/bl/brightness"), "350")
        self.ps("off")
        self.assertEqual(read(f"{self.bl}/bl/brightness"), "350")

    def test_reapply_after_reboot(self):
        self.ps("on")
        # restart: 165 Hz z ulozenych Monitoru, systemova cast pryc
        with open(self.xr) as f:
            st = json.load(f)
        st["outputs"][0]["current"] = ["2560x1600", "165.00"]
        with open(self.xr, "w") as f:
            json.dump(st, f)
        os.unlink(f"{self.state}/log")
        self.ps("reapply")
        self.assertEqual(self.rate(), ["2560x1600", "60.00"])
        self.assertIn("start luxos-powersaver.service", self.log())
        self.ps("off")
        self.assertEqual(self.rate(), ["2560x1600", "165.00"])

    def test_reapply_off_stops_leftover(self):
        write(f"{self.d}/run/luxos/powersaver", "")
        self.ps("reapply")
        self.assertIn("stop luxos-powersaver.service", self.log())
        os.unlink(f"{self.d}/run/luxos/powersaver")
        os.unlink(f"{self.state}/log")
        self.ps("reapply")
        self.assertEqual(self.log(), "")


class RateCap(unittest.TestCase):
    def out(self, name, rates, cur, active=True):
        return {"name": name, "connected": True, "active": active,
                "modes": [{"name": "1920x1080", "rates": rates, "current": cur, "preferred": rates[0]}]}

    def test_targets(self):
        self.assertEqual(ld.rate_cap_target(self.out("eDP-1", ["144.00", "120.00", "60.01", "59.95"], "144.00")),
                         ("1920x1080", "144.00", "60.01"))
        self.assertIsNone(ld.rate_cap_target(self.out("eDP-1", ["60.02", "48.01"], "60.02")))
        self.assertIsNone(ld.rate_cap_target(self.out("HDMI-1", ["144.00", "60.00"], "144.00")))   # externi ne
        self.assertIsNone(ld.rate_cap_target(self.out("eDP-1", ["144.00", "60.00"], "144.00", active=False)))
        self.assertIsNone(ld.rate_cap_target(self.out("eDP-1", ["165.00", "120.00"], "165.00")))   # bez 60 Hz


# =====================================================================================
# 3. Soukroma sbernice D-Bus: falesny prehravac MPRIS a xfconfd
# =====================================================================================
class ServiceThread:
    """Falesne sluzby D-Bus bezi ve vlastnim vlakne a smycce (synchronni volani testovaneho kodu
    by jinak cekalo na vlastni hlavni smycku)."""

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
        """fn(*args) ve vlakne sluzeb, vysledek zpet."""
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


class FakePlayer:
    """Prehravac na vlastnim spojeni; PlayPause zmeni stav a ohlasi ho signalem (volitelne se zpozdenim)."""

    def __init__(self, svc, address, name="org.mpris.MediaPlayer2.fakeplayer", status="Paused", signal_delay=0,
                 emit=True):
        self.svc = svc
        svc.run(self._init, address, name, status, signal_delay, emit)

    def _init(self, address, name, status, signal_delay, emit):
        self.conn = Gio.DBusConnection.new_for_address_sync(
            address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, None)
        self.status, self.delay, self.emit = status, signal_delay, emit
        self.title = "Song A"
        self.calls = []
        node = Gio.DBusNodeInfo.new_for_xml(PLAYER_XML)
        self.conn.register_object("/org/mpris/MediaPlayer2", node.interfaces[0], self.on_call, self.on_get, None)
        self.name = name
        self.conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName",
                            GLib.Variant("(su)", (name, 4)), None, 0, 2000, None)

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
        self.svc = svc
        svc.run(self._init, address)

    def _init(self, address):
        self.conn = Gio.DBusConnection.new_for_address_sync(
            address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, None)
        node = Gio.DBusNodeInfo.new_for_xml(XFCONF_XML)
        self.conn.register_object("/org/xfce/Xfconf", node.interfaces[0], self.on_call, None, None)
        self.conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName",
                            GLib.Variant("(su)", ("org.xfce.Xfconf", 4)), None, 0, 2000, None)

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


class Bus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # TestDBus odnastavi DISPLAY a DBUS_SESSION_BUS_ADDRESS - po testu je vratit (dalsi testy GUI)
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
        self.bus = Gio.DBusConnection.new_for_address_sync(
            self.address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, None)
        self.players = []

    def tearDown(self):
        for p in self.players:
            p.quit()
        self.bus.close_sync(None)
        spin(lambda: False, 0.05)

    def player(self, **kw):
        p = FakePlayer(self.svc, self.address, **kw)
        self.players.append(p)
        return p


class Mpris(Bus):
    def test_pure_state(self):
        st = luxos_mpris.player_state("org.mpris.MediaPlayer2.firefox.instance_1_23",
                                      {"PlaybackStatus": "Playing", "Metadata": {"xesam:title": "T",
                                                                                 "xesam:artist": ["A", "B"]}})
        self.assertEqual((st["app"], st["title"], st["artist"], st["playing"]), ("Firefox", "T", "A, B", True))
        players = {"org.mpris.MediaPlayer2.a": {"PlaybackStatus": "Paused", "Metadata": {"xesam:title": "x"}},
                   "org.mpris.MediaPlayer2.b": {"PlaybackStatus": "Playing"},
                   "org.mpris.MediaPlayer2.c": {"PlaybackStatus": "Stopped"}}
        self.assertEqual(luxos_mpris.pick_current(players)["bus"], "org.mpris.MediaPlayer2.b")
        players["org.mpris.MediaPlayer2.b"]["PlaybackStatus"] = "Stopped"
        self.assertEqual(luxos_mpris.pick_current(players)["bus"], "org.mpris.MediaPlayer2.a")
        self.assertIsNone(luxos_mpris.pick_current({"org.mpris.MediaPlayer2.c": {"PlaybackStatus": "Stopped"}}))

    def test_events_without_polling(self):
        p0 = self.player(status="Playing")            # bezi uz pred startem hlidace
        w = luxos_mpris.Watcher(self.bus)
        hits = []
        w.connect(lambda: hits.append(w.playing()))
        self.assertTrue(spin(lambda: w.playing()))
        self.assertEqual(w.current()["title"], "Song A")
        p0.set_status("Paused")
        self.assertTrue(spin(lambda: not w.playing()))
        p0.title = "Song B"
        p0.notify(Metadata=p0.meta())
        self.assertTrue(spin(lambda: w.current()["title"] == "Song B"))
        # novy prehravac za behu, pak jeho konec
        p1 = self.player(name="org.mpris.MediaPlayer2.other", status="Playing")
        self.assertTrue(spin(lambda: w.current() and w.current()["bus"] == p1.name))
        self.players.remove(p1)
        p1.quit()
        self.assertTrue(spin(lambda: p1.name not in w.players))
        self.assertFalse(w.playing())
        self.assertTrue(hits)

    def test_play_pause_is_immediate(self):
        p = self.player(status="Playing", signal_delay=400)    # pomaly prehravac (signal az za 0,4 s)
        w = luxos_mpris.Watcher(self.bus)
        self.assertTrue(spin(lambda: w.playing()))
        seen = []
        w.connect(lambda: seen.append((time.monotonic(), w.current()["playing"])))
        t0 = time.monotonic()
        w.call(p.name, "PlayPause")
        self.assertTrue(spin(lambda: seen))
        self.assertFalse(seen[0][1])                       # hned "pozastaveno"
        self.assertLess(seen[0][0] - t0, 0.05)             # bez cekani na prehravac
        self.assertTrue(spin(lambda: p.calls == ["PlayPause"]))
        spin(lambda: False, 0.6)
        self.assertFalse(w.playing())                       # signal prehravace stav potvrdil

    def test_silent_player_corrected(self):
        # Prehravac, ktery prikaz odmitne/ignoruje a nic neohlasi: stav se do 1 s opravi dotazem
        p = self.player(status="Playing", emit=False)
        w = luxos_mpris.Watcher(self.bus)
        self.assertTrue(spin(lambda: w.playing()))
        w.call(p.name, "Next")                              # Next stav nemeni
        self.assertTrue(w.playing())
        p.status = "Paused"                                 # zmena bez signalu (hlidac mysli "hraje")
        w.call(p.name, "PlayPause")                         # optimisticky "pozastaveno", prehravac ale spusti
        self.assertFalse(w.playing())
        self.assertTrue(spin(lambda: w.playing(), 2.0))     # dotaz po 0,7 s vrati skutecnost


class FakeWatcher:
    def __init__(self):
        self.on = False
        self.cbs = []

    def connect(self, cb):
        self.cbs.append(cb)

    def playing(self):
        return self.on

    def set(self, on):
        self.on = on
        for cb in self.cbs:
            cb()


class KeepAwakeTest(Bus):
    def setUp(self):
        super().setUp()
        self.cfg = tempfile.mkdtemp(prefix="luxos-awake-")
        self.hub = load_program("luxos_hub_test", os.path.join(BIN, "luxos-hub"))
        self.hub.SLEEP_OVERRIDE = os.path.join(self.cfg, "sleep-override")
        self.hub.SLEEP_WHILE_PLAYING = os.path.join(self.cfg, "sleep-while-playing")
        self.hub.PLAYBACK_GRACE = 1
        self.hub.read_override.__defaults__ = (self.hub.SLEEP_OVERRIDE,)
        self.hub.write_override.__defaults__ = (self.hub.SLEEP_OVERRIDE,)
        self.hub.external_monitor = lambda: False
        self.xf = FakeXfconf(self.svc, self.address, {"lid-action-on-battery": 1, "lid-action-on-ac": 3,
                                            "inactivity-on-battery": 30, "inactivity-on-ac": 14})
        self.slept = []
        self.lid = False

    def tearDown(self):
        self.svc.run(self.xf.conn.close_sync, None)
        shutil.rmtree(self.cfg, ignore_errors=True)
        super().tearDown()

    def make(self):
        w = FakeWatcher()
        ka = self.hub.KeepAwake(self.bus, None, w)
        ka.upower = lambda prop: {"OnBattery": True, "LidIsClosed": self.lid}[prop]
        ka.sleep = self.slept.append
        return w, ka

    def vals(self):
        return {k: (v.unpack() if hasattr(v, "unpack") else v) for k, v in self.xf.values.items()}

    def test_pure(self):
        d = self.hub
        self.assertEqual(d.plan_override({"lid-action-on-battery": 1, "lid-action-on-ac": 3,
                                          "inactivity-on-battery": 14, "inactivity-on-ac": 60}),
                         {"lid-action-on-battery": (1, 0), "inactivity-on-ac": (60, 14)})
        self.assertEqual(d.plan_override({"lid-action-on-battery": 0}), {})
        self.assertEqual(d.plan_restore({"lid-action-on-battery": 1, "inactivity-on-ac": 60},
                                        {"lid-action-on-battery": 0, "inactivity-on-ac": 30}),
                         {"lid-action-on-battery": 1})      # 30 nastavil mezitim uzivatel
        self.assertEqual(d.lid_sleep_action({"lid-action-on-battery": 1}, True, True, False), "Suspend")
        self.assertEqual(d.lid_sleep_action({"lid-action-on-battery": 2}, True, True, False), "Hibernate")
        self.assertIsNone(d.lid_sleep_action({"lid-action-on-battery": 1}, True, False, False))
        self.assertIsNone(d.lid_sleep_action({"lid-action-on-battery": 1}, True, True, True))
        self.assertIsNone(d.lid_sleep_action({"lid-action-on-battery": 1}, False, True, False))   # na AC bez zmeny

    def test_external_monitor(self):
        drm = os.path.join(self.cfg, "drm")
        write(f"{drm}/card1-eDP-1/status", "connected\n")
        write(f"{drm}/card1-HDMI-A-1/status", "disconnected\n")
        os.makedirs(f"{drm}/card1")
        self.assertFalse(load_program("d2", os.path.join(BIN, "luxos-hub")).external_monitor(drm))
        write(f"{drm}/card1-HDMI-A-1/status", "connected\n")
        self.assertTrue(load_program("d3", os.path.join(BIN, "luxos-hub")).external_monitor(drm))

    def test_play_with_lid_closed_then_stop(self):
        w, ka = self.make()
        w.set(True)
        self.assertEqual(self.vals(), {"lid-action-on-battery": 0, "lid-action-on-ac": 3,
                                       "inactivity-on-battery": 14, "inactivity-on-ac": 14})
        self.assertTrue(os.path.exists(self.hub.SLEEP_OVERRIDE))
        self.lid = True                       # vik zavren behem hrani - xfpm jen vypne obrazovku
        w.set(False)
        w.set(True)                           # mezera mezi skladbami: nic se nevraci
        spin(lambda: False, 1.3)
        self.assertEqual(self.vals()["lid-action-on-battery"], 0)
        w.set(False)
        self.assertTrue(spin(lambda: self.slept, 3))
        self.assertEqual(self.slept, ["Suspend"])
        self.assertEqual(self.vals(), {"lid-action-on-battery": 1, "lid-action-on-ac": 3,
                                       "inactivity-on-battery": 30, "inactivity-on-ac": 14})
        self.assertFalse(os.path.exists(self.hub.SLEEP_OVERRIDE))

    def test_lid_open_no_sleep_and_option_off(self):
        w, ka = self.make()
        w.set(True)
        open(self.hub.SLEEP_WHILE_PLAYING, "w").close()      # uzivatel volbu vypnul behem hrani
        ka.changed()
        self.assertTrue(spin(lambda: not os.path.exists(self.hub.SLEEP_OVERRIDE), 3))
        self.assertEqual(self.vals()["lid-action-on-battery"], 1)
        self.assertEqual(self.slept, [])
        w.set(False)
        w.set(True)                                              # volba vypnuta -> beze zmeny
        self.assertEqual(self.vals()["lid-action-on-battery"], 1)

    def test_crash_recovery(self):
        self.xf.values["lid-action-on-battery"] = 0
        self.hub.write_override({"lid-action-on-battery": 1})
        self.make()                                             # novy start luxos-hub
        self.assertEqual(self.vals()["lid-action-on-battery"], 1)
        self.assertFalse(os.path.exists(self.hub.SLEEP_OVERRIDE))


if __name__ == "__main__":
    unittest.main()
