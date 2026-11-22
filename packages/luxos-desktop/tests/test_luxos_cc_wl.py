#!/usr/bin/env python3
"""Ovladaci centrum na Waylandu ve vzhledu One UI (files/lsl/luxos_cc.lsl v luxos-hub): snimky proti vzorum
(svetly a tmavy rezim) a ovladani mysi i klavesnici proti nahradnim sluzbam. Headless labwc ze sysrootu harnessu
(vzory, bez rozmazani v kompozitoru) a luxwm (out/luxwm-test/build), kde vrstva dostane klavesnici hned.

    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      scripts/wl-test/run-all packages/luxos-desktop/tests/test_luxos_cc_wl.py

Nahradni sluzby: nmcli, pactl, sporice a spoustene aplikace jsou skripty v PATH (zapisuji volani do calls.log),
BlueZ a logind na vlastni systemove sbernici, historie oznameni (Nerusit) na vlastni sbernici relace.
Vzory: tests/wl-cc-goldens/*.png, novy vzor LUXOS_CC_UPDATE_GOLDENS=1; snimky i do LUXOS_CC_SHOTS.
"""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_luxos_bar_wl import Bar, crop, gradient, pixel, png_read, png_write, ppm_read  # noqa: E402
from test_luxos_hub_wl import Log  # noqa: E402

PKG = HERE.parent
REPO = PKG.parent.parent
WLT = REPO / "scripts/wl-test/wlt"
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
SYSROOT = Path(os.environ.get("WLT_SYSROOT") or REPO / "out/wl-test/sysroot")
LUXWM_BUILD = Path(os.environ.get("LUXWM_BUILD") or REPO / "out/luxwm-test/build")
HAVE_LABWC = (SYSROOT / "usr/bin/labwc").exists() or shutil.which("labwc")
HAVE_LUXWM = (LUXWM_BUILD / "luxwm").exists()
TOOLS = all(shutil.which(t) for t in ("make", "gcc", "wayland-scanner", "pkg-config", "dbus-daemon"))
GOLDENS = HERE / "wl-cc-goldens"
UPDATE = os.environ.get("LUXOS_CC_UPDATE_GOLDENS") == "1"
OUT_W, OUT_H = 1280, 800
# okno vpravo nahore bez listy (luxos_hub_popup: okraj 8 px vpravo, 6 px nahore)
EDGE, TOP = 8, 6

FAKE_SERVICES = r'''
import sys
from gi.repository import Gio, GLib
system, session, log = sys.argv[1], sys.argv[2], open(sys.argv[3], "a", buffering=1)
state = {"powered": True, "dnd": False}
BLUEZ = """<node><interface name="org.bluez.Adapter1"><property name="Powered" type="b" access="readwrite"/></interface></node>"""
LOGIND = """<node><interface name="org.freedesktop.login1.Session">
<method name="SetBrightness"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="u" direction="in"/></method>
</interface></node>"""
HISTORY = """<node><interface name="cz.luxos.NotificationHistory">
<method name="GetDoNotDisturb"><arg type="b" direction="out"/></method>
<method name="SetDoNotDisturb"><arg type="b" direction="in"/></method>
</interface></node>"""
def bus(address):
    return Gio.DBusConnection.new_for_address_sync(address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
                                                   | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
def iface(xml):
    return Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0]
def bluez_get(conn, sender, path, name, prop):
    return GLib.Variant("b", state["powered"])
def bluez_set(conn, sender, path, name, prop, value):
    state["powered"] = value.unpack()
    print("bluez Powered", state["powered"], file=log)
    return True
def logind(conn, sender, path, name, method, params, inv):
    print("logind", method, *params.unpack(), file=log)
    inv.return_value(None)
def history(conn, sender, path, name, method, params, inv):
    if method == "SetDoNotDisturb":
        state["dnd"] = params.unpack()[0]
        print("dnd", state["dnd"], file=log)
        inv.return_value(None)
    else:
        inv.return_value(GLib.Variant("(b)", (state["dnd"],)))
sys_bus, ses_bus = bus(system), bus(session)
sys_bus.register_object("/org/bluez/hci0", iface(BLUEZ), None, bluez_get, bluez_set)
sys_bus.register_object("/org/freedesktop/login1/session/auto", iface(LOGIND), logind, None, None)
ses_bus.register_object("/cz/luxos/NotificationHistory", iface(HISTORY), history, None, None)
names = []
def owned(conn, name):
    names.append(name)
    if len(names) == 3:
        print("ready", flush=True)
Gio.bus_own_name_on_connection(sys_bus, "org.bluez", 0, owned, None)
Gio.bus_own_name_on_connection(sys_bus, "org.freedesktop.login1", 0, owned, None)
Gio.bus_own_name_on_connection(ses_bus, "org.freedesktop.Notifications", 0, owned, None)
GLib.MainLoop().run()
'''

