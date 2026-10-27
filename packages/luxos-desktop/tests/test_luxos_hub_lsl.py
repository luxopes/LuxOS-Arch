"""Testy luxos-hub v LSL (files/lsl/luxos-hub.lsl): okna Ovladaciho centra a Kalendare na signaly,
"!" pro sit bez internetu, upozorneni earlyoom, Trezor, neuspavani pri prehravani, agent BlueZ,
LuxOS Care, Ovladace a upozorneni na zmenu casu. Vse na soukrome sbernici D-Bus (Gio.TestDBus slouzi jako session i system bus)
s falesnymi sluzbami a falesnymi programy v PATH; okna pod Xvfb.

Spusteni: env -u DISPLAY xvfb-run -a python3 -m unittest packages/luxos-desktop/tests/test_luxos_hub_lsl.py -v
LUXOS_LSLC: prekladac lslc (LSL >= 0.10.6, jinak se testy preskoci). Nikdy ne na skutecne obrazovce.
"""
import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LSL = os.path.join(HERE, "..", "files", "lsl")
I18N_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "luxos-i18n", "files"))
TMP = tempfile.mkdtemp(prefix="luxos-lslhub-")   # bez "luxos-hub" v ceste: podle ni se pozna bezici hub
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
sys.path.insert(0, HERE)
sys.path.insert(0, I18N_DIR)

import gi  # noqa: E402

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from test_luxos_power import PLAYER_XML, FakePlayer, FakeXfconf, ServiceThread, spin  # noqa: E402,F401


def translation(key):
    with open(os.path.join(I18N_DIR, "cs.tsv"), encoding="utf-8") as f:
        for line in f:
            k, _, v = line.rstrip("\n").partition("\t")
            if k == key:
                return v
    raise KeyError(key)


def build():
    """Prelozi luxos-hub (a jeho dve jmena) z files/lsl; None bez vhodneho prekladace."""
    if not LSLC or not os.environ.get("DISPLAY"):
        return None
    src = os.path.join(TMP, "src")
    os.makedirs(src, exist_ok=True)
    for f in glob.glob(os.path.join(LSL, "*.lsl")):
        shutil.copy(f, src)
    out = os.path.join(TMP, "bin")
    os.makedirs(out, exist_ok=True)
    r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", os.path.join(src, "luxos-hub.lsl"), os.path.join(out, "luxos-hub")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        return None
    for name in ("luxos-control-center", "luxos-calendar"):
        os.symlink("luxos-hub", os.path.join(out, name))
    # maly klient Snimku obrazovky (pozadavky na hub pres socket)
    r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", os.path.join(src, "luxos-screenshot.lsl"), os.path.join(out, "luxos-screenshot")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        return None
    return out


BIN = build()
DISPLAY = os.environ.get("DISPLAY")
# Snimek cele (virtualni) obrazovky pro LUXOS_TEST_SHOTS
SHOT = ("import sys, gi\ngi.require_version('Gdk', '3.0')\nfrom gi.repository import Gdk\n"
        "r = Gdk.get_default_root_window()\n"
        "Gdk.pixbuf_get_from_window(r, 0, 0, r.get_width(), r.get_height()).savev(sys.argv[1], 'png', [], [])\n")

NM_XML = """<node><interface name="org.freedesktop.NetworkManager">
  <property name="State" type="u" access="read"/><property name="Connectivity" type="u" access="read"/>
</interface></node>"""
PANEL_XML = """<node><interface name="org.xfce.Panel">
  <method name="PluginEvent"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/></method>
</interface></node>"""
XFCONF_SIGNAL_XML = """<node><interface name="org.xfce.Xfconf">
  <signal name="PropertyChanged"><arg type="s"/><arg type="s"/><arg type="v"/></signal>
</interface></node>"""
NOTIFY_XML = """<node><interface name="org.freedesktop.Notifications">
  <method name="Notify"><arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/>
    <arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/><arg type="a{sv}" direction="in"/>
    <arg type="i" direction="in"/><arg type="u" direction="out"/></method>
  <signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
</interface></node>"""
LOGIN_XML = """<node><interface name="org.freedesktop.login1.Manager">
  <method name="Inhibit"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/>
    <arg type="s" direction="in"/><arg type="h" direction="out"/></method>
  <signal name="PrepareForSleep"><arg type="b"/></signal>
</interface></node>"""
BLUEZ_XML = """<node><interface name="org.bluez.AgentManager1">
  <method name="RegisterAgent"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
  <method name="RequestDefaultAgent"><arg type="o" direction="in"/></method>
</interface></node>"""
DEVICE_XML = """<node><interface name="org.freedesktop.DBus.Properties">
  <method name="GetAll"><arg type="s" direction="in"/><arg type="a{sv}" direction="out"/></method>
</interface></node>"""


class FakeService:
    """Falesna sluzba na soukrome sbernici: jmeno, objekty s XML a obsluhou volani; zaznam volani."""

    def __init__(self, svc, address, name, objects, properties=None):
        self.svc, self.calls, self.properties = svc, [], properties or {}
        svc.run(self._init, address, name, objects)

    def _init(self, address, name, objects):
        self.conn = Gio.DBusConnection.new_for_address_sync(
            address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
        for path, xml in objects:
            node = Gio.DBusNodeInfo.new_for_xml(xml)
            self.conn.register_object(path, node.interfaces[0], self.on_call, self.on_get, None)
        self.conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "RequestName",
                            GLib.Variant("(su)", (name, 4)), None, 0, 2000, None)

    def on_get(self, _c, _s, path, iface, prop):
        return self.properties[prop]

    def on_call(self, _c, _s, path, iface, method, params, inv):
        args = params.unpack()
        self.calls.append((method, args))
        if method == "Notify":
            inv.return_value(GLib.Variant("(u)", (len(self.calls) + 40,)))
        elif method == "Inhibit":
            fds = Gio.UnixFDList.new()
            r, w = os.pipe()
            os.close(w)
            idx = fds.append(r)
            os.close(r)
            inv.return_value_with_unix_fd_list(GLib.Variant("(h)", (idx,)), fds)
        elif method == "GetAll":
            inv.return_value(GLib.Variant("(a{sv})", ({k: v for k, v in self.properties.items()},)))
        else:
            inv.return_value(None)

    def emit(self, path, iface, name, variant):
        self.svc.run(self.conn.emit_signal, None, path, iface, name, variant)

    def close(self):
        self.svc.run(self.conn.close_sync, None)


