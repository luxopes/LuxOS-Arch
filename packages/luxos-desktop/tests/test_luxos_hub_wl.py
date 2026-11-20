#!/usr/bin/env python3
"""luxos-hub na Waylandu: Ovladaci centrum (SIGUSR1) a Kalendar (SIGUSR2) jako plochy layer-shell pod tlacitkem
listy, bez zaseknuti, zavreni klavesou Esc a klikem mimo; jas pres logind. Headless luxwm (out/luxwm-test/build,
packages/luxwm/tests/build-host.sh) i bezne labwc ze sysrootu harnessu, vzdy se dvema vystupy.

    env -u DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u XAUTHORITY DBUS_SYSTEM_BUS_ADDRESS=unix:path=/nonexistent \\
      systemd-run --user --scope -p TasksMax=300 -p MemoryMax=1G -p MemorySwapMax=0 -- timeout 900 \\
      python3 -m unittest packages/luxos-desktop/tests/test_luxos_hub_wl.py -v

Hub, lista a prepinace luxos-cc-toggle / luxos-calendar-toggle se prekladaji z files/lsl. Skutecna sbernice
ani obrazovka se nepouziva (soukrome XDG_RUNTIME_DIR, sbernice D-Bus jen v testu jasu).
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
from test_luxos_bar_wl import Bar, pixel, ppm_read  # noqa: E402

PKG = HERE.parent
REPO = PKG.parent.parent
WLT = REPO / "scripts/wl-test/wlt"
LSLC = os.environ.get("LUXOS_LSLC") or shutil.which("lslc")
SYSROOT = Path(os.environ.get("WLT_SYSROOT") or REPO / "out/wl-test/sysroot")
LUXWM_BUILD = Path(os.environ.get("LUXWM_BUILD") or REPO / "out/luxwm-test/build")
HAVE_LABWC = (SYSROOT / "usr/bin/labwc").exists() or shutil.which("labwc")
HAVE_LUXWM = (LUXWM_BUILD / "luxwm").exists()
TOOLS = all(shutil.which(t) for t in ("make", "gcc", "wayland-scanner", "pkg-config"))
OUT_W, OUT_H = 1280, 720
BAR = 32
# klik -> okno viditelne; zaseknuty hub (drive futex ve wl_display_read_events) by se neukazal nikdy
SHOW_LIMIT = 2.0

FAKE_LOGIND = r'''
import sys
from gi.repository import Gio, GLib
XML = """<node><interface name="org.freedesktop.login1.Session">
<method name="SetBrightness"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="u" direction="in"/></method>
</interface></node>"""
def call(conn, sender, path, iface, method, params, inv):
    print("set", *params.unpack(), flush=True)
    inv.return_value(None)
def acquired(conn, name):
    conn.register_object("/org/freedesktop/login1/session/auto", Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0], call)
    print("ready", flush=True)
conn = Gio.DBusConnection.new_for_address_sync(sys.argv[1], Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
                                               | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
Gio.bus_own_name_on_connection(conn, "org.freedesktop.login1", 0, acquired, None)
GLib.MainLoop().run()
'''


class Log:
    """Testovaci zaznam okna (LUXOS_CC_TEST_LOG / LUXOS_CAL_TEST_LOG): radky od znacky."""

    def __init__(self, path):
        self.path = path

    def lines(self):
        try:
            return self.path.read_text().splitlines()
        except FileNotFoundError:
            return []

    def mark(self):
        return len(self.lines())

    def wait(self, prefix, start=0, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for line in self.lines()[start:]:
                if line.startswith(prefix):
                    return line
            time.sleep(0.02)
        raise AssertionError(f"{prefix!r} se v {self.path.name} neobjevilo: {self.lines()[-20:]}")


@unittest.skipUnless(LSLC and TOOLS and WLT.exists(), "chybi lslc nebo nastroje sestaveni")
class HubWayland:
    compositor = ""

    @classmethod
    def setUpClass(cls):
        base = REPO / "out/wl-test"
        base.mkdir(parents=True, exist_ok=True)
        cls.tmp = Path(tempfile.mkdtemp(prefix="hubwl-", dir=base))
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
        for name in ("luxos-hub", "luxos-bar", "luxos-cc-toggle", "luxos-calendar-toggle"):
            r = subprocess.run([LSLC, "--target", "linux-x86_64-gnu", str(src / f"{name}.lsl"), str(cls.bin / name)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"{name}: " + r.stdout + r.stderr)
        os.symlink("luxos-hub", cls.bin / "luxos-control-center")
        os.symlink("luxos-hub", cls.bin / "luxos-calendar")

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
            shutil.rmtree(self.session, True)

    # ---- relace ----

    def wlt(self, *args, env=None):
        r = subprocess.run([str(WLT), *args], capture_output=True, text=True, timeout=120, env=env)
        if r.returncode != 0:
            self.fail(f"wlt {args[0]}: " + r.stdout + r.stderr)
        return r.stdout

    def start(self):
        name = f"h{self.compositor[:2]}{os.getpid() % 100000}-{self._testMethodName[-6:]}"
        args = ["start", "--mode", "headless", "--outputs", "2", "--size", f"{OUT_W}x{OUT_H}", "--timeout", "600",
                "--name", name]
        env = dict(os.environ)
        if self.compositor == "luxwm":
            conf = self.tmp / f"luxwm-{name}.conf"
            conf.write_text("xwayland = no\n" + (REPO / "packages/luxwm/luxwm.conf").read_text())
            env["WLT_COMPOSITOR_ENV"] = (f"LUXCOMP_VIRTUAL_INPUT=1 LUXWM_SYSTEM_CONFIG={conf} "
                                         f"LD_LIBRARY_PATH={LUXWM_BUILD}:{SYSROOT}/usr/lib")
            # lista smi na hlavy monitoru a seznam oken jako /usr/bin/luxos-bar; hub privilegia nema
            env["WLT_PRIVILEGED"] = str(self.bin / "luxos-bar")
            args += ["--", str(LUXWM_BUILD / "luxwm")]
        self.session = Path(self.wlt(*args, env=env).strip().splitlines()[-1])
        self.env = {}
        for line in self.wlt("env", str(self.session)).splitlines():
            key, _, value = line.removeprefix("export ").partition("=")
            self.env[key] = value
        self.env.pop("LD_LIBRARY_PATH", None)
        self.env.update(GDK_BACKEND="wayland", NO_AT_BRIDGE="1", GTK_A11Y="none", LUXOS_WL_LIB=str(self.lib),
                        PATH=f"{self.bin}:/usr/bin:/bin", LUXOS_BAR_TRACE="1", LUXOS_BAR_NOW="2026-11-20 09:41")
        conf = self.session / "config"
        (conf / "luxos").mkdir(parents=True, exist_ok=True)
        (conf / "luxos/appearance").write_text("light\n")
        (conf / "gtk-3.0").mkdir(parents=True, exist_ok=True)
        (conf / "gtk-3.0/settings.ini").write_text("[Settings]\ngtk-font-name=Inter 10\ngtk-enable-animations=false\n")
        # notebook s podsvicenim a bez baterie (stav jen ze souboru testu)
        self.backlight = self.session / "backlight"
        (self.backlight / "intel_backlight").mkdir(parents=True)
        (self.backlight / "intel_backlight/brightness").write_text("600\n")
        (self.backlight / "intel_backlight/max_brightness").write_text("1200\n")
        (self.session / "power").mkdir()
        self.cc = Log(self.session / "cc.log")
        self.cal = Log(self.session / "cal.log")
        return self.session

    def bar(self):
        p = subprocess.Popen([str(self.bin / "luxos-bar")], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        bar = Bar(p)
        bar.wait(r"^ready$")
        bar.wait(r"^drawn HEADLESS-2")
        return bar

    def hub(self, **extra):
        env = dict(self.env, LUXOS_HUB_PREBUILD_DELAY="1", LUXOS_HUB_NEWS_DELAY="100000", LUXOS_HUB_NO_PORTAL="1",
                   LUXOS_CC_TEST_LOG=str(self.cc.path), LUXOS_CAL_TEST_LOG=str(self.cal.path),
                   LUXOS_BACKLIGHT=str(self.backlight), LUXOS_POWER_SUPPLY=str(self.session / "power"),
                   LUXOS_CALENDAR_DIR=str(self.session / "calendar"), **extra)
        p = subprocess.Popen([str(self.bin / "luxos-hub")], env=env, stdout=subprocess.DEVNULL,
                             stderr=open(self.session / "hub.log", "w"))
        self.procs.append(p)
        pidfile = Path(self.env["XDG_RUNTIME_DIR"]) / "luxos-control-center.pid"
        deadline = time.monotonic() + 5
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        # okna se stavi predem (LUXOS_HUB_PREBUILD_DELAY), at prvni otevreni neni studene
        time.sleep(2.0)
        self.assertIsNone(p.poll(), (self.session / "hub.log").read_text())
        return p

    def input(self, *cmds):
        self.wlt("input", str(self.session), *cmds)

    def shot(self):
        path = self.session / "shot.ppm"
        self.wlt("shot", str(self.session), str(path))
        return ppm_read(path)

    def client(self):
        """Okno aplikace s fokusem -> bod v nem pro klik mimo vyskakovaci okno (polohu urcuje kompozitor)."""
        client = REPO / "out/wl-test/bin/wlt-client"
        p = subprocess.Popen([str(client), "--app-id", "test.window", "--title", "Window", "--size", "500x300",
                              "--color", "3a6ea5"], env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            image = self.shot()
            for y in range(100, OUT_H, 20):
                for x in range(0, image[0], 20):
                    if pixel(image, x, y) == "3a6ea5":
                        self.inside = f"move {x} {y}"
                        return p
            time.sleep(0.2)
        self.fail("okno aplikace se neukazalo")

    def wait_pixels(self, check, timeout=2.0):
        """Prvni snimek splnujici check (kompozitor kresli az po commitu plochy) -> True, jinak False."""
        deadline = time.monotonic() + timeout
        while True:
            if check(self.shot()):
                return True
            if time.monotonic() > deadline:
                keep = self.tmp.parent / f"hub-wl-{self.compositor}-{self._testMethodName}.ppm"
                self.wlt("shot", str(self.session), str(keep))
                return False
            time.sleep(0.1)

    def close_by_key(self, hub, signum, log):
        """Esc zavre okno otevrene bez kliku v liste. labwc pri prepnuti klavesnice exclusive -> on demand
        vrati fokus oknu aplikace (popup.show), tam okno zavre jen dalsi signal; luxwm fokus vrstve necha."""
        mark = log.mark()
        if self.compositor == "labwc":
            hub.send_signal(signum)
        else:
            self.input("key Escape")
        log.wait("hidden", mark)

    # ---- testy ----

    def test_control_center_under_bar_button_on_second_output(self):
        self.start()
        bar = self.bar()
        hub = self.hub()
        self.client()
        # Ovladaci centrum je v liste uplne vpravo, tady na druhem vystupu
        button = 2 * OUT_W - 18
        before = self.shot()
        mark, bmark = self.cc.mark(), bar.mark()
        clicked = time.monotonic()
        self.input(f"move {button} 16", "sleep 0.1", "click")
        _, m = bar.wait(r"^control-center (\d+) (\d+)", start=bmark)
        self.assertEqual(int(m.group(1)), OUT_W)
        center = OUT_W + int(m.group(2))
        placed = self.cc.wait("placed ", mark, timeout=SHOW_LIMIT)
        self.cc.wait("shown", mark, timeout=SHOW_LIMIT)
        shown = time.monotonic() - clicked
        print(f"\n  {self.compositor}: klik -> Ovladaci centrum {shown * 1000:.0f} ms, {placed}")
        words = placed.split()
        self.assertEqual(words[:3], ["placed", "anchor", str(OUT_W)])
        left = int(words[3])
        self.assertGreater(left, OUT_W)
        self.assertLessEqual(left, center)
        self.assertLess(shown, SHOW_LIMIT)
        # okno pod tlacitkem na druhem vystupu, pod vyhradnou zonou listy; prvni vystup na tom miste beze zmeny
        empty = pixel(before, left + 40, BAR + 40)
        self.assertTrue(self.wait_pixels(lambda image: pixel(image, left + 40, BAR + 40) != empty))
        image = self.shot()
        self.assertEqual(pixel(image, left - OUT_W + 40, BAR + 40), pixel(before, left - OUT_W + 40, BAR + 40))
        self.assertEqual(pixel(image, left + 40, BAR + 2), pixel(before, left + 40, BAR + 2))
        # Esc zavre
        mark = self.cc.mark()
        self.input("key Escape")
        self.cc.wait("hidden", mark)
        self.assertTrue(self.wait_pixels(lambda image: pixel(image, left + 40, BAR + 40) == empty))
        # znovu otevrit, dalsi klik na tlacitko zavre
        mark = self.cc.mark()
        self.input(f"move {button} 16", "sleep 0.1", "click")
        self.cc.wait("shown", mark, timeout=SHOW_LIMIT)
        mark = self.cc.mark()
        self.input(f"move {button} 16", "sleep 0.1", "click")
        self.cc.wait("hidden", mark)
        # klik mimo (do okna aplikace na prvnim vystupu) zavre
        mark = self.cc.mark()
        self.input(f"move {button} 16", "sleep 0.1", "click")
        self.cc.wait("shown", mark, timeout=SHOW_LIMIT)
        time.sleep(0.6)
        mark = self.cc.mark()
        self.input(self.inside, "click")
        self.cc.wait("hidden", mark)
        time.sleep(0.6)
        self.assertNotIn("shown", self.cc.lines()[mark:], "klik mimo okno znovu otevrel")
        self.assertIsNone(hub.poll())

    def test_signals_show_without_bar_and_calendar(self):
        self.start()
        hub = self.hub()
        self.client()
        self.background = pixel(self.shot(), OUT_W - 100, 60)
        # SIGUSR1 bez listy (zkratka): vystup vybere kompozitor, vpravo nahore
        mark = self.cc.mark()
        sent = time.monotonic()
        hub.send_signal(signal.SIGUSR1)
        self.assertEqual(self.cc.wait("placed ", mark, timeout=SHOW_LIMIT), "placed default right")
        self.cc.wait("shown", mark, timeout=SHOW_LIMIT)
        cc_ms = (time.monotonic() - sent) * 1000
        # klavesnici muze dostat az po chvili (popup.show: nejdriv on demand, pak na chvili exclusive)
        time.sleep(0.4)
        self.close_by_key(hub, signal.SIGUSR1, self.cc)
        # SIGUSR2: Kalendar stejne (hodiny vpravo)
        mark = self.cal.mark()
        sent = time.monotonic()
        hub.send_signal(signal.SIGUSR2)
        self.assertEqual(self.cal.wait("placed ", mark, timeout=SHOW_LIMIT), "placed default right")
        self.cal.wait("shown", mark, timeout=SHOW_LIMIT)
        cal_ms = (time.monotonic() - sent) * 1000
        print(f"\n  {self.compositor}: SIGUSR1 -> {cc_ms:.0f} ms, SIGUSR2 -> {cal_ms:.0f} ms")
        # vpravo nahore (bez listy primo pod hornim okrajem) na nekterem vystupu
        self.assertTrue(self.wait_pixels(lambda image: any(pixel(image, x, 60) != self.background
                                                           for x in (OUT_W - 100, 2 * OUT_W - 100))))
        time.sleep(0.4)
        self.close_by_key(hub, signal.SIGUSR2, self.cal)
        # prepinac luxos-calendar-toggle posle hubu SIGUSR2; klik mimo zavre i Kalendar
        mark = self.cal.mark()
        subprocess.run([str(self.bin / "luxos-calendar-toggle")], env=self.env, check=True, timeout=10)
        self.cal.wait("shown", mark, timeout=SHOW_LIMIT)
        time.sleep(0.6)
        mark = self.cal.mark()
        if self.compositor == "labwc":
            hub.send_signal(signal.SIGUSR2)
        else:
            self.input(self.inside, "click")
        self.cal.wait("hidden", mark)
        # hodiny uprostred listy: Kalendar na stredu
        (self.session / "config/luxos/appearance.conf").write_text("BAR_CLOCK=center\n")
        mark = self.cal.mark()
        hub.send_signal(signal.SIGUSR2)
        self.assertEqual(self.cal.wait("placed ", mark, timeout=SHOW_LIMIT), "placed default center")
        self.assertIsNone(hub.poll())
        self.assertNotIn("LSL callback error", (self.session / "hub.log").read_text())

    @unittest.skipUnless(shutil.which("dbus-daemon"), "chybi dbus-daemon")
    def test_brightness_through_logind(self):
        self.start()
        bus = self.session / "system_bus"
        p = subprocess.Popen(["dbus-daemon", "--session", f"--address=unix:path={bus}", "--nofork", "--nopidfile"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        for _ in range(100):
            if bus.exists():
                break
            time.sleep(0.05)
        fake = subprocess.Popen(["python3", "-I", "-c", FAKE_LOGIND, f"unix:path={bus}"], stdout=subprocess.PIPE,
                                env=dict(os.environ, PYTHONUNBUFFERED="1"))
        self.procs.append(fake)
        logind = Bar(fake)
        logind.wait(r"^ready$")
        hub = self.hub(DBUS_SYSTEM_BUS_ADDRESS=f"unix:path={bus}", LUXOS_CC_TEST_SLIDE="30",
                       LUXOS_CC_TEST_SLIDER="s_bright")
        mark = self.cc.mark()
        hub.send_signal(signal.SIGUSR1)
        self.cc.wait("shown", mark, timeout=SHOW_LIMIT)
        # posuvnik dojede na 30 %: posledni hodnota dorazi (nejvys jedna zmena na ceste), nejmene 10 %
        logind.wait(r"^set backlight intel_backlight 360$", timeout=5)
        calls = [line for line in logind.lines if line.startswith("set ")]
        self.assertTrue(all(int(c.split()[3]) >= 120 for c in calls), calls)
        self.assertLessEqual(len(calls), 30)
        self.assertEqual(calls[-1], "set backlight intel_backlight 360")
        self.assertNotIn("brightness:", (self.session / "hub.log").read_text())
        self.assertIsNone(hub.poll())


@unittest.skipUnless(HAVE_LUXWM, "chybi luxwm (packages/luxwm/tests/build-host.sh)")
class HubLuxwm(HubWayland, unittest.TestCase):
    compositor = "luxwm"


@unittest.skipUnless(HAVE_LABWC, "chybi labwc (scripts/wl-test/fetch-sysroot.sh)")
class HubLabwc(HubWayland, unittest.TestCase):
    compositor = "labwc"


if __name__ == "__main__":
    unittest.main()
