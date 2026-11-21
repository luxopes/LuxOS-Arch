#!/usr/bin/env python3
"""LuxOS - Nastaveni > Mys a touchpad (luxos_page_mouse, drive luxos-scrolling): zmeny pres UI (luxos_testctl)
a jejich ucinek.

Wayland: stranka pod luxwm headless zapise mouse_*/touchpad_* do ~/.config/luxwm/luxwm.conf a luxwm je po reload
pouzije (IPC get_input, nastavene hodnoty). Headless nema zarizeni libinput; skutecna zarizeni overuje
packages/luxwm/tests/test_luxwm_libinput_vm.py ve VM. X11: falesny xinput (stav zarizeni v souboru) a xfconf-query
(zaznam volani) - hodnoty ze zarizeni, set-prop jen na zarizeni sveho druhu, kanal pointers jako xfsettingsd.

    packages/luxwm/tests/build-host.sh
    .../runiso.sh python3 -m unittest -v packages/luxos-desktop/tests/test_settings_mouse.py
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
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lsl_app  # noqa: E402

REPO = HERE.parent.parent.parent
WLT = REPO / "scripts/wl-test/wlt"
OUT = Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test")
SYSROOT = Path(os.environ.get("WLT_SYSROOT") or OUT / "sysroot")
LUXWM_BUILD = Path(os.environ.get("LUXWM_BUILD") or REPO / "out/luxwm-test/build")
LUXWM = LUXWM_BUILD / "luxwm"
TMP = None
BIN = {}

FAKE_XINPUT = r'''#!/usr/bin/env python3
import json, os, sys
path = os.environ["FAKE_XINPUT_STATE"]
with open(path) as f:
    devices = json.load(f)
a = sys.argv[1:]
by_id = {d["id"]: d for d in devices}
if a == ["list", "--name-only"]:
    print("\n".join(d["name"] for d in devices))
elif a == ["list", "--id-only"]:
    print("\n".join(d["id"] for d in devices))
elif a[0] == "list-props" and a[1] in by_id:
    d = by_id[a[1]]
    print("Device '%s':" % d["name"])
    for i, (name, values) in enumerate(d["props"].items()):
        print("\t%s (%d):\t%s" % (name, 300 + i, ", ".join(values)))
elif a[0] == "set-prop" and a[1] in by_id:
    by_id[a[1]]["props"][a[2]] = a[3:]
    with open(path, "w") as f:
        json.dump(devices, f)
else:
    sys.exit(1)
'''
FAKE_XFCONF = '#!/bin/sh\nprintf "%s\\n" "$*" >> "$FAKE_XFCONF_LOG"\n'

DEVICES = [
    {"id": "2", "name": "Virtual core pointer", "props": {"Device Enabled": ["1"]}},
    {"id": "4", "name": "Virtual core XTEST pointer", "props": {"Device Enabled": ["1"], "libinput Accel Speed": ["0.000000"]}},
    {"id": "9", "name": "AT Translated Set 2 keyboard", "props": {"Device Enabled": ["1"], "libinput Send Events Mode Enabled": ["0", "0"]}},
    {"id": "10", "name": "Logitech USB Optical Mouse", "props": {
        "Device Enabled": ["1"], "libinput Accel Speed": ["0.000000"], "libinput Accel Profile Enabled": ["1", "0", "0"],
        "libinput Natural Scrolling Enabled": ["0"], "libinput Left Handed Enabled": ["0"],
        "libinput Middle Emulation Enabled": ["0"], "libinput Scroll Method Enabled": ["0", "0", "0"]}},
    {"id": "11", "name": "SynPS/2 Synaptics TouchPad", "props": {
        "Device Enabled": ["1"], "libinput Tapping Enabled": ["1"], "libinput Tapping Drag Enabled": ["1"],
        "libinput Accel Speed": ["0.250000"], "libinput Accel Profile Enabled": ["1", "0", "0"],
        "libinput Natural Scrolling Enabled": ["0"], "libinput Left Handed Enabled": ["0"],
        "libinput Disable While Typing Enabled": ["1"], "libinput Click Method Enabled": ["1", "0"],
        "libinput Scroll Method Enabled": ["1", "0", "0"]}},
]


def setUpModule():
    global TMP
    TMP = tempfile.mkdtemp(prefix="luxos-mouse-", dir=luxos_testguard._private_dir())
    BIN["luxos-settings"] = lsl_app.build("luxos-settings", TMP)
    BIN["luxos-scrolling"] = lsl_app.build("luxos-scrolling", TMP)


def tearDownModule():
    if TMP:
        shutil.rmtree(TMP, True)


def wait_for(cond, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.1)
    return cond()


def read(path):
    try:
        return Path(path).read_text()
    except FileNotFoundError:
        return ""


class Page:
    def page_state(self):
        return json.loads(self.app.ask("page-state", "page-state"))

    def open(self, env):
        self.app = lsl_app.App([BIN["luxos-settings"], "mouse"], env)
        self.assertTrue(self.app.wait(lambda: self.app.dump()), self.app.stderr())

    def conf(self):
        return read(Path(self.home) / ".config/luxwm/luxwm.conf")


@unittest.skipUnless(LUXWM.exists() and WLT.exists(), "needs luxwm (packages/luxwm/tests/build-host.sh) and scripts/wl-test")
class MouseWayland(Page, unittest.TestCase):
    def setUp(self):
        self.app = None
        self.home = tempfile.mkdtemp(dir=TMP)
        sysconf = Path(self.home) / "system-luxwm.conf"
        sysconf.write_text("xwayland = no\nworkspaces = 1\n")
        name = f"m{os.getpid() % 10000}-{self._testMethodName[5:15]}"
        env = dict(os.environ, WLT_COMPOSITOR_ENV=f"LUXWM_SYSTEM_CONFIG={sysconf} LD_LIBRARY_PATH={LUXWM_BUILD}:{SYSROOT}/usr/lib")
        r = subprocess.run([str(WLT), "start", "--mode", "headless", "--size", "1280x800", "--name", name, "--", str(LUXWM)],
                           env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.session = Path(r.stdout.strip().splitlines()[-1])
        self.env = {}
        for line in subprocess.run([str(WLT), "env", str(self.session)], capture_output=True, text=True).stdout.splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            self.env[key] = value
        self.env.pop("LD_LIBRARY_PATH", None)
        self.env.update(GDK_BACKEND="wayland", GTK_A11Y="none", NO_AT_BRIDGE="1", LUXWM_SYSTEM_CONFIG=str(sysconf),
                        LANG="C.UTF-8", LC_ALL="C.UTF-8", LUXOS_I18N_DIR=lsl_app.I18N)
        self.bus = lsl_app.Bus()
        self.env["DBUS_SESSION_BUS_ADDRESS"] = self.bus.address

    def tearDown(self):
        if self.app:
            self.app.stop()
        self.bus.stop()
        subprocess.run([str(WLT), "stop", str(self.session)], capture_output=True)
        shutil.rmtree(self.session, True)

    def conf(self):
        return read(Path(self.env["XDG_CONFIG_HOME"]) / "luxwm/luxwm.conf")

    def luxwm_input(self):
        r = subprocess.run([str(LUXWM_BUILD / "luxwm-msg"), "get-input"], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def configured(self, kind, option):
        return self.luxwm_input()["config"][kind][option]

    def test_changes_reach_luxwm(self):
        self.open(self.env)
        st = self.page_state()
        self.assertTrue(st["wayland"])
        self.assertEqual(st["devices"], [], "headless backend has no libinput devices")
        self.assertFalse(st["touchpad"], "touchpad section hidden without a touchpad")
        self.assertEqual(st["values"]["mouse_speed"], 0)
        self.assertIsNone(self.configured("mouse", "speed"))

        self.app.ask("slider Pointer speed = -40")
        self.assertTrue(wait_for(lambda: self.configured("mouse", "speed") == -40), self.conf())
        self.assertIn("mouse_speed = -40\n", self.conf())
        self.app.ask("switch Natural scrolling = on")
        self.assertTrue(wait_for(lambda: self.configured("touchpad", "natural_scroll") is True), self.conf())
        self.assertIsNone(self.configured("mouse", "natural_scroll"), "touchpad option does not touch mice")
        self.app.ask("switch Tap to click = on")
        self.assertTrue(wait_for(lambda: self.configured("touchpad", "tap") is True), self.conf())
        self.app.ask("switch Natural wheel direction = on")
        self.assertTrue(wait_for(lambda: self.configured("mouse", "natural_scroll") is True))
        self.app.ask("combo Primary mouse button = right")
        self.assertTrue(wait_for(lambda: self.configured("mouse", "left_handed") is True))
        self.app.ask("switch Pointer acceleration = off")
        self.assertTrue(wait_for(lambda: self.configured("mouse", "accel") == "flat"))
        self.app.ask("combo Scroll with = edge")
        self.app.ask("combo Right click = clickfinger")
        self.app.ask("slider Tracking speed = 60")
        self.assertTrue(wait_for(lambda: self.configured("touchpad", "speed") == 60))
        config = self.luxwm_input()["config"]["touchpad"]
        self.assertEqual((config["scroll_method"], config["click_method"]), ("edge", "clickfinger"))
        self.app.ask("switch Tap to click = off")
        self.assertTrue(wait_for(lambda: self.configured("touchpad", "tap") is False))
        self.app.ask("switch Inertia on the touchpad = off")
        self.assertTrue(wait_for(lambda: "kinetic=false" in read(Path(self.env["XDG_CONFIG_HOME"]) / "luxos/scrolling.conf")))

        # znovu otevrena stranka ukazuje ulozene hodnoty
        self.app.stop()
        self.open(self.env)
        values = self.page_state()["values"]
        self.assertEqual(values["mouse_speed"], -40)
        self.assertEqual(values["touchpad_speed"], 60)
        self.assertIs(values["touchpad_tap"], False)
        self.assertIs(values["mouse_left_handed"], True)
        self.assertEqual(values["mouse_accel"], "flat")
        self.assertEqual(values["touchpad_scroll_method"], "edge")


class MouseX11(Page, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.xvfb = lsl_app.Xvfb()

    @classmethod
    def tearDownClass(cls):
        cls.xvfb.stop()

    def setUp(self):
        self.app = None
        self.home = tempfile.mkdtemp(dir=TMP)
        bindir = Path(self.home) / "bin"
        bindir.mkdir()
        for name, text in (("xinput", FAKE_XINPUT), ("xfconf-query", FAKE_XFCONF)):
            (bindir / name).write_text(text)
            (bindir / name).chmod(0o755)
        self.state = Path(self.home) / "xinput.json"
        self.state.write_text(json.dumps(DEVICES))
        self.xfconf_log = Path(self.home) / "xfconf.log"
        self.env = dict(os.environ, HOME=self.home, XDG_CONFIG_HOME=os.path.join(self.home, ".config"),
                        XDG_CACHE_HOME=os.path.join(self.home, ".cache"), LANG="C.UTF-8", LC_ALL="C.UTF-8",
                        PATH=str(bindir) + os.pathsep + os.environ["PATH"], DISPLAY=self.xvfb.display,
                        FAKE_XINPUT_STATE=str(self.state), FAKE_XFCONF_LOG=str(self.xfconf_log),
                        LUXOS_I18N_DIR=lsl_app.I18N, NO_AT_BRIDGE="1", LUXWM_SYSTEM_CONFIG="/nonexistent")
        self.env.pop("WAYLAND_DISPLAY", None)
        self.bus = lsl_app.Bus()
        self.env["DBUS_SESSION_BUS_ADDRESS"] = self.bus.address
        luxos_testguard.check_env(self.env)

    def tearDown(self):
        if self.app:
            self.app.stop()
        self.bus.stop()

    def prop(self, dev, name):
        return {d["id"]: d for d in json.loads(self.state.read_text())}[dev]["props"][name]

    def assert_xfconf(self, line):
        # xinput se zmeni o chvili driv nez kanal pointers
        self.assertTrue(wait_for(lambda: line in read(self.xfconf_log).splitlines()), read(self.xfconf_log))

    def test_values_from_devices_and_live_apply(self):
        self.open(self.env)
        st = self.page_state()
        self.assertFalse(st["wayland"])
        self.assertTrue(st["touchpad"])
        self.assertEqual(sorted((d["name"], d["kind"]) for d in st["devices"]),
                         [("Logitech USB Optical Mouse", "mouse"), ("SynPS/2 Synaptics TouchPad", "touchpad")],
                         "keyboard and XTEST are not pointers to configure")
        values = st["values"]
        self.assertIs(values["touchpad_tap"], True, "shown as the device has it")
        self.assertEqual(values["touchpad_speed"], 25)
        self.assertEqual(values["mouse_speed"], 0)

        self.app.ask("slider Pointer speed = -35")
        self.assertTrue(wait_for(lambda: self.prop("10", "libinput Accel Speed") == ["-0.35"]))
        self.assertEqual(self.prop("11", "libinput Accel Speed"), ["0.250000"], "mouse speed does not touch the touchpad")
        self.assert_xfconf("-c pointers -p /Logitech_USB_Optical_Mouse/Properties/libinput_Accel_Speed -n -t double -s -0.35")
        self.app.ask("switch Tap to click = off")
        self.assertTrue(wait_for(lambda: self.prop("11", "libinput Tapping Enabled") == ["0"]))
        self.assert_xfconf("-c pointers -p /SynPS2_Synaptics_TouchPad/Properties/libinput_Tapping_Enabled -n -t int -s 0")
        self.app.ask("switch Natural scrolling = on")
        self.assertTrue(wait_for(lambda: self.prop("11", "libinput Natural Scrolling Enabled") == ["1"]))
        self.assertEqual(self.prop("10", "libinput Natural Scrolling Enabled"), ["0"])
        self.assert_xfconf("-c pointers -p /SynPS2_Synaptics_TouchPad/ReverseScrolling -n -t bool -s true")
        self.app.ask("combo Scroll with = edge")
        self.assertTrue(wait_for(lambda: self.prop("11", "libinput Scroll Method Enabled") == ["0", "1", "0"]))
        self.assert_xfconf("-c pointers -p /SynPS2_Synaptics_TouchPad/Properties/libinput_Scroll_Method_Enabled -n -a "
                      "-t int -s 0 -t int -s 1 -t int -s 0")
        self.app.ask("combo Primary mouse button = right")
        self.assertTrue(wait_for(lambda: self.prop("10", "libinput Left Handed Enabled") == ["1"]))
        self.assert_xfconf("-c pointers -p /Logitech_USB_Optical_Mouse/RightHanded -n -t bool -s false")
        self.app.ask("switch Pointer acceleration = off")
        self.assertTrue(wait_for(lambda: self.prop("10", "libinput Accel Profile Enabled") == ["0", "1", "0"]))
        # stejne nastaveni i pro relaci na Waylandu
        conf = self.conf()
        for line in ("mouse_speed = -35", "touchpad_tap = no", "touchpad_natural_scroll = yes", "touchpad_scroll_method = edge",
                     "mouse_left_handed = yes", "mouse_accel = flat"):
            self.assertIn(line + "\n", conf)

    def test_no_touchpad_hides_section(self):
        self.state.write_text(json.dumps([d for d in DEVICES if d["id"] != "11"]))
        self.open(self.env)
        st = self.page_state()
        self.assertFalse(st["touchpad"])
        shown = [w.get("text") for win in self.app.dump() for w in win["widgets"] if w["vis"]]
        self.assertIn("Pointer speed", shown)
        self.assertNotIn("Tap to click", shown)


class ScrollingCli(unittest.TestCase):
    """luxos-scrolling status / kinetic / smooth-wheel bez okna (odkaz na luxos-settings, stranka mouse)."""

    def run_cli(self, home, *args):
        env = {"PATH": "/usr/bin:/bin", "HOME": home, "XDG_CONFIG_HOME": os.path.join(home, ".config")}
        return subprocess.run([BIN["luxos-scrolling"], *args], env=env, capture_output=True, text=True, timeout=20,
                              stdin=subprocess.DEVNULL)

    def test_status_and_changes(self):
        home = tempfile.mkdtemp(dir=TMP)
        self.assertEqual(self.run_cli(home, "status").stdout, "smooth_wheel=true\nkinetic=true\n")
        self.assertEqual(self.run_cli(home, "kinetic", "off").returncode, 0)
        self.assertEqual(self.run_cli(home, "smooth-wheel", "off").returncode, 0)
        self.assertEqual(self.run_cli(home, "kinetic", "on").returncode, 0)
        self.assertEqual(self.run_cli(home, "status").stdout, "smooth_wheel=false\nkinetic=true\n")
        self.assertIn("[scrolling]\nsmooth_wheel=false\nkinetic=true\n", read(os.path.join(home, ".config/luxos/scrolling.conf")))
        self.assertEqual(self.run_cli(home, "kinetic", "maybe").returncode, 2)
        self.assertEqual(self.run_cli(home, "bogus").returncode, 2)


if __name__ == "__main__":
    unittest.main()
