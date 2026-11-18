#!/usr/bin/env python3
"""LuxOS - Ovladaci centrum: dlazdice Wi-Fi a Bluetooth jako v Androidu (files/lsl/luxos_cc.lsl).

    xvfb-run -a dbus-run-session -- python3 -m unittest packages/luxos-desktop/tests/test_luxos_cc_tiles.py -v

Klik na modrou bublinu s ikonou prepne (Wi-Fi: nmcli radio, Bluetooth: BlueZ Powered), klik jinam na dlazdici
otevre nastaveni (Wi-Fi: okno Wi-Fi z listy, Bluetooth: aplikace Bluetooth). BlueZ je falesna sluzba na
vlastni "systemove" sbernici, nmcli, luxos-bar-popup a luxos-bluetooth jsou napodobeniny v PATH.
Polohy bubliny a nazvu zapisuje okno s LUXOS_CC_TEST_LOG do <zaznam>.pos ("pos jmeno x y").
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
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "files", "lsl", "luxos-hub.lsl")
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
UNDER_XVFB = bool(os.environ.get("DISPLAY")) and "xvfb-run" in os.environ.get("XAUTHORITY", "")
BIN = tempfile.mkdtemp(prefix="luxos-cc-tiles-bin-")


def build():
    if not LSLC:
        return False
    r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", SRC, os.path.join(BIN, "luxos-hub")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError(r.stderr + r.stdout)
    os.symlink("luxos-hub", os.path.join(BIN, "luxos-control-center"))
    return True


BUILT = build()

FAKE_NMCLI = r'''#!/bin/sh
echo "nmcli $*" >> "$FAKE_LOG"
case "$*" in
  "radio wifi") cat "$FAKE_STATE/radio" ;;
  "radio wifi off") echo disabled > "$FAKE_STATE/radio" ;;
  "radio wifi on") echo enabled > "$FAKE_STATE/radio" ;;
  *"general"*) echo enabled ;;
esac
exit 0
'''
FAKE_LOGGER = '#!/bin/sh\necho "$(basename "$0") $*" >> "$FAKE_LOG"\n'

FAKE_BLUEZ = r'''
import sys
from gi.repository import Gio, GLib
log = sys.argv[1]
XML = """<node><interface name='org.bluez.Adapter1'><property name='Powered' type='b' access='readwrite'/></interface></node>"""
state = {"Powered": True}
def get(conn, sender, path, iface, prop):
    return GLib.Variant("b", state[prop])
def set_(conn, sender, path, iface, prop, value):
    state[prop] = value.unpack()
    with open(log, "a") as f:
        f.write("bluez set %s %s\n" % (prop, state[prop]))
    return True
bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
bus.register_object("/org/bluez/hci0", Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], None, get, set_)
Gio.bus_own_name_on_connection(bus, "org.bluez", 0, None, None)
print("ready", flush=True)
GLib.MainLoop().run()
'''


@unittest.skipUnless(BUILT, "needs lslc with the linux-x86_64-gnu target")
@unittest.skipUnless(UNDER_XVFB, "GUI only under xvfb-run (never on a real display)")
class ControlCenterTiles(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="luxos-cc-tiles-")
        self.addCleanup(shutil.rmtree, self.t, True)
        fake, state, run = (os.path.join(self.t, d) for d in ("fake", "state", "run"))
        for d in (fake, state, run):
            os.makedirs(d)
        os.chmod(run, 0o700)
        for name, body in (("nmcli", FAKE_NMCLI), ("luxos-bar-popup", FAKE_LOGGER), ("luxos-bluetooth", FAKE_LOGGER)):
            p = os.path.join(fake, name)
            with open(p, "w") as f:
                f.write(body)
            os.chmod(p, 0o755)
        with open(os.path.join(state, "radio"), "w") as f:
            f.write("enabled\n")
        self.log = os.path.join(self.t, "calls")
        self.ui = os.path.join(self.t, "cc.log")
        self.procs = []
        sysbus = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address"], stdout=subprocess.PIPE, text=True)
        self.procs.append(sysbus)
        address = sysbus.stdout.readline().strip()
        self.env = dict(os.environ, PATH=fake + ":" + os.environ["PATH"], FAKE_LOG=self.log, FAKE_STATE=state,
                        XDG_RUNTIME_DIR=run, XDG_CONFIG_HOME=os.path.join(self.t, "config"),
                        XDG_CACHE_HOME=os.path.join(self.t, "cache"), DBUS_SYSTEM_BUS_ADDRESS=address,
                        LUXOS_CC_TEST_LOG=self.ui, LUXOS_HUB_NO_AUTOHIDE="1", LANG="C", NO_AT_BRIDGE="1",
                        GIO_USE_VFS="local")
        script = os.path.join(self.t, "bluez.py")
        with open(script, "w") as f:
            f.write(FAKE_BLUEZ)
        bluez = subprocess.Popen([sys.executable, script, self.log], env=self.env, stdout=subprocess.PIPE, text=True)
        self.procs.append(bluez)
        self.assertEqual(bluez.stdout.readline().strip(), "ready")
        cc = subprocess.Popen([os.path.join(BIN, "luxos-control-center"), "--background"], env=self.env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(cc)
        self.assertTrue(self.wait_for(lambda: os.path.exists(os.path.join(run, "luxos-control-center.pid"))))

    def tearDown(self):
        for p in reversed(self.procs):
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()

    def read(self, path):
        try:
            with open(path) as f:
                return f.read()
        except OSError:
            return ""

    def wait_for(self, check, timeout=8.0):
        end = time.time() + timeout
        while time.time() < end:
            if check():
                return True
            time.sleep(0.1)
        return check()

    def show(self):
        shown = self.read(self.ui).count("shown")
        subprocess.run([os.path.join(BIN, "luxos-control-center")], env=self.env, timeout=20)
        self.assertTrue(self.wait_for(lambda: self.read(self.ui).count("shown") > shown), self.read(self.ui))
        self.assertTrue(self.wait_for(lambda: self.read(self.ui + ".pos").count("pos bt-title") > shown),
                        self.read(self.ui + ".pos"))

    def click(self, name):
        pos = {}
        for line in self.read(self.ui + ".pos").splitlines():
            parts = line.split(" ")
            if parts[0] == "pos" and len(parts) == 4:
                pos[parts[1]] = (parts[2], parts[3])
        x, y = pos[name]
        subprocess.run(["xdotool", "mousemove", x, y, "click", "1"], check=True)
        time.sleep(0.8)

    def test_wifi_bubble_toggles_rest_opens_wifi(self):
        self.show()
        self.click("wifi-title")
        self.assertTrue(self.wait_for(lambda: "luxos-bar-popup wifi" in self.read(self.log)), self.read(self.log))
        self.assertNotIn("nmcli radio wifi off", self.read(self.log), "klik na nazev neprepina")
        self.show()
        self.click("wifi-bubble")
        self.assertTrue(self.wait_for(lambda: "nmcli radio wifi off" in self.read(self.log)), self.read(self.log))
        self.assertEqual(self.read(self.log).count("luxos-bar-popup"), 1, "klik na bublinu neotevira okno")

    def test_bluetooth_bubble_toggles_rest_opens_app(self):
        self.show()
        self.click("bt-bubble")
        self.assertTrue(self.wait_for(lambda: "bluez set Powered False" in self.read(self.log)), self.read(self.log))
        self.assertNotIn("luxos-bluetooth", self.read(self.log), "klik na bublinu neotevira aplikaci")
        self.click("bt-bubble")
        self.assertTrue(self.wait_for(lambda: "bluez set Powered True" in self.read(self.log)), self.read(self.log))
        self.click("bt-title")
        self.assertTrue(self.wait_for(lambda: "luxos-bluetooth" in self.read(self.log)), self.read(self.log))


if __name__ == "__main__":
    unittest.main()