@unittest.skipUnless(BIN, "chybi lslc (LSL >= 0.10.6, LUXOS_LSLC) nebo DISPLAY (spustit pod xvfb-run)")
class Hub(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tdbus = Gio.TestDBus.new(Gio.TestDBusFlags.NONE)
        cls.tdbus.up()
        cls.address = cls.tdbus.get_bus_address()
        cls.svc = ServiceThread()
        cls.fake = os.path.join(TMP, "fake")
        os.makedirs(cls.fake, exist_ok=True)
        for name in ("notify-send", "luxos-datasaver", "luxos-appearance", "luxos-safe", "luxos-powersaver", "brightnessctl",
                     "luxos-displays", "xfce4-panel", "luxos-update", "luxos-drivers", "xfce4-session-logout", "nmcli", "pactl"):
            with open(os.path.join(cls.fake, name), "w") as f:
                f.write('#!/bin/sh\nprintf "%s\\n" "$(basename "$0") $*" >>"$FAKE_LOG"\n')
            os.chmod(os.path.join(cls.fake, name), 0o755)
        # xfconf-query: panel s pluginem luxos-netcheck (id 5), jinak nic
        with open(os.path.join(cls.fake, "xfconf-query"), "w") as f:
            f.write('#!/bin/sh\nprintf "%s\\n" "xfconf-query $*" >>"$FAKE_LOG"\n'
                    'case "$*" in\n  "-c xfce4-panel -l -p /plugins") printf "/plugins/plugin-1\\n/plugins/plugin-5\\n/plugins/plugin-5/command\\n";;\n'
                    '  "-c xfce4-panel -p /plugins/plugin-5/command") echo luxos-netcheck;;\n  *) echo false;;\nesac\n')
        os.chmod(os.path.join(cls.fake, "xfconf-query"), 0o755)
        # okno prihlaseni do site: zapise se a ceka, dokud ho hub neukonci
        with open(os.path.join(cls.fake, "luxos-network-login"), "w") as f:
            f.write('#!/bin/sh\necho "luxos-network-login $$ $*" >>"$FAKE_LOG"\nexec sleep 60\n')
        os.chmod(os.path.join(cls.fake, "luxos-network-login"), 0o755)
        # vlastni kontrola portalu (DNS site): odpoved z FAKE_PORTAL, jinak "none"
        with open(os.path.join(cls.fake, "luxos-portal-check"), "w") as f:
            f.write('#!/bin/sh\necho "luxos-portal-check" >>"$FAKE_LOG"\necho "${FAKE_PORTAL:-none}"\n')
        os.chmod(os.path.join(cls.fake, "luxos-portal-check"), 0o755)
        # pomocne programy Care a Ovladacu (misto Pythonu s HTTPS / luxos-hwdetect)
        cls.care_helper = os.path.join(TMP, "care_helper.py")
        with open(cls.care_helper, "w") as f:
            f.write('import json, os, sys\nopen(os.environ["FAKE_LOG"], "a").write("care-ask " + sys.argv[2] + "\\n")\n'
                    'print(json.dumps({"option": None, "info": "signed_out", "started": False}))\n')
        cls.drivers_helper = os.path.join(TMP, "drivers_helper.py")
        with open(cls.drivers_helper, "w") as f:
            f.write('import json, os\nopen(os.environ["FAKE_LOG"], "a").write("drivers-check\\n")\n'
                    'print(json.dumps({"notify": True, "names": ["Grafika NVIDIA"], "key": "nvidia-open-dkms nvidia-utils"}))\n')

    @classmethod
    def tearDownClass(cls):
        cls.svc.stop()
        cls.tdbus.down()

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="home-", dir=TMP)
        self.runtime = os.path.join(self.home, "run")
        self.cfg = os.path.join(self.home, ".config", "luxos")
        self.cache = os.path.join(self.home, ".cache", "luxos")
        for d in (self.runtime, self.cfg, self.cache):
            os.makedirs(d)
        self.log = os.path.join(self.home, "calls.log")
        self.services = []
        self.hub = None

    def tearDown(self):
        if self.hub and self.hub.poll() is None:
            self.hub.send_signal(signal.SIGTERM)
            try:
                self.hub.wait(5)
            except subprocess.TimeoutExpired:
                self.hub.kill()
        for s in self.services:
            s.close()

    def service(self, name, objects, properties=None):
        s = FakeService(self.svc, self.address, name, objects, properties)
        self.services.append(s)
        return s

    def env(self, **extra):
        env = {"PATH": self.fake + ":/usr/bin:/bin", "HOME": self.home, "XDG_RUNTIME_DIR": self.runtime,
               "XDG_CONFIG_HOME": os.path.join(self.home, ".config"), "XDG_CACHE_HOME": os.path.join(self.home, ".cache"),
               "LUXOS_I18N_DIR": I18N_DIR, "LANG": "cs_CZ.UTF-8", "FAKE_LOG": self.log, "DISPLAY": DISPLAY,
               "DBUS_SESSION_BUS_ADDRESS": self.address, "DBUS_SYSTEM_BUS_ADDRESS": self.address, "NO_AT_BRIDGE": "1",
               "LUXOS_HUB_PREBUILD_DELAY": "1", "LUXOS_HUB_NETCHECK_DELAY": "1", "LUXOS_HUB_NOINET_DELAY": "1", "LUXOS_HUB_NOINET_GRACE": "0", "LUXOS_PLAYBACK_GRACE": "1",
               "LUXOS_CC_TEST_LOG": os.path.join(self.home, "cc.log"), "LUXOS_CAL_TEST_LOG": os.path.join(self.home, "cal.log"),
               "LUXOS_CALENDAR_DIR": os.path.join(self.home, "calendar"), "LUXOS_POWER_SUPPLY": os.path.join(self.home, "nosupply"),
               "LUXOS_BACKLIGHT": os.path.join(self.home, "nobacklight"), "LUXOS_CARE_HELPER": self.care_helper,
               "LUXOS_DRIVERS_HELPER": self.drivers_helper, "LUXOS_CARE_ROOT": os.path.join(self.home, "root"),
               "LUXOS_CARE_DELAY": "1", "LUXOS_DRIVERS_DELAY": "1", "LUXOS_DRM_DIR": os.path.join(self.home, "drm"),
               "LUXOS_MOUNTINFO": os.path.join(self.home, "mountinfo"), "GTK_THEME": "Adwaita:dark",
               "LUXOS_HUB_NO_AUTOHIDE": "1",
               "LUXOS_AUDIO_HELPER": os.path.join(self.home, "no-audio-helper")}   # zvuk jen v test_audio_*      # pod Xvfb bez spravce oken by se okno hned zavrelo ztratou fokusu
        if "XAUTHORITY" in os.environ:
            env["XAUTHORITY"] = os.environ["XAUTHORITY"]
        env.update(extra)
        return env

    def start_hub(self, **extra):
        self.err_path = os.path.join(self.home, "hub.err")
        self.err_file = open(self.err_path, "w")
        self.hub = subprocess.Popen([os.path.join(BIN, "luxos-hub")], env=self.env(**extra), stderr=self.err_file, text=True)
        self.assertTrue(self.wait_for(lambda: os.path.exists(os.path.join(self.runtime, "luxos-calendar.pid")), 10), "hub se nespustil")
        time.sleep(1.5)          # start GTK a predpripravena okna (LUXOS_HUB_PREBUILD_DELAY=1)
        return self.hub

    def hub_err(self):
        with open(self.err_path) as f:
            return f.read()

    def wait_for(self, cond, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.05)
        return cond()

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return f.read().splitlines()

    def ui_log(self, name):
        path = os.path.join(self.home, name)
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return f.read().split()

    def run_prog(self, name, *args, **extra):
        return subprocess.run([os.path.join(BIN, name), *args], env=self.env(**extra), capture_output=True, text=True, timeout=20)

    # ---- okna, signaly, pid soubory ------------------------------------------------------------------
    def test_windows_on_signals_and_clean_exit(self):
        hub = self.start_hub()
        pid = str(hub.pid)
        for name in ("luxos-hub.pid", "luxos-control-center.pid", "luxos-calendar.pid"):
            with open(os.path.join(self.runtime, name)) as f:
                self.assertEqual(f.read().strip(), pid)
        hub.send_signal(signal.SIGUSR1)
        self.assertTrue(self.wait_for(lambda: self.ui_log("cc.log") == ["shown"]), (self.ui_log("cc.log"), self.hub_err()))
        hub.send_signal(signal.SIGUSR1)
        self.assertTrue(self.wait_for(lambda: self.ui_log("cc.log") == ["shown", "hidden"]), self.ui_log("cc.log"))
        hub.send_signal(signal.SIGUSR2)
        self.assertTrue(self.wait_for(lambda: "shown" in self.ui_log("cal.log")))
        # stejny program pod jmenem luxos-control-center / luxos-calendar jen posle signal bezicimu hubu
        self.assertEqual(self.run_prog("luxos-control-center").returncode, 0)
        self.assertTrue(self.wait_for(lambda: self.ui_log("cc.log") == ["shown", "hidden", "shown"]))
        self.assertEqual(self.run_prog("luxos-calendar").returncode, 0)
        self.assertTrue(self.wait_for(lambda: self.ui_log("cal.log").count("hidden") == 1))
        out = self.run_prog("luxos-control-center", "--panel")
        self.assertEqual(out.stdout, "<icon>luxos-control-center-symbolic</icon><iconclick>luxos-cc-toggle</iconclick><tool>"
                         + translation("Control Center") + "</tool>\n")
        hub.send_signal(signal.SIGTERM)
        # 143: luxos-session ho po kill spusti znovu (kod 0 by smycku ukoncil); po odhlaseni konci X
        self.assertEqual(hub.wait(5), 143)
        self.assertEqual(sorted(os.listdir(self.runtime)), [])
        err = self.hub_err()
        self.assertNotIn("CRITICAL", err, err)
        self.assertNotIn("LSL callback error", err, err)

    def test_screenshot_served_by_hub(self):
        """luxos-screenshot preda pozadavek bezicimu hubu (okna pripravena predem): snimek vyrezu a lista."""
        hub = self.start_hub()
        out = os.path.join(self.home, "shots")
        nothing = {"LUXOS_SCREENSHOT_UI": "/nonexistent"}            # bez hubu by klient selhal
        r = self.run_prog("luxos-screenshot", "--portion", "--region", "1,2,30,20", "--output", out, "--no-thumbnail", **nothing)
        self.assertEqual(r.returncode, 0, (r.stderr, self.hub_err()))
        files = os.listdir(out)
        self.assertEqual(len(files), 1, files)
        self.assertEqual(r.stdout.strip(), os.path.join(out, files[0]))
        self.assertTrue(files[0].startswith(translation("Screenshot %s at %s").split("%s")[0]))
        with open(os.path.join(out, files[0]), "rb") as f:
            head = f.read(24)
        self.assertEqual((int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")), (30, 20))
        # lista: klient ceka, dalsi spusteni ji zavre
        tb = subprocess.Popen([os.path.join(BIN, "luxos-screenshot")], env=self.env(**nothing), stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
        time.sleep(0.5)
        self.assertIsNone(tb.poll())
        self.assertEqual(self.run_prog("luxos-screenshot", "--close", **nothing).returncode, 0)
        self.assertEqual(tb.wait(5), 0)
        hub.send_signal(signal.SIGTERM)
        self.assertEqual(hub.wait(5), 143)     # po SIGTERM: luxos-session ho spusti znovu
        err = self.hub_err()
        self.assertNotIn("LSL callback error", err, err)

    def test_profile_picture_in_control_center(self):
        # ~/.face z Profilove fotky: kolecko profilu ukaze fotku (styl .avatar.photo) misto pismena
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 64, 64)
        pb.fill(0xe03030ff)
        pb.savev(os.path.join(self.home, ".face"), "png", [], [])
        hub = self.start_hub()
        hub.send_signal(signal.SIGUSR1)
        self.assertTrue(self.wait_for(lambda: "shown" in self.ui_log("cc.log")), self.hub_err())
        self.assertIn("photo", self.ui_log("cc.log"))
        hub.send_signal(signal.SIGTERM)
        self.assertEqual(hub.wait(5), 143)
        err = self.hub_err()
        self.assertNotIn("CRITICAL", err, err)
        self.assertNotIn("Theme parsing error", err, err)

    def test_standalone_control_center_and_calendar(self):
        err = open(os.path.join(self.home, "cc.err"), "w")
        cc = subprocess.Popen([os.path.join(BIN, "luxos-control-center"), "--background"], env=self.env(), stderr=err, text=True)
        try:
            self.assertTrue(self.wait_for(lambda: os.path.exists(os.path.join(self.runtime, "luxos-control-center.pid"))))
            time.sleep(1.0)
            self.assertEqual(self.run_prog("luxos-control-center").returncode, 0)        # druhe spusteni = prepnuti
            self.assertTrue(self.wait_for(lambda: self.ui_log("cc.log") == ["shown"]), (self.ui_log("cc.log"), open(os.path.join(self.home, "cc.err")).read()))
            self.assertEqual(self.run_prog("luxos-control-center").returncode, 0)
            self.assertTrue(self.wait_for(lambda: self.ui_log("cc.log") == ["shown", "hidden"]))
        finally:
            cc.send_signal(signal.SIGTERM)
            self.assertEqual(cc.wait(5), 0)
        self.assertFalse(os.path.exists(os.path.join(self.runtime, "luxos-control-center.pid")))
        cal = subprocess.Popen([os.path.join(BIN, "luxos-calendar"), "--background"], env=self.env(), stderr=err, text=True)
        try:
            self.assertTrue(self.wait_for(lambda: os.path.exists(os.path.join(self.runtime, "luxos-calendar.pid"))))
            time.sleep(1.0)
            self.assertEqual(self.run_prog("luxos-calendar").returncode, 0)
            self.assertTrue(self.wait_for(lambda: "shown" in self.ui_log("cal.log")))
        finally:
            cal.send_signal(signal.SIGTERM)
            self.assertEqual(cal.wait(5), 0)

    def test_control_center_wifi_qr_link(self):
        """Pod dlazdicemi odkaz na QR kod Wi-Fi: pripojeno = sdilet, bez site = naskenovat, vypnuto = nic."""
        fake = os.path.join(self.home, "fake-nm")
        os.makedirs(fake)
        state = os.path.join(self.home, "nmstate")
        with open(os.path.join(fake, "nmcli"), "w") as f:
            f.write('#!/bin/sh\nst=$(cat "%s")\ncase "$*" in\n'
                    '  "radio wifi") [ "$st" = off ] && echo disabled || echo enabled;;\n'
                    '  "-t -f ACTIVE,SSID device wifi") [ "$st" = on ] && printf "no:Soused\\nyes:Domov\\n" || echo "no:Soused";;\n'
                    '  "-t -f TYPE,STATE device") echo "wifi:disconnected";;\n'
                    'esac\n' % state)
        os.chmod(os.path.join(fake, "nmcli"), 0o755)
        hub = self.start_hub(PATH=fake + ":" + self.fake + ":/usr/bin:/bin")
        shown = 0
        for st, expect in (("on", "wifi-qr:share"), ("noconn", "wifi-qr:scan"), ("off", "wifi-qr:")):
            with open(state, "w") as f:
                f.write(st)
            hub.send_signal(signal.SIGUSR1)
            shown += 1
            self.assertTrue(self.wait_for(lambda: self.ui_log("cc.log").count("shown") == shown))
            self.assertTrue(self.wait_for(lambda: self.ui_log("cc.log")[-1] == expect), (st, self.ui_log("cc.log")))
            if st == "on" and os.environ.get("LUXOS_TEST_SHOTS"):
                time.sleep(0.5)
                subprocess.run([sys.executable, "-c", SHOT, os.path.join(os.environ["LUXOS_TEST_SHOTS"], "cc-wifi-qr.png")],
                               env=dict(os.environ), timeout=20)
            hub.send_signal(signal.SIGUSR1)
            self.assertTrue(self.wait_for(lambda: self.ui_log("cc.log")[-1] == "hidden"))
        err = self.hub_err()
        self.assertNotIn("LSL callback error", err, err)

    def test_calendar_weather_line(self):
        """Kalendar ukaze pod dneskem souhrn z aplikace Pocasi, jen kdyz je cerstvy (do 3 h)."""
        wdir = os.path.join(self.cache, "weather")
        os.makedirs(wdir)
        summary = {"name": "Praha", "fetched": int(time.time()) - 600, "units": "metric", "temp": 13, "max": 13,
                   "min": 6, "code": 2, "is_day": True, "condition": "Partly Cloudy", "icon": "partly-cloudy-day"}
        with open(os.path.join(wdir, "summary.json"), "w") as f:
            json.dump(summary, f)
        hub = self.start_hub()
        hub.send_signal(signal.SIGUSR2)
        self.assertTrue(self.wait_for(lambda: "weather-line" in self.ui_log("cal.log")), (self.ui_log("cal.log"), self.hub_err()))
        if os.environ.get("LUXOS_TEST_SHOTS"):
            time.sleep(0.5)
            subprocess.run([sys.executable, "-c", SHOT, os.path.join(os.environ["LUXOS_TEST_SHOTS"], "calendar-weather.png")],
                           env=dict(os.environ), timeout=20)
        hub.send_signal(signal.SIGUSR2)
        self.assertTrue(self.wait_for(lambda: self.ui_log("cal.log")[-1] == "hidden"))
        # stary souhrn (4 h) se neukaze
        summary["fetched"] -= 4 * 3600
        with open(os.path.join(wdir, "summary.json"), "w") as f:
            json.dump(summary, f)
        hub.send_signal(signal.SIGUSR2)
        self.assertTrue(self.wait_for(lambda: self.ui_log("cal.log").count("shown") == 2))
        time.sleep(0.5)
        log = self.ui_log("cal.log")
        self.assertNotIn("weather-line", log[len(log) - 1 - log[::-1].index("hidden"):], log)
        err = self.hub_err()
        self.assertNotIn("LSL callback error", err, err)

    # ---- sit bez internetu, Sporic dat ----------------------------------------------------------------
    def test_connectivity_and_networks(self):
        nm = self.service("org.freedesktop.NetworkManager", [("/org/freedesktop/NetworkManager", NM_XML)],
                          {"State": GLib.Variant("u", 70), "Connectivity": GLib.Variant("u", 3)})
        panel = self.service("org.xfce.Panel", [("/org/xfce/Panel", PANEL_XML)])
        open(os.path.join(self.cfg, "datasaver"), "w").close()
        self.start_hub()
        # po prihlaseni: obnova pluginu "!" a jedno upozorneni (bez internetu)
        self.assertTrue(self.wait_for(lambda: ("PluginEvent", ("genmon-5", "refresh", True)) in panel.calls, 8))
        self.assertTrue(self.wait_for(lambda: any(c.startswith("notify-send") for c in self.calls())))
        notes = [c for c in self.calls() if c.startswith("notify-send")]
        self.assertEqual(len(notes), 1)
        self.assertIn(translation("No internet connection"), notes[0])
        self.assertIn(translation("You are connected to the network, but the internet is not available."), notes[0])
        # zmena Connectivity -> obnova pluginu, bez dalsiho upozorneni (stav 3 -> 3 neni zmena)
        panel.calls.clear()
        nm.emit("/org/freedesktop/NetworkManager", "org.freedesktop.DBus.Properties", "PropertiesChanged",
                GLib.Variant("(sa{sv}as)", ("org.freedesktop.NetworkManager", {"Connectivity": GLib.Variant("u", 3)}, [])))
        self.assertTrue(self.wait_for(lambda: panel.calls, 5))
        time.sleep(0.5)
        self.assertEqual(len([c for c in self.calls() if c.startswith("notify-send")]), 1)
        # portal -> druhe upozorneni az po plnem pripojeni a navratu
        nm.properties["Connectivity"] = GLib.Variant("u", 4)
        nm.emit("/org/freedesktop/NetworkManager", "org.freedesktop.DBus.Properties", "PropertiesChanged",
                GLib.Variant("(sa{sv}as)", ("org.freedesktop.NetworkManager", {"Connectivity": GLib.Variant("u", 4)}, [])))
        time.sleep(1.5)
        nm.properties["Connectivity"] = GLib.Variant("u", 2)
        nm.emit("/org/freedesktop/NetworkManager", "org.freedesktop.DBus.Properties", "PropertiesChanged",
                GLib.Variant("(sa{sv}as)", ("org.freedesktop.NetworkManager", {"State": GLib.Variant("u", 70)}, [])))
        self.assertTrue(self.wait_for(lambda: len([c for c in self.calls() if c.startswith("notify-send")]) == 2, 5))
        portal_note = [c for c in self.calls() if c.startswith("notify-send")][-1]
        self.assertIn(translation("This network requires you to sign in before you can use the internet."), portal_note)
        self.assertIn("-A login=" + translation("Sign In"), portal_note)
        # sit s portalem: okno pro prihlaseni se otevre samo, jen jednou
        self.assertTrue(self.wait_for(lambda: any(c.startswith("luxos-network-login") for c in self.calls()), 5))
        login_pid = int([c for c in self.calls() if c.startswith("luxos-network-login")][0].split()[1])
        nm.emit("/org/freedesktop/NetworkManager", "org.freedesktop.DBus.Properties", "PropertiesChanged",
                GLib.Variant("(sa{sv}as)", ("org.freedesktop.NetworkManager", {"State": GLib.Variant("u", 70)}, [])))
        time.sleep(1.5)
        self.assertEqual(len([c for c in self.calls() if c.startswith("luxos-network-login")]), 1)
        # prihlaseno -> okno se zavre, upozorneni "Pripojeno"
        nm.properties["Connectivity"] = GLib.Variant("u", 4)
        nm.emit("/org/freedesktop/NetworkManager", "org.freedesktop.DBus.Properties", "PropertiesChanged",
                GLib.Variant("(sa{sv}as)", ("org.freedesktop.NetworkManager", {"Connectivity": GLib.Variant("u", 4)}, [])))
        self.assertTrue(self.wait_for(lambda: not os.path.exists(f"/proc/{login_pid}") or
                                      open(f"/proc/{login_pid}/stat").read().split()[2] == "Z", 5))
        self.assertTrue(self.wait_for(lambda: translation("Connected to the internet") in self.calls()[-1], 5))
        # nove pripojeni -> Sporic dat znovu (jen s priznakem datasaver)
        nm.emit("/org/freedesktop/NetworkManager", "org.freedesktop.DBus.Properties", "PropertiesChanged",
                GLib.Variant("(sa{sv}as)", ("org.freedesktop.NetworkManager", {"ActiveConnections": GLib.Variant("ao", [])}, [])))
        self.assertTrue(self.wait_for(lambda: "luxos-datasaver reapply" in self.calls(), 5))

    def test_portal_behind_vpn_dns(self):
        """NM hlasi jen omezene pripojeni (Tailscale DNS za portalem): portal najde luxos-portal-check."""
        nm = self.service("org.freedesktop.NetworkManager", [("/org/freedesktop/NetworkManager", NM_XML)],
                          {"State": GLib.Variant("u", 70), "Connectivity": GLib.Variant("u", 3)})
        self.service("org.xfce.Panel", [("/org/xfce/Panel", PANEL_XML)])
        self.start_hub(FAKE_PORTAL="portal http://login.portal.test/guest 10.5.0.2", LUXOS_HUB_NOINET_DELAY="3")
        self.assertTrue(self.wait_for(lambda: any(c.startswith("luxos-network-login") for c in self.calls()), 8))
        login = [c for c in self.calls() if c.startswith("luxos-network-login")]
        self.assertEqual(login[0].split()[2:], ["http://login.portal.test/guest", "10.5.0.2"])
        self.assertTrue(self.wait_for(lambda: any(translation("Sign in to the network") in c for c in self.calls()), 5))
        time.sleep(4.5)
        # portal: zadne "Bez internetu", okno jen jednou i pres dalsi kontroly
        self.assertFalse(any(translation("No internet connection") in c for c in self.calls()), self.calls())
        self.assertEqual(len([c for c in self.calls() if c.startswith("luxos-network-login")]), 1)
        login_pid = int(login[0].split()[1])
        nm.properties["Connectivity"] = GLib.Variant("u", 4)
        nm.emit("/org/freedesktop/NetworkManager", "org.freedesktop.DBus.Properties", "PropertiesChanged",
                GLib.Variant("(sa{sv}as)", ("org.freedesktop.NetworkManager", {"Connectivity": GLib.Variant("u", 4)}, [])))
        self.assertTrue(self.wait_for(lambda: not os.path.exists(f"/proc/{login_pid}") or
                                      open(f"/proc/{login_pid}/stat").read().split()[2] == "Z", 5))
        self.assertTrue(self.wait_for(lambda: translation("Connected to the internet") in self.calls()[-1], 5))

    def test_limited_without_portal_still_warns(self):
        """Omezene pripojeni bez portalu (kontrola vraci none): po limitu upozorneni Bez internetu."""
        self.service("org.freedesktop.NetworkManager", [("/org/freedesktop/NetworkManager", NM_XML)],
                     {"State": GLib.Variant("u", 70), "Connectivity": GLib.Variant("u", 3)})
        self.service("org.xfce.Panel", [("/org/xfce/Panel", PANEL_XML)])
        self.start_hub(LUXOS_HUB_NOINET_DELAY="2")
        self.assertTrue(self.wait_for(lambda: any(translation("No internet connection") in c for c in self.calls()), 8))
        self.assertIn("luxos-portal-check", self.calls())
        self.assertFalse(any(c.startswith("luxos-network-login") for c in self.calls()))

    def test_no_internet_notice_waits_for_lasting_state(self):
        """Po prihlaseni NM chvili hlasi omezene pripojeni: bez upozorneni, kdyz se do limitu pripoji."""
        nm = self.service("org.freedesktop.NetworkManager", [("/org/freedesktop/NetworkManager", NM_XML)],
                          {"State": GLib.Variant("u", 70), "Connectivity": GLib.Variant("u", 3)})
        self.service("org.xfce.Panel", [("/org/xfce/Panel", PANEL_XML)])
        self.start_hub(LUXOS_HUB_NOINET_DELAY="4")
        time.sleep(2.0)
        nm.properties["Connectivity"] = GLib.Variant("u", 4)
        nm.emit("/org/freedesktop/NetworkManager", "org.freedesktop.DBus.Properties", "PropertiesChanged",
                GLib.Variant("(sa{sv}as)", ("org.freedesktop.NetworkManager", {"Connectivity": GLib.Variant("u", 4)}, [])))
        time.sleep(5.0)
        self.assertFalse(any(translation("No internet connection") in c for c in self.calls()), self.calls())

    # ---- nedostatek pameti -------------------------------------------------------------------------------
    def test_low_memory_notification(self):
        earlyoom = self.service("net.nuetzlich.Fake", [("/", NM_XML)], {"State": GLib.Variant("u", 0), "Connectivity": GLib.Variant("u", 0)})
        self.start_hub()
        time.sleep(0.5)
        earlyoom.emit("/", "net.nuetzlich.SystemNotifications", "Notify",
                      GLib.Variant("(ss)", ("Low memory! Killing process 4242 firefox. ...", "")))
        self.assertTrue(self.wait_for(lambda: any("firefox" in c for c in self.calls()), 5))
        note = [c for c in self.calls() if c.startswith("notify-send")][0]
        self.assertIn("-u critical", note)
        self.assertIn(translation("Memory is running low"), note)
        self.assertIn(translation("“%s” used too much memory and was closed so the computer would not freeze.").replace("%s", "firefox"), note)
        # davka stejnych signalu -> jedno upozorneni
        earlyoom.emit("/", "net.nuetzlich.SystemNotifications", "Notify", GLib.Variant("(ss)", ("process 4242 firefox;", "")))
        time.sleep(0.7)
        self.assertEqual(len([c for c in self.calls() if c.startswith("notify-send")]), 1)

    # ---- Trezor --------------------------------------------------------------------------------------------
    def test_safe_locks_on_screen_lock_and_sleep(self):
        login = self.service("org.freedesktop.login1", [("/org/freedesktop/login1", LOGIN_XML)])
        saver = self.service("org.xfce.ScreenSaver", [("/org/xfce/ScreenSaver", NM_XML)], {"State": GLib.Variant("u", 0), "Connectivity": GLib.Variant("u", 0)})
        self.start_hub()
        self.assertTrue(self.wait_for(lambda: ("Inhibit", ("sleep", translation("Safe"), "Lock the Safe before sleep", "delay")) in login.calls, 5))
        saver.emit("/org/xfce/ScreenSaver", "org.xfce.ScreenSaver", "ActiveChanged", GLib.Variant("(b)", (True,)))
        self.assertTrue(self.wait_for(lambda: "luxos-safe lock --force" in self.calls(), 5))
        # volba "zamknout pri zamceni obrazovky" vypnuta -> nic
        with open(os.path.join(self.cfg, "safe.json"), "w") as f:
            json.dump({"lock_on_screen_lock": False}, f)
        saver.emit("/org/xfce/ScreenSaver", "org.xfce.ScreenSaver", "ActiveChanged", GLib.Variant("(b)", (True,)))
        time.sleep(0.7)
        self.assertEqual(self.calls().count("luxos-safe lock --force"), 1)
        # pred uspanim vzdy; po probuzeni novy inhibitor
        login.calls.clear()
        login.emit("/org/freedesktop/login1", "org.freedesktop.login1.Manager", "PrepareForSleep", GLib.Variant("(b)", (True,)))
        self.assertTrue(self.wait_for(lambda: self.calls().count("luxos-safe lock --force") == 2, 5))
        login.emit("/org/freedesktop/login1", "org.freedesktop.login1.Manager", "PrepareForSleep", GLib.Variant("(b)", (False,)))
        self.assertTrue(self.wait_for(lambda: any(c[0] == "Inhibit" for c in login.calls), 5))

    # ---- neuspavat pri prehravani ----------------------------------------------------------------------------
    def test_keep_awake_while_playing(self):
        xf = FakeXfconf(self.svc, self.address, {"lid-action-on-battery": 1, "lid-action-on-ac": 3,
                                                 "inactivity-on-battery": 30, "inactivity-on-ac": 14})
        self.services.append(type("S", (), {"close": lambda s: self.svc.run(xf.conn.close_sync, None)})())
        player = FakePlayer(self.svc, self.address, status="Playing")
        self.start_hub()
        override = os.path.join(self.cfg, "sleep-override")
        self.assertTrue(self.wait_for(lambda: os.path.exists(override), 8))
        vals = lambda: {k: (v.unpack() if hasattr(v, "unpack") else v) for k, v in xf.values.items()}  # noqa: E731
        self.assertEqual(vals(), {"lid-action-on-battery": 0, "lid-action-on-ac": 3, "inactivity-on-battery": 14, "inactivity-on-ac": 14})
        with open(override) as f:
            self.assertEqual(sorted(f.read().split()), ["inactivity-on-battery=30", "lid-action-on-battery=1"])
        player.set_status("Paused")
        self.assertTrue(self.wait_for(lambda: not os.path.exists(override), 8))      # po 1 s ticha (LUXOS_PLAYBACK_GRACE)
        self.assertEqual(vals(), {"lid-action-on-battery": 1, "lid-action-on-ac": 3, "inactivity-on-battery": 30, "inactivity-on-ac": 14})
        player.quit()

    # ---- agent BlueZ ---------------------------------------------------------------------------------------------
    def test_bluetooth_agent_registers_and_answers(self):
        bluez = self.service("org.bluez", [("/org/bluez", BLUEZ_XML), ("/org/bluez/hci0/dev_AA", DEVICE_XML)],
                             {"Alias": GLib.Variant("s", "Sluchatka"), "Trusted": GLib.Variant("b", True)})
        self.start_hub()
        self.assertTrue(self.wait_for(lambda: ("RegisterAgent", ("/org/luxos/bluetooth/agent", "KeyboardDisplay")) in bluez.calls
                                      and ("RequestDefaultAgent", ("/org/luxos/bluetooth/agent",)) in bluez.calls, 8))
        # hub ma dve spojeni (session i system na teze sbernici) bez vlastniho jmena: agent je na tom,
        # ktere odpovi; kandidati podle PID
        names = self.svc.run(bluez.conn.call_sync, "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                             "ListNames", None, None, 0, 2000, None).unpack()[0]

        def call_agent(method, params):
            for n in names:
                if not n.startswith(":"):
                    continue
                try:
                    pid = self.svc.run(bluez.conn.call_sync, "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                       "GetConnectionUnixProcessID", GLib.Variant("(s)", (n,)), None, 0, 2000, None).unpack()[0]
                except (GLib.Error, AttributeError):
                    continue
                if pid != self.hub.pid:
                    continue
                try:
                    return bluez.conn.call_sync(n, "/org/luxos/bluetooth/agent", "org.bluez.Agent1", method, params, None, 0, 5000, None)
                except GLib.Error as e:
                    if "UnknownMethod" not in e.message and "objekt neexistuje" not in e.message:
                        raise
            self.fail("agent hubu nenalezen na sbernici")
        # duveryhodne zarizeni: AuthorizeService bez dialogu, Release bez odpovedi s hodnotou
        r = call_agent("AuthorizeService", GLib.Variant("(os)", ("/org/bluez/hci0/dev_AA", "0000110b-0000-1000-8000-00805f9b34fb")))
        self.assertEqual(r.unpack(), ())
        # sluzba LuxOS Companion: bez dialogu i u neduveryhodneho zarizeni (schvaluje ji aplikace sama)
        bluez.properties["Trusted"] = GLib.Variant("b", False)
        r = call_agent("AuthorizeService", GLib.Variant("(os)", ("/org/bluez/hci0/dev_AA", "AD9B7C10-6CE5-4F35-9952-728F760FCB70")))
        self.assertEqual(r.unpack(), ())
        r = call_agent("Release", None)
        self.assertEqual(r.unpack(), ())

    # ---- tapeta prihlasovaci obrazovky ---------------------------------------------------------------------------
    def test_wallpaper_change_syncs_login_screen(self):
        """Zmena tapety plochy (xfconf xfce4-desktop .../last-image) -> jedno luxos-appearance greeter-sync."""
        xfconf = self.service("org.xfce.Xfconf", [("/org/xfce/Xfconf", XFCONF_SIGNAL_XML)])
        self.start_hub(LUXOS_HUB_WALLSYNC_DELAY="300")

        def emit(channel, prop, value):
            xfconf.emit("/org/xfce/Xfconf", "org.xfce.Xfconf", "PropertyChanged",
                        GLib.Variant("(ssv)", (channel, prop, GLib.Variant("s", value))))

        def syncs():
            return [c for c in self.calls() if c == "luxos-appearance greeter-sync"]
        # jine vlastnosti a kanaly nic nespousti
        emit("xfce4-desktop", "/backdrop/screen0/monitoreDP-1/workspace0/image-style", "5")
        emit("xfce4-panel", "/plugins/plugin-1/last-image", "x")
        time.sleep(1.0)
        self.assertEqual(syncs(), [])
        # davka zmen (vsechny monitory a plochy) -> jedno spusteni
        for mon in ("eDP-1", "HDMI-1"):
            for ws in range(4):
                emit("xfce4-desktop", f"/backdrop/screen0/monitor{mon}/workspace{ws}/last-image", "/usr/share/backgrounds/luxos/luxos-dark.jpg")
        self.assertTrue(self.wait_for(lambda: len(syncs()) == 1, 5), self.calls())
        time.sleep(0.8)
        self.assertEqual(len(syncs()), 1)
        # dalsi zmena pozdeji -> dalsi spusteni
        emit("xfce4-desktop", "/backdrop/screen0/monitoreDP-1/workspace0/last-image", "/usr/share/backgrounds/luxos/luxos-light.jpg")
        self.assertTrue(self.wait_for(lambda: len(syncs()) == 2, 5), self.calls())
        self.assertEqual(self.hub.poll(), None)

    # ---- LuxOS Care a Ovladace -----------------------------------------------------------------------------------
    def test_care_restart_notice_after_reboot(self):
        """Prechod/aktualizace jadra pred restartem: po restartu uz "Restartujte" nechodi."""
        notes = self.service("org.freedesktop.Notifications", [("/org/freedesktop/Notifications", NOTIFY_XML)])
        root = os.path.join(self.home, "root")
        os.makedirs(os.path.join(root, "var", "lib", "luxos-care"))
        os.makedirs(os.path.join(root, "proc"))
        now = int(time.time())
        with open(os.path.join(root, "proc", "stat"), "w") as f:
            f.write(f"cpu  1 2 3\nbtime {now - 30}\nprocesses 5\n")
        with open(os.path.join(root, "var", "lib", "luxos-care", "events.json"), "w") as f:
            json.dump({"seq": 2, "events": [{"seq": 1, "kind": "updated", "count": 0, "reboot": True, "time": now - 120},
                                            {"seq": 2, "kind": "problem", "title": "Disk %s is almost full", "args": ["/"], "time": now}]}, f)
        with open(os.path.join(root, "var", "lib", "luxos-care", "state.json"), "w") as f:
            json.dump({"problems": []}, f)
        self.start_hub()
        self.assertTrue(self.wait_for(lambda: any(c[1][3] == translation("LuxOS found a problem")
                                                  for c in notes.calls if c[0] == "Notify"), 10), notes.calls)
        time.sleep(0.5)
        titles = [c[1][3] for c in notes.calls if c[0] == "Notify"]
        self.assertNotIn(translation("Restart to finish the kernel update"), titles)
        self.assertNotIn(translation("LuxOS was updated"), titles)

    def test_care_and_drivers_notifications(self):
        notes = self.service("org.freedesktop.Notifications", [("/org/freedesktop/Notifications", NOTIFY_XML)])
        root = os.path.join(self.home, "root", "var", "lib", "luxos-care")
        os.makedirs(root)
        now = int(time.time())
        with open(os.path.join(root, "events.json"), "w") as f:
            json.dump({"seq": 2, "events": [{"seq": 1, "kind": "updated", "count": 7, "time": now - 60},
                                            {"seq": 2, "kind": "problem", "title": "Disk %s is almost full", "args": ["/"], "time": now}]}, f)
        with open(os.path.join(root, "state.json"), "w") as f:
            json.dump({"problems": [{"id": "p1", "title": "x", "ai": {"request_id": "0123456789ab", "status": "pending", "options": []}}]}, f)
        self.start_hub()
        self.assertTrue(self.wait_for(lambda: len([c for c in notes.calls if c[0] == "Notify"]) >= 3, 10), notes.calls)
        titles = [c[1][3] for c in notes.calls if c[0] == "Notify"]
        self.assertIn(translation("LuxOS was updated"), titles)
        self.assertIn(translation("LuxOS found a problem"), titles)
        self.assertIn(translation("Additional drivers are available"), titles)
        bodies = [c[1][4] for c in notes.calls if c[0] == "Notify"]
        self.assertIn(translation("%d packages were updated.").replace("%d", "7"), bodies)
        self.assertTrue(any("Grafika NVIDIA" in b for b in bodies))
        self.assertTrue(self.wait_for(lambda: "care-ask 0123456789ab" in self.calls() and "drivers-check" in self.calls(), 5))
        # odpoved "neprihlasen" -> dalsi upozorneni s vyzvou k prihlaseni
        self.assertTrue(self.wait_for(lambda: any(translation("Sign in to LuxAI to let LuxOS fix unknown problems.") in c[1][4]
                                                  for c in notes.calls if c[0] == "Notify"), 5))
        with open(os.path.join(self.cache, "care-seen")) as f:
            self.assertEqual(f.read().strip(), "2")
        with open(os.path.join(self.cache, "care-ai-asked")) as f:
            self.assertEqual(f.read().split(), ["0123456789ab"])
        # akce upozorneni: "open" u Care otevre luxos-update, "ignore" u Ovladacu zapise odmitnute baliky
        ids = {c[1][3]: 41 + i for i, c in enumerate(notes.calls) if c[0] == "Notify"}
        notes.emit("/org/freedesktop/Notifications", "org.freedesktop.Notifications", "ActionInvoked",
                   GLib.Variant("(us)", (ids[translation("LuxOS was updated")], "open")))
        self.assertTrue(self.wait_for(lambda: "luxos-update " in self.calls(), 5))
        notes.emit("/org/freedesktop/Notifications", "org.freedesktop.Notifications", "ActionInvoked",
                   GLib.Variant("(us)", (ids[translation("Additional drivers are available")], "ignore")))
        ignored = os.path.join(self.cfg, "drivers-ignored")
        self.assertTrue(self.wait_for(lambda: os.path.exists(ignored), 5))
        with open(ignored) as f:
            self.assertEqual(f.read().strip(), "nvidia-open-dkms nvidia-utils")
        # nova udalost v souboru -> dalsi upozorneni (sledovani slozky)
        before = len(notes.calls)
        with open(os.path.join(root, "events.json.tmp"), "w") as f:
            json.dump({"seq": 3, "events": [{"seq": 3, "kind": "updates_available", "count": 4, "time": now}]}, f)
        os.replace(os.path.join(root, "events.json.tmp"), os.path.join(root, "events.json"))
        self.assertTrue(self.wait_for(lambda: len(notes.calls) > before, 8))
        self.assertEqual(notes.calls[-1][1][3], translation("Updates are available"))


    # ---- zvuk: automaticke prepnuti vystupu ------------------------------------------------------------
    def test_audio_switch_runs_helper_on_card_events(self):
        """pactl subscribe: zmena karty (HDMI monitoru) spusti pomocny program, zmena hlasitosti ne."""
        fake = os.path.join(self.home, "audio-bin")
        os.makedirs(fake)
        with open(os.path.join(fake, "pactl"), "w") as f:
            f.write('#!/bin/sh\n[ "$1" = subscribe ] || exit 0\n'
                    'echo "subscribe $LC_ALL" >>"$FAKE_LOG"\n'
                    'sleep 1\necho "Event \'change\' on sink #5"\nsleep 1.5\n'
                    'echo "Event \'change\' on card #47"\necho "Event \'change\' on card #47"\n'
                    'echo "Event \'new\' on sink #80"\nexec sleep 30\n')
        os.chmod(os.path.join(fake, "pactl"), 0o755)
        helper = os.path.join(self.home, "audio_helper.py")
        with open(helper, "w") as f:
            f.write('import os, sys\nopen(os.environ["FAKE_LOG"], "a").write("audio-" + sys.argv[1] + "\\n")\n')
        self.start_hub(PATH=fake + ":" + self.fake + ":/usr/bin:/bin", LUXOS_AUDIO_HELPER=helper)
        checks = lambda: [c for c in self.calls() if c == "audio-check"]
        self.assertTrue(self.wait_for(lambda: "subscribe C" in self.calls(), 5), self.calls())
        self.assertTrue(self.wait_for(lambda: len(checks()) >= 1, 5), self.calls())   # stav po prihlaseni
        time.sleep(1.2)                                  # zmena hlasitosti (sink #5) nic nespusti
        self.assertEqual(len(checks()), 1, self.calls())
        self.assertTrue(self.wait_for(lambda: len(checks()) == 2, 5), self.calls())   # davka udalosti -> jedna kontrola
        time.sleep(1.0)
        self.assertEqual(len(checks()), 2, self.calls())

    # ---- zmena casu (letni/zimni) ----------------------------------------------------------------------
    def time_change_hub(self, tz, local, **extra):
        """Hub s "ted" posunutym na mistni cas `local` (rok, mesic, den, hodina, minuta) v pasmu tz."""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        target = datetime(*local, tzinfo=ZoneInfo(tz)).timestamp()
        return self.start_hub(TZ=tz, LUXOS_TIME_OFFSET=str(int(target - time.time())), LUXOS_TIMECHANGE_DELAY="1", **extra)

    def read(self, path):
        with open(path) as f:
            return f.read()

    def time_notes(self):
        return [c for c in self.calls() if c.startswith("notify-send") and "preferences-system-time" in c]

    def test_time_change_evening_before_and_morning_after(self):
        # 25. 10. 2026 ve 3:00 SELC -> 2:00 SEC; vecer predtim upozorneni s tlacitkem Vypnout
        self.time_change_hub("Europe/Prague", (2026, 10, 24, 19, 0))
        self.assertTrue(self.wait_for(lambda: self.time_notes(), 8), self.calls())
        note = self.time_notes()[0]
        self.assertIn(translation("Winter time starts tonight"), note)
        self.assertIn(translation("Clocks go back from %s to %s. Your computer changes the time automatically.")
                      .replace("%s", "03:00", 1).replace("%s", "02:00", 1), note)
        self.assertIn("-A off=" + translation("Turn Off"), note)
        with open(os.path.join(self.cfg, "time-change.state")) as f:
            self.assertEqual(f.read(), "BEFORE=1792890000\n")
        # znovu po probuzeni: uz neupozorni
        self.hub.send_signal(signal.SIGTERM)
        self.hub.wait(5)
        self.time_change_hub("Europe/Prague", (2026, 10, 24, 22, 0))
        time.sleep(2.5)
        self.assertEqual(len(self.time_notes()), 1)
        # rano po zmene
        self.hub.send_signal(signal.SIGTERM)
        self.hub.wait(5)
        self.time_change_hub("Europe/Prague", (2026, 10, 25, 9, 30))
        self.assertTrue(self.wait_for(lambda: len(self.time_notes()) == 2, 8), self.calls())
        self.assertIn(translation("Winter time has started"), self.time_notes()[1])
        self.assertIn(translation("Clocks went back from %s to %s.").replace("%s", "03:00", 1).replace("%s", "02:00", 1),
                      self.time_notes()[1])

    def test_time_change_spring_timer_and_turn_off(self):
        # 10 s pred 18:00 den pred letnim casem: upozorni casovac; tlacitko Vypnout zapise TIME_CHANGE=0
        answer = os.path.join(self.home, "answer")
        os.makedirs(answer)
        with open(os.path.join(answer, "notify-send"), "w") as f:
            f.write('#!/bin/sh\nprintf "%s\\n" "notify-send $*" >>"$FAKE_LOG"\ncase "$*" in *off=*) echo off;; esac\n')
        os.chmod(os.path.join(answer, "notify-send"), 0o755)
        with open(os.path.join(self.cfg, "notifications.conf"), "w") as f:
            f.write("OTHER=1\n")
        self.time_change_hub("America/New_York", (2027, 3, 13, 17, 59, 50), PATH=answer + ":" + self.env()["PATH"])
        time.sleep(1.5)
        self.assertEqual(self.time_notes(), [])
        self.assertTrue(self.wait_for(lambda: self.time_notes(), 15), self.calls())
        note = self.time_notes()[0]
        self.assertIn(translation("Summer time starts tonight"), note)
        self.assertIn(translation("Clocks go forward from %s to %s. Your computer changes the time automatically.")
                      .replace("%s", "02:00", 1).replace("%s", "03:00", 1), note)
        conf = os.path.join(self.cfg, "notifications.conf")
        self.assertTrue(self.wait_for(lambda: "TIME_CHANGE=0" in self.read(conf), 5))
        with open(conf) as f:
            self.assertEqual(f.read(), "OTHER=1\nTIME_CHANGE=0\n")

    def test_time_change_off_and_zones_without_change(self):
        with open(os.path.join(self.cfg, "notifications.conf"), "w") as f:
            f.write("TIME_CHANGE=0\n")
        self.time_change_hub("Europe/Prague", (2026, 10, 24, 19, 0))
        time.sleep(2.5)
        self.assertEqual(self.time_notes(), [])
        self.hub.send_signal(signal.SIGTERM)
        self.hub.wait(5)
        os.unlink(os.path.join(self.cfg, "notifications.conf"))
        self.time_change_hub("Asia/Tokyo", (2026, 10, 24, 19, 0))
        time.sleep(2.5)
        self.assertEqual(self.time_notes(), [])
        self.assertFalse(os.path.exists(os.path.join(self.cfg, "time-change.state")))


if __name__ == "__main__":
    unittest.main()