# Nahradni programy: stav v $FAKE_STATE, kazde volani radkem do $FAKE_CALLS
FAKE_BIN = {
    "nmcli": r'''
case "$*" in
    "radio wifi") cat "$FAKE_STATE/wifi" ;;
    "radio wifi on") echo enabled >"$FAKE_STATE/wifi" ;;
    "radio wifi off") echo disabled >"$FAKE_STATE/wifi" ;;
    "-t -f ACTIVE,SSID device wifi") echo "yes:Home Network" ;;
    "-t -f CONNECTIVITY general") echo full ;;
    "-t -f TYPE,STATE device") echo wifi:connected ;;
esac''',
    "pactl": r'''
case "$1" in
    get-sink-volume) echo "Volume: front-left: 24248 / $(cat "$FAKE_STATE/vol")% / -26,00 dB" ;;
    get-sink-mute) echo "Mute: $(cat "$FAKE_STATE/mute")" ;;
    set-sink-volume) echo "${4%\%}" >"$FAKE_STATE/vol" ;;
    set-sink-mute)
        case "$4" in
            toggle) if [ "$(cat "$FAKE_STATE/mute")" = yes ]; then echo no; else echo yes; fi >"$FAKE_STATE/mute.new"
                    mv "$FAKE_STATE/mute.new" "$FAKE_STATE/mute" ;;
            0) echo no >"$FAKE_STATE/mute" ;;
            *) echo yes >"$FAKE_STATE/mute" ;;
        esac ;;
esac''',
    "luxos-datasaver": r'''if [ "$1" = on ]; then : >"$XDG_CONFIG_HOME/luxos/datasaver"; else rm -f "$XDG_CONFIG_HOME/luxos/datasaver"; fi''',
    "luxos-powersaver": r'''if [ "$1" = on ]; then : >"$XDG_CONFIG_HOME/luxos/powersaver"; else rm -f "$XDG_CONFIG_HOME/luxos/powersaver"; fi''',
}
LAUNCHED = ("luxos-appearance", "luxos-bluetooth", "luxos-wifi-qr", "luxos-settings", "luxos-account", "luxos-power",
            "luxos-displays", "luxos-network-login", "rfkill")


@unittest.skipUnless(LSLC and TOOLS and WLT.exists(), "chybi lslc, dbus-daemon nebo nastroje sestaveni")
class ControlCenter:
    compositor = ""

    @classmethod
    def setUpClass(cls):
        base = Path(os.environ.get("WLT_OUT") or REPO / "out/wl-test")
        base.mkdir(parents=True, exist_ok=True)
        cls.tmp = Path(tempfile.mkdtemp(prefix="ccwl-", dir=base))
        r = subprocess.run(["make", "-s", "-C", str(PKG / "files/src/luxos-wl"), f"OUT={cls.tmp}"], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("libluxos-wl: " + r.stdout + r.stderr)
        cls.lib = cls.tmp / "libluxos-wl.so.0"
        src = cls.tmp / "src"
        src.mkdir()
        for f in (PKG / "files/lsl").glob("*.lsl"):
            shutil.copy(f, src)
        cls.bin = cls.tmp / "bin"
        cls.bin.mkdir()
        r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", "--system-bindings", str(src), str(src / "luxos-hub.lsl"),
                            str(cls.bin / "luxos-hub")], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("luxos-hub: " + r.stdout + r.stderr)
        for name, body in FAKE_BIN.items():
            (cls.bin / name).write_text(f'#!/bin/sh\necho "{name} $*" >>"$FAKE_CALLS"\n{body}\n')
        for name in LAUNCHED:
            (cls.bin / name).write_text(f'#!/bin/sh\necho "{name} $*" >>"$FAKE_CALLS"\n')
        for name in [*FAKE_BIN, *LAUNCHED]:
            (cls.bin / name).chmod(0o755)
        # symbolicke ikony balicku (QR, rezimy obrazovek) jako v /usr/share/icons/hicolor
        icons = cls.tmp / "data/icons/hicolor/scalable/apps"
        icons.mkdir(parents=True)
        for f in (PKG / "files/icons").glob("*-symbolic.svg"):
            shutil.copy(f, icons)
        (cls.tmp / "data/icons/hicolor/index.theme").write_text(
            "[Icon Theme]\nName=Hicolor\nDirectories=scalable/apps\n\n[scalable/apps]\nSize=16\nMinSize=8\nMaxSize=512\nType=Scalable\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def setUp(self):
        self.procs = []
        self.session = None

    def tearDown(self):
        for p in reversed(self.procs):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
            if p.stdout:
                p.stdout.close()
        if self.session:
            subprocess.run([str(WLT), "stop", str(self.session)], capture_output=True)
            log = self.session / "hub.log"
            if log.exists():
                shutil.copy(log, self.save_dir() / f"{type(self).__name__}.{self._testMethodName}.hub.log")
            shutil.rmtree(self.session, True)

    # ---- relace ----

    def wlt(self, *args, env=None):
        r = subprocess.run([str(WLT), *args], capture_output=True, text=True, timeout=120, env=env)
        if r.returncode != 0:
            self.fail(f"wlt {args[0]}: " + r.stdout + r.stderr)
        return r.stdout

    def daemon(self, name):
        address = self.session / name
        p = subprocess.Popen(["dbus-daemon", "--session", f"--address=unix:path={address}", "--nofork", "--nopidfile"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        deadline = time.monotonic() + 5
        while not address.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        return f"unix:path={address}"

    def start(self, dark=False):
        name = f"c{self.compositor[:2]}{os.getpid() % 100000}-{self._testMethodName[-6:]}"
        args = ["start", "--mode", "headless", "--outputs", "1", "--size", f"{OUT_W}x{OUT_H}", "--timeout", "600", "--name", name]
        env = dict(os.environ)
        if self.compositor == "luxwm":
            conf = self.tmp / f"luxwm-{name}.conf"
            conf.write_text("xwayland = no\n" + (REPO / "packages/luxwm/luxwm.conf").read_text())
            env["WLT_COMPOSITOR_ENV"] = (f"LUXCOMP_VIRTUAL_INPUT=1 LUXWM_SYSTEM_CONFIG={conf} "
                                         f"LD_LIBRARY_PATH={LUXWM_BUILD}:{SYSROOT}/usr/lib")
            args += ["--", str(LUXWM_BUILD / "luxwm")]
        self.session = Path(self.wlt(*args, env=env).strip().splitlines()[-1])
        self.env = {}
        for line in self.wlt("env", str(self.session)).splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            self.env[key] = value
        self.env.pop("LD_LIBRARY_PATH", None)
        state = self.session / "state"
        state.mkdir()
        (state / "wifi").write_text("enabled\n")
        (state / "vol").write_text("40\n")
        (state / "mute").write_text("no\n")
        self.calls = self.session / "calls.log"
        self.calls.write_text("")
        system, bus = self.daemon("system_bus"), self.daemon("session_bus")
        fake = subprocess.Popen(["python3", "-I", "-c", FAKE_SERVICES, system, bus, str(self.calls)], stdout=subprocess.PIPE,
                                env=dict(os.environ, PYTHONUNBUFFERED="1"))
        self.procs.append(fake)
        Bar(fake).wait(r"^ready$")
        conf = self.session / "config"
        (conf / "luxos").mkdir(parents=True, exist_ok=True)
        (conf / "luxos/appearance").write_text("dark\n" if dark else "light\n")
        wall = self.session / "wall.png"
        if dark:
            png_write(wall, 320, 200, gradient(320, 200, (24, 30, 62), (46, 28, 60)))
        else:
            png_write(wall, 320, 200, gradient(320, 200, (246, 214, 196), (214, 222, 246)))
        (conf / "luxos/appearance.conf").write_text(f"WALLPAPER={wall}\n")
        (conf / "luxai").mkdir()
        (conf / "luxai/account.json").write_text('{"sessionToken": "t", "user": {"displayName": "Alex Morgan"}}')
        (conf / "gtk-3.0").mkdir(parents=True, exist_ok=True)
        theme = "Adwaita-dark" if dark else "Adwaita"
        icons = "WhiteSur" if Path("/usr/share/icons/WhiteSur").exists() else "Adwaita"
        (conf / "gtk-3.0/settings.ini").write_text(f"[Settings]\ngtk-theme-name={theme}\ngtk-icon-theme-name={icons}\n"
                                                   "gtk-font-name=Inter 10\ngtk-enable-animations=false\n")
        # GTK na Waylandu bere motiv z GSettings (luxos-appearance nastavi gtk-theme), ne ze settings.ini
        (conf / "glib-2.0/settings").mkdir(parents=True)
        (conf / "glib-2.0/settings/keyfile").write_text(f"[org/gnome/desktop/interface]\ngtk-theme='{theme}'\n"
                                                        f"icon-theme='{icons}'\nfont-name='Inter 10'\nenable-animations=false\n")
        backlight = self.session / "backlight/intel_backlight"
        backlight.mkdir(parents=True)
        (backlight / "brightness").write_text("900\n")
        (backlight / "max_brightness").write_text("1200\n")
        bat = self.session / "power/BAT0"
        bat.mkdir(parents=True)
        for key, value in {"capacity": 76, "status": "Discharging", "energy_now": 38000000, "energy_full": 50000000,
                           "power_now": 16000000}.items():
            (bat / key).write_text(f"{value}\n")
        self.cc = Log(self.session / "cc.log")
        self.env.update(GDK_BACKEND="wayland", NO_AT_BRIDGE="1", GTK_A11Y="none", LUXOS_WL_LIB=str(self.lib),
                        PATH=f"{self.bin}:/usr/bin:/bin", DBUS_SYSTEM_BUS_ADDRESS=system, DBUS_SESSION_BUS_ADDRESS=bus,
                        XDG_DATA_DIRS=f"{self.tmp}/data:/usr/share", FAKE_STATE=str(state), FAKE_CALLS=str(self.calls),
                        GSETTINGS_BACKEND="keyfile",
                        LUXOS_HUB_PREBUILD_DELAY="1", LUXOS_HUB_NEWS_DELAY="100000", LUXOS_HUB_NO_PORTAL="1",
                        LUXOS_CC_TEST_LOG=str(self.cc.path), LUXOS_BACKLIGHT=str(backlight.parent),
                        LUXOS_POWER_SUPPLY=str(bat.parent), LUXOS_CALENDAR_DIR=str(self.session / "calendar"), LANG="C.UTF-8")
        hub = subprocess.Popen([str(self.bin / "luxos-hub")], env=self.env, stdout=subprocess.DEVNULL,
                               stderr=open(self.session / "hub.log", "w"))
        self.procs.append(hub)
        pidfile = Path(self.env["XDG_RUNTIME_DIR"]) / "luxos-control-center.pid"
        deadline = time.monotonic() + 5
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(2.0)
        self.assertIsNone(hub.poll(), (self.session / "hub.log").read_text())
        self.hub = hub

    def open(self):
        """Ukaze okno (SIGUSR1 jako zkratka) -> slovnik poloh prvku na obrazovce a obdelnik okna."""
        mark = self.cc.mark()
        self.hub.send_signal(signal.SIGUSR1)
        self.cc.wait("shown", mark, timeout=3)
        self.cc.wait("wifi-qr:share", 0, timeout=5)
        w, h = map(int, self.cc.wait("size ", mark).split()[1:])
        self.rect = (OUT_W - EDGE - w, TOP, w, h)
        self.pos = {}
        for line in self.cc.lines()[mark:]:
            if line.startswith("tilepos "):
                _, name, x, y, width = line.split()
                self.pos[name] = (self.rect[0] + int(x), TOP + int(y), int(width))
        time.sleep(0.5)
        return self.pos

    def click(self, name, dx=0):
        x, y, _ = self.pos[name]
        self.input(f"move {x + dx} {y}", "sleep 0.1", "click")

    def input(self, *cmds):
        self.wlt("input", str(self.session), *cmds)

    def shot(self):
        path = self.session / "shot.ppm"
        self.wlt("shot", str(self.session), str(path))
        return ppm_read(path)

    def wait_call(self, text, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            lines = self.calls.read_text().splitlines()
            if text in lines:
                return lines
            time.sleep(0.05)
        self.fail(f"{text!r} nezavolano: {self.calls.read_text()[-600:]}\ncc.log: {self.cc.lines()[-15:]}\n"
                  + (self.session / "hub.log").read_text()[-1500:])

    def assert_bubble(self, name, on, timeout=3.0):
        """Bublina dlazdice bila (zapnuto) / pruhledna (vypnuto): bod v bubline vlevo od ikony."""
        x, y, _ = self.pos[name]
        deadline = time.monotonic() + timeout
        while True:
            v = bytes.fromhex(pixel(self.shot(), x - 13, y))
            if (min(v) >= 245) == on:
                return
            if time.monotonic() > deadline:
                self.fail(f"bublina {name} neni {'zapnuta' if on else 'vypnuta'} ({v.hex()})")
            time.sleep(0.15)

    def save_dir(self):
        keep = Path(os.environ.get("LUXOS_CC_SHOTS") or self.tmp.parent / "cc-shots")
        keep.mkdir(parents=True, exist_ok=True)
        return keep

    def save(self, name, image):
        png_write(self.save_dir() / f"{name}.png", *image)
        return self.save_dir() / f"{name}.png"


@unittest.skipUnless(HAVE_LABWC, "chybi labwc (scripts/wl-test/fetch-sysroot.sh)")
class ControlCenterLabwc(ControlCenter, unittest.TestCase):
    compositor = "labwc"

    def golden(self, dark, name):
        self.start(dark=dark)
        # pravy pruh obrazovky i pred otevrenim (snimky pred/po pro vlastnika)
        self.open()
        image = self.shot()
        self.save(name + "-screen", crop(image, OUT_W - 440, 0, 440, OUT_H))
        x, y, w, h = self.rect
        self.assertLessEqual(y + h, OUT_H, "okno presahuje obrazovku")
        # sirka jako ostatni vyskakovaci okna listy, cele na obrazovce i na 1366x768 pod listou
        self.assertLessEqual(w, 380)
        self.assertLessEqual(h, 768 - 28 - 12)
        image = crop(image, x, y, w, h)
        out = self.save(name, image)
        golden = GOLDENS / f"{name}.png"
        if UPDATE or not golden.exists():
            GOLDENS.mkdir(exist_ok=True)
            shutil.copy(out, golden)
            if not UPDATE:
                self.skipTest(f"vzor {golden} vytvoren")
        want = png_read(golden)
        self.assertEqual(want[:2], image[:2], "jina velikost nez vzor")
        a, b = want[2], image[2]
        diff = [abs(a[i] - b[i]) for i in range(len(a))]
        bad = sum(1 for i in range(0, len(diff), 3) if max(diff[i:i + 3]) > 48) / (len(diff) // 3)
        mean = sum(diff) / len(diff)
        print(f"\n  {name}: prumerny rozdil {mean:.2f}, odlisne pixely {bad * 100:.2f} %")
        self.assertLess(mean, 4.0, f"snimek {out} se lisi od {golden}")
        self.assertLess(bad, 0.02, f"snimek {out} se lisi od {golden}")

    def test_golden_light(self):
        self.golden(False, "cc-light")

    def test_golden_dark(self):
        self.golden(True, "cc-dark")


class Interaction:
    def test_tiles_toggle_real_backends(self):
        self.start()
        self.open()
        # Wi-Fi: bublina prepne radio (nmcli), okno zustane otevrene
        self.assert_bubble("wifi-bubble", True)
        self.click("wifi-bubble")
        self.wait_call("nmcli radio wifi off")
        self.assert_bubble("wifi-bubble", False)
        self.click("wifi-bubble")
        self.wait_call("nmcli radio wifi on")
        self.assert_bubble("wifi-bubble", True)
        # Bluetooth: bublina vypne adapter BlueZ (Powered)
        self.assert_bubble("bt-bubble", True)
        self.click("bt-bubble")
        self.wait_call("bluez Powered False")
        self.assert_bubble("bt-bubble", False)
        # Nerusit pres historii oznameni, sporice pres luxos-datasaver/-powersaver
        self.click("dnd")
        self.wait_call("dnd True")
        self.assert_bubble("dnd", True)
        self.click("data")
        self.wait_call("luxos-datasaver on")
        self.assert_bubble("data", True)
        self.click("power")
        self.wait_call("luxos-powersaver on")
        self.assert_bubble("power", True)
        self.click("power")
        self.wait_call("luxos-powersaver off")
        self.assert_bubble("power", False)
        self.assertNotIn("hidden", self.cc.lines())
        # ztlumeni tlacitkem vedle posuvniku, posuvnik hlasitosti klikem (zvuk zase zapne)
        self.click("vol-side")
        self.wait_call("pactl set-sink-mute @DEFAULT_SINK@ toggle")
        self.assert_bubble("vol-side", False)
        x, y, width = self.pos["vol"]
        self.click("vol", width // 4)
        self.wait_call("pactl set-sink-mute @DEFAULT_SINK@ 0")
        deadline = time.monotonic() + 5
        volumes = []
        while not volumes and time.monotonic() < deadline:
            volumes = [float(l.split()[-1].rstrip("%")) for l in self.calls.read_text().splitlines()
                       if l.startswith("pactl set-sink-volume")]
            time.sleep(0.05)
        self.assertTrue(volumes and 65 <= volumes[-1] <= 95, volumes)
        # jas pres logind (Session.SetBrightness), nejmene 10 %
        self.click("bright", -width // 2 + 4)
        self.wait_call("logind SetBrightness backlight intel_backlight 120")
        self.assertNotIn("Traceback", (self.session / "hub.log").read_text())
        self.assertIsNone(self.hub.poll())

    def test_links_open_apps_and_close(self):
        self.start()
        for name, call in (("wifi-title", None), ("bt-title", "luxos-bluetooth "), ("qr", "luxos-wifi-qr "),
                           ("bright-side", "luxos-displays "), ("dark", "luxos-appearance toggle")):
            self.open()
            mark = self.cc.mark()
            self.click(name)
            self.cc.wait("hidden", mark)
            if call:
                self.wait_call(call)
            time.sleep(0.4)
        # napajeni: zavre okno a posle liste SIGUSR2 (nabidka LuxOS, test_luxos_hub_wl)
        self.open()
        mark = self.cc.mark()
        self.click("power-button")
        self.cc.wait("power", mark)
        self.cc.wait("hidden", mark)
        self.assertIn("tile Wi-Fi settings", self.cc.lines())
        self.assertIsNone(self.hub.poll())


@unittest.skipUnless(HAVE_LABWC, "chybi labwc (scripts/wl-test/fetch-sysroot.sh)")
class InteractionLabwc(Interaction, ControlCenter, unittest.TestCase):
    compositor = "labwc"


@unittest.skipUnless(HAVE_LUXWM, "chybi luxwm (packages/luxwm/tests/build-host.sh)")
class InteractionLuxwm(Interaction, ControlCenter, unittest.TestCase):
    compositor = "luxwm"

    def tab_to(self, name, limit=30):
        for _ in range(limit):
            mark = self.cc.mark()
            self.input("key Tab")
            if self.cc.wait("focus ", mark, timeout=2) == f"focus {name}":
                return
        self.fail(f"Tab nedosel na {name}: {self.cc.lines()[-10:]}")

    def test_keyboard(self):
        # luxwm da vrstve klavesnici hned po zobrazeni: Tab prochazi prvky, mezernik prepina, sipky posouvaji
        self.start()
        self.open()
        self.tab_to("dnd")
        self.input("key space")
        self.wait_call("dnd True")
        self.tab_to("vol")
        time.sleep(0.3)
        self.save("cc-keyboard-focus", crop(self.shot(), OUT_W - 440, 0, 440, OUT_H))
        self.input("key Right")
        self.wait_call("pactl set-sink-volume @DEFAULT_SINK@ 45.0%")
        self.tab_to("bt-bubble")
        self.input("key Return")
        self.wait_call("bluez Powered False")
        # zbytek dlazdice (nastaveni) je vlastni zastavka Tab
        self.tab_to("wifi-tile")
        mark = self.cc.mark()
        self.input("key Return")
        self.cc.wait("tile Wi-Fi settings", mark)
        self.cc.wait("hidden", mark)
        self.open()
        mark = self.cc.mark()
        self.input("key Escape")
        self.cc.wait("hidden", mark)
        self.assertIsNone(self.hub.poll())

    # snimky s materialem kompozitoru (rozmazani, stin) pro vlastnika; vzory jsou z labwc
    def test_look_light(self):
        self.start()
        self.open()
        self.save("cc-luxwm-light", crop(self.shot(), OUT_W - 440, 0, 440, OUT_H))

    def test_look_dark(self):
        self.start(dark=True)
        self.open()
        self.save("cc-luxwm-dark", crop(self.shot(), OUT_W - 440, 0, 440, OUT_H))


if __name__ == "__main__":
    unittest.main()
